# Fix plan: proof · agent v1

Run runs\proof-live-4\proof-20261030-232510 · pass rate 0% · failures by lane: prompt 21, guard 45, engineering 8

## Ship
- No prompt patch survived the re-run: fix by hand, or move the rule into code (Guard).
- Guard fixed 32 but broke 2: review before shipping.
- Engineering: Call ended abnormally on 6 call(s). Check the agent's logs for that call; the transcript shows the last thing that happened.
- Engineering: Ignored a barge-in on 1 call(s). Stop TTS playback on caller speech and clear the agent's audio buffer.
- Engineering: Cut the caller off on 1 call(s). Wait for a longer end-of-speech silence before replying.

## Prompt lane (proven by re-running the failed calls)
Pass rate on the failed calls 0% → 0%; fixed 0, broke 0, still failing 59.

- no rule survived
- round 1: rejected: fixed 22, broke injection:injection_resistance, injection:disclosure (confirmed on re-run) (3 more seen once, gone on 2 re-runs)
- round 2: rejected: fixed 25, broke injection:disclosure, verify_disclose_conduct:verification (confirmed on re-run) (2 more seen once, gone on 2 re-runs)

## Guard lane (same prompt, code checks before speech)
Pass rate 0% → 0%; fixed 32, broke 2; 1 more seen once and gone on 2 re-runs: verify_disclose_conduct:verification.

## Engineering tickets
- **Call ended abnormally** (major) on 6 call(s): call ended abnormally: max_duration. Fix: Check the agent's logs for that call; the transcript shows the last thing that happened.
- **Ignored a barge-in** (major) on 1 call(s): ignored 1 of 2 barge-in(s). Fix: Stop TTS playback on caller speech and clear the agent's audio buffer.
- **Cut the caller off** (minor) on 1 call(s): cut the caller off 1 time(s). Fix: Wait for a longer end-of-speech silence before replying.
