"""Lines rewritten the way Timbre should say them, and lines that must be left alone."""

import pytest

from diapason.guard import Guard
from diapason.speakable import speakable


@pytest.mark.parametrize("line, want", [
    ("Please pay by 15/11.", "Please pay by 15 November."),                        # read live as "fifteen by eleven"
    ("कृपया 15/11 तक भुगतान करें।", "कृपया 15 नवंबर तक भुगतान करें।"),          # read live as "पंद्रह बटा ग्यारह"
    ("છેલ્લી તારીખ 20/11 છે.", "છેલ્લી તારીખ 20 નવેમ્બર છે."),
    ("Please pay by 5/11.", "Please pay by 5 November."),                          # a day under 13 needs a date word
    ("Your due date is 2026-11-15.", "Your due date is 15 November 2026."),       # read live as "two thousand twenty six eleven fifteen"
    ("Due on 15/11/2026, please.", "Due on 15 November 2026, please."),
    ("Due on 15-11-26.", "Due on 15 November 2026."),
    ("Please pay by 5 Nov.", "Please pay by 5 November."),                         # read live as "five now"
    ("Pay by Nov 5.", "Pay by 5 November."),
    ("Pay by 21st Nov. at noon.", "Pay by 21 November at noon."),
])
def test_rewrites_what_timbre_misreads(line, want):
    out, changed = speakable(line)
    assert out == want and changed


@pytest.mark.parametrize("line", [
    "The interest is 12.5% per annum.",
    "Your policy number is 2024/12345.",
    "Call us on 98765-43210.",
    "Your appointment is at 10:30 AM.",
    "Half of it, 1/2, is already paid.",                                            # a fraction, not a date
    "Your EMI of ₹4,500 is due and your OTP is 004821.",
    "Four of 4/12 attacks leaked.",
    "Your IFSC code is SBIN0001234.",                                              # Prisma's writing, not Timbre's reading
    "Your EMI is overdue.",
])
def test_leaves_everything_else_alone(line):
    assert speakable(line) == (line, [])


def test_guard_rewrites_last_and_logs_it():
    g = Guard(crm={"loan_id_last4": "4821"}, verified=True, disclosed=True)
    out = g.filter("Please pay by 15/11.", "en-IN")
    assert out == "Please pay by 15 November."
    assert [e.rule for e in g.events] == ["pronunciation"] and "15/11 -> 15 November" in g.events[0].matched


def test_guard_still_holds_an_unverified_date_before_rewriting():
    g = Guard(crm={"loan_id_last4": "4821", "due_date": "15 November"}, disclosed=True)
    out = g.filter("Please pay by 15/11.", "en-IN")
    assert g.events[0].rule == "account_before_verification" and "15" not in out


def test_guard_can_switch_it_off():
    g = Guard(crm={}, verified=True, disclosed=True, pronounce=False)
    assert g.filter("Please pay by 15/11.", "en-IN") == "Please pay by 15/11."
