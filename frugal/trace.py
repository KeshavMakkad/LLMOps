"""Fixed request trace used for all experiments.

Per eval item: the original question, a paraphrase, sometimes an exact repeat, and for about
half of them a near-miss (similar wording, different correct answer). Requests in the same
group_id may share an answer.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from functools import lru_cache

from pydantic import BaseModel

from frugal.config import DATA_DIR

REPEAT_FRACTION = 0.3  # share of items that get an exact resend (real traffic repeats itself)


class EvalItem(BaseModel):
    id: str
    domain: str
    subdomain: str = ""
    task_type: str = "qa"
    question: str
    context: str | None = None
    reference_answer: str = ""
    source_docs: list[str] = []
    expected_behavior: str = "answer"
    format_spec: str | None = None
    difficulty: str = "medium"
    tags: list[str] = []


class Request(BaseModel):
    req_id: str
    group_id: str
    kind: str  # original | paraphrase | repeat | near_miss
    item_id: str
    domain: str
    question: str
    context: str | None = None

    @property
    def has_reference(self) -> bool:
        return self.kind != "near_miss"


@lru_cache
def load_items() -> dict[str, EvalItem]:
    items = {}
    for p in sorted((DATA_DIR / "eval").glob("*.jsonl")):
        if p.name.startswith("_"):
            continue
        for line in p.read_text().splitlines():
            if line.strip():
                it = EvalItem(**json.loads(line))
                items[it.id] = it
    return items


def _variants() -> dict[str, dict]:
    p = DATA_DIR / "trace" / "variants.jsonl"
    if not p.exists():
        return {}
    return {v["item_id"]: v for v in (json.loads(x) for x in p.read_text().splitlines() if x.strip())}


def build_trace(seed: int = 7, max_groups: int | None = None) -> list[Request]:
    """Deterministic trace. max_groups samples eval items stratified by domain (all of an item's
    requests come along), so small CI traces still contain hits and near-misses."""
    items = load_items()
    variants = _variants()
    rng = random.Random(seed)

    ids = sorted(items)
    if max_groups and max_groups < len(ids):
        by_domain: dict[str, list[str]] = defaultdict(list)
        for i in ids:
            by_domain[items[i].domain].append(i)
        per = max(1, max_groups // len(by_domain))
        picked = []
        for d in sorted(by_domain):
            pool = by_domain[d][:]
            rng.shuffle(pool)
            # Prefer items that have a near-miss so the false-hit metric has support.
            pool.sort(key=lambda i: variants.get(i, {}).get("near_miss") is None)
            picked += pool[:per]
        ids = sorted(picked)

    reqs: list[Request] = []
    for iid in ids:
        it, v = items[iid], variants.get(iid, {})
        base = {"item_id": iid, "domain": it.domain, "context": it.context}
        reqs.append(Request(req_id=f"{iid}:o", group_id=iid, kind="original", question=it.question, **base))
        if v.get("paraphrase"):
            reqs.append(Request(req_id=f"{iid}:p", group_id=iid, kind="paraphrase", question=v["paraphrase"], **base))
        if rng.random() < REPEAT_FRACTION:
            reqs.append(Request(req_id=f"{iid}:r", group_id=iid, kind="repeat", question=it.question, **base))
        if v.get("near_miss"):
            reqs.append(Request(req_id=f"{iid}:n", group_id=f"{iid}:near", kind="near_miss",
                                question=v["near_miss"], **base))
    # Traffic order is shuffled: whichever request of a group arrives first is answered by the
    # model, and later ones can be served from cache. Correctness is judged by group_id, not order.
    rng.shuffle(reqs)
    return reqs
