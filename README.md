# Bhool Bhulaiya

**Crash-testing for Indian voice agents.** Synthetic callers phone your AI agent and try to break it: an
angry uncle in Hinglish on a street line, a Gujarati aunty who is confused about the amount, the borrower's
brother fishing for details, someone who barges in, goes silent, or tries a prompt injection. Every call is
measured from the audio, judged against your SOP with quoted evidence, and rolled up into a pass/fail gate
you can put in CI. Failed real calls from production become new test cases automatically.

Built on Gnani AI: **Prisma** (speech to text), **Evon** (reasoning) and **Timbre** (text to speech).

## Why

Gnani's stack already scores real calls after they happen (Analytics) and coaches human agents live
(Assist). What's missing is testing an *AI* agent before it reaches customers, and proving a new prompt
didn't break last month's fix. English-only tools exist for this (Hamming, Coval, Cekura); none model
Indian phone reality: 8 kHz lines, code-mixing, babble noise, interruptions.

## How a test call works

```
 persona + behaviour          Evon plays the caller (knows its hidden facts and goal, not the agent's SOP)
        |
   Timbre v3.0 voice          emotion tags: <shouting> <sigh> <slow> ... ; 13 voices, 10 languages + Hinglish
        |
 telephony channel            noise at a target SNR (traffic, crowd, fan, office), clipping, 300-3400 Hz,
        |                     8 kHz G.711 mu-law, bursty packet loss, jitter underruns. Seeded, replayable
        v
 agent under test  <--------  WebSocket, 20 ms frames in real time (Twilio Media Streams semantics)
        |
 caller's ears                endpointing on played-out audio + Prisma STT -> the caller replies, or barges in
        |
 judge                        1. metrics measured from the two audio tracks (no model involved)
                              2. code checks: banned phrases, captured slots vs ground truth
                              3. Evon rubric x3 samples, majority vote, every failure must quote the
                                 transcript; an unverifiable quote becomes "review", never a silent fail
```

**Measured per call:** response latency (p50/p95), unanswered turns, dead air, talk-over, barge-ins and
whether the agent yielded, the agent cutting the caller off, abnormal endings.

**Judged per call:** disclosure, identity verification, privacy (wrong-person calls), RBI Fair Practices
conduct, factual accuracy, prompt-injection resistance, task success, language match, escalation, tone.

**Per suite:** pass rate, flaky scenarios (same scenario passing and failing across runs), a
persona x phone-line heatmap, failure ranking, HTML report with playable audio, JUnit XML for CI.

## Quick start

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Windows; use .venv/bin on Linux/macOS
bhool selftest                     # whole pipeline against a scripted fake agent: zero API credits
bhool dashboard                    # http://127.0.0.1:8000: start runs, watch calls live, open reports
```

With a Gnani key (copy `.env.example` to `.env`):

```bash
bhool plan suites/emi_collection.yaml --limit 6        # usage estimate before spending anything
bhool serve-agent --version v1                         # reference agent with 7 seeded bugs, ws://127.0.0.1:8765
bhool run suites/emi_collection.yaml --limit 6         # exit code 1 if the gate fails
bhool ingest suites/emi_collection.yaml calls/*.wav    # judge real stereo calls; failures -> suites/regressions.yaml
```

## Commands

| Command | What it does | Credits |
|---|---|---|
| `bhool validate SUITE` | check a suite, list its scenarios | none |
| `bhool plan SUITE` | upper-bound TTS chars, STT seconds, Evon calls | none |
| `bhool selftest` | full pipeline against a fake agent | none |
| `bhool run SUITE` | live run; `--limit`, `--only`, `--label v2`, `--redact`, hard caps `--max-tts-chars` / `--max-stt-seconds` / `--max-evon-calls` | yes |
| `bhool diff RUN_A RUN_B` | fixed / regressed / still failing per scenario; exit 1 on any regression | none |
| `bhool generate SOP.txt NAME` | draft a full suite from an SOP (validated, library behaviours) | 1 Evon call |
| `bhool suggest RUN SUITE` | fixes grouped by root cause, from the run's evidence | 1 Evon call |
| `bhool calibrate RUN labels.csv` | judge vs human: agreement, Cohen's kappa, missed and false fails | none |
| `bhool library` | the 15 built-in adversarial caller behaviours | none |
| `bhool ingest SUITE WAVS...` | production calls -> verdicts -> regression cases | yes |
| `bhool serve-agent --version v1\|v2` | the reference agent to test against | yes |
| `bhool dashboard` | live view and run history | per run |

**Enterprise safeguards.** Budget caps refuse an API call *before* it would cross the limit; calls cut short
are skipped (never judged) and the gate fails, so a half-run can't look green. `--redact` masks mobile
numbers, Aadhaar, PAN, account numbers and emails (Latin, Devanagari and Gujarati digits) in everything
written to disk; the dashboard redacts by default. The judge prompt fences the transcript and tells Evon
that caller lines are data, because the test callers themselves attempt prompt injection.

## Suites

A suite is YAML: the target, the agent's spec (SOP, required disclosures, banned phrases, slots to collect),
personas, behaviours and phone lines. They expand as a deterministic, sampled matrix, plus explicit
`cases` (which is how production regressions are stored). See [suites/emi_collection.yaml](suites/emi_collection.yaml).

## The reference agent

[reference_agent.py](core/bhool/reference_agent.py) is an EMI-collection agent on Prisma + Evon + Timbre.
**v1** ships with seven seeded bugs (no disclosure, debt stated before verification, threats, Hindi-only,
no injection guard, a fixed-level VAD that crowd noise defeats, no barge-in handling); **v2** fixes them.
The offline tests already show v1's VAD failing on in-band noise and ignoring barge-ins while v2 passes.

## Status, honestly

- All tests pass offline: channel simulator, metrics, schema, judge logic, the real-time call engine,
  the reference agent over a real websocket, the regression loop, budgets, redaction, diff, generation
  and calibration. All model calls are faked.
- **Not yet run against the live Gnani APIs.** The clients follow docs.gnani.ai and are tested against
  mocked responses. Results numbers (catch rate on v1's seeded bugs, v1 vs v2 pass rate, judge agreement
  with human labels) will be added here only once measured.
- Targets other than WebSocket (Twilio phone dial-out, Inya) are designed but not wired yet.

## Layout

```
core/bhool/channel/     telephony simulator and noise beds
core/bhool/caller/      the synthetic caller: brain (Evon), mouth (Timbre + channel), ears (endpointing)
core/bhool/call/        transport protocol and the real-time call engine
core/bhool/judge/       audio metrics and the rubric judge
core/bhool/regress.py   production calls -> regression cases
core/bhool/runner.py    suite execution, aggregation, usage accounting
core/bhool/server.py    dashboard API + live event stream; static/index.html is the UI
ci/                     the pull-request gate for an agent's own repo
```
