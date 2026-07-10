# AI Engineer Daily Digest

A self-hosted newsletter system that fetches AI content daily, scores it with an LLM, and emails a curated digest to subscribers every morning at **08:00 JST**.

## Quick Start

```bash
cd ai-newsletter
docker compose up -d
```

| Service  | URL                        | Purpose              |
|----------|----------------------------|----------------------|
| Frontend | http://iitgpu07:3737       | Admin UI             |
| Backend  | http://iitgpu07:8585       | FastAPI + scheduler  |
| Database | iitgpu07:5435              | PostgreSQL (pgdata)  |

## What It Does

1. Every morning at **07:50 JST** a cron job fires
2. Fetches content from 8 source categories (GitHub, arXiv, HF Papers, labs, voices, newsletters, model releases, web)
3. Scores every item 0–10 with the Why-LLM model, writes summaries and application notes
4. Deduplicates against items sent in the last 14 days
5. Emails the top 10 items to all active subscribers — English digest to EN subscribers, Japanese translation to JA subscribers
6. Persists all scored items to a searchable catalog (Explore page)

## Documentation

| File | What it covers |
|------|----------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram, services, tech stack |
| [docs/PIPELINE.md](docs/PIPELINE.md) | End-to-end data flow per run |
| [docs/SOURCES.md](docs/SOURCES.md) | All content sources and scoring rubric |
| [docs/DATABASE.md](docs/DATABASE.md) | DB schema — all tables and columns |
| [docs/API.md](docs/API.md) | All REST endpoints |
| [docs/CRON.md](docs/CRON.md) | Scheduler setup and how to change the time |
| [docs/FRONTEND.md](docs/FRONTEND.md) | UI panels and features |
| [docs/PERSONALIZATION.md](docs/PERSONALIZATION.md) | Design: per-article 👍/👎 feedback + per-user re-ranking (not yet built) |
| [docs/AGENTIC_PATTERNS.md](docs/AGENTIC_PATTERNS.md) | Agentic vs pipeline patterns — what the LLM actually does |
| [docs/FASTAPI_PATTERNS.md](docs/FASTAPI_PATTERNS.md) | Advanced FastAPI patterns used in this project |
| [docs/ASYNC_SYNC.md](docs/ASYNC_SYNC.md) | When to use async vs sync — decision guide with examples |
| [docs/PYTHON_MODULES.md](docs/PYTHON_MODULES.md) | Python packages, `__init__.py`, and import rules |
| [MODEL_COMPARISON.md](MODEL_COMPARISON.md) | Why-LLM vs MiMo-V2.5 benchmark |
| [SUBSCRIBERS.md](SUBSCRIBERS.md) | Active subscriber list with language preference |
