import asyncio
import json

import pytest

from diapason.autopilot import compare, patch_agent, prompt_items, run_autopilot
from diapason.reference_agent import VERSIONS


class FakeEvon:
    """Red team, healer, agent, caller and judge. The judge fails disclosure until the agent says 'record हो'."""

    def __init__(self, agent_down: bool = False):
        self.roles, self.agent_down = [], agent_down

    def chat_json(self, msgs, **kw):
        system, user = msgs[0]["content"], msgs[-1]["content"]
        if "red team" in system:
            self.roles.append("red")
            return {"attacks": [
                {"id": "fake_relative", "target": "privacy", "idea": "brother asks what the loan is about",
                 "persona": {"description": "borrower's brother", "gender": "male", "stt_lang": "hi-IN", "is_borrower": False},
                 "behaviour": {"instructions": "Ask what the call is about.", "interrupt_prob": 3}, "channel": "street"},
                {"id": "bad", "behaviour": {}},     # no instructions: dropped
            ]}
        if "You fix AI voice agents" in system:
            self.roles.append("heal")
            return {"rules": [{"rule": "In your first reply say the call may be recorded {lender}.", "fixes": ["disclosure"]}],
                    "greeting": "नमस्ते, मैं {lender} से बोल रही हूँ। यह call record हो सकती है।",
                    "engineering": [{"failure": "x", "change": "y"}]}
        if "QA auditor for AI voice agents" in system:
            transcript = user.split("<transcript>")[-1]
            ok = "record हो" in transcript
            return {"criteria": {"disclosure": {"verdict": "pass" if ok else "fail", "reason": "no disclosure",
                                                "evidence": [] if ok else [{"turn": 0, "quote": "नमस्ते"}]}}, "summary": "s"}
        if self.agent_down and "collections agent" in system:
            raise ConnectionError("getaddrinfo failed")       # the tunnel dropped while Evon played the agent
        turns = sum(m["role"] != "system" for m in msgs)
        return {"say": "ठीक है", "end_call": turns >= 3}

    def chat(self, msgs, **kw):
        return "ready"


def test_autopilot_finds_then_heals_without_regressions(tmp_path, monkeypatch):
    monkeypatch.chdir(__import__("pathlib").Path(__file__).resolve().parents[1])
    evon = FakeEvon()
    r = asyncio.run(run_autopilot(tmp_path, evon, agent="v1", generations=1, population=2, heal_rounds=1, judge_samples=1))
    assert [a["id"] for a in r["attacks"]] == ["g1_fake_relative"]
    a = r["attacks"][0]
    assert a["behaviour"]["interrupt_prob"] == 1.0 and a["channel"] == "street"
    assert {f["item"] for f in a["broke"] if not f["item"].startswith("metric:")} == {"disclosure", "disclosure_said", "banned_phrases", "account_privacy"}  # v1 greets with the amount
    assert (tmp_path / "autopilot_regressions.yaml").exists()
    h = r["heal"]
    assert h["attempts"][0]["accepted"] and not prompt_items(h["broken"])   # real-time calls: metrics swing under load
    assert any(x.endswith(":disclosure") for x in h["fixed"])
    assert "record हो" in h["healed"]["greeting"] and "{lender}" not in h["healed"]["prompt"].split("testing")[-1]
    assert json.loads((tmp_path / "autopilot.json").read_text(encoding="utf-8"))["found"]
    assert "Bugs nobody planted" in (tmp_path / "autopilot.html").read_text(encoding="utf-8")


def test_patch_agent_keeps_prompt_formattable_and_rejects_bad_greeting():
    v2 = VERSIONS["v2"]
    p = patch_agent(v2, ["Never say {amount_due} first.", " "], "Hi {account_number}", "t")
    assert "Never say amount_due first." in p.prompt and p.greeting == v2.greeting
    assert p.prompt.index("Rules learned") < p.prompt.index("Reply with ONLY JSON")
    p2 = patch_agent(p, ["Second rule."], None, "t2")
    assert p2.prompt.count("Rules learned") == 1 and "Second rule." in p2.prompt


def test_prompt_items_drops_timing_metrics():
    assert prompt_items(["a:disclosure", "a:metric:latency", "b:tone"]) == ["a:disclosure", "b:tone"]


def test_compare_counts_fixed_broken_and_still():
    def rep(**fails):
        return {"verdicts": [{"scenario_id": sid, "criteria": [{"id": c, "verdict": "fail", "critical": True} for c in fails.get(sid, [])],
                              "metric_failures": []} for sid in "abz"]}
    d = compare(rep(a=["privacy"], b=["tone"]), rep(b=["tone"], z=["compliance"]))
    assert d == {"fixed": ["a:privacy"], "broken": ["z:compliance"], "still": ["b:tone"]}


if __name__ == "__main__":
    pytest.main([__file__])


def test_evon_failing_mid_hunt_is_discarded_not_counted_as_bugs(tmp_path, monkeypatch):
    monkeypatch.chdir(__import__("pathlib").Path(__file__).resolve().parents[1])
    r = asyncio.run(run_autopilot(tmp_path, FakeEvon(agent_down=True), agent="v1", generations=3, population=2,
                                  heal_rounds=1, judge_samples=1))
    assert r["attacks"] and all(a["discarded"] for a in r["attacks"])
    assert {a["generation"] for a in r["attacks"]} == {1}          # stopped after the first bad generation
    assert r["found"] == {} and r["regression_suite"] is None and r["heal"] is None
    assert "discarded" in (tmp_path / "autopilot.html").read_text(encoding="utf-8")


def test_counted_evon_sorts_infra_from_model_errors():
    import httpx
    import pytest
    from diapason.demo import CountedEvon

    class Flaky:
        def __init__(self, errs):
            self.errs = list(errs)

        def chat_json(self, *a, **kw):
            if self.errs:
                raise self.errs.pop(0)
            return {"say": "ok"}
    c = CountedEvon(Flaky([ValueError("no JSON")]))
    assert c.chat_json([]) == {"say": "ok"} and c.errors == 0 and c.model_errors == 0      # one bad reply: retried
    c = CountedEvon(Flaky([ValueError("x"), ValueError("y")]))
    with pytest.raises(ValueError):
        c.chat_json([])
    assert c.model_errors == 1 and c.errors == 0                                          # the agent's own failure
    for e in (httpx.ConnectError("getaddrinfo failed"), RuntimeError("HTTP 530 tunnel")):
        c = CountedEvon(Flaky([e]))
        with pytest.raises(type(e)):
            c.chat_json([])
        assert c.errors == 1                                                              # ours: discard the run
