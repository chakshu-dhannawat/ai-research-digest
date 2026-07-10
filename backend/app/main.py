import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import get_pool, close_pool
from app.routers.api import router as api_router
from app.services.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scheduled_pipeline():
    logger.info("Cron triggered: running daily pipeline")
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT email, language FROM subscribers WHERE active = TRUE")
        groups: dict[str, list[str]] = {"en": [], "ja": []}
        for r in rows:
            lang = r["language"] if r["language"] in ("en", "ja") else "en"
            groups[lang].append(r["email"])
        if any(groups.values()):
            result = await run_pipeline(recipients_by_lang=groups, is_test=False)
        else:
            # Fall back to default recipients
            result = await run_pipeline()
        logger.info("Cron pipeline result: %s", result)
    except Exception as e:
        logger.exception("Cron pipeline failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    logger.info("DB pool ready")

    scheduler.add_job(
        scheduled_pipeline,
        CronTrigger(hour=settings.cron_hour, minute=settings.cron_minute, timezone="Asia/Tokyo"),
        id="daily_newsletter",
        replace_existing=True,
        # A busy event loop can delay the fire past APScheduler's 1s default grace,
        # which silently skips the whole day (as happened 2026-07-10). Allow a late
        # fire up to 1h and coalesce any pileup into a single run.
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Scheduler started: pipeline at %02d:%02d JST, delivery by 08:00 JST", settings.cron_hour, settings.cron_minute)

    yield

    scheduler.shutdown()
    await close_pool()
    logger.info("Shutdown complete")


app = FastAPI(title="AI Newsletter", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
