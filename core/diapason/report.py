"""Render a SuiteReport as a self-contained HTML page and as JUnit XML for CI."""

from __future__ import annotations

from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

CSS = """
@import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans+Devanagari:wght@400;500&family=Noto+Sans+Gujarati:wght@400;500&display=swap");
:root{color-scheme:dark;--bg:#04050a;--fg:#f5f6ff;--text:#c6cbdd;--muted:#80879e;--card:rgba(15,18,31,.82);--soft:rgba(255,255,255,.06);
  --line:rgba(150,160,255,.13);--pass:#43e398;--fail:#ff5f73;--review:#ffc14d;--cyan:#38e3d6;
  --grad:linear-gradient(105deg,#b3a6ff 0%,#7b93ff 42%,#38e3d6 100%);
  --serif:"Instrument Serif",Georgia,serif;--sans:Inter,"Noto Sans Devanagari","Noto Sans Gujarati",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;color:var(--text);font:15px/1.6 var(--sans);-webkit-font-smoothing:antialiased;
  background:radial-gradient(900px 600px at 50% -200px,rgba(122,104,255,.22),transparent 70%),
  radial-gradient(rgba(160,170,255,.09) 1px,transparent 1.2px) 0 0/26px 26px,var(--bg)}
::selection{background:rgba(154,138,255,.35);color:#fff}
main{max-width:1120px;margin:0 auto;padding:48px 20px 80px}
a{color:var(--fg);text-decoration-color:rgba(154,138,255,.5);text-underline-offset:3px}
h1{font:400 clamp(34px,5vw,54px)/1.02 var(--serif);letter-spacing:-.02em;color:var(--fg);margin:0 0 8px}
h1:before{content:"DIAPASON";display:block;font:600 11px/1 var(--mono);letter-spacing:.18em;color:var(--cyan);margin-bottom:16px}
h2{font:400 28px/1.1 var(--serif);color:var(--fg);margin:44px 0 14px;letter-spacing:-.01em}
h3{color:var(--fg)}
.muted{color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:26px 0}
.kpi{position:relative;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;overflow:hidden}
.kpi:after{content:"";position:absolute;left:18px;right:18px;top:0;height:1px;background:var(--grad);opacity:.5}
.kpi b{display:block;font:500 28px/1.2 var(--mono);color:var(--fg);letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi span,.kpi div{font-size:12.5px;color:var(--muted)}
.gate{display:inline-block;vertical-align:middle;padding:4px 12px;border-radius:999px;font:600 11px var(--mono);letter-spacing:.08em;border:1px solid currentColor}
.gate.ok{color:var(--pass);background:rgba(67,227,152,.1)}.gate.no{color:var(--fail);background:rgba(255,95,115,.1)}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden}
th,td{padding:11px 12px;border-bottom:1px solid rgba(255,255,255,.06);text-align:left;vertical-align:top}
th{font:500 11px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
tr:last-child td{border-bottom:0}tbody tr:hover{background:rgba(154,138,255,.05)}
.scroll{overflow-x:auto}.cell{font:600 13px var(--mono);text-align:center;color:var(--fg)}
.pass{color:var(--pass)}.fail{color:var(--fail)}.review{color:var(--review)}.na{color:var(--muted)}
details{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:10px 0;padding:13px 16px}
details[open]{border-color:rgba(154,138,255,.35)}summary{cursor:pointer;font-weight:500;color:var(--fg)}
.turn{margin:4px 0}.turn .who{display:inline-block;min-width:70px;font:500 11px var(--mono);color:var(--muted)}
audio{width:100%;margin:10px 0;filter:invert(.9) hue-rotate(180deg)}
.ev{font-size:13px;border-left:2px solid var(--cyan);padding-left:10px;margin:5px 0}
code{font:12.5px var(--mono);background:var(--soft);border:1px solid rgba(255,255,255,.07);border-radius:6px;padding:1px 6px;color:var(--fg)}
"""


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def _heat_color(rate: float) -> str:
    # red -> amber -> green, readable in both themes via alpha
    if rate >= 0.85:
        return "rgba(31,122,77,.16)"
    if rate >= 0.5:
        return "rgba(161,98,7,.16)"
    return "rgba(194,65,12,.18)"


def write_html(report, path: str | Path) -> None:
    r = report
    gate = '<span class="gate ok">GATE PASSED</span>' if r.gate_passed else '<span class="gate no">GATE FAILED</span>'
    channels = sorted({c for row in r.heatmap.values() for c in row})
    heat_rows = "".join(
        f"<tr><th>{escape(p)}</th>" + "".join(
            f'<td class="cell" style="background:{_heat_color(row[c])}">{_pct(row[c])}</td>' if c in row else "<td></td>"
            for c in channels) + "</tr>"
        for p, row in sorted(r.heatmap.items())
    )
    crit = "".join(f"<tr><td>{escape(k)}</td><td>{v}</td></tr>"
                   for k, v in sorted(r.criteria_failures.items(), key=lambda kv: -kv[1]))
    beh = "".join(f"<tr><td>{escape(k)}</td><td>{_pct(v)}</td></tr>" for k, v in sorted(r.behaviour_pass_rate.items()))

    calls = {(c["scenario_id"], c["run"]): c for c in r.calls_detail}
    blocks = []
    for v in sorted(r.verdicts, key=lambda v: (v["passed"], v["scenario_id"], v["run"])):
        c = calls.get((v["scenario_id"], v["run"]), {})
        status = '<span class="pass">PASS</span>' if v["passed"] else '<span class="fail">FAIL</span>'
        rows = "".join(
            f'<tr><td>{escape(x["id"])}{" *" if x["critical"] else ""}</td><td class="{x["verdict"]}">{x["verdict"]}</td>'
            f'<td>{x["agreement"]:.0%}</td><td>{escape(x["reason"])}'
            + "".join(f'<div class="ev">T{e["turn"]}: “{escape(str(e["quote"]))}”</div>' for e in x["evidence"])
            + "</td></tr>"
            for x in v["criteria"]
        )
        turns = "".join(
            f'<div class="turn"><span class="who">{t["start"]:.1f}s {escape(t["speaker"])}</span>{escape(t["text"])}'
            f'{" <em class=muted>(interjection)</em>" if t.get("kind") == "interjection" else ""}</div>'
            for t in c.get("turns", [])
        )
        m = c.get("metrics", {})
        audio = f'<audio controls preload="none" src="{escape(v["scenario_id"])}/run{v["run"]}/mix.wav"></audio>' if c.get("caller_wav") else ""
        mf = "".join(f'<div class="fail">• {escape(f)}</div>' for f in v["metric_failures"])
        blocks.append(f"""<details{'' if v['passed'] else ' open'}><summary>{status} · {escape(v['scenario_id'])} · run {v['run']}
<span class="muted"> · {c.get('end_reason', '')} · {c.get('duration_s', 0):.0f}s · p95 {m.get('latency_p95_s') or '—'}s</span></summary>
{audio}{mf}<p class="muted">{escape(v.get('summary') or '')}</p>
<div class="scroll"><table><tr><th>criterion (* critical)</th><th>verdict</th><th>agree</th><th>reason / evidence</th></tr>{rows}</table></div>
<h3 style="font-size:14px">Transcript</h3>{turns}</details>""")

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Diapason report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Instrument+Serif&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<h1>{escape(r.suite)} {gate}</h1><div class="muted">run {escape(r.run_id)} · started {escape(r.started_at)} · {r.duration_s:.0f}s</div>
{''.join(f'<div class="fail">• {escape(x)}</div>' for x in r.gate_reasons)}
<div class="kpis"><div class="kpi"><span class="muted">Pass rate</span><b>{_pct(r.pass_rate)}</b></div>
<div class="kpi"><span class="muted">Calls</span><b>{r.calls}</b></div>
<div class="kpi"><span class="muted">Latency p50</span><b>{r.latency_p50_s if r.latency_p50_s is not None else '—'}s</b></div>
<div class="kpi"><span class="muted">Latency p95</span><b>{r.latency_p95_s if r.latency_p95_s is not None else '—'}s</b></div>
<div class="kpi"><span class="muted">Flaky scenarios</span><b>{sum(s.flaky for s in r.scenarios)}</b></div></div>
<h2>Pass rate by persona × phone line</h2><div class="scroll"><table><tr><th></th>{''.join(f'<th>{escape(c)}</th>' for c in channels)}</tr>{heat_rows}</table></div>
<h2>Pass rate by caller behaviour</h2><table>{beh}</table>
<h2>What failed most</h2><table><tr><th>criterion / metric</th><th>failed calls</th></tr>{crit or '<tr><td colspan=2 class=muted>nothing</td></tr>'}</table>
<h2>Calls</h2>{''.join(blocks)}
<p class="muted">Usage: {escape(str(r.usage))}</p></main></body></html>"""
    Path(path).write_text(html, encoding="utf-8")


def write_junit(report, path: str | Path) -> None:
    suite = ET.Element("testsuite", name=report.suite, tests=str(report.calls),
                       failures=str(sum(not v["passed"] for v in report.verdicts)), time=str(report.duration_s))
    for v in report.verdicts:
        case = ET.SubElement(suite, "testcase", classname=report.suite, name=f'{v["scenario_id"]}#run{v["run"]}')
        if not v["passed"]:
            reasons = [f'{c["id"]}: {c["verdict"]} {c["reason"]}' for c in v["criteria"] if c["verdict"] in ("fail", "review")]
            reasons += v["metric_failures"]
            ET.SubElement(case, "failure", message="; ".join(reasons)[:500]).text = "\n".join(reasons)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
