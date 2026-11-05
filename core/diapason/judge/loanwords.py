"""Script variants for English words inside Indian-language speech.

Prisma transcribes English loanwords spoken inside Hindi/Gujarati/Marathi speech in the native
script ("police" -> पुलिस, "legal action" -> लीगल एक्शन), as measured in this project's live runs.
Code checks written in Latin script would silently miss them, so each phrase is expanded to the
spellings Prisma actually produces. Extend per suite with `banned_phrase_variants`.
"""

from __future__ import annotations

# lower-case Latin -> Devanagari and Gujarati spellings seen in, or consistent with, Prisma output
LOANWORDS: dict[str, list[str]] = {
    "police": ["पुलिस", "पोलीस", "પોલીસ", "પોલિસ"],
    "legal": ["लीगल", "लिगल", "લીગલ"],
    "action": ["एक्शन", "ऐक्शन", "એક્શન"],
    "legal action": ["लीगल एक्शन", "लिगल एक्शन", "લીગલ એક્શન"],
    "court": ["कोर्ट", "કોર્ટ"],
    "jail": ["जेल", "જેલ"],
    "arrest": ["अरेस्ट", "અરેસ્ટ"],
    "fir": ["एफ आई आर", "एफआईआर", "એફ આઈ આર"],
    "case": ["केस", "કેસ"],
    "warrant": ["वारंट", "વોરંટ"],
    "recovery agent": ["रिकवरी एजेंट", "રિકવરી એજન્ટ"],
    "blacklist": ["ब्लैकलिस्ट", "બ્લેકલિસ્ટ"],
    "cibil": ["सिबिल", "સિબિલ"],
    "otp": ["ओ टी पी", "ओटीपी", "ઓ ટી પી", "ઓટીપી"],
    "pin": ["पिन", "પિન"],
    "cvv": ["सी वी वी", "सीवीवी", "સી વી વી"],
    "password": ["पासवर्ड", "પાસવર્ડ"],
    "family": ["फैमिली", "ફેમિલી"],
    "office": ["ऑफिस", "ઓફિસ"],
}


def variants(phrase: str, extra: dict[str, list[str]] | None = None) -> list[str]:
    """The phrase plus its native-script spellings: whole-phrase entries, else word-by-word composition."""
    key = phrase.strip().lower()
    table = {**LOANWORDS, **{k.lower(): v for k, v in (extra or {}).items()}}
    out = [phrase]
    if key in table:
        out += table[key]
    else:
        words = key.split()
        if len(words) > 1 and all(w in table for w in words):
            # Compose per script position: the i-th spelling of each word (Devanagari first, then Gujarati).
            for i in range(max(len(table[w]) for w in words)):
                out.append(" ".join(table[w][min(i, len(table[w]) - 1)] for w in words))
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq
