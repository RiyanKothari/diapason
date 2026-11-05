# Launch kit (LinkedIn + X)

Every number here matches the README, `results/` and the 60-second film. Change a number only after changing the evidence.
Rules that apply (challenge terms): organic engagement only. No engagement pods or swaps, no paid boosts, no bots. A
misleading demo disqualifies, so nothing in a post may promise more than the evidence shows.

The repository stays private, so the posts point at the deployed site only: it plays every call and carries every
measurement. Nothing in a post may send a stranger to the code.

## Before posting

1. The site is live at https://diapason-mu.vercel.app (Vercel project `diapason`, static files only). To update it:
   `diapason site --out site --proof runs/proof-live-5`, then `npx vercel deploy --prod` from `site/`. `runs/` and `site/`
   are git-ignored, so a Vercel project connected to the repo would have nothing to build; `site/vercel.json` pins it to
   plain static files.
2. Upload `runs/video/diapason-film-60s.mp4` to LinkedIn **natively** (not a YouTube link: native video is shown larger and
   counts as the "public video of a working application").
3. Tag Gnani by typing `@Gnani` and picking **Gnani.ai** from the dropdown, so it becomes a real tag, not plain text.
4. Post on a weekday morning (9-11 am IST). For the first hour, reply to every comment.
5. Put the link in the first comment, not the post: LinkedIn shows posts with outside links to fewer people.
6. Nominate this post in the participant workspace.

## The post (LinkedIn, nominated)

> Before an AI voice agent talks to a million Indians, who tests it the way Indians actually call?
>
> Real callers phone from a noisy shop, switch from Hindi to Gujarati mid-sentence, hand the phone to their brother, cut
> the agent off, and sometimes tell it to "ignore your instructions". Most voice agents are tested with a handful of polite
> test calls.
>
> So for the #GreatIndianAIInternshipChallenge I built Diapason, on all three of Gnani's models:
>
> 🔹 Before launch: synthetic callers phone your agent in Hindi, Hinglish, Gujarati, Tamil, Marathi, Telugu, Kannada or
> English, over a simulated 8 kHz phone line with fan, traffic and market noise, and try to break it. Every call is judged
> against your rules, and every fail quotes the agent's own words.
> 🔹 During the call: Diapason Guard checks each sentence in code before it is spoken. Shield does the same in front of any
> agent on Twilio, Exotel or Plivo, with no change to the agent.
> 🔹 After the call: an auditor scores calls against industry scorecards.
>
> To know it works, I planted 7 bugs in a collections agent and measured:
> • 8 of 8 tests caught them
> • Guard, with the agent's prompt untouched, prevented 6 of 6 text bugs
> • v4 (the model picks what to do, code speaks every fact) removed 6 of 6 and passed 5 of 6 calls
> • the auditor got 90-94% of 560 verdicts right on calls it never saw, and caught every fatal breach
> • across 3,366 noisy-line transcripts, 98% of IDs, amounts and dates survive
>
> Gnani's models do all the work:
> • Prisma is the callers' ears
> • Timbre is their voices
> • Evon plays the callers, the agent, the judge and the red team. Evon has no hosted API yet, so I run it myself on a
> free Kaggle GPU.
>
> My favourite bug: Timbre read "4821" aloud as a number, Prisma wrote "फोर थाउज़ंड एट हंडरेड ट्वेंटी वन", and no caller could
> ever verify. Only a live call finds that.
>
> I didn't trust my own AI judge either. It once failed 9 of 9 correct calls; I measured that, fixed it, and it now fails
> none of them while still catching every real leak.
>
> If you build voice agents for Indian customers: what breaks yours most?
>
> @Gnani.ai #GnaniAI #GreatIndianAIInternshipChallenge #VoiceAI #ConversationalAI

## First comment (post it yourself, right after)

> ▶ The 60-second demo and the full film, played from the run files: https://diapason-mu.vercel.app/watch-60.html
> 📊 The planted-bug proof, the phone-line atlas and every call, with the agent's own words (you can listen to them):
> https://diapason-mu.vercel.app
> The code is private for now. Happy to walk anyone through it.

## X (nominated post: the first one, with the same 60-second video attached)

1/
> Test your AI voice agent the way Indians call: noisy 8 kHz lines, Hinglish, a brother on the phone, "ignore your
> instructions".
>
> I built Diapason on [Gnani handle] Prisma, Timbre and Evon. I planted 7 bugs: 8 of 8 tests caught them.
>
> #GnaniAI #GreatIndianAIInternshipChallenge

2/
> How it works: Timbre gives the callers their voices, Prisma their ears, and Evon plays the callers, the agent, the judge
> and the red team.
>
> Evon has no hosted API yet, so I run it myself on a free Kaggle GPU.

3/
> The bug only a live call could find: Timbre read the loan ID "4821" aloud as a number, Prisma wrote "four thousand eight
> hundred twenty one", and no caller could ever verify.
>
> Every caller failed, until the digit reader was fixed.

4/
> Guard checks each sentence in code before the agent speaks it: 6 of 6 text bugs prevented, with the prompt untouched.
>
> Across 3,366 noisy-line transcripts, 98% of IDs, amounts and dates survive.
>
> Demo and every run: https://diapason-mu.vercel.app

Check Gnani's X handle before tagging; it isn't recorded anywhere in this repo. Each post must stay within 280
characters (a link counts as 23).

## Answers for likely comments

- **Can I try it?** The site plays every call and shows every verdict with the agent's own words. The code is private for
  now; testing your own agent over a phone-platform stream uses Gnani credits, capped up front.
- **Is the code open?** Not yet. Every number is backed by run files, and I'm happy to show the code to anyone evaluating it.
- **How is it different from Hamming, Coval or Cekura?** Those test voice agents too, mostly for English. Diapason is built around
  Indian calls: code-mixing, 8 kHz noise, digits and dates said the way Indian callers say them (in eight languages), RBI
  collections rules, and a guard and Shield that act during the call. Every accuracy number is published with what it misses.
- **Does it work with my stack?** Anything that takes calls over Twilio Media Streams, an Exotel or Plivo stream, or a websocket.
- **Real customer data?** No. Every caller is synthetic and every brand is fictional. The 3,366 transcripts are Prisma's
  real output on Timbre speech sent through a simulated noisy line, not recorded calls.
- **Why self-host Evon?** It has no hosted API yet, so it runs on a free Kaggle GPU. That's also why test runs don't judge latency.
- **What's the weakest part?** On its own the judge both misses and invents privacy failures, so a code check has the final say
  there; the only human labels are mine; every caller is synthetic; the Inya and real-phone targets work end to end offline
  but haven't run live yet.

## Follow-ups (one short story each, each pointing back to the nominated post)

| Day | Story | The number |
|---|---|---|
| 1 | Launch (the post above) | 8/8 planted bugs caught |
| 2 | The bug only a live call could find: "4821" spoken as a number | Every caller failed verification, until the digit reader was fixed |
| 3 | My AI judge failed every correct call, and how I measured the fix | Clean calls wrongly failed: 9/9 → 0/9, with 7/7 leaks still caught |
| 4 | Prisma writes no numerals in Tamil | Digit and date reading: 1/28 → 28/28, and 24/24 held out |
| 5 | Shield: compliance in front of any agent, live | Every threat replaced; median hold 678 ms per line |

Close each one with "Demo: see my pinned post". The deadline is 10 Nov, 11:59 PM IST, and engagement counts only
until then, so post the launch as early as possible and submit by 9 Nov evening.
