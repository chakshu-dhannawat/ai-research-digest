import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.config import settings
from app.utils import now_jst

logger = logging.getLogger(__name__)

# Sources whose items may lack dates and need probing / LLM fallback.
DATE_PROBE_SOURCES = {"labs", "newsletter", "voices", "web_search"}

# Maximum age for articles (dynamic from settings, default 90 days = ~3 months).
DEFAULT_MAX_AGE_DAYS = 90

# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------


def parse_iso_loose(value: str | None) -> datetime | None:
    """Parse an ISO-ish or bare YYYY-MM-DD string to a UTC-aware datetime."""
    if not value:
        return None
    s = value.strip().replace("Z", "+00:00")
    for candidate in (s, s[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_rfc2822(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value.strip())
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def parse_any_date(value: str | None) -> datetime | None:
    return parse_iso_loose(value) or parse_rfc2822(value)


def clamp_datetime(dt: datetime, *, max_future_days: int = 1) -> datetime | None:
    """Reject dates unreasonably far in the future (parser noise / wrong)."""
    if dt is None:
        return None
    ceiling = datetime.now(timezone.utc) + timedelta(days=max_future_days)
    if dt > ceiling:
        return None
    return dt


# ---------------------------------------------------------------------------
# Manual / rule-based HTML date extraction
# ---------------------------------------------------------------------------


class DateExtractor:
    """Rule-based extraction of article publication dates from HTML/URL."""

    JSONLD_RE = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.I | re.S,
    )

    META_PATTERNS: list[tuple[int, re.Pattern]] = [
        # (priority, regex); lower priority wins.
        (1, re.compile(r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']', re.I)),
        (1, re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']article:published_time["\']', re.I)),
        (2, re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:published_time|og:article:published_time)["\'][^>]+content=["\']([^"\']+)["\']', re.I)),
        (2, re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:published_time["\']', re.I)),
        (2, re.compile(r'<meta[^>]+(?:property|name)=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']', re.I)),
        (2, re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']datePublished["\']', re.I)),
        (3, re.compile(r'<meta[^>]+(?:property|name)=["\']article:modified_time["\'][^>]+content=["\']([^"\']+)["\']', re.I)),
        (4, re.compile(r'<meta[^>]+(?:property|name)=["\']publish-date["\'][^>]+content=["\']([^"\']+)["\']', re.I)),
        (4, re.compile(r'<meta[^>]+(?:property|name)=["\']parsely-pub-date["\'][^>]+content=["\']([^"\']+)["\']', re.I)),
        (4, re.compile(r'<meta[^>]+(?:property|name)=["\']sailthru\.date["\'][^>]+content=["\']([^"\']+)["\']', re.I)),
    ]

    TIME_TAG_RE = re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I)
    URL_DATE_RE = re.compile(r'/(?P<year>\d{4})[/-](?P<month>\d{1,2})(?:[/-](?P<day>\d{1,2}))?(?=[/"#?]|$)')

    @classmethod
    def from_html(cls, html: str, url: str = "") -> tuple[datetime | None, str]:
        """Return (datetime_utc, source_label) from HTML/URL."""
        candidates: list[tuple[int, datetime, str]] = []

        # 1. JSON-LD (highest fidelity when present).
        for script_match in cls.JSONLD_RE.finditer(html):
            snippet = script_match.group(1)
            # Strip HTML comments / CDATA wrappers that break JSON parsing.
            snippet = re.sub(r"<!--|-->|<!\[CDATA\[|\]\]>", "", snippet)
            try:
                data = json.loads(snippet)
            except json.JSONDecodeError:
                continue

            items: list = [data]
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and isinstance(data.get("@graph"), list):
                items = data["@graph"]

            for item in items:
                if not isinstance(item, dict):
                    continue
                dtype = str(item.get("@type", "")).lower()
                is_article = any(
                    x in dtype for x in ("newsarticle", "blogposting", "article", "scholarlyarticle")
                )
                baseprio = 1 if is_article else 2
                for key in ("datePublished", "dateCreated", "dateModified"):
                    raw = item.get(key)
                    dt = parse_any_date(raw)
                    if dt:
                        prio = baseprio + (0 if key == "datePublished" else 1)
                        candidates.append((prio, dt, f"jsonld.{key}"))

        # 2. Meta tags (accept ISO or RFC-2822).
        for priority, pattern in cls.META_PATTERNS:
            m = pattern.search(html)
            if m:
                dt = parse_any_date(m.group(1))
                if dt:
                    candidates.append((priority, dt, "meta"))

        # 3. <time datetime="...">.
        for m in cls.TIME_TAG_RE.finditer(html):
            dt = parse_any_date(m.group(1))
            if dt:
                candidates.append((5, dt, "time"))

        # 4. URL path date (lowest confidence).
        if url:
            url_match = cls.URL_DATE_RE.search(url)
            if url_match:
                gd = url_match.groupdict()
                try:
                    dt = datetime(
                        int(gd["year"]), int(gd["month"]), int(gd["day"] or 1),
                        tzinfo=timezone.utc,
                    )
                    candidates.append((6, dt, "url_path"))
                except ValueError:
                    pass

        for priority, dt, source in sorted(candidates, key=lambda x: x[0]):
            dt = clamp_datetime(dt)
            if dt:
                return dt, source

        return None, ""


# ---------------------------------------------------------------------------
# LLM fallback for date extraction
# ---------------------------------------------------------------------------

_LLM_DATE_SYSTEM_PROMPT = """\
You are a publication-date extractor for an AI newsletter.

Given an article URL, title, and a short text snippet from the page, determine the ORIGINAL publication date of the article. Prefer "published" over "last updated" or "modified" unless only an updated date is available.

Return ONLY a JSON object with this exact shape and no other text:
{"date": "YYYY-MM-DD", "confidence": "high" | "medium" | "low" | "none", "source": "meta" | "page_text" | "url" | "guess", "reason": "one sentence"}

Rules:
- If the date is clearly in metadata or the page text, return it as YYYY-MM-DD and confidence high/medium/low.
- If you must infer from context, return confidence low or none.
- If no date can be determined, return {"confidence": "none", "date": null, "source": "none", "reason": "..."}.
- Do not return future dates beyond today."""


def _strip_html_to_snippet(html: str, max_chars: int = 2500) -> str:
    """Return visible text snippet from HTML without external dependencies."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def llm_extract_date(client, model: str, url: str, title: str, html: str) -> tuple[datetime | None, str]:
    """Use the LLM to extract a publication date from article HTML.

    Returns (datetime_utc, provenance_label). datetime is None if extraction fails.
    """
    try:
        snippet = _strip_html_to_snippet(html, max_chars=2500)
        user = (
            f"Article URL: {url}\n"
            f"Title: {title}\n"
            f"Snippet:\n{snippet}"
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_DATE_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=256,
        )
        raw = (resp.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
    except Exception as e:
        logger.debug("LLM date extraction parse/request failed for %s: %s", url, e)
        return None, "llm_error"

    confidence = (parsed.get("confidence") or "").lower()
    date_str = parsed.get("date")
    if confidence == "none" or not date_str:
        return None, "llm_none"

    dt = parse_iso_loose(date_str)
    if not dt:
        return None, "llm_unparseable"

    dt = clamp_datetime(dt)
    if not dt:
        return None, "llm_future"

    provenance = f"llm:{parsed.get('source', 'unknown')}:{confidence}"
    return dt, provenance


# ---------------------------------------------------------------------------
# Orchestrated date enrichment + age filter
# ---------------------------------------------------------------------------


async def enrich_and_filter_by_age(
    items: list[dict],
    llm_client=None,
    llm_model: str | None = None,
    max_age_days: int | None = None,
    max_concurrent_html: int = 8,
    max_concurrent_llm: int = 4,
) -> list[dict]:
    """Enrich items with publication dates and drop anything older than max_age_days.

    - Uses existing `published_at` when present.
    - Probes HTML for article-type sources with no date.
    - Optionally calls an LLM to infer dates when manual extraction fails.
    - Drops items whose date cannot be determined (no more "keep on guess").
    """
    if max_age_days is None:
        max_age_days = getattr(settings, "max_article_age_days", DEFAULT_MAX_AGE_DAYS)

    cutoff = now_jst() - timedelta(days=max_age_days)
    cutoff_utc = cutoff.astimezone(timezone.utc)

    # Parse existing dates.
    for it in items:
        pub = it.get("published_at")
        if pub:
            dt = parse_any_date(pub)
            if dt:
                it["_pub_dt"] = dt

    # --- Manual HTML probe for date-less article sources ---------------------
    to_probe: list[dict] = [
        it for it in items
        if "_pub_dt" not in it
        and it.get("source") in DATE_PROBE_SOURCES
        and str(it.get("url", "")).startswith("http")
    ]

    html_cache: dict[str, str] = {}
    sem_html = asyncio.Semaphore(max_concurrent_html)
    sem_llm = asyncio.Semaphore(max_concurrent_llm)

    async with httpx.AsyncClient(
        proxy=settings.http_proxy,
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=40, max_keepalive_connections=15),
    ) as shared_client:

        async def _probe_html(it: dict):
            async with sem_html:
                try:
                    resp = await shared_client.get(it["url"])
                    resp.raise_for_status()
                    html = resp.text
                except Exception as e:
                    logger.debug("HTML date probe failed for %s: %s", it.get("url"), e)
                    return

                html_cache[it["url"]] = html
                dt, source = DateExtractor.from_html(html, it.get("url", ""))
                if dt:
                    it["_pub_dt"] = dt
                    it["_date_source"] = source

        if to_probe:
            await asyncio.gather(*(_probe_html(it) for it in to_probe), return_exceptions=True)

        # --- LLM fallback for still-date-less items --------------------------
        if llm_client and llm_model:
            to_llm = [it for it in items if "_pub_dt" not in it]

            async def _probe_llm(it: dict):
                async with sem_llm:
                    html = html_cache.get(it["url"])
                    if not html and it.get("url", "").startswith("http"):
                        try:
                            resp = await shared_client.get(it["url"])
                            html = resp.text
                        except Exception:
                            return
                    if not html:
                        return

                    dt, source = await asyncio.to_thread(
                        llm_extract_date,
                        llm_client, llm_model, it["url"], it.get("title", ""), html,
                    )
                    if dt:
                        it["_pub_dt"] = dt
                        it["_date_source"] = source

            if to_llm:
                await asyncio.gather(*(_probe_llm(it) for it in to_llm), return_exceptions=True)

    # --- Apply cutoff. Undated items use a "recent fallback" only for items we
    # scraped from current listing pages (Anthropic, MiniMax); all others are dropped. -
    kept, dropped_old, dropped_undated = [], 0, 0
    for it in items:
        dt = it.pop("_pub_dt", None)
        source = it.pop("_date_source", None)
        recent_fallback = it.pop("_recent_fallback", None)

        if dt is None and recent_fallback:
            dt = parse_any_date(recent_fallback)
            source = "recent_fallback"

        if dt is None:
            dropped_undated += 1
            continue
        if dt < cutoff_utc:
            dropped_old += 1
            continue

        it["published_at"] = dt.isoformat()
        if source:
            it["date_source"] = source
        kept.append(it)

    logger.info(
        "Recency filter (%dd): kept=%d dropped_old=%d dropped_undated=%d",
        max_age_days, len(kept), dropped_old, dropped_undated,
    )
    return kept
