import numpy as np

from bhool.judge import measure_call, speech_segments

SR = 8000


def track(spans, total_s=20.0, noise=0.002, seed=0):
    """A track with voiced spans [(start, end), ...] over light background noise."""
    rng = np.random.default_rng(seed)
    x = noise * rng.standard_normal(int(total_s * SR))
    t = np.arange(x.size) / SR
    for s, e in spans:
        m = (t >= s) & (t < e)
        x[m] += 0.3 * np.sin(2 * np.pi * 180 * t[m])
    return x.astype(np.float32)


def test_segments_found_with_short_pauses_bridged():
    x = track([(1.0, 2.0), (2.2, 3.0), (6.0, 7.0)])
    segs = speech_segments(x, SR)
    assert len(segs) == 2
    assert abs(segs[0].start - 1.0) < 0.05 and abs(segs[0].end - 3.0) < 0.05


def test_latency_measured():
    caller = track([(0.0, 2.0), (6.0, 8.0)], seed=1)
    agent = track([(3.2, 5.0), (9.5, 12.0)], seed=2)
    m = measure_call(caller, agent, SR)
    assert m.response_latencies_s == [pytest_approx(1.2), pytest_approx(1.5)]
    assert m.unanswered_turns == 0


def pytest_approx(v, tol=0.05):
    class _A:
        def __eq__(self, o):
            return abs(o - v) <= tol
        def __repr__(self):
            return f"~{v}"
    return _A()


def test_unanswered_turn():
    caller = track([(0.0, 2.0), (12.0, 13.0)], seed=1)
    agent = track([(14.0, 15.0)], seed=2)
    m = measure_call(caller, agent, SR)
    assert m.unanswered_turns == 1


def test_dead_air():
    caller = track([(0.0, 2.0)], seed=1)
    agent = track([(7.0, 8.0)], seed=2)
    m = measure_call(caller, agent, SR)
    assert m.dead_air_events == 1
    assert abs(m.longest_dead_air_s - 5.0) < 0.1


def test_barge_in_ignored_vs_yielded():
    # Agent talks 2-10s; caller barges in at 4s; agent keeps talking 6 more seconds -> ignored.
    m = measure_call(track([(0, 1.5), (4.0, 5.0)], seed=1), track([(2.0, 10.0)], seed=2), SR)
    assert m.barge_ins == 1 and m.barge_ins_ignored == 1
    # Agent stops 0.5 s after the barge-in -> yielded.
    m = measure_call(track([(0, 1.5), (4.0, 5.0)], seed=1), track([(2.0, 4.5)], seed=2), SR)
    assert m.barge_ins == 1 and m.barge_ins_ignored == 0


def test_agent_cuts_off_caller():
    m = measure_call(track([(0.0, 5.0)], seed=1), track([(2.0, 4.0)], seed=2), SR)
    assert m.agent_cut_off_caller == 1


def test_low_snr_speech_still_segmented():
    """Speech only ~8 dB above the noise (a street call) must still be found."""
    rng = np.random.default_rng(3)
    x = track([(2.0, 4.0), (7.0, 9.0)], noise=0.0)
    p = np.mean(x[x != 0] ** 2)
    x = x + (np.sqrt(p / 10 ** 0.8) * rng.standard_normal(x.size)).astype(np.float32)
    segs = speech_segments(x, SR)
    assert len(segs) == 2
    assert abs(segs[0].start - 2.0) < 0.1 and abs(segs[1].end - 9.0) < 0.1


def test_silence_is_empty():
    assert speech_segments(np.zeros(SR * 3, np.float32), SR) == []
