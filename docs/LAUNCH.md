# Launch kit (LinkedIn + X)

Every number here matches the README, `results/` and the 60-second film. Change a number only after changing the evidence.
Rules that apply (challenge terms): organic engagement only. No engagement pods or swaps, no paid boosts, no bots. A
misleading demo disqualifies, so nothing in a post may promise more than the evidence shows.

The repository is public since 9 Nov (https://github.com/RiyanKothari/diapason), and the site links to it. The posts
still point at the site first: it plays every call and carries every measurement.

## Before posting

1. The site is live at https://diapason-mu.vercel.app (Vercel project `diapason`, static files only). To update it:
   `diapason site --out site --proof runs/proof-live-5`, then `npx vercel deploy --prod` from `site/`. `runs/` and `site/`
   are git-ignored, so a Vercel project connected to the repo would have nothing to build; `site/vercel.json` pins it to
   plain static files.
2. Upload `runs/video/diapason-film-60s.mp4` to LinkedIn **natively** (not a YouTube link: native video is shown larger and
   counts as the "public video of a working application").
3. Tag Gnani by typing `@Gnani` and picking **Gnani.ai** from the dropdown, so it becomes a real tag, not plain text.
4. Post on Friday 6 Nov at 9:00 IST (see the playbook). For the first hour, reply to every comment.
5. Put the link in the first comment, not the post: LinkedIn shows posts with outside links to fewer people.
6. Nominate this post in the participant workspace.

## What goes in each post (media)

LinkedIn can't mix a video and images in one post, so the launch post carries the video and the follow-ups carry the
images. Images are in `runs/launch-media/` (captured from the live site at 2x; rerun the capture after a site change).

| Post | Media | Notes |
|---|---|---|
| Launch (nominated) | `runs/video/diapason-film-60s.mp4` with your voiceover (script below) | Native upload. Cover: `00-thumbnail-4x5.png` (or `00-thumbnail-16x9.png`). Turn on captions: most people watch muted |
| Day 2: "4821" bug | `02-same-caller-guard.png` | The guard strikes out the threat and holds the amount until the caller verifies |
| Day 3: the judge | `03-v1-to-v4.png` (and `06-proof.png` as a 2nd image) | The matrix is the single clearest image of the project |
| Day 4: Tamil numerals | `09-every-language.png` (the transcript, its number words lit, the value read) | |
| Day 5: Shield | a 20 s screen recording of a Shield block | |
| X post 1 | the same video | X post 3: `02-same-caller-guard.png`; X post 5: `03-v1-to-v4.png` |

**The launch video: the 60-second film, with your voice over it.** `runs/video/diapason-film-60s.mp4` (the same film plays
at https://diapason-mu.vercel.app/watch-60.html). It has its own sound in one place: from about 6 s to 26 s the real
recorded call plays (the agent's threat in Hindi, Ramesh answering, the agent threatening again). Don't talk over it;
it is the strongest moment in the film. Speak only in the gaps below. Each line fits its scene at a relaxed pace.

| Film time | On screen | You say |
|---|---|---|
| 0-5 s | "Before your voice agent talks to a million Indians, it has to survive these callers." | "I built a crash test for Indian voice agents. Listen to what my test agent says first." |
| 5-26 s | The call: transcript, fail stamps | **Nothing. The call speaks.** |
| 26-31 s | The call's fails on screen | "That's a bug I planted: a threat, and the loan amount, before checking who picked up." |
| 31-41 s | The same agent behind Guard | "Diapason's guard checks every sentence in code before it's spoken. Same agent, prompt untouched. The threat never reaches the caller." |
| 41-50 s | v1 to v4 on the same calls | "I planted seven bugs. Every one was caught, and each new version is re-tested on the same calls until they're gone." |
| 50-55 s | QA on every call | "After the call, every call is scored, with the agent's own words as proof." |
| 55-60 s | Diapason, Prisma, Timbre, Evon | "Diapason. Built on Gnani's Prisma, Timbre and Evon." |

How to record it in one take (Windows): open the film page full-screen (F11), start Snipping Tool's screen recording
(Win+Shift+R) with the microphone and system audio on, press Play on the film, and read the lines as the scenes change.
Then trim the start and end in Clipchamp, turn on auto captions, and export 1080p.

## The post (LinkedIn, nominated)

The first two lines are all most people see before "...see more", so they carry a shock and an open question ("Here's
why."). The crash-test comparison explains the product in one breath; the three numbered lines say what it does; the
4821 story is the one people remember. No emojis.

> An AI agent told a borrower: "Pay today, or there'll be legal action."
> I built it to say that. Here's why.
>
> Cars get crash-tested before they hit the road. AI voice agents that will talk to millions of Indians usually get a
> few polite test calls and go live. Then a real customer calls from a noisy shop, switches from Hindi to Gujarati
> halfway, or his brother picks up, and the agent breaks.
>
> So I planted seven bugs in a test agent (that threat was one of them) and built Diapason to find them.
>
> What it does:
> 1. Before launch, synthetic callers phone your agent in eight languages, over a noisy phone line, and try to break it.
> 2. During a call, a guard checks every sentence before the agent says it.
> 3. After the call, an auditor scores it and quotes the agent's exact words for every mistake.
>
> It caught all seven bugs, and the guard stopped six of them before they were ever spoken.
>
> The best bug was one I didn't plant: the loan ID "4821" was read out as "four thousand eight hundred twenty-one", so
> no caller could ever verify. No unit test caught it. One real call did.
>
> Built on Gnani's Prisma, Timbre and Evon for the #GreatIndianAIInternshipChallenge. The 60-second demo is below, and
> you can listen to every test call (link in the comments).
>
> If you've ever been stuck with a voice bot, what did it get wrong?
>
> @Gnani.ai #GnaniAI #VoiceAI #ConversationalAI

Media: the film with your voiceover, uploaded natively, cover `00-thumbnail-4x5.png`, captions on.

## First comment (post it yourself within a minute)

> You can listen to every test call here: https://diapason-mu.vercel.app
>
> In QA Studio you can open a call in Tamil, Kannada or any of the other languages:
> https://diapason-mu.vercel.app/studio.html
>
> I built it solo over the last two weeks. Happy to answer anything about how it works.

## X (nominated post: the first one, with the video attached)

1/ (video)
> An AI agent told a borrower: "Pay today, or there'll be legal action." I built it to say that.
>
> Then I built Diapason to catch it: crash tests for Indian voice agents, on [Gnani handle] Prisma, Timbre & Evon. 7
> planted bugs, all caught. #GnaniAI #GreatIndianAIInternshipChallenge

2/
> My favourite find: Timbre read the loan ID "4821" as "four thousand eight hundred twenty-one", so no caller could
> verify. No unit test caught it. One real call did.

3/ (image `03-v1-to-v4.png`)
> Every test call, replayed: https://diapason-mu.vercel.app

Check Gnani's X handle before tagging; it isn't recorded anywhere in this repo.

## Launch-day playbook (organic only)

**Tonight (5 Nov)**
1. Record the voiceover over the film (script above) and export it. Captions on.
2. Profile: headline "Building Diapason: crash tests for Indian voice agents"; add the site to Featured. Optional banner:
   `00-thumbnail-16x9.png`.
3. Find Gnani's X handle and follow Gnani on both platforms.
4. Write down 15-25 people who would genuinely care (classmates in AI, a professor, anyone in voice AI or fintech). After
   the post is live, message each one personally and ask what they think. Asking for honest feedback is organic;
   trading likes, joining pods or swapping engagement is not, and disqualifies.

**Launch: Friday 6 Nov, 9:00 IST** (deadline is Tuesday 10 Nov, so waiting for a Tuesday slot would lose four days)
1. 9:00 LinkedIn post with the video; 9:01 the first comment with the links.
2. 9:10 the X thread, video on post 1.
3. 9:00-10:00 is the hour that decides reach: reply to every comment within minutes, with a real answer and a question
   back. Use "Answers for likely comments" below. Don't edit the post after the first 10 minutes.
4. Send the personal messages from step 4 once the post has its first few reactions.
5. Nominate both posts in the participant workspace.

**Don't**: ask for "comment YES and I'll DM the link", tag more than Gnani, post the links in the post body, change any
number, or use engagement groups of any kind.

## Messages to friends (send after the post is live)

Send each one yourself, to one person at a time, with their name. Asking people you know for honest feedback is
organic; trading likes, engagement groups or "like for like" are not, and disqualify. Never promise anything in return.

**WhatsApp, to friends and classmates**
> Hey [name]! I just posted about the project I've spent the last two weeks on. It's called Diapason: it crash-tests AI
> voice agents the way Indians actually call (noisy lines, Hindi switching to Gujarati, the brother picking up the
> phone). It's my entry for Gnani AI's internship challenge.
>
> Could you have a look and tell me honestly what you think? Was it clear what it does? Did the demo make sense?
> Anything confusing?
>
> If you find it interesting, a comment with your thoughts or a question would mean a lot. The shortlist partly depends
> on how people engage with the post.
>
> [link to the post]
> Thank you!

**LinkedIn message, to a professor, a senior or someone in AI**
> Hi [name], I just shared a project I built for Gnani AI's internship challenge: Diapason, which crash-tests AI voice
> agents on realistic Indian calls before they go live. I'd really value your honest feedback, especially on whether
> the problem and the demo come across clearly. Here's the post: [link]

## Answers for likely comments

- **Can I try it?** Yes: https://github.com/RiyanKothari/diapason, `pip install -e .`, then `diapason demo` (no keys) or
  `diapason dashboard` and Prove it. Testing your own agent over a phone-platform stream uses Gnani credits, capped up front.
- **Is the code open?** Yes, the repository is public, with every run file behind the numbers.
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

## Follow-ups (one story each, each pointing back to the nominated post)

Only the nominated post's engagement counts, so each one ends with "Demo: see my pinned post" and you add the launch
post's link as the first comment. One image each.

**Sat 7 Nov, 10:00 IST** · image `02-same-caller-guard.png`
> Every one of my test callers failed to verify. Every single one.
>
> The agent asked for the last four digits of the loan ID. The caller said "4821". Timbre, the voice, read it out as
> "four thousand eight hundred twenty-one", and Prisma wrote down exactly that. So the check never matched.
>
> No unit test would have found this, because every piece worked on its own. It only broke when a real voice went
> through a real phone line.
>
> So Diapason now reads numbers the way Indians actually say them: digit by digit, as one number, or in English inside
> a Hindi sentence.
>
> Demo: see my pinned post.
> #GnaniAI #GreatIndianAIInternshipChallenge

**Sun 8 Nov, 11:00 IST** · image `09-every-language.png`
> Prisma doesn't write numerals in Tamil.
>
> Say "4821" in Tamil and the transcript comes back as "நான்கு ஆயிரத்தி எண்ணூற்றி இருபத்தொன்று". Same in Marathi,
> Telugu and Kannada. Any test that looks for digits fails before it starts.
>
> So I taught Diapason's readers those number words, including the ones Tamil and Kannada join into one word. Before:
> 1 of 28 real transcripts read right. After: 28 of 28, and 24 of 24 on new numbers and a new voice, written after the
> fix.
>
> Every one of those transcripts is on the site, word by word. Demo: see my pinned post.
> #GnaniAI #GreatIndianAIInternshipChallenge

**Mon 9 Nov, 9:00 IST** · images `03-v1-to-v4.png` and `06-proof.png`
> My AI judge failed 9 out of 9 correct calls.
>
> Diapason uses Evon to judge every test call against the rules. On calls where the agent did everything right, it
> still marked verification as a fail, every time. If I'd trusted it, every agent would have looked broken.
>
> So I labelled calls by hand, measured the judge against them, and rewrote the rule it kept misreading. A code check
> now backs it up wherever the words alone decide.
>
> Clean calls wrongly failed: 9 of 9 before, 0 of 9 after. Real leaks still caught: 7 of 7.
>
> An AI that tests AI needs testing too. Demo: see my pinned post.
> #GnaniAI #GreatIndianAIInternshipChallenge

Submit on Mon 9 Nov evening, with the nominated post links.

**Tue 10 Nov, 9:00 IST** · image `04-the-numbers.png` (or a 20-second screen recording of Shield)
> Last day of the challenge, so here's the part I haven't shown yet: Shield.
>
> Most teams can't rewrite their voice agent. Shield sits between the phone line and the agent, on Twilio, Exotel or
> Plivo, and checks every sentence before the caller hears it. No change to the agent.
>
> In a live test on an Exotel stream it replaced every threat and every missing disclosure, and held each line for a
> median of 678 ms.
>
> Thank you to everyone who commented, asked questions and pushed back this week. Demo: see my pinned post.
> #GnaniAI #GreatIndianAIInternshipChallenge

Engagement counts until 10 Nov, 11:59 PM IST.
