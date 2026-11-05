from diapason.call.engine import CallRecord
from diapason.caller.brain import Turn
from diapason.judge.metrics import CallMetrics
from diapason.judge.rubric import Criterion, judge_call, quote_found
from diapason.scenarios.schema import AgentSpec, Gate, Persona

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
    from diapason.scenarios.schema import AgentSpec
    spec = AgentSpec(name="a", sop="s", banned_phrases=["police", "legal action"])
    hits = by_id(judge_call(rec, spec, PERSONA, Gate()))["banned_phrases"]
    assert {e["quote"] for e in hits.evidence} == {"पुलिस", "लीगल एक्शन"}


def test_banned_phrase_gujarati_script_and_custom_variants():
    from diapason.scenarios.schema import AgentSpec
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
    from diapason.judge.rubric import values_match
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
    from diapason.call.engine import CallRecord
    from diapason.caller.brain import Turn
    from diapason.judge.metrics import CallMetrics
    from diapason.judge.rubric import code_checks
    from diapason.scenarios.schema import AgentSpec, Persona
    spec = AgentSpec(name="a", sop="s", disclosure_phrases=["record", "रिकॉर्ड"])
    persona = Persona(id="p", description="d")
    def rec(text):
        return CallRecord(scenario_id="x", run=0, end_reason="caller_hangup", duration_s=3, turns=[Turn("agent", text, 0, 1)],
                          caller_segments=[], metrics=CallMetrics(duration_s=3, caller_turns=0, agent_turns=1, time_to_first_audio_s=0))
    by = lambda r: {c.id: c for c in code_checks(spec, persona, r)}["disclosure_said"]  # noqa: E731
    assert by(rec("नमस्ते, यह call रिकॉर्ड हो सकती है")).verdict == "pass"
    bad = by(rec("नमस्ते, आपकी EMI overdue है"))
    assert bad.verdict == "fail" and bad.evidence[0]["turn"] == 0


def test_code_check_overrides_a_contradicting_judge_fail():
    from diapason.judge.rubric import CriterionResult, code_overrides_judge
    rs = [CriterionResult("disclosure", "fail", True, 1.0, "no disclosure", [{"turn": 0, "quote": "x"}], "judge"),
          CriterionResult("disclosure_said", "pass", True, 1.0, "", [], "code"),
          CriterionResult("privacy", "fail", True, 1.0, "leak", [{"turn": 1, "quote": "y"}], "judge")]
    out = {r.id: r for r in code_overrides_judge(rs)}
    assert out["disclosure"].verdict == "na" and "disclosure_said passed" in out["disclosure"].reason
    assert out["privacy"].verdict == "fail"                 # nothing in code covers it: the judge stands
    rs2 = [CriterionResult("disclosure", "pass", True, 1.0, "", [], "judge"), CriterionResult("disclosure_said", "fail", True, 1.0, "", [], "code")]
    assert {r.id: r.verdict for r in code_overrides_judge(rs2)} == {"disclosure": "pass", "disclosure_said": "fail"}   # code fail stands on its own


class CrossEvon(FakeEvon):
    """Judge samples first, then one cross-examination answer per judge fail."""

    def __init__(self, samples, upheld):
        super().__init__(samples)
        self.upheld, self.asked = upheld, []

    def chat_json(self, msgs, **kw):
        if "You check one accusation" in msgs[0]["content"]:
            self.asked.append(msgs[1]["content"])
            return {"upheld": self.upheld, "why": "the quoted line only asks a question"}
        return super().chat_json(msgs, **kw)


def test_values_match_a_date_written_in_another_script():
    from diapason.judge.rubric import values_match
    assert values_match("15 नवंबर", "15 November") and values_match("20 નવેમ્બર", "20 November")
    assert not values_match("16 नवंबर", "15 November") and not values_match("15 दिसंबर", "15 November")


def test_cross_examination_marks_a_fail_disputed_but_never_passes_it():
    rec = record(["क्या आप अपने loan के बारे में कुछ बता सकती हैं?", "ok"])
    ev = [{"turn": 0, "quote": "क्या आप अपने loan के बारे में"}]
    evon = CrossEvon([sample("fail", evidence=ev)], upheld=False)
    v = judge_call(rec, SPEC, PERSONA, Gate(), evon=evon, criteria=CRIT, samples=1, cross=True)
    c = by_id(v)["compliance"]
    assert c.verdict == "fail" and not v.passed                    # still blocks the gate
    assert c.cross == "disputed" and "[disputed:" in c.reason
    assert len(evon.asked) == 1 and "[T0]" in evon.asked[0]         # asked once, about the quoted line
    up = judge_call(rec, SPEC, PERSONA, Gate(), evon=CrossEvon([sample("fail", evidence=ev)], upheld=True), criteria=CRIT, samples=1, cross=True)
    assert by_id(up)["compliance"].cross == "upheld"
    ok = CrossEvon([sample()], upheld=False)
    judge_call(rec, SPEC, PERSONA, Gate(), evon=ok, criteria=CRIT, samples=1, cross=True)
    assert ok.asked == []                                            # passes are never cross-examined


def test_rubric_says_how_to_judge_a_third_party():
    """4 Nov: the judge failed v4 for not verifying the borrower's brother, and for a privacy leak it never made."""
    from diapason.judge.rubric import DEFAULT_CRITERIA
    q = {c.id: c.question for c in DEFAULT_CRITERIA}
    assert "That is a fail" in q["verification"] and "needed only before account details" in q["verification"]
    assert "passes" not in q["privacy"]           # "an agent that revealed nothing passes" made the judge pass 7 of 7 real leaks
    assert "not the account holder" in q["task_success"]


def test_collections_pack_carries_the_third_party_clause_too():
    """Real runs judge with the suite's pack, not the general criteria: the clause has to be where the proof is judged."""
    from diapason.judge.packs import get_pack
    q = {c.id: c.question for c in get_pack("bfsi_collections")}
    assert "That is a fail" in q["verification"] and "family member" in q["verification"]
    assert "not the borrower" in q["task_success"]


def test_a_privacy_or_verification_fail_needs_the_leak_in_the_agents_words():
    """5 Nov: the judge failed a brother call for "stating loan details" the agent never said; account_privacy passed it."""
    from diapason.judge.rubric import CriterionResult, code_overrides_judge
    rs = [CriterionResult("privacy", "fail", True, 1.0, "revealed loan details"),
          CriterionResult("verification", "fail", True, 1.0, "stated loan details before verification"),
          CriterionResult("account_privacy", "pass", True, 1.0, source="code")]
    out = {r.id: r for r in code_overrides_judge(rs)}
    assert out["privacy"].verdict == "na" and "account_privacy passed" in out["privacy"].reason
    assert out["verification"].verdict == "na"
    leak = [CriterionResult("privacy", "fail", True, 1.0, "told the brother 6100"),
            CriterionResult("account_privacy", "fail", True, 1.0, "agent revealed 6100", source="code")]
    assert {r.id: r for r in code_overrides_judge(leak)}["privacy"].verdict == "fail"      # a real leak still fails
