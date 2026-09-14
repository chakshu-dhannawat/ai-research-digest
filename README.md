# AI Engineer Daily Digest 🤖📬

A self-hosted, LLM-curated daily newsletter for AI engineering teams.

It fetches content from research labs, practitioner blogs, GitHub repos, model releases, and news outlets; scores every item with a local or hosted LLM; and delivers a concise, source-diverse digest by email and Microsoft Teams every weekday morning.

---

## ✨ What You Get

- **7 content sources** in one pipeline: HuggingFace papers, AI lab blogs, practitioner voices, AI news outlets, GitHub repos, model releases, and web news.
- **LLM scoring & summarization** — each item gets a 0–10 relevance score, a 2–3 sentence summary, and a concrete "how to apply" note.
- **Source-diverse top-10 selection** — no single source can dominate; every active source gets at least one slot.
- **14-day deduplication** — subscribers never see the same article twice.
- **Bilingual delivery** — English digest + Japanese translation from the same curated set.
- **Web UI** — searchable catalog of every scored item, subscriber management, and pipeline controls.
- **Microsoft Teams post** — English digest also lands in your Teams channel.

---

## 🚀 Quick Start

### 1. Prerequisites

You need:

- **Docker & Docker Compose** installed.
- **An OpenAI-compatible LLM endpoint** (local vLLM, TGI, LiteLLM proxy, OpenAI, etc.).
- **A GitHub personal access token** (raises search rate limits from 10 to 30 requests/minute).
- **An SMTP relay** to send email (Gmail, Mailgun, AWS SES, your company relay, etc.).
- *(Optional)* **A Microsoft Teams incoming webhook** if you want Teams posts.

### 2. Get your credentials

#### GitHub token

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic).
2. Generate a new token. **No scopes are required** for public repo search, but authentication raises rate limits.
3. Copy the token (starts with `ghp_`).

#### LLM endpoint

If you have a local vLLM server:

```bash
# example local endpoint
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=Qwen/Qwen3.5-72B-Instruct
LLM_API_KEY=not-needed-for-local
```

If you use OpenAI:

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

Any provider with an OpenAI-compatible chat completions API works.

#### SMTP relay

For Gmail:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=you@gmail.com
```

You will need an app password if you use Gmail 2FA.

#### Microsoft Teams webhook (optional)

1. In Teams, go to the channel → ... → Connectors → Incoming Webhook.
2. Create a webhook and copy the URL.
3. Set `TEAMS_WEBHOOK_URL=<url>` in `.env`.
4. Leave it empty if you only want email delivery.

### 3. Clone & configure

```bash
git clone https://github.com/chakshu-dhannawat/ai-research-digest.git
cd ai-research-digest
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in your values:

| Variable | What it's for | Example |
|----------|---------------|---------|
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `http://localhost:8000/v1` |
| `LLM_API_KEY` | API key for the LLM endpoint | `sk-...` |
| `LLM_MODEL` | Model name | `Qwen/Qwen3.5-72B-Instruct` |
| `GITHUB_TOKEN` | GitHub PAT | `ghp_...` |
| `SMTP_HOST` / `SMTP_PORT` | Outgoing mail relay | `smtp.gmail.com` / `587` |
| `SENDER_EMAIL` | From address | `newsletter@example.com` |
| `ALERT_EMAIL` | Alert address if pipeline fails | `admin@example.com` |
| `DEFAULT_RECIPIENTS` | Comma-separated subscriber list | `a@example.com,b@example.com` |
| `TEAMS_WEBHOOK_URL` | Optional Teams webhook | leave empty to disable |

> 🔒 `backend/.env` is git-ignored. Never commit it.

### 4. Start the stack

```bash
docker compose up -d
```

### 5. Verify

```bash
curl http://localhost:8585/api/health
# → {"status":"ok"}
```

| Service | URL | Purpose |
|---------|-----|---------|
| Frontend | http://localhost:3737 | Admin UI & catalog |
| Backend API | http://localhost:8585 | FastAPI + scheduler |
| Database | localhost:5435 | PostgreSQL |

### 6. Run a dry-run (no emails sent)

```bash
make preview
```

Check `dryrun_output/` for the candidate list, scored items, and final selection.

### 7. Send a real digest

```bash
make send-now
```

---

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Crawlers   │────▶│  LLM Scorer  │────▶│  Selector   │
│ 7 sources   │     │ score/summary│     │ top-10 +   │
└─────────────┘     └──────────────┘     │ diversity  │
                                          └──────┬──────┘
                                                 ▼
                                       ┌──────────────────┐
                                       │ Email + Teams +  │
                                       │ Searchable Catalog│
                                       └──────────────────┘
```

Detailed docs:

| Doc | Topic |
|-----|-------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System diagram & services |
| [docs/PIPELINE.md](docs/PIPELINE.md) | End-to-end data flow |
| [docs/CRAWLER.md](docs/CRAWLER.md) | Search algorithm & how to add sources |
| [docs/SOURCES.md](docs/SOURCES.md) | All content sources & scoring rubric |
| [docs/API.md](docs/API.md) | REST endpoints |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema |
| [docs/CRON.md](docs/CRON.md) | Scheduler setup |
| [docs/FRONTEND.md](docs/FRONTEND.md) | UI guide |

---

## 📡 Content Sources

| Category | What it fetches | Key feeds |
|----------|-----------------|-----------|
| **hf_papers** | HuggingFace Daily Papers | community-upvoted papers |
| **labs** | AI lab & tooling blogs | OpenAI, DeepMind, Hugging Face, vLLM, SWE-bench, MTEB, MCP, Anthropic, MiniMax |
| **voices** | Practitioner blogs | Eugene Yan, Lilian Weng, Simon Willison, Chip Huyen, Hamel Husain, etc. |
| **newsletter** | News outlets & digests | Latent Space, Import AI, MarkTechPost, Elastic Blog |
| **github** | Trending AI repos | recency-sorted GitHub search across 5 topic clusters |
| **model_release** | New model releases | HF trending, tracked HF orgs, GitHub releases |
| **web_search** | Web news | Google News RSS |

Add or remove sources by editing `backend/app/services/news_fetcher.py` and `backend/app/services/github_crawler.py`. See [docs/CRAWLER.md](docs/CRAWLER.md) for the full guide.

---

## 🛠️ Development Commands

```bash
# Start everything
make up

# Rebuild after code changes
make build

# View backend logs
make logs

# Run a dry-run inside the container
make test-run

# Stop everything
make down

# Clean state (removes DB volume)
make clean
```

---

## ⚙️ Common Customization

### Change the send time

Edit `CRON_HOUR` and `CRON_MINUTE` in `backend/.env`, then restart:

```bash
docker compose restart backend
```

### Add a new RSS source

Open `backend/app/services/news_fetcher.py` and add a feed tuple:

```python
AI_LABS_FEEDS = [
    ...
    ("My Favorite Lab", "https://lab.example.com/feed.xml"),
]
```

Then rebuild and run a preview:

```bash
make build
make preview
```

### Disable Teams posting

Set `TEAMS_WEBHOOK_URL=` (empty) in `backend/.env`.

### Use a different LLM

Any OpenAI-compatible endpoint works. Update `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` in `backend/.env`.

---

## 📜 License

MIT — feel free to fork and adapt for your own team.
