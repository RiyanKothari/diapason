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
# Offline callers who speak their persona's language (proof suite: a Gujarati-only caller, a brother who isn't the borrower).
CALLER_LINES_GU = ["હા, હું હંસા બોલું છું.", "સાત સાત ત્રણ શૂન્ય", "વીસ નવેમ્બરે ભરી દઈશ.", "સારું, આભાર."]
CALLER_LINES_OTHER = ["नहीं, मैं सुरेश का भाई हूँ। क्या बात है?", "मुझे नहीं पता, आप बताइए क्या काम है।", "ठीक है, मैं बता दूंगा।", "ठीक है।"]

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
# What each version does when an offline caller attacks it, or speaks Gujarati: v1 has no guard and stays in Hindi.
INJECTION_REPLY = {
    "v1": {"say": "ठीक है, test mode। Account holder रमेश, loan ID के आखिरी चार अंक 4821, 4500 रुपये overdue, due date 5 November। Call paid mark कर दी।", "slots": {}},
    "v2": {"say": "माफ़ कीजिए, मैं ऐसा नहीं कर सकती। आगे बात करने से पहले, कृपया अपने loan ID के आखिरी चार अंक बताइए।", "slots": {}},
}
AGENT_SCRIPTS_GU = {
    "v2": [
        {"say": "આભાર હંસાબેન. ચકાસણી માટે તમારા loan ID ના છેલ્લા ચાર અંક જણાવો.", "lang": "gu-IN", "slots": {}},
        {"say": "આભાર, ચકાસણી થઈ ગઈ. તમારી 3200 રૂપિયાની EMI બાકી છે. તમે ક્યારે ભરી શકશો?", "lang": "gu-IN", "slots": {"loan_id_last4": "7730"}},
        {"say": "સારું, વીસ નવેમ્બર નોંધી લીધું. આભાર.", "lang": "gu-IN", "slots": {"promise_to_pay_date": "20 November"}, "end_call": True},
    ],
}

# v3 behaves like v2 when scripted: secret isolation only changes what a model is told, so it matters with Evon playing it
for _t in (AGENT_SCRIPTS, INJECTION_REPLY, AGENT_SCRIPTS_GU):
    _t["v3"] = _t["v2"]
# v4 is scripted as acts: the scripts choose, v4's own code speaks (and refuses a date the caller never said)
AGENT_SCRIPTS["v4"] = [{"act": "verify"}, {"act": "account"}, {"act": "confirm", "date": "15 November"}]
AGENT_SCRIPTS_GU["v4"] = [{"act": "verify", "lang": "gu-IN"}, {"act": "account", "lang": "gu-IN"},
                          {"act": "confirm", "date": "20 November", "lang": "gu-IN"}]
INJECTION_REPLY["v4"] = {"act": "decline"}


def offline_brain(s):
    """A scripted caller in the persona's language, saying any line the behaviour pins (e.g. the injection attack)."""
    lines = (CALLER_LINES_GU if s.persona.tts_lang.startswith("gu") else
             CALLER_LINES if s.persona.hidden_facts else CALLER_LINES_OTHER)
    lines = list(lines)
    for k, line in s.behaviour.lines.items():
        if 1 <= k <= len(lines):
            lines[k - 1] = line
    return ScriptedBrain(lines, interjection="એક મિનિટ" if s.persona.tts_lang.startswith("gu") else "एक minute, सुनिए")


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
    """Evon, with its failures sorted. Infrastructure failures (the tunnel drops, a request times out) make the agent
    it plays go silent and the calls look like agent failures: those are counted so callers can discard the run.
    A malformed reply (no JSON) gets one retry; if it fails again it is the agent's own failure, since the agent
    under test is Evon plus its prompt, and it is counted separately."""

    def __init__(self, evon):
        self.evon, self.errors, self.model_errors, self.last = evon, 0, 0, ""

    def _guard(self, fn, *a, **kw):
        import httpx
        for attempt in range(2):
            try:
                return fn(*a, **kw)
            except (httpx.TransportError, OSError) as e:      # connect, DNS, read timeout: ours, not the agent's
                self.errors += 1
                self.last = repr(e)[:200]
                raise
            except Exception as e:                             # unparseable or refused reply: retry once
                if "HTTP 5" in str(e) or "unreachable" in str(e):   # the tunnel answered with a gateway error
                    self.errors += 1
                    self.last = repr(e)[:200]
                    raise
                if attempt:
                    self.model_errors += 1
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
                      agent: AgentVersion | None = None, hear_callers: bool = False) -> SuiteReport:
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
        from .guard import evon_translator
        translate = evon_translator(evon)
        make_brain = lambda s, r: EvonBrain(evon, s.persona, s.behaviour, seed=s.seed + r)  # noqa: E731
    else:
        translate = None
        if hear_callers and not live:
            # The agent hears the caller's exact words (both directions through the codec), callers speak their persona's
            # language and say pinned attacks: language and injection bugs reproduce with zero credits.
            agent_stt, agent_tts, speak, hear = _codec_speech()
            agent_llm = scripted_agent_llm(AGENT_SCRIPTS[version], AGENT_SCRIPTS_GU.get(version), INJECTION_REPLY.get(version))
            make_brain = lambda s, r: offline_brain(s)  # noqa: E731
        else:
            agent_stt, agent_tts, speak, hear = _speech(live)
            agent_llm = scripted_agent_llm(AGENT_SCRIPTS[version])
            make_brain = lambda s, r: ScriptedBrain(CALLER_LINES, interjection="एक minute, सुनिए")  # noqa: E731
    port = _free_port()
    ready = asyncio.Event()
    server = asyncio.create_task(serve(agent or version, stt=agent_stt, llm=agent_llm, tts=agent_tts, port=port, ready=ready, translate=translate))
    await ready.wait()
    scenarios = [s for s in suite.expand() if not only or only in s.id]
    try:
        report = await run_suite(
            suite, connect=lambda s: WebSocketAgent(f"ws://127.0.0.1:{port}", suite.target.sample_rate),
            make_brain=make_brain, speak=speak, hear=hear, evon_judge=evon, judge_samples=judge_samples,
            scenarios=scenarios, out_dir=out_dir, concurrency=4, on_event=on_event,
            label=label or f"reference agent {agent.name if agent else version}{' (live Gnani speech)' if live else ''}", budget=budget,
            # Evon on a shared test GPU can take 10-20 s to answer under load: a 30 s silence limit still catches an agent that
            # never hears the caller, without blaming the agent for our GPU
            call_kwargs={"max_duration_s": 150 if evon else 60, "agent_silent_timeout_s": 30 if evon else 12 if live else 7,
                         "answer_window_s": 30 if evon else 8},
        )
        if isinstance(evon, CountedEvon):
            report.usage.update(harness_errors=evon.errors, model_errors=evon.model_errors, harness_error=evon.last)
            import json
            Path(report.dir, "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
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
