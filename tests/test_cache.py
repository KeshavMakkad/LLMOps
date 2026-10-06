import numpy as np

from frugal.cache import SemanticCache, cache_scope, numbers_in
from frugal.config import CacheCfg


def test_numbers_normalise_indian_units():
    assert numbers_in("tax on 15L") == numbers_in("tax on ₹15 lakh") == numbers_in("Rs 15,00,000 income")
    assert numbers_in("turnover 1.2 cr") == frozenset({12000000.0})
    assert numbers_in("no numbers") == frozenset()


def _vec(*xs):
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_exact_hit_and_scope_isolation():
    c = SemanticCache(CacheCfg(exact=True, semantic=False))
    s1, s2 = cache_scope("tax", None), cache_scope("tax", "pasted clause A")
    c.store(s1, "What is 80C?", "ans", "r1", "g1")
    assert c.lookup(s1, "  what is 80c? ").kind == "exact"
    assert c.lookup(s2, "What is 80C?") is None  # same question, different pasted text: never shared


def test_number_guard_blocks_near_miss_but_not_paraphrase():
    cfg = CacheCfg(exact=False, semantic=True, threshold=0.9, number_guard=True)
    c = SemanticCache(cfg)
    s = cache_scope("tax", None)
    c.store(s, "tax on 15L income new regime", "A15", "r1", "g1", _vec(1, 0))
    assert c.lookup(s, "tax for 18 lakh income, new regime", _vec(1, 0.01)) is None
    assert c.lookup(s, "new regime tax if I earn ₹15 lakh", _vec(1, 0.01)).entry.answer == "A15"
    assert c.stats.rejected_by_numbers == 1


def test_threshold_respected():
    c = SemanticCache(CacheCfg(semantic=True, threshold=0.99))
    s = cache_scope("github", None)
    c.store(s, "q", "a", "r1", "g1", _vec(1, 0))
    assert c.lookup(s, "q2", _vec(1, 0.5)) is None
