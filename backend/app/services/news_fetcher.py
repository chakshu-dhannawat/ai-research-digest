import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
from duckduckgo_search import DDGS

from app.config import settings
from app.utils import now_jst
from app.services.date_extractor import parse_any_date, enrich_and_filter_by_age

logger = logging.getLogger(__name__)

async def fetch_hf_papers(max_per_day: int = 5, populated_days: int = 1, lookback_days: int = 6, max_days_total: int | None = None) -> list[dict]:
    """HuggingFace Daily Papers.

    `max_days_total` is a hard ceiling used during refill passes to avoid
    unbounded lookback while still satisfying minimum-item targets."""
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
    effective_lookback = min(lookback_days, max_days_total) if max_days_total is not None else lookback_days

    seen_ids: set[str] = set()
    days_with_papers = 0
    async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        for back in range(effective_lookback + 1):
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
    return parse_any_date(raw)

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


async def fetch_ai_labs(max_per_feed: int = 4, anthropic_max_items: int = 5, minimax_max_items: int = 6) -> list[dict]:
    """Official AI lab / research-org blogs & technical reports (source='labs').
    Includes the Anthropic and MiniMax scrapers."""
    cutoff = now_jst() - timedelta(days=NEWSLETTER_RECENCY_DAYS)

    async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        items = await _fetch_feed_items(client, AI_LABS_FEEDS, "labs", max_per_feed, cutoff)

    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)
    items = items[:15]

    items.extend(await _scrape_anthropic(client=None, max_items=anthropic_max_items))
    items.extend(await _scrape_minimax(max_items=minimax_max_items))

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
        today_iso = now_jst().isoformat()
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
                "_recent_fallback": today_iso,
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
    """Scrape Anthropic listing pages.

    Items are returned WITHOUT a forced recent-fallback date. The pipeline's
    date extractor will probe each article page for a real publication date;
    articles whose date cannot be determined are dropped. This prevents old
    evergreen posts from appearing as today's news.
    """
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


async def fetch_model_releases(
    max_items: int = 8,
    hf_trending_limit: int = 10,
    gh_releases_per_page: int = 3,
    org_limit: int = 5,
    org_cutoff_days: int = 14,
) -> list[dict]:
    items: list[dict] = []
    org_items: list[dict] = []
    cutoff = now_jst() - timedelta(days=7)

    async with httpx.AsyncClient(
        proxy=settings.http_proxy, timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True,
    ) as client:
        # --- HuggingFace trending models ---
        try:
            resp = await client.get(
                "https://huggingface.co/api/models",
                params={"sort": "likes7d", "limit": hf_trending_limit, "expand[]": ["safetensors", "createdAt"]},
            )
            resp.raise_for_status()
            for model in resp.json():
                model_id = model.get("modelId") or model.get("id", "")
                params = _fmt_param_count(model)
                created = model.get("createdAt", "")
                cdt = parse_any_date(created)
                # The digest is about *new* releases; an old model that happens to
                # trend this week is not a release announcement.
                if cdt is None or cdt < cutoff:
                    continue
                items.append({
                    "source": "model_release",
                    "title": model_id,
                    "url": f"https://huggingface.co/{model_id}",
                    "description": f"{model.get('pipeline_tag', '')}{' · ' + params if params else ''} — {model.get('downloads', 0):,} downloads, {model.get('likes', 0)} likes this week",
                    "stars": model.get("likes"),
                    "language": None,
                    "topics": [model_id.split("/")[0]] if "/" in model_id else ["huggingface"],
                    "published_at": cdt.isoformat() if cdt else None,
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
                    params={"per_page": gh_releases_per_page},
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
                        "published_at": pub_dt.isoformat(),
                    })
            except Exception as e:
                logger.warning("GitHub release fetch failed for %s/%s: %s", owner, repo, e)

        # --- Tracked HF labs (GLM / MiniMax) — newest models by org ---
        org_cutoff = now_jst() - timedelta(days=org_cutoff_days)
        for org, label in HF_TRACKED_ORGS:
            try:
                resp = await client.get(
                    "https://huggingface.co/api/models",
                    params={"author": org, "sort": "createdAt", "direction": -1, "limit": org_limit, "expand[]": ["safetensors", "createdAt"]},
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


# Focused query set to reduce DuckDuckGo rate-limit risk while still catching
# the two biggest categories: new models/tools and research/announcements.
WEB_SEARCH_QUERIES = [
    "new AI model released this week",
    "LLM breakthrough announcement",
    "new open source AI tool developer",
]


async def fetch_web_search_news(max_per_query: int = 3, timelimit: str = "w") -> list[dict]:
    items: list[dict] = []
    seen_urls: set[str] = set()

    def _search():
        results = []
        with DDGS(proxy=settings.http_proxy) as ddgs:
            for query in WEB_SEARCH_QUERIES:
                try:
                    hits = list(ddgs.news(query, max_results=max_per_query, timelimit=timelimit))
                    results.extend(hits)
                except Exception as e:
                    logger.warning("Web search failed for '%s': %s", query, e)
                # DuckDuckGo throttles rapid sequential queries; spacing them out
                # dramatically reduces 403 rate-limit errors.
                time.sleep(1.5)
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


# --- Article date enrichment + age filter (delegated to date_extractor) ---


async def filter_articles_by_age(items: list[dict], max_age_days: int | None = None, llm_client=None, llm_model: str | None = None) -> list[dict]:
    """Drop articles older than `max_age_days` using manual extraction plus
    optional LLM fallback. Items whose date cannot be determined are dropped."""
    return await enrich_and_filter_by_age(
        items,
        llm_client=llm_client,
        llm_model=llm_model,
        max_age_days=max_age_days,
    )
