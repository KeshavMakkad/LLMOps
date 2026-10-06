import pytest
from fastapi.testclient import TestClient

from frugal import gate
from frugal.experiment import run_experiment


def test_offline_experiment_end_to_end(tmp_path):
    res = run_experiment(["optimized"], max_groups=8, judge_model="gemini-judge", out=tmp_path / "r.json")
    n, o = res["policies"]["naive"], res["policies"]["optimized"]
    assert n["llm_calls"] == n["requests"] and n["cache_hits"] == 0
    assert o["total_tokens"] < n["total_tokens"]
    assert 0 < o["tokens_saved_pct"] < 1
    assert o["quality_delta"]["n"] > 0
    assert o["cost_usd"] == 0.0  # free tier: actual spend is zero...
    assert n["est_cost_usd"] > 0  # ...but the paid-price estimate is not
    assert len(res["records"]["optimized"]) == o["requests"]


def test_gate_fails_on_significant_quality_drop_or_false_hits():
    cfg = gate.GateCfg()
    good = {"policy": "p", "quality_delta": {"value": -0.05, "lo": -0.3, "hi": 0.2, "n": 50},
            "false_hit_rate": 0.02, "tokens_saved_pct": 0.5}
    assert gate.evaluate(good, cfg)["passed"]
    drop = {**good, "quality_delta": {"value": -0.6, "lo": -0.9, "hi": -0.3, "n": 50}}
    assert not gate.evaluate(drop, cfg)["passed"]
    noisy = {**good, "quality_delta": {"value": -0.6, "lo": -1.4, "hi": 0.1, "n": 6}}
    assert gate.evaluate(noisy, cfg)["passed"]  # big but not significant: don't block on noise
    assert not gate.evaluate({**good, "false_hit_rate": 0.2}, cfg)["passed"]
    assert not gate.evaluate({**good, "tokens_saved_pct": 0.05}, cfg)["passed"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from frugal.api import main

    monkeypatch.setattr(main, "MAX_DAILY_CALLS", 2)
    main._calls.update(n=0)
    main._caches.clear()
    return TestClient(main.app)


def test_api_cache_hits_skip_model_and_budget(client):
    body = {"question": "How long do refunds take after I cancel?", "domain": "swiggy"}
    first = client.post("/v1/answer", json=body).json()
    assert first["served_from"] == "llm" and first["tokens"]["prompt"] > 0
    again = client.post("/v1/answer", json=body).json()
    assert again["served_from"] == "exact_cache" and again["tokens"]["prompt"] == 0
    client.post("/v1/answer", json={**body, "question": "What does Swiggy One include?"})
    over = client.post("/v1/answer", json={**body, "question": "Is alcohol delivered?"})
    assert over.status_code == 429  # daily model-call budget of 2 is used up...
    assert client.post("/v1/answer", json=body).json()["served_from"] == "exact_cache"  # ...cache still serves
    assert client.get("/v1/stats").json()["requests"] >= 3


def test_api_rejects_paths_and_unknown_domains(client):
    assert client.post("/v1/answer", json={"question": "hello there", "domain": "swiggy",
                                           "policy": "../../etc/passwd"}).status_code == 404
    assert client.post("/v1/answer", json={"question": "hello there", "domain": "nope"}).status_code == 400


def test_single_flight_coalesces_concurrent_identical_requests(client, monkeypatch):
    import threading
    import time

    from frugal.api import main
    from frugal.pipeline import answer_with_llm

    monkeypatch.setattr(main, "MAX_DAILY_CALLS", 1000)
    calls = []

    def slow_answer(*a, **kw):  # a slow model makes the stampede window wide
        calls.append(1)
        time.sleep(0.3)
        return answer_with_llm(*a, **kw)

    monkeypatch.setattr("frugal.pipeline.answer_with_llm", slow_answer)
    body = {"question": "Can I cancel after the restaurant accepts my order?", "domain": "swiggy"}
    results = []
    threads = [threading.Thread(target=lambda: results.append(client.post("/v1/answer", json=body).json()))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1  # 8 concurrent identical requests -> one model call
    assert sorted(r["served_from"] for r in results).count("exact_cache") == 7


def test_empty_cheap_answer_falls_back_and_is_never_cached(monkeypatch):
    from frugal.cache import SemanticCache
    from frugal.config import load_policy
    from frugal.llm.client import LLMResponse
    from frugal.pipeline import handle
    from frugal.trace import Request

    seen = []

    def fake_complete(model_key, *a, **kw):
        seen.append(model_key)
        text = "" if model_key == "gemma-26b" else "Refunds take 5-7 business days."
        return LLMResponse(text=text, model=model_key, input_tokens=100, output_tokens=10, cost_usd=0.0,
                           est_cost_usd=0.001, latency_ms=5.0)

    monkeypatch.setattr("frugal.pipeline.complete", fake_complete)
    pol = load_policy("optimized")
    cache = SemanticCache(pol.cache)
    req = Request(req_id="r1", group_id="g", kind="original", item_id="x", domain="swiggy",
                  question="what is the refund policy for cancelled orders")
    rec = handle(req, pol, cache)
    assert seen == ["gemma-26b", "gemini-lite"] and rec.fallback and rec.tier == "strong"
    assert rec.answer and rec.prompt_tokens == 200  # the failed cheap attempt's tokens still count

    seen.clear()
    monkeypatch.setattr("frugal.pipeline.complete", lambda *a, **kw: LLMResponse(
        text="", model="m", input_tokens=1, output_tokens=0, cost_usd=0, est_cost_usd=0, latency_ms=1))
    bad = handle(Request(req_id="r2", group_id="h", kind="original", item_id="y", domain="tax",
                         question="what is section 80C about"), pol, cache)
    assert bad.served_from == "error" and len(cache.entries) == 1  # the empty answer was not cached
