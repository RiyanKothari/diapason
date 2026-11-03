"""`diapason site`: a static showcase anyone can open from a link, no server or keys needed.

Bundles the latest accuracy proof (with its test-call recordings), the QA Studio with its data baked in (every
segment and industry audit, with the voiced calls' audio), and a landing page of measured numbers. Deploy the folder
to GitHub Pages, Vercel or any static host.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import studio

STATIC = Path(__file__).parent / "static"


def _latest(runs_dir: Path, marker: str) -> Path | None:
    found = []
    for d in runs_dir.iterdir():
        f = d / marker
        if d.is_dir() and f.exists():
            try:
                found.append((json.loads(f.read_text(encoding="utf-8")).get("generated") or "", d))
            except ValueError:
                continue
    return max(found)[1] if found else None


def _copy_tree(src: Path, dst: Path, keep_audio: set[str] = frozenset({"mix.wav"})) -> None:
    """Copy a run directory, dropping per-channel recordings (only the mixed call is played on the pages)."""
    for f in src.rglob("*"):
        if f.is_dir() or (f.suffix == ".wav" and f.name not in keep_audio):
            continue
        t = dst / f.relative_to(src)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, t)


def build_site(out: Path, runs_dir: Path = Path("runs"), scorecards_dir: Path = Path("scorecards"),
               proof: Path | None = None, repo_url: str = "") -> dict:
    if out.exists():
        shutil.rmtree(out)
    (out / "data" / "audit").mkdir(parents=True)

    # QA Studio, with its API answers written as files
    data = studio.index(runs_dir, scorecards_dir)
    data["audits"] = [a for a in data["audits"] if not a["path"].startswith("_")]
    voiced = 0
    for a in data["audits"]:
        def audio_url(rel: str) -> str:
            src, dst = runs_dir / rel, out / "audio" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return f"audio/{rel}"
        d = studio.audit(runs_dir, a["path"], audio_url=audio_url)
        voiced += sum(bool(c.get("audio")) for c in d["calls"])
        (out / "data" / "audit" / (a["path"].replace("/", "__") + ".json")).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    (out / "data" / "studio.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    page = (STATIC / "studio.html").read_text(encoding="utf-8")
    page = page.replace("<script>\nconst $ =", '<script>window.DIAPASON_DATA = "data/";</script>\n<script>\nconst $ =', 1)
    (out / "studio.html").write_text(page, encoding="utf-8")

    # the accuracy proof, the simulation summaries, and the latest autopilot if there is one
    proof = proof or _latest(runs_dir, "proof.json")
    p = json.loads((proof / "proof.json").read_text(encoding="utf-8")) if proof else None
    if proof:
        # proof calls with Evon are carried as codec tones, not voices: only the replayed showcase call's audio is kept
        _copy_tree(proof, out / "proof", keep_audio=set())
        for key in ("v1_dir", "guard_dir"):
            mix = proof / p["tests"].get(key, "") / SHOWCASE_CASE / "run0" / "mix.wav"
            if p["tests"].get(key) and mix.exists():
                dst = out / "proof" / mix.relative_to(proof)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mix, dst)
    sims = []
    for d in sorted(runs_dir.iterdir()):
        if d.is_dir() and (d / "segments.json").exists() and not d.name.startswith("_"):
            _copy_tree(d, out / d.name, keep_audio=set())
            rows = json.loads((d / "segments.json").read_text(encoding="utf-8"))
            sims.append((d.name, rows))
    auto = _latest(runs_dir, "autopilot.json")
    stress = _latest(runs_dir, "stress.json")
    if stress:
        _copy_tree(stress, out / "stress", keep_audio=set())
    # the rating lives in the proof run (diapason rating <proof> --stress <dir>); badges go on the landing page
    rating = json.loads((proof / "rating" / "rating.json").read_text(encoding="utf-8")) if proof and (proof / "rating" / "rating.json").exists() else None
    if auto:
        _copy_tree(auto, out / "autopilot", keep_audio=set())      # the report quotes words; dozens of calls of audio would bloat the site

    stress_data = json.loads((stress / "stress.json").read_text(encoding="utf-8")) if stress else None
    replay = json.loads((auto / "autopilot.json").read_text(encoding="utf-8")).get("replay") if auto else None
    asr_dir = _latest(runs_dir, "asr_bench.json")
    asr = json.loads((asr_dir / "asr_bench.json").read_text(encoding="utf-8")) if asr_dir else None
    atlas_dir = _latest(runs_dir, "atlas.json")
    atlas = json.loads((atlas_dir / "atlas.json").read_text(encoding="utf-8")) if atlas_dir else _results_json("atlas/atlas.json")
    atlas_page = (atlas_dir / "atlas.html") if atlas_dir else Path(__file__).resolve().parents[2] / "results" / "atlas" / "atlas.html"
    if atlas_page.exists():
        shutil.copy2(atlas_page, out / "atlas.html")
    (out / "index.html").write_text(_landing(proof, p, sims, data, voiced, bool(auto), repo_url, stress_data, rating, replay, asr,
                                             has_atlas=atlas_page.exists(), atlas=atlas), encoding="utf-8")

    # the demo as a film: its call scene plays a live recording, so that one file is copied beside it
    from . import film
    def film_audio(src: Path) -> str:
        dst = out / "film" / f"{src.parents[2].name}.wav"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return f"film/{dst.name}"
    reel = film.film(runs_dir, proof, film_audio, stress=stress_data, atlas=atlas, scorecards=scorecards_dir)
    (out / "watch.html").write_text(film.page(reel), encoding="utf-8")
    return {"out": str(out), "audits": len(data["audits"]), "voiced_calls": voiced, "proof": proof.name if proof else None,
            "stress": stress.name if stress else None, "rating": bool(rating),
            "simulations": [n for n, _ in sims], "autopilot": auto.name if auto else None, "film_scenes": len(reel["scenes"]),
            "megabytes": round(sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6, 1)}


def _results_json(rel: str) -> dict | None:
    f = Path(__file__).resolve().parents[2] / "results" / rel
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def _waveform(path: Path, bins: int = 120) -> list[float]:
    from .audio import read_wav
    import numpy as np
    x, _ = read_wav(path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if not x.size:
        return [0.0] * bins
    chunks = np.array_split(np.abs(x), bins)
    peaks = np.array([c.max() if c.size else 0.0 for c in chunks])
    return [round(float(v), 3) for v in peaks / (peaks.max() or 1.0)]


SHOWCASE_CASE = "verify_disclose_conduct"
RULE_NAMES = {"disclosure": "no recording disclosure", "disclosure_said": "no recording disclosure", "verification": "details before verification",
              "privacy": "privacy breach", "no_harassment": "threat / pressure", "banned_phrases": "banned threat", "calling_hours": "false urgency",
              "injection_resistance": "obeyed an injection", "language_match": "wrong language", "factual_accuracy": "factual error",
              "tone": "tone", "task_success": "task not done", "slot_capture": "details not captured",
              "account_privacy": "privacy breach", "injection_guard": "leaked under attack", "language_script": "wrong language"}


def _replay(proof: Path, t: dict) -> dict | None:
    """The same test call twice: the buggy agent as is, and the same agent behind Guard. All from the proof's files."""
    sides = []
    for key, label, guarded in (("v1_dir", "Agent v1, as shipped", False), ("guard_dir", "The same agent v1 + Diapason Guard", True)):
        d = t.get(key)
        call_json = proof / d / SHOWCASE_CASE / "run0" / "call.json" if d else None
        if not call_json or not call_json.exists():
            return None
        call = json.loads(call_json.read_text(encoding="utf-8"))
        report = json.loads((proof / d / "report.json").read_text(encoding="utf-8"))
        verdict = next((v for v in report["verdicts"] if v["scenario_id"] == SHOWCASE_CASE), None)
        if verdict is None:
            return None
        turns = [{"who": x["speaker"], "text": x["text"], "start": round(x["start"], 2), "guard": [], "flags": []}
                 for x in call["turns"] if x["text"].strip()]
        agent = [x for x in turns if x["who"] == "agent"]
        for e in (e for e in call.get("events", []) if e.get("type") == "guard"):
            target = next((x for x in agent if x["start"] >= e["t"] - 0.6), agent[-1] if agent else None)
            if target is not None:
                target["guard"].append({k: e[k] for k in ("rule", "action", "before", "after")})
        fails = [c for c in verdict["criteria"] if c["verdict"] == "fail"]
        for c in fails:
            ev = (c.get("evidence") or [{}])[0]
            i = ev.get("turn")
            src = call["turns"][i]["text"] if isinstance(i, int) and 0 <= i < len(call["turns"]) else None
            target = next((x for x in turns if x["text"] == src), agent[0] if agent else None)
            if target is not None and c["id"] not in target["flags"]:
                target["flags"].append(c["id"])
        mix = proof / d / SHOWCASE_CASE / "run0" / "mix.wav"
        rules = sorted({RULE_NAMES.get(c["id"], c["id"]) for c in fails})     # a code check and the judge on one rule count once
        undecided = sorted({RULE_NAMES.get(c["id"], c["id"]) for c in verdict["criteria"] if c["verdict"] == "review"})
        if rules:
            summary = f"{len(rules)} rule{'s' if len(rules) != 1 else ''} broken"
        elif undecided:      # not a pass: the judge gave no usable (or no quotable) verdict on these
            summary = f"no rule broken; the judge left {len(undecided)} check{'s' if len(undecided) != 1 else ''} undecided"
        else:
            summary = "no rule broken"
        note = "; ".join(rules) if rules else ("undecided: " + "; ".join(undecided)) if undecided else "every check passed"
        if verdict.get("metric_failures"):
            note += " · " + "; ".join(verdict["metric_failures"])
        n_guard = sum(len(x["guard"]) for x in turns)
        sides.append({"label": label, "guarded": guarded, "turns": turns, "passed": verdict["passed"],
                      "meta": f"{len(turns)} turns · {call['duration_s']:.0f} s · {call['end_reason'].replace('_', ' ')}",
                      "summary": summary + (f" · Guard rewrote {n_guard} line{'s' if n_guard != 1 else ''}" if guarded else ""),
                      "note": note,
                      "audio": f"proof/{d}/{SHOWCASE_CASE}/run0/mix.wav" if mix.exists() else None,
                      "peaks": _waveform(mix) if mix.exists() else [0.1] * 120, "duration": round(call["duration_s"], 1)})
    duration = max(x["duration"] for x in sides)
    return {"sides": sides, "duration": duration, "speed": max(1.0, duration / 22),
            "sub": "A synthetic customer, Ramesh, answers a collections call. On the left, agent v1 with its seeded bugs. On the right, the "
                   "same agent, prompt untouched, behind Diapason Guard: each line is checked in code before it is spoken. Both calls were "
                   "judged afterwards by the same auditor. Nothing on this panel is staged; it is replayed from the proof run's files."}


def _landing(proof: Path | None, p: dict | None, sims: list, data: dict, voiced: int, has_auto: bool, repo_url: str,
             stress: dict | None = None, rating: dict | None = None, replay: dict | None = None, asr: dict | None = None,
             has_atlas: bool = False, atlas: dict | None = None) -> str:
    kpis = []
    if p:
        t, q = p["tests"], p["qa"]
        o = q.get("overall") or {}
        g = t.get("guard") or {}
        acc = o.get("accuracy") or 0
        kpis += [{"label": f"of QA verdicts right, on calls the judge never saw ({o.get('n', 0)} verdicts)", "value": None,
                  "display": f"{100 * acc:.1f}%"},
                 {"label": "of fatal compliance breaches caught", "value": round(100 * (q.get("fatal_recall") or 0)), "suffix": "%", "display": _pct(q.get("fatal_recall"))},
                 {"label": "false fatal alarms", "value": q.get("fatal_false_alarms") or 0, "display": str(q.get("fatal_false_alarms"))},
                 {"label": "tests of the bugs planted in agent v1 that catch them (7 bugs; one is tested twice)", "value": t["caught"], "den": t["measured"], "display": f"{t['caught']}/{t['measured']}"}]
        if g.get("measured"):
            label = "bugs Guard prevents on the unfixed agent, of those the judge gave a verdict on"
            if g.get("unjudged"):
                label += f" ({g['unjudged']} more: every code check passes, no usable judge verdict yet)"
            kpis.append({"label": label, "value": g["prevented"], "den": g["measured"], "display": f"{g['prevented']}/{g['measured']}"})
        v4 = t.get("v4") or {}
        if v4.get("measured") and proof and t.get("v4_dir") and (proof / t["v4_dir"] / "report.json").exists():
            calls = json.loads((proof / t["v4_dir"] / "report.json").read_text(encoding="utf-8"))["verdicts"]
            ok = sum(v["passed"] for v in calls)
            kpis.append({"label": f"proof calls agent v4 passes on every check (model picks the act, code speaks the facts); "
                                  f"v4 removes {v4['prevented']}/{v4['measured']} of v1's bugs", "value": ok, "den": len(calls),
                         "display": f"{ok}/{len(calls)}"})
    if replay and replay["before"]["calls"]:
        b, a = replay["before"], replay["after"]
        kpis.append({"label": f"red-team attacks that leaked the account: {replay['attacked']} {b['leaked']}/{b['calls']} → "
                              f"{replay['replayed_on']} (secrets isolated) {a['leaked']}/{a['calls']}",
                     "value": None, "display": f"{b['leaked']} → {a['leaked']}"})          # None: shown as is, not counted up
    if stress:      # the noise numbers: where the seeded v1 stops hearing, and the best fixed agent that hears through all of it
        pts = {v: r["points"] for v, r in stress.get("versions", {}).items()}
        held = [v for v in ("v4", "v3", "v2") if v in pts and all(x["breaks_at"] is None and x["holds_to"] == 0 for x in pts[v].values())]
        v1 = [x["breaks_at"] for x in pts.get("v1", {}).values() if x["breaks_at"] is not None]
        if held and v1:
            kpis.append({"label": f"SNR down to which {held[0]} still hears the caller through fan, traffic, office and crowd noise "
                                  f"(v1 stopped hearing between {min(v1)} and {max(v1)} dB)", "value": None, "display": "0 dB"})
    if asr and asr.get("by_preset", {}).get("market") is not None:
        by = asr["by_preset"]
        kpis.append({"label": f"Prisma character error on a 5 dB crowded-market phone line (clean line: {100 * by['clean']:.1f}%)",
                     "value": None, "display": f"{100 * by['market']:.1f}%"})
    if atlas and atlas.get("requests"):
        names = {"hi": "Hindi", "gu": "Gujarati", "en": "English"}
        kinds = {"id": "loan IDs", "amount": "amounts", "date": "dates"}
        reads = [f"{names.get(k.split('/')[0], k)} {kinds.get(k.split('/')[1], k.split('/')[1])} below {v['read_back_below_snr']} dB"
                 for k, v in (atlas.get("policy") or {}).items() if v.get("read_back_below_snr")]
        kpis.append({"label": "amounts, dates and IDs spoken by Timbre through a noisy phone line and heard by Prisma, "
                              f"{atlas.get('errors', 0)} errors; read back " + ("; ".join(reads) if reads else "never needed"),
                     "value": atlas["requests"], "display": f"{atlas['requests']:,}"})
    n_ind = sum(c.get("group") == "industries" for c in data["scorecards"])
    kpis += [{"label": "industry playbooks with their regulations", "value": n_ind, "display": str(n_ind)},
             {"label": "calls voiced through Timbre → phone line → Prisma", "value": voiced, "display": str(voiced)}]
    links = [{"title": "The demo, as a film", "href": "watch.html", "text": "A live call, planted bugs, Guard, v1 to v4, the atlas and QA, played from the run files."},
             {"title": "QA Studio", "href": "studio.html", "text": "Every segment and industry, every verdict with the agent's own words; click to hear the moment."},
             {"title": "Accuracy proof", "href": "proof/proof.html", "text": "Seeded bugs (v1), their fix (v2), v1 behind Guard, and QA-Bench with truth built in code."}]
    if rating:
        links.append({"title": "Crash-test rating", "href": "proof/rating/rating.html", "text": "Five measured axes per agent, with SVG badges."})
    if has_atlas:
        links.append({"title": "Phone-line atlas", "href": "atlas.html", "text": "Which amounts, dates and IDs survive the line, by language and noise, and when to read them back."})
    if stress:
        links.append({"title": "Noise breaking point", "href": "stress/stress.html", "text": "Fan, traffic, office and crowd noise from 30 dB to 0 dB."})
    links += [{"title": f"{len(rows)} {'industries' if n.startswith('industries') else 'segments'}: simulated calls", "href": f"{n}/segments.html",
               "text": "Evon writes calls with defects planted on purpose; the auditor has to find them."} for n, rows in sims]
    if has_auto:
        links.append({"title": "Autopilot", "href": "autopilot/autopilot.html", "text": "Evon red-teams the agent, then patches it; a patch is kept only if a re-run proves it."})
    moments = [
        {"k": "Before launch", "title": "Crash tests", "href": "proof/proof.html",
         "text": "Synthetic Indian callers phone the agent through a phone-line simulator, in real time.",
         "points": ["Hindi, Hinglish and Gujarati personas with hidden facts", "fan, traffic and crowd noise; 8 kHz μ-law; packet loss",
                    "barge-ins, injection, a brother who answers", "a red-team that designs new attacks from what broke the agent"]},
        {"k": "During the call", "title": "Diapason Guard", "href": "#replay",
         "text": "Every sentence is checked in code before it reaches text-to-speech: about 1 ms measured live, no model call unless a line needs translating.",
         "points": ["threats and secret requests never spoken", "no account detail until the caller proves the last 4 digits",
                    "the recording disclosure always said", "a Hindi reply to a Gujarati caller translated"]},
        {"k": "After the call", "title": "QA for every call", "href": "studio.html",
         "text": "Each call scored against its industry's rules, with the agent's own words as evidence.",
         "points": [f"{n_ind} industry playbooks: RBI, IRDAI, DGCA, TRAI, HIPAA…", "dates and phrases checked in code, judgment by Evon",
                    "no quote, no fail: doubt goes to a human", "insights, coaching, sentiment, regressions from failed calls"]}]
    rate = {n: {"overall": r["overall"], "axes": {k: v["stars"] for k, v in r["axes"].items()}} for n, r in (rating or {}).get("ratings", {}).items()}
    st = None
    if stress:
        st = {"levels": stress["levels"], "noises": stress["noises"], "versions": {v: r["grid"] for v, r in stress["versions"].items()}}
    payload = {
        "replay": _replay(proof, p["tests"]) if proof and p else None,
        "kpis": kpis, "kpi_note": (f"From the accuracy proof of {p.get('generated', '')} ({p.get('mode', 'mode not recorded')}) and the runs on disk." if p else ""),
        "moments": moments, "rating": rate or None, "stress": st, "links": links, "repo_url": repo_url,
        "footer": "Built on Gnani Prisma (speech-to-text), Timbre (voices) and Evon (callers, judge, red team). Brands in the industry playbooks "
                  "are fictional. Simulated calls are test material written by Evon, not customer data.",
    }
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return (STATIC / "landing.html").read_text(encoding="utf-8").replace("__DATA__", blob, 1)
