"""What Prisma writes when an Indian caller says an ID, an amount or a date in a new language, and whether the readers get it.

Before teaching the digit and date readers a language, measure what they will actually be given: each sentence is spoken
by Timbre, transcribed by Prisma in the same language (clean line), then read back by `spoken_digits` and `date_keys`.

    .venv/Scripts/python.exe scripts/lang_probe.py                  # ~3 Gnani credits: 28 short sentences, TTS + STT
    .venv/Scripts/python.exe scripts/lang_probe.py --reread         # re-read the saved transcripts with today's readers
    .venv/Scripts/python.exe scripts/lang_probe.py --held-out       # ~3 credits: new numbers, dates and voice, never
                                                                    # seen while the readers were written
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from diapason.judge.dates import date_keys  # noqa: E402
from diapason.judge.numbers import spoken_digits  # noqa: E402

OUT = ROOT / "runs/lang-probe/probe.json"
# (language, kind, style, sentence, gold): gold is digits, or comma-joined date keys
ROWS = [
    ("ta-IN", "id", "numerals", "என் கடனின் கடைசி நான்கு இலக்கங்கள் 4821.", "4821"),
    ("ta-IN", "id", "digit words", "என் கடனின் கடைசி நான்கு இலக்கங்கள் நான்கு எட்டு இரண்டு ஒன்று.", "4821"),
    ("ta-IN", "id", "English digit words", "என் கடனின் கடைசி நான்கு இலக்கங்கள் four eight two one.", "4821"),
    ("ta-IN", "amount", "numerals", "உங்களுக்கு 4500 ரூபாய் நிலுவையில் உள்ளது.", "4500"),
    ("ta-IN", "amount", "words", "உங்களுக்கு நான்காயிரத்து ஐநூறு ரூபாய் நிலுவையில் உள்ளது.", "4500"),
    ("ta-IN", "date", "numerals + month", "நான் 15 நவம்பர் அன்று பணம் செலுத்துவேன்.", "d15,m11"),
    ("ta-IN", "date", "words + month", "நான் பதினைந்து நவம்பர் அன்று பணம் செலுத்துவேன்.", "d15,m11"),
    ("mr-IN", "id", "numerals", "माझ्या कर्जाचे शेवटचे चार अंक 4821 आहेत.", "4821"),
    ("mr-IN", "id", "digit words", "माझ्या कर्जाचे शेवटचे चार अंक चार आठ दोन एक आहेत.", "4821"),
    ("mr-IN", "id", "English digit words", "माझ्या कर्जाचे शेवटचे चार अंक four eight two one आहेत.", "4821"),
    ("mr-IN", "amount", "numerals", "तुमचे 4500 रुपये बाकी आहेत.", "4500"),
    ("mr-IN", "amount", "words", "तुमचे चार हजार पाचशे रुपये बाकी आहेत.", "4500"),
    ("mr-IN", "date", "numerals + month", "मी 15 नोव्हेंबरला पैसे भरीन.", "d15,m11"),
    ("mr-IN", "date", "words + month", "मी पंधरा नोव्हेंबरला पैसे भरीन.", "d15,m11"),
    ("te-IN", "id", "numerals", "నా లోన్ చివరి నాలుగు అంకెలు 4821.", "4821"),
    ("te-IN", "id", "digit words", "నా లోన్ చివరి నాలుగు అంకెలు నాలుగు ఎనిమిది రెండు ఒకటి.", "4821"),
    ("te-IN", "id", "English digit words", "నా లోన్ చివరి నాలుగు అంకెలు four eight two one.", "4821"),
    ("te-IN", "amount", "numerals", "మీకు 4500 రూపాయలు బాకీ ఉంది.", "4500"),
    ("te-IN", "amount", "words", "మీకు నాలుగు వేల ఐదు వందల రూపాయలు బాకీ ఉంది.", "4500"),
    ("te-IN", "date", "numerals + month", "నేను 15 నవంబర్ న చెల్లిస్తాను.", "d15,m11"),
    ("te-IN", "date", "words + month", "నేను పదిహేను నవంబర్ న చెల్లిస్తాను.", "d15,m11"),
    ("kn-IN", "id", "numerals", "ನನ್ನ ಸಾಲದ ಕೊನೆಯ ನಾಲ್ಕು ಅಂಕೆಗಳು 4821.", "4821"),
    ("kn-IN", "id", "digit words", "ನನ್ನ ಸಾಲದ ಕೊನೆಯ ನಾಲ್ಕು ಅಂಕೆಗಳು ನಾಲ್ಕು ಎಂಟು ಎರಡು ಒಂದು.", "4821"),
    ("kn-IN", "id", "English digit words", "ನನ್ನ ಸಾಲದ ಕೊನೆಯ ನಾಲ್ಕು ಅಂಕೆಗಳು four eight two one.", "4821"),
    ("kn-IN", "amount", "numerals", "ನಿಮಗೆ 4500 ರೂಪಾಯಿ ಬಾಕಿ ಇದೆ.", "4500"),
    ("kn-IN", "amount", "words", "ನಿಮಗೆ ನಾಲ್ಕು ಸಾವಿರದ ಐನೂರು ರೂಪಾಯಿ ಬಾಕಿ ಇದೆ.", "4500"),
    ("kn-IN", "date", "numerals + month", "ನಾನು 15 ನವೆಂಬರ್ ರಂದು ಪಾವತಿಸುತ್ತೇನೆ.", "d15,m11"),
    ("kn-IN", "date", "words + month", "ನಾನು ಹದಿನೈದು ನವೆಂಬರ್ ರಂದು ಪಾವತಿಸುತ್ತೇನೆ.", "d15,m11"),
]


# Written after the readers were, with other numbers, dates and a male voice: the readers' test, not their source.
HELD_OUT = [
    ("ta-IN", "id", "numerals", "என் கணக்கு எண்ணின் கடைசி நான்கு இலக்கங்கள் 5519.", "5519"),
    ("ta-IN", "id", "digit words", "கடைசி நான்கு இலக்கங்கள் ஏழு ஏழு மூன்று பூஜ்ஜியம்.", "7730"),
    ("ta-IN", "amount", "numerals", "நிலுவைத் தொகை 6100 ரூபாய்.", "6100"),
    ("ta-IN", "amount", "words", "நிலுவைத் தொகை மூவாயிரத்து இருநூறு ரூபாய்.", "3200"),
    ("ta-IN", "date", "numerals + month", "நான் 5 டிசம்பர் அன்று கட்டுவேன்.", "d5,m12"),
    ("ta-IN", "date", "words + month", "நான் இருபது நவம்பர் அன்று கட்டுவேன்.", "d20,m11"),
    ("mr-IN", "id", "numerals", "माझ्या खात्याचे शेवटचे चार अंक 5519 आहेत.", "5519"),
    ("mr-IN", "id", "digit words", "शेवटचे चार अंक सात सात तीन शून्य आहेत.", "7730"),
    ("mr-IN", "amount", "numerals", "तुमची थकबाकी 6100 रुपये आहे.", "6100"),
    ("mr-IN", "amount", "words", "तुमची थकबाकी तीन हजार दोनशे रुपये आहे.", "3200"),
    ("mr-IN", "date", "numerals + month", "मी 5 डिसेंबरला पैसे भरीन.", "d5,m12"),
    ("mr-IN", "date", "words + month", "मी वीस नोव्हेंबरला पैसे भरीन.", "d20,m11"),
    ("te-IN", "id", "numerals", "నా ఖాతా చివరి నాలుగు అంకెలు 5519.", "5519"),
    ("te-IN", "id", "digit words", "చివరి నాలుగు అంకెలు ఏడు ఏడు మూడు సున్నా.", "7730"),
    ("te-IN", "amount", "numerals", "మీ బకాయి 6100 రూపాయలు.", "6100"),
    ("te-IN", "amount", "words", "మీ బకాయి మూడు వేల రెండు వందల రూపాయలు.", "3200"),
    ("te-IN", "date", "numerals + month", "నేను 5 డిసెంబర్ న చెల్లిస్తాను.", "d5,m12"),
    ("te-IN", "date", "words + month", "నేను ఇరవై నవంబర్ న చెల్లిస్తాను.", "d20,m11"),
    ("kn-IN", "id", "numerals", "ನನ್ನ ಖಾತೆಯ ಕೊನೆಯ ನಾಲ್ಕು ಅಂಕೆಗಳು 5519.", "5519"),
    ("kn-IN", "id", "digit words", "ಕೊನೆಯ ನಾಲ್ಕು ಅಂಕೆಗಳು ಏಳು ಏಳು ಮೂರು ಸೊನ್ನೆ.", "7730"),
    ("kn-IN", "amount", "numerals", "ನಿಮ್ಮ ಬಾಕಿ 6100 ರೂಪಾಯಿ.", "6100"),
    ("kn-IN", "amount", "words", "ನಿಮ್ಮ ಬಾಕಿ ಮೂರು ಸಾವಿರದ ಇನ್ನೂರು ರೂಪಾಯಿ.", "3200"),
    ("kn-IN", "date", "numerals + month", "ನಾನು 5 ಡಿಸೆಂಬರ್ ರಂದು ಪಾವತಿಸುತ್ತೇನೆ.", "d5,m12"),
    ("kn-IN", "date", "words + month", "ನಾನು ಇಪ್ಪತ್ತು ನವೆಂಬರ್ ರಂದು ಪಾವತಿಸುತ್ತೇನೆ.", "d20,m11"),
]


def read(kind: str, gold: str, text: str) -> bool:
    return set(gold.split(",")) <= date_keys(text) if kind == "date" else gold in spoken_digits(text)


def report(rows: list[dict]) -> None:
    for r in rows:
        r["read_sentence"], r["read_heard"] = read(r["kind"], r["gold"], r["sentence"]), read(r["kind"], r["gold"], r["heard"])
        print(f"{r['lang']} {r['kind']:6} {r['style']:20} read {'ok ' if r['read_heard'] else 'NO '}| heard: {r['heard']}")
    for lang in sorted({r["lang"] for r in rows}):
        rs = [r for r in rows if r["lang"] == lang]
        print(f"{lang}: readers get {sum(r['read_heard'] for r in rs)}/{len(rs)} of what Prisma wrote")


def main(rows_in=ROWS, voice="Kalpana", out=OUT) -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from diapason.gnani import Prisma, Timbre
    tts, stt = Timbre(), Prisma()
    rows = []
    for lang, kind, style, sentence, gold in rows_in:
        audio, sr = tts.synthesize(sentence, voice=voice, lang=lang)
        rows.append({"lang": lang, "kind": kind, "style": style, "sentence": sentence, "gold": gold,
                     "heard": stt.transcribe(audio, sr, lang)["transcript"]})
    out.parent.mkdir(parents=True, exist_ok=True)
    report(rows)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"TTS {tts.chars} chars in {tts.calls} calls (cache hits {tts.hits}); saved {out}")


if __name__ == "__main__":
    held = ROOT / "runs/lang-probe/heldout.json"
    if "--reread" in sys.argv:
        for f in (OUT, held):
            if f.exists():
                rows = json.loads(f.read_text(encoding="utf-8"))
                print(f"== {f.name}")
                report(rows)
                f.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    elif "--held-out" in sys.argv:
        main(HELD_OUT, voice="Prakash", out=held)
    else:
        main()
