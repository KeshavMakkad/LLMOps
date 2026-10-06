"""Savings dashboard (Streamlit). Reads the API if FRUGAL_API_URL is set, else results/*.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="frugal: LLM cost optimiser", page_icon="💸", layout="wide")
ROOT = Path(__file__).resolve().parent.parent

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"  # validated categorical slots 1-3
GRID = "rgba(128,128,128,.15)"


def _setting(name: str) -> str:
    v = os.environ.get(name, "")
    if not v:
        try:
            v = st.secrets.get(name, "")
        except Exception:  # noqa: BLE001 - no secrets file
            pass
    return v


API = _setting("FRUGAL_API_URL").rstrip("/")


@st.cache_data(ttl=300, show_spinner=False)
def load() -> tuple[dict | None, dict | None, str]:
    exp = sweep = None
    src = "committed results"
    if API:
        try:
            exp = requests.get(f"{API}/v1/experiments/latest?include_records=true", timeout=60).json()
            src = f"live API ({API})"
        except Exception:  # noqa: BLE001
            exp = None
    if exp is None and (ROOT / "results" / "latest.json").exists():
        exp = json.loads((ROOT / "results" / "latest.json").read_text())
    if (ROOT / "results" / "sweep.json").exists():
        sweep = json.loads((ROOT / "results" / "sweep.json").read_text())
    return exp, sweep, src


def pct(v: float | None) -> str:
    return "–" if v is None else f"{v:.0%}"


def ci_text(e: dict | None, fmt: str = "{:+.2f}") -> str:
    if not e or e.get("value") is None:
        return "–"
    return f"{fmt.format(e['value'])}  [{fmt.format(e['lo'])}, {fmt.format(e['hi'])}]"


exp, sweep, src = load()
st.title("💸 frugal")
st.caption("A drop-in layer that cuts LLM spend (semantic cache, context management, prompt compression, model "
           "downshift) and proves quality holds. Every number below comes from replaying the same fixed "
           f"request trace through each policy. Source: {src}.")

if exp is None:
    st.warning("No experiment published yet. Run `frugal run --publish`.")
    st.stop()

P = exp["policies"]
naive = P.get("naive")
best = P.get("optimized") or list(P.values())[-1]
tr = exp["trace"]

# ------------------------------------------------------------------ headline
st.subheader(f"`optimized` vs `naive` · {tr['requests']} requests · {tr['groups']} question groups")
c = st.columns(6)
c[0].metric("Tokens saved", pct(best.get("tokens_saved_pct")),
            help="Prompt + output tokens actually sent to models, measured from API usage.")
c[1].metric("Model calls avoided", pct(best.get("llm_calls_saved_pct")))
c[2].metric("Cache hit rate", pct(best["hit_rate"]), help=f"false-hit rate {pct(best['false_hit_rate'])}")
c[3].metric("Quality Δ (judge, 1–5)", f"{best['quality_delta']['value']:+.2f}" if best.get("quality_delta") else "–",
            help=f"95% CI {ci_text(best.get('quality_delta'))}")
c[4].metric("Est. $ saved*", f"{best.get('est_cost_saved_pct', 0):.0%}",
            help=f"${best.get('est_cost_saved_usd', 0):.4f} on this trace at paid-tier prices")
c[5].metric("Actual spend", f"${best['cost_usd']:.2f}", help="Everything runs on free tiers.")
st.caption("*Estimate: the measured tokens priced at published paid rates (Gemini 3.1 Flash-Lite "
           "$0.25 / $1.50, Gemma 4 26B-A4B $0.09 / $0.30 per 1M input / output tokens, retrieved 2026-10-06). "
           "Actual spend is $0: free tier.")

tabs = st.tabs(["Before / after", "Cache: hit vs false-hit", "Per-request drill-down", "Method"])

# ------------------------------------------------------------------ before/after + ablation
with tabs[0]:
    rows = []
    for name, s in P.items():
        rows.append({
            "policy": name,
            "tokens": s["total_tokens"],
            "tokens saved": s.get("tokens_saved_pct"),
            "model calls": s["llm_calls"],
            "cache hits": s["cache_hits"],
            "false hits": s["false_hits"],
            "cheap-tier share": s["cheap_tier_share"],
            "context words sent (mean)": round(s["context_words_mean"]),
            "quality (mean)": s["quality_mean"]["value"],
            "quality Δ [95% CI]": ci_text(s.get("quality_delta")),
            "pass rate": s["quality_pass_rate"]["value"],
            "p50 ms": s["latency_p50_ms"],
            "p99 ms": s["latency_p99_ms"],
            "est $ (paid prices)": s["est_cost_usd"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"tokens saved": st.column_config.NumberColumn(format="percent"),
                                "cheap-tier share": st.column_config.NumberColumn(format="percent"),
                                "pass rate": st.column_config.NumberColumn(format="percent"),
                                "quality (mean)": st.column_config.NumberColumn(format="%.2f"),
                                "p50 ms": st.column_config.NumberColumn(format="%.0f"),
                                "p99 ms": st.column_config.NumberColumn(format="%.0f"),
                                "est $ (paid prices)": st.column_config.NumberColumn(format="$%.4f")})
    st.caption("`cache`, `context`, `compress` and `downshift` each switch on ONE lever (ablation); `optimized` "
               "combines them.")

    left, right = st.columns(2)
    with left:
        names = list(P)
        fig = go.Figure(go.Bar(
            x=[P[n]["total_tokens"] for n in names], y=names, orientation="h",
            marker=dict(color=[ORANGE if n == "naive" else BLUE for n in names]),
            text=[f"{P[n].get('tokens_saved_pct', 0):.0%} saved" if n != "naive" else "baseline" for n in names],
            textposition="outside", hovertemplate="%{y}: %{x:,} tokens<extra></extra>"))
        fig.update_layout(title="Tokens sent to models", height=330, margin=dict(l=10, r=40, t=40, b=10),
                          yaxis=dict(autorange="reversed"), xaxis=dict(gridcolor=GRID))
        st.plotly_chart(fig, width="stretch")
    with right:
        pts = [(n, P[n]["quality_delta"]) for n in P if P[n].get("quality_delta", {}).get("value") is not None]
        fig = go.Figure(go.Scatter(
            x=[e["value"] for _, e in pts], y=[n for n, _ in pts], mode="markers",
            marker=dict(size=11, color=BLUE, line=dict(width=2, color="white")),
            error_x=dict(type="data", symmetric=False, array=[e["hi"] - e["value"] for _, e in pts],
                         arrayminus=[e["value"] - e["lo"] for _, e in pts], thickness=2, width=0, color=BLUE),
            hovertemplate="%{y}: %{x:+.2f}<extra></extra>"))
        fig.add_vline(x=0, line_dash="dot", line_color="gray")
        fig.update_layout(title="Quality change vs naive (judge score, 95% CI)", height=330,
                          margin=dict(l=10, r=10, t=40, b=10), yaxis=dict(autorange="reversed"),
                          xaxis=dict(gridcolor=GRID, zeroline=False))
        st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------------ cache sweep
with tabs[1]:
    if not sweep:
        st.info("Run `frugal sweep` to produce the threshold sweep.")
    else:
        df = pd.DataFrame(sweep["rows"])
        st.markdown("Each line is one cache design. **Hit rate** saves money; **false-hit rate** is the share of "
                    "cache-served answers that belonged to a *different* question (a wrong answer served "
                    "confidently). No LLM answers are needed: hits are simulated from the trace order and "
                    "labelled by question group.")
        colors = dict(zip(df["variant"].unique(), [BLUE, ORANGE, AQUA]))
        l2, r2 = st.columns(2)
        for col, metric, title in ((l2, "hit_rate", "Hit rate"), (r2, "false_hit_rate", "False-hit rate")):
            fig = go.Figure()
            for v, g in df.groupby("variant", sort=False):
                fig.add_trace(go.Scatter(x=g["threshold"], y=g[metric], mode="lines+markers", name=v,
                                         line=dict(width=2, color=colors[v]), marker=dict(size=8)))
            fig.update_layout(title=f"{title} vs similarity threshold", height=360, yaxis=dict(tickformat=".0%",
                              gridcolor=GRID), xaxis=dict(gridcolor=GRID), margin=dict(l=10, r=10, t=40, b=10),
                              legend=dict(orientation="h", y=-0.2))
            col.plotly_chart(fig, width="stretch")
        sims = sweep.get("similarity", {})
        if sims.get("paraphrase", {}).get("values"):
            fig = go.Figure()
            for k, colr, label in (("paraphrase", BLUE, "paraphrase (same answer)"),
                                   ("near_miss", ORANGE, "near-miss (different answer)")):
                fig.add_trace(go.Histogram(x=sims[k]["values"], name=label, marker_color=colr, opacity=0.75,
                                           xbins=dict(size=0.01)))
            fig.update_layout(barmode="overlay", height=320, title="Similarity to the original question",
                              xaxis_title="cosine similarity (bge-small)", margin=dict(l=10, r=10, t=40, b=10),
                              legend=dict(orientation="h", y=-0.25))
            st.plotly_chart(fig, width="stretch")
            st.caption("The two populations overlap almost completely, so no similarity threshold alone can separate "
                       "a reworded question from a changed one. That is why the cache needs guards.")
        st.dataframe(df[["variant", "threshold", "hit_rate", "correct_hit_rate", "false_hit_rate",
                         "near_miss_false_hit_rate", "llm_calls", "guard_verifier_calls"]], hide_index=True,
                     width="stretch")

# ------------------------------------------------------------------ drill-down
with tabs[2]:
    recs = exp.get("records") or {}
    if not recs:
        st.info("Per-request records aren't included in this snapshot.")
    else:
        pol = st.selectbox("Policy", [p for p in recs if p != "naive"] or list(recs))
        df = pd.DataFrame(recs[pol])
        base = pd.DataFrame(recs.get("naive", [])).set_index("req_id") if "naive" in recs else None
        f1, f2 = st.columns(2)
        src_filter = f1.multiselect("Served from", sorted(df["served_from"].unique()), default=None)
        only_false = f2.toggle("Only false cache hits", value=False)
        view = df
        if src_filter:
            view = view[view["served_from"].isin(src_filter)]
        if only_false:
            view = view[view["false_hit"]]
        cols = ["req_id", "kind", "served_from", "cache_similarity", "tier", "route_rule", "prompt_tokens",
                "output_tokens", "context_words", "score", "latency_ms"]
        if base is not None:
            view = view.assign(naive_tokens=view["req_id"].map(base["prompt_tokens"] + base["output_tokens"]),
                               naive_score=view["req_id"].map(base["score"]))
            cols += ["naive_tokens", "naive_score"]
        st.dataframe(view[cols], hide_index=True, width="stretch", height=420)
        rid = st.selectbox("Inspect a request", view["req_id"].tolist())
        if rid:
            r = df.set_index("req_id").loc[rid]
            st.markdown(f"**{rid}** · {r['kind']} · served from **{r['served_from']}**"
                        + (f" (similarity {r['cache_similarity']:.3f}, source {r['cache_source_req']})"
                           if r["served_from"].endswith("cache") else f" · tier **{r['tier']}** ({r['route_rule']})"))
            if r["false_hit"]:
                st.error("False hit: this answer was cached for a different question.")
            a, b = st.columns(2)
            a.markdown(f"**{pol}** answer (score {r['score']})")
            a.write(r["answer"])
            if base is not None and rid in base.index:
                b.markdown(f"**naive** answer (score {base.loc[rid, 'score']})")
                b.write(base.loc[rid, "answer"])

# ------------------------------------------------------------------ method
with tabs[3]:
    j = exp["judge"]
    st.markdown(f"""
**Trace.** {tr['requests']} requests built from a 100-item eval set over 4 domains (Swiggy support, GitHub
support, Indian tax, Indian legal) grounded in 70 public documents: each question, a paraphrase (same
answer), exact repeats (~30%), and near-misses (same wording, different answer) for ~half of them.
Kinds: {tr['kinds']}. The order is shuffled once (seed {tr['seed']}) and fixed, so every policy sees the
same traffic.

**Quality.** Each answer with a reference is graded 1–5 by a reference-guided judge (`{j['model']}`,
rubric `{j['version']}`; pass = score ≥ {j['pass_score']}). Δ is paired per request vs `naive`, with a 95%
bootstrap CI. Near-miss requests have no reference; for them the metric is the false-hit rate.

**Cost.** Tokens are the prompt + output counts the model API reports. The cache verifier's own calls are
included. "Est. $" prices those tokens at the published paid-tier rates; actual spend is $0 (free tier).

**Latency.** Provider time of the model call plus the layer's own overhead (embedding, cache lookup,
rerank, compression). Rate-limit waits are excluded.
""")
