# FastAPI Advanced Patterns — Learn from This Codebase

This file explains the advanced FastAPI patterns used in this project, with the actual code as examples.

---

## 1. Lifespan — Startup & Shutdown Logic

**File:** `backend/app/main.py`

### The Old Way (deprecated)
```python
@app.on_event("startup")
async def startup():
    ...

@app.on_event("shutdown")
async def shutdown():
    ...
```
This is deprecated in FastAPI 0.93+.

### The New Way — `@asynccontextmanager`
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP: everything before `yield` runs once when the server starts ---
    await get_pool()           # open DB connection pool
    scheduler.start()          # start the cron scheduler
    logger.info("Ready")

    yield                      # ← server runs here, handling requests

    # --- SHUTDOWN: everything after `yield` runs when the server stops ---
    scheduler.shutdown()
    await close_pool()

app = FastAPI(lifespan=lifespan)
```

**Why it matters:**
- The `yield` is the dividing line: before = startup, after = shutdown
- Startup runs before any request is accepted
- Shutdown runs after the last request completes (graceful)
- It's a single function — easier to reason about than two separate hooks
- Uses the standard Python `contextlib` pattern, not a FastAPI-specific API

**In this project:**
1. DB connection pool is opened (before any request could need it)
2. APScheduler is started (cron job registered and ready)
3. On shutdown — scheduler stops, DB pool closes cleanly

---

## 2. APIRouter — Splitting Routes Across Files

**Files:** `backend/app/routers/api.py`, `backend/app/main.py`

Without a router, all routes go in `main.py` — messy for large apps.

### In the router file (`api.py`)
```python
from fastapi import APIRouter

router = APIRouter(prefix="/api")   # all routes get /api prefixed automatically

@router.get("/newsletters")         # actual path: GET /api/newsletters
async def list_newsletters():
    ...

@router.post("/subscribe")          # actual path: POST /api/subscribe
async def subscribe(req: SubscribeRequest):
    ...
```

### In `main.py`
```python
from app.routers.api import router as api_router

app = FastAPI(lifespan=lifespan)
app.include_router(api_router)      # registers all routes from the router
```

**Why it matters:**
- `prefix="/api"` is set once on the router — you never repeat `/api` in every route
- You can have multiple routers (e.g. `router_admin`, `router_public`) each with their own prefix, tags, and dependencies
- `include_router` can also add a prefix again: `app.include_router(router, prefix="/v2")` — useful for versioning

---

## 3. Pydantic Models — Request & Response Validation

**File:** `backend/app/models/schemas.py`

FastAPI uses Pydantic v2 for automatic validation, serialization, and docs generation.

### Request body
```python
class SubscribeRequest(BaseModel):
    email: str
    language: str = "en"        # default value — field is optional in the request

@router.post("/subscribe")
async def subscribe(req: SubscribeRequest):  # FastAPI auto-parses JSON body into req
    print(req.email, req.language)
```
If the request body is missing `email`, FastAPI returns a 422 Unprocessable Entity automatically — no manual validation needed.

### Response model
```python
class NewsletterOut(BaseModel):
    id: int
    sent_at: datetime
    subject: str
    recipient_emails: list[str]
    item_count: int
    status: str
    error_message: str | None = None   # nullable field
    is_test: bool = False

@router.get("/newsletters", response_model=list[NewsletterOut])
async def list_newsletters():
    rows = await conn.fetch("SELECT ...")
    return [NewsletterOut(**dict(r)) for r in rows]
```

**What `response_model` does:**
- Validates the response data before sending
- Strips any extra fields (security: accidentally added internal data won't leak)
- Generates the correct schema in `/docs` (Swagger UI)
- `list[NewsletterOut]` means the response is a JSON array of these objects

### Union types (Python 3.10+ syntax)
```python
error_message: str | None = None    # same as Optional[str] = None
finished_at: datetime | None        # required but nullable
```

---

## 4. Query Parameters — Automatic Parsing

**File:** `backend/app/routers/api.py`

Function parameters that are NOT in the path and NOT a Pydantic model are automatically treated as **query parameters**.

```python
@router.get("/newsletters")
async def list_newsletters(limit: int = 30, include_test: bool = False):
    # GET /api/newsletters              → limit=30, include_test=False
    # GET /api/newsletters?limit=5      → limit=5,  include_test=False
    # GET /api/newsletters?include_test=true → limit=30, include_test=True
    ...
```

FastAPI auto-coerces types: `?limit=5` arrives as a string `"5"` in HTTP but FastAPI converts it to `int` for you. If `?limit=abc` is sent, it returns a 422 automatically.

For the search endpoint with many filters:
```python
@router.get("/items")
async def search_items(
    q: str = "",
    source: str = "",
    keyword: str = "",
    min_score: float = 0,
    date_from: str = "",
    date_to: str = "",
    limit: int = 60,
    offset: int = 0,
):
```
Every parameter here is an optional query param with a default. The URL looks like:
`GET /api/items?q=rag&source=arxiv&min_score=7&limit=10`

---

## 5. HTTPException — Returning Error Responses

```python
from fastapi import HTTPException

@router.post("/pipeline/run")
async def trigger_pipeline():
    if _running_task and not _running_task.done():
        raise HTTPException(400, "Pipeline already running")
    ...
```

`raise HTTPException(status_code, detail)` immediately stops the handler and returns:
```json
HTTP 400
{"detail": "Pipeline already running"}
```

This is idiomatic FastAPI — you raise, not return an error. Common codes used here:
- `400` Bad Request (invalid state)
- `404` Not Found
- `422` Unprocessable Entity (Pydantic auto-raises this on bad input)

---

## 6. `asyncio.create_task` — Fire-and-Forget Background Work

**File:** `backend/app/routers/api.py`

```python
_running_task: asyncio.Task | None = None

@router.post("/pipeline/send-now")
async def send_now(req: InstantSendRequest):
    global _running_task
    if _running_task and not _running_task.done():
        raise HTTPException(400, "Pipeline already running")

    _running_task = asyncio.create_task(run_pipeline(recipients=req.recipients, is_test=True))
    await asyncio.sleep(0.5)           # brief wait to let it start
    return PipelineStatus(run_id=0, status="started")
```

**What's happening:**
- `asyncio.create_task(coro)` schedules the coroutine to run in the background on the event loop
- The HTTP request **returns immediately** with `{"status": "started"}` — it does NOT wait for the pipeline to finish (which takes ~4 minutes)
- The task runs concurrently with incoming requests
- `_running_task` stored at module level acts as a simple mutex — prevents double-triggering
- `task.done()` returns `True` when the coroutine finishes or raises an exception

**Contrast with `await`:**
```python
await run_pipeline(...)        # caller WAITS — HTTP request hangs for 4 minutes
asyncio.create_task(...)       # caller returns immediately — pipeline runs in background
```

---

## 7. `asyncio.to_thread` — Running Sync Code Without Blocking

**File:** `backend/app/services/pipeline.py`

```python
github_items = await asyncio.to_thread(fetch_trending_repos)
scored = await asyncio.to_thread(score_and_summarize, all_items)
```

**The problem:** FastAPI runs on a single-threaded async event loop. If you call a blocking (synchronous) function directly — like PyGithub's REST calls or the OpenAI SDK — it blocks the entire server. No other requests can be handled while it runs.

**The solution:** `asyncio.to_thread(func, *args)` runs the function in a thread pool executor. The event loop is free to handle other requests while the thread runs. `await` gets the result back when done.

Use this whenever you call:
- Synchronous HTTP libraries (requests, PyGithub)
- The `openai` SDK (it's sync)
- Any CPU-bound or blocking I/O code in an async context

---

## 8. CORSMiddleware — Allowing Frontend Requests

**File:** `backend/app/main.py`

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # allow any origin (frontend on :3737, browser, etc.)
    allow_methods=["*"],     # GET, POST, DELETE, etc.
    allow_headers=["*"],
)
```

Without this, browsers block requests from `http://iitgpu07:3737` to `http://iitgpu07:8585` (different ports = different origin). The middleware adds the required `Access-Control-Allow-*` headers to responses.

`allow_origins=["*"]` is fine for internal tools. For public APIs, restrict to your actual domain: `["https://yourapp.com"]`.

---

## 9. Dependency Injection via DB Pool

This project uses a simple module-level singleton instead of FastAPI's `Depends()` system, but it's worth knowing both patterns.

### Pattern used here (module singleton)
```python
# database.py
pool: asyncpg.Pool | None = None

async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(...)
    return pool
```
```python
# in a route
pool = await get_pool()
async with pool.acquire() as conn:
    rows = await conn.fetch("SELECT ...")
```
Simple. The pool is created once and reused. Works well for a single-service app.

### The FastAPI `Depends()` pattern (for reference)
```python
async def get_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn               # conn is available to the route
        # cleanup happens here after the request ends

@router.get("/items")
async def list_items(conn = Depends(get_db)):   # FastAPI injects conn
    return await conn.fetch("SELECT ...")
```
`Depends()` is powerful for auth, DB sessions, and shared logic — but adds complexity. The singleton approach here is simpler and fine for an internal app.

---

## 10. Pydantic Settings — Config from `.env`

**File:** `backend/app/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    db_host: str = "db"
    cron_hour: int = 7               # default value
    llm_model: str = "Why-LLM"

    class Config:
        env_file = ".env"            # load from .env automatically

settings = Settings()                # singleton — import this everywhere
```

**How it works:**
- Pydantic reads `.env` file and environment variables
- Environment variables override `.env` values (Docker `environment:` block wins)
- Type coercion is automatic: `CRON_HOUR=7` (string in .env) → `int` in code
- `settings` is imported at module level — it's evaluated once at startup

Access anywhere:
```python
from app.config import settings

print(settings.cron_hour)   # 7
print(settings.llm_model)   # "Why-LLM"
```

---

## 11. APScheduler — In-Process Cron Jobs

**File:** `backend/app/main.py`

APScheduler lets you run scheduled jobs inside the same Python process as FastAPI — no external cron daemon, no Celery, no Redis queue needed.

### The Three Pieces

**1. Create the scheduler** (module level, before the app)
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
```
`AsyncIOScheduler` integrates with asyncio's event loop — your job functions can be `async def` and use `await` normally.

**2. Register jobs and start inside lifespan**
```python
from apscheduler.triggers.cron import CronTrigger

@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()

    scheduler.add_job(
        scheduled_pipeline,              # the function to call
        CronTrigger(
            hour=settings.cron_hour,     # 7
            minute=settings.cron_minute, # 50
            timezone="Asia/Tokyo",       # JST — critical for correct fire time
        ),
        id="daily_newsletter",           # unique ID — lets you replace/cancel by name
        replace_existing=True,           # safe to restart: replaces old job, no duplicate
    )
    scheduler.start()
    logger.info("Scheduler started: pipeline at %02d:%02d JST", settings.cron_hour, settings.cron_minute)

    yield

    scheduler.shutdown()   # clean stop — waits for any running job to finish
    await close_pool()
```

**3. The job function itself**
```python
async def scheduled_pipeline():
    logger.info("Cron triggered: running daily pipeline")
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT email, language FROM subscribers WHERE active = TRUE")
        groups = {"en": [], "ja": []}
        for r in rows:
            lang = r["language"] if r["language"] in ("en", "ja") else "en"
            groups[lang].append(r["email"])
        await run_pipeline(recipients_by_lang=groups, is_test=False)
    except Exception as e:
        logger.exception("Cron pipeline failed: %s", e)
```
It's a plain `async def` — no special decorator needed. APScheduler calls it at the scheduled time.

---

### CronTrigger — Cron Expression Breakdown

```python
CronTrigger(hour=7, minute=50, timezone="Asia/Tokyo")
# fires at 07:50 every day in JST
```

`CronTrigger` accepts the same fields as a Unix crontab, but as keyword arguments:

| Field | Keyword | Example values |
|-------|---------|----------------|
| Minute | `minute` | `0`, `30`, `*/15` (every 15 min) |
| Hour | `hour` | `7`, `9`, `*/2` (every 2 hours) |
| Day of month | `day` | `1`, `15`, `last` |
| Month | `month` | `1-12`, `jan`, `*/3` |
| Day of week | `day_of_week` | `mon-fri`, `0-4`, `*/1` |

**Why `timezone` matters:** Without it, the scheduler uses UTC. `07:50 UTC` is `16:50 JST` — completely wrong. Always set `timezone` explicitly for scheduled jobs.

```python
# Every weekday at 9 AM JST
CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone="Asia/Tokyo")

# Every 30 minutes
CronTrigger(minute="*/30")

# First day of every month at midnight UTC
CronTrigger(day=1, hour=0, minute=0)
```

---

### Other Trigger Types

APScheduler has three trigger families. `CronTrigger` is one:

```python
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta

# Run every 5 minutes (polling, health checks)
scheduler.add_job(check_health, IntervalTrigger(minutes=5))

# Run exactly once at a specific datetime (one-shot future task)
scheduler.add_job(send_announcement, DateTrigger(run_date=datetime(2026, 7, 1, 9, 0)))
```

---

### `replace_existing=True` — Why It's Important

```python
scheduler.add_job(..., id="daily_newsletter", replace_existing=True)
```

Without `replace_existing=True`:
- On first start: job added fine ✓
- On restart (container restart, code reload): `ConflictingIdError` — job with that ID already exists in the job store ✗

With `replace_existing=True`:
- Restart replaces the old job definition cleanly ✓
- Safe to call `add_job` multiple times with the same `id` ✓

---

### Scheduler vs `asyncio.create_task` — When to Use Which

Both run async work outside of a request. The difference:

| | APScheduler | `asyncio.create_task()` |
|--|-------------|------------------------|
| Triggered by | Time (cron/interval/date) | Code (a route handler) |
| Persistent across runs | Yes (job store) | No (dies with the event loop) |
| Survives restarts | With persistent job store | No |
| Use case | Daily email, periodic cleanup | Long background task kicked off by a user action |

In this project:
- `scheduler` → fires the daily newsletter at 07:50 JST every day
- `asyncio.create_task()` → fires a test pipeline when someone clicks "Send Now" in the UI

---

### Full Flow: From Cron Fire to Email Sent

```
07:50:00 JST
    │
    ▼
APScheduler fires scheduled_pipeline()
    │
    ▼
Query DB: SELECT email, language FROM subscribers WHERE active = TRUE
    │
    ▼
Group into {"en": [...9 emails...], "ja": [...4 emails...]}
    │
    ▼
run_pipeline(recipients_by_lang=groups, is_test=False)
    │
    ├── fetch all sources (GitHub, HF papers, arXiv, RSS feeds...)
    ├── dedup against last 14 days
    ├── LLM score + summarize (batches of 3, ~40 calls)
    ├── save to fetched_items catalog
    ├── send EN email via BCC to 9 subscribers
    ├── translate to Japanese
    ├── send JA email via BCC to 4 subscribers
    └── mark items as sent
    │
    ▼
~07:54 JST — both emails delivered
```

---

### Checking the Scheduler in Logs

On container start:
```
Scheduler started: pipeline at 07:50 JST, delivery by 08:00 JST
```

When it fires:
```
Cron triggered: running daily pipeline
...
Pipeline complete: 10 items sent to {'en': [...], 'ja': [...]}
Job "scheduled_pipeline ... next run at: 2026-06-19 07:50:00 JST" executed successfully
```

---

## Quick Reference — FastAPI Concepts Used Here

| Concept | Where | What it does |
|---------|-------|-------------|
| `@asynccontextmanager` lifespan | `main.py` | Startup/shutdown in one function |
| `APIRouter(prefix=...)` | `api.py` | Group routes, shared URL prefix |
| `app.include_router()` | `main.py` | Register router into the app |
| `response_model=list[X]` | route decorators | Validate + shape response, drive /docs |
| `BaseModel` request body | `schemas.py` | Auto-parse + validate JSON body |
| `str | None = None` | `schemas.py` | Optional nullable field (Python 3.10+) |
| `HTTPException(400, "msg")` | `api.py` | Return structured error response |
| `asyncio.create_task()` | `api.py` | Fire-and-forget background coroutine |
| `asyncio.to_thread()` | `pipeline.py` | Run sync/blocking code off the event loop |
| `CORSMiddleware` | `main.py` | Allow cross-origin browser requests |
| `pydantic_settings.BaseSettings` | `config.py` | Typed config from `.env` + env vars |
| `AsyncIOScheduler` + `CronTrigger` | `main.py` | In-process cron, started/stopped in lifespan |
