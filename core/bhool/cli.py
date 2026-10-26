"""bhool: command line for Bhool Bhulaiya."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from .scenarios import Scenario, Suite, load_suite

app = typer.Typer(add_completion=False, help="Adversarial, telephony-realistic testing for Indian voice agents.")


def _utf8_console() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _select(suite: Suite, limit: int | None, only: str | None) -> list[Scenario]:
    scenarios = suite.expand()
    if only:
        scenarios = [s for s in scenarios if only in s.id]
    return scenarios[:limit] if limit else scenarios


def _printer(verbose: bool):
    def on_event(e: dict) -> None:
        t = e.get("type")
        if t == "verdict":
            mark = "PASS" if e["passed"] else "FAIL"
            extra = "" if e["passed"] else "  <- " + ", ".join(e["failures"])[:160]
            typer.echo(f"  {mark}  {e['scenario']} #{e['run']}{extra}")
        elif t == "call_error":
            typer.echo(f"  ERROR {e['scenario']} #{e['run']}: {e['error']}", err=True)
        elif verbose and t == "turn":
            typer.echo(f"    [{e['scenario']}] {e['speaker']:6} {e['text']}")
    return on_event


def _summary(report) -> None:
    typer.echo(f"\n{report.suite}: {report.pass_rate:.0%} of {report.calls} calls passed; "
               f"p50 {report.latency_p50_s}s p95 {report.latency_p95_s}s")
    typer.echo("GATE PASSED" if report.gate_passed else "GATE FAILED: " + "; ".join(report.gate_reasons))
    typer.echo(f"usage: {json.dumps(report.usage)}")
    typer.echo(f"report: {Path(report.dir) / 'report.html'}")


@app.command()
def validate(suite_path: Path):
    """Check a suite file and list the scenarios it expands to."""
    _utf8_console()
    suite = load_suite(suite_path)
    scenarios = suite.expand()
    typer.echo(f"{suite.name}: {len(scenarios)} scenarios x {suite.runs_per_scenario} runs")
    for s in scenarios:
        typer.echo(f"  {s.id}")


@app.command()
def plan(suite_path: Path, limit: int = typer.Option(None, help="Only the first N scenarios"),
         only: str = typer.Option(None, help="Only scenarios whose id contains this"),
         judge_samples: int = 3):
    """Dry run: estimate API usage before spending any credits."""
    from .runner import estimate_usage
    _utf8_console()
    suite = load_suite(suite_path)
    est = estimate_usage(suite, _select(suite, limit, only), judge_samples=judge_samples)
    for k, v in est.items():
        typer.echo(f"{k:18} {v}")


@app.command()
def run(
    suite_path: Path,
    url: str = typer.Option(None, help="Override the suite's websocket target URL"),
    out: Path = Path("runs"),
    concurrency: int = 4,
    limit: int = typer.Option(None, help="Only the first N scenarios"),
    only: str = typer.Option(None, help="Only scenarios whose id contains this"),
    judge_samples: int = 3,
    no_judge: bool = typer.Option(False, help="Skip the Evon judge (code checks and metrics only)"),
    verbose: bool = False,
):
    """Run a suite against a live agent with Gnani Prisma, Timbre and Evon. Exit code 1 if the gate fails."""
    from .runner import run_suite
    from .wiring import live_components
    _utf8_console()
    suite = load_suite(suite_path)
    try:
        c = live_components(suite, url=url, judge=not no_judge)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    report = asyncio.run(run_suite(
        suite, c.connect, c.make_brain, c.speak, c.hear, evon_judge=c.evon_judge, out_dir=out,
        concurrency=concurrency, scenarios=_select(suite, limit, only), on_event=_printer(verbose),
        judge_samples=judge_samples,
    ))
    typer.echo(f"TTS cache: {c.tts.hits} hits, {c.tts.calls} API calls")
    _summary(report)
    raise typer.Exit(0 if report.gate_passed else 1)


@app.command()
def selftest(
    suite_path: Path = Path("suites/emi_collection.yaml"),
    limit: int = 4,
    out: Path = Path("runs"),
    stubborn: bool = typer.Option(False, help="Use a fake agent that ignores barge-ins, to see failures"),
):
    """Run the whole pipeline against a scripted fake agent. Uses zero API credits."""
    from .runner import run_suite
    from .wiring import offline_components
    _utf8_console()
    suite = load_suite(suite_path)
    c = offline_components(suite, stubborn=stubborn)
    report = asyncio.run(run_suite(
        suite, c.connect, c.make_brain, c.speak, c.hear, evon_judge=None, out_dir=out, concurrency=4,
        scenarios=_select(suite, limit, None), on_event=_printer(False), call_kwargs=c.call_kwargs,
    ))
    _summary(report)


@app.command()
def ingest(
    suite_path: Path,
    recordings: list[Path],
    regressions: Path = typer.Option(Path("suites/regressions.yaml"), help="Regression suite to append failed calls to"),
    lang: str = typer.Option("hi-IN", help="Prisma language code for transcription"),
    caller_channel: int = typer.Option(0, help="Which stereo channel is the customer (0 = left)"),
    judge_samples: int = 3,
):
    """Judge real (dual-channel) call recordings; turn each failed call into a regression test case."""
    from .gnani import Evon, Prisma
    from .judge.rubric import judge_call
    from .regress import append_regressions, distill, estimate_channel, ingest_call
    from .scenarios import Persona
    _utf8_console()
    load_dotenv()
    suite = load_suite(suite_path)
    stt, evon = Prisma(), Evon()
    hear = lambda audio, sr, lg: stt.transcribe_long(audio, sr, lg) if audio.size >= 0.2 * sr else ""  # noqa: E731
    unknown = Persona(id="production", description="a real customer; their true facts are unknown")
    new, passed = [], 0
    for path in recordings:
        rec, caller, sr = ingest_call(path, hear, lang, caller_channel)
        v = judge_call(rec, suite.agent, unknown, suite.gate, evon, samples=judge_samples)
        if v.passed:
            passed += 1
            typer.echo(f"  PASS  {path.name}")
            continue
        typer.echo(f"  FAIL  {path.name}: " + ", ".join([c.id for c in v.criteria if c.verdict in ("fail", "review")] + v.metric_failures))
        persona, behaviour, failure = distill(rec, v, suite, evon)
        new.append((persona, behaviour, estimate_channel(caller, sr, rec.scenario_id), failure, str(path)))
    if new:
        reg = append_regressions(suite, regressions, new)
        typer.echo(f"\n{len(new)} new regression case(s) -> {regressions} ({len(reg.cases)} total). "
                   f"Run them with: bhool run {regressions}")
    typer.echo(f"{passed}/{len(recordings)} production calls passed")


@app.command()
def dashboard(host: str = "127.0.0.1", port: int = 8000, suites: Path = Path("suites"), runs: Path = Path("runs")):
    """Open the live dashboard: start runs, watch every call as it happens, browse reports."""
    import uvicorn
    from .server import create_app
    _utf8_console()
    load_dotenv()
    typer.echo(f"dashboard on http://{host}:{port}")
    uvicorn.run(create_app(suites, runs), host=host, port=port, log_level="warning")


@app.command("serve-agent")
def serve_agent(version: str = typer.Option("v1", help="v1 (seeded bugs) or v2 (fixed)"),
                host: str = "127.0.0.1", port: int = 8765, voice: str = "Kalpana"):
    """Serve the reference EMI-collection agent (Prisma + Evon + Timbre) at ws://host:port."""
    from .gnani import Evon, Prisma, Timbre
    from .reference_agent import VERSIONS, serve
    _utf8_console()
    load_dotenv()
    if version not in VERSIONS:
        raise typer.BadParameter(f"version must be one of {sorted(VERSIONS)}")
    tts, stt, evon = Timbre(), Prisma(), Evon()
    typer.echo(f"reference agent {version} on ws://{host}:{port}")
    asyncio.run(serve(
        version,
        stt=lambda audio, sr, lang: stt.transcribe_long(audio, sr, lang) if audio.size >= 0.2 * sr else "",
        llm=lambda msgs: evon.chat_json(msgs, temperature=0.4, max_tokens=300),
        tts=lambda text, v, lang: tts.synthesize(text, voice=voice, lang=lang),
        host=host, port=port,
    ))


if __name__ == "__main__":
    app()
