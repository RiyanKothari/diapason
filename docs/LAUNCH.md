# Launch kit (LinkedIn + X)

Every number here matches the README, `results/` and the 60-second film. Change a number only after changing the evidence.
Rules that apply (challenge terms): organic engagement only. No engagement pods or swaps, no paid boosts, no bots. A
misleading demo disqualifies, so nothing in a post may promise more than the README shows.

## Before posting

1. The links must work for a stranger: the repository public, and the site deployed (`diapason site`, then any static host).
2. Upload `runs/video/diapason-film-60s.mp4` to LinkedIn **natively** (not a YouTube link: native video is shown larger and
   counts as the "public video of a working application").
3. Tag Gnani by typing `@Gnani` and picking **Gnani.ai** from the dropdown, so it becomes a real tag, not plain text.
4. Post on a weekday morning (9-11 am IST). For the first hour, reply to every comment.
5. Put the links in the first comment, not the post: LinkedIn shows posts with outside links to fewer people.
6. Nominate this post in the participant workspace.

## The post (LinkedIn, nominated)

> Before an AI voice agent talks to a million Indians, who tests it the way Indians actually call?
>
> Real callers phone from a noisy shop, switch from Hindi to Gujarati mid-sentence, hand the phone to their brother, cut
> the agent off, and sometimes tell it to "ignore your instructions". Most voice agents are tested with a handful of polite
> test calls.
>
> So for the #GreatIndianAIInternshipChallenge I built Diapason, on Gnani's own models:
>
> 🔹 Before launch: synthetic callers phone your agent in Hindi, Hinglish, Gujarati, Tamil, Marathi, Telugu, Kannada or
> English, over a simulated 8 kHz phone line with fan, traffic and market noise, and try to break it. Every call is judged
> against your rules, and every fail quotes the agent's own words.
> 🔹 During the call: Diapason Guard checks each sentence in code before it is spoken. Shield does the same in front of any
> agent on Twilio, Exotel or Plivo, with no change to the agent.
> 🔹 After the call: an auditor scores real calls against industry scorecards.
>
> To know it works, I planted 7 bugs in a collections agent and measured:
> • 8 of 8 tests caught them
> • Guard, with the agent's prompt untouched, prevented 6 of 6 text bugs
> • v4 (the model picks what to do, code speaks every fact) removed 6 of 6 and passed 5 of 6 calls
> • the auditor got 93.6% of 560 verdicts right and caught every fatal breach
> • across 3,366 real transcripts of IDs, amounts and dates on noisy lines, 98% of details survive
>
> Built on @Gnani.ai Prisma (the callers' ears), Timbre (their voices) and Evon (the callers, the agent, the judge and the
> red team).
>
> My favourite bug: Timbre read "4821" aloud as a number, Prisma wrote "फोर थाउज़ंड एट हंडरेड ट्वेंटी वन", and no caller could
> ever verify. Only a live call finds that.
>
> What is weak is written down in the README too. If you build voice agents for Indian customers: what breaks yours most?
>
> #GnaniAI #GreatIndianAIInternshipChallenge #VoiceAI #ConversationalAI

## First comment (post it yourself, right after)

> ▶ The 60-second demo, and the full 2-minute film, are drawn from the run files: <site>/watch-60.html
> 💻 Code and every measurement behind the numbers: <repo>
> Try it free: `diapason dashboard`, then **Prove it**. It runs the same six calls against v1 to v4 in about 3 minutes.

## X (nominated post, if you post there too)

> Test your AI voice agent the way Indians call: noisy lines, Hinglish, a brother on the phone, "ignore your
> instructions". Diapason: crash tests, a live guard and QA on Gnani Prisma, Timbre and Evon. 8/8 planted bugs caught.
> [tag Gnani] #GnaniAI #GreatIndianAIInternshipChallenge

Attach the same 60-second video. Check Gnani's X handle before tagging; it isn't recorded anywhere in this repo.

## Answers for likely comments

- **Can I try it?** Yes: clone the repo, `pip install -e .`, then `diapason dashboard`. Prove it runs v1 to v4 for free. Testing
  your own agent over a phone-platform stream uses Gnani credits, capped up front.
- **How is it different from Hamming, Coval or Cekura?** Those test voice agents too, mostly for English. Diapason is built around
  Indian calls: code-mixing, 8 kHz noise, digits and dates said the way Indian callers say them (in eight languages), RBI
  collections rules, and a guard and Shield that act during the call. Every accuracy number is published with what it misses.
- **Does it work with my stack?** Anything that takes calls over Twilio Media Streams, an Exotel or Plivo stream, or a websocket.
- **Real customer data?** No. Every caller is synthetic and every brand is fictional.
- **Why self-host Evon?** It has no hosted API yet, so it runs on a free Kaggle GPU. That's also why test runs don't judge latency.
- **What's the weakest part?** On its own the judge both misses and invents privacy failures, so a code check has the final say
  there; the only human labels are mine; the Inya and real-phone targets work end to end offline but haven't run live yet.

## Follow-ups (one short story each, each pointing back to the nominated post)

| Day | Story | The number |
|---|---|---|
| 1 | Launch (the post above) | 8/8 planted bugs caught |
| 2 | The bug only a live call could find: "4821" spoken as a number | Every caller failed verification, until the digit reader was fixed |
| 3 | My AI judge failed every correct call, and how I measured the fix | Clean calls wrongly failed: 9/9 → 0/9, with 7/7 leaks still caught |
| 4 | Prisma writes no numerals in Tamil | Digit and date reading: 1/28 → 28/28, and 24/24 held out |
| 5 | Shield: compliance in front of any agent, live | Every threat replaced; median hold 678 ms per line |

Close each one with "Demo and code: see my pinned post". The deadline is 10 Nov, 11:59 PM IST, and engagement counts only
until then, so post the launch as early as possible and submit by 9 Nov evening.
