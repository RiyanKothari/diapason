"""The QA audit as one self-contained HTML page (Gnani's visual language, light and dark)."""

from __future__ import annotations

from html import escape
from pathlib import Path

from ..report import CSS, _heat_color, _pct
from .scorecard import Scorecard

QA_CSS = """
.bar{height:8px;border-radius:99px;background:var(--soft);overflow:hidden;min-width:80px}.bar i{display:block;height:100%;background:var(--pass)}
.bar.mid i{background:var(--review)}.bar.low i{background:var(--fail)}
.tag{display:inline-block;font-size:11px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted);margin-left:4px}
.tag.fatal{color:var(--fail);border-color:currentColor}.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}.card h3{margin:0 0 8px;font:500 14px var(--sans);color:var(--fg)}
.turn.hit{background:rgba(194,65,12,.08);border-radius:6px}.score{font:400 28px var(--serif);color:var(--fg)}
ul.plain{margin:0;padding-left:18px}svg.spark{display:block;margin:6px 0}.scroll>table{min-width:720px}
"""


def _bar(rate: float | None) -> str:
    if rate is None:
        return '<span class="na">—</span>'
    cls = "" if rate >= 0.85 else " mid" if rate >= 0.5 else " low"
    return f'<div class="bar{cls}" title="{rate:.0%}"><i style="width:{rate * 100:.0f}%"></i></div>'


def _verdict(v: str) -> str:
    cls = {"pass": "pass", "fail": "fail", "review": "review"}.get(v, "na")
    return f'<span class="{cls}">{escape(v)}</span>'


def _spark(sent: list[dict]) -> str:
    if len(sent) < 2:
        return ""
    w, h, n = 220, 40, len(sent)
    pts = " ".join(f"{i * w / (n - 1):.0f},{h / 2 - s['score'] * h / 5:.0f}" for i, s in enumerate(sent))
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-label="caller sentiment">'
            f'<line x1="0" x2="{w}" y1="{h / 2}" y2="{h / 2}" stroke="currentColor" opacity=".15"/>'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="2"/></svg>')


FATAL = '<span class="tag fatal">fatal</span>'


def _call(c: dict, labels: dict[str, str]) -> str:
    hits = {e["turn"] for p in c["params"] for e in p["evidence"] if p["verdict"] in ("fail", "review")}
    rows = "".join(
        f"<tr><td>{escape(labels.get(p['id'], p['id']))}{FATAL if p['fatal'] else ''}</td>"
        f"<td>{_verdict(p['verdict'])}</td><td class='muted'>{'' if p['source'] == 'code' else format(p['agreement'], '.0%')}</td>"
        f"<td>{escape(p['reason'])}" + "".join(f'<div class="ev">T{e["turn"]} · {e.get("t", "")}s · “{escape(e["quote"])}”</div>' for e in p["evidence"])
        + "</td></tr>" for p in c["params"])
    ins = c.get("insights") or {}
    side = ""
    if ins.get("summary"):
        side += f"<p>{escape(ins['summary'])}</p>"
    if ins.get("disposition"):
        side += f"<p class='muted'>Disposition: <b>{escape(ins['disposition'])}</b>" + (
            " · " + ", ".join(f"{escape(k)} = {escape(v)}" for k, v in ins.get("entities", {}).items()) if ins.get("entities") else "") + "</p>"
    if ins.get("sentiment"):
        side += f"<div class='muted'>Caller sentiment (start {ins.get('sentiment_start')} → end {ins.get('sentiment_end')})</div>{_spark(ins['sentiment'])}"
    if ins.get("coaching"):
        side += "<h3>Coaching</h3><ul class='plain'>" + "".join(f"<li>T{x['turn']} ({x['t']}s): {escape(x['tip'])}</li>" for x in ins["coaching"]) + "</ul>"
    transcript = "".join(
        f'<div class="turn{" hit" if i in hits else ""}"><span class="who">T{i} {escape(t["speaker"])} {t["start"]:.1f}s</span>{escape(t["text"])}</div>'
        for i, t in enumerate(c["turns"]))
    review = ("<p class='review'>Needs human review: " + escape("; ".join(c["review"])) + "</p>") if c["review"] else ""
    score = "—" if c["score"] is None else f"{c['score']:g}"
    status = "pass" if c["passed"] else "fail"
    meta = " · ".join(escape(str(c["meta"][k])) for k in ("agent_id", "campaign") if c["meta"].get(k))
    fatal = ' · <span class="fail">fatal: ' + escape(", ".join(c["fatal"])) + "</span>" if c["fatal"] else ""
    flag = ' · <span class="review">review</span>' if c["review"] else ""
    return (f"<details><summary><span class='{status}'>{score}</span> · {escape(c['call_id'])}"
            f"{fatal}{flag} <span class='muted'>{meta}</span></summary>"
            f"{review}<div class='grid2'><div>{side or '<p class=muted>No insights (offline).</p>'}</div>"
            f"<div class='scroll'><table><tr><th>Parameter</th><th>Verdict</th><th>Agree</th><th>Why / evidence</th></tr>{rows}</table></div></div>"
            f"<h3>Transcript</h3>{transcript}</details>")


def write_html(data: dict, card: Scorecard, path: str | Path) -> None:
    s = data["summary"]
    labels = {p.id: p.label for p in card.parameters()}
    kpis = [("Calls audited", f"{s['audited']}/{s['calls']}"), ("Average score", s["avg_score"] if s["avg_score"] is not None else "—"),
            ("Pass rate", _pct(s["pass_rate"])), ("Fatal-error calls", _pct(s["fatal_rate"])),
            ("Need human review", len(s["review_queue"]))]
    if s["sentiment"]["calls"]:
        kpis.append(("Sentiment improved", f"{s['sentiment']['improved']}/{s['sentiment']['calls']}"))
    kpi_html = "".join(f"<div class='kpi'><span class='muted'>{k}</span><b>{escape(str(v))}</b></div>" for k, v in kpis)

    sections = "".join(f"<tr><td>{escape(v['name'])}</td><td>{'—' if v['avg'] is None else v['avg']}</td>"
                       f"<td>{_bar(None if v['avg'] is None else v['avg'] / 100)}</td></tr>" for v in s["sections"].values())
    prow = []
    for pid, p in s["parameters"].items():
        reason = escape(p["top_reasons"][0]["reason"]) if p["top_reasons"] else ""
        ex = p["examples"][0] if p["examples"] else None
        quote = f'<div class="ev">{escape(ex["call_id"])} T{ex["turn"]}: “{escape(ex["quote"])}”</div>' if ex else ""
        agree = "" if p["avg_agreement"] is None else f"{p['avg_agreement']:.0%}"
        prow.append(f"<tr><td>{escape(p['label'])}{FATAL if p['fatal'] else ''}"
                    f"<span class='tag'>{'Evon' if p['type'] == 'llm' else 'code'}</span></td><td>{_bar(p['pass_rate'])}</td>"
                    f"<td>{_pct(p['pass_rate'])}</td><td>{p['fails']}</td><td>{p['review']}</td><td class='muted'>{agree}</td>"
                    f"<td>{reason}{quote}</td></tr>")

    groups = ""
    for key, g in s["groups"].items():
        if not g:
            continue
        pids = list(s["parameters"])
        head = "".join(f"<th>{escape(labels[p])}</th>" for p in pids)
        body = "".join(
            f"<tr><th>{escape(name)}</th><td>{v['calls']}</td><td>{v['avg_score'] if v['avg_score'] is not None else '—'}</td>"
            f"<td>{_pct(v['pass_rate'])}</td>"
            + "".join(f'<td class="cell" style="background:{_heat_color(v["param_pass_rates"][p])}">{_pct(v["param_pass_rates"][p])}</td>'
                      if p in v["param_pass_rates"] else "<td></td>" for p in pids) + "</tr>"
            for name, v in g.items())
        coach = "".join(f"<div class='card'><h3>{escape(name)} · weakest: {escape(labels.get(v['weakest'], v['weakest'] or '—'))}</h3>"
                        + ("<ul class='plain'>" + "".join(f"<li>{escape(t['tip'])} <span class='muted'>({escape(t['call_id'])})</span></li>" for t in v["coaching"]) + "</ul>" if v["coaching"] else "<span class='muted'>No coaching notes.</span>")
                        + "</div>" for name, v in g.items())
        groups += (f"<h2>By {escape(key.replace('_', ' '))}</h2><div class='scroll'><table><tr><th></th><th>Calls</th><th>Avg</th><th>Pass</th>{head}</tr>"
                   f"{body}</table></div><div class='grid2' style='margin-top:12px'>{coach}</div>")

    def counts(title: str, items) -> str:
        items = list(items.items()) if isinstance(items, dict) else items
        if not items:
            return ""
        return f"<div class='card'><h3>{title}</h3><ul class='plain'>" + "".join(f"<li>{escape(str(k))} — {n}</li>" for k, n in items) + "</ul></div>"
    mix = counts("Dispositions", s["dispositions"]) + counts("Topics", s["topics"]) + counts("Root causes", [(x["root_cause"], x["n"]) for x in s["root_causes"]])

    extra = ""
    cal = s.get("calibration")
    if cal and cal.get("overall"):
        o = cal["overall"]
        extra += (f"<h2>Agreement with human QA</h2><p>{o['n']} labelled verdicts: {o['agreement']:.0%} agreement, Cohen's κ "
                  f"{o['kappa'] if o['kappa'] is not None else '—'}, fail recall {_pct(o['fail_recall'])}, fail precision {_pct(o['fail_precision'])}.</p>")
    dr = s.get("drift")
    if dr:
        moved = "".join(f"<li>{escape(labels.get(m['parameter'], m['parameter']))}: {_pct(m['before'])} → {_pct(m['after'])}</li>" for m in dr["moved"])
        extra += (f"<h2>Since the last audit</h2><p>Average score change: {dr['avg_score_change'] if dr['avg_score_change'] is not None else '—'}"
                  f" · pass rate {_pct(dr['pass_rate_before'])} → {_pct(dr['pass_rate_after'])}</p>" + (f"<ul>{moved}</ul>" if moved else ""))

    queue = "".join(f"<tr><td>{escape(q['call_id'])}</td><td>{q['score'] if q['score'] is not None else '—'}</td><td>{escape('; '.join(q['reasons']))}</td></tr>"
                    for q in s["review_queue"])
    calls = "".join(_call(c, labels) for c in sorted(data["calls"], key=lambda c: (c["score"] is None, c["score"] or 0)))
    usage = data.get("usage") or {}
    cov = s["coverage"]
    foot = (f"{cov['timed_calls']} calls with timing · {cov['talk_minutes']} talk minutes · {cov['audio_minutes']} audio minutes transcribed · "
            f"{cov['judge_samples']} Evon judge samples" + (f" · usage {escape(str(usage))}" if usage else ""))
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA Audit</title><link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Instrument+Serif&display=swap" rel="stylesheet">
<style>{CSS}{QA_CSS}</style></head><body><main>
<p class="muted">Bhool Bhulaiya · Quality audit · {escape(data['generated'])}</p>
<h1>{escape(s['scorecard'])}</h1>
<p class="muted">Pass mark {s['pass_mark']:g}. Code-checked parameters are exact; Evon parameters are majority-voted with transcript-verified quotes, and anything uncertain goes to a human.</p>
<div class="kpis">{kpi_html}</div>{extra}
<h2>Sections</h2><table><tr><th>Section</th><th>Average</th><th></th></tr>{sections}</table>
<h2>Parameters</h2><div class="scroll"><table><tr><th>Parameter</th><th></th><th>Pass</th><th>Fails</th><th>Review</th><th>Agree</th><th>Top reason · example</th></tr>{''.join(prow)}</table></div>
{groups}
{'<h2>What the calls were about</h2><div class="grid2">' + mix + '</div>' if mix else ''}
{'<h2>Human review queue</h2><div class="scroll"><table><tr><th>Call</th><th>Score</th><th>Why</th></tr>' + queue + '</table></div>' if queue else ''}
<h2>Calls</h2>{calls}
<p class="muted" style="margin-top:32px">{foot}</p>
</main></body></html>"""
    Path(path).write_text(page, encoding="utf-8")
