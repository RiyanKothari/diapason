"""`diapason fix`: the fix agent. From a failed run to fixes that are proven, not suggested.

Every failure of the run is sorted into the lane that can actually fix it:

prompt       what the model chose to say (tone, task, factual errors, escalation, injection obedience). Evon writes new
             prompt rules; the patched agent re-runs only the calls that failed; a patch is kept only if it fixes
             something and breaks nothing (autopilot.heal).
guard        what code can enforce before speech (threats, the recording disclosure, account details before verification,
             echoed IDs, the caller's language). The same failed calls re-run with Diapason Guard on, prompt untouched.
             For an agent Diapason does not run, the same rules ship as Shield in block mode in front of it.
engineering  what no prompt fixes (latency, barge-in, endpointing, dead air). Written up as tickets with the measurement.

The output is a fix plan: per lane what was tried, what the re-run proved, and what to ship, as JSON and Markdown.
Proof needs the agent's prompt in Diapason's hands: the reference agents, or an agent rebuilt from its prompt.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from .autopilot import compare, confirm_breaks, heal, prompt_items
from .checks import explain, metric_id
from .reference_agent import VERSIONS, AgentVersion
from .scenarios.schema import Case, Suite

# checks that Guard's code enforces before speech (guard.py): the guard lane can fix these without touching the prompt
GUARD_FIXABLE = {"banned_phrases", "no_harassment", "compliance", "disclosure", "disclosure_said", "account_privacy",
                 "verification", "privacy", "injection_guard", "language_match", "language_script"}


def triage(report: dict) -> dict:
    """Every failure of a run, in the lane that can fix it, explained."""
    lanes: dict[str, list] = {"prompt": [], "guard": [], "engineering": []}
    for v in report["verdicts"]:
        if v["passed"]:
            continue
        for c in v["criteria"]:
            if c["verdict"] != "fail":
                continue
            ev = (c.get("evidence") or [{}])[0] or {}
            item = {"scenario": v["scenario_id"], **explain(c["id"], c.get("reason") or "", ev.get("quote", ""))}
            lanes["guard" if c["id"] in GUARD_FIXABLE else "prompt"].append(item)
        for m in v.get("metric_failures") or []:
            lanes["engineering"].append({"scenario": v["scenario_id"], **explain(metric_id(m), m)})
    return lanes


def failing_suite(suite: Suite, report: dict) -> Suite:
    """The suite cut down to the calls that failed: a fix is re-tested where it matters, at a fraction of the cost."""
    failed = {v["scenario_id"] for v in report["verdicts"] if not v["passed"]}
    cases = [Case(id=s["scenario_id"], persona=s["persona"], behaviour=s["behaviour"], channel=s["channel"],
                  failure="; ".join(s.get("failures") or [])[:300])
             for s in report["scenarios"] if s["scenario_id"] in failed]
    return suite.model_copy(update={"cases": cases, "matrix": None, "name": f"{suite.name}-failed"})


def tickets(items: list[dict]) -> list[dict]:
    """Engineering failures grouped by kind: one ticket per problem, with every call it showed up on."""
    out: dict[str, dict] = {}
    for x in items:
        t = out.setdefault(x["id"], {"id": x["id"], "title": x["name"], "severity": x["severity"], "fix": x["fix"],
                                     "why": x["why"], "calls": [], "measured": []})
        t["calls"].append(x["scenario"])
        t["measured"].append(x["detail"])
    return sorted(out.values(), key=lambda t: -len(t["calls"]))


async def fix(run_dir: Path, suite: Suite, evon, out: Path, agent: AgentVersion | None = None, rounds: int = 2,
              judge_samples: int = 3, on_event=None) -> dict:
    report = json.loads((Path(run_dir) / "report.json").read_text(encoding="utf-8"))
    lanes = triage(report)
    plan: dict = {"run": str(run_dir), "generated": time.strftime("%Y-%m-%d %H:%M"), "suite": suite.name,
                  "agent": agent.name if agent else None, "pass_rate": report["pass_rate"],
                  "lanes": {k: len(v) for k, v in lanes.items()}, "failures": lanes,
                  "engineering": tickets(lanes["engineering"]), "prompt": None, "guard": None}
    if agent is None:
        plan["note"] = ("No agent prompt to patch, so nothing could be re-run: the prompt and guard lanes are listed, not proven. "
                        "Name the agent the run tested (a reference version) to prove fixes.")
        return _write(plan, out)
    retest = failing_suite(suite, report)
    if lanes["prompt"] or lanes["guard"]:
        # the prompt lane: Evon patches, the failed calls re-run, a patch survives only if it fixes and breaks nothing
        h = await heal(evon, retest, agent, out / "prompt", rounds=rounds, judge_samples=judge_samples, on_event=on_event)
        accepted = [r for a in h["attempts"] if a.get("accepted") for r in a["rules"]]
        plan["prompt"] = {"before_pass_rate": h["before_pass_rate"], "after_pass_rate": h["after_pass_rate"],
                          "rules": accepted, "greeting": h["healed"]["greeting"] if h["healed"]["greeting"] != agent.greeting else "",
                          "fixed": prompt_items(h["fixed"]), "broken": prompt_items(h["broken"]), "still": prompt_items(h["still"]),
                          "flaky_breaks": h.get("flaky_breaks") or [], "attempts": len(h["attempts"]), "error": h.get("error"),
                          "tried": [{"round": a["round"], "accepted": a["accepted"], "rules": a["rules"],
                                     "fixed": len(prompt_items(a.get("fixed") or [])), "broken": prompt_items(a.get("broken") or []),
                                     "flaky_breaks": a.get("flaky_breaks") or [],
                                     "error": a.get("error", "")} for a in h["attempts"]],
                          "baseline_dir": h["before_dir"], "after_dir": h["after_dir"]}
    if lanes["guard"] and not agent.guard:
        # the guard lane: the same failed calls, the same prompt, Guard on
        from .demo import run_version
        # heal's baseline is these same failed calls before any patch: reuse it rather than pay for the calls twice
        base = json.loads((out / "prompt" / plan["prompt"]["baseline_dir"] / "report.json").read_text(encoding="utf-8")) \
            if plan["prompt"] and not plan["prompt"]["error"] else None
        if base is None:
            base = (await run_version(agent.name, retest, out / "guard", on_event, evon=evon, judge_samples=judge_samples,
                                      agent=agent, label=f"{agent.name} before guard")).to_dict()
        guarded = replace(agent, name=f"{agent.name}+guard", guard=True)
        rep = (await run_version(agent.name, retest, out / "guard", on_event, evon=evon, judge_samples=judge_samples,
                                 agent=guarded, label=guarded.name)).to_dict()
        d = compare(base, rep)
        broken, flaky = prompt_items(d["broken"]), []
        if broken and prompt_items(d["fixed"]):
            broken, flaky = await confirm_breaks(evon, retest, guarded, broken, out / "guard", judge_samples, on_event)
        plan["guard"] = {"before_pass_rate": base["pass_rate"], "after_pass_rate": rep["pass_rate"],
                         "fixed": prompt_items(d["fixed"]), "broken": broken, "flaky_breaks": flaky, "still": prompt_items(d["still"]),
                         "after_dir": Path(rep["dir"]).relative_to(out).as_posix()}
    plan["ship"] = _recommend(plan)
    return _write(plan, out)


def _flakes(lane: dict) -> str:
    n = len(lane.get("flaky_breaks") or [])
    return f" ({n} seen once and gone on 2 re-runs)" if n else ""


def _recommend(plan: dict) -> list[str]:
    out = []
    p, g = plan.get("prompt"), plan.get("guard")
    if p and p["rules"] and not p["broken"]:
        out.append(f"Add {len(p['rules'])} prompt rule(s): re-run fixed {len(p['fixed'])} failure(s), broke none{_flakes(p)}.")
    elif p and p.get("error"):
        out.append(f"Prompt lane not run ({p['error']}): run the fix again.")
    elif p:
        out.append("No prompt patch survived the re-run: fix by hand, or move the rule into code (Guard).")
    if g and g["fixed"] and not g["broken"]:
        out.append(f"Turn on Guard (or put Shield in block mode in front of the agent): re-run fixed {len(g['fixed'])} failure(s), "
                   f"broke none{_flakes(g)}.")
    elif g and g["broken"]:
        out.append(f"Guard fixed {len(g['fixed'])} but broke {len(g['broken'])}: review before shipping.")
    for t in plan["engineering"]:
        out.append(f"Engineering: {t['title']} on {len(t['calls'])} call(s). {t['fix']}")
    return out


def _write(plan: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "fix-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# Fix plan: {plan['suite']}" + (f" · agent {plan['agent']}" if plan["agent"] else ""), "",
          f"Run {plan['run']} · pass rate {round(100 * plan['pass_rate'])}% · failures by lane: "
          + ", ".join(f"{k} {v}" for k, v in plan["lanes"].items()), ""]
    if plan.get("note"):
        md += [f"> {plan['note']}", ""]
    md += ["## Ship", *[f"- {s}" for s in plan.get("ship") or ["Nothing proven yet."]], ""]
    if plan.get("prompt"):
        p = plan["prompt"]
        md += ["## Prompt lane (proven by re-running the failed calls)",
               f"Pass rate on the failed calls {round(100 * p['before_pass_rate'])}% → {round(100 * p['after_pass_rate'])}%; "
               f"fixed {len(p['fixed'])}, broke {len(p['broken'])}, still failing {len(p['still'])}.", ""]
        md += [f"- `{r}`" for r in p["rules"]] or [f"- not run: {p['error']}" if p.get("error") else "- no rule survived"]
        for a in p.get("tried") or []:
            flaky = f" ({len(a['flaky_breaks'])} more seen once, gone on 2 re-runs)" if a.get("flaky_breaks") else ""
            md.append(f"- round {a['round']}: " + (a["error"] or (f"accepted: fixed {a['fixed']}{flaky}" if a["accepted"] else
                      f"rejected: fixed {a['fixed']}, broke {', '.join(a['broken'][:4])} (confirmed on re-run){flaky}")))
        md.append("")
    if plan.get("guard"):
        g = plan["guard"]
        md += ["## Guard lane (same prompt, code checks before speech)",
               f"Pass rate {round(100 * g['before_pass_rate'])}% → {round(100 * g['after_pass_rate'])}%; fixed {len(g['fixed'])}, "
               f"broke {len(g['broken'])}" + (f"; {len(g['flaky_breaks'])} more seen once and gone on 2 re-runs: "
                                             f"{', '.join(g['flaky_breaks'])}" if g.get("flaky_breaks") else "") + ".", ""]
    if plan["engineering"]:
        md += ["## Engineering tickets", *[f"- **{t['title']}** ({t['severity']}) on {len(t['calls'])} call(s): {t['measured'][0]}. "
                                            f"Fix: {t['fix']}" for t in plan["engineering"]], ""]
    (out / "fix-plan.md").write_text("\n".join(md), encoding="utf-8")
    return plan


def agent_for(name: str | None) -> AgentVersion | None:
    if name is None:
        return None
    if name not in VERSIONS:
        raise ValueError(f"agent must be one of {sorted(VERSIONS)}")
    return VERSIONS[name]
