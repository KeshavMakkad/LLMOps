"""Deterministic fake models for tests and offline runs.

The cheap tier drops numbers and the fake grader scores by word overlap with the reference,
so the levers still have measurable effects without any API calls.
"""

from __future__ import annotations

import hashlib
import json
import re

_WORD = re.compile(r"[a-z0-9₹%.]+")


def _h(*parts: str) -> int:
    return int(hashlib.md5("||".join(parts).encode()).hexdigest()[:8], 16)


def _between(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


def fake_completion(model: str, system: str, user: str, json_mode: bool) -> str:
    if "RESPONSE_FORMAT: grade" in user:
        ref = _words(_between(user, "reference_answer"))
        ans = _words(_between(user, "answer"))
        overlap = len(ref & ans) / max(1, len(ref))
        score = 1 + round(4 * min(1.0, overlap * 1.6))
        return json.dumps({"reason": f"fake overlap {overlap:.2f}", "score": int(score)})

    question = _between(user, "question")
    docs = _between(user, "documents")
    # Prefer document sentences that share words with the question.
    q = _words(question)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", docs) if s.strip()]
    ranked = sorted(sentences, key=lambda s: -len(q & _words(s)))
    body = " ".join(ranked[:3]) if ranked else f"General answer about: {question}"
    if "lite" in model:
        body = re.sub(r"\d[\d,.]*", "some", body)  # the cheap tier is sloppy with numbers
    return f"{body} (answered by {model})"
