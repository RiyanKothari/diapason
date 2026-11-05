# Submission text (Great Indian AI Internship Challenge)

Ready to paste into the participant workspace. Every number matches README "Results and limitations" and `results/`.
Fill the three post links once the posts are live.

## Project title

Diapason: crash-tests, a live guard and QA for Indian voice agents

## Problem

AI voice agents for Indian customers are tested by people making a handful of test calls. Real callers phone from a noisy
shop, mix Hindi and English, switch to Gujarati, interrupt, go silent, hand the phone to a brother, or try to talk the agent
out of its rules. Failures that reach customers here are compliance failures: an agent that threatens, states a debt to the
wrong person, or reads out account details breaks RBI fair-practice rules. Nothing tests agents the way Indian customers call,
nothing stops a violation in the moment, and after-call QA rarely says how accurate it is.

## Target users

Teams that build or run AI voice agents for Indian customers: lenders and collections, insurers, telecom and support
centres, and the delivery teams of voice-AI platforms who launch agents for them.

## Gnani models and APIs used

- **Prisma (speech-to-text, v3 REST):** the synthetic caller's ears on every live call, transcribing the agent over an 8 kHz
  phone line; transcribing recorded calls for QA; and the agent's own ears in the reference agents. Measured on phone audio:
  1.4% character error on a clean line, 5.5% on a 5 dB crowded-market line; in the phone-line atlas, 3,366 transcripts of IDs,
  amounts and dates through four noises at 30-0 dB.
- **Timbre (text-to-speech, v3.0):** the voices of the synthetic callers (13 voices, emotion tags such as shouting or slow,
  Hindi, Hinglish, Gujarati, Tamil, Marathi, Telugu, Kannada, English) and of the reference agents.
- **Evon v3.3 (LLM, open weights, self-hosted on a free Kaggle GPU):** plays each caller's mind (persona, hidden facts,
  goal), plays the agent under test, judges every call against the rules with quoted evidence, red-teams the agent by
  designing new attacks, translates Guard's lines, and picks v4's dialogue acts.

## Contribution

Solo: Riyan Kothari. Design, code, test suites, live runs and measurements.

## Written explanation

Diapason covers a voice agent's whole life. **Before launch**, synthetic Indian callers phone the agent in real time
through a simulated phone line (8 kHz μ-law, fan, traffic, office and crowd noise at a set signal-to-noise ratio, packet
loss) and try to break it: an angry Hinglish caller, a Gujarati-only aunty, the borrower's brother, barge-ins, silence,
prompt injection. Every call is measured from the audio (latency, unanswered turns, barge-in handling) and judged against
the agent's rules; every fail must quote the agent's own words. **During the call**, Diapason Guard checks each sentence in
code before it is spoken (about 1 ms a line): it drops threats, holds account details until the caller has verified, adds
the recording disclosure and translates a reply in the wrong language. **After the call**, an auditor scores recorded calls
against industry scorecards.

To know whether it works, I planted 7 bugs in a reference collections agent (v1) and measured, on live test calls where
Evon plays the agent, callers and judge:

- the tests caught all 7 (8 of 8 test cases; one bug is tested on two callers);
- the same buggy agent behind Guard, prompt unchanged: all 6 of its text bugs prevented;
- an AI red team broke the fixed agent (v2) with 12 of 12 attacks; once the secret was taken out of the model (v3), account
  leaks across the same 12 attacks fell from 4 to 0;
- v4, where the model picks a dialogue act and code speaks every fact from the account record, removed all 6 text bugs and
  passed 5 of 6 test calls on every check (v1 and v2 passed none);
- the fixed agent hears callers through all four noises down to 0 dB; v1 stops at 10-20 dB;
- the auditor, on calls it never saw: 93.6% of 560 verdicts right, every fatal breach caught, no false fatal alarms;
- a phone-line atlas of 3,366 real Prisma transcripts (loan IDs, amounts and dates in Hindi, Gujarati and English, spoken by
  Timbre through four noises from 30 dB to 0 dB): 98% of details survive, and it tells an agent which way to say each one
  and when to read it back (Gujarati IDs below 10 dB).

The most useful bug came from a live call: Timbre read "4821" aloud as a number and Prisma wrote it as English words in
Devanagari ("फोर थाउज़ंड एट हंडरेड ट्वेंटी वन"), so no caller could ever verify. Now the parser reads digits the way Indian
callers say them (pairs, "double", whole numbers), and the same call verifies first try. On 5 Nov the same readers learned
Tamil, Marathi, Telugu and Kannada: measured first, because Prisma writes no numerals in those languages, they went from 1 of
28 live transcripts to 28 of 28, and 24 of 24 on a held-out set written afterwards.

What is weak is written down too: on its own the Evon judge both misses and invents privacy failures, so on privacy and
verification a judge fail now stands only when a code check finds the leak in the agent's words (7 of 7 leaks, 0 of 9 clean
calls failed, on 45 hand labels); my labels are the only human labels so far, and the Inya and phone-number targets (an Inya agent built from the SOP calls Diapason's number; Diapason scores
each side's speech recognition against the other side's words) run end to end offline but have not yet been run live. Customers and lenders in every test are
synthetic and fictional.

## Links

- Demo video: (link)
- LinkedIn post: (link)
- X post: (link)
- Showcase and evidence: https://diapason-mu.vercel.app (the repository is private; code available to Gnani on request)
