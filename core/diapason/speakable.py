"""Write a line the way Timbre will say it right: the last step before text-to-speech.

Guard checks what an agent says; this checks how it will sound. Each rewrite fixes a reading measured live on Timbre
(scripts/model_probe.py, 14 Nov 2026), heard back through Prisma:

- a date without a year is read as a fraction: "15/11" -> "fifteen by eleven", "पंद्रह बटा ग्यारह"        -> "15 November"
- an ISO date is read as numbers: "2026-11-15" -> "two thousand twenty six eleven fifteen"         -> "15 November 2026"
- a month abbreviation is not expanded: "5 Nov." -> "five nov", heard as "five now"                 -> "5 November"

Not here: an IFSC code like "SBIN0001234" comes back from Prisma as "sbin" or "s bin" however its letters are spelled (spaces,
commas, dots, dashes all tried), so that is Prisma's writing, not something a rewrite can fix.

Months are written in the line's own script, so a Hindi line says "15 नवंबर". It is plain code (no model call), so it
can't change what a line means: a fraction like "1/2" is left alone unless the line reads as a date.
"""

from __future__ import annotations

import re

from .judge.scripts import dominant

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "devanagari": ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
    "gujarati": ["જાન્યુઆરી", "ફેબ્રુઆરી", "માર્ચ", "એપ્રિલ", "મે", "જૂન", "જુલાઈ", "ઓગસ્ટ", "સપ્ટેમ્બર", "ઓક્ટોબર", "નવેમ્બર", "ડિસેમ્બર"],
    "tamil": ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"],
    "telugu": ["జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్", "జూలై", "ఆగస్టు", "సెప్టెంబర్", "అక్టోబర్", "నవంబర్", "డిసెంబర్"],
    "kannada": ["ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ", "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್"],
}
ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
# words that make "5/11" a date rather than a fraction
DATE_CUES = ["by", "on", "till", "until", "before", "after", "date", "due", "from", "तक", "को", "तारीख", "तारीख़", "दिनांक",
             "સુધી", "તારીખ", "ના રોજ", "வரை", "தேதி", "அன்று", "లోగా", "తేదీ", "ರಂದು", "ದಿನಾಂಕ", "ಒಳಗೆ"]

_NO_YEAR = re.compile(r"(?<![\d/.\-])(\d{1,2})\s?[/-]\s?(\d{1,2})(?![\d/%\-]|\.\d)")
_WITH_YEAR = re.compile(r"(?<![\d/.\-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d/\-]|\.\d)")
_ISO = re.compile(r"(?<![\d/.\-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\d/\-]|\.\d)")
_ABBR_AFTER = re.compile(r"(?<![\d.])(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b(?:\.(?=\s+[a-z0-9]))?",
                         re.IGNORECASE)                     # "5 Nov." ends a sentence: its full stop stays
_ABBR_BEFORE = re.compile(r"\b(jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?!\d|\.\d)", re.IGNORECASE)


def _month(n: int, script: str) -> str:
    return MONTHS.get(script, MONTHS["en"])[n - 1]


def _date(d: str, m: str, script: str, year: str = "") -> str | None:
    day, mon = int(d), int(m)
    if not (1 <= day <= 31 and 1 <= mon <= 12):
        return None
    y = (("20" + year) if len(year) == 2 else year) if year else ""
    return f"{day} {_month(mon, script)}" + (f" {y}" if y else "")


def speakable(text: str) -> tuple[str, list[str]]:
    """The line rewritten for text-to-speech, and what was changed (empty when nothing was)."""
    script = dominant(text) or "en"
    script = script if script in MONTHS else "en"
    changed: list[str] = []

    def sub(pattern: re.Pattern, fn, s: str) -> str:
        def repl(m: re.Match) -> str:
            new = fn(m)
            if new is None or new == m.group(0):
                return m.group(0)
            changed.append(f"{m.group(0)} -> {new}")
            return new
        return pattern.sub(repl, s)

    out = sub(_ISO, lambda m: _date(m.group(3), m.group(2), script, m.group(1)), text)
    out = sub(_WITH_YEAR, lambda m: _date(m.group(1), m.group(2), script, m.group(3)), out)
    low = f" {out.lower()} "
    cued = any(f" {c} " in low or c in out for c in DATE_CUES if not c.isascii()) or any(f" {c} " in low for c in DATE_CUES if c.isascii())
    out = sub(_NO_YEAR, lambda m: _date(m.group(1), m.group(2), script) if (int(m.group(1)) > 12 or cued) else None, out)
    out = sub(_ABBR_AFTER, lambda m: f"{int(m.group(1))} {_month(ABBR[m.group(2).lower()], script)}", out)
    out = sub(_ABBR_BEFORE, lambda m: f"{int(m.group(2))} {_month(ABBR[m.group(1).lower()], script)}", out)
    return out, changed
