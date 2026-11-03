# Demo kit: 60-second video, walkthrough, posts

Every number here is copied from README "Results and limitations" and backed by a file in [results/](../results/). If a new
run changes a number, change it in the README first, then here. No real company names anywhere: industries and fictional
brands only. Never show the Kaggle notebook's output on screen (it prints the Evon key).

## Numbers to quote (and only these)

| Say | Source |
|---|---|
| The tests caught all 7 bugs planted in an agent (8 of 8 test cases) | results/proof/proof.json |
| The same buggy agent behind Diapason Guard, prompt unchanged: 4 of 6 text bugs prevented (judge); every code check passes on all 6 | results/proof/proof.json (guard) |
| 98% of loan IDs, amounts and dates survive Timbre → noisy phone line (30-0 dB) → Prisma, across 3,366 transcripts | results/atlas/atlas.json |
| Taking the secret out of the model: account leaks across 12 attacks fell from 4 to 0 | results/autopilot/replay-v3.json |
| v4, where the model picks the act and code speaks the facts, passed 5 of 6 test calls; every earlier version 0 | results/proof/calls-v4.json |
| The fixed agent hears callers down to 0 dB SNR; v1 stopped at 10-20 dB | results/stress/stress.json |
| The auditor, on calls it never saw: 93.6% of 560 verdicts right, every fatal breach caught, no false fatal alarms | results/qa-bench/qa.json, results/proof/proof.json (qa) |
| Prisma on a 5 dB crowded-market phone line: 5.5% character error (1.4% clean) | README asr-bench |

Say "measured on Evon-played test calls over a simulated phone line" once, on screen or in the caption. Don't use the star
ratings in the video (they need explaining), "under a millisecond" (the live figure is about 1 ms), or any language beyond
Hindi, Hinglish, Gujarati and English.

## The film: record the demo instead of editing it

`diapason site`, then open `site/watch.html` (or `/watch` on `diapason dashboard`). It is about two minutes, 16:9, and every
scene is drawn from run files: the live v1 call with its own audio and the threat flagged as it is said, 8 / 8 planted-bug
tests, Guard's rewrites, v1 → v4, the atlas, the noise sweep, QA accuracy. Press R (or open `watch.html?record`) to hide the
controls, full-screen it, and screen-record with system audio. For a 60-second cut, record the call, Guard, v1 → v4 and the
end card (`?scene=call`, `?scene=guard`, `?scene=versions`, `?scene=outro` jump straight to them). Captions are in the
picture already.

## 60-second video: one story

| Time | Screen | Caption / voice-over |
|---|---|---|
| 0-5 s | A phone waveform, then the showcase title | "Before your AI agent talks to a million Indians, crash-test it." |
| 5-17 s | Showcase replay, left side: v1 says "वरना legal action होगा" to Ramesh; red flags appear with the quote | "A synthetic customer calls. The agent threatens him and states his debt before checking who he is. Every flag quotes its words." |
| 17-27 s | Right side: the same agent behind Guard; the threat is crossed out, the verification question appears instead | "Same agent, prompt untouched, behind Diapason Guard: every sentence checked in code before it's spoken. Every code check passes on all 6 text bugs." |
| 27-35 s | Autopilot replay: 12 attacks, leaks 4 → 0 | "An AI red team attacked it 12 ways. Taking the secret out of the model: leaks 4 → 0." |
| 35-46 s | Live dashboard call: the caller says 4821, Prisma's transcript "फोर थाउज़ंड एट हंडरेड ट्वेंटी वन", then v4 verifying | "Then a live call found what no offline test could: Prisma writes '4821' as English words in Devanagari. Fixed, and v4 verifies first try." |
| 46-54 s | Noise sweep grid: v1 red from 10-20 dB, fixed agent green to 0 dB | "Fan, office, crowd: the fixed agent hears the caller down to 0 dB. v1 stopped at 10-20." |
| 54-60 s | Logo line and link | "Built on Gnani: Prisma hears, Timbre speaks, Evon calls, guards and judges." |

Shots (all exist): the showcase (`diapason site`, then open `site/index.html`), `results/live-gnani/` call for the transcript,
the dashboard (`diapason dashboard`) for a live take, `site/autopilot/autopilot.html`, `site/stress/stress.html`.
Burn the captions in: most people watch muted.

## The link to share

`diapason site` builds the showcase; deploy `site/` (Vercel or a `gh-pages` branch) and put the link in the post, the
written explanation and the README. The submission form has no repo field, so the link in the post is how a reviewer finds
the evidence.

## 3-minute walkthrough (for the submission)

1. The gap (20 s): voice agents are tested by people making test calls; nothing tests them the way Indian customers call.
2. Before launch (40 s): personas x behaviours x phone lines, the live view, the report, the CI gate, the red team.
3. During the call (40 s): Guard on v1; secret isolation (v3); v4, where the model picks the act and code speaks the facts.
4. How we know (50 s): the proof table, QA-Bench, the judge measured against my labels on live calls (and where it is weak:
   it misses most privacy leaks, which a code check catches), the live digit bug.
5. Next (30 s): an Inya-built agent tested black-box, real phone calls, labels from someone other than me.

## LinkedIn post (draft)

> Voice AI in India gets tested by people making test calls. Real customers call from a noisy shop, switch to Gujarati
> mid-sentence, interrupt, or hand the phone to their brother.
>
> So I built Diapason on Gnani's Prisma, Timbre and Evon: synthetic Indian callers that crash-test a voice agent before
> launch, a guard that checks every sentence before the agent speaks it, and an auditor that quotes the agent's own words.
>
> Measured, on Evon-played test calls over a simulated phone line:
> • All 7 bugs I planted in an agent caught. Behind the guard, prompt untouched, every code check passes on all 6 text bugs.
> • 12 red-team attacks: account leaks 4 → 0 once the secret was taken out of the model.
> • An agent where the model picks the move and code speaks every fact: 5 of 6 test calls passed, every earlier version 0.
> • Fan, traffic, office and crowd noise: the fixed agent hears the caller down to 0 dB.
>
> The best bug came from a live call: Prisma writes "4821" as "फोर थाउज़ंड एट हंडरेड ट्वेंटी वन", so no caller could
> ever verify. What didn't work (and where my own judge is weak) is in the README too.
>
> 60-second demo below. #GreatIndianAIInternshipChallenge #GnaniAI

## X post (draft)

> Built a crash-test lab for Indian voice agents on Gnani's Prisma + Timbre + Evon: synthetic callers in Hindi, Hinglish and
> Gujarati on noisy lines, a guard that checks every sentence before it's spoken, an auditor that quotes the agent.
> An agent where the model picks the move and code speaks the facts: 5/6 test calls passed, every earlier version 0. Demo 👇 #GnaniAI #GreatIndianAIInternshipChallenge

Handles and hashtags: confirm Gnani's exact handles on LinkedIn and X before posting. Organic engagement only; the rules
disqualify engagement swaps and paid boosts.
