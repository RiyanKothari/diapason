"""Numbers, months and date words in Marathi, Tamil, Telugu and Kannada, for the digit and date readers.

Measured before written (scripts/lang_probe.py, 4 Nov, Timbre -> Prisma on a clean line): of 28 IDs, amounts and dates
said in these four languages, the Hindi/Gujarati/English readers got 1. What Prisma writes:

- never numerals: "4821" comes back spelled out, as one number ("நான்கு ஆயிரத்தி எண்ணூற்றி இருபத்தொன்று",
  "ನಾಲ್ಕು ಸಾವಿರದ ಎಂಟುನೂರ ಇಪ್ಪತ್ತೊಂದು", "నాలుగు వేల ఎనిమిది వందల ఇరవై ఒకటి", "चार हजार आठ शे एकवीस");
- English digit words in the language's script: "ஃபோர் எய்ட் டூ ஒன்", "ఫోర్ ఎయిట్ టూ వన్", "ಫೋರ್ ಏಟ್ ಟು ಒನ್";
- Tamil and Kannada join tens and units into one word (இருபத்தொன்று = 21, ಇಪ್ಪತ್ತೊಂದು = 21) and thousands too
  (நான்காயிரத்தி = 4000): those forms are generated here by the vowel-merge rule, not typed out one by one;
- month names with a case ending fused on: "नोव्हेंबरला", "ನವೆಂಬರಂದು".

Left out on purpose: Marathi 13 "तेरा" (in a Hindi transcript it is "your") and Marathi May "मे" (Prisma writes Hindi
"में", "in", as "मे"). Ordinal day forms (பதினைந்தாம், ಹದಿನೈದನೇ) are not read yet.
"""

from __future__ import annotations

# ------------------------------------------------------------------ Marathi (Devanagari, its own words)
MR = ["शून्य", "एक", "दोन", "तीन", "चार", "पाच", "सहा", "सात", "आठ", "नऊ", "दहा", "अकरा", "बारा", "", "चौदा", "पंधरा",
      "सोळा|सोळ", "सतरा", "अठरा", "एकोणीस|एकोणिस", "वीस", "एकवीस", "बावीस", "तेवीस", "चोवीस|चौवीस", "पंचवीस", "सव्वीस",
      "सत्तावीस", "अठ्ठावीस|अठ्ठाविस", "एकोणतीस", "तीस", "एकतीस", "बत्तीस", "तेहेतीस|तेहतीस", "चौतीस|चौत्तीस", "पस्तीस",
      "छत्तीस", "सदतीस", "अडतीस", "एकोणचाळीस", "चाळीस", "एक्केचाळीस|एकेचाळीस", "बेचाळीस", "त्रेचाळीस", "चव्वेचाळीस",
      "पंचेचाळीस", "सेहेचाळीस|सेहचाळीस", "सत्तेचाळीस", "अठ्ठेचाळीस", "एकोणपन्नास", "पन्नास", "एक्कावन्न|एक्कावन",
      "बावन्न", "त्रेपन्न", "चोपन्न", "पंचावन्न", "छप्पन्न", "सत्तावन्न", "अठ्ठावन्न", "एकोणसाठ", "साठ", "एकसष्ट",
      "बासष्ट", "त्रेसष्ट", "चौसष्ट", "पासष्ट", "सहासष्ट", "सदुसष्ट", "अडुसष्ट", "एकोणसत्तर", "सत्तर", "एकाहत्तर",
      "बाहत्तर", "त्र्याहत्तर", "चौर्‍याहत्तर|चौऱ्याहत्तर", "पंचाहत्तर", "शहात्तर", "सत्याहत्तर", "अठ्ठ्याहत्तर",
      "एकोणऐंशी", "ऐंशी", "एक्क्याऐंशी", "ब्याऐंशी", "त्र्याऐंशी", "चौऱ्याऐंशी", "पंच्याऐंशी", "शहाऐंशी", "सत्त्याऐंशी",
      "अठ्ठ्याऐंशी", "एकोणनव्वद", "नव्वद", "एक्क्याण्णव", "ब्याण्णव", "त्र्याण्णव", "चौऱ्याण्णव", "पंच्याण्णव",
      "शहाण्णव", "सत्त्याण्णव", "अठ्ठ्याण्णव", "नव्व्याण्णव"]
MR_HUNDREDS = {"शंभर": 100, "दोनशे": 200, "तीनशे": 300, "चारशे": 400, "पाचशे": 500, "सहाशे": 600, "सातशे": 700,
               "आठशे": 800, "नऊशे": 900}
MR_MULT = {"शे": 100}

# ------------------------------------------------------------------ Tamil
_TA_SIGN = {"அ": "", "ஆ": "ா", "இ": "ி", "ஈ": "ீ", "உ": "ு", "ஊ": "ூ", "எ": "ெ", "ஏ": "ே", "ஐ": "ை", "ஒ": "ொ", "ஓ": "ோ"}
TA_UNITS = {0: "பூஜ்ஜியம்|பூஜ்யம்|சைபர்|ஜீரோ", 1: "ஒன்று|ஒண்ணு", 2: "இரண்டு|ரெண்டு", 3: "மூன்று|மூணு", 4: "நான்கு|நாலு",
            5: "ஐந்து|அஞ்சு", 6: "ஆறு", 7: "ஏழு", 8: "எட்டு", 9: "ஒன்பது|ஒம்பது"}
TA_TEENS = {10: "பத்து", 11: "பதினொன்று|பதினொண்ணு", 12: "பன்னிரண்டு|பன்னெண்டு", 13: "பதின்மூன்று|பதிமூன்று|பதிமூணு",
            14: "பதினான்கு|பதினாலு", 15: "பதினைந்து|பதினஞ்சு", 16: "பதினாறு", 17: "பதினேழு", 18: "பதினெட்டு",
            19: "பத்தொன்பது"}
TA_TENS = {20: ("இருபது", "இருபத்"), 30: ("முப்பது", "முப்பத்"), 40: ("நாற்பது", "நாற்பத்"), 50: ("ஐம்பது", "ஐம்பத்"),
           60: ("அறுபது", "அறுபத்"), 70: ("எழுபது", "எழுபத்"), 80: ("எண்பது", "எண்பத்"), 90: ("தொண்ணூறு", "தொண்ணூற்")}
TA_HUNDREDS = {100: "நூறு", 200: "இருநூறு", 300: "முந்நூறு|முன்னூறு", 400: "நானூறு|நாநூறு", 500: "ஐநூறு", 600: "அறுநூறு",
               700: "எழுநூறு", 800: "எண்ணூறு"}
TA_THOUSAND_STEMS = {1: "ஓர்", 2: "இரண்ட்", 3: "மூவ்|மூன்ற்", 4: "நால்|நான்க்", 5: "ஐய்|ஐந்த்", 6: "ஆற்", 7: "ஏழ்",
                     8: "எட்ட்", 9: "ஒன்பத்", 10: "பத்த்"}
TA_MULT = {"ஆயிரம்": 1000, "ஆயிரத்து": 1000, "ஆயிரத்தி": 1000, "ஆயிரத்தை": 1000}

# ------------------------------------------------------------------ Kannada
_KN_SIGN = {"ಅ": "", "ಆ": "ಾ", "ಇ": "ಿ", "ಈ": "ೀ", "ಉ": "ು", "ಊ": "ೂ", "ಎ": "ೆ", "ಏ": "ೇ", "ಐ": "ೈ", "ಒ": "ೊ", "ಓ": "ೋ"}
KN_UNITS = {0: "ಸೊನ್ನೆ|ಶೂನ್ಯ|ಜೀರೋ", 1: "ಒಂದು", 2: "ಎರಡು", 3: "ಮೂರು", 4: "ನಾಲ್ಕು", 5: "ಐದು", 6: "ಆರು", 7: "ಏಳು",
            8: "ಎಂಟು", 9: "ಒಂಬತ್ತು"}
KN_TEENS = {10: "ಹತ್ತು", 11: "ಹನ್ನೊಂದು", 12: "ಹನ್ನೆರಡು", 13: "ಹದಿಮೂರು", 14: "ಹದಿನಾಲ್ಕು", 15: "ಹದಿನೈದು", 16: "ಹದಿನಾರು",
            17: "ಹದಿನೇಳು", 18: "ಹದಿನೆಂಟು", 19: "ಹತ್ತೊಂಬತ್ತು"}
KN_TENS = {20: ("ಇಪ್ಪತ್ತು", "ಇಪ್ಪತ್ತ್"), 30: ("ಮೂವತ್ತು", "ಮೂವತ್ತ್"), 40: ("ನಲವತ್ತು", "ನಲವತ್ತ್"), 50: ("ಐವತ್ತು", "ಐವತ್ತ್"),
           60: ("ಅರವತ್ತು", "ಅರವತ್ತ್"), 70: ("ಎಪ್ಪತ್ತು", "ಎಪ್ಪತ್ತ್"), 80: ("ಎಂಬತ್ತು", "ಎಂಬತ್ತ್"), 90: ("ತೊಂಬತ್ತು", "ತೊಂಬತ್ತ್")}
KN_HUNDREDS = {100: "ನೂರು", 200: "ಇನ್ನೂರು", 300: "ಮುನ್ನೂರು", 400: "ನಾನೂರು|ನಾನ್ನೂರು|ನಾಲ್ಕುನೂರು", 500: "ಐನೂರು",
               600: "ಆರುನೂರು|ಆರ್ನೂರು", 700: "ಏಳುನೂರು", 800: "ಎಂಟುನೂರು", 900: "ಒಂಬೈನೂರು|ಒಂಬತ್ತುನೂರು"}
KN_MULT = {"ಸಾವಿರ": 1000, "ಸಾವಿರದ": 1000, "ಸಾವಿರದಾ": 1000, "ಸಾವಿರಾ": 1000}

# ------------------------------------------------------------------ Telugu (tens and units are written apart)
TE_WORDS = {0: "సున్నా|జీరో", 1: "ఒకటి|ఒక", 2: "రెండు", 3: "మూడు", 4: "నాలుగు", 5: "ఐదు", 6: "ఆరు", 7: "ఏడు",
            8: "ఎనిమిది", 9: "తొమ్మిది", 10: "పది", 11: "పదకొండు", 12: "పన్నెండు", 13: "పదమూడు", 14: "పద్నాలుగు|పధ్నాలుగు",
            15: "పదిహేను|పదేను", 16: "పదహారు|పదారు", 17: "పదిహేడు|పదేడు", 18: "పద్దెనిమిది|పద్ధెనిమిది", 19: "పందొమ్మిది|పంతొమ్మిది",
            20: "ఇరవై", 30: "ముప్పై|ముప్ఫై", 40: "నలభై|నలబై", 50: "యాభై|యాబై", 60: "అరవై", 70: "డెబ్బై", 80: "ఎనభై|ఎనబై",
            90: "తొంభై|తొంబై"}
TE_MULT = {"వంద": 100, "వందల": 100, "వందలు": 100, "నూరు": 100, "నూట": 100, "వెయ్యి": 1000, "వేల": 1000, "వేలు": 1000}

# English number words as Prisma writes them in these scripts (Marathi's are Hindi's Devanagari spellings)
EN_SPELT = {
    "zero": "ஜீரோ|జీరో|ಜೀರೋ", "one": "ஒன்|వన్|ಒನ್|ವನ್", "two": "டூ|టూ|ಟು|ಟೂ", "three": "த்ரீ|త్రీ|ತ್ರೀ",
    "four": "ஃபோர்|ఫోర్|ಫೋರ್", "five": "ஃபைவ்|ఫైవ్|ಫೈವ್", "six": "சிக்ஸ்|సిక్స్|ಸಿಕ್ಸ್", "seven": "செவன்|సెవెన్|ಸೆವೆನ್",
    "eight": "எய்ட்|எயிட்|ఎయిట్|ಏಟ್|ಎಯ್ಟ್", "nine": "நைன்|నైన్|ನೈನ್", "ten": "டென்|టెన్|ಟೆನ್",
    "double": "டபுள்|డబుల్|ಡಬಲ್", "triple": "ட்ரிபிள்|ట్రిపుల్|ಟ್ರಿಪಲ್",
}

# native digits, all scripts Prisma transcribes
DIGIT_CHARS = ("०१२३४५६७८९", "૦૧૨૩૪૫૬૭૮૯", "௦௧௨௩௪௫௬௭௮௯", "౦౧౨౩౪౫౬౭౮౯", "೦೧೨೩೪೫೬೭೮೯", "০১২৩৪৫৬৭৮৯",
               "੦੧੨੩੪੫੬੭੮੯", "൦൧൨൩൪൫൬൭൮൯")
DIGITS = str.maketrans("".join(DIGIT_CHARS), "0123456789" * len(DIGIT_CHARS))


def _merge(stem: str, word: str, signs: dict[str, str]) -> str:
    """Join a consonant-final stem and a word: a leading vowel becomes its sign (இருபத் + ஒன்று = இருபத்தொன்று)."""
    if stem.endswith(("்", "್")) and word and word[0] in signs:
        return stem[:-1] + signs[word[0]] + word[1:]
    return stem + word


def _alts(spec: str) -> list[str]:
    return [w for w in spec.split("|") if w]


def number_words() -> tuple[dict[str, int], dict[str, int]]:
    """(word -> value, multiplier word -> 100 or 1000) for the four languages, generated forms included."""
    words: dict[str, int] = {}
    for n, spec in enumerate(MR):
        words.update({w: n for w in _alts(spec)})
    words.update(MR_HUNDREDS)
    # Tamil
    for table in (TA_UNITS, TA_TEENS):
        for n, spec in table.items():
            words.update({w: n for w in _alts(spec)})
    for t, (word, stem) in TA_TENS.items():
        link = stem + stem[-2] + "ு"                          # இருபத்து: the tens word before a consonant
        words.update({word: t, link: t, stem + stem[-2] + "ி": t})
        for u in range(1, 10):
            for uw in _alts(TA_UNITS[u]):
                words[_merge(stem + stem[-2] + "்", uw, _TA_SIGN)] = t + u   # doubled before a vowel: இருபத்தொன்று
                words[link + uw] = t + u
                words[stem + stem[-2] + "ி" + uw] = t + u
    for h, spec in TA_HUNDREDS.items():
        for w in _alts(spec):                                 # எண்ணூறு, and before more: எண்ணூற்றி, எண்ணூற்று
            words.update({w: h, w[:-2] + "ற்றி": h, w[:-2] + "ற்று": h})
    words.update({"தொள்ளாயிரம்": 900, "தொள்ளாயிரத்து": 900, "தொள்ளாயிரத்தி": 900})
    for n, spec in TA_THOUSAND_STEMS.items():                 # நான்காயிரம், நான்காயிரத்தி = 4000
        for stem in _alts(spec):
            base = _merge(stem, "ஆயிரம்", _TA_SIGN)
            words.update({base: n * 1000, base[:-2] + "த்து": n * 1000, base[:-2] + "த்தி": n * 1000})
    # Kannada
    for table in (KN_UNITS, KN_TEENS):
        for n, spec in table.items():
            words.update({w: n for w in _alts(spec)})
    for t, (word, stem) in KN_TENS.items():
        words[word] = t
        for u in range(1, 10):
            for uw in _alts(KN_UNITS[u]):
                words[_merge(stem, uw, _KN_SIGN)] = t + u      # ಇಪ್ಪತ್ತೊಂದು
                if uw[0] not in _KN_SIGN:
                    words[stem[:-2] + uw] = t + u              # ಇಪ್ಪತ್ಮೂರು
    for h, spec in KN_HUNDREDS.items():
        for w in _alts(spec):                                 # ಎಂಟುನೂರು, and before more: ಎಂಟುನೂರ, ನೂರಾ, ನೂರ್
            words.update({w: h, w[:-1]: h, w[:-1] + "ಾ": h, w[:-1] + "್": h})
    # Telugu
    for n, spec in TE_WORDS.items():
        words.update({w: n for w in _alts(spec)})
    for t in range(20, 100, 10):                              # ఇరవైఒకటి, if Prisma ever joins them
        for tw in _alts(TE_WORDS[t]):
            for u in range(1, 10):
                words.update({tw + uw: t + u for uw in _alts(TE_WORDS[u])})
    return words, MR_MULT | TA_MULT | KN_MULT | TE_MULT


MONTHS = {
    1: "जानेवारी|ஜனவரி|జనవరి|ಜನವರಿ", 2: "फेब्रुवारी|பிப்ரவரி|ఫిబ్రవరి|ಫೆಬ್ರವರಿ", 3: "மார்ச்|మార్చి|ಮಾರ್ಚ್",
    4: "एप्रिल|ஏப்ரல்|ఏప్రిల్|ಏಪ್ರಿಲ್", 5: "மே|మే|ಮೇ", 6: "ஜூன்|జూన్|ಜೂನ್", 7: "जुलै|ஜூலை|జూలై|ಜುಲೈ",
    8: "ऑगस्ट|ஆகஸ்ட்|ఆగస్టు|ఆగస్ట్|ಆಗಸ್ಟ್", 9: "सप्टेंबर|செப்டம்பர்|సెప్టెంబర్|ಸೆಪ್ಟೆಂಬರ್",
    10: "ऑक्टोबर|அக்டோபர்|అక్టోబర్|ಅಕ್ಟೋಬರ್", 11: "नोव्हेंबर|நவம்பர்|నవంబర్|ನವೆಂಬರ್",
    12: "डिसेंबर|டிசம்பர்|డిసెంబర్|ಡಿಸೆಂಬರ್",
}


def month_names() -> dict[int, list[str]]:
    """Each name, and the name without its final virama: Prisma fuses case endings on (ನವೆಂಬರ್ + ಅಂದು = ನವೆಂಬರಂದು)."""
    out: dict[int, list[str]] = {}
    for m, spec in MONTHS.items():
        names = _alts(spec)
        out[m] = names + [n[:-1] for n in names if n.endswith(("्", "்", "్", "್"))]
    return out


DATE_MARKERS = ["तारीख", "तारखेला", "தேதி", "తేదీ", "ದಿನಾಂಕ", "ತಾರೀಖು"]
RELATIVE = {"today": ["இன்று", "இன்னைக்கு", "ఈరోజు", "నేడు", "ಇವತ್ತು", "ಇಂದು"],
            "tomorrow": ["उद्या", "நாளை", "நாளைக்கு", "రేపు", "ನಾಳೆ"],
            "day_after": ["परवा", "நாளன்னைக்கு", "ఎల్లుండి", "ನಾಡಿದ್ದು"]}
