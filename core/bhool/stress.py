"""`bhool stress`: where does the agent stop hearing its customers?

The agent's ears (its voice-activity detection and endpointing) are code, not a model, so this needs no Evon and no
credits: the same caller phones the agent through a phone line whose noise is stepped down from 30 dB SNR to 0 dB, for
each kind of noise an Indian caller has around them (a ceiling fan, traffic, a crowded market, an office). A level
"holds" when the agent answered every turn and the call ended normally. The breaking point is the first level, going
down, where it didn't.
"""

from __future__ import annotations

import json
import time
from html import escape
from pathlib import Path

NOISES = ["fan", "traffic", "office", "crowd"]
LEVELS = [30, 20, 15, 10, 5, 0]
HEARING = ("never answered", "agent_silent", "max_duration")     # the agent missed the caller, as opposed to other faults


def sweep_suite(base, noises=NOISES, levels=LEVELS, runs: int = 1):
    from .scenarios.schema import Suite
    data = base.model_dump(mode="json")
    persona = data["personas"][0]
    coop = next(b for b in data["behaviours"] if b["id"] == "cooperative")
    data.update(name=f"{base.name}-stress", personas=[persona], behaviours=[coop], matrix=None, runs_per_scenario=runs,
                channels=[{"id": f"{n}_{s}", "noise": n, "snr_db": s} for n in noises for s in levels],
                cases=[{"id": f"{n}_{s}", "persona": persona["id"], "behaviour": "cooperative", "channel": f"{n}_{s}"}
                       for n in noises for s in levels])
    return Suite.model_validate(data)


def breaking_points(grid: dict[str, dict[int, bool]], levels=LEVELS) -> dict[str, dict]:
    out = {}
    for noise, row in grid.items():
        holds, breaks = None, None
        for snr in sorted(levels, reverse=True):
            if row.get(snr) is None:
                continue
            if row[snr]:
                holds = snr
            else:
                breaks = snr
                break
        out[noise] = {"holds_to": holds, "breaks_at": breaks}
    return out


def heard_grid(rep: dict, noises=NOISES) -> dict[str, dict[int, bool]]:
    """noise -> SNR -> heard, from a sweep run's report: a level holds only if every call at it was heard."""
    grid: dict[str, dict[int, bool]] = {n: {} for n in noises}
    for vd in rep["verdicts"]:
        noise, snr = vd["scenario_id"].rsplit("_", 1)
        ok = not any(h in f for f in vd["metric_failures"] for h in HEARING)
        grid.setdefault(noise, {})[int(snr)] = grid.get(noise, {}).get(int(snr), True) and ok
    return grid


async def run_stress(out: Path, versions: list[str], evon=None, noises=NOISES, levels=LEVELS, runs: int = 1,
                     suite_path: str = "suites/proof.yaml", on_event=None) -> dict:
    from .demo import run_version
    from .scenarios import load_suite
    out.mkdir(parents=True, exist_ok=True)
    base = load_suite(suite_path)
    results = {}
    for v in versions:
        # hear_callers: the agent decodes the caller's actual words (noise decodes to nothing), so a reply to a burst of
        # babble is impossible and every reply is to the customer
        rep = (await run_version(v, sweep_suite(base, noises, levels, runs), out, on_event, evon=evon, judge_samples=1,
                                 label=f"reference agent {v}: noise sweep", hear_callers=True)).to_dict()
        grid = heard_grid(rep, noises)
        results[v] = {"grid": {n: {str(k): val for k, val in row.items()} for n, row in grid.items()},
                      "points": breaking_points(grid, levels), "report_dir": Path(rep["dir"]).name}
    data = {"generated": time.strftime("%Y-%m-%d %H:%M"), "mode": "Evon brains" if evon else "offline (scripted brains; the ears are the agent's real code)",
            "levels": levels, "noises": noises, "versions": results}
    (out / "stress.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    write_html(data, out / "stress.html")
    return data


def write_html(data: dict, path: Path) -> None:
    from .report import CSS
    levels = data["levels"]
    head = "".join(f"<th>{s} dB</th>" for s in levels)
    rows = ""
    for v, r in data["versions"].items():
        for n in data["noises"]:
            cells = "".join(
                f"<td class='{'pass' if r['grid'][n].get(str(s)) else 'fail' if r['grid'][n].get(str(s)) is False else 'na'}' style='text-align:center'>"
                f"{'heard' if r['grid'][n].get(str(s)) else 'missed' if r['grid'][n].get(str(s)) is False else '—'}</td>" for s in levels)
            p = r["points"][n]
            verdict = (f"holds to {p['holds_to']} dB" if p["breaks_at"] is None else
                       f"breaks at {p['breaks_at']} dB" + (f" (holds to {p['holds_to']})" if p["holds_to"] is not None else ""))
            rows += f"<tr><td><b>{escape(v)}</b></td><td>{escape(n)}</td>{cells}<td><b>{escape(verdict)}</b></td></tr>"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Noise Breaking Point</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Instrument+Serif&display=swap" rel="stylesheet">
<style>{CSS}.scroll>table{{min-width:760px}}</style></head><body><main>
<p class="muted">Bhool Bhulaiya · noise breaking point · {escape(data['generated'])} · {escape(data['mode'])}</p>
<h1>Where does the agent stop hearing its customers?</h1>
<p class="muted">The same caller phones the agent through a phone line whose noise is stepped down from {levels[0]} dB SNR to {levels[-1]} dB:
a ceiling fan, traffic, an office, a crowded market. "Heard" means the agent answered every turn and the call ended normally.
Lower is better: an agent that holds to 5 dB hears a customer standing in traffic.</p>
<div class="scroll"><table><tr><th>Agent</th><th>Noise</th>{head}<th>Result</th></tr>{rows}</table></div>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
