"""Semantic cache: exact match, then embedding similarity, guarded against near-miss questions."""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field

import numpy as np

from frugal.config import CacheCfg
from frugal.rag.embed import embed_texts


def _normalise(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def cache_scope(domain: str, context: str | None) -> str:
    """Entries only match within the same domain AND the same pasted user text: 'explain this
    clause' about two different clauses must never share an answer."""
    return f"{domain}|{hashlib.sha256((context or '').encode()).hexdigest()[:16]}"


@dataclass
class CacheEntry:
    scope: str
    question: str
    norm_question: str
    vec: np.ndarray
    answer: str
    req_id: str
    group_id: str  # evaluation bookkeeping only (decides whether a hit was correct)


@dataclass
class CacheHit:
    kind: str  # exact | semantic
    similarity: float
    entry: CacheEntry


_UNIT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "l": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "k": 1e3}
_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lac|crores?|cr|l|k)?\b", re.IGNORECASE)


def numbers_in(text: str) -> frozenset[float]:
    """Numeric values in a question, with Indian units normalised (15L == 15 lakh == 15,00,000)."""
    out = set()
    for num, unit in _NUM.findall(text):
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        out.add(round(v * _UNIT.get(unit.lower(), 1.0), 4))
    return frozenset(out)


@dataclass
class GuardStats:
    candidates: int = 0
    rejected_by_numbers: int = 0
    rejected_by_verifier: int = 0
    verifier_calls: int = 0
    verifier_tokens: int = 0
    verifier_est_cost_usd: float = 0.0


@dataclass
class SemanticCache:
    cfg: CacheCfg
    entries: list[CacheEntry] = field(default_factory=list)
    stats: GuardStats = field(default_factory=GuardStats)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def lookup(self, scope: str, question: str, vec: np.ndarray | None = None, domain: str = "") -> CacheHit | None:
        if not (self.cfg.exact or self.cfg.semantic):
            return None
        norm = _normalise(question)
        with self._lock:
            pool = [e for e in self.entries if e.scope == scope]
        if self.cfg.exact:
            for e in pool:
                if e.norm_question == norm:
                    return CacheHit("exact", 1.0, e)
        if not (self.cfg.semantic and pool):
            return None
        v = vec if vec is not None else embed_question(question)
        sims = np.stack([e.vec for e in pool]) @ v
        for i in np.argsort(-sims)[: self.cfg.max_candidates]:
            if sims[i] < self.cfg.threshold:
                break
            e = pool[int(i)]
            self.stats.candidates += 1
            if self.cfg.number_guard and numbers_in(e.question) != numbers_in(question):
                self.stats.rejected_by_numbers += 1
                continue
            if self.cfg.verify_model and not self._verify(e.question, question, domain):
                self.stats.rejected_by_verifier += 1
                continue
            return CacheHit("semantic", float(sims[i]), e)
        return None

    def _verify(self, cached_q: str, new_q: str, domain: str) -> bool:
        from frugal.llm import LLMError, complete, parse_json

        user = (f"Domain: {domain}\nQuestion A: {cached_q}\nQuestion B: {new_q}\n\n"
                "Would exactly the same answer be fully correct for both questions? Answer false if any "
                "detail that could change the answer differs (amounts, dates, plan, product, role, "
                "condition, before/after, which party). Return ONLY JSON: {\"same\": true|false}")
        try:
            r = complete(self.cfg.verify_model, "You check whether two user questions are equivalent.", user,
                         max_tokens=50, json_mode=True, purpose="cache_verify")
        except LLMError:
            return False  # fail closed: when unsure, call the model instead of serving a maybe-wrong answer
        self.stats.verifier_calls += 1
        self.stats.verifier_tokens += r.input_tokens + r.output_tokens
        self.stats.verifier_est_cost_usd += r.est_cost_usd
        try:
            return bool(parse_json(r.text).get("same"))
        except Exception:
            return False

    def store(self, scope: str, question: str, answer: str, req_id: str, group_id: str,
              vec: np.ndarray | None = None) -> None:
        if not (self.cfg.exact or self.cfg.semantic):
            return
        v = vec if vec is not None else embed_question(question)
        with self._lock:
            self.entries.append(CacheEntry(scope, question, _normalise(question), v, answer, req_id, group_id))


def embed_question(question: str) -> np.ndarray:
    # Symmetric (question-vs-question) similarity, so both sides use the document embedding.
    return embed_texts([question])[0]
