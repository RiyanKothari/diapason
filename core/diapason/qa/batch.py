"""Audit a batch of calls and roll the results up into what a QA lead acts on."""

from __future__ import annotations

import csv
import json
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..advise import cohen_kappa
from .conversation import Conversation
from .engine import QAResult, score_call
from .scorecard import Scorecard


def run_batch(convs: list[Conversation], card: Scorecard, evon=None, samples: int = 3,
              concurrency: int = 4, on_result=None) -> list[QAResult]:
    """Score every call; a failure on one call is recorded on it, never aborts the batch."""
    def one(c: Conversation) -> QAResult:
        try:
            r = score_call(c, card, evon, samples)
        except Exception as e:
            r = QAResult(c.call_id, c.meta, None, False, [], {}, [], {}, {}, {}, [f"audit error: {e!r}"[:200]], [], c.timed,
                         error=repr(e)[:300], audio_s=c.audio_s)
        if on_result:
            on_result(r)
        return r
    with ThreadPoolExecutor(max(1, concurrency)) as pool:
        return list(pool.map(one, convs))


def _rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 1) if xs else None


def aggregate(results: list[QAResult], card: Scorecard, group_by: tuple[str, ...] = ("agent_id", "campaign")) -> dict:
    ok = [r for r in results if r.error is None]
    scored = [r for r in ok if r.score is not None]
    params = card.parameters()
    by_param: dict[str, dict] = {}
    for p in params:
        rs = [x for r in ok for x in r.params if x.id == p.id]
        applicable = [x for x in rs if x.verdict in ("pass", "fail")]
        judged = [x.agreement for x in rs if x.source == "judge" and x.verdict in ("pass", "fail")]
        fails = [(r.call_id, x) for r in ok for x in r.params if x.id == p.id and x.verdict == "fail"]
        reasons = Counter(x.reason for _, x in fails if x.reason)
        by_param[p.id] = {
            "label": p.label, "section": card.section_of()[p.id], "fatal": p.fatal, "weight": p.weight, "type": p.check.type,
            "applicable": len(applicable), "pass_rate": _rate([x.verdict == "pass" for x in applicable]),
            "fails": len(fails), "review": sum(x.verdict == "review" for x in rs), "na": sum(x.verdict == "na" for x in rs),
            "skipped": sum(x.verdict == "skipped" for x in rs),
            "avg_agreement": round(statistics.fmean(judged), 3) if judged else None,
            "top_reasons": [{"reason": k, "n": n} for k, n in reasons.most_common(3)],
            "examples": [{"call_id": cid, **e} for cid, x in fails for e in x.evidence][:5],
        }

    def group(key: str) -> dict:
        g: dict[str, list[QAResult]] = defaultdict(list)
        for r in ok:
            if r.meta.get(key) not in (None, ""):
                g[str(r.meta[key])].append(r)
        out = {}
        for k, rs in g.items():
            weakest = None
            rates = {}
            for p in params:
                v = [x.verdict == "pass" for r in rs for x in r.params if x.id == p.id and x.verdict in ("pass", "fail")]
                if v:
                    rates[p.id] = _rate(v)
            if rates:
                weakest = min(rates, key=lambda i: (rates[i], i))
            tips = [{"call_id": r.call_id, "tip": c["tip"]} for r in rs if not r.passed for c in (r.insights.get("coaching") or [])]
            out[k] = {"calls": len(rs), "avg_score": _mean([r.score for r in rs if r.score is not None]),
                      "pass_rate": _rate([r.passed for r in rs]), "fatal_calls": sum(bool(r.fatal) for r in rs),
                      "param_pass_rates": rates, "weakest": weakest, "coaching": tips[:5]}
        return dict(sorted(out.items(), key=lambda kv: (kv[1]["avg_score"] is None, -(kv[1]["avg_score"] or 0))))

    shifts = [r.insights["sentiment_shift"] for r in ok if "sentiment_shift" in r.insights]
    scores = [r.score for r in scored]
    return {
        "scorecard": card.name, "pass_mark": card.pass_mark,
        "calls": len(results), "audited": len(ok), "errors": [{"call_id": r.call_id, "error": r.error} for r in results if r.error],
        "avg_score": _mean(scores), "median_score": round(statistics.median(scores), 1) if scores else None,
        "pass_rate": _rate([r.passed for r in ok]), "fatal_rate": _rate([bool(r.fatal) for r in ok]),
        "score_bands": {b: sum(lo <= s < hi for s in scores) for b, lo, hi in
                        (("0-49", 0, 50), ("50-69", 50, 70), ("70-84", 70, 85), ("85-100", 85, 100.01))},
        "sections": {s.id: {"name": s.name or s.id, "avg": _mean([r.sections[s.id] for r in ok if r.sections.get(s.id) is not None])}
                     for s in card.sections},
        "parameters": by_param,
        "groups": {k: group(k) for k in group_by},
        "dispositions": dict(Counter(r.insights.get("disposition") for r in ok if r.insights.get("disposition")).most_common()),
        "topics": Counter(t.lower() for r in ok for t in r.insights.get("topics") or []).most_common(10),
        "root_causes": [{"root_cause": k, "n": n} for k, n in
                        Counter(r.insights["root_cause"] for r in ok if r.insights.get("root_cause")).most_common(5)],
        "sentiment": {"calls": len(shifts), "improved": sum(s > 0 for s in shifts), "worsened": sum(s < 0 for s in shifts),
                      "avg_shift": round(statistics.fmean(shifts), 2) if shifts else None},
        "review_queue": [{"call_id": r.call_id, "score": r.score, "reasons": r.review} for r in ok if r.review],
        "worst_calls": [{"call_id": r.call_id, "score": r.score, "fatal": r.fatal} for r in sorted(scored, key=lambda r: r.score)[:5]],
        "coverage": {"timed_calls": sum(r.timed for r in ok), "audio_minutes": round(sum(r.audio_s for r in results) / 60, 1),
                     "talk_minutes": round(sum(r.analytics.get("duration_s", 0) for r in ok) / 60, 1),
                     "judge_samples": sum(r.judge_samples for r in ok)},
    }


def calibrate(results: list[QAResult], labels_csv: str | Path) -> dict:
    """Agreement with human QA. labels_csv: call_id, parameter, verdict (pass|fail|na).
    A 'review' from the auditor counts as disagreement, so routing to a human can't inflate the number."""
    got = {(r.call_id, p.id): p.verdict for r in results for p in r.params}
    per: dict[str, list[tuple[str, str]]] = defaultdict(list)
    missing = 0
    with open(labels_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["call_id"].strip(), row["parameter"].strip())
            human = row["verdict"].strip().lower()
            if human not in ("pass", "fail", "na"):
                raise ValueError(f"bad verdict {human!r} for {key}")
            if key not in got or got[key] == "skipped":
                missing += 1
                continue
            per[key[1]].append((human, got[key]))

    def stats(pairs):
        tp = sum(h == "fail" and a == "fail" for h, a in pairs)
        fp = sum(h != "fail" and a == "fail" for h, a in pairs)
        fn = sum(h == "fail" and a != "fail" for h, a in pairs)
        return {"n": len(pairs), "agreement": round(sum(h == a for h, a in pairs) / len(pairs), 3), "kappa": cohen_kappa(pairs),
                "fail_precision": round(tp / (tp + fp), 3) if tp + fp else None,
                "fail_recall": round(tp / (tp + fn), 3) if tp + fn else None}
    allp = [x for v in per.values() for x in v]
    return {"parameters": {k: stats(v) for k, v in sorted(per.items())}, "overall": stats(allp) if allp else None,
            "labels_not_scored": missing}


def drift(current: dict, baseline: dict, threshold: float = 0.1) -> dict:
    """What moved since a previous audit: score delta and parameters whose pass rate shifted by >= threshold."""
    moved = []
    for pid, p in current["parameters"].items():
        b = (baseline.get("parameters") or {}).get(pid)
        if b and p["pass_rate"] is not None and b.get("pass_rate") is not None:
            d = round(p["pass_rate"] - b["pass_rate"], 3)
            if abs(d) >= threshold:
                moved.append({"parameter": pid, "before": b["pass_rate"], "after": p["pass_rate"], "change": d})
    ds = None if current["avg_score"] is None or baseline.get("avg_score") is None else round(current["avg_score"] - baseline["avg_score"], 1)
    return {"avg_score_change": ds, "pass_rate_before": baseline.get("pass_rate"), "pass_rate_after": current["pass_rate"],
            "moved": sorted(moved, key=lambda m: m["change"])}


def write_outputs(results: list[QAResult], summary: dict, card: Scorecard, out_dir: Path, usage: dict | None = None,
                  redact_pii: bool = True) -> Path:
    from .report import write_html
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": summary, "usage": usage or {},
            "calls": [r.to_dict() for r in results]}
    if redact_pii:     # DPDP: stored audits keep evidence, not phone/Aadhaar/PAN/account numbers
        from ..redact import _walk
        keys = ("text", "quote", "reason", "summary", "tip", "root_cause")
        data["calls"], data["summary"] = _walk(data["calls"], keys), _walk(data["summary"], keys)
    (out_dir / "qa.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    ids = [p.id for p in card.parameters()]
    with open(out_dir / "calls.csv", "w", newline="", encoding="utf-8-sig") as f:      # BOM: Excel reads Hindi correctly
        w = csv.writer(f)
        w.writerow(["call_id", "agent_id", "campaign", "score", "passed", "fatal", "disposition", "sentiment_shift", "needs_review", *ids])
        for r in results:
            v = {p.id: p.verdict for p in r.params}
            w.writerow([r.call_id, r.meta.get("agent_id", ""), r.meta.get("campaign", ""), r.score, r.passed, ";".join(r.fatal),
                        r.insights.get("disposition", ""), r.insights.get("sentiment_shift", ""), bool(r.review), *[v.get(i, "") for i in ids]])
    write_html(data, card, out_dir / "qa.html")
    return out_dir
