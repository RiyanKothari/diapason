"""Telephony channel simulator.

Signal path, in the order a real Indian mobile call degrades audio:
  mic (speech + background noise at a target SNR)
  -> handset gain and clipping
  -> narrowband filter (300-3400 Hz) and resample to 8 kHz
  -> G.711 mu-law codec
  -> network: bursty packet loss (Gilbert-Elliott) with concealment, and jitter-buffer underruns
Deterministic for a given seed, so a failing test call can be replayed exactly.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy.signal import butter, sosfilt

from ..audio import resample, rms
from .noise import make_noise

PHONE_SR = 8000
FRAME_MS = 20


class ChannelProfile(BaseModel):
    id: str = "clean"
    noise: Literal["none", "fan", "office", "traffic", "crowd"] = "none"
    noise_file: str | None = None
    snr_db: float = Field(30.0, ge=-10, le=60)
    gain_db: float = 0.0
    clip_level: float = Field(1.0, gt=0, le=1.0)
    narrowband: bool = True
    codec: Literal["none", "mulaw"] = "mulaw"
    loss_pct: float = Field(0.0, ge=0, lt=50)
    loss_burst_frames: float = Field(1.5, ge=1.0)
    concealment: Literal["zero", "repeat"] = "repeat"
    underrun_pct: float = Field(0.0, ge=0, lt=20)


PRESETS: dict[str, ChannelProfile] = {
    "clean": ChannelProfile(id="clean", codec="none", narrowband=False),
    "landline": ChannelProfile(id="landline", noise="office", snr_db=30),
    "fan_room": ChannelProfile(id="fan_room", noise="fan", snr_db=15),
    "street": ChannelProfile(id="street", noise="traffic", snr_db=8, gain_db=4, clip_level=0.8, loss_pct=2),
    "market": ChannelProfile(id="market", noise="crowd", snr_db=5, loss_pct=3),
    "bad_network": ChannelProfile(id="bad_network", noise="traffic", snr_db=12, loss_pct=12, loss_burst_frames=3, underrun_pct=4),
}


def active_speech_power(x: np.ndarray, sr: int) -> float:
    """Mean power over frames within 30 dB of the loudest frame, so pauses don't dilute SNR."""
    n = int(sr * FRAME_MS / 1000)
    frames = x[: x.size // n * n].reshape(-1, n) if x.size >= n else x.reshape(1, -1)
    p = np.mean(np.square(frames, dtype=np.float64), axis=1)
    if p.max() <= 0:
        return 0.0
    return float(p[p >= p.max() * 1e-3].mean())


def mulaw(x: np.ndarray, mu: float = 255.0) -> np.ndarray:
    """Companding to 8-bit and back, which reproduces G.711 quantisation noise."""
    y = np.sign(x) * np.log1p(mu * np.abs(np.clip(x, -1, 1))) / np.log1p(mu)
    q = np.round(y * 127) / 127
    return (np.sign(q) * np.expm1(np.abs(q) * np.log1p(mu)) / mu).astype(np.float32)


def gilbert_elliott(n_frames: int, loss_pct: float, burst: float, rng: np.random.Generator) -> np.ndarray:
    """Boolean mask of lost frames with the requested mean loss and mean burst length."""
    loss = loss_pct / 100
    if loss <= 0:
        return np.zeros(n_frames, bool)
    r = 1.0 / burst                    # bad -> good
    p = loss * r / (1 - loss)          # good -> bad, so stationary loss = p / (p + r)
    lost = np.zeros(n_frames, bool)
    bad = rng.random() < loss
    for i in range(n_frames):
        lost[i] = bad
        bad = (rng.random() >= r) if bad else (rng.random() < p)
    return lost


def apply_channel(speech: np.ndarray, sr: int, profile: ChannelProfile, seed: int = 0) -> tuple[np.ndarray, int, dict]:
    """Degrade clean speech as a phone call would. Returns (audio, sample_rate, stats)."""
    rng = np.random.default_rng(seed)
    x = speech.astype(np.float64)
    stats: dict = {"profile": profile.id, "seed": seed}

    if profile.noise != "none" or profile.noise_file:
        noise = make_noise(profile.noise, x.size, sr, rng, profile.noise_file).astype(np.float64)
        p_s, p_n = active_speech_power(x, sr), float(np.mean(noise**2))
        if p_s > 0 and p_n > 0:
            noise *= np.sqrt(p_s / (p_n * 10 ** (profile.snr_db / 10)))
            x = x + noise
            stats["snr_db_measured"] = round(10 * np.log10(p_s / np.mean(noise**2)), 2)

    x = x * 10 ** (profile.gain_db / 20)
    stats["clipped_pct"] = round(100 * float(np.mean(np.abs(x) >= profile.clip_level)), 3)
    x = np.clip(x, -profile.clip_level, profile.clip_level)

    out_sr = sr
    if profile.narrowband:
        sos = butter(6, [300, 3400], btype="band", fs=sr, output="sos")
        x = resample(sosfilt(sos, x), sr, PHONE_SR)
        out_sr = PHONE_SR

    if profile.codec == "mulaw":
        x = mulaw(x)

    n = int(out_sr * FRAME_MS / 1000)
    n_frames = x.size // n
    if n_frames and (profile.loss_pct > 0 or profile.underrun_pct > 0):
        frames = x[: n_frames * n].reshape(n_frames, n).copy()
        lost = gilbert_elliott(n_frames, profile.loss_pct, profile.loss_burst_frames, rng)
        for i in np.flatnonzero(lost):
            if profile.concealment == "repeat" and i > 0:
                frames[i] = frames[i - 1] * 0.5    # simple PLC: attenuated repeat
            else:
                frames[i] = 0.0
        stats["loss_pct_actual"] = round(100 * float(lost.mean()), 2)
        pieces, underruns = [], 0
        for i in range(n_frames):
            if rng.random() < profile.underrun_pct / 100:
                pieces.append(np.zeros(n * int(rng.integers(1, 4))))  # 20-60 ms gap
                underruns += 1
            pieces.append(frames[i])
        pieces.append(x[n_frames * n :])
        x = np.concatenate(pieces)
        stats["underruns"] = underruns

    stats["out_rms"] = round(rms(x), 5)
    return x.astype(np.float32), out_sr, stats
