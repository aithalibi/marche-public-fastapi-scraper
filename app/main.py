import asyncio
import sys

from fastapi import FastAPI

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.routes.scrape import router

app = FastAPI(
    title="Marchés Publics Scraper",
    description="Scrape marchespublics.gov.ma advanced search results.",
    version="1.0.0",
)

app.include_router(router)
