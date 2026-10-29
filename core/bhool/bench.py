"""`bhool asr-bench`: how speech recognition holds up on Indian phone lines.

Timbre speaks sentences whose text is known -> the channel simulator degrades them per preset
-> Prisma transcribes -> character error rate (CER) against the source. The output is a
language x line grid: where recognition breaks, and how far each kind of noise pushes it.
Sentences favour what contact-centre calls hinge on: amounts, dates, IDs, code-mixing.
"""

from __future__ import annotations

import json
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from pathlib import Path

import numpy as np

from .channel import PRESETS, apply_channel

@dataclass(frozen=True)
class Sentence:
    tts_lang: str
    stt_lang: str
    voice: str
    text: str                       # what Timbre speaks
    ref: str = ""                   # expected transcript in Prisma's script convention; defaults to text
    entities: tuple[str, ...] = ()  # details that must survive exactly: amounts, dates, IDs, intent words

    @property
    def reference(self) -> str:
        return self.ref or self.text

    # Kept tuple-compatible for callers that unpack (tts_lang, stt_lang, voice, text).
    def __iter__(self):
        return iter((self.tts_lang, self.stt_lang, self.voice, self.text))


# Prisma writes English loanwords inside Hindi speech in Devanagari (EMI -> ई एम आई), so code-mixed
# references are given in that convention; scoring the Latin original would overstate error ~3x.
SENTENCES: list[Sentence] = [
    Sentence("hi-en", "hi-IN", "Prakash", "मेरा EMI already pay हो गया है, आप बार बार call क्यों कर रहे हो?",
             ref="मेरा ई एम आई ऑलरेडी पे हो गया है, आप बार बार कॉल क्यों कर रहे हो?", entities=("पे हो गया",)),
    Sentence("hi-en", "hi-IN", "Shivani", "मैं पंद्रह November तक पैंतालीस सौ रुपये pay कर दूंगी।",
             ref="मैं पंद्रह नवंबर तक पैंतालीस सौ रुपये पे कर दूंगी।", entities=("पंद्रह", "पैंतालीस सौ")),
    Sentence("hi-IN", "hi-IN", "Avinash", "मेरे loan के आखिरी चार अंक चार आठ दो एक हैं।",
             ref="मेरे लोन के आखिरी चार अंक चार आठ दो एक हैं।", entities=("चार आठ दो एक",)),
    Sentence("gu-IN", "gu-IN", "Lakshmi", "મને સમજાતું નથી કે કેટલા પૈસા બાકી છે.", entities=("બાકી",)),
    Sentence("gu-IN", "gu-IN", "Harshad", "હું વીસ તારીખે ત્રણ હજાર બસો રૂપિયા ભરી દઈશ.",
             entities=("વીસ તારીખે", "ત્રણ હજાર બસો", "ભરી દઈશ")),
    Sentence("mr-IN", "mr-IN", "Kalpana", "माझे हप्ते मी पुढच्या आठवड्यात भरेन.", entities=("पुढच्या आठवड्यात", "भरेन")),
    Sentence("ta-IN", "ta-IN", "Chetana", "என் கடன் தொகையை அடுத்த வாரம் செலுத்துகிறேன்.", entities=("அடுத்த வாரம்",)),
    Sentence("en-IN", "en-IN", "Devansh", "My loan ID ends with four eight two one, please check again.",
             entities=("four eight two one",)),
]


def entity_hits(entities: tuple[str, ...], hyp: str) -> tuple[int, list[str]]:
    """How many critical details appear verbatim (after normalisation) in the transcript, and which were lost."""
    h = f" {normalize(hyp)} "
    lost = [e for e in entities if f" {normalize(e)} " not in h]
    return len(entities) - len(lost), lost


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


def run_bench(
    speak: Callable[[str, str, str], tuple[np.ndarray, int]],
    transcribe: Callable[[np.ndarray, int, str], str],
    presets: list[str] | None = None,
    sentences: list | None = None,
    seeds: int = 1,
    on_row: Callable[[dict], None] | None = None,
) -> dict:
    presets = presets or list(PRESETS)
    rows = []
    for s in sentences or SENTENCES:
        s = s if isinstance(s, Sentence) else Sentence(*s)
        clean, sr = speak(s.text, s.voice, s.tts_lang)
        for name in presets:
            for seed in range(seeds):
                audio, out_sr, stats = apply_channel(clean, sr, PRESETS[name], seed=seed)
                t0 = time.perf_counter()
                hyp = transcribe(audio, out_sr, s.stt_lang)
                hits, lost = entity_hits(s.entities, hyp)
                row = {"lang": s.tts_lang, "stt_lang": s.stt_lang, "preset": name, "seed": seed,
                       "cer": round(cer(s.reference, hyp), 3), "entities": len(s.entities), "entity_hits": hits,
                       "entities_lost": lost, "stt_ms": round((time.perf_counter() - t0) * 1000),
                       "spoken": s.text, "ref": s.reference, "hyp": hyp, "channel": stats}
                rows.append(row)
                if on_row:
                    on_row(row)
    grid: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        grid[r["lang"]][r["preset"]].append(r["cer"])
    mean = {lang: {p: round(float(np.mean(v)), 3) for p, v in ps.items()} for lang, ps in grid.items()}
    by_preset = {p: round(float(np.mean([r["cer"] for r in rows if r["preset"] == p])), 3) for p in presets}

    def entity_rate(rs):
        total = sum(r["entities"] for r in rs)
        return round(sum(r["entity_hits"] for r in rs) / total, 3) if total else None

    entities_by_preset = {p: entity_rate([r for r in rows if r["preset"] == p]) for p in presets}
    return {"presets": presets, "grid": mean, "by_preset": by_preset, "entities_by_preset": entities_by_preset,
            "rows": rows}


def write_bench_report(result: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "asr_bench.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    def color(c: float) -> str:
        return "rgba(47,125,79,.28)" if c <= 0.1 else "rgba(168,116,26,.28)" if c <= 0.25 else "rgba(179,64,47,.30)"

    ps = result["presets"]
    head = "".join(f"<th>{escape(p)}</th>" for p in ps)
    body = "".join(
        f"<tr><th>{escape(lang)}</th>" + "".join(
            f'<td style="background:{color(row[p])}">{row[p]:.1%}</td>' if p in row else "<td></td>" for p in ps) + "</tr>"
        for lang, row in result["grid"].items())
    foot = "<tr><th>all (CER)</th>" + "".join(f"<td><b>{result['by_preset'][p]:.1%}</b></td>" for p in ps) + "</tr>"
    ent = result.get("entities_by_preset", {})
    foot += "<tr><th>details kept</th>" + "".join(
        f"<td><b>{ent[p]:.0%}</b></td>" if ent.get(p) is not None else "<td>—</td>" for p in ps) + "</tr>"
    worst = sorted(result["rows"], key=lambda r: (-len(r.get("entities_lost", [])), -r["cer"]))[:8]
    worst_html = "".join(f"<tr><td>{escape(r['lang'])}</td><td>{escape(r['preset'])}</td><td>{r['cer']:.0%}</td>"
                         f"<td>{escape(', '.join(r.get('entities_lost', [])) or '—')}</td>"
                         f"<td>{escape(r['ref'])}</td><td>{escape(r['hyp'])}</td></tr>" for r in worst)
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASR stress bench</title><style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--line:#e6e3dc;--muted:#6b6a65}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe6;--line:#33322e;--muted:#9b9a94}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1000px;margin:0 auto;padding:24px 16px}}
table{{border-collapse:collapse;width:100%;margin:12px 0}}th,td{{border-bottom:1px solid var(--line);padding:7px 9px;text-align:left}}
.scroll{{overflow-x:auto}}p{{color:var(--muted)}}</style></head><body><main>
<h1>Speech recognition under Indian phone conditions</h1>
<p>Character error rate (lower is better) of Prisma on Timbre speech with known text, after each telephony preset.</p>
<div class="scroll"><table><tr><th>language</th>{head}</tr>{body}{foot}</table></div>
<p>"Details kept" is the share of critical details (amounts, dates, IDs, intent words such as "will pay") that survive exactly: what a contact centre actually depends on.</p>
<h2>Hardest cases</h2><div class="scroll"><table><tr><th>lang</th><th>line</th><th>CER</th><th>details lost</th><th>expected</th><th>heard</th></tr>{worst_html}</table></div>
</main></body></html>"""
    path = out / "asr_bench.html"
    path.write_text(html, encoding="utf-8")
    return path
