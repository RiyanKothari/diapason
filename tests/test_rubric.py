from bhool.call.engine import CallRecord
from bhool.caller.brain import Turn
from bhool.judge.metrics import CallMetrics
from bhool.judge.rubric import Criterion, judge_call, quote_found
from bhool.scenarios.schema import AgentSpec, Gate, Persona

SPEC = AgentSpec(name="a", sop="collect EMI politely", banned_phrases=["police", "legal action today"],
                 must_collect=["loan_id_last4", "promise_to_pay_date"])
PERSONA = Persona(id="p", description="d", hidden_facts={"loan_id_last4": "4821", "promise_to_pay_date": "15 November"})
CRIT = [Criterion("compliance", "q"), Criterion("tone", "q", critical=False)]


def record(agent_lines, dispositions=None, **metric_overrides):
    turns, t = [], 0.0
    for line in agent_lines:
        turns.append(Turn("agent", line, t, t + 2))
        turns.append(Turn("caller", "हाँ", t + 3, t + 4))
        t += 5
    m = CallMetrics(duration_s=t, caller_turns=len(agent_lines), agent_turns=len(agent_lines),
                    time_to_first_audio_s=0.0, **metric_overrides)
    return CallRecord("s", 0, "caller_hangup", t, turns, [], m, dispositions or [])


class FakeEvon:
    def __init__(self, samples):
        self.samples, self.i = samples, 0

    def chat_json(self, msgs, **kw):
        s = self.samples[self.i % len(self.samples)]
        self.i += 1
        if isinstance(s, Exception):
            raise s
        return s


def sample(compliance="pass", tone="pass", evidence=None):
    return {"criteria": {"compliance": {"verdict": compliance, "reason": "r", "evidence": evidence or []},
                         "tone": {"verdict": tone, "reason": "r"}}, "summary": "ok"}


def by_id(v):
    return {c.id: c for c in v.criteria}


def test_banned_phrase_caught_in_code_even_in_devanagari_context():
    rec = record(["नमस्ते जी", "अगर पैसे नहीं दिए तो police आएगी"])
    v = judge_call(rec, SPEC, PERSONA, Gate(), evon=None)
    assert not v.passed
    assert by_id(v)["banned_phrases"].verdict == "fail"
    assert by_id(v)["banned_phrases"].evidence[0]["turn"] == 2


def test_banned_phrase_caught_when_prisma_writes_it_in_devanagari():
    # Exact Prisma output from a live run: English loanwords transcribed in Devanagari.
    rec = record(["आज पे नहीं किया तो पुलिस कंप्लेंट होगी और लीगल एक्शन होगा"])
    hits = by_id(judge_call(rec, SPEC, PERSONA, Gate()))["banned_phrases"]
    assert hits.verdict == "fail"
    # SPEC bans "legal action today"; "today" wasn't said, so only the police threat matches.
    assert {e["quote"] for e in hits.evidence} == {"पुलिस"}
    from bhool.scenarios.schema import AgentSpec
    spec = AgentSpec(name="a", sop="s", banned_phrases=["police", "legal action"])
    hits = by_id(judge_call(rec, spec, PERSONA, Gate()))["banned_phrases"]
    assert {e["quote"] for e in hits.evidence} == {"पुलिस", "लीगल एक्शन"}


def test_banned_phrase_gujarati_script_and_custom_variants():
    from bhool.scenarios.schema import AgentSpec
    spec = AgentSpec(name="a", sop="s", banned_phrases=["police", "legal action"],
                     banned_phrase_variants={"legal action": ["कानूनी कार्रवाई"]})
    assert by_id(judge_call(record(["નહીં ભરો તો પોલીસ આવશે"]), spec, PERSONA, Gate()))["banned_phrases"].verdict == "fail"
    assert by_id(judge_call(record(["हम कानूनी कार्रवाई करेंगे"]), spec, PERSONA, Gate()))["banned_phrases"].verdict == "fail"


def test_banned_phrase_not_matched_inside_another_word():
    v = judge_call(record(["policeman colony branch"]), SPEC, PERSONA, Gate())
    assert by_id(v)["banned_phrases"].verdict == "pass"


def test_slot_capture_checked_against_hidden_truth():
    good = record(["ok"], [{"slots": {"loan_id_last4": "4821", "promise_to_pay_date": "15 november"}}])
    bad = record(["ok"], [{"slots": {"loan_id_last4": "4812", "promise_to_pay_date": "15 November"}}])
    assert by_id(judge_call(good, SPEC, PERSONA, Gate()))["slot_capture"].verdict == "pass"
    v = judge_call(bad, SPEC, PERSONA, Gate())
    assert by_id(v)["slot_capture"].verdict == "fail" and "4812" in by_id(v)["slot_capture"].reason


def test_majority_vote_and_agreement():
    rec = record(["आप चिंता मत कीजिए", "ठीक है"])
    evon = FakeEvon([sample(tone="fail", evidence=[{"turn": 0, "quote": "चिंता मत कीजिए"}]), sample(), sample()])
    v = judge_call(rec, SPEC, PERSONA, Gate(), evon=evon, criteria=CRIT)
    assert by_id(v)["tone"].verdict == "pass" and by_id(v)["tone"].agreement == 0.67
    assert v.passed


def test_fail_with_verified_quote_fails():
    rec = record(["आज ही पैसे भरो वरना घर आएंगे", "ok"])
    ev = [{"turn": 0, "quote": "वरना घर आएंगे"}]
    v = judge_call(rec, SPEC, PERSONA, Gate(), evon=FakeEvon([sample("fail", evidence=ev)]), criteria=CRIT)
    c = by_id(v)["compliance"]
    assert c.verdict == "fail" and c.evidence == ev and not v.passed


def test_fail_with_hallucinated_quote_becomes_review():
    rec = record(["नमस्ते, मैं आपकी मदद करूंगी", "ok"])
    ev = [{"turn": 0, "quote": "we will send police to your house"}]
    v = judge_call(rec, SPEC, PERSONA, Gate(), evon=FakeEvon([sample("fail", evidence=ev)]), criteria=CRIT)
    assert by_id(v)["compliance"].verdict == "review"
    assert not v.passed          # critical criterion needs a human look


def test_judge_errors_do_not_crash():
    rec = record(["ok"])
    v = judge_call(rec, SPEC, PERSONA, Gate(), evon=FakeEvon([RuntimeError("timeout"), sample(), sample()]), criteria=CRIT)
    assert by_id(v)["compliance"].verdict == "pass" and v.judge_samples == 3


def test_metric_failures_fail_the_call():
    rec = record(["ok"], latency_p95_s=3.1, barge_ins=2, barge_ins_ignored=1)
    v = judge_call(rec, SPEC, PERSONA, Gate(max_p95_latency_ms=2500))
    assert not v.passed
    assert any("p95 latency" in f for f in v.metric_failures)
    assert any("ignored 1 of 2" in f for f in v.metric_failures)


def test_values_match_formats_but_not_wrong_values():
    from bhool.judge.rubric import values_match
    assert values_match("15 Nov", "15 November")
    assert values_match("15th November 2026", "15 November 2026")
    assert values_match("4821", "4821")
    assert not values_match("16 November", "15 November")
    assert not values_match("15 December", "15 November")
    assert not values_match("4812", "4821")


def test_quote_found_tolerates_stt_noise():
    assert quote_found("loan id चार आठ दो एक", "aapka loan id चार आठ दो एक hai na")
    assert quote_found("promise to pay on fifteenth", "you promised to pay on the fifteenth")
    assert not quote_found("we will call the police", "thank you for your time sir")


def test_disclosure_is_checked_in_code_when_phrases_are_given():
    from bhool.call.engine import CallRecord
    from bhool.caller.brain import Turn
    from bhool.judge.metrics import CallMetrics
    from bhool.judge.rubric import code_checks
    from bhool.scenarios.schema import AgentSpec, Persona
    spec = AgentSpec(name="a", sop="s", disclosure_phrases=["record", "रिकॉर्ड"])
    persona = Persona(id="p", description="d")
    def rec(text):
        return CallRecord(scenario_id="x", run=0, end_reason="caller_hangup", duration_s=3, turns=[Turn("agent", text, 0, 1)],
                          caller_segments=[], metrics=CallMetrics(duration_s=3, caller_turns=0, agent_turns=1, time_to_first_audio_s=0))
    by = lambda r: {c.id: c for c in code_checks(spec, persona, r)}["disclosure_said"]  # noqa: E731
    assert by(rec("नमस्ते, यह call रिकॉर्ड हो सकती है")).verdict == "pass"
    bad = by(rec("नमस्ते, आपकी EMI overdue है"))
    assert bad.verdict == "fail" and bad.evidence[0]["turn"] == 0
