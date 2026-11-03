"""Numbers as Indian callers say them, and as Prisma writes them down, turned back into digits.

Found live (2 Nov): Timbre read a caller's "4821" as "four thousand eight hundred twenty one" and Prisma wrote it as
"फोर थाउज़ंड एट हंडरेड ट्वेंटी वन": English number words in Devanagari. The old parser knew single digit words only, so
no caller could ever verify and the agent asked for the digits until the call timed out. Real callers say the last four
digits every way there is:

    digit by digit      "चार आठ दो एक", "four eight two one", "ફોર એટ ટુ વન", "4 8 2 1"
    in pairs            "अड़तालीस इक्कीस", "forty eight twenty one", "અડતાલીસ એકવીસ"
    as one number       "चार हज़ार आठ सौ इक्कीस", "four thousand eight hundred twenty one"
    with repeats        "डबल सात तीन शून्य", "double seven three zero"

Words 0-99 in Hindi, Gujarati and English, English number words written in Devanagari or Gujarati script, hundred and
thousand, and double/triple. Spelling variants of nukta and chandrabindu are folded before lookup.
"""

from __future__ import annotations

import re

_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")
_SPLIT = re.compile(r"[\s,.;:!?।()\"'“”‘’/₹-]+")      # "₹4,500" is 4500

_HI = ["शून्य|जीरो|ज़ीरो|झीरो", "एक", "दो", "तीन", "चार", "पांच|पाँच", "छह|छः|छे", "सात", "आठ", "नौ", "दस", "ग्यारह", "बारह",
       "तेरह", "चौदह", "पंद्रह|पन्द्रह", "सोलह", "सत्रह", "अठारह", "उन्नीस", "बीस", "इक्कीस", "बाईस", "तेईस", "चौबीस", "पच्चीस",
       "छब्बीस", "सत्ताईस", "अट्ठाईस|अठ्ठाईस|अठाईस", "उनतीस|उन्तीस", "तीस", "इकतीस|इकत्तीस", "बत्तीस", "तैंतीस|तेतीस|तैतीस",
       "चौंतीस|चौतीस", "पैंतीस|पैतीस", "छत्तीस", "सैंतीस|सैतीस", "अड़तीस|अडतीस", "उनतालीस|उन्तालीस", "चालीस", "इकतालीस",
       "बयालीस|बियालीस", "तैंतालीस|तैतालीस", "चवालीस|चौवालीस", "पैंतालीस|पैतालीस", "छियालीस", "सैंतालीस|सैतालीस",
       "अड़तालीस|अडतालीस", "उनचास", "पचास", "इक्यावन", "बावन", "तिरपन|तिरेपन", "चौवन|चव्वन", "पचपन", "छप्पन", "सत्तावन",
       "अट्ठावन|अठावन", "उनसठ", "साठ", "इकसठ", "बासठ", "तिरसठ|तिरेसठ", "चौंसठ|चौसठ", "पैंसठ|पैसठ", "छियासठ", "सड़सठ|सरसठ",
       "अड़सठ|अडसठ", "उनहत्तर", "सत्तर", "इकहत्तर", "बहत्तर", "तिहत्तर", "चौहत्तर", "पचहत्तर", "छिहत्तर", "सतहत्तर",
       "अठहत्तर", "उन्यासी|उनासी", "अस्सी", "इक्यासी", "बयासी", "तिरासी", "चौरासी", "पचासी", "छियासी", "सत्तासी",
       "अट्ठासी|अठासी", "नवासी", "नब्बे", "इक्यानबे|इक्यानवे", "बानबे|बानवे", "तिरानबे|तिरानवे", "चौरानबे|चौरानवे",
       "पचानबे|पचानवे", "छियानबे|छियानवे", "सत्तानबे|सत्तानवे", "अट्ठानबे|अट्ठानवे", "निन्यानबे|निन्यानवे"]
_GU = ["શૂન્ય|ઝીરો", "એક", "બે", "ત્રણ", "ચાર", "પાંચ", "છ", "સાત", "આઠ", "નવ", "દસ", "અગિયાર", "બાર", "તેર", "ચૌદ", "પંદર",
       "સોળ", "સત્તર", "અઢાર", "ઓગણીસ", "વીસ", "એકવીસ", "બાવીસ", "ત્રેવીસ|તેવીસ", "ચોવીસ", "પચ્ચીસ", "છવ્વીસ", "સત્તાવીસ",
       "અઠ્ઠાવીસ", "ઓગણત્રીસ", "ત્રીસ", "એકત્રીસ", "બત્રીસ", "તેત્રીસ", "ચોત્રીસ", "પાંત્રીસ", "છત્રીસ", "સાડત્રીસ|સાડીત્રીસ",
       "આડત્રીસ|અડત્રીસ", "ઓગણચાલીસ", "ચાલીસ", "એકતાલીસ", "બેતાલીસ", "તેતાલીસ|ત્રેતાલીસ", "ચુંમાલીસ|ચુમ્માલીસ", "પિસ્તાલીસ",
       "છેતાલીસ", "સુડતાલીસ", "અડતાલીસ", "ઓગણપચાસ", "પચાસ", "એકાવન", "બાવન", "ત્રેપન", "ચોપન", "પંચાવન", "છપ્પન", "સત્તાવન",
       "અઠ્ઠાવન", "ઓગણસાઠ", "સાઠ", "એકસઠ", "બાસઠ", "ત્રેસઠ", "ચોસઠ", "પાંસઠ", "છાસઠ", "સડસઠ", "અડસઠ", "ઓગણસિત્તેર",
       "સિત્તેર", "એકોતેર", "બોંતેર|બોતેર", "તોંતેર|તોતેર", "ચુમોતેર", "પંચોતેર", "છોંતેર|છોતેર", "સિત્યોતેર|સિત્તોતેર",
       "ઇઠ્યોતેર|અઠ્યોતેર", "ઓગણએંસી", "એંસી", "એક્યાસી", "બ્યાસી", "ત્યાસી", "ચોર્યાસી", "પંચ્યાસી|પંચાસી", "છ્યાસી",
       "સિત્યાસી", "ઇઠ્યાસી|અઠ્યાસી", "નેવ્યાસી", "નેવું", "એકાણું", "બાણું", "ત્રાણું", "ચોરાણું", "પંચાણું", "છન્નું", "સત્તાણું",
       "અઠ્ઠાણું", "નવ્વાણું"]
_EN_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
             "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
            "ninety": 90}
# English number words as Prisma writes them in Devanagari or Gujarati script
_EN_SPELT = {
    "zero": "जीरो|ઝીરો", "one": "वन|वॅन|વન", "two": "टू|ટુ|ટૂ", "three": "थ्री|थ्रि|થ્રી", "four": "फोर|फ़ोर|ફોર",
    "five": "फाइव|फ़ाइव|फाईव|ફાઇવ|ફાઈવ", "six": "सिक्स|સિક્સ", "seven": "सेवन|सेवेन|સેવન", "eight": "एट|ऐट|एइट|एयठ|एइठ|એટ|એઇટ|એઈટ",
    "nine": "नाइन|नाईन|નાઇન|નાઈન", "ten": "टेन|ટેન", "eleven": "इलेवन|ઇલેવન", "twelve": "ट्वेल्व|ટ્વેલ્વ",
    "thirteen": "थर्टीन", "fourteen": "फोर्टीन", "fifteen": "फिफ्टीन", "sixteen": "सिक्सटीन", "seventeen": "सेवनटीन",
    "eighteen": "एटीन", "nineteen": "नाइनटीन", "twenty": "ट्वेंटी|ट्वेन्टी|ટ્વેન્ટી", "thirty": "थर्टी|થર્ટી",
    "forty": "फोर्टी|फ़ोर्टी|ફોર્ટી", "fifty": "फिफ्टी|फ़िफ़्टी|ફિફ્ટી", "sixty": "सिक्सटी|सिक्स्टी|સિક્સ્ટી",
    "seventy": "सेवेंटी|सेवनटी|સેવન્ટી", "eighty": "एटी|एइटी|એટી", "ninety": "नाइंटी|नाइन्टी|નાઇન્ટી",
    "hundred": "हंड्रेड|हंडरेड|हन्ड्रेड|હન્ડ્રેડ", "thousand": "थाउजंड|थाउजेंड|थाउसंड|थाउजन्ड|થાઉઝન્ડ|થાઉઝંડ",
    "double": "डबल|ડબલ", "triple": "ट्रिपल|ટ્રિપલ",
}
_MULT = {"hundred": 100, "सौ": 100, "સો": 100, "thousand": 1000, "हजार": 1000, "હજાર": 1000}
_REPEAT = {"double": 2, "triple": 3}


def _fold(word: str) -> str:
    """One spelling per word: drop nukta, chandrabindu as anusvara (पाँच = पांच, ज़ीरो = जीरो)."""
    return word.replace("़", "").replace("઼", "").replace("ँ", "ं").replace("ઁ", "ં")


WORDS: dict[str, int | str] = {}
for _table in (_HI, _GU):
    for _n, _ws in enumerate(_table):
        WORDS.update({_fold(w): _n for w in _ws.split("|")})
WORDS.update({w: n for n, w in enumerate(_EN_UNITS)} | _EN_TENS)
for _en, _ws in _EN_SPELT.items():
    for _w in _ws.split("|"):
        WORDS[_fold(_w)] = _en
WORDS.update({k: k for k in _MULT} | {k: k for k in _REPEAT})
# Gujarati says 200-900 as one word ("ત્રણ હજાર બસો" = 3200); found by `diapason atlas` checking its own corpus
for _n, _ws in enumerate(["", "", "બસો|બેસો", "ત્રણસો", "ચારસો", "પાંચસો", "છસો", "સાતસો", "આઠસો", "નવસો"]):
    WORDS.update({_fold(w): _n * 100 for w in _ws.split("|") if w})


def word_value(tok: str) -> int | None:
    """A single number word in any script (पंद्रह, ફિફ્ટીન, फिफ्टीन, fifteen) as an int, else None."""
    v = _value(tok)
    if isinstance(v, str):
        v = int(v) if v.isdigit() else None
    return v


def _value(tok: str) -> int | str | None:
    """A token's meaning: digits as a string (keeps "0821"), a number, or a multiplier/repeat word."""
    if tok.isdigit():
        return tok
    v = WORDS.get(_fold(tok))
    if isinstance(v, str) and v not in _MULT and v not in _REPEAT:
        v = WORDS[v]                                      # "फोर" -> "four" -> 4
    return v


def _phrase(vals: list) -> str:
    """One unbroken run of number tokens, as the digits it means."""
    if any(v in _MULT for v in vals):                     # "four thousand eight hundred twenty one" = 4821
        total = cur = 0
        for v in vals:
            if v in _REPEAT:
                continue
            m = _MULT.get(v) if isinstance(v, str) and not v.isdigit() else None
            if m == 1000:
                total, cur = total + (cur or 1) * 1000, 0
            elif m == 100:
                cur = (cur or 1) * 100
            else:
                cur += int(v)
        return str(total + cur)
    out, i = [], 0
    while i < len(vals):
        v = vals[i]
        if v in _REPEAT and i + 1 < len(vals) and vals[i + 1] not in _REPEAT:
            out.append(str(vals[i + 1]) * _REPEAT[v])     # "double seven" = 77
            i += 2
            continue
        if isinstance(v, int) and v >= 20 and v % 10 == 0 and i + 1 < len(vals) and isinstance(vals[i + 1], int) \
                and 1 <= vals[i + 1] <= 9:
            out.append(str(v + vals[i + 1]))              # "forty eight" = 48
            i += 2
            continue
        if v not in _REPEAT:
            out.append(str(v))
        i += 1
    return "".join(out)


def spoken_digits(text: str) -> str:
    """Digits in the order they are said, however they were said (see the module docstring)."""
    phrases, cur = [], []
    for tok in _SPLIT.split(text.lower().translate(_DIGITS)):
        if not tok:
            continue
        v = _value(tok)
        if v is None:
            if cur:
                phrases.append(cur)
            cur = []
        else:
            cur.append(v)
    if cur:
        phrases.append(cur)
    return "".join(_phrase(p) for p in phrases)
