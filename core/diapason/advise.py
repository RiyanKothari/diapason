"""After a run: suggest fixes for what failed, and measure how far the judge can be trusted."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

SUGGEST_SYSTEM = """You are a senior voice-AI engineer reviewing failed test calls of a voice agent.
Group the failures by root cause. For each group give: the root cause, the evidence (scenario
ids and quotes as given), and a concrete fix: exact text to add to the agent's system prompt,
or an engineering change (VAD, barge-in handling, latency, language detection) when the
failure is not a prompt problem. Do not invent failures that are not listed.
Reply in Markdown with one "### <root cause>" section per group, most severe first."""


def failure_digest(report: dict, limit: int = 40) -> str:
    lines = []
    for v in report["verdicts"]:
        if v["passed"]:
            continue
        for c in v["criteria"]:
            if c["verdict"] in ("fail", "review"):
                ev = " | ".join(f'T{e["turn"]} "{e["quote"]}"' for e in c["evidence"])
                lines.append(f'- {v["scenario_id"]}: {c["id"]} ({c["verdict"]}): {c["reason"]} {ev}'.strip())
        lines += [f'- {v["scenario_id"]}: metric: {f}' for f in v["metric_failures"]]
    return "\n".join(lines[:limit])


def suggest_fixes(report: dict, sop: str, evon) -> str:
    digest = failure_digest(report)
    if not digest:
        return "No failures in this run."
    text = evon.chat([{"role": "system", "content": SUGGEST_SYSTEM},
                      {"role": "user", "content": f"AGENT SOP:\n{sop}\n\nFAILURES:\n{digest}"}],
                     temperature=0.3, max_tokens=2000)
    return f"# Suggested fixes for {report['suite']} ({report.get('label') or report['run_id']})\n\n{text.strip()}\n"


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Agreement beyond chance between two raters; None when undefined (one class only)."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys()) / (n * n)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 3)


def calibrate(report: dict | None, labels_csv: str | Path, load=None) -> dict:
    """labels_csv columns: scenario_id, run, criterion, verdict (pass|fail|na), and optionally run_dir (from `diapason label`,
    which spans several runs): then each row is matched in load(run_dir)'s report instead of `report`.

    'review' verdicts from the judge count as disagreement on a fail, so they cannot inflate agreement.
    """
    def verdicts(rep: dict, prefix: str = "") -> dict:
        return {(prefix, v["scenario_id"], int(v["run"]), c["id"]): c["verdict"] for v in rep["verdicts"] for c in v["criteria"]}
    judged = verdicts(report) if report else {}
    loaded: set[str] = set()
    per: dict[str, list[tuple[str, str]]] = defaultdict(list)
    missing = 0
    with open(labels_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rd = (row.get("run_dir") or "").strip() if load else ""
            if rd and rd not in loaded:
                judged.update(verdicts(load(rd), rd))
                loaded.add(rd)
            key = (rd, row["scenario_id"].strip(), int(row["run"]), row["criterion"].strip())
            human = row["verdict"].strip().lower()
            if human not in ("pass", "fail", "na"):
                raise ValueError(f"bad verdict {human!r} in labels for {key}")
            if key not in judged:
                missing += 1
                continue
            per[key[3]].append((human, judged[key]))
    out = {}
    for crit, pairs in sorted(per.items()):
        out[crit] = {"n": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3),
                     "kappa": cohen_kappa(pairs),
                     "judge_missed_fail": sum(a == "fail" and b != "fail" for a, b in pairs),
                     "judge_false_fail": sum(a != "fail" and b == "fail" for a, b in pairs)}
    allp = [p for ps in per.values() for p in ps]
    return {"criteria": out, "overall": {"n": len(allp), "agreement": round(sum(a == b for a, b in allp) / len(allp), 3) if allp else None,
                                         "kappa": cohen_kappa(allp)}, "labels_not_in_report": missing}
