"""HTTP API for the optimiser."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from frugal import __version__, metrics, store
from frugal.cache import SemanticCache, cache_scope, embed_question
from frugal.config import ROOT, list_policies, load_domains, load_policy
from frugal.pipeline import handle
from frugal.trace import Request as TraceRequest

load_dotenv(ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("frugal.api")
app = FastAPI(title="frugal", version=__version__, description="LLM cost-optimisation layer")

# One warm cache per policy for the life of the process. (A multi-instance deployment would back
# this with pgvector; one free-tier instance doesn't need it.)
_caches: dict[str, SemanticCache] = {}
_cache_lock = threading.Lock()

# single-flight: concurrent identical questions wait for the first answer instead of
# all missing the cache (load test: 43 model calls for 8 questions without this)
_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()
COALESCE_WAIT_S = 90

# Free-tier quota protection: a hard cap on model calls per UTC day for this instance.
MAX_DAILY_CALLS = int(os.environ.get("FRUGAL_MAX_DAILY_CALLS", "300"))
_calls = {"day": date.today().isoformat(), "n": 0}
_calls_lock = threading.Lock()


def require_token(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("FRUGAL_API_TOKEN")
    if token and authorization != f"Bearer {token}":
        raise HTTPException(401, "missing or invalid bearer token")


def _reserve_call() -> None:
    with _calls_lock:
        today = date.today().isoformat()
        if _calls["day"] != today:
            _calls.update(day=today, n=0)
        if _calls["n"] >= MAX_DAILY_CALLS:
            raise HTTPException(429, f"daily model-call budget ({MAX_DAILY_CALLS}) used up; cached answers "
                                     "are still served, new questions resume tomorrow")
        _calls["n"] += 1


@app.middleware("http")
async def _timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["x-response-time-ms"] = f"{(time.perf_counter() - t0) * 1000:.1f}"
    return response


class AnswerRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    domain: str
    context: str | None = Field(default=None, max_length=8000)  # pasted text, e.g. a contract clause
    policy: str = "optimized"


@app.post("/v1/answer", dependencies=[Depends(require_token)])
def answer(req: AnswerRequest) -> dict:
    if req.domain not in load_domains():
        raise HTTPException(400, f"domain must be one of {sorted(load_domains())}")
    try:
        policy = load_policy(req.policy, allow_path=False)
    except FileNotFoundError:
        raise HTTPException(404, f"unknown policy '{req.policy}'") from None
    with _cache_lock:
        cache = _caches.setdefault(policy.name, SemanticCache(policy.cache))
    key = f"{policy.name}|{cache_scope(req.domain, req.context)}|{' '.join(req.question.lower().split())}"
    with _inflight_lock:
        ev = _inflight.get(key)
        leader = ev is None
        if leader:
            ev = _inflight[key] = threading.Event()
    if not leader:
        ev.wait(COALESCE_WAIT_S)  # then fall through: the leader's answer is now in the cache
    try:
        return _answer(req, policy, cache)
    finally:
        if leader:
            with _inflight_lock:
                _inflight.pop(key, None)
            ev.set()


def _answer(req: AnswerRequest, policy, cache: SemanticCache) -> dict:
    rid = f"api-{time.time_ns()}"
    treq = TraceRequest(req_id=rid, group_id=rid, kind="live", item_id="", domain=req.domain,
                        question=req.question, context=req.context)
    # Peek at the cache first: hits must not consume the daily model-call budget.
    vec = embed_question(req.question) if policy.cache.semantic else None
    if cache.lookup(cache_scope(req.domain, req.context), req.question, vec, domain=req.domain) is None:
        _reserve_call()
    rec = handle(treq, policy, cache)
    if rec.served_from == "error":
        raise HTTPException(502, f"model call failed: {rec.error}")
    metrics.PIPELINE_REQUESTS.labels(policy.name, rec.served_from, rec.tier or "-").inc()
    metrics.TOKENS_USED.labels(policy.name).inc(rec.prompt_tokens + rec.output_tokens)
    metrics.EST_COST.labels(policy.name).inc(rec.est_cost_usd)
    try:
        store.log_request(policy=policy.name, domain=req.domain, served_from=rec.served_from, tier=rec.tier,
                          model=rec.model, prompt_tokens=rec.prompt_tokens, output_tokens=rec.output_tokens,
                          cost_usd=rec.cost_usd, est_cost_usd=rec.est_cost_usd, latency_ms=rec.latency_ms,
                          detail={"route_rule": rec.route_rule, "cache_similarity": rec.cache_similarity,
                                  "context_words": rec.context_words, "retrieved_words": rec.retrieved_words})
    except Exception as exc:  # logging must never fail a user request
        log.warning("request log failed: %s", exc)
    return {
        "answer": rec.answer,
        "served_from": rec.served_from,
        "cache_similarity": rec.cache_similarity,
        "tier": rec.tier,
        "route_rule": rec.route_rule,
        "model": rec.model,
        "tokens": {"prompt": rec.prompt_tokens, "output": rec.output_tokens},
        "context_words": {"retrieved": rec.retrieved_words, "sent": rec.context_words},
        "cost_usd": rec.cost_usd,
        "est_cost_usd_at_paid_prices": rec.est_cost_usd,
        "latency_ms": {"total": round(rec.latency_ms, 1), "model": round(rec.llm_ms, 1),
                       "overhead": round(rec.overhead_ms, 1)},
        "sources": rec.retrieved_docs,
    }


@app.get("/v1/stats")
def stats(policy: str | None = None) -> dict:
    return {**store.summary(policy), "daily_calls_used": _calls["n"], "daily_call_budget": MAX_DAILY_CALLS}


@app.get("/v1/requests")
def requests_log(limit: int = 50) -> list[dict]:
    return store.recent(min(limit, 500))


@app.get("/v1/experiments/latest")
def latest_experiment(include_records: bool = False) -> dict:
    p = ROOT / "results" / "latest.json"
    if not p.exists():
        raise HTTPException(404, "no published experiment yet (run `frugal run --publish`)")
    data = json.loads(p.read_text())
    if not include_records:
        data.pop("records", None)
    return data


@app.get("/v1/policies")
def policies() -> dict:
    return {n: load_policy(n).model_dump() for n in list_policies()}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/metrics")
def prom() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
