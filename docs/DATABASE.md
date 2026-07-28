# Database Schema

PostgreSQL 16. Connection: `postgresql://newsletter:newsletter@db:5432/newsletter` (internal Docker network).
External access: `iitgpu07.hon.otsuka-shokai:5435`.

Schema is initialized by `db/init.sql` on first start. Migrations are applied at startup in `backend/app/database.py` via `ALTER TABLE … ADD COLUMN IF NOT EXISTS`.

---

## Tables

### `subscribers`
Who receives the newsletter.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| email | TEXT UNIQUE | |
| subscribed_at | TIMESTAMP | |
| active | BOOLEAN | `FALSE` = unsubscribed |
| language | TEXT | `'en'` or `'ja'`, default `'en'` |

---

### `newsletters`
One row per email send (one per language per cron run).

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| sent_at | TIMESTAMP | |
| subject | TEXT | |
| recipient_emails | TEXT[] | All BCC recipients for this send |
| item_count | INTEGER | Number of items in the email |
| status | TEXT | `'sent'` or `'failed'` |
| error_message | TEXT | Populated on failure |
| is_test | BOOLEAN | Test sends (UI Test Send tab) |

---

### `newsletter_items`
Items included in each newsletter send.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| newsletter_id | INTEGER FK → newsletters | |
| source | TEXT | `github`, `arxiv`, `hf_papers`, etc. |
| title | TEXT | |
| url | TEXT | |
| summary | TEXT | LLM-generated |
| stars | INTEGER | GitHub stars or HF upvotes |
| language | TEXT | Programming language (GitHub only) |
| topics | TEXT[] | |
| relevance_score | REAL | 0–10 |
| created_at | TIMESTAMP | |

---

### `sent_item_hashes`
Deduplication ledger. Prevents the same item from being sent within the rolling window.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| item_hash | TEXT UNIQUE | `sha256(source:title)[:32]` |
| sent_date | DATE | Date it was sent |

Hash is checked against items with `sent_date >= CURRENT_DATE - 14` (configurable via `DEDUP_WINDOW_DAYS`).

---

### `pipeline_runs`
Audit log for every pipeline execution.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| started_at | TIMESTAMP | |
| finished_at | TIMESTAMP | |
| status | TEXT | `'running'`, `'completed'`, `'failed'` |
| github_items_found | INTEGER | |
| news_items_found | INTEGER | All non-GitHub sources combined |
| items_after_dedup | INTEGER | Items actually sent |
| error_message | TEXT | |
| is_test | BOOLEAN | |

---

### `fetched_items`
Searchable catalog of **every item ever fetched and scored**. Powers the Explore page.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| source | TEXT | Source key |
| title | TEXT | |
| url | TEXT UNIQUE | Dedup key — same URL updates in place |
| description | TEXT | Original description (truncated to 1000 chars) |
| summary | TEXT | LLM-generated summary |
| application | TEXT | LLM application note for Otsuka |
| relevance_score | REAL | 0–10 |
| stars | INTEGER | GitHub stars or HF upvotes |
| language | TEXT | Programming language |
| topics | TEXT[] | Source-provided topics |
| keywords | TEXT[] | LLM-generated tags + publisher brand tag |
| published_at | TIMESTAMPTZ | Original publish date when known |
| first_seen | TIMESTAMP | First time this URL was fetched |
| last_seen | TIMESTAMP | Updated on every run that fetches it |

**Indexes:**
- `idx_fetched_items_score` — ORDER BY relevance_score (Top 10 queries)
- `idx_fetched_items_source` — filter by source
- `idx_fetched_items_seen` — filter by recency
- `idx_fetched_items_keywords` — GIN index for `keywords @> ARRAY[...]` tag search

---

## Useful Queries

```sql
-- Current subscriber count by language
SELECT language, COUNT(*) FROM subscribers WHERE active = TRUE GROUP BY language;

-- Items in catalog by source
SELECT source, COUNT(*) FROM fetched_items GROUP BY source ORDER BY count DESC;

-- Last 5 newsletters sent
SELECT id, sent_at, item_count, is_test FROM newsletters ORDER BY sent_at DESC LIMIT 5;

-- Check dedup window — items sent in last 14 days
SELECT COUNT(*) FROM sent_item_hashes WHERE sent_date >= CURRENT_DATE - 14;

-- Top 10 highest-scored items this week
SELECT title, source, relevance_score FROM fetched_items
WHERE last_seen >= NOW() - INTERVAL '7 days'
ORDER BY relevance_score DESC LIMIT 10;
```
