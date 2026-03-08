"""
Scraper for election.ekantipur.com
Scrapes two sections:
  1. Party-wise Results     → div.party-stat-inside-wrap
  2. Proportional Results   → #partyContainer_2082

Install dependencies:
    pip install requests beautifulsoup4 selenium
    ChromeDriver: https://chromedriver.chromium.org/
"""

import json
import sys
import time

from bs4 import BeautifulSoup

URL = "https://election.ekantipur.com/?lng=eng"


# ── Selenium (primary method since page is JS-rendered) ───────────────────────

def get_soup() -> BeautifulSoup | None:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("[selenium] Not installed. Run: pip install selenium")
        return None

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--log-level=3")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Edge(options=options)
    try:
        driver.get(URL)

        print("[selenium] Waiting for party-wise section ...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "party-stat-inside-wrap"))
        )

        print("[selenium] Waiting for proportional section ...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "partyContainer_2082"))
        )
        time.sleep(2)

        return BeautifulSoup(driver.page_source, "html.parser")

    except Exception as e:
        print(f"[selenium] Error: {e}")
        return None
    finally:
        driver.quit()


# ── requests fallback ─────────────────────────────────────────────────────────

def get_soup_requests() -> BeautifulSoup | None:
    try:
        import requests
    except ImportError:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    print("[requests] Fetching page ...")
    try:
        resp = requests.get(URL, headers=headers, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[requests] Failed: {e}")
        return None


# ── Section 1: Party-wise Results ─────────────────────────────────────────────

def scrape_party_wise(soup: BeautifulSoup) -> list[dict]:
    container = soup.find("div", class_="party-stat-inside-wrap")
    if not container:
        print("[party-wise] Container not found.")
        return []

    results = []
    first_cols = container.find_all(
        lambda tag: tag.name and tag.get("class") and
        any("first-col" in c for c in tag["class"])
    )

    for fc in first_cols:
        party_name = fc.get_text(strip=True)
        if not party_name or party_name.lower() == "party":
            continue

        row_el = fc.parent
        second_cols = row_el.find_all(
            lambda tag: tag.name and tag.get("class") and
            any("second-col" in c for c in tag["class"])
        )

        win  = second_cols[0].get_text(strip=True) if len(second_cols) > 0 else "N/A"
        lead = second_cols[1].get_text(strip=True) if len(second_cols) > 1 else "N/A"

        results.append({"Party": party_name, "Win": win, "Lead": lead})

    print(f"[party-wise] Found {len(results)} parties.")
    return results


# ── Section 2: Proportional Results ──────────────────────────────────────────

def scrape_proportional(soup: BeautifulSoup) -> list[dict]:
    container = soup.find(id="partyContainer_2082")
    if not container:
        print("[proportional] Container not found.")
        return []

    results = []
    cards = container.find_all("div", class_=lambda c: c and "col-xl-3" in c)

    for card in cards:
        texts = [t.strip() for t in card.get_text(separator="\n").split("\n") if t.strip()]
        if len(texts) < 2:
            continue

        votes      = texts[-1]
        party_name = " ".join(texts[:-1])

        if not any(ch.isdigit() for ch in votes):
            continue

        results.append({"Party": party_name, "Votes": votes})

    print(f"[proportional] Found {len(results)} parties.")
    return results


# ── Display ───────────────────────────────────────────────────────────────────

def print_party_wise(results: list[dict]):
    if not results:
        return

    # Dynamically size the party column to the longest name
    col_w = max(len(r["Party"]) for r in results) + 2

    total_w = col_w + 12  # 6 for Win + 6 for Lead
    divider = "─" * total_w

    print()
    print("┌" + divider + "┐")
    print("│" + " PARTY-WISE RESULTS".center(total_w) + "│")
    print("├" + divider + "┤")
    print(f"│  {'Party':<{col_w - 2}}  {'Win':>4}  {'Lead':>4}  │")
    print("├" + divider + "┤")
    for row in results:
        print(f"│  {row['Party']:<{col_w - 2}}  {row['Win']:>4}  {row['Lead']:>4}  │")
    print("├" + divider + "┤")
    print(f"│  Total: {len(results)} parties{' ' * (total_w - len(str(len(results))) - 10)}│")
    print("└" + divider + "┘")


def print_proportional(results: list[dict]):
    if not results:
        return

    col_w   = max(len(r["Party"]) for r in results) + 2
    vote_w  = max(len(r["Votes"]) for r in results) + 2
    total_w = col_w + vote_w + 2

    divider = "─" * total_w

    print()
    print("┌" + divider + "┐")
    print("│" + " PROPORTIONAL RESULTS 2082".center(total_w) + "│")
    print("├" + divider + "┤")
    print(f"│  {'Party':<{col_w - 2}}  {'Votes':>{vote_w - 2}}  │")
    print("├" + divider + "┤")
    for row in results:
        print(f"│  {row['Party']:<{col_w - 2}}  {row['Votes']:>{vote_w - 2}}  │")
    print("├" + divider + "┤")
    print(f"│  Total: {len(results)} parties{' ' * (total_w - len(str(len(results))) - 10)}│")
    print("└" + divider + "┘")


# ── Save ──────────────────────────────────────────────────────────────────────

def save_json(party_wise: list[dict], proportional: list[dict]):
    data = {
        "party_wise_results":   party_wise,
        "proportional_results": proportional,
    }
    path = "election_results.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[✓] All results saved to '{path}'")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    soup = get_soup_requests() or get_soup()

    if not soup:
        print("\n[✗] Could not load the page.")
        sys.exit(1)

    party_wise   = scrape_party_wise(soup)
    proportional = scrape_proportional(soup)

    if not party_wise and not proportional:
        print("\n[✗] Could not extract any results.")
        sys.exit(1)

    print_party_wise(party_wise)
    print_proportional(proportional)
    save_json(party_wise, proportional)


if __name__ == "__main__":
    main()