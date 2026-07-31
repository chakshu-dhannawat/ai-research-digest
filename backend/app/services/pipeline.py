import asyncio
import logging
import re
from datetime import datetime, timezone

from app.config import settings
from app.utils import now_jst
from app.database import get_pool
from app.services.github_crawler import fetch_trending_repos
from app.services.news_fetcher import fetch_ai_newsletters, fetch_model_releases, fetch_web_search_news, fetch_ai_voices, fetch_hf_papers, fetch_ai_labs, filter_articles_by_age
from app.services.llm_summarizer import score_and_summarize, translate_items_to_japanese, current_model, reset_llm_resolution, _resolve
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

# Minimum recent items we want from each source before scoring. If the initial
# fetch falls short, exactly one refill wave widens parameters for that source.
_SOURCE_MINIMUMS = {
    "github": 5,
    "hf_papers": 3,
    "labs": 4,
    "voices": 3,
    "newsletter": 4,
    "model_release": 3,
    "web_search": 3,
}

# Soft ceiling on total candidates before scoring to protect LLM cost/time.
_MAX_PRESCORE_ITEMS = 50


async def _safe_fetch(name: str, coro) -> list[dict]:
    """Run an async fetcher inside a try/except so one source never kills the run."""
    try:
        items = await coro
        logger.info("Fetched %d items from %s", len(items), name)
        return items
    except Exception as e:
        logger.exception("Fetch failed for %s: %s", name, e)
        return []


def _count_by_source(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in items:
        src = it.get("source", "unknown")
        counts[src] = counts.get(src, 0) + 1
    return counts


def _source_quality_key(item: dict):
    """Sort key for trimming excess items: newest/starry/substantive first."""
    pub_str = item.get("published_at") or ""
    try:
        pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
    except Exception:
        pub_dt = datetime.min.replace(tzinfo=timezone.utc)
    stars = item.get("stars") or 0
    desc_len = len(item.get("description") or "")
    return (pub_dt, stars, desc_len)


def _url_dedup(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        url = str(it.get("url", ""))
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        out.append(it)
    return out


def _cap_candidates(items: list[dict]) -> list[dict]:
    """Respect per-source minimums while capping total candidates."""
    by_source: dict[str, list[dict]] = {}
    for it in items:
        by_source.setdefault(it.get("source", "unknown"), []).append(it)

    preserved: list[dict] = []
    extras: list[dict] = []
    for source, its in by_source.items():
        its.sort(key=_source_quality_key, reverse=True)
        minimum = _SOURCE_MINIMUMS.get(source, 0)
        preserved.extend(its[:minimum])
        extras.extend(its[minimum:])

    if len(preserved) >= _MAX_PRESCORE_ITEMS:
        all_sorted = sorted(preserved + extras, key=_source_quality_key, reverse=True)
        return all_sorted[:_MAX_PRESCORE_ITEMS]

    extras.sort(key=_source_quality_key, reverse=True)
    allowed_extra = _MAX_PRESCORE_ITEMS - len(preserved)
    return preserved + extras[:allowed_extra]


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
        # --- Initial fetch wave (concurrent, isolated per source) --------------
        initial_coros = {
            "github": asyncio.to_thread(fetch_trending_repos, max_per_query=5),
            "hf_papers": fetch_hf_papers(max_per_day=5, populated_days=1, lookback_days=6),
            "newsletter": fetch_ai_newsletters(max_per_feed=5),
            "labs": fetch_ai_labs(max_per_feed=4),
            "model_release": fetch_model_releases(max_items=8),
            "web_search": fetch_web_search_news(max_per_query=3, timelimit="w"),
            "voices": fetch_ai_voices(max_per_feed=4),
        }
        names = list(initial_coros.keys())
        initial_results_raw = await asyncio.gather(
            *(_safe_fetch(name, initial_coros[name]) for name in names),
            return_exceptions=True,
        )
        initial_results = {
            name: (res if not isinstance(res, Exception) else [])
            for name, res in zip(names, initial_results_raw)
        }
        all_items = [it for items in initial_results.values() for it in items]

        # Recency filter with manual extraction + LLM fallback.
        llm_client, llm_model = await asyncio.to_thread(_resolve)
        all_items = await filter_articles_by_age(
            all_items,
            max_age_days=settings.max_article_age_days,
            llm_client=llm_client,
            llm_model=llm_model,
        )
        all_items = _url_dedup(all_items)

        # --- One refill wave for sources below their minimum -------------------
        counts = _count_by_source(all_items)
        deficits = {src: max(0, _SOURCE_MINIMUMS[src] - counts.get(src, 0)) for src in _SOURCE_MINIMUMS}
        refill_sources = [src for src, d in deficits.items() if d > 0]

        if refill_sources:
            logger.info("Refilling sources below minimum: %s", deficits)
            refill_params = {
                "github": {"max_per_query": 10},
                "hf_papers": {"max_per_day": 8, "populated_days": 3, "lookback_days": 14, "max_days_total": 14},
                "newsletter": {"max_per_feed": 10},
                "labs": {"max_per_feed": 10, "anthropic_max_items": 10, "minimax_max_items": 10},
                "model_release": {"max_items": 16, "hf_trending_limit": 20, "gh_releases_per_page": 6, "org_limit": 10, "org_cutoff_days": 60},
                "web_search": {"max_per_query": 6, "timelimit": "m"},
                "voices": {"max_per_feed": 10},
            }
            refill_coros = {
                "github": lambda: asyncio.to_thread(fetch_trending_repos, **refill_params["github"]),
                "hf_papers": lambda: fetch_hf_papers(**refill_params["hf_papers"]),
                "newsletter": lambda: fetch_ai_newsletters(**refill_params["newsletter"]),
                "labs": lambda: fetch_ai_labs(**refill_params["labs"]),
                "model_release": lambda: fetch_model_releases(**refill_params["model_release"]),
                "web_search": lambda: fetch_web_search_news(**refill_params["web_search"]),
                "voices": lambda: fetch_ai_voices(**refill_params["voices"]),
            }
            active_refills = {src: refill_coros[src]() for src in refill_sources}
            refill_results_raw = await asyncio.gather(
                *(_safe_fetch(src, active_refills[src]) for src in refill_sources),
                return_exceptions=True,
            )
            refill_results = {
                src: (res if not isinstance(res, Exception) else [])
                for src, res in zip(refill_sources, refill_results_raw)
            }
            refill_counts = {src: len(items) for src, items in refill_results.items()}
            logger.info("Refill wave added items: %s", refill_counts)

            if any(refill_results.values()):
                refill_items = [it for items in refill_results.values() for it in items]
                refill_items = await filter_articles_by_age(
                    refill_items,
                    max_age_days=settings.max_article_age_days,
                    llm_client=llm_client,
                    llm_model=llm_model,
                )
                all_items = _url_dedup(all_items + refill_items)

        if not is_test:
            all_items = await filter_already_sent(pool, all_items)

        all_items = _cap_candidates(all_items)
        pre_score_count = len(all_items)
        fetch_counts = _count_by_source(all_items)
        logger.info("Candidate pool: %d items %s", pre_score_count, fetch_counts)

        await _update_run(pool, run_id, github_found=fetch_counts.get("github", 0),
                          news_found=pre_score_count, refilled_sources=refill_sources,
                          pre_score_count=pre_score_count)

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
            items_l = await asyncio.to_thread(translate_items_to_japanese, top_items) if lang == "ja" else top_items
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


async def _update_run(pool, run_id: int, github_found: int = 0, news_found: int = 0,
                      refilled_sources: list[str] | None = None, pre_score_count: int | None = None):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE pipeline_runs SET github_items_found=$1, news_items_found=$2, "
            "refilled_sources=$3, pre_score_count=$4 WHERE id=$5",
            github_found, news_found, refilled_sources or [], pre_score_count, run_id,
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
