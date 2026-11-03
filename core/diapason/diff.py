"""Compare two runs of the same suite: what the new agent version fixed, and what it broke."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ScenarioChange:
    scenario_id: str
    before: float | None      # pass rate, None = not in that run
    after: float | None
    status: str               # fixed | regressed | still_failing | still_passing | improved | worsened | new | removed
    failures_after: list[str] = field(default_factory=list)


@dataclass
class RunDiff:
    before: str
    after: str
    pass_rate_before: float
    pass_rate_after: float
    p95_before: float | None
    p95_after: float | None
    changes: list[ScenarioChange]
    criteria_delta: dict[str, int]      # failures after - before, per criterion

    @property
    def regressions(self) -> list[ScenarioChange]:
        return [c for c in self.changes if c.status in ("regressed", "worsened")]

    def counts(self) -> dict[str, int]:
        return dict(Counter(c.status for c in self.changes))

    def to_dict(self) -> dict:
        return asdict(self) | {"counts": self.counts()}


def load_report(path: str | Path) -> dict:
    p = Path(path)
    if p.is_dir():
        p = p / "report.json"
    return json.loads(p.read_text(encoding="utf-8"))


def classify(before: float | None, after: float | None) -> str:
    if before is None:
        return "new"
    if after is None:
        return "removed"
    if before < 1 and after == 1:
        return "fixed"
    if before == 1 and after < 1:
        return "regressed"
    if before == after:
        return "still_passing" if after == 1 else "still_failing"
    return "improved" if after > before else "worsened"


def diff_reports(a: dict, b: dict) -> RunDiff:
    sa = {s["scenario_id"]: s for s in a["scenarios"]}
    sb = {s["scenario_id"]: s for s in b["scenarios"]}
    changes = []
    for sid in sorted(sa.keys() | sb.keys()):
        before = sa[sid]["pass_rate"] if sid in sa else None
        after = sb[sid]["pass_rate"] if sid in sb else None
        changes.append(ScenarioChange(sid, before, after, classify(before, after), sb.get(sid, {}).get("failures", [])))
    crit = {k: b["criteria_failures"].get(k, 0) - a["criteria_failures"].get(k, 0)
            for k in a["criteria_failures"].keys() | b["criteria_failures"].keys()}
    order = {"regressed": 0, "worsened": 1, "still_failing": 2, "fixed": 3, "improved": 4, "new": 5, "removed": 6, "still_passing": 7}
    changes.sort(key=lambda c: (order[c.status], c.scenario_id))
    return RunDiff(
        before=a.get("label") or a["run_id"], after=b.get("label") or b["run_id"],
        pass_rate_before=a["pass_rate"], pass_rate_after=b["pass_rate"],
        p95_before=a.get("latency_p95_s"), p95_after=b.get("latency_p95_s"),
        changes=changes, criteria_delta={k: v for k, v in sorted(crit.items()) if v},
    )


def arrow(x: float, y: float) -> str:
    return f"{x:.0%} → {y:.0%}"


def to_markdown(d: RunDiff) -> str:
    lines = [f"## {d.before} → {d.after}", "",
             f"- Pass rate: **{arrow(d.pass_rate_before, d.pass_rate_after)}**",
             f"- Latency p95: {d.p95_before}s → {d.p95_after}s",
             "- " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(d.counts().items())), ""]
    for title, keep in (("Regressions", ("regressed", "worsened")), ("Fixed", ("fixed", "improved")), ("Still failing", ("still_failing",))):
        rows = [c for c in d.changes if c.status in keep]
        if rows:
            lines.append(f"### {title}")
            for c in rows:
                why = f" — {'; '.join(c.failures_after)[:200]}" if c.failures_after and c.status != "fixed" else ""
                lines.append(f"- `{c.scenario_id}` {arrow(c.before or 0, c.after or 0)}{why}")
            lines.append("")
    if d.criteria_delta:
        lines.append("### Failures by criterion (after − before)")
        lines += [f"- {k}: {v:+d}" for k, v in d.criteria_delta.items()]
    return "\n".join(lines)
