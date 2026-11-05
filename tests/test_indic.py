"""Digits and dates in Marathi, Tamil, Telugu and Kannada, read from what Prisma actually wrote (scripts/lang_probe.py)."""

import json
from pathlib import Path

import pytest

from diapason.judge.dates import date_keys
from diapason.judge.numbers import COLLISIONS, spoken_digits

ROWS = json.loads((Path(__file__).parent / "data" / "prisma_indic_transcripts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", ROWS, ids=[f"{r['split']}-{r['lang']}-{r['kind']}-{r['style']}" for r in ROWS])
def test_reads_what_prisma_wrote(row):
    """28 transcripts the readers were written from, and 24 held out (other numbers, dates and voice) written after."""
    if row["kind"] == "date":
        assert set(row["gold"].split(",")) <= date_keys(row["heard"]), row["heard"]
    else:
        assert row["gold"] in spoken_digits(row["heard"]), row["heard"]


def test_joined_tamil_and_kannada_forms_are_generated():
    assert spoken_digits("இருபத்தொன்று") == "21" and spoken_digits("தொண்ணூற்றொன்பது") == "99"
    assert spoken_digits("இருபத்து மூன்று") == "23" and spoken_digits("நான்காயிரத்தி ஐநூறு") == "4500"
    assert spoken_digits("ಇಪ್ಪತ್ತೊಂದು") == "21" and spoken_digits("ಇಪ್ಪತ್ಮೂರು") == "23"
    assert spoken_digits("೪೮೨೧") == "4821" and spoken_digits("௪௮௨௧") == "4821"           # native digits


def test_nothing_new_changes_how_hindi_or_gujarati_read():
    assert not COLLISIONS
    assert spoken_digits("तेरा नाम क्या है") == ""            # Marathi 13, but Hindi "your": left out on purpose
    assert date_keys("मे payment कर दूँगा") == set()           # Marathi May, but Prisma's spelling of Hindi "में"
    assert spoken_digits("अड़तालीस इक्कीस") == "4821" and spoken_digits("ત્રણ હજાર બસો") == "3200"
