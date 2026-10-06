"""Context-window management (rerank + truncation) and query-aware prompt compression."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

import numpy as np

from frugal.config import CompressionCfg, ContextCfg, RetrievalCfg
from frugal.rag.corpus import Chunk
from frugal.rag.embed import embed_texts
from frugal.rag.index import retrieve


def words(text: str) -> int:
    return len(text.split())


_reranker = None
_rerank_lock = threading.Lock()
RERANK_MODEL = os.environ.get("FRUGAL_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")


def _rerank_scores(query: str, texts: list[str]) -> list[float]:
    if os.environ.get("FRUGAL_FAKE_EMBED") == "1":  # offline: lexical overlap stands in
        q = set(query.lower().split())
        return [float(len(q & set(t.lower().split()))) for t in texts]
    global _reranker
    with _rerank_lock:
        if _reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _reranker = TextCrossEncoder(RERANK_MODEL)
        return [float(s) for s in _reranker.rerank(query, texts, batch_size=8)]


@dataclass
class ContextResult:
    chunks: list[Chunk]
    retrieved_words: int  # before any context management
    kept_words: int
    top_rerank_score: float | None
    retrieved_docs: list[str]


def build_context(domain: str, query: str, rcfg: RetrievalCfg, ccfg: ContextCfg) -> ContextResult:
    if not rcfg.enabled:
        return ContextResult([], 0, 0, None, [])
    hits = retrieve(domain, query, rcfg.chunk_words, rcfg.overlap_words, rcfg.top_k)
    chunks = [h.chunk for h in hits]
    before = sum(words(c.text) for c in chunks)
    top = None
    if ccfg.rerank and chunks:
        scores = _rerank_scores(query, [c.text for c in chunks])
        order = np.argsort(scores)[::-1]
        chunks = [chunks[i] for i in order]
        top = float(scores[order[0]])
    chunks = chunks[: ccfg.keep]
    if ccfg.max_context_words:
        kept, budget = [], ccfg.max_context_words
        for c in chunks:  # truncation policy: keep whole chunks in rank order until the budget
            if words(c.text) > budget:
                break
            kept.append(c)
            budget -= words(c.text)
        chunks = kept or chunks[:1]
    after = sum(words(c.text) for c in chunks)
    return ContextResult(chunks, before, after, top, list(dict.fromkeys(c.doc_id for c in chunks)))


# prompt compression

_SENT = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z(\[])")  # never split before a digit ("Rs. 40")
_ABBREV = re.compile(r"\b(?:Rs|No|Sec|Sr|Dr|Mr|Ms|Inc|Ltd|e\.g|i\.e|etc|vs|viz|Art|Cl)\.$", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for part in _SENT.split(text):
        if out and _ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def compress_chunks(query: str, chunks: list[Chunk], cfg: CompressionCfg) -> tuple[list[Chunk], int, int]:
    """Keep the sentences most similar to the question (in original order) until ~target_ratio
    of the words remain. Sentences with numbers get a small bonus."""
    sents: list[tuple[int, str]] = []
    for ci, c in enumerate(chunks):
        for s in _sentences(c.text):
            if words(s) >= cfg.min_sentence_words:
                sents.append((ci, s.strip()))
    total = sum(words(c.text) for c in chunks)
    if not sents or total == 0:
        return chunks, total, total
    vecs = embed_texts([s for _, s in sents])
    q = embed_texts([query], task="RETRIEVAL_QUERY")[0]
    scores = vecs @ q + np.array([0.05 if re.search(r"\d", s) else 0.0 for _, s in sents])
    budget = max(1, int(total * cfg.target_ratio))
    keep, used = set(), 0
    for i in np.argsort(-scores):
        n = words(sents[i][1])
        if used + n > budget and keep:
            continue
        keep.add(int(i))
        used += n
    out = []
    for ci, c in enumerate(chunks):
        body = " ".join(s for j, (cj, s) in enumerate(sents) if cj == ci and j in keep)
        if body:
            title = c.text.split("\n", 1)[0] if c.text.startswith("[") else ""
            out.append(Chunk(c.chunk_id, c.doc_id, c.title, f"{title}\n{body}".strip()))
    return out, total, sum(words(c.text) for c in out)
