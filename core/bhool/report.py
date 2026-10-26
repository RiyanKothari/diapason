"""Render a SuiteReport as a self-contained HTML page and as JUnit XML for CI."""

from __future__ import annotations

from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--card:#fff;--line:#e6e3dc;--pass:#2f7d4f;--fail:#b3402f;--review:#a8741a;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#9b9a94;--card:#1f1f1c;--line:#33322e;--pass:#5cbf83;--fail:#e97a68;--review:#e0b25a;--accent:#8ea4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 12px}
.muted{color:var(--muted)}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.kpi b{display:block;font-size:22px}
.gate{display:inline-block;padding:4px 10px;border-radius:999px;font-weight:600;color:#fff}.gate.ok{background:var(--pass)}.gate.no{background:var(--fail)}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-weight:600;font-size:13px;color:var(--muted)}
.scroll{overflow-x:auto}.cell{font-weight:600;text-align:center}
.pass{color:var(--pass)}.fail{color:var(--fail)}.review{color:var(--review)}.na{color:var(--muted)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:10px 14px}summary{cursor:pointer;font-weight:600}
.turn{margin:2px 0}.turn .who{display:inline-block;min-width:64px;font-size:12px;color:var(--muted)}audio{width:100%;margin:8px 0}
.ev{font-size:13px;border-left:3px solid var(--line);padding-left:8px;margin:4px 0}code{font-size:13px}
"""


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def _heat_color(rate: float) -> str:
    # red -> amber -> green, readable in both themes via alpha
    if rate >= 0.85:
        return "rgba(47,125,79,.28)"
    if rate >= 0.5:
        return "rgba(168,116,26,.28)"
    return "rgba(179,64,47,.30)"


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
<title>Bhool Bhulaiya report</title><style>{CSS}</style></head><body><main>
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
