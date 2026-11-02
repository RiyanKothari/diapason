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
    from .call.telephony import MediaStreamAgent
    from .call.transport import WebSocketAgent
    from .caller.brain import EvonBrain
    from .gnani import Evon, Prisma, Timbre
    load_dotenv()
    target_url = url or suite.target.url
    connect = phone_connector(suite) if suite.target.type in ("phone", "inya") else (
        (lambda s: MediaStreamAgent(target_url)) if suite.target.type == "media_stream"
        else (lambda s: WebSocketAgent(target_url, suite.target.sample_rate)))
    tts, stt, evon = Timbre(), Prisma(), Evon()

    def speak(utt, p):
        return tts.synthesize(utt.tts_text(), voice=p.voice, lang=p.tts_lang, speed=p.speed)

    def hear(audio, sr, lang):
        return stt.transcribe_long(audio, sr, lang) if audio.size >= 0.2 * sr else ""

    return Components(
        connect=connect,
        make_brain=lambda s, r: EvonBrain(evon, s.persona, s.behaviour, seed=s.seed + r),
        speak=speak, hear=hear, evon_judge=evon if judge else None, call_kwargs={}, tts=tts,
    )


class PhoneConnector:
    """One bridge for the whole run; remembers each call it placed so Inya's log of it can be fetched afterwards."""

    def __init__(self, suite: Suite):
        import os

        from .call.telephony import PhoneBridge, Twilio
        public = os.environ.get("BHOOL_PUBLIC_URL", "")
        if not public.startswith("https://"):
            raise ValueError("set BHOOL_PUBLIC_URL to the https URL of a tunnel to the bridge port "
                             "(e.g. `cloudflared tunnel --url http://localhost:8790`)")
        self.suite, self.calls = suite, []
        self.bridge = PhoneBridge(public, port=int(os.environ.get("BHOOL_BRIDGE_PORT", "8790")))
        self.twilio = Twilio()
        self.inya = None
        if suite.target.type == "inya":
            from .inya import Inya
            self.inya = Inya()

    def __call__(self, scenario):
        from .call.telephony import PhoneAgent
        t = self.suite.target
        conn = PhoneAgent(self.bridge, number=t.number or "", mode="inya" if t.type == "inya" else "dial",
                          twilio=self.twilio, inya=self.inya, bot_id=t.agent_id or "")
        self.calls.append((scenario.id, conn))
        return conn


def phone_connector(suite: Suite) -> PhoneConnector:
    return PhoneConnector(suite)


def offline_components(suite: Suite, stubborn: bool = False) -> Components:
    from .fakes import ScriptedAgent, ScriptedBrain, fake_hear, fake_speak
    return Components(
        connect=lambda s: ScriptedAgent(sample_rate=suite.target.sample_rate, replies=6, yields=not stubborn,
                                        slots=dict(s.persona.hidden_facts)),
        make_brain=lambda s, r: ScriptedBrain(OFFLINE_LINES),
        speak=fake_speak(), hear=fake_hear(), evon_judge=None,
        call_kwargs={"max_duration_s": 60, "agent_silent_timeout_s": 8},
    )
