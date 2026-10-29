# How Bhool Bhulaiya uses Gnani AI

Every Gnani model has a load-bearing role. Nothing here is decorative.

| Model | API used | Role in the product | Where |
|---|---|---|---|
| **Prisma v2.5** (STT) | REST `POST /stt/v3` (≤60 s clips) | The synthetic caller's ears: transcribes each agent turn so the caller can react | `caller/ears.py` → `gnani.Prisma` |
| | REST, chunked | Re-transcribes recorded calls for judging; transcribes both channels of production recordings | `regress.py` |
| | REST under every channel preset | `asr-bench`: CER grid by language × phone line | `bench.py` |
| | Realtime WS `wss://…/stt/v3/stream` (1024-byte PCM16 frames, telephony VAD preset) | Client implemented for streaming use; the next step for the reference agent's endpointing | `gnani.stream_transcribe` |
| **Timbre v3.0** (TTS) | REST `POST /api/v1/tts/inference`, WAV 16 kHz | The callers' voices: 13 voices × 10 languages + `hi-en` Hinglish | `caller/mouth.py` |
| | Inline audio tags | Caller emotion: `<shouting>` for the angry uncle, `<sigh> <slow>` for the confused aunty, `<coughs>` … | `caller/brain.Utterance.tts_text` |
| | Same | The reference agent's voice | `reference_agent.py` |
| **Evon v3.3** (30B-A3B) | OpenAI-compatible chat (`EVON_BASE_URL`) | The caller's mind: role-plays a persona that knows only its own facts | `caller/brain.EvonBrain` |
| | JSON mode, k samples | The judge: rubric verdicts with quoted, verified evidence; majority vote | `judge/rubric.py` |
| | JSON mode | Suite generation from an SOP; failed production call → regression case; fix suggestions | `generate.py`, `regress.py`, `advise.py` |
| | JSON mode | The reference agent's brain | `reference_agent.py` |

## Why this matters to Gnani specifically

- **The gap it fills.** Gnani already does post-call QA (Analytics) and live coaching for humans
  (Assist). This adds automated, adversarial, *pre-launch and regression* testing for AI agents, under
  the conditions Gnani's models are built for: 8 kHz telephony, code-mixing, noisy lines.
- **It uses Gnani to test Gnani.** Timbre plays the customers, Evon plays and judges them, Prisma
  listens. A delivery team can stress an Inya agent with Gnani's own stack.
- **Vertical rubric packs** match Gnani's markets: `bfsi_collections` (RBI Fair Practices Code),
  `insurance` (IRDAI), `healthcare`, `telecom` (TRAI TCCCPR), `kyc`.
- **`asr-bench`** gives the Prisma team a reproducible language × line CER grid: seeded noise, codec
  and packet loss, so a model change can be compared like for like.
- **Telephony realism**: the channel simulator models what Gnani's 14M hours of telephonic audio
  look like: narrowband, G.711, bursty loss, Indian street and market noise.

## Credit discipline (5,000 programme credits)

- `bhool plan` estimates usage before anything is spent; `--max-tts-chars`, `--max-stt-seconds`,
  `--max-evon-calls` are hard caps enforced before each request.
- Timbre output is cached on disk by every input that changes the audio, so re-runs of a suite are
  TTS-free.
- `bhool demo`, `selftest`, `load --offline` and the whole test suite use zero credits.

## Contracts followed (from docs.gnani.ai)

- Auth header `X-API-Key-ID`; retries with backoff on 429/500/503; error bodies surfaced as
  `HTTP <code> <type>: <message>`.
- STT languages: `bn-IN en-IN gu-IN hi-IN kn-IN ml-IN mr-IN pa-IN ta-IN te-IN`. There is no Hinglish
  STT code, so code-mixed speech is transcribed with `hi-IN`; TTS accepts `hi-en`.
- Timbre v3 voices are validated at suite load, so a typo'd voice fails before any credit is spent.
