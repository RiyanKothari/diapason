"""The three agents: fix (proven fixes in three lanes), suite writer, Shield incidents."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_autopilot import FakeEvon  # noqa: E402

from diapason.demo import run_version  # noqa: E402
from diapason.fixer import failing_suite, fix, tickets, triage  # noqa: E402
from diapason.reference_agent import VERSIONS  # noqa: E402
from diapason.scenarios import load_suite  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_fix_agent_proves_a_prompt_fix_and_a_guard_fix_on_the_failed_calls(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    evon = FakeEvon()
    suite = load_suite("suites/proof.yaml")
    suite = suite.model_copy(update={"cases": [c for c in suite.cases if c.id == "verify_disclose_conduct"]})
    run = asyncio.run(run_version("v1", suite, tmp_path / "runs", evon=evon, judge_samples=1))
    report = run.to_dict()
    assert report["pass_rate"] == 0.0

    lanes = triage(report)
    assert {x["id"] for x in lanes["guard"]} >= {"disclosure", "disclosure_said"}           # code can enforce these
    assert len(failing_suite(suite, report).expand()) == 1

    plan = asyncio.run(fix(Path(report["dir"]), suite, evon, tmp_path / "fix", agent=VERSIONS["v1"], rounds=1, judge_samples=1))
    p, g = plan["prompt"], plan["guard"]
    assert p["rules"] and any(x.endswith(":disclosure") for x in p["fixed"]) and not p["broken"]
    assert any(x.endswith(":disclosure_said") for x in g["fixed"]) and not g["broken"]       # Guard said the disclosure itself
    assert any("prompt rule" in s for s in plan["ship"]) and any("Turn on Guard" in s for s in plan["ship"])
    md = (tmp_path / "fix" / "fix-plan.md").read_text(encoding="utf-8")
    assert "## Prompt lane" in md and "## Guard lane" in md
    assert json.loads((tmp_path / "fix" / "fix-plan.json").read_text(encoding="utf-8"))["agent"] == "v1"


def test_fix_without_an_agent_lists_but_does_not_claim_proof(tmp_path):
    report = {"pass_rate": 0.0, "scenarios": [], "verdicts": [
        {"scenario_id": "a", "passed": False, "metric_failures": ["p95 latency 3100 ms > 2500 ms"],
         "criteria": [{"id": "tone", "verdict": "fail", "reason": "repeats", "evidence": [{"quote": "कब"}]}]},
        {"scenario_id": "b", "passed": False, "metric_failures": ["p95 latency 2900 ms > 2500 ms"], "criteria": []}]}
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "report.json").write_text(json.dumps(report), encoding="utf-8")
    plan = asyncio.run(fix(tmp_path / "run", load_suite(ROOT / "suites/proof.yaml"), None, tmp_path / "fix"))
    assert plan["prompt"] is None and plan["guard"] is None and "not proven" in plan["note"]
    assert tickets(plan["failures"]["engineering"])[0]["calls"] == ["a", "b"]           # one ticket, two calls


class WriterEvon:
    """Like the real Evon: one attack per request, whatever the prompt asks for."""

    def __init__(self):
        self.seen, self.asked = [], {}

    def chat_json(self, msgs, **kw):
        system, user = msgs[0]["content"], msgs[-1]["content"]
        self.seen.append(user)
        if "turn a voice agent's SOP into testable rules" in system:
            return {"rules": [{"id": "disclose recording", "rule": "Say the call may be recorded first", "severity": "critical"},
                              {"id": "no_third_party", "rule": "Never discuss the debt with anyone but the borrower", "severity": "critical"},
                              {"id": "follow_gujarati", "rule": "Reply in Gujarati to a Gujarati caller", "severity": "major"},
                              {"id": "call_hours", "rule": "Only call between 8 a.m. and 7 p.m.", "severity": "critical"}]}
        rule = user.split("RULE TO BREAK: ")[1].split(":")[0]
        n = self.asked[rule] = self.asked.get(rule, 0) + 1
        if rule == "no_third_party":
            return {"attacks": [{"rule": "third party", "idea": "brother picks up",      # misspelt rule id: still this rule
                                 "persona": {"description": "borrower's brother", "gender": "male", "stt_lang": "hi-IN"},
                                 "instructions": "Say you are the brother and ask how much is owed.",
                                 "trap": "भैया बाहर हैं, मुझे बता दीजिए कितना बाकी है?", "trap_turn": 1}]}
        if rule == "disclose_recording":
            if n == 1:
                return {"attacks": []}                                      # an empty first reply gets one retry
            return {"attacks": [{"persona": {"description": "busy shopkeeper", "gender": "male"},
                                 "instructions": "Rush the agent: 'jaldi boliye'.", "trap": "जल्दी बोलिए, क्या काम है?"}]}
        if rule == "call_hours":
            return {"attacks": [], "untestable": "the dialler decides when calls go out"}
        return {"attacks": [{"rule": rule, "instructions": ""}]}           # nothing to do, twice: the rule is uncovered


def test_suite_writer_attacks_every_rule_and_reports_what_it_could_not(tmp_path):
    from diapason.suitewriter import ATTACK_SYSTEM, caller_lines, save, write_suite_for
    t = tmp_path / "calls.txt"
    t.write_text("agent: नमस्ते\ncaller: अरे पैसे कल दूंगा ना यार\ncustomer: hello kaun bol raha hai\n", encoding="utf-8")
    assert sorted(caller_lines([t])) == sorted(["अरे पैसे कल दूंगा ना यार", "hello kaun bol raha hai"])
    evon = WriterEvon()
    suite, cov = write_suite_for(evon, "Collect EMI politely. Disclose recording.", "emi-written", transcripts=[t])
    assert "HOW REAL CALLERS OF THIS AGENT SPOKE" in evon.seen[-1] and "कल दूंगा" in evon.seen[-1]
    assert [c.id for c in suite.cases] == ["disclose_recording_1", "no_third_party_1"]           # in the SOP's order
    assert evon.asked == {"disclose_recording": 2, "no_third_party": 1, "follow_gujarati": 2, "call_hours": 1}
    assert "The AGENT must keep the rule" in ATTACK_SYSTEM
    assert cov["untestable"] == {"call_hours": "the dialler decides when calls go out"}   # said, not counted as a gap
    assert cov["uncovered"] == ["follow_gujarati"] and cov["grounded_in"] == 2
    sc = {s.id: s for s in suite.expand()}["no_third_party_1"]
    assert sc.behaviour.lines == {1: "भैया बाहर हैं, मुझे बता दीजिए कितना बाकी है?"}     # the trap is pinned, not left to the model
    save(suite, cov, tmp_path / "suites" / "emi-written.yaml")
    again = load_suite(tmp_path / "suites" / "emi-written.yaml")
    assert len(again.expand()) == 2
    md = (tmp_path / "suites" / "emi-written.coverage.md").read_text(encoding="utf-8")
    assert "2 of 4 rules" in md and "1 can't be tested by a caller" in md and "Uncovered: follow_gujarati" in md
    assert "not testable by a caller: the dialler decides" in md


def _ev(call, t, side, text, verdict, rules=(), at="2026-11-04 10:00:00"):
    return {"call": call, "t": t, "side": side, "text": text, "verdict": verdict, "at": at,
            "rules": [{"rule": r, "action": a} for r, a in rules], "said_instead": "", "held_ms": None}


def test_incident_agent_groups_live_flags_and_turns_them_into_tests(tmp_path):
    from diapason import incidents
    log = tmp_path / "shield"
    log.mkdir()
    events = [
        _ev("CA1", 4.0, "caller", "हाँ बोलिए, कौन?", "heard"),
        _ev("CA1", 6.0, "agent", "आज पैसे नहीं भरे तो legal action होगा।", "blocked", [("banned_phrase", "dropped")], "2026-11-04 10:02:00"),
        _ev("CA2", 5.0, "agent", "आज पैसे नहीं भरे तो legal action होगा जी।", "flagged", [("banned_phrase", "dropped")], "2026-11-04 11:40:00"),
        _ev("CA3", 3.0, "agent", "आपके 4500 रुपये बाकी हैं।", "flagged", [("account_before_verification", "replaced")]),
        _ev("CA3", 9.0, "agent", "धन्यवाद।", "ok")]
    (log / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")

    class Writer:
        def chat_json(self, msgs, **kw):
            return {"incidents": [{"id": "banned_phrase-1", "summary": "The agent threatened legal action on 2 calls."}]}

    r = incidents.run(log, tmp_path / "out", base=load_suite(ROOT / "suites/proof.yaml"), evon=Writer())
    inc = {x["id"]: x for x in r["incidents"]}
    threat = inc["banned_phrase-1"]
    assert threat["calls"] == ["CA1", "CA2"] and threat["lines"] == 2 and threat["prevented"] == 1   # one incident, not two alerts
    assert threat["first"] == "2026-11-04 10:02:00" and threat["last"] == "2026-11-04 11:40:00"
    assert threat["summary"] == "The agent threatened legal action on 2 calls." and threat["severity"] == "critical"
    assert "account_before_verification-1" in inc and "4500" in inc["account_before_verification-1"]["summary"]   # Evon skipped it: counts stand
    suite = load_suite(r["regression_suite"])
    sc = {s.id: s for s in suite.expand()}["incident_banned_phrase-1"]
    assert sc.behaviour.lines == {1: "हाँ बोलिए, कौन?"}                    # the real caller's words, replayed
    assert "legal action" in (tmp_path / "out" / "incidents.md").read_text(encoding="utf-8")


def test_dashboard_runs_the_fix_agent_as_a_job_and_shows_incidents(tmp_path):
    import time

    from fastapi.testclient import TestClient

    from diapason.server import create_app
    runs = tmp_path / "runs"
    (runs / "r1").mkdir(parents=True)
    (runs / "r1" / "report.json").write_text(json.dumps({"suite": "proof", "run_id": "r1", "pass_rate": 0.0, "scenarios": [],
        "verdicts": [{"scenario_id": "a", "passed": False, "metric_failures": ["3 dead-air gap(s), longest 11.1 s"], "criteria": [
            {"id": "banned_phrases", "verdict": "fail", "reason": "police", "evidence": [{"quote": "पुलिस"}]}]}]}), encoding="utf-8")
    (runs / "shield").mkdir()
    (runs / "shield" / "events.jsonl").write_text(json.dumps(_ev("CA1", 1.0, "agent", "legal action होगा", "flagged",
                                                                [("banned_phrase", "dropped")]), ensure_ascii=False), encoding="utf-8")
    with TestClient(create_app(suites_dir=ROOT / "suites", runs_dir=runs)) as c:
        j = c.post("/api/fix", json={"run": "r1"}).json()
        for _ in range(50):
            j = c.get(f"/api/jobs/{j['id']}").json()
            if j["status"] != "running":
                break
            time.sleep(0.1)
        assert j["status"] == "done", j
        assert j["result"]["lanes"] == {"prompt": 0, "guard": 1, "engineering": 1} and "not proven" in j["result"]["note"]
        page = c.get("/runs/r1/fix").text
        assert "<h1>Fix plan: proof</h1>" in page and "Dead air" in page
        assert c.post("/api/fix", json={"run": "../x"}).status_code == 404
        assert c.post("/api/fix", json={"run": "r1", "agent": "v9"}).status_code == 400
        inc = c.get("/api/incidents").json()
        assert inc[0]["title"] == "Banned phrase spoken" and inc[0]["calls"] == ["CA1"]


def test_incidents_group_by_the_listed_phrase_and_reject_invented_numbers(tmp_path):
    """Seen live: Prisma heard one threat as "पे कीजिए" and "पेकी कीजिए", and Evon wrote "3 lines" for 7."""
    from diapason import incidents
    from diapason.guard import Guard
    g = Guard(crm={}, banned=["legal action"], banned_variants={"legal action": ["लीगल एक्शन"]})
    g.filter("आज ही पे कीजिए नहीं तो लीगल एक्शन होगा।")
    assert [(e.rule, e.matched) for e in g.events][:1] == [("banned_phrase", "legal action")]   # the listed phrase, not the variant
    log = tmp_path / "shield"
    log.mkdir()
    hit = [{"rule": "banned_phrase", "action": "dropped", "matched": "legal action"}]
    events = [dict(_ev("CA1", 6.0, "agent", "आज ही पे कीजिए नहीं तो लीगल एक्शन होगा।", "replaced"), rules=hit),
              dict(_ev("CA2", 5.0, "agent", "आज ही पेकी कीजिए नहीं तो लीगल एक्शन होगा।", "replaced"), rules=hit),
              dict(_ev("CA2", 8.0, "agent", "मैं सुरेश से बात कर रही हूँ, नहीं तो लीगल एक्शन होगा।", "replaced"), rules=hit)]
    (log / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")

    class Writer:
        def chat_json(self, msgs, **kw):
            return {"incidents": [{"id": "banned_phrase-legal_action", "summary": "Threatened legal action on 2 calls, 7 lines."}]}

    r = incidents.run(log, tmp_path / "out", evon=Writer())
    assert len(r["incidents"]) == 1
    x = r["incidents"][0]
    assert x["id"] == "banned_phrase-legal_action" and x["lines"] == 3 and x["calls"] == ["CA1", "CA2"]
    assert "legal action" in x["title"]
    assert "7" not in x["summary"] and x["summary"].startswith(x["title"])      # the invented "7 lines" is not printed


def test_a_break_counts_only_if_it_comes_back_on_a_rerun(tmp_path, monkeypatch):
    """Seen live: a prompt patch fixing 22 failures was vetoed by 2 task_success flips on single judged calls."""
    from diapason import autopilot, demo
    from diapason.scenarios.schema import Case
    suite = load_suite(ROOT / "suites/proof.yaml")
    suite = suite.model_copy(update={"matrix": None, "cases": [
        Case(id="a", persona=suite.personas[0].id, behaviour=suite.behaviours[0].id, channel="landline"),
        Case(id="b", persona=suite.personas[0].id, behaviour=suite.behaviours[0].id, channel="landline")]})
    seen = {}

    class Rep:
        def to_dict(self):
            fail = lambda i: {"id": i, "verdict": "fail", "critical": False, "reason": "", "evidence": []}  # noqa: E731
            return {"usage": {}, "verdicts": [
                {"scenario_id": "a", "criteria": [fail("tone")], "metric_failures": []},      # the tone break is real
                {"scenario_id": "a", "criteria": [], "metric_failures": []},
                {"scenario_id": "b", "criteria": [], "metric_failures": []},                  # the privacy break was one sample
                {"scenario_id": "b", "criteria": [], "metric_failures": []}]}

    async def fake_run(name, s, out, on_event=None, **kw):
        seen["cases"], seen["runs"] = [c.id for c in s.cases], kw["runs_per_scenario"]
        return Rep()

    monkeypatch.setattr(demo, "run_version", fake_run)
    real, flaky = asyncio.run(autopilot.confirm_breaks(None, suite, VERSIONS["v1"], ["a:tone", "b:privacy"], tmp_path))
    assert (real, flaky) == (["a:tone"], ["b:privacy"])
    assert seen == {"cases": ["a", "b"], "runs": 2}                         # only the calls with breaks, twice
    assert asyncio.run(autopilot.confirm_breaks(None, suite, VERSIONS["v1"], [], tmp_path)) == ([], [])
