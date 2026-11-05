"""Dashboard server: start suite runs, stream every call live over a WebSocket, browse past runs.

    diapason dashboard            -> http://127.0.0.1:8000
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
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
    target: str | None = None      # live: "websocket" (Diapason protocol) or "media_stream" (Twilio Media Streams)
    stubborn: bool = False         # offline only: a fake agent that ignores barge-ins
    judge: bool = True
    label: str = ""
    # Live runs spend Gnani credits, so the dashboard always caps them; the CLI is where an uncapped run is chosen.
    max_tts_chars: int | None = 400
    max_stt_seconds: float | None = 60
    redact: bool = True            # dashboards get shared; mask PII by default
    version: str | None = None     # reference mode: v1-v4, or v1+guard / v3+guard
    evon: bool = False             # reference mode: Evon plays the agent and callers, and judges (no speech credits)


class FixRequest(BaseModel):
    run: str
    agent: str | None = None       # a reference version (v1-v4) to prove fixes on; None lists the lanes without proof
    rounds: int = 2


class WriteRequest(BaseModel):
    name: str
    sop: str
    transcripts: str = ""          # pasted lines, "caller: ..." per line


class AgentCheck(BaseModel):
    url: str
    target: str = "websocket"      # websocket | media_stream (Twilio) | exotel | plivo
    timeout_s: float = 8.0


async def probe_agent(url: str, target: str = "websocket", timeout_s: float = 8.0) -> dict:
    """Open a call to the agent and time its first audio. Nothing is sent but the call setup: no credits, no caller."""
    import time as _t

    from .call.telephony import MediaStreamAgent
    from .call.transport import WebSocketAgent
    if not url.startswith(("ws://", "wss://")):
        return {"ok": False, "stage": "url", "error": "the agent URL must start with ws:// or wss://"}
    stream = {"media_stream": "twilio", "exotel": "exotel", "plivo": "plivo"}.get(target)
    agent = MediaStreamAgent(url, dialect=stream) if stream else WebSocketAgent(url, 16000)
    t0 = _t.perf_counter()
    try:
        await asyncio.wait_for(agent.start("connection-check", {}), timeout_s)
    except Exception as e:
        return {"ok": False, "stage": "connect", "error": f"{type(e).__name__}: {e}"[:300]}
    connected = _t.perf_counter() - t0
    first, events = None, 0

    async def listen():
        nonlocal first, events
        async for ev in agent.events():
            events += 1
            if ev.kind == "audio" and ev.audio:
                first = _t.perf_counter() - t0
                return
            if ev.kind == "hangup":
                return
    try:
        await asyncio.wait_for(listen(), timeout_s)
    except asyncio.TimeoutError:
        pass
    finally:
        try:
            await agent.close()
        except Exception:
            pass
    return {"ok": True, "connect_ms": round(connected * 1000), "first_audio_ms": round(first * 1000) if first else None,
            "note": ("the agent greeted first" if first else
                     f"connected, but the agent did not speak within {timeout_s:.0f} s (fine if it waits for the caller)")}


def _try_load(f: Path):
    try:
        return load_suite(f)
    except Exception:
        return None


def _markdown_page(md: str, title: str) -> str:
    """A fix plan or incident report as a readable page: headings, bullets, quotes and code, nothing else."""
    import html
    import re as _re
    out = []
    for line in md.splitlines():
        t = html.escape(line)
        t = _re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = _re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        if t.startswith("# "):
            out.append(f"<h1>{t[2:]}</h1>")
        elif t.startswith("## "):
            out.append(f"<h2>{t[3:]}</h2>")
        elif t.startswith("- "):
            out.append(f"<li>{t[2:]}</li>")
        elif t.startswith("&gt; "):
            out.append(f"<blockquote>{t[5:]}</blockquote>")
        elif t.strip():
            out.append(f"<p>{t}</p>")
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{title}</title>"
            "<style>:root{color-scheme:light dark}body{max-width:860px;margin:40px auto;padding:0 16px;font:15px/1.6 Inter,system-ui,sans-serif}"
            "h1{font-weight:500}h2{margin-top:28px;font-weight:500}code{background:rgba(127,127,127,.15);padding:1px 5px;border-radius:5px}"
            "blockquote{border-left:3px solid #c2410c;margin:6px 0;padding:2px 12px}</style>" + "\n".join(out))


def create_app(suites_dir: str | Path = "suites", runs_dir: str | Path = "runs",
               scorecards_dir: str | Path = "scorecards") -> FastAPI:
    suites_dir, runs_dir, scorecards_dir = Path(suites_dir), Path(runs_dir), Path(scorecards_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Diapason")
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

    @app.get("/theme.css")
    def theme():
        return FileResponse(STATIC / "theme.css", media_type="text/css")

    @app.get("/api/evolution")
    def evolution_matrix():
        """The newest proof that measured more than v1 and v2, as a bugs x versions matrix."""
        from .proof import evolution
        for d in sorted((d for d in runs_dir.iterdir() if (d / "proof.json").exists()),
                        key=lambda d: (d / "proof.json").stat().st_mtime, reverse=True):
            data = json.loads((d / "proof.json").read_text(encoding="utf-8"))
            if data.get("tests", {}).get("bugs"):
                updated = time.strftime("%Y-%m-%d %H:%M", time.localtime((d / "proof.json").stat().st_mtime))
                return {"dir": d.name, "updated": updated, **evolution(data)}
        return None

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
                out.append({k: r.get(k) for k in ("suite", "run_id", "started_at", "calls", "pass_rate", "label",
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
        if req.mode == "reference":
            return start_reference(req, suite)
        if req.mode == "live" and not (req.max_tts_chars and req.max_stt_seconds):
            raise HTTPException(400, "a live run needs a TTS character and an STT seconds budget")
        try:
            c = (live_components(suite, url=req.url, judge=req.judge, target=req.target) if req.mode == "live"
                 else offline_components(suite, req.stubborn))
        except Exception as e:
            raise HTTPException(400, str(e)) from e
        scenarios = suite.expand()[: req.limit] if req.limit else suite.expand()
        state["running"] = suite.name

        async def go():
            try:
                await run_suite(suite, c.connect, c.make_brain, c.speak, c.hear, evon_judge=c.evon_judge,
                                out_dir=runs_dir, scenarios=scenarios, on_event=broadcast, call_kwargs=c.call_kwargs,
                                label=req.label, redact_pii=req.redact, budget=Budget(max_tts_chars=req.max_tts_chars, max_stt_seconds=req.max_stt_seconds))
            except Exception as e:
                broadcast({"type": "suite_error", "error": repr(e)})
            finally:
                state["running"] = None

        asyncio.create_task(go())
        return {"started": suite.name, "calls": len(scenarios) * suite.runs_per_scenario, "mode": req.mode}

    def start_reference(req: RunRequest, suite):
        """One of Diapason's own reference agents under test: scripted (free, instant) or played by Evon (no speech credits)."""
        from dataclasses import replace

        from .demo import run_version
        from .reference_agent import VERSIONS
        base, _, guarded = (req.version or "").partition("+")
        if base not in VERSIONS or guarded not in ("", "guard"):
            raise HTTPException(400, f"version must be one of {sorted(VERSIONS)}, optionally +guard")
        agent = replace(VERSIONS[base], name=f"{base}+guard", guard=True) if guarded else VERSIONS[base]
        evon = None
        if req.evon:
            from .gnani import Evon
            try:
                evon = Evon()
            except Exception as e:
                raise HTTPException(400, f"Evon is not configured: {e}") from e
        if req.limit and suite.cases:
            suite = suite.model_copy(update={"cases": suite.cases[: req.limit], "matrix": None})
        state["running"] = f"{suite.name} · {agent.name}"

        async def go():
            try:
                await run_version(base, suite, runs_dir, broadcast, evon=evon, judge_samples=1, agent=agent,
                                  hear_callers=evon is None, label=f"reference agent {agent.name} ({'Evon' if evon else 'scripted'})")
            except Exception as e:
                broadcast({"type": "suite_error", "error": repr(e)})
            finally:
                state["running"] = None

        asyncio.create_task(go())
        return {"started": suite.name, "agent": agent.name, "mode": "reference", "evon": bool(evon)}

    @app.post("/api/check-agent")
    async def check_agent(req: AgentCheck):
        """Connect to an agent the way a test call would, and wait for it to speak: before any credits are spent."""
        return await probe_agent(req.url, req.target, req.timeout_s)

    jobs: dict[str, dict] = {}

    def job(kind: str, work) -> dict:
        """Run an agent in the background; the page polls /api/jobs/<id>. One of each kind at a time."""
        if any(j["kind"] == kind and j["status"] == "running" for j in jobs.values()):
            raise HTTPException(409, f"a {kind} job is already running")
        jid = f"{kind}-{len(jobs) + 1}"
        jobs[jid] = {"id": jid, "kind": kind, "status": "running", "result": None, "error": None}

        async def go():
            try:
                jobs[jid]["result"] = await work()
                jobs[jid]["status"] = "done"
            except Exception as e:
                jobs[jid].update(status="error", error=f"{type(e).__name__}: {e}"[:400])
        asyncio.create_task(go())
        return jobs[jid]

    @app.get("/api/jobs/{jid}")
    def job_status(jid: str):
        if jid not in jobs:
            raise HTTPException(404)
        return jobs[jid]

    @app.post("/api/fix")
    async def fix_run(req: FixRequest):
        """The fix agent on a past run: lanes, and with a reference agent, fixes proven by re-running the failed calls."""
        from .fixer import agent_for, fix
        run_dir = run_path(req.run)
        name = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["suite"]
        suite = next((s for f in sorted(suites_dir.glob("*.y*ml")) if (s := _try_load(f)) and s.name == name), None)
        if suite is None:
            raise HTTPException(400, f"no suite named {name!r} in {suites_dir}")
        try:
            agent = agent_for(req.agent)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        evon = None
        if agent:
            from .gnani import Evon
            load_dotenv()
            evon = Evon()

        async def work():
            plan = await fix(run_dir, suite, evon, run_dir / "fix", agent=agent, rounds=req.rounds)
            return {"ship": plan.get("ship") or [], "note": plan.get("note"), "lanes": plan["lanes"],
                    "page": f"/runs/{req.run}/fix"}
        return job("fix", work)

    @app.get("/runs/{run_dir}/fix", response_class=HTMLResponse)
    def fix_page(run_dir: str):
        f = run_path(run_dir) / "fix" / "fix-plan.md"
        if not f.exists():
            raise HTTPException(404, "no fix plan for this run yet")
        return _markdown_page(f.read_text(encoding="utf-8"), "Fix plan")

    @app.post("/api/write-suite")
    async def write_suite_job(req: WriteRequest):
        """The suite-writer agent: a caller for every rule in the SOP, saved to suites/ once it loads."""
        import re as _re
        from .gnani import Evon
        from .suitewriter import save, write_suite_for
        name = _re.sub(r"[^a-z0-9-]+", "-", req.name.lower()).strip("-")[:40]
        if not name or not req.sop.strip():
            raise HTTPException(400, "a name and the SOP are needed")
        load_dotenv()
        evon = Evon()
        tmp = runs_dir / "_writer" / f"{name}.txt"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(req.transcripts, encoding="utf-8")

        async def work():
            suite, cov = await asyncio.to_thread(write_suite_for, evon, req.sop, name, [tmp] if req.transcripts.strip() else [])
            save(suite, cov, suites_dir / f"{name}.yaml")
            return {"suite": f"{name}.yaml", "cases": len(suite.cases), "rules": len(cov["rules"]), "uncovered": cov["uncovered"],
                    "untestable": cov["untestable"]}
        return job("write", work)

    @app.get("/api/incidents")
    def incidents_now():
        """The incident agent's grouping of Shield's log, without Evon (instant): counts, quotes, first and last seen."""
        from .incidents import run as run_incidents
        r = run_incidents(runs_dir / "shield", runs_dir / "incidents")
        return r["incidents"]

    @app.get("/api/shield")
    def shield_log():
        """Diapason Shield's verdicts on live calls (diapason shield logs to runs/shield)."""
        from .shield import summarize
        return summarize(runs_dir / "shield")

    @app.get("/api/compare")
    def compare(a: str, b: str):
        """What changed between two runs of a suite: fixed, regressed, still failing, with every failure explained."""
        from .checks import explain, metric_id
        from .diff import diff_reports, load_report
        ra, rb = (load_report(run_path(x)) for x in (a, b))
        if ra.get("suite") != rb.get("suite"):
            raise HTTPException(400, f"different suites: {ra.get('suite')} vs {rb.get('suite')}")
        d = diff_reports(ra, rb).to_dict()

        def why(f: str) -> dict:
            cid = f.split(" (")[0]
            return explain(cid if " " not in cid else metric_id(f), f)
        for c in d["changes"]:
            c["explained"] = [why(f) for f in c["failures_after"]]
        d["criteria_delta"] = [{"id": k, "delta": v, "name": explain(k)["name"]} for k, v in d["criteria_delta"].items()]
        return d

    def run_path(name: str) -> Path:
        p = (runs_dir / name).resolve()
        if p.parent != runs_dir.resolve() or not (p / "report.json").exists():
            raise HTTPException(404, f"no run {name!r}")
        return p

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

    @app.get("/watch", response_class=HTMLResponse)
    def watch(cut: str = "full"):
        """The demo as a film, drawn from the runs on disk right now (?cut=60 for the 60-second cut)."""
        from . import film
        from .site import _latest, _results_json

        def latest(marker):
            d = _latest(runs_dir, marker)
            return json.loads((d / marker).read_text(encoding="utf-8")) if d else None
        reel = film.film(runs_dir, _latest(runs_dir, "proof.json"),
                         lambda src: f"/film-audio/{src.relative_to(runs_dir).as_posix()}",
                         stress=latest("stress.json"), atlas=latest("atlas.json") or _results_json("atlas/atlas.json"),
                         scorecards=scorecards_dir, short=cut == "60")
        return film.page(reel)

    @app.get("/film-audio/{path:path}")
    def film_audio(path: str):
        f = (runs_dir / path).resolve()
        if runs_dir.resolve() not in f.parents or f.suffix != ".wav" or not f.exists():
            raise HTTPException(404)
        return FileResponse(f, media_type="audio/wav")

    @app.get("/studio", response_class=HTMLResponse)
    def studio():
        return (STATIC / "studio.html").read_text(encoding="utf-8")

    @app.get("/api/studio")
    def studio_index():
        """Every scorecard (segments and industry playbooks) and every audit on disk, newest first."""
        from .studio import index
        return index(runs_dir, scorecards_dir)

    @app.get("/api/studio/audit/{path:path}")
    def studio_audit(path: str):
        from .studio import audit
        data = audit(runs_dir, path)
        if data is None:
            raise HTTPException(404)
        return data

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
