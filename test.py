from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Locator, Page, TimeoutError, sync_playwright

URL = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&searchAnnCons"


@dataclass
class ScrapeConfig:
    keyword: str | None
    max_pages: int
    output_csv: Path
    headless: bool
    timeout_ms: int


def _first_visible(page: Page, selectors: list[str]) -> Locator | None:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _fill_keyword_if_any(page: Page, keyword: str | None) -> None:
    if not keyword:
        return

    # Try likely fields used for "référence / intitulé / objet".
    candidate_selectors = [
        "input[name*='mot']",
        "input[name*='Mot']",
        "input[id*='mot']",
        "input[id*='Mot']",
        "input[name*='keyword']",
        "input[id*='keyword']",
        "input[type='text']",
    ]
    field = _first_visible(page, candidate_selectors)
    if field:
        field.fill(keyword)
        return

    print("[WARN] No keyword input detected; continuing with current form criteria.")


def _click_search(page: Page) -> None:
    # Prefer semantic text-based locators, then fall back.
    buttons = [
        page.get_by_role("button", name="Lancer la recherche"),
        page.get_by_role("link", name="Lancer la recherche"),
        page.locator("input[type='submit'][value*='Lancer']"),
        page.locator("button:has-text('Lancer la recherche')"),
    ]

    for b in buttons:
        try:
            if b.count() > 0:
                b.first.click()
                return
        except Exception:
            continue

    # Last resort: submit first visible form.
    form = page.locator("form").first
    if form.count() > 0:
        form.locator("input[type='submit'], button[type='submit']").first.click()
        return

    raise RuntimeError("Could not find a search/submit control on the page.")


def _extract_table_rows(table: Locator) -> list[dict[str, str]]:
    headers = [h.strip() for h in table.locator("tr th").all_inner_texts() if h.strip()]
    rows = table.locator("tr")
    out: list[dict[str, str]] = []

    for i in range(rows.count()):
        row = rows.nth(i)
        cells = [c.strip() for c in row.locator("td").all_inner_texts()]
        if not cells:
            continue
        if not any(cells):
            continue
        if headers and len(headers) >= len(cells):
            out.append({headers[j]: cells[j] for j in range(len(cells))})
        else:
            out.append({f"col_{j + 1}": v for j, v in enumerate(cells)})

    return out


def _find_result_table(page: Page) -> Locator | None:
    tables = page.locator("table")
    best_table: Locator | None = None
    best_score = -1

    for i in range(tables.count()):
        t = tables.nth(i)
        tr_count = t.locator("tr").count()
        td_count = t.locator("td").count()
        if tr_count < 2 or td_count < 4:
            continue

        text = (t.inner_text() or "").strip()
        if not text:
            continue

        score = td_count
        lowered = text.lower()
        if "procédure" in lowered or "référence" in lowered or "objet" in lowered:
            score += 500

        if score > best_score:
            best_score = score
            best_table = t

    return best_table


def _go_next_page(page: Page) -> bool:
    candidates = [
        page.get_by_role("link", name="Suivant"),
        page.get_by_role("link", name=">"),
        page.locator("a:has-text('Suivant')"),
        page.locator("a[title*='Suivant']"),
    ]
    for nxt in candidates:
        try:
            if nxt.count() > 0 and nxt.first.is_visible():
                nxt.first.click()
                return True
        except Exception:
            continue
    return False


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def scrape(config: ScrapeConfig) -> list[dict[str, str]]:
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

        _fill_keyword_if_any(page, config.keyword)
        _click_search(page)

        try:
            page.wait_for_load_state("networkidle")
        except TimeoutError:
            pass

        page_index = 1
        while page_index <= config.max_pages:
            print(f"[INFO] Extracting page {page_index}...")
            table = _find_result_table(page)
            if not table:
                print("[WARN] No result table found.")
                break

            page_rows = _extract_table_rows(table)
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

            if not _go_next_page(page):
                print("[INFO] No next page link found. Stopping.")
                break

            page_index += 1
            time.sleep(1.0)
            try:
                page.wait_for_load_state("networkidle")
            except TimeoutError:
                pass

        browser.close()

    _write_csv(config.output_csv, all_rows)
    return all_rows


def _ask_int(prompt: str, default: int, minimum: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and int(raw) >= minimum:
            return int(raw)
        print(f"[WARN] Enter a number >= {minimum}.")


def _ask_bool(prompt: str, default: bool) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} ({default_text}): ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("[WARN] Enter y or n.")


def _prompt_config(default_max_pages: int, default_output: str, default_timeout_ms: int) -> ScrapeConfig:
    print("[INPUT] Enter search options (press Enter to keep default values).")
    keyword_raw = input("Keyword (reference/title/object), optional: ").strip()
    max_pages = _ask_int("Max pages to scrape", default_max_pages, 1)
    output_raw = input(f"Output CSV path [{default_output}]: ").strip() or default_output
    headed = _ask_bool("Show browser window", False)
    timeout_ms = _ask_int("Timeout in milliseconds", default_timeout_ms, 10000)

    return ScrapeConfig(
        keyword=keyword_raw or None,
        max_pages=max_pages,
        output_csv=Path(output_raw).expanduser().resolve(),
        headless=not headed,
        timeout_ms=timeout_ms,
    )


def parse_args() -> ScrapeConfig:
    parser = argparse.ArgumentParser(description="Scrape marchespublics advanced search results.")
    parser.add_argument("--keyword", type=str, default=None, help="Keyword for reference/title/object.")
    parser.add_argument("--max-pages", type=int, default=3, help="Maximum pages to scrape.")
    parser.add_argument("--output", type=str, default="marchespublics_results.csv", help="Output CSV path.")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode.")
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Playwright timeout in milliseconds.")
    parser.add_argument("--interactive", action="store_true", help="Prompt for inputs in terminal.")
    args = parser.parse_args()

    if args.interactive or len(sys.argv) == 1:
        return _prompt_config(
            default_max_pages=max(1, args.max_pages),
            default_output=args.output,
            default_timeout_ms=max(10000, args.timeout_ms),
        )

    return ScrapeConfig(
        keyword=args.keyword,
        max_pages=max(1, args.max_pages),
        output_csv=Path(args.output).resolve(),
        headless=not args.headed,
        timeout_ms=max(10000, args.timeout_ms),
    )


if __name__ == "__main__":
    cfg = parse_args()
    data = scrape(cfg)
    print(f"[DONE] Extracted {len(data)} rows -> {cfg.output_csv}")