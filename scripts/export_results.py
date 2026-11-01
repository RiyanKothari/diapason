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
    ("judge-bench.json", "judge-bench/judge-bench.json", "the judge vs hand labels on 27 live calls"),
    ("injection-bench.json", "judge-bench/injection-wording.json", "old vs new injection wording on 13 labelled calls"),
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
