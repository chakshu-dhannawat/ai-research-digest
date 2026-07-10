# Agentic Patterns in This Codebase

## Honest Answer First: Is This an Agentic System?

**No.** This system does not use an agentic framework (no LangChain agents, no LangGraph, no AutoGen, no CrewAI). The LLM does **not** decide what to fetch, does **not** use tools, and does **not** loop or self-correct. There is no planning step.

What it IS is a **deterministic pipeline with an LLM inside one step**. Understanding the distinction is important — most production AI systems are closer to this than to true agents.

---

## The Agentic Spectrum

```
Deterministic Pipeline ◄──────────────────────────────────► True Agentic System
        │                                                              │
  LLM called once,                                         LLM decides every step,
  fixed input/output,                                      picks tools, loops,
  hardcoded flow                                           self-corrects, plans
        │                                                              │
  ┌─────┴─────┐                               ┌─────────────────────┐ │
  │ THIS SYSTEM│                              │  LangGraph, AutoGen │ │
  │  pipeline  │                              │  CrewAI, ReAct      │─┘
  └────────────┘                              └─────────────────────┘
```

This system sits firmly on the **left** — and that's a deliberate, good engineering decision.
The LLM is used for what it's genuinely better at (evaluation + language) while Python handles what Python is better at (fetching, routing, scheduling, DB writes).

---

## What Framework Is Used?

| Concern | Tool |
|---------|------|
| Pipeline orchestration | Plain Python (`pipeline.py`) |
| LLM calls | `openai` Python SDK (pointed at a self-hosted vLLM endpoint) |
| LLM model | Why-LLM (DeepSeek-based, served on `macdep01:8001` via vLLM) |
| Scheduling | APScheduler (`AsyncIOScheduler`) |
| Web API | FastAPI |
| HTTP fetching | `httpx`, `PyGithub`, `duckduckgo-search` |

No LangChain, no LangGraph, no vector store, no embeddings, no memory management framework.

---

## What the LLM Actually Does

The LLM is called in exactly **two** roles, both one-shot (no loops, no tools):

### Role 1: Batch Evaluator / Judge

```
Input:  Plain-text list of 3 items (title, source, description, readme snippet)
Output: JSON array with score, summary, application, keywords for each item

[0] source=arxiv | FlashAttention-3: Fast and Accurate Attention
  stars=None | topics=cs.CL
  desc: We present FlashAttention-3, a new algorithm for attention...

[1] source=github | langchain-ai/langchain
  stars=95000 | topics=llm, agents
  desc: Build LLM-powered applications...

→ LLM returns:
[
  {"index": 0, "score": 9, "summary": "...", "application": "...", "keywords": ["attention","inference"]},
  {"index": 1, "score": 2, "summary": "...", "application": "...", "keywords": ["langchain"]}
]
```

The LLM is acting as a **judge** — applying a scoring rubric to a fixed set of inputs. This is one of the most reliable LLM use patterns because:
- The task is well-defined and bounded
- Output format is strictly specified
- Temperature is 0 (deterministic)
- Failure fallback exists (score=0, use original description)

### Role 2: Translator

```
Input:  English summary + application text for 3 items
Output: Japanese translations of each

→ Same one-shot pattern, structured JSON output, temperature=0
```

---

## The "Research Agent" — What It Actually Is

The phrase "research agent" is a useful mental model but the actual implementation is pure Python with zero LLM involvement:

```
"Research Agent" = news_fetcher.py + github_crawler.py
```

Here's what each "research step" actually does:

### Step 1: GitHub Crawler (`github_crawler.py`)
```python
AI_SEARCH_QUERIES = [
    "LLM OR large-language-model OR GPT",
    "AI agent OR agentic OR multi-agent",
    "RAG OR retrieval-augmented OR vector-database",
    "fine-tuning OR RLHF OR DPO OR alignment",
    "diffusion OR multimodal OR vision-language",
]

# For each query, run two hardcoded sub-searches:
#   1. Brand new repos (created last 7 days, stars > 5)
#   2. Fast-growing repos (last month, 10-5000 stars)
# Then enrich each result with README text using ThreadPoolExecutor
```
Decision logic: **zero**. All 5 queries are hardcoded. The "research strategy" is predetermined by a developer.

### Step 2: HuggingFace Daily Papers (`news_fetcher.py`)
```python
dates = [today, yesterday]
for date in dates:
    papers = GET https://huggingface.co/api/daily_papers?date={date}
    top_5 = sorted(papers, by_upvotes)[:5]
```
Fetches a ranked list and takes the top 5. No LLM, no decisions — just an API call and a sort.

### Step 3: arXiv (`news_fetcher.py`)
```python
ARXIV_QUERIES = ["cat:cs.AI", "cat:cs.CL", "cat:cs.CV", "cat:cs.LG"]
# Fetch latest 3 papers per category via RSS
```
Hardcoded categories. Static query.

### Step 4: RSS Feeds (labs, voices, newsletters)
```python
AI_LABS_FEEDS = [("OpenAI", "...rss.xml"), ("Google DeepMind", "..."), ...]
AI_VOICES_FEEDS = [("Eugene Yan", "..."), ("Chip Huyen", "..."), ...]
# Parse XML, filter by recency (14 days), return items
```
Deterministic list maintained by a developer.

### Step 5: Web Search (`news_fetcher.py`)
```python
with DDGS() as ddgs:
    results = ddgs.news("AI LLM 2025", max_results=5)
```
DuckDuckGo keyword search. Hardcoded query string.

**Summary:** The "research" step is a **fixed data ingestion pipeline**, not an agent. The sources, queries, and strategies are all predetermined by developer decisions in code, not by an LLM reasoning about what to look for.

---

## Patterns That ARE Used Here

Even though this isn't an agent, it uses several patterns that appear in agentic systems:

### Pattern 1: LLM as Judge / Evaluator
The most practical agentic primitive. Instead of using the LLM to generate content, use it to evaluate or rank a set of inputs.

```
Human curated a scoring rubric → LLM applies it consistently at scale
```

This is a production-safe pattern because: bounded input, structured output, verifiable results, cheap to retry on failure.

### Pattern 2: Structured Output Extraction
Force the LLM to return parseable data rather than prose.

```python
# System prompt ends with strict format spec:
"Return ONLY a JSON array ... no markdown fences, no commentary:
[{'index': 0, 'score': 8, 'summary': '...', 'keywords': ['rag']}, ...]"

# temperature=0 — no randomness
# _extract_json_array() — multi-level fallback parser if LLM wraps in markdown
```

This pattern + `temperature=0` makes LLM output as predictable as a deterministic function.

### Pattern 3: Prompt as Policy
The `SYSTEM_PROMPT` in `llm_summarizer.py` encodes the entire decision policy:
- Who is the reader
- What they already know (so don't repeat it)
- What topics to up-weight and why
- What to down-weight and why
- Score anchors with concrete examples

The rubric IS the agent's "brain". Improving it changes behavior system-wide — no code change needed.

### Pattern 4: Self-Healing Model Resolver
```python
def _resolve_model() -> str:
    served = [m.id for m in _client.models.list().data]
    if settings.llm_model in served:
        return settings.llm_model
    elif served:
        logger.warning("Falling back to %r", served[0])
        return served[0]    # use whatever is actually served
```
The system detects at runtime that the configured model name doesn't match what's available and adapts. This is a micro-agentic pattern: observe → decide → act (within a fixed decision tree).

### Pattern 5: Graceful Degradation
```python
except Exception as e:
    logger.error("LLM scoring failed for batch %d: %s", i, e)
    for item in batch:
        item["relevance_score"] = 0       # safe default
        item["summary"] = item.get("description", "")[:200]   # fall back to raw
```
The pipeline never crashes on LLM failure. Failed items get score=0 and are filtered out at the top-10 selection stage. Resilience without a retry loop.

---

## What True Agentic Patterns Would Look Like Here

If you wanted to make this system more agentic, here's what that would look like and the trade-offs:

### ReAct Agent for Research
Instead of hardcoded RSS feeds, the LLM could decide where to look:
```
LLM: "I should search for recent RAG papers on arXiv"
→ Tool call: arxiv_search("RAG long-context 2025")
LLM: "I should also check if MiniMax posted anything"
→ Tool call: fetch_blog("minimaxi.com/news")
LLM: "That's enough, I have 20 items"
→ Done
```
**Trade-off:** Unpredictable, harder to debug, LLM may miss obvious sources or loop. The hardcoded approach ensures every source is always checked.

### LLM-Driven Dedup / Clustering
Instead of hash-based dedup, an LLM could cluster semantically similar items:
```
"These 3 items are all about the same Flash Attention paper — keep the best one"
```
**Trade-off:** Expensive (embeddings or LLM call per item pair), slower, harder to verify.

### Agentic Newsletter Editor
Instead of "top 10 by score", an LLM could reason about the final selection:
```
"I have 3 RAG papers and 4 agent papers. The reader saw a lot of RAG last week.
I'll prioritize the agent papers and include only the best RAG paper."
```
**Trade-off:** Non-deterministic, hard to explain why certain items were excluded.

**The current approach** — deterministic scoring, sort, take top 10 — is transparent, auditable, and fast. You can explain exactly why each item was or wasn't included.

---

## How This Would Evolve Into an Agentic System

A natural next step would be using the LLM to select sources dynamically:

```python
# Future: LLM decides search strategy based on recent coverage gaps
strategy = llm.decide_research_strategy(
    recent_topics=last_7_days_keywords,
    covered_sources=last_run_sources,
)
# strategy.extra_queries = ["sparse attention mechanisms", "MoE routing"]
# strategy.skip_sources = ["github"]  # already heavy this week
```

This keeps the LLM where it adds value (reasoning about gaps) while Python handles execution (the actual fetches). This hybrid is the sweet spot for most production AI systems.

---

## Summary

| Question | Answer |
|----------|--------|
| Is this an agentic system? | No — deterministic pipeline with LLM inside one step |
| What framework? | Plain Python + OpenAI SDK. No LangChain/AutoGen/CrewAI |
| What does the LLM decide? | Score + summary + application for each item, in one shot |
| Does the LLM choose what to fetch? | No — hardcoded queries and feeds |
| Does the LLM loop or self-correct? | No — one call per batch, fallback on failure |
| LLM call pattern | `system prompt (rubric) + user (plain-text items) → JSON array` |
| Temperature | 0 — fully deterministic |
| Where is the "agent brain"? | The SYSTEM_PROMPT in `llm_summarizer.py` |
