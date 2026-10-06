# 15-minute presentation outline

Rubric weights: problem framing 20%, architecture 30%, LLMOps depth 20%, trade-off reasoning 20%,
presentation 10%.

| min | slide | rubric | content |
|---|---|---|---|
| 0–1 | Hook | Problem | "Our RAG bot sends every question, plus 1,000 words of context, to the strong model. Most of that is waste. But every way to cut it can quietly break answers." |
| 1–3 | The four levers and their risks | Problem | Cache → serves the wrong answer. Compression → drops the key sentence. Truncation → loses context. Downshift → cheap model gets numbers wrong. Thesis: every saving needs a measured quality bound. |
| 3–7 | Architecture | Architecture | Request path diagram (cache → guards → rerank/truncate → compress → route → model). Policies as versioned YAML; ablation design (one lever per policy). |
| 7–9 | How we measure | Architecture / LLMOps | Fixed 281-request trace: originals, paraphrases, repeats, near-misses, labelled by group. Replay → judge → paired Δ with bootstrap CI. Cache decisions sequential, generation parallel. |
| 9–11 | The cache finding | LLMOps depth | Similarity histogram: paraphrases 0.948 vs near-misses 0.944, so no threshold separates them. Sweep chart: embedding-only 25–38% false hits → number guard → LLM verifier 0%. |
| 11–12 | Before / after | LLMOps depth | Dashboard headline: tokens saved, calls avoided, quality Δ with CI, est. $ at paid prices (labelled), actual $0. Per-lever ablation bars. |
| 12–13 | CI gate demo | LLMOps depth | PR that loosens the cache → gate fails on false hits → blocked. |
| 13–14 | Trade-offs and what broke | Trade-offs | Free-tier limits (3.5 Flash 20/day) forced separate models per role. Bugs the eval caught: empty Gemma answers cached, "Rs. 40" split by compression, "2.5 years" sent to the cheap tier. Load test found a cache stampede (43 → 8 calls). |
| 14–15 | Numbers and next steps | Presentation | README numbers table. Next: held-out trace for threshold choice, learned router, pgvector-backed shared cache. |

## Likely Q&A
- **Why not just raise the threshold?** The sweep shows false hits stay at ~25% even at 0.96–0.98, because near-misses are as similar as paraphrases. The threshold is the wrong tool.
- **Doesn't the verifier cost money?** One short cheap-tier call per candidate, versus a full strong-tier call with RAG context avoided. It's included in the token totals.
- **Is the judge biased?** It's a Gemini model, so any self-preference favours the strong (Gemini) tier over Gemma. That makes the downshift quality result conservative.
- **Why are the $ figures estimates?** Everything runs on free tiers (actual $0). The estimate prices the measured tokens at published paid rates; tokens saved is the primary, measured metric.
- **Small sample?** Every number states its n. The gate requires significance, not just a lower mean.
