# Frontend

React + Vite SPA served by nginx on port **3737**. iPhone-first layout, light theme.

**Entry point:** `frontend/src/App.jsx`
**Styles:** `frontend/src/index.css`
**API client:** `frontend/src/api/client.js`

---

## Tabs

### Home
- **Subscribe section** (top): enter email + choose English / 日本語 → calls `POST /api/subscribe`
- For already-subscribed emails: shows current language + toggle to update → calls `POST /api/subscribe/language`
- **Source cards**: clickable links to each data source (GitHub, HF Daily Papers, arXiv, AI Labs, Voices, Newsletters, Model Releases, Web Search)
- Delivery info: "Daily at 8:00 AM JST"

### History
- Lists all sent newsletters from `GET /api/newsletters`
- Click a newsletter to expand and see its items with scores and summaries
- Date displayed in JST (uses `parseUTC()` helper to fix timezone parsing)

### Explore
Search and browse the full item catalog (`fetched_items` table).

Features:
- **Top 10 rail** — highest-scored items from the last 14 days, shown as cards with score badge + 2-line summary
- **Hot Topics chips** — trending keyword tags (recency-weighted), clickable to filter
- **Source filter chips** — filter by source; includes a ⭐ Favorites chip
- **Date presets** — All / Last week / Last month / Last 3 months
- **Free-text search** — searches title, description, summary, keywords
- **Card view** — each result shows source badge, score, stars/upvotes, clickable `#keyword` pills, summary, and "💡 How to apply" box
- **Favorites** — star any card to save it to localStorage (`ainl_favorites` key); persist across page reloads

### Test Send
- Enter one or more email addresses → triggers `POST /api/pipeline/send-now`
- Sends a full test run (dedup skipped, not marked as sent, not logged as production)
- Shows run status

---

## Key Constants (`App.jsx`)

```js
SOURCE_COLORS   // accent colors per source key
SOURCE_LINKS    // URL for each source's homepage
DATE_PRESETS    // [['All', null], ['Last week', 7], ...]
FAV_KEY         // 'ainl_favorites' (localStorage)
```

## `parseUTC(ts)`

Timestamps from the DB have no timezone suffix. `new Date("2026-06-11T23:57:36")` is parsed as **local time** in browsers, causing off-by-one day errors in JST. `parseUTC` appends `'Z'` if no timezone suffix is present, forcing UTC interpretation.

---

## nginx Config

`frontend/nginx.conf` serves the Vite build on port 3737.
API calls from the browser to `/api/...` are proxied to `backend:8585`.

```nginx
location /api/ {
    proxy_pass http://backend:8585;
}
```
