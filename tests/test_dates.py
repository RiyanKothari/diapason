import pytest

from bhool.judge.dates import date_keys, echoes
from bhool.qa import Check, Parameter, Scorecard, Section, from_turns
from bhool.qa.engine import code_check
from bhool.scenarios.schema import AgentSpec


@pytest.mark.parametrize("text, want", [
    ("पंद्रह नवंबर को पक्का कर दूंगा", {"d15", "m11"}),
    ("मैं २० तारीख को दूंगा", {"d20"}),
    ("પંદર નવેમ્બરે ચોક્કસ કરી દઈશ", {"d15", "m11"}),
    ("I will pay on the 15th", {"d15"}),
    ("on the fifteenth of December", {"d15", "m12"}),
    ("कल कर दूंगा", {"rel:tomorrow"}),
    ("next Monday is fine", {"wd:mon"}),
])
def test_dates_in_three_languages(text, want):
    assert date_keys(text) == want


@pytest.mark.parametrize("text", ["चार आठ दो एक", "एक मिनट रुकिए", "I have two kids", "ठीक है।", "4500 रुपये बाकी हैं"])
def test_numbers_that_are_not_dates(text):
    assert date_keys(text) == set()


def test_echo_needs_the_same_day():
    assert echoes(date_keys("पंद्रह नवंबर को"), date_keys("ठीक है, 15 November note कर लिया"))
    assert not echoes(date_keys("पंद्रह नवंबर को"), date_keys("ठीक है, बीस नवंबर"))
    assert not echoes(date_keys("कल दूंगा"), date_keys("ठीक है जी"))


def _card():
    return Scorecard(name="t", agent=AgentSpec(name="a", sop="s"),
                     sections=[Section(id="r", parameters=[Parameter(id="confirms_back", check=Check(type="echo"))])])


def _verdict(turns):
    conv = from_turns("c", [{"speaker": s, "text": t} for s, t in turns])
    return code_check(_card().parameters()[0], conv, _card(), {}, None)


def test_echo_check_pass_fail_na():
    assert _verdict([("agent", "कब pay करेंगे?"), ("caller", "पंद्रह नवंबर को"), ("agent", "ठीक है, पंद्रह नवंबर note किया")])[0] == "pass"
    v, reason, ev = _verdict([("agent", "कब pay करेंगे?"), ("caller", "पंद्रह नवंबर को"), ("agent", "ठीक है।")])
    assert v == "fail" and ev[0]["turn"] == 2 and "T1" in reason
    assert _verdict([("agent", "कब pay करेंगे?"), ("caller", "अभी नहीं बता सकता"), ("agent", "ठीक है")])[0] == "na"
    # the last date offered is the agreed one
    assert _verdict([("caller", "दस तारीख"), ("agent", "दस नहीं हो पाएगा"), ("caller", "तो बीस तारीख"), ("agent", "ठीक है, बीस तारीख")])[0] == "pass"
