"""The dashboard as a product: failures explained, runs compared, an agent checked before any credits are spent."""

import asyncio
import json

import websockets
from fastapi.testclient import TestClient

from diapason.checks import CATALOG, explain, explain_verdict, metric_id
from diapason.runner import estimate_usage
from diapason.scenarios import load_suite
from diapason.server import create_app, probe_agent


def test_every_failure_is_explained_most_severe_first():
    v = {"criteria": [{"id": "tone", "verdict": "fail", "reason": "repeated itself", "evidence": [{"quote": "कब बात हो सकती है"}]},
                      {"id": "privacy", "verdict": "fail", "reason": "told the brother", "evidence": [{"quote": "4500 रुपये"}]},
                      {"id": "escalation", "verdict": "na"},
                      {"id": "factual_accuracy", "verdict": "review", "reason": "unsure"}],
         "metric_failures": ["p95 latency 2636 ms > 2500 ms", "ignored 1 of 2 barge-in(s)"]}
    out = explain_verdict(v)
    assert [x["id"] for x in out] == ["privacy", "latency", "barge_in", "tone", "factual_accuracy"]
    assert out[0]["severity"] == "critical" and out[0]["quote"] == "4500 रुपये" and out[0]["fix"]
    assert out[-1]["severity"] == "review"                      # undecided by the judge: a human looks, not a failure
    assert metric_id("3 dead-air gap(s), longest 11.1 s") == "dead_air"
    assert explain("a_suite_specific_check")["name"] == "A suite specific check"
    assert all({"name", "severity", "why", "fix"} <= set(e) for e in CATALOG.values())


def test_live_estimate_is_in_gnani_credits():
    e = estimate_usage(load_suite("suites/proof.yaml"))
    assert e["credits_max"] == round(e["tts_chars_max"] / 555 + e["stt_seconds_max"] / 180, 1) and e["credits_max"] > 0


def test_agent_check_times_the_greeting_and_reports_a_dead_url():
    async def agent(ws):
        start = json.loads(await ws.recv())
        assert start["type"] == "start"
        await asyncio.sleep(0.05)
        await ws.send(b"\x00\x01" * 320)                 # the agent's first audio
        await asyncio.sleep(0.5)

    async def go():
        async with websockets.serve(agent, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            ok = await probe_agent(f"ws://127.0.0.1:{port}", "websocket", 3)
        dead = await probe_agent("ws://127.0.0.1:9", "websocket", 2)
        bad = await probe_agent("http://example.com", "websocket", 2)
        return ok, dead, bad
    ok, dead, bad = asyncio.run(go())
    assert ok["ok"] and ok["first_audio_ms"] >= 40 and ok["note"] == "the agent greeted first"
    assert not dead["ok"] and dead["stage"] == "connect"
    assert not bad["ok"] and bad["stage"] == "url"


def _report(run_id, scen):
    return {"suite": "s", "run_id": run_id, "label": "", "pass_rate": sum(p for p, _ in scen.values()) / len(scen),
            "latency_p95_s": 1.0, "criteria_failures": {"privacy": sum("privacy (fail)" in f for _, f in scen.values())},
            "scenarios": [{"scenario_id": k, "pass_rate": p, "failures": f} for k, (p, f) in scen.items()]}


def test_compare_says_what_was_fixed_and_what_broke(tmp_path):
    runs = tmp_path / "runs"
    for name, scen in {"r1": {"a": (0.0, ["privacy (fail)"]), "b": (1.0, [])},
                       "r2": {"a": (1.0, []), "b": (0.0, ["p95 latency 3000 ms > 2500 ms"])}}.items():
        (runs / name).mkdir(parents=True)
        (runs / name / "report.json").write_text(json.dumps(_report(name, scen)), encoding="utf-8")
    c = TestClient(create_app(runs_dir=runs))
    d = c.get("/api/compare", params={"a": "r1", "b": "r2"}).json()
    by = {x["scenario_id"]: x for x in d["changes"]}
    assert by["a"]["status"] == "fixed" and by["b"]["status"] == "regressed"
    assert by["b"]["explained"][0]["id"] == "latency" and by["b"]["explained"][0]["fix"]
    assert d["criteria_delta"] == [{"id": "privacy", "delta": -1, "name": "Privacy breach"}]
    assert c.get("/api/compare", params={"a": "r1", "b": "../x"}).status_code == 404
