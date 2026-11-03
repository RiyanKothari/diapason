"""Load calls from anything a contact centre has, and measure them.

Inputs (a file or a directory of them):
- ``.wav``    dual-channel recording, one party per channel: transcribed with Prisma (spends STT credit),
              timing measured from the audio itself. A sidecar ``<name>.json`` adds metadata.
- ``.json``   one transcript ``{"call_id", "agent_id", "campaign", "crm": {...}, "turns": [...]}``,
              or a Diapason test call (``call.json`` with recordings next to it)
- ``.jsonl``  one transcript per line (bulk exports, e.g. Inya conversation logs)
- ``.csv``    rows of ``call_id, speaker, text[, start, end, agent_id, campaign]``
- ``.txt``    ``Agent: ...`` / ``Customer: ...`` lines

A turn is ``{"speaker": "agent"|"caller", "text": ..., "start": s, "end": s}``; speaker aliases
(bot, ai, assistant / customer, user, borrower) are accepted. Transcripts without timestamps are
scored on content only: timing metrics become not-applicable instead of being invented.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..call.engine import CallRecord
from ..caller.brain import Turn
from ..judge.metrics import CallMetrics, Segment, measure_segments

AGENT_ALIASES = {"agent", "bot", "ai", "assistant", "voicebot", "va", "executive", "rep"}
CALLER_ALIASES = {"caller", "customer", "user", "borrower", "client", "human", "cx"}
SUPPORTED = {".wav", ".json", ".jsonl", ".csv", ".txt"}


@dataclass
class Conversation:
    call_id: str
    record: CallRecord
    meta: dict = field(default_factory=dict)      # agent_id, campaign, date, crm, source
    timed: bool = True                             # timestamps are real (audio or a timed transcript)
    audio_s: float = 0.0                           # seconds of audio sent to STT


def _speaker(raw: str) -> str:
    s = str(raw).strip().lower()
    if s in AGENT_ALIASES:
        return "agent"
    if s in CALLER_ALIASES:
        return "caller"
    raise ValueError(f"unknown speaker {raw!r}: use agent/caller (or an alias like bot/customer)")


def from_turns(call_id: str, turns: list[dict], meta: dict | None = None) -> Conversation:
    """Build a conversation from transcript turns; synthesises timing (~2.5 words/s) when absent."""
    timed = bool(turns) and all(t.get("start") is not None and t.get("end") is not None for t in turns)
    out, clock = [], 0.0
    for t in turns:
        text = str(t.get("text", "")).strip()
        if not text:
            continue
        if timed:
            start, end = float(t["start"]), float(t["end"])
        else:
            start, end = clock, clock + max(0.6, len(text.split()) / 2.5)
            clock = end + 0.5
        out.append(Turn(_speaker(t.get("speaker", "")), text, start, end))
    out.sort(key=lambda t: t.start)
    duration = max((t.end for t in out), default=0.0)
    if timed:
        metrics = measure_segments([Segment(t.start, t.end) for t in out if t.speaker == "caller"],
                                   [Segment(t.start, t.end) for t in out if t.speaker == "agent"], duration)
    else:
        metrics = CallMetrics(duration_s=round(duration, 3), caller_turns=sum(t.speaker == "caller" for t in out),
                              agent_turns=sum(t.speaker == "agent" for t in out), time_to_first_audio_s=None)
    rec = CallRecord(scenario_id=call_id, run=0, end_reason="production", duration_s=round(duration, 3), turns=out,
                     caller_segments=[], metrics=metrics, dispositions=list((meta or {}).get("dispositions", [])))
    return Conversation(call_id, rec, {k: v for k, v in (meta or {}).items() if k != "dispositions"}, timed)


def _from_obj(obj: dict, default_id: str, source: str) -> Conversation:
    turns = obj.get("turns") or obj.get("transcript") or obj.get("messages")
    if not isinstance(turns, list):
        raise ValueError(f"{source}: transcript needs a 'turns' list")
    meta = {k: v for k, v in obj.items() if k not in ("turns", "transcript", "messages")}
    meta["source"] = source
    return from_turns(str(obj.get("call_id") or obj.get("id") or default_id), turns, meta)


def _txt(path: Path) -> Conversation:
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z]+)\s*:\s*(.+)$", line)
        if m:
            turns.append({"speaker": m.group(1), "text": m.group(2)})
        elif turns and line.strip():
            turns[-1]["text"] += " " + line.strip()
    return from_turns(path.stem, turns, {"source": str(path)})


def _csv(path: Path) -> list[Conversation]:
    calls: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cid = (row.get("call_id") or path.stem).strip()
            c = calls.setdefault(cid, {"call_id": cid, "turns": [], "source": str(path)})
            for k in ("agent_id", "campaign", "date"):
                if row.get(k):
                    c[k] = row[k]
            num = lambda v: float(v) if v not in (None, "") else None  # noqa: E731
            c["turns"].append({"speaker": row["speaker"], "text": row["text"], "start": num(row.get("start")), "end": num(row.get("end"))})
    return [_from_obj(c, cid, str(path)) for cid, c in calls.items()]


def _wav(path: Path, hear, lang: str, caller_channel: int) -> Conversation:
    from ..regress import ingest_call
    if hear is None:
        raise ValueError(f"{path.name}: audio input needs speech-to-text (run with live Prisma, not --offline)")
    seconds = [0.0]

    def counted(audio, sr, lg):
        seconds[0] += audio.size / sr
        return hear(audio, sr, lg)
    rec, _, _ = ingest_call(path, counted, lang, caller_channel)
    side = path.with_suffix(".json")
    meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    meta["source"] = str(path)
    return Conversation(str(meta.get("call_id") or path.stem), rec, meta, True, round(seconds[0], 1))


def load(paths: list[Path], hear=None, lang: str = "hi-IN", caller_channel: int = 0) -> list[Conversation]:
    """Every conversation in these files/directories, in a stable order."""
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED)
        elif p.exists():
            files.append(p)
        else:
            raise FileNotFoundError(p)
    wav_stems = {f.with_suffix("") for f in files if f.suffix.lower() == ".wav"}
    out: list[Conversation] = []
    for f in files:
        ext = f.suffix.lower()
        if ext == ".wav":
            if f.name in ("caller.wav", "agent.wav"):
                continue                      # halves of a Diapason test call; loaded via its call.json
            out.append(_wav(f, hear, lang, caller_channel))
        elif ext == ".json":
            if f.with_suffix("") in wav_stems:
                continue                      # metadata sidecar of a recording
            obj = json.loads(f.read_text(encoding="utf-8"))
            if f.name == "call.json" and "scenario_id" in obj:
                from ..runner import load_call
                rec = load_call(f)
                cid = f"{rec.scenario_id}#{rec.run}"
                out.append(Conversation(cid, rec, {"source": str(f), "campaign": f.parent.parent.name}, True))
            elif f.name not in ("report.json", "qa.json", "usage.json"):
                out.append(_from_obj(obj, f.stem, str(f)))
        elif ext == ".jsonl":
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
                if line.strip():
                    out.append(_from_obj(json.loads(line), f"{f.stem}-{i}", f"{f}:{i + 1}"))
        elif ext == ".csv":
            out += _csv(f)
        elif ext == ".txt":
            out.append(_txt(f))
    seen: dict[str, int] = {}
    for c in out:                              # call ids must be unique to index results
        n = seen.get(c.call_id, 0)
        seen[c.call_id] = n + 1
        if n:
            c.call_id = f"{c.call_id}~{n}"
    return out


# ---------------------------------------------------------------- conversation analytics (deterministic)

QUESTION_WORDS = {"क्या", "कब", "कैसे", "कितना", "कितने", "क्यों", "कौन", "कहाँ", "શું", "ક્યારે", "કેમ", "કેટલા",
                  "what", "when", "how", "why", "which", "who", "where"}


def script_mix(text: str) -> dict[str, float]:
    """Share of letters by script: what languages a speaker actually used (Hinglish shows as both)."""
    counts = {"devanagari": 0, "gujarati": 0, "latin": 0, "other": 0}
    for ch in text:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        key = ("devanagari" if "DEVANAGARI" in name else "gujarati" if "GUJARATI" in name
               else "latin" if "LATIN" in name else "other")
        counts[key] += 1
    total = sum(counts.values())
    return {k: round(v / total, 3) for k, v in counts.items() if v} if total else {}


def analyse(conv: Conversation) -> dict:
    """Talk dynamics a QA lead looks at, computed from turns (timing parts only when timed)."""
    turns = conv.record.turns
    by = {s: [t for t in turns if t.speaker == s] for s in ("agent", "caller")}
    words = {s: sum(len(t.text.split()) for t in ts) for s, ts in by.items()}
    talk = {s: sum(t.end - t.start for t in ts) for s, ts in by.items()}
    m = conv.record.metrics
    out = {
        "turns": len(turns),
        "agent_words": words["agent"], "caller_words": words["caller"],
        "agent_questions": sum(1 for t in by["agent"] if "?" in t.text or any(w.strip("?।,.") in QUESTION_WORDS for w in t.text.lower().split())),
        "script_mix": {s: script_mix(" ".join(t.text for t in ts)) for s, ts in by.items()},
    }
    if conv.timed and sum(talk.values()) > 0:
        dur = max(conv.record.duration_s, 1e-6)
        out.update({
            "duration_s": round(conv.record.duration_s, 1),
            "agent_talk_ratio": round(talk["agent"] / sum(talk.values()), 3),
            "silence_ratio": round(max(0.0, 1 - (talk["agent"] + talk["caller"] - m.overlap_s) / dur), 3),
            "agent_wpm": round(60 * words["agent"] / talk["agent"], 1) if talk["agent"] else None,
            "caller_wpm": round(60 * words["caller"] / talk["caller"], 1) if talk["caller"] else None,
            "longest_agent_monologue_s": round(max((t.end - t.start for t in by["agent"]), default=0.0), 1),
        })
    return out


def metric_values(conv: Conversation, analytics: dict) -> dict[str, float]:
    """Every number a ``metric`` check may reference. Timing ones are absent for untimed transcripts."""
    vals: dict[str, float] = {k: v for k, v in analytics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if conv.timed:
        for k, v in conv.record.metrics.to_dict().items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals[k] = v
    return vals
