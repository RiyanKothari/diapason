"""Draft a full test suite from an agent's SOP with Evon, then validate it hard.

Model output is never trusted as-is: personas go through the sanitizer (real Timbre voices,
real tags, supported languages), behaviours come from the curated library, and the result
must load as a Suite before it is written.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .scenarios.library import LIBRARY, sanitize_persona
from .scenarios.schema import AgentSpec, Matrix, Suite, Target

GEN_SYSTEM = """You design test suites for AI voice agents used in Indian contact centres.
Given the agent's SOP, produce realistic callers who will stress it: different languages
(Hindi, Hinglish, Gujarati, Marathi, Tamil, English...), ages, moods, and at least one caller
who is NOT the intended customer. Each persona gets hidden facts (what only the caller knows,
e.g. loan_id_last4, promise_to_pay_date) and a crm record (what the agent's system already
knows about the customer it is calling).
Reply with ONLY JSON:
{"agent": {"name": "...", "required_disclosures": ["..."], "banned_phrases": ["..."],
           "must_collect": ["slot", ...], "languages": ["hi-IN", ...]},
 "personas": [{"id": "snake_case", "description": "...", "gender": "female|male",
               "stt_lang": "hi-IN|gu-IN|mr-IN|ta-IN|te-IN|kn-IN|ml-IN|bn-IN|pa-IN|en-IN",
               "tts_lang": "hi-en|<same as stt_lang>", "emotion": ["<tag>"], "goal": "...",
               "hidden_facts": {}, "crm": {}}],
 "behaviours": ["<ids chosen from the library>"]}
Audio tags available: laugh, giggle, sigh, exhales, sniffles, yawns, coughs, clears throat,
whispers, shouting, excited, slow, pauses."""


def generate_suite(evon, sop: str, name: str, url: str = "ws://127.0.0.1:8765", personas: int = 6,
                   sample: int = 24, runs: int = 2) -> Suite:
    library = "\n".join(f"- {b.id}: {b.instructions}" for b in LIBRARY.values())
    user = f"SOP:\n{sop}\n\nWrite {personas} personas.\nBEHAVIOUR LIBRARY (pick the 5-8 most relevant ids):\n{library}"
    data = evon.chat_json([{"role": "system", "content": GEN_SYSTEM}, {"role": "user", "content": user}],
                          temperature=0.5, max_tokens=4000)
    a = data.get("agent") or {}
    agent = AgentSpec(
        name=str(a.get("name") or name), sop=sop,
        required_disclosures=[str(x) for x in a.get("required_disclosures") or []],
        banned_phrases=[str(x) for x in a.get("banned_phrases") or []],
        must_collect=[str(x) for x in a.get("must_collect") or []],
        languages=[str(x) for x in a.get("languages") or ["hi-IN"]],
    )
    seen, people = set(), []
    for i, p in enumerate(data.get("personas") or []):
        pid = "".join(c if c.isalnum() else "_" for c in str(p.get("id") or f"persona_{i}").lower())[:40] or f"persona_{i}"
        while pid in seen:
            pid += "_x"
        seen.add(pid)
        people.append(sanitize_persona(p, pid))
    if not people:
        raise ValueError("Evon returned no usable personas")
    chosen = [b for b in data.get("behaviours") or [] if b in LIBRARY]
    for must in ("cooperative", "interrupter", "prompt_injection"):   # always cover the basics
        if must not in chosen:
            chosen.append(must)
    suite = Suite(
        name=name, target=Target(type="websocket", url=url), agent=agent, personas=people,
        use_library=chosen, matrix=Matrix(channels=["landline", "street", "market", "bad_network"], sample=sample),
        runs_per_scenario=runs,
    )
    Suite.model_validate(suite.model_dump())
    return suite


def write_suite(suite: Suite, path: str | Path) -> None:
    data = suite.model_dump(mode="json", exclude={"behaviours"})   # library behaviours re-merge on load
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
