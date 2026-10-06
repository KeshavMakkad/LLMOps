"""Request log for the API (Postgres via DATABASE_URL, SQLite otherwise)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    __tablename__ = "request_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    policy: Mapped[str] = mapped_column(String(64))
    domain: Mapped[str] = mapped_column(String(32))
    served_from: Mapped[str] = mapped_column(String(20))
    tier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    for old in ("postgres://", "postgresql://"):
        if url.startswith(old):
            return url.replace(old, "postgresql+psycopg://", 1)
    if not url:
        Path(".frugal").mkdir(exist_ok=True)
        return "sqlite:///.frugal/frugal.db"
    return url


@lru_cache
def engine():
    url = _db_url()
    kw = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, **kw)
    Base.metadata.create_all(eng)
    return eng


def log_request(**fields) -> None:
    with Session(engine()) as s:
        s.add(RequestLog(ts=datetime.now(timezone.utc), **fields))
        s.commit()


def summary(policy: str | None = None) -> dict:
    with Session(engine()) as s:
        q = select(RequestLog.served_from, func.count(), func.sum(RequestLog.prompt_tokens + RequestLog.output_tokens),
                   func.sum(RequestLog.cost_usd), func.sum(RequestLog.est_cost_usd), func.avg(RequestLog.latency_ms))
        if policy:
            q = q.where(RequestLog.policy == policy)
        rows = s.execute(q.group_by(RequestLog.served_from)).all()
    out = {r[0]: {"requests": r[1], "tokens": int(r[2] or 0), "cost_usd": float(r[3] or 0),
                  "est_cost_usd": float(r[4] or 0), "avg_latency_ms": float(r[5] or 0)} for r in rows}
    total = sum(v["requests"] for v in out.values())
    hits = sum(v["requests"] for k, v in out.items() if k.endswith("cache"))
    return {"by_source": out, "requests": total, "hit_rate": hits / total if total else 0.0}


def recent(limit: int = 50) -> list[dict]:
    with Session(engine()) as s:
        rows = s.scalars(select(RequestLog).order_by(RequestLog.id.desc()).limit(limit)).all()
    return [{"ts": r.ts.isoformat(), "policy": r.policy, "domain": r.domain, "served_from": r.served_from,
             "tier": r.tier, "tokens": r.prompt_tokens + r.output_tokens, "cost_usd": r.cost_usd,
             "est_cost_usd": r.est_cost_usd, "latency_ms": r.latency_ms, **(r.detail or {})} for r in rows]
