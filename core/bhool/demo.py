"""`bhool demo`: the whole product, end to end, with zero API credits.

Serves the reference agent v1 (seeded bugs) and then v2 (fixed) over real websockets, runs the
same suite against each through the real harness (channel simulator, real-time call engine,
metrics, code checks, reports), then diffs the two runs. Models are offline stand-ins: the
agent's words round-trip through ToneCodec so the transcript is exactly what it said. The
Evon rubric judge is not run offline; banned phrases, slot capture and audio metrics are.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

from .call.transport import WebSocketAgent
from .diff import diff_reports, to_markdown
from .fakes import ScriptedBrain, ToneCodec, fake_speak, scripted_agent_llm
from .reference_agent import AgentVersion, serve
from .runner import SuiteReport, run_suite
from .scenarios import Suite, load_suite

CALLER_LINES = ["हाँ बोलिए, मैं रमेश बोल रहा हूँ", "चार आठ दो एक", "पंद्रह November को pay कर दूंगा", "ठीक है, धन्यवाद"]

AGENT_SCRIPTS = {
    # v1: states the debt to whoever answers, threatens, never verifies, misses the loan ID.
    "v1": [
        {"say": "आपकी EMI 4500 रुपये की overdue है। आज pay नहीं किया तो police complaint होगी और legal action होगा।", "slots": {}},
        {"say": "देखिए, आपको आज ही पैसे भरने होंगे, वरना बहुत problem होगी आपके लिए।", "slots": {}},
        {"say": "ठीक है, पंद्रह तारीख note कर लिया।", "slots": {"promise_to_pay_date": "15 November"}, "end_call": True},
    ],
    # v2: verifies first, states the amount only after, confirms the date back, polite close.
    "v2": [
        {"say": "धन्यवाद रमेश जी। verify करने के लिए loan ID के आखिरी चार अंक बताइए।", "slots": {}},
        {"say": "धन्यवाद, verify हो गया। आपकी 4500 रुपये की EMI बाकी है। आप कब pay कर पाएंगे?", "slots": {"loan_id_last4": "4821"}},
        {"say": "ठीक है, पंद्रह November note कर लिया। आपका दिन शुभ हो।", "slots": {"promise_to_pay_date": "15 November"}, "end_call": True},
    ],
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _speech(live: bool):
    """(agent_stt, agent_tts, caller_speak, caller_hear): offline stand-ins, or real Prisma + Timbre."""
    if not live:
        codec = ToneCodec()
        return (lambda audio, sr, lang: "हाँ" if audio.size else "", lambda text, voice, lang: codec.encode(text),
                fake_speak(), lambda audio, sr, lang: codec.decode(audio, sr))
    from dotenv import load_dotenv
    from .gnani import Prisma, Timbre
    load_dotenv()
    tts, stt = Timbre(), Prisma()

    def hear(audio, sr, lang):
        return stt.transcribe_long(audio, sr, lang) if audio.size >= 0.2 * sr else ""

    return (hear, lambda text, voice, lang: tts.synthesize(text, voice=voice, lang=lang),
            lambda utt, p: tts.synthesize(utt.tts_text(), voice=p.voice, lang=p.tts_lang, speed=p.speed), hear)


class CountedEvon:
    """Evon, counting its failures. When Evon itself fails mid-run (the tunnel drops, a request times out), the
    agent it plays goes silent and the calls look like agent failures; the count lets callers discard them."""

    def __init__(self, evon):
        self.evon, self.errors, self.last = evon, 0, ""

    def _guard(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            self.errors += 1
            self.last = repr(e)[:200]
            raise

    def chat(self, *a, **kw):
        return self._guard(self.evon.chat, *a, **kw)

    def chat_json(self, *a, **kw):
        return self._guard(self.evon.chat_json, *a, **kw)


def _codec_speech():
    """Both directions through one ToneCodec: every word is carried exactly, timing and phone-line
    effects stay real, and no speech API is called. For runs where the brains, not the voices, matter."""
    codec = ToneCodec()
    return (lambda audio, sr, lang: codec.decode(audio, sr), lambda text, voice, lang: codec.encode(text),
            lambda utt, p: codec.encode(utt.text), lambda audio, sr, lang: codec.decode(audio, sr))


async def run_version(version: str, suite_path: str | Path | Suite, out_dir: str | Path, on_event=None, live: bool = False,
                      only: str | None = None, budget=None, evon=None, judge_samples: int = 3,
                      runs_per_scenario: int | None = None, label: str | None = None,
                      agent: AgentVersion | None = None) -> SuiteReport:
    """evon=None: scripted agent and caller (zero cost). evon given: Evon plays the agent (v1/v2 prompt), the
    caller (persona + behaviour) and the judge, with simulated phone audio; no Gnani speech credits.
    agent: serve this prompt/config instead of the stock `version` (e.g. a patch from `heal`)."""
    suite = suite_path if isinstance(suite_path, Suite) else load_suite(suite_path)
    if runs_per_scenario:
        suite = suite.model_copy(update={"runs_per_scenario": runs_per_scenario})
    if evon is not None:
        # The agent's thinking time here is our shared test GPU, not the agent's design: don't judge it.
        # Endpointing, unanswered turns and barge-in handling are still the agent's own and still measured.
        suite = suite.model_copy(update={"gate": suite.gate.model_copy(update={"max_p95_latency_ms": None, "check_dead_air": False})})
        from .caller.brain import EvonBrain
        evon = CountedEvon(evon)
        agent_stt, agent_tts, speak, hear = _codec_speech()
        agent_llm = lambda msgs: evon.chat_json(msgs, temperature=0.4, max_tokens=300)  # noqa: E731
        make_brain = lambda s, r: EvonBrain(evon, s.persona, s.behaviour, seed=s.seed + r)  # noqa: E731
    else:
        agent_stt, agent_tts, speak, hear = _speech(live)
        agent_llm = scripted_agent_llm(AGENT_SCRIPTS[version])
        make_brain = lambda s, r: ScriptedBrain(CALLER_LINES, interjection="एक minute, सुनिए")  # noqa: E731
    port = _free_port()
    ready = asyncio.Event()
    server = asyncio.create_task(serve(agent or version, stt=agent_stt, llm=agent_llm, tts=agent_tts, port=port, ready=ready))
    await ready.wait()
    scenarios = [s for s in suite.expand() if not only or only in s.id]
    try:
        report = await run_suite(
            suite, connect=lambda s: WebSocketAgent(f"ws://127.0.0.1:{port}", suite.target.sample_rate),
            make_brain=make_brain, speak=speak, hear=hear, evon_judge=evon, judge_samples=judge_samples,
            scenarios=scenarios, out_dir=out_dir, concurrency=4, on_event=on_event,
            label=label or f"reference agent {version}{' (live Gnani speech)' if live else ''}", budget=budget,
            call_kwargs={"max_duration_s": 90 if evon else 60, "agent_silent_timeout_s": 12 if (live or evon) else 7},
        )
        if isinstance(evon, CountedEvon):
            report.usage["harness_errors"], report.usage["harness_error"] = evon.errors, evon.last
        return report
    finally:
        server.cancel()
        await asyncio.gather(server, return_exceptions=True)


async def run_demo(suite_path: str | Path = "suites/demo.yaml", out_dir: str | Path = "runs", on_event=None,
                   live: bool = False, only: str | None = None, budget=None):
    v1 = await run_version("v1", suite_path, out_dir, on_event, live, only, budget)
    v2 = await run_version("v2", suite_path, out_dir, on_event, live, only, budget)
    d = diff_reports(v1.to_dict(), v2.to_dict())
    md = to_markdown(d)
    Path(v2.dir, "diff_from_v1.md").write_text(md, encoding="utf-8")
    return v1, v2, d, md
