"""QA scorecards: the weighted evaluation forms contact-centre QA teams fill in by hand, made executable.

A scorecard is sections of parameters. Each parameter has a weight, may be *fatal* (a fail zeroes the
call, the industry convention for compliance breaches) and one check:

- ``llm``            Evon answers a yes/no question (or a 1..N scale) with quoted, verified evidence
- ``phrase_present`` a speaker must say one of these phrases (native-script loanword spellings included)
- ``phrase_absent``  a speaker must never say any of these phrases
- ``order``          the first ``first`` phrase must come before the first ``then`` phrase
                     (e.g. verify identity before stating the amount)
- ``metric``         a measured number must satisfy a bound, e.g. ``latency_p95_s <= 2.5``
- ``slot``           a value (e.g. promise_to_pay_date) must be captured, and match the CRM when known
- ``echo``           after the customer offers a date, the agent repeats it back (dates read in Hindi, Gujarati, English)

Everything except ``llm`` is computed in code: free, deterministic and impossible to hallucinate.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..scenarios.schema import AgentSpec

CheckType = Literal["llm", "phrase_present", "phrase_absent", "order", "metric", "slot", "echo"]
METRIC_RE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*(<=|>=|==|!=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")


class Check(BaseModel):
    type: CheckType = "llm"
    question: str | None = None                    # llm
    scale: int | None = Field(None, ge=2, le=10)    # llm: score 1..scale instead of pass/fail
    phrases: list[str] = []                         # phrase_present / phrase_absent
    speaker: Literal["agent", "caller"] = "agent"
    first: list[str] = []                           # order
    then: list[str] = []                            # order
    metric: str | None = None                       # metric: "<name> <op> <number>"
    slot: str | None = None                         # slot
    of: Literal["date"] = "date"                    # echo: what must be repeated back

    @model_validator(mode="after")
    def _complete(self):
        need = {"llm": self.question, "phrase_present": self.phrases, "phrase_absent": self.phrases,
                "order": self.first and self.then, "metric": self.metric, "slot": self.slot, "echo": True}[self.type]
        if not need:
            raise ValueError(f"check type {self.type!r} is missing its fields")
        if self.type == "metric" and not METRIC_RE.match(self.metric or ""):
            raise ValueError(f"metric check must look like 'latency_p95_s <= 2.5', got {self.metric!r}")
        return self

    def describe(self) -> str:
        if self.type == "llm":
            return self.question or ""
        if self.type == "phrase_present":
            return f"{self.speaker} says one of: " + ", ".join(self.phrases)
        if self.type == "phrase_absent":
            return f"{self.speaker} never says: " + ", ".join(self.phrases)
        if self.type == "order":
            return f"{' / '.join(self.first)} before {' / '.join(self.then)}"
        if self.type == "metric":
            return self.metric or ""
        if self.type == "echo":
            return f"after the customer offers a {self.of}, the agent repeats it back"
        return f"captures {self.slot}"


class Parameter(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = ""
    weight: float = Field(1.0, ge=0)
    fatal: bool = False
    check: Check
    source: str = ""            # the clause of the policy or regulation this check enforces (see qa/compile.py)

    @property
    def label(self) -> str:
        return self.name or self.id.replace("_", " ")


class Section(BaseModel):
    id: str
    name: str = ""
    parameters: list[Parameter]


class Scorecard(BaseModel):
    """A QA form. ``agent`` gives the judge the SOP; ``dispositions``/``entities`` drive call insights."""
    name: str
    agent: AgentSpec
    sections: list[Section]
    dispositions: list[str] = ["resolved", "promise_to_pay", "callback", "refused", "wrong_party", "escalated", "other"]
    entities: list[str] = []
    pass_mark: float = Field(80, ge=0, le=100)
    review_agreement: float = Field(0.67, ge=0, le=1)   # LLM verdicts with lower agreement go to a human
    review_margin: float = Field(5, ge=0)               # scores this close to the pass mark go to a human
    language: str = "hi-IN"                             # Prisma language for audio input
    caller_channel: int = Field(0, ge=0, le=1)          # stereo channel carrying the customer

    @model_validator(mode="after")
    def _unique(self):
        ids = [p.id for p in self.parameters()]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate parameter ids: {sorted(dup)}")
        if not ids:
            raise ValueError("a scorecard needs at least one parameter")
        return self

    def parameters(self) -> list[Parameter]:
        return [p for s in self.sections for p in s.parameters]

    def section_of(self) -> dict[str, str]:
        return {p.id: s.id for s in self.sections for p in s.parameters}


def from_pack(pack: str, agent: AgentSpec, name: str | None = None) -> Scorecard:
    """A ready scorecard from a compliance rubric pack: critical criteria become fatal parameters,
    the agent's banned phrases a code-checked fatal parameter, and the audio metrics a section."""
    from ..judge.packs import get_pack
    crit = get_pack(pack)
    compliance = [Parameter(id=c.id, weight=10, fatal=True, check=Check(question=c.question)) for c in crit if c.critical]
    conduct = [Parameter(id=c.id, weight=5, check=Check(question=c.question, scale=5 if c.id == "tone" else None))
               for c in crit if not c.critical]
    if agent.banned_phrases:
        compliance.insert(0, Parameter(id="banned_phrases", weight=10, fatal=True,
                                       check=Check(type="phrase_absent", phrases=agent.banned_phrases)))
    conduct += [Parameter(id=f"captures_{s}", weight=5, check=Check(type="slot", slot=s)) for s in agent.must_collect]
    experience = [
        Parameter(id="responsive", name="answers within 2.5 s (p95)", weight=3, check=Check(type="metric", metric="latency_p95_s <= 2.5")),
        Parameter(id="no_dead_air", name="no dead air over 3 s", weight=2, check=Check(type="metric", metric="dead_air_events == 0")),
        Parameter(id="no_talk_over", name="never cuts the customer off", weight=2, check=Check(type="metric", metric="agent_cut_off_caller == 0")),
        Parameter(id="yields_to_barge_in", name="stops when interrupted", weight=2, check=Check(type="metric", metric="barge_ins_ignored == 0")),
    ]
    return Scorecard(name=name or f"{agent.name} · {pack}", agent=agent, entities=list(agent.must_collect),
                     sections=[Section(id="compliance", name="Compliance", parameters=compliance),
                               Section(id="conduct", name="Conduct & outcome", parameters=conduct),
                               Section(id="experience", name="Caller experience (measured)", parameters=experience)])
