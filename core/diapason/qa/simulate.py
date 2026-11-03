"""`diapason qa simulate`: QA-Bench for every business segment, from nothing but its scorecard.

For any scorecard, Evon writes realistic calls of that business in Indian languages with defects planted on
purpose: the agent breaks exactly the parameters we chose (and the writer declares any knock-on breach), and
follows the rest. The audit then has to find them.

- Code-checked parameters (phrases, order) are verified in code before a call is used: a writer that failed
  to plant a defect, or broke one it didn't declare, gets one retry; after that those parameters are left
  out of scoring for that call, never silently counted.
- Timing defects (slow replies, talking over the customer) are laid out in code, so they are exact.
- With voice, each call is spoken by Timbre (two voices, the customer through a simulated phone line),
  written as a dual-channel WAV and transcribed back by Prisma: the audit runs on real ASR output, exactly
  as on a production recording.

Truth for Evon-judged parameters comes from the plan, so it is only as good as the writer's obedience.
That is why the headline is *planted-defect recall*; fails on parameters neither planted nor declared are
reported as *unplanted flags*, an upper bound on false alarms, not as proven errors.
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .conversation import Conversation, from_turns
from .engine import code_check
from .scorecard import Parameter, Scorecard

CODE_TYPES = {"phrase_present", "phrase_absent", "order", "echo"}
TIMING = {"responsive": "slow", "no_dead_air": "slow", "no_talk_over": "talk_over"}
MOODS = ["calm", "irritated", "confused", "elderly and slow to follow", "in a hurry", "anxious", "polite but firm"]
LANG_NAMES = {"hi-IN": "Hindi (Devanagari, with English loanwords as Indians say them)", "gu-IN": "Gujarati (Gujarati script)",
              "mr-IN": "Marathi (Devanagari)", "en-IN": "Indian English", "ta-IN": "Tamil (Tamil script)",
              "bn-IN": "Bengali (Bengali script)", "te-IN": "Telugu (Telugu script)", "kn-IN": "Kannada (Kannada script)"}
TTS_LANG = {"hi-IN": "hi-en"}
AGENT_VOICES, FEMALE, MALE = ["Kalpana", "Shivani", "Avinash"], ["Lakshmi", "Chetana", "Vasudha"], ["Prakash", "Devansh", "Harshad"]

WRITER_SYSTEM = """You write realistic transcripts of phone calls between an agent of an Indian business and a customer,
to test a call-quality auditor. Speech as people really talk on the phone: short turns, fillers, numbers in words
sometimes. Write each side in the language given, in its own script (English loanwords such as EMI, policy, refund,
OTP may stay in Latin script). The agent is excellent: it follows every QA parameter listed, correctly.
The agent works for the business named; never mention any real company, bank or brand.
Reply with ONLY JSON: {"turns": [{"speaker": "agent|customer", "text": "..."}]}"""

PLANT_SYSTEM = """You plant ONE defect in a call transcript, to test a call-quality auditor. You get the business SOP, the
numbered transcript and one QA parameter. Change the call so the AGENT clearly and unmistakably breaks that parameter,
the way a careless or pushy real agent would; keep everything else as it is and natural. Either replace one agent turn,
or insert a new agent turn after a given turn. If the parameter only applies in some situation (a third party answering,
an emergency, a refund request, a hardship, an opt-out request), also give a short customer line that creates it; it is
said just before the agent's new line. Keep the call's language unless the parameter is about language.
Never introduce any real company, bank or brand name.
If breaking it unavoidably breaks other listed parameters, name them.
Reply with ONLY JSON: {"action": "replace|insert_after", "turn": <index>, "setup": "<customer line, or empty>",
 "agent": "<the agent's new line>", "also_breaks": ["<parameter id>", ...]}"""

VERIFY_SYSTEM = """You check one line from a call transcript for a test. You get a QA rule, the few turns before the line,
and the AGENT's line. Does the agent's line, in this context, clearly and unmistakably break the rule, so that a careful
auditor would fail the call on it? Answer strictly: a line that merely fails to mention something, or is only slightly
off, does not count unless the rule is about saying that thing. Reply with ONLY JSON: {"breaks": true|false, "why": "<one sentence>"}"""


@dataclass
class SimCall:
    call_id: str
    segment: str
    lang: str
    mood: str
    planted: list[str]
    timing: list[str]                       # slow | talk_over
    turns: list[dict] = field(default_factory=list)
    declared: list[str] = field(default_factory=list)   # planted + knock-on breaches the planter declared
    excluded: list[str] = field(default_factory=list)   # the call disagrees with the plan on a code-checked parameter
    plants: list[dict] = field(default_factory=list)     # the exact line planted for each defect: the ground truth
    wav: str = ""
    error: str = ""


def plantable(card: Scorecard) -> list[Parameter]:
    """Parameters a writer can break on purpose: yes/no Evon checks and code checks (scales and metrics excluded)."""
    return [p for p in card.parameters() if (p.check.type == "llm" and not p.check.scale) or p.check.type in CODE_TYPES]


def plan_calls(card: Scorecard, segment: str, n: int, seed: int) -> list[SimCall]:
    rng = random.Random(f"{segment}:{seed}")
    pool = [p.id for p in plantable(card)]
    timing_ids = [p.id for p in card.parameters() if p.id in TIMING]
    langs = [lang for lang in card.agent.languages if lang in LANG_NAMES] or ["hi-IN"]
    calls = []
    for i in range(n):
        k = 0 if i % 5 == 0 else rng.choice([1, 1, 2, 2, 3])        # every fifth call is clean
        planted = rng.sample(pool, min(k, len(pool)))
        timing = sorted({TIMING[t] for t in timing_ids if rng.random() < 0.15}) if k else []
        calls.append(SimCall(f"{segment}-{i:02d}", segment, langs[i % len(langs)], rng.choice(MOODS), planted, timing))
    return calls


def _param_lines(card: Scorecard) -> str:
    return "\n".join(f"- {p.id}{' (FATAL)' if p.fatal else ''}: {p.check.describe()}"
                     for p in card.parameters() if p.check.type not in ("metric", "slot"))


def layout(turns: list[dict], timing: list[str], seed: int = 0) -> list[dict]:
    """Times for a transcript: ~2.5 words/s, 0.6 s turn gaps; 'slow' makes agent replies 4 s late,
    'talk_over' makes one agent reply start a second before the customer finishes."""
    rng = random.Random(seed)
    out, cut_done = [], False
    for k, t in enumerate(turns):
        dur = max(1.0, len(t["text"].split()) / 2.5)
        if not k:
            start = 0.0
        elif t["speaker"] == "agent":
            prev = out[-1]
            if "talk_over" in timing and not cut_done and prev["speaker"] == "customer":
                # start inside the customer's turn: >0.3 s after they began, >0.5 s before they finish
                start, cut_done = prev["end"] - min(1.0, prev["end"] - prev["start"] - 0.4), True
            else:
                start = prev["end"] + (4.0 if "slow" in timing else 0.5 + 0.3 * rng.random())
        else:
            start = out[-1]["end"] + 0.5 + 0.4 * rng.random()
        out.append({**t, "start": round(start, 2), "end": round(start + dur, 2)})
    return out


def _conv(call: SimCall) -> Conversation:
    return from_turns(call.call_id, layout(call.turns, call.timing), {"segment": call.segment, "lang": call.lang,
                                                                      "agent_id": f"{call.segment}-agent", "campaign": call.segment})


def check_obedience(card: Scorecard, call: SimCall) -> list[str]:
    """Code-checked parameters where the written call disagrees with the plan."""
    conv = _conv(call)
    bad = []
    for p in card.parameters():
        if p.check.type not in CODE_TYPES:
            continue
        verdict, _, _ = code_check(p, conv, card, {}, None)
        if (p.id in call.declared) != (verdict == "fail"):
            bad.append(p.id)
    return bad


def _numbered(turns: list[dict]) -> str:
    return "\n".join(f"[{i}] {t['speaker'].upper()}: {t['text']}" for i, t in enumerate(turns))


def apply_plant(turns: list[dict], edit: dict) -> tuple[list[dict], int] | None:
    """Apply a planter edit; returns the new turns and the index of the planted agent line."""
    agent = str(edit.get("agent") or "").strip()
    i = edit.get("turn")
    if not agent or not isinstance(i, int) or not 0 <= i < len(turns):
        return None
    setup = str(edit.get("setup") or "").strip()
    new = [dict(t) for t in turns]
    add = ([{"speaker": "customer", "text": setup}] if setup else []) + [{"speaker": "agent", "text": agent}]
    if edit.get("action") == "replace" and new[i]["speaker"] == "agent":
        new[i:i + 1] = add
        return new, i + len(add) - 1
    new[i + 1:i + 1] = add
    return new, i + len(add)


def _code_fails(p: Parameter, turns: list[dict], card: Scorecard) -> bool:
    conv = from_turns("x", layout(turns, []), {})
    return code_check(p, conv, card, {}, None)[0] == "fail"


def confirm_plant(evon, p: Parameter, turns: list[dict], at: int) -> tuple[bool, str]:
    """A narrow, separate question: does this one agent line break this one rule? The auditor never sees this."""
    context = "\n".join(f"{t['speaker'].upper()}: {t['text']}" for t in turns[max(0, at - 3):at])
    try:
        v = evon.chat_json([{"role": "system", "content": VERIFY_SYSTEM},
                            {"role": "user", "content": f"RULE: {p.check.describe()}\n\nBEFORE:\n{context}\n\nAGENT'S LINE: {turns[at]['text']}"}],
                           temperature=0.0, max_tokens=200)
    except Exception as e:
        return False, f"check failed: {e!r}"[:120]
    return bool(isinstance(v, dict) and v.get("breaks") is True), str((v or {}).get("why", "")) if isinstance(v, dict) else ""


def plant(evon, card: Scorecard, call: SimCall, p: Parameter) -> dict | None:
    """Plant one defect as a targeted edit, then confirm it landed: code-checked defects in code, Evon-judged ones by a
    separate one-line check. Up to three attempts; a defect that never lands is not counted as planted."""
    feedback = ""
    for _ in range(3):
        user = (f"BUSINESS SOP:\n{card.agent.sop}\n\nALL QA PARAMETERS:\n{_param_lines(card)}\n\n"
                f"TRANSCRIPT:\n{_numbered(call.turns)}\n\nBREAK THIS PARAMETER: {p.id}: {p.check.describe()}{feedback}")
        try:
            edit = evon.chat_json([{"role": "system", "content": PLANT_SYSTEM}, {"role": "user", "content": user}],
                                  temperature=0.7, max_tokens=800)
        except Exception as e:
            call.error = f"planter: {e!r}"[:200]
            continue
        applied = apply_plant(call.turns, edit if isinstance(edit, dict) else {})
        if applied is None:
            feedback = "\nYour last edit was not usable: give action, a valid turn index and the agent's new line."
            continue
        turns, at = applied
        if p.check.type in CODE_TYPES and not _code_fails(p, turns, card):
            c = p.check
            hint = {"phrase_absent": f"the agent must say one of these exact words: {', '.join(c.phrases)}",
                    "phrase_present": f"no agent turn may contain any of: {', '.join(c.phrases)} (rewrite the turn that has them)",
                    "order": f"the agent must say one of [{', '.join(c.then[:6])}] before any of [{', '.join(c.first[:6])}]",
                    "echo": "the customer must offer a specific date and the agent's next replies must not repeat it"}[c.type]
            feedback = f"\nYour last edit did not break it: {hint}."
            continue
        if p.check.type == "llm":
            ok, why = confirm_plant(evon, p, turns, at)
            if not ok:
                feedback = (f"\nYour last line did not clearly break it ({why}). Write an agent line that unmistakably breaks "
                            f"this rule" + (", in a different language from the customer" if p.id == "language_match" else "") + ".")
                continue
        call.turns = turns
        also = [str(x) for x in edit.get("also_breaks") or [] if isinstance(x, (str, int))]
        return {"parameter": p.id, "turn": at, "text": turns[at]["text"], "setup": str(edit.get("setup") or ""), "also_breaks": also}
    return None


def write_call(evon, card: Scorecard, call: SimCall) -> SimCall:
    """A clean call first, then each planned defect planted as its own edit, then a check of the result in code."""
    by_id = {p.id: p for p in card.parameters()}
    for _ in range(2):
        user = (f"BUSINESS: {card.agent.name}\nBUSINESS SOP:\n{card.agent.sop}\n\nQA PARAMETERS (the agent follows all of them):\n{_param_lines(card)}\n\n"
                f"CALL: language {LANG_NAMES[call.lang]}; customer is {call.mood}; 8 to 14 turns; the agent speaks first.")
        try:
            data = evon.chat_json([{"role": "system", "content": WRITER_SYSTEM}, {"role": "user", "content": user}],
                                  temperature=0.8, max_tokens=2500)
        except Exception as e:
            call.error = f"writer: {e!r}"[:200]
            continue
        turns = [{"speaker": "agent" if str(t.get("speaker", "")).lower().startswith("a") else "customer",
                  "text": str(t.get("text", "")).strip()} for t in data.get("turns") or [] if isinstance(t, dict)]
        turns = [t for t in turns if t["text"]]
        if len(turns) >= 4:
            call.turns, call.error = turns, ""
            break
        call.error = "writer returned too few turns"
    if not call.turns:
        return call
    declared, landed = set(), []
    for pid in call.planted:
        got = plant(evon, card, call, by_id[pid])
        if got:
            call.plants.append(got)
            landed.append(pid)
            declared |= {x for x in got["also_breaks"] if x in by_id}
    call.planted = landed                       # a defect that could not be planted is not counted as planted
    if "talk_over" in call.timing and not any(t["speaker"] == "customer" for t in call.turns[:-1]):
        call.timing = [x for x in call.timing if x != "talk_over"]
    call.declared = sorted(set(landed) | declared)
    call.excluded = check_obedience(card, call)
    return call


# ---------------------------------------------------------------- voice: Timbre speaks, Prisma hears

def voice_call(call: SimCall, tts, out_dir: Path, sr: int = 8000, line: str = "landline", seed: int = 0) -> Path:
    """Dual-channel WAV (customer on channel 0, through a phone line; agent on channel 1)."""
    from ..audio import resample, write_wav_channels
    from ..channel.sim import PRESETS, apply_channel
    timed = layout(call.turns, call.timing, seed)
    rng = random.Random(call.call_id)
    agent_voice = rng.choice(AGENT_VOICES)
    cust_voice = rng.choice(FEMALE + MALE)
    lang = TTS_LANG.get(call.lang, call.lang)
    clips = []
    for t in timed:
        audio, asr = tts.synthesize(t["text"], voice=agent_voice if t["speaker"] == "agent" else cust_voice, lang=lang)
        clips.append((t, resample(audio, asr, sr)))
    # Real clip lengths differ from the plan: keep each planned gap (or overlap) relative to the previous turn's end.
    placed, prev_end = [], 0.0
    for k, (t, a) in enumerate(clips):
        start = max(0.0, prev_end + (t["start"] - timed[k - 1]["end"])) if k else 0.0
        placed.append((t, a, start))
        prev_end = start + a.size / sr
    n = int((max(s + a.size / sr for _, a, s in placed) + 0.5) * sr)
    chans = np.zeros((2, n), np.float32)
    for t, a, start in placed:
        i = int(start * sr)
        ch = 0 if t["speaker"] == "customer" else 1
        chans[ch, i : i + a.size] += a[: n - i]
    line_audio, lsr, _ = apply_channel(chans[0], sr, PRESETS[line], seed=seed)
    chans[0] = resample(line_audio, lsr, sr)[:n] if lsr != sr else line_audio[:n]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{call.call_id}.wav"
    write_wav_channels(path, chans, sr)
    path.with_suffix(".json").write_text(json.dumps({"call_id": call.call_id, "segment": call.segment, "lang": call.lang,
                                                     "agent_id": f"{call.segment}-agent", "campaign": call.segment},
                                                    ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- scoring against the plan

def evaluate(calls: list[SimCall], results, card: Scorecard) -> dict:
    by = {r.call_id: r for r in results}
    fatal_ids = {p.id for p in card.parameters() if p.fatal}
    # A written call can't control slots (no CRM) or untargeted metrics (e.g. talk ratio): not scored.
    unscored = {p.id for p in card.parameters() if p.check.type == "slot" or (p.check.type == "metric" and p.id not in TIMING)}
    per: dict[str, dict] = {}
    planted_hits, planted_review, planted_n, unplanted_flags, unplanted_n = 0, 0, 0, 0, 0
    fatal_truth, fatal_got, examples = [], [], []
    for c in calls:
        r = by.get(c.call_id)
        if r is None or r.error or not c.turns:
            continue
        got = {p.id: p for p in r.params}
        for pid, pr in got.items():
            if pid in c.excluded or pid in unscored or pr.verdict == "skipped":
                continue
            s = per.setdefault(pid, {"planted": 0, "caught": 0, "review": 0, "unplanted": 0, "flags": 0, "type": pr.source})
            if pid in c.planted:
                s["planted"] += 1
                planted_n += 1
                if pr.verdict == "fail":
                    s["caught"] += 1
                    planted_hits += 1
                elif pr.verdict == "review":
                    s["review"] += 1
                    planted_review += 1
                else:
                    examples.append({"call_id": c.call_id, "parameter": pid, "kind": "missed", "verdict": pr.verdict, "reason": pr.reason})
            elif pid not in c.declared and pid not in TIMING:
                s["unplanted"] += 1
                unplanted_n += 1
                if pr.verdict == "fail":
                    s["flags"] += 1
                    unplanted_flags += 1
                    examples.append({"call_id": c.call_id, "parameter": pid, "kind": "unplanted flag", "verdict": "fail", "reason": pr.reason})
            elif pid in TIMING:
                want_fail = TIMING[pid] in c.timing
                s["planted" if want_fail else "unplanted"] += 1
                if want_fail:
                    planted_n += 1
                    s["caught"] += pr.verdict == "fail"
                    planted_hits += pr.verdict == "fail"
                else:
                    unplanted_n += 1
                    s["flags"] += pr.verdict == "fail"
                    unplanted_flags += pr.verdict == "fail"
                if want_fail != (pr.verdict == "fail"):
                    examples.append({"call_id": c.call_id, "parameter": pid, "kind": "missed" if want_fail else "unplanted flag",
                                     "verdict": pr.verdict, "reason": pr.reason})
        fatal_truth.append(bool((set(c.declared) - set(c.excluded)) & fatal_ids))
        fatal_got.append(bool(r.fatal))

    def pct(a, b):
        return round(a / b, 3) if b else None
    tf = [(t, g) for t, g in zip(fatal_truth, fatal_got)]
    return {"calls": len(tf), "planted": planted_n, "planted_recall": pct(planted_hits, planted_n),
            "planted_to_review": planted_review, "unplanted_checked": unplanted_n,
            "unplanted_flag_rate": pct(unplanted_flags, unplanted_n),
            "fatal_recall": pct(sum(t and g for t, g in tf), sum(t for t, _ in tf)),
            "false_fatal": sum(g and not t for t, g in tf), "clean_fatal_calls": sum(not t for t, _ in tf),
            "excluded_params": sum(len(c.excluded) for c in calls),
            "parameters": {k: {**v, "recall": pct(v["caught"], v["planted"]), "flag_rate": pct(v["flags"], v["unplanted"])}
                           for k, v in per.items()},
            "examples": examples[:40]}


def simulate_segment(card: Scorecard, segment: str, out: Path, evon, n: int = 6, seed: int = 1, samples: int = 3,
                     voice_calls: int = 0, tts=None, hear=None, on_event=None) -> dict:
    from .batch import aggregate, run_batch, write_outputs
    from .conversation import _wav
    calls = plan_calls(card, segment, n, seed)
    with ThreadPoolExecutor(4) as pool:
        calls = list(pool.map(lambda c: write_call(evon, card, c), calls))
    convs = []
    for i, c in enumerate(calls):
        if not c.turns:
            continue
        if i < voice_calls and tts is not None and hear is not None:
            try:
                c.wav = str(voice_call(c, tts, out / "audio", seed=seed + i))
                conv = _wav(Path(c.wav), hear, c.lang, 0)
                conv.meta.update({"segment": segment, "lang": c.lang, "voiced": True})
                convs.append(conv)
                continue
            except Exception as e:          # a voice failure (budget, API) falls back to the text call
                c.error = f"voice: {e!r}"[:200]
        convs.append(_conv(c))
    results = run_batch(convs, card, evon, samples, 4, on_result=lambda r: on_event and on_event(
        {"type": "qa_call", "segment": segment, "call": r.call_id, "score": r.score, "passed": r.passed}))
    write_outputs(results, aggregate(results, card), card, out, redact_pii=False)
    ev = evaluate(calls, results, card)
    data = {"segment": segment, "scorecard": card.name, "seed": seed, "evaluation": ev,
            "calls": [asdict(c) for c in calls]}
    (out / "simulate.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def write_segments_html(rows: list[dict], path: Path, generated: str) -> None:
    from html import escape
    from ..report import CSS

    def pct(x):
        return "—" if x is None else f"{x:.0%}"
    body = "".join(
        f"<tr><td><b>{escape(r['scorecard'])}</b><div class=muted>{escape(r['segment'])}</div></td><td>{r['evaluation']['calls']}</td>"
        f"<td>{r['evaluation']['planted']}</td><td><b>{pct(r['evaluation']['planted_recall'])}</b></td>"
        f"<td>{r['evaluation']['planted_to_review']}</td><td>{pct(r['evaluation']['unplanted_flag_rate'])}</td>"
        f"<td>{pct(r['evaluation']['fatal_recall'])}</td><td>{r['evaluation']['false_fatal']}/{r['evaluation']['clean_fatal_calls']}</td>"
        f"<td>{sum(1 for c in r['calls'] if c['wav'])}</td><td><a href='{escape(r['segment'])}/qa.html'>audit</a></td></tr>"
        for r in rows)
    tot_p = sum(r["evaluation"]["planted"] for r in rows)
    tot_c = sum(round((r["evaluation"]["planted_recall"] or 0) * r["evaluation"]["planted"]) for r in rows)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA Across Segments</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Instrument+Serif&display=swap" rel="stylesheet">
<style>{CSS}.scroll>table{{min-width:760px}}</style></head><body><main>
<p class="muted">Diapason · QA across segments · {escape(generated)}</p>
<h1>One auditor, every business</h1>
<p class="muted">For each segment's scorecard, Evon wrote calls with defects planted on purpose; the auditor had to find them.
Planted recall: share of planted defects it failed. Review: sent to a human instead. Unplanted flags: fails on parameters neither
planted nor declared by the writer (an upper bound on false alarms). Voiced calls were spoken by Timbre over a simulated phone line and
transcribed by Prisma before the audit.</p>
<p class="muted"><b>Read recall as a lower bound.</b> Evon also writes the defects, and even after a separate confirmation step some
"planted" lines do not actually break the rule; each call shows the exact planted line next to the auditor's verdict, so a miss can be
checked in seconds. QA-Bench, where truth is built in code, is the accuracy measure.</p>
<div class="kpis"><div class="kpi"><span class="muted">Segments</span><b>{len(rows)}</b></div>
<div class="kpi"><span class="muted">Planted defects found</span><b>{tot_c}/{tot_p}</b></div>
<div class="kpi"><span class="muted">Calls audited</span><b>{sum(r['evaluation']['calls'] for r in rows)}</b></div></div>
<div class="scroll"><table><tr><th>Segment</th><th>Calls</th><th>Planted</th><th>Recall</th><th>Review</th><th>Unplanted flags</th>
<th>Fatal recall</th><th>False fatal</th><th>Voiced</th><th></th></tr>{body}</table></div>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
