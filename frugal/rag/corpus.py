"""Corpus loading and chunking."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import yaml

from frugal.config import DATA_DIR


@dataclass(frozen=True)
class Doc:
    doc_id: str
    title: str
    source_url: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # "<doc_id>#<n>"
    doc_id: str
    title: str
    text: str


def _parse(path) -> Doc:
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    domain = path.parent.name
    return Doc(
        doc_id=meta.get("doc_id") or f"{domain}/{path.stem}",
        title=str(meta.get("title", path.stem)),
        source_url=str(meta.get("source_url", "")),
        text=body.strip(),
    )


@lru_cache
def load_docs(domain: str) -> tuple[Doc, ...]:
    d = DATA_DIR / "corpus" / domain
    return tuple(_parse(p) for p in sorted(d.glob("*.md")))


def doc_ids(domain: str) -> set[str]:
    return {d.doc_id for d in load_docs(domain)}


def chunk_doc(doc: Doc, chunk_words: int, overlap_words: int) -> list[Chunk]:
    """Paragraph-aware fixed-size chunking: packs paragraphs up to `chunk_words`, splitting
    oversized paragraphs, with `overlap_words` carried over between chunks."""
    paras = [p.strip() for p in doc.text.split("\n\n") if p.strip()]
    words_stream: list[list[str]] = []
    for p in paras:
        w = p.split()
        for i in range(0, len(w), chunk_words):
            words_stream.append(w[i : i + chunk_words])

    chunks: list[Chunk] = []
    cur: list[str] = []
    for pw in words_stream:
        if cur and len(cur) + len(pw) > chunk_words:
            chunks.append(cur)
            cur = cur[-overlap_words:] if overlap_words else []
        cur = cur + pw
    if cur:
        chunks.append(cur)
    return [
        Chunk(chunk_id=f"{doc.doc_id}#{i}", doc_id=doc.doc_id, title=doc.title,
              text=f"[{doc.title}]\n" + " ".join(words))
        for i, words in enumerate(chunks)
    ]


def chunk_domain(domain: str, chunk_words: int, overlap_words: int) -> list[Chunk]:
    out: list[Chunk] = []
    for d in load_docs(domain):
        out.extend(chunk_doc(d, chunk_words, overlap_words))
    return out
