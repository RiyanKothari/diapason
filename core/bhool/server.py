"""Dashboard server: start suite runs, stream every call live over a WebSocket, browse past runs.

    bhool dashboard            -> http://127.0.0.1:8000
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .runner import Budget, estimate_usage, run_suite
from .scenarios import load_suite
from .wiring import live_components, offline_components

STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    suite: str
    mode: str = "offline"          # offline (zero credits) | live
    limit: int | None = 4
    url: str | None = None
    stubborn: bool = False         # offline only: a fake agent that ignores barge-ins
    judge: bool = True
    label: str = ""
    max_tts_chars: int | None = None
    redact: bool = True            # dashboards get shared; mask PII by default


def create_app(suites_dir: str | Path = "suites", runs_dir: str | Path = "runs",
               scorecards_dir: str | Path = "scorecards") -> FastAPI:
    suites_dir, runs_dir, scorecards_dir = Path(suites_dir), Path(runs_dir), Path(scorecards_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Bhool Bhulaiya")
    clients: set[asyncio.Queue] = set()
    history: list[dict] = []          # events of the current run, replayed to late joiners
    state = {"running": None}

    def broadcast(e: dict) -> None:
        if e.get("type") == "suite_start":
            history.clear()
        history.append(e)
        for q in list(clients):
            q.put_nowait(e)

    def suite_path(name: str) -> Path:
        p = (suites_dir / name).resolve()
        if p.parent != suites_dir.resolve() or p.suffix not in (".yaml", ".yml") or not p.exists():
            raise HTTPException(404, f"no suite {name!r}")
        return p

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/suites")
    def suites():
        out = []
        for p in sorted(suites_dir.glob("*.y*ml")):
            try:
                s = load_suite(p)
                out.append({"file": p.name, "name": s.name, "scenarios": len(s.expand()),
                            "runs_per_scenario": s.runs_per_scenario, "estimate": estimate_usage(s)})
            except Exception as e:      # show broken suites instead of hiding them
                out.append({"file": p.name, "error": str(e)[:300]})
        return out

    @app.get("/api/runs")
    def runs():
        out = []
        for d in sorted(runs_dir.iterdir(), reverse=True):
            f = d / "report.json"
            if f.exists():
                r = json.loads(f.read_text(encoding="utf-8"))
                out.append({k: r.get(k) for k in ("suite", "run_id", "started_at", "calls", "pass_rate",
                                                  "latency_p95_s", "gate_passed", "gate_reasons")} | {"dir": d.name})
        return out

    @app.get("/api/status")
    def status():
        return {"running": state["running"]}

    @app.post("/api/runs")
    async def start_run(req: RunRequest):
        if state["running"]:
            raise HTTPException(409, f"a run is already in progress: {state['running']}")
        suite = load_suite(suite_path(req.suite))
        try:
            c = live_components(suite, url=req.url, judge=req.judge) if req.mode == "live" else offline_components(suite, req.stubborn)
        except Exception as e:
            raise HTTPException(400, str(e)) from e
        scenarios = suite.expand()[: req.limit] if req.limit else suite.expand()
        state["running"] = suite.name

        async def go():
            try:
                await run_suite(suite, c.connect, c.make_brain, c.speak, c.hear, evon_judge=c.evon_judge,
                                out_dir=runs_dir, scenarios=scenarios, on_event=broadcast, call_kwargs=c.call_kwargs,
                                label=req.label, redact_pii=req.redact, budget=Budget(max_tts_chars=req.max_tts_chars))
            except Exception as e:
                broadcast({"type": "suite_error", "error": repr(e)})
            finally:
                state["running"] = None

        asyncio.create_task(go())
        return {"started": suite.name, "calls": len(scenarios) * suite.runs_per_scenario, "mode": req.mode}

    @app.websocket("/api/live")
    async def live(ws: WebSocket):
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue()
        for e in history:
            q.put_nowait(e)
        clients.add(q)
        try:
            while True:
                await ws.send_text(json.dumps(await q.get(), ensure_ascii=False, default=str))
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(q)

    @app.get("/api/qa")
    def qa_audits():
        out = []
        for d in sorted(runs_dir.iterdir(), reverse=True):
            f = d / "qa.json"
            if f.exists():
                q = json.loads(f.read_text(encoding="utf-8"))
                s = q["summary"]
                out.append({"dir": d.name, "generated": q.get("generated"), "scorecard": s["scorecard"], "calls": s["calls"],
                            "avg_score": s["avg_score"], "pass_rate": s["pass_rate"], "fatal_rate": s["fatal_rate"],
                            "review": len(s["review_queue"])})
        return out

    @app.get("/studio", response_class=HTMLResponse)
    def studio():
        return (STATIC / "studio.html").read_text(encoding="utf-8")

    @app.get("/api/studio")
    def studio_index():
        """Every scorecard (one per business segment) and every audit on disk, newest first."""
        import yaml
        from .qa import Scorecard
        books = {}
        pb = Path("playbooks/industries.yaml")
        if pb.exists():
            from .playbooks import load_playbooks
            try:
                books = {b.id: b for b in load_playbooks(pb)}
            except Exception:
                books = {}
        cards = []
        files = [("segments", f) for f in sorted(scorecards_dir.glob("*.yaml"))] +                 [("industries", f) for f in sorted((scorecards_dir / "industries").glob("*.yaml"))]
        for group, f in files:
            try:
                c = Scorecard.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
            except Exception as e:
                cards.append({"stem": f"{group}/{f.stem}", "group": group, "name": f.stem, "error": str(e)[:200]})
                continue
            b = books.get(f.stem) if group == "industries" else None
            extra = {"title": b.title, "brand": b.brand, "sector": b.sector, "use_case": b.use_case, "languages": b.languages,
                     "regulations": b.regulations} if b else {}
            cards.append({"stem": f"{group}/{f.stem}", "group": group, **extra, "name": c.name, "agent": c.agent.name, "sop": c.agent.sop, "pass_mark": c.pass_mark,
                          "checks": len(c.parameters()), "fatal": sum(p.fatal for p in c.parameters()),
                          "code": sum(p.check.type != "llm" for p in c.parameters()),
                          "sections": [{"id": s.id, "name": s.name or s.id, "params": [
                              {"id": p.id, "label": p.label, "fatal": p.fatal, "type": p.check.type, "describe": p.check.describe()}
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

    @app.get("/api/studio/audit/{path:path}")
    def studio_audit(path: str):
        root = runs_dir.resolve()
        f = (runs_dir / path / "qa.json").resolve()
        if root not in f.parents or not f.exists():
            raise HTTPException(404)
        q = json.loads(f.read_text(encoding="utf-8"))
        sim = f.parent / "simulate.json"
        plan = {c["call_id"]: c for c in json.loads(sim.read_text(encoding="utf-8"))["calls"]} if sim.exists() else {}
        for c in q["calls"]:
            src = (c.get("meta") or {}).get("source") or ""
            c["audio"] = None
            if src.lower().endswith(".wav"):
                a = Path(src).resolve()
                if root in a.parents and a.exists():
                    c["audio"] = "/runs/" + a.relative_to(root).as_posix()
            p = plan.get(c["call_id"])
            c["planted"] = (p or {}).get("planted")
            c["timing_planted"] = (p or {}).get("timing")
            c["plants"] = (p or {}).get("plants") or []
        return {"summary": q.get("summary"), "generated": q.get("generated"), "calls": q["calls"],
                "evaluation": json.loads(sim.read_text(encoding="utf-8")).get("evaluation") if sim.exists() else None}

    @app.get("/api/proof")
    def proofs():
        """Accuracy proofs and autopilot runs, newest first, with their headline numbers."""
        out = []
        for d in sorted(runs_dir.iterdir(), reverse=True):
            if (d / "proof.json").exists():
                p = json.loads((d / "proof.json").read_text(encoding="utf-8"))
                t, q = p["tests"], p["qa"]
                out.append({"kind": "proof", "dir": d.name, "page": "proof.html", "generated": p["generated"],
                            "headline": f"bugs caught {t['caught']}/{t['measured']} · v2 flags {t['false_alarms']} · "
                                        f"QA accuracy {round(100 * (q.get('overall') or {}).get('accuracy', 0))}% · "
                                        f"decisions right {round(100 * (q.get('decision_accuracy') or 0))}%"})
            elif (d / "segments.json").exists():
                rows = json.loads((d / "segments.json").read_text(encoding="utf-8"))
                found = sum(round((r["evaluation"]["planted_recall"] or 0) * r["evaluation"]["planted"]) for r in rows)
                out.append({"kind": "segments", "dir": d.name, "page": "segments.html",
                            "generated": time.strftime("%Y-%m-%d %H:%M", time.localtime((d / "segments.json").stat().st_mtime)),
                            "headline": f"{len(rows)} {'industries' if d.name.startswith('industries') else 'segments'} · planted defects found {found}/{sum(r['evaluation']['planted'] for r in rows)} · "
                                        f"false fatal {sum(r['evaluation']['false_fatal'] for r in rows)}/"
                                        f"{sum(r['evaluation']['clean_fatal_calls'] for r in rows)}"})
            elif (d / "autopilot.json").exists():
                a = json.loads((d / "autopilot.json").read_text(encoding="utf-8"))
                h = a.get("heal") or {}
                broke = sum(bool(x["broke"]) for x in a["attacks"])
                out.append({"kind": "autopilot", "dir": d.name, "page": "autopilot.html", "generated": a["generated"],
                            "headline": f"{broke}/{len(a['attacks'])} attacks broke agent {a['agent']}"
                                        + (f" · healed {round(100 * h['before_pass_rate'])}% → {round(100 * h['after_pass_rate'])}%, "
                                           f"{len(h['broken'])} regressions" if h else "")})
        return sorted(out, key=lambda x: x["generated"], reverse=True)

    @app.get("/runs/{run_dir}/report")
    def report(run_dir: str):
        f = (runs_dir / run_dir / "report.html").resolve()
        if runs_dir.resolve() not in f.parents or not f.exists():
            raise HTTPException(404)
        return FileResponse(f)

    @app.get("/runs/{run_dir}/qa")
    def qa_report(run_dir: str):
        f = (runs_dir / run_dir / "qa.html").resolve()
        if runs_dir.resolve() not in f.parents or not f.exists():
            raise HTTPException(404)
        return FileResponse(f)

    app.mount("/runs", StaticFiles(directory=runs_dir), name="runs")
    return app
