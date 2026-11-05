"""`diapason atlas`: which details survive an Indian phone line, and how an agent should say them.

A collections or support call hinges on three details: an ID ("last four digits 4821"), an amount and a date. Each is
written several ways (numerals, digit words, pairs, one number, English words inside Hindi), spoken by Timbre in several
voices, pushed through the channel simulator at every noise type from 30 dB down to 0 dB, transcribed by Prisma, and read
back by the same parsers the judge and the agents use. A detail *survives* when the parsed transcript still holds it.

The answer is a map with two uses:
- **for an agent builder**: the phrasing to put in an agent's mouth (and to expect from callers) in each language;
- **for the agent itself**: the line quality below which a detail must be read back before it is acted on.

Measured, not assumed: everything comes from real Timbre audio and real Prisma transcripts.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import escape
from pathlib import Path

import numpy as np

from .channel import PRESETS, ChannelProfile, apply_channel
from .judge.dates import date_keys
from .judge.numbers import spoken_digits

NOISES = ("office", "fan", "traffic", "crowd")
SNRS = (30, 20, 15, 10, 5, 0)


@dataclass(frozen=True)
class Item:
    lang: str          # language label: hi, gu, en
    tts_lang: str
    stt_lang: str
    kind: str          # id | amount | date
    style: str         # how the detail is written for Timbre
    text: str
    gold: str          # digits for id/amount; comma-joined date keys for date

    def survives(self, hyp: str) -> bool:
        if self.kind == "date":
            return set(self.gold.split(",")) <= date_keys(hyp)
        return self.gold in spoken_digits(hyp)


def _items() -> list[Item]:
    hi, gu, en = ("hi", "hi-en", "hi-IN"), ("gu", "gu-IN", "gu-IN"), ("en", "en-IN", "en-IN")
    rows = [
        (hi, "id", "numerals", "मेरे loan के last four digits 4821 हैं।", "4821"),
        (hi, "id", "spaced numerals", "मेरे loan के last four digits 4 8 2 1 हैं।", "4821"),
        (hi, "id", "digit words", "मेरे loan के last four digits चार आठ दो एक हैं।", "4821"),
        (hi, "id", "pairs", "मेरे loan के last four digits अड़तालीस इक्कीस हैं।", "4821"),
        (hi, "id", "English digit words", "मेरे loan के last four digits four eight two one हैं।", "4821"),
        (hi, "amount", "numerals", "आपके 4500 रुपये बाकी हैं।", "4500"),
        (hi, "amount", "rupee sign", "आपके ₹4,500 बाकी हैं।", "4500"),
        (hi, "amount", "hundreds", "आपके पैंतालीस सौ रुपये बाकी हैं।", "4500"),
        (hi, "amount", "thousands", "आपके चार हज़ार पाँच सौ रुपये बाकी हैं।", "4500"),
        (hi, "date", "numerals + month", "मैं 15 November को pay कर दूँगा।", "d15,m11"),
        (hi, "date", "words + month", "मैं पंद्रह नवंबर को pay कर दूँगा।", "d15,m11"),
        (hi, "date", "ordinal (English)", "मैं fifteenth November को pay कर दूँगा।", "d15,m11"),
        (hi, "date", "day/month numerals", "मैं 15/11 को pay कर दूँगा।", "d15,m11"),
        (gu, "id", "numerals", "મારા લોનના છેલ્લા ચાર આંકડા 7730 છે.", "7730"),
        (gu, "id", "digit words", "મારા લોનના છેલ્લા ચાર આંકડા સાત સાત ત્રણ શૂન્ય છે.", "7730"),
        (gu, "id", "pairs", "મારા લોનના છેલ્લા ચાર આંકડા સિત્યોતેર ત્રીસ છે.", "7730"),
        (gu, "id", "double", "મારા લોનના છેલ્લા ચાર આંકડા ડબલ સાત ત્રણ શૂન્ય છે.", "7730"),
        (gu, "amount", "numerals", "તમારા 3200 રૂપિયા બાકી છે.", "3200"),
        (gu, "amount", "thousands", "તમારા ત્રણ હજાર બસો રૂપિયા બાકી છે.", "3200"),
        (gu, "amount", "hundreds", "તમારા બત્રીસ સો રૂપિયા બાકી છે.", "3200"),
        (gu, "date", "numerals + month", "હું 20 નવેમ્બરે પૈસા ભરી દઈશ.", "d20,m11"),
        (gu, "date", "words + month", "હું વીસ નવેમ્બરે પૈસા ભરી દઈશ.", "d20,m11"),
        (gu, "date", "day only (તારીખ)", "હું વીસ તારીખે પૈસા ભરી દઈશ.", "d20"),
        (en, "id", "numerals", "The last four digits of my loan are 4821.", "4821"),
        (en, "id", "digit words", "The last four digits of my loan are four eight two one.", "4821"),
        (en, "id", "pairs", "The last four digits of my loan are forty-eight twenty-one.", "4821"),
        (en, "id", "double", "The last four digits of my loan are double seven three zero.", "7730"),
        (en, "amount", "numerals", "You have 4500 rupees due.", "4500"),
        (en, "amount", "rupee sign", "You have Rs. 4,500 due.", "4500"),
        (en, "amount", "thousands", "You have four thousand five hundred rupees due.", "4500"),
        (en, "date", "numerals + month", "I will pay on 15 November.", "d15,m11"),
        (en, "date", "ordinal", "I will pay on the fifteenth of November.", "d15,m11"),
        (en, "date", "day/month numerals", "I will pay on 15/11.", "d15,m11"),
    ]
    return [Item(l[0], l[1], l[2], kind, style, text, gold) for l, kind, style, text, gold in rows]


ITEMS = _items()
VOICES = {"hi": ("Prakash", "Shivani"), "gu": ("Harshad", "Lakshmi"), "en": ("Devansh", "Kalpana")}


def conditions(noises=NOISES, snrs=SNRS) -> list[tuple[str, ChannelProfile]]:
    """Clean wideband, then every noise x SNR over a narrowband mu-law phone line, then a lossy mobile line."""
    out = [("clean", ChannelProfile(id="clean", codec="none", narrowband=False))]
    out += [(f"{n}@{s}", ChannelProfile(id=f"{n}@{s}", noise=n, snr_db=s)) for n in noises for s in snrs]
    out.append(("bad_network", PRESETS["bad_network"]))
    return out


def run_atlas(
    speak: Callable[[str, str, str], tuple[np.ndarray, int]],
    transcribe: Callable[[np.ndarray, int, str], str],
    items: list[Item] | None = None,
    voices: dict[str, tuple[str, ...]] | None = None,
    conds: list[tuple[str, ChannelProfile]] | None = None,
    seeds: int = 2,
    workers: int = 1,                # Prisma: "Only 1 active request is allowed at a time" (HTTP 429)
    on_row: Callable[[dict], None] | None = None,
) -> dict:
    items, voices, conds = items or ITEMS, voices or VOICES, conds or conditions()
    jobs = []
    for it in items:
        for v in voices[it.lang]:
            clean, sr = speak(it.text, v, it.tts_lang)
            for name, prof in conds:
                for seed in range(1 if name == "clean" else seeds):
                    jobs.append((it, v, name, prof, seed, clean, sr))

    def one(job) -> dict:
        it, v, name, prof, seed, clean, sr = job
        audio, out_sr, _ = apply_channel(clean, sr, prof, seed=seed)
        t0 = time.perf_counter()
        try:
            hyp, err = transcribe(audio, out_sr, it.stt_lang), None
        except Exception as e:                       # one failed request must not sink a 3,000-request sweep
            hyp, err = "", repr(e)[:160]
        row = {"lang": it.lang, "kind": it.kind, "style": it.style, "voice": v, "cond": name,
               "noise": prof.noise, "snr": None if name in ("clean", "bad_network") else prof.snr_db, "seed": seed,
               "survived": bool(hyp) and it.survives(hyp), "gold": it.gold, "spoken": it.text, "hyp": hyp,
               "audio_s": round(audio.size / out_sr, 2), "stt_ms": round((time.perf_counter() - t0) * 1000)}
        if err:
            row["error"] = err
        if on_row:
            on_row(row)
        return row

    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(one, jobs))
    return summarize(rows)


def _rate(rs: list[dict]) -> float | None:
    rs = [r for r in rs if "error" not in r]
    return round(sum(r["survived"] for r in rs) / len(rs), 3) if rs else None


def summarize(rows: list[dict], target: float = 0.95) -> dict:
    """Survival by (lang, kind, style) x condition; the best phrasing per (lang, kind); and the read-back threshold:
    the lowest SNR at which that phrasing still survives `target` of the time across all four noises."""
    by = defaultdict(list)
    for r in rows:
        by[(r["lang"], r["kind"], r["style"])].append(r)
    table = []
    for (lang, kind, style), rs in by.items():
        snr = {str(s): _rate([r for r in rs if r["snr"] == s]) for s in SNRS}
        table.append({"lang": lang, "kind": kind, "style": style, "clean": _rate([r for r in rs if r["cond"] == "clean"]),
                      "bad_network": _rate([r for r in rs if r["cond"] == "bad_network"]), "by_snr": snr,
                      "by_noise": {n: _rate([r for r in rs if r["noise"] == n]) for n in NOISES},
                      "overall": _rate(rs), "n": len(rs)})
    best, policy = {}, {}
    for lang, kind in {(t["lang"], t["kind"]) for t in table}:
        cands = [t for t in table if t["lang"] == lang and t["kind"] == kind]
        top = max(cands, key=lambda t: (t["overall"] or 0, t["by_snr"]["0"] or 0))
        best[f"{lang}/{kind}"] = top["style"]
        ok = [s for s in SNRS if (top["by_snr"][str(s)] or 0) >= target]
        # the threshold is where survival stays >= target at that SNR and every cleaner one
        floor = None
        for s in SNRS:                                    # SNRS runs clean -> noisy
            if (top["by_snr"][str(s)] or 0) >= target:
                floor = s
            else:
                break
        policy[f"{lang}/{kind}"] = {"style": top["style"], "read_back_below_snr": floor,
                                    "survives_at": {str(s): top["by_snr"][str(s)] for s in SNRS}, "ok_snrs": ok}
    errors = sum("error" in r for r in rows)
    return {"generated": time.strftime("%Y-%m-%d %H:%M"), "target": target, "requests": len(rows), "errors": errors,
            "stt_seconds": round(sum(r["audio_s"] for r in rows), 1), "table": sorted(table, key=lambda t: (t["lang"], t["kind"], -(t["overall"] or 0))),
            "best": best, "policy": policy, "rows": rows}


def rescore(res: dict) -> dict:
    """Re-read every saved transcript with the current number and date readers: zero credits. Keeps the first
    reading as `survived_first` so a reader fix is visible as a reader fix, not as Prisma improving."""
    rows = []
    for r in res["rows"]:
        it = Item(r["lang"], "", "", r["kind"], r["style"], r["spoken"], r["gold"])
        rows.append({**r, "survived_first": r.get("survived_first", r["survived"]),
                     "survived": bool(r["hyp"]) and it.survives(r["hyp"])})
    out = summarize(rows, res.get("target", 0.95))
    out["generated"], out["rescored"] = res["generated"], time.strftime("%Y-%m-%d %H:%M")
    out["reader_fixes"] = sum(r["survived"] and not r["survived_first"] for r in rows)
    out["reader_losses"] = sum(r["survived_first"] and not r["survived"] for r in rows)
    return out


def write_atlas_report(res: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "atlas.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    def cell(v):
        if v is None:
            return "<td>—</td>"
        c = "var(--ok)" if v >= 0.95 else "var(--mid)" if v >= 0.75 else "var(--bad)"
        return f'<td style="background:{c}">{v:.0%}</td>'

    head = "<th>clean</th>" + "".join(f"<th>{s} dB</th>" for s in SNRS) + "<th>lossy</th>"
    sections = []
    for lang, title in (("hi", "Hindi / Hinglish"), ("gu", "Gujarati"), ("en", "English")):
        rows = [t for t in res["table"] if t["lang"] == lang]
        if not rows:
            continue
        body = "".join(
            f"<tr><th>{escape(t['kind'])}</th><td class=s>{escape(t['style'])}"
            + (" ★" if res["best"].get(f"{lang}/{t['kind']}") == t["style"] else "") + "</td>"
            + cell(t["clean"]) + "".join(cell(t["by_snr"][str(s)]) for s in SNRS) + cell(t["bad_network"]) + "</tr>"
            for t in rows)
        sections.append(f"<h2>{title}</h2><table><tr><th>detail</th><th>written as</th>{head}</tr>{body}</table>")
    pol = "".join(
        f"<tr><td>{escape(k)}</td><td>{escape(p['style'])}</td><td>"
        + ("not needed down to 0 dB" if p["read_back_below_snr"] == 0 else f"below {p['read_back_below_snr']} dB"
           if p["read_back_below_snr"] is not None else "always") + "</td></tr>"
        for k, p in sorted(res["policy"].items()))
    lost = [r for r in res["rows"] if not r["survived"] and r["snr"] is not None and r["snr"] >= 15][:12]
    lost_html = "".join(f"<tr><td>{escape(r['lang'])}/{escape(r['kind'])}</td><td>{escape(r['cond'])}</td>"
                        f"<td>{escape(r['spoken'])}</td><td>{escape(r['hyp'])}</td></tr>" for r in lost)
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phone-line atlas</title><style>
:root{{--bg:#fbfaf7;--fg:#1d1b18;--mute:#6b665d;--line:#e4e0d8;--ok:rgba(47,125,79,.28);--mid:rgba(168,116,26,.28);--bad:rgba(179,64,47,.30)}}
@media (prefers-color-scheme:dark){{:root{{--bg:#171614;--fg:#ece8e1;--mute:#a39d92;--line:#2f2c28}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:1000px;margin:0 auto;padding:24px 16px}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px;font-size:13px;display:block;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:4px 6px;text-align:center}} td.s{{text-align:left}} p,.m{{color:var(--mute)}}
</style></head><body>
<h1>Which details survive an Indian phone line</h1>
<p>Each detail was written several ways, spoken by Timbre ({sum(len(v) for v in VOICES.values())} voices), passed through the
channel simulator (narrowband μ-law; fan, office, traffic and crowd noise at each SNR; plus a lossy mobile line), transcribed by
Prisma and parsed by Diapason's own number and date readers. A cell is the share of transcripts that still held the exact detail
(each SNR column pools the four noises). ★ = the phrasing that survives best. {res['requests']} Prisma requests,
{res['stt_seconds'] / 60:.0f} minutes of audio, {res['errors']} failed requests, generated {escape(res['generated'])}.</p>
{f"<p>Re-read {escape(res['rescored'])} with fixed readers: {res['reader_fixes']} transcripts the first reading wrongly counted as lost (Prisma had heard them right; Diapason's number and date readers could not read them), {res['reader_losses']} the other way.</p>" if res.get('rescored') else ""}
{''.join(sections)}
<h2>What an agent should do</h2>
<p>Say each detail the ★ way; read it back to the caller before acting on it when the line is worse than this (survival under
{res['target']:.0%}):</p>
<table><tr><th>language / detail</th><th>say it as</th><th>read it back</th></tr>{pol}</table>
<h2>Lost on a decent line (15 dB or better)</h2>
<table><tr><th>detail</th><th>line</th><th>spoken</th><th>Prisma heard</th></tr>{lost_html or '<tr><td colspan=4>none</td></tr>'}</table>
</body></html>"""
    path = out / "atlas.html"
    path.write_text(html, encoding="utf-8")
    return path
