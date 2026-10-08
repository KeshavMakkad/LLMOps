"""Embeddings. Backends: local fastembed (default), gemini, fake (tests)."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from frugal.llm import cache, ratelimit

LOCAL_MODEL = os.environ.get("FRUGAL_LOCAL_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
GEMINI_MODEL = os.environ.get("FRUGAL_EMBED_MODEL", "gemini-embedding-001")
_DIMS = {"local": 384, "gemini": 768, "fake": 384}
# Gemini's free-tier quota counts every text in a batch, so keep batches small and paced.
GEMINI_BATCH = int(os.environ.get("FRUGAL_EMBED_BATCH", "20"))
EMBED_BATCH_LOCAL = int(os.environ.get("FRUGAL_LOCAL_EMBED_BATCH", "8"))

_gemini_client = None
_local_model = None
_local_lock = threading.Lock()
_vec_conn: sqlite3.Connection | None = None


def backend() -> str:
    if os.environ.get("FRUGAL_FAKE_EMBED") == "1":
        return "fake"
    return os.environ.get("FRUGAL_EMBED_BACKEND", "local")


def embed_dim() -> int:
    return _DIMS[backend()]


def model_id() -> str:
    return {"local": LOCAL_MODEL, "gemini": GEMINI_MODEL, "fake": "fake-hash"}[backend()]


# ------------------------------------------------------------------ backends


def _fake(texts: list[str]) -> np.ndarray:
    dim = _DIMS["fake"]
    m = np.zeros((len(texts), dim), dtype=np.float32)
    for r, text in enumerate(texts):
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
            m[r, h % dim] += 1.0 if (h >> 12) % 2 else -1.0
    return m


def _vec_db() -> sqlite3.Connection:
    """Local vector cache (SQLite). Filled by `frugal build-index` at image build time."""
    global _vec_conn
    if _vec_conn is None:
        path = Path(os.environ.get("FRUGAL_EMBED_CACHE", ".frugal/embeddings.sqlite"))
        path.parent.mkdir(parents=True, exist_ok=True)
        _vec_conn = sqlite3.connect(path, check_same_thread=False)
        _vec_conn.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, v BLOB NOT NULL)")
        _vec_conn.commit()
    return _vec_conn


def _local(texts: list[str], task: str) -> np.ndarray:
    keys = [hashlib.sha256(f"{LOCAL_MODEL}|{task}|{t}".encode()).hexdigest() for t in texts]
    found: dict[str, np.ndarray] = {}
    with _local_lock:
        db = _vec_db()
        for i in range(0, len(keys), 500):
            part = keys[i : i + 500]
            rows = db.execute(f"SELECT k, v FROM emb WHERE k IN ({','.join('?' * len(part))})", part).fetchall()
            found.update({k: np.frombuffer(v, dtype=np.float32) for k, v in rows})
    missing = [i for i, k in enumerate(keys) if k not in found]
    if missing:
        vecs = _local_model_embed([texts[i] for i in missing], task)
        with _local_lock:
            _vec_db().executemany("INSERT OR REPLACE INTO emb (k, v) VALUES (?, ?)",
                                  [(keys[i], v.tobytes()) for i, v in zip(missing, vecs)])
            _vec_db().commit()
        for i, v in zip(missing, vecs):
            found[keys[i]] = v
    return np.vstack([found[k] for k in keys])


def _local_model_embed(texts: list[str], task: str) -> np.ndarray:
    global _local_model
    with _local_lock:  # the ONNX session is not safe to initialise concurrently
        if _local_model is None:
            from fastembed import TextEmbedding

            # no ONNX memory arena: it holds on to peak buffers, too much for a 512 MB instance
            _local_model = TextEmbedding(LOCAL_MODEL, threads=int(os.environ.get("FRUGAL_EMBED_THREADS", "1")),
                                         enable_cpu_mem_arena=False)
        # bge uses an instruction prefix for queries; query_embed applies it.
        fn = _local_model.query_embed if task == "RETRIEVAL_QUERY" else _local_model.embed
        # Small batches: ONNX Runtime's memory arena grows to the largest batch it has seen,
        # and 64 x 512-token batches pushed RSS past 2.5 GB (Render free has 512 MB).
        return np.asarray(list(fn(texts, batch_size=EMBED_BATCH_LOCAL)), dtype=np.float32)


def _retryable(exc: BaseException) -> bool:
    return getattr(exc, "code", None) in (429, 500, 503, 504)


@retry(retry=retry_if_exception(_retryable), wait=wait_exponential(multiplier=4, min=5, max=90),
       stop=stop_after_attempt(8), reraise=True)
def _gemini_batch(contents: list[str], task: str):
    global _gemini_client
    from google import genai
    from google.genai import types

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    ratelimit.acquire("embeddings", int(os.environ.get("FRUGAL_EMBED_RPM", "30")))
    return _gemini_client.models.embed_content(
        model=GEMINI_MODEL, contents=contents,
        config=types.EmbedContentConfig(task_type=task, output_dimensionality=_DIMS["gemini"]),
    )


def _gemini(texts: list[str], task: str) -> np.ndarray:
    """Cached per text: the API is quota-limited, so never embed the same text twice."""
    keys = [cache.make_key("emb", {"m": GEMINI_MODEL, "t": task, "d": _DIMS["gemini"], "x": t}) for t in texts]
    out: list[list[float] | None] = []
    for k in keys:
        hit = cache.get(k)
        out.append(hit["v"] if hit else None)
    missing = [i for i, v in enumerate(out) if v is None]
    for start in range(0, len(missing), GEMINI_BATCH):
        idx = missing[start : start + GEMINI_BATCH]
        resp = _gemini_batch([texts[i] for i in idx], task)
        for i, e in zip(idx, resp.embeddings):
            out[i] = list(e.values)
            cache.put(keys[i], {"v": out[i]})
    return np.asarray(out, dtype=np.float32)


def embed_texts(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
    """Returns an L2-normalised (n, embed_dim()) float32 matrix."""
    if not texts:
        return np.zeros((0, embed_dim()), dtype=np.float32)
    b = backend()
    m = _fake(texts) if b == "fake" else _local(texts, task) if b == "local" else _gemini(texts, task)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms
