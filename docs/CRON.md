# Cron / Scheduler

## How It Works

The scheduler is **in-process** — no external cron daemon, no Celery, no Redis. APScheduler runs inside the FastAPI lifespan (`backend/app/main.py`).

```python
scheduler.add_job(
    scheduled_pipeline,
    CronTrigger(hour=settings.cron_hour, minute=settings.cron_minute, timezone="Asia/Tokyo"),
    id="daily_newsletter",
    replace_existing=True,
)
```

The scheduler starts when the backend container starts and shuts down cleanly when it stops.

## Current Schedule

| Setting | Value |
|---------|-------|
| Fire time | **07:50 JST** |
| Typical run duration | ~4 minutes (EN + JA both) |
| Delivery by | **08:00 JST** |

## Changing the Time

Edit `backend/.env`:
```
CRON_HOUR=7
CRON_MINUTE=50
```

Then restart the backend:
```bash
docker compose restart backend
```

The new time is shown in the backend logs on startup:
```
Scheduler started: pipeline at 07:50 JST, delivery by 08:00 JST
```

`config.py` has matching defaults (`cron_hour=7`, `cron_minute=50`) as a fallback if `.env` is missing.

## What the Scheduled Job Does

1. Queries `SELECT email, language FROM subscribers WHERE active = TRUE`
2. Groups into `{"en": [...], "ja": [...]}`
3. Calls `run_pipeline(recipients_by_lang=groups, is_test=False)`

If the subscriber table is empty, falls back to `DEFAULT_RECIPIENTS` in `.env`.

## Resilience

- `restart: always` in `compose.yml` — backend auto-restarts on crash
- If the backend is down at 07:50, the job is missed (no catch-up). Restart and use **Test Send** to resend manually.
- Pipeline errors are caught, logged, and written to `pipeline_runs.error_message` — they do not crash the backend.
