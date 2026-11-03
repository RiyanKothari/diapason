"""diapason: command line for Diapason."""

from __future__ import annotations

import asyncio
import json
import sys
import time
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
    label: str = typer.Option("", help="Name this run, e.g. the agent version (used by `diff`)"),
    max_tts_chars: int = typer.Option(None, help="Hard cap: stop before exceeding this many TTS characters"),
    max_stt_seconds: float = typer.Option(None, help="Hard cap on seconds of audio sent to STT"),
    max_evon_calls: int = typer.Option(None, help="Hard cap on Evon requests (caller + judge)"),
    redact: bool = typer.Option(False, help="Mask phone/Aadhaar/PAN/account numbers in stored reports"),
    target: str = typer.Option(None, help="Override the target: websocket | media_stream (Twilio Media Streams) | "
                                          "phone (Diapason dials --number) | inya (an Inya agent calls Diapason's number)"),
    number: str = typer.Option(None, help="phone: the agent's number, E.164"),
    agent_id: str = typer.Option(None, help="inya: the Inya botId (see `diapason inya deploy`)"),
    verbose: bool = False,
):
    """Run a suite against a live agent with Gnani Prisma, Timbre and Evon. Exit code 1 if the gate fails."""
    from .runner import Budget, run_suite
    from .scenarios.schema import Target
    from .wiring import live_components
    _utf8_console()
    load_dotenv()
    suite = load_suite(suite_path)
    if target:
        suite.target = Target(type=target, url=url or suite.target.url, number=number, agent_id=agent_id,
                              sample_rate=8000 if target != "websocket" else suite.target.sample_rate)
    if suite.target.type in ("phone", "inya") and concurrency != 1:
        typer.echo("phone calls run one at a time (one bridge, calls matched in order)")
        concurrency = 1
    try:
        c = live_components(suite, url=url, judge=not no_judge)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    report = asyncio.run(run_suite(
        suite, c.connect, c.make_brain, c.speak, c.hear, evon_judge=c.evon_judge, out_dir=out,
        concurrency=concurrency, scenarios=_select(suite, limit, only), on_event=_printer(verbose),
        judge_samples=judge_samples, label=label, redact_pii=redact,
        budget=Budget(max_tts_chars, max_stt_seconds, max_evon_calls),
    ))
    typer.echo(f"TTS cache: {c.tts.hits} hits, {c.tts.calls} API calls")
    _summary(report)
    if suite.target.type == "inya":
        _inya_crosscheck(c.connect, report)
    raise typer.Exit(0 if report.gate_passed else 1)


def _inya_crosscheck(connector, report) -> None:
    """After an Inya run: fetch Inya's own log of each call and score each side's ears against the other's words."""
    from .inya import crosscheck
    out = []
    by_scenario = {c["scenario_id"]: c for c in report.calls_detail}
    for sid, conn in connector.calls:
        rec = by_scenario.get(sid)
        ref = conn.meta.get("clientReferenceId", "")
        if rec is None:
            continue
        log = connector.inya.find_call(connector.suite.target.agent_id, ref, since=time.time() - 3600) if ref else None
        if not log:
            typer.echo(f"  {sid}: Inya has not logged the call yet ({ref})")
            continue
        x = crosscheck(rec["turns"], log.get("transcript", []))
        out.append({"scenario": sid, "conversationId": log.get("conversationId"), **x})
        typer.echo(f"  {sid}: agent's ears CER {x['caller_to_agent']['cer']}, Diapason's ears CER {x['agent_to_caller']['cer']}")
    if out:
        path = Path(report.dir or "runs") / "inya-crosscheck.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        typer.echo(f"cross-check: {path}")


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
    from .judge.packs import get_pack
    from .judge.rubric import judge_call
    from .regress import append_regressions, distill, ingest_call
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
        v = judge_call(rec, suite.agent, unknown, suite.gate, evon, criteria=get_pack(suite.rubric), samples=judge_samples)
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
                   f"Run them with: diapason run {regressions}")
    typer.echo(f"{passed}/{len(recordings)} production calls passed")


@app.command()
def demo(suite_path: Path = Path("suites/demo.yaml"), out: Path = Path("runs"),
         live: bool = typer.Option(False, help="Real Timbre voices + Prisma STT on both sides (scripted brains, no Evon)"),
         only: str = typer.Option(None, help="Only scenarios whose id contains this"),
         max_tts_chars: int = typer.Option(3000, help="Hard cap per version in --live mode"),
         max_stt_seconds: float = typer.Option(600, help="Hard cap per version in --live mode"),
         verbose: bool = False):
    """Showcase: reference agent v1 (seeded bugs) vs v2 (fixed) through the full harness, then a diff."""
    from .demo import run_demo
    from .runner import Budget
    _utf8_console()
    typer.echo("Testing reference agent v1 (seeded bugs), then v2, through the full harness. "
               + ("LIVE Gnani speech: spends credits within the caps.\n" if live else "No API credits.\n"))
    budget = Budget(max_tts_chars=max_tts_chars, max_stt_seconds=max_stt_seconds) if live else None
    v1, v2, d, md = asyncio.run(run_demo(suite_path, out, on_event=_printer(verbose), live=live, only=only, budget=budget))
    typer.echo("")
    for r in (v1, v2):
        typer.echo(f"{r.label}: {r.pass_rate:.0%} pass, p95 {r.latency_p95_s}s, "
                   f"{'GATE PASSED' if r.gate_passed else 'GATE FAILED'}  -> {Path(r.dir) / 'report.html'}")
    typer.echo("\n" + md)


@app.command()
def load(suite_path: Path, levels: str = "1,4,8,16", url: str = typer.Option(None),
         offline: bool = typer.Option(False, help="Against in-process reference agent v2 with offline models (no credits)"),
         no_judge: bool = True, out: Path = Path("runs/load"), label: str = "",
         only: str = typer.Option(None, help="Scenario to load with (id substring); default: the first"),
         mix: bool = typer.Option(False, help="Cycle all scenarios instead of repeating one (confounds the curve)")):
    """Latency and pass rate as simultaneous calls rise. The knee is the agent's real capacity."""
    from .load import run_load, write_load_report
    _utf8_console()
    suite = load_suite(suite_path)
    lv = [int(x) for x in levels.split(",")]
    picked = _select(suite, None, only)
    if not picked:
        raise typer.BadParameter(f"no scenario matches {only!r}")

    async def go():
        if not offline:
            from .wiring import live_components
            return await run_load(suite, lv, live_components(suite, url=url, judge=not no_judge), out,
                                  scenarios=picked, label=label, mix=mix)
        import socket
        from .demo import AGENT_SCRIPTS, CALLER_LINES
        from .fakes import ScriptedBrain, ToneCodec, fake_speak, scripted_agent_llm
        from .reference_agent import serve
        from .call.transport import WebSocketAgent
        from .wiring import Components
        codec = ToneCodec()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        ready = asyncio.Event()
        server = asyncio.create_task(serve("v2", stt=lambda a, sr, lg: "हाँ" if a.size else "",
                                           llm=scripted_agent_llm(AGENT_SCRIPTS["v2"]),
                                           tts=lambda t, v, lg: codec.encode(t), port=port, ready=ready))
        await ready.wait()
        try:
            c = Components(connect=lambda s: WebSocketAgent(f"ws://127.0.0.1:{port}", suite.target.sample_rate),
                           make_brain=lambda s, r: ScriptedBrain(CALLER_LINES), speak=fake_speak(),
                           hear=lambda a, sr, lg: codec.decode(a, sr), evon_judge=None,
                           call_kwargs={"max_duration_s": 60, "agent_silent_timeout_s": 8})
            return await run_load(suite, lv, c, out, scenarios=picked, label=label or "reference v2 (offline)", mix=mix)
        finally:
            server.cancel()
            await asyncio.gather(server, return_exceptions=True)

    res = asyncio.run(go())
    for p in res["points"]:
        typer.echo(f"  x{p['concurrency']:<4} pass {p['pass_rate']:.0%}  p50 {p['latency_p50_s']}s  p95 {p['latency_p95_s']}s  errors {p['errors']}")
    typer.echo(f"report: {write_load_report(res, out)}")


@app.command("asr-bench")
def asr_bench(presets: str = typer.Option(None, help="Comma-separated presets (default: all)"),
              langs: str = typer.Option(None, help="Comma-separated tts langs to include, e.g. hi-en,gu-IN"),
              seeds: int = 1, out: Path = Path("runs/asr-bench")):
    """Prisma accuracy (CER) per language x phone-line preset, on Timbre speech with known text."""
    from .bench import SENTENCES, run_bench, write_bench_report
    from .gnani import Prisma, Timbre
    _utf8_console()
    load_dotenv()
    tts, stt = Timbre(), Prisma()
    sents = [s for s in SENTENCES if not langs or s.tts_lang in langs.split(",")]
    res = run_bench(
        speak=lambda text, voice, lang: tts.synthesize(text, voice=voice, lang=lang),
        transcribe=lambda audio, sr, lang: stt.transcribe(audio, sr, lang)["transcript"],
        presets=presets.split(",") if presets else None, sentences=sents, seeds=seeds,
        on_row=lambda r: typer.echo(f"  {r['lang']:6} {r['preset']:12} CER {r['cer']:6.1%}  details {r['entity_hits']}/{r['entities']}"
                                    + (f" lost {r['entities_lost']}" if r['entities_lost'] else "") + f"  | {r['hyp']}"),
    )
    path = write_bench_report(res, out)
    typer.echo("\nCER:          " + "  ".join(f"{p}: {c:.1%}" for p, c in res["by_preset"].items()))
    typer.echo("details kept: " + "  ".join(f"{p}: {c:.0%}" for p, c in res["entities_by_preset"].items() if c is not None))
    typer.echo(f"report: {path}   (TTS API calls {tts.calls}, cache hits {tts.hits})")


@app.command()
def atlas(seeds: int = 2, langs: str = typer.Option(None, help="Comma-separated: hi,gu,en (default: all)"),
          workers: int = typer.Option(1, help="Prisma allows one active request per key"), out: Path = Path("runs/atlas"),
          rescore: bool = typer.Option(False, help="Re-read the saved transcripts in --out with the current readers (no credits)")):
    """Which IDs, amounts and dates survive an Indian phone line (Timbre -> noise x SNR -> Prisma), and how to say them."""
    from .atlas import ITEMS, rescore as rescore_atlas, run_atlas, write_atlas_report
    from .gnani import Prisma, Timbre
    _utf8_console()
    if rescore:
        res = rescore_atlas(json.loads((out / "atlas.json").read_text(encoding="utf-8")))
        write_atlas_report(res, out)
        for k, p in sorted(res["policy"].items()):
            typer.echo(f"  {k:12} say it as {p['style']:22} read back below {p['read_back_below_snr']} dB")
        typer.echo(f"rescored {res['requests']} transcripts: reader fixes {res['reader_fixes']}, reader losses {res['reader_losses']}")
        return
    load_dotenv()
    tts, stt = Timbre(), Prisma()
    items = [i for i in ITEMS if not langs or i.lang in langs.split(",")]
    done = [0]

    def tick(r):
        done[0] += 1
        if done[0] % 100 == 0 or "error" in r:
            typer.echo(f"  {done[0]} requests" + (f"  error: {r['error']}" if "error" in r else ""))

    res = run_atlas(
        speak=lambda text, voice, lang: tts.synthesize(text, voice=voice, lang=lang),
        transcribe=lambda audio, sr, lang: stt.transcribe(audio, sr, lang)["transcript"],
        items=items, seeds=seeds, workers=workers, on_row=tick,
    )
    path = write_atlas_report(res, out)
    for k, p in sorted(res["policy"].items()):
        typer.echo(f"  {k:12} say it as {p['style']:22} read back below {p['read_back_below_snr']} dB")
    typer.echo(f"report: {path}   ({res['requests']} STT requests, {res['stt_seconds'] / 60:.1f} min audio, "
               f"{res['errors']} errors; TTS API calls {tts.calls}, {tts.chars} chars, cache hits {tts.hits})")


@app.command()
def rejudge(run_dir: Path, suite_path: Path, with_evon: bool = typer.Option(False, help="Also re-run the Evon rubric judge")):
    """Re-score a saved run with the current judge, from its recordings. Zero speech credits."""
    from .runner import rejudge_run
    _utf8_console()
    load_dotenv()
    evon = None
    if with_evon:
        from .gnani import Evon
        evon = Evon()
    r = rejudge_run(run_dir, load_suite(suite_path), evon)
    for v in r.verdicts:
        fails = [c["id"] for c in v["criteria"] if c["verdict"] in ("fail", "review")] + v["metric_failures"]
        typer.echo(f"  {'PASS' if v['passed'] else 'FAIL'}  {v['scenario_id']} #{v['run']}" + (f"  <- {', '.join(fails)}" if fails else ""))
    _summary(r)


@app.command()
def diff(before: Path, after: Path, out: Path = typer.Option(None, help="Write the Markdown summary here")):
    """Compare two runs (dirs or report.json): what got fixed, what regressed. Exit 1 on any regression."""
    from .diff import diff_reports, load_report, to_markdown
    _utf8_console()
    d = diff_reports(load_report(before), load_report(after))
    md = to_markdown(d)
    typer.echo(md)
    if out:
        out.write_text(md, encoding="utf-8")
    raise typer.Exit(1 if d.regressions else 0)


@app.command()
def generate(sop: Path, name: str, out: Path = typer.Option(None, help="Default: suites/<name>.yaml"),
             url: str = "ws://127.0.0.1:8765", personas: int = 6, sample: int = 24):
    """Draft a complete test suite from an SOP text file with Evon (one Evon call)."""
    from .gnani import Evon
    from .generate import generate_suite, write_suite
    _utf8_console()
    load_dotenv()
    suite = generate_suite(Evon(), sop.read_text(encoding="utf-8"), name, url=url, personas=personas, sample=sample)
    path = out or Path("suites") / f"{name}.yaml"
    write_suite(suite, path)
    typer.echo(f"{path}: {len(suite.personas)} personas, {len(suite.behaviours)} behaviours, {len(suite.expand())} scenarios")
    typer.echo("Review it before running: generated suites are a draft, not ground truth.")


@app.command()
def suggest(run_dir: Path, suite_path: Path, out: Path = typer.Option(None)):
    """Ask Evon for concrete fixes, grouped by root cause, for everything that failed in a run."""
    from .advise import suggest_fixes
    from .diff import load_report
    from .gnani import Evon
    _utf8_console()
    load_dotenv()
    md = suggest_fixes(load_report(run_dir), load_suite(suite_path).agent.sop, Evon())
    typer.echo(md)
    (out or Path(run_dir) / "suggested_fixes.md").write_text(md, encoding="utf-8")


@app.command()
def label(run_dirs: list[Path] = typer.Argument(..., help="Run directories whose calls to label (each has report.json)"),
          out: Path = typer.Option(Path("runs/labels.html"), help="The page; open it in a browser, label, download CSV"),
          base: Path = typer.Option(Path("runs"), help="run_dir values in the CSV are relative to this; pass it to calibrate")):
    """A page for labelling calls by hand (judge verdicts hidden), to measure the judge with `diapason calibrate`."""
    from .label import collect, write_page
    calls = collect(run_dirs, base)
    write_page(calls, out)
    typer.echo(f"{len(calls)} calls, {sum(len(c['criteria']) for c in calls)} judgments to label: {out}\n"
               f"then: diapason calibrate {base} labels.csv")


@app.command()
def calibrate(run_dir: Path, labels: Path):
    """Agreement and Cohen's kappa between human labels (CSV) and the judge, per criterion. For a CSV from
    `diapason label` (it has a run_dir column), RUN_DIR is the base those run_dir paths are relative to (e.g. runs)."""
    from .advise import calibrate as calib
    from .diff import load_report
    _utf8_console()
    multi = not (Path(run_dir) / "report.json").exists()
    res = calib(None if multi else load_report(run_dir), labels, load=lambda rd: load_report(Path(run_dir) / rd))
    typer.echo(f"{'criterion':22} {'n':>4} {'agree':>6} {'kappa':>6} {'missed':>6} {'false':>6}")
    for k, v in res["criteria"].items():
        typer.echo(f"{k:22} {v['n']:>4} {v['agreement']:>6.0%} {str(v['kappa']):>6} {v['judge_missed_fail']:>6} {v['judge_false_fail']:>6}")
    o = res["overall"]
    typer.echo(f"{'overall':22} {o['n']:>4} {o['agreement'] or 0:>6.0%} {str(o['kappa']):>6}")
    if res["labels_not_in_report"]:
        typer.echo(f"({res['labels_not_in_report']} label rows had no matching verdict)")
    (Path(run_dir) / "calibration.json").write_text(json.dumps(res, indent=2), encoding="utf-8")


@app.command()
def doctor(live: bool = typer.Option(False, help="Also make one tiny real call to each API (~6 TTS chars, ~1 s STT, 1 Evon reply)")):
    """Check the .env setup. Never prints key values."""
    import os
    import time as _t
    _utf8_console()
    env = Path(".env")
    ok = True

    def line(good: bool, what: str, hint: str = "") -> None:
        nonlocal ok
        ok &= good
        typer.echo(f"  {'OK  ' if good else 'FAIL'}  {what}" + (f"   -> {hint}" if hint and not good else ""))

    line(env.exists(), ".env file present", "copy .env.example to .env in the project folder")
    load_dotenv()
    key = os.environ.get("GNANI_API_KEY", "")
    line(bool(key), f"GNANI_API_KEY set ({len(key)} chars)", "paste the key from app.gnani.ai into .env")
    base = os.environ.get("EVON_BASE_URL", "")
    line(base.startswith(("http://", "https://")), f"EVON_BASE_URL looks like a URL ({base or 'empty'})",
         "an OpenAI-compatible base URL ending in /v1 (Gnani-hosted, or your own vLLM)")
    typer.echo(f"  info  EVON_MODEL = {os.environ.get('EVON_MODEL') or '(default) gnani/gnani-evon-v3.3-30B-A3B'}")
    typer.echo(f"  info  EVON_API_KEY {'set' if os.environ.get('EVON_API_KEY') else 'not set (fine for an unauthenticated local vLLM)'}")
    if live and key:
        from .gnani import Evon, Prisma, Timbre
        try:
            t0 = _t.perf_counter()
            audio, sr = Timbre(cache_dir=".cache/doctor").synthesize("नमस्ते जी", voice="Shivani", lang="hi-IN")
            line(audio.size > 0, f"Timbre TTS: {audio.size / sr:.1f}s audio in {(_t.perf_counter() - t0) * 1000:.0f} ms")
            t0 = _t.perf_counter()
            text = Prisma().transcribe(audio, sr, "hi-IN").get("transcript", "")
            line(bool(text.strip()), f"Prisma STT: heard {text!r} in {(_t.perf_counter() - t0) * 1000:.0f} ms")
        except Exception as e:
            line(False, f"Gnani speech APIs: {e}", "check the key, credits, and that the key is for Prisma/Timbre")
        if not base:
            typer.echo("  skip  Evon live check: EVON_BASE_URL not set")
        else:
            try:
                t0 = _t.perf_counter()
                reply = Evon().chat([{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=5, temperature=0)
                line(bool(reply.strip()), f"Evon: replied {reply.strip()[:30]!r} in {(_t.perf_counter() - t0) * 1000:.0f} ms")
            except Exception as e:
                line(False, f"Evon: {e}", "check EVON_BASE_URL / EVON_MODEL / EVON_API_KEY")
    elif live:
        typer.echo("  skip  live checks: GNANI_API_KEY is not set")
    typer.echo("\nready" if ok else "\nnot ready")
    raise typer.Exit(0 if ok else 1)


@app.command()
def schema(out: Path = Path("suite.schema.json")):
    """Write the suite JSON Schema (for editor autocomplete and validation of suite YAML)."""
    from .scenarios import Suite
    out.write_text(json.dumps(Suite.model_json_schema(), indent=2), encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command()
def library():
    """List the built-in adversarial caller behaviours (use_library in a suite)."""
    from .scenarios.library import LIBRARY
    _utf8_console()
    for b in LIBRARY.values():
        typer.echo(f"{b.id:20} {b.instructions}")


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
                host: str = "127.0.0.1", port: int = 8765, voice: str = "Kalpana",
                guard: bool = typer.Option(False, help="Diapason Guard checks every line before it is spoken"),
                protocol: str = typer.Option("diapason", help="diapason (harness protocol), or a phone platform's media stream "
                                                           "as an agent taking calls speaks it: twilio, exotel or plivo")):
    """Serve the reference EMI-collection agent (Prisma + Evon + Timbre) at ws://host:port."""
    from .gnani import Evon, Prisma, Timbre
    from .guard import evon_translator
    from .reference_agent import VERSIONS, serve
    _utf8_console()
    load_dotenv()
    if version not in VERSIONS:
        raise typer.BadParameter(f"version must be one of {sorted(VERSIONS)}")
    from dataclasses import replace
    tts, stt, evon = Timbre(), Prisma(), Evon()
    agent = replace(VERSIONS[version], name=f"{version}+guard", guard=True) if guard else VERSIONS[version]
    typer.echo(f"reference agent {agent.name} on ws://{host}:{port}")
    asyncio.run(serve(
        agent,
        stt=lambda audio, sr, lang: stt.transcribe_long(audio, sr, lang) if audio.size >= 0.2 * sr else "",
        llm=lambda msgs: evon.chat_json(msgs, temperature=0.4, max_tokens=300),
        tts=lambda text, v, lang: tts.synthesize(text, voice=voice, lang=lang),
        host=host, port=port,
        translate=evon_translator(evon), protocol=protocol,
    ))


def _suite_of(run_dir: Path, suites_dir: Path = Path("suites")):
    """The suite file a run came from (the report records the suite's name, not its path)."""
    name = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["suite"]
    for f in sorted(suites_dir.glob("*.y*ml")):
        try:
            s = load_suite(f)
        except Exception:
            continue
        if s.name == name:
            return s
    raise typer.BadParameter(f"no suite named {name!r} in {suites_dir}; pass --suite")


@app.command()
def fix(run_dir: Path, agent: str = typer.Option(None, help="Reference agent the run tested (v1-v4): needed to prove fixes"),
        suite: Path = typer.Option(None, help="The run's suite file (default: found by name in suites/)"),
        rounds: int = typer.Option(2, help="Prompt patches to try"), judge_samples: int = 3,
        out: Path = typer.Option(None, help="Default: <run_dir>/fix")):
    """The fix agent: sort a run's failures into prompt, guard and engineering lanes, and prove each fix by re-running
    only the failed calls (Evon plays agent, callers and judge: no speech credits)."""
    from .fixer import agent_for, fix as run_fix
    from .gnani import Evon
    _utf8_console()
    load_dotenv()
    s = load_suite(suite) if suite else _suite_of(run_dir)
    evon = Evon() if agent else None
    plan = asyncio.run(run_fix(run_dir, s, evon, out or run_dir / "fix", agent=agent_for(agent), rounds=rounds,
                               judge_samples=judge_samples))
    typer.echo(f"failures by lane: {plan['lanes']}")
    for line in plan.get("ship") or [plan.get("note", "")]:
        typer.echo(f"  - {line}")
    typer.echo(f"plan: {(out or run_dir / 'fix') / 'fix-plan.md'}")


@app.command("write-suite")
def write_suite_cmd(sop: Path, name: str = typer.Option(..., help="Suite name"),
                    transcripts: list[Path] = typer.Option(None, help="Real call transcripts (caller: / customer: lines) to sound like"),
                    url: str = "ws://127.0.0.1:8765", out: Path = typer.Option(None, help="Default: suites/<name>.yaml")):
    """The suite-writer agent: every rule in the SOP gets a caller built to break it; prints what stays uncovered."""
    from .gnani import Evon
    from .suitewriter import save, write_suite_for
    _utf8_console()
    load_dotenv()
    files = [f for t in transcripts or [] for f in ([t] if t.is_file() else sorted(t.glob("*.txt")))]
    suite_, cov = write_suite_for(Evon(), sop.read_text(encoding="utf-8"), name, transcripts=files, url=url)
    path = out or Path("suites") / f"{name}.yaml"
    save(suite_, cov, path)
    typer.echo(f"{len(suite_.cases)} attack cases for {len(cov['rules'])} rules"
               + (f", uncovered: {', '.join(cov['uncovered'])}" if cov["uncovered"] else ", every rule covered")
               + f"\nsuite: {path}\ncoverage: {path.with_suffix('.coverage.md')}")


@app.command()
def incidents(log: Path = typer.Option(Path("runs/shield"), help="Shield's log folder"),
              suite: Path = typer.Option(None, help="Base suite to add the regression cases to"),
              out: Path = typer.Option(Path("runs/incidents")), use_evon: bool = typer.Option(True, help="Let Evon write the summaries")):
    """The incident agent: group Shield's live flags into incidents, write them up, and turn each into a test case."""
    from .incidents import run as run_incidents
    _utf8_console()
    load_dotenv()
    evon = None
    if use_evon:
        from .gnani import Evon
        evon = Evon()
    r = run_incidents(log, out, base=load_suite(suite) if suite else None, evon=evon)
    typer.echo(f"{len(r['incidents'])} incident(s) from {r['calls']} call(s), {r['flagged_lines']} flagged line(s)")
    for x in r["incidents"]:
        typer.echo(f"  [{x['severity']}] {x['title']}: {len(x['calls'])} call(s), {x['lines']} line(s), {x['prevented']} stopped")
    if r.get("regression_suite"):
        typer.echo(f"regression suite: {r['regression_suite']}")
    typer.echo(f"report: {out / 'incidents.md'}")


@app.command()
def shield(agent: str = typer.Option(..., help="The agent's media-stream websocket URL (where the platform used to stream calls)"),
           dialect: str = typer.Option("twilio", help="The platform's stream format: twilio, exotel or plivo"),
           mode: str = typer.Option("monitor", help="monitor: flag, never touch the call. block: hold each agent line until checked"),
           host: str = "127.0.0.1", port: int = 8791,
           crm: Path = typer.Option(None, help="JSON account record, if the platform does not pass it as stream parameters"),
           voice: str = typer.Option(None, help="block mode: speak Guard's corrected line with this Timbre voice instead of silence"),
           lang: str = typer.Option("hi-IN", help="Language Prisma transcribes in"),
           listen_caller: bool = typer.Option(True, help="Also transcribe the caller, so Shield knows when they verified"),
           out: Path = typer.Option(Path("runs/shield"), help="Where every verdict is logged (the dashboard reads it)")):
    """Diapason Shield: put a compliance monitor in front of any voice agent's phone line, with no change to the agent.

    Point the platform's stream at Shield (ws://host:port) instead of at the agent. Shield relays the call both ways and
    checks everything the agent says with Guard's rules: threats, secret requests, the recording disclosure, account
    details before verification. Transcription uses Prisma (credits per minute of agent speech, and of caller speech
    with --listen-caller)."""
    import json as _json

    from .audio import float_to_pcm16, resample
    from .gnani import Prisma, Timbre
    from .shield import Shield
    _utf8_console()
    load_dotenv()
    stt = Prisma()
    speak = None
    if voice:
        tts = Timbre()

        def speak(text: str) -> bytes:
            x, sr = tts.synthesize(text, voice=voice, lang=lang)
            return float_to_pcm16(resample(x, sr, 8000))
    record = _json.loads(crm.read_text(encoding="utf-8")) if crm else {}
    s = Shield(agent, hear=lambda x, sr: stt.transcribe_long(x, sr, lang) if x.size >= 0.2 * sr else "",
               dialect_name=dialect, mode=mode, crm=record, speak=speak, listen_caller=listen_caller, log_dir=out,
               on_event=lambda e: typer.echo(f"{e['t']:7.1f}s {e['side']:6} {e['verdict']:8} {e['text'][:90]}"
                                             + (f"  [{', '.join(r['rule'] for r in e['rules'])}]" if e["rules"] else "")))
    typer.echo(f"Diapason Shield ({mode}, {dialect}) on ws://{host}:{port} -> {agent}; log {out}")
    asyncio.run(s.serve(host, port))


@app.command()
def proof(out: Path = typer.Option(None, help="Default: runs/proof-<time>"),
          offline: bool = typer.Option(False, help="Scripted agent and code checks only (judge-only bugs show 'needs Evon')"),
          judge_samples: int = typer.Option(3, min=1, max=7), qa_calls: int = typer.Option(40, min=4),
          qa_seed: int = typer.Option(7, help="QA-Bench corpus seed; use a new one to measure on calls the judge was never tuned on"),
          rescore: Path = typer.Option(None, help="Don't run anything: re-apply today's code checks to this finished proof's saved calls"),
          rerun_guard: Path = typer.Option(None, help="Re-run only the v1 + Guard calls of this finished proof, then rescore"),
          add_v3: Path = typer.Option(None, help="Run v3 (secrets isolated) on this finished proof's cases, then rescore"),
          add_v3_guard: Path = typer.Option(None, help="Run v3 behind Guard on this finished proof's cases, then rescore"),
          add_v4: Path = typer.Option(None, help="Run v4 (model picks acts, code speaks facts, Guard on) on this finished proof's cases, then rescore"),
          verbose: bool = False):
    """Measure accuracy: planted bugs caught by the tests (v1 vs fixed v2) and QA-Bench. No Gnani speech credits."""
    import time
    from .proof import run_proof
    _utf8_console()
    load_dotenv()
    if rescore or rerun_guard or add_v3 or add_v3_guard or add_v4:
        from .proof import rescore as do_rescore
        if rerun_guard or add_v3 or add_v3_guard or add_v4:
            from .gnani import Evon
            from .proof import rerun_guard as do_rerun
            rescore = rerun_guard or add_v3 or add_v3_guard or add_v4
            which = "v4" if add_v4 else "v3guard" if add_v3_guard else "v3" if add_v3 else "guard"
            data = asyncio.run(do_rerun(rescore, Evon(), judge_samples, _printer(verbose), which=which))
        else:
            data = do_rescore(rescore)
        t = data["tests"]
        typer.echo(f"rescored {rescore}: planted bugs caught {t['caught']}/{t['measured']} · also flagged on v2: {t['false_alarms']}")
        for b in t["bugs"]:
            typer.echo(f"  {b['status']:22} {b['what']}")
        g = t.get("guard") or {}
        if g.get("measured"):
            typer.echo(f"GUARD  {g['prevented']}/{g['measured']} text bugs prevented" + (f" ({g['disputed']} still-flagged disputed by cross-examination)" if g.get("disputed") else ""))
        for k, name in (("v3", "V3     "), ("v3guard", "V3+G   "), ("v4", "V4     ")):
            if (t.get(k) or {}).get("measured"):
                typer.echo(f"{name}{t[k]['prevented']}/{t[k]['measured']} text bugs gone" + (f" ({t[k]['disputed']} still-flagged disputed by cross-examination)" if t[k].get("disputed") else ""))
        return
    evon = None
    if not offline:
        from .gnani import Evon
        evon = Evon()
        evon.chat([{"role": "user", "content": "Reply with the word ready."}], max_tokens=5)   # fail fast if Evon is down
    out = out or Path("runs") / f"proof-{time.strftime('%Y%m%d-%H%M%S')}"
    typer.echo(f"Proof run ({'offline' if offline else 'Evon plays agent, callers and judge'}); no Gnani speech credits.\n")
    data = asyncio.run(run_proof(out, evon, judge_samples, qa_calls, on_event=_printer(verbose), qa_seed=qa_seed))
    t, q = data["tests"], data["qa"]
    typer.echo(f"\nTESTS  planted bugs caught {t['caught']}/{t['measured']} · also flagged on v2 (see quotes): {t['false_alarms']} · "
               f"pass rate v1 {t['v1_pass_rate']:.0%} -> v2 {t['v2_pass_rate']:.0%}")
    for b in t["bugs"]:
        typer.echo(f"  {b['status']:22} {b['what']}")
    g = t.get("guard") or {}
    if g.get("measured"):
        typer.echo(f"GUARD  v1 unchanged + Diapason Guard: {g['prevented']}/{g['measured']} text bugs prevented · "
                   f"{g['interventions']} line(s) rewritten · pass rate {g['pass_rate']:.0%}")
    o = q.get("overall") or {}
    pct = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
    typer.echo(f"QA     verdict accuracy {pct(o.get('accuracy'))} · fail precision {pct(o.get('fail_precision'))} · "
               f"fail recall {pct(o.get('fail_recall'))} · fatal recall {pct(q['fatal_recall'])} · decisions right {pct(q['decision_accuracy'])}")
    typer.echo(f"\nreport: {out / 'proof.html'}")


@app.command()
def autopilot(agent: str = typer.Option("v2", help="Reference agent to attack: v1 (seeded bugs) or v2 (fixed)"),
              suite: Path = typer.Option(Path("suites/proof.yaml"), help="Agent SOP, account and base cases"),
              generations: int = typer.Option(3, min=1, max=8), population: int = typer.Option(4, min=1, max=12),
              heal_rounds: int = typer.Option(2, min=0, max=5), judge_samples: int = typer.Option(3, min=1, max=7),
              out: Path = typer.Option(None, help="Default: runs/autopilot-<time>"), verbose: bool = False,
              resume: Path = typer.Option(None, help="Skip the hunt: heal a finished hunt in this directory"),
              replay: Path = typer.Option(None, help="Replay this finished hunt's attacks on --agent (e.g. the fix) and compare leaks")):
    """Evon red-teams the agent (finds bugs nobody planted), then patches its prompt and keeps only verified fixes."""
    import time
    from .autopilot import run_autopilot
    from .gnani import Evon
    _utf8_console()
    load_dotenv()
    evon = Evon()
    evon.chat([{"role": "user", "content": "Reply with the word ready."}], max_tokens=5)   # fail fast if Evon is down
    out = resume or out or Path("runs") / f"autopilot-{time.strftime('%Y%m%d-%H%M%S')}"
    printer = _printer(verbose)
    if replay:
        from .autopilot import replay as do_replay
        s = asyncio.run(do_replay(replay, evon, agent, judge_samples, printer))
        typer.echo(f"\nLEAKS  {s['attacked']}: {s['before']['leaked']}/{s['before']['calls']} attacks leaked the account · "
                   f"{agent}: {s['after']['leaked']}/{s['after']['calls']}\nreport: {replay / 'autopilot.html'}")
        return

    def on_event(e: dict) -> None:
        if e.get("type") == "hunt_generation":
            if e.get("discarded"):
                typer.echo(f"\nHUNT   generation {e['generation']}: Evon failed {e['discarded']} time(s) mid-run; results discarded, hunt stopped\n")
            else:
                typer.echo(f"\nHUNT   generation {e['generation']}: {e['broke']}/{e['tried']} attacks broke the agent\n")
        elif e.get("type") == "heal_round":
            typer.echo(f"\nHEAL   round {e['round']}: {'kept' if e['accepted'] else 'rejected'} "
                       f"(fixed {e['fixed']}, broke {e['broken']})\n")
        else:
            printer(e)

    typer.echo(f"Autopilot on reference agent {agent}: Evon is red team, callers, agent and judge; no Gnani speech credits.\n")
    r = asyncio.run(run_autopilot(out, evon, agent, str(suite), generations, population, heal_rounds if heal_rounds else 0,
                                  judge_samples, do_heal=heal_rounds > 0, on_event=on_event, resume=bool(resume)))
    counted = [a for a in r["attacks"] if not a.get("discarded")]
    typer.echo(f"\nFOUND  {sum(bool(a['broke']) for a in counted)}/{len(counted)} attacks broke {agent}; "
               f"failure types: {', '.join(f'{k} ({len(v)})' for k, v in r['found'].items()) or 'none'}")
    h = r["heal"]
    if h and h.get("error"):
        typer.echo(f"HEAL   not done: {h['error']}")
    elif h:
        typer.echo(f"HEALED pass rate {h['before_pass_rate']:.0%} -> {h['after_pass_rate']:.0%} · fixed {len(h['fixed'])} · "
                   f"regressions {len(h['broken'])} · still failing {len(h['still'])}")
    typer.echo(f"\nreport: {out / 'autopilot.html'}")


@app.command()
def site(out: Path = typer.Option(Path("site"), help="Output folder (deploy it to any static host)"),
         proof: Path = typer.Option(None, help="Proof run to show (default: the latest)"),
         repo_url: str = typer.Option("", help="Link to the source repository")):
    """A static showcase: landing page of measured numbers, the accuracy proof, and the QA Studio with its data baked in."""
    from .site import build_site
    _utf8_console()
    r = build_site(out, proof=proof, repo_url=repo_url)
    typer.echo(f"site: {r['out']} · {r['audits']} audits · {r['voiced_calls']} voiced calls · proof {r['proof']} · "
               f"simulations {', '.join(r['simulations']) or 'none'} · autopilot {r['autopilot'] or 'none'} · {r['megabytes']} MB")
    typer.echo(f"preview: python -m http.server -d {out} 8080   then open http://127.0.0.1:8080")


@app.command()
def stress(agent: list[str] = typer.Option(["v1", "v2"], help="Reference agent versions to sweep"),
           noise: list[str] = typer.Option(None, help="Noise types (default: fan, traffic, office, crowd)"),
           runs: int = typer.Option(2, min=1, max=5, help="Calls per level; a level holds only if every call was heard"),
           evon: bool = typer.Option(False, help="Evon plays agent and caller (default: scripted; the ears are the agent's own code)"),
           out: Path = typer.Option(None, help="Default: runs/stress-<time>"), verbose: bool = False):
    """Noise breaking point: step the line's SNR from 30 dB to 0 dB per noise type and find where the agent stops hearing."""
    import time
    from .stress import NOISES, run_stress
    _utf8_console()
    load_dotenv()
    ev = None
    if evon:
        from .gnani import Evon
        ev = Evon()
    out = out or Path("runs") / f"stress-{time.strftime('%Y%m%d-%H%M%S')}"
    d = asyncio.run(run_stress(out, agent, ev, noise or NOISES, runs=runs, on_event=_printer(verbose)))
    for v, r in d["versions"].items():
        typer.echo(f"{v:6} " + " · ".join(f"{n}: " + (f"holds to {p['holds_to']} dB" if p["breaks_at"] is None else f"breaks at {p['breaks_at']} dB")
                                          for n, p in r["points"].items()))
    typer.echo(f"report: {out / 'stress.html'}")


@app.command()
def rating(proof: Path = typer.Argument(..., help="A proof run directory (has proof.json)"),
           stress_dir: Path = typer.Option(None, "--stress", help="A noise-sweep run directory (has stress.json)"),
           out: Path = typer.Option(None, help="Default: <proof>/rating")):
    """Crash-test rating: five measured axes and an overall star rating per agent, plus shareable SVG badges."""
    from .rating import build_rating
    _utf8_console()
    d = build_rating(proof, stress_dir / "stress.json" if stress_dir else None, out or proof / "rating")
    for name, r in d["ratings"].items():
        typer.echo(f"{name:9} {'★' * r['overall']}{'☆' * (5 - r['overall'])}  " +
                   " · ".join(f"{k} {v['stars'] if v['stars'] is not None else '-'}" for k, v in r["axes"].items()))
    typer.echo(f"report: {(out or proof / 'rating') / 'rating.html'}")


pb_app = typer.Typer(add_completion=False, help="Industry playbooks: a tailored QA scorecard and test suite per vertical.")
app.add_typer(pb_app, name="playbooks")


@pb_app.command("list")
def playbooks_list(path: Path = Path("playbooks/industries.yaml")):
    """Every industry playbook: use case, languages, regulations, checks and fatal rules."""
    from .playbooks import load_playbooks, summary
    _utf8_console()
    for b in load_playbooks(path):
        s = summary(b)
        typer.echo(f"{s['title'][:46]:46} {s['brand'][:24]:24} {','.join(s['languages']):24} "
                   f"{s['checks']:>2} checks · {s['fatal']} fatal · {s['scenarios']} test calls")


@pb_app.command("build")
def playbooks_build(path: Path = Path("playbooks/industries.yaml"), scorecards: Path = Path("scorecards/industries"),
                    suites: Path = Path("suites/industries")):
    """Write scorecards/industries/<id>.yaml (QA form) and suites/industries/<id>.yaml (adversarial test suite) per industry."""
    from .playbooks import load_playbooks, write_all
    _utf8_console()
    books = load_playbooks(path)
    for sc, su in write_all(books, scorecards, suites):
        typer.echo(f"  {sc}  {su}")
    typer.echo(f"{len(books)} industry playbooks built. Audit with: diapason qa simulate {scorecards}/<id>.yaml")


inya_app = typer.Typer(add_completion=False, help="Agents built on Gnani's Inya platform, tested from the outside.")
app.add_typer(inya_app, name="inya")


@inya_app.command("deploy")
def inya_deploy(suite_path: Path, persona: str = typer.Option(None, help="Whose account record the agent gets (default: first)"),
                bot_id: str = typer.Option(None, help="Update this existing agent instead of creating one")):
    """Build the suite's agent on Inya from its SOP (Create Agent + Update Agent) and print its botId."""
    from .inya import Inya, agent_fields
    _utf8_console()
    load_dotenv()
    suite = load_suite(suite_path)
    p = next((x for x in suite.personas if x.id == persona), suite.personas[0])
    inya = Inya()
    bot_id = bot_id or inya.create_agent(f"diapason-{suite.name}-{p.id}", f"Diapason test agent ({suite.name})")
    inya.update_agent(bot_id, **agent_fields(suite, p))
    typer.echo(f"Inya agent {bot_id} ({p.id}). Next: whitelist Diapason's Twilio number in Inya, then")
    typer.echo(f"  diapason run {suite_path} --target inya --agent-id {bot_id} --only <case>")


@inya_app.command("config")
def inya_config(suite_path: Path, persona: str = typer.Option(None, help="Whose account record the agent gets (default: first)"),
                out: Path = typer.Option(None, help="Also write the fields here as text")):
    """The same agent `deploy` builds, as fields to paste into the Inya dashboard (for workspaces without an API key)."""
    from .inya import agent_fields
    _utf8_console()
    suite = load_suite(suite_path)
    p = next((x for x in suite.personas if x.id == persona), suite.personas[0])
    f = agent_fields(suite, p)
    text = (f"Agent name:\n  diapason-{suite.name}-{p.id}\n\nLanguages:\n  {', '.join(f['botDetails']['language'])}"
            f"  (language switch {'on' if f['languageSwitch'] else 'off'})\n\nGreeting / welcome message:\n  {f['greetingMessage']}"
            f"\n\nSystem prompt (paste all of it):\n{f['systemPrompt']}\n")
    typer.echo(text)
    if out:
        out.write_text(text, encoding="utf-8")


@inya_app.command("logs")
def inya_logs(bot_id: str, limit: int = 10):
    """Inya's own log of recent calls with an agent: who said what, as the platform recorded it."""
    from .inya import Inya
    _utf8_console()
    load_dotenv()
    for c in Inya().logs(bot_id, page_size=limit):
        typer.echo(f"{c.get('conversationId')}  {c.get('name')}  {len(c.get('transcript') or [])} turns")
        for m in (c.get("transcript") or [])[:12]:
            typer.echo(f"   {m.get('role'):9} {m.get('content', '')}")


qa_app = typer.Typer(add_completion=False, help="Quality audits of real calls: evidence-backed scorecards, analytics, coaching.")
app.add_typer(qa_app, name="qa")


def _load_scorecard(path: Path):
    import yaml
    from .qa import Scorecard
    return Scorecard.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@qa_app.command("template")
def qa_template(suite_path: Path = typer.Argument(..., help="A suite whose agent spec (SOP, banned phrases, slots) to use"),
                out: Path = typer.Option(None, help="Default: scorecards/<suite name>.yaml"),
                pack: str = typer.Option(None, help="Rubric pack (default: the suite's)")):
    """Write a ready QA scorecard from a suite's agent spec and a compliance pack; edit weights to taste."""
    import yaml
    from .qa import from_pack
    suite = load_suite(suite_path)
    card = from_pack(pack or suite.rubric, suite.agent, name=f"{suite.agent.name} QA")
    out = out or Path("scorecards") / f"{suite.name}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(card.model_dump(mode="json", exclude_defaults=True), allow_unicode=True, sort_keys=False), encoding="utf-8")
    typer.echo(f"{out}: {len(card.parameters())} parameters in {len(card.sections)} sections")


@qa_app.command("audit")
def qa_audit(
    scorecard: Path,
    inputs: list[Path] = typer.Argument(..., help="Recordings (.wav, dual-channel), transcripts (.json/.jsonl/.csv/.txt), run dirs"),
    out: Path = typer.Option(None, help="Default: runs/qa-<scorecard>-<time>"),
    offline: bool = typer.Option(False, help="Code checks and measurements only: no Evon, no STT, zero cost"),
    judge_samples: int = typer.Option(3, min=1, max=7),
    concurrency: int = typer.Option(4, min=1),
    labels: Path = typer.Option(None, help="Human QA labels CSV (call_id, parameter, verdict) to measure agreement"),
    baseline: Path = typer.Option(None, help="A previous qa.json to report drift against"),
    max_stt_seconds: float = typer.Option(None, help="Hard cap on audio sent to Prisma"),
    max_evon_calls: int = typer.Option(None, help="Hard cap on Evon requests"),
    redact: bool = typer.Option(True, help="Mask phone/Aadhaar/PAN/account numbers in stored outputs (DPDP)"),
    to_regressions: Path = typer.Option(None, help="Turn fatal-error calls into test cases in this regression suite"),
    suite_path: Path = typer.Option(None, "--suite", help="Base suite for --to-regressions"),
):
    """Audit real calls against a scorecard: per-call scores with quoted evidence, analytics, coaching, review queue."""
    import time
    from .qa import aggregate, calibrate, drift, load, run_batch, write_outputs
    from .runner import Budget, Usage
    _utf8_console()
    load_dotenv()
    card = _load_scorecard(scorecard)
    usage = Usage(Budget(max_stt_seconds=max_stt_seconds, max_evon_calls=max_evon_calls))
    hear = evon = None
    if not offline:
        from .gnani import Evon, Prisma
        if any(p.suffix.lower() == ".wav" or p.is_dir() for p in inputs):
            stt = Prisma()
            hear = usage.wrap_hear(lambda audio, sr, lg: stt.transcribe_long(audio, sr, lg) if audio.size >= 0.2 * sr else "")
        evon = usage.wrap_evon(Evon())
    convs = load(inputs, hear, card.language, card.caller_channel)
    typer.echo(f"Auditing {len(convs)} call(s) against '{card.name}' ({len(card.parameters())} parameters)"
               + (" offline: Evon parameters skipped." if offline else f", {judge_samples} Evon samples each."))

    def show(r):
        s = "ERROR" if r.error else ("PASS " if r.passed else "FAIL ")
        why = r.error or ", ".join(r.fatal and [f"fatal: {f}" for f in r.fatal] or [p.id for p in r.params if p.verdict == "fail"])
        typer.echo(f"  {s} {r.score if r.score is not None else '—':>5}  {r.call_id}" + (f"  <- {why}"[:150] if why else "")
                   + ("  [review]" if r.review else ""))
    results = run_batch(convs, card, evon, judge_samples, concurrency, on_result=show)
    summary = aggregate(results, card)
    if labels:
        summary["calibration"] = calibrate(results, labels)
    if baseline:
        summary["drift"] = drift(summary, json.loads(baseline.read_text(encoding="utf-8"))["summary"])
    out = out or Path("runs") / f"qa-{scorecard.stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    write_outputs(results, summary, card, out, usage.to_dict(), redact_pii=redact)
    typer.echo(f"\n{summary['audited']}/{summary['calls']} audited · avg score {summary['avg_score']} · pass {summary['pass_rate']} · "
               f"fatal {summary['fatal_rate']} · {len(summary['review_queue'])} for human review")
    if summary.get("calibration", {}).get("overall"):
        o = summary["calibration"]["overall"]
        typer.echo(f"agreement with human QA: {o['agreement']:.0%} (kappa {o['kappa']}) on {o['n']} labels")
    typer.echo(f"usage: {json.dumps(usage.to_dict())}\nreport: {out / 'qa.html'}  (also qa.json, calls.csv)")
    if to_regressions:
        if not suite_path or offline:
            raise typer.BadParameter("--to-regressions needs --suite and Evon (not --offline)")
        from .judge.rubric import CallVerdict, CriterionResult
        from .regress import append_regressions, distill
        suite, items = load_suite(suite_path), []
        for r, c in zip(results, convs):
            if not r.fatal:
                continue
            v = CallVerdict(r.call_id, 0, False, [CriterionResult(p.id, p.verdict, p.fatal, p.agreement, p.reason, p.evidence)
                                                  for p in r.params if p.verdict in ("fail", "review")], [])
            persona, behaviour, failure = distill(c.record, v, suite, evon)
            from .channel import ChannelProfile
            channel = ChannelProfile(id=f"prod_{r.call_id}", noise="none", snr_db=30.0)
            items.append((persona, behaviour, channel, failure, str(c.meta.get("source", r.call_id))))
        if items:
            reg = append_regressions(suite, to_regressions, items)
            typer.echo(f"{len(items)} fatal call(s) -> test cases in {to_regressions} ({len(reg.cases)} total)")


@qa_app.command("bench")
def qa_bench(scorecard: Path = Path("scorecards/emi_collections.yaml"),
             n: int = typer.Option(40, min=4, help="Calls in the labelled corpus"), seed: int = 7,
             offline: bool = typer.Option(False, help="Code checks only (Evon parameters skipped)"),
             judge_samples: int = typer.Option(3, min=1, max=7), concurrency: int = 4,
             max_evon_calls: int = typer.Option(None), out: Path = Path("runs/qa-bench")):
    """Measure the auditor's accuracy on calls whose correct verdicts are known by construction."""
    from .qa import aggregate, write_outputs
    from .qa.bench import run_bench
    from .runner import Budget, Usage
    _utf8_console()
    load_dotenv()
    card = _load_scorecard(scorecard)
    usage = Usage(Budget(max_evon_calls=max_evon_calls))
    evon = None
    if not offline:
        from .gnani import Evon
        evon = usage.wrap_evon(Evon())
    calls, truth, results, ev = run_bench(card, evon, n, seed, judge_samples, concurrency)
    out.mkdir(parents=True, exist_ok=True)
    (out / "corpus.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in calls), encoding="utf-8")
    (out / "bench.json").write_text(json.dumps({"evaluation": ev, "truth": truth, "usage": usage.to_dict()}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_outputs(results, aggregate(results, card), card, out, usage.to_dict(), redact_pii=False)
    typer.echo(f"QA-Bench: {ev['calls']} calls · {'offline (code checks only)' if offline else f'Evon x{judge_samples}'}\n")
    typer.echo(f"{'parameter':26} {'type':14} {'n':>3} {'acc':>6} {'fail P':>7} {'fail R':>7} {'review':>6}")
    pct = lambda x: "  —" if x is None else f"{x:.0%}"  # noqa: E731
    for pid, s in ev["parameters"].items():
        typer.echo(f"{pid:26} {s['type']:14} {s['n']:>3} {pct(s['accuracy']):>6} {pct(s['fail_precision']):>7} {pct(s['fail_recall']):>7} {s['to_review']:>6}")
    o = ev["overall"]
    if o:
        typer.echo(f"\noverall verdict accuracy {pct(o['accuracy'])} · fail precision {pct(o['fail_precision'])} · fail recall {pct(o['fail_recall'])}")
    typer.echo(f"pass/fail decision accuracy {pct(ev['decision_accuracy'])} · fatal-error recall {pct(ev['fatal_recall'])} · "
               f"fatal false alarms {ev['fatal_false_alarms']} · score MAE {ev['score_mae']}")
    typer.echo(f"usage: {json.dumps(usage.to_dict())}\nreport: {out / 'qa.html'} · {out / 'bench.json'}")


@qa_app.command("compile")
def qa_compile(policy: Path = typer.Argument(..., help="Policy, SOP or regulation text (.txt/.md)"),
               out: Path = typer.Option(None, help="Default: scorecards/<policy name>.yaml"),
               name: str = typer.Option(None, help="Scorecard name")):
    """A policy in, an executable scorecard out: Evon writes the checks, each one traced to the clause it enforces."""
    from .gnani import Evon
    from .qa.compile import compile_policy, write
    _utf8_console()
    load_dotenv()
    text = policy.read_text(encoding="utf-8")
    card, notes = compile_policy(Evon(), text, name)
    out = out or Path("scorecards") / f"{policy.stem}.yaml"
    write(card, out, str(policy))
    ps = card.parameters()
    typer.echo(f"{card.name}: {len(ps)} checks · {sum(p.fatal for p in ps)} fatal · {sum(p.check.type != 'llm' for p in ps)} in code · "
               f"{sum(not p.source.startswith('[') for p in ps if p.check.type != 'metric')} traced to a verified clause")
    for n in notes:
        typer.echo(f"  note: {n}")
    typer.echo(f"written: {out}")


@qa_app.command("simulate")
def qa_simulate(scorecards: list[Path] = typer.Argument(None, help="Default: every scorecard in scorecards/"),
                calls: int = typer.Option(6, min=1, max=50, help="Calls per segment"), seed: int = 1,
                voice_calls: int = typer.Option(0, min=0, help="Per segment, speak this many with Timbre and transcribe with Prisma (uses credits)"),
                judge_samples: int = typer.Option(3, min=1, max=7),
                max_tts_chars: int = typer.Option(None, help="Hard cap on Timbre characters for the whole run"),
                max_stt_seconds: float = typer.Option(None, help="Hard cap on audio sent to Prisma for the whole run"),
                out: Path = typer.Option(None, help="Default: runs/segments-<time>")):
    """QA-Bench for every segment: Evon writes calls with planted defects from each scorecard; the auditor must find them."""
    import time
    from .gnani import Evon
    from .qa.simulate import simulate_segment, write_segments_html
    from .runner import Budget, Usage
    _utf8_console()
    load_dotenv()
    paths = scorecards or sorted(Path("scorecards").glob("*.yaml"))
    usage = Usage(Budget(max_tts_chars=max_tts_chars, max_stt_seconds=max_stt_seconds))
    evon, tts, hear = Evon(), None, None
    evon.chat([{"role": "user", "content": "Reply with the word ready."}], max_tokens=5)   # fail fast if Evon is down
    if voice_calls:
        from .gnani import Prisma, Timbre
        timbre, stt = Timbre(), Prisma()

        class _Counted:          # count characters against the budget before each Timbre request
            def synthesize(self, text, **kw):
                if usage.budget.max_tts_chars is not None and usage.tts_chars + len(text) > usage.budget.max_tts_chars:
                    usage._refuse(f"TTS chars {usage.tts_chars}+{len(text)} > {usage.budget.max_tts_chars}")
                usage.tts_calls += 1
                usage.tts_chars += len(text)
                return timbre.synthesize(text, **kw)
        tts = _Counted()
        hear = usage.wrap_hear(lambda audio, sr, lg: stt.transcribe_long(audio, sr, lg) if audio.size >= 0.2 * sr else "")
    out = out or Path("runs") / f"segments-{time.strftime('%Y%m%d-%H%M%S')}"
    rows = []
    for p in paths:
        card = _load_scorecard(p)
        typer.echo(f"{card.name}: writing {calls} calls with planted defects...")
        r = simulate_segment(card, p.stem, out / p.stem, evon, calls, seed, judge_samples, voice_calls, tts, hear)
        e = r["evaluation"]
        pct = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
        typer.echo(f"  planted defects found {pct(e['planted_recall'])} of {e['planted']} · to review {e['planted_to_review']} · "
                   f"unplanted flags {pct(e['unplanted_flag_rate'])} · fatal recall {pct(e['fatal_recall'])} · "
                   f"false fatal {e['false_fatal']}/{e['clean_fatal_calls']}")
        rows.append(r)
        write_segments_html(rows, out / "segments.html", time.strftime("%Y-%m-%d %H:%M"))
        (out / "segments.json").write_text(json.dumps([{k: v for k, v in x.items() if k != "calls"} for x in rows],
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(f"\nusage: {json.dumps(usage.to_dict())}\nreport: {out / 'segments.html'}")


if __name__ == "__main__":
    app()
