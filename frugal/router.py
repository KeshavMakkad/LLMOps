"""Model downshift: ordered rules decide which tier answers a request."""

from __future__ import annotations

import re

from frugal.config import DownshiftCfg


def words(text: str) -> int:
    return len(text.split())


# Any number, or wording that asks for a calculation. A missed "2.5 years" sent a limitation-period
# question to the cheap tier, which got it wrong, so this errs towards the strong tier.
_NUMERIC = re.compile(r"(\d|₹|calculat|compute|how much|how many|total|overage)", re.IGNORECASE)


def route(question: str, user_context: str | None, top_rerank: float | None, cfg: DownshiftCfg,
          default_tier: str) -> tuple[str, str]:
    """Returns (tier, rule name). Features are computed from the request only; no labels."""
    if not cfg.enabled:
        return default_tier, "disabled"
    feats = {
        "has_user_context": bool(user_context),
        "numeric_reasoning": bool(_NUMERIC.search(question)),
        "question_words": words(question),
        "top_rerank": top_rerank,
    }
    for r in cfg.rules:
        if r.has_user_context is not None and r.has_user_context != feats["has_user_context"]:
            continue
        if r.numeric_reasoning is not None and r.numeric_reasoning != feats["numeric_reasoning"]:
            continue
        if r.max_question_words is not None and feats["question_words"] > r.max_question_words:
            continue
        if r.min_top_rerank_score is not None and (top_rerank is None or top_rerank < r.min_top_rerank_score):
            continue
        return r.tier, r.name
    return default_tier, "default"
