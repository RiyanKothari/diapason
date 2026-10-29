"""Test-suite format.

A suite names a target agent, the agent's spec (what it must and must not do), and
scenarios. Scenarios come from an explicit list and/or a matrix of
personas x behaviours x channels, sampled deterministically to fit a budget.
"""

from __future__ import annotations

import hashlib
import itertools
import random
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from ..channel import PRESETS, ChannelProfile

STT_LANGS = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "pa-IN", "ta-IN", "te-IN"}
# Timbre accepts the STT codes plus Hinglish and auto-detect.
TTS_LANGS = STT_LANGS | {"hi-en", "auto"}
TIMBRE_V3_VOICES = {
    "Shivani", "Lakshmi", "Kalpana", "Chetana", "Vasudha", "Riyaa", "Tarika",
    "Avinash", "Shubham", "Prakash", "Devansh", "Yashraj", "Harshad",
}
EMOTION_TAGS = {
    "laugh", "giggle", "sigh", "exhales", "sniffles", "yawns", "coughs",
    "clears throat", "whispers", "shouting", "excited", "slow", "pauses",
}


class Target(BaseModel):
    type: Literal["websocket", "phone", "inya"]
    url: str | None = None          # websocket target
    number: str | None = None       # phone target, E.164
    agent_id: str | None = None     # inya target
    sample_rate: int = 16000

    @model_validator(mode="after")
    def _needs_address(self):
        need = {"websocket": "url", "phone": "number", "inya": "agent_id"}[self.type]
        if not getattr(self, need):
            raise ValueError(f"target type {self.type!r} requires {need!r}")
        return self


class AgentSpec(BaseModel):
    """What the agent under test is supposed to do; drives scenario generation and judging."""
    name: str
    sop: str = Field(..., description="Standard operating procedure / system prompt summary")
    required_disclosures: list[str] = []
    disclosure_phrases: list[str] = []   # words that prove a disclosure was said (any one), checked in code, e.g. [record, रिकॉर्ड]
    banned_phrases: list[str] = []
    # Extra native-script spellings, e.g. {"legal action": ["कानूनी कार्रवाई"]}; built-ins cover common loanwords.
    banned_phrase_variants: dict[str, list[str]] = {}
    must_collect: list[str] = []   # slots, e.g. ["loan_id", "promise_to_pay_date"]
    languages: list[str] = ["hi-IN"]


class Persona(BaseModel):
    id: str
    description: str
    stt_lang: str = "hi-IN"          # what the agent must transcribe; code-mixed Hindi uses hi-IN
    tts_lang: str = "hi-en"
    voice: str = "Shivani"
    emotion: list[str] = []          # Timbre v3 audio tags used by the caller bot
    speed: float = Field(1.0, ge=0.85, le=1.15)
    hidden_facts: dict[str, str] = {}   # ground truth the agent should extract, e.g. loan_id
    crm: dict[str, str] = {}            # what the agent's systems already know; sent to the agent at call start
    goal: str = ""

    @model_validator(mode="after")
    def _check(self):
        if self.stt_lang not in STT_LANGS:
            raise ValueError(f"{self.id}: stt_lang {self.stt_lang!r} not supported by Prisma")
        if self.tts_lang not in TTS_LANGS:
            raise ValueError(f"{self.id}: tts_lang {self.tts_lang!r} not supported by Timbre")
        if self.voice not in TIMBRE_V3_VOICES:
            raise ValueError(f"{self.id}: voice {self.voice!r} is not a Timbre v3.0 voice")
        bad = set(self.emotion) - EMOTION_TAGS
        if bad:
            raise ValueError(f"{self.id}: unknown audio tags {sorted(bad)}")
        return self


class Behaviour(BaseModel):
    id: str
    instructions: str               # what the caller bot does, in plain words
    interrupt_prob: float = Field(0.0, ge=0, le=1)   # chance per agent turn of barging in
    silence_s: float = Field(0.0, ge=0)              # stays silent this long at some point
    max_turns: int = Field(12, ge=1, le=60)
    # Exact words for given replies (1 = the caller's first reply). A model role-playing a caller drifts back
    # to its persona and may never deliver the attack; a pinned line always lands.
    lines: dict[int, str] = {}


class Scenario(BaseModel):
    id: str
    persona: Persona
    behaviour: Behaviour
    channel: ChannelProfile
    seed: int


class Matrix(BaseModel):
    personas: list[str] | Literal["all"] = "all"
    behaviours: list[str] | Literal["all"] = "all"
    channels: list[str] | Literal["all"] = "all"
    sample: int | None = Field(None, ge=1, description="cap on scenarios; None = full product")
    seed: int = 0


class Case(BaseModel):
    """An explicit scenario, e.g. one distilled from a failed production call."""
    id: str
    persona: str
    behaviour: str
    channel: str
    source: str = ""        # where it came from (production call file)
    failure: str = ""       # what went wrong originally; the case passes once this no longer happens


class Gate(BaseModel):
    min_pass_rate: float = Field(0.85, ge=0, le=1)
    max_p95_latency_ms: int | None = 2500
    check_dead_air: bool = True     # off when the agent's response time is not the agent's own (see demo.run_version)


class Suite(BaseModel):
    name: str
    target: Target
    agent: AgentSpec
    personas: list[Persona]
    behaviours: list[Behaviour] = []
    use_library: bool | list[str] = False   # add built-in adversarial behaviours (all, or these ids)
    channels: list[ChannelProfile] = []
    matrix: Matrix | None = Matrix()      # None: only the explicit cases run
    cases: list[Case] = []
    runs_per_scenario: int = Field(1, ge=1, le=10)
    gate: Gate = Gate()
    rubric: str = "general"    # judge pack: general, bfsi_collections, insurance, healthcare, telecom, kyc

    @model_validator(mode="after")
    def _known_rubric(self):
        from ..judge.packs import get_pack
        get_pack(self.rubric)
        return self

    @model_validator(mode="after")
    def _merge_library(self):
        if self.use_library:
            from .library import LIBRARY
            ids = list(LIBRARY) if self.use_library is True else self.use_library
            unknown = [i for i in ids if i not in LIBRARY]
            if unknown:
                raise ValueError(f"unknown library behaviours: {unknown}; available: {sorted(LIBRARY)}")
            own = {b.id for b in self.behaviours}
            self.behaviours = self.behaviours + [LIBRARY[i] for i in ids if i not in own]
        if not self.behaviours:
            raise ValueError("suite needs at least one behaviour (define some or set use_library)")
        return self

    @model_validator(mode="after")
    def _unique_ids(self):
        for kind, items in (("persona", self.personas), ("behaviour", self.behaviours), ("channel", self.channels)):
            ids = [i.id for i in items]
            dup = {i for i in ids if ids.count(i) > 1}
            if dup:
                raise ValueError(f"duplicate {kind} ids: {sorted(dup)}")
        return self

    def channel_pool(self) -> dict[str, ChannelProfile]:
        return {**PRESETS, **{c.id: c for c in self.channels}}

    def expand(self) -> list[Scenario]:
        """Explicit cases, then persona x behaviour x channel from the matrix, sampled deterministically."""
        def pick(names, pool: dict, kind: str):
            if names == "all":
                return list(pool.values())
            missing = [n for n in names if n not in pool]
            if missing:
                raise ValueError(f"matrix references unknown {kind}: {missing}")
            return [pool[n] for n in names]

        def seed_for(sid: str, salt: int) -> int:
            return int(hashlib.sha256(f"{sid}:{salt}".encode()).hexdigest()[:8], 16)

        personas, behaviours = {p.id: p for p in self.personas}, {b.id: b for b in self.behaviours}
        out = []
        for c in self.cases:
            p = pick([c.persona], personas, "persona")[0]
            b = pick([c.behaviour], behaviours, "behaviour")[0]
            ch = pick([c.channel], self.channel_pool(), "channel")[0]
            out.append(Scenario(id=c.id, persona=p, behaviour=b, channel=ch, seed=seed_for(c.id, 0)))
        if self.matrix is None:
            return out

        m = self.matrix
        # "all" channels means the suite's own channels, or every preset if it defines none;
        # named channels may refer to either.
        channels = (
            list(({c.id: c for c in self.channels} or PRESETS).values())
            if m.channels == "all"
            else pick(m.channels, self.channel_pool(), "channel")
        )
        combos = list(itertools.product(
            pick(m.personas, personas, "persona"),
            pick(m.behaviours, behaviours, "behaviour"),
            channels,
        ))
        if m.sample and m.sample < len(combos):
            combos = random.Random(m.seed).sample(combos, m.sample)
        for p, b, c in combos:
            sid = f"{p.id}__{b.id}__{c.id}"
            out.append(Scenario(id=sid, persona=p, behaviour=b, channel=c, seed=seed_for(sid, m.seed)))
        return out


def load_suite(path: str | Path) -> Suite:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Suite.model_validate(data)
