"""Production calls -> verdicts -> replayable regression cases.

A failed real call is turned into a scenario that reproduces its trigger: a persona like
the real caller, a behaviour that says the caller's key lines verbatim, and a channel
measured from the recording's own noise. Every future agent version must pass it.

Input: dual-channel WAV (one channel per party), the norm for contact-centre recording.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

from .audio import read_wav_channels
from .call.engine import CallRecord, Hear
from .caller.brain import Turn
from .channel import ChannelProfile
from .judge.metrics import Segment, group_turns, measure_segments, speech_segments
from .judge.rubric import CallVerdict
from .scenarios.library import sanitize_persona
from .scenarios.schema import Behaviour, Case, Persona, Suite


def ingest_call(path: str | Path, hear: Hear, lang: str = "hi-IN", caller_channel: int = 0) -> tuple[CallRecord, np.ndarray, int]:
    """Transcribe and measure a dual-channel recording. Returns (record, caller audio, sr)."""
    path = Path(path)
    chans, sr = read_wav_channels(path)
    if chans.shape[0] != 2:
        raise ValueError(f"{path.name}: need a 2-channel recording (caller and agent on separate channels), got {chans.shape[0]}")
    caller, agent = chans[caller_channel], chans[1 - caller_channel]
    c_segs, a_segs = speech_segments(caller, sr), speech_segments(agent, sr)
    turns = []
    for speaker, own, other, audio in (("caller", c_segs, a_segs, caller), ("agent", a_segs, c_segs, agent)):
        for seg in group_turns(own, other):
            text = hear(audio[int(seg.start * sr) : int(seg.end * sr)], sr, lang)
            turns.append(Turn(speaker, text, seg.start, seg.end))
    # A stretch the VAD called speech but STT heard nothing in is a noise burst (a click, a door, a fan surge),
    # not a turn: drop it, and measure timing from the turns that were actually spoken.
    turns = [t for t in turns if t.text.strip()]
    duration = caller.size / sr
    metrics = measure_segments([Segment(t.start, t.end) for t in turns if t.speaker == "caller"],
                               [Segment(t.start, t.end) for t in turns if t.speaker == "agent"], duration)
    rec = CallRecord(scenario_id=path.stem, run=0, end_reason="production", duration_s=round(duration, 3),
                     turns=sorted(turns, key=lambda t: t.start), caller_segments=c_segs, metrics=metrics)
    return rec, caller, sr


def estimate_channel(caller: np.ndarray, sr: int, call_id: str) -> ChannelProfile:
    """Approximate the caller's line from the recording: SNR from speech vs non-speech frames,
    narrowband if there's (almost) no energy above 3.8 kHz. The noise type is approximated as
    in-band babble, the hardest common case."""
    segs = speech_segments(caller, sr)
    mask = np.zeros(caller.size, bool)
    for s in segs:
        mask[int(s.start * sr) : int(s.end * sr)] = True
    p_speech = float(np.mean(caller[mask] ** 2)) if mask.any() else 0.0
    p_noise = float(np.mean(caller[~mask] ** 2)) if (~mask).any() else 0.0
    snr = 40.0 if p_noise <= 1e-10 or p_speech <= 0 else 10 * np.log10(max(p_speech - p_noise, 1e-12) / p_noise)
    snr = float(np.clip(round(snr, 1), -5, 40))
    narrow = True
    if sr > 8000 and caller.size:
        spec = np.abs(np.fft.rfft(caller)) ** 2
        f = np.fft.rfftfreq(caller.size, 1 / sr)
        narrow = spec[f > 3800].sum() < 0.01 * spec.sum()
    noisy = snr < 25
    return ChannelProfile(id=f"prod_{call_id}", noise="crowd" if noisy else "none", snr_db=snr if noisy else 30.0,
                          narrowband=narrow, codec="mulaw" if narrow else "none")


DISTILL_SYSTEM = """You turn a failed real customer call into a reproducible test case for a voice agent.
Describe the CALLER (not the agent) so that a role-play actor can recreate the same pressure that made the
agent fail. Copy the caller's key trigger lines word for word from the transcript.
Reply with ONLY JSON:
{"persona": {"description": "...", "gender": "female|male", "stt_lang": "hi-IN|gu-IN|en-IN|...",
  "tts_lang": "hi-en|hi-IN|gu-IN|en-IN|...", "emotion": ["<audio tag>", ...], "goal": "...",
  "hidden_facts": {"<slot>": "<value>"}},
 "behaviour": {"instructions": "...", "key_lines": ["<verbatim caller line>", ...], "interrupts": true|false},
 "failure": "<one sentence: what the agent did wrong; the case passes when it no longer happens>"}"""


def distill(rec: CallRecord, verdict: CallVerdict, suite: Suite, evon) -> tuple[Persona, Behaviour, str]:
    failures = [f"{c.id}: {c.reason} " + " | ".join(f'T{e["turn"]} "{e["quote"]}"' for e in c.evidence)
                for c in verdict.criteria if c.verdict in ("fail", "review")] + verdict.metric_failures
    user = (f"AGENT SOP:\n{suite.agent.sop}\n\nWHAT FAILED:\n- " + "\n- ".join(failures)
            + f"\n\nTRANSCRIPT:\n{rec.transcript()}")
    data = evon.chat_json([{"role": "system", "content": DISTILL_SYSTEM}, {"role": "user", "content": user}],
                          temperature=0.2, max_tokens=1200)
    p, b = data.get("persona") or {}, data.get("behaviour") or {}
    pid = f"prod_{rec.scenario_id}"
    persona = sanitize_persona({"description": "caller from a failed production call", **p}, pid)
    lines = [str(x) for x in b.get("key_lines") or [] if str(x).strip()][:4]
    instructions = str(b.get("instructions") or "Behave as the real caller did.")
    if lines:
        instructions += " At the moments they fit, say these lines word for word: " + " / ".join(f'"{x}"' for x in lines)
    behaviour = Behaviour(id=pid, instructions=instructions, interrupt_prob=0.6 if b.get("interrupts") else 0.0)
    return persona, behaviour, str(data.get("failure") or "; ".join(failures))[:300]


def append_regressions(base: Suite, path: str | Path, items: list[tuple[Persona, Behaviour, ChannelProfile, str, str]]) -> Suite:
    """Add distilled cases to a regression suite file (created from the base suite if missing). Idempotent per call id."""
    path = Path(path)
    if path.exists():
        reg = Suite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    else:
        # Built empty, so skip validation here; it is validated in full once populated, below.
        reg = Suite.model_construct(name=f"{base.name}-regressions", target=base.target, agent=base.agent, personas=[],
                                    behaviours=[], use_library=False, channels=[], matrix=None, cases=[], gate=base.gate,
                                    runs_per_scenario=max(2, base.runs_per_scenario))
    for persona, behaviour, channel, failure, source in items:
        reg.personas = [p for p in reg.personas if p.id != persona.id] + [persona]
        reg.behaviours = [b for b in reg.behaviours if b.id != behaviour.id] + [behaviour]
        reg.channels = [c for c in reg.channels if c.id != channel.id] + [channel]
        reg.cases = [c for c in reg.cases if c.id != persona.id] + [
            Case(id=persona.id, persona=persona.id, behaviour=behaviour.id, channel=channel.id, source=source, failure=failure)]
    Suite.model_validate(reg.model_dump())     # fail loudly before writing anything broken
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(reg.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return reg
