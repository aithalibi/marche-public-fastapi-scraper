from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.config import DEFAULT_MAX_PAGES, DEFAULT_TIMEOUT_MS


@dataclass
class ScrapeConfig:
    keyword: str | None
    date_debut: str | None
    date_fin: str | None
    region: str | None
    max_pages: int
    headless: bool
    timeout_ms: int


class ScrapeRequest(BaseModel):
    keyword: Optional[str] = Field(None, description="Keyword for reference/title/object.")
    date_debut: Optional[str] = Field(None, description="Start date (DD/MM/YYYY).")
    date_fin: Optional[str] = Field(None, description="End date (DD/MM/YYYY).")
    region: Optional[str] = Field(None, description="Region name or code to filter results.")
    max_pages: int = Field(DEFAULT_MAX_PAGES, ge=1, description="Maximum number of result pages to scrape.")
    headless: bool = Field(True, description="Run browser in headless mode.")
    timeout_ms: int = Field(DEFAULT_TIMEOUT_MS, ge=10_000, description="Playwright timeout in milliseconds.")


class SearchInfo(BaseModel):
    keyword: Optional[str]
    date_debut: Optional[str]
    date_fin: Optional[str]
    region: Optional[str]
    scraped_at: str


class ScrapeResponse(BaseModel):
    search: SearchInfo
    total_rows: int
    rows: list[dict[str, str]]
