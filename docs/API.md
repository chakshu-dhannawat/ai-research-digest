# API Reference

Base URL: `http://iitgpu07.hon.otsuka-shokai.co.jp:8585/api`

Auto-generated docs: `http://iitgpu07.hon.otsuka-shokai.co.jp:8585/docs`

---

## Pipeline

| Method | Path | Description |
|--------|------|-------------|
| POST | `/pipeline/run` | Start a test run (skips dedup, skips mark-sent) |
| POST | `/pipeline/send-now` | Send test email to specific recipients |

**`/pipeline/send-now` body:**
```json
{ "recipients": ["you@example.com"] }
```

---

## Newsletters

| Method | Path | Description |
|--------|------|-------------|
| GET | `/newsletters` | List sent newsletters (excludes test runs by default) |
| GET | `/newsletters?include_test=true` | Include test sends |
| GET | `/newsletters/{id}/items` | Items included in a specific newsletter |
| GET | `/runs` | List pipeline run audit log |

---

## Subscribers

| Method | Path | Description |
|--------|------|-------------|
| POST | `/subscribe` | Subscribe (or reactivate) with language |
| DELETE | `/subscribe` | Unsubscribe |
| GET | `/subscribe/check?email=...` | Check subscription status + language |
| POST | `/subscribe/language` | Update language preference |
| GET | `/subscribers` | List all active subscribers |

**`/subscribe` body:**
```json
{ "email": "you@example.com", "language": "en" }
```

**`/subscribe/language` body:**
```json
{ "email": "you@example.com", "language": "ja" }
```

---

## Explore / Catalog

| Method | Path | Description |
|--------|------|-------------|
| GET | `/items` | Search the catalog |
| GET | `/items/top` | Top-scored items from the last N days |
| GET | `/items/hot-topics` | Trending keyword tags (weighted by score + recency) |
| GET | `/items/sources` | Item count per source |

**`/items` query params:**

| Param | Default | Description |
|-------|---------|-------------|
| `q` | `""` | Full-text search (title, description, summary, keywords) |
| `source` | `""` | Filter by source key (`github`, `arxiv`, `hf_papers`, etc.) |
| `keyword` | `""` | Filter by keyword tag (exact, lowercase) |
| `min_score` | `0` | Minimum relevance score |
| `date_from` | `""` | ISO date, e.g. `2026-06-01` |
| `date_to` | `""` | ISO date |
| `limit` | `60` | |
| `offset` | `0` | |

**`/items/top` query params:** `days=14`, `limit=10`

**`/items/hot-topics` query params:** `days=14`, `limit=14`

---

## Health

```
GET /api/health  →  {"status": "ok"}
```
