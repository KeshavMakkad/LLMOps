"""Optional Langfuse tracing (enabled when the keys are set)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from frugal.config import ModelSpec
    from frugal.llm.client import LLMResponse

log = logging.getLogger(__name__)
_client = None
_disabled = False


def _lf():
    global _client, _disabled
    if _disabled:
        return None
    if _client is None:
        if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
            _disabled = True
            return None
        try:
            from langfuse import Langfuse

            _client = Langfuse()
        except Exception as exc:  # tracing must never break an eval
            log.warning("langfuse disabled: %s", exc)
            _disabled = True
            return None
    return _client


def log_generation(name: str, spec: "ModelSpec", system: str, user: str, resp: "LLMResponse",
                   metadata: dict) -> None:
    lf = _lf()
    if lf is None:
        return
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(milliseconds=resp.latency_ms)
        trace_id = metadata.get("run_id")
        lf.generation(
            trace_id=trace_id,
            name=name,
            model=spec.model,
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            output=resp.text,
            start_time=start,
            end_time=end,
            usage={"input": resp.input_tokens, "output": resp.output_tokens, "unit": "TOKENS",
                   "total_cost": resp.cost_usd},
            metadata={**metadata, "provider": spec.provider},
        )
    except Exception as exc:
        log.debug("langfuse log failed: %s", exc)


def flush() -> None:
    lf = _lf()
    if lf is not None:
        try:
            lf.flush()
        except Exception:
            pass
