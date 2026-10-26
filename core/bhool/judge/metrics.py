"""Deterministic call metrics measured from audio, independent of any model's judgement.

Input is the call as two time-aligned mono tracks: what the caller emitted and what the
agent emitted. The test harness records each side separately, so no diarization guesswork
is involved. Each track is segmented with an adaptive energy VAD.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

FRAME_S = 0.02


@dataclass(frozen=True)
class Segment:
    start: float
    end: float

    @property
    def dur(self) -> float:
        return self.end - self.start


def speech_segments(
    x: np.ndarray,
    sr: int,
    min_speech_s: float = 0.12,
    hangover_s: float = 0.3,
    margin_db: float = 12.0,
    dynamic_range_db: float = 45.0,
    use_noise_floor: bool = True,
) -> list[Segment]:
    """Energy VAD: frames above max(noise floor + margin, peak - range) are speech.

    Gaps shorter than hangover_s are bridged; blips shorter than min_speech_s are dropped.
    Set use_noise_floor=False for clean speech, which may have no pauses to estimate a floor from.
    """
    n = int(sr * FRAME_S)
    if x.size < n:
        return []
    frames = x[: x.size // n * n].reshape(-1, n).astype(np.float64)
    db = 10 * np.log10(np.mean(frames**2, axis=1) + 1e-12)
    if db.max() < -70:          # digital silence
        return []
    peak = db.max()
    thresh = peak - dynamic_range_db
    if use_noise_floor:
        floor = np.percentile(db, 10)
        span = peak - floor
        if span < 6.0:
            # No real floor: the track is (nearly) all speech. Accept anything near the peak.
            thresh = max(thresh, peak - 15.0)
        else:
            # Margin above the floor, but never more than halfway to the peak, so speech on a
            # low-SNR line (e.g. 8 dB) still clears it.
            thresh = max(thresh, floor + min(margin_db, span / 2))
    active = db > thresh

    segs: list[list[float]] = []
    for i in np.flatnonzero(active):
        t = i * FRAME_S
        if segs and t - segs[-1][1] <= hangover_s:
            segs[-1][1] = t + FRAME_S
        else:
            segs.append([t, t + FRAME_S])
    return [Segment(round(float(s), 3), round(float(e), 3)) for s, e in segs if e - s >= min_speech_s]


def _speaking_at(segs: list[Segment], t: float) -> Segment | None:
    for s in segs:
        if s.start <= t < s.end:
            return s
    return None


def group_turns(own: list[Segment], other: list[Segment], turn_gap_s: float = 0.7) -> list[Segment]:
    """Merge one side's segments into turns: pauses < turn_gap_s with no reply in between."""
    turns: list[Segment] = []
    for s in own:
        if turns:
            prev = turns[-1]
            replied = any(prev.end <= o.start < s.start for o in other)
            if s.start - prev.end < turn_gap_s and not replied:
                turns[-1] = Segment(prev.start, s.end)
                continue
        turns.append(s)
    return turns


@dataclass
class CallMetrics:
    duration_s: float
    caller_turns: int
    agent_turns: int
    time_to_first_audio_s: float | None
    response_latencies_s: list[float] = field(default_factory=list)
    latency_p50_s: float | None = None
    latency_p95_s: float | None = None
    unanswered_turns: int = 0
    dead_air_events: int = 0
    longest_dead_air_s: float = 0.0
    overlap_s: float = 0.0
    barge_ins: int = 0
    barge_ins_ignored: int = 0          # agent kept talking > yield_s after caller barged in
    agent_yield_times_s: list[float] = field(default_factory=list)
    agent_cut_off_caller: int = 0       # agent started talking while the caller was mid-turn

    def to_dict(self) -> dict:
        return asdict(self)


def measure_call(
    caller: np.ndarray,
    agent: np.ndarray,
    sr: int,
    turn_gap_s: float = 0.7,
    dead_air_s: float = 3.0,
    yield_s: float = 1.5,
    answer_window_s: float = 8.0,
    caller_segments: list[Segment] | None = None,
) -> CallMetrics:
    """caller_segments: ground-truth caller speech intervals when known (the harness rendered
    them), which beats VAD on a deliberately noisy caller track."""
    if caller.size != agent.size:
        n = max(caller.size, agent.size)
        caller, agent = np.pad(caller, (0, n - caller.size)), np.pad(agent, (0, n - agent.size))
    duration = caller.size / sr
    c_segs = sorted(caller_segments, key=lambda s: s.start) if caller_segments is not None else speech_segments(caller, sr)
    a_segs = speech_segments(agent, sr)
    c_turns = group_turns(c_segs, a_segs, turn_gap_s)
    a_turns = group_turns(a_segs, c_segs, turn_gap_s)

    # Response latency: caller turn ends while the agent is silent -> next agent onset.
    latencies, unanswered = [], 0
    for i, ct in enumerate(c_turns):
        if _speaking_at(a_segs, ct.end):
            continue
        nxt_caller = c_turns[i + 1].start if i + 1 < len(c_turns) else duration
        onset = next((a.start for a in a_segs if ct.end <= a.start), None)
        if onset is not None and onset - ct.end <= answer_window_s and onset <= nxt_caller:
            latencies.append(round(onset - ct.end, 3))
        elif ct.end + answer_window_s <= duration or nxt_caller < duration:
            unanswered += 1

    # Dead air: nobody speaking, between the first and last speech of the call.
    all_segs = sorted(c_segs + a_segs, key=lambda s: s.start)
    gaps, cursor = [], None
    for s in all_segs:
        if cursor is not None and s.start > cursor:
            gaps.append(s.start - cursor)
        cursor = s.end if cursor is None else max(cursor, s.end)
    long_gaps = [g for g in gaps if g >= dead_air_s]

    # Overlap and barge-in handling.
    overlap = sum(max(0.0, min(c.end, a.end) - max(c.start, a.start)) for c in c_segs for a in a_segs)
    barge_ins, ignored, yields = 0, 0, []
    for c in c_segs:
        a = _speaking_at(a_segs, c.start)
        if a and c.start - a.start > 0.3:   # caller cut in on an agent turn already under way
            barge_ins += 1
            y = a.end - c.start
            yields.append(round(y, 3))
            if y > yield_s:
                ignored += 1
    cut_off = 0
    for a in a_segs:
        c = _speaking_at(c_segs, a.start)
        if c and a.start - c.start > 0.3 and c.end - a.start > 0.5:
            cut_off += 1

    def pct(v: list[float], q: float) -> float | None:
        return round(float(np.percentile(v, q)), 3) if v else None

    return CallMetrics(
        duration_s=round(duration, 3),
        caller_turns=len(c_turns),
        agent_turns=len(a_turns),
        time_to_first_audio_s=a_segs[0].start if a_segs else None,
        response_latencies_s=latencies,
        latency_p50_s=pct(latencies, 50),
        latency_p95_s=pct(latencies, 95),
        unanswered_turns=unanswered,
        dead_air_events=len(long_gaps),
        longest_dead_air_s=round(max(gaps, default=0.0), 3),
        overlap_s=round(overlap, 3),
        barge_ins=barge_ins,
        barge_ins_ignored=ignored,
        agent_yield_times_s=yields,
        agent_cut_off_caller=cut_off,
    )
