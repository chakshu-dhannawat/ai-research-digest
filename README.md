# AI Engineer Daily Digest

A self-hosted newsletter system that fetches AI content daily, scores it with an LLM, and emails a curated digest to subscribers every weekday morning at **08:00 JST**.

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url>
cd ai-newsletter
cp backend/.env.example backend/.env
```

Edit `backend/.env` with your own credentials:

| Variable | Purpose |
|----------|---------|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | LLM endpoint for scoring & summarization |
| `LLM_FALLBACK_BASE_URL` / `LLM_FALLBACK_MODEL` | Fallback LLM endpoint |
| `GITHUB_TOKEN` | GitHub personal access token for repo search |
| `SMTP_HOST` / `SMTP_PORT` | Outgoing SMTP relay |
| `SENDER_EMAIL` / `DEFAULT_RECIPIENTS` | Sender address and default subscriber list |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams incoming webhook (optional) |
| `HTTP_PROXY` / `HTTPS_PROXY` | Corporate proxy if needed (can be left empty) |

> **Note:** `backend/.env` is git-ignored. Never commit it.

### 2. Start the stack

```bash
docker compose up -d
```

### 3. Verify

```bash
curl http://localhost:8585/api/health
```

Expected: `{"status":"ok"}`

| Service  | Local URL              | Purpose              |
|----------|------------------------|----------------------|
| Frontend | http://localhost:3737  | Admin / explore UI   |
| Backend  | http://localhost:8585  | FastAPI + scheduler  |
| Database | localhost:5435         | PostgreSQL           |

### 4. Trigger a test run (dry-run, no emails sent)

```bash
curl -X POST http://localhost:8585/api/pipeline/preview
```

Artifacts are written to `dryrun_output/` for review.

### 5. Trigger a real send (optional)

```bash
curl -X POST http://localhost:8585/api/pipeline/send-now
```

## What It Does

1. Every weekday morning at **07:50 JST** a cron job fires.
2. Fetches content from 7 source categories: GitHub repos, HuggingFace trending papers, AI lab blogs, practitioner voices, AI news outlets, model releases, and web search news.
3. Scores every item 0–10 with the configured LLM, then writes a summary and an application note.
4. Deduplicates against items sent in the last 14 days.
5. Emails the top 10 items to active subscribers — English digest to EN subscribers, Japanese translation to JA subscribers.
6. Posts the English digest to the configured Microsoft Teams channel.
7. Persists all scored items to a searchable catalog in the frontend Explore page.

## Documentation

| File | What it covers |
|------|----------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, services, tech stack |
| [docs/PIPELINE.md](docs/PIPELINE.md) | End-to-end data flow per run |
| [docs/SOURCES.md](docs/SOURCES.md) | All content sources and scoring rubric |
| [docs/CRAWLER.md](docs/CRAWLER.md) | Search algorithm, crawler strategy, and how to add sources |
| [docs/DATABASE.md](docs/DATABASE.md) | DB schema — all tables and columns |
| [docs/API.md](docs/API.md) | All REST endpoints |
| [docs/CRON.md](docs/CRON.md) | Scheduler setup and how to change the time |
| [docs/FRONTEND.md](docs/FRONTEND.md) | UI panels and features |
| [docs/FOLDER_STRUCTURE.md](docs/FOLDER_STRUCTURE.md) | Repository layout |

## Common Tasks

### Add a new RSS source

Open `backend/app/services/news_fetcher.py`, find the feed list for the right category (`AI_NEWSLETTER_FEEDS`, `AI_VOICES_FEEDS`, or `AI_LABS_FEEDS`), and add a tuple:

```python
("Source Name", "https://example.com/feed.xml"),
```

See [docs/CRAWLER.md](docs/CRAWLER.md) for the full guide.

### Change the send time

Edit `CRON_HOUR` and `CRON_MINUTE` in `backend/.env`, then restart the backend container.

### Disable a source

Set the source minimum to 0 in `backend/app/services/pipeline.py` (`_SOURCE_MINIMUMS`), or remove its feed entries from `news_fetcher.py`.

## Development

```bash
# Rebuild after code changes
docker compose up -d --build backend

# View backend logs
docker compose logs -f backend

# Run a Python script inside the container
docker compose exec backend python3 - <<'PY'
import asyncio
from app.services.pipeline import run_pipeline
asyncio.run(run_pipeline(dry_run=True))
PY
```

## License

Internal use at Otsuka Shokai.
