# Architecture

## System Diagram

```
                        ┌─────────────────────────────────────────┐
                        │          Docker Compose (iitgpu07)      │
                        │                                         │
  Browser ──:3737──►  │  frontend (nginx:alpine)                │
                        │    React + Vite SPA                     │
                        │           │ API calls                   │
                        │           ▼                             │
  Admin / API ──:8585──►│  backend (python:3.12-slim)            │
                        │    FastAPI + APScheduler                │
                        │    uvicorn :8585                        │
                        │           │ asyncpg                     │
                        │           ▼                             │
                        │  db (postgres:16-alpine)               │
                        │    exposed :5435 on host                │
                        │    volume: pgdata (persistent)          │
                        └─────────────────────────────────────────┘

  External dependencies (accessed via corporate proxy):
    macdep01:8001/v1   ──  Why-LLM (scoring, vLLM)
    macdep01:8008/v1   ──  MiMo-V2.5 via LiteLLM (ad-hoc test sends only)
    mta-fm21:25        ──  SMTP relay (no auth, no TLS)
    api.github.com     ──  GitHub trending repos
    huggingface.co     ──  HF Daily Papers API
    arxiv.org          ──  arXiv RSS
    various RSS feeds  ──  labs, voices, newsletters
    duckduckgo         ──  web search news fallback
```

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Container runtime | Docker Compose | Single-host, easy restart |
| Backend framework | FastAPI (Python 3.12) | Async, fast, auto-docs |
| Scheduler | APScheduler 3.x (`AsyncIOScheduler`) | In-process cron, no extra service |
| DB driver | asyncpg | Native async Postgres |
| Database | PostgreSQL 16 | JSONB + GIN indexes for array search |
| LLM client | openai SDK (pointed at vLLM) | Compatible with any OpenAI-compatible endpoint |
| HTTP client | httpx | Async HTTP, proxy support |
| Email | smtplib (stdlib) | Plain SMTP, no auth |
| Frontend | React + Vite | iPhone-first SPA |
| Serving frontend | nginx:alpine | Static files + reverse proxy |
| GitHub crawling | PyGithub | REST v3 search |
| HTML templates | Jinja2 | Newsletter HTML rendering |

## Proxy

All outbound HTTP from the backend container goes through:
```
http://proxy.otsuka-shokai.co.jp:8080
```
Internal hosts (DB, LLM, SMTP) are in `NO_PROXY` and bypass the proxy.
