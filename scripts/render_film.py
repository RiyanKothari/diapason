"""Render the film (site/watch.html, or the 60-second cut) to an MP4 with its real audio.

The film is drawn frame by frame on a fixed clock: for each of 30 frames a second the page is moved to that instant
(its own seek), every CSS fade and pop is stepped to the same instant, and the frame is captured and piped to ffmpeg.
Recording it in real time dropped frames whenever the page was busy, which played back as jitter; a fixed clock cannot
drop one. ffmpeg then lays the live call's own recording under the call scene, at the speed and moment the page plays
it. Nothing is re-created: it is the same page a visitor sees, captured.

    diapason site && .venv/Scripts/python.exe scripts/render_film.py --cut 60      # needs Chrome and: pip install -e ".[video]"
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def payload(page: Path) -> dict:
    m = re.search(r"const FILM = (.*?);\nconst S = ", page.read_text(encoding="utf-8"), re.S)
    if not m:
        raise SystemExit(f"{page} has no film data; build it with `diapason site`")
    return json.loads(m.group(1))


def serve(folder: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(folder))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# Freeze the page's own clock and hand frame control to the renderer: seek(t) draws the film at t, and each CSS animation
# (a fade, a pop, a blinking dot) is paused when it first appears and then set to the time elapsed since then.
FREEZE = """(() => {
  const s = document.getElementById("start"); if (s) s.remove();
  playing = false;
  const born = new Map();
  window.__frame = (t) => {
    seek(t);
    for (const a of document.getAnimations()) {
      if (!born.has(a)) { born.set(a, t); a.pause(); }
      a.currentTime = (t - born.get(a)) * 1000;
    }
    return true;
  };
})()"""


def render(url: str, seconds: float, fps: int, encode: list[str]) -> int:
    """Capture every frame of the film at a fixed rate and pipe it to ffmpeg; returns the number of frames."""
    from playwright.sync_api import sync_playwright
    n = round(seconds * fps)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", args=["--mute-audio"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(url, wait_until="networkidle")
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_timeout(500)
        page.evaluate(FREEZE)
        proc = subprocess.Popen(encode, stdin=subprocess.PIPE)
        try:
            for k in range(n):
                page.evaluate("t => window.__frame(t)", k / fps)
                proc.stdin.write(page.screenshot(type="jpeg", quality=93))
                if k % (fps * 10) == 0:
                    print(f"  {k / fps:4.0f} s of {seconds:.0f} s", flush=True)
        finally:
            proc.stdin.close()
            proc.wait()
        browser.close()
    if proc.returncode:
        raise SystemExit(f"ffmpeg failed ({proc.returncode})")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cut", choices=["full", "60"], default="full")
    ap.add_argument("--site", type=Path, default=ROOT / "site")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    page = a.site / ("watch-60.html" if a.cut == "60" else "watch.html")
    film = payload(page)
    out = a.out or ROOT / "runs" / "video" / f"diapason-film{'-60s' if a.cut == '60' else ''}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    starts, acc = [], 0.0
    for s in film["scenes"]:
        starts.append(acc)
        acc += s["dur"]
    total = film["total"]
    call = next(((s, starts[i]) for i, s in enumerate(film["scenes"]) if s["type"] == "call"), None)

    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    fps = 30
    srv, base = serve(a.site)
    try:
        cmd = [ff, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-"]
        if call:
            s, at = call
            cmd += ["-i", str(a.site / s["audio"]), "-filter_complex",
                    f"[1:a]atrim=0:{s['length']},asetpts=PTS-STARTPTS,atempo={s['rate']},adelay={int(at * 1000)}:all=1,apad[a]",
                    "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-movflags", "+faststart", str(out)]
        frames = render(f"{base}/{page.name}?record", total, fps, cmd)
    finally:
        srv.shutdown()
    print(f"{out}  ({total:.0f} s, {frames} frames at {fps} fps, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
