import numpy as np

from diapason.atlas import ITEMS, conditions, run_atlas, summarize, write_atlas_report


def test_every_item_survives_its_own_text():
    # the parsers must read each detail back from the exact words written, or the atlas would blame Prisma for our bug
    bad = [(i.lang, i.kind, i.style) for i in ITEMS if not i.survives(i.text)]
    assert not bad, bad


def test_atlas_runs_end_to_end_and_finds_the_threshold(tmp_path):
    items = [i for i in ITEMS if i.lang == "en" and i.kind == "id"][:2]
    by_text = {i.text: i for i in items}

    def speak(text, voice, lang):
        return np.full(16000, 0.1, np.float32) * (1 + list(by_text).index(text)), 16000

    def transcribe(audio, sr, lang):
        # a fake recogniser that keeps digit words and loses everything once the line is noisy
        loud = float(np.abs(audio).max())
        return "four eight two one" if loud > 0.12 or np.std(audio) < 0.05 else "for ate to won"

    res = run_atlas(speak, transcribe, items=items, voices={"en": ("Devansh",)},
                    conds=conditions(noises=("fan",), snrs=(30, 0)), seeds=1, workers=2)
    assert res["requests"] == 2 * 4 and res["errors"] == 0
    assert set(res["best"]) == {"en/id"}
    assert (tmp_path / "atlas.html").exists() is False
    path = write_atlas_report(res, tmp_path)
    assert "What an agent should do" in path.read_text(encoding="utf-8")


def test_threshold_is_the_last_snr_before_the_first_failure():
    rows = []
    for snr, ok in ((30, True), (20, True), (15, True), (10, False), (5, True), (0, False)):
        rows.append({"lang": "hi", "kind": "id", "style": "digit words", "cond": f"fan@{snr}", "noise": "fan",
                     "snr": snr, "survived": ok, "audio_s": 3.0})
    p = summarize(rows)["policy"]["hi/id"]
    assert p["read_back_below_snr"] == 15    # 5 dB passing by luck does not lower the threshold
