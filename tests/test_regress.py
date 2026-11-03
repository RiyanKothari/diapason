from pathlib import Path

import numpy as np

from diapason.audio import write_wav_channels
from diapason.fakes import tone
from diapason.judge.rubric import judge_call
from diapason.regress import append_regressions, distill, estimate_channel, ingest_call
from diapason.scenarios import Persona, load_suite

SUITE = Path(__file__).parent.parent / "suites" / "emi_collection.yaml"
SR = 8000


def stereo_call(path, snr_db=10.0, seed=0):
    """Customer on the left, agent on the right, alternating turns, babble-ish noise on the customer line."""
    rng = np.random.default_rng(seed)
    n = SR * 12
    caller, agent = np.zeros(n, np.float32), np.zeros(n, np.float32)
    for s, e in [(0.5, 2.5), (4.0, 7.5), (9.0, 11.5)]:
        agent[int(s * SR) : int(s * SR) + int((e - s) * SR)] = tone(e - s, SR, 180)
    for s, e in [(3.0, 3.8), (8.0, 8.7)]:
        caller[int(s * SR) : int(s * SR) + int((e - s) * SR)] = tone(e - s, SR, 230)
    p = np.mean(caller[caller != 0] ** 2)
    caller += (np.sqrt(p / 10 ** (snr_db / 10)) * rng.standard_normal(n)).astype(np.float32)
    write_wav_channels(path, np.stack([caller, agent]), SR)


def hear(audio, sr, lang):
    return "आज ही पैसे भरो नहीं तो police आएगी" if audio.size > 1.5 * sr else "मेरे पास अभी पैसे नहीं हैं"


class FakeEvon:
    def chat_json(self, msgs, **kw):
        if "reproducible test case" in msgs[0]["content"]:
            return {"persona": {"description": "worried daily-wage worker", "gender": "male", "stt_lang": "hi-IN",
                                "tts_lang": "hi-en", "emotion": ["sigh", "crying"], "goal": "explain he can't pay yet"},
                    "behaviour": {"instructions": "plead for more time", "key_lines": ["मेरे पास अभी पैसे नहीं हैं"],
                                  "interrupts": True},
                    "failure": "agent threatened police"}
        return {"criteria": {"compliance": {"verdict": "fail", "reason": "threat",
                                            "evidence": [{"turn": 0, "quote": "police आएगी"}]}}, "summary": "s"}


def test_ingest_transcribes_both_channels_and_measures(tmp_path):
    stereo_call(tmp_path / "call1.wav")
    rec, caller, sr = ingest_call(tmp_path / "call1.wav", hear)
    speakers = [t.speaker for t in rec.turns]
    assert speakers == ["agent", "caller", "agent", "caller", "agent"]
    assert rec.metrics.response_latencies_s and abs(rec.metrics.response_latencies_s[0] - 0.2) < 0.15


def test_estimate_channel_recovers_snr_and_band(tmp_path):
    stereo_call(tmp_path / "c.wav", snr_db=10)
    _, caller, sr = ingest_call(tmp_path / "c.wav", hear)
    ch = estimate_channel(caller, sr, "c")
    assert ch.narrowband and ch.noise == "crowd"
    assert abs(ch.snr_db - 10) < 3.5, ch.snr_db


def test_failed_call_becomes_replayable_regression_case(tmp_path):
    suite = load_suite(SUITE)
    stereo_call(tmp_path / "call7.wav")
    rec, caller, sr = ingest_call(tmp_path / "call7.wav", hear)
    v = judge_call(rec, suite.agent, Persona(id="production", description="x"), suite.gate, FakeEvon(), samples=1)
    assert not v.passed      # banned phrase "police" alone fails it
    persona, behaviour, failure = distill(rec, v, suite, FakeEvon())
    assert persona.voice in {"Avinash", "Shubham", "Prakash", "Devansh", "Yashraj", "Harshad"}
    assert persona.emotion == ["sigh"]                       # unknown tag "crying" dropped
    assert "मेरे पास अभी पैसे नहीं हैं" in behaviour.instructions and behaviour.interrupt_prob > 0
    out = tmp_path / "regressions.yaml"
    item = (persona, behaviour, estimate_channel(caller, sr, rec.scenario_id), failure, "call7.wav")
    append_regressions(suite, out, [item])
    append_regressions(suite, out, [item])                    # idempotent
    reg = load_suite(out)
    scenarios = reg.expand()
    assert [s.id for s in scenarios] == ["prod_call7"]
    assert reg.cases[0].failure == "agent threatened police"
    assert scenarios[0].channel.id == "prod_call7"
