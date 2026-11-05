"""Phone targets end to end, without a phone: the reference agent speaks Twilio Media Streams, Diapason plays Twilio
(media_stream), and a fake Twilio relays a "phone call" between Diapason's bridge and the agent (phone)."""

import asyncio

import pytest
import json

import numpy as np
import websockets

from diapason.call.engine import run_call
from diapason.call.telephony import MediaStreamAgent, PhoneAgent, PhoneBridge, mulaw_decode, mulaw_encode, twiml_stream
from diapason.channel import PRESETS
from diapason.fakes import ScriptedBrain, fake_hear, fake_speak
from diapason.reference_agent import serve
from diapason.scenarios import Behaviour, Persona, Scenario
from tests.test_reference_agent import LINES, fake_llm, fake_stt, fake_tts, free_port

SCENARIO = Scenario(id="phone", persona=Persona(id="p", description="d", crm={"name": "रमेश", "loan_id_last4": "4821"}),
                    behaviour=Behaviour(id="coop", instructions="x"), channel=PRESETS["clean"], seed=5)


def test_mulaw_round_trip_is_g711_accurate():
    x = (np.sin(np.linspace(0, 200, 8000)) * 20000).astype("<i2")
    y = np.frombuffer(mulaw_decode(mulaw_encode(x.tobytes())), "<i2").astype(float)
    assert len(mulaw_encode(x.tobytes())) == x.size                    # one byte per sample
    assert np.max(np.abs(y - x) / (np.abs(x) + 64)) < 0.07              # mu-law keeps ~3.5% relative error
    assert mulaw_encode(np.zeros(4, "<i2").tobytes()) == b"\xff" * 4    # silence is 0xFF


async def _agent(port, protocol="twilio"):
    ready = asyncio.Event()
    task = asyncio.create_task(serve("v2", fake_stt, fake_llm, fake_tts, port=port, ready=ready, protocol=protocol))
    await ready.wait()
    return task


@pytest.mark.parametrize("dialect", ["twilio", "exotel", "plivo"])
def test_media_stream_target_drives_an_agent_in_each_platforms_dialect(dialect):
    async def go():
        port = free_port()
        server = await _agent(port, dialect)
        try:
            return await run_call(SCENARIO, MediaStreamAgent(f"ws://127.0.0.1:{port}", dialect=dialect), ScriptedBrain(LINES),
                                  fake_speak(), fake_hear(), max_duration_s=45, agent_silent_timeout_s=7)
        finally:
            server.cancel()
            await asyncio.gather(server, return_exceptions=True)

    rec = asyncio.run(go())
    assert rec.end_reason == "agent_hangup", rec.end_reason
    assert sum(t.speaker == "agent" for t in rec.turns) >= 3
    assert rec.metrics.unanswered_turns == 0


class FakeTwilio:
    """Places a 'call' by joining Diapason's bridge stream to the agent's stream, as Twilio joins two call legs."""

    def __init__(self, bridge_ws, agent_ws):
        self.bridge_ws, self.agent_ws, self.number, self.tasks, self.hung = bridge_ws, agent_ws, "+15550100", [], []

    async def call(self, to, twiml):
        token = twiml.split('name="token" value="')[1].split('"')[0]
        self.tasks.append(asyncio.create_task(self._leg(token)))
        return "CAfake"

    async def hangup(self, sid):
        self.hung.append(sid)

    async def _leg(self, token):
        async with websockets.connect(self.bridge_ws) as b, websockets.connect(self.agent_ws) as a:
            for ws, params in ((b, {"token": token}), (a, {})):
                await ws.send(json.dumps({"event": "start", "start": {"streamSid": "MZ1", "customParameters": params}}))

            async def pipe(src, dst):
                async for raw in src:
                    m = json.loads(raw)
                    if m.get("event") == "media":                   # caller audio -> agent, agent audio -> caller
                        await dst.send(json.dumps({"event": "media", "media": {"payload": m["media"]["payload"]}}))
                await dst.close()
            await asyncio.gather(pipe(b, a), pipe(a, b), return_exceptions=True)


def test_phone_target_through_the_bridge():
    async def go():
        aport, bport = free_port(), free_port()
        server = await _agent(aport)
        bridge = PhoneBridge(f"http://127.0.0.1:{bport}", port=bport)
        twilio = FakeTwilio(f"ws://127.0.0.1:{bport}/stream", f"ws://127.0.0.1:{aport}")
        try:
            rec = await run_call(SCENARIO, PhoneAgent(bridge, "+919800000000", "dial", twilio), ScriptedBrain(LINES),
                                 fake_speak(), fake_hear(), max_duration_s=45, agent_silent_timeout_s=7)
            return rec, twilio
        finally:
            server.cancel()
            bridge.server.should_exit = True
            await asyncio.gather(server, *twilio.tasks, return_exceptions=True)

    rec, twilio = asyncio.run(go())
    assert rec.end_reason == "agent_hangup", rec.end_reason
    assert sum(t.speaker == "agent" for t in rec.turns) >= 3
    assert twilio.hung == ["CAfake"]                                 # Diapason ends the call it placed


def test_inbound_twiml_streams_to_the_bridge():
    xml = twiml_stream("wss://x.trycloudflare.com/stream", {"token": "inbound"})
    assert '<Stream url="wss://x.trycloudflare.com/stream"><Parameter name="token" value="inbound"/>' in xml
