from pathlib import Path

import pytest
import yaml

from bhool.playbooks import RULES, Playbook, build_scorecard, build_suite, load_playbooks, write_all
from bhool.qa import Scorecard
from bhool.scenarios import load_suite

ROOT = Path(__file__).resolve().parents[1]


def books():
    return load_playbooks(ROOT / "playbooks" / "industries.yaml")


def test_every_industry_has_a_valid_playbook():
    bs = books()
    assert len(bs) == 22 and len({b.id for b in bs}) == 22
    for b in bs:
        card = build_scorecard(b)
        ids = [p.id for p in card.parameters()]
        assert {"recording_disclosure", "language_match", "tone"} <= set(ids)
        assert any(p.fatal for p in card.parameters()), b.id
        suite = build_suite(b)
        assert suite.expand() and all(s.persona.stt_lang in b.languages for s in suite.expand()), b.id


def test_collections_industries_get_conduct_rules_and_verification_order():
    by = {b.id: b for b in books()}
    card = build_scorecard(by["psu_bank_collections"])
    fatal = {p.id for p in card.parameters() if p.fatal}
    assert {"no_threats", "third_party_privacy", "banned_phrases", "verifies_first"} <= fatal
    assert "पुलिस" in card.agent.banned_phrase_variants["police"]
    assert "no_contacts_threat" in {p.id for p in build_scorecard(by["digital_lending_collections"]).parameters()}
    assert "refund_choice" in {p.id for p in build_scorecard(by["airline_disruptions"]).parameters() if p.fatal}


def test_third_party_callers_know_no_account_facts():
    b = {b.id: b for b in books()}["microfinance"]
    husband = [p for p in build_suite(b).personas if "NOT the account holder" in p.description]
    assert husband and husband[0].hidden_facts == {}


def test_built_files_round_trip(tmp_path):
    out = write_all(books()[:3], tmp_path / "sc", tmp_path / "su")
    for sc, su in out:
        assert "fictional" in sc.read_text(encoding="utf-8")
        Scorecard.model_validate(yaml.safe_load(sc.read_text(encoding="utf-8")))
        assert load_suite(su).expand()


def test_unknown_rule_is_rejected(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text(yaml.safe_dump({"playbooks": [{"id": "x", "title": "X", "brand": "B", "sector": "s", "use_case": "u", "languages": ["hi-IN"],
                                                "regulations": ["r"], "sop": "s", "rules": ["no_such_rule"],
                                                "callers": [{"description": "d"}]}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rules"):
        load_playbooks(f)
    assert "no_threats" in RULES and Playbook.model_fields["id"]
