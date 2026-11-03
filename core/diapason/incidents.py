"""`diapason incidents`: the incident agent. Shield's flags on live calls become incidents, then regression tests.

1. Group: every flagged or blocked agent line in Shield's log is grouped by the rule it broke, then by what was said
   (lines that share most of their words are one pattern), in code. "14 calls threatened legal action since 10:02" is
   one incident, not 14 alerts.
2. Explain: Evon writes each incident up for a compliance lead (what happened, how often, the likely cause), quoting the
   agent's own words. Without Evon the write-up is the counts and quotes alone.
3. Prevent: each incident becomes a test case. The caller's lines that led up to the violation on a real call are pinned
   as the test caller's lines, so the next agent version is tested on exactly what tripped this one.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .checks import CATALOG
from .judge.scripts import dominant
from .scenarios.schema import Behaviour, Case, Persona, Suite

# Guard's rule names (what Shield logs) -> the check each one is a live case of
RULE_CHECK = {"banned_phrase": "banned_phrases", "missing_disclosure": "disclosure_said", "secret_request": "injection_guard",
              "account_before_verification": "account_privacy", "verification_digits": "injection_guard",
              "language_mismatch": "language_script"}
SCRIPT_LANG = {"devanagari": "hi-IN", "gujarati": "gu-IN", "latin": "en-IN"}

EXPLAIN_SYSTEM = """You write incident reports for the compliance lead of a contact centre that runs AI voice agents.
For each incident you are given the rule broken, how many calls and lines, when, and the agent's exact words.
Write two or three plain sentences: what the agent did, how widespread it is, and the most likely cause (a prompt rule,
a missing check, a model habit). Quote the agent's words. Do not invent numbers.
Reply with ONLY JSON: {"incidents": [{"id": "...", "summary": "..."}]}"""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 2}


def _similar(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= 0.5


def load(log_dir: Path) -> list[dict]:
    f = log_dir / "events.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


def group(events: list[dict]) -> list[dict]:
    flagged = [e for e in events if e["side"] == "agent" and e["verdict"] in ("flagged", "blocked", "replaced") and e.get("rules")]
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for e in flagged:
        violating = [r["rule"] for r in e["rules"] if r["action"] in ("dropped", "replaced")]
        by_rule[(violating or [e["rules"][0]["rule"]])[0]].append(e)
    incidents = []
    for rule, evs in by_rule.items():
        patterns: list[list[dict]] = []
        for e in evs:                                              # one incident per distinct thing said
            w = _words(e["text"])
            home = next((p for p in patterns if _similar(w, _words(p[0]["text"]))), None)
            (home.append(e) if home is not None else patterns.append([e]))
        for i, p in enumerate(patterns, 1):
            check = CATALOG.get(RULE_CHECK.get(rule, ""), {})
            calls = sorted({e["call"] for e in p})
            incidents.append({"id": f"{rule}-{i}", "rule": rule, "check": RULE_CHECK.get(rule, rule),
                              "title": check.get("name", rule.replace("_", " ")), "severity": check.get("severity", "major"),
                              "calls": calls, "lines": len(p), "prevented": sum(e["verdict"] in ("blocked", "replaced") for e in p),
                              "first": min(e.get("at", "") for e in p), "last": max(e.get("at", "") for e in p),
                              "quotes": list(dict.fromkeys(e["text"] for e in p))[:3], "events": p})
    order = {"critical": 0, "major": 1, "minor": 2}
    return sorted(incidents, key=lambda x: (order.get(x["severity"], 3), -len(x["calls"]), -x["lines"]))


def explain(incidents: list[dict], evon=None) -> None:
    for x in incidents:
        x["summary"] = (f"{x['title']} on {len(x['calls'])} call(s), {x['lines']} line(s), between {x['first']} and {x['last']}; "
                        f"{x['prevented']} stopped by Shield. Agent said: \"{x['quotes'][0]}\"")
    if evon is None or not incidents:
        return
    brief = [{k: x[k] for k in ("id", "title", "severity", "lines", "prevented", "first", "last", "quotes")} | {"calls": len(x["calls"])}
             for x in incidents]
    try:
        out = evon.chat_json([{"role": "system", "content": EXPLAIN_SYSTEM},
                              {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}], temperature=0.2, max_tokens=2000)
        written = {i.get("id"): str(i.get("summary") or "").strip() for i in out.get("incidents") or []}
        for x in incidents:
            if written.get(x["id"]):
                x["summary"] = written[x["id"]]
    except Exception:
        pass                                                       # the counted write-up stands without Evon


def regression_cases(incidents: list[dict], events: list[dict]) -> tuple[list[Persona], list[Behaviour], list[Case]]:
    """Each incident replayed: the caller's real lines before the violation, pinned, on the call it first happened."""
    personas, behaviours, cases = [], [], []
    for x in incidents:
        first = x["events"][0]
        said = [e["text"] for e in events if e["call"] == first["call"] and e["side"] == "caller" and e["t"] <= first["t"]]
        script = dominant(" ".join(said)) if said else None
        pid, bid, cid = f"live_{x['id']}", f"replay_{x['id']}", f"incident_{x['id']}"
        personas.append(Persona(id=pid, description=f"caller from live call {first['call']}", stt_lang=SCRIPT_LANG.get(script or "", "hi-IN"),
                                tts_lang="hi-en" if script in (None, "devanagari") else SCRIPT_LANG.get(script, "hi-en")))
        behaviours.append(Behaviour(id=bid, max_turns=max(4, len(said) + 3),
                                    instructions=("Replay a real caller: say the pinned lines in order, then answer naturally. "
                                                  f"On the real call the agent then broke: {x['title']}."),
                                    lines={i + 1: s for i, s in enumerate(said[:6])}))
        cases.append(Case(id=cid, persona=pid, behaviour=bid, channel="landline", source=f"shield call {first['call']}",
                          failure=f"{x['check']}: {x['quotes'][0][:200]}"))
    return personas, behaviours, cases


def run(log_dir: Path, out: Path, base: Suite | None = None, evon=None) -> dict:
    events = load(log_dir)
    incidents = group(events)
    explain(incidents, evon)
    out.mkdir(parents=True, exist_ok=True)
    result = {"calls": len({e["call"] for e in events}), "flagged_lines": sum(x["lines"] for x in incidents),
              "incidents": [{k: v for k, v in x.items() if k != "events"} for x in incidents]}
    if base is not None and incidents:
        import yaml
        ps, bs, cs = regression_cases(incidents, events)
        suite = base.model_copy(update={"name": f"{base.name}-incidents", "personas": list(base.personas) + ps,
                                        "behaviours": list(base.behaviours) + bs, "cases": cs, "matrix": None, "use_library": False})
        Suite.model_validate(suite.model_dump())
        path = out / f"{suite.name}.yaml"
        path.write_text(yaml.safe_dump(suite.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")
        result["regression_suite"] = str(path)
    (out / "incidents.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# Incidents from Shield: {result['calls']} call(s), {result['flagged_lines']} flagged line(s)", ""]
    for x in result["incidents"]:
        md += [f"## {x['title']} ({x['severity']}) · {len(x['calls'])} call(s), {x['lines']} line(s), {x['prevented']} stopped",
               x["summary"], "", *[f"> {q}" for q in x["quotes"]], ""]
    if result.get("regression_suite"):
        md.append(f"Every incident is now a test case: `diapason run {result['regression_suite']}`")
    (out / "incidents.md").write_text("\n".join(md), encoding="utf-8")
    return result
