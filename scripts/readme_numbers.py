"""Print the README tables from results files.

  python scripts/readme_numbers.py [results/latest.json] [results/sweep.json] [results/loadtest/local_stats.csv]
"""

import csv
import json
import sys
from pathlib import Path


def ci(e, fmt="{:+.2f}"):
    if not e or e.get("value") is None:
        return "–"
    return f"{fmt.format(e['value'])} [{fmt.format(e['lo'])}, {fmt.format(e['hi'])}]"


def main():
    exp = Path(sys.argv[1] if len(sys.argv) > 1 else "results/latest.json")
    sw = Path(sys.argv[2] if len(sys.argv) > 2 else "results/sweep.json")
    lt = Path(sys.argv[3] if len(sys.argv) > 3 else "results/loadtest/local_stats.csv")

    if exp.exists():
        r = json.loads(exp.read_text())
        t = r["trace"]
        print(f"Run `{r['run_id']}`: {t['requests']} requests, {t['groups']} question groups, kinds {t['kinds']}; "
              f"judge `{r['judge']['model']}` ({r['judge']['version']}).\n")
        print("| policy | tokens | tokens saved | model calls | cache hit / false-hit | cheap tier | quality (1–5) "
              "| Δ quality vs naive [95% CI] | pass rate | p50 / p99 ms | est. $ at paid prices* |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for name, s in r["policies"].items():
            q = s["quality_mean"]["value"]
            pr = s["quality_pass_rate"]["value"]
            print(f"| `{name}` | {s['total_tokens']:,} | {s.get('tokens_saved_pct', 0):.0%} | {s['llm_calls']} | "
                  f"{s['hit_rate']:.0%} / {s['false_hit_rate']:.0%} | {s['cheap_tier_share']:.0%} | "
                  f"{q:.2f} | {ci(s.get('quality_delta'))} | {pr:.0%} | "
                  f"{s['latency_p50_ms']:.0f} / {s['latency_p99_ms']:.0f} | ${s['est_cost_usd']:.4f} |")
        o = r["policies"].get("optimized")
        if o:
            n = r["policies"]["naive"]
            print(f"\nPer request (`optimized`): {o['total_tokens'] / o['requests']:.0f} tokens vs "
                  f"{n['total_tokens'] / n['requests']:.0f} naive; est. ${o['est_cost_usd'] / o['requests']:.6f} vs "
                  f"${n['est_cost_usd'] / n['requests']:.6f} at paid prices; actual ${o['cost_usd']:.2f}.")
            g = o.get("cache_guard", {})
            print(f"Cache guard: {g.get('candidates', 0)} candidates, {g.get('rejected_by_numbers', 0)} rejected by "
                  f"numbers, {g.get('rejected_by_verifier', 0)} by the verifier ({g.get('verifier_calls', 0)} calls, "
                  f"{g.get('verifier_tokens', 0):,} tokens).")
    if sw.exists():
        d = json.loads(sw.read_text())
        print(f"\nCache sweep ({d['requests']} requests):\n")
        print("| design | threshold | hit rate | correct hits | false-hit rate | near-misses served wrongly | "
              "verifier calls |")
        print("|---|---|---|---|---|---|---|")
        for row in d["rows"]:
            if row["threshold"] in (0.84, 0.88, 0.92):
                print(f"| {row['variant']} | {row['threshold']:.2f} | {row['hit_rate']:.1%} | "
                      f"{row['correct_hit_rate']:.1%} | {row['false_hit_rate']:.1%} | "
                      f"{row['near_miss_false_hit_rate']:.1%} | {row['guard_verifier_calls']} |")
        s = d["similarity"]
        print(f"\nSimilarity to the original question: paraphrases mean {s['paraphrase']['mean']:.3f}, "
              f"near-misses mean {s['near_miss']['mean']:.3f}.")
    if lt.exists():
        print("\n| endpoint | requests | req/s | p50 ms | p99 ms | failures |")
        print("|---|---|---|---|---|---|")
        for row in csv.DictReader(lt.open()):
            print(f"| {row['Name']} | {int(row['Request Count']):,} | {float(row['Requests/s']):.1f} | {row['50%']} | "
                  f"{row['99%']} | {row['Failure Count']} |")


if __name__ == "__main__":
    main()
