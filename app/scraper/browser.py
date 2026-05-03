from __future__ import annotations

import re
import unicodedata

from playwright.sync_api import Locator, Page

from app.config import URL


def _first_visible(page: Page, selectors: list[str]) -> Locator | None:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.upper().replace("-", " ").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _click_if_present(locator: Locator) -> bool:
    try:
        if locator.count() > 0:
            locator.first.click()
            return True
    except Exception:
        return False
    return False


def _ensure_checkbox_visible(checkbox: Locator) -> None:
    checkbox.evaluate(
        """
        el => {
          let node = el;
          while (node) {
            if (node.style && node.style.display === 'none') {
              node.style.display = 'block';
            }
            node = node.parentElement;
          }
          const list = el.closest('ul');
          if (list && list.style) {
            list.style.display = 'block';
          }
        }
        """
    )


def _mark_checkbox(checkbox: Locator) -> None:
    _ensure_checkbox_visible(checkbox)
    checkbox.evaluate(
        """
        el => {
          el.checked = true;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.dispatchEvent(new Event('click', { bubbles: true }));
        }
        """
    )


def fill_date_if_any(page: Page, date_debut: str | None, date_fin: str | None) -> None:
    if date_debut:
        debut_selectors = [
            "input[name*='dateMiseEnLigneCalculeStart']",
            "input[id*='dateMiseEnLigneCalculeStart']",
            "input[name*='dateMiseEnLigneStart']",
            "input[id*='dateMiseEnLigneStart']",
            "input[name*='dateDebut']",
            "input[id*='dateDebut']",
            "input[name*='date_debut']",
            "input[id*='date_debut']",
            "input[name*='DateDebut']",
        ]
        field = _first_visible(page, debut_selectors)
        if field:
            field.fill(date_debut)
        else:
            print("[WARN] No date_debut input detected; skipping.")

    if date_fin:
        fin_selectors = [
            "input[name*='dateMiseEnLigneCalculeEnd']",
            "input[id*='dateMiseEnLigneCalculeEnd']",
            "input[name*='dateMiseEnLigneEnd']",
            "input[id*='dateMiseEnLigneEnd']",
            "input[name*='dateFin']",
            "input[id*='dateFin']",
            "input[name*='date_fin']",
            "input[id*='date_fin']",
            "input[name*='DateFin']",
        ]
        field = _first_visible(page, fin_selectors)
        if field:
            field.fill(date_fin)
        else:
            print("[WARN] No date_fin input detected; skipping.")


def _select_region_via_popup(page: Page, region: str) -> bool:
    details_link = page.locator("#ctl0_CONTENU_PAGE_AdvancedSearch_linkLieuExe1")
    if details_link.count() == 0:
        return False

    with page.expect_popup() as popup_info:
        details_link.first.click()

    popup = popup_info.value
    popup.wait_for_load_state("domcontentloaded")
    popup.wait_for_load_state("networkidle")

    region_value = _normalize(region)

    # The popup exposes province/city selection under the province radio mode.
    province_radio = popup.locator("#ctl0_CONTENU_PAGE_repeaterGeoN0_ctl0_selectiongeoN0Select")
    if province_radio.count() > 0:
        province_radio.first.check(force=True)

    # Match an exact province/city checkbox first, e.g. "MARRAKECH", "RABAT".
    province_checkbox = None
    province_checkboxes = popup.locator("input.check[title]")
    for i in range(province_checkboxes.count()):
        candidate = province_checkboxes.nth(i)
        try:
            title = candidate.get_attribute("title") or ""
            if _normalize(title) == region_value and title.strip().upper() != "TOUS":
                province_checkbox = candidate
                break
        except Exception:
            continue

    if province_checkbox is not None:
        _mark_checkbox(province_checkbox)
        validate = popup.locator("#ctl0_CONTENU_PAGE_validateButton")
        if validate.count() > 0:
            validate.first.click()
            page.wait_for_timeout(1000)
            return True

    # Fallback: match a region panel like "Casablanca-Settat" or "Marrakech-Safi"
    toggles = popup.locator("div.title-toggle")
    for i in range(toggles.count()):
        toggle = toggles.nth(i)
        try:
            toggle_text = toggle.inner_text().strip()
        except Exception:
            continue

        if _normalize(toggle_text) != region_value:
            continue

        toggle.click()
        panel_id = toggle.evaluate("el => el.getAttribute('onclick') || ''")
        match = re.search(r"'([^']+)'", panel_id)
        if not match:
            break

        panel = popup.locator(f"#{match.group(1)}")
        panel.evaluate("el => { if (el.style) el.style.display = 'block'; }")
        _mark_checkbox(panel.locator("input.check[title='Tous']").first)
        validate = popup.locator("#ctl0_CONTENU_PAGE_validateButton")
        if validate.count() > 0:
            validate.first.click()
            page.wait_for_timeout(1000)
            return True

    if not popup.is_closed():
        _click_if_present(popup.locator("input[value='Annuler']"))
    return False


def fill_region_if_any(page: Page, region: str | None) -> None:
    if not region:
        return

    region_selectors = [
        "select[name*='region']",
        "select[id*='region']",
        "select[name*='Region']",
        "select[id*='Region']",
    ]
    for sel in region_selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible():
                loc.select_option(label=region)
                return
        except Exception:
            try:
                loc.select_option(value=region)
                return
            except Exception:
                continue

    if _select_region_via_popup(page, region):
        return

    print("[WARN] No region select input detected; skipping.")


def fill_keyword_if_any(page: Page, keyword: str | None) -> None:
    if not keyword:
        return

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


def click_search(page: Page) -> None:
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

    form = page.locator("form").first
    if form.count() > 0:
        form.locator("input[type='submit'], button[type='submit']").first.click()
        return

    raise RuntimeError("Could not find a search/submit control on the page.")


def go_next_page(page: Page) -> bool:
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
