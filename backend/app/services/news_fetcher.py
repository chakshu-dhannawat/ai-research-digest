import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
from duckduckgo_search import DDGS

from app.config import settings
from app.utils import now_jst

logger = logging.getLogger(__name__)

ARXIV_QUERIES = [
    "cat:cs.AI",
    "cat:cs.CL",
    "cat:cs.CV",
    "cat:cs.LG",
]



async def fetch_arxiv_papers(max_per_category: int = 3) -> list[dict]:
    papers = []

    async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True) as client:
        for cat in ARXIV_QUERIES:
            url = (
                f"https://export.arxiv.org/api/query?"
                f"search_query={cat}&sortBy=submittedDate&sortOrder=descending"
                f"&start=0&max_results={max_per_category}"
            )
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.findall("atom:entry", ns):
                    title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
                    summary = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")[:500]
                    link = ""
                    for l in entry.findall("atom:link", ns):
                        if l.get("type") == "text/html":
                            link = l.get("href", "")
                            break
                    if not link:
                        link = entry.findtext("atom:id", "", ns)
                    published = entry.findtext("atom:published", "", ns).strip()
                    papers.append({
                        "source": "arxiv",
                        "title": title,
                        "url": link,
                        "description": summary,
                        "stars": None,
                        "language": None,
                        "topics": [cat.replace("cat:", "")],
                        "published_at": published or None,
                    })
            except Exception as e:
                logger.warning("arXiv fetch failed for %s: %s", cat, e)

    seen_urls = set()
    deduped = []
    for p in papers:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            deduped.append(p)
    papers = deduped

    logger.info("Fetched %d arXiv papers", len(papers))
    return papers


async def fetch_hf_papers(max_per_day: int = 5, populated_days: int = 1, lookback_days: int = 6) -> list[dict]:
    """HuggingFace Daily Papers — community-curated TRENDING papers, ranked by
    upvotes. This surfaces the high-impact papers that digests like The AI
    Timeline feature. Tagged as its own source ("hf_papers").

    Scans backward day-by-day (up to `lookback_days`) and keeps the top
    `max_per_day` papers from the most recent `populated_days` day(s) that
    actually have papers. Since the pipeline runs daily, fetching just the
    single most recent populated day is enough — Friday's papers are already
    covered by Saturday/Sunday runs, and cross-run dedup prevents repeats. The
    backward scan still bridges weekends/holidays and the UTC-vs-JST date shift
    so a Monday run finds the latest available day rather than an empty one.
    Dedupes by arXiv id."""
    items: list[dict] = []

    def _upvotes(p):
        return p.get("upvotes") or (p.get("paper") or {}).get("upvotes") or 0

    now = now_jst()

    seen_ids: set[str] = set()
    days_with_papers = 0
    async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True) as client:
        for back in range(lookback_days + 1):
            if days_with_papers >= populated_days:
                break
            date = (now - timedelta(days=back)).strftime("%Y-%m-%d")
            try:
                resp = await client.get(f"https://huggingface.co/api/daily_papers?date={date}")
                resp.raise_for_status()
                papers = resp.json()
            except Exception as e:
                logger.warning("HF daily papers fetch failed for %s: %s", date, e)
                continue
            if not papers:
                continue

            day_items = []
            for p in papers:
                pp = p.get("paper") or {}
                pid = (pp.get("id") or "").strip()
                title = (pp.get("title") or p.get("title") or "").strip().replace("\n", " ")
                if not pid or not title or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                summary = (pp.get("summary") or "").strip().replace("\n", " ")[:500]
                day_items.append({
                    "source": "hf_papers",
                    "title": title,
                    "url": f"https://arxiv.org/abs/{pid}",
                    "description": summary,
                    "stars": _upvotes(p),
                    "language": None,
                    "topics": ["HF Paper"],
                    "published_at": pp.get("publishedAt") or p.get("publishedAt"),
                    "_upvotes_raw": _upvotes(p),
                })

            if not day_items:
                continue
            # Top max_per_day by upvotes for this day
            day_items.sort(key=lambda x: x.pop("_upvotes_raw"), reverse=True)
            items.extend(day_items[:max_per_day])
            days_with_papers += 1

    logger.info("Fetched %d HF trending papers", len(items))
    return items


# Active, frequently-updated AI blogs (verified live). The recency filter in
# fetch_ai_newsletters drops anything older than NEWSLETTER_RECENCY_DAYS, so
# slow-publishing feeds simply contribute nothing when they have no fresh post.
# --- Three distinct categories (all verified live; same recency filter) ---

# AI news outlets, digests, and company/product blogs (source="newsletter").
AI_NEWSLETTER_FEEDS = [
    ("Import AI", "https://importai.substack.com/feed"),
    ("Elastic Blog", "https://www.elastic.co/blog/feed"),
    ("Latent Space", "https://www.latent.space/feed"),
    ("MarkTechPost", "https://www.marktechpost.com/feed/"),
]

# Named individual practitioners sharing expertise (source="voices").
AI_VOICES_FEEDS = [
    ("Eugene Yan", "https://eugeneyan.com/rss/"),
    ("Interconnects (Nathan Lambert)", "https://www.interconnects.ai/feed"),
    ("Philipp Schmid", "https://www.philschmid.de/rss"),
    ("Ethan Mollick", "https://www.oneusefulthing.org/feed"),
    ("Hamel Husain", "https://hamel.dev/index.xml"),
    ("Chip Huyen", "https://huyenchip.com/feed.xml"),
    ("Jay Alammar", "https://jalammar.github.io/feed.xml"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    ("Sebastian Raschka", "https://magazine.sebastianraschka.com/feed"),
    ("Lilian Weng", "https://lilianweng.github.io/index.xml"),
]

# Official AI lab / research-org blogs & technical reports (source="labs").
# The Anthropic and MiniMax scrapers also feed into this category.
AI_LABS_FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Google Research", "https://research.google/blog/rss/"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Together AI", "https://www.together.ai/blog/rss.xml"),
    ("Qwen", "https://qwenlm.github.io/blog/index.xml"),
]

NEWSLETTER_RECENCY_DAYS = 14


def _parse_entry_date(entry) -> datetime | None:
    """Extract a timezone-aware publication date from an RSS or Atom entry."""
    raw = (
        entry.findtext("pubDate")
        or entry.findtext("{http://purl.org/dc/elements/1.1/}date")
        or entry.findtext("{http://www.w3.org/2005/Atom}published")
        or entry.findtext("{http://www.w3.org/2005/Atom}updated")
    )
    if not raw:
        return None
    raw = raw.strip()
    # RSS pubDate is RFC 822 ("Thu, 11 Jun 2026 00:00:00 GMT")
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    # Atom published/updated is ISO 8601 ("2026-06-11T23:35:17+00:00")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

ANTHROPIC_PAGES = [
    ("Anthropic News", "https://www.anthropic.com/news"),
    ("Anthropic Engineering", "https://www.anthropic.com/engineering"),
    ("Anthropic Research", "https://www.anthropic.com/research"),
]


async def _fetch_feed_items(client, feeds, source: str, max_per_feed: int, cutoff: datetime) -> list[dict]:
    """Parse a list of RSS/Atom feeds, keeping up to max_per_feed recent items each."""
    items = []
    for feed_name, feed_url in feeds:
        try:
            resp = await client.get(feed_url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)

            # Handle both RSS 2.0 (<item>) and Atom (<entry>) feeds
            entries = root.findall(".//item")
            if not entries:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entries = root.findall("atom:entry", ns)

            kept = 0
            for entry in entries:
                if kept >= max_per_feed:
                    break
                # Recency filter — skip posts older than the cutoff. Feeds are
                # reverse-chronological, so a stale newest entry means the whole
                # feed is stale (e.g. a quarterly blog) and contributes nothing.
                pub_dt = _parse_entry_date(entry)
                if pub_dt is not None and pub_dt < cutoff:
                    continue

                title = (
                    entry.findtext("title", "").strip()
                    or entry.findtext("{http://www.w3.org/2005/Atom}title", "").strip()
                )
                link = entry.findtext("link", "").strip()
                if not link:
                    # Atom <link href="..."/>: the URL is in the href attribute.
                    # NOTE: an ElementTree element with no children is falsy, so
                    # `entry.find(...) or {}` silently drops the href — iterate
                    # explicitly and prefer the alternate/html link.
                    for l in entry.findall("{http://www.w3.org/2005/Atom}link"):
                        if l.get("rel", "alternate") == "alternate":
                            link = l.get("href", "")
                            if l.get("type") == "text/html":
                                break
                desc_raw = (
                    entry.findtext("description", "").strip()
                    or entry.findtext("{http://www.w3.org/2005/Atom}summary", "").strip()
                )
                # Strip HTML tags for a clean snippet
                description = re.sub(r"<[^>]+>", "", desc_raw)[:500]

                if title:
                    items.append({
                        "source": source,
                        "title": title,
                        "url": link,
                        "description": description,
                        "stars": None,
                        "language": None,
                        "topics": [feed_name],
                        "published_at": pub_dt.isoformat() if pub_dt else None,
                    })
                    kept += 1
        except Exception as e:
            logger.warning("%s fetch failed for %s: %s", source, feed_name, e)
    return items


async def fetch_ai_newsletters(max_per_feed: int = 5) -> list[dict]:
    cutoff = now_jst() - timedelta(days=NEWSLETTER_RECENCY_DAYS)

    async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True) as client:
        items = await _fetch_feed_items(client, AI_NEWSLETTER_FEEDS, "newsletter", max_per_feed, cutoff)

    # Newest first across all feeds (undated items sort last), then cap to keep
    # LLM scoring time bounded so delivery stays before 09:00 JST.
    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)
    items = items[:20]
    logger.info("Fetched %d newsletter items (recency <= %dd)", len(items), NEWSLETTER_RECENCY_DAYS)
    return items


async def fetch_ai_labs(max_per_feed: int = 4) -> list[dict]:
    """Official AI lab / research-org blogs & technical reports (source='labs').
    Includes the Anthropic and MiniMax scrapers."""
    cutoff = now_jst() - timedelta(days=NEWSLETTER_RECENCY_DAYS)

    async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True) as client:
        items = await _fetch_feed_items(client, AI_LABS_FEEDS, "labs", max_per_feed, cutoff)

    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)
    items = items[:15]

    items.extend(await _scrape_anthropic(client=None))
    items.extend(await _scrape_minimax())

    logger.info("Fetched %d AI labs items (recency <= %dd)", len(items), NEWSLETTER_RECENCY_DAYS)
    return items


async def _scrape_minimax(client=None, max_items: int = 6) -> list[dict]:
    """MiniMax has no RSS feed — scrape model/paper announcements off its news page."""
    items = []
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True)
    try:
        resp = await client.get("https://www.minimax.io/news")
        resp.raise_for_status()
        cards = re.findall(r'href="(/news/[^"]+)"[^>]*>(?:<[^>]+>)*\s*([^<]{3,90})', resp.text)
        seen = set()
        for path, title in cards:
            title = title.strip()
            if not title or path in seen:
                continue
            seen.add(path)
            items.append({
                "source": "labs",
                "title": title,
                "url": f"https://www.minimax.io{path}",
                "description": title,
                "stars": None,
                "language": None,
                "topics": ["MiniMax"],
                "published_at": None,
            })
            if len(items) >= max_items:
                break
    except Exception as e:
        logger.warning("MiniMax scrape failed: %s", e)
    finally:
        if should_close:
            await client.aclose()

    logger.info("Scraped %d MiniMax items", len(items))
    return items


async def fetch_ai_voices(max_per_feed: int = 4) -> list[dict]:
    """Named individual practitioners sharing expertise (source='voices')."""
    cutoff = now_jst() - timedelta(days=NEWSLETTER_RECENCY_DAYS)

    async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True) as client:
        items = await _fetch_feed_items(client, AI_VOICES_FEEDS, "voices", max_per_feed, cutoff)

    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)
    items = items[:15]
    logger.info("Fetched %d AI voices items (recency <= %dd)", len(items), NEWSLETTER_RECENCY_DAYS)
    return items


async def _scrape_anthropic(client=None, max_items: int = 5) -> list[dict]:
    items = []
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True)

    try:
        for label, url in ANTHROPIC_PAGES:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
                cards = re.findall(
                    r'<a[^>]*href="(/(?:research|engineering|news)/[^"]+)"[^>]*>.*?'
                    r'(?:<h[23][^>]*>([^<]+)</h[23]>|class="[^"]*title[^"]*"[^>]*>([^<]+)<)',
                    html, re.DOTALL,
                )
                seen = set()
                for match in cards[:max_items]:
                    path = match[0]
                    title = (match[1] or match[2]).strip()
                    if not title or path in seen:
                        continue
                    seen.add(path)
                    items.append({
                        "source": "labs",
                        "title": title,
                        "url": f"https://www.anthropic.com{path}",
                        "description": title,
                        "stars": None,
                        "language": None,
                        "topics": [label],
                        "published_at": None,
                    })
            except Exception as e:
                logger.warning("Anthropic scrape failed for %s: %s", label, e)
    finally:
        if should_close:
            await client.aclose()

    logger.info("Scraped %d Anthropic items", len(items))
    return items


GITHUB_MODEL_REPOS = [
    ("openai", "openai-python"),
    ("QwenLM", "Qwen3"),
    ("deepseek-ai", "DeepSeek-V3"),
    ("meta-llama", "llama-models"),
    ("google", "gemma_pytorch"),
    ("anthropics", "anthropic-sdk-python"),
    ("mistralai", "mistral-inference"),
    ("vllm-project", "vllm"),
    ("huggingface", "transformers"),
]

# Labs that ship on HuggingFace (no GitHub releases) — track their newest models
# directly by org. (org_id, brand label used for tagging). These are the reputable
# labs whose papers/reports The AI Timeline and similar digests feature.
HF_TRACKED_ORGS = [
    ("zai-org", "GLM"),        # Z.ai / Zhipu — GLM family
    ("MiniMaxAI", "MiniMax"),  # MiniMax family
    ("deepseek-ai", "DeepSeek"),
    ("Qwen", "Qwen"),          # Alibaba Qwen
    ("moonshotai", "Kimi"),    # Moonshot AI — Kimi
]


def _fmt_param_count(model: dict) -> str:
    """Human-readable parameter count from HF safetensors metadata, e.g. '427B
    params'. Returns '' if unavailable. Requires expand[]=safetensors on the
    list query. Giving the LLM the real size prevents it inventing one."""
    total = (model.get("safetensors") or {}).get("total")
    if not total:
        return ""
    if total >= 1_000_000_000:
        return f"{total / 1e9:.0f}B params"
    return f"{total / 1e6:.0f}M params"


async def fetch_model_releases(max_items: int = 8) -> list[dict]:
    items: list[dict] = []
    org_items: list[dict] = []
    cutoff = now_jst() - timedelta(days=7)

    async with httpx.AsyncClient(
        proxy=settings.http_proxy, timeout=30, follow_redirects=True,
    ) as client:
        # --- HuggingFace trending models ---
        try:
            resp = await client.get(
                "https://huggingface.co/api/models",
                params={"sort": "likes7d", "limit": 10, "expand[]": "safetensors"},
            )
            resp.raise_for_status()
            for model in resp.json():
                model_id = model.get("modelId") or model.get("id", "")
                params = _fmt_param_count(model)
                items.append({
                    "source": "model_release",
                    "title": model_id,
                    "url": f"https://huggingface.co/{model_id}",
                    "description": f"{model.get('pipeline_tag', '')}{' · ' + params if params else ''} — {model.get('downloads', 0):,} downloads, {model.get('likes', 0)} likes this week",
                    "stars": model.get("likes"),
                    "language": None,
                    "topics": [model_id.split("/")[0]] if "/" in model_id else ["huggingface"],
                })
        except Exception as e:
            logger.warning("HuggingFace trending fetch failed: %s", e)

        # --- GitHub releases from key repos ---
        headers = {}
        if settings.github_token:
            headers["Authorization"] = f"token {settings.github_token}"

        for owner, repo in GITHUB_MODEL_REPOS:
            try:
                resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/releases",
                    params={"per_page": 3},
                    headers=headers,
                )
                resp.raise_for_status()
                for release in resp.json():
                    published = release.get("published_at", "")
                    try:
                        pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        continue
                    if pub_dt < cutoff:
                        continue
                    tag = release.get("tag_name", "")
                    name = release.get("name") or tag
                    items.append({
                        "source": "model_release",
                        "title": f"{owner}/{repo} {name}",
                        "url": release.get("html_url", ""),
                        "description": (release.get("body") or "")[:500],
                        "stars": None,
                        "language": None,
                        "topics": [owner],
                    })
            except Exception as e:
                logger.warning("GitHub release fetch failed for %s/%s: %s", owner, repo, e)

        # --- Tracked HF labs (GLM / MiniMax) — newest models by org ---
        org_cutoff = now_jst() - timedelta(days=30)
        for org, label in HF_TRACKED_ORGS:
            try:
                resp = await client.get(
                    "https://huggingface.co/api/models",
                    params={"author": org, "sort": "createdAt", "direction": -1, "limit": 5, "expand[]": "safetensors"},
                )
                resp.raise_for_status()
                for model in resp.json():
                    created = model.get("createdAt", "")
                    try:
                        cdt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        cdt = None
                    if cdt and cdt < org_cutoff:
                        continue
                    model_id = model.get("id") or model.get("modelId", "")
                    if not model_id:
                        continue
                    params = _fmt_param_count(model)
                    org_items.append({
                        "source": "model_release",
                        "title": model_id,
                        "url": f"https://huggingface.co/{model_id}",
                        "description": f"{model.get('pipeline_tag', '') or 'model'}{' · ' + params if params else ''} — "
                                       f"{model.get('likes', 0)} likes (new from {label})",
                        "stars": model.get("likes"),
                        "language": None,
                        "topics": [label],
                        "published_at": cdt.isoformat() if cdt else None,
                    })
            except Exception as e:
                logger.warning("HF org fetch failed for %s: %s", org, e)

    # Trending + GitHub capped to max_items; tracked-lab models always included.
    items = items[:max_items] + org_items
    logger.info("Fetched %d model release items", len(items))
    return items


WEB_SEARCH_QUERIES = [
    "new AI model released this week",
    "LLM breakthrough announcement today",
    "new open source AI model 2026",
    "AI research paper trending this week",
    "new AI tool launch developer",
]


async def fetch_web_search_news(max_per_query: int = 3) -> list[dict]:
    items: list[dict] = []
    seen_urls: set[str] = set()

    def _search():
        results = []
        with DDGS(proxy=settings.http_proxy) as ddgs:
            for query in WEB_SEARCH_QUERIES:
                try:
                    hits = list(ddgs.news(query, max_results=max_per_query, timelimit="w"))
                    results.extend(hits)
                except Exception as e:
                    logger.warning("Web search failed for '%s': %s", query, e)
        return results

    import asyncio
    raw_results = await asyncio.to_thread(_search)

    for hit in raw_results:
        url = hit.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append({
            "source": "web_search",
            "title": hit.get("title", ""),
            "url": url,
            "description": hit.get("body", "")[:500],
            "stars": None,
            "language": None,
            "topics": ["web_search"],
            "published_at": hit.get("date"),  # ddgs news returns ISO date
        })

    logger.info("Fetched %d web search items", len(items))
    return items


# --- Article date enrichment + age filter ---------------------------------

ARTICLE_MAX_AGE_DAYS = 180  # ~6 months

# Sources whose items are time-sensitive "articles" and may arrive without a
# date (mainly the Anthropic/MiniMax scrapers). Structured sources (arxiv,
# hf_papers, github, model_release) are recent by construction, so we never
# spend a web request probing their dates.
_DATE_PROBE_SOURCES = {"labs", "newsletter", "voices", "web_search"}

# Publication-date patterns, most reliable first. All capture an ISO-ish date.
_DATE_META_PATTERNS = [
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|article:published|datePublished|og:published_time|og:article:published_time)["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:article:published_time|datePublished|og:published_time)["\']', re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I),
]


def _parse_iso_loose(value: str | None) -> datetime | None:
    """Parse an ISO-ish date string to a tz-aware datetime (assume UTC if no tz)."""
    if not value:
        return None
    s = value.strip().replace("Z", "+00:00")
    # Try full ISO, then a bare YYYY-MM-DD prefix.
    for candidate in (s, s[:10]):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_date_from_html(html: str) -> datetime | None:
    for pat in _DATE_META_PATTERNS:
        m = pat.search(html)
        if m:
            dt = _parse_iso_loose(m.group(1))
            if dt:
                return dt
    return None


async def filter_articles_by_age(items: list[dict], max_age_days: int = ARTICLE_MAX_AGE_DAYS) -> list[dict]:
    """Drop articles older than `max_age_days`. Items already carrying a
    `published_at` are filtered directly; date-less items from article sources
    are probed by fetching the page and reading its publication-date metadata.
    Items whose date cannot be determined are KEPT (we never drop on a guess)."""
    cutoff = now_jst() - timedelta(days=max_age_days)

    # Items needing a web probe: no date yet, article-type source, http(s) URL.
    to_probe = [
        it for it in items
        if not it.get("published_at")
        and it.get("source") in _DATE_PROBE_SOURCES
        and str(it.get("url", "")).startswith("http")
    ]

    if to_probe:
        async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=12, follow_redirects=True) as client:
            async def _probe(it):
                try:
                    resp = await client.get(it["url"])
                    resp.raise_for_status()
                    dt = _extract_date_from_html(resp.text)
                    if dt:
                        it["published_at"] = dt.isoformat()
                except Exception as e:
                    logger.debug("Date probe failed for %s: %s", it.get("url"), e)
            await asyncio.gather(*(_probe(it) for it in to_probe))

    kept, dropped = [], 0
    for it in items:
        dt = _parse_iso_loose(it.get("published_at"))
        if dt is not None and dt < cutoff:
            dropped += 1
            continue
        kept.append(it)

    if dropped:
        logger.info("Age filter: dropped %d article(s) older than %d days", dropped, max_age_days)
    return kept
