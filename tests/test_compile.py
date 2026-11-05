import pytest

from diapason.qa.compile import build

POLICY = """3. Recovery agents shall not threaten the borrower with police action or jail.
4. Every call must say that the call is being recorded.
5. Agents must verify the borrower's identity before discussing the loan amount.
6. Agents must treat borrowers in hardship with empathy and offer a callback."""


def test_compiled_checks_are_typed_validated_and_traced_to_clauses():
    data = {"name": "Recovery calls", "agent": {"name": "Recovery desk", "sop": "Call borrowers politely."}, "sections": [
        {"id": "conduct", "name": "Conduct", "parameters": [
            {"id": "no threats", "weight": 10, "fatal": True, "source": "shall not threaten the borrower with police action or jail",
             "check": {"type": "phrase_absent", "phrases": ["police", "jail", "पुलिस"]}},
            {"id": "disclosure", "weight": 6, "source": "Every call must say that the call is being recorded",
             "check": {"type": "phrase_present", "phrases": ["record", "रिकॉर्ड"]}},
            {"id": "verify_first", "weight": 8, "fatal": True, "source": "verify the borrower's identity before discussing the loan amount",
             "check": {"type": "order", "first": ["last 4"], "then": ["rupees"]}},
            {"id": "empathy", "weight": 5, "source": "offer a free laptop to every borrower", "check": {"type": "llm", "question": "Was the agent empathetic?"}},
            {"id": "broken", "check": {"type": "order", "first": ["x"]}, "source": "verify"},
        ]}]}
    card, notes = build(data, POLICY)
    ps = {p.id: p for p in card.parameters()}
    assert ps["no_threats"].check.type == "phrase_absent" and ps["no_threats"].fatal and "पुलिस" in card.agent.banned_phrases
    assert ps["verify_first"].check.type == "order" and not ps["verify_first"].source.startswith("[")
    assert ps["empathy"].source.startswith("[unverified]")              # a clause that isn't in the text is flagged
    assert "broken" not in ps and any("dropped broken" in n for n in notes)   # an incomplete check is dropped, not guessed
    assert {"responsive", "no_dead_air"} <= set(ps)                      # measured experience always added


def test_nothing_usable_is_an_error():
    with pytest.raises(ValueError):
        build({"sections": [{"id": "x", "parameters": ["junk"]}]}, POLICY)
