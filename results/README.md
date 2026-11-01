# Results

The measured evidence behind the README, copied from `runs/` by `scripts/export_results.py`.
Audio is left out (size); `bhool site` keeps the showcase call's recording.

| File | What it shows |
|---|---|
| [proof/proof.json](proof/proof.json) | planted bugs caught, bugs gone per fix (Guard, v3, v3 + Guard, v4), QA-Bench |
| [proof/proof.html](proof/proof.html) | the same, as a page |
| [rating/rating.json](rating/rating.json) | crash-test rating: five axes per agent |
| [rating/rating.html](rating/rating.html) | the same, as a page with badges |
| [qa-bench/qa.json](qa-bench/qa.json) | the auditor's accuracy on calls with known verdicts |
| [stress/stress.json](stress/stress.json) | noise breaking point per agent and noise type |
| [stress/stress.html](stress/stress.html) | the same, as a page |
| [autopilot/autopilot.json](autopilot/autopilot.json) | red team: 12 of 12 attacks broke v2 |
| [autopilot/replay-v3.json](autopilot/replay-v3.json) | the same 12 attacks on v3: account leaks 4 -> 0 |
| [judge-bench/judge-bench.json](judge-bench/judge-bench.json) | the judge vs hand labels on 27 live calls |
| [judge-bench/injection-wording.json](judge-bench/injection-wording.json) | old vs new injection wording on 13 labelled calls |
| [proof/calls-v1.json](proof/calls-v1.json) | every proof call of v1: transcript, metrics, each verdict with its quote |
| [proof/calls-v2.json](proof/calls-v2.json) | every proof call of v2: transcript, metrics, each verdict with its quote |
| [proof/calls-v1-guard.json](proof/calls-v1-guard.json) | every proof call of v1-guard: transcript, metrics, each verdict with its quote |
| [proof/calls-v3.json](proof/calls-v3.json) | every proof call of v3: transcript, metrics, each verdict with its quote |
| [proof/calls-v3-guard.json](proof/calls-v3-guard.json) | every proof call of v3-guard: transcript, metrics, each verdict with its quote |
| [proof/calls-v4.json](proof/calls-v4.json) | every proof call of v4: transcript, metrics, each verdict with its quote |
| [live-gnani/demo-emi-collection-20261102-020506-call.json](live-gnani/demo-emi-collection-20261102-020506-call.json) | v3 + Guard before the digit fix: '4821' became 'फोर थाउज़ंड एट हंडरेड ट्वेंटी वन', never verified |
| [live-gnani/demo-emi-collection-20261102-020506-report.json](live-gnani/demo-emi-collection-20261102-020506-report.json) | v3 + Guard before the digit fix: '4821' became 'फोर थाउज़ंड एट हंडरेड ट्वेंटी वन', never verified |
| [live-gnani/demo-emi-collection-20261102-021747-call.json](live-gnani/demo-emi-collection-20261102-021747-call.json) | v4 after the fix: verified, stated the account from the record, confirmed the date |
| [live-gnani/demo-emi-collection-20261102-021747-report.json](live-gnani/demo-emi-collection-20261102-021747-report.json) | v4 after the fix: verified, stated the account from the record, confirmed the date |
