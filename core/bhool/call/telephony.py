"""Real phone calls and Twilio Media Streams, as Bhool targets.

Three ways to reach an agent that Bhool does not run itself:

``media_stream``  The agent speaks Twilio Media Streams over a websocket (most voice-agent stacks do: it is how they
                  take phone calls). Bhool plays Twilio: no phone, no telephony bill, same bytes the agent gets live.
``phone``         Bhool dials the agent's phone number through Twilio and bridges the call's audio into the harness.
                  The phone network is the channel: real codec, real jitter, real latency.
``inya``          Bhool asks Gnani's Inya platform to place a test call from an Inya agent to Bhool's own Twilio
                  number (the Trigger Test Call API), answers it, and plays the caller. The agent is a black box.

The harness side of all three is an ``AgentConnection`` at 8 kHz; audio crosses as G.711 mu-law, 20 ms per message.
A phone call carries no CRM, no disposition and no hangup reason: the agent's own record of the call is fetched
afterwards from its platform (``inya.py``) and set beside what Bhool heard.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
from html import escape

import httpx
import numpy as np
import websockets
from fastapi import Request, WebSocket   # module level: FastAPI resolves route annotations from module globals

from .transport import AgentEvent

SR = 8000
_BIAS, _CLIP = 0x84, 32635


def mulaw_encode(pcm16: bytes) -> bytes:
    """PCM16 LE -> G.711 mu-law bytes (ITU-T G.711)."""
    x = np.frombuffer(pcm16, "<i2").astype(np.int32)
    sign = (x < 0).astype(np.int32)
    mag = np.minimum(np.abs(x), _CLIP) + _BIAS
    exp = np.clip(np.floor(np.log2(mag)).astype(np.int32) - 7, 0, 7)
    mant = (mag >> (exp + 3)) & 0x0F
    return (~((sign << 7) | (exp << 4) | mant) & 0xFF).astype(np.uint8).tobytes()


def mulaw_decode(data: bytes) -> bytes:
    """G.711 mu-law bytes -> PCM16 LE."""
    u = ~np.frombuffer(data, np.uint8).astype(np.int32) & 0xFF
    exp, mant = (u >> 4) & 7, u & 0x0F
    mag = (((mant << 3) + _BIAS) << exp) - _BIAS
    return np.where(u & 0x80, -mag, mag).astype("<i2").tobytes()


def media(stream_sid: str, pcm16: bytes) -> str:
    return json.dumps({"event": "media", "streamSid": stream_sid,
                       "media": {"payload": base64.b64encode(mulaw_encode(pcm16)).decode()}})


def twiml_stream(ws_url: str, params: dict | None = None) -> str:
    p = "".join(f'<Parameter name="{escape(k)}" value="{escape(str(v))}"/>' for k, v in (params or {}).items())
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="{escape(ws_url)}">{p}</Stream></Connect></Response>'


class _Stream:
    """One live Media Streams socket, seen from the side that sends caller audio and receives the agent's."""

    def __init__(self, ws, stream_sid: str = ""):
        self.ws, self.sid = ws, stream_sid

    async def send(self, pcm: bytes) -> None:
        try:
            await self.ws.send(media(self.sid, pcm))
        except (websockets.ConnectionClosed, RuntimeError):
            pass

    async def events(self, stop_on: tuple[str, ...] = ("stop",)) -> AsyncIterator[AgentEvent]:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                ev = msg.get("event")
                if ev == "media":
                    yield AgentEvent("audio", audio=mulaw_decode(base64.b64decode(msg["media"]["payload"])))
                elif ev == "clear":
                    yield AgentEvent("clear")
                elif ev == "mark":
                    yield AgentEvent("other", data={"type": "mark", **msg.get("mark", {})})
                elif ev in stop_on:
                    break
        except (websockets.ConnectionClosed, RuntimeError):
            pass
        yield AgentEvent("hangup", data={"reason": "stream closed"})


class MediaStreamAgent:
    """Bhool plays Twilio and connects straight to an agent's Media Streams websocket. The CRM travels as the
    stream's custom parameters, as it would from a Twilio <Stream><Parameter/> on a real call."""

    sample_rate = SR

    def __init__(self, url: str, headers: dict | None = None):
        self.url, self.headers = url, headers or {}
        self.ws, self.stream = None, None
        self.call_sid = "CA" + uuid.uuid4().hex

    async def start(self, scenario_id: str, context: dict | None = None) -> None:
        self.ws = await websockets.connect(self.url, additional_headers=self.headers, max_size=2**24)
        sid = "MZ" + uuid.uuid4().hex
        await self.ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await self.ws.send(json.dumps({"event": "start", "sequenceNumber": "1", "streamSid": sid, "start": {
            "streamSid": sid, "callSid": self.call_sid, "accountSid": "AC" + "0" * 32, "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": SR, "channels": 1},
            "customParameters": {"scenario": scenario_id, **{k: str(v) for k, v in (context or {}).items()}}}}))
        self.stream = _Stream(self.ws, sid)

    async def send_audio(self, pcm: bytes) -> None:
        await self.stream.send(pcm)

    async def events(self) -> AsyncIterator[AgentEvent]:
        async for e in self.stream.events():
            yield e

    async def close(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps({"event": "stop", "streamSid": self.stream.sid}))
            except websockets.ConnectionClosed:
                pass
            await self.ws.close()


class PhoneBridge:
    """Where Twilio sends a live call's audio: POST /voice answers with TwiML that streams to WS /stream.

    Twilio must reach it from the internet, so it runs behind a tunnel; BHOOL_PUBLIC_URL is the tunnel's https URL.
    Calls are matched to waiting harness connections by a token parameter (outbound) or in arrival order (inbound).
    """

    def __init__(self, public_url: str, host: str = "127.0.0.1", port: int = 8790):
        self.public, self.host, self.port = public_url.rstrip("/"), host, port
        self.waiting: dict[str, asyncio.Future] = {}
        self.inbound: asyncio.Queue = asyncio.Queue()
        self.server = None

    @property
    def ws_url(self) -> str:
        return self.public.replace("https://", "wss://").replace("http://", "ws://") + "/stream"

    async def start(self) -> None:
        if self.server is not None:
            return
        import uvicorn
        from fastapi import FastAPI, Response

        app = FastAPI()

        @app.post("/voice")
        async def voice(request: Request):             # an inbound call to Bhool's number (e.g. an Inya test call)
            return Response(twiml_stream(self.ws_url, {"token": "inbound"}), media_type="application/xml")

        @app.websocket("/stream")
        async def stream(ws: WebSocket):
            await ws.accept()
            sock = _StarletteSocket(ws)
            sid, token = "", "inbound"
            async for raw in sock:                     # read up to "start" to learn the stream and its token
                msg = json.loads(raw)
                if msg.get("event") == "start":
                    sid = msg["start"]["streamSid"]
                    token = msg["start"].get("customParameters", {}).get("token", "inbound")
                    break
            done = asyncio.get_running_loop().create_future()
            s = _Stream(sock, sid)
            s.done = done
            fut = self.waiting.pop(token, None)
            if fut is not None and not fut.done():
                fut.set_result(s)
            else:
                await self.inbound.put(s)
            await done                                 # keep the socket open until the harness hangs up

        self.server = uvicorn.Server(uvicorn.Config(app, host=self.host, port=self.port, log_level="warning"))
        asyncio.create_task(self.server.serve())
        while not self.server.started:
            await asyncio.sleep(0.05)

    def expect(self, token: str) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self.waiting[token] = fut
        return fut


class _StarletteSocket:
    """Starlette's WebSocket with the send / async-iteration surface _Stream expects from `websockets`."""

    def __init__(self, ws):
        self.ws = ws

    async def send(self, text: str) -> None:
        try:
            await self.ws.send_text(text)
        except Exception as e:                       # WebSocketDisconnect, uvicorn's ClientDisconnected, send after close
            raise RuntimeError("closed") from e

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return await self.ws.receive_text()
        except Exception:                            # disconnects surface as several exception types
            raise StopAsyncIteration from None

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            pass


class Twilio:
    """The two Twilio REST calls Bhool needs: place a call, end a call. Plain HTTP, no SDK."""

    def __init__(self, sid: str | None = None, token: str | None = None, number: str | None = None,
                 http: httpx.AsyncClient | None = None):
        self.sid = sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
        self.token = token or os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.number = number or os.environ.get("TWILIO_NUMBER", "")
        if not (self.sid and self.token and self.number):
            raise ValueError("set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_NUMBER in .env")
        self.http = http or httpx.AsyncClient(timeout=20)
        self.base = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}"

    async def call(self, to: str, twiml: str) -> str:
        r = await self.http.post(f"{self.base}/Calls.json", auth=(self.sid, self.token),
                                 data={"To": to, "From": self.number, "Twiml": twiml})
        if r.status_code >= 300:
            raise RuntimeError(f"Twilio HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["sid"]

    async def hangup(self, call_sid: str) -> None:
        await self.http.post(f"{self.base}/Calls/{call_sid}.json", auth=(self.sid, self.token), data={"Status": "completed"})


class PhoneAgent:
    """A real phone call. mode="dial": Bhool calls `number`. mode="inya": an Inya agent calls Bhool's number."""

    sample_rate = SR

    def __init__(self, bridge: PhoneBridge, number: str = "", mode: str = "dial", twilio: Twilio | None = None,
                 inya=None, bot_id: str = "", answer_timeout_s: float = 60.0):
        self.bridge, self.number, self.mode, self.twilio, self.inya, self.bot_id = bridge, number, mode, twilio, inya, bot_id
        self.timeout = answer_timeout_s
        self.stream: _Stream | None = None
        self.call_sid = ""
        self.meta: dict = {}

    async def start(self, scenario_id: str, context: dict | None = None) -> None:
        await self.bridge.start()
        if self.mode == "dial":
            token = uuid.uuid4().hex
            fut = self.bridge.expect(token)
            self.call_sid = await self.twilio.call(self.number, twiml_stream(self.bridge.ws_url, {"token": token}))
            self.stream = await asyncio.wait_for(fut, self.timeout)
        else:
            ref = f"bhool-{scenario_id}-{uuid.uuid4().hex[:8]}"
            num = self.twilio.number if self.twilio else self.number
            cc, local = ("+" + num.lstrip("+")[:-10], num[-10:]) if len(num.lstrip("+")) > 10 else ("+91", num)
            self.meta = await asyncio.to_thread(self.inya.trigger_call, self.bot_id, local, cc, ref, ref)
            self.meta["clientReferenceId"] = ref
            self.stream = await asyncio.wait_for(self.bridge.inbound.get(), self.timeout)

    async def send_audio(self, pcm: bytes) -> None:
        if self.stream:
            await self.stream.send(pcm)

    async def events(self) -> AsyncIterator[AgentEvent]:
        async for e in self.stream.events():
            yield e

    async def close(self) -> None:
        if self.call_sid and self.twilio:
            try:
                await self.twilio.hangup(self.call_sid)
            except httpx.HTTPError:
                pass
        if self.stream is not None:
            await self.stream.ws.close()
            if getattr(self.stream, "done", None) and not self.stream.done.done():
                self.stream.done.set_result(None)
