"""Assemble the pieces run_suite needs: live (Gnani APIs) or offline (fakes, zero credits)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from .scenarios import Suite

OFFLINE_LINES = ["हाँ बोलिए", "मेरा loan ID चार आठ दो एक है", "पंद्रह तारीख को pay कर दूंगा", "ठीक है, bye"]


@dataclass
class Components:
    connect: Any
    make_brain: Any
    speak: Any
    hear: Any
    evon_judge: Any
    call_kwargs: dict
    tts: Any = None


def live_components(suite: Suite, url: str | None = None, judge: bool = True) -> Components:
    from .call.transport import WebSocketAgent
    from .caller.brain import EvonBrain
    from .gnani import Evon, Prisma, Timbre
    load_dotenv()
    if suite.target.type != "websocket":
        raise ValueError(f"target type {suite.target.type!r} is not wired yet; use websocket")
    target_url = url or suite.target.url
    tts, stt, evon = Timbre(), Prisma(), Evon()

    def speak(utt, p):
        return tts.synthesize(utt.tts_text(), voice=p.voice, lang=p.tts_lang, speed=p.speed)

    def hear(audio, sr, lang):
        return stt.transcribe_long(audio, sr, lang) if audio.size >= 0.2 * sr else ""

    return Components(
        connect=lambda s: WebSocketAgent(target_url, suite.target.sample_rate),
        make_brain=lambda s, r: EvonBrain(evon, s.persona, s.behaviour, seed=s.seed + r),
        speak=speak, hear=hear, evon_judge=evon if judge else None, call_kwargs={}, tts=tts,
    )


def offline_components(suite: Suite, stubborn: bool = False) -> Components:
    from .fakes import ScriptedAgent, ScriptedBrain, fake_hear, fake_speak
    return Components(
        connect=lambda s: ScriptedAgent(sample_rate=suite.target.sample_rate, replies=6, yields=not stubborn,
                                        slots=dict(s.persona.hidden_facts)),
        make_brain=lambda s, r: ScriptedBrain(OFFLINE_LINES),
        speak=fake_speak(), hear=fake_hear(), evon_judge=None,
        call_kwargs={"max_duration_s": 60, "agent_silent_timeout_s": 8},
    )
