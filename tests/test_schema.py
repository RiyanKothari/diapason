from pathlib import Path

import pytest
from pydantic import ValidationError

from bhool.scenarios import Persona, load_suite

SUITE = Path(__file__).parent.parent / "suites" / "emi_collection.yaml"


def test_example_suite_loads_and_expands():
    suite = load_suite(SUITE)
    scenarios = suite.expand()
    assert len(scenarios) == 24                      # sampled from 3 x 5 x 4 = 60
    assert len({s.id for s in scenarios}) == 24
    assert {s.channel.id for s in scenarios} <= {"landline", "street", "market", "bad_network"}


def test_expansion_is_deterministic():
    a = [(s.id, s.seed) for s in load_suite(SUITE).expand()]
    b = [(s.id, s.seed) for s in load_suite(SUITE).expand()]
    assert a == b


def test_full_product_without_sample():
    suite = load_suite(SUITE)
    suite.matrix.sample = None
    assert len(suite.expand()) == 3 * 5 * 4


def test_rejects_unknown_voice_and_tag():
    with pytest.raises(ValidationError, match="Timbre v3.0 voice"):
        Persona(id="x", description="d", voice="Kaveri")
    with pytest.raises(ValidationError, match="unknown audio tags"):
        Persona(id="x", description="d", emotion=["crying"])


def test_rejects_unknown_matrix_channel():
    suite = load_suite(SUITE)
    suite.matrix.channels = ["moon_base"]
    with pytest.raises(ValueError, match="unknown channel"):
        suite.expand()
