# Search Algorithm & Crawler Design

This document explains how content is discovered, how the search algorithm balances freshness with quality, and how to add or remove sources.

## Overview

The pipeline runs multiple independent crawlers in parallel. Each crawler returns a list of candidate items with a common schema:

```python
{
    "source": "github",          # source category
    "title": "...",
    "url": "...",
    "description": "...",
    "stars": 123,                # optional
    "language": "Python",        # optional
    "topics": ["tag1", "tag2"],  # feed or topic labels
    "published_at": "2026-09-01T00:00:00+00:00",
}
```

After fetching, all candidates are:
1. Deduplicated by URL.
2. Filtered by age (`MAX_ARTICLE_AGE_DAYS`, default 45 days).
3. Filtered against items already sent in the last 14 days.
4. Capped to a soft ceiling of 100 items before scoring.
5. Scored 0–10 and summarized by the configured LLM.
6. Selected into a diverse top-10 digest.

## Crawler-by-Crawler Algorithm

### GitHub (`github_crawler.py`)

**Goal:** Surface brand-new and recently-active AI repositories that the engineering team has not seen before.

**Problem with a naive approach:**
- Searching `created:>7_days_ago sort=stars` returns the same high-star repos every day. The 14-day dedup filter removes them after the first send, leaving 0 repos on subsequent days.
- Searching only `created:>yesterday` fails at the 07:50 JST production run because only ~8 hours of the current UTC day have elapsed.

**Solution:** Three complementary searches per topic, all sorted by **recency** instead of stars:

| Query | Window | Sort | Purpose |
|-------|--------|------|---------|
| `created:>3_days_ago stars:>3` | 3 days | `created desc` | Very fresh repos, newest first |
| `created:>7_days_ago stars:>5` | 7 days | `created desc` | Weekly cycle of new repos |
| `pushed:>3_days_ago created:>30_days_ago stars:10..5000` | 3 days pushed / 30 days created | `updated desc` | Repos gaining activity this week |

**Enrichment:** Each repo's README is fetched and truncated to 3000 characters. The README snippet is given to the LLM scorer as extra context.

### HuggingFace Daily Papers (`fetch_hf_papers`)

**Goal:** Surface community-curated, highly-upvoted papers.

**Algorithm:**
- Scan backward day-by-day from today.
- Stop after `populated_days` (1 on normal days, 3 on Monday to catch the weekend).
- From each populated day, keep the top 5 papers by upvotes.
- Dedupe by arXiv ID.

### RSS Categories (`fetch_ai_newsletters`, `fetch_ai_voices`, `fetch_ai_labs`)

**Shared algorithm (`_fetch_rss_category`):**
1. Parse each feed with `xml.etree.ElementTree` (handles RSS 2.0 `<item>` and Atom `<entry>`).
2. Extract title, link, description, and publication date.
3. Drop items older than `NEWSLETTER_RECENCY_DAYS` (14 days).
4. Sort newest-first across all feeds in the category.
5. Cap to the category limit (newsletter 20, labs 15, voices 15).

**Scrapers in `labs`:** Anthropic and MiniMax have no reliable RSS feeds, so their listing pages are scraped with regex and passed through the date extractor.

### Model Releases (`fetch_model_releases`)

Three signals:
1. **HF trending** — `sort=likes7d`, keep only models created in the last 7 days.
2. **GitHub releases** — monitor releases from major model/tooling repos, keep only those published in the last 7 days.
3. **Tracked HF orgs** — newest models from GLM, MiniMax, DeepSeek, Qwen, and Kimi, filtered by a 14-day creation window.

### Web Search (`fetch_web_search_news`)

**Source:** Google News RSS (replaced DuckDuckGo because of consistent 403 rate limits).

**Queries:**
- `new AI model released`
- `LLM breakthrough announcement`
- `new open source AI tool developer`

Items are deduped by URL and merged into the AI News & Blogs section.

## Source Diversity Selection

After scoring, the top-10 selector (`_select_top_diverse` in `pipeline.py`) guarantees:
- Every source with at least one eligible item (score ≥ `MIN_DIGEST_SCORE` = 4) gets at least one slot.
- No single source can occupy more than 3 slots.
- Remaining slots are filled by descending score.

If fewer than `MIN_DIGEST_ITEMS` = 7 items clear the score floor, the pipeline backfills with the next-best scored items.

## How to Add a New Source

### Option A: Add an RSS feed

Open `backend/app/services/news_fetcher.py` and add a tuple to the appropriate list:

```python
# For company/product blogs or news outlets
AI_NEWSLETTER_FEEDS = [
    ...
    ("Example Blog", "https://example.com/rss.xml"),
]

# For individual practitioner blogs
AI_VOICES_FEEDS = [
    ...
    ("Author Name", "https://author.example.com/feed.xml"),
]

# For official lab / tooling blogs
AI_LABS_FEEDS = [
    ...
    ("Lab Name", "https://lab.example.com/blog/feed.xml"),
]
```

Restart the backend:

```bash
docker compose up -d --build backend
```

Trigger a dry-run to verify the feed works:

```bash
curl -X POST http://localhost:8585/api/pipeline/preview
```

Check `dryrun_output/*_candidates.json` to see items from the new feed.

### Option B: Add a custom crawler

If the source has no RSS feed, add a new async function in `backend/app/services/news_fetcher.py` (or a new module) that returns a list of candidate dicts. Then wire it into `backend/app/services/pipeline.py`:

```python
"my_source": _safe_fetch("my_source", my_custom_fetcher()),
```

Add a minimum target in `_SOURCE_MINIMUMS` if you want the pipeline to refill when the source is empty:

```python
_SOURCE_MINIMUMS = {
    ...
    "my_source": 3,
}
```

### Option C: Remove a source

Delete its feed entries or remove the fetcher call from `pipeline.py`. Also remove it from `_SOURCE_MINIMUMS` if present.

## How to Tune Search Parameters

| Parameter | Location | Effect |
|-----------|----------|--------|
| `NEWSLETTER_RECENCY_DAYS` | `news_fetcher.py` | How many days of RSS history to keep |
| `MAX_ARTICLE_AGE_DAYS` | `backend/.env` | Hard age cutoff for all candidates |
| `_MAX_PRESCORE_ITEMS` | `pipeline.py` | Soft ceiling on candidates before scoring |
| `_SOURCE_MINIMUMS` | `pipeline.py` | Minimum items to fetch per source; triggers refill |
| `MIN_DIGEST_SCORE` | `pipeline.py` | Score floor for the final digest |
| GitHub `max_per_query` | `pipeline.py` | Repos fetched per sub-query |
| GitHub query windows | `github_crawler.py` | How far back to search |

## Monitoring Crawler Health

Each crawler logs a summary line:

```text
INFO:app.services.github_crawler:Found 24 unique repos across all queries
INFO:app.services.news_fetcher:Fetched 30 AI labs items (recency <= 14d)
INFO:app.services.pipeline:Candidate pool: 97 items {'github': 24, ...}
```

Watch for:
- `Found 0 unique repos across all queries` — GitHub window may be too narrow.
- High `below score X dropped from send` — candidates are low quality or off-topic.
- `Diverse top-10 selection returned N items; digest may be thin today` — not enough sources produced eligible items.
