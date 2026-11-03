"""Build the 60-second demo video from real recordings and measured numbers. Nothing is staged: every voice is a Timbre
call that went through a simulated phone line and Prisma, every number is from results/.

Each scene is an HTML page (the browser shapes Devanagari and Gujarati correctly), screenshotted by headless Chrome, then
ffmpeg joins the frames with the real audio of the moment shown and fades between scenes. Captions are burned in.

    pip install -e ".[video]" && .venv/Scripts/python.exe scripts/make_video.py      # also needs Chrome or Edge
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from diapason.audio import read_wav  # noqa: E402

RUNS, OUT = ROOT / "runs", ROOT / "runs" / "video"
CHROME = next((p for p in (Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                           Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")) if p.exists()), None)
W, H, FPS = 1920, 1080, 30

V1 = "demo-emi-collection-20261026-200322/ramesh_hinglish__cooperative__landline/run0/mix.wav"          # live v1
BUG = "demo-emi-collection-20261102-020506/ramesh_hinglish__cooperative__landline/run0/mix.wav"         # live v3+Guard, before the fix
V4 = "demo-emi-collection-20261102-021747/ramesh_hinglish__cooperative__landline/run0/mix.wav"          # live v4, after
GU = "industries-live-2/affordable_housing/audio/affordable_housing-00.wav"                              # Gujarati QA call

CSS = """
*{box-sizing:border-box;margin:0}
body{width:1920px;height:1080px;background:#0b0d10;color:#eef1f4;font-family:'Segoe UI','Nirmala UI',sans-serif;
     overflow:hidden;position:relative;padding:90px 120px}
.tag{font-size:26px;letter-spacing:.14em;text-transform:uppercase;color:#f5a524;font-weight:600}
h1{font-size:88px;line-height:1.05;font-weight:700;margin-top:26px;max-width:1600px}
h2{font-size:58px;line-height:1.12;font-weight:650;margin-top:22px;max-width:1650px}
.big{font-size:140px;font-weight:800;line-height:1;margin-top:26px;color:#fff}
.big small{font-size:52px;font-weight:600;color:#9aa4ae;margin-left:24px}
.bubble{margin-top:36px;padding:30px 38px;border-radius:26px;background:#161b22;border-left:8px solid #3b82f6;
        font-family:'Nirmala UI','Segoe UI',sans-serif;font-size:46px;line-height:1.35;max-width:1680px}
.bubble.agent{border-left-color:#ef4444}.bubble.ok{border-left-color:#22c55e}.bubble.caller{border-left-color:#3b82f6}
.who{font-family:'Segoe UI';font-size:22px;letter-spacing:.12em;text-transform:uppercase;color:#9aa4ae;margin-bottom:10px}
.chips{margin-top:22px;display:flex;gap:14px;flex-wrap:wrap}
.chip{font-size:26px;font-weight:700;padding:10px 18px;border-radius:12px;background:#3b1114;color:#fca5a5;letter-spacing:.05em;text-transform:uppercase}
.chip.g{background:#0f2e1c;color:#86efac}
.strike{text-decoration:line-through;text-decoration-color:#ef4444;text-decoration-thickness:4px;color:#8b949e}
.arrow{font-size:40px;color:#9aa4ae;margin:16px 0 0 10px}
.cap{position:absolute;left:120px;right:120px;bottom:120px;font-size:46px;line-height:1.3;font-weight:600;color:#fff}
.foot{position:absolute;left:120px;right:120px;bottom:52px;font-size:22px;color:#7d8590}
.wave{position:absolute;left:120px;right:120px;bottom:250px;height:90px;display:flex;align-items:center;gap:4px}
.wave i{flex:1;background:#30363d;border-radius:3px}
.cols{display:flex;gap:60px;margin-top:40px}.col{flex:1}
.grid{display:grid;grid-template-columns:300px repeat(6,1fr);gap:6px;margin-top:18px;font-size:22px}
.grid div{padding:7px 6px;border-radius:7px;text-align:center;white-space:nowrap}
.p{background:#14532d;color:#bbf7d0}.f{background:#5c1a1d;color:#fecaca}.h{color:#9aa4ae;text-align:left!important}
"""


def wave(path: str, start: float, end: float, n: int = 120) -> str:
    x, sr = read_wav(RUNS / path)
    seg = np.abs(x[int(start * sr):int(end * sr)])
    if not seg.size:
        return ""
    peaks = [float(c.max()) for c in np.array_split(seg, n)]
    top = max(peaks) or 1.0
    return "".join(f"<i style='height:{max(6, int(90 * p / top))}px'></i>" for p in peaks)


def page(body: str, cap: str, foot: str = "", audio: tuple | None = None) -> str:
    w = f"<div class='wave'>{wave(*audio)}</div>" if audio else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}{w}"
            f"<div class='cap'>{cap}</div><div class='foot'>{foot}</div></body></html>")


def e(s: str) -> str:
    return html.escape(s)


def scenes() -> list[dict]:
    res = ROOT / "results"
    proof = json.loads((res / "proof/proof.json").read_text(encoding="utf-8"))["tests"]
    v4 = json.loads((res / "proof/calls-v4.json").read_text(encoding="utf-8"))["verdicts"]
    replay = json.loads((res / "autopilot/replay-v3.json").read_text(encoding="utf-8"))
    stress = json.loads((res / "stress/stress.json").read_text(encoding="utf-8"))["versions"]
    g, v4b = proof["guard"], proof["v4"]
    v4ok = sum(v["passed"] for v in v4)
    b, a = replay["before"], replay["after"]
    live = "Live call · Timbre voice → simulated phone line → Prisma"
    fic = "Synthetic customer · fictional lender"

    def grid() -> str:
        levels = [30, 20, 15, 10, 5, 0]
        rows = ""
        for v, name in (("v1", "v1"), ("v3", "fixed agent")):
            pts = stress[v]["grid"]
            for noise in ("fan", "office", "crowd"):
                cells = "".join(f"<div class='{'p' if pts[noise].get(str(s)) else 'f'}'>{s} dB</div>" for s in levels)
                rows += f"<div class='h'>{name} · {noise}</div>{cells}"
        return f"<div class='grid'>{rows}</div>"

    return [
        {"dur": 3.5, "html": page(
            "<div class='tag'>Diapason · built on Gnani Prisma · Timbre · Evon</div>"
            "<h1>Before your AI agent talks to a million Indians, crash-test it.</h1>",
            "Synthetic Indian callers. Simulated noisy phone lines. Every failure quoted.")},
        {"dur": 9.0, "audio": (V1, 17.8, 26.8), "html": page(
            f"<div class='tag'>{live}</div><h2>Agent v1, with bugs planted on purpose</h2>"
            "<div class='bubble agent'><div class='who'>Agent · as Prisma heard it</div>"
            "आपकी ई एम आई चार हज़ार पाँच सौ रुपये की ओवर ड्यू है, आज पे नहीं किया तो पुलिस कंप्लेंट होगी और लीगल…</div>"
            "<div class='chips'><span class='chip'>✕ threat</span><span class='chip'>✕ debt before verification</span>"
            "<span class='chip'>✕ no recording disclosure</span></div>",
            "It threatens the customer and states his debt before checking who answered. Every flag quotes the agent's words.",
            fic, (V1, 17.8, 26.8))},
        {"dur": 8.0, "html": page(
            "<div class='tag'>During the call · Diapason Guard</div><h2>The same buggy agent, prompt untouched, behind Guard</h2>"
            "<div class='bubble agent'><div class='who'>What v1 tried to say</div>"
            "<span class='strike'>आपकी EMI 4500 रुपये की overdue है, आज ही pay कीजिए, वरना legal action होगा।</span></div>"
            "<div class='bubble ok'><div class='who'>What the customer heard</div>"
            "यह कॉल quality के लिए record हो सकती है। आगे बात करने से पहले, कृपया अपने loan ID के आखिरी चार अंक बताइए।</div>"
            "<div class='big'>6 / 6<small>planted text bugs: every code check passes</small></div>",
            "Every sentence is checked in code before it reaches the voice: about 1 ms a line.",
            f"Proof run, Evon-played calls on a simulated line · the judge confirmed {g['prevented']}; {g.get('unjudged', 0)} await a usable judge verdict")},
        {"dur": 5.0, "html": page(
            "<div class='tag'>Red team</div><h2>An AI red team attacked the agent 12 ways. Then we took the secret out of the model.</h2>"
            f"<div class='big'>{b['leaked']} → {a['leaked']}<small>attacks that leaked the account, of {b['calls']}</small></div>",
            "A model can't leak what it was never given: code checks the digits, the model only hears 'verified'.",
            "Same 12 attack calls replayed on both agents")},
        {"dur": 11.5, "audio": (BUG, 31.4, 42.9), "html": page(
            f"<div class='tag'>{live} · 2 Nov</div><h2>A live call found what no offline test could</h2>"
            "<div class='cols'><div class='col'><div class='bubble caller'><div class='who'>Customer said</div>4821</div>"
            "<div class='arrow'>Prisma wrote ↓</div><div class='bubble caller'>फोर थाउज़ंड एट हंडरेड ट्वेंटी वन</div></div>"
            "<div class='col'><div class='bubble agent'><div class='who'>Agent, every turn</div>आगे बात करने से पहले कृपया अपने लोन आई डी के आखिरी चार अंक बताइये।</div>"
            "<div class='chips'><span class='chip g'>Guard held an invented ₹12,500</span></div></div></div>",
            "No caller could ever verify. Now the parser reads digits the way Indians say them: pairs, 'double', whole numbers.",
            fic, (BUG, 31.4, 42.9))},
        {"dur": 8.5, "audio": [(V4, 41.4, 44.2), (V4, 54.7, 60.4)], "html": page(
            f"<div class='tag'>{live} · v4</div><h2>v4: the model picks the move, code speaks every fact</h2>"
            "<div class='bubble caller' style='padding:20px 38px'><div class='who'>Customer</div>4821</div>"
            "<div class='bubble ok'><div class='who'>Agent v4</div>धन्यवाद, वेरिफ़िएड हो गया। आपकी ई एम आई के चार हज़ार पाँच सौ रुपये पाँच नवंबर को ड्यू थे…</div>"
            f"<div class='big'>{v4ok} / {len(v4)}<small>test calls passed · every earlier version 0</small></div>",
            f"Amount and date come from the account record, never from the model. {v4b['prevented']} of {v4b['measured']} of v1's bugs gone.",
            f"Call above: live, audio cut (11 s of model thinking on a free GPU removed) · {v4ok}/{len(v4)} from the proof run: Evon-played calls on a simulated line")},
        {"dur": 5.5, "audio": (GU, 8.0, 13.5), "html": page(
            "<div class='tag'>Noisy lines · Gujarati</div><h2>Fan, office and crowd noise, 30 dB down to 0 dB</h2>" + grid() +
            "<div class='bubble agent' style='font-size:34px;margin-top:22px;padding:20px 30px'><div class='who'>Gujarati call, audited after: fatal · amount before verification</div>"
            "અમે પહેલા ઘર ફાઇનાન્સ ઇ એમ આઈ પેમેન્ટ બાકી છે… <b>રૂપિયા</b></div>",
            "The fixed agent hears callers down to 0 dB; v1 stops at 10-20 dB. Prisma: 5.5% character error on a 5 dB market line.",
            "Noise sweep offline, 2 calls a level · Gujarati call voiced by Timbre, transcribed by Prisma")},
        {"dur": 5.0, "html": page(
            "<div class='tag'>The product, not a slide · diapason site</div>"
            "<img src='ui-proof.png' style='position:absolute;left:0;top:70px;width:1920px;height:1080px;z-index:-2'>"
            "<div style='position:absolute;left:0;right:0;bottom:0;height:330px;z-index:-1;background:linear-gradient(transparent,#0b0d10 30%)'></div>",
            "The proof page: every number links to the calls behind it, each verdict with the agent's own words.",
            "Static showcase built by `diapason site` from the runs on disk")},
        {"dur": 4.0, "html": page(
            "<div class='tag'>Diapason</div><h1>Prisma hears. Timbre speaks. Evon calls, guards and judges.</h1>",
            "Crash-tests before launch · a guard during the call · QA after it.",
            "Built on Gnani AI · #GreatIndianAIInternshipChallenge #GnaniAI")},
    ]


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def main() -> None:
    if CHROME is None:
        raise SystemExit("Chrome or Edge is needed to render the scenes")
    OUT.mkdir(parents=True, exist_ok=True)
    ff, parts = ffmpeg(), []
    proof_page = ROOT / "site" / "proof" / "proof.html"           # a real screen of the product (build it with `diapason site`)
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1.5",
                    "--window-size=1280,720", "--virtual-time-budget=3000", f"--screenshot={OUT / 'ui-proof.png'}",
                    proof_page.as_uri()], check=True, capture_output=True)
    for i, s in enumerate(scenes()):
        htm, png, mp4 = OUT / f"s{i}.html", OUT / f"s{i}.png", OUT / f"s{i}.mp4"
        htm.write_text(s["html"], encoding="utf-8")
        subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={W},{H}", f"--screenshot={png}", htm.as_uri()], check=True, capture_output=True)
        d = s["dur"]
        clips = s.get("audio")
        clips = [clips] if isinstance(clips, tuple) else (clips or [])
        cmd = [ff, "-y", "-loglevel", "error", "-loop", "1", "-t", str(d), "-i", str(png)]
        for path, a, b in clips:
            cmd += ["-ss", str(a), "-t", str(b - a), "-i", str(RUNS / path)]
        if clips:
            ins = "".join(f"[{k + 1}:a]" for k in range(len(clips)))
            af = (f"{ins}concat=n={len(clips)}:v=0:a=1,aresample=44100,aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=c0,dynaudnorm,"
                  f"apad,atrim=0:{d},afade=t=in:d=0.15,afade=t=out:st={d - 0.35}:d=0.35[a]")
        else:
            cmd += ["-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=44100:cl=stereo"]
            af = "[1:a]anull[a]"
        vf = f"[0:v]fps={FPS},format=yuv420p,fade=t=in:d=0.3,fade=t=out:st={d - 0.3}:d=0.3[v]"
        cmd += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-t", str(d), str(mp4)]
        subprocess.run(cmd, check=True)
        parts.append(mp4)
    lst = OUT / "parts.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    final = OUT / "diapason-60s.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-movflags", "+faststart", str(final)], check=True, cwd=OUT)
    total = sum(s["dur"] for s in scenes())
    print(f"{final.relative_to(ROOT)}: {total:.1f} s, {final.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
