import asyncpg

from app.config import settings

pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            min_size=2,
            max_size=10,
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS subscribers ("
                "id SERIAL PRIMARY KEY, "
                "email TEXT UNIQUE NOT NULL, "
                "subscribed_at TIMESTAMP NOT NULL DEFAULT NOW(), "
                "active BOOLEAN NOT NULL DEFAULT TRUE)"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS fetched_items ("
                "id SERIAL PRIMARY KEY, "
                "source TEXT NOT NULL, "
                "title TEXT NOT NULL, "
                "url TEXT UNIQUE, "
                "description TEXT, "
                "summary TEXT, "
                "application TEXT, "
                "relevance_score REAL, "
                "stars INTEGER, "
                "language TEXT, "
                "topics TEXT[], "
                "keywords TEXT[], "
                "published_at TIMESTAMPTZ, "
                "first_seen TIMESTAMP NOT NULL DEFAULT NOW(), "
                "last_seen TIMESTAMP NOT NULL DEFAULT NOW())"
            )
            # Migration for existing DBs that predate the keywords column
            await conn.execute(
                "ALTER TABLE fetched_items ADD COLUMN IF NOT EXISTS keywords TEXT[]"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fetched_items_score ON fetched_items(relevance_score DESC)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fetched_items_source ON fetched_items(source)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fetched_items_keywords ON fetched_items USING GIN (keywords)"
            )
            # Add is_test columns if missing
            for table in ("newsletters", "pipeline_runs"):
                try:
                    await conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT FALSE"
                    )
                except Exception:
                    pass
            # Migration: per-subscriber language preference
            try:
                await conn.execute(
                    "ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'en'"
                )
            except Exception:
                pass
            # Migration: record which LLM produced each newsletter (audit only,
            # never surfaced to recipients).
            try:
                await conn.execute(
                    "ALTER TABLE newsletters ADD COLUMN IF NOT EXISTS model_used TEXT"
                )
            except Exception:
                pass
            # Migration: track Microsoft Teams channel delivery per pipeline run.
            try:
                await conn.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS teams_posted_at TIMESTAMP"
                )
                await conn.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS teams_error TEXT"
                )
            except Exception:
                pass
            # Migration: normalize existing emails to lowercase so case variants
            # ("Aryan@..." vs "aryan@...") resolve to the same subscriber.
            try:
                await conn.execute(
                    "UPDATE subscribers SET email = LOWER(email) WHERE email <> LOWER(email)"
                )
            except Exception:
                pass
            # Pre-seed default subscribers
            for email in [
                "chakshu@otsuka-shokai.co.jp",
                "rahil@otsuka-shokai.co.jp",
                "naman@otsuka-shokai.co.jp",
                "kataria.mitouru@otsuka-shokai.co.jp",
            ]:
                await conn.execute(
                    "INSERT INTO subscribers (email) VALUES ($1) "
                    "ON CONFLICT (email) DO NOTHING",
                    email,
                )
    return pool


async def close_pool():
    global pool
    if pool:
        await pool.close()
        pool = None
