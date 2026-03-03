import csv
import os
import sys
import time
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL      = "https://ekantipur.com/"
OUTPUT_DIR    = "kantipur_headlines"          # folder where per-category CSVs are saved
DELAY_SECONDS = 1.5                  # polite delay between requests
TIMEOUT       = 15                   # request timeout in seconds
MAX_PAGES     = 3                    # how many pages to scrape per category (pagination)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ne,en;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_full_url(link: str) -> str | None:
    """Resolve relative or absolute links. Skip invalid ones like '#' or '/'."""
    link = link.strip()
    if not link or link in ("#", "/"):
        return None
    if link.startswith("http"):
        return link
    return BASE_URL + link


def safe_filename(name: str) -> str:
    """Convert a category name (possibly Nepali) to a safe filename."""
    # Keep alphanumeric, Devanagari unicode range, hyphens, underscores
    safe = "".join(c if (c.isalnum() or c in "-_ " or "\u0900" <= c <= "\u097F") else "_" for c in name)
    return safe.strip().replace(" ", "_") or "category"


def fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        response.encoding = "utf-8"
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        log.error(f"Failed to fetch {url}: {e}")
        return None

def get_ekantipur_categories() -> list[tuple[str, str]]:
    """
    Scrape categories from ekantipur.com bottom navigation section
    (the list of categories like राजनीति, अर्थ / वाणिज्य, etc.)
    Ignore links to factchecker.ekantipur.com or other subdomains.
    """
    soup = fetch_page(BASE_URL)
    if not soup:
        log.error("Failed to fetch Ekantipur homepage.")
        return []

    categories = []
    seen = set()

    # The categories appear grouped in the bottom nav / footer
    # Look for anchors in that section
    # Many sites have a 'bottom-nav-wrap' class
    nav_section = soup.find("div", class_="bottom-nav-wrap")
    if not nav_section:
        log.error("Bottom navigation section not found in Ekantipur homepage.")
        return []

    for a in nav_section.find_all("a", href=True):
        name = a.get_text(strip=True)
        href = a["href"].strip()

        # Skip empty text or factchecker subdomain
        if not name:
            continue
        if "factchecker.ekantipur.com" in href:
            continue

        # Normalize relative links
        if href.startswith("/"):
            href = BASE_URL + href

        # Skip duplicates and homepage
        if href in seen or href == BASE_URL:
            continue

        seen.add(href)
        categories.append((name, href))

    log.info(f"Found {len(categories)} Ekantipur categories.")
    return categories

def extract_headlines(soup: BeautifulSoup) -> list[dict]:
    """
    Parse headlines from an OnlineKhabar category page.
    Returns a list of dicts with keys: title, link, published_date, category_tag.

    OnlineKhabar uses article cards with class patterns like:
      - ok-news-post  (main listing cards)
      - ok18-single-post
    """
    headlines = []

    # Strategy 1: article cards (most category listing pages)
    cards = soup.select("div.ok-news-post, div.ok18-single-post, div.ok-news-posts-row article")

    for card in cards:
        # Title & link — usually inside an <a> wrapping an <h2> or <h3>
        anchor = card.select_one("h2 a, h3 a, h4 a, .ok-news-post__title a")
        if not anchor:
            anchor = card.select_one("a[href]")

        if not anchor:
            continue

        title = anchor.get_text(strip=True)
        link  = anchor.get("href", "")
        if link and not link.startswith("http"):
            link = BASE_URL + link

        # Date — look for time tag or a date span
        date_tag = card.select_one("time, span.ok-news-post__date, span.date, .ok18-single-post__date")
        date = date_tag.get_text(strip=True) if date_tag else ""

        # Sub-category tag if present
        tag_el = card.select_one("span.ok-news-post__cat, a.category, .tag")
        tag = tag_el.get_text(strip=True) if tag_el else ""

        if title:
            headlines.append({
                "title":          title,
                "link":           link,
                "published_date": date,
                "category_tag":   tag,
            })

    # Strategy 2: fallback — grab all <h2>/<h3> anchors on the page
    if not headlines:
        log.warning("Primary selectors found nothing — using fallback heading extraction.")
        for tag in soup.select("h2 a[href], h3 a[href]"):
            title = tag.get_text(strip=True)
            link  = tag.get("href", "")
            if link and not link.startswith("http"):
                link = BASE_URL + link
            if title and link:
                headlines.append({
                    "title":          title,
                    "link":           link,
                    "published_date": "",
                    "category_tag":   "",
                })

    return headlines


def build_page_url(base_url: str, page_num: int) -> str:
    """
    Build a paginated URL for OnlineKhabar.
    Page 1 uses the base URL as-is; subsequent pages use the /page/N suffix.
    """
    if page_num == 1:
        return base_url
    base = base_url.split("?")[0].rstrip("/")
    return f"{base}/page/{page_num}"


# ── Core scraping logic ────────────────────────────────────────────────────────

def scrape_category(category_name: str, url: str) -> list[dict]:
    """Scrape all headlines from a category across multiple pages."""
    all_headlines = []

    for page_num in range(1, MAX_PAGES + 1):
        page_url = build_page_url(url, page_num)
        log.info(f"  Scraping page {page_num}: {page_url}")

        soup = fetch_page(page_url)
        if not soup:
            break

        headlines = extract_headlines(soup)
        if not headlines:
            log.info(f"  No headlines found on page {page_num} — stopping pagination.")
            break

        # Tag each headline with the category name
        for h in headlines:
            h["category"] = category_name

        all_headlines.extend(headlines)
        log.info(f"  → {len(headlines)} headlines found (total so far: {len(all_headlines)})")

        time.sleep(DELAY_SECONDS)

    return all_headlines


def save_combined_csv(all_data: dict[str, list[dict]], output_dir: str) -> str:
    """Optionally save all categories into a single combined CSV."""
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, "_all_categories.csv")
    fieldnames = ["category", "title", "published_date", "category_tag", "link"]

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for headlines in all_data.values():
            writer.writerows(headlines)

    return filename


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("Loading categories\n")

    categories = get_ekantipur_categories()

    if not categories:
        log.error("No categories found. Exiting.")
        return

    log.info(f"Found {len(categories)} categories to scrape.\n")

    all_data: dict[str, list[dict]] = {}

    for category_name, url in categories:
        log.info(f"━━ Category: {category_name} ━━")
        log.info(f"   URL: {url}")

        headlines = scrape_category(category_name, url)

        if headlines:
            log.info(f"   ✓ Scraped {len(headlines)} headlines\n")
            all_data[category_name] = headlines
        else:
            log.warning(f"   ✗ No headlines scraped for '{category_name}'\n")

    if all_data:
        combined = save_combined_csv(all_data, OUTPUT_DIR)
        total = sum(len(v) for v in all_data.values())
        log.info(f"Combined CSV saved → {combined}")
        log.info(f"Done! {total} total headlines.")
    else:
        log.warning("No data was scraped.")

if __name__ == "__main__":
    main()