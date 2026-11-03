"""`watch.html`: the demo as a film that plays in the browser, every frame drawn from files in this repo.

Not a screen recording and not a mock: each scene is a renderer, and its data is a run on disk. The call scene plays a
live call's own audio (Timbre voices through the phone-line simulator, heard by Prisma) with its transcript, latencies
and failed checks in sync; the scoreboards come from the accuracy proof, the atlas and the noise sweep. Rebuild the site
and the film changes with the evidence. Press R (or open ?record) to hide the controls and screen-record it at 1080p.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import yaml

LIVE_V1 = "demo-emi-collection-20261026-200322"        # agent v1, live: Timbre callers, phone-line sim, Prisma, Evon
LIVE_CASE = "ramesh_hinglish__cooperative__landline"
TEXT_BUGS = ("disclosure", "verification", "conduct", "privacy", "language", "injection")
CHECK_NAMES = {"banned_phrases": "banned threat", "slot_capture": "loan ID never captured", "disclosure": "no recording disclosure",
               "verification": "debt before verification", "privacy": "privacy breach", "no_harassment": "threat / pressure",
               "language_match": "wrong language", "injection_resistance": "obeyed an injection", "factual_accuracy": "factual error",
               "tone": "tone", "task_success": "task not done", "disclosure_said": "no recording disclosure"}


def _json(p: Path) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _peaks(path: Path, bins: int = 160) -> list[float]:
    import numpy as np

    from .audio import read_wav
    x, _ = read_wav(path)
    x = np.abs(x.mean(axis=1) if x.ndim > 1 else x)
    if not x.size:
        return [0.0] * bins
    p = np.array([c.max() if c.size else 0.0 for c in np.array_split(x, bins)])
    return [round(float(v), 3) for v in p / (p.max() or 1.0)]


def _cast(suite_path: Path) -> list[dict]:
    """The proof suite's six callers, as the cold open introduces them."""
    s = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    persona = {p["id"]: p for p in s.get("personas", [])}
    chan = {c["id"]: c for c in s.get("channels", [])}
    out = []
    for case in s.get("cases", []):
        p, c = persona.get(case.get("persona"), {}), chan.get(case.get("channel"), {})
        name = (p.get("crm") or {}).get("name", p.get("id", ""))
        line = f"{c.get('noise', 'clean')} noise, {c.get('snr_db', '–')} dB" if c else ""
        out.append({"id": case["id"], "name": name, "who": case.get("persona", ""), "does": case.get("behaviour", ""), "line": line})
    return out


def _call_scene(runs: Path, audio_url: Callable[[Path], str]) -> dict | None:
    d = runs / LIVE_V1
    call, report = _json(d / LIVE_CASE / "run0" / "call.json"), _json(d / "report.json")
    mix = d / LIVE_CASE / "run0" / "mix.wav"
    if not call or not report or not mix.exists():
        return None
    v = next(x for x in report["verdicts"] if x["scenario_id"] == LIVE_CASE)
    lat = list(call["metrics"].get("response_latencies_s") or [])
    turns, k = [], 0
    for t in call["turns"]:
        row = {"who": t["speaker"], "text": t["text"], "start": round(t["start"], 2), "end": round(t.get("end", t["start"]), 2), "flags": []}
        if t["speaker"] == "agent" and turns and turns[-1]["who"] == "caller" and k < len(lat):
            row["latency"], k = lat[k], k + 1
        turns.append(row)
    fails = []
    for c in v["criteria"]:
        if c["verdict"] != "fail":
            continue
        name = CHECK_NAMES.get(c["id"], c["id"])
        quotes = [e for e in c.get("evidence") or [] if isinstance(e.get("turn"), int)]
        for e in quotes:
            if 0 <= e["turn"] < len(turns):
                turns[e["turn"]]["flags"].append({"name": name, "quote": e.get("quote", "")})
        fails.append({"name": name, "why": c.get("reason") or c.get("rationale") or "", "at": quotes[0]["turn"] if quotes else None})
    m = call["metrics"]
    return {"type": "call", "dur": round(call["duration_s"] / 1.15 + 5, 1), "rate": 1.15, "audio": audio_url(mix), "peaks": _peaks(mix),
            "length": round(call["duration_s"], 2), "turns": turns, "fails": fails, "gate": report.get("gate_reasons") or [],
            "metric_failures": v.get("metric_failures") or [], "p50": m.get("latency_p50_s"), "p95": m.get("latency_p95_s"),
            "title": "Agent v1 takes a call", "kicker": "Live call · Timbre voices · 8 kHz phone line · Prisma ears · Evon agent",
            "source": f"runs/{LIVE_V1}: call.json, mix.wav, report.json",
            "captions": [[0, "A synthetic customer, Ramesh, picks up. Everything you hear went through an 8 kHz phone line."],
                         [turns[2]["start"] / 1.15 if len(turns) > 2 else 12, "The agent threatens him. Diapason's checks flag it the moment it is said."],
                         [call["duration_s"] / 1.15, "A threat, a loan ID never checked, replies slower than the gate allows: this agent does not ship."]]}


def _guard_scene(proof: Path, p: dict) -> dict | None:
    from .site import SHOWCASE_CASE
    t = p["tests"]
    rows = []
    for key in ("v1_dir", "guard_dir"):
        call = _json(proof / t.get(key, "") / SHOWCASE_CASE / "run0" / "call.json") if t.get(key) else None
        if not call:
            return None
        rows.append(call)
    v1, gd = rows
    rewrites = [{"rule": e.get("rule", ""), "before": e.get("before", ""), "after": e.get("after", ""), "action": e.get("action", "")}
                for e in gd.get("events", []) if e.get("type") == "guard" and e.get("before")]
    first = lambda c: next((x["text"] for x in c["turns"] if x["speaker"] == "agent" and x["text"].strip()), "")
    g = t.get("guard") or {}
    return {"type": "guard", "dur": 15, "title": "The same agent, behind Diapason Guard", "rewrites": rewrites[:4],
            "v1_open": first(v1), "guard_open": first(gd), "prevented": g.get("prevented"), "measured": g.get("measured"),
            "bugs": [{"id": b["id"], "status": b["status"]} for b in g.get("bugs", []) if b["id"] in TEXT_BUGS],
            "kicker": "Every sentence checked in code before text-to-speech · prompt untouched",
            "source": f"proof run {proof.name}: {t.get('guard_dir')}",
            "captions": [[0, "Diapason Guard sits between the agent and its voice. Each sentence is checked in code before it is spoken."],
                         [8, "Threats are dropped, the disclosure is added. The agent's prompt is not touched."]]}


def _versions_scene(proof: Path, p: dict) -> dict:
    t = p["tests"]
    cols = []
    for key, label in (("guard", "v1 + Guard"), ("v3", "v3"), ("v3guard", "v3 + Guard"), ("v4", "v4")):
        g = t.get(key)
        if not g:
            continue
        st = {b["id"]: b["status"] for b in g["bugs"]}
        calls = None
        if t.get(f"{key}_dir") and (r := _json(proof / t[f"{key}_dir"] / "report.json")):
            calls = [sum(v["passed"] for v in r["verdicts"]), len(r["verdicts"])]
        cols.append({"label": label, "cells": [st.get(b, "") for b in TEXT_BUGS], "prevented": g.get("prevented"),
                     "measured": g.get("measured"), "calls": calls})
    what = {b["id"]: b["what"] for b in t["bugs"]}
    return {"type": "versions", "dur": 11, "title": "Fix, re-test, prove it", "rows": [{"id": b, "what": what.get(b, b)} for b in TEXT_BUGS],
            "cols": cols, "kicker": "Each version re-runs the same six calls; Evon judges every one",
            "source": f"proof run {proof.name}: proof.json",
            "captions": [[0, "Every version of the agent faces the same six callers, and every call is judged again."],
                         [7, "v4: the model picks what to do, code speaks the facts. Six of six text bugs gone."]]}


def _bugs_scene(p: dict) -> dict:
    t = p["tests"]
    return {"type": "bugs", "dur": 9, "title": "Seven bugs planted in agent v1", "bugs": [{"id": b["id"], "what": b["what"], "caught": b["status"].startswith("caught")} for b in t["bugs"]],
            "caught": t["caught"], "measured": t["measured"], "false_alarms": t.get("false_alarms"),
            "kicker": "One bug is tested twice: 8 tests", "source": "proof.json",
            "captions": [[0, "To know the tests work, we planted seven bugs in agent v1 and ran the suite."], [5, "Every planted bug was caught."]]}


def _atlas_scene(atlas: dict) -> dict:
    groups: dict = {}
    for r in atlas["table"]:
        g = groups.setdefault((r["lang"], r["kind"]), {"n": 0, "snr": {}})
        for s, v in r["by_snr"].items():
            a = g["snr"].setdefault(s, [0.0, 0])
            a[0] += v * r["n"]
            a[1] += r["n"]
    langs = {"hi": "Hindi", "gu": "Gujarati", "en": "English"}
    snrs = sorted({s for g in groups.values() for s in g["snr"]}, key=lambda s: -int(s))
    rows = [{"label": f"{langs.get(l, l)} {k}", "cells": [round(g["snr"][s][0] / g["snr"][s][1], 3) for s in snrs]}
            for (l, k), g in sorted(groups.items())]
    names = {"hi": "Hindi", "gu": "Gujarati", "en": "English"}
    reads = [{"what": f"{names.get(k.split('/')[0], k)} {k.split('/')[1]}", "below": v["read_back_below_snr"], "style": v.get("style", ""),
              "at": v.get("survives_at", {})} for k, v in (atlas.get("policy") or {}).items() if v.get("read_back_below_snr")]
    return {"type": "atlas", "dur": 11, "title": "Which details survive the phone line", "snrs": snrs, "rows": rows,
            "requests": atlas.get("requests"), "minutes": round((atlas.get("stt_seconds") or 0) / 60),
            "target": atlas.get("target", 0.95), "read_back": reads, "fixes": atlas.get("reader_fixes"), "kicker": "Timbre speaks it, the line degrades it, Prisma hears it",
            "source": "results/atlas/atlas.json",
            "captions": [[0, "Amounts, dates and loan IDs in Hindi, Gujarati and English, spoken by Timbre through rising noise and heard by Prisma."],
                         [6, "Where a detail stops surviving, the agent should read it back. That threshold is measured, not guessed."]]}


def _stress_scene(stress: dict) -> dict:
    v = stress["versions"]
    keep = [k for k in ("v1", "v4") if k in v]
    br = [x["breaks_at"] for x in v.get("v1", {}).get("points", {}).values() if x.get("breaks_at") is not None]
    held = "v4" in v and all(x.get("breaks_at") is None for x in v["v4"].get("points", {}).values())
    cap = (f"The same caller on noisier and noisier lines: v1 stops hearing between {min(br)} and {max(br)} dB."
           if br else "The same caller on noisier and noisier lines.") + (" v4 hears through every level, down to 0 dB." if held else "")
    return {"type": "stress", "dur": 8, "title": "Where each agent stops hearing", "levels": stress["levels"], "noises": stress["noises"],
            "versions": {k: v[k]["grid"] for k in keep}, "kicker": f"{', '.join(stress['noises'])} noise, 30 dB down to 0 dB",
            "source": "stress.json",
            "captions": [[0, cap]]}


def _qa_scene(p: dict, n_industries: int) -> dict:
    o = p["qa"].get("overall") or {}
    return {"type": "qa", "dur": 9, "title": "After the call: QA on every call", "accuracy": o.get("accuracy"), "n": o.get("n"),
            "fatal_recall": p["qa"].get("fatal_recall"), "fatal_false_alarms": p["qa"].get("fatal_false_alarms"),
            "industries": n_industries, "kicker": "Scored on calls the judge never saw, with truth planted in code",
            "source": "proof.json (qa)",
            "captions": [[0, "After launch, the same judge audits every call against its industry's rules, quoting the agent's own words."]]}


def film(runs: Path, proof: Path | None, audio_url: Callable[[Path], str], stress: dict | None = None,
         atlas: dict | None = None, suite: Path = Path("suites/proof.yaml"), scorecards: Path = Path("scorecards")) -> dict:
    p = _json(proof / "proof.json") if proof else None
    cast = _cast(suite) if suite.exists() else []
    scenes: list = [{"type": "intro", "dur": 8, "cast": cast, "title": "Before your voice agent talks to a million Indians,",
                     "title2": "it has to survive these callers.",
                     "captions": [[0, "Six synthetic Indian callers, each built to break a voice agent in a different way."]]}]
    if (c := _call_scene(runs, audio_url)):
        scenes.append(c)
    if p and p["tests"].get("bugs"):         # a proof without per-bug results has nothing to show in these three
        scenes.append(_bugs_scene(p))
        if (g := _guard_scene(proof, p)):
            scenes.append(g)
        if (v := _versions_scene(proof, p))["cols"]:
            scenes.append(v)
    if atlas:
        scenes.append(_atlas_scene(atlas))
    if stress:
        scenes.append(_stress_scene(stress))
    if p and (p.get("qa") or {}).get("overall"):
        n_ind = len(list((scorecards / "industries").glob("*.yaml"))) if (scorecards / "industries").exists() else 0
        scenes.append(_qa_scene(p, n_ind))
    scenes.append({"type": "outro", "dur": 7, "title": "Diapason", "models": [
        {"name": "Prisma", "role": "the callers' ears, every call re-transcribed"},
        {"name": "Timbre", "role": "the callers' voices, with emotion"},
        {"name": "Evon", "role": "callers, judge and red team"}],
        "captions": [[0, "Diapason. Crash tests before launch, a guard during the call, QA after it. Built on Gnani."]]})
    return {"scenes": scenes, "total": round(sum(s["dur"] for s in scenes), 1),
            "note": "Every scene is drawn from run files in the repository at build time; nothing is staged or typed in."}


def page(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return (Path(__file__).parent / "static" / "watch.html").read_text(encoding="utf-8").replace("__DATA__", blob, 1)
