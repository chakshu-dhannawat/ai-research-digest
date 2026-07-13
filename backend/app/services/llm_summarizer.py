import json
import logging
import re

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Ordered LLM endpoints, highest priority first. The resolver tries each in
# order: the first reachable endpoint serving a usable model wins. WITHIN an
# endpoint it prefers the configured model but self-heals to whatever IS served
# (the vLLM boxes occasionally rename/swap models, and other models may be
# deployed on the same endpoint). A new pipeline run re-evaluates from the top.
#
# DISABLED — DeepSeek on macdep01:8001 must NOT be used (kept for reference):
#   {"base_url": "http://macdep01.tdc.otsuka-shokai.co.jp:8001/v1", "model": "DeepSeek-V4-Flash"},
LLM_ENDPOINTS = [
    {"base_url": settings.llm_base_url, "model": settings.llm_model},                    # Qwen  — default
    {"base_url": settings.llm_fallback_base_url, "model": settings.llm_fallback_model},  # MiniMax — fallback
]

# Output token budget per call. The default Qwen3.5 endpoint has a 128k context,
# so there is ample headroom; 4000 comfortably fits full summaries for a batch.
_max_tokens: int = 4000

_resolved: tuple[OpenAI, str] | None = None


def _resolve() -> tuple[OpenAI, str]:
    """Return (client, model) for the highest-priority reachable endpoint.

    Tries each endpoint in LLM_ENDPOINTS order; within an endpoint, prefers the
    configured model but self-heals to any served model. Cached until
    reset_llm_resolution() (called at the start of each pipeline run) so a
    recovered primary endpoint is picked up again instead of sticking on the
    fallback forever."""
    global _resolved
    if _resolved:
        return _resolved
    last_err = None
    for ep in LLM_ENDPOINTS:
        base, preferred = ep.get("base_url"), ep.get("model")
        if not base:
            continue
        try:
            client = OpenAI(base_url=base, api_key=settings.llm_api_key, timeout=60)
            served = [m.id for m in client.models.list().data]
            if not served:
                logger.warning("LLM endpoint %s serves no models; trying next", base)
                continue
            model = preferred if preferred in served else served[0]
            if preferred not in served:
                logger.warning("Preferred model %r not served at %s; using %r (served: %s)",
                               preferred, base, model, served)
            logger.info("LLM resolved: %r @ %s", model, base)
            _resolved = (client, model)
            return _resolved
        except Exception as e:
            last_err = e
            logger.warning("LLM endpoint %s unreachable (%s); trying next", base, e)
            continue
    raise RuntimeError(f"No LLM endpoint reachable; last error: {last_err}")


def reset_llm_resolution() -> None:
    """Clear the cached endpoint/model so the next call re-evaluates from the top
    of LLM_ENDPOINTS. Called at the start of each pipeline run to recover the
    primary endpoint after a transient outage."""
    global _resolved
    _resolved = None


def current_model() -> str:
    """Name of the model actually used for scoring (resolved, self-healing).
    For audit/logging — recorded against each newsletter."""
    return _resolve()[1]


SYSTEM_PROMPT = """\
You are a principal AI engineer curating a daily digest for the Advanced AI Research \
Section (先端AI研究課) of the Multi-AI Center at Otsuka Corporation — an applied-AI \
research and platform team that owns the full vertical: training and adapting models on \
on-prem H100/H200 hardware, building retrieval and agent infrastructure, and shipping \
production assistants. You evaluate GitHub repos, research papers, model releases, and \
AI blog/lab posts.

The readers are expert AI researchers and engineers. This digest keeps the TEAM at the \
frontier and FILLS KNOWLEDGE GAPS — surface what is NEW, deep, or non-obvious across the \
lab's remit. They already know the popular tools and the basics; do not waste their time \
on those.

The lab's DEFINING constraint is Japanese enterprise data (quotations, orders, billing, \
support threads, sales reports), where off-the-shelf models, tokenizers, and text \
analyzers degrade measurably. Anything that improves Japanese / CJK / multilingual model \
behavior, tokenization, or low-resource adaptation is unusually valuable here.

What the lab actually works on (score against the WHOLE team, not any one person):
- Model adaptation: SFT, instruction tuning, RLHF/DPO/GRPO across 10+ models; LoRA/QLoRA \
and full-parameter fine-tuning on multi-node GPUs; continual pretraining on open bases; \
model merging; knowledge distillation.
- Tokenizer & vocabulary engineering: domain / Japanese token sets, training tokenizers, \
adding low-frequency terms.
- Retrieval & search: hybrid retrieval over Elasticsearch with Japanese analyzers fused \
with dense vectors; ANN indexing (HNSW, IVF, PQ); reranking; domain fine-tuned EMBEDDING \
models (the team's highest-leverage lever); knowledge graphs and Graph-RAG for multi-hop.
- Document intelligence: OCR and PDF preprocessing APIs; VLM-based document parsing; \
chart/table extraction; shared text+image embedding indexes; multimodal RAG.
- Agentic systems: MCP servers, agent harness/orchestration, multi-agent reliability, \
memory and planning, context engineering, tool-use, evals.
- Efficient serving & inference: vLLM internals, quantization (GPTQ, AWQ, FP8, BitNet), \
KV-cache, speculative decoding, MoE, multi-node serving, Ray.
- Speech: Whisper-class Japanese STT, Japanese/English code-switching.
- Evaluation: domain-specific benchmark design and human evaluation; prompting best \
practices.
- Applied products: knowledge-management QA, quotation/FAQ assistants, sales pre-visit \
bots on Databricks, microlearning and skill extraction, enterprise search, video search.

Tech the team ALREADY runs (so merely using these is NOT noteworthy): vLLM, LiteLLM, \
Langflow, LibreChat, Elasticsearch, LangChain, LlamaIndex, MCP, PyTorch, Ray, Databricks, \
PostgreSQL, Redis, FAISS, Docker, Kubernetes.

For each item, produce four things:

1. **Relevance score** (integer 0-10) = MARGINAL VALUE to this expert team: how much NEW, \
important, actionable knowledge it adds to the workstreams above. Popularity, stars, and \
hype are NOT value. Score on an ABSOLUTE scale — judge each item against the rubric below, \
NOT against the other items in this batch — so scores stay comparable across the whole run. \
When unsure between two bands, choose the LOWER one. High scores must be EARNED and are \
rare; most items land in 3-6.
   A 9-10 requires ALL THREE: (a) a genuinely NEW technique/result/capability, (b) enough \
technical DEPTH to act on (explains HOW, with methods/benchmarks/numbers), and (c) a clear \
map to a current lab workstream above. Missing any one caps the score at 7-8 or below.
   - UP-WEIGHT: novel post-training / fine-tuning methods (LoRA/QLoRA, SFT, RLHF, DPO, \
GRPO, distillation, continual pretraining, model merging); tokenizer/vocabulary work and \
Japanese/CJK/multilingual/low-resource adaptation (CENTRAL — weight extra); embedding-model \
training, hybrid retrieval, reranking, ANN tuning, Graph-RAG; quantization & efficient \
inference (GPTQ, AWQ, FP8, BitNet, KV-cache, speculative decoding, vLLM internals, MoE, \
multi-node/Ray); agentic reliability, context engineering, MCP, evals; VLM / document AI \
(OCR, layout, chart/table extraction, multimodal RAG); Japanese ASR / code-switching; \
evaluation & benchmarking methodology; LLM reasoning, long-context, security. Deep \
engineering write-ups that explain HOW (top lab engineering blogs, e.g. Anthropic \
Engineering, are high-signal — boost them); a real new model/capability from a major lab.
   - GAPS: give EXTRA weight to strong material BEYOND the team's current daily stack \
(advanced evals, agent reliability, quantized/multi-node serving, ANN tuning, tokenizer \
methods, VLM document pipelines, distillation).
   - DOWN-WEIGHT (1-3): famous tools the team already knows UNLESS a substantively NEW \
capability — high stars or "trending" do NOT raise the score; beginner tutorials, "build \
your first X", awesome-lists; marketing/PR, funding/business news, opinion, listicles; \
minor version bumps.
   - OFF-DOMAIN: the lab is software + enterprise, not physical AI. Treat embodied AI, \
robotics, autonomous driving, and physical simulation as an off-scope APPLICATION and \
down-weight accordingly — BUT if such work introduces a transferable METHOD (a \
post-training/RL algorithm, a quantization or multimodal technique), score that method on \
its merits rather than zeroing it.
   Bands: 9-10 = must-read, new + deep + on-topic (rare); 7-8 = valuable new technique / \
paper / high-signal engineering post; 4-6 = incremental, partly known, or niche; 1-3 = \
established-with-nothing-new, beginner, marketing, or off-scope application (EVEN if very \
popular); 0 = noise or content-free.
   Anchors: new Japanese-tokenizer or LoRA/quantization/ANN/embedding technique, or a deep \
Anthropic-Engineering agent-loops post -> 8-10; bare "LangChain"/"transformers"/famous \
mega-repo -> 1-3 (even 100k+ stars); "build your first RAG app" or funding news -> 1-2; \
robotics/embodied-AI application with no transferable method -> 1-2.

2. **Summary** (2-3 sentences): Explain WHAT the item is (its core \
contribution or purpose) and WHY it matters technically (what problem it \
solves, what improvement it offers, or why the approach is notable). Be \
specific — mention model names, benchmarks, techniques, or key numbers \
ONLY when they appear in the provided text. NEVER invent or guess \
parameter counts, model sizes, benchmark scores, context lengths, or dates \
that are not given — if a spec is not in the input, describe it qualitatively \
instead (e.g. "a new VLM" not "a 41B VLM"). Avoid vague praise.

3. **Application** (1-2 sentences): Concretely describe how the LAB could apply this in \
its work. Be SPECIFIC — reference the team's actual stack and workstreams: improving \
hybrid Elasticsearch + vector retrieval and reranking, fine-tuning Japanese embedding \
models, LoRA/QLoRA or full post-training of Japanese LLMs on multi-node vLLM, tokenizer / \
vocabulary engineering, quantized multi-node serving, VLM-based document pipelines, \
Graph-RAG, MCP / agent orchestration, Japanese ASR, or the quotation/FAQ, KMS, sales \
pre-visit, and microlearning assistants. Don't be generic.

4. **Keywords** (array of 3-5 short lowercase tags): specific CONTENT topics — \
techniques, model families, domains (e.g. "rag", "lora", "vllm", "agents", \
"quantization", "vlm", "document-ai"). NOT the source name.

Return ONLY a JSON array of SCORED results — do NOT echo or repeat the input. One object \
per item, same index. Each object MUST contain index, score (0-10 integer), summary, \
application, keywords — no other fields, no markdown fences, no commentary:
[{"index": 0, "score": 8, "summary": "...", "application": "...", "keywords": ["rag","vllm"]}, ...]"""


# String-valued fields the model emits. Used to repair a recurring DeepSeek-V4
# defect where the OPENING quote of a string value is dropped (e.g.
# `"summary_ja": Sean...",` instead of `"summary_ja": "Sean...",`), which
# otherwise makes the whole batch unparseable and silently fall back to English.
_STRING_VALUE_KEYS = r"(?:summary_ja|application_ja|summary|application)"


def _repair_unquoted_values(text: str) -> str:
    """Insert a missing opening quote after a string key's colon. A properly
    quoted value (next char is '"') or an empty/array/object value is left
    untouched; only a bare value (starts with a letter/digit/CJK char) is fixed."""
    return re.sub(
        rf'("{_STRING_VALUE_KEYS}"\s*:\s*)(?=[^"\s,}}\]])',
        r'\1"',
        text,
    )


def _extract_json_array(raw: str) -> list[dict]:
    """Extract a JSON array from LLM output, handling markdown fences and
    surrounding prose robustly."""
    text = raw.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the outermost JSON array brackets
    start = text.find("[")
    if start != -1:
        text = text[start:]

    # Try as-is, then trimmed to the last complete object + a closing ']'. The
    # model often omits the array's closing bracket; a naive rfind(']') would
    # instead catch a keywords-array ']' and chop off the last item — so rebuild
    # the close from the last '}'. This also strips any trailing prose. Each form
    # is also tried after repairing dropped opening quotes on string values.
    last_brace = text.rfind("}")
    trimmed = text[: last_brace + 1] + "]" if last_brace != -1 else None
    candidates = [text]
    if trimmed:
        candidates.append(trimmed)
    candidates.append(_repair_unquoted_values(text))
    if trimmed:
        candidates.append(_repair_unquoted_values(trimmed))
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue

    # Last resort: recover the array object-by-object so one bad item doesn't
    # zero the whole batch (repair dropped quotes here too).
    objs = []
    for m in re.finditer(r"\{[^{}]*\}", text):
        for chunk in (m.group(0), _repair_unquoted_values(m.group(0))):
            try:
                objs.append(json.loads(chunk))
                break
            except json.JSONDecodeError:
                continue
    if objs:
        return objs
    raise json.JSONDecodeError("no JSON array found", text, 0)


def score_and_summarize(items: list[dict]) -> list[dict]:
    if not items:
        return []

    # The serving model has a 4096-token total context, so batch input + output
    # must stay well under that. Batch 3 leaves room for the rubric prompt plus
    # full output for every item (batch 4 truncated the last item's JSON).
    batch_size = 3
    results = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        # Present items as PLAIN TEXT (not JSON) so the weak model can't just echo
        # the input array back — it must emit fresh scored JSON.
        blocks = []
        for j, item in enumerate(batch):
            title = item.get("title") or item.get("name", "")
            block = [f"[{j}] source={item.get('source')} | {title}"]
            meta = []
            if item.get("stars") is not None:
                meta.append(f"stars={item.get('stars')}")
            if item.get("topics"):
                meta.append("topics=" + ", ".join(str(t) for t in item.get("topics", [])))
            if meta:
                block.append("  " + " | ".join(meta))
            desc = (item.get("description") or "")[:350]
            if desc:
                block.append("  desc: " + desc)
            readme = (item.get("readme_snippet") or "")[:400]
            if readme:
                block.append("  readme: " + readme)
            blocks.append("\n".join(block))
        user_content = "Score each item below; output ONLY the JSON array.\n\n" + "\n\n".join(blocks)

        try:
            client, model = _resolve()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                max_tokens=_max_tokens,
            )
            raw = (resp.choices[0].message.content or "").strip()
            scored = _extract_json_array(raw)

            for entry in scored:
                idx = entry.get("index", 0)
                if 0 <= idx < len(batch):
                    batch[idx]["relevance_score"] = entry.get("score", 0)
                    batch[idx]["summary"] = entry.get("summary", "")
                    batch[idx]["application"] = entry.get("application", "")
                    batch[idx]["keywords"] = _clean_keywords(entry.get("keywords"))

            results.extend(batch)
        except Exception as e:
            logger.error("LLM scoring failed for batch %d: %s", i, e)
            for item in batch:
                item["relevance_score"] = 0
                item["summary"] = item.get("description", "")[:200]
                item["application"] = ""
                item["keywords"] = []
            results.extend(batch)

    return results


def _clean_keywords(kw) -> list[str]:
    """Normalize the model's keywords to <=5 short lowercase tags."""
    if isinstance(kw, str):
        kw = kw.split(",")
    if not isinstance(kw, list):
        return []
    out = []
    for t in kw:
        t = str(t).strip().lower()
        if t and len(t) <= 30 and t not in out:
            out.append(t)
    return out[:5]


_TRANSLATE_SYSTEM_PROMPT = """\
You are a professional translator producing a Japanese AI digest for the Advanced AI \
Research Section of the Multi-AI Center at Otsuka Corporation. Translate the SUMMARY and \
APPLICATION of each item into natural, \
professional Japanese using business 敬語. Keep technical terms, model names, benchmarks, \
and proper nouns accurate (you may keep well-known English product/technique names as-is). \
Do NOT translate titles.

Return ONLY a JSON array — no markdown fences, no commentary. One object per item, same \
index, with the Japanese translations:
[{"index": 0, "summary_ja": "...", "application_ja": "..."}, ...]"""


def translate_items_to_japanese(items: list[dict]) -> list[dict]:
    """Return COPIES of items with `summary` and `application` translated to
    professional Japanese (敬語). `title` and all other fields are unchanged.
    On failure for a batch/item, falls back to the original English text."""
    if not items:
        return []

    out = [dict(item) for item in items]

    batch_size = 3
    for i in range(0, len(out), batch_size):
        batch = out[i : i + batch_size]
        # Present items as PLAIN TEXT (not JSON) so the model can't just echo the
        # input array back — it must emit fresh translated JSON.
        blocks = []
        for j, item in enumerate(batch):
            block = [f"[{j}]"]
            block.append("  summary: " + (item.get("summary") or ""))
            block.append("  application: " + (item.get("application") or ""))
            blocks.append("\n".join(block))
        user_content = (
            "Translate each item's summary and application into Japanese; "
            "output ONLY the JSON array.\n\n" + "\n\n".join(blocks)
        )

        try:
            client, model = _resolve()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _TRANSLATE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                max_tokens=_max_tokens,
            )
            content = (resp.choices[0].message.content or "").strip()
            translated = _extract_json_array(content)

            for entry in translated:
                idx = entry.get("index", -1)
                if 0 <= idx < len(batch):
                    summary_ja = entry.get("summary_ja")
                    application_ja = entry.get("application_ja")
                    if summary_ja:
                        batch[idx]["summary"] = summary_ja
                    if application_ja:
                        batch[idx]["application"] = application_ja
        except Exception as e:
            logger.error("Japanese translation failed for batch %d: %s", i, e)
            # Leave the original English text in place for this batch.

    return out


def extract_keywords(items: list[dict]) -> list[dict]:
    """Lightweight keywords-only pass for backfilling existing catalog items.
    Each input item needs id/title/summary; returns [{id, keywords}]."""
    if not items:
        return []

    sys_prompt = (
        "For each item, return 3-5 short lowercase CONTENT keywords (techniques, "
        "model families, domains — e.g. \"rag\", \"vllm\", \"agents\"). "
        "Return ONLY a JSON array: [{\"index\":0,\"keywords\":[\"rag\",\"vllm\"]}, ...]"
    )
    out = []
    batch_size = 8
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        payload = [
            {"index": j, "title": it.get("title", ""), "summary": (it.get("summary") or "")[:200]}
            for j, it in enumerate(batch)
        ]
        try:
            client, model = _resolve()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=600,
            )
            parsed = _extract_json_array((resp.choices[0].message.content or "").strip())
            kw_by_idx = {e.get("index", -1): _clean_keywords(e.get("keywords")) for e in parsed}
            for j, it in enumerate(batch):
                out.append({"id": it.get("id"), "keywords": kw_by_idx.get(j, [])})
        except Exception as e:
            logger.warning("Keyword backfill failed for batch %d: %s", i, e)
            for it in batch:
                out.append({"id": it.get("id"), "keywords": []})
    return out
