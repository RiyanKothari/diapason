"""`diapason qa compile`: a policy or regulation in, an executable QA scorecard out, every check traced to its clause.

Compliance teams turn circulars and SOPs into QA forms by hand, and the link between "this check" and "that clause"
lives in someone's head. Here Evon reads the text and writes the scorecard, and each parameter carries the exact
clause it enforces. The quote is verified against the source text, so a check can't cite a rule that isn't there.
Mechanical rules become code checks (phrases that must or must never be said, verify-before-details order); only
judgment calls are left to Evon at audit time. The result is validated as a Scorecard before it is written.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..judge.rubric import quote_found
from .scorecard import Check, Parameter, Scorecard, Section
from ..scenarios.schema import AgentSpec

COMPILE_SYSTEM = """You turn a contact-centre policy or regulation into an executable QA scorecard for auditing calls.
For every rule an agent's call can break, write one parameter. Prefer exact code checks when the rule is mechanical:
- phrase_absent: words the agent must never say (threats, asking for an OTP). List the phrases as they would be spoken,
  in English and in Hindi/Gujarati script when relevant; for requests, write the request ("OTP बताइए"), not the warning.
- phrase_present: words that must be said (a recording disclosure: "record", "रिकॉर्ड").
- order: one thing must come before another (identity verified before the amount is stated): give "first" and "then" phrases.
- llm: anything needing judgment; write a yes/no question about the AGENT, saying when to answer na.
Every parameter MUST include "source": a short exact quote (copied word for word) of the clause it enforces.
Mark a parameter fatal if breaking it is a regulatory breach. Weights 1-10.
Reply with ONLY JSON:
{"name": "...", "agent": {"name": "...", "sop": "<3-5 sentence summary of what the agent must do>"},
 "sections": [{"id": "snake_case", "name": "...", "parameters": [
   {"id": "snake_case", "name": "...", "weight": 8, "fatal": true, "source": "<exact quote>",
    "check": {"type": "llm|phrase_present|phrase_absent|order", "question": "...", "phrases": [], "first": [], "then": []}}]}]}"""

EXPERIENCE = Section(id="experience", name="Caller experience (measured)", parameters=[
    Parameter(id="responsive", name="answers within 2.5 s (p95)", weight=3, check=Check(type="metric", metric="latency_p95_s <= 2.5")),
    Parameter(id="no_dead_air", name="no dead air over 3 s", weight=3, check=Check(type="metric", metric="dead_air_events == 0")),
    Parameter(id="no_talk_over", name="never cuts the customer off", weight=3, check=Check(type="metric", metric="agent_cut_off_caller == 0"))])


def _slug(s: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(s).lower())).strip("_")[:40] or "param"


def build(data: dict, policy: str, name: str | None = None) -> tuple[Scorecard, list[str]]:
    """A validated Scorecard from the model's JSON. Unusable parameters are dropped and reported, never guessed at."""
    notes, sections, seen = [], [], set()
    for si, sec in enumerate(data.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        params = []
        for raw in sec.get("parameters") or []:
            if not isinstance(raw, dict):
                continue
            pid = _slug(raw.get("id") or raw.get("name"))
            while pid in seen:
                pid += "_2"
            c = raw.get("check") if isinstance(raw.get("check"), dict) else {}
            kind = c.get("type") if c.get("type") in ("llm", "phrase_present", "phrase_absent", "order") else "llm"
            src = str(raw.get("source") or "").strip()
            try:
                check = Check(type=kind, question=c.get("question") or (raw.get("name") if kind == "llm" else None),
                              phrases=[str(x) for x in c.get("phrases") or [] if str(x).strip()],
                              first=[str(x) for x in c.get("first") or [] if str(x).strip()],
                              then=[str(x) for x in c.get("then") or [] if str(x).strip()])
                weight = min(10.0, max(1.0, float(raw.get("weight") or 5)))
            except (ValueError, TypeError) as e:
                notes.append(f"dropped {pid}: {str(e).splitlines()[0][:120]}")
                continue
            if not src or not quote_found(src, policy, threshold=0.75):
                notes.append(f"{pid}: its cited clause is not in the policy text; kept, marked unverified")
                src = f"[unverified] {src}" if src else "[no clause cited]"
            seen.add(pid)
            params.append(Parameter(id=pid, name=str(raw.get("name") or "")[:80], weight=weight, fatal=bool(raw.get("fatal")),
                                    source=src[:300], check=check))
        if params:
            sections.append(Section(id=_slug(sec.get("id") or f"section_{si}"), name=str(sec.get("name") or "")[:60], parameters=params))
    if not sections:
        raise ValueError("Evon returned no usable parameters")
    a = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    banned = [ph for s in sections for p in s.parameters if p.check.type == "phrase_absent" for ph in p.check.phrases]
    agent = AgentSpec(name=str(a.get("name") or name or "agent"), sop=str(a.get("sop") or policy[:600]), banned_phrases=banned)
    card = Scorecard(name=name or str(data.get("name") or "Compiled scorecard"), agent=agent, sections=sections + [EXPERIENCE])
    return card, notes


def compile_policy(evon, policy: str, name: str | None = None) -> tuple[Scorecard, list[str]]:
    data = evon.chat_json([{"role": "system", "content": COMPILE_SYSTEM}, {"role": "user", "content": f"POLICY TEXT:\n{policy[:12000]}"}],
                          temperature=0.2, max_tokens=4000)
    return build(data, policy, name)


def write(card: Scorecard, path: Path, policy_file: str) -> None:
    head = f"# Compiled by `diapason qa compile` from {policy_file}. Each parameter's `source` is the clause it enforces;\n" \
           f"# review before use: [unverified] marks a clause that could not be found word for word in the text.\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + yaml.safe_dump(card.model_dump(mode="json", exclude_defaults=True), allow_unicode=True, sort_keys=False), encoding="utf-8")
