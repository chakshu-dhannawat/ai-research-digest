# Async vs Sync — When to Use Which

This is one of the most practically important decisions in Python backend development.
All examples are from this codebase.

---

## The Mental Model First

Python's `asyncio` runs on a **single thread** with an **event loop**.

```
Event Loop (single thread)
│
├── handles request A  →  hits DB  →  PAUSES (waiting for DB) →─────────────────┐
│                                                                                 │
├── while A waits, handles request B  →  hits DB  →  PAUSES →──────────────┐    │
│                                                                            │    │
├── while B waits, handles request C ...                                    │    │
│                                                                            │    │
│   DB responds for B  ←─────────────────────────────────────────────────────┘    │
├── resumes B, finishes it                                                        │
│   DB responds for A  ←──────────────────────────────────────────────────────────┘
└── resumes A, finishes it
```

The key insight: **pausing** (awaiting I/O) is cheap — the loop can do other work.
**Blocking** (running synchronous CPU/I/O code without yielding) freezes the entire loop.

---

## The One Rule

> **Never block the event loop.**
>
> If your code takes more than a few milliseconds without hitting an `await`, every
> other request is frozen until it finishes.

Everything else follows from this rule.

---

## Decision Flowchart

```
Is this function doing I/O? (network, DB, file, sleep)
│
├── YES → Is there an async library for it? (asyncpg, httpx, aiofiles)
│          ├── YES → use `async def` + `await`            ← best case
│          └── NO  → use `asyncio.to_thread(sync_func)`   ← wrap the blocking call
│
└── NO → Is it CPU-heavy? (data processing, encoding, heavy math)
          ├── YES → use `asyncio.to_thread()` or ProcessPoolExecutor
          └── NO  → plain `def` is fine; FastAPI runs it in a threadpool automatically
```

---

## Category 1: Native Async I/O → `async def` + `await`

Use this when the library itself is async-native.

### asyncpg (DB queries) — used throughout this project
```python
# api.py
async def list_newsletters(limit: int = 30):
    pool = await get_pool()
    async with pool.acquire() as conn:           # async context manager
        rows = await conn.fetch(                 # await the actual query
            "SELECT * FROM newsletters LIMIT $1", limit
        )
    return [NewsletterOut(**dict(r)) for r in rows]
```
`conn.fetch()` suspends until Postgres responds. The event loop handles other requests while waiting.

### httpx (HTTP requests) — used in `news_fetcher.py`
```python
async def fetch_hf_papers():
    async with httpx.AsyncClient(proxy=..., timeout=30) as client:
        resp = await client.get("https://huggingface.co/api/daily_papers?date=...")
        resp.raise_for_status()
        papers = resp.json()
```
`httpx.AsyncClient` is the async version. The `await client.get(...)` suspends while waiting for the HTTP response — no thread needed.

**Async libraries you'll commonly use:**
| Library | What for |
|---------|----------|
| `asyncpg` | PostgreSQL |
| `httpx` (AsyncClient) | HTTP requests |
| `aiofiles` | File I/O |
| `aioredis` | Redis |
| `motor` | MongoDB |
| `aiomysql` | MySQL |

---

## Category 2: Blocking Sync Library → `asyncio.to_thread()`

Use this when you're stuck with a sync library that has no async version.

### PyGithub (sync REST calls) — `pipeline.py`
```python
# WRONG — blocks the event loop for seconds
github_items = fetch_trending_repos()           # sync, does many HTTP calls

# CORRECT — runs in a thread, event loop stays free
github_items = await asyncio.to_thread(fetch_trending_repos)
```

### OpenAI SDK (sync HTTP) — `pipeline.py`
```python
# The openai SDK is synchronous — it uses requests under the hood
# WRONG
scored = score_and_summarize(all_items)

# CORRECT
scored = await asyncio.to_thread(score_and_summarize, all_items)
```

`asyncio.to_thread(fn, arg1, arg2)` is equivalent to:
```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, fn, arg1, arg2)
```
Both submit the function to Python's default ThreadPoolExecutor and await the result.

### When `to_thread` is NOT enough: CPU-heavy work
Threads in Python are limited by the GIL — two threads can't run Python bytecode simultaneously. For truly CPU-bound work (heavy numpy, image processing, model inference):
```python
import asyncio
from concurrent.futures import ProcessPoolExecutor

executor = ProcessPoolExecutor()

async def run_heavy():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, cpu_heavy_function, data)
```
Processes bypass the GIL. For LLM inference, this is usually handled by vLLM's own server — you call it via HTTP (async), so you never need process pools for inference.

---

## Category 3: Plain `def` in FastAPI — It's Not Always Wrong

FastAPI automatically runs synchronous route handlers in a thread pool — you don't need `asyncio.to_thread` inside them.

```python
# FastAPI detects this is NOT async and runs it in a threadpool automatically
@router.get("/sync-example")
def get_something():                   # plain def, not async def
    result = some_blocking_call()      # safe — it's already in a thread
    return result
```

**However**, once you're in an `async def` route, everything changes:
```python
@router.get("/async-example")
async def get_something():
    result = some_blocking_call()      # DANGEROUS — blocks the event loop!
    return result
```

**The confusion:** `async def` routes don't get the automatic thread treatment. If you declare a route `async def`, you're taking full responsibility for not blocking.

**Rule of thumb:**
- Use `async def` for routes that do DB queries or async HTTP calls
- Use `def` (plain) for routes that only call sync code and you don't want to bother with `to_thread`
- Don't mix: don't call blocking sync code inside `async def` without `to_thread`

---

## Category 4: The `github_crawler.py` Pattern — Sync With Internal Parallelism

```python
# github_crawler.py
def fetch_trending_repos() -> list[dict]:   # plain sync function
    ...
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_enrich_repo, r): r for r in all_repos}
        for future in as_completed(futures):
            data = future.result()
            enriched.append(data)
    return enriched
```

This is a **sync** function that uses threads internally for parallelism (enriching 20+ repos simultaneously). It's called via `asyncio.to_thread()` from the pipeline, so the event loop doesn't block.

The internal `ThreadPoolExecutor` is separate from asyncio's threadpool — it's for parallelizing the sync work within the function itself.

---

## Real Comparison: httpx vs requests

```python
# requests — SYNC, blocks the event loop
import requests

async def fetch_bad():
    r = requests.get("https://api.example.com/data")   # blocks here!
    return r.json()

# httpx AsyncClient — ASYNC, event loop stays free
import httpx

async def fetch_good():
    async with httpx.AsyncClient() as client:
        r = await client.get("https://api.example.com/data")   # suspends here
    return r.json()

# httpx sync client — also exists, use with asyncio.to_thread
async def fetch_also_fine():
    r = await asyncio.to_thread(requests.get, "https://api.example.com/data")
    return r.json()
```

This project uses `httpx.AsyncClient` everywhere in `news_fetcher.py` — the right choice since the fetcher is itself an `async def`.

---

## Spot the Bug — Common Mistakes

### Bug 1: Calling blocking code in async context
```python
async def run_pipeline(...):
    # BUG — openai SDK is sync; this freezes the server for minutes
    scored = score_and_summarize(all_items)

    # FIX
    scored = await asyncio.to_thread(score_and_summarize, all_items)
```

### Bug 2: Using sync `open()` in async code
```python
async def read_template():
    # BUG — file I/O blocks
    text = open("template.html").read()

    # FIX option 1 — wrap with to_thread
    text = await asyncio.to_thread(open("template.html").read)

    # FIX option 2 — use aiofiles
    async with aiofiles.open("template.html") as f:
        text = await f.read()

    # FIX option 3 — read at startup, cache in memory (what this project does)
    # In email_sender.py: _TEMPLATE_PATH.read_text() is called inside
    # asyncio.to_thread() indirectly via score_and_summarize
```

### Bug 3: Forgetting `await`
```python
async def get_items():
    rows = conn.fetch("SELECT ...")   # BUG — returns a coroutine object, not data!
    rows = await conn.fetch("...")    # FIX
```
Forgetting `await` doesn't raise an error immediately — `rows` just becomes a coroutine object. You'll get a confusing `AttributeError` or `TypeError` later when you try to iterate it.

### Bug 4: Sharing mutable state across async tasks
```python
# api.py — the running task guard
_running_task: asyncio.Task | None = None

async def trigger():
    global _running_task
    if _running_task and not _running_task.done():
        raise HTTPException(400, "already running")
    _running_task = asyncio.create_task(run_pipeline())
```
This works **only because asyncio is single-threaded**. There's no race condition between the check and the assignment — nothing else runs between those two lines (no `await` between them). In a multi-threaded context you'd need a lock. In asyncio, a race can only happen if there's an `await` between the check and the write.

---

## Quick Decision Guide

| Situation | Solution |
|-----------|----------|
| DB query (asyncpg) | `await conn.fetch(...)` |
| HTTP request (httpx AsyncClient) | `await client.get(...)` |
| HTTP request (requests / sync) | `asyncio.to_thread(requests.get, url)` |
| OpenAI / PyGithub SDK | `asyncio.to_thread(sync_func, args)` |
| File read (small, startup) | `Path.read_text()` in `__init__` or startup |
| File read (large, per-request) | `asyncio.to_thread(path.read_text)` |
| CPU computation (<100ms) | Fine in `async def` directly |
| CPU computation (>100ms) | `asyncio.to_thread()` or `ProcessPoolExecutor` |
| Route with only sync code | Use plain `def` — FastAPI threads it automatically |
| Route with DB or async HTTP | Use `async def` + `await` throughout |
| Parallel sync calls | `ThreadPoolExecutor` inside `asyncio.to_thread` |
| Parallel async calls | `asyncio.gather(coro1, coro2, coro3)` |

---

## `asyncio.gather` — Running Multiple Coroutines in Parallel

Not used directly in this project but important to know:

```python
# Sequential — total time = A + B + C
result_a = await fetch_source_a()
result_b = await fetch_source_b()
result_c = await fetch_source_c()

# Parallel — total time = max(A, B, C)
result_a, result_b, result_c = await asyncio.gather(
    fetch_source_a(),
    fetch_source_b(),
    fetch_source_c(),
)
```

This project fetches all sources sequentially (simple to reason about at ~4 min total). If you wanted to cut fetch time, `asyncio.gather` would be the first optimization.
