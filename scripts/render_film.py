"""Render the film (site/watch.html, or the 60-second cut) to an MP4 with its real audio.

The film plays in headless Chrome in real time and is screen-recorded at 1920x1080; ffmpeg then lays the live call's own
recording under the call scene, at the speed and moment the page plays it. Nothing is re-created: it is the same page a
visitor sees, captured.

    diapason site && .venv/Scripts/python.exe scripts/render_film.py --cut 60      # needs Chrome and: pip install -e ".[video]"
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
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


def record(url: str, seconds: float, tmp: Path) -> tuple[Path, float]:
    """Screen-record the film from its first frame; returns the video and how long it ran before the film started."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(tmp),
                                  record_video_size={"width": 1920, "height": 1080})
        born = time.time()
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle")
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_timeout(500)
        page.click("#start")
        lead = time.time() - born
        page.wait_for_timeout(int((seconds + 1.0) * 1000))
        video = Path(page.video.path())
        ctx.close()
        browser.close()
    return video, lead


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
    srv, base = serve(a.site)
    tmp = Path(tempfile.mkdtemp(prefix="film-"))
    try:
        video, lead = record(f"{base}/{page.name}?record", total, tmp)
        cmd = [ff, "-y", "-loglevel", "error", "-ss", f"{lead:.3f}", "-i", str(video)]
        if call:
            s, at = call
            cmd += ["-i", str(a.site / s["audio"]), "-filter_complex",
                    f"[1:a]atrim=0:{s['length']},asetpts=PTS-STARTPTS,atempo={s['rate']},adelay={int(at * 1000)}:all=1,apad[a]",
                    "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-r", "30", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{out}  ({total:.0f} s, {out.stat().st_size / 1e6:.1f} MB, lead-in trimmed {lead:.2f} s)")


if __name__ == "__main__":
    main()
