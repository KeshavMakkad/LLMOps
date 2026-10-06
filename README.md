# frugal 💸

**A drop-in layer that cuts LLM spend (semantic cache, context management, prompt compression and
model downshift) and proves, with an eval gate, that answer quality holds.**

| | |
|---|---|
| 🔌 API (Render) | `https://frugal-api.onrender.com` → [`/docs`](https://frugal-api.onrender.com/docs) *(set after deploy)* |
| 📊 Dashboard (Streamlit) | `https://frugal.streamlit.app` *(set after deploy)* |

---

## 1. Problem

A typical RAG app sends every question, with its top-k retrieved chunks, to the strongest model
it uses. Much of that is waste:
- the same question arrives again, reworded;
- most of the retrieved context is irrelevant;
- most questions don't need the strongest model.

Each fix has a quality risk, though:
- a semantic cache can serve the answer to a *different* question;
- compression and truncation can drop the one sentence that mattered;
- a cheaper model can get the arithmetic wrong.

**frugal** applies four levers and measures every one of them, both the saving and the quality
cost, on a fixed request trace. A CI gate refuses any configuration change that saves money by
quietly breaking answers.

## 2. The four levers

| lever | what it does | where |
|---|---|---|
| **Semantic cache** | Exact match, then embedding similarity (bge-small, local), scoped by domain and pasted text. Guarded by a **number guard** (the amounts in both questions must match, with lakh/crore/k normalised) and a **cheap-LLM verifier** ("would the same answer be correct for both?"). Concurrent identical requests are **coalesced** (single-flight). | `frugal/cache.py`, `frugal/api/main.py` |
| **Context-window management** | Retrieve top 8 → cross-encoder **rerank** (ms-marco MiniLM, local) → keep the top 3 → **truncate** to a 450-word budget. | `frugal/context.py` (`build_context`) |
| **Prompt compression** | Query-aware extractive compression, a lightweight stand-in for LLMLingua: split the context into sentences, score each by embedding similarity to the question (plus a bonus for numbers), and keep the best in original order until ~60% of the words remain. | `frugal/context.py` (`compress_chunks`) |
| **Model downshift** | Ordered, versioned rules on request features (pasted text? arithmetic/amounts?). Easy requests go to **Gemma 4 26B-A4B** (a mixture-of-experts model, ~4B active parameters); the rest stay on **Gemini 3.1 Flash-Lite**. | `frugal/router.py`, `configs/policies/*.yaml` |

Each lever is a field in a versioned policy YAML (`configs/policies/`): `naive` (baseline), one
ablation per lever (`cache`, `context`, `compress`, `downshift`), and `optimized` (all levers).

## 3. Architecture

```mermaid
flowchart LR
  Q[question + domain\n(+ pasted text)] --> C{semantic cache\nexact → embedding ≥ τ\n→ number guard → LLM verifier}
  C -- hit --> A[answer\n0 model tokens]
  C -- miss --> R[retrieve top-8\n(local index)] --> RR[cross-encoder rerank\nkeep 3, 450-word budget] --> CP[query-aware\ncompression ~60%] --> RT{downshift rules}
  RT -- easy --> L[Gemma 4 26B-A4B\ncheap tier]
  RT -- numbers / pasted text --> F[Gemini 3.1 Flash-Lite\nstrong tier]
  L & F --> A
  A --> LOG[(request log: tokens, actual $,\nest. $ at paid prices, latency, decisions)]
  subgraph offline [evaluation]
    T[fixed 281-request trace] --> X[replay each policy] --> J[reference-guided judge\n1–5 + bootstrap CI] --> D[dashboard + CI gate]
  end
```

**How an experiment works** (`frugal/experiment.py`):
1. Build the trace (`frugal/trace.py`). For each of the 100 eval questions it includes:
   - the original;
   - a paraphrase (same correct answer);
   - an exact repeat (~30% of questions);
   - for ~half, a **near-miss**: same wording, but a detail that changes the answer
     ("₹15L" → "₹18L", "Pro" → "Free", "tenant" → "landlord").

   `group_id` records which requests may legitimately share an answer. The order is shuffled once
   and fixed.
2. Replay each policy over the trace.
   - Cache decisions are made in arrival order. Hits depend only on earlier *questions*, so the
     misses can then be answered in parallel without changing the outcome.
   - Every model call records the tokens the API reported, the actual cost, the paid-tier
     estimate and the provider latency.
3. Judge every answer that has a reference with a reference-guided LLM judge (1–5;
   `frugal/quality.py`). Compute Δ vs `naive`, paired per request, with a 95% bootstrap CI.
4. The gate (`frugal/gate.py`) fails a policy if any of these hold:
   - quality drops significantly (Δ < −0.25 and the CI excludes 0);
   - the false-hit rate is above 5%;
   - tokens saved are below 20%.

## 4. Numbers

Every table below is printed by `python scripts/readme_numbers.py` from files the commands wrote.
Nothing is typed in by hand. *Est. $* means the measured tokens priced at Google's published
paid rates (Gemini 3.1 Flash-Lite $0.25 / $1.50 from Google's pricing page; Gemma 4 26B-A4B
$0.09 / $0.30 from its OpenRouter listing; per 1M input/output tokens, retrieved 2026-10-06). **Actual spend is $0**, because everything runs on free tiers.

### 4.1 Before / after (`frugal run --max-groups 24 --publish`)

<!-- EXPERIMENT_TABLE -->
*pending: the experiment run is in progress*
<!-- /EXPERIMENT_TABLE -->

### 4.2 Semantic cache: hit rate vs false-hit rate (`frugal sweep`, full 281-request trace)

| design | threshold | hit rate | correct hits | false-hit rate | near-misses served wrongly | verifier calls |
|---|---|---|---|---|---|---|
| embedding only | 0.84 | 63.3% | 39.1% | **38.2%** | 62.5% | 0 |
| embedding only | 0.88 | 59.8% | 40.2% | 32.7% | 56.2% | 0 |
| embedding only | 0.92 | 52.3% | 39.1% | 25.2% | 41.7% | 0 |
| + number guard | 0.84 | 53.7% | 42.3% | 21.2% | 33.3% | 0 |
| + number guard | 0.88 | 52.3% | 42.3% | 19.0% | 29.2% | 0 |
| + number guard | 0.92 | 44.8% | 39.9% | 11.1% | 14.6% | 0 |
| **+ number guard + LLM verifier** | **0.84** | **45.2%** | **45.2%** | **0.0%** | **0.0%** | 135 |
| + number guard + LLM verifier | 0.88 | 44.8% | 44.8% | 0.0% | 0.0% | 130 |
| + number guard + LLM verifier | 0.92 | 40.9% | 40.9% | 0.0% | 0.0% | 104 |

**Why the guards matter.** Paraphrases are on average 0.948 similar to their original question,
and near-misses 0.944. The two populations overlap almost completely, so **no similarity
threshold alone can separate "same question, reworded" from "same wording, different answer"**.
An embedding-only cache at the common 0.92 setting served a wrong answer for 1 in 4 hits.

The number guard is free and halves that. The verifier, one short Flash-Lite call per candidate (Gemini 3.5 Flash-Lite in this sweep),
drives it to zero. It also gives the **most correct hits** of any design: blocking wrong hits
means the right answers get cached for later reuse.

### 4.3 Service load test (`locust -u 50 -r 25 -t 60s`, local, fake model)

This measures the layer's own overhead (cache lookup, embedding, routing), not model latency.
Popular questions are asked repeatedly, so after warm-up 99.95% are cache hits.

| endpoint | requests | req/s | p50 ms | p99 ms | failures |
|---|---|---|---|---|---|
| `POST /v1/answer` | 17,478 | 296.0 | 6 | 55 | 0 |
| `GET /v1/stats` | 2,190 | 37.1 | 5 | 32 | 0 |
| `GET /healthz` | 2,180 | 36.9 | 2 | 20 | 0 |
| **aggregate** | 21,848 | **370.0** | 5 | 52 | **0** |

**Cache stampede, found by this test.** Before request coalescing, 50 concurrent users asking 8
cold questions caused **43 model calls**: identical requests all missed before the first answer
was stored. With single-flight coalescing it took **exactly 8**, and p99 fell from 73 to 55 ms.
`tests/test_experiment_gate_api.py::test_single_flight…` locks this in.

## 5. CI: the eval gate

`.github/workflows/eval-gate.yml` runs on any PR that touches `configs/`, `frugal/cache.py`, `frugal/context.py`, `frugal/router.py` or
`frugal/pipeline.py`:

1. It replays a stratified 24-group slice of the trace through `naive` and the PR's `optimized`.
2. It judges both.
3. It posts the verdict as a sticky PR comment.
4. It fails the check if the change saves money by breaking quality.

`naive`'s calls are served from a shared Postgres response cache, so each PR only pays (in free
quota) for what it changed. *Screenshot pending deployment:* `docs/img/blocked-pr.png`. To
reproduce, see `docs/SETUP.md` §4.

## 6. Eval set and trace

- **100 questions over 4 domains**, grounded in 70 real public documents (≈103k words): Swiggy
  customer support, GitHub developer support, Indian income tax and GST, and Indian legal
  (statutes plus contract clauses).
- **The questions** include 12 adversarial items (should refuse), 12 out-of-scope items (should
  abstain), 12 format-constrained items, 23 multi-hop items and 39 numeric items.
- **The trace adds** 100 paraphrases, 48 near-misses and 33 exact repeats, for 281 requests. See
  `data/trace/variants.jsonl`.
- **Scoring:** a reference-guided LLM judge (Gemini 3.1 Flash-Lite Preview, rubric `grade-v1`, 1–5, pass ≥ 4) for
  quality, and trace labels (`group_id`) for cache correctness. Both are described in
  `frugal/quality.py` and `frugal/trace.py`.

## 7. Observability

- **Per request:** prompt and output tokens (as reported by the API), actual cost ($0), est. cost
  at paid prices, provider latency, and the layer's own overhead. Also every lever decision:
  served from cache, similarity, routing rule and tier, context words before and after.
  - In experiments these are in `results/latest.json` and the dashboard's drill-down tab.
  - In the service they go to the `request_log` table (Neon) and `GET /v1/requests`.
- **Prometheus `/metrics`:**
  - `frugal_requests_total{policy,served_from,tier}`
  - `frugal_tokens_total`
  - `frugal_est_cost_usd_total`
  - `frugal_llm_latency_seconds`
- **Langfuse:** every uncached model call is a traced generation, tagged with policy, request and
  tier.

## 8. Design decisions and trade-offs

| decision | alternative | why (measured where possible) |
|---|---|---|
| Number guard + cheap-LLM verifier on cache candidates | Similarity threshold only | §4.2: no threshold separates paraphrases from near-misses. The guards take false hits from 25–38% to 0% at the cost of 135 tiny calls. |
| Threshold 0.84 (with guards) | 0.92 "safe default" | With the verifier the false-hit rate is 0% at every tested threshold, so the lower threshold buys more correct hits (45% vs 41%). |
| Local embeddings and reranker (fastembed, ONNX) | Gemini embeddings | The Gemini free tier allows 1,000 embedded texts a day; one index needs ~1.5k. Local is $0, quota-free and fits in 512 MB once pre-built. |
| Extractive, query-aware compression | LLMLingua(-2) | LLMLingua needs a ~500 MB+ model, too heavy for the free 512 MB instance. Extractive keeps whole sentences, so numbers stay intact. |
| Strong tier = Gemini 3.1 Flash-Lite, cheap = Gemma 4 26B-A4B | Gemini 3.5 Flash as the strong tier | The 3.5 Flash free tier is capped at 20 requests/day and each Flash-Lite model at 500/day (from the API's own 429s), so the strong tier, judge and sweep verifier use separate models. Gemma 4 26B-A4B is 2.8× cheaper on input and 5× on output at paid prices. |
| Rules-based downshift | Learned router | Transparent, versioned and reviewable in a PR, and enough to show the gate catching a bad rule. A learned router is future work. |
| Judge = Gemini 3.1 Flash-Lite Preview with the reference answer | Strong judge, no reference | Reference-guided grading is an easier task, so a cheap judge is adequate. It's a different model from both tiers, with its own quota. Being Gemini-family, any self-preference would favour the strong tier, which makes the downshift result conservative. The judge's own agreement isn't separately calibrated (see limitations). |
| Cache decisions sequential, generation parallel | Fully sequential replay | Identical results, roughly 6× faster on free-tier rate limits. |
| Single-flight request coalescing | None | §4.3: 43 → 8 model calls under concurrency. |

## 9. Setup

See [`docs/SETUP.md`](docs/SETUP.md). In short: a Gemini API key (free), plus Neon, Render and
Streamlit Cloud accounts (free); Langfuse is optional.

```bash
pip install -e ".[dev,ui,tracing]" && cp .env.example .env   # add GEMINI_API_KEY
frugal build-index && frugal sweep && frugal run --max-groups 24 --publish
streamlit run dashboard/app.py
pytest -q    # hermetic, no keys
```

## 10. Limitations

- The eval set, paraphrases and near-misses are LLM-drafted from real documents (see §6).
- The cache threshold was chosen on the same trace it's reported on. With the verifier the
  false-hit rate is 0% at all tested thresholds, which makes this less sensitive, but a held-out
  trace is the honest next step.
- The judge (Gemini 3.1 Flash-Lite Preview) is not calibrated against human labels in this project.
- Free-tier daily quotas make a full-trace experiment span more than a day; results here use a
  stratified slice, with the size stated next to every number.
- The cache is in-process, one per instance. Multiple instances would need a shared store
  (pgvector).

## 11. Resume line

> Built **frugal**, an LLM cost-optimisation layer (semantic cache with number-guard + LLM
> verification, cross-encoder rerank/truncation, query-aware prompt compression, rules-based model
> downshift) with eval-gated quality bounds in CI. It cut token spend by **X%** at a **Y** quality
> change (95% CI) on a 4-domain request trace, and took cache false hits from 25% to 0%.
