from __future__ import annotations

import asyncio
import sys
import time

from playwright.sync_api import TimeoutError, sync_playwright

from app.config import URL
from app.models import ScrapeConfig
from app.scraper.browser import click_search, fill_date_if_any, fill_keyword_if_any, fill_region_if_any, go_next_page
from app.scraper.extractor import extract_table_rows, find_result_table


def run_scrape(config: ScrapeConfig) -> list[dict[str, str]]:
    if sys.platform == "win32":
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    all_rows: list[dict[str, str]] = []
    seen_rows: set[tuple[tuple[str, str], ...]] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless)
        context = browser.new_context(
            locale="fr-FR",
            timezone_id="Africa/Casablanca",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(config.timeout_ms)

        print("[INFO] Opening page...")
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        fill_keyword_if_any(page, config.keyword)
        fill_date_if_any(page, config.date_debut, config.date_fin)
        fill_region_if_any(page, config.region)
        click_search(page)

        try:
            page.wait_for_load_state("networkidle")
        except TimeoutError:
            pass

        page_index = 1
        while page_index <= config.max_pages:
            print(f"[INFO] Extracting page {page_index}...")
            table = find_result_table(page)
            if not table:
                print("[WARN] No result table found.")
                break

            page_rows = extract_table_rows(table)
            if not page_rows:
                print("[INFO] No data rows found on this page.")
                break

            added = 0
            for row in page_rows:
                key = tuple(sorted((k, v) for k, v in row.items()))
                if key in seen_rows:
                    continue
                seen_rows.add(key)
                all_rows.append(row)
                added += 1
            print(f"[INFO] Added {added} new rows (total={len(all_rows)}).")

            if page_index >= config.max_pages:
                break

            if not go_next_page(page):
                print("[INFO] No next page link found. Stopping.")
                break

            page_index += 1
            time.sleep(1.0)
            try:
                page.wait_for_load_state("networkidle")
            except TimeoutError:
                pass

        browser.close()

    return all_rows
