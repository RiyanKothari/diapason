"""Dates as people say them on Indian phone calls, so "did the agent repeat the date back?" is a code check.

Reads digits in Latin, Devanagari and Gujarati script, day numbers 1-31 as words in Hindi, Gujarati and English,
month names in all three scripts, relative days (kal, parson, tomorrow, next week) and weekdays. A number on its own
is not a date ("char aath do ek" is a loan ID): it needs a month, a date word (taarikh, date) or to be a relative day.
"""

from __future__ import annotations

import re

_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")

_HI = ["एक", "दो", "तीन", "चार", "पांच|पाँच", "छह|छः|छ", "सात", "आठ", "नौ", "दस", "ग्यारह", "बारह", "तेरह", "चौदह",
       "पंद्रह|पन्द्रह", "सोलह", "सत्रह", "अठारह", "उन्नीस", "बीस", "इक्कीस", "बाईस", "तेईस", "चौबीस", "पच्चीस", "छब्बीस",
       "सत्ताईस", "अट्ठाईस|अठ्ठाईस|अठाईस", "उनतीस|उन्तीस", "तीस", "इकतीस|इकत्तीस"]
_GU = ["એક", "બે", "ત્રણ", "ચાર", "પાંચ", "છ", "સાત", "આઠ", "નવ", "દસ", "અગિયાર", "બાર", "તેર", "ચૌદ", "પંદર", "સોળ",
       "સત્તર", "અઢાર", "ઓગણીસ", "વીસ", "એકવીસ", "બાવીસ", "ત્રેવીસ", "ચોવીસ", "પચ્ચીસ", "છવ્વીસ", "સત્તાવીસ", "અઠ્ઠાવીસ",
       "ઓગણત્રીસ", "ત્રીસ", "એકત્રીસ"]
_EN = ["one|first", "two|second", "three|third", "four|fourth", "five|fifth", "six|sixth", "seven|seventh", "eight|eighth",
       "nine|ninth", "ten|tenth", "eleven|eleventh", "twelve|twelfth", "thirteen|thirteenth", "fourteen|fourteenth",
       "fifteen|fifteenth", "sixteen|sixteenth", "seventeen|seventeenth", "eighteen|eighteenth", "nineteen|nineteenth",
       "twenty|twentieth", "twenty-one|twenty-first", "twenty-two|twenty-second", "twenty-three|twenty-third",
       "twenty-four|twenty-fourth", "twenty-five|twenty-fifth", "twenty-six|twenty-sixth", "twenty-seven|twenty-seventh",
       "twenty-eight|twenty-eighth", "twenty-nine|twenty-ninth", "thirty|thirtieth", "thirty-one|thirty-first"]
DAY_WORDS: dict[str, int] = {w: i + 1 for table in (_HI, _GU, _EN) for i, ws in enumerate(table) for w in ws.split("|")}

MONTHS: dict[int, list[str]] = {
    1: ["january", "jan", "जनवरी", "જાન્યુઆરી"], 2: ["february", "feb", "फरवरी", "फ़रवरी", "ફેબ્રુઆરી"],
    3: ["march", "मार्च", "માર્ચ"], 4: ["april", "apr", "अप्रैल", "એપ્રિલ"], 5: ["may", "मई", "મે"],
    6: ["june", "jun", "जून", "જૂન"], 7: ["july", "jul", "जुलाई", "જુલાઈ"], 8: ["august", "aug", "अगस्त", "ઑગસ્ટ", "ઓગસ્ટ"],
    9: ["september", "sep", "sept", "सितंबर", "सितम्बर", "સપ્ટેમ્બર"], 10: ["october", "oct", "अक्टूबर", "ऑक्टोबर", "ઑક્ટોબર", "ઓક્ટોબર"],
    11: ["november", "nov", "नवंबर", "नवम्बर", "નવેમ્બર"], 12: ["december", "dec", "दिसंबर", "दिसम्बर", "ડિસેમ્બર"],
}
MARKERS = ["तारीख", "तारीख़", "तारिख", "tarikh", "taarikh", "date", "તારીખ", "तारखेला", "तारीखला"]
RELATIVE: dict[str, list[str]] = {
    "today": ["today", "आज", "આજે"], "tomorrow": ["tomorrow", "कल", "આવતીકાલે", "કાલે"],
    "day_after": ["परसों", "પરમદિવસે", "પરમ"], "next_week": ["अगले हफ्ते", "अगले हफ़्ते", "next week", "આવતા અઠવાડિયે"],
    "month_end": ["महीने के आखिर", "month end", "end of the month", "મહિનાના અંતે"],
}
WEEKDAYS: dict[str, list[str]] = {
    "mon": ["monday", "सोमवार", "સોમવાર"], "tue": ["tuesday", "मंगलवार", "મંગળવાર"], "wed": ["wednesday", "बुधवार", "બુધવાર"],
    "thu": ["thursday", "गुरुवार", "बृहस्पतिवार", "ગુરુવાર"], "fri": ["friday", "शुक्रवार", "શુક્રવાર"],
    "sat": ["saturday", "शनिवार", "શનિવાર"], "sun": ["sunday", "रविवार", "રવિવાર"],
}

_SPLIT = re.compile(r"[\s,.;:!?।()\"'“”‘’/-]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _SPLIT.split(text.lower().translate(_DIGITS)) if t]


def _is(token: str, word: str) -> bool:
    """Whole word, or the word plus a short case ending (નવેમ્બરે, 15th, पंद्रहवीं)."""
    return token == word or (token.startswith(word) and len(token) - len(word) <= 3)


def date_keys(text: str) -> set[str]:
    """{"d15", "m11"} / {"rel:tomorrow"} / {"wd:mon"} for a turn that names a date; empty if it names none."""
    low = text.lower().translate(_DIGITS)
    toks = _tokens(text)
    keys: set[str] = set()
    for m, names in MONTHS.items():
        if any(_is(t, n) for t in toks for n in names if len(n) > 2 or t == n):
            keys.add(f"m{m}")
    marker = any(_is(t, w) for t in toks for w in MARKERS)
    days = set()
    for t in toks:
        d = re.fullmatch(r"(\d{1,2})(st|nd|rd|th)?", t)
        if d and 1 <= int(d.group(1)) <= 31:
            days.add(int(d.group(1)))
            marker = marker or bool(d.group(2))           # "the 15th" is a date by itself
        elif re.fullmatch(r"[a-z-]+(st|nd|rd|th)", t) and t in DAY_WORDS:
            days.add(DAY_WORDS[t])
            marker = True                                  # "fifteenth" too
        else:
            days |= {n for w, n in DAY_WORDS.items() if _is(t, w) and len(w) > 1}
    if days and (keys or marker):
        keys |= {f"d{d}" for d in days}
    for name, words in RELATIVE.items():
        if any(w in low for w in words if " " in w) or any(t == w for t in toks for w in words):
            keys.add(f"rel:{name}")
    for name, words in WEEKDAYS.items():
        if any(_is(t, w) for t in toks for w in words):
            keys.add(f"wd:{name}")
    return keys if (any(k.startswith("d") for k in keys) or any(":" in k for k in keys) or any(k.startswith("m") for k in keys)) else set()


def echoes(offer: set[str], reply: set[str]) -> bool:
    """Does the reply repeat the offered date? Day numbers must match when the customer gave one; otherwise the
    month, relative day or weekday must."""
    days = {k for k in offer if k.startswith("d")}
    if days:
        return bool(days & reply)
    return bool(offer & reply)
