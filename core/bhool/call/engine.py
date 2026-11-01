"""One test call: a synthetic caller against the agent under test, in real time.

A single 20 ms clock drives both directions, so the recorded tracks are sample-aligned:
each tick sends one caller frame and plays out one frame of the agent's buffered audio
(agents may send faster than real time; a phone line plays it at real time). The caller
hears only what has been played out, so it replies when the agent has actually finished.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..audio import float_to_pcm16, pcm16_to_float, write_wav
from ..caller.brain import Brain, Turn, Utterance
from ..caller.ears import Ears
from ..caller.mouth import ChannelStream
from ..judge.metrics import CallMetrics, Segment, measure_call
from ..scenarios.schema import Persona, Scenario
from .transport import AgentConnection

Speak = Callable[[Utterance, Persona], tuple[np.ndarray, int]]
Hear = Callable[[np.ndarray, int, str], str]

GOODBYE = {"gu-IN": "ઠીક છે, આવજો.", "en-IN": "Okay, bye.", "hi-IN": "ठीक है, नमस्ते।"}


@dataclass
class CallRecord:
    scenario_id: str
    run: int
    end_reason: str
    duration_s: float
    turns: list[Turn]
    caller_segments: list[Segment]
    metrics: CallMetrics
    dispositions: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    caller_wav: str | None = None
    agent_wav: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = self.metrics.to_dict()
        return d

    def transcript(self) -> str:
        return "\n".join(
            f"[T{i} {t.speaker.upper()} {t.start:.1f}s-{t.end:.1f}s{' interjection' if t.kind == 'interjection' else ''}] {t.text}"
            for i, t in enumerate(self.turns)
        )


async def run_call(
    scenario: Scenario,
    conn: AgentConnection,
    brain: Brain,
    speak: Speak,
    hear: Hear,
    out_dir: Path | None = None,
    run: int = 0,
    max_duration_s: float = 150.0,
    first_wait_s: float = 4.0,
    agent_silent_timeout_s: float = 15.0,
    frame_ms: int = 20,
    on_event: Callable[[dict], None] | None = None,
    answer_window_s: float = 8.0,
) -> CallRecord:
    loop = asyncio.get_running_loop()
    persona, behaviour = scenario.persona, scenario.behaviour
    sr = conn.sample_rate
    n = int(sr * frame_ms / 1000)
    dt = n / sr
    stream = ChannelStream(scenario.channel, sr, scenario.seed + run, max_s=max_duration_s + 10)
    ears = Ears(sr)
    rng = random.Random(scenario.seed + run)
    q: asyncio.Queue = asyncio.Queue()
    playout: list[np.ndarray] = []
    caller_frames: list[np.ndarray] = []
    agent_frames: list[np.ndarray] = []
    history: list[Turn] = []
    truth: list[Segment] = []
    events: list[dict] = []
    dispositions: list[dict] = []
    st = {"stop": False, "ending": False, "silenced": False, "pending_reply": False, "agent_start": 0.0, "timed_out": False}

    def emit(e: dict) -> None:
        events.append(e)
        if on_event:
            on_event({"scenario": scenario.id, "run": run, **e})

    def now() -> float:
        return round(stream.time_s, 3)

    def pop_playout() -> np.ndarray:
        out, need = [], n
        while need and playout:
            chunk = playout[0]
            take = chunk[:need]
            out.append(take)
            need -= take.size
            if take.size == chunk.size:
                playout.pop(0)
            else:
                playout[0] = chunk[take.size :]
        frame = np.concatenate(out) if out else np.zeros(0, np.float32)
        return np.pad(frame, (0, n - frame.size)) if frame.size < n else frame

    async def receiver():
        async for ev in conn.events():
            if ev.kind == "audio":
                playout.append(pcm16_to_float(ev.audio))
            elif ev.kind == "clear":
                playout.clear()
                emit({"type": "agent_clear", "t": now()})
            elif ev.kind == "disposition":
                dispositions.append(ev.data)
                emit({"type": "disposition", "t": now(), "data": ev.data})
            elif ev.kind == "hangup":
                await q.put(("hangup", now()))
                return
            elif (ev.data or {}).get("type") == "guard":        # the agent's guard rewrote a line before speaking it
                emit({**ev.data, "t": now()})

    async def clock():
        t0, k, was_speaking = loop.time(), 0, False
        while not st["stop"]:
            delay = t0 + k * dt - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            t = k * dt
            frame = stream.next_frame(n)
            await conn.send_audio(float_to_pcm16(frame))
            caller_frames.append(frame)
            a = pop_playout()
            agent_frames.append(a)
            for e in ears.feed(a, t):
                await q.put(e)
            if was_speaking and not stream.speaking:
                await q.put(("caller_done", round(t + dt, 3)))
            was_speaking = stream.speaking
            k += 1
            if t >= max_duration_s and not st["timed_out"]:
                st["timed_out"] = True
                await q.put(("timeout", t))

    def guard(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            q.put_nowait(("error", repr(task.exception())))

    async def say(utt: Utterance, kind: str = "speech") -> None:
        audio, asr = await asyncio.to_thread(speak, utt, persona)
        segs = stream.say(audio, asr)
        start = segs[0].start if segs else now()
        end = segs[-1].end if segs else start
        truth.extend(segs)
        turn = Turn("caller", utt.text, start, end, kind)
        history.append(turn)
        emit({"type": "turn", "speaker": "caller", "kind": kind, "text": utt.text, "tags": utt.tags, "start": start, "end": end})
        if utt.end_call:
            st["ending"] = True

    async def respond() -> None:
        if behaviour.silence_s and not st["silenced"] and sum(t.speaker == "agent" for t in history) >= 2:
            st["silenced"] = True
            emit({"type": "silence", "t": now(), "seconds": behaviour.silence_s})
            await asyncio.sleep(behaviour.silence_s)
            if ears.talking or not q.empty():
                return   # the agent spoke into the silence; its turn drives the next reply
        if sum(t.speaker == "caller" and t.kind == "speech" for t in history) >= behaviour.max_turns:
            utt = Utterance(GOODBYE.get(persona.stt_lang, GOODBYE["hi-IN"]), end_call=True)
        else:
            utt = await asyncio.to_thread(brain.reply, history)
        await say(utt)

    async def barge_in() -> None:
        await asyncio.sleep(rng.uniform(1.0, 2.2))
        if ears.talking and not stream.speaking and not st["ending"]:
            emit({"type": "barge_in_attempt", "t": now()})
            await say(brain.interjection(), kind="interjection")

    await conn.start(scenario.id, dict(persona.crm))
    tasks = [asyncio.create_task(receiver()), asyncio.create_task(clock())]
    for t in tasks:
        t.add_done_callback(guard)
    side: list[asyncio.Task] = []
    end_reason = "unknown"
    try:
        try:
            first = await asyncio.wait_for(q.get(), first_wait_s)
            q.put_nowait(first)
        except TimeoutError:
            emit({"type": "agent_no_greeting", "t": now()})
            await say(brain.opening())
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), agent_silent_timeout_s)
            except TimeoutError:
                if stream.speaking or ears.talking:
                    continue
                end_reason = "agent_silent"
                break
            kind = ev[0]
            if kind == "error":
                end_reason = f"error: {ev[1]}"
                break
            if kind == "hangup":
                end_reason = "agent_hangup"
                # An agent streams faster than real time and may hang up while its last line is still queued to play (seen
                # live: v4's date confirmation was lost and scored "accepted without confirmation"). On a phone line that
                # line still plays out, so let it, then transcribe it.
                deadline = now() + 15.0
                while playout and now() < deadline:
                    await asyncio.sleep(dt)
                while not q.empty():
                    ev = q.get_nowait()
                    if ev[0] == "start":
                        st["agent_start"] = ev[1]
                    elif ev[0] == "end":
                        _, t_end, audio = ev
                        text = await asyncio.to_thread(hear, audio, sr, persona.stt_lang)
                        history.append(Turn("agent", text, st["agent_start"], t_end))
                        emit({"type": "turn", "speaker": "agent", "text": text, "start": st["agent_start"], "end": t_end})
                break
            if kind == "timeout":
                end_reason = "max_duration"
                break
            if kind == "start":
                st["agent_start"] = ev[1]
                emit({"type": "agent_speaking", "t": ev[1]})
                if behaviour.interrupt_prob and not stream.speaking and rng.random() < behaviour.interrupt_prob:
                    side.append(asyncio.create_task(barge_in()))
            elif kind == "end":
                _, t_end, audio = ev
                text = await asyncio.to_thread(hear, audio, sr, persona.stt_lang)
                history.append(Turn("agent", text, st["agent_start"], t_end))
                emit({"type": "turn", "speaker": "agent", "text": text, "start": st["agent_start"], "end": t_end})
                if st["ending"]:
                    continue    # agent's goodbye; we hang up once our own last line has played
                if stream.speaking:
                    st["pending_reply"] = True
                    continue
                await respond()
            elif kind == "caller_done":
                if st["ending"]:
                    await asyncio.sleep(0.8)
                    end_reason = "caller_hangup"
                    break
                if st["pending_reply"] and not ears.talking:
                    st["pending_reply"] = False
                    await respond()
    finally:
        st["stop"] = True
        for t in side + tasks:
            t.cancel()
        await asyncio.gather(*side, *tasks, return_exceptions=True)
        await conn.close()

    for _, t_end, audio in ears.flush(now()):
        text = await asyncio.to_thread(hear, audio, sr, persona.stt_lang)
        history.append(Turn("agent", text, st["agent_start"], t_end))

    caller = np.concatenate(caller_frames) if caller_frames else np.zeros(0, np.float32)
    agent = np.concatenate(agent_frames) if agent_frames else np.zeros(0, np.float32)
    metrics = measure_call(caller, agent, sr, caller_segments=truth, answer_window_s=answer_window_s)
    rec = CallRecord(
        scenario_id=scenario.id, run=run, end_reason=end_reason, duration_s=round(caller.size / sr, 3),
        turns=sorted(history, key=lambda t: t.start), caller_segments=truth, metrics=metrics,
        dispositions=dispositions, events=events,
    )
    if out_dir is not None:
        d = Path(out_dir) / scenario.id / f"run{run}"
        write_wav(d / "caller.wav", caller, sr)
        write_wav(d / "agent.wav", agent, sr)
        write_wav(d / "mix.wav", 0.5 * (caller + agent), sr)
        rec.caller_wav, rec.agent_wav = str(d / "caller.wav"), str(d / "agent.wav")
        (d / "call.json").write_text(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    emit({"type": "call_end", "reason": end_reason, "duration_s": rec.duration_s})
    return rec
