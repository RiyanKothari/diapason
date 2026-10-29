"""Rubric packs, ASR bench, the ToneCodec used by the offline demo, and the demo itself."""

import asyncio

import numpy as np
import pytest

from bhool.bench import cer, run_bench, write_bench_report
from bhool.fakes import ToneCodec
from bhool.judge.packs import PACKS, get_pack
from bhool.scenarios import Suite, load_suite


def test_every_pack_has_unique_ids_and_critical_rules():
    for name, crits in PACKS.items():
        ids = [c.id for c in crits]
        assert len(ids) == len(set(ids)), name
        assert any(c.critical for c in crits), name


def test_bfsi_pack_covers_rbi_fair_practices():
    ids = {c.id for c in get_pack("bfsi_collections")}
    assert {"disclosure", "verification", "privacy", "no_harassment", "hardship"} <= ids


def test_suite_rejects_unknown_rubric():
    data = load_suite("suites/emi_collection.yaml").model_dump()
    data["rubric"] = "astrology"
    with pytest.raises(ValueError, match="unknown rubric pack"):
        Suite.model_validate(data)


def test_tone_codec_round_trips_text_even_cut_short():
    codec = ToneCodec()
    items = [codec.encode(t) for t in ["नमस्ते जी", "आपकी EMI बाकी है", "ठीक है, धन्यवाद"]]
    for (audio, sr), text in zip(items, ["नमस्ते जी", "आपकी EMI बाकी है", "ठीक है, धन्यवाद"]):
        assert codec.decode(audio, sr) == text
        assert codec.decode(audio[: sr // 3], sr) == text        # yielded mid-sentence


def test_cer_basics():
    assert cer("नमस्ते जी", "नमस्ते जी।") == 0
    assert cer("abcd", "abxd") == 0.25
    assert cer("abcd", "") == 1


def test_bench_grid_ranks_presets(tmp_path):
    sents = [("hi-en", "hi-IN", "Shivani", "मैं पंद्रह तारीख को pay करूँगी"), ("gu-IN", "gu-IN", "Lakshmi", "હું વીસ તારીખે ભરીશ")]
    ref = {s[3] for s in sents}

    def speak(text, voice, lang):
        sr = 16000
        audio = (0.2 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype(np.float32)
        speak.last = text
        return audio, sr

    def transcribe(audio, sr, lang):
        # Pretend recognition degrades with noise: drop characters in proportion to noise energy.
        text = speak.last
        noisy = float(np.std(np.diff(audio))) > 0.05
        return text[: len(text) // 2] if noisy else text

    res = run_bench(speak, transcribe, presets=["clean", "market"], sentences=sents)
    assert set(res["grid"]) == {"hi-en", "gu-IN"}
    assert res["by_preset"]["clean"] == 0.0 and res["by_preset"]["market"] > 0.3
    assert all(r["ref"] in ref for r in res["rows"])
    path = write_bench_report(res, tmp_path)
    assert "Hardest cases" in path.read_text(encoding="utf-8")


def test_offline_demo_v1_fails_on_seeded_bugs_v2_fixes_landline(tmp_path):
    from bhool.demo import run_demo
    v1, v2, d, md = asyncio.run(run_demo("suites/demo.yaml", tmp_path))
    v1_fail = {c["id"] for v in v1.verdicts if "landline" in v["scenario_id"] for c in v["criteria"] if c["verdict"] == "fail"}
    assert {"banned_phrases", "slot_capture"} <= v1_fail
    landline = {c.scenario_id: c.status for c in d.changes if "landline" in c.scenario_id}
    assert set(landline.values()) == {"fixed"}, landline
    assert v1.pass_rate < v2.pass_rate
