"""How the harness talks to the agent under test.

WebSocket protocol (mirrors Twilio Media Streams semantics so phone adapters map 1:1):
  harness -> agent  text   {"type": "start", "scenario": id, "sample_rate": sr, "context": {crm fields}}
                    binary PCM16 LE mono at sample_rate, one 20 ms frame per message, real-time pace
  agent -> harness  binary PCM16 LE mono at sample_rate, any pace (the harness plays it out in real time)
                    text   {"type": "clear"}        flush audio not yet played (the agent yielded to a barge-in)
                    text   {"type": "disposition", "slots": {...}}   what the agent captured, for checking
                    text   {"type": "hangup"}       the agent ended the call
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

import websockets


@dataclass
class AgentEvent:
    kind: Literal["audio", "clear", "disposition", "hangup", "other"]
    audio: bytes = b""
    data: dict = field(default_factory=dict)


class AgentConnection(Protocol):
    sample_rate: int

    async def start(self, scenario_id: str, context: dict | None = None) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    def events(self) -> AsyncIterator[AgentEvent]: ...
    async def close(self) -> None: ...


class WebSocketAgent:
    def __init__(self, url: str, sample_rate: int = 16000, headers: dict | None = None):
        self.url, self.sample_rate, self.headers = url, sample_rate, headers or {}
        self.ws = None

    async def start(self, scenario_id: str, context: dict | None = None) -> None:
        self.ws = await websockets.connect(self.url, additional_headers=self.headers, max_size=2**24)
        await self.ws.send(json.dumps({"type": "start", "scenario": scenario_id, "sample_rate": self.sample_rate,
                                       "context": context or {}}, ensure_ascii=False))

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self.ws.send(pcm)
        except websockets.ConnectionClosed:
            pass   # the receiver reports the hangup

    async def events(self) -> AsyncIterator[AgentEvent]:
        try:
            async for msg in self.ws:
                if isinstance(msg, bytes):
                    yield AgentEvent("audio", audio=msg)
                    continue
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                kind = data.get("type")
                yield AgentEvent(kind if kind in ("clear", "disposition", "hangup") else "other", data=data)
        except websockets.ConnectionClosed:
            pass
        yield AgentEvent("hangup", data={"reason": "connection closed"})

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
