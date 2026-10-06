"""Response cache keyed on the full request (SQLite, or Postgres with FRUGAL_CACHE_BACKEND=postgres)."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_pg_ready = False


def enabled() -> bool:
    return os.environ.get("FRUGAL_CACHE", "on").lower() not in ("off", "0", "false")


def _use_pg() -> bool:
    return os.environ.get("FRUGAL_CACHE_BACKEND") == "postgres" and bool(os.environ.get("DATABASE_URL"))


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        cache_dir = Path(os.environ.get("FRUGAL_CACHE_DIR", ".frugal/cache"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(cache_dir / "llm.sqlite", check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        _conn.commit()
    return _conn


def _pg():
    global _pg_ready
    from sqlalchemy import text

    from frugal.store import engine

    eng = engine()
    if not _pg_ready:
        with eng.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS llm_cache (k TEXT PRIMARY KEY, v TEXT NOT NULL)"))
        _pg_ready = True
    return eng, text


def make_key(namespace: str, payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return namespace + ":" + hashlib.sha256(blob.encode()).hexdigest()


def get(key: str) -> dict | None:
    if not enabled():
        return None
    if _use_pg():
        eng, text = _pg()
        with eng.connect() as c:
            row = c.execute(text("SELECT v FROM llm_cache WHERE k = :k"), {"k": key}).fetchone()
    else:
        with _lock:
            row = _db().execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def put(key: str, value: dict) -> None:
    if not enabled():
        return
    if _use_pg():
        eng, text = _pg()
        with eng.begin() as c:
            c.execute(text("INSERT INTO llm_cache (k, v) VALUES (:k, :v) ON CONFLICT (k) DO NOTHING"),
                      {"k": key, "v": json.dumps(value)})
        return
    with _lock:
        _db().execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (key, json.dumps(value)))
        _db().commit()
