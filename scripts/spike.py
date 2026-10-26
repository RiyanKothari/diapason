"""Day-1 spike: measure Timbre + Prisma end to end under each telephony preset.

For each test sentence: Timbre synthesizes it -> the channel simulator degrades it ->
Prisma transcribes it -> character error rate against the source text.
Also records per-call latency and TTS characters used, for the credit budget.

Usage:  .venv/Scripts/python scripts/spike.py [--presets clean,street,...] [--out runs/spike.json]
Needs GNANI_API_KEY in .env.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
from bhool.channel import PRESETS, apply_channel  # noqa: E402
from bhool.gnani import Prisma, Timbre  # noqa: E402

SENTENCES = [
    # (tts_lang, stt_lang, voice, text)
    ("hi-en", "hi-IN", "Prakash", "मेरा EMI already pay हो गया है, आप बार बार call क्यों कर रहे हो?"),
    ("hi-IN", "hi-IN", "Shivani", "मैं पंद्रह नवंबर तक पूरा पैसा जमा कर दूंगा।"),
    ("gu-IN", "gu-IN", "Lakshmi", "મને સમજાતું નથી કે કેટલા પૈસા બાકી છે."),
    ("en-IN", "en-IN", "Avinash", "My loan ID ends with four eight two one, please check again."),
]


def normalize(s: str) -> str:
    """Lowercase, NFC, drop punctuation, collapse whitespace. Keeps Indic combining marks."""
    s = unicodedata.normalize("NFC", s.lower())
    s = "".join(ch for ch in s if ch.isalnum() or ch.isspace() or unicodedata.category(ch).startswith("M"))
    return " ".join(s.split())


def cer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / max(1, len(r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", default=",".join(PRESETS))
    ap.add_argument("--out", default="runs/spike.json")
    args = ap.parse_args()
    load_dotenv()
    tts, stt = Timbre(), Prisma()
    rows = []
    for tts_lang, stt_lang, voice, text in SENTENCES:
        t0 = time.perf_counter()
        clean, sr = tts.synthesize(text, voice=voice, lang=tts_lang)
        tts_ms = (time.perf_counter() - t0) * 1000
        for name in args.presets.split(","):
            audio, out_sr, stats = apply_channel(clean, sr, PRESETS[name], seed=0)
            t0 = time.perf_counter()
            hyp = stt.transcribe(audio, out_sr, lang=stt_lang)["transcript"]
            stt_ms = (time.perf_counter() - t0) * 1000
            row = {"lang": tts_lang, "preset": name, "cer": round(cer(text, hyp), 3),
                   "tts_ms": round(tts_ms), "stt_ms": round(stt_ms), "ref": text, "hyp": hyp, "channel": stats}
            rows.append(row)
            print(f"{tts_lang:6} {name:12} CER {row['cer']:.3f}  stt {row['stt_ms']:5d} ms  | {hyp}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"rows": rows, "tts_api_calls": tts.calls, "tts_cache_hits": tts.hits,
                                          "tts_chars": tts.chars}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTTS calls {tts.calls}, cache hits {tts.hits}, chars {tts.chars}. Saved {args.out}")


if __name__ == "__main__":
    main()
