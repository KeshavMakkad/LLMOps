"""frugal CLI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from frugal.config import ROOT

load_dotenv(ROOT / ".env")
app = typer.Typer(add_completion=False, help="LLM cost-optimisation layer with eval-gated quality bounds")
console = Console()


def _ci(e: dict | None) -> str:
    if not e or e.get("value") is None:
        return "-"
    return f"{e['value']:+.2f} [{e['lo']:+.2f},{e['hi']:+.2f}]"


def print_summary(result: dict) -> None:
    t = Table(title=f"Policies on a {result['trace']['requests']}-request trace "
                    f"({result['trace']['groups']} groups) | judge {result['judge']['model']}")
    for c in ("policy", "tokens", "saved", "calls", "hit rate", "false hits", "cheap tier", "quality",
              "Δ quality (95% CI)", "pass", "p50 ms", "p99 ms", "est $*"):
        t.add_column(c)
    for name, s in result["policies"].items():
        t.add_row(name, f"{s['total_tokens']:,}", f"{s.get('tokens_saved_pct', 0):.0%}", str(s["llm_calls"]),
                  f"{s['hit_rate']:.0%}", f"{s['false_hits']}", f"{s['cheap_tier_share']:.0%}",
                  f"{s['quality_mean']['value']:.2f}" if s["quality_mean"]["value"] is not None else "-",
                  _ci(s.get("quality_delta")),
                  f"{s['quality_pass_rate']['value']:.0%}" if s["quality_pass_rate"]["value"] is not None else "-",
                  f"{s['latency_p50_ms']:.0f}" if s["latency_p50_ms"] is not None else "-",
                  f"{s['latency_p99_ms']:.0f}" if s["latency_p99_ms"] is not None else "-",
                  f"{s['est_cost_usd']:.4f}")
    console.print(t)
    console.print("* est $ = the same tokens at published paid-tier prices; actual spend is $0 (free tier).")


@app.command()
def models():
    """Check that every model id in configs/models.yaml is live on your Gemini key."""
    from google import genai

    from frugal.config import load_models

    live = {m.name.removeprefix("models/") for m in genai.Client(api_key=os.environ["GEMINI_API_KEY"]).models.list()}
    for k, m in load_models().items():
        if m.provider == "gemini":
            console.print(f"{k:20} {m.model:28} {'live' if m.model in live else '[red]NOT FOUND[/]'}")


@app.command()
def validate():
    """Validate the eval set, trace variants and corpus references."""
    from frugal.rag.corpus import doc_ids
    from frugal.trace import _variants, build_trace, load_items

    items = load_items()
    bad = [f"{i.id}: unknown doc {d}" for i in items.values() for d in i.source_docs if d not in doc_ids(i.domain)]
    v = _variants()
    missing = sorted(set(items) - set(v))
    trace = build_trace()
    kinds: dict[str, int] = {}
    for r in trace:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    console.print(f"eval items: {len(items)} | variants: {len(v)} (missing {len(missing)}) | "
                  f"trace: {len(trace)} {kinds}")
    for b in bad:
        console.print(f"[red]{b}")
    if bad or missing:
        sys.exit(1)


@app.command("build-index")
def build_index():
    """Pre-embed everything the policies need (retrieval index, trace questions) and load the
    reranker, so Docker images / CI start warm and the 512 MB instance never embeds the corpus."""
    from frugal.config import list_policies, load_policy
    from frugal.context import _rerank_scores
    from frugal.rag.embed import embed_texts
    from frugal.rag.index import get_index
    from frugal.trace import build_trace, load_items

    cfgs = {(p.retrieval.chunk_words, p.retrieval.overlap_words)
            for p in map(load_policy, list_policies()) if p.retrieval.enabled}
    domains = sorted({i.domain for i in load_items().values()})
    for cw, ov in sorted(cfgs):
        for d in domains:
            console.print(f"index {d:7} {cw}/{ov}: {len(get_index(d, cw, ov).chunks)} chunks")
    embed_texts([r.question for r in build_trace()])
    _rerank_scores("warm up", ["the reranker model is downloaded and cached"])
    console.print("done")


@app.command()
def sweep(max_groups: int = typer.Option(None),
          verify: bool = typer.Option(True, help="include the LLM-verifier variant (cheap-tier calls, cached)"),
          out: Path = typer.Option(ROOT / "results" / "sweep.json")):
    """Semantic-cache threshold sweep: hit rate vs false-hit rate for 3 cache designs."""
    from frugal.sweep import VARIANTS, similarity_report
    from frugal.sweep import sweep as _sweep
    from frugal.trace import build_trace

    trace = build_trace(max_groups=max_groups)
    grid = [round(0.80 + 0.02 * i, 2) for i in range(10)]
    variants = list(VARIANTS) if verify else [v for v in VARIANTS if not VARIANTS[v]["verify_model"]]
    rows = _sweep(trace, grid, variants, verify_thresholds=[0.84, 0.88, 0.92])
    t = Table(title=f"Cache threshold sweep ({len(trace)} requests)")
    for c in ("design", "threshold", "hit rate", "correct hits", "false-hit rate", "near-miss served wrongly",
              "model calls", "verifier calls"):
        t.add_column(c)
    for r in rows:
        t.add_row(r["variant"], f"{r['threshold']:.2f}", f"{r['hit_rate']:.1%}", f"{r['correct_hit_rate']:.1%}",
                  f"{r['false_hit_rate']:.1%}", f"{r['near_miss_false_hit_rate']:.1%}", str(r["llm_calls"]),
                  str(r["guard_verifier_calls"]))
    console.print(t)
    sims = similarity_report(trace)
    for k, v in sims.items():
        console.print(f"similarity to original, {k}: mean {v['mean']:.3f}  p10 {v['p10']:.3f}  "
                      f"p90 {v['p90']:.3f}  (n={v['n']})")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "similarity": sims, "requests": len(trace)}, indent=1))
    console.print(f"-> {out}")


@app.command()
def run(policies: list[str] = typer.Argument(None, help="policies to compare to naive (default: all)"),
        max_groups: int = typer.Option(None, help="sample this many question groups (stratified)"),
        judge: str = typer.Option("gemini-judge"),
        out: Path = typer.Option(None, help="results JSON path"),
        publish: bool = typer.Option(False, help="also write results/latest.json for the dashboard")):
    """Replay policies over the trace, judge quality, compare to naive."""
    import logging

    from frugal.config import list_policies
    from frugal.experiment import run_experiment

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for noisy in ("httpx", "google_genai", "google_genai.models"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    result = run_experiment(policies or list_policies(), max_groups=max_groups, judge_model=judge, out=out)
    print_summary(result)
    if publish:
        latest = ROOT / "results" / "latest.json"
        latest.write_text(Path(result["path"]).read_text())
        console.print(f"published -> {latest}")
    console.print(f"results -> {result['path']}")


@app.command()
def gate(policy: str = typer.Argument("optimized"),
         max_groups: int = typer.Option(24, help="trace size for CI (stratified groups)"),
         judge: str = typer.Option("gemini-judge"),
         summary_md: Path = typer.Option(None, help="write the verdict markdown here (e.g. for a PR comment)")):
    """CI eval gate: does `policy` keep quality vs naive while still saving tokens?"""
    from frugal import gate as g
    from frugal.experiment import run_experiment

    result = run_experiment([policy], max_groups=max_groups, judge_model=judge)
    cand = result["policies"][load_policy_name(policy)]
    verdict = g.evaluate(cand, g.load_gate())
    md = g.markdown(verdict, cand, result["trace"])
    console.print(md)
    for target in filter(None, [summary_md, os.environ.get("GITHUB_STEP_SUMMARY")]):
        with open(target, "a") as f:
            f.write(md + "\n")
    sys.exit(0 if verdict["passed"] else 1)


def load_policy_name(name_or_path: str) -> str:
    from frugal.config import load_policy

    return load_policy(name_or_path).name


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Run the optimiser as an HTTP service."""
    import uvicorn

    uvicorn.run("frugal.api.main:app", host=host, port=port)


if __name__ == "__main__":
    app()
