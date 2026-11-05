import csv
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from diapason.qa import Check, Parameter, Scorecard, Section, aggregate, calibrate, drift, from_pack, from_turns, load, run_batch, score_call, write_outputs
from diapason.qa.bench import build_corpus, evaluate, run_bench
from diapason.scenarios import load_suite
from diapason.scenarios.schema import AgentSpec

ROOT = Path(__file__).resolve().parents[1]
AGENT = AgentSpec(name="a", sop="Verify, state amount, get a date. Never threaten.", banned_phrases=["police"], must_collect=["promise_to_pay_date"])


def card(*params, **kw) -> Scorecard:
    return Scorecard(name="t", agent=AGENT, sections=[Section(id="s", parameters=list(params))], **kw)


def turns(*lines, timed=True, gap=0.6):
    out, t = [], 0.0
    for who, text in lines:
        out.append({"speaker": who, "text": text, **({"start": t, "end": t + 2.0} if timed else {})})
        t += 2.0 + gap
    return out


CALL = turns(("agent", "नमस्ते, यह कॉल रिकॉर्ड हो रही है। loan ID के आखिरी चार अंक बताइए।"), ("caller", "चार आठ दो एक"),
             ("agent", "धन्यवाद, आपकी EMI के 4500 रुपये बाकी हैं। कब pay करेंगे?"), ("caller", "पंद्रह नवंबर को"),
             ("agent", "ठीक है, पंद्रह नवंबर note कर लिया।"))


class FakeEvon:
    """Answers the judge prompt from a list of samples, and the insights prompt from `info`."""

    def __init__(self, samples, info=None):
        self.samples, self.info, self.i, self.calls = samples, info or {}, 0, 0

    def chat_json(self, msgs, **kw):
        self.calls += 1
        if "analyse one customer call" in msgs[0]["content"]:
            return self.info
        s = self.samples[self.i % len(self.samples)]
        self.i += 1
        if isinstance(s, Exception):
            raise s
        return s


def P(pid, check, **kw):
    return Parameter(id=pid, check=check, **kw)


# ---------------------------------------------------------------- scorecard

def test_scorecard_validation():
    with pytest.raises(ValidationError):
        Check(type="metric", metric="latency > fast")
    with pytest.raises(ValidationError):
        Check(type="llm")
    with pytest.raises(ValidationError):
        card(P("x", Check(question="q")), P("x", Check(question="q")))


def test_example_scorecard_and_pack_template_validate():
    sc = Scorecard.model_validate(yaml.safe_load((ROOT / "scorecards/emi_collections.yaml").read_text(encoding="utf-8")))
    assert {"order", "metric", "slot", "llm", "phrase_present", "phrase_absent"} <= {p.check.type for p in sc.parameters()}
    tmpl = from_pack("bfsi_collections", load_suite(ROOT / "suites/emi_collection.yaml").agent)
    fatal = {p.id for p in tmpl.parameters() if p.fatal}
    assert {"banned_phrases", "no_harassment", "privacy"} <= fatal


# ---------------------------------------------------------------- loading

def test_loads_every_transcript_format(tmp_path):
    (tmp_path / "a.jsonl").write_text("\n".join(json.dumps({"call_id": f"j{i}", "agent_id": "x", "turns": CALL}) for i in range(2)), encoding="utf-8")
    with open(tmp_path / "b.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["call_id", "speaker", "text", "start", "end", "agent_id"])
        w.writerow(["c1", "Bot", "नमस्ते", "0", "1", "y"])
        w.writerow(["c1", "Customer", "हाँ", "1.5", "2", "y"])
    (tmp_path / "c.txt").write_text("Agent: Hello\nCustomer: haan\nboliye\n", encoding="utf-8")
    (tmp_path / "d.json").write_text(json.dumps({"id": "d1", "messages": turns(("assistant", "hi"), ("user", "ok"), timed=False)}), encoding="utf-8")
    convs = {c.call_id: c for c in load([tmp_path])}
    assert set(convs) == {"j0", "j1", "c1", "c", "d1"}
    assert convs["c1"].meta["agent_id"] == "y" and convs["c1"].record.turns[0].speaker == "agent"
    assert convs["c"].record.turns[1].text == "haan boliye" and not convs["c"].timed
    with pytest.raises(ValueError):
        from_turns("z", [{"speaker": "narrator", "text": "x"}])


# ---------------------------------------------------------------- code checks

def test_code_checks_phrases_order_metrics():
    sc = card(P("rec", Check(type="phrase_present", phrases=["रिकॉर्ड"])),
              P("threat", Check(type="phrase_absent", phrases=["police"]), fatal=True),
              P("verify_first", Check(type="order", first=["आखिरी चार"], then=["रुपये"])),
              P("fast", Check(type="metric", metric="latency_p95_s <= 2.5")))
    r = score_call(from_turns("ok", CALL), sc)
    assert {p.id: p.verdict for p in r.params} == {"rec": "pass", "threat": "pass", "verify_first": "pass", "fast": "pass"}
    assert r.score == 100 and r.passed

    # Prisma writes "police" in Devanagari; amount stated before verification; slow replies
    bad = turns(("agent", "आपके 4500 रुपये बाकी हैं, नहीं भरे तो पुलिस आएगी। loan ID के आखिरी चार अंक?"), ("caller", "चार आठ"),
                ("agent", "ठीक है"), gap=4.0)
    r = score_call(from_turns("bad", bad), sc)
    v = {p.id: p for p in r.params}
    assert v["threat"].verdict == "fail" and v["threat"].evidence[0]["quote"] == "पुलिस"
    assert v["verify_first"].verdict == "fail" and "रुपये" in v["verify_first"].reason
    assert v["fast"].verdict == "fail"
    assert r.fatal == ["threat"] and r.score == 0 and not r.passed


def test_untimed_transcript_makes_timing_not_applicable():
    sc = card(P("fast", Check(type="metric", metric="latency_p95_s <= 2.5")), P("rec", Check(type="phrase_present", phrases=["रिकॉर्ड"])))
    r = score_call(from_turns("u", turns(*[(t["speaker"], t["text"]) for t in CALL], timed=False)), sc)
    assert {p.id: p.verdict for p in r.params} == {"fast": "na", "rec": "pass"} and r.metrics == {}


def test_slot_checks_against_crm_and_skips_offline():
    sc = card(P("ptp", Check(type="slot", slot="promise_to_pay_date")))
    conv = from_turns("s", CALL, {"crm": {"promise_to_pay_date": "15 November"}})
    assert score_call(conv, sc).params[0].verdict == "skipped"                       # nothing logged, no Evon
    right = FakeEvon([{}], {"entities": {"promise_to_pay_date": "15 Nov"}})
    assert score_call(conv, sc, right).params[0].verdict == "pass"
    wrong = FakeEvon([{}], {"entities": {"promise_to_pay_date": "16 November"}})
    p = score_call(conv, sc, wrong).params[0]
    assert p.verdict == "fail" and "CRM" in p.reason
    logged = from_turns("l", CALL, {"dispositions": [{"slots": {"promise_to_pay_date": "15 November"}}]})
    assert score_call(logged, sc).params[0].verdict == "pass"                         # agent's own log counts offline


# ---------------------------------------------------------------- Evon judge

def judge(**params):
    return {"parameters": params}


def test_llm_majority_scale_and_evidence_verification():
    sc = card(P("polite", Check(question="q"), weight=1), P("tone", Check(question="q", scale=5), weight=1),
              P("made_up", Check(question="q"), fatal=True))
    fake = FakeEvon([
        judge(polite={"verdict": "pass"}, tone={"score": 4}, made_up={"verdict": "fail", "evidence": [{"turn": 0, "quote": "we will send police"}]}),
        judge(polite={"verdict": "fail", "evidence": [{"turn": 2, "quote": "कब pay करेंगे"}]}, tone={"score": 5}, made_up={"verdict": "fail"}),
        judge(polite={"verdict": "pass"}, tone={"score": 4}, made_up={"verdict": "pass"}),
    ])
    r = score_call(from_turns("j", CALL), sc, fake, samples=3)
    v = {p.id: p for p in r.params}
    assert v["polite"].verdict == "pass" and v["polite"].agreement == 0.67 and v["polite"].evidence == []
    assert v["tone"].verdict == "pass" and v["tone"].value == 0.75
    assert v["made_up"].verdict == "review"                 # fail without a real quote is never a fail
    assert r.fatal == [] and any("made_up" in x for x in r.review)
    assert not any(x.startswith("polite") for x in r.review)     # a 2-of-3 majority meets the 0.67 bar
    r = score_call(from_turns("j", CALL), sc.model_copy(update={"review_agreement": 0.9}), FakeEvon(fake.samples), samples=3)
    assert any(x.startswith("polite") for x in r.review)          # a stricter scorecard routes splits to a human


def test_verified_fail_quote_carries_timestamp_and_bad_samples_dont_crash():
    sc = card(P("conduct", Check(question="q"), fatal=True))
    ev = [{"turn": 2, "quote": "कब pay करेंगे"}]
    fake = FakeEvon([RuntimeError("timeout"), judge(conduct={"verdict": "fail", "evidence": ev}), judge(conduct={"verdict": "fail", "evidence": ev})])
    r = score_call(from_turns("f", CALL), sc, fake, samples=3)
    p = r.params[0]
    assert p.verdict == "fail" and p.evidence[0]["t"] == 5.2 and r.fatal == ["conduct"] and r.score == 0


def test_insights_are_sanitised():
    info = {"summary": "s", "disposition": "made_up", "entities": {"promise_to_pay_date": "15 Nov", "other": "x"},
            "caller_sentiment": [{"turn": 1, "score": -5}, {"turn": 3, "score": 2}, {"turn": 0, "score": 1}, {"turn": 99, "score": 0}],
            "coaching": [{"turn": 2, "tip": "confirm the amount"}, {"turn": 50, "tip": "bad"}]}
    sc = card(P("x", Check(type="phrase_present", phrases=["नमस्ते"])), entities=["promise_to_pay_date"])
    i = score_call(from_turns("i", CALL), sc, FakeEvon([{}], info)).insights
    assert i["disposition"] == "other" and i["entities"] == {"promise_to_pay_date": "15 Nov"}
    assert [s["turn"] for s in i["sentiment"]] == [1, 3] and i["sentiment"][0]["score"] == -2 and i["sentiment_shift"] == 4
    assert [c["turn"] for c in i["coaching"]] == [2]


# ---------------------------------------------------------------- batch, calibration, drift, outputs

def test_batch_rollup_calibration_drift_and_redacted_outputs(tmp_path):
    sc = card(P("threat", Check(type="phrase_absent", phrases=["police"]), fatal=True),
              P("rec", Check(type="phrase_present", phrases=["रिकॉर्ड"])))
    good = from_turns("g", CALL, {"agent_id": "A"})
    bad = from_turns("b", turns(("agent", "मेरा नंबर 9876543210 है, police आएगी")), {"agent_id": "B"})
    results = run_batch([good, bad], sc, concurrency=2)
    s = aggregate(results, sc)
    assert s["pass_rate"] == 0.5 and s["fatal_rate"] == 0.5
    assert s["groups"]["agent_id"]["B"]["weakest"] in ("threat", "rec") and list(s["groups"]["agent_id"]) == ["A", "B"]
    assert s["parameters"]["threat"]["examples"][0]["call_id"] == "b"

    labels = tmp_path / "labels.csv"
    labels.write_text("call_id,parameter,verdict\ng,threat,pass\nb,threat,fail\ng,rec,pass\nb,rec,pass\n", encoding="utf-8")
    cal = calibrate(results, labels)
    assert cal["overall"]["n"] == 4 and cal["parameters"]["threat"]["fail_recall"] == 1.0
    assert cal["parameters"]["rec"]["agreement"] == 0.5

    before = {**s, "avg_score": 90.0, "parameters": {"threat": {"pass_rate": 1.0}}}
    d = drift(s, before)
    assert d["moved"][0]["parameter"] == "threat" and d["moved"][0]["change"] == -0.5

    write_outputs(results, s, sc, tmp_path / "out")
    data = json.loads((tmp_path / "out/qa.json").read_text(encoding="utf-8"))
    assert "9876543210" not in json.dumps(data, ensure_ascii=False)
    assert (tmp_path / "out/qa.html").read_text(encoding="utf-8").count("<details>") == 2
    rows = list(csv.reader(open(tmp_path / "out/calls.csv", encoding="utf-8-sig")))
    assert rows[0][-2:] == ["threat", "rec"] and len(rows) == 3


def test_one_broken_call_does_not_sink_the_batch():
    sc = card(P("x", Check(question="q")))

    class Boom:
        def chat_json(self, *a, **k):
            raise RuntimeError("down")
    rs = run_batch([from_turns("a", CALL)], sc, Boom())
    assert rs[0].error is None and rs[0].params[0].verdict == "review"


# ---------------------------------------------------------------- QA-Bench

def test_bench_corpus_is_deterministic_and_covers_failures():
    a, ta = build_corpus(20, seed=3)
    b, tb = build_corpus(20, seed=3)
    assert a == b and ta == tb
    fails = {k for t in ta.values() for k, v in t.items() if v == "fail"}
    assert {"recording_disclosure", "verifies_before_amount", "banned_phrases", "privacy", "language_match"} <= fails


def test_bench_code_checks_are_exact_offline():
    sc = Scorecard.model_validate(yaml.safe_load((ROOT / "scorecards/emi_collections.yaml").read_text(encoding="utf-8")))
    _, truth, results, ev = run_bench(sc, None, n=40)
    for pid, s in ev["parameters"].items():
        assert s["accuracy"] == 1.0, (pid, s)
    assert ev["fatal_recall"] == 1.0 and ev["fatal_false_alarms"] == 0
    assert evaluate(results, truth, sc) == ev


def test_cli_audit_offline_end_to_end(tmp_path):
    from typer.testing import CliRunner
    from diapason.cli import app
    src = tmp_path / "calls.jsonl"
    src.write_text("\n".join(json.dumps({"call_id": f"c{i}", "agent_id": "A", "turns": CALL}) for i in range(3)), encoding="utf-8")
    out = tmp_path / "audit"
    res = CliRunner().invoke(app, ["qa", "audit", str(ROOT / "scorecards/emi_collections.yaml"), str(src), "--offline", "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "3/3 audited" in res.output and (out / "qa.html").exists()
    tmpl = tmp_path / "card.yaml"
    res = CliRunner().invoke(app, ["qa", "template", str(ROOT / "suites/emi_collection.yaml"), "--out", str(tmpl)])
    assert res.exit_code == 0 and Scorecard.model_validate(yaml.safe_load(tmpl.read_text(encoding="utf-8")))


def test_judge_output_as_list_or_junk_never_crashes_the_audit():
    from diapason.qa.engine import _param_rows
    assert _param_rows({"parameters": [{"id": "tone", "score": 4}, "junk"]}) == {"tone": {"id": "tone", "score": 4}}
    assert _param_rows(["not", "a", "dict"]) == {} and _param_rows({"parameters": {"a": [1]}}) == {}
