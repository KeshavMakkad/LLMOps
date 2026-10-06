"""Replay policies over the request trace, grade the answers, compare against naive.

Cache hit/miss is decided in arrival order first (it only depends on earlier questions),
then the misses are answered in parallel.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from frugal import tracing
from frugal.cache import SemanticCache, cache_scope, embed_question
from frugal.config import ROOT, Policy, load_policy
from frugal.pipeline import Record, answer_with_llm
from frugal.quality import JUDGE_VERSION, PASS_SCORE, judge
from frugal.stats import bootstrap_mean
from frugal.trace import Request, build_trace, load_items

log = logging.getLogger("frugal.experiment")
WORKERS = int(os.environ.get("FRUGAL_WORKERS", "6"))
RESULTS_DIR = ROOT / "results"
MAX_ERROR_RATE = float(os.environ.get("FRUGAL_MAX_ERROR_RATE", "0.05"))


class QuotaError(RuntimeError):
    pass


def replay(policy: Policy, trace: list[Request], run_id: str = "") -> tuple[list[Record], dict]:
    cache = SemanticCache(policy.cache)
    recs: dict[str, Record] = {}
    misses: list[Request] = []
    source_of: dict[str, str] = {}
    for req in trace:  # pass 1: decide hits in arrival order
        rec = Record(req_id=req.req_id, group_id=req.group_id, kind=req.kind, policy=policy.name)
        t0 = time.perf_counter()
        scope = cache_scope(req.domain, req.context)
        vec = embed_question(req.question) if policy.cache.semantic else None
        hit = cache.lookup(scope, req.question, vec, domain=req.domain)
        rec.overhead_ms = (time.perf_counter() - t0) * 1000
        if hit:
            rec.served_from = f"{hit.kind}_cache"
            rec.cache_similarity, rec.cache_source_req = hit.similarity, hit.entry.req_id
            rec.cache_source_group = hit.entry.group_id
            source_of[req.req_id] = hit.entry.req_id
        else:
            misses.append(req)
            cache.store(scope, req.question, "", req.req_id, req.group_id, vec)
        recs[req.req_id] = rec

    def _answer(req: Request) -> Record:  # pass 2: model calls for misses, in parallel
        return answer_with_llm(req, policy, recs[req.req_id], run_id)

    log.info("%s: %d requests, %d cache hits, answering %d misses", policy.name, len(trace),
             len(trace) - len(misses), len(misses))
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, _ in enumerate(ex.map(_answer, misses), 1):
            if i % 10 == 0 or i == len(misses):
                log.info("%s: answered %d/%d", policy.name, i, len(misses))
    for rid, src in source_of.items():  # hits reuse their source's answer
        recs[rid].answer = recs[src].answer
        if not recs[src].answer:  # source failed: this request would have gone to the model too
            recs[rid].served_from, recs[rid].error = "error", "cache source had no answer"
    errors = [r for r in recs.values() if r.served_from == "error"]
    if len(errors) > MAX_ERROR_RATE * max(1, len(misses)):
        raise QuotaError(f"{len(errors)}/{len(misses)} model calls failed for policy '{policy.name}' "
                         f"(e.g. {errors[0].error[:160]}). Likely a free-tier quota; completed calls are "
                         "cached, so re-run later to resume.")
    return [recs[r.req_id] for r in trace], vars(cache.stats)


def judge_all(recs: list[Record], trace: list[Request], judge_model: str, run_id: str = "") -> dict[str, int | None]:
    items = load_items()
    by_id = {r.req_id: r for r in trace}
    todo = [r for r in recs if by_id[r.req_id].has_reference and r.answer]

    def _one(rec: Record):
        req = by_id[rec.req_id]
        return rec.req_id, judge(items[req.item_id], req.question, rec.answer, judge_model, run_id)[0]

    log.info("judging %d answers", len(todo))
    with ThreadPoolExecutor(WORKERS) as ex:
        scores = dict(ex.map(_one, todo))
    failed = sum(1 for v in scores.values() if v is None)
    if failed > MAX_ERROR_RATE * max(1, len(todo)):
        raise QuotaError(f"{failed}/{len(todo)} judge calls failed; re-run later to resume from cache.")
    for rec in recs:  # served-but-wrong answers on near-misses can't be graded vs a reference
        if rec.req_id not in scores and by_id[rec.req_id].has_reference:
            scores[rec.req_id] = 1  # empty / errored answer on a reference request
    return scores


def _pct(xs: list[float], q: float) -> float | None:
    return float(np.percentile(xs, q)) if xs else None


def summarise(policy: Policy, recs: list[Record], scores: dict[str, int | None],
              base: dict | None = None, n_boot: int = 2000, guard: dict | None = None) -> dict:
    llm = [r for r in recs if r.served_from == "llm"]
    hits = [r for r in recs if r.served_from.endswith("cache")]
    near = [r for r in recs if r.kind == "near_miss"]
    guard = guard or {}
    # The cache verifier's own (cheap-tier) calls are part of the policy's cost.
    tokens = sum(r.prompt_tokens + r.output_tokens for r in recs) + guard.get("verifier_tokens", 0)
    graded = {k: v for k, v in scores.items() if v is not None}
    s = {
        "policy": policy.name,
        "description": policy.description.strip(),
        "requests": len(recs),
        "llm_calls": len(llm),
        "cache_hits": len(hits),
        "exact_hits": sum(r.served_from == "exact_cache" for r in recs),
        "semantic_hits": sum(r.served_from == "semantic_cache" for r in recs),
        "hit_rate": len(hits) / len(recs) if recs else 0.0,
        "false_hits": sum(r.false_hit for r in recs),
        "false_hit_rate": (sum(r.false_hit for r in hits) / len(hits)) if hits else 0.0,
        "near_miss_served_from_cache": (sum(r.served_from.endswith("cache") for r in near) / len(near))
        if near else 0.0,
        "prompt_tokens": sum(r.prompt_tokens for r in recs),
        "output_tokens": sum(r.output_tokens for r in recs),
        "total_tokens": tokens,
        "context_words_mean": float(np.mean([r.context_words for r in llm])) if llm else 0.0,
        "retrieved_words_mean": float(np.mean([r.retrieved_words for r in llm])) if llm else 0.0,
        "cost_usd": sum(r.cost_usd for r in recs),
        "est_cost_usd": sum(r.est_cost_usd for r in recs) + guard.get("verifier_est_cost_usd", 0.0),
        "cache_guard": guard,
        "cheap_tier_share": (sum(r.tier == "cheap" for r in llm) / len(llm)) if llm else 0.0,
        "route_rules": dict(Counter(r.route_rule for r in llm)),
        "latency_p50_ms": _pct([r.latency_ms for r in recs], 50),
        "latency_p99_ms": _pct([r.latency_ms for r in recs], 99),
        "llm_latency_p50_ms": _pct([r.llm_ms for r in llm if not r.llm_cached], 50),
        "overhead_p50_ms": _pct([r.overhead_ms for r in recs], 50),
        "quality_mean": bootstrap_mean(list(graded.values()), n_boot=n_boot).dict(),
        "quality_pass_rate": bootstrap_mean([1.0 if v >= PASS_SCORE else 0.0 for v in graded.values()],
                                            n_boot=n_boot).dict(),
        "graded": len(graded),
        "errors": sum(r.served_from == "error" for r in recs),
    }
    if base:
        bs = base["_scores"]
        common = [k for k in graded if bs.get(k) is not None]
        s["quality_delta"] = bootstrap_mean([graded[k] - bs[k] for k in common], n_boot=n_boot).dict()
        s["pass_rate_delta"] = bootstrap_mean(
            [(graded[k] >= PASS_SCORE) - (bs[k] >= PASS_SCORE) for k in common], n_boot=n_boot).dict()
        s["tokens_saved_pct"] = 1 - tokens / base["total_tokens"] if base["total_tokens"] else 0.0
        s["est_cost_saved_usd"] = base["est_cost_usd"] - s["est_cost_usd"]
        s["est_cost_saved_pct"] = 1 - s["est_cost_usd"] / base["est_cost_usd"] if base["est_cost_usd"] else 0.0
        s["llm_calls_saved_pct"] = 1 - len(llm) / base["llm_calls"] if base["llm_calls"] else 0.0
    return s


def run_experiment(policy_names: list[str], max_groups: int | None = None, judge_model: str = "gemini-judge",
                   seed: int = 7, out: Path | None = None, baseline: str = "naive") -> dict:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    trace = build_trace(seed=seed, max_groups=max_groups)
    names = [baseline] + [p for p in policy_names if p != baseline]
    result = {"run_id": run_id, "trace": {"requests": len(trace), "groups": len({r.item_id for r in trace}),
                                          "kinds": dict(Counter(r.kind for r in trace)), "seed": seed,
                                          "max_groups": max_groups},
              "judge": {"model": judge_model, "version": JUDGE_VERSION, "pass_score": PASS_SCORE},
              "policies": {}, "records": {}}
    base = None
    try:
        for name in names:
            pol = load_policy(name)
            recs, guard = replay(pol, trace, run_id)
            scores = judge_all(recs, trace, judge_model, run_id)
            summ = summarise(pol, recs, scores, base, guard=guard)
            if name == baseline:
                base = {**summ, "_scores": scores}
            result["policies"][name] = summ
            result["records"][name] = [{**r.model_dump(), "score": scores.get(r.req_id),
                                        "latency_ms": r.latency_ms, "false_hit": r.false_hit} for r in recs]
            result["policies"][name]["config"] = pol.model_dump()
    finally:
        tracing.flush()
    out = out or RESULTS_DIR / "experiments" / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, default=str, indent=1))
    result["path"] = str(out)
    return result
