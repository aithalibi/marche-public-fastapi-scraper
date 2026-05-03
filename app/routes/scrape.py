from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models import ScrapeConfig, ScrapeRequest, ScrapeResponse, SearchInfo
from app.scraper.runner import run_scrape

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/scrape", response_model=ScrapeResponse, summary="Run a scrape and return results as JSON")
def scrape(request: ScrapeRequest) -> ScrapeResponse:
    """
    Trigger a scrape of marchespublics.gov.ma and return the extracted rows as JSON.

    Expect the call to take several seconds per page.
    """
    config = ScrapeConfig(
        keyword=request.keyword,
        date_debut=request.date_debut,
        date_fin=request.date_fin,
        region=request.region,
        max_pages=request.max_pages,
        headless=request.headless,
        timeout_ms=request.timeout_ms,
    )

    try:
        rows = run_scrape(config)
    except Exception as exc:
        logger.exception("Scrape failed for keyword=%r region=%r date_debut=%r date_fin=%r", request.keyword, request.region, request.date_debut, request.date_fin)
        raise HTTPException(status_code=500, detail=traceback.format_exc()) from exc

    return ScrapeResponse(
        search=SearchInfo(
            keyword=request.keyword,
            date_debut=request.date_debut,
            date_fin=request.date_fin,
            region=request.region,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        ),
        total_rows=len(rows),
        rows=rows,
    )


@router.post("/scrape/csv", summary="Run a scrape and download results as a CSV file")
def scrape_csv(request: ScrapeRequest) -> StreamingResponse:
    """
    Same as /scrape but streams the result back as a downloadable CSV file.
    """
    config = ScrapeConfig(
        keyword=request.keyword,
        date_debut=request.date_debut,
        date_fin=request.date_fin,
        region=request.region,
        max_pages=request.max_pages,
        headless=request.headless,
        timeout_ms=request.timeout_ms,
    )

    try:
        rows = run_scrape(config)
    except Exception as exc:
        logger.exception("CSV scrape failed for keyword=%r region=%r date_debut=%r date_fin=%r", request.keyword, request.region, request.date_debut, request.date_fin)
        raise HTTPException(status_code=500, detail=traceback.format_exc()) from exc

    if not rows:
        return StreamingResponse(iter([""]), media_type="text/csv")

    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                keys.append(k)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys)
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)

    filename = f"marchespublics_{request.keyword or 'all'}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/health", summary="Health check")
async def health() -> dict[str, str]:
    return {"status": "ok"}
