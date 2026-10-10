# frugal 💸

**A drop-in layer that cuts LLM spend (semantic cache, context management, prompt compression and
model downshift) and proves, with an eval gate, that answer quality holds.**

| | |
|---|---|
| 🔌 API (Render) | [frugal-api-9x10.onrender.com](https://frugal-api-9x10.onrender.com/docs) (interactive docs at `/docs`) |
| 📊 Dashboard (Streamlit) | [frugal-llmops.streamlit.app](https://frugal-llmops.streamlit.app) |

The live API runs on Render's free 512 MB instance, which can't hold both local ONNX models, so it
runs with `FRUGAL_RERANK=off` (context is still trimmed to the top 5 chunks within 750 words, in
retrieval order). All numbers below come from evaluation runs with the cross-encoder on.

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

**ML problem.** Input: a question, its domain and optional pasted text. Output: a grounded answer.
For each request the layer decides whether to serve a cached answer, how much context to send and
which model tier to call. The target is the cheapest path whose answer still scores like the
baseline's.

**Requirements** (the first three are enforced by the gate, §5):
- quality: no significant drop vs `naive` (judge Δ ≥ −0.25, or the 95% CI includes 0);
- cache correctness: false-hit rate ≤ 5%;
- savings: ≥ 20% of tokens vs `naive`;
- cost and footprint: $0 actual spend, a 512 MB host, at most 300 live model calls a day
  (`FRUGAL_MAX_DAILY_CALLS`; cache hits don't count);
- overhead: the layer itself must stay small next to model latency (measured p99 55 ms, §4.3).

**Scope.** In: the cost layer in front of a RAG app, for 4 domains. Out: the chat UI, user
accounts, training or fine-tuning models, and a learned router.

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

### 4.1 Before / after (`frugal run --max-groups 24 --publish`, 79 requests, 55 graded)

<!-- EXPERIMENT_TABLE -->
Run `20261007-123523`: 79 requests, 24 question groups, kinds {'original': 24, 'paraphrase': 24, 'near_miss': 24, 'repeat': 7}; judge `gemini-judge` (grade-v1).

| policy | tokens | tokens saved | model calls | cache hit / false-hit | cheap tier | quality (1–5) | Δ quality vs naive [95% CI] | pass rate | p50 / p99 ms | est. $ at paid prices* |
|---|---|---|---|---|---|---|---|---|---|---|
| `naive` | 181,088 | 0% | 79 | 0% / 0% | 0% | 4.40 | – | 84% | 5084 / 15089 | $0.0650 |
| `aggressive` | 51,184 | 72% | 50 | 37% / 3% | 16% | 3.67 | -0.73 [-1.05, -0.44] | 58% | 4648 / 20221 | $0.0206 |
| `cache` | 119,675 | 34% | 50 | 37% / 3% | 0% | 4.38 | -0.02 [-0.09, +0.04] | 82% | 2474 / 13123 | $0.0426 |
| `compress` | 140,638 | 22% | 79 | 0% / 0% | 0% | 4.18 | -0.22 [-0.42, -0.02] | 75% | 5967 / 24472 | $0.0527 |
| `context` | 86,330 | 52% | 79 | 0% / 0% | 0% | 4.00 | -0.40 [-0.65, -0.18] | 69% | 7286 / 11999 | $0.0373 |
| `downshift` | 181,461 | -0% | 79 | 0% / 0% | 19% | 4.40 | +0.00 [+0.00, +0.00] | 84% | 5621 / 21760 | $0.0570 |
| `optimized` | 84,151 | 54% | 50 | 37% / 3% | 16% | 4.25 | -0.15 [-0.31, +0.00] | 78% | 2513 / 11655 | $0.0291 |

Per request (`optimized`): 1065 tokens vs 2292 naive; est. $0.000369 vs $0.000822 at paid prices; actual $0.00.
Cache guard: 51 candidates, 17 rejected by numbers, 11 by the verifier (34 calls, 5,012 tokens).

**What the ablations show:**
- **Cache:** 34% of tokens saved, with no measurable quality loss.
- **Downshift:** 19% of calls go to the cheap tier, cutting estimated cost by 12% with no measurable loss. Gemma matched the strong model's score on every question it was routed.
- **Context trimming and compression:** these save tokens but cost real quality. Keeping only 3 chunks / 450 words lost 0.40 points; compressing to 60% lost 0.22.

**`aggressive`** (the first combined config, with every lever at its tightest) saved 72% of tokens but
lost **0.73 points**. That's a significant drop, so **the eval gate blocks it**. **`optimized`**
(the tuned config) keeps the free levers, uses a gentler context budget (top 5 chunks within 750
words) and leaves compression off. It saves **54% of tokens** (estimated $ at paid prices −55%),
halves median latency (5.1 s → 2.5 s), and passes the gate with a quality change of
**−0.15 [−0.31, +0.00]**.

```
## ❌ frugal eval gate: FAIL   (policy `aggressive` vs `naive`, 79 requests)
| quality vs naive (judge score Δ, 95% CI) | -0.73 [-1.05, -0.44] (n=55) | Δ ≥ -0.25 or CI includes 0 | FAIL |
| false-hit rate                            | 3.4%                        | ≤ 5%                       | pass |
| tokens saved vs naive                     | 71.7%                       | ≥ 20%                      | pass |
```
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

**The verifier model matters.** In the end-to-end experiment (§4.1) the verifier was Gemini 3.1
Flash-Lite rather than 3.5, and 1 of 29 cache hits (3.4%) was wrong. That's still inside the gate's
5% limit.

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
quota) for what it changed. The gate needs the repo secrets `GEMINI_API_KEY` and `DATABASE_URL`.

To see it block a PR, copy the aggressive config over the shipped one on a branch and open a PR:

```bash
git checkout -b squeeze-more-tokens
sed 's/^name: aggressive/name: optimized/' configs/policies/aggressive.yaml > configs/policies/optimized.yaml
git commit -am "Tighten context budget and enable compression" && git push -u origin squeeze-more-tokens
```

With `gate` marked as a required check on `main`, the PR shows the failing quality check and can't
be merged.

## 6. Eval set and trace

- **100 questions over 4 domains**, grounded in 70 real public documents (≈103k words): Swiggy
  customer support, GitHub developer support, Indian income tax and GST, and Indian legal
  (statutes plus contract clauses).
- **The questions** include 12 adversarial items (should refuse), 12 out-of-scope items (should
  abstain), 12 format-constrained items, 23 multi-hop items and 39 numeric items.
- **Format:** `data/eval/<domain>.jsonl`, one JSON object per line with `id`, `domain`, `subdomain`,
  `task_type` (`qa`, `clause_analysis`, `format`, `adversarial`, `out_of_scope`), `question`, optional
  `context` (pasted clause text), `reference_answer`, `source_docs` (corpus `doc_id`s that support it),
  `expected_behavior` (`answer`, `refuse`, `escalate`, `abstain`), `format_spec`, `difficulty` and `tags`.
  Corpus files in `data/corpus/<domain>/` carry `doc_id`, `title`, `source_url` and `retrieved` in their
  front matter. `frugal validate` checks every item and every cited document.
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

**Monitoring coverage** (of the five usual categories):

| category | what we watch | where |
|---|---|---|
| operational | latency, request counts, cost, daily call cap | `/metrics`, `request_log`, dashboard |
| input | domain, pasted text, routing rule hit per request | `request_log`, `GET /v1/requests` |
| output | tokens, served-from (cache / tier), cache similarity | `request_log`, Langfuse |
| quality | offline judge score and false-hit rate per policy, on every gated PR | `results/latest.json`, gate comment |
| drift | **not yet.** Next step: track the cache hit rate and routing mix over time and alert on shifts | |

**Online evaluation is not built yet.** Today quality is measured offline on the fixed trace. The
next step is to sample a share of live `request_log` answers to the same judge (no reference
answer, so a rubric-only grade) and plot it on the dashboard.

## 8. Deployment, rollout and rollback

- **Serving:** one Docker container on Render (`render.yaml`), FastAPI, models called over the
  Gemini API; embeddings and reranker run in-process (ONNX). A GitHub Actions cron (`keepalive.yml`)
  pings `/healthz` so the free instance doesn't sleep.
- **Rollout:** every behaviour change is a PR to a versioned policy YAML. The eval gate replays the
  trace and must pass, then the merge to `main` auto-deploys (`autoDeploy: true`).
- **Rollback:** `git revert` the policy change and push; Render redeploys the previous config. This
  was used for real: the `aggressive` policy was reverted in `28bceec` after it failed the gate.
- **Safety nets:** the daily call cap, a request timeout on every model call, and single-flight
  coalescing so a burst can't multiply model calls.

## 9. Design decisions and trade-offs

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
| `optimized` = cache + downshift + gentle context, compression off | All levers at their tightest (`aggressive`) | §4.1: `aggressive` saved 72% of tokens but lost 0.73 quality points (gate fails). The ablations pinned the loss on tight context (−0.40) and compression (−0.22). The tuned config keeps 54% of the savings at −0.15. |
| Single-flight request coalescing | None | §4.3: 43 → 8 model calls under concurrency. |

## 10. Setup

Everything is free tier.

| what | used for |
|---|---|
| `GEMINI_API_KEY` ([AI Studio](https://aistudio.google.com/apikey)) | Gemini 3.1 Flash-Lite (strong tier, cache verifier), Gemma 4 26B-A4B (cheap tier), Gemini 3.1 Flash-Lite Preview (grader) |
| `DATABASE_URL` ([Neon](https://neon.tech), pooled URL) | request log for the API, shared response cache for the CI gate (optional locally) |
| [Render](https://render.com) | hosts the API from `render.yaml` (New → Blueprint) |
| [Streamlit Cloud](https://share.streamlit.io) | hosts `dashboard/app.py` |
| Langfuse keys (optional) | per-call traces |

Embeddings (`BAAI/bge-small-en-v1.5`) and the reranker (`Xenova/ms-marco-MiniLM-L-6-v2`) run
locally through `fastembed`: no key, no quota.

```bash
pip install -e ".[dev,ui,tracing]" && cp .env.example .env   # add GEMINI_API_KEY
frugal models          # check the model ids in configs/models.yaml are live
frugal validate        # eval set + trace + corpus integrity
frugal build-index     # one-off: embed corpus + trace, download reranker (~3 min)
frugal sweep           # cache threshold sweep -> results/sweep.json
frugal run --max-groups 24 --publish   # all policies -> results/latest.json
frugal serve           # API on :8000, docs at /docs
streamlit run dashboard/app.py
pytest -q              # hermetic: fake models, no keys, no network
```

Offline, with no keys at all: `FRUGAL_FAKE_EMBED=1 FRUGAL_FAKE_LLM=1 frugal run --max-groups 12`.

Deploying: on Render, create a Blueprint from this repo and set `GEMINI_API_KEY` and
`DATABASE_URL` (`FRUGAL_API_TOKEN` is generated; send it as `Authorization: Bearer …` to
`POST /v1/answer`). For CI, add the repo secrets `GEMINI_API_KEY` and `DATABASE_URL`.

## 11. Limitations

- The eval set, paraphrases and near-misses are LLM-drafted from real documents (see §6).
- The cache threshold was chosen on the same trace it's reported on. With the verifier the
  false-hit rate is 0% at all tested thresholds, which makes this less sensitive, but a held-out
  trace is the honest next step.
- The judge (Gemini 3.1 Flash-Lite Preview) is not calibrated against human labels in this project.
- Free-tier daily quotas (500 requests per model per day) limit the experiment to a stratified slice
  of the trace (79 requests, 24 question groups). The size is stated next to every number.
- The cache is in-process, one per instance. Multiple instances would need a shared store
  (pgvector).

## 12. Resume line

> Built **frugal**, an LLM cost-optimisation layer (semantic cache with a number guard and LLM
> verification, cross-encoder rerank and truncation, prompt compression, rules-based model downshift)
> with eval-gated quality bounds in CI. It cut token spend by **54%** and halved median latency, at a
> **−0.15 / 5** quality change (95% CI −0.31 to 0.00), on a 4-domain request trace. It also took
> semantic-cache false hits from 25–38% to under 4%, and the CI gate blocked a 72%-saving config
> that broke answer quality.
