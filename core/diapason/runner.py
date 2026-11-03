"""Run a suite: every scenario x run, concurrently; judge each call; aggregate into a report."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .call.engine import CallRecord, Hear, Speak, run_call
from .call.transport import AgentConnection
from .caller.brain import Brain
from .judge.packs import get_pack
from .judge.rubric import CallVerdict, judge_call
from .scenarios.schema import Scenario, Suite

ConnectFactory = Callable[[Scenario], AgentConnection]
BrainFactory = Callable[[Scenario, int], Brain]


@dataclass
class ScenarioSummary:
    scenario_id: str
    persona: str
    behaviour: str
    channel: str
    runs: int
    passed: int
    pass_rate: float
    flaky: bool
    failures: list[str] = field(default_factory=list)


@dataclass
class SuiteReport:
    suite: str
    run_id: str
    started_at: str
    duration_s: float
    calls: int
    pass_rate: float
    latency_p50_s: float | None
    latency_p95_s: float | None
    gate_passed: bool
    gate_reasons: list[str]
    scenarios: list[ScenarioSummary]
    criteria_failures: dict[str, int]
    heatmap: dict[str, dict[str, float]]          # persona -> channel -> pass rate
    behaviour_pass_rate: dict[str, float]
    verdicts: list[dict]
    calls_detail: list[dict]
    usage: dict
    dir: str = ""
    label: str = ""                 # e.g. the agent version under test
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    """Hard caps on API consumption for one run. None = unlimited."""
    max_tts_chars: int | None = None
    max_stt_seconds: float | None = None
    max_evon_calls: int | None = None


class Usage:
    """Counts what a run consumed and refuses any API call that would cross the budget.

    Counts are of requests made (TTS cache hits included), so the cap is conservative.
    """

    def __init__(self, budget: Budget | None = None):
        self.budget = budget or Budget()
        self.tts_chars = self.tts_calls = self.stt_calls = self.evon_calls = 0
        self.stt_seconds = 0.0
        self.exhausted: str | None = None

    def _refuse(self, what: str) -> None:
        self.exhausted = what
        raise BudgetExceeded(f"budget exhausted: {what}")

    def wrap_speak(self, speak: Speak) -> Speak:
        def f(utt, persona):
            n = len(utt.tts_text())
            if self.budget.max_tts_chars is not None and self.tts_chars + n > self.budget.max_tts_chars:
                self._refuse(f"TTS chars {self.tts_chars}+{n} > {self.budget.max_tts_chars}")
            self.tts_calls += 1
            self.tts_chars += n
            return speak(utt, persona)
        return f

    def wrap_hear(self, hear: Hear) -> Hear:
        def f(audio, sr, lang):
            s = audio.size / sr
            if self.budget.max_stt_seconds is not None and self.stt_seconds + s > self.budget.max_stt_seconds:
                self._refuse(f"STT seconds {self.stt_seconds:.0f}+{s:.0f} > {self.budget.max_stt_seconds}")
            self.stt_calls += 1
            self.stt_seconds += s
            return hear(audio, sr, lang)
        return f

    def _count_evon(self) -> None:
        if self.budget.max_evon_calls is not None and self.evon_calls + 1 > self.budget.max_evon_calls:
            self._refuse(f"Evon calls > {self.budget.max_evon_calls}")
        self.evon_calls += 1

    def wrap_evon(self, evon):
        if evon is None:
            return None
        usage = self

        class Counted:
            def chat_json(self, *a, **k):
                usage._count_evon()
                return evon.chat_json(*a, **k)

            def chat(self, *a, **k):
                usage._count_evon()
                return evon.chat(*a, **k)
        return Counted()

    def wrap_brain(self, brain):
        """The caller brain calls Evon too; count it against the same budget."""
        evon = getattr(brain, "evon", None)
        if evon is not None:
            brain.evon = self.wrap_evon(evon)
        return brain

    def to_dict(self) -> dict:
        return {"tts_chars": self.tts_chars, "tts_calls": self.tts_calls, "stt_calls": self.stt_calls,
                "stt_seconds": round(self.stt_seconds, 1), "evon_calls": self.evon_calls,
                "budget_exhausted": self.exhausted}


METRIC_KINDS = {"latency": "latency", "never answered": "unanswered", "barge-in": "barge_in",
                "cut the caller": "cut_off", "dead-air": "dead_air", "abnormally": "abnormal_end"}


def metric_kind(failure: str) -> str:
    return next((k for needle, k in METRIC_KINDS.items() if needle in failure), "other")


def aggregate(suite: Suite, run_id: str, started: float, records: list[CallRecord],
              verdicts: list[CallVerdict], scenarios: list[Scenario], usage: dict) -> SuiteReport:
    by_sid: dict[str, list[CallVerdict]] = defaultdict(list)
    for v in verdicts:
        by_sid[v.scenario_id].append(v)
    summaries, heat, beh = [], defaultdict(lambda: defaultdict(list)), defaultdict(list)
    crit_fail: dict[str, int] = defaultdict(int)
    for v in verdicts:
        for c in v.criteria:
            if c.verdict in ("fail", "review"):
                crit_fail[c.id] += 1
        for f in v.metric_failures:
            crit_fail[f"metric: {metric_kind(f)}"] += 1
    for s in scenarios:
        vs = by_sid.get(s.id, [])
        if not vs:
            continue
        passed = sum(v.passed for v in vs)
        fails = sorted({f"{c.id} ({c.verdict})" for v in vs for c in v.criteria if c.verdict in ("fail", "review")}
                       | {f for v in vs for f in v.metric_failures})
        summaries.append(ScenarioSummary(s.id, s.persona.id, s.behaviour.id, s.channel.id, len(vs), passed,
                                         round(passed / len(vs), 2), 0 < passed < len(vs), fails))
        heat[s.persona.id][s.channel.id].extend(v.passed for v in vs)
        beh[s.behaviour.id].extend(v.passed for v in vs)
    lat = [x for r in records for x in r.metrics.response_latencies_s]
    rate = round(sum(v.passed for v in verdicts) / len(verdicts), 3) if verdicts else 0.0
    p95 = round(float(np.percentile(lat, 95)), 3) if lat else None
    reasons = []
    if rate < suite.gate.min_pass_rate:
        reasons.append(f"pass rate {rate:.0%} < gate {suite.gate.min_pass_rate:.0%}")
    if suite.gate.max_p95_latency_ms and p95 is not None and p95 * 1000 > suite.gate.max_p95_latency_ms:
        reasons.append(f"suite p95 latency {p95 * 1000:.0f} ms > {suite.gate.max_p95_latency_ms} ms")
    if not verdicts:
        reasons.append("no calls completed")
    return SuiteReport(
        suite=suite.name, run_id=run_id, started_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        duration_s=round(time.time() - started, 1), calls=len(verdicts), pass_rate=rate,
        latency_p50_s=round(float(np.percentile(lat, 50)), 3) if lat else None, latency_p95_s=p95,
        gate_passed=not reasons, gate_reasons=reasons, scenarios=summaries, criteria_failures=dict(crit_fail),
        heatmap={p: {c: round(sum(v) / len(v), 2) for c, v in cs.items()} for p, cs in heat.items()},
        behaviour_pass_rate={b: round(sum(v) / len(v), 2) for b, v in beh.items()},
        verdicts=[v.to_dict() for v in verdicts], calls_detail=[r.to_dict() for r in records], usage=usage,
    )


async def run_suite(
    suite: Suite,
    connect: ConnectFactory,
    make_brain: BrainFactory,
    speak: Speak,
    hear: Hear,
    evon_judge=None,
    out_dir: str | Path = "runs",
    concurrency: int = 4,
    scenarios: list[Scenario] | None = None,
    on_event: Callable[[dict], None] | None = None,
    judge_samples: int = 3,
    call_kwargs: dict | None = None,
    budget: Budget | None = None,
    label: str = "",
    redact_pii: bool = False,
) -> SuiteReport:
    started = time.time()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    root = Path(out_dir) / f"{suite.name}-{run_id}"
    root.mkdir(parents=True, exist_ok=True)
    scenarios = scenarios if scenarios is not None else suite.expand()
    usage = Usage(budget)
    speak_c, hear_c, judge_c = usage.wrap_speak(speak), usage.wrap_hear(hear), usage.wrap_evon(evon_judge)
    sem = asyncio.Semaphore(concurrency)
    records: list[CallRecord] = []
    verdicts: list[CallVerdict] = []
    emit = on_event or (lambda e: None)
    emit({"type": "suite_start", "suite": suite.name, "run_id": run_id, "calls": len(scenarios) * suite.runs_per_scenario})

    skipped: list[str] = []

    async def one(s: Scenario, run: int):
        async with sem:
            if usage.exhausted:
                skipped.append(f"{s.id}#{run}")
                emit({"type": "call_skipped", "scenario": s.id, "run": run, "reason": usage.exhausted})
                return
            emit({"type": "call_start", "scenario": s.id, "run": run, "persona": s.persona.id,
                  "behaviour": s.behaviour.id, "channel": s.channel.id})
            try:
                rec = await run_call(s, connect(s), usage.wrap_brain(make_brain(s, run)), speak_c, hear_c,
                                     out_dir=root, run=run, on_event=on_event, **(call_kwargs or {}))
            except BudgetExceeded:
                # a call cut short by the budget is not evidence about the agent: skip, don't judge
                skipped.append(f"{s.id}#{run}")
                emit({"type": "call_skipped", "scenario": s.id, "run": run, "reason": usage.exhausted})
                return
            except Exception as e:
                emit({"type": "call_error", "scenario": s.id, "run": run, "error": repr(e)})
                return
            try:
                v = await asyncio.to_thread(judge_call, rec, suite.agent, s.persona, suite.gate, judge_c,
                                            get_pack(suite.rubric), judge_samples)
            except BudgetExceeded:
                skipped.append(f"{s.id}#{run}")
                emit({"type": "call_skipped", "scenario": s.id, "run": run, "reason": usage.exhausted})
                return
            records.append(rec)
            verdicts.append(v)
            from .checks import explain_verdict
            emit({"type": "verdict", "scenario": s.id, "run": run, "passed": v.passed,
                  "failures": [c.id for c in v.criteria if c.verdict in ("fail", "review")] + v.metric_failures,
                  "details": explain_verdict(v)})

    await asyncio.gather(*(one(s, r) for s in scenarios for r in range(suite.runs_per_scenario)))
    report = aggregate(suite, run_id, started, records, verdicts, scenarios, usage.to_dict())
    report.dir, report.label, report.skipped = str(root), label, skipped
    if skipped:
        report.gate_passed = False
        report.gate_reasons.append(f"{len(skipped)} call(s) skipped: {usage.exhausted}")
    if redact_pii:
        from .redact import redact_call_file, redact_report
        redact_report(report)
        for call_json in root.glob("*/run*/call.json"):
            redact_call_file(call_json)
    (root / "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    from .report import write_html, write_junit
    write_html(report, root / "report.html")
    write_junit(report, root / "junit.xml")
    emit({"type": "suite_end", "run_id": run_id, "pass_rate": report.pass_rate, "gate_passed": report.gate_passed,
          "report": str(root / "report.html")})
    return report


def load_call(call_json: Path, answer_window_s: float | None = None) -> CallRecord:
    """Rebuild a CallRecord from its saved call.json, re-measuring metrics from the saved recordings (with the answer window
    the run was measured with: Evon-played runs allow 30 s, see demo.run_version)."""
    from .audio import read_wav
    from .caller.brain import Turn
    from .judge.metrics import Segment, measure_call
    d = json.loads(Path(call_json).read_text(encoding="utf-8"))
    caller, sr = read_wav(Path(call_json).parent / "caller.wav")
    agent, _ = read_wav(Path(call_json).parent / "agent.wav")
    truth = [Segment(s["start"], s["end"]) for s in d["caller_segments"]]
    return CallRecord(
        scenario_id=d["scenario_id"], run=d["run"], end_reason=d["end_reason"], duration_s=d["duration_s"],
        turns=[Turn(**t) for t in d["turns"]], caller_segments=truth,
        metrics=measure_call(caller, agent, sr, caller_segments=truth,
                             **({"answer_window_s": answer_window_s} if answer_window_s else {})),
        dispositions=d.get("dispositions", []), events=d.get("events", []),
        caller_wav=d.get("caller_wav"), agent_wav=d.get("agent_wav"),
    )


def rejudge_run(run_dir: str | Path, suite: Suite, evon_judge=None, judge_samples: int = 3) -> SuiteReport:
    """Re-score a saved run with the current metrics, code checks and (optionally) Evon. No calls are re-made."""
    root = Path(run_dir)
    old = json.loads((root / "report.json").read_text(encoding="utf-8"))
    if "harness_errors" in old.get("usage", {}):
        # Evon played the agent (demo.run_version): its thinking time was our shared test GPU, so the run was gated without
        # latency and dead air, and a re-judge must be too (seen: re-judging the live proof failed every call on GPU latency)
        suite = suite.model_copy(update={"gate": suite.gate.model_copy(update={"max_p95_latency_ms": None, "check_dead_air": False})})
    window = 30.0 if "harness_errors" in old.get("usage", {}) else None
    by_id = {s.id: s for s in suite.expand()}
    records, verdicts, used = [], [], []
    for cj in sorted(root.glob("*/run*/call.json")):
        rec = load_call(cj, window)
        scen = by_id.get(rec.scenario_id)
        if scen is None:
            continue    # scenario no longer in the suite
        records.append(rec)
        used.append(scen)
        v = judge_call(rec, suite.agent, scen.persona, suite.gate, evon_judge, get_pack(suite.rubric), judge_samples)
        if evon_judge is None:      # code checks refreshed; the judge's earlier verdicts are kept, not thrown away
            from .judge.rubric import CriterionResult, code_overrides_judge
            prev = next((p for p in old["verdicts"] if p["scenario_id"] == rec.scenario_id and p["run"] == rec.run), None)
            keep = [CriterionResult(**{k: c.get(k) for k in ("id", "verdict", "critical", "agreement", "reason", "evidence", "source")},
                                    cross=c.get("cross") or "")
                    for c in (prev or {}).get("criteria", []) if c.get("source") == "judge"]
            v.criteria = code_overrides_judge(v.criteria + keep)
            v.summary, v.judge_samples = (prev or {}).get("summary", ""), (prev or {}).get("judge_samples", 0)
            v.passed = not v.metric_failures and not any(c.critical and c.verdict in ("fail", "review") for c in v.criteria)
        verdicts.append(v)
    uniq = list({s.id: s for s in used}.values())
    report = aggregate(suite, old["run_id"], time.time(), records, verdicts, uniq, old.get("usage", {}))
    report.dir, report.label = str(root), old.get("label", "")
    backup = root / "report.before-rejudge.json"
    if not backup.exists():
        backup.write_text((root / "report.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    from .report import write_html, write_junit
    write_html(report, root / "report.html")
    write_junit(report, root / "junit.xml")
    return report


def estimate_usage(suite: Suite, scenarios: list[Scenario] | None = None, avg_caller_chars: int = 70,
                   avg_agent_turn_s: float = 6.0, judge_samples: int = 3) -> dict:
    """Upper-bound usage before spending anything. Turns are capped by each behaviour's max_turns."""
    scenarios = scenarios if scenarios is not None else suite.expand()
    calls = len(scenarios) * suite.runs_per_scenario
    turns = sum(min(s.behaviour.max_turns, 10) for s in scenarios) * suite.runs_per_scenario
    tts_max, stt_max = turns * avg_caller_chars, round(turns * avg_agent_turn_s)
    return {
        "calls": calls,
        "max_caller_turns": turns,
        # Gnani's published rates: about 555 TTS characters or 3 STT minutes per credit (Evon is self-hosted: no credits)
        "credits_max": round(tts_max / 555 + stt_max / 60 / 3, 1),
        "tts_chars_max": turns * avg_caller_chars,
        "stt_seconds_max": round(turns * avg_agent_turn_s),
        "evon_calls_max": turns + calls * judge_samples,
        "assumptions": f"<= {avg_caller_chars} chars per caller line, <= {avg_agent_turn_s}s per agent turn, "
                       f"{judge_samples} judge samples per call; TTS cache hits on re-runs cost nothing",
    }
