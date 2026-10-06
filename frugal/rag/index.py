"""Vector index per (domain, chunking): in-memory numpy, or pgvector."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import numpy as np

from frugal.rag.corpus import Chunk, chunk_domain
from frugal.rag.embed import embed_dim, embed_texts, model_id


@dataclass
class Hit:
    chunk: Chunk
    score: float


class MemoryIndex:
    def __init__(self, domain: str, chunk_words: int, overlap_words: int):
        self.chunks = chunk_domain(domain, chunk_words, overlap_words)
        self.matrix = embed_texts([c.text for c in self.chunks])

    def search(self, query: str, top_k: int) -> list[Hit]:
        if not self.chunks:
            return []
        q = embed_texts([query], task="RETRIEVAL_QUERY")[0]
        scores = self.matrix @ q
        idx = np.argsort(-scores)[:top_k]
        return [Hit(self.chunks[i], float(scores[i])) for i in idx]


class PgVectorIndex:
    def __init__(self, domain: str, chunk_words: int, overlap_words: int):
        from sqlalchemy import text

        from frugal.store import engine

        self.cfg = f"{model_id()}:{domain}:{chunk_words}:{overlap_words}"
        self.table = f"rag_chunks_{embed_dim()}"  # one table per vector width
        self.engine = engine()
        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(
                f"CREATE TABLE IF NOT EXISTS {self.table} (cfg TEXT, chunk_id TEXT, doc_id TEXT, title TEXT, "
                f"body TEXT, embedding vector({embed_dim()}), PRIMARY KEY (cfg, chunk_id))"))
            n = conn.execute(text(f"SELECT count(*) FROM {self.table} WHERE cfg = :c"), {"c": self.cfg}).scalar()
        if not n:
            chunks = chunk_domain(domain, chunk_words, overlap_words)
            vecs = embed_texts([c.text for c in chunks])
            with self.engine.begin() as conn:
                for c, v in zip(chunks, vecs):
                    conn.execute(
                        text(f"INSERT INTO {self.table} VALUES (:cfg, :id, :doc, :title, :body, :emb) "
                             "ON CONFLICT DO NOTHING"),
                        {"cfg": self.cfg, "id": c.chunk_id, "doc": c.doc_id, "title": c.title,
                         "body": c.text, "emb": str(v.tolist())})

    def search(self, query: str, top_k: int) -> list[Hit]:
        from sqlalchemy import text

        q = embed_texts([query], task="RETRIEVAL_QUERY")[0]
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT chunk_id, doc_id, title, body, 1 - (embedding <=> CAST(:q AS vector)) AS s "
                     f"FROM {self.table} WHERE cfg = :c ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"),
                {"q": str(q.tolist()), "c": self.cfg, "k": top_k}).fetchall()
        return [Hit(Chunk(r[0], r[1], r[2], r[3]), float(r[4])) for r in rows]


_indexes: dict[tuple, object] = {}
_lock = threading.Lock()


def get_index(domain: str, chunk_words: int, overlap_words: int):
    key = (domain, chunk_words, overlap_words)
    with _lock:
        if key not in _indexes:
            use_pg = (os.environ.get("FRUGAL_VECTOR_BACKEND") == "pgvector"
                      and os.environ.get("DATABASE_URL", "").startswith("postgres"))
            _indexes[key] = (PgVectorIndex if use_pg else MemoryIndex)(domain, chunk_words, overlap_words)
        return _indexes[key]


def retrieve(domain: str, query: str, chunk_words: int, overlap_words: int, top_k: int) -> list[Hit]:
    return get_index(domain, chunk_words, overlap_words).search(query, top_k)
