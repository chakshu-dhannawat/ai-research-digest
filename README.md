# AI Engineer Daily Digest 🤖📬

A self-hosted, LLM-curated daily newsletter for AI engineering teams.

It fetches content from research labs, practitioner blogs, GitHub repos, model releases, and news outlets; scores every item with a local or hosted LLM; and delivers a concise, source-diverse digest by email and Microsoft Teams every weekday morning.

---

## Why I built this

I'm Chakshu Dhannawat, an AI engineer. I was running this digest every morning for myself because the field moves faster than anyone can track by hand. The alternatives were either another paid newsletter subscription or handing my reading habits to somebody else's service.

I wanted something that:

- runs on my own machine,
- uses my own API key,
- fetches from a source list I control, and
- tells me what actually shipped yesterday, not what was popular last week.

I run it against a self-hosted Qwen model on my own GPU box via a custom OpenAI-compatible endpoint. Any OpenAI-compatible server works exactly the same — Ollama, vLLM, LM Studio, OpenAI, OpenRouter, Groq. Nothing in the pipeline is tied to a specific vendor.

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
- **An email sender**. The easiest option is **[Resend](https://resend.com)** — sign up, copy the API key, and you can send from `onboarding@resend.dev` without verifying a domain. If you prefer, you can also use any SMTP relay (Gmail, Mailgun, AWS SES, your company relay, etc.).
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

#### Email sender (Resend — recommended)

1. Sign up at [resend.com](https://resend.com).
2. Go to API Keys → Create API Key.
3. Copy the key (starts with `re_`).
4. Set it in `backend/.env`:

```bash
RESEND_API_KEY=re_...
SENDER_EMAIL=onboarding@resend.dev
DEFAULT_RECIPIENTS=you@example.com
```

You can send from `onboarding@resend.dev` immediately; no domain verification required for testing. Once you want a custom from address, verify your domain in Resend and update `SENDER_EMAIL`.

#### Email sender (SMTP alternative)

If you prefer not to use Resend, leave `RESEND_API_KEY` empty and configure SMTP. For Gmail:

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
| `RESEND_API_KEY` | Recommended email sender API key | `re_...` (leave empty to use SMTP) |
| `SMTP_HOST` / `SMTP_PORT` | Outgoing mail relay (fallback) | `smtp.gmail.com` / `587` |
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
| Database | postgresql://localhost:5435 | PostgreSQL |

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

Seven categories are fetched on every run. The feed list is the main value of the project — the scoring and delivery pipeline is generic, but the sources are curated.

| Category | What it covers | Key sources |
|----------|----------------|-------------|
| **github** | GitHub REST repository search across five AI topic clusters: LLMs / GPT-class models, agents and tool use, RAG and vector databases, fine-tuning / RLHF / DPO, and diffusion / multimodal models. Each query looks for brand-new repos and recently-pushed repos, sorted by recency. README snippets are pulled in for scoring context. | public GitHub search |
| **hf_papers** | Hugging Face Daily Papers — the community-curated, upvote-ranked list. The crawler scans backward to the most recent day that actually has papers, so weekends and holidays don't produce an empty section. Papers are deduplicated by arXiv id. | HuggingFace Daily Papers |
| **labs** | Official lab and research-org blogs and tool docs. RSS feeds where available; HTML scraping where a usable feed doesn't exist. | OpenAI, Google DeepMind, Google Research, Hugging Face, Together AI, Qwen, vLLM, SWE-bench, MTEB, MCP, Anthropic, MiniMax |
| **voices** | Practitioner blogs and individual AI engineers writing long-form. See the detailed list below. | Eugene Yan, Nathan Lambert, Philipp Schmid, Ethan Mollick, Hamel Husain, Chip Huyen, Jay Alammar, Simon Willison, Sebastian Raschka, Lilian Weng |
| **newsletter** | AI news outlets and digests. | Latent Space, Import AI, MarkTechPost, Elastic Blog |
| **model_release** | New model releases from three streams: Hugging Face models trending by weekly likes (filtered to genuinely new models), GitHub release feeds for key inference frameworks and SDKs, and the newest models from tracked HF orgs. | HF trending, vLLM, Transformers, Qwen, DeepSeek, GLM (Z.ai), MiniMax, Moonshot/Kimi, OpenAI Python SDK, Anthropic SDK |
| **web_search** | Web news via Google News RSS for standing queries about new model releases, LLM breakthrough announcements, and new open-source AI tooling. | Google News RSS |

Items from blog and newsletter feeds are filtered to roughly the last 14 days; anything older than `MAX_ARTICLE_AGE_DAYS` (default 45) is dropped before scoring. Anything already sent within `DEDUP_WINDOW_DAYS` (default 14) is not sent again.

### Practitioner voices in detail

These are the individual engineers and researchers I follow because they write about the *practice* of building AI systems, not just announcements. They are the main reason the digest feels useful instead of noisy.

| Author | Blog | Why I included them |
|--------|------|---------------------|
| **Eugene Yan** | [eugeneyan.com](https://eugeneyan.com) | Rigorously practical writing on ML systems, evaluation, and building products that actually work. |
| **Nathan Lambert** | [Interconnects](https://www.interconnects.ai) | Deep, timely takes on RLHF, post-training, and the open-source model ecosystem. |
| **Philipp Schmid** | [philschmid.de](https://www.philschmid.de) | Hands-on Hugging Face and AWS deployment guides; great for applied MLOps. |
| **Ethan Mollick** | [One Useful Thing](https://www.oneusefulthing.org) | Clear-eyed perspective on how generative AI is actually being used in practice. |
| **Hamel Husain** | [hamel.dev](https://hamel.dev) | Engineering-heavy posts on LLM evals, tooling, and production workflows. |
| **Chip Huyen** | [chiphuyen.com](https://chiphuyen.com) | Strong systems thinking around ML infrastructure, data, and real-world trade-offs. |
| **Jay Alammar** | [jalammar.github.io](https://jalammar.github.io) | Best-in-class visual explanations of transformers and LLM internals. |
| **Simon Willison** | [simonwillison.net](https://simonwillison.net) | Prolific notes on new tools, APIs, and quick experiments — catches things I would miss. |
| **Sebastian Raschka** | [sebastianraschka.com](https://sebastianraschka.com) | Accessible but technically solid deep dives into models and training methods. |
| **Lilian Weng** | [lilianweng.github.io](https://lilianweng.github.io) | Authoritative long-form posts from an OpenAI research lead on safety, agents, and LLM behavior. |

Add or remove sources by editing `backend/app/services/news_fetcher.py` and `backend/app/services/github_crawler.py`. See [docs/CRAWLER.md](docs/CRAWLER.md) and [docs/SOURCES.md](docs/SOURCES.md) for the full guide.

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
