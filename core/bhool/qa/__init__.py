"""Bhool QA: evidence-backed quality audits of real customer calls (human or AI agents).

The test harness asks "will this agent survive real callers?" before launch; this asks "how did
every real call go?" after. Same judge discipline: code checks first, Evon only where judgment is
needed, every fail quoted from the transcript, and uncertainty routed to a human.
"""

from .batch import aggregate, calibrate, drift, run_batch, write_outputs
from .conversation import Conversation, analyse, from_turns, load
from .engine import ParamResult, QAResult, score_call
from .scorecard import Check, Parameter, Scorecard, Section, from_pack

__all__ = ["Check", "Conversation", "ParamResult", "Parameter", "QAResult", "Scorecard", "Section", "aggregate", "analyse",
           "calibrate", "drift", "from_pack", "from_turns", "load", "run_batch", "score_call", "write_outputs"]
