# Folder Structure

```
ai-newsletter/
├── compose.yml                  # Docker Compose — 3 services: db, backend, frontend
├── README.md                    # Quick start + doc index
│
├── docs/                        # Documentation
│   ├── ARCHITECTURE.md          # System diagram, tech stack
│   ├── PIPELINE.md              # End-to-end data flow
│   ├── CRON.md                  # Scheduler setup
│   ├── SOURCES.md               # All content sources + scoring rubric
│   ├── DATABASE.md              # DB schema + useful queries
│   ├── API.md                   # REST endpoints
│   ├── FRONTEND.md              # UI panels + features
│   └── FOLDER_STRUCTURE.md     # This file
│
├── SUBSCRIBERS.md               # Active subscriber list with languages
├── MODEL_COMPARISON.md          # Why-LLM vs MiMo-V2.5 benchmark
│
├── db/
│   └── init.sql                 # Initial schema (runs once on DB creation)
│
├── backend/
│   ├── Dockerfile               # python:3.12-slim, runs uvicorn
│   ├── requirements.txt         # Python dependencies
│   ├── .env                     # Secrets + config (not committed)
│   └── app/
│       ├── main.py              # FastAPI app + APScheduler lifespan
│       ├── config.py            # Pydantic Settings (reads .env)
│       ├── database.py          # asyncpg pool + schema migrations
│       ├── models/
│       │   └── schemas.py       # Pydantic request/response models
│       ├── routers/
│       │   └── api.py           # All REST endpoints
│       ├── services/
│       │   ├── pipeline.py      # Main orchestration: fetch→dedup→score→send
│       │   ├── github_crawler.py # GitHub trending repo search + enrichment
│       │   ├── news_fetcher.py  # All other sources: HF papers, arXiv, RSS, scraping
│       │   ├── llm_summarizer.py # LLM scoring, translation, keyword extraction
│       │   ├── dedup.py         # Hash-based dedup with 14-day window
│       │   └── email_sender.py  # Jinja2 render + SMTP send
│       └── templates/
│           └── newsletter.html  # Email HTML template (Jinja2)
│
└── frontend/
    ├── Dockerfile               # nginx:alpine, serves built SPA on :3737
    ├── nginx.conf               # Proxy /api/ → backend:8585
    ├── package.json             # React + Vite deps
    ├── vite.config.js           # Build config
    ├── index.html               # HTML shell
    └── src/
        ├── main.jsx             # React entry point
        ├── App.jsx              # All UI: tabs, panels, components
        ├── index.css            # All styles (no CSS framework)
        └── api/
            └── client.js        # Typed fetch wrappers for every endpoint
```

## Key Config: `backend/.env`

```
LLM_BASE_URL=http://macdep01.tdc.otsuka-shokai.co.jp:8001/v1
LLM_MODEL=Why-LLM
ANTHROPIC_FOUNDRY_BASE_URL=http://macdep01.tdc.otsuka-shokai.co.jp:8008/
FOUNDRY_MODEL=anthropic-MiMo-V2.5   # ad-hoc test sends only
SMTP_HOST=mta-fm21.otsuka-shokai.co.jp
CRON_HOUR=7
CRON_MINUTE=50
DEDUP_WINDOW_DAYS=14
TOP_N_ITEMS=10
GITHUB_TOKEN=...
```

## Common Commands

```bash
# Start everything
docker compose up -d

# View backend logs (scheduler, pipeline, emails)
docker compose logs backend -f

# Restart backend only (e.g. after config/code change)
docker compose restart backend

# Connect to DB directly
psql -h iitgpu07.hon.otsuka-shokai.co.jp -p 5435 -U newsletter -d newsletter

# Rebuild frontend after code change
docker compose build frontend && docker compose up -d frontend
```
