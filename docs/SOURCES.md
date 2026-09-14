# Content Sources

All sources are fetched during each pipeline run. RSS feed items older than `NEWSLETTER_RECENCY_DAYS = 14` days are dropped before scoring.

## Source Categories

### `github` — Trending GitHub Repos
**File:** `backend/app/services/github_crawler.py`

Searches GitHub for recently-created or recently-pushed AI repos using 5 topic queries:
- LLM / large-language-model / GPT
- AI agent / agentic / multi-agent
- RAG / retrieval-augmented / vector-database
- fine-tuning / RLHF / DPO / alignment
- diffusion / multimodal / vision-language

For each topic three searches run, sorted by **recency** so the same high-star repos are not returned every day:
1. `created:>3_days_ago` — newest repos first.
2. `created:>7_days_ago` — wider net, newest first.
3. `pushed:>3_days_ago created:>30_days_ago` — recently active repos.

Each repo is enriched with its README snippet. Default fetch: 10 repos per sub-query.

---

### `hf_papers` — HuggingFace Daily Papers
**File:** `backend/app/services/news_fetcher.py` → `fetch_hf_papers()`

Fetches `https://huggingface.co/api/daily_papers?date=YYYY-MM-DD` for today and recent days. Keeps the top 5 by upvotes per populated day. Deduped by arXiv paper ID. These are community-curated, heavily-upvoted papers — highest signal for frontier research.

---

### `labs` — AI Lab Technical Blogs
**File:** `backend/app/services/news_fetcher.py` → `fetch_ai_labs()`

Official engineering/research blogs from major AI labs and tooling projects:

| Source | Feed |
|--------|------|
| OpenAI News | openai.com/news/rss.xml |
| OpenAI Developers / Cookbook | developers.openai.com/rss.xml |
| Google DeepMind | deepmind.google/blog/rss.xml |
| Google Research | research.google/blog/rss |
| Hugging Face | huggingface.co/blog/feed.xml |
| Together AI | together.ai/blog/rss.xml |
| Qwen | qwenlm.github.io/blog/index.xml |
| vLLM Blog | vllm.ai/blog/rss.xml |
| SWE-bench | github.com/SWE-bench/SWE-bench/releases.atom |
| MTEB | github.com/embeddings-benchmark/mteb/releases.atom |
| MCP Docs | github.com/modelcontextprotocol/docs/commits/main.atom |
| Anthropic | Scraped: /news, /engineering, /research |
| MiniMax | Scraped: minimax.io/news |

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
| Sebastian Raschka | magazine.sebastianraschka.com |
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

Tracks three signals:
1. **HuggingFace trending models** — `likes7d` sort, filtered to models created within the last 7 days.
2. **GitHub releases** from major model/tooling repos (OpenAI, Qwen, DeepSeek, Meta Llama, Google Gemma, Anthropic, Mistral, vLLM, Transformers).
3. **Tracked HF labs** — newest models by org: zai-org (GLM), MiniMaxAI, deepseek-ai, Qwen, moonshotai (Kimi).

---

### `web_search` — Web Search News
**File:** `backend/app/services/news_fetcher.py` → `fetch_web_search_news()`

Fetches recent AI news via Google News RSS for three queries:
- `new AI model released`
- `LLM breakthrough announcement`
- `new open source AI tool developer`

Lower priority; merged into the AI News & Blogs email section.

---

## Scoring Rubric

Handled by `backend/app/services/llm_summarizer.py` using the configured LLM endpoint (`LLM_BASE_URL`, `LLM_MODEL`).

**Otsuka Shokai context baked in:**
- RAG on Elasticsearch, multi-agent orchestration, LLM fine-tuning (LoRA/QLoRA), vLLM serving on multi-node GPUs, VLM/document AI, Japanese enterprise tools.

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
| 📰 AI News & Blogs | `newsletter` + `web_search` | Most days |
| 🤗 HuggingFace Trending Papers | `hf_papers` | Almost always |

Sections with 0 items are hidden automatically.
