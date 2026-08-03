# Pipeline — End-to-End Data Flow

Every run (cron or manual) executes `run_pipeline()` in `backend/app/services/pipeline.py`.

## Steps

```
1. FETCH          Gather raw items from all sources concurrently
       │            (GitHub, HF Papers, newsletters, labs, voices, model releases, web)
       │            On Monday, HF Daily Papers fetches the most recent 3 populated
       │            days (up to Friday/Saturday/Sunday) so the weekend is covered.
       ▼
2. RECENCY        Keep items published within the last 3 months (configurable via
       │            MAX_ARTICLE_AGE_DAYS). Date extraction order per item:
       │              feed date → HTML metadata/JSON-LD/<time>/URL path → LLM fallback
       │            Scraped listing-page items fall back to "today" only if no real date is found.
       │            Items without any date are dropped.
       ▼
3. REFILL         If a source falls below its minimum target, do one wider fetch pass
       │            for that source only, then re-apply the recency filter.
       ▼
4. DEDUP          Drop items already sent within the last 14 days
       │            (hash = sha256(source:title)[:32], checked against sent_item_hashes)
       │            Test runs skip this step.
       ▼
5. SCORE          Send candidates to the LLM in batches of 3
       │            Each item gets: relevance_score (0-10), summary, application, keywords
       │            Sort descending by score → take top 10
       ▼
6. SAVE CATALOG   Upsert all scored items into fetched_items (deduped by URL)
       │            Powers the Explore page. Isolated — catalog failure never blocks email.
       ▼
7. SEND EMAIL     For each language group (en / ja):
        │              ja → translate summaries + application to Japanese (敬語)
        │              Render Jinja2 HTML template
        │              Send BCC email via mta-fm21:25
        │              Record in newsletters + newsletter_items tables
        ▼
8. TEAMS POST     If TEAMS_WEBHOOK_URL is set, post an Adaptive Card digest
        │            to the Microsoft Teams channel (production only, non-blocking)
        ▼
9. MARK SENT      Write hashes to sent_item_hashes (production only, once per run)
```

## Language Handling

Subscribers are grouped by their `language` preference (`en` or `ja`).
- EN group → items in English, subject: `AI Engineer Daily Digest — YYYY-MM-DD`
- JA group → `translate_items_to_japanese()` translates summary + application (titles stay in English), subject: `AIエンジニア・デイリーダイジェスト — YYYY-MM-DD`

Both groups receive the **same top-10 items**, just translated.

## Email Delivery

- BCC: all recipients in a single `Bcc:` header; `To:` is set to the sender address
- One BCC email per language group per run
- SMTP: `mta-fm21.otsuka-shokai.co.jp:25`, no auth, no TLS

## Teams Channel Delivery

- Optional: set `TEAMS_WEBHOOK_URL` to a Microsoft Teams **Incoming Webhook** or **Power Automate** workflow URL.
- Posts the English-language digest as an Adaptive Card once per production run.
- Card layout: title + date, section headers (Model Releases, GitHub, arXiv, etc.), each item as a clickable title with a short summary and score, plus a **Browse all articles** button.
- Teams failures are logged and recorded in `pipeline_runs.teams_error` but do **not** fail the email send.

## Batch Sizing (LLM)

Why-LLM has a 4096-token context window.
- `batch_size = 3` items per call
- `max_tokens = 2000` output budget
- Input trimmed: description ≤ 350 chars, readme ≤ 400 chars

## Item Counts (typical run)

| Stage | Count |
|-------|-------|
| Raw fetched | ~100–150 items |
| After recency filter (90d) + refill | ~50 candidates capped |
| After 14-day dedup | ~35–50 items |
| After scoring + sort | top 10 sent |
| Catalog (cumulative) | 400+ items |

## Triggering a Manual Run

Via the UI: **Test Send** tab → enter email(s) → click Send.

Via API:
```bash
# Test run (skips dedup, skips mark-sent)
curl -X POST http://iitgpu07.hon.otsuka-shokai.co.jp:8585/api/pipeline/send-now \
  -H "Content-Type: application/json" \
  -d '{"recipients": ["you@example.com"]}'
```
