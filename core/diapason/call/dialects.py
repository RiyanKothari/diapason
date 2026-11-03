"""The media-stream dialects of the telephony platforms Indian voice agents run on: Twilio, Exotel and Plivo.

All three put a phone call's audio on a websocket as JSON events with base64 audio, 8 kHz mono, 20 ms per message, but
each names things its own way: Twilio says ``streamSid`` and sends mu-law; Exotel says ``stream_sid`` and sends raw
16-bit PCM (slin); Plivo says ``streamId``, takes the agent's audio as ``playAudio`` and a barge-in as ``clearAudio``.
A ``Dialect`` speaks both sides of one of them, so Diapason can play the platform to an agent (testing), play an agent to
the platform (the reference agent), or sit between the two (Shield).

Formats follow each platform's published stream documentation. Every dialect round-trips through Diapason's own
simulators in the tests; none has yet been run against a live Exotel or Plivo account.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from .telephony import mulaw_decode, mulaw_encode

SR = 8000


@dataclass(frozen=True)
class Dialect:
    name: str
    encoding: str           # "mulaw" | "slin" (16-bit little-endian PCM)
    sid_key: str            # how the stream id is spelt at the top level of each event

    # ------------------------------------------------------------------ audio
    def encode(self, pcm16: bytes) -> str:
        return base64.b64encode(mulaw_encode(pcm16) if self.encoding == "mulaw" else pcm16).decode()

    def decode(self, payload: str) -> bytes:
        raw = base64.b64decode(payload)
        return mulaw_decode(raw) if self.encoding == "mulaw" else raw

    # ------------------------------------------------------------------ the platform's side (what it sends an agent)
    def opening(self, sid: str, call_id: str, params: dict) -> list[dict]:
        p = {k: str(v) for k, v in params.items()}
        if self.name == "exotel":
            return [{"event": "connected"},
                    {"event": "start", "sequence_number": 1, "stream_sid": sid,
                     "start": {"stream_sid": sid, "call_sid": call_id, "account_sid": "diapason", "from": "", "to": "",
                               "custom_parameters": p,
                               "media_format": {"encoding": "base64", "sample_rate": str(SR), "bit_rate": "128kbps"}}}]
        if self.name == "plivo":
            return [{"event": "start", "sequenceNumber": 0,
                     "start": {"callId": call_id, "streamId": sid, "accountId": "diapason", "tracks": ["inbound"],
                               "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": SR}},
                     "extra_headers": json.dumps(p, ensure_ascii=False)}]
        return [{"event": "connected", "protocol": "Call", "version": "1.0.0"},
                {"event": "start", "sequenceNumber": "1", "streamSid": sid,
                 "start": {"streamSid": sid, "callSid": call_id, "accountSid": "AC" + "0" * 32, "tracks": ["inbound"],
                           "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": SR, "channels": 1},
                           "customParameters": p}}]

    def caller_media(self, sid: str, pcm16: bytes) -> dict:
        media = {"payload": self.encode(pcm16)}
        if self.name == "plivo":
            media["track"] = "inbound"
        return {"event": "media", self.sid_key: sid, "media": media}

    def stop(self, sid: str) -> dict:
        return {"event": "stop", self.sid_key: sid}

    # ------------------------------------------------------------------ the agent's side (what it sends back)
    def agent_media(self, sid: str, pcm16: bytes) -> dict:
        if self.name == "plivo":
            return {"event": "playAudio", "media": {"contentType": "audio/x-mulaw", "sampleRate": SR, "payload": self.encode(pcm16)}}
        return {"event": "media", self.sid_key: sid, "media": {"payload": self.encode(pcm16)}}

    def agent_clear(self, sid: str) -> dict:
        return {"event": "clearAudio", "streamId": sid} if self.name == "plivo" else {"event": "clear", self.sid_key: sid}

    # ------------------------------------------------------------------ either side
    def parse(self, msg: dict) -> tuple[str, object]:
        """(kind, value): ("start", (sid, params)) | ("media", pcm16) | ("clear", None) | ("mark", name) | ("stop", None)
        | ("connected", None) | ("other", msg)."""
        ev = msg.get("event")
        if ev == "start":
            s = msg.get("start") or {}
            sid = s.get("streamSid") or s.get("stream_sid") or s.get("streamId") or msg.get(self.sid_key) or ""
            params = s.get("customParameters") or s.get("custom_parameters") or {}
            if not params and msg.get("extra_headers"):
                try:
                    params = json.loads(msg["extra_headers"])
                except ValueError:
                    params = dict(kv.split("=", 1) for kv in str(msg["extra_headers"]).split(",") if "=" in kv)
            return "start", (sid, dict(params))
        if ev in ("media", "playAudio"):
            return "media", self.decode((msg.get("media") or {}).get("payload", ""))
        if ev in ("clear", "clearAudio"):
            return "clear", None
        if ev in ("mark", "checkpoint"):
            return "mark", (msg.get("mark") or {}).get("name") or msg.get("name")
        if ev == "stop":
            return "stop", None
        if ev == "connected":
            return "connected", None
        return "other", msg


DIALECTS = {d.name: d for d in (Dialect("twilio", "mulaw", "streamSid"), Dialect("exotel", "slin", "stream_sid"),
                                Dialect("plivo", "mulaw", "streamId"))}


def dialect(name: str) -> Dialect:
    if name not in DIALECTS:
        raise ValueError(f"unknown stream dialect {name!r}: use one of {', '.join(DIALECTS)}")
    return DIALECTS[name]
