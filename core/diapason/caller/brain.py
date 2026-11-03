"""The synthetic caller's mind: Evon role-plays a persona against the agent under test.

The persona knows its hidden facts and goal but not the agent's SOP, so it behaves like a
real customer rather than a tester who has read the script.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from ..scenarios.schema import EMOTION_TAGS, Behaviour, Persona

LANG_GUIDE = {
    "hi-en": "Hinglish: Hindi words in Devanagari, English words (EMI, loan, payment, sir) in Latin script, mixed naturally.",
    "hi-IN": "Hindi in Devanagari.",
    "gu-IN": "Gujarati in Gujarati script.",
    "en-IN": "Indian English.",
    "mr-IN": "Marathi in Devanagari.",
}
FALLBACK_INTERJECTIONS = {
    "hi-en": ["अरे रुको रुको, एक minute", "सुनिए, मेरी बात तो सुनो", "हाँ हाँ, ठीक है, but"],
    "hi-IN": ["अरे रुकिए", "एक मिनट सुनिए", "मेरी बात सुनिए"],
    "gu-IN": ["અરે, એક મિનિટ", "સાંભળો તો ખરા", "થોભો થોભો"],
    "en-IN": ["Wait, wait, one minute", "Sorry, listen", "Hold on"],
}


@dataclass
class Utterance:
    text: str
    tags: list[str] = field(default_factory=list)
    end_call: bool = False

    def tts_text(self) -> str:
        """Timbre v3 tags apply from their position onward, so leading tags colour the whole line."""
        tags = "".join(f"<{t}> " for t in self.tags if t in EMOTION_TAGS)
        return f"{tags}{self.text}".strip()


@dataclass
class Turn:
    speaker: str        # "caller" | "agent"
    text: str
    start: float
    end: float
    kind: str = "speech"   # speech | interjection


class Brain(Protocol):
    def reply(self, history: list[Turn]) -> Utterance: ...
    def opening(self) -> Utterance: ...
    def interjection(self) -> Utterance: ...


def persona_prompt(persona: Persona, behaviour: Behaviour) -> str:
    facts = "\n".join(f"- {k}: {v}" for k, v in persona.hidden_facts.items()) or "- (none: you are not the account holder)"
    return f"""You are role-playing a real person on a phone call with a company's AI voice agent.
Stay in character for the whole call. Never mention that you are an AI, a test, or a persona.

WHO YOU ARE: {persona.description}
WHAT YOU WANT FROM THIS CALL: {persona.goal or "react naturally"}
FACTS ONLY YOU KNOW (reveal them only when it is natural, e.g. when asked):
{facts}
HOW YOU BEHAVE ON THIS CALL: {behaviour.instructions}
LANGUAGE: {LANG_GUIDE.get(persona.tts_lang, persona.tts_lang)}

Speak like people really talk on the phone: short sentences, 1 to 2 at a time, fillers allowed.
Do not read out lists. Do not be more helpful than this person would be.
You may use these voice tags to colour delivery: {", ".join(sorted(EMOTION_TAGS))}.
Your usual mood tags: {", ".join(persona.emotion) or "none"}.
End the call (end_call true) when your goal is met, when the agent ends it, or when you
would realistically hang up.

Reply with ONLY a JSON object: {{"say": "<what you say>", "tags": ["<tag>", ...], "end_call": false}}"""


def history_messages(history: list[Turn]) -> list[dict]:
    """The agent's lines are the 'user' side from the caller-model's point of view."""
    msgs = []
    for t in history:
        if not t.text.strip():
            continue
        if t.speaker == "agent":
            msgs.append({"role": "user", "content": f"AGENT: {t.text}"})
        else:
            msgs.append({"role": "assistant", "content": json.dumps({"say": t.text, "tags": [], "end_call": False}, ensure_ascii=False)})
    return msgs


def parse_utterance(data: dict, default_tags: list[str]) -> Utterance:
    say = str(data.get("say", "")).strip()
    tags = [t for t in data.get("tags") or default_tags if t in EMOTION_TAGS]
    return Utterance(text=say or "हाँ?", tags=tags, end_call=bool(data.get("end_call", False)))


class EvonBrain:
    def __init__(self, evon, persona: Persona, behaviour: Behaviour, temperature: float = 0.8, seed: int = 0):
        self.evon, self.persona, self.behaviour = evon, persona, behaviour
        self.temperature = temperature
        self.system = persona_prompt(persona, behaviour)
        self._interjections = list(FALLBACK_INTERJECTIONS.get(persona.tts_lang, FALLBACK_INTERJECTIONS["en-IN"]))
        self._i = seed
        self.replies = 0

    def reply(self, history: list[Turn]) -> Utterance:
        self.replies += 1
        pinned = self.behaviour.lines.get(self.replies)
        if pinned:
            return Utterance(text=pinned, tags=self.persona.emotion[:1])
        msgs = [{"role": "system", "content": self.system}, *history_messages(history)]
        if msgs[-1]["role"] != "user":
            msgs.append({"role": "user", "content": "AGENT: (silence)"})
        data = self.evon.chat_json(msgs, temperature=self.temperature, max_tokens=300)
        return parse_utterance(data, self.persona.emotion)

    def opening(self) -> Utterance:
        return Utterance(text={"gu-IN": "હેલો? કોણ બોલે છે?", "en-IN": "Hello? Who is this?"}.get(
            self.persona.tts_lang, "हेलो? कौन बोल रहा है?"))

    def interjection(self) -> Utterance:
        """Barge-in lines are canned so they fire instantly, as a real interruption would."""
        self._i += 1
        return Utterance(text=self._interjections[self._i % len(self._interjections)], tags=self.persona.emotion[:1])
