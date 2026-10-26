"""Dashboard server: start suite runs, stream every call live over a WebSocket, browse past runs.

    bhool dashboard            -> http://127.0.0.1:8000
"""

from __future__ import annotations

import asyncio
import json
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


def create_app(suites_dir: str | Path = "suites", runs_dir: str | Path = "runs") -> FastAPI:
    suites_dir, runs_dir = Path(suites_dir), Path(runs_dir)
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

    @app.get("/runs/{run_dir}/report")
    def report(run_dir: str):
        f = (runs_dir / run_dir / "report.html").resolve()
        if runs_dir.resolve() not in f.parents or not f.exists():
            raise HTTPException(404)
        return FileResponse(f)

    app.mount("/runs", StaticFiles(directory=runs_dir), name="runs")
    return app
