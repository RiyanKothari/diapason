"""Online endpointing of the agent's played-out audio, frame by frame.

Emits ("start", t) when the agent starts talking and ("end", t, audio) once it has been
quiet for end_silence_s. Audio arrives clean over the websocket, so an absolute level
threshold is enough; the 100 ms pre-roll keeps word onsets for transcription.
"""

from __future__ import annotations

import numpy as np


class Ears:
    def __init__(self, sr: int, threshold_dbfs: float = -45.0, start_frames: int = 3,
                 end_silence_s: float = 0.8, preroll_s: float = 0.1):
        self.sr, self.threshold = sr, threshold_dbfs
        self.start_frames, self.end_silence_s = start_frames, end_silence_s
        self.preroll: list[np.ndarray] = []
        self.preroll_n = int(preroll_s * sr)
        self.buf: list[np.ndarray] = []
        self.active = False
        self.run = 0          # consecutive loud frames while idle
        self.quiet_s = 0.0    # silence so far while active
        self.started_at = 0.0

    @property
    def talking(self) -> bool:
        return self.active

    def feed(self, frame: np.ndarray, t: float) -> list[tuple]:
        """Process one frame that started playing at time t."""
        dur = frame.size / self.sr
        level = 10 * np.log10(np.mean(np.square(frame, dtype=np.float64)) + 1e-12)
        loud = level > self.threshold
        events: list[tuple] = []
        if not self.active:
            self.preroll.append(frame)
            while sum(f.size for f in self.preroll) > self.preroll_n + frame.size * self.start_frames:
                self.preroll.pop(0)
            self.run = self.run + 1 if loud else 0
            if self.run >= self.start_frames:
                self.active, self.quiet_s = True, 0.0
                self.started_at = round(t - dur * (self.start_frames - 1), 3)
                self.buf = list(self.preroll)
                self.preroll = []
                events.append(("start", self.started_at))
            return events
        self.buf.append(frame)
        self.quiet_s = 0.0 if loud else self.quiet_s + dur
        if self.quiet_s >= self.end_silence_s:
            audio = np.concatenate(self.buf)
            trim = int(self.quiet_s * self.sr)
            events.append(("end", round(t + dur - self.quiet_s, 3), audio[: max(1, audio.size - trim)]))
            self.active, self.buf, self.run = False, [], 0
        return events

    def flush(self, t: float) -> list[tuple]:
        """Call ended while the agent was talking: emit what was heard."""
        if not self.active or not self.buf:
            return []
        self.active = False
        audio, self.buf = np.concatenate(self.buf), []
        return [("end", round(t, 3), audio)]
