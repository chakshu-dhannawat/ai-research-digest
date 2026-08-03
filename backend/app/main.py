import logging
import traceback
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import get_pool, close_pool
from app.routers.api import router as api_router
from app.services.email_sender import send_alert_email
from app.services.pipeline import run_pipeline
from app.utils import JST

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _today_jst() -> date:
    return datetime.now(JST).date()


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

        if result.get("status") != "sent":
            error = result.get("error") or "unknown"
            logger.error("Daily pipeline did not send a newsletter: %s", result)
            send_alert_email(
                subject=f"[AI Newsletter] No newsletter sent — {_today_jst().isoformat()}",
                body_text=(
                    f"The daily newsletter did not send on {_today_jst().isoformat()}.\n\n"
                    f"Pipeline result: {result}\n\n"
                    f"Main error: {error}\n\n"
                    f"The error above was recorded by the pipeline (likely an SMTP failure, "
                    f"LLM failure, or empty digest). Check the full backend logs for context."
                ),
            )
    except Exception as e:
        logger.exception("Cron pipeline failed: %s", e)
        send_alert_email(
            subject=f"[AI Newsletter] Pipeline crashed — {_today_jst().isoformat()}",
            body_text=(
                f"The daily newsletter pipeline crashed on {_today_jst().isoformat()}.\n\n"
                f"Main error: {e}\n\n"
                f"Traceback:\n{traceback.format_exc()}"
            ),
        )


async def _check_newsletter_sent_today() -> bool:
    """Return True if a non-test newsletter already exists for the current JST day."""
    pool = await get_pool()
    today_jst = datetime.combine(_today_jst(), datetime.min.time(), tzinfo=JST)
    start_utc = (today_jst - timedelta(hours=9)).replace(tzinfo=None)
    end_utc = (today_jst + timedelta(hours=15)).replace(tzinfo=None)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM newsletters "
            "WHERE is_test = FALSE AND sent_at >= $1 AND sent_at < $2",
            start_utc,
            end_utc,
        )
    return bool(row and row["cnt"] > 0)


async def _last_pipeline_run_summary() -> str:
    """Fetch the most recent non-test pipeline run so alerts contain the real error."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, started_at, status, error_message "
            "FROM pipeline_runs WHERE is_test = FALSE "
            "ORDER BY id DESC LIMIT 1"
        )
    if not row:
        return "No pipeline_runs record found at all."
    lines = [
        f"Last pipeline run:",
        f"  id:     {row['id']}",
        f"  start:  {row['started_at']}",
        f"  status: {row['status']}",
    ]
    if row["error_message"]:
        lines.append(f"  error:  {row['error_message']}")
    return "\n".join(lines)


async def daily_send_sentinel():
    """Runs after the delivery window; warns the developer if nothing went out."""
    try:
        if await _check_newsletter_sent_today():
            logger.info("Send sentinel ok: a newsletter was sent today")
            return
        logger.error("Send sentinel alert: no newsletter record for today")
        run_summary = await _last_pipeline_run_summary()
        send_alert_email(
            subject=f"[AI Newsletter] No newsletter record for {_today_jst().isoformat()}",
            body_text=(
                f"No daily newsletter was recorded as sent for {_today_jst().isoformat()}.\n\n"
                f"{run_summary}\n\n"
                "The scheduler may have failed to start, the pipeline may have crashed, or "
                "the container may have been restarted after the scheduled window.\n\n"
                f"Please check the backend logs for container ai-newsletter-backend-1."
            ),
        )
    except Exception as e:
        logger.exception("Send sentinel check failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    logger.info("DB pool ready")

    scheduler.add_job(
        scheduled_pipeline,
        CronTrigger(
            hour=settings.cron_hour,
            minute=settings.cron_minute,
            day_of_week="mon-fri",
            timezone="Asia/Tokyo",
        ),
        id="daily_newsletter",
        replace_existing=True,
        # A busy event loop can delay the fire past APScheduler's 1s default grace,
        # which silently skips the whole day (as happened 2026-07-10). Allow a late
        # fire up to 1h and coalesce any pileup into a single run.
        misfire_grace_time=3600,
        coalesce=True,
    )
    # Safety net: if the scheduled job did not run or did not succeed for any reason,
    # alert the developer shortly after the expected delivery time. Runs on weekdays only.
    scheduler.add_job(
        daily_send_sentinel,
        CronTrigger(hour=8, minute=10, day_of_week="mon-fri", timezone="Asia/Tokyo"),
        id="daily_send_sentinel",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: pipeline at %02d:%02d JST on weekdays, delivery by 08:00 JST",
        settings.cron_hour, settings.cron_minute,
    )

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
