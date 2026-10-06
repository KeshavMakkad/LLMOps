"""Eval gate for policy changes.

Fails if quality drops significantly vs naive, if too many cache hits are false hits,
or if the token savings fall below the configured floor.
"""

from __future__ import annotations

from pydantic import BaseModel

from frugal.config import CONFIG_DIR, _load_yaml


class GateCfg(BaseModel):
    max_quality_drop: float = 0.25
    max_false_hit_rate: float = 0.05
    min_tokens_saved: float = 0.20


def load_gate() -> GateCfg:
    p = CONFIG_DIR / "gate.yaml"
    return GateCfg(**_load_yaml(p)) if p.exists() else GateCfg()


def evaluate(cand: dict, cfg: GateCfg) -> dict:
    d = cand.get("quality_delta") or {}
    checks = [
        {"check": "quality vs naive (judge score Δ, 95% CI)",
         "value": d, "rule": f"Δ ≥ -{cfg.max_quality_drop} or CI includes 0",
         "passed": not (d.get("value") is not None and d["value"] < -cfg.max_quality_drop
                        and d.get("hi") is not None and d["hi"] < 0)},
        {"check": "false-hit rate (cache answers that were wrong)",
         "value": cand["false_hit_rate"], "rule": f"≤ {cfg.max_false_hit_rate:.0%}",
         "passed": cand["false_hit_rate"] <= cfg.max_false_hit_rate},
        {"check": "tokens saved vs naive",
         "value": cand.get("tokens_saved_pct", 0.0), "rule": f"≥ {cfg.min_tokens_saved:.0%}",
         "passed": cand.get("tokens_saved_pct", 0.0) >= cfg.min_tokens_saved},
    ]
    ok = all(c["passed"] for c in checks)
    return {"policy": cand["policy"], "passed": ok, "decision": "pass" if ok else "fail", "checks": checks}


def _fmt(v) -> str:
    if isinstance(v, dict):
        if v.get("value") is None:
            return "n/a"
        return f"{v['value']:+.2f} [{v['lo']:+.2f}, {v['hi']:+.2f}] (n={v['n']})"
    return f"{v:.1%}"


def markdown(result: dict, cand: dict, trace: dict) -> str:
    icon = "✅" if result["passed"] else "❌"
    lines = [
        f"## {icon} frugal eval gate: **{result['decision'].upper()}**",
        "",
        f"Policy `{result['policy']}` vs `naive` on a {trace['requests']}-request trace "
        f"({trace['groups']} question groups).",
        "",
        "| check | value | rule | result |",
        "|---|---|---|---|",
    ]
    for c in result["checks"]:
        lines.append(f"| {c['check']} | {_fmt(c['value'])} | {c['rule']} | {'pass' if c['passed'] else '**FAIL**'} |")
    lines += [
        "",
        f"Savings: **{cand.get('tokens_saved_pct', 0):.0%} tokens**, {cand.get('llm_calls_saved_pct', 0):.0%} fewer "
        f"model calls, cache hit rate {cand['hit_rate']:.0%}, "
        f"{cand['cheap_tier_share']:.0%} of calls on the cheap tier. "
        f"Estimated ${cand.get('est_cost_saved_usd', 0):.4f} saved on this trace *at paid-tier prices* "
        f"(actual spend ${cand['cost_usd']:.2f}: free tier).",
    ]
    return "\n".join(lines)
