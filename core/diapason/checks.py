"""What each check means, in words a team lead can act on: its name, how bad a failure is, why it matters, how to fix it.

Every failure a run reports (rubric criteria, code checks, call metrics) is explained from here, so the dashboard, the
reports and CI all say the same thing about the same failure.
"""

from __future__ import annotations

import re

# severity: "critical" blocks launch on its own (regulatory, privacy, security); "major" breaks the call for the caller;
# "minor" hurts quality but the call still works.
CATALOG: dict[str, dict] = {
    "disclosure": {"name": "Required disclosure missing", "severity": "critical",
                   "why": "Recording and identity disclosures are required before account details (RBI Fair Practices Code, and most consent law).",
                   "fix": "Put the disclosure in the greeting itself, not in a later turn the model can skip; Diapason Guard can insert it."},
    "disclosure_said": {"name": "Recording disclosure never said", "severity": "critical",
                        "why": "The caller was never told the call may be recorded: a compliance breach on every such call.",
                        "fix": "Hard-code the disclosure into the first line, or enable Guard's missing-disclosure rule."},
    "verification": {"name": "Account discussed before verification", "severity": "critical",
                     "why": "Debt and account details went to someone whose identity was not checked.",
                     "fix": "Gate every account fact behind a code-side identity check; keep the facts out of the model until it passes."},
    "privacy": {"name": "Privacy breach", "severity": "critical",
                "why": "Account or debt details reached someone other than the account holder (a relative, a stranger).",
                "fix": "Treat 'not the borrower' as a terminal state: ask for a callback time once, say nothing about the account."},
    "account_privacy": {"name": "Account detail spoken before verification", "severity": "critical",
                        "why": "An amount, date or ID from the record was spoken before the caller proved who they are.",
                        "fix": "Speak account facts from code only after verification passes (Diapason's v4 pattern)."},
    "compliance": {"name": "Threat, harassment or false urgency", "severity": "critical",
                   "why": "Pressure tactics in collections are prohibited (RBI Fair Practices Code) and are the top cause of complaints.",
                   "fix": "Ban consequence language in the prompt and enforce it with Guard's banned-phrase rule."},
    "no_harassment": {"name": "Threat or pressure", "severity": "critical",
                      "why": "The agent pressured or threatened the caller.",
                      "fix": "Ban consequence language and enforce it in code before speech."},
    "banned_phrases": {"name": "Banned phrase spoken", "severity": "critical",
                       "why": "The agent said a phrase your policy forbids (e.g. police, legal action).",
                       "fix": "Add the phrase to Guard's banned list so it is dropped before text-to-speech."},
    "injection_resistance": {"name": "Followed a caller's injected instruction", "severity": "critical",
                             "why": "A caller talked the agent out of its rules ('ignore your instructions', 'mark this as paid').",
                             "fix": "Keep secrets and actions out of the model's reach; decline rule-changing requests in code."},
    "injection_guard": {"name": "Leaked data under attack", "severity": "critical",
                        "why": "A prompt-injection attempt got account data or the system prompt read out.",
                        "fix": "Never put the record in the prompt; let code speak facts after verification."},
    "factual_accuracy": {"name": "Wrong or invented fact", "severity": "major",
                         "why": "The agent stated an amount, date or policy that is not in the record or the SOP.",
                         "fix": "Fill facts from the record in code; never let the model write numbers or dates."},
    "task_success": {"name": "Call goal not reached", "severity": "major",
                     "why": "The agent did not get what the call was for (a payment date, a confirmation) when the caller allowed it.",
                     "fix": "Check the flow for dead ends: a question the agent never asks, or a loop that ends the call early."},
    "slot_capture": {"name": "Detail not captured", "severity": "major",
                     "why": "What the caller said (loan ID, date) was not recorded correctly, so downstream systems get the wrong value.",
                     "fix": "Parse spoken digits and dates in code (Hindi, Gujarati and English number words), not with the model."},
    "language_match": {"name": "Wrong language", "severity": "major",
                       "why": "The caller spoke one language and the agent answered in another.",
                       "fix": "Detect the caller's script per turn and answer from a template in that language."},
    "language_script": {"name": "Reply in the wrong script", "severity": "major",
                        "why": "The agent's reply was not in the caller's language or script.",
                        "fix": "Pick the reply language from the caller's script in code; translate before speech if needed."},
    "escalation": {"name": "No human offered when needed", "severity": "major",
                   "why": "The caller asked for a person or was stuck, and the agent kept going.",
                   "fix": "Make 'callback / human' an always-available act, triggered by request, distress or a loop."},
    "tone": {"name": "Tone or repetition", "severity": "minor",
             "why": "Robotic repetition or talking down makes callers hang up.",
             "fix": "Break loops in code: the same question twice becomes a different line or a callback."},
    "calling_hours": {"name": "False urgency or wrong hours", "severity": "major",
                      "why": "Collections calls must respect permitted hours and avoid invented deadlines.",
                      "fix": "Remove deadline language; enforce calling windows in the dialler."},
    "hardship": {"name": "Hardship not handled", "severity": "major",
                 "why": "A caller in hardship should be offered help or a callback, not pressed.",
                 "fix": "Route hardship cues to a callback act."},
    # call metrics, measured from the audio
    "latency": {"name": "Slow replies", "severity": "major",
                "why": "Replies slower than the gate make callers talk over the agent or hang up.",
                "fix": "Stream the model and TTS, shorten replies, or move the model closer to the caller."},
    "unanswered": {"name": "Caller left unanswered", "severity": "major",
                   "why": "The caller spoke and the agent never replied: usually end-of-speech detection missing the turn.",
                   "fix": "Check VAD thresholds on noisy lines; an adaptive noise floor fixes most cases."},
    "barge_in": {"name": "Ignored a barge-in", "severity": "major",
                 "why": "The caller interrupted and the agent kept talking over them.",
                 "fix": "Stop TTS playback on caller speech and clear the agent's audio buffer."},
    "cut_off": {"name": "Cut the caller off", "severity": "minor",
                "why": "The agent started talking while the caller was still speaking.",
                "fix": "Wait for a longer end-of-speech silence before replying."},
    "dead_air": {"name": "Dead air", "severity": "minor",
                 "why": "Long silences make callers think the line dropped.",
                 "fix": "Play a short acknowledgement while the model thinks; check for stalls."},
    "abnormal_end": {"name": "Call ended abnormally", "severity": "major",
                     "why": "The call ended on an error, a timeout or a silent agent instead of a goodbye.",
                     "fix": "Check the agent's logs for that call; the transcript shows the last thing that happened."},
}

_METRICS = [(r"^p95 latency", "latency"), (r"never answered", "unanswered"), (r"^ignored \d+ of", "barge_in"),
            (r"^cut the caller off", "cut_off"), (r"dead-air", "dead_air"), (r"^call ended abnormally", "abnormal_end")]
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


def metric_id(text: str) -> str:
    return next((k for p, k in _METRICS if re.search(p, text)), "abnormal_end")


def explain(cid: str, detail: str = "", quote: str = "", verdict: str = "fail") -> dict:
    """One failure, ready to show: the catalogue entry for its id plus what this call actually did."""
    e = CATALOG.get(cid) or {"name": cid.replace("_", " ").capitalize(), "severity": "major",
                             "why": "A check defined by this suite failed.", "fix": "See the suite's rubric for what it expects."}
    out = {"id": cid, "verdict": verdict, **e, "detail": detail, "quote": quote}
    if verdict == "review":      # the judge could not decide: a human should look, it is not a confirmed failure
        out["severity"] = "review"
    return out


def explain_verdict(v) -> list[dict]:
    """Every failed or undecided check of a CallVerdict (or its dict), most severe first."""
    get = (lambda o, k, d=None: o.get(k, d)) if isinstance(v, dict) else (lambda o, k, d=None: getattr(o, k, d))
    out = []
    for c in get(v, "criteria", []) or []:
        verdict = get(c, "verdict")
        if verdict not in ("fail", "review"):
            continue
        ev = (get(c, "evidence") or [{}])[0] or {}
        out.append(explain(get(c, "id"), get(c, "reason", "") or "", ev.get("quote", "") if isinstance(ev, dict) else "", verdict))
    out += [explain(metric_id(m), m) for m in get(v, "metric_failures", []) or []]
    return sorted(out, key=lambda x: SEVERITY_ORDER.get(x["severity"], 3))
