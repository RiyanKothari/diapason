# Architecture

## One test call

```
Scenario = persona × behaviour × channel × seed
   │
   ├─ caller/brain.py    Evon role-plays the persona (hidden facts, goal, language, emotion tags)
   ├─ caller/mouth.py    Timbre speech → normalised to −20 dBFS → mixed with the line's noise bed →
   │                     channel/sim.py (gain/clip, 300–3400 Hz, 8 kHz μ-law, Gilbert–Elliott loss,
   │                     jitter underruns) → a continuous outgoing stream, noise included between turns
   ├─ call/engine.py     one 20 ms clock: send 1 caller frame, play out 1 agent frame (agents may send
   │                     faster than real time; a phone line plays at real time) → tracks sample-aligned
   │                     by construction; barge-in and silence behaviours scheduled here
   ├─ caller/ears.py     endpointing on what has been *played*, so the caller replies when the agent
   │                     has actually finished; Prisma transcribes each agent turn
   └─ call/transport.py  WebSocket protocol mirroring Twilio Media Streams (start / audio / clear /
                         disposition / hangup), so a telephony bridge maps one-to-one
```

## Judging, in order of trust

1. **Measured** (`judge/metrics.py`): VAD on the agent track; caller intervals are ground truth from
   rendering. Latency p50/p95, unanswered turns, dead air, overlap, barge-ins and yield time, agent
   cutting the caller off. No model involved.
2. **Checked in code** (`judge/rubric.code_checks`): banned phrases (token-padded, Indic-safe),
   captured slots vs the persona's hidden truth (format-tolerant: "15 Nov" = "15 November").
3. **Judged by Evon** (`judge/rubric.py` + `judge/packs.py`): k samples → majority per criterion with
   agreement; every fail must quote the transcript and the quote is verified (fuzzy, STT-tolerant);
   unverifiable fails become `review`, which still blocks a critical criterion. The transcript is
   fenced and declared as data, because the test callers attempt prompt injection.

A call passes only if no critical criterion fails or needs review and no metric breaches the gate.

## Suite → report

`runner.py` expands the suite (explicit `cases` first, then a seeded sample of the matrix), runs calls
concurrently under a hard budget, judges each, and aggregates: pass rate, flakiness (same scenario
passing and failing across runs), persona × line heatmap, failure ranking. `report.py` writes HTML
(with audio) and JUnit XML. `diff.py` compares runs; `regress.py` turns failed production calls into
cases; `advise.py` suggests fixes and calibrates the judge against human labels.

## Design choices worth defending

- **Determinism.** Every random choice is seeded from the scenario id, so a failing call can be
  replayed bit-for-bit: same noise, same packet loss, same barge-in timing.
- **Ground truth over inference.** The harness rendered the caller, so caller timing is known, not
  estimated; slot checks use the persona's hidden facts, not the judge's opinion.
- **A judge that can say "I don't know".** `review` exists so an LLM's unverifiable claim never
  silently becomes a pass or a fail.
- **Zero-credit paths everywhere.** Fakes (`fakes.py`) stand in for every model, including a
  ToneCodec that round-trips text through audio, so the full pipeline is testable offline.
