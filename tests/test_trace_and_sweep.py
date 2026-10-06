from frugal.config import CacheCfg
from frugal.rag.embed import embed_texts
from frugal.sweep import simulate
from frugal.trace import Request, build_trace


def test_trace_is_deterministic_and_complete():
    a, b = build_trace(seed=7), build_trace(seed=7)
    assert [r.req_id for r in a] == [r.req_id for r in b]
    kinds = {r.kind for r in a}
    assert {"original", "paraphrase", "near_miss", "repeat"} <= kinds
    assert len({r.item_id for r in a}) == 100


def test_small_trace_keeps_whole_groups():
    t = build_trace(max_groups=8)
    items = {r.item_id for r in t}
    assert len(items) == 8
    assert all(f"{i}:o" in {r.req_id for r in t} for i in items)


def test_simulate_counts_false_hits_by_group():
    mk = lambda rid, gid, q, kind="original": Request(req_id=rid, group_id=gid, kind=kind, item_id=gid[:3],  # noqa: E731
                                                      domain="tax", question=q)
    trace = [mk("a", "g1", "tax on salary"), mk("b", "g1", "tax on salary", "repeat"),
             mk("c", "g1:near", "tax on salary", "near_miss")]
    vecs = embed_texts([r.question for r in trace])
    res = simulate(trace, CacheCfg(exact=True, semantic=True, threshold=0.5), vecs)
    assert res["hits"] == 2 and res["false_hits"] == 1 and res["near_miss_false_hit_rate"] == 1.0
