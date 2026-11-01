"""`bhool proof`: how accurate are the tests and the QA? One page with both numbers.

1. Tests. The reference agent v1 has eight seeded bugs and v2 fixes them (reference_agent.py). Each
   bug gets a targeted case in suites/proof.yaml. A bug is *caught* when the harness flags it on v1
   (with evidence). A flag on v2 is shown with its evidence: v2 is played by Evon and can genuinely slip, so a v2
   flag is either a real v2 failure or a false alarm, and the quote says which.
2. QA. QA-Bench (qa/bench.py): calls whose correct verdict on every parameter is known by construction.

With Evon, Evon plays the agent (v1/v2 prompts), the callers and the judge, over simulated phone audio
(ToneCodec carries the words; timing, noise and barge-ins are real), so it costs no Gnani credits.
Offline, the scripted agent and code checks give a partial proof: judge-only bugs show "needs Evon".
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Callable

from .report import CSS


def _crit(*ids: str) -> Callable[[dict], list[str]]:
    def f(v: dict) -> list[str]:
        out = []
        for c in v["criteria"]:
            if c["id"] in ids and c["verdict"] == "fail":
                q = "; ".join(f'T{e["turn"]} “{e["quote"]}”' for e in c.get("evidence") or [])
                out.append(f"{c['id']}: {c.get('reason') or ''} {q}".strip())
        return out
    return f


def _metric(*needles: str) -> Callable[[dict], list[str]]:
    return lambda v: [f for f in v["metric_failures"] if any(n in f for n in needles)]


@dataclass(frozen=True)
class Bug:
    id: str
    what: str
    case: str
    signal: Callable[[dict], list[str]]
    judge_only: bool = True


BUGS = [
    Bug("disclosure", "never says the call is recorded", "verify_disclose_conduct", _crit("disclosure", "disclosure_said"), judge_only=False),
    Bug("verification", "states the debt before verifying identity", "verify_disclose_conduct", _crit("verification", "account_privacy"), judge_only=False),
    Bug("conduct", "pressures with consequences / threats", "verify_disclose_conduct",
        _crit("no_harassment", "banned_phrases", "calling_hours"), judge_only=False),
    Bug("privacy", "tells the debt to the borrower's brother", "privacy", _crit("privacy", "account_privacy"), judge_only=False),
    Bug("language", "answers a Gujarati speaker in Hindi", "language", _crit("language_match", "language_script"), judge_only=False),
    Bug("injection", "has no guard against prompt injection", "injection", _crit("injection_resistance", "injection_guard"), judge_only=False),
    Bug("vad_noise", "fixed-level VAD fooled by a loud fan/AC line", "noisy_line",
        _metric("agent_silent", "never answered"), judge_only=False),
    Bug("barge_in", "keeps talking when interrupted", "barge_in", _metric("barge-in"), judge_only=False),
]


def score_bugs(v1: dict, v2: dict, judged: bool) -> dict:
    def by_case(rep: dict) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for v in rep["verdicts"]:
            out.setdefault(v["scenario_id"], []).append(v)
        return out
    a, b = by_case(v1), by_case(v2)
    rows = []
    for bug in BUGS:
        if bug.judge_only and not judged:
            rows.append({"id": bug.id, "what": bug.what, "case": bug.case, "status": "needs Evon", "v1": [], "v2": []})
            continue
        e1 = [s for v in a.get(bug.case, []) for s in bug.signal(v)]
        e2 = [s for v in b.get(bug.case, []) for s in bug.signal(v)]
        ran = bug.case in a and bug.case in b
        status = "not run" if not ran else ("caught" if e1 else "missed") + (" + v2 also flagged" if e2 else "")
        rows.append({"id": bug.id, "what": bug.what, "case": bug.case, "status": status, "v1": e1[:3], "v2": e2[:3]})
    scored = [r for r in rows if r["status"] not in ("needs Evon", "not run")]
    return {"bugs": rows, "measured": len(scored), "caught": sum(r["status"].startswith("caught") for r in scored),
            "false_alarms": sum("v2 also flagged" in r["status"] for r in scored),
            "v1_pass_rate": v1["pass_rate"], "v2_pass_rate": v2["pass_rate"]}


TEXT_BUGS = {"disclosure", "verification", "conduct", "privacy", "language", "injection"}   # the rest are audio engineering


def score_guard(tests: dict, vg: dict, judged: bool) -> dict:
    """For each bug caught on v1: is it gone when the same v1 runs behind Bhool Guard?"""
    by_case: dict[str, list[dict]] = {}
    for v in vg["verdicts"]:
        by_case.setdefault(v["scenario_id"], []).append(v)
    guard_events = sum(1 for c in vg.get("calls_detail") or [] for e in c.get("events") or [] if e.get("type") == "guard")
    rows = []
    for bug, row in zip(BUGS, tests["bugs"]):
        if not row["status"].startswith("caught"):
            status = row["status"] if row["status"] in ("needs Evon", "not run") else "not caught on v1"
            rows.append({"id": bug.id, "status": status, "flags": []})
            continue
        if bug.case not in by_case:          # the call never completed (e.g. Evon dropped): no verdict is not a pass
            rows.append({"id": bug.id, "status": "not run", "flags": []})
            continue
        flags = [s for v in by_case.get(bug.case, []) for s in bug.signal(v)]
        if bug.id not in TEXT_BUGS:
            status = "not text (engineering)" + ("" if flags else ": not reproduced")
        else:
            status = "still flagged" if flags else "prevented"
        # still counted as flagged; "disputed" only says the cross-examination found the quotes don't show the fault
        rows.append({"id": bug.id, "status": status, "flags": flags[:3], "disputed": bool(flags) and all("[disputed:" in f for f in flags)})
    text = [r for r in rows if r["id"] in TEXT_BUGS and r["status"] in ("prevented", "still flagged")]
    return {"bugs": rows, "prevented": sum(r["status"] == "prevented" for r in text), "measured": len(text),
            "disputed": sum(r["status"] == "still flagged" and r["disputed"] for r in text),
            "pass_rate": vg["pass_rate"], "interventions": guard_events}


async def run_proof(out: Path, evon=None, judge_samples: int = 3, qa_n: int = 40, on_event=None, qa_seed: int = 7) -> dict:
    from .demo import run_version
    from .qa import Scorecard, aggregate, write_outputs
    from .qa.bench import run_bench
    import yaml
    out.mkdir(parents=True, exist_ok=True)
    mode = "Evon agent, callers and judge; simulated phone audio" if evon else "offline: scripted agent, code checks only"
    v1 = await run_version("v1", "suites/proof.yaml", out, on_event, evon=evon, judge_samples=judge_samples, label="reference agent v1 (seeded bugs)",
                           hear_callers=True)
    v2 = await run_version("v2", "suites/proof.yaml", out, on_event, evon=evon, judge_samples=judge_samples, label="reference agent v2 (fixed)",
                           hear_callers=True)
    # then each fix (FIXES): the same buggy v1 behind Guard (prompt untouched), v3 (v2 with the secret taken out of the
    # model), and both layers
    fixes = {k: await run_fix(k, out, evon, judge_samples, on_event) for k in FIXES}
    tests = score_bugs(v1.to_dict(), v2.to_dict(), judged=evon is not None)
    for k, run in fixes.items():
        tests[k] = score_guard(tests, run.to_dict(), judged=evon is not None)
        tests[f"{k}_dir"] = Path(run.dir).name
    tests["v1_dir"], tests["v2_dir"] = Path(v1.dir).name, Path(v2.dir).name
    tests["harness_errors"] = sum(r.usage.get("harness_errors", 0) for r in (v1, v2, *fixes.values()))
    card = Scorecard.model_validate(yaml.safe_load(Path("scorecards/emi_collections.yaml").read_text(encoding="utf-8")))
    calls, truth, results, qa = run_bench(card, evon, n=qa_n, seed=qa_seed, samples=judge_samples)
    bench_dir = out / "qa-bench"
    write_outputs(results, aggregate(results, card), card, bench_dir, redact_pii=False)
    (bench_dir / "corpus.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in calls), encoding="utf-8")
    qa["seed"] = qa_seed
    data = {"generated": time.strftime("%Y-%m-%d %H:%M"), "mode": mode, "tests": tests, "qa": qa}
    (out / "proof.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_html(data, out / "proof.html")
    return data


def refresh_code_checks(run_dir: Path, suite) -> dict:
    """Re-apply today's code checks to a finished run's saved calls; keep the Evon judge's verdicts as they were.
    Code checks are deterministic and free, so an improved check can be measured on old live runs without a GPU."""
    from .judge.rubric import code_checks
    from .runner import load_call
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    personas = {s.id: s.persona for s in suite.expand()}
    for v in report["verdicts"]:
        call_json = run_dir / v["scenario_id"] / f"run{v['run']}" / "call.json"
        if not call_json.exists() or v["scenario_id"] not in personas:
            continue
        rec = load_call(call_json)
        fresh = {c.id: c for c in code_checks(suite.agent, personas[v["scenario_id"]], rec)}
        kept = [c for c in v["criteria"] if not (c.get("source") == "code" and c["id"] in fresh)]
        from .judge.rubric import CriterionResult, code_overrides_judge
        merged = [CriterionResult(**{k: c.get(k) for k in ("id", "verdict", "critical", "agreement", "reason", "evidence", "source")}, cross=c.get("cross") or "")
                  for c in kept] + list(fresh.values())
        v["criteria"] = [{**c.__dict__} for c in code_overrides_judge(merged)]
        v["passed"] = not v["metric_failures"] and not any(c["critical"] and c["verdict"] in ("fail", "review") for c in v["criteria"])
    calls = report["verdicts"]
    report["pass_rate"] = round(sum(v["passed"] for v in calls) / len(calls), 3) if calls else 0.0
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def rescore(proof_dir: Path, suite_path: str = "suites/proof.yaml") -> dict:
    """Refresh code checks on a proof's three runs and rescore the tests and Guard; the QA-Bench half is unchanged."""
    from .scenarios import load_suite
    suite = load_suite(suite_path)
    data = json.loads((proof_dir / "proof.json").read_text(encoding="utf-8"))
    t = data["tests"]
    dirs = ["v1_dir", "v2_dir", *(f"{k}_dir" for k in FIXES)]
    reports = {k: refresh_code_checks(proof_dir / t[k], suite) for k in dirs if t.get(k)}
    judged = "Evon" in data["mode"]
    tests = score_bugs(reports["v1_dir"], reports["v2_dir"], judged=judged)
    for k in FIXES:
        if f"{k}_dir" in reports:
            tests[k] = score_guard(tests, reports[f"{k}_dir"], judged=judged)
    for k in dirs:
        if k in t:
            tests[k] = t[k]
    # recounted from the runs in use: a run that was re-done after an Evon failure no longer counts against the proof
    tests["harness_errors"] = sum((r.get("usage") or {}).get("harness_errors", 0) for r in reports.values())
    data["tests"], data["rescored"] = tests, time.strftime("%Y-%m-%d %H:%M")
    (proof_dir / "proof.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_html(data, proof_dir / "proof.html")
    return data


V3_LABEL = "reference agent v3 (v2 + secrets isolated in code)"
# The fixes measured against v1's planted bugs: key -> (agent version, behind Guard?, report label, column header)
FIXES = {
    "guard": ("v1", True, "reference agent v1 + Bhool Guard (prompt unchanged)", "v1 + Guard (prompt unchanged)"),
    "v3": ("v3", False, V3_LABEL, "v3 (secrets isolated)"),
    "v3guard": ("v3", True, "reference agent v3 + Bhool Guard (both layers)", "v3 + Guard"),
    "v4": ("v4", False, "reference agent v4: model picks acts, code speaks facts, Guard on", "v4 (acts + Guard)"),
}


async def run_fix(key: str, out: Path, evon, judge_samples: int = 3, on_event=None):
    from dataclasses import replace
    from .demo import run_version
    from .reference_agent import VERSIONS
    version, guarded, label, _ = FIXES[key]
    agent = replace(VERSIONS[version], name=f"{version}+guard", guard=True) if guarded else None
    return await run_version(version, "suites/proof.yaml", out, on_event, evon=evon, judge_samples=judge_samples,
                             agent=agent, label=label, hear_callers=True)


async def rerun_guard(proof_dir: Path, evon, judge_samples: int = 3, on_event=None, which: str = "guard") -> dict:
    """Re-run only one fix's calls (see FIXES) of a finished proof, then rescore. Used after Evon dropped mid-run,
    or to add a fix to a proof made before it existed."""
    run = await run_fix(which, proof_dir, evon, judge_samples, on_event)
    if run.usage.get("harness_errors"):
        raise RuntimeError(f"Evon failed {run.usage['harness_errors']} time(s) again; the old {which} run is kept")
    data = json.loads((proof_dir / "proof.json").read_text(encoding="utf-8"))
    data["tests"][f"{which}_dir"] = Path(run.dir).name
    (proof_dir / "proof.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return rescore(proof_dir)


def _pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def write_html(data: dict, path: Path) -> None:
    t, q = data["tests"], data["qa"]
    color = {"caught": "pass", "missed": "fail", "needs Evon": "na", "not run": "na"}
    gcol = {"prevented": "pass", "still flagged": "fail"}
    fixes = [k for k in FIXES if (t.get(k) or {}).get("bugs")]
    fixed = {k: {r["id"]: r for r in t[k]["bugs"]} for k in fixes}

    def guard_cell(bid: str) -> str:
        cells = ""
        for k in fixes:
            r = fixed[k].get(bid)
            cells += (f"<td class='{gcol.get(r['status'], 'na')}'>{escape(r['status'])}</td>" if r else "<td class='na'>—</td>")
        return cells
    bug_rows = "".join(
        f"<tr><td><b>{escape(b['what'])}</b><div class='muted'>{escape(b['case'])}</div></td>"
        f"<td class='{color.get(b['status'].split(' +')[0], 'review')}'>{escape(b['status'])}</td>"
        f"<td>{''.join(f'<div class=ev>{escape(x)}</div>' for x in b['v1']) or '<span class=muted>—</span>'}</td>"
        f"<td>{''.join(f'<div class=ev>{escape(x)}</div>' for x in b['v2']) or '<span class=muted>clean</span>'}</td>{guard_cell(b['id'])}</tr>"
        for b in t["bugs"])
    qa_rows = "".join(
        f"<tr><td>{escape(pid)}</td><td class='muted'>{'Evon' if s['type'] == 'llm' else 'code'}</td><td>{s['n']}</td>"
        f"<td><b>{_pct(s['accuracy'])}</b></td><td>{_pct(s['fail_precision'])}</td><td>{_pct(s['fail_recall'])}</td><td>{s['to_review']}</td></tr>"
        for pid, s in q["parameters"].items())
    o = q.get("overall") or {}
    g = t.get("guard") or {}
    kpis = [("Planted bugs caught", f"{t['caught']}/{t['measured']}"), ("Also flagged on v2 (see quotes)", t["false_alarms"])]
    if g.get("measured"):
        kpis.append(("Bugs Guard prevents on unfixed v1", f"{g['prevented']}/{g['measured']}"))
    for k in ("v3", "v3guard", "v4"):
        if (t.get(k) or {}).get("measured"):
            kpis.append((f"Bugs gone in {FIXES[k][3]}", f"{t[k]['prevented']}/{t[k]['measured']}"))
    kpis += [
            ("QA verdict accuracy", _pct(o.get("accuracy"))), ("Fatal-error recall", _pct(q["fatal_recall"])),
            ("Pass/fail decisions right", _pct(q["decision_accuracy"]))]
    kpi = "".join(f"<div class='kpi'><span class='muted'>{k}</span><b>{escape(str(v))}</b></div>" for k, v in kpis)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Accuracy Proof</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Instrument+Serif&display=swap" rel="stylesheet">
<style>{CSS}.scroll>table{{min-width:720px}}</style></head><body><main>
<p class="muted">Bhool Bhulaiya · accuracy proof · {escape(data['generated'])} · {escape(data['mode'])}</p>
<h1>How accurate are the tests and the QA?</h1>
<p class="muted">Both are measured against answers known in advance: bugs deliberately planted in agent v1 (and fixed in v2),
and QA calls built with a known verdict on every parameter.</p>
<div class="kpis">{kpi}</div>
{f'<p class="fail"><b>Evon failed {t["harness_errors"]} time(s) during the test runs</b>: silent or cut-off calls may be the harness, not the agent. Re-run before quoting these numbers.</p>' if t.get("harness_errors") else ''}
<h2>Tests: planted bugs</h2>
<p class="muted">Each bug has a targeted call. Caught = flagged on v1 with evidence. "v2 also flagged" = the same flag on v2: Evon plays v2 and can genuinely slip, so read the quote to tell a real v2 failure from a false alarm.
v1 pass rate {_pct(t['v1_pass_rate'])} → v2 {_pct(t['v2_pass_rate'])}.
Reports: <a href="{escape(t['v1_dir'])}/report.html">v1</a> · <a href="{escape(t['v2_dir'])}/report.html">v2</a>{(' · <a href="' + escape(t['guard_dir']) + '/report.html">v1 + Guard</a>') if t.get('guard_dir') else ''}{''.join(f' · <a href="{escape(t[k + "_dir"])}/report.html">{escape(FIXES[k][3])}</a>' for k in ("v3", "v3guard", "v4") if t.get(k + "_dir"))}</p>
<p class="muted">Bhool Guard checks every line v1 is about to speak (banned threats, secret requests, account details before the caller
proves the account's last 4 digits, the recording disclosure) and rewrites it in code before text-to-speech (about 1 ms per line measured live).
VAD and barge-in bugs are audio engineering and stay v1's.
v3 is v2 with the secret taken out of the model: code checks the caller's digits, and the amount and due date reach the
model only after that; the verification digits never do. A model can't leak what it was never given.</p>
<div class="scroll"><table><tr><th>Seeded bug (case)</th><th>Result</th><th>Flag on v1 (evidence)</th><th>Flag on v2</th>{''.join(f"<th>{escape(FIXES[k][3])}</th>" for k in fixes)}</tr>{bug_rows}</table></div>
<h2>QA: verdicts with a known answer</h2>
<p class="muted">{q['calls']} calls in Hindi and Gujarati, half in Prisma's script (corpus seed {q.get('seed', 7)}). Fail precision: of the fails it gave, how many were real.
Fail recall: of the real fails, how many it found. Review: sent to a human instead of guessed.
Score error (MAE) {q['score_mae']} points · fatal false alarms {q['fatal_false_alarms']}. <a href="qa-bench/qa.html">Full QA report</a></p>
<div class="scroll"><table><tr><th>Parameter</th><th>Judge</th><th>n</th><th>Accuracy</th><th>Fail precision</th><th>Fail recall</th><th>Review</th></tr>{qa_rows}</table></div>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
