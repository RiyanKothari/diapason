"""Copy the measured evidence behind the README's numbers from runs/ (git-ignored, large: audio) into results/ (committed,
small: JSON and HTML, no audio), so anyone who clones the repo can check every number without running anything.

    .venv/Scripts/python.exe scripts/export_results.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS, OUT = ROOT / "runs", ROOT / "results"
PROOF = "proof-live-4"
LABELS = {"v1_dir": "v1", "v2_dir": "v2", "guard_dir": "v1-guard", "v3_dir": "v3", "v3guard_dir": "v3-guard", "v4_dir": "v4"}
FILES = [   # (source under runs/, destination under results/, what it proves)
    (f"{PROOF}/proof.json", "proof/proof.json", "planted bugs caught, bugs gone per fix (Guard, v3, v3 + Guard, v4), QA-Bench"),
    (f"{PROOF}/proof.html", "proof/proof.html", "the same, as a page"),
    (f"{PROOF}/rating/rating.json", "rating/rating.json", "crash-test rating: five axes per agent"),
    (f"{PROOF}/rating/rating.html", "rating/rating.html", "the same, as a page with badges"),
    (f"{PROOF}/qa-bench/qa.json", "qa-bench/qa.json", "the auditor's accuracy on calls with known verdicts"),
    ("stress-v5/stress.json", "stress/stress.json", "noise breaking point per agent and noise type"),
    ("stress-v5/stress.html", "stress/stress.html", "the same, as a page"),
    ("autopilot-live-7/autopilot.json", "autopilot/autopilot.json", "red team: 12 of 12 attacks broke v2"),
    ("autopilot-live-7/replay-v3/replay.json", "autopilot/replay-v3.json", "the same 12 attacks on v3: account leaks 4 -> 0"),
    ("judge-bench.json", "judge-bench/judge-bench.json", "the judge and the code checks vs 27 hand labels on 17 live calls"),
    ("injection-bench.json", "judge-bench/injection-wording.json", "old vs new injection wording on 13 labelled calls"),
    ("asr-bench/asr_bench.json", "prisma/asr_bench.json", "Prisma character error per language and phone line (18 utterances)"),
    ("atlas/atlas.json", "atlas/atlas.json", "phone-line atlas: 3,366 Prisma transcripts of IDs, amounts and dates, noise x SNR, re-read with fixed readers"),
    ("atlas/atlas.html", "atlas/atlas.html", "the same, as a page: survival per phrasing and SNR, and what an agent should do"),
    ("digit-bug.json", "live-gnani/digit-bug.json", "Prisma's transcript of a caller's '4821', and what each digit parser makes of it"),
]
LIVE = {  # dashboard calls through real Gnani speech (Timbre voices, Prisma ears), 2 Nov
    "demo-emi-collection-20261102-020506": "v3 + Guard before the digit fix: '4821' became 'फोर थाउज़ंड एट हंडरेड ट्वेंटी वन', never verified",
    "demo-emi-collection-20261102-021747": "v4 after the fix: verified, stated the account from the record, confirmed the date",
}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    rows = []
    for src, dst, what in FILES:
        s = RUNS / src
        if not s.exists():
            print(f"missing, skipped: runs/{src}")
            continue
        (OUT / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, OUT / dst)
        rows.append((dst, what))
    tests = json.loads((RUNS / PROOF / "proof.json").read_text(encoding="utf-8"))["tests"]
    for key, name in LABELS.items():
        if tests.get(key):
            dst = f"proof/calls-{name}.json"
            shutil.copy2(RUNS / PROOF / tests[key] / "report.json", OUT / dst)
            rows.append((dst, f"every proof call of {name}: transcript, metrics, each verdict with its quote"))
    seed23 = RUNS / "proof-live-3" / "proof.json"          # the earlier QA-Bench corpus, quoted in the README
    if seed23.exists():
        (OUT / "qa-bench").mkdir(parents=True, exist_ok=True)
        qa = json.loads(seed23.read_text(encoding="utf-8"))["qa"]
        (OUT / "qa-bench/seed-23.json").write_text(json.dumps(qa, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append(("qa-bench/seed-23.json", "the auditor's accuracy on an earlier corpus (seed 23)"))
    voiced = []
    for wav in sorted(RUNS.glob("*/*/audio/*.wav")):
        if wav.parts[-4].startswith("_"):
            continue
        qa = wav.parents[1] / "qa.json"
        calls = json.loads(qa.read_text(encoding="utf-8"))["calls"] if qa.exists() else []
        c = next((c for c in calls if c["call_id"] == wav.stem), None)
        meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8")) if wav.with_suffix(".json").exists() else {}
        if c:
            voiced.append({"call": f"{wav.parts[-4]}/{wav.parts[-3]}/{wav.stem}", "lang": meta.get("lang"), "audio_s": c.get("audio_s"),
                           "score": c.get("score"), "passed": c.get("passed"), "fatal": c.get("fatal"),
                           "turns": [{k: t[k] for k in ("speaker", "text", "start", "end") if k in t} for t in c.get("turns", [])]})
    if voiced:
        (OUT / "live-gnani").mkdir(parents=True, exist_ok=True)
        (OUT / "live-gnani/voiced-calls.json").write_text(json.dumps(voiced, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append(("live-gnani/voiced-calls.json", f"{len(voiced)} QA calls voiced by Timbre over a phone line and transcribed by Prisma, with verdicts"))
    for d, what in LIVE.items():
        for f in sorted((RUNS / d).glob("*/run0/call.json")) + [RUNS / d / "report.json"]:
            if f.exists():
                dst = f"live-gnani/{d}-{f.name}"
                (OUT / dst).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, OUT / dst)
                rows.append((dst, what))
    index = ["# Results", "", "The measured evidence behind the README, copied from `runs/` by `scripts/export_results.py`.",
             "Audio is left out (size); `bhool site` keeps the showcase call's recording.", "", "| File | What it shows |", "|---|---|"]
    index += [f"| [{dst}]({dst}) | {what} |" for dst, what in rows]
    (OUT / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"{len(rows)} files, {size / 1e6:.1f} MB -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
