# LLM Scoring Models — Why-LLM vs MiMo-V2.5

The newsletter pipeline scores/summarizes every fetched item with an OpenAI-compatible
LLM. Two are wired up. **Why-LLM is the default for cron and all normal jobs**; the
MiMo "foundry" endpoint is kept in `.env` for ad-hoc/manual runs.

## Endpoints & config

| | **Why-LLM** (default) | **MiMo-V2.5** (ad-hoc) |
|---|---|---|
| Env vars | `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | `ANTHROPIC_FOUNDRY_BASE_URL` / `ANTHROPIC_FOUNDRY_API_KEY` / `FOUNDRY_MODEL` |
| Base URL | `macdep01…:8001/v1` (vLLM) | `macdep01…:8008/v1` (LiteLLM proxy) |
| Model id | `Why-LLM` | `anthropic-MiMo-V2.5` |
| Context window | **4096 tokens** (small) | Large (reasoning-grade) |
| Type | Standard chat model | **Reasoning model** (hidden `reasoning_content`) |
| Used by | Cron + UI test sends | Manual one-off runs only |

## Behavior differences

| Aspect | Why-LLM | MiMo-V2.5 |
|---|---|---|
| **Speed** | ~1 s/item (4 items in **4.2 s**) | ~6.5 s/item (4 items in **26.3 s**) — **~6× slower** |
| **Batch settings** | `batch_size=5`, `max_tokens=1600` (must fit 4096 ctx) | needs `max_tokens≈16000` — reasoning consumes the budget before the JSON answer |
| **Failure mode** | occasionally drops a single item to `None` (malformed JSON), recovered object-by-object | returns `content=None` (empty) if the token budget is too small → whole batch falls back to 0 |
| **Edge-case nuance** | sometimes terse / drops borderline items | stronger reasoning on borderline items |
| **Cost of a full run** | ~3–4 min for ~120 items | ~13–15 min for ~120 items |

> ⚠️ The first MiMo test send (newsletter #25) came out **all 0/10** precisely because
> `max_tokens=1600` (sized for Why-LLM) was too small for MiMo's reasoning — it emitted
> no answer content. Fixed by making `_max_tokens` overridable (→ 16000) and guarding
> `None` content.

## Scoring quality — identical 4-item sample

| Item | Why-LLM | MiMo-V2.5 |
|---|---|---|
| vLLM (inference engine) | **9/10** — `vllm, inference, pagedattention, gpu-memory, serving` | **9/10** — `vllm, llm, inference, gpu, optimization` |
| zai-org/GLM-5.2 (model release) | **6/10** — `glm, llm-release, evaluation, enterprise` | **5/10** — `glm, llm, model-release, fine-tuning, multilingual` |
| Hybrid dense-sparse RAG (paper) | **8/10** — `rag, hybrid-search, bm25, retrieval, elasticsearch` | **8/10** — `rag, hybrid-retrieval, bm25, dense-vectors, elasticsearch` |
| "Show HN: a toy vector database" | **dropped** (`None`, malformed entry) | **2/10** — `vector-database, hobby, toy, experimental` ("not for production") |

**Takeaways**
- Scores agree closely on the substantive items (±1).
- Keyword quality is comparable; both correctly emit brand/content tags (`vllm`, `glm`, `rag`).
- MiMo handled the low-value edge case more gracefully (scored + explained it), where Why-LLM
  dropped it. MiMo's reasoning gives slightly more nuanced summaries.

## Recommendation

- **Keep Why-LLM as the default** for the daily cron and UI test sends: it's ~6× faster, which
  keeps the ~120-item run inside the pre-09:00 delivery window, and its quality is on par for the
  bulk of items.
- **Use MiMo-V2.5 ad-hoc** when you want higher-nuance scoring on a smaller set and don't mind the
  ~13–15 min runtime. It's configured and ready in `.env`; a run just overrides the client/model/
  token budget for that process — it never changes the live default.
