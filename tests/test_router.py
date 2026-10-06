from frugal.config import DownshiftCfg, DownshiftRule, load_policy
from frugal.router import route


def test_routing_rules_first_match_wins():
    cfg = DownshiftCfg(enabled=True, rules=[
        DownshiftRule(name="ctx", tier="strong", has_user_context=True),
        DownshiftRule(name="num", tier="strong", numeric_reasoning=True),
        DownshiftRule(name="rest", tier="cheap")])
    assert route("explain this clause", "clause text", None, cfg, "strong") == ("strong", "ctx")
    assert route("how much tax on 12 lakh?", None, None, cfg, "strong") == ("strong", "num")
    assert route("what is a ruleset?", None, None, cfg, "strong") == ("cheap", "rest")
    assert route("anything", None, None, DownshiftCfg(enabled=False), "strong") == ("strong", "disabled")


def test_any_number_routes_to_strong():
    p = load_policy("optimized")
    assert route("my complaint is 2.5 years old, can I still file?", None, None, p.downshift, "strong")[0] == "strong"
