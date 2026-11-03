"""The demo film: every scene is built from run files, and what it says follows the data."""

import json
import wave

from bhool import film
from bhool.site import build_site


def _wav(path, seconds=2.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\x10\x00" * int(8000 * seconds))


def _runs(tmp_path):
    runs = tmp_path / "runs"
    d = runs / film.LIVE_V1 / film.LIVE_CASE / "run0"
    _wav(d / "mix.wav")
    turns = [{"speaker": "agent", "text": "नमस्ते", "start": 0.2, "end": 1.0},
             {"speaker": "caller", "text": "हाँ बोलिए", "start": 1.2, "end": 1.5},
             {"speaker": "agent", "text": "पैसे नहीं दिए तो पुलिस आएगी", "start": 1.6, "end": 2.0}]
    (d / "call.json").write_text(json.dumps({"duration_s": 2.0, "turns": turns, "events": [],
                                             "metrics": {"response_latencies_s": [0.1], "latency_p50_s": 0.1, "latency_p95_s": 0.1}}), encoding="utf-8")
    (runs / film.LIVE_V1 / "report.json").write_text(json.dumps({"gate_reasons": ["pass rate 0% < gate 85%"], "verdicts": [
        {"scenario_id": film.LIVE_CASE, "passed": False, "metric_failures": [], "criteria": [
            {"id": "banned_phrases", "verdict": "fail", "reason": "agent said banned phrase(s): ['पुलिस']",
             "evidence": [{"turn": 2, "quote": "पुलिस"}]},
            {"id": "disclosure", "verdict": "pass", "evidence": []}]}]}), encoding="utf-8")
    proof = runs / "proof-x"
    bugs = [{"id": b, "what": b, "status": "caught"} for b in film.TEXT_BUGS]
    v4 = {"prevented": 6, "measured": 6, "bugs": [{"id": b, "status": "prevented"} for b in film.TEXT_BUGS]}
    (proof / "v4").mkdir(parents=True)
    (proof / "v4" / "report.json").write_text(json.dumps({"verdicts": [{"passed": True}, {"passed": False}]}), encoding="utf-8")
    (proof / "proof.json").write_text(json.dumps({"generated": "now", "tests": {"caught": 6, "measured": 6, "false_alarms": 0,
        "bugs": bugs, "v4": v4, "v4_dir": "v4"}, "qa": {"overall": {"accuracy": 0.9, "n": 10}, "fatal_recall": 1.0,
        "fatal_false_alarms": 0}}), encoding="utf-8")
    return runs, proof


def test_the_call_scene_is_the_recorded_call_with_its_failed_checks(tmp_path):
    runs, proof = _runs(tmp_path)
    reel = film.film(runs, proof, lambda p: f"film/{p.name}", suite=tmp_path / "none.yaml", scorecards=tmp_path)
    kinds = [s["type"] for s in reel["scenes"]]
    assert kinds == ["intro", "call", "bugs", "versions", "qa", "outro"]       # no guard, atlas or stress data: no scene
    call = reel["scenes"][1]
    assert call["audio"] == "film/mix.wav" and len(call["peaks"]) == 160
    assert call["turns"][2]["flags"] == [{"name": "banned threat", "quote": "पुलिस"}]
    assert [f["name"] for f in call["fails"]] == ["banned threat"]           # a passed check is never shown as failed
    assert call["turns"][2]["latency"] == 0.1
    v = reel["scenes"][3]
    assert v["cols"] == [{"label": "v4", "cells": ["prevented"] * 6, "prevented": 6, "measured": 6, "calls": [1, 2]}]
    assert abs(reel["total"] - sum(s["dur"] for s in reel["scenes"])) < 1e-6


def test_noise_caption_only_claims_what_the_sweep_shows():
    grid = {"fan": {"30": True, "0": False}}
    stress = {"levels": [30, 0], "noises": ["fan"], "versions": {
        "v1": {"grid": grid, "points": {"fan": {"breaks_at": 0, "holds_to": 30}}},
        "v4": {"grid": grid, "points": {"fan": {"breaks_at": 0, "holds_to": 30}}}}}
    cap = film._stress_scene(stress)["captions"][0][1]
    assert "between 0 and 0 dB" in cap and "v4 hears" not in cap          # v4 broke too: the film must not say it held
    stress["versions"]["v4"]["points"]["fan"] = {"breaks_at": None, "holds_to": 0}
    assert "v4 hears through every level" in film._stress_scene(stress)["captions"][0][1]


def test_site_ships_the_film_with_its_audio(tmp_path):
    runs, proof = _runs(tmp_path)
    out = tmp_path / "site"
    info = build_site(out, runs_dir=runs, scorecards_dir=tmp_path / "none", proof=proof)
    page = (out / "watch.html").read_text(encoding="utf-8")
    assert "__DATA__" not in page and '"type": "call"' in page and info["film_scenes"] >= 5
    assert (out / "film" / f"{film.LIVE_V1}.wav").exists()
    assert 'href="watch.html"' in (out / "index.html").read_text(encoding="utf-8")
