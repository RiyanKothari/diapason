"""Offline stand-ins for the agent under test and for Gnani's models.

They let the whole harness run end to end with zero API credits: in tests, in
`bhool selftest`, and while designing suites.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np

from .audio import float_to_pcm16, pcm16_to_float
from .caller.brain import Turn, Utterance
from .call.transport import AgentEvent


def tone(seconds: float, sr: int, f0: float = 200.0, amp: float = 0.25) -> np.ndarray:
    """Speech-like stand-in: a harmonic tone with a 4 Hz syllabic envelope that never goes silent."""
    t = np.arange(int(seconds * sr)) / sr
    env = 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 2 * t))
    return (amp * env * (np.sin(2 * np.pi * f0 * t) + 0.4 * np.sin(2 * np.pi * 2.5 * f0 * t))).astype(np.float32)


class ScriptedAgent:
    """A fake voice agent with controllable flaws.

    latency_s:   delay after it decides the caller finished, before it replies
    reply_s:     length of each reply
    yields:      stops talking (sends "clear") when the caller barges in
    yield_s:     how long it takes to yield
    replies:     replies before it sends a disposition and hangs up (greeting excluded)
    burst:       sends each reply all at once (like a fast TTS) instead of in real time
    """

    def __init__(self, sample_rate: int = 16000, latency_s: float = 0.6, reply_s: float = 1.5,
                 greeting_s: float = 1.2, yields: bool = True, yield_s: float = 0.4, replies: int = 3,
                 end_silence_s: float = 0.5, slots: dict | None = None, burst: bool = True):
        self.sample_rate = sample_rate
        self.latency_s, self.reply_s, self.greeting_s = latency_s, reply_s, greeting_s
        self.yields, self.yield_s, self.max_replies = yields, yield_s, replies
        self.end_silence_s, self.slots, self.burst = end_silence_s, slots or {}, burst
        self.q: asyncio.Queue = asyncio.Queue()
        self.t = 0.0                 # agent clock, advanced by received caller frames
        self.caller_talking = False
        self.caller_speech_s = 0.0
        self.caller_quiet_s = 0.0
        self.playing_until = 0.0     # agent-clock time its queued audio finishes playing
        self.reply_at: float | None = None
        self.yield_at: float | None = None
        self.replies = 0
        self.done = False

    async def start(self, scenario_id: str, context: dict | None = None) -> None:
        self._speak(self.greeting_s, f0=170)

    def _speak(self, seconds: float, f0: float = 200.0) -> None:
        self.playing_until = max(self.playing_until, self.t) + seconds
        self.q.put_nowait(AgentEvent("audio", audio=float_to_pcm16(tone(seconds, self.sample_rate, f0))))

    async def send_audio(self, pcm: bytes) -> None:
        if self.done:
            return
        x = pcm16_to_float(pcm)
        self.t += x.size / self.sample_rate
        loud = 10 * np.log10(np.mean(np.square(x, dtype=np.float64)) + 1e-12) > -40
        dt = x.size / self.sample_rate
        if loud:
            self.caller_talking, self.caller_quiet_s = True, 0.0
            self.caller_speech_s += dt
            self.reply_at = None
            if self.yields and self.playing_until > self.t and self.yield_at is None:
                self.yield_at = self.t + self.yield_s
        elif self.caller_talking:
            self.caller_quiet_s += dt
            if self.caller_quiet_s >= self.end_silence_s:
                self.caller_talking = False
                if self.caller_speech_s >= 0.2:
                    self.reply_at = self.t + self.latency_s
                self.caller_speech_s = 0.0
        if self.yield_at is not None and self.t >= self.yield_at:
            self.yield_at = None
            if self.playing_until > self.t:
                self.playing_until = self.t
                self.q.put_nowait(AgentEvent("clear"))
        if self.reply_at is not None and self.t >= self.reply_at:
            self.reply_at = None
            if self.replies >= self.max_replies:
                self.done = True
                self.q.put_nowait(AgentEvent("disposition", data={"type": "disposition", "slots": self.slots}))
                self.q.put_nowait(AgentEvent("hangup"))
                return
            self.replies += 1
            self._speak(self.reply_s)

    async def events(self) -> AsyncIterator[AgentEvent]:
        while True:
            ev = await self.q.get()
            yield ev
            if ev.kind == "hangup":
                return

    async def close(self) -> None:
        self.done = True


class ScriptedBrain:
    """Says its lines in order; the last one ends the call."""

    def __init__(self, lines: list[str], interjection: str = "रुको रुको"):
        self.lines, self.i, self._interjection = lines, 0, interjection

    def reply(self, history: list[Turn]) -> Utterance:
        line = self.lines[min(self.i, len(self.lines) - 1)]
        self.i += 1
        return Utterance(line, end_call=self.i >= len(self.lines))

    def opening(self) -> Utterance:
        return Utterance("hello?")

    def interjection(self) -> Utterance:
        return Utterance(self._interjection)


def fake_speak(seconds_per_char: float = 0.03, min_s: float = 0.6, max_s: float = 2.5):
    def speak(utt: Utterance, persona) -> tuple[np.ndarray, int]:
        return tone(min(max_s, max(min_s, len(utt.text) * seconds_per_char)), 16000, f0=240), 16000
    return speak


def fake_hear(text: str = "(agent speech)"):
    def hear(audio: np.ndarray, sr: int, lang: str) -> str:
        return f"{text} {audio.size / sr:.1f}s"
    return hear
