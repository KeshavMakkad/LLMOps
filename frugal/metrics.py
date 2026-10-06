"""Prometheus metrics, served at /metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram

if TYPE_CHECKING:
    from frugal.config import ModelSpec
    from frugal.llm.client import LLMResponse

LLM_REQUESTS = Counter("frugal_llm_requests_total", "LLM calls", ["provider", "model", "purpose", "cached"])
LLM_ERRORS = Counter("frugal_llm_errors_total", "LLM call failures", ["provider", "model", "purpose"])
LLM_TOKENS = Counter("frugal_llm_tokens_total", "Tokens (uncached calls)", ["model", "direction"])
LLM_COST = Counter("frugal_llm_cost_usd_total", "Actual USD spent on uncached calls", ["model", "purpose"])
LLM_LATENCY = Histogram(
    "frugal_llm_latency_seconds", "Provider latency of uncached calls", ["model", "purpose"],
    buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32, 64),
)
HTTP_LATENCY = Histogram(
    "frugal_http_request_seconds", "API request latency", ["route", "method", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
PIPELINE_REQUESTS = Counter("frugal_requests_total", "Requests through the optimiser",
                            ["policy", "served_from", "tier"])
TOKENS_USED = Counter("frugal_tokens_total", "Prompt+output tokens actually sent to models", ["policy"])
EST_COST = Counter("frugal_est_cost_usd_total", "Spend at paid-tier prices (estimate)", ["policy"])


def record_llm(spec: "ModelSpec", purpose: str, resp: "LLMResponse", cached: bool) -> None:
    LLM_REQUESTS.labels(spec.provider, spec.model, purpose, str(cached).lower()).inc()
    if cached:
        return
    LLM_TOKENS.labels(spec.model, "input").inc(resp.input_tokens)
    LLM_TOKENS.labels(spec.model, "output").inc(resp.output_tokens)
    LLM_COST.labels(spec.model, purpose).inc(resp.cost_usd)
    LLM_LATENCY.labels(spec.model, purpose).observe(resp.latency_ms / 1000)
