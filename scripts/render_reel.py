"""Render the demo reel: a motion-designed film of Diapason, narrated by Gnani Timbre, to an MP4.

Everything on screen comes from the run files: the real test call and its recording, Guard's real rewrites, every planted
bug and the v1-to-v4 proof, the red team's attacks and the leak they caused, Prisma's Tamil and Telugu transcripts, the
phone-line atlas, the noise sweep, QA Studio's calls by language, and the measured numbers. The narration is voiced by
Timbre and each scene is as long as its narration, so picture and sound share one clock: the page draws any instant
exactly (render(t)), the audio is mixed on the same timeline, and the frames are captured one by one at 30 fps. The sound
design (whooshes, hits, a low bed) is synthesised here, so nothing in the mix is borrowed.

    .venv/Scripts/python.exe scripts/render_reel.py                 # about 2,000 Timbre characters the first time, then cached
    .venv/Scripts/python.exe scripts/render_reel.py --still 3 40    # check stills at those seconds, no render
"""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from diapason import film, site  # noqa: E402

SR = 48000
FPS = 30
XFADE = 0.7
VOICE = ("Devansh", "en-IN")
SPEED = 1.05
PROOF = ROOT / "runs" / "proof-live-5"
OWN = "--own-intro" in sys.argv                                   # the intro left for the author's own voice
OWN_WAV = ROOT / "runs" / "video" / "intro-voice.wav"              # if recorded, mixed in at the intro's cue
OUT = ROOT / "runs" / "video" / ("diapason-reel-own-intro.mp4" if OWN else "diapason-reel.mp4")
WORK = ROOT / "runs" / "video" / "reel"

NARRATION = {
    "intro": "Hi, I'm Riyan. I usually narrate my own demos, but applying to a speech AI company, it felt right to let Gnani's "
             "Timbre do the talking.",
    "title": "This is Diapason: crash tests for Indian voice agents.",
    "cast": "Synthetic callers phone your agent over a noisy phone line and try to break it, in Hindi, Gujarati, Tamil, Telugu, "
            "Kannada, Marathi and English. They interrupt, try prompt injection, or turn out to be the wrong person.",
    "call": "Every fail is caught as it's said, quoting the agent's own words.",
    "bugs": "To prove it, I planted seven bugs. No recording disclosure. The debt told before verifying, to the brother, with "
            "threats. Hindi to a Gujarati speaker. A prompt injection obeyed. A fan mistaken for speech. Talking over the "
            "caller. All of them caught.",
    "matrix": "Each fix is re-tested on the same calls, until version four, where code speaks every fact, removes all six text bugs.",
    "guard": "Guard checks every sentence in code before it's spoken. The threat is cut, and the amount waits until the caller "
             "is verified.",
    "shield": "Shield does the same in front of any agent, on Twilio, Exotel or Plivo, holding each line for a median of six "
              "hundred seventy-eight milliseconds.",
    "redteam": "Evon red-teams the agent with new attacks. Version two leaked the account in four of twelve. With the secret "
               "out of the model, none.",
    "langs": "Prisma writes Tamil and Telugu numbers as words. Diapason still reads them.",
    "atlas": "Across three thousand noisy transcripts, ninety-eight percent of IDs, amounts and dates survive, and a noise sweep "
             "shows where each agent stops hearing.",
    "found": "Only a live call found this: Timbre read forty-eight twenty-one as one big number, so nobody could verify. And my "
             "own judge failed nine of nine correct calls, until I fixed it.",
    "qa": "After the call, an auditor scores every call on twenty-two industry playbooks, gets over ninety percent right, and "
          "sends any doubt to a human.",
    "gnani": "Timbre gives the callers voices. Prisma is their ears. Evon plays the caller, the agent, the judge and the red team.",
    "end": "Diapason. Test your agent the way India calls.",
}

# Callers from real test calls, one or two per language (names as the calls say them)
CAST = [
    {"native": "रमेश", "name": "Ramesh", "lang": "Hindi", "what": "Shop owner, angry about repeated calls", "say": "Hindi"},
    {"native": "હંસા", "name": "Hansa", "lang": "Gujarati", "what": "Speaks only Gujarati", "say": "Gujarati"},
    {"native": "குமார்", "name": "Kumar", "lang": "Tamil", "what": "Has a loan, and a problem with it", "say": "Tamil"},
    {"native": "రాజు", "name": "Raju", "lang": "Telugu", "what": "Gig worker who lost his job last month", "say": "Telugu"},
    {"native": "ಸವಿತಾ", "name": "Savita", "lang": "Kannada", "what": "Microfinance borrower", "say": "Kannada"},
    {"native": "वंदना", "name": "Vandana", "lang": "Marathi", "what": "Microfinance borrower", "say": "Marathi"},
    {"native": "Anil", "name": "Anil", "lang": "English", "what": "Lost his bank card at the market", "say": "English"},
    {"native": "सुरेश's brother", "name": "Suresh's brother", "lang": "Hindi", "what": "Not the borrower: nothing may be said", "say": "wrong"},
]
BUG_WORDS = ["disclosure", "verifying", "threats", "brother", "Gujarati", "injection", "fan", "Talking"]   # the planted bugs, in proof order
TRANSITIONS = {"intro": "zoom", "title": "zoom", "cast": "iris", "line": "slide", "call": "wipe", "bugs": "iris", "matrix": "slide",
               "guard": "zoom", "shield": "wipe", "redteam": "slide", "langs": "iris", "atlas": "slide", "found": "zoom", "qa": "wipe",
               "gnani": "iris", "end": "zoom"}
LANG_NAMES = {"hi-IN": ("Hindi", "हिन्दी"), "en-IN": ("English", ""), "gu-IN": ("Gujarati", "ગુજરાતી"), "ta-IN": ("Tamil", "தமிழ்"),
              "mr-IN": ("Marathi", "मराठी"), "kn-IN": ("Kannada", "ಕನ್ನಡ"), "te-IN": ("Telugu", "తెలుగు"), "bn-IN": ("Bengali", "বাংলা")}


# ------------------------------------------------------------------------------------------------ audio helpers
def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        a = np.frombuffer(w.readframes(n), np.int16).astype(np.float32) / 32768
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return resample(a, sr)


def resample(a: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return a
    t = np.arange(int(len(a) * SR / sr)) / SR
    return np.interp(t, np.arange(len(a)) / sr, a).astype(np.float32)


def place(mix: np.ndarray, clip: np.ndarray, at: float, gain: float = 1.0) -> None:
    i = int(at * SR)
    j = min(len(mix), i + len(clip))
    if j > i:
        mix[i:j] += clip[: j - i] * gain


def peaks(a: np.ndarray, n: int) -> list[float]:
    b = np.array_split(np.abs(a), n)
    p = np.array([x.max() if len(x) else 0 for x in b])
    return [round(float(v), 3) for v in p / max(p.max(), 1e-6)]


def whoosh(dur: float = 0.8, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = rng.standard_normal(n).astype(np.float32)
    cut = np.linspace(0.02, 0.35, n) ** 1.5                     # a one-pole low-pass opening up: air rushing past
    y = np.zeros(n, np.float32)
    acc = 0.0
    for k in range(n):
        acc += cut[k] * (x[k] - acc)
        y[k] = acc
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return y * env / max(np.abs(y * env).max(), 1e-6)


def hit(dur: float = 1.2) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    f = 85 * np.exp(-t * 3) + 40                                 # a falling sub thump
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.5)
    click = np.random.default_rng(7).standard_normal(len(t)) * np.exp(-t * 90) * 0.4
    y = body + click
    return (y / np.abs(y).max()).astype(np.float32)


def bed(total: float) -> np.ndarray:
    t = np.arange(int(total * SR)) / SR
    y = np.zeros_like(t)
    for f, a in ((55, .5), (110.4, .35), (164.6, .25), (220.8, .18), (277.2, .1)):
        y += a * np.sin(2 * np.pi * f * t + np.sin(2 * np.pi * .07 * t) * 2) * (0.7 + 0.3 * np.sin(2 * np.pi * (0.05 + f / 4000) * t))
    fade = np.clip(t / 3, 0, 1) * np.clip((total - t) / 3, 0, 1)
    return (y / np.abs(y).max() * fade).astype(np.float32)


# ------------------------------------------------------------------------------------------------ material
def narrate() -> dict[str, np.ndarray]:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from diapason.gnani import Timbre
    tts = Timbre(cache_dir=ROOT / ".cache" / "tts")
    out = {}
    for k, text in NARRATION.items():
        a, sr = tts.synthesize(text, voice=VOICE[0], lang=VOICE[1], sr=24000, speed=SPEED)
        a = resample(np.asarray(a, np.float32), sr)
        out[k] = a / max(np.abs(a).max(), 1e-6) * 0.9
    print(f"narration: {tts.calls} Timbre calls, {tts.chars} characters ({tts.hits} cached)", flush=True)
    return out


def word_time(text: str, word: str, dur: float) -> float:
    ws = text.split()
    i = next((k for k, w in enumerate(ws) if word.lower() in w.lower()), 0)
    return dur * i / len(ws)


def build() -> tuple[dict, np.ndarray]:
    nar = narrate()
    nd = {k: len(v) / SR for k, v in nar.items()}
    call = film._call_scene(ROOT / "runs", lambda p: str(p), short=False)
    mixwav = read_wav(ROOT / call["audio"])
    threat = next(t for t in call["turns"] if t["flags"])
    p = json.loads((PROOF / "proof.json").read_text(encoding="utf-8"))
    guard = site._guard_calls(PROOF, p["tests"])[0]["steps"]
    heard = site._heard(ROOT / "runs")
    auto = json.loads((ROOT / "runs" / "autopilot-live-7" / "autopilot.json").read_text(encoding="utf-8"))
    atlas = json.loads((ROOT / "runs" / "atlas" / "atlas.json").read_text(encoding="utf-8"))
    studio = json.loads((ROOT / "site" / "data" / "studio.json").read_text(encoding="utf-8"))
    stress = json.loads((site._latest(ROOT / "runs", "stress.json") / "stress.json").read_text(encoding="utf-8"))
    evo = site._evolution(p)

    scenes, sfx_whoosh, sfx_hit, voice = [], [], [], []
    t0 = 0.0

    def add(kind: str, dur: float, **kw) -> dict:
        nonlocal t0
        scenes.append({"type": kind, "start": round(t0, 3), "dur": round(dur, 3), "trans_in": TRANSITIONS.get(kind, "zoom"), **kw})
        if t0 > 0:
            sfx_whoosh.append(t0)
        t0 += dur
        return scenes[-1]

    def said(kind: str, sc: dict, at: float = .5) -> None:
        voice.append((nar[kind], sc["start"] + at, 1))

    def fit(kind: str, lead: float = .5, tail: float = .7, least: float = 0) -> float:
        return max(least, lead + nd[kind] + tail)

    def cue(kind: str, word: str, lead: float = .5, early: float = 0) -> float:
        return round(lead + word_time(NARRATION[kind], word, nd[kind]) - early, 2)

    # 1. cold open: the agent's real threat, on its own recording
    seg = mixwav[int(threat["start"] * SR): int((threat["end"] + .3) * SR)]
    s = add("open", 1.0 + len(seg) / SR + 1.5, audio_at=1.0, audio_len=round(len(seg) / SR, 3), peaks=peaks(seg, 120), text=threat["text"],
            hot=["पुलिस", "कंप्लेंट", "लीगल", "एक्शन"],
            english="Your EMI of ₹4,500 is overdue. If you don't pay today, there'll be a police complaint and legal action.")
    s["stamp_at"] = round(s["audio_at"] + s["audio_len"] * .72, 3)
    voice.append((seg, s["start"] + s["audio_at"], .85))
    sfx_hit.append(s["start"] + s["stamp_at"])
    # 2. Riyan, in Timbre's voice; the title; the callers; the line
    own = read_wav(OWN_WAV)[: int(8.6 * SR)] if OWN and OWN_WAV.exists() else None
    it = add("intro", fit("intro", .5, .6), voice_at=.5, voice_len=round(len(own) / SR if own is not None else nd["intro"], 2),
             peaks=peaks(own if own is not None else (np.zeros(SR) if OWN else nar["intro"]), 160), sub_at=1.8 if OWN else cue("intro", "usually"),
             sub="Demoing to a speech AI company in my own voice? That felt ironic. So Gnani's Timbre narrates the rest." if OWN else
                 "I usually narrate my own demos. Applying to a speech AI company, it felt right to let their model do the talking.",
             chip="From here on: narrated by Gnani Timbre" if OWN else "Narrated by Gnani Timbre")
    if not OWN:
        said("intro", it)
    elif own is not None:
        voice.append((own / max(np.abs(own).max(), 1e-6) * .9, it["start"] + .5, 1))
    tt = add("title", fit("title", .9, .7, 4.0))
    said("title", tt, .9)
    sfx_hit.append(tt["start"] + .9)
    c = add("cast", fit("cast", .4, .6), cast=CAST)
    c["cues"] = [cue("cast", m["say"], .4) for m in CAST]
    said("cast", c, .4)
    # 3. the real call, at its own speed, its transcript on its own timings
    off = max(0.0, call["turns"][0]["start"] - .4)                  # from the agent's first word, not the dial-in silence
    upto = threat["end"] + 1.2 - off
    clip = mixwav[int(off * SR): int((off + upto) * SR)]
    turns = [{"who": u["who"], "text": u["text"], "start": round(u["start"] - off, 2)} for u in call["turns"] if u["start"] - off < upto]
    hot_at = threat["start"] - off + (threat["end"] - threat["start"]) * .55
    cs = add("call", .6 + upto + .4 + nd["call"] + .8, audio_at=.6, audio_len=round(upto, 2), peaks=peaks(clip, 110), turns=turns,
             fails=[{"name": "Banned threat", "why": f"\"पुलिस\" and \"लीगल एक्शन\", said at {threat['start']:.1f} s"},
                    {"name": "Loan ID never captured", "why": "Ramesh says चार आठ दो एक later in the call; the agent never checks it"}])
    cs["fail_at"] = [round(.6 + hot_at, 2), round(.6 + upto + .1, 2)]
    cs["verdict_at"] = round(.6 + upto + .6, 2)
    voice.append((clip, cs["start"] + .6, .85))
    said("call", cs, .6 + upto + .4)
    sfx_hit += [cs["start"] + cs["fail_at"][0], cs["start"] + cs["verdict_at"]]
    # 4. every planted bug, named as it is caught; then v1 to v4
    bg = add("bugs", fit("bugs", .5, .7), bugs=[{"what": b["what"]} for b in evo["bugs"]])
    bg["cues"] = [cue("bugs", w) for w in BUG_WORDS]
    said("bugs", bg)
    m = add("matrix", fit("matrix", .5, .6, 8.0), evolution=evo)
    said("matrix", m)
    # 5. Guard, then Shield
    steps = []
    for st in guard[:2]:
        d = next((x for x in st["drafts"] if x["rule"] == "account_before_verification"), st["drafts"][0])
        steps.append({"at": st["at"], "draft": d["before"], "said": st["said"],
                      "rule": {"banned_phrase": "threat removed", "account_before_verification": "held until verified"}.get(d["rule"], d["rule"])})
    g = add("guard", fit("guard", .5, .8, 9.8), steps=steps, cues=[.8, 4.6])
    said("guard", g)
    sh = add("shield", fit("shield", .5, .6, 7.0), bad=steps[0]["draft"], good=steps[0]["said"], stat_at=4.4,
             stats=[["678 ms", "median hold per line (live, Exotel stream)"], ["33 / 35", "lines held under 1 s"],
                    ["every", "threat and missing disclosure replaced"]])
    said("shield", sh)
    # 6. the red team
    rp = auto["replay"]
    rt = add("redteam", fit("redteam", .5, .6, 7.5), ideas=[a["idea"].split(".")[0][:96] for a in auto["attacks"][:3]],
             leak=rp["before"]["examples"][3]["quote"].split("।")[0] + "।", before=rp["before"]["leaked"], after=rp["after"]["leaked"],
             of=rp["before"]["calls"], leak_at=cue("redteam", "leaked", early=.3), big_at=cue("redteam", "secret", early=.3))
    said("redteam", rt)
    # 7. languages, the atlas and the noise sweep, the bugs only live calls found
    fonts = {"Tamil": ("ta", "Tamil"), "Telugu": ("te", "Telugu")}
    rows = []
    for lang, kind in (("Tamil", "id"), ("Telugu", "amount")):
        r = next((x for x in heard["rows"] if x["lang"] == lang and x["kind"] == kind and len(x["words"]) <= 9), None)
        if r:
            rows.append({**r, "code": fonts[lang][0], "font": fonts[lang][1], "kindLabel": {"id": "LOAN ID", "amount": "AMOUNT"}[kind]})
    la = add("langs", fit("langs", .6, 1.0, 6.8), rows=rows, cues=[.8, 3.4])
    said("langs", la, .6)
    cols = ["clean", "30", "20", "15", "10", "5", "0"]
    arow = []
    for code, name in (("hi", "Hindi"), ("gu", "Gujarati"), ("en", "English")):
        vals = []
        for col in cols:
            sel = [r for r in atlas["rows"] if r["lang"] == code and ((r["cond"] == "clean") if col == "clean"
                   else r.get("snr") is not None and float(r["snr"]) == float(col))]
            vals.append(round(sum(r["survived"] for r in sel) / max(len(sel), 1), 3))
        arow.append({"name": name, "vals": vals})
    sweep = [{"v": f"agent {v}", "cells": [stress["versions"][v]["grid"]["fan"][str(lv)] is True for lv in stress["levels"]]}
             for v in ("v1", "v3") if v in stress["versions"]]
    at = add("atlas", fit("atlas", .5, .7, 7.5), cols=["clean"] + [f"{x} dB" for x in cols[1:]], rows=arow, sweep=sweep,
             levels=stress["levels"], noise="fan", sweep_at=cue("atlas", "sweep", early=.2))
    said("atlas", at)
    fd = add("found", fit("found", .5, .9), cues=[.4, cue("found", "judge", early=.3)])
    said("found", fd)
    # 8. QA, Gnani, the end
    cnt = Counter(lang for a in studio["audits"] for lang, _ in (a.get("langs") or []) if lang)
    qa = add("qa", fit("qa", .5, 1.2, 7.0),
             kpis=[["22", "industry playbooks, each with its regulations"], ["90-94%", "of verdicts right, on calls the auditor never saw"],
                   ["100%", "of fatal breaches caught; any doubt goes to a human"]],
             langs=[[LANG_NAMES.get(lang, (lang, ""))[0], LANG_NAMES.get(lang, (lang, ""))[1], n] for lang, n in cnt.most_common()],
             cues=[.4, cue("qa", "ninety", early=.2), cue("qa", "doubt", early=.3)], langs_at=round(.5 + nd["qa"] - .5, 2))
    said("qa", qa)
    gn = add("gnani", fit("gnani", .5, .6, 6.0), models=[
        {"name": "Timbre", "role": "the callers' voices in eight languages, with emotion, and this narration"},
        {"name": "Prisma", "role": "their ears, over an 8 kHz phone line"},
        {"name": "Evon", "role": "the callers, the agent, the judge and the red team, self-hosted"}],
        cues=[cue("gnani", w, early=.15) for w in ("Timbre", "Prisma", "Evon")])
    said("gnani", gn)
    en = add("end", .5 + nd["end"] + 1.5)
    said("end", en)
    sfx_hit.append(en["start"] + .3)
    total = round(t0, 3)

    # the mix, on the same timeline
    mix = np.zeros(int((total + .5) * SR), np.float32)
    speech = np.zeros_like(mix)
    for clip_, at_, gain in voice:
        place(speech, clip_, at_, gain)
    pad = bed(total + .5)[: len(mix)]
    env = np.abs(speech)
    win = int(.25 * SR)
    acc = np.concatenate([[0], np.cumsum(env)])                    # a running mean (a direct convolution here takes minutes)
    idx = np.arange(len(env))
    duck = ((acc[np.clip(idx + win // 2, 0, len(env))] - acc[np.clip(idx - win // 2, 0, len(env))]) / win).astype(np.float32)
    pad *= 0.075 / (1 + 6 * np.clip(duck * 6, 0, 1))              # the bed steps back whenever anyone speaks
    mix += speech + pad
    for k, at_ in enumerate(sfx_whoosh):
        place(mix, whoosh(.8, k), at_ - .4, .22)
    h_ = hit()
    for at_ in sfx_hit:
        place(mix, h_, at_, .5)
    mix /= max(np.abs(mix).max() / .95, 1)
    data = {"scenes": scenes, "total": total, "xfade": XFADE, "flashes": [round(s["start"] + s["stamp_at"], 2), round(tt["start"] + .9, 2)]}
    return data, mix


def page(data: dict) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "reel.html"
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path.write_text((ROOT / "core" / "diapason" / "static" / "reel.html").read_text(encoding="utf-8").replace("__DATA__", blob, 1), encoding="utf-8")
    return path


def open_page(pw, path: Path):
    b = pw.chromium.launch(channel="chrome")
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(path.as_uri(), wait_until="networkidle")
    pg.evaluate("window.__ready")
    pg.wait_for_timeout(800)
    return b, pg, errs


def main() -> None:
    import imageio_ffmpeg
    from playwright.sync_api import sync_playwright
    data, mix = build()
    path = page(data)
    total = data["total"]
    print(f"reel: {total:.1f} s, {len(data['scenes'])} scenes: " + ", ".join(f"{s['type']} {s['dur']:.1f}" for s in data["scenes"]), flush=True)
    if "--still" in sys.argv:
        with sync_playwright() as pw:
            b, pg, errs = open_page(pw, path)
            for t in (float(x) for x in sys.argv[sys.argv.index("--still") + 1:]):
                pg.evaluate("t => window.__frame(t)", t)
                pg.screenshot(path=str(WORK / f"still-{t:06.2f}.png"))
            b.close()
        print("page errors:", errs or "none")
        return
    wav = WORK / "reel.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype(np.int16).tobytes())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-", "-i", str(wav),
           "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium",
           "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", str(OUT)]
    n = round(total * FPS)
    with sync_playwright() as pw:
        b, pg, errs = open_page(pw, path)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            for k in range(n):
                pg.evaluate("t => window.__frame(t)", k / FPS)
                proc.stdin.write(pg.screenshot(type="jpeg", quality=93))
                if k % (FPS * 20) == 0:
                    print(f"  {k / FPS:5.0f} s of {total:.0f} s", flush=True)
        finally:
            proc.stdin.close()
            proc.wait()
        b.close()
    print(f"{OUT}  ({total:.0f} s, {n} frames, {OUT.stat().st_size / 1e6:.1f} MB; page errors: {errs or 'none'})")


if __name__ == "__main__":
    main()
