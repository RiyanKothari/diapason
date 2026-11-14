"""Probe Gnani's Timbre and Prisma with the inputs that break Indian voice agents, and score what comes back.

Two kinds of probe:
- round trips: Timbre speaks a sentence (an OTP with leading zeros, a date as 15/11/2026, a lakh amount, a phone number,
  an IFSC code...), Prisma transcribes it, and Diapason's own readers check whether the detail survived;
- Prisma alone on audio that should give no text (silence, noise, a tone, DTMF), and on audio it should still handle
  (clipped, 8 kHz, very short, very long, the wrong language setting).
Every request and response is saved, so each finding can be reproduced.

    .venv/Scripts/python.exe scripts/model_probe.py        # a few hundred credits at most; Timbre audio is cached
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from diapason.judge.dates import date_keys  # noqa: E402
from diapason.judge.numbers import spoken_digits  # noqa: E402

OUT = ROOT / "runs" / "model-probe"
VOICE = {"en-IN": "Kalpana", "hi-IN": "Prakash", "gu-IN": "Lakshmi", "ta-IN": "Kalpana", "hi-en": "Shivani"}

# (language, what is being tested, sentence, kind, gold): kind "digits" checks that gold appears in the digits Prisma's words
# carry; "date" that the date keys are found; "listen" is kept for a human to read (no reliable automatic check)
ROUND_TRIPS = [
    ("en-IN", "date dd/mm/yyyy", "Your due date is 15/11/2026.", "date", "d15,m11"),
    ("en-IN", "date dd-mm-yyyy", "Your due date is 15-11-2026.", "date", "d15,m11"),
    ("en-IN", "date ISO", "Your due date is 2026-11-15.", "date", "d15,m11"),
    ("en-IN", "date short month", "Please pay by 5 Nov.", "date", "d5,m11"),
    ("en-IN", "ordinal date", "Please pay by the 21st of November.", "date", "d21,m11"),
    ("en-IN", "rupee amount", "Your EMI is ₹4,500.", "digits", "4500"),
    ("en-IN", "lakh grouping", "The loan amount is ₹1,50,000.", "digits", "150000"),
    ("en-IN", "lakh in words", "The loan amount is ₹2.5 lakh.", "listen", ""),
    ("en-IN", "Rs. prefix", "You owe Rs. 3200 this month.", "digits", "3200"),
    ("en-IN", "phone number", "Call us on 9876543210.", "digits", "9876543210"),
    ("en-IN", "phone with +91", "Call us on +91 98765 43210.", "digits", "9876543210"),
    ("en-IN", "OTP with leading zeros", "Your OTP is 004821.", "digits", "004821"),
    ("en-IN", "account ending in zeros", "Your account ends in 0042.", "digits", "0042"),
    ("en-IN", "time", "Your appointment is at 10:30 AM.", "digits", "1030"),
    ("en-IN", "policy number with slash", "Your policy number is 2024/12345.", "digits", "202412345"),
    ("en-IN", "percentage", "The interest is 12.5% per annum.", "listen", ""),
    ("en-IN", "IFSC code", "Your IFSC code is SBIN0001234.", "digits", "0001234"),
    ("en-IN", "PAN", "Your PAN is ABCDE1234F.", "digits", "1234"),
    ("en-IN", "title abbreviation", "Dr. Sharma will call you at 5 pm.", "listen", ""),
    ("en-IN", "UPI ID", "Send it to ramesh@okhdfc.", "listen", ""),
    ("hi-IN", "rupee amount", "आपकी EMI ₹4,500 है।", "digits", "4500"),
    ("hi-IN", "date dd/mm/yyyy", "आखिरी तारीख 15/11/2026 है।", "date", "d15,m11"),
    ("hi-IN", "OTP with leading zeros", "आपका OTP 004821 है।", "digits", "004821"),
    ("hi-IN", "lakh grouping", "कुल राशि ₹1,50,000 है।", "digits", "150000"),
    ("hi-IN", "phone number", "मुझे 9876543210 पर कॉल करें।", "digits", "9876543210"),
    ("hi-IN", "time", "आपकी अपॉइंटमेंट 10:30 बजे है।", "digits", "1030"),
    ("gu-IN", "rupee amount", "તમારો EMI ₹3,200 છે.", "digits", "3200"),
    ("gu-IN", "date dd/mm/yyyy", "છેલ્લી તારીખ 20/11/2026 છે.", "date", "d20,m11"),
    ("gu-IN", "OTP with leading zeros", "તમારો OTP 007730 છે.", "digits", "007730"),
    ("ta-IN", "OTP with leading zeros", "உங்கள் OTP 004821.", "digits", "004821"),
    ("ta-IN", "date dd/mm/yyyy", "கடைசி தேதி 15/11/2026.", "date", "d15,m11"),
    ("hi-en", "Hinglish date and amount", "Kal 15 November ko 4500 rupees pay karna hai.", "digits", "4500"),
]

# odd inputs Timbre should either speak sensibly or refuse cleanly
ODD_TTS = [
    ("en-IN", "empty text", ""),
    ("en-IN", "whitespace only", "   "),
    ("en-IN", "symbols only", "₹₹₹ ### ***"),
    ("en-IN", "emoji", "Thank you 😀 have a nice day 🙏"),
    ("en-IN", "Hindi text with an English voice setting", "आपकी EMI 4500 रुपये है।"),
    ("en-IN", "very long text", " ".join(["Please keep your loan ID ready before you call us again."] * 22)),
]


def tone(f: float, dur: float, sr: int, amp: float = .3) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def dtmf(digits: str, sr: int) -> np.ndarray:
    rows, cols = [697, 770, 852, 941], [1209, 1336, 1477]
    keys = "123456789*0#"
    out = []
    for d in digits:
        i = keys.index(d)
        out += [tone(rows[i // 3], .18, sr, .2) + tone(cols[i % 3], .18, sr, .2), np.zeros(int(.12 * sr), np.float32)]
    return np.concatenate(out)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from diapason.gnani import Prisma, Timbre
    tts, stt = Timbre(cache_dir=ROOT / ".cache" / "tts-probe"), Prisma()
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, list] = {"round_trips": [], "odd_tts": [], "prisma": []}

    def hear(a: np.ndarray, sr: int, lang: str, long: bool = False) -> tuple[str, float, str]:
        t0 = time.time()
        try:
            r = stt.transcribe_long(a, sr, lang) if long else stt.transcribe(a, sr, lang)["transcript"]
            return (r if isinstance(r, str) else str(r)), round(time.time() - t0, 2), ""
        except Exception as e:                                          # an error is a finding too
            return "", round(time.time() - t0, 2), f"{type(e).__name__}: {str(e)[:160]}"

    print("== round trips: Timbre speaks, Prisma hears, Diapason's readers check", flush=True)
    speech = {}
    for lang, what, text, kind, gold in ROUND_TRIPS:
        try:
            a, sr = tts.synthesize(text, voice=VOICE[lang], lang=lang)
            a = np.asarray(a, np.float32)
        except Exception as e:
            results["round_trips"].append({"lang": lang, "what": what, "text": text, "tts_error": f"{type(e).__name__}: {str(e)[:160]}"})
            print(f"  TTS ERROR {lang} {what}: {e}", flush=True)
            continue
        speech.setdefault(lang, (a, sr))
        heard, secs, err = hear(a, sr, "hi-IN" if lang == "hi-en" else lang)
        ok = None
        if not err and kind == "digits":
            ok = gold in spoken_digits(heard)
        elif not err and kind == "date":
            ok = set(gold.split(",")) <= date_keys(heard)
        results["round_trips"].append({"lang": lang, "what": what, "text": text, "kind": kind, "gold": gold, "heard": heard,
                                       "survived": ok, "audio_s": round(len(a) / sr, 2), "stt_s": secs, "stt_error": err})
        mark = "ok  " if ok else ("??  " if ok is None else "LOST")
        print(f"  {mark} {lang} {what:26} | {heard[:90]}", flush=True)

    print("== odd inputs to Timbre", flush=True)
    for lang, what, text in ODD_TTS:
        t0 = time.time()
        try:
            a, sr = tts.synthesize(text, voice=VOICE[lang], lang=lang)
            a = np.asarray(a, np.float32)
            heard, _, err = hear(a, sr, lang, long=len(a) / sr > 25)
            row = {"what": what, "chars": len(text), "ok": True, "audio_s": round(len(a) / sr, 2), "peak": round(float(np.abs(a).max()) if len(a) else 0, 3),
                   "heard": heard, "stt_error": err, "tts_s": round(time.time() - t0, 2)}
        except Exception as e:
            row = {"what": what, "chars": len(text), "ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "tts_s": round(time.time() - t0, 2)}
        results["odd_tts"].append(row)
        print(f"  {what:40} -> {('audio ' + str(row.get('audio_s')) + ' s | ' + row.get('heard', '')[:70]) if row['ok'] else row['error']}", flush=True)

    print("== Prisma on its own", flush=True)
    rng = np.random.default_rng(0)
    hi, hsr = speech.get("hi-IN", (None, None))
    gu = speech.get("gu-IN", (None, None))
    cases = [
        ("silence, 16 kHz", np.zeros(48000, np.float32), 16000, "hi-IN", "empty"),
        ("silence, 8 kHz", np.zeros(24000, np.float32), 8000, "hi-IN", "empty"),
        ("white noise", (rng.standard_normal(48000) * .05).astype(np.float32), 16000, "hi-IN", "empty"),
        ("brown noise (rumble)", (np.cumsum(rng.standard_normal(48000)) / 300).astype(np.float32), 16000, "hi-IN", "empty"),
        ("1 kHz tone", tone(1000, 3, 16000), 16000, "hi-IN", "empty"),
        ("DTMF keypresses 4821", dtmf("4821", 16000), 16000, "en-IN", "empty"),
        ("50 Hz mains hum", tone(50, 3, 16000, .4), 16000, "hi-IN", "empty"),
    ]
    if hi is not None:
        r8 = np.interp(np.arange(int(len(hi) * 8000 / hsr)) * hsr / 8000, np.arange(len(hi)), hi).astype(np.float32)
        cases += [
            ("Hindi speech, clipped hard", np.clip(hi * 8, -1, 1).astype(np.float32), hsr, "hi-IN", "speech"),
            ("Hindi speech at 8 kHz", r8, 8000, "hi-IN", "speech"),
            ("Hindi speech, first 0.4 s only", hi[: int(.4 * hsr)], hsr, "hi-IN", "short"),
            ("Hindi speech, very quiet (-40 dB)", (hi * .01).astype(np.float32), hsr, "hi-IN", "speech"),
            ("Hindi speech sent as Tamil (ta-IN)", hi, hsr, "ta-IN", "wrong-lang"),
            ("Hindi speech sent as English (en-IN)", hi, hsr, "en-IN", "wrong-lang"),
            ("Hindi speech, 60 s (repeated), plain transcribe", np.tile(np.concatenate([hi, np.zeros(int(.6 * hsr), np.float32)]), 60 // max(1, int(len(hi) / hsr + .6)) + 1)[: 60 * hsr], hsr, "hi-IN", "long"),
        ]
    if gu[0] is not None:
        cases.append(("Gujarati speech sent as Hindi (hi-IN)", gu[0], gu[1], "hi-IN", "wrong-lang"))
    for what, a, sr, lang, expect in cases:
        heard, secs, err = hear(a, sr, lang)
        results["prisma"].append({"what": what, "lang": lang, "expect": expect, "audio_s": round(len(a) / sr, 2), "heard": heard, "stt_s": secs, "error": err})
        print(f"  {what:46} [{lang}] -> {('ERROR ' + err) if err else repr(heard[:90])}", flush=True)

    (OUT / "probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"TTS {tts.chars} chars in {tts.calls} calls ({tts.hits} cached); saved {OUT / 'probe.json'}")


if __name__ == "__main__":
    main()
