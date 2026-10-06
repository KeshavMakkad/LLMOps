"""LLM client for Gemini / OpenRouter / fake, with caching, rate limiting, retries and cost tracking."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from frugal import metrics, tracing
from frugal.config import ModelSpec, get_model
from frugal.llm import cache, ratelimit


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float  # actual USD paid for the original call ($0 on free tiers)
    est_cost_usd: float  # same tokens at published paid-tier prices (labelled estimate)
    latency_ms: float  # provider latency of the original call
    cached: bool = False


class LLMError(RuntimeError):
    pass


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 409, 429, 500, 502, 503, 504, 529)
    if isinstance(exc, (httpx.TransportError, TimeoutError)):
        return True
    name = type(exc).__name__
    # transient SDK errors, matched by name so we don't import every SDK here
    if name in ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
                "OverloadedError", "ServiceUnavailable", "ResourceExhausted"):
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code in (429, 500, 503, 504)


def cost_of(spec: ModelSpec, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * spec.input_per_mtok + output_tokens * spec.output_per_mtok) / 1_000_000


def paid_cost_of(spec: ModelSpec, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * spec.paid_input_per_mtok + output_tokens * spec.paid_output_per_mtok) / 1_000_000


# ------------------------------------------------------------------ providers

_gemini_client = None

# offline mode: cheap tier -> fake-lite (drops numbers), everything else -> fake
FAKE_MAP = {"gemma-26b": "fake-lite"}


def _call_gemini(spec: ModelSpec, system: str, user: str, temperature: float, max_tokens: int,
                 json_mode: bool) -> tuple[str, int, int]:
    global _gemini_client
    from google import genai
    from google.genai import types

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    if not spec.supports_system:
        user = f"{system}\n\n---\n\n{user}"
    if json_mode and not spec.supports_json_mode:
        user += "\n\nRespond with a single JSON object and nothing else."
    cfg = types.GenerateContentConfig(
        system_instruction=system if spec.supports_system else None,
        temperature=temperature,
        max_output_tokens=max_tokens,
        response_mime_type="application/json" if json_mode and spec.supports_json_mode else None,
        thinking_config=(types.ThinkingConfig(thinking_level=spec.thinking_level) if spec.thinking_level
                         else types.ThinkingConfig(thinking_budget=0) if spec.disable_thinking else None),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    resp = _gemini_client.models.generate_content(model=spec.model, contents=user, config=cfg)
    um = resp.usage_metadata
    in_tok = (um.prompt_token_count or 0) if um else 0
    out_tok = ((um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0)) if um else 0
    return resp.text or "", in_tok, out_tok


def _call_openrouter(spec: ModelSpec, system: str, user: str, temperature: float, max_tokens: int,
                     json_mode: bool) -> tuple[str, int, int, float | None]:
    body = {
        "model": spec.model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
                 "X-Title": "frugal"},
        json=body,
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    if "choices" not in data:
        raise LLMError(f"openrouter error: {data}")
    usage = data.get("usage", {})
    # OpenRouter reports what the call actually cost; prefer it over registry prices.
    return (data["choices"][0]["message"]["content"] or "", usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0), usage.get("cost"))


def _call_fake(spec: ModelSpec, system: str, user: str, temperature: float, max_tokens: int,
               json_mode: bool) -> tuple[str, int, int]:
    from frugal.llm.fake import fake_completion

    text = fake_completion(spec.model, system, user, json_mode)
    return text, len((system + user).split()), len(text.split())


_PROVIDERS = {
    "gemini": _call_gemini,
    "openrouter": _call_openrouter,
    "fake": _call_fake,
}


@retry(retry=retry_if_exception(_is_retryable), wait=wait_exponential(multiplier=2, min=2, max=60),
       stop=stop_after_attempt(6), reraise=True)
def _call_with_retry(spec: ModelSpec, *args) -> tuple[tuple, float]:
    """Returns (provider result, latency_ms of the successful attempt). Latency excludes our own
    rate-limit waits and retry backoff, so it measures the provider, not our throttling."""
    ratelimit.acquire(spec.key, spec.rpm)
    t0 = time.perf_counter()
    result = _PROVIDERS[spec.provider](spec, *args)
    return result, (time.perf_counter() - t0) * 1000


# ------------------------------------------------------------------ public API


def complete(
    model_key: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    json_mode: bool = False,
    purpose: str = "generation",
    trace_meta: dict | None = None,
) -> LLMResponse:
    if os.environ.get("FRUGAL_FAKE_LLM") == "1" and not model_key.startswith("fake"):
        model_key = FAKE_MAP.get(model_key, "fake")
    spec = get_model(model_key)
    key = cache.make_key("llm", {"provider": spec.provider, "model": spec.model, "system": system,
                                 "user": user, "temperature": temperature, "max_tokens": max_tokens,
                                 "json": json_mode, "thinking": spec.thinking_level or spec.disable_thinking})
    hit = cache.get(key)
    if hit is not None:
        resp = LLMResponse(**{**hit, "cached": True})
        metrics.record_llm(spec, purpose, resp, cached=True)
        return resp

    try:
        (text, in_tok, out_tok, *reported), latency_ms = _call_with_retry(
            spec, system, user, temperature, max_tokens, json_mode)
    except Exception as exc:
        metrics.LLM_ERRORS.labels(spec.provider, spec.model, purpose).inc()
        raise LLMError(f"{spec.key}: {type(exc).__name__}: {exc}") from exc
    resp = LLMResponse(text=text, model=spec.model, input_tokens=in_tok, output_tokens=out_tok,
                       cost_usd=reported[0] if reported and reported[0] is not None else cost_of(spec, in_tok, out_tok),
                       est_cost_usd=paid_cost_of(spec, in_tok, out_tok), latency_ms=latency_ms)
    cache.put(key, {k: v for k, v in asdict(resp).items() if k != "cached"})
    metrics.record_llm(spec, purpose, resp, cached=False)
    tracing.log_generation(name=purpose, spec=spec, system=system, user=user, resp=resp,
                           metadata=trace_meta or {})
    return resp


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json(text: str) -> dict:
    """Lenient JSON extraction: handles ```json fences and leading prose."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            raise
        return json.loads(m.group(0))

