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
bhool demo                         # reference agent v1 (seeded bugs) vs v2, full harness, diff. Zero credits
bhool dashboard                    # http://127.0.0.1:8000: start runs, watch calls live, open reports
```

What `bhool demo` shows, measured on this machine: v1 fails all 4 calls on its seeded bugs (police
threat, missed loan ID, ignored barge-in, silence on a crowded line); v2 fixes both landline calls
(0% → 100%) and the tool **still flags v2 on the 5 dB crowded-market line**, where energy-based
endpointing can't separate the caller from babble. That last finding is the point: it's real, and it's
what you'd fix next (Prisma's streaming VAD).

Docs: [how each Gnani model is used](docs/GNANI.md) · [architecture](docs/ARCHITECTURE.md)

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
| `bhool demo` | v1 vs v2 reference agent through the full harness, with diff | none |
| `bhool asr-bench` | Prisma CER per language × phone line on Timbre speech with known text | STT + cached TTS |
| `bhool load SUITE --levels 1,4,8,16` | latency and pass rate vs simultaneous calls (`--offline` for none) | per call |
| `bhool schema` | suite JSON Schema for editor autocomplete | none |
| `bhool ingest SUITE WAVS...` | production calls -> verdicts -> regression cases | yes |
| `bhool serve-agent --version v1\|v2` | the reference agent to test against | yes |
| `bhool dashboard` | live view, run history and QA audits | per run |
| `bhool qa audit SCORECARD CALLS...` | QA audit of real calls (see below); `--offline`, `--labels`, `--baseline`, `--to-regressions` | Evon; STT for audio only |
| `bhool qa template SUITE` | a ready scorecard from a suite's agent spec and rubric pack | none |
| `bhool qa bench` | the auditor's own accuracy on calls with known verdicts | Evon (`--offline`: none) |
| `bhool qa simulate [SCORECARD...]` | QA-Bench for **every segment**: Evon writes calls with planted defects from each scorecard; `--voice-calls N` speaks them with Timbre over a phone line and transcribes with Prisma first | Evon; Timbre + Prisma for voiced calls (capped) |
| `bhool playbooks list\|build` | one tailored QA scorecard + adversarial test suite **per industry** (22 voice-AI verticals) from `playbooks/industries.yaml` | none |
| `bhool dashboard` → `/studio` | **QA Studio**: segment tiles, a parameter × call heatmap, every verdict with its quote, click to hear the moment | none |
| `bhool proof` | **one accuracy page**: planted bugs caught by the tests (v1 vs fixed v2) + QA-Bench; Evon plays agent, callers and judge over simulated phone audio | Evon only, no Gnani credits |
| `bhool autopilot --agent v2` | **red team + self-repair**: Evon designs attack callers, breeds new ones from what broke the agent, saves every hit as a regression suite, then patches the prompt and keeps only fixes that a re-run proves (fixed ≥ 1, broke 0) | Evon only, no Gnani credits |

**Rubric packs** (`rubric:` in a suite): `general`, `bfsi_collections` (RBI Fair Practices Code),
`insurance` (IRDAI), `healthcare`, `telecom` (TRAI), `kyc`.

**Enterprise safeguards.** Budget caps refuse an API call *before* it would cross the limit; calls cut short
are skipped (never judged) and the gate fails, so a half-run can't look green. `--redact` masks mobile
numbers, Aadhaar, PAN, account numbers and emails (Latin, Devanagari and Gujarati digits) in everything
written to disk; the dashboard redacts by default. The judge prompt fences the transcript and tells Evon
that caller lines are data, because the test callers themselves attempt prompt injection.

## Quality audits of real calls

Testing asks "will this agent survive real callers?" before launch; `bhool qa audit` asks "how did every
real call go?" after, for AI and human agents alike. It reads dual-channel recordings (Prisma transcribes
them), or transcripts as JSON, JSONL, CSV or text (no STT credits), or Bhool's own test runs.

A **scorecard** ([scorecards/emi_collections.yaml](scorecards/emi_collections.yaml)) is the weighted QA form
a contact-centre QA team fills in by hand, made executable. Each parameter has a weight, may be *fatal*
(a fail zeroes the call), and one check:

| Check | Decided by | Example |
|---|---|---|
| `phrase_present` / `phrase_absent` | code, with native-script loanword spellings (`police` = पुलिस = પોલીસ) | recording disclosure; no threats |
| `order` | code | identity verified *before* the amount is said |
| `metric` | code, from audio or a timed transcript | `latency_p95_s <= 2.5`, `agent_cut_off_caller == 0`, `agent_talk_ratio <= 0.65` |
| `slot` | code, against the CRM when given | promise-to-pay date captured and correct |
| `llm` (yes/no or 1..N scale) | Evon, k samples, majority vote, quotes verified against the transcript | no harassment, hardship handled, tone |

Per call: score, section scores, fatal errors, every verdict with a quoted, timestamped line, talk
analytics (talk ratio, words per minute, silence, longest monologue, script mix), and Evon insights
(summary, disposition, extracted entities, caller sentiment over the call, root cause, coaching tied to
the turn). Per batch: leaderboards and parameter heatmaps by agent and campaign, the most common reasons for
each failing parameter with examples, dispositions, topics, sentiment shift, drift against a previous
audit (`--baseline`), agreement with human QA labels (`--labels`: agreement, Cohen's kappa, fail
precision and recall), and a **human review queue**. A judge fail whose quote isn't in the transcript, a split
vote or a borderline score goes to a person instead of being guessed. Fatal calls can become regression
tests (`--to-regressions`). Outputs: `qa.html`, `qa.json`, `calls.csv` (Excel-safe), PII redacted by default.

**Seven segments, ready to run** ([scorecards/](scorecards)): EMI collections (RBI Fair Practices Code), insurance
renewal & sales (IRDAI), healthcare appointments (clinical safety, DPDP), telecom support & offers (TRAI), banking fraud
helpline (RBI customer liability), e-commerce order support (Consumer Protection E-Commerce Rules), KYC & onboarding
(RBI KYC, Aadhaar Act). Each has 13-15 parameters, 3-5 fatal compliance rules, and every check type. Banned phrases match
the *request* ("CVV बताइए"), not the warning ("never share your CVV"), so a good agent isn't failed for doing its job.

**QA Studio** (`bhool dashboard`, then `/studio`): pick a segment; see every parameter of every call as a heatmap (planted
defects outlined); open a call to read it as a chat with flagged turns, the scorecard with each verdict's reason, agreement
and quote, Evon's summary, sentiment curve, root cause and coaching. For recordings, a timeline marks each failure: click a
verdict and the audio jumps to that moment.

**Industry playbooks** (`bhool playbooks build`): 22 verticals where Indian enterprises run voice AI: public-sector and small
finance bank collections, bank customer service, rural farm and two-wheeler loans, consumer-durable loans, microfinance, housing
finance, digital lending and BNPL, insurance renewals and claims, airline disruptions, vacation memberships, automotive service and
roadside assistance, US clinic reminders, outsourced multilingual support, appliance service, matchmaking memberships, an
engineering firm's IT helpdesk and Indic-software support. Each names the use case, its customers' languages (Tamil, Kannada,
Marathi, Malayalam, Telugu, Bengali, Punjabi, Gujarati...), the rules that bind it, and realistic callers (a farmer paying after
harvest, a Gulf worker's wife with an infant on a cancelled flight, a borrower's husband answering her phone). Rules come from a
shared library of 38: RBI collections conduct and recovery-agent norms, Digital Lending Guidelines (no threats to phone contacts,
KFS and cooling-off), the microfinance directions (no coercion, no public shaming), no prepayment charge on floating-rate home
loans, IRDAI mis-selling and free-look, DGCA passenger rights (refund, not a forced credit shell), HIPAA minimum necessary and
TCPA opt-out, PCI DSS, TRAI DND. The builder writes `scorecards/industries/<id>.yaml` and `suites/industries/<id>.yaml`; the QA
Studio shows them as tiles. Brands are fictional.

**QA across segments** (`bhool qa simulate`): no other segment has hand-built test calls, so Evon writes them from the
scorecard: first a clean, compliant call, then each defect planted as its own targeted edit (replace or insert one agent line,
with a customer line that sets up the situation when needed). The exact planted line is kept as ground truth and shown in the
Studio. Code-checked defects are verified in code, with one retry; anything that still disagrees with the plan is excluded,
never silently counted. (Asking a model to write a call that breaks rules X and Y in one go doesn't work: in our first live run
it quietly wrote compliant agents, and the "misses" were the writer's, not the auditor's.) With `--voice-calls`, calls are spoken by
Timbre, sent through the phone-line simulator and transcribed by Prisma, so the audit runs on real ASR output. Headline:
planted-defect recall; fails on parameters neither planted nor declared are reported as *unplanted flags*, an upper bound on
false alarms.

**Measured on live Evon (29 Oct):** 22 industry playbooks x 4 calls and 7 segments x 6 calls, 1 call per industry voiced
(Timbre, phone line, Prisma; 8,951 TTS characters and 709 s of STT for 7 voiced calls). The auditor failed 98 of 190 defects Evon
claimed to have planted (52%), sent 4 more to review, flagged 8-10% of parameters that were neither planted nor declared, and
zeroed 13 of 76 calls written as clean. **This is not the auditor's accuracy.** In a spot check of 14 random misses, 11 were planted
lines that do not actually break the rule (a "doesn't name the company" line that names it, a "no reference number" line that gives
one), 1 was a planter mix-up and 2 were real auditor misses (medicine advice passed; a language mismatch sent to review). Evon is a
weak defect planter even with a separate confirmation step, so these runs are realistic test calls for every industry and a lower
bound; the auditor's accuracy is QA-Bench below, where truth is built in code.

**QA-Bench** (`bhool qa bench`) measures the auditor itself. Vendors publish coverage ("100% of calls
audited"), not accuracy. The bench builds collections calls whose correct verdict on every parameter is
known by construction (missed disclosure, verification out of order, threats, privacy leaks to a family
member, pushy hardship handling, Gujarati caller answered in Hindi, slow or talk-over timing), in Hindi and
Gujarati, half in the script Prisma actually produces. It reports per-parameter accuracy and fail
precision/recall, pass/fail decision accuracy, fatal-error recall and score error.

Measured on live Evon v3.3 (3 judge samples per parameter), on a 40-call corpus (seed 23) generated *after* the judge prompts
were last changed, so it was never tuned on:

| QA-Bench, 40 calls, unseen seed | Verdict accuracy | Notes |
|---|---|---|
| Code-checked parameters (7) | 99.6% | phrases, order, slot, timing metrics |
| Evon-judged parameters (7) | 81.1% | strong: lender named 100%, hardship 100%, privacy 93%, harassment 90%; weak: tone 80%, language match 75%, **confirms-back 30%** |
| All 560 verdicts | 90.4% | fail precision 78%, fail recall 94% |
| Pass/fail decision per call | 92.5% | fatal-error recall **100%**, false fatal alarms **0** |

Confirms-back (did the agent repeat the agreed date) is the auditor's weak spot: Evon misreads a bare "ok" vs. a read-back in
mixed script. It is reported, not hidden; the next step is to make it a code check against the extracted date.

## Autopilot: bugs nobody planted

Seeded bugs prove the harness catches what you already suspect. `bhool autopilot` goes after what you don't:

1. **Hunt.** Evon, as a red team, reads the agent's SOP and designs attack callers: who calls (the borrower, a
   brother, someone claiming to be from the bank or the police), what they want, how they behave, in which
   language and on which phone line. Key attack lines are pinned so the caller can't drift out of the attack.
   Each generation is run through the real harness and judged with evidence; the next generation varies the
   attacks that broke the agent (is it real? where are its edges?) and probes rules nobody has broken yet.
2. **Remember.** Every attack that broke something is written to `autopilot_regressions.yaml`: a bug found
   once is tested on every future version.
3. **Heal.** Evon proposes new prompt rules (and a new opening line if that is the problem). The patched agent is
   re-run on the attacks *and* the original suite; a patch is kept only if it fixes at least one failure and
   breaks nothing that passed. Endpointing, barge-in and latency failures are listed as engineering work, since
   no prompt fixes those.

Output: `autopilot.html` with every attack, the judge's quoted evidence, the rules added and before/after.

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

- **Offline:** 130+ tests pass with every model faked: channel simulator, metrics, judge logic, the real-time call engine,
  the reference agent over a real websocket, regression loop, budgets, redaction, autopilot, simulation, playbooks, dates.
- **Live Gnani APIs, capped runs:** `bhool doctor --live` passes on Timbre, Prisma and self-hosted Evon v3.3.
  Prisma on Timbre speech (`asr-bench`): 1.4% CER on a clean line, 5.5% on a 5 dB market line, 89-100% of critical
  details kept. 7 calls voiced end to end (Timbre, phone line, Prisma) across industries.
- **The auditor (QA-Bench on live Evon, unseen corpus):** 90.4% of 560 verdicts right, fatal-error recall 100%, no false
  fatal alarms, 92.5% of pass/fail decisions right. Its weakest Evon parameter (confirms-back, 30%) is now a code check:
  100% on three corpora (seeds 7, 11, 23), offline.
- **The tests (`bhool proof`, live Evon, best run):** 7 of 8 seeded bugs caught. Two v2 flags: one a real v2 slip (it told the
  borrower's brother there is a loan due), one a judge error since closed (fails must now be proven by the agent's own words).
- **Simulated calls for every industry:** see "Measured on live Evon" above; useful test calls, not an accuracy number.
- **Autopilot (hunt + heal):** built and tested offline; both live runs were cut short by Evon going offline mid-run, and those
  results were discarded (the harness now detects that and refuses to count harness failures as agent bugs). A clean live run
  is pending.
- **Not done:** judge agreement with human labels on real calls (the tooling exists: `--labels`); Twilio and Inya targets.

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
