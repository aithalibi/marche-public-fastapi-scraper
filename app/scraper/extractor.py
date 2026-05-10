from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.sync_api import Locator, Page


DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
TIME_RE = re.compile(r"\b\d{2}:\d{2}\b")


def _clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    lines = [line.strip() for line in value.splitlines()]
    lines = [line for line in lines if line and line != ":"]
    return "\n".join(lines)


def _split_lines(value: str) -> list[str]:
    cleaned = _clean_text(value)
    return [line for line in cleaned.split("\n") if line]


def _extract_date(value: str) -> str | None:
    match = DATE_RE.search(value)
    return match.group(0) if match else None


def _extract_time(value: str) -> str | None:
    match = TIME_RE.search(value)
    return match.group(0) if match else None


def _parse_category_cell(value: str) -> dict[str, str]:
    lines = _split_lines(value)
    procedure = ""
    categorie = ""
    date_publication = ""

    for line in lines:
        if not procedure and not DATE_RE.search(line):
            procedure = line
            continue
        if not categorie and not DATE_RE.search(line):
            categorie = line
            continue
        if not date_publication:
            found_date = _extract_date(line)
            if found_date:
                date_publication = found_date

    return {
        "procedure": procedure,
        "categorie": categorie,
        "date_publication": date_publication,
    }


def _parse_reference_cell(value: str) -> dict[str, str]:
    lines = _split_lines(value)
    reference = lines[0] if lines else ""

    objet_parts: list[str] = []
    acheteur_parts: list[str] = []
    current: str | None = None

    for line in lines[1:]:
        lowered = line.lower()
        if lowered.startswith("objet"):
            current = "objet"
            objet_parts.append(line.split(":", 1)[1].strip() if ":" in line else line)
            continue
        if lowered.startswith("acheteur public"):
            current = "acheteur"
            acheteur_parts.append(line.split(":", 1)[1].strip() if ":" in line else line)
            continue
        if current == "objet":
            objet_parts.append(line)
            continue
        if current == "acheteur":
            acheteur_parts.append(line)

    return {
        "reference": reference,
        "intitule": " ".join(part for part in objet_parts if part).strip(),
        "acheteur": " ".join(part for part in acheteur_parts if part).strip(),
    }


def _parse_region_cell(value: str) -> str:
    lines = _split_lines(value)
    for line in reversed(lines):
        if line != "-":
            return line
    return ""


def _parse_deadline_cell(value: str) -> dict[str, str]:
    cleaned = _clean_text(value)
    date_limite = _extract_date(cleaned) or ""
    heure_limite = _extract_time(cleaned) or ""
    return {
        "date_limite": date_limite,
        "heure_limite": heure_limite,
    }


def _extract_detail_url(row: Locator) -> str:
    links = row.locator("a[href]")
    for i in range(links.count()):
        link = links.nth(i)
        href = (link.get_attribute("href") or "").strip()
        text = ""
        title = ""
        try:
            text = (link.inner_text() or "").strip().lower()
            title = (link.get_attribute("title") or "").strip().lower()
        except Exception:
            pass

        haystack = f"{href} {text} {title}".lower()
        if "entreprisedetailsconsultation" in haystack or "suiviconsultation" in haystack or "popupdetaillots" in haystack or "détail" in haystack or "detail" in haystack:
            return _normalize_detail_url(href)

    for i in range(links.count()):
        href = (links.nth(i).get_attribute("href") or "").strip()
        if href and not href.startswith("javascript:"):
            return _normalize_detail_url(href)

    return ""


def _normalize_detail_url(href: str) -> str:
    href = href.strip()
    javascript_url = re.search(r"popUp\('([^']+)'", href)
    if javascript_url:
        href = javascript_url.group(1)
    return urljoin("https://www.marchespublics.gov.ma/", href)


def _parse_raw_row(cells: list[str], detail_url: str) -> dict[str, str]:
    category_info = _parse_category_cell(cells[1] if len(cells) > 1 else "")
    reference_info = _parse_reference_cell(cells[2] if len(cells) > 2 else "")
    deadline_info = _parse_deadline_cell(cells[4] if len(cells) > 4 else "")

    return {
        "reference": reference_info["reference"],
        "intitule": reference_info["intitule"],
        "categorie": category_info["categorie"],
        "procedure": category_info["procedure"],
        "acheteur": reference_info["acheteur"],
        "region": _parse_region_cell(cells[3] if len(cells) > 3 else ""),
        "date_publication": category_info["date_publication"],
        "date_limite": deadline_info["date_limite"],
        "heure_limite": deadline_info["heure_limite"],
        "urlOfficielle": detail_url,
    }


def extract_table_rows(table: Locator) -> list[dict[str, str]]:
    rows = table.locator("tr")
    out: list[dict[str, str]] = []

    for i in range(rows.count()):
        row = rows.nth(i)
        cells = [_clean_text(c) for c in row.locator("td").all_inner_texts()]
        if not cells or not any(cells):
            continue
        parsed = _parse_raw_row(cells, _extract_detail_url(row))
        if parsed["reference"] or parsed["intitule"] or parsed["acheteur"]:
            out.append(parsed)

    return out


def find_result_table(page: Page) -> Locator | None:
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
