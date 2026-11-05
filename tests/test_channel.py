import numpy as np
import pytest

from diapason.channel import PRESETS, ChannelProfile, apply_channel
from diapason.channel.sim import active_speech_power, gilbert_elliott, mulaw

SR = 16000


def tone_bursts(seconds=4.0, sr=SR):
    """Speech-like stand-in: 300 ms voiced bursts separated by pauses."""
    t = np.arange(int(seconds * sr)) / sr
    x = 0.3 * (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 880 * t))
    x *= (t % 0.5) < 0.3
    return x.astype(np.float32)


@pytest.mark.parametrize("snr", [0, 5, 10, 20])
def test_snr_hits_target(snr):
    x = tone_bursts()
    _, _, stats = apply_channel(x, SR, ChannelProfile(noise="crowd", snr_db=snr, narrowband=False, codec="none"), seed=1)
    assert abs(stats["snr_db_measured"] - snr) < 0.5


def test_narrowband_outputs_8k_and_removes_out_of_band():
    t = np.arange(SR * 2) / SR
    x = (0.5 * np.sin(2 * np.pi * 6000 * t)).astype(np.float32)   # above 3400 Hz
    y, sr, _ = apply_channel(x, SR, ChannelProfile(codec="none"), seed=0)
    assert sr == 8000
    assert np.sqrt(np.mean(y**2)) < 0.01


def test_deterministic_for_seed():
    x = tone_bursts()
    a, _, _ = apply_channel(x, SR, PRESETS["bad_network"], seed=42)
    b, _, _ = apply_channel(x, SR, PRESETS["bad_network"], seed=42)
    c, _, _ = apply_channel(x, SR, PRESETS["bad_network"], seed=43)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_gilbert_elliott_mean_loss_and_burstiness():
    rng = np.random.default_rng(0)
    lost = gilbert_elliott(200_000, loss_pct=10, burst=3, rng=rng)
    assert abs(lost.mean() - 0.10) < 0.01
    runs = np.diff(np.flatnonzero(np.diff(np.r_[0, lost.astype(int), 0])))[::2]
    assert abs(runs.mean() - 3) < 0.3


def test_mulaw_error_is_small_relative_to_signal():
    x = np.linspace(-0.9, 0.9, 10_000).astype(np.float32)
    err = np.abs(mulaw(x) - x)
    assert err.max() < 0.03
    assert np.all(err[np.abs(x) < 0.01] < 0.001)   # fine resolution near zero, as in G.711


def test_clipping_reported():
    x = tone_bursts()
    _, _, stats = apply_channel(x, SR, ChannelProfile(gain_db=12, clip_level=0.5, codec="none", narrowband=False), seed=0)
    assert stats["clipped_pct"] > 1


def test_active_speech_power_ignores_pauses():
    x = tone_bursts()
    padded = np.concatenate([x, np.zeros_like(x)])
    assert abs(active_speech_power(x, SR) - active_speech_power(padded, SR)) / active_speech_power(x, SR) < 0.05


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_runs(name):
    y, sr, stats = apply_channel(tone_bursts(1.0), SR, PRESETS[name], seed=3)
    assert y.size > 0 and np.all(np.isfinite(y))
