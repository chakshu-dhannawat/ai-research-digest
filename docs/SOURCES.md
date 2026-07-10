# Content Sources

All sources are fetched during each pipeline run. Items older than `NEWSLETTER_RECENCY_DAYS = 14` days are dropped from RSS feeds.

## Source Categories

### `github` — Trending GitHub Repos
**File:** `backend/app/services/github_crawler.py`

Searches GitHub for recently-created or rapidly-growing AI repos using 5 queries:
- LLM / large-language-model / GPT
- AI agent / agentic / multi-agent
- RAG / retrieval-augmented / vector-database
- fine-tuning / RLHF / DPO / alignment
- diffusion / multimodal / vision-language

Two sub-queries per topic: brand-new repos (last 7 days, stars > 5) and fast-growing repos (last month, 10–5000 stars). Enriches each repo with README snippet. Up to 5 results per query.

---

### `hf_papers` — HuggingFace Daily Papers
**File:** `backend/app/services/news_fetcher.py` → `fetch_hf_papers()`

Fetches `https://huggingface.co/api/daily_papers?date=YYYY-MM-DD` for **today and yesterday**. Takes the **top 5 by upvotes per day** (= up to 10 total). Deduped by arXiv paper ID. These are community-curated, heavily-upvoted papers — highest signal for frontier research.

---

### `arxiv` — arXiv CS Papers
**File:** `backend/app/services/news_fetcher.py` → `fetch_arxiv_papers()`

RSS feed: `https://rss.arxiv.org/rss/cs.AI+cs.CL`. Fetches recent submissions from CS.AI and CS.CL categories.

---

### `labs` — AI Lab Technical Blogs
**File:** `backend/app/services/news_fetcher.py` → `fetch_ai_labs()`

Official engineering/research blogs from major AI labs:

| Source | Feed |
|--------|------|
| OpenAI | openai.com/news/rss.xml |
| Google DeepMind | deepmind.google/blog/rss.xml |
| Google Research | research.google/blog/rss |
| Hugging Face | huggingface.co/blog/feed.xml |
| Together AI | together.ai/blog/rss.xml |
| Qwen | qwenlm.github.io/blog/index.xml |
| Anthropic | Scraped: /news, /engineering, /research |
| MiniMax | Scraped: minimaxi.com/en/news |

---

### `voices` — Individual AI Practitioners
**File:** `backend/app/services/news_fetcher.py` → `fetch_ai_voices()`

RSS feeds from named researchers and engineers:

| Person | Blog |
|--------|------|
| Eugene Yan | eugeneyan.com |
| Nathan Lambert (Interconnects) | interconnects.ai |
| Philipp Schmid | philschmid.de |
| Ethan Mollick | oneusefulthing.org |
| Hamel Husain | hamel.dev |
| Chip Huyen | huyenchip.com |
| Jay Alammar | jalammar.github.io |
| Simon Willison | simonwillison.net |
| Sebastian Raschka | sebastianraschka.com |
| Lilian Weng | lilianweng.github.io |

---

### `newsletter` — AI News Outlets
**File:** `backend/app/services/news_fetcher.py` → `fetch_ai_newsletters()`

| Source | Feed |
|--------|------|
| Import AI | importai.substack.com/feed |
| Elastic Blog | elastic.co/blog/feed |
| Latent Space | latent.space/feed |
| MarkTechPost | marktechpost.com/feed |

Items from the Elastic Blog with "elastic" in topics are separated into their own email section.

---

### `model_release` — New Model Releases
**File:** `backend/app/services/news_fetcher.py` → `fetch_model_releases()`

Tracks GitHub releases from major model organizations:

| Org | Tag |
|-----|-----|
| zai-org | GLM |
| MiniMaxAI | MiniMax |
| deepseek-ai | DeepSeek |
| Qwen | Qwen |
| moonshotai | Kimi |

Also pulls from GitHub trending filtered to model-release keywords. Up to 8 items total.

---

### `web_search` — Web Search News
**File:** `backend/app/services/news_fetcher.py` → `fetch_web_search_news()`

DuckDuckGo search for recent AI news as a fallback/supplement. Lower priority, merged into the AI News & Blogs email section.

---

## Scoring Rubric

Handled by `backend/app/services/llm_summarizer.py` using Why-LLM at `macdep01:8001/v1`.

**Otsuka Shokai context baked in:**
- RAG on Elasticsearch, multi-agent orchestration, LLM fine-tuning (LoRA/QLoRA), vLLM serving on multi-node GPUs, VLM/document AI, Japanese enterprise tools

**UP-WEIGHT (8–10):** Novel techniques, deep engineering write-ups, Anthropic Engineering posts, new frontier models. Priority: fine-tuning, agent loops, ANN/vector search, quantization/efficient inference, RAG advances, VLM/document AI.

**DOWN-WEIGHT (1–3):** LangChain, LlamaIndex, transformers, Ollama (already known); tutorials, awesome-lists, marketing; embodied AI, robotics, autonomous driving, RL for games.

**Score bands:**
- 9–10: Must-read novel SOTA (rare)
- 7–8: Valuable new technique or high-signal lab post
- 4–6: Incremental or niche
- 1–3: Established tool with nothing new, beginner, or off-domain
- 0: Noise or pure embodied/robotics

## Email Sections (in send order)

| Section | Source key | Shown when |
|---------|-----------|------------|
| 🚀 Recent Model Releases | `model_release` | New model from tracked orgs |
| 🔬 AI Labs & Technical Reports | `labs` | Lab blog posts present |
| 🗣️ Voices | `voices` | Practitioner posts present |
| 🔥 Trending GitHub Repos | `github` | GitHub items present |
| 📡 Elastic Blog | `newsletter` (elastic topic) | Elastic posts present |
| 📰 AI News & Blogs | `newsletter` + `web_search` | Always (most days) |
| 🤗 HuggingFace Trending Papers | `hf_papers` | Almost always (2-day window) |
| 📄 arXiv Papers | `arxiv` | Almost always |

Sections with 0 items are hidden automatically.
