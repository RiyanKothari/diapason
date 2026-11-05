"""The caller's outgoing audio as a continuous phone stream.

A real line never goes digitally silent: between utterances the agent hears the caller's
background (traffic, fan, crowd) through the same codec. ChannelStream pre-renders that
noise bed for the whole call and, when the caller speaks, renders speech mixed with the
matching slice of the bed through the channel, so the agent's VAD is tested on both.
"""

from __future__ import annotations

import numpy as np

from ..audio import resample
from ..channel import ChannelProfile, apply_channel
from ..channel.noise import make_noise
from ..channel.sim import active_speech_power
from ..judge.metrics import Segment, speech_segments

INTERNAL_SR = 16000
REF_DBFS = -20.0   # active speech level the caller is normalised to


class ChannelStream:
    def __init__(self, profile: ChannelProfile, out_sr: int, seed: int, max_s: float = 300.0):
        self.profile, self.out_sr, self.seed = profile, out_sr, seed
        self.quiet = profile.model_copy(update={"noise": "none", "noise_file": None})
        rng = np.random.default_rng(seed)
        n = int(max_s * INTERNAL_SR)
        ref_power = 10 ** (REF_DBFS / 10)
        if profile.noise != "none" or profile.noise_file:
            bed = make_noise(profile.noise, n, INTERNAL_SR, rng, profile.noise_file).astype(np.float64)
            bed *= np.sqrt(ref_power / 10 ** (profile.snr_db / 10) / max(np.mean(bed**2), 1e-12))
        else:
            bed = np.zeros(n)
        self.bed_raw = bed
        rendered, ch_sr, _ = apply_channel(bed, INTERNAL_SR, self.quiet, seed=seed)
        self.bed_out = resample(rendered, ch_sr, out_sr)
        self.cursor = 0                      # samples sent so far, at out_sr
        self.pending = np.zeros(0, np.float32)
        self.utterances = 0

    @property
    def speaking(self) -> bool:
        return self.pending.size > 0

    @property
    def time_s(self) -> float:
        return self.cursor / self.out_sr

    def say(self, speech: np.ndarray, sr: int) -> list[Segment]:
        """Queue an utterance; returns its ground-truth speech intervals on the call timeline."""
        x = resample(speech.astype(np.float32), sr, INTERNAL_SR).astype(np.float64)
        p = active_speech_power(x, INTERNAL_SR)
        if p > 0:
            x *= np.sqrt(10 ** (REF_DBFS / 10) / p)
        start_s = self.time_s + self.pending.size / self.out_sr
        i = int(start_s * INTERNAL_SR) % self.bed_raw.size
        noise = np.resize(np.roll(self.bed_raw, -i), x.size)
        self.utterances += 1
        out, ch_sr, _ = apply_channel(x + noise, INTERNAL_SR, self.quiet, seed=self.seed + self.utterances)
        self.pending = np.concatenate([self.pending, resample(out, ch_sr, self.out_sr)])
        return [Segment(round(start_s + s.start, 3), round(start_s + s.end, 3)) for s in speech_segments(x.astype(np.float32), INTERNAL_SR, use_noise_floor=False)]

    def stop_speaking(self) -> None:
        self.pending = np.zeros(0, np.float32)

    def next_frame(self, n: int) -> np.ndarray:
        if self.pending.size:
            frame, self.pending = self.pending[:n], self.pending[n:]
            if frame.size < n:   # utterance ends mid-frame: fill the rest with the bed
                j = (self.cursor + frame.size) % self.bed_out.size
                frame = np.concatenate([frame, np.resize(np.roll(self.bed_out, -j), n - frame.size)])
        else:
            j = self.cursor % self.bed_out.size
            frame = self.bed_out[j : j + n]
            if frame.size < n:
                frame = np.concatenate([frame, self.bed_out[: n - frame.size]])
        self.cursor += n
        return frame.astype(np.float32)
