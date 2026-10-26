"""Clients for Gnani Prisma (STT), Timbre (TTS) and Evon (LLM).

Contracts follow docs.gnani.ai: REST STT POST /stt/v3, realtime STT wss /stt/v3/stream
(1024-byte PCM16 frames at real-time pace), TTS POST /api/v1/tts/inference.
Evon is reached through any OpenAI-compatible endpoint (Gnani-hosted, vLLM or Friendli).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import websockets

from .audio import float_to_pcm16, read_wav, wav_bytes

BASE = "https://api.vachana.ai"
STT_WS = "wss://api.vachana.ai/stt/v3/stream"
FRAME_BYTES = 1024
RETRY_STATUS = {429, 500, 503}


class GnaniError(RuntimeError):
    pass


def _key(explicit: str | None) -> str:
    key = explicit or os.environ.get("GNANI_API_KEY")
    if not key:
        raise GnaniError("GNANI_API_KEY is not set (copy .env.example to .env)")
    return key


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code == 200:
        return
    try:
        err = resp.json().get("error", {})
        msg = f"{err.get('type', 'error')}: {err.get('message', resp.text[:200])}"
    except ValueError:
        msg = resp.text[:200]
    raise GnaniError(f"HTTP {resp.status_code} {msg}")


def _post_with_retry(client: httpx.Client, url: str, attempts: int = 4, **kw) -> httpx.Response:
    for i in range(attempts):
        resp = client.post(url, **kw)
        if resp.status_code not in RETRY_STATUS or i == attempts - 1:
            return resp
        time.sleep(min(8, 0.5 * 2**i))
    return resp


class Prisma:
    """Speech-to-text."""

    def __init__(self, api_key: str | None = None, timeout: float = 60):
        self.key = _key(api_key)
        self.http = httpx.Client(timeout=timeout)

    def transcribe(self, audio: np.ndarray, sr: int, lang: str = "hi-IN", fmt: str = "verbatim") -> dict:
        """REST transcription for clips up to 60 s. Returns the API's JSON."""
        if audio.size / sr > 60:
            raise GnaniError("REST STT accepts at most 60 s; use transcribe_long or batch")
        resp = _post_with_retry(
            self.http, f"{BASE}/stt/v3",
            headers={"X-API-Key-ID": self.key},
            files={"audio_file": ("audio.wav", wav_bytes(audio, sr), "audio/wav")},
            data={"language_code": lang, "format": fmt},
        )
        _raise_for(resp)
        return resp.json()

    def transcribe_long(self, audio: np.ndarray, sr: int, lang: str = "hi-IN", chunk_s: float = 30) -> str:
        n = int(chunk_s * sr)
        return " ".join(
            self.transcribe(audio[i : i + n], sr, lang)["transcript"].strip() for i in range(0, audio.size, n)
        ).strip()


@dataclass
class StreamEvent:
    type: str
    text: str = ""
    latency_ms: int | None = None
    segment_index: int | None = None
    raw: dict | None = None


async def stream_transcribe(
    chunks: AsyncIterator[bytes],
    sr: int = 16000,
    lang: str = "hi-IN",
    api_key: str | None = None,
    telephony_vad: bool = False,
) -> AsyncIterator[StreamEvent]:
    """Realtime STT. `chunks` must yield PCM16 mono at real-time pace; frames are re-cut to 1024 bytes."""
    headers = {"x-api-key-id": _key(api_key), "lang_code": lang, "x-sample-rate": str(sr)}
    if telephony_vad:
        headers.update({"x-vad-threshold": "0.7", "x-min-speech-ms": "200", "x-min-silence-ms": "500"})
    async with websockets.connect(STT_WS, additional_headers=headers) as ws:
        async def sender():
            buf = b""
            async for chunk in chunks:
                buf += chunk
                while len(buf) >= FRAME_BYTES:
                    await ws.send(buf[:FRAME_BYTES])
                    buf = buf[FRAME_BYTES:]
            if buf:
                await ws.send(buf.ljust(FRAME_BYTES, b"\0"))
            await asyncio.sleep(1.5)   # let the final segment flush; the API has no end-of-stream message
            await ws.close()

        task = asyncio.create_task(sender())
        try:
            async for msg in ws:
                evt = json.loads(msg)
                if evt.get("type") == "error":
                    raise GnaniError(evt.get("message", "stream error"))
                yield StreamEvent(
                    type=evt.get("type", ""), text=evt.get("text", ""),
                    latency_ms=evt.get("latency"), segment_index=evt.get("segment_index"), raw=evt,
                )
        finally:
            task.cancel()


async def paced_frames(audio: np.ndarray, sr: int) -> AsyncIterator[bytes]:
    """Yield 1024-byte PCM16 frames at real-time cadence, as the realtime API requires."""
    pcm = float_to_pcm16(audio)
    frame_s = (FRAME_BYTES // 2) / sr
    t0 = time.monotonic()
    for i, off in enumerate(range(0, len(pcm), FRAME_BYTES)):
        yield pcm[off : off + FRAME_BYTES]
        await asyncio.sleep(max(0.0, t0 + (i + 1) * frame_s - time.monotonic()))


class Timbre:
    """Text-to-speech with an on-disk cache keyed by every input that changes the audio."""

    def __init__(self, api_key: str | None = None, cache_dir: str | Path = ".cache/tts", timeout: float = 60):
        self.key = _key(api_key)
        self.http = httpx.Client(timeout=timeout)
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.calls = self.hits = self.chars = 0

    def synthesize(
        self, text: str, voice: str = "Shivani", lang: str = "hi-en",
        model: str = "timbre-v3.0", speed: float = 1.0, sr: int = 16000,
    ) -> tuple[np.ndarray, int]:
        body = {
            "text": text, "voice": voice, "model": model, "language": lang, "speed": speed,
            "audio_config": {"container": "wav", "encoding": "linear_pcm", "sample_rate": sr, "num_channels": 1, "sample_width": 2},
        }
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
        path = self.cache / f"{digest}.wav"
        if path.exists():
            self.hits += 1
            return read_wav(path)
        resp = _post_with_retry(
            self.http, f"{BASE}/api/v1/tts/inference",
            headers={"X-API-Key-ID": self.key, "Content-Type": "application/json"}, json=body,
        )
        _raise_for(resp)
        self.calls += 1
        self.chars += len(text)
        path.write_bytes(resp.content)
        return read_wav(resp.content)


class Evon:
    """Evon v3.3 through an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, timeout: float = 120):
        self.base = (base_url or os.environ.get("EVON_BASE_URL", "")).rstrip("/")
        if not self.base:
            raise GnaniError("EVON_BASE_URL is not set (copy .env.example to .env)")
        self.model = model or os.environ.get("EVON_MODEL", "gnani/gnani-evon-v3.3-30B-A3B")
        key = api_key or os.environ.get("EVON_API_KEY")
        self.http = httpx.Client(timeout=timeout, headers={"Authorization": f"Bearer {key}"} if key else {})

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 512, json_mode: bool = False) -> str:
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        resp = _post_with_retry(self.http, f"{self.base}/chat/completions", json=body)
        if resp.status_code != 200:
            raise GnaniError(f"Evon HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"]

    def chat_json(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 1500) -> dict:
        """Ask for JSON; tolerate models that wrap it in prose or code fences."""
        text = self.chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise GnaniError(f"Evon returned no JSON object: {text[:200]}")
        return json.loads(text[start : end + 1])
