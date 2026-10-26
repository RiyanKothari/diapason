"""PII redaction for stored artefacts (DPDP Act 2023 hygiene).

The judge always sees raw transcripts; redaction applies only to what is written to disk.
Indian identifiers covered: mobile numbers, Aadhaar, PAN, account/card-length digit runs,
email addresses. Short numbers (amounts, dates, 4-digit loan suffixes) are kept because
they are the substance of most findings. Devanagari/Gujarati digits are matched too.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Latin, Devanagari and Gujarati digits
D = r"[0-9०-९૦-૯]"

PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("AADHAAR", re.compile(rf"(?<!{D}){D}{{4}}[ -]?{D}{{4}}[ -]?{D}{{4}}(?!{D})")),
    ("PHONE", re.compile(rf"(?<!{D})(?:\+?91[ -]?)?[6-9६-९૬-૯]{D}{{4}}[ -]?{D}{{5}}(?!{D})")),
    ("NUMBER", re.compile(rf"(?<!{D}){D}(?:[ -]?{D}){{7,}}(?!{D})")),   # 8+ digit runs: accounts, cards
]


def redact(text: str) -> str:
    for label, pat in PATTERNS:
        text = pat.sub(f"[{label}]", text)
    return text


def _walk(obj, keys=("text", "quote", "reason", "summary")):
    if isinstance(obj, dict):
        return {k: redact(v) if k in keys and isinstance(v, str) else _walk(v, keys) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(x, keys) for x in obj]
    return obj


def redact_report(report) -> None:
    report.verdicts = _walk(report.verdicts)
    report.calls_detail = _walk(report.calls_detail)


def redact_call_file(path: str | Path) -> None:
    p = Path(path)
    p.write_text(json.dumps(_walk(json.loads(p.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2), encoding="utf-8")
