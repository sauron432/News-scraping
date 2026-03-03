import csv
import os
import sys
import time
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL      = "https://www.setopati.com"
OUTPUT_DIR    = "setopati_headlines"     
DELAY_SECONDS = 1.5
TIMEOUT       = 15
MAX_PAGES     = int(sys.argv[1]) if len(sys.argv) > 1 else 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ne,en;q=0.9",
    "Referer": "https://www.setopati.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    """Convert Nepali category name to a safe filename."""
    safe = "".join(
        c if (c.isalnum() or c in "-_ " or "\u0900" <= c <= "\u097F") else "_"
        for c in name
    )
    return safe.strip().replace(" ", "_") or "category"


def fetch_page(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except requests.RequestException as e:
        log.error(f"Failed to fetch {url}: {e}")
        return None


def build_page_url(base_url: str, page_num: int) -> str:
    """
    Setopati uses /page/N pagination (same pattern as onlinekhabar).
    Page 1 uses the base URL directly.
    """
    if page_num == 1:
        return base_url
    base = base_url.rstrip("/")
    return f"{base}/page/{page_num}"

def extract_headlines(soup: BeautifulSoup) -> list[dict]:
    """
    Extract headlines from a Setopati category page.

    Setopati renders full absolute URLs in href, e.g.:
      https://www.setopati.com/politics/383036
      https://www.setopati.com/kinmel/banking/382989
    The cleanest title source is the anchor's `title` attribute.
    Author and date appear as sibling text nodes just after the anchor.
    """
    import re
    # Match absolute article URLs: domain + 1-2 path segments + numeric ID
    article_pattern = re.compile(
        r"^https://www\.setopati\.com/[a-z\-]+(/[a-z\-]+)*/\d+$"
    )
    nepali_digits = re.compile(r"[०-९]")

    headlines = []
    seen_links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if not article_pattern.match(href):
            continue
        if href in seen_links:
            continue
        seen_links.add(href)

        # `title` attribute is the cleanest headline source on Setopati
        title = a.get("title", "").strip()
        if not title:
            title = " ".join(a.get_text(separator=" ", strip=True).split())
        if len(title) < 5:
            continue

        # Author and date sit just outside the anchor in the parent block
        parent = a.find_parent(["div", "article", "li"])
        date = ""
        author = ""
        if parent:
            texts = [t.strip() for t in parent.strings if t.strip() and t.strip() != title]
            for t in texts:
                if not author and not nepali_digits.search(t) and len(t) < 40:
                    author = t
                if not date and nepali_digits.search(t):
                    date = t

        headlines.append({
            "title":  title,
            "link":   href,
            "author": author,
            "date":   date,
        })

    return headlines

def get_categories() -> list[tuple[str, str]]:
    """
    Scrape category names and links dynamically
    from the main header navigation.
    """
    soup = fetch_page(BASE_URL)
    if not soup:
        log.error("Could not fetch homepage for categories.")
        return []

    categories = []
    seen_links = set()

    # Only match stable class
    nav_div = soup.find("div", class_="header-main")

    if not nav_div:
        log.error("Navigation div not found.")
        return []

    for a in nav_div.find_all("a", href=True):
        name = a.get_text(strip=True)
        href = a["href"].strip()

        if not name:
            continue

        if href.startswith("/"):
            href = BASE_URL + href

        # Skip homepage
        if href == BASE_URL:
            continue

        # Avoid article links (they contain numeric IDs)
        if href.rstrip("/").split("/")[-1].isdigit():
            continue

        if href in seen_links:
            continue

        seen_links.add(href)
        categories.append((name, href))

    log.info(f"Discovered {len(categories)} categories from header.")
    return categories

# ── Core ───────────────────────────────────────────────────────────────────────

def scrape_category(category_name: str, url: str) -> list[dict]:
    all_headlines = []

    for page_num in range(1, MAX_PAGES + 1):
        page_url = build_page_url(url, page_num)
        log.info(f"  Page {page_num}: {page_url}")

        soup = fetch_page(page_url)
        if not soup:
            break

        headlines = extract_headlines(soup)
        if not headlines:
            log.info(f"  No headlines on page {page_num} — stopping.")
            break

        for h in headlines:
            h["category"] = category_name

        all_headlines.extend(headlines)
        log.info(f"  → {len(headlines)} found (total: {len(all_headlines)})")

        time.sleep(DELAY_SECONDS)

    return all_headlines


    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, safe_filename(category_name) + ".csv")
    fieldnames = ["category", "title", "author", "date", "link"]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(headlines)

    return filepath


def save_combined_csv(all_data: dict[str, list[dict]]) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, "_all_categories.csv")
    fieldnames = ["category", "title", "author", "date", "link"]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for headlines in all_data.values():
            writer.writerows(headlines)

    return filepath


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    categories = get_categories()

    if not categories:
        log.error("No categories found. Exiting.")
        return

    log.info(f"Setopati scraper starting — {len(categories)} categories, {MAX_PAGES} page(s) each")
    log.info(f"Output folder: {OUTPUT_DIR}/\n")

    all_data: dict[str, list[dict]] = {}

    for category_name, url in categories:
        log.info(f"━━ {category_name} ━━")
        headlines = scrape_category(category_name, url)

        if headlines:
            all_data[category_name] = headlines
        else:
            log.warning(f"   ✗ Nothing scraped for '{category_name}'\n")

    if all_data:
        combined = save_combined_csv(all_data)
        total = sum(len(v) for v in all_data.values())
        log.info(f"✅ Done! {total} total headlines across {len(all_data)} categories.")
        log.info(f"   Combined CSV → {combined}")
    else:
        log.warning("No data was scraped.")
    
if __name__ == "__main__":
    main()