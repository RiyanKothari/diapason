import json
import re
from pathlib import Path

import numpy as np
import yaml

from bhool.audio import read_wav_channels
from bhool.qa import Scorecard
from bhool.qa.simulate import evaluate, layout, plan_calls, simulate_segment, voice_call, write_segments_html

ROOT = Path(__file__).resolve().parents[1]


def card(name="emi_collections"):
    return Scorecard.model_validate(yaml.safe_load((ROOT / "scorecards" / f"{name}.yaml").read_text(encoding="utf-8")))


class FakeEvon:
    """Writer writes a clean call; planter edits in each defect (llm ones as a marker line); judge fails exactly the marked ones.

    lazy: the planter's first attempt at a code-checked defect doesn't land (tests the verify-and-retry path)."""

    def __init__(self, disobey: str | None = None, lazy: bool = False, weak: tuple = ()):
        self.disobey, self.lazy, self.tries, self.weak = disobey, lazy, {}, set(weak)

    def chat_json(self, msgs, **kw):
        system, user = msgs[0]["content"], msgs[-1]["content"]
        if "follows every QA parameter" in system:
            turns = [{"speaker": "agent", "text": "नमस्ते, सहयोग फाइनेंस से प्रिया। यह कॉल रिकॉर्ड हो रही है। loan ID के आखिरी चार अंक बताइए।"},
                     {"speaker": "customer", "text": "चार आठ दो एक"},
                     {"speaker": "agent", "text": "धन्यवाद। 4500 रुपये बाकी हैं।"},
                     {"speaker": "customer", "text": "पंद्रह तारीख को दूंगा"}]
            if self.disobey:
                turns[2]["text"] += " police"      # breaks banned_phrases although the call should be clean
            return {"turns": turns}
        if "You check one line" in system:
            return {"breaks": "[[BREAK:" in user.split("AGENT'S LINE:")[-1], "why": "marker"}
        if "You plant ONE defect" in system:
            pid = re.search(r"BREAK THIS PARAMETER: (\w+):", user).group(1)
            self.tries[pid] = self.tries.get(pid, 0) + 1
            if pid in self.weak:
                return {"action": "insert_after", "turn": 3, "agent": "ठीक है जी।"}      # claims a plant, breaks nothing
            if self.lazy and self.tries[pid] == 1 and pid in ("recording_disclosure", "verifies_before_amount", "banned_phrases"):
                return {"action": "insert_after", "turn": 3, "agent": "ठीक है।"}
            if pid == "recording_disclosure":
                return {"action": "replace", "turn": 0, "agent": "नमस्ते, सहयोग फाइनेंस से प्रिया। loan ID के आखिरी चार अंक बताइए।"}
            if pid == "verifies_before_amount":
                return {"action": "replace", "turn": 0, "agent": "नमस्ते, यह कॉल रिकॉर्ड हो रही है। आपकी EMI के 4500 रुपये overdue हैं। loan ID के आखिरी चार अंक बताइए।"}
            if pid == "banned_phrases":
                return {"action": "insert_after", "turn": 2, "agent": "वरना police आएगी।"}
            return {"action": "insert_after", "turn": 3, "setup": "", "agent": f"[[BREAK:{pid}]]"}
        if "quality auditor" in system:
            body = user.split("<transcript>")[-1]
            marks = re.findall(r"\[T(\d+) [^\]]*\][^\n]*\[\[BREAK:(\w+)\]\]", body)
            return {"parameters": {p: {"verdict": "fail", "reason": "planted", "evidence": [{"turn": int(i), "quote": f"[[BREAK:{p}]]"}]}
                                   for i, p in marks}}
        return {}


def test_plan_is_deterministic_with_clean_calls():
    a, b = plan_calls(card(), "emi", 10, seed=3), plan_calls(card(), "emi", 10, seed=3)
    assert [c.planted for c in a] == [c.planted for c in b]
    assert a[0].planted == [] and a[5].planted == [] and any(c.planted for c in a)


def test_layout_plants_slow_and_talk_over():
    turns = [{"speaker": "agent", "text": "a b c"}, {"speaker": "customer", "text": " ".join(["w"] * 10)}, {"speaker": "agent", "text": "x y"}]
    slow = layout(turns, ["slow"])
    assert abs(slow[2]["start"] - slow[1]["end"] - 4.0) < 0.02
    over = layout(turns, ["talk_over"])
    assert over[2]["start"] < over[1]["end"]


def test_simulated_segment_finds_every_planted_defect(tmp_path):
    r = simulate_segment(card(), "emi", tmp_path, FakeEvon(), n=8, seed=2, samples=1)
    e = r["evaluation"]
    assert e["calls"] == 8 and e["planted"] > 0 and e["planted_recall"] == 1.0 and e["unplanted_flag_rate"] == 0.0
    assert e["false_fatal"] == 0 and (tmp_path / "qa.html").exists() and (tmp_path / "simulate.json").exists()
    write_segments_html([r], tmp_path / "segments.html", "now")
    assert "One auditor, every business" in (tmp_path / "segments.html").read_text(encoding="utf-8")


def test_disobedient_writer_is_retried_then_excluded_not_counted(tmp_path):
    r = simulate_segment(card(), "emi", tmp_path, FakeEvon(disobey="banned_phrases"), n=5, seed=2, samples=1)
    assert r["evaluation"]["excluded_params"] > 0
    assert all("banned_phrases" in c["excluded"] for c in r["calls"] if "banned_phrases" not in c["planted"])
    assert r["evaluation"]["parameters"]["banned_phrases"]["flags"] == 0


class FakeTTS:
    def synthesize(self, text, voice="x", lang="hi-en"):
        sr = 16000
        t = np.arange(int(sr * max(0.5, len(text) * 0.03))) / sr
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr


def test_voice_call_is_dual_channel_and_audits_through_stt(tmp_path):
    from bhool.qa.conversation import _wav
    from bhool.qa.simulate import SimCall
    c = SimCall("emi-00", "emi", "hi-IN", "calm", [], [], turns=[{"speaker": "agent", "text": "नमस्ते " * 5},
                                                                   {"speaker": "customer", "text": "हाँ " * 6},
                                                                   {"speaker": "agent", "text": "धन्यवाद " * 4}])
    path = voice_call(c, FakeTTS(), tmp_path)
    chans, sr = read_wav_channels(path)
    assert chans.shape[0] == 2 and sr == 8000
    assert json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["segment"] == "emi"
    conv = _wav(path, lambda a, s, lg: "बोला", "hi-IN", 0)
    assert [t.speaker for t in conv.record.turns][:3] == ["agent", "caller", "agent"] and conv.audio_s > 0


def test_evaluate_counts_misses_and_flags():
    from bhool.qa.engine import ParamResult, QAResult
    from bhool.qa.simulate import SimCall
    calls = [SimCall("c1", "s", "hi-IN", "calm", ["privacy"], [], turns=[{}], declared=["privacy"])]
    pr = lambda pid, v: ParamResult(pid, "x", v, 1, False, None, 1.0, "", [], "judge")  # noqa: E731
    res = [QAResult("c1", {}, 50, False, [], {}, [pr("privacy", "pass"), pr("tone", "fail")], {}, {}, {}, [], [], True)]
    e = evaluate(calls, res, card())
    assert e["planted_recall"] == 0.0 and e["unplanted_flag_rate"] == 1.0
    assert {x["kind"] for x in e["examples"]} == {"missed", "unplanted flag"}


def test_studio_api_lists_segments_and_serves_calls_with_plan(tmp_path):
    from fastapi.testclient import TestClient
    from bhool.server import create_app
    simulate_segment(card(), "emi_collections", tmp_path / "seg" / "emi_collections", FakeEvon(), n=3, seed=2, samples=1)
    c = TestClient(create_app(runs_dir=tmp_path, scorecards_dir=ROOT / "scorecards"))
    d = c.get("/api/studio").json()
    assert len(d["scorecards"]) >= 7 and all("error" not in s for s in d["scorecards"])
    a = d["audits"][0]
    assert a["path"] == "seg/emi_collections" and a["evaluation"]["calls"] == 3
    calls = c.get("/api/studio/audit/seg/emi_collections").json()["calls"]
    assert len(calls) == 3 and "planted" in calls[1] and calls[1]["audio"] is None
    assert c.get("/api/studio/audit/../..").status_code == 404
    assert "QA Studio" in c.get("/studio").text


def test_planted_code_defects_are_verified_and_retried(tmp_path):
    fake = FakeEvon(lazy=True)
    r = simulate_segment(card(), "emi", tmp_path, fake, n=10, seed=4, samples=1)
    code_plants = [p for c in r["calls"] for p in c["plants"] if p["parameter"] in ("recording_disclosure", "verifies_before_amount", "banned_phrases")]
    assert code_plants and all(fake.tries[p["parameter"]] >= 2 for p in code_plants)
    assert r["evaluation"]["planted_recall"] == 1.0
    assert all(p["text"] for c in r["calls"] for p in c["plants"])


def test_apply_plant_replace_and_insert_with_setup():
    from bhool.qa.simulate import apply_plant
    turns = [{"speaker": "agent", "text": "a"}, {"speaker": "customer", "text": "b"}, {"speaker": "agent", "text": "c"}]
    new, at = apply_plant(turns, {"action": "replace", "turn": 2, "agent": "X"})
    assert new[2]["text"] == "X" and at == 2 and len(new) == 3
    new, at = apply_plant(turns, {"action": "insert_after", "turn": 1, "setup": "help!", "agent": "Y"})
    assert [t["text"] for t in new] == ["a", "b", "help!", "Y", "c"] and at == 3
    assert apply_plant(turns, {"action": "replace", "turn": 9, "agent": "Z"}) is None


def test_unconfirmed_llm_plants_are_retried_then_not_counted(tmp_path):
    fake = FakeEvon(weak=("privacy", "no_harassment", "hardship_handling", "language_match", "identifies_lender"))
    r = simulate_segment(card(), "emi", tmp_path, fake, n=10, seed=4, samples=1)
    weak_planned = [pid for pid in fake.weak if fake.tries.get(pid)]
    assert weak_planned and all(fake.tries[pid] % 3 == 0 for pid in weak_planned)       # three attempts per planned defect
    assert not any(pid in c["planted"] for c in r["calls"] for pid in fake.weak)         # never counted as planted
