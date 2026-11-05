"""`diapason load`: how an agent's latency and correctness degrade as simultaneous calls rise.

At each level N, N calls run at once (scenarios cycled to fill the level). The output is a
curve of p50/p95 response latency and pass rate against concurrency: the knee is the
agent's real capacity per instance.
"""

from __future__ import annotations

import itertools
import json
from html import escape
from pathlib import Path

from .runner import run_suite
from .scenarios import Scenario, Suite


async def run_load(suite: Suite, levels: list[int], components, out_dir: str | Path, scenarios: list[Scenario] | None = None,
                   label: str = "", on_event=None, mix: bool = False) -> dict:
    """mix=False (default) runs one scenario at every level, so only the load changes between points."""
    base = scenarios or suite.expand()
    if not mix:
        base = base[:1]
    suite = suite.model_copy(update={"runs_per_scenario": 1})
    points = []
    for n in levels:
        # Cycle scenarios to exactly n calls; suffix ids so each call has its own recording dir.
        batch = [s.model_copy(update={"id": f"{s.id}__c{i}", "seed": s.seed + i})
                 for i, s in zip(range(n), itertools.cycle(base))]
        rep = await run_suite(suite, components.connect, components.make_brain, components.speak, components.hear,
                              evon_judge=components.evon_judge, out_dir=Path(out_dir) / f"level-{n}", concurrency=n,
                              scenarios=batch, call_kwargs=components.call_kwargs, label=f"{label} x{n}", on_event=on_event)
        errors = n - rep.calls
        points.append({"concurrency": n, "calls": rep.calls, "errors": errors, "pass_rate": rep.pass_rate,
                       "latency_p50_s": rep.latency_p50_s, "latency_p95_s": rep.latency_p95_s, "report": rep.dir})
    return {"suite": suite.name, "label": label, "scenario": base[0].id if len(base) == 1 else "mixed", "points": points}


def write_load_report(result: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "load.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    pts = result["points"]
    w, h, pad = 640, 260, 40
    xs = [p["concurrency"] for p in pts]
    ys = [v for p in pts for v in (p["latency_p50_s"], p["latency_p95_s"]) if v is not None] or [1]
    xmax, ymax = max(xs), max(ys) * 1.15

    def xy(c, v):
        return pad + (c / xmax) * (w - 2 * pad), h - pad - (v / ymax) * (h - 2 * pad)

    def line(key, color):
        p = [xy(q["concurrency"], q[key]) for q in pts if q[key] is not None]
        dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>' for x, y in p)
        return f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in p)}"/>{dots}'

    ticks = "".join(f'<text x="{xy(c, 0)[0]:.1f}" y="{h - pad + 16}" text-anchor="middle" font-size="11" fill="currentColor">{c}</text>' for c in xs)
    svg = (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="latency vs concurrency">'
           f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="currentColor" opacity=".3"/>'
           f'{line("latency_p50_s", "#3b5bdb")}{line("latency_p95_s", "#b3402f")}{ticks}'
           f'<text x="{pad}" y="{pad - 12}" font-size="12" fill="currentColor">response latency (s), max {ymax:.2f}</text></svg>')
    rows = "".join(f"<tr><td>{p['concurrency']}</td><td>{p['calls']}</td><td>{p['errors']}</td><td>{p['pass_rate']:.0%}</td>"
                   f"<td>{p['latency_p50_s']}</td><td>{p['latency_p95_s']}</td></tr>" for p in pts)
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Load test</title><style>:root{{--bg:#fbfaf7;--fg:#1d1d1b;--line:#e6e3dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe6;--line:#33322e}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}main{{max-width:760px;margin:0 auto;padding:24px 16px}}
table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid var(--line);padding:7px;text-align:left}}</style></head><body><main>
<h1>{escape(result['suite'])} under load {escape(result['label'])}</h1>
<p><span style="color:#3b5bdb">p50</span> and <span style="color:#b3402f">p95</span> response latency by number of simultaneous calls.</p>
{svg}<table><tr><th>concurrent calls</th><th>judged</th><th>errors</th><th>pass rate</th><th>p50 s</th><th>p95 s</th></tr>{rows}</table>
</main></body></html>"""
    path = out / "load.html"
    path.write_text(html, encoding="utf-8")
    return path
