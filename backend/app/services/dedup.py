import hashlib
import logging

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)


def item_hash(item: dict) -> str:
    key = f"{item.get('source','')}:{item.get('title','')}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


async def filter_already_sent(pool: asyncpg.Pool, items: list[dict]) -> list[dict]:
    hashes = [item_hash(it) for it in items]
    existing = set()

    async with pool.acquire() as conn:
        # Only suppress items sent within the recency window, so evergreen items
        # (GitHub repos, model releases, voices) can resurface afterward instead
        # of being blocked forever.
        rows = await conn.fetch(
            "SELECT item_hash FROM sent_item_hashes "
            "WHERE item_hash = ANY($1::text[]) AND sent_date >= CURRENT_DATE - $2::int",
            hashes, settings.dedup_window_days,
        )
        existing = {r["item_hash"] for r in rows}

    filtered = []
    for it, h in zip(items, hashes):
        if h not in existing:
            it["_hash"] = h
            filtered.append(it)

    logger.info("Dedup: %d -> %d items (removed %d already-sent)", len(items), len(filtered), len(items) - len(filtered))
    return filtered


async def mark_as_sent(pool: asyncpg.Pool, items: list[dict]):
    hashes = [it.get("_hash") or item_hash(it) for it in items]
    async with pool.acquire() as conn:
        # Refresh sent_date on conflict. With DO NOTHING the date froze at the
        # first send, so once an item aged past the recency window it resurfaced
        # every day forever. Bumping it restarts the suppression window, so an
        # evergreen item resurfaces at most once per dedup_window_days.
        await conn.executemany(
            "INSERT INTO sent_item_hashes (item_hash) VALUES ($1) "
            "ON CONFLICT (item_hash) DO UPDATE SET sent_date = CURRENT_DATE",
            [(h,) for h in hashes],
        )
