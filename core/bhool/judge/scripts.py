"""Which script a line is written in, and which digits it speaks: the building blocks of the language and security code checks.

Gujarati, Tamil, Telugu, Kannada, Malayalam, Bengali and Punjabi each have their own script, so answering a Gujarati
caller in Hindi is visible in the characters alone. Hindi and Marathi share Devanagari and code-mixed speech mixes in
Latin, so those are never called a mismatch: the check only fires where the script settles it.
"""

from __future__ import annotations

import re

from .dates import DAY_WORDS

SCRIPTS = {
    "devanagari": re.compile(r"[ऀ-ॿ]"), "gujarati": re.compile(r"[઀-૿]"), "gurmukhi": re.compile(r"[਀-੿]"),
    "bengali": re.compile(r"[ঀ-৿]"), "tamil": re.compile(r"[஀-௿]"), "telugu": re.compile(r"[ఀ-౿]"),
    "kannada": re.compile(r"[ಀ-೿]"), "malayalam": re.compile(r"[ഀ-ൿ]"), "latin": re.compile(r"[A-Za-z]"),
}
OWN_SCRIPT = {"gujarati", "gurmukhi", "bengali", "tamil", "telugu", "kannada", "malayalam"}   # a language you can tell by its script

DIGIT_WORDS = {w: n for w, n in DAY_WORDS.items() if n <= 9} | {"शून्य": 0, "zero": 0, "શૂન્ય": 0, "ઝીરો": 0, "जीरो": 0}
_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")


def dominant(text: str, min_letters: int = 4) -> str | None:
    """The line's script: its main Indian script if it has one (code-mixed "आज payment कीजिए" is Devanagari, however many
    English loanwords it carries), else Latin; None for a line too short to tell."""
    counts = {name: len(rx.findall(text)) for name, rx in SCRIPTS.items()}
    indic = max((n for n in counts if n != "latin"), key=counts.get)
    if counts[indic] >= min_letters:
        return indic
    return "latin" if counts["latin"] >= min_letters else None


def spoken_digits(text: str) -> str:
    """Digits in the order they are said: "चार आठ दो एक" and "4821" both give "4821"."""
    out = []
    for tok in re.split(r"[\s,.;:!?।()-]+", text.lower().translate(_DIGITS)):
        if tok.isdigit():
            out.append(tok)
        elif tok in DIGIT_WORDS:
            out.append(str(DIGIT_WORDS[tok]))
    return "".join(out)
