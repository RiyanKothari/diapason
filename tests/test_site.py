import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_simulate import FakeEvon, card  # noqa: E402

from diapason.qa.simulate import simulate_segment, write_segments_html  # noqa: E402
from diapason.site import build_site  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_static_site_has_everything_without_a_server(tmp_path):
    runs = tmp_path / "runs"
    r = simulate_segment(card(), "emi_collections", runs / "segments-x" / "emi_collections", FakeEvon(), n=3, seed=2, samples=1)
    (runs / "segments-x" / "segments.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "calls"}]), encoding="utf-8")
    write_segments_html([r], runs / "segments-x" / "segments.html", "now")
    proof = runs / "proof-x"
    (proof / "v1" / "case" / "run0").mkdir(parents=True)
    (proof / "v1" / "case" / "run0" / "mix.wav").write_bytes(b"RIFF")
    (proof / "v1" / "case" / "run0" / "caller.wav").write_bytes(b"RIFF")
    (proof / "proof.html").write_text("<a href='v1/report.html'>v1</a>", encoding="utf-8")
    (proof / "proof.json").write_text(json.dumps({"generated": "2026-10-28 21:31", "tests": {"caught": 7, "measured": 8},
                                                  "qa": {"overall": {"accuracy": 0.904}, "fatal_recall": 1.0, "fatal_false_alarms": 0,
                                                         "decision_accuracy": 0.925}}), encoding="utf-8")
    (runs / "_superseded" / "old").mkdir(parents=True)
    out = tmp_path / "site"
    info = build_site(out, runs_dir=runs, scorecards_dir=ROOT / "scorecards")
    assert info["proof"] == "proof-x" and info["simulations"] == ["segments-x"]
    landing = (out / "index.html").read_text(encoding="utf-8")
    assert "90.4%" in landing and "7/8" in landing and "studio.html" in landing
    assert 'window.DIAPASON_DATA = "data/"' in (out / "studio.html").read_text(encoding="utf-8")
    studio = json.loads((out / "data" / "studio.json").read_text(encoding="utf-8"))
    assert [a["path"] for a in studio["audits"]] == ["segments-x/emi_collections"]
    assert (out / "data" / "audit" / "segments-x__emi_collections.json").exists()
    assert not (out / "proof" / "v1" / "case" / "run0" / "mix.wav").exists()      # Evon proof calls are codec tones:
    assert not (out / "proof" / "v1" / "case" / "run0" / "caller.wav").exists()   # only the replayed showcase call is kept
    assert (out / "segments-x" / "segments.html").exists()


def test_site_keeps_only_the_showcase_calls_audio(tmp_path):
    from diapason.site import SHOWCASE_CASE, build_site
    runs = tmp_path / "runs"
    proof = runs / "proof-x"
    for d in ("v1", "g"):
        for case in (SHOWCASE_CASE, "privacy"):
            (proof / d / case / "run0").mkdir(parents=True)
            (proof / d / case / "run0" / "mix.wav").write_bytes(b"RIFF")
    (proof / "proof.json").write_text(json.dumps({"generated": "now", "mode": "offline", "tests": {
        "caught": 0, "measured": 0, "false_alarms": 0, "bugs": [], "v1_dir": "v1", "v2_dir": "v1", "guard_dir": "g"},
        "qa": {"overall": {}, "parameters": {}}}), encoding="utf-8")
    out = tmp_path / "site"
    build_site(out, runs_dir=runs, scorecards_dir=tmp_path / "none", proof=proof)
    kept = sorted(p.relative_to(out / "proof").as_posix() for p in (out / "proof").rglob("*.wav"))
    assert kept == [f"g/{SHOWCASE_CASE}/run0/mix.wav", f"v1/{SHOWCASE_CASE}/run0/mix.wav"]
