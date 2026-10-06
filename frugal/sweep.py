"""Cache threshold sweep: hit rate vs false-hit rate, no answer generation needed."""

from __future__ import annotations

import numpy as np

from frugal.cache import SemanticCache, cache_scope
from frugal.config import CacheCfg
from frugal.rag.embed import embed_texts
from frugal.trace import Request


def simulate(trace: list[Request], cfg: CacheCfg, vecs: np.ndarray) -> dict:
    cache = SemanticCache(cfg)
    hits = correct = false = near_total = near_false = 0
    for i, r in enumerate(trace):
        scope = cache_scope(r.domain, r.context)
        hit = cache.lookup(scope, r.question, vecs[i], domain=r.domain)
        near_total += r.kind == "near_miss"
        if hit is None:
            cache.store(scope, r.question, "", r.req_id, r.group_id, vecs[i])
            continue
        hits += 1
        if hit.entry.group_id == r.group_id:
            correct += 1
        else:
            false += 1
            near_false += r.kind == "near_miss"
    n = len(trace)
    return {
        "threshold": cfg.threshold,
        "hit_rate": hits / n,
        "correct_hit_rate": correct / n,
        "false_hit_rate": false / hits if hits else 0.0,  # share of served cache answers that were wrong
        "near_miss_false_hit_rate": near_false / near_total if near_total else 0.0,
        "llm_calls": n - hits,
        "hits": hits,
        "false_hits": false,
        **{f"guard_{k}": v for k, v in vars(cache.stats).items()},
    }


VARIANTS = {
    "embedding only": {"number_guard": False, "verify_model": None},
    "+ number guard": {"number_guard": True, "verify_model": None},
    "+ number guard + LLM verifier": {"number_guard": True, "verify_model": "gemini-35-lite"},
}


def sweep(trace: list[Request], thresholds: list[float], variants: list[str] | None = None,
          verify_thresholds: list[float] | None = None) -> list[dict]:
    vecs = embed_texts([r.question for r in trace])
    rows = []
    for name in variants or list(VARIANTS):
        ts = verify_thresholds if (VARIANTS[name]["verify_model"] and verify_thresholds) else thresholds
        for t in ts:
            cfg = CacheCfg(exact=True, semantic=True, threshold=t, **VARIANTS[name])
            rows.append({"variant": name, **simulate(trace, cfg, vecs)})
    return rows


def similarity_report(trace: list[Request]) -> dict:
    """Each paraphrase's / near-miss's similarity to its own original: how separable the two
    populations are bounds what any threshold can do."""
    vecs = embed_texts([r.question for r in trace])
    idx = {r.req_id: i for i, r in enumerate(trace)}
    out: dict[str, list[float]] = {"paraphrase": [], "near_miss": []}
    for r in trace:
        if r.kind in out and f"{r.item_id}:o" in idx:
            out[r.kind].append(float(vecs[idx[r.req_id]] @ vecs[idx[f"{r.item_id}:o"]]))
    return {k: {"n": len(v), "mean": float(np.mean(v)) if v else None,
                "p10": float(np.percentile(v, 10)) if v else None,
                "p90": float(np.percentile(v, 90)) if v else None, "values": v} for k, v in out.items()}
