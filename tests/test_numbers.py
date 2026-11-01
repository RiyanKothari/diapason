"""The last four digits, every way an Indian caller says them and Prisma writes them down."""

import pytest

from bhool.judge.scripts import spoken_digits

CASES = {
    "फोर थाउज़ंड एट हंडरेड ट्वेंटी वन": "4821",        # seen live: Prisma on Timbre reading "4821"; verification never unlocked
    "चार आठ दो एक": "4821", "४८२१": "4821", "4 8 2 1": "4821", "48 21": "4821", "4,821": "4821",
    "चार हज़ार आठ सौ इक्कीस": "4821", "four eight two one": "4821", "forty eight twenty one": "4821",
    "अड़तालीस इक्कीस": "4821", "फोर एट टू वन": "4821", "ફોર એટ ટુ વન": "4821",
    "डबल सात तीन शून्य": "7730", "double seven three zero": "7730", "સાત સાત ત્રણ શૂન્ય": "7730", "સિત્યોતેર ત્રીસ": "7730",
    "पाँच पाँच एक नौ": "5519", "पचपन उन्नीस": "5519", "ज़ीरो एट टू वन": "0821", "0821": "0821",
    "मैं payment पंद्रह November को करूँगा": "15", "हाँ बोलिए": "", "एक minute, चार आठ दो एक": "14821",
}


@pytest.mark.parametrize("said,digits", CASES.items())
def test_spoken_digits(said, digits):
    assert spoken_digits(said) == digits


def test_guard_and_v4_unlock_on_the_live_transcript():
    from bhool.acts import ActState
    from bhool.guard import Guard
    live = "फोर थाउज़ंड एट हंडरेड ट्वेंटी वन"
    g = Guard(crm={"loan_id_last4": "4821", "amount_due": "4500", "due_date": "5 November"})
    g.hear(live)
    st = ActState(crm={"loan_id_last4": "4821"})
    st.hear(live)
    assert g.verified and st.verified
