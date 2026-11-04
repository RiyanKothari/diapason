"""Diapason Shield: a compliance monitor in front of any voice agent's phone line. No change to the agent.

The telephony platform (Twilio, Exotel or Plivo) streams the call to Shield instead of to the agent; Shield opens the
same stream to the agent and relays both ways, untouched. It listens to the agent's side as it plays: each utterance is
transcribed (Prisma) and run through Guard's rules: banned threats, requests for secrets, the recording disclosure,
account details spoken before the caller proved who they are. The caller's side can be transcribed too, so Shield knows
when verification happened.

mode="monitor"  the call is never touched; every utterance is logged with its verdict, live. Zero added latency.
mode="block"    each agent utterance is held until it has been checked. A clean one plays; a violating one is dropped,
                or replaced by Guard's corrected line spoken with Timbre when a voice is given. The cost is latency:
                the length of the utterance plus transcription, measured and logged per utterance as ``held_ms``.

Guard (guard.py) is the same check inside an agent Diapason builds; Shield is the same check outside one it didn't.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import websockets

from .call.dialects import SR, dialect
from .guard import Guard

VIOLATIONS = ("dropped", "replaced")       # Guard actions that mean the line must not be spoken as it was
FRAME = SR // 50                           # 20 ms


@dataclass
class ShieldEvent:
    call: str
    t: float
    side: str                  # agent | caller
    text: str
    verdict: str               # ok | flagged | blocked | replaced | heard
    rules: list = field(default_factory=list)
    said_instead: str = ""
    held_ms: float | None = None
    at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))      # wall clock, for incidents


class _Utterances:
    """Cuts a stream of 8 kHz PCM into utterances: speech that ends in half a second of quiet, or a gap in the stream."""

    def __init__(self, quiet_s: float = 0.5, floor: float = 300.0):
        self.buf, self.quiet, self.voiced = [], 0, False
        self.quiet_n, self.floor = int(quiet_s * SR), floor

    def push(self, pcm: bytes) -> bytes | None:
        x = np.frombuffer(pcm, "<i2")
        self.buf.append(pcm)
        loud = x.size and float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) > self.floor
        self.voiced |= bool(loud)
        self.quiet = 0 if loud else self.quiet + x.size
        return self.flush() if self.voiced and self.quiet >= self.quiet_n else None

    def flush(self) -> bytes | None:
        out = b"".join(self.buf) if self.voiced else None
        self.buf, self.quiet, self.voiced = [], 0, False
        return out


class Shield:
    def __init__(self, agent_url: str, hear: Callable[[np.ndarray, int], str], dialect_name: str = "twilio",
                 mode: str = "monitor", crm: dict | None = None, speak: Callable[[str], bytes] | None = None,
                 listen_caller: bool = True, banned: list[str] | None = None, gap_s: float = 0.45,
                 on_event: Callable[[dict], None] | None = None, log_dir: Path | None = None):
        if mode not in ("monitor", "block"):
            raise ValueError("mode is monitor or block")
        self.agent_url, self.hear, self.d, self.mode = agent_url, hear, dialect(dialect_name), mode
        self.crm, self.speak, self.listen_caller, self.gap_s = crm or {}, speak, listen_caller, gap_s
        self.banned, self.on_event, self.log_dir = banned, on_event, log_dir
        self.calls: dict[str, list[ShieldEvent]] = {}

    # ------------------------------------------------------------------ one call
    async def handle(self, tel) -> None:
        opening, sid, params = [], "", {}
        async for raw in tel:                                  # everything up to "start" goes to the agent as is
            opening.append(raw)
            kind, value = self.d.parse(json.loads(raw))
            if kind == "start":
                sid, params = value
                break
        crm = {**self.crm, **{k: v for k, v in params.items() if k != "scenario"}}
        guard = Guard(crm=crm, **({"banned": self.banned} if self.banned else {}))
        call, t0 = sid or f"call-{len(self.calls) + 1}", time.perf_counter()
        self.calls[call] = []
        try:
            agent = await websockets.connect(self.agent_url, max_size=2**24)
        except Exception as e:
            self._emit(ShieldEvent(call, 0.0, "agent", f"could not reach the agent: {e}", "error"))
            return
        for raw in opening:
            await agent.send(raw)
        up = asyncio.create_task(self._caller_side(tel, agent, guard, call, t0))
        down = asyncio.create_task(self._agent_side(agent, tel, guard, call, sid, t0))
        try:
            await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (up, down):
                task.cancel()
            await asyncio.gather(up, down, return_exceptions=True)
            for ws in (agent, tel):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._save(call)

    async def _caller_side(self, tel, agent, guard: Guard, call: str, t0: float) -> None:
        cut = _Utterances()
        async for raw in tel:
            await agent.send(raw)                               # the caller is never delayed
            kind, value = self.d.parse(json.loads(raw))
            if kind == "media" and self.listen_caller and (pcm := cut.push(value)):
                text = await self._transcribe(pcm)
                if text:
                    guard.hear(text)
                    self._emit(ShieldEvent(call, self._t(t0), "caller", text, "heard"))
            elif kind == "stop":
                break

    async def _agent_side(self, agent, tel, guard: Guard, call: str, sid: str, t0: float) -> None:
        cut, held, start = _Utterances(), [], None

        async def finish(pcm: bytes | None) -> None:
            nonlocal held, start
            msgs, began, held, start = held, start, [], None
            if not pcm:
                for m in msgs:
                    await tel.send(m)
                return
            text = await self._transcribe(pcm)
            before = len(guard.events)
            after = guard.filter(text) if text else ""
            new = guard.events[before:]
            rules = [{"rule": e.rule, "action": e.action, **({"matched": e.matched} if e.matched else {})} for e in new]
            bad = any(e.action in VIOLATIONS for e in new)
            missing_disclosure = any(e.rule == "missing_disclosure" for e in new)
            held_ms = round((time.perf_counter() - began) * 1000) if began and self.mode == "block" else None
            if self.mode == "monitor":
                verdict, said = ("flagged" if new else "ok"), ""
            elif bad or (missing_disclosure and self.speak):
                if self.speak and after:
                    said = after
                    for chunk in _frames(await asyncio.to_thread(self.speak, after)):
                        await tel.send(json.dumps(self.d.agent_media(sid, chunk)))
                    verdict = "replaced"
                else:
                    said, verdict = "", "blocked"
            else:
                for m in msgs:
                    await tel.send(m)
                verdict, said = ("flagged" if new else "ok"), ""
            if text or new:
                self._emit(ShieldEvent(call, self._t(t0), "agent", text, verdict, rules, said, held_ms))

        while True:
            try:
                raw = await asyncio.wait_for(agent.recv(), self.gap_s)
            except asyncio.TimeoutError:
                await finish(cut.flush())                         # the agent paused: its utterance is over
                continue
            except websockets.ConnectionClosed:
                await finish(cut.flush())
                return
            kind, value = self.d.parse(json.loads(raw))
            if kind == "media":
                if self.mode == "block":
                    held.append(raw)
                    start = start or time.perf_counter()
                else:
                    await tel.send(raw)
                if (pcm := cut.push(value)) is not None:
                    await finish(pcm)
            elif kind == "clear":                                 # the agent yielded to a barge-in: drop what it held
                held, start = [], None
                cut.flush()
                await tel.send(raw)
            else:
                await tel.send(raw)

    # ------------------------------------------------------------------ plumbing
    async def _transcribe(self, pcm: bytes) -> str:
        x = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768.0
        try:
            return str(await asyncio.to_thread(self.hear, x, SR) or "").strip()
        except Exception as e:                                    # a failed transcription never breaks the call
            return f"[not transcribed: {type(e).__name__}]"

    @staticmethod
    def _t(t0: float) -> float:
        return round(time.perf_counter() - t0, 2)

    def _emit(self, e: ShieldEvent) -> None:
        self.calls.setdefault(e.call, []).append(e)
        d = asdict(e) | {"type": "shield", "mode": self.mode}
        if self.on_event:
            self.on_event(d)
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with (self.log_dir / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _save(self, call: str) -> None:
        if not self.log_dir:
            return
        ev = [asdict(e) for e in self.calls.get(call, [])]
        flagged = [e for e in ev if e["verdict"] in ("flagged", "blocked", "replaced")]
        (self.log_dir / "calls").mkdir(parents=True, exist_ok=True)
        (self.log_dir / "calls" / f"{call}.json").write_text(json.dumps(
            {"call": call, "mode": self.mode, "utterances": len([e for e in ev if e["side"] == "agent"]),
             "flagged": len(flagged), "events": ev}, ensure_ascii=False, indent=1), encoding="utf-8")

    async def serve(self, host: str = "127.0.0.1", port: int = 8791, ready: asyncio.Event | None = None) -> None:
        async with websockets.serve(self.handle, host, port, max_size=2**24):
            if ready:
                ready.set()
            await asyncio.Future()


def _frames(pcm: bytes) -> list[bytes]:
    n = FRAME * 2
    return [pcm[i:i + n] for i in range(0, len(pcm), n)]


def summarize(log_dir: Path, limit: int = 200) -> dict:
    """What the dashboard shows: the latest events and per-call counts, from Shield's own log."""
    f = log_dir / "events.jsonl"
    events = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []
    agent = [e for e in events if e["side"] == "agent"]
    by_rule: dict[str, int] = {}
    for e in agent:
        for r in e.get("rules") or []:
            by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1
    held = [e["held_ms"] for e in agent if e.get("held_ms") is not None]
    return {"events": events[-limit:], "calls": len({e["call"] for e in events}), "utterances": len(agent),
            "flagged": sum(e["verdict"] in ("flagged", "blocked", "replaced") for e in agent),
            "blocked": sum(e["verdict"] in ("blocked", "replaced") for e in agent), "by_rule": by_rule,
            "held_ms_p50": sorted(held)[len(held) // 2] if held else None}
