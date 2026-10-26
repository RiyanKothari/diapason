"""The reference agent over a real websocket, driven by the real harness, with fake models.

Proves the seeded engineering bugs are measurable: v1's fixed VAD fails on street noise and
v1 ignores barge-ins; v2 handles both.
"""

import asyncio
import socket

import numpy as np

from bhool.call.engine import run_call
from bhool.call.transport import WebSocketAgent
from bhool.channel import PRESETS
from bhool.fakes import ScriptedBrain, fake_hear, fake_speak, tone
from bhool.reference_agent import serve
from bhool.scenarios import Behaviour, Persona, Scenario


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fake_stt(audio, sr, lang):
    return "हाँ जी" if audio.size > 0 else ""


def fake_llm(messages):
    users = sum(m["role"] == "user" for m in messages)
    return {"say": "जी, समझ गई। आप कब pay करेंगे?", "lang": "hi-IN",
            "slots": {"promise_to_pay_date": "15 November"} if users >= 2 else {}, "end_call": users >= 3}


def fake_tts(text, voice, lang, seconds_per_char=0.04):
    sr = 16000
    return tone(min(6.0, max(0.8, len(text) * seconds_per_char)), sr, f0=170), sr


async def call(version, behaviour, channel, lines, tts=fake_tts):
    port = free_port()
    ready = asyncio.Event()
    server = asyncio.create_task(serve(version, fake_stt, fake_llm, tts, port=port, ready=ready))
    await ready.wait()
    try:
        s = Scenario(id="ref", persona=Persona(id="p", description="d", crm={"name": "रमेश"}),
                     behaviour=behaviour, channel=PRESETS[channel], seed=5)
        return await run_call(s, WebSocketAgent(f"ws://127.0.0.1:{port}"), ScriptedBrain(lines),
                              fake_speak(), fake_hear(), max_duration_s=45, agent_silent_timeout_s=7)
    finally:
        server.cancel()
        await asyncio.gather(server, return_exceptions=True)


COOP = Behaviour(id="coop", instructions="x")
INTERRUPT = Behaviour(id="int", instructions="x", interrupt_prob=1.0)
LINES = ["हाँ बोलिए", "चार आठ दो एक", "पंद्रह को", "ठीक है"]


def test_v2_completes_call_with_disposition():
    rec = asyncio.run(call("v2", COOP, "clean", LINES))
    assert rec.end_reason == "agent_hangup", rec.end_reason
    assert rec.dispositions and rec.dispositions[0]["slots"]["promise_to_pay_date"] == "15 November"
    assert rec.metrics.unanswered_turns == 0


def test_v1_fixed_vad_breaks_on_in_band_noise_v2_does_not():
    # Crowd babble sits inside the 300-3400 Hz phone band (traffic rumble mostly doesn't),
    # so it is what defeats a fixed-threshold VAD.
    v1 = asyncio.run(call("v1", COOP, "market", LINES))
    v2 = asyncio.run(call("v2", COOP, "market", LINES))
    # v1 hears the crowd as endless speech, so it never takes its turn.
    assert v1.end_reason == "agent_silent" or v1.metrics.unanswered_turns > 0
    assert v2.end_reason == "agent_hangup", v2.end_reason
    assert v2.metrics.unanswered_turns == 0


def test_v1_ignores_barge_in_v2_yields():
    long_tts = lambda text, voice, lang: fake_tts(text, voice, lang, seconds_per_char=0.12)  # noqa: E731
    v1 = asyncio.run(call("v1", INTERRUPT, "clean", LINES, tts=long_tts))
    v2 = asyncio.run(call("v2", INTERRUPT, "clean", LINES, tts=long_tts))
    assert v1.metrics.barge_ins >= 1 and v1.metrics.barge_ins_ignored >= 1
    assert v2.metrics.barge_ins >= 1 and v2.metrics.barge_ins_ignored == 0
