import asyncio
import logging
from datetime import date

from fastapi import APIRouter, HTTPException

from app.database import get_pool
from app.models.schemas import (
    FetchedItemOut,
    HotTopicOut,
    InstantSendRequest,
    LanguageUpdate,
    NewsletterItemOut,
    NewsletterOut,
    PipelineRunOut,
    PipelineStatus,
    SubscribeRequest,
    SubscriberOut,
)


def _normalize_language(value: str | None) -> str:
    return value if value in ("en", "ja") else "en"


def _normalize_email(value: str) -> str:
    # Email addresses are case-insensitive in practice; store and match lowercase
    # so "Aryan@..." and "aryan@..." are treated as the same subscriber.
    return value.strip().lower()

_ITEM_COLS = (
    "id, source, title, url, description, summary, application, "
    "relevance_score, stars, language, "
    "COALESCE(topics, '{}') AS topics, COALESCE(keywords, '{}') AS keywords, "
    "published_at, last_seen"
)
from app.services.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_running_task: asyncio.Task | None = None


@router.post("/pipeline/run", response_model=PipelineStatus)
async def trigger_pipeline():
    global _running_task
    if _running_task and not _running_task.done():
        raise HTTPException(400, "Pipeline already running")
    _running_task = asyncio.create_task(run_pipeline(is_test=True))
    await asyncio.sleep(0.5)
    return PipelineStatus(run_id=0, status="started")


@router.post("/pipeline/send-now", response_model=PipelineStatus)
async def send_now(req: InstantSendRequest):
    global _running_task
    if _running_task and not _running_task.done():
        raise HTTPException(400, "Pipeline already running")
    _running_task = asyncio.create_task(run_pipeline(recipients=req.recipients, is_test=True))
    await asyncio.sleep(0.5)
    return PipelineStatus(run_id=0, status="started")


@router.post("/pipeline/preview", response_model=PipelineStatus)
async def preview_pipeline():
    """Dry-run the full pipeline: fetch, score, select, but do NOT send email
    or post to Teams. Artifacts are written to dryrun_output/ for review."""
    global _running_task
    if _running_task and not _running_task.done():
        raise HTTPException(400, "Pipeline already running")
    _running_task = asyncio.create_task(run_pipeline(dry_run=True))
    await asyncio.sleep(0.5)
    return PipelineStatus(run_id=0, status="started")


@router.get("/newsletters", response_model=list[NewsletterOut])
async def list_newsletters(limit: int = 30, include_test: bool = False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if include_test:
            rows = await conn.fetch(
                "SELECT id, sent_at, subject, recipient_emails, item_count, status, error_message, is_test "
                "FROM newsletters ORDER BY sent_at DESC LIMIT $1",
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, sent_at, subject, recipient_emails, item_count, status, error_message, is_test "
                "FROM newsletters WHERE is_test = FALSE ORDER BY sent_at DESC LIMIT $1",
                limit,
            )
    return [NewsletterOut(**dict(r)) for r in rows]


@router.get("/newsletters/{newsletter_id}/items", response_model=list[NewsletterItemOut])
async def get_newsletter_items(newsletter_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, source, title, url, summary, stars, language, topics, relevance_score "
            "FROM newsletter_items WHERE newsletter_id = $1 ORDER BY relevance_score DESC",
            newsletter_id,
        )
    return [NewsletterItemOut(**dict(r)) for r in rows]


@router.get("/runs", response_model=list[PipelineRunOut])
async def list_runs(limit: int = 30, include_test: bool = False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if include_test:
            rows = await conn.fetch(
                "SELECT id, started_at, finished_at, status, github_items_found, news_items_found, "
                "items_after_dedup, error_message, is_test FROM pipeline_runs ORDER BY started_at DESC LIMIT $1",
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, started_at, finished_at, status, github_items_found, news_items_found, "
                "items_after_dedup, error_message, is_test FROM pipeline_runs "
                "WHERE is_test = FALSE ORDER BY started_at DESC LIMIT $1",
                limit,
            )
    return [PipelineRunOut(**dict(r)) for r in rows]


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest):
    language = _normalize_language(req.language)
    email = _normalize_email(req.email)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO subscribers (email, language) VALUES ($1, $2) "
            "ON CONFLICT (email) DO UPDATE SET active = TRUE, "
            "language = EXCLUDED.language, subscribed_at = NOW()",
            email,
            language,
        )
    return {"status": "subscribed", "email": email, "language": language}


@router.delete("/subscribe")
async def unsubscribe(req: SubscribeRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE subscribers SET active = FALSE WHERE email = $1",
            _normalize_email(req.email),
        )
    return {"status": "unsubscribed"}


@router.post("/subscribe/language")
async def update_language(req: LanguageUpdate):
    language = _normalize_language(req.language)
    email = _normalize_email(req.email)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE subscribers SET language = $1 WHERE email = $2",
            language,
            email,
        )
    return {"status": "updated", "email": email, "language": language}


@router.get("/subscribe/check")
async def check_subscription(email: str):
    email = _normalize_email(email)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active, language FROM subscribers WHERE email = $1",
            email,
        )
    subscribed = row is not None and row["active"]
    language = _normalize_language(row["language"]) if row is not None else "en"
    return {"email": email, "subscribed": subscribed, "language": language}


@router.get("/subscribers", response_model=list[SubscriberOut])
async def list_subscribers():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, subscribed_at, active, language FROM subscribers WHERE active = TRUE "
            "ORDER BY subscribed_at DESC",
        )
    return [SubscriberOut(**dict(r)) for r in rows]


@router.get("/items/sources")
async def item_sources():
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM fetched_items")
        rows = await conn.fetch(
            "SELECT source, COUNT(*) AS count FROM fetched_items GROUP BY source ORDER BY count DESC"
        )
    return {"total": total, "sources": [dict(r) for r in rows]}


@router.get("/items", response_model=list[FetchedItemOut])
async def search_items(
    q: str = "", source: str = "", keyword: str = "", min_score: float = 0,
    date_from: str = "", date_to: str = "",
    limit: int = 60, offset: int = 0,
):
    clauses = ["relevance_score >= $1"]
    params: list = [min_score]
    if q:
        params.append(f"%{q}%")
        i = len(params)
        clauses.append(
            f"(title ILIKE ${i} OR description ILIKE ${i} OR summary ILIKE ${i} "
            f"OR array_to_string(topics, ' ') ILIKE ${i} "
            f"OR array_to_string(keywords, ' ') ILIKE ${i})"
        )
    if source:
        params.append(source)
        clauses.append(f"source = ${len(params)}")
    if keyword:
        # Match a Hot Topic / card tag against keywords (fallback to topics)
        params.append(keyword.lower())
        clauses.append(
            f"(keywords @> ARRAY[${len(params)}]::text[] "
            f"OR EXISTS (SELECT 1 FROM unnest(topics) t WHERE lower(t) = ${len(params)}))"
        )
    # Date filter on the item's effective date: published_at when known, else first_seen
    if date_from:
        params.append(date.fromisoformat(date_from))
        clauses.append(f"COALESCE(published_at::date, first_seen::date) >= ${len(params)}")
    if date_to:
        params.append(date.fromisoformat(date_to))
        clauses.append(f"COALESCE(published_at::date, first_seen::date) <= ${len(params)}")
    where = " AND ".join(clauses)
    params.append(limit)
    lim_i = len(params)
    params.append(offset)
    off_i = len(params)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_ITEM_COLS} "
            f"FROM fetched_items WHERE {where} "
            f"ORDER BY relevance_score DESC NULLS LAST, last_seen DESC "
            f"LIMIT ${lim_i} OFFSET ${off_i}",
            *params,
        )
    return [FetchedItemOut(**dict(r)) for r in rows]


@router.get("/items/top", response_model=list[FetchedItemOut])
async def top_items(days: int = 14, limit: int = 10):
    """Auto-curated Top N: highest-scored items from the recent window."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_ITEM_COLS} FROM fetched_items "
            f"WHERE COALESCE(published_at, first_seen) >= NOW() - ($1 || ' days')::interval "
            f"AND relevance_score IS NOT NULL "
            f"ORDER BY relevance_score DESC NULLS LAST, COALESCE(published_at, first_seen) DESC "
            f"LIMIT $2",
            str(days), limit,
        )
    return [FetchedItemOut(**dict(r)) for r in rows]


@router.get("/items/hot-topics", response_model=list[HotTopicOut])
async def hot_topics(days: int = 14, limit: int = 14):
    """Most frequent content keywords across the recent window, weighted by score
    and recency. Falls back to `topics` for items whose keywords aren't set yet."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH recent AS (
                SELECT LOWER(tag) AS keyword,
                       GREATEST(COALESCE(relevance_score, 1), 1)
                         * (1.0 + GREATEST(0, 14 - EXTRACT(EPOCH FROM
                              (NOW() - COALESCE(published_at, first_seen))) / 86400.0) / 14.0) AS weight
                FROM fetched_items,
                     LATERAL unnest(
                        CASE WHEN keywords IS NOT NULL AND cardinality(keywords) > 0
                             THEN keywords ELSE topics END
                     ) AS tag
                WHERE COALESCE(published_at, first_seen) >= NOW() - ($1 || ' days')::interval
                  AND tag IS NOT NULL AND length(trim(tag)) > 0
            )
            SELECT keyword, ROUND(SUM(weight))::int AS count
            FROM recent GROUP BY keyword
            ORDER BY SUM(weight) DESC, COUNT(*) DESC
            LIMIT $2
            """,
            str(days), limit,
        )
    return [HotTopicOut(**dict(r)) for r in rows]


@router.get("/health")
async def health():
    return {"status": "ok"}
