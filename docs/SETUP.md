# Setup: accounts, keys, deploy

Everything is free tier. No paid API credits are needed.

## 1. Keys and accounts

| # | Get it at | Variable | Used for |
|---|---|---|---|
| 1 | https://aistudio.google.com/apikey | `GEMINI_API_KEY` | Gemini 3.1 Flash-Lite (strong tier, cache verifier), Gemma 4 26B-A4B (cheap tier), Gemini 3.1 Flash-Lite Preview (judge). Free-tier daily request caps mean a full experiment may span two days; it resumes from the cache. |
| 2 | https://neon.tech | `DATABASE_URL` | Request log for the live service, plus the shared response cache used by the CI gate. Use the **pooled** connection string. |
| 3 | https://render.com | (account) | Hosts the API from `render.yaml`. |
| 4 | https://share.streamlit.io | (account) | Hosts the dashboard (`dashboard/app.py`). |
| 5 | https://cloud.langfuse.com (optional) | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Per-call traces. |

Embeddings (`BAAI/bge-small-en-v1.5`) and the reranker (`Xenova/ms-marco-MiniLM-L-6-v2`) run
locally through `fastembed`. They need no key, have no quota, and are downloaded once.

## 2. Local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ui,tracing]"
cp .env.example .env            # fill in GEMINI_API_KEY (DATABASE_URL optional locally)
frugal models                   # check the model ids in configs/models.yaml are live
frugal validate                 # eval set + trace + corpus integrity
frugal build-index              # one-off: embed corpus + trace, download reranker (~3 min)
frugal sweep                    # cache threshold sweep (embeddings + cheap verifier calls only)
frugal run --max-groups 24 --publish   # replay all policies, judge, write results/latest.json
streamlit run dashboard/app.py
pytest -q                       # hermetic: fake models, no keys, no network
```

Offline (no keys at all): `FRUGAL_FAKE_EMBED=1 FRUGAL_FAKE_LLM=1 frugal run --max-groups 12`.

## 3. Deploy

1. **Neon:** create a project and copy the pooled connection string.
2. **Render:** New → Blueprint → this repo. Set `GEMINI_API_KEY`, `DATABASE_URL` and the optional
   Langfuse keys. `FRUGAL_API_TOKEN` is generated for you; send it as `Authorization: Bearer …`
   to `POST /v1/answer`. `FRUGAL_MAX_DAILY_CALLS` (default 300) caps model calls per day to protect
   the free quota. Cache hits don't count against it.
3. **GitHub repo settings:**
   - Secrets: `GEMINI_API_KEY`, `DATABASE_URL`.
   - Variable: `FRUGAL_URL` (the Render URL, used by the keep-alive cron).
4. **Streamlit Cloud:** New app → `dashboard/app.py`. In Secrets, set
   `FRUGAL_API_URL = "https://<your-render-service>"`. Without it, the dashboard reads the
   committed `results/latest.json` and `results/sweep.json`.

## 4. The CI eval gate (and the screenshot)

`.github/workflows/eval-gate.yml` runs on any PR touching `configs/`, `frugal/cache.py`, `frugal/context.py`, `frugal/router.py` or
`frugal/pipeline.py`. It replays a stratified 24-group slice of the trace through `naive` and the
PR's `optimized` policy, judges both, and fails on any of:
- a significant quality drop;
- a false-hit rate above 5%;
- tokens saved below 20%.

Thresholds live in `configs/gate.yaml`.

To produce the "blocked PR" screenshot:
```bash
git checkout -b aggressive-cache
# make the cache dangerously loose: no guards, low threshold
sed -i '' 's/threshold: 0.84/threshold: 0.80/; s/number_guard: true/number_guard: false/; s/verify_model: gemini-lite/verify_model: null/' configs/policies/optimized.yaml
git commit -am "Raise cache hit rate" && git push -u origin aggressive-cache   # open a PR
```
The gate should fail on false hits. Mark the `eval-gate / gate` check as required in branch
protection so the PR can't merge.
