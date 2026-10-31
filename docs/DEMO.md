# Demo kit: 60-second video, walkthrough, posts

Every number below is measured (see README "Status, honestly"). Re-check them against the latest `runs/` before recording;
if a run changes a number, change it here first. No real company names anywhere: industries and fictional brands only.

## 60-second video

| Time | Screen | Voice-over (or captions) |
|---|---|---|
| 0-5 s | Black, then a phone waveform | "Before your AI agent talks to a million Indians, it has to survive these callers." |
| 5-15 s | Dashboard live view: a Gujarati caller on a noisy line, transcript and per-turn latency ticking, a red flag | "Bhool Bhulaiya calls your agent like real Indian customers do: Gujarati, Hinglish, fan noise, interruptions, someone's brother picking up." |
| 15-25 s | The flag opens: the agent's exact words, quoted, timestamped | "Every failure comes with the agent's own words as proof. No quote, no fail: it goes to a human instead." |
| 25-35 s | QA Studio: industry tiles, then the parameter × call heatmap; click a red cell, the audio jumps to that moment | "The same auditor scores real calls for 22 industries: collections, microfinance, airlines, clinics. Click a verdict, hear the moment." |
| 35-45 s | Proof page: QA verdict accuracy 90%, fatal-error recall 100%, 0 false fatal alarms | "And we measured the auditor: on calls it had never seen, it caught every fatal compliance breach with zero false alarms." |
| 45-52 s | Proof table, third column "v1 + Guard": the same buggy agent, prompt untouched, with Guard; a crossed-out line "वरना legal action होगा" replaced live | "Then we stopped testing after the fact. Guard checks every sentence before the agent says it, in under a millisecond: the threat never reaches the customer." |
| 52-55 s | Crash-test rating badges: v1 ★, v1 + Guard ★★★, v2 ★★★★ | "And every agent gets a crash-test rating, from measured calls." |
| 55-60 s | Logo line | "Built entirely on Gnani: Prisma hears, Timbre speaks, Evon thinks and judges." |

Shots to capture (all exist today): dashboard live run (`bhool dashboard`, run `suites/demo.yaml` offline for a clean take),
`/studio` with a voiced call selected, `runs/proof-live-3/proof.html`, `runs/industries-live-2/segments.html`.

## The link to share

Build the showcase after the latest live run (`bhool site`) and deploy `site/` (`npx vercel site --prod` or a `gh-pages`
branch). Put that link in the post and the submission: judges can open the proof, the Studio and the voiced calls without
installing anything.

## 3-minute walkthrough (for the submission)

1. The gap (20 s): voice agents are tested by people making test calls; nothing tests them the way Indian customers call.
2. Test before launch (50 s): suite YAML, personas x behaviours x phone lines, the live view, the report, the CI gate.
3. Audit after launch (50 s): QA Studio, scorecards per industry with their regulations, evidence, review queue, coaching.
4. How we know it works (40 s): `bhool proof` and QA-Bench, the measured numbers, and what failed and how we fixed it
   (the judge citing the caller's words; dates now checked in code).
5. What's next (20 s): human-labelled calibration on real calls, phone and Inya targets, autopilot repair loop live.

## LinkedIn post (draft)

> Voice AI in India is tested by people making test calls. Real customers call from a fan-noisy shop in Surat, switch to
> Gujarati mid-sentence, interrupt, or hand the phone to their brother.
>
> So I built Bhool Bhulaiya: synthetic Indian callers that phone a voice agent before launch, and an auditor that scores
> every real call after it, on Gnani's stack: Prisma (speech-to-text), Timbre (voices) and Evon (the callers' and the judge's brain).
>
> What I measured, not claimed:
> • On calls the auditor had never seen: 90% of verdicts right, 100% of fatal compliance breaches caught, 0 false fatal alarms.
> • 7 of 8 bugs I planted in a test agent caught, plus one I didn't plant: the "fixed" agent told a borrower's brother about the loan.
> • 22 industry playbooks (collections, microfinance, airlines, clinics, BNPL...) with their regulations: RBI, IRDAI, DGCA, TRAI, HIPAA.
> • Every fail cites the agent's own words. No quote, no fail: it goes to a human.
>
> What didn't work first time is in the README too.
>
> 60-second demo below. Built for the #GreatIndianAIInternshipChallenge by @Gnani.ai #GnaniAI

## X post (draft)

> Built a crash-test lab for Indian voice agents on @Gnani_ai's Prisma + Timbre + Evon: synthetic callers in Hindi, Gujarati,
> Tamil on noisy lines, and an auditor that quotes the agent's own words for every fail.
> Measured on unseen calls: 90% verdicts right, 100% fatal breaches caught, 0 false fatal alarms. Demo 👇
> #GnaniAI #GreatIndianAIInternshipChallenge

Handles and hashtags: confirm the exact Gnani handles on LinkedIn and X before posting. Organic engagement only; the rules
disqualify engagement swaps and paid boosts.
