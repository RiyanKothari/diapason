"""Procedural noise beds for Indian phone-call conditions.

These need no dataset, so every test is reproducible from a seed. A real recording
(e.g. from MUSAN) can be used instead through ChannelProfile.noise_file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

from ..audio import read_wav, resample


def _norm(x: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(x)) or 1.0
    return (x / peak).astype(np.float32)


def _colored(n: int, rng: np.random.Generator, exponent: float) -> np.ndarray:
    """Noise with power spectrum ~ 1/f**exponent (0 white, 1 pink, 2 brown)."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n)
    f[0] = f[1] if n > 1 else 1.0
    spec /= f ** (exponent / 2)
    return _norm(np.fft.irfft(spec, n))


def _band(x: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    sos = butter(4, [lo, min(hi, sr / 2 - 1)], btype="band", fs=sr, output="sos")
    return sosfilt(sos, x)


def _syllabic_envelope(n: int, sr: int, rng: np.random.Generator, rate_hz: float = 4.0) -> np.ndarray:
    """Slow random on/off envelope at roughly speech-syllable rate."""
    knots = max(2, int(n / sr * rate_hz) + 2)
    env = np.clip(rng.standard_normal(knots) + 0.3, 0, None)
    return np.interp(np.arange(n), np.linspace(0, n, knots), env)


def fan(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    return _norm(_band(_colored(n, rng, 1.0), sr, 60, 2000))


def office(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    x = 0.5 * _colored(n, rng, 1.0)
    # keyboard clicks: short decaying impulses at random times
    click = np.exp(-np.arange(int(0.008 * sr)) / (0.0015 * sr)) * rng.standard_normal(int(0.008 * sr))
    for t in rng.integers(0, max(1, n - click.size), size=int(n / sr * 6)):
        x[t : t + click.size] += 0.8 * click
    return _norm(x)


def traffic(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    x = _colored(n, rng, 2.0) * (0.6 + 0.4 * _syllabic_envelope(n, sr, rng, rate_hz=0.3))
    # horns: two-tone bursts, a staple of Indian street audio
    t = np.arange(n) / sr
    for start in rng.uniform(0, max(n / sr - 1, 0.1), size=max(1, int(n / sr / 4))):
        dur = rng.uniform(0.25, 0.8)
        mask = (t >= start) & (t < start + dur)
        f0 = rng.uniform(380, 520)
        x[mask] += 0.7 * (np.sin(2 * np.pi * f0 * t[mask]) + 0.6 * np.sin(2 * np.pi * 1.26 * f0 * t[mask]))
    return _norm(x)


def crowd(n: int, sr: int, rng: np.random.Generator, talkers: int = 8) -> np.ndarray:
    """Babble: several band-limited voices-like sources, each syllabically modulated."""
    x = np.zeros(n)
    for _ in range(talkers):
        lo = rng.uniform(250, 500)
        src = _band(rng.standard_normal(n), sr, lo, lo * rng.uniform(4, 7))
        x += src * _syllabic_envelope(n, sr, rng, rate_hz=rng.uniform(3, 6))
    return _norm(x)


GENERATORS = {"fan": fan, "office": office, "traffic": traffic, "crowd": crowd}


def make_noise(kind: str, n: int, sr: int, rng: np.random.Generator, noise_file: str | None = None) -> np.ndarray:
    if noise_file:
        bed, bed_sr = read_wav(Path(noise_file))
        bed = resample(bed, bed_sr, sr)
        if bed.size == 0:
            raise ValueError(f"noise file is empty: {noise_file}")
        start = int(rng.integers(0, bed.size))
        return _norm(np.resize(np.roll(bed, -start), n))
    if kind not in GENERATORS:
        raise ValueError(f"unknown noise kind {kind!r}; choose from {sorted(GENERATORS)} or set noise_file")
    return GENERATORS[kind](n, sr, rng)
