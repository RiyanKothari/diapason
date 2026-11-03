"""Audio I/O and conversion helpers. Float32 mono in [-1, 1] is the internal format."""

from __future__ import annotations

import io
import wave
from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly


def pcm16_to_float(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x.astype(np.float32, copy=False)
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def read_wav(src: str | Path | bytes) -> tuple[np.ndarray, int]:
    """Read a 16-bit PCM WAV (path or bytes) and return mono float32 audio and its sample rate."""
    f = io.BytesIO(src) if isinstance(src, bytes) else open(src, "rb")
    with f, wave.open(f, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"only 16-bit PCM WAV is supported, got {8 * w.getsampwidth()}-bit")
        sr, ch = w.getframerate(), w.getnchannels()
        x = pcm16_to_float(w.readframes(w.getnframes()))
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def read_wav_channels(src: str | Path) -> tuple[np.ndarray, int]:
    """Read a 16-bit PCM WAV keeping channels separate: returns (channels x samples, sample rate)."""
    with wave.open(str(src), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"only 16-bit PCM WAV is supported, got {8 * w.getsampwidth()}-bit")
        sr, ch = w.getframerate(), w.getnchannels()
        x = pcm16_to_float(w.readframes(w.getnframes()))
    return x.reshape(-1, ch).T.copy(), sr


def write_wav_channels(path: str | Path, channels: np.ndarray, sr: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels.shape[0])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(float_to_pcm16(channels.T.reshape(-1)))


def write_wav(path: str | Path, x: np.ndarray, sr: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(float_to_pcm16(x))


def wav_bytes(x: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(float_to_pcm16(x))
    return buf.getvalue()


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0
