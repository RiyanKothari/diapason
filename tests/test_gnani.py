"""Offline tests for the Gnani clients against a mocked HTTP transport."""

import json

import httpx
import numpy as np
import pytest

from bhool import gnani
from bhool.audio import wav_bytes
from bhool.gnani import Evon, GnaniError, Prisma, Timbre


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(gnani.time, "sleep", lambda s: None)
    monkeypatch.setenv("GNANI_API_KEY", "test-key")


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tts_request_shape_and_cache(tmp_path):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, content=wav_bytes(np.zeros(1600, np.float32), 16000))

    tts = Timbre(cache_dir=tmp_path)
    tts.http = mock(handler)
    x, sr = tts.synthesize("नमस्ते <sigh> हाँ", voice="Lakshmi", lang="hi-IN")
    y, _ = tts.synthesize("नमस्ते <sigh> हाँ", voice="Lakshmi", lang="hi-IN")
    assert sr == 16000 and x.size == 1600 and np.array_equal(x, y)
    assert len(seen) == 1 and tts.calls == 1 and tts.hits == 1
    req = seen[0]
    assert req.url.path == "/api/v1/tts/inference"
    assert req.headers["X-API-Key-ID"] == "test-key"
    body = json.loads(req.content)
    assert body["model"] == "timbre-v3.0" and body["voice"] == "Lakshmi" and body["language"] == "hi-IN"
    assert body["audio_config"]["container"] == "wav" and body["audio_config"]["sample_rate"] == 16000
    # A different voice is a cache miss.
    tts.synthesize("नमस्ते <sigh> हाँ", voice="Kalpana", lang="hi-IN")
    assert len(seen) == 2


def test_stt_retries_on_429_then_succeeds():
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) < 3:
            return httpx.Response(429, json={"success": False, "error": {"type": "rate_limit", "message": "slow down"}})
        return httpx.Response(200, json={"success": True, "transcript": "हाँ जी"})

    stt = Prisma()
    stt.http = mock(handler)
    out = stt.transcribe(np.zeros(8000, np.float32), 8000, lang="gu-IN")
    assert out["transcript"] == "हाँ जी" and len(calls) == 3
    assert calls[0].url.path == "/stt/v3"
    assert b'name="language_code"' in calls[0].content and b"gu-IN" in calls[0].content


def test_stt_error_message_is_surfaced():
    stt = Prisma()
    stt.http = mock(lambda req: httpx.Response(403, json={"success": False, "error": {"type": "forbidden", "message": "no credits"}}))
    with pytest.raises(GnaniError, match="403 forbidden: no credits"):
        stt.transcribe(np.zeros(8000, np.float32), 8000)


def test_stt_rejects_over_60s():
    with pytest.raises(GnaniError, match="60 s"):
        Prisma().transcribe(np.zeros(8000 * 61, np.float32), 8000)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY")
    with pytest.raises(GnaniError, match="GNANI_API_KEY"):
        Prisma()


def test_evon_json_tolerates_fences():
    def handler(req):
        body = json.loads(req.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"pass": true}\n```'}}]})

    evon = Evon(base_url="http://evon.test/v1", model="evon")
    evon.http = mock(handler)
    assert evon.chat_json([{"role": "user", "content": "x"}]) == {"pass": True}


def test_one_active_request_limit_is_a_short_queue_not_a_backoff(monkeypatch):
    from bhool import gnani
    sleeps, calls = [], {"n": 0}
    monkeypatch.setattr(gnani.time, "sleep", lambda s: sleeps.append(s))

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 5:   # seen live: two STT users on one key
            return httpx.Response(429, json={"detail": {"error_code": "RATE_LIMITED",
                                  "message": "Only 1 active request is allowed at a time."}})
        return httpx.Response(200, json={"transcript": "ok"})

    resp = gnani._post_with_retry(httpx.Client(transport=httpx.MockTransport(handler)), "https://x/stt/v3")
    assert resp.status_code == 200 and calls["n"] == 6
    assert max(sleeps) < 0.2                   # polled, not 0.5 -> 1 -> 2 -> 4 s backoff that gives up after 4
