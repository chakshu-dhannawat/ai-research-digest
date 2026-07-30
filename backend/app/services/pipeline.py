import asyncio
import logging
import re
from datetime import datetime

from app.config import settings
from app.utils import now_jst
from app.database import get_pool
from app.services.github_crawler import fetch_trending_repos
from app.services.news_fetcher import fetch_ai_newsletters, fetch_model_releases, fetch_web_search_news, fetch_ai_voices, fetch_hf_papers, fetch_ai_labs, filter_articles_by_age
from app.services.llm_summarizer import score_and_summarize, translate_items_to_japanese, current_model, reset_llm_resolution
from app.services.dedup import filter_already_sent, mark_as_sent
from app.services.email_sender import render_newsletter, send_email
from app.services.teams_sender import send_teams_digest

logger = logging.getLogger(__name__)

# Items scoring below this are junk (beginner/marketing/off-scope) OR silent
# scoring failures (which fall back to score 0) — neither belongs in the digest,
# even to fill it out. They are still saved to the searchable catalog.
MIN_DIGEST_SCORE = 4

# Even on a thin day, send at least this many items — backfilled from the
# highest-scoring leftovers below MIN_DIGEST_SCORE — so the digest never looks
# broken. Only kicks in if fewer than this many items clear the real floor.
MIN_DIGEST_ITEMS = 3

# Tie-breaker for equal relevance scores: prefer higher-signal editorial sources,
# then more substantive text. Without this, equal scores fell to fetch (source
# concat) order, which let arbitrary ordering decide the top-N cutoff.
_SOURCE_RANK = {
    "model_release": 0, "labs": 1, "hf_papers": 2, "voices": 3,
    "newsletter": 4, "github": 5, "web_search": 6,
}


def _digest_sort_key(item: dict) -> tuple:
    score = item.get("relevance_score") or 0
    rank = _SOURCE_RANK.get(item.get("source", ""), 9)
    desc_len = len(item.get("description") or "")
    return (-score, rank, -desc_len)  # score desc, source rank asc, longer desc first


async def run_pipeline(
    recipients: list[str] | None = None,
    is_test: bool = False,
    recipients_by_lang: dict[str, list[str]] | None = None,
) -> dict:
    pool = await get_pool()

    # Re-evaluate LLM endpoints from the top each run so a recovered primary
    # (Qwen) is preferred again instead of sticking on a fallback.
    reset_llm_resolution()

    run_id = await _create_run(pool, is_test)

    try:
        github_items = await asyncio.to_thread(fetch_trending_repos)
        hf_paper_items = await fetch_hf_papers()
        newsletter_items = await fetch_ai_newsletters()
        labs_items = await fetch_ai_labs()
        model_release_items = await fetch_model_releases()
        web_search_items = await fetch_web_search_news()
        voices_items = await fetch_ai_voices()

        await _update_run(pool, run_id, github_found=len(github_items),
                          news_found=len(hf_paper_items) + len(newsletter_items) + len(labs_items) + len(model_release_items) + len(web_search_items) + len(voices_items))

        all_items = github_items + hf_paper_items + newsletter_items + labs_items + model_release_items + web_search_items + voices_items

        # Drop anything older than ~6 months (probes the web for dates on
        # date-less scraped articles), before dedup/scoring.
        all_items = await filter_articles_by_age(all_items)

        if not is_test:
            all_items = await filter_already_sent(pool, all_items)

        scored = await asyncio.to_thread(score_and_summarize, all_items)
        scored.sort(key=_digest_sort_key)

        # Persist the full scored set to the searchable catalog (deduped by URL).
        # Isolated so a catalog failure never blocks the newsletter send.
        try:
            await _save_fetched_items(pool, scored)
        except Exception as e:
            logger.warning("Failed to save fetched_items catalog: %s", e)

        eligible = [it for it in scored if (it.get("relevance_score") or 0) >= MIN_DIGEST_SCORE]
        if len(eligible) < len(scored):
            logger.info("Digest floor: %d/%d items below score %d dropped from send (kept in catalog)",
                        len(scored) - len(eligible), len(scored), MIN_DIGEST_SCORE)
        top_items = eligible[: settings.top_n_items]

        # Thin-day backfill: `scored` is already sorted best-first, so the next
        # leftovers are the least-bad of what's left, not arbitrary items.
        if len(top_items) < MIN_DIGEST_ITEMS:
            picked_ids = {id(it) for it in top_items}
            leftovers = [it for it in scored if id(it) not in picked_ids]
            needed = MIN_DIGEST_ITEMS - len(top_items)
            backfill = leftovers[:needed]
            if backfill:
                logger.info("Digest backfill: only %d item(s) cleared score %d; adding %d below-floor item(s) to reach %d",
                            len(top_items), MIN_DIGEST_SCORE, len(backfill), MIN_DIGEST_ITEMS)
                top_items = top_items + backfill

        if not top_items:
            await _finish_run(pool, run_id, "completed", items_after_dedup=0)
            return {"run_id": run_id, "status": "no_new_items", "items_sent": 0}

        # Build language -> recipients map. Explicit per-lang wins; else a single
        # English group from `recipients` or the configured default.
        if recipients_by_lang:
            lang_map = recipients_by_lang
        elif recipients:
            lang_map = {"en": recipients}
        else:
            lang_map = {"en": settings.default_recipients.split(",")}

        date_str = now_jst().strftime("%Y-%m-%d")
        model_used = current_model()  # audit only — never shown to recipients
        newsletter_ids = []
        for lang, rcpts in lang_map.items():
            if not rcpts:
                continue
            items_l = translate_items_to_japanese(top_items) if lang == "ja" else top_items
            html = render_newsletter(items_l, lang=lang)
            if lang == "ja":
                subject = f"🤖 AIエンジニア・デイリーダイジェスト — {date_str}"
            else:
                subject = f"🤖 AI Engineer Daily Digest — {date_str}"
            send_email(html, rcpts, subject)
            nid = await _save_newsletter(pool, subject, rcpts, items_l, is_test, model_used)
            newsletter_ids.append(nid)

        # Mark sent ONCE total (prod only), not per language group.
        if not is_test:
            await mark_as_sent(pool, top_items)

        # Best-effort Teams channel post (prod only, non-blocking).
        if not is_test:
            try:
                teams_ok = await send_teams_digest(top_items)
                await _record_teams_status(pool, run_id, error=None if teams_ok else "unknown error")
            except Exception as e:
                logger.exception("Teams post failed; continuing pipeline: %s", e)
                await _record_teams_status(pool, run_id, error=str(e))

        await _finish_run(pool, run_id, "completed", items_after_dedup=len(top_items))

        logger.info("Pipeline complete: %d items sent to %s", len(top_items), lang_map)
        return {
            "run_id": run_id,
            "newsletter_ids": newsletter_ids,
            "status": "sent",
            "items_sent": len(top_items),
        }

    except Exception as e:
        logger.exception("Pipeline failed")
        await _finish_run(pool, run_id, "failed", error=str(e))
        return {"run_id": run_id, "status": "failed", "error": str(e)}


async def _create_run(pool, is_test: bool = False) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO pipeline_runs (is_test) VALUES ($1) RETURNING id",
            is_test,
        )


async def _update_run(pool, run_id: int, github_found: int = 0, news_found: int = 0):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE pipeline_runs SET github_items_found=$1, news_items_found=$2 WHERE id=$3",
            github_found, news_found, run_id,
        )


async def _finish_run(pool, run_id: int, status: str, items_after_dedup: int = 0, error: str | None = None):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE pipeline_runs SET finished_at=NOW(), status=$1, items_after_dedup=$2, error_message=$3 WHERE id=$4",
            status, items_after_dedup, error, run_id,
        )


async def _record_teams_status(pool, run_id: int, error: str | None = None):
    async with pool.acquire() as conn:
        if error is None:
            await conn.execute(
                "UPDATE pipeline_runs SET teams_posted_at=NOW(), teams_error=NULL WHERE id=$1",
                run_id,
            )
        else:
            await conn.execute(
                "UPDATE pipeline_runs SET teams_posted_at=NULL, teams_error=$1 WHERE id=$2",
                error, run_id,
            )


# Sources whose feed/topic name is a meaningful publisher brand worth tagging
# (e.g. "Anthropic News" -> anthropic, "Elastic Blog" -> elastic, "Qwen" -> qwen).
_BRAND_SOURCES = {"newsletter", "voices", "model_release", "labs"}


def _brand_tag(source: str, topics: list) -> str | None:
    if source not in _BRAND_SOURCES or not topics:
        return None
    t = (topics[0] or "").lower()
    t = re.sub(r"\(.*?\)", "", t)                              # drop "(Nathan Lambert)"
    t = re.sub(r"\b(blog|news|engineering|research)\b", "", t)  # drop section words
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or None


def _merge_keywords(item: dict) -> list[str]:
    """Content keywords (from the LLM) plus a deterministic publisher brand tag."""
    kws = list(item.get("keywords") or [])
    brand = _brand_tag(item.get("source", ""), item.get("topics") or [])
    if brand and brand not in kws:
        kws.append(brand)
    return kws


async def _save_fetched_items(pool, items: list[dict]):
    """Upsert every scored item into the searchable catalog, deduped by URL."""
    async with pool.acquire() as conn:
        for item in items:
            url = item.get("url")
            title = item.get("title") or item.get("name", "")
            if not url or not title:
                continue
            pub = item.get("published_at")
            pub_dt = None
            if pub:
                try:
                    pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pub_dt = None
            await conn.execute(
                """INSERT INTO fetched_items
                   (source, title, url, description, summary, application,
                    relevance_score, stars, language, topics, published_at, keywords, last_seen)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
                   ON CONFLICT (url) DO UPDATE SET
                     title=EXCLUDED.title,
                     description=EXCLUDED.description,
                     summary=EXCLUDED.summary,
                     application=EXCLUDED.application,
                     relevance_score=EXCLUDED.relevance_score,
                     stars=EXCLUDED.stars,
                     language=EXCLUDED.language,
                     topics=EXCLUDED.topics,
                     published_at=EXCLUDED.published_at,
                     keywords=EXCLUDED.keywords,
                     last_seen=NOW()""",
                item.get("source", ""),
                title,
                url,
                (item.get("description") or "")[:1000],
                item.get("summary", ""),
                item.get("application", ""),
                item.get("relevance_score"),
                item.get("stars"),
                item.get("language"),
                item.get("topics", []),
                pub_dt,
                _merge_keywords(item),
            )


async def _save_newsletter(pool, subject: str, recipients: list[str], items: list[dict], is_test: bool = False, model_used: str | None = None) -> int:
    async with pool.acquire() as conn:
        nid = await conn.fetchval(
            "INSERT INTO newsletters (subject, recipient_emails, item_count, status, is_test, model_used) "
            "VALUES ($1, $2, $3, 'sent', $4, $5) RETURNING id",
            subject, recipients, len(items), is_test, model_used,
        )
        for item in items:
            title = item.get("title") or item.get("name", "")
            await conn.execute(
                """INSERT INTO newsletter_items
                   (newsletter_id, source, title, url, summary, stars, language, topics, relevance_score)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                nid,
                item.get("source", ""),
                title,
                item.get("url"),
                item.get("summary", ""),
                item.get("stars"),
                item.get("language"),
                item.get("topics", []),
                item.get("relevance_score"),
            )
        return nid
