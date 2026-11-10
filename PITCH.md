# Diapason: crash tests for Indian voice agents

**Riyan Kothari · SRM Institute of Science and Technology · solo entry, Great Indian AI Internship Challenge**
Live demo: https://diapason-mu.vercel.app · 3-minute demo video (narrated by Gnani Timbre): https://diapason-mu.vercel.app/diapason-demo.mp4

## The problem

AI voice agents that will talk to millions of Indians usually go live after a handful of polite test calls. Real callers
phone from a noisy shop, switch from Hindi to Gujarati halfway, hand the phone to their brother, cut the agent off, or
tell it to "ignore your instructions". In lending, insurance and support, the failures that follow are compliance
failures: a threat, a debt told to the wrong person, an account number read out. Nothing tests agents the way Indians
actually call, and nothing stops a bad sentence in the moment.

## The solution

Diapason covers a voice agent's whole life:

1. **Before launch: crash tests.** Synthetic callers phone the agent in real time over a simulated 8 kHz phone line with
   fan, traffic, office or crowd noise, in Hindi, Hinglish, Gujarati, Tamil, Marathi, Telugu, Kannada and English, and
   try to break it. Every call is judged against the agent's rules, and every fail quotes the agent's own words.
2. **During the call: Guard and Shield.** Each sentence is checked in code before it is spoken (about 1 ms a line):
   threats dropped, account details held until the caller verifies, the recording disclosure added, a wrong-language
   reply translated. Shield does the same in front of any agent on Twilio, Exotel or Plivo, with no change to the agent.
3. **After the call: QA.** An auditor scores calls against 22 industry scorecards, sending doubtful verdicts to a human.

## Built on all three Gnani models

- **Timbre** gives the callers their voices (13 voices, emotion tags, eight languages).
- **Prisma** is their ears on every call, over the phone line.
- **Evon** (self-hosted on a free Kaggle GPU, as it has no hosted API) plays the callers' minds, the agent under test, the
  judge with quoted evidence, and a red team that designs new attacks.

## Proof, measured

I planted 7 bugs in a reference collections agent and measured on live calls:

- the tests caught all 7 (8 of 8 test cases);
- Guard, with the agent's prompt untouched, prevented all 6 text bugs;
- v4 (the model picks what to do, code speaks every fact) removed all 6 and passed 5 of 6 calls;
- the auditor got 90-94% of 560 verdicts right on calls it never saw and caught every fatal breach;
- 98% of IDs, amounts and dates survive noisy lines (3,366 Prisma transcripts, 30 dB down to 0 dB).

The best bug was found by a live call: Timbre read the loan ID "4821" as "four thousand eight hundred twenty-one", so
no caller could ever verify. No unit test could catch it.

## Honest limits and what's next

Every caller and brand is synthetic; the only human labels are mine; the Inya and real-phone-number targets work end to
end offline but have not run live. Next: run them live, and check how a sentence will sound, not just what it says.

**Code:** https://github.com/RiyanKothari/diapason (`pip install -e .`, then `diapason demo` runs with no keys).
