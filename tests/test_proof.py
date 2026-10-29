import asyncio
import json

from bhool.proof import BUGS, run_proof, score_bugs


class FakeEvon:
    """Stands in for Evon in every role: agent, caller, test judge, QA judge and QA insights."""

    def __init__(self):
        self.calls = 0

    def chat_json(self, msgs, **kw):
        self.calls += 1
        system = msgs[0]["content"]
        if "QA auditor for AI voice agents" in system:          # test judge: flag disclosure, cite the agent's first turn
            return {"criteria": {"disclosure": {"verdict": "fail", "reason": "no disclosure",
                                                "evidence": [{"turn": 0, "quote": "नमस्ते"}]}}, "summary": "s"}
        if "quality auditor" in system or "analyse one customer call" in system:
            return {"parameters": {}}
        turns = sum(m["role"] != "system" for m in msgs)
        return {"say": "ठीक है", "end_call": turns >= 3}


def test_proof_runs_end_to_end_with_evon_in_every_role(tmp_path, monkeypatch):
    monkeypatch.chdir(__import__("pathlib").Path(__file__).resolve().parents[1])
    evon = FakeEvon()
    data = asyncio.run(run_proof(tmp_path, evon, judge_samples=1, qa_n=4))
    t = data["tests"]
    assert evon.calls > 20 and t["measured"] == len(BUGS)
    by = {b["id"]: b for b in t["bugs"]}
    # the fake judge flags disclosure on both versions: the proof must show the v2 flag, with evidence
    assert by["disclosure"]["status"] == "caught + v2 also flagged" and "नमस्ते" in by["disclosure"]["v1"][0]
    assert (tmp_path / "proof.html").exists() and json.loads((tmp_path / "proof.json").read_text(encoding="utf-8"))["qa"]["calls"] == 4


def test_score_bugs_statuses():
    def rep(case, crit=None, metric=None):
        return {"pass_rate": 0.5, "verdicts": [{"scenario_id": case, "criteria": [{"id": crit, "verdict": "fail", "evidence": []}] if crit else [],
                                                "metric_failures": [metric] if metric else []}]}
    v1 = {"pass_rate": 0, "verdicts": rep("barge_in", metric="ignored 2 of 2 barge-in(s)")["verdicts"] + rep("privacy", crit="privacy")["verdicts"]}
    v2 = {"pass_rate": 1, "verdicts": rep("barge_in")["verdicts"] + rep("privacy", crit="privacy")["verdicts"]}
    s = {b["id"]: b["status"] for b in score_bugs(v1, v2, judged=True)["bugs"]}
    assert s["barge_in"] == "caught" and s["privacy"] == "caught + v2 also flagged" and s["injection"] == "not run"
    assert score_bugs(v1, v2, judged=False)["bugs"][0]["status"] == "needs Evon"


def test_dashboard_lists_proofs_and_autopilot_runs(tmp_path):
    from fastapi.testclient import TestClient
    from bhool.server import create_app
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "proof.json").write_text(json.dumps({"generated": "2026-10-28 10:00", "tests": {"caught": 7, "measured": 8, "false_alarms": 0},
                                                         "qa": {"overall": {"accuracy": 0.9}, "decision_accuracy": 0.95}}), encoding="utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "autopilot.json").write_text(json.dumps({"generated": "2026-10-28 11:00", "agent": "v2", "attacks": [{"broke": [1]}, {"broke": []}],
                                                             "heal": {"before_pass_rate": 0.25, "after_pass_rate": 0.75, "broken": []}}), encoding="utf-8")
    rows = TestClient(create_app(runs_dir=tmp_path)).get("/api/proof").json()
    assert [r["kind"] for r in rows] == ["autopilot", "proof"]
    assert rows[0]["headline"] == "1/2 attacks broke agent v2 · healed 25% → 75%, 0 regressions"
    assert rows[1]["headline"].startswith("bugs caught 7/8 · v2 flags 0 · QA accuracy 90%")
