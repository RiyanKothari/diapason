"""Diapason Shield in front of an agent it did not build: monitor flags, block drops, block with a voice corrects."""

import asyncio
import json

import numpy as np
import pytest
import websockets

from diapason.call.dialects import SR, dialect
from diapason.fakes import ToneCodec
from diapason.shield import Shield, summarize

THREAT = "आपकी EMI overdue है, वरना legal action होगा।"            # v1's opening, seen live: a threat, no disclosure
BYE = "धन्यवाद, आपका दिन शुभ हो।"
CRM = {"name": "रमेश", "loan_id_last4": "4821", "amount_due": "4500", "due_date": "5 November", "lender": "Sahyog Finance"}


def pcm(codec, text):
    x, _ = codec.encode(text)
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


async def run(mode, dialect_name="twilio", speak=False, tmp=None):
    codec, d = ToneCodec(sr=SR), dialect(dialect_name)

    async def agent(ws):                                   # an agent Shield knows nothing about
        sid = ""
        async for raw in ws:
            kind, value = d.parse(json.loads(raw))
            if kind == "start":
                sid = value[0]
                break
        for text in (THREAT, BYE):
            audio = pcm(codec, text)
            for i in range(0, len(audio), 320):
                await ws.send(json.dumps(d.agent_media(sid, audio[i:i + 320])))
            await asyncio.sleep(1.0)                       # the agent waits for the caller
        await asyncio.sleep(5)

    events = []
    say = (lambda text: pcm(codec, text)) if speak else None
    shield = Shield("", hear=lambda x, sr: codec.decode(x, sr), dialect_name=dialect_name, mode=mode, crm=CRM,
                    speak=say, listen_caller=False, on_event=events.append, log_dir=tmp)
    async with websockets.serve(agent, "127.0.0.1", 0) as a:
        shield.agent_url = f"ws://127.0.0.1:{a.sockets[0].getsockname()[1]}"
        async with websockets.serve(shield.handle, "127.0.0.1", 0) as s:
            heard = []
            async with websockets.connect(f"ws://127.0.0.1:{s.sockets[0].getsockname()[1]}") as tel:   # the platform's side
                for m in d.opening("MZ1", "CA1", {}):
                    await tel.send(json.dumps(m))
                end = asyncio.get_running_loop().time() + 4.5
                while (left := end - asyncio.get_running_loop().time()) > 0:
                    try:
                        kind, value = d.parse(json.loads(await asyncio.wait_for(tel.recv(), left)))
                    except asyncio.TimeoutError:
                        break
                    if kind == "media":
                        heard.append(value)
                await tel.send(json.dumps(d.stop("MZ1")))
    audio = np.frombuffer(b"".join(heard), "<i2").astype(np.float32) / 32768
    return audio, [e for e in events if e["side"] == "agent"], codec


def test_monitor_flags_the_threat_and_changes_nothing():
    audio, ev, codec = asyncio.run(run("monitor"))
    first = ev[0]
    assert first["text"] == THREAT and first["verdict"] == "flagged"
    assert {"banned_phrase", "missing_disclosure"} <= {r["rule"] for r in first["rules"]}
    assert ev[1]["text"] == BYE and ev[1]["verdict"] == "ok"
    expected = (len(pcm(codec, THREAT)) + len(pcm(codec, BYE))) // 2
    assert abs(audio.size - expected) < SR * 0.05            # every sample the agent sent reached the caller


@pytest.mark.parametrize("dialect_name", ["twilio", "exotel", "plivo"])
def test_block_drops_the_threat_before_the_caller_hears_it(dialect_name, tmp_path):
    audio, ev, codec = asyncio.run(run("block", dialect_name, tmp=tmp_path))
    assert ev[0]["verdict"] == "blocked" and ev[0]["held_ms"] is not None
    assert ev[1]["verdict"] == "ok"
    assert abs(audio.size - len(pcm(codec, BYE)) // 2) < SR * 0.05     # only the goodbye was played
    assert codec.decode(audio, SR) == BYE
    s = summarize(tmp_path)
    assert s["utterances"] == 2 and s["blocked"] == 1 and s["by_rule"]["banned_phrase"] == 1
    assert json.loads((tmp_path / "calls" / "MZ1.json").read_text(encoding="utf-8"))["flagged"] == 1


def test_block_with_a_voice_says_the_corrected_line_instead():
    audio, ev, codec = asyncio.run(run("block", speak=True))
    first = ev[0]
    assert first["verdict"] == "replaced" and "record" in first["said_instead"] and "legal action" not in first["said_instead"]
    n = len(pcm(codec, first["said_instead"])) // 2
    assert codec.decode(audio[:n], SR) == first["said_instead"]       # the caller heard the corrected line, then the goodbye


def test_dashboard_reads_shields_log(tmp_path):
    from fastapi.testclient import TestClient

    from diapason.server import create_app
    asyncio.run(run("block", tmp=tmp_path / "runs" / "shield"))
    s = TestClient(create_app(runs_dir=tmp_path / "runs")).get("/api/shield").json()
    assert s["calls"] == 1 and s["utterances"] == 2 and s["blocked"] == 1 and s["held_ms_p50"] is not None
    assert [e["verdict"] for e in s["events"]] == ["blocked", "ok"]
