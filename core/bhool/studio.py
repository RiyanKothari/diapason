"""QA Studio data: every scorecard (segments and industry playbooks) and every audit on disk.

Shared by the dashboard server (/api/studio) and the static site (`bhool site`), so both show exactly the same thing.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def index(runs_dir: Path, scorecards_dir: Path, playbooks: Path = Path("playbooks/industries.yaml")) -> dict:
    from .qa import Scorecard
    books = {}
    if playbooks.exists():
        from .playbooks import load_playbooks
        try:
            books = {b.id: b for b in load_playbooks(playbooks)}
        except Exception:
            books = {}
    cards = []
    files = [("segments", f) for f in sorted(scorecards_dir.glob("*.yaml"))] + \
            [("industries", f) for f in sorted((scorecards_dir / "industries").glob("*.yaml"))]
    for group, f in files:
        try:
            c = Scorecard.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
        except Exception as e:
            cards.append({"stem": f"{group}/{f.stem}", "group": group, "name": f.stem, "error": str(e)[:200]})
            continue
        b = books.get(f.stem) if group == "industries" else None
        extra = {"title": b.title, "brand": b.brand, "sector": b.sector, "use_case": b.use_case, "languages": b.languages,
                 "regulations": b.regulations} if b else {}
        cards.append({"stem": f"{group}/{f.stem}", "group": group, **extra, "name": c.name, "agent": c.agent.name,
                      "sop": c.agent.sop, "pass_mark": c.pass_mark, "checks": len(c.parameters()),
                      "fatal": sum(p.fatal for p in c.parameters()), "code": sum(p.check.type != "llm" for p in c.parameters()),
                      "sections": [{"id": s.id, "name": s.name or s.id, "params": [
                          {"id": p.id, "label": p.label, "fatal": p.fatal, "type": p.check.type, "describe": p.check.describe(), "source": p.source}
                          for p in s.parameters]} for s in c.sections]})
    audits = []
    for f in list(runs_dir.glob("*/qa.json")) + list(runs_dir.glob("*/*/qa.json")):
        try:
            q = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        s = q.get("summary") or {}
        sim = f.parent / "simulate.json"
        ev = json.loads(sim.read_text(encoding="utf-8")).get("evaluation") if sim.exists() else None
        audits.append({"path": f.parent.relative_to(runs_dir).as_posix(), "generated": q.get("generated"),
                       "scorecard": s.get("scorecard"), "calls": s.get("calls"), "avg_score": s.get("avg_score"),
                       "pass_rate": s.get("pass_rate"), "fatal_rate": s.get("fatal_rate"),
                       "review": len(s.get("review_queue") or []), "evaluation": ev})
    audits.sort(key=lambda a: a["generated"] or "", reverse=True)
    return {"scorecards": cards, "audits": audits}


def audit(runs_dir: Path, path: str, audio_url=lambda rel: "/runs/" + rel) -> dict | None:
    """One audit's calls, with the planted-defect plan (for simulated calls) and a URL for each call's recording.
    None if the path is not an audit inside runs_dir."""
    root = runs_dir.resolve()
    f = (runs_dir / path / "qa.json").resolve()
    if root not in f.parents or not f.exists():
        return None
    q = json.loads(f.read_text(encoding="utf-8"))
    sim = f.parent / "simulate.json"
    simd = json.loads(sim.read_text(encoding="utf-8")) if sim.exists() else {}
    plan = {c["call_id"]: c for c in simd.get("calls", [])}
    for c in q["calls"]:
        src = (c.get("meta") or {}).get("source") or ""
        c["audio"] = None
        if src.lower().endswith(".wav"):
            a = Path(src).resolve()
            if root in a.parents and a.exists():
                c["audio"] = audio_url(a.relative_to(root).as_posix())
        p = plan.get(c["call_id"]) or {}
        c["planted"], c["timing_planted"], c["plants"] = p.get("planted"), p.get("timing"), p.get("plants") or []
    return {"summary": q.get("summary"), "generated": q.get("generated"), "calls": q["calls"], "evaluation": simd.get("evaluation")}
