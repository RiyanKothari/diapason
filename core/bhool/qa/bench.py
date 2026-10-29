"""QA-Bench: how often is the auditor right?

Speech-analytics vendors publish coverage ("100% of calls audited") but not accuracy. This builds
collections calls whose correct verdict on every parameter is known by construction (planted
disclosure misses, verification out of order, threats, privacy leaks, pushy hardship handling,
language mismatch, slow or talk-over timing) in Hindi and Gujarati, half of them in the script
Prisma actually produces (English loanwords in Devanagari), then measures per-parameter accuracy
and fail precision/recall, pass/fail decision accuracy and score error against that truth.

Truth is by construction, so this measures the auditor, not human labellers; `bhool qa audit
--labels` measures agreement with real human QA on real calls.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .batch import run_batch
from .conversation import from_turns
from .scorecard import Scorecard

LINES = {
    "hi": {
        "hello": "हाँ, बोलिए।",
        "open": "नमस्ते, मैं सहयोग फाइनेंस से प्रिया बोल रही हूँ।",
        "disclose": " यह कॉल रिकॉर्ड हो रही है।",
        "verify": "आगे बढ़ने से पहले, कृपया अपने loan ID के आखिरी चार अंक बताइए।",
        "digits": "चार आठ दो एक।",
        "amount": "धन्यवाद। आपकी EMI के 4500 रुपये overdue हैं।",
        "police": "आज payment नहीं हुआ तो police complaint होगी।",
        "home": "आज नहीं भरा तो हमारे लोग घर आएंगे।",
        "hardship": "मेरी नौकरी चली गई है, अभी पैसे बिल्कुल नहीं हैं, बहुत मुश्किल चल रही है।",
        "empathy": "यह सुनकर दुख हुआ। मैं आपके लिए restructuring की callback बुक कर देती हूँ।",
        "pushy": "वो आपकी problem है, EMI तो आज ही भरनी पड़ेगी।",
        "ask": "आप कब तक payment कर पाएंगे?",
        "date": "पंद्रह नवंबर को पक्का कर दूंगा, आप चिंता मत कीजिए।",
        "confirm": "ठीक है, पंद्रह नवंबर को 4500 रुपये, note कर लिया। धन्यवाद।",
        "ok": "ठीक है।",
        "nodate": "अभी नहीं बता सकता, बाद में देखूंगा।",
        "later": "ठीक है, हम बाद में call करेंगे।",
        "wife": "मैं उनकी पत्नी बोल रही हूँ, वो अभी घर पर नहीं हैं।",
        "leak": "उन्हें बता दीजिए कि उनकी 4500 रुपये की EMI overdue है।",
        "bye": "ठीक है।",
    },
    "gu": {
        "hello": "હા, બોલો.",
        "open": "નમસ્તે, હું સહયોગ ફાઇનાન્સથી પ્રિયા બોલું છું.",
        "disclose": " આ કૉલ રેકોર્ડ થઈ રહ્યો છે.",
        "verify": "આગળ વધતા પહેલા, તમારા loan ID ના છેલ્લા ચાર અંક જણાવો.",
        "digits": "ચાર આઠ બે એક.",
        "amount": "આભાર. તમારી EMI ના 4500 રૂપિયા overdue છે.",
        "police": "આજે payment નહીં થાય તો પોલીસ complaint થશે.",
        "home": "આજે નહીં ભરો તો અમારા લોકો ઘરે આવશે.",
        "hardship": "મારી નોકરી જતી રહી છે, હમણાં પૈસા બિલકુલ નથી, બહુ તકલીફ છે.",
        "empathy": "સાંભળીને દુઃખ થયું. હું તમારા માટે restructuring નો callback બુક કરું છું.",
        "pushy": "એ તમારી problem છે, EMI તો આજે જ ભરવી પડશે.",
        "ask": "તમે ક્યારે payment કરી શકશો?",
        "date": "પંદર નવેમ્બરે ચોક્કસ કરી દઈશ, તમે ચિંતા ના કરો.",
        "confirm": "સારું, પંદર નવેમ્બરે 4500 રૂપિયા, નોંધી લીધું. આભાર.",
        "ok": "સારું.",
        "nodate": "હમણાં કહી શકું નહીં, પછી જોઈશ.",
        "later": "સારું, અમે પછી call કરીશું.",
        "wife": "હું એમની પત્ની બોલું છું, એ હમણાં ઘરે નથી.",
        "leak": "એમને કહી દેજો કે એમની 4500 રૂપિયાની EMI overdue છે.",
        "bye": "સારું.",
    },
}
# What Prisma hi-IN actually writes for English words inside Hindi speech (measured live).
PRISMA_HI = {"loan ID": "लोन आईडी", "EMI": "ई एम आई", "overdue": "ओवरड्यू", "payment": "पेमेंट", "police": "पुलिस",
             "complaint": "कंप्लेंट", "problem": "प्रॉब्लम", "restructuring": "रीस्ट्रक्चरिंग", "callback": "कॉलबैक",
             "note": "नोट", "call": "कॉल"}


@dataclass
class Variant:
    lang: str            # hi | gu | gu_mismatch (Gujarati caller, Hindi agent)
    disclose: bool
    verify_first: bool
    threat: str          # none | police | home
    hardship: str        # none | empathy | pushy
    ptp: str             # confirm | noconfirm | none
    wrong_party: bool
    slow: bool
    talk_over: bool
    prisma_script: bool


def _variant(rng: random.Random) -> Variant:
    return Variant(lang=rng.choice(["hi", "hi", "gu", "gu_mismatch"]), disclose=rng.random() < 0.7, verify_first=rng.random() < 0.7,
                   threat=rng.choice(["none", "none", "police", "home"]), hardship=rng.choice(["none", "empathy", "pushy"]),
                   ptp=rng.choice(["confirm", "confirm", "noconfirm", "none"]), wrong_party=rng.random() < 0.15,
                   slow=rng.random() < 0.25, talk_over=rng.random() < 0.2, prisma_script=rng.random() < 0.5)


# Prisma's Devanagari loanwords apply to Hindi (hi-IN) transcripts only.


def build_call(i: int, v: Variant) -> tuple[dict, dict[str, str]]:
    """One timed transcript and its true verdict per parameter of scorecards/emi_collections.yaml."""
    caller_l = LINES["gu" if v.lang.startswith("gu") else "hi"]
    agent_l = LINES["hi" if v.lang in ("hi", "gu_mismatch") else "gu"]
    script: list[tuple[str, str]] = [("caller", caller_l["hello"]), ("agent", agent_l["open"] + (agent_l["disclose"] if v.disclose else ""))]
    if v.wrong_party:
        script += [("caller", caller_l["wife"]), ("agent", agent_l["leak"]), ("caller", caller_l["bye"])]
    else:
        if v.verify_first:
            script += [("agent", agent_l["verify"]), ("caller", caller_l["digits"]), ("agent", agent_l["amount"])]
        else:
            script += [("agent", agent_l["amount"]), ("agent", agent_l["verify"]), ("caller", caller_l["digits"])]
        if v.threat != "none":
            script.append(("agent", agent_l[v.threat]))
        if v.hardship != "none":
            script += [("caller", caller_l["hardship"]), ("agent", agent_l[v.hardship])]
        script.append(("agent", agent_l["ask"]))
        if v.ptp == "none":
            script += [("caller", caller_l["nodate"]), ("agent", agent_l["later"])]
        else:
            script += [("caller", caller_l["date"]), ("agent", agent_l["confirm" if v.ptp == "confirm" else "ok"])]
    if v.prisma_script and v.lang == "hi":
        fixed = []
        for who, text in script:
            for en, dev in PRISMA_HI.items():
                text = text.replace(en, dev)
            fixed.append((who, text))
        script = fixed
    # merge consecutive same-speaker lines into one turn, then lay out time
    merged: list[list[str]] = []
    for who, text in script:
        if merged and merged[-1][0] == who:
            merged[-1][1] += " " + text
        else:
            merged.append([who, text])
    turns, t, cut_done = [], 0.0, False
    for k, (who, text) in enumerate(merged):
        dur = max(1.0, len(text.split()) / 2.5)
        if k and who == "agent":
            prev = turns[-1]
            if v.talk_over and not cut_done and prev["end"] - prev["start"] >= 2.0:
                t, cut_done = prev["end"] - 1.0, True            # agent cuts in a second before the customer finishes
            else:
                t = prev["end"] + (4.0 if v.slow else 0.6)
        elif k:
            t = turns[-1]["end"] + 0.5
        turns.append({"speaker": who, "text": text, "start": round(t, 2), "end": round(t + dur, 2)})

    threat = v.threat != "none" and not v.wrong_party
    pushy = v.hardship == "pushy" and not v.wrong_party
    truth = {
        "identifies_lender": "pass",
        "recording_disclosure": "pass" if v.disclose else "fail",
        "verifies_before_amount": "fail" if v.wrong_party or not v.verify_first else "pass",
        "privacy": "fail" if v.wrong_party else "pass",
        "banned_phrases": "fail" if threat else "pass",
        "no_harassment": "fail" if threat or pushy else "pass",
        "hardship_handling": "na" if v.hardship == "none" or v.wrong_party else ("pass" if v.hardship == "empathy" else "fail"),
        "captures_ptp": "pass" if v.ptp != "none" and not v.wrong_party else "fail",
        "confirms_back": "na" if v.ptp == "none" or v.wrong_party else ("pass" if v.ptp == "confirm" else "fail"),
        "tone": "fail" if threat or pushy else "pass",
        "language_match": "fail" if v.lang == "gu_mismatch" else "pass",
        "responsive": "fail" if v.slow else "pass",
        "no_dead_air": "fail" if v.slow else "pass",
        "no_talk_over": "fail" if cut_done else "pass",
    }
    tags = [v.lang, "prisma-script" if v.prisma_script and v.lang == "hi" else "latin-loanwords"] + [k for k, on in (
        ("wrong-party", v.wrong_party), ("threat", threat), ("pushy", pushy), ("slow", v.slow), ("talk-over", cut_done)) if on]
    return {"call_id": f"bench-{i:03d}", "agent_id": f"agent-{chr(65 + i % 4)}", "campaign": "qa-bench", "tags": tags, "turns": turns}, truth


def build_corpus(n: int = 40, seed: int = 7) -> tuple[list[dict], dict[str, dict[str, str]]]:
    rng = random.Random(seed)
    calls, truth = [], {}
    for i in range(n):
        obj, t = build_call(i, _variant(rng))
        calls.append(obj)
        truth[obj["call_id"]] = t
    return calls, truth


def evaluate(results, truth: dict[str, dict[str, str]], card: Scorecard) -> dict:
    weights = {p.id: p for p in card.parameters()}
    per: dict[str, list[tuple[str, str]]] = {}
    decisions, score_err, fatal_hits = [], [], []
    for r in results:
        t = truth[r.call_id]
        got = {p.id: p.verdict for p in r.params}
        for pid, want in t.items():
            if got.get(pid) not in (None, "skipped"):
                per.setdefault(pid, []).append((want, got[pid]))
        judged = {pid for pid in t if got.get(pid) not in (None, "skipped")}
        true_fatal = any(t[p] == "fail" and weights[p].fatal for p in judged)
        pts = [(weights[p].weight, 1.0 if t[p] == "pass" else 0.0) for p in judged if t[p] in ("pass", "fail")]
        true_score = 0.0 if true_fatal else (100 * sum(w * v for w, v in pts) / sum(w for w, _ in pts) if pts else None)
        true_pass = true_score is not None and true_score >= card.pass_mark and not true_fatal
        decisions.append(true_pass == r.passed)
        fatal_hits.append((true_fatal, bool(r.fatal)))
        if true_score is not None and r.score is not None:
            score_err.append(abs(true_score - r.score))

    def stats(pairs):
        tp = sum(w == "fail" and g == "fail" for w, g in pairs)
        fp = sum(w != "fail" and g == "fail" for w, g in pairs)
        fn = sum(w == "fail" and g != "fail" for w, g in pairs)
        return {"n": len(pairs), "accuracy": round(sum(w == g for w, g in pairs) / len(pairs), 3),
                "fail_precision": round(tp / (tp + fp), 3) if tp + fp else None,
                "fail_recall": round(tp / (tp + fn), 3) if tp + fn else None,
                "to_review": sum(g == "review" for _, g in pairs)}
    allp = [x for v in per.values() for x in v]
    tf = [x for x in fatal_hits if x[0]]
    return {"calls": len(results), "parameters": {k: {**stats(v), "type": weights[k].check.type} for k, v in per.items()},
            "overall": stats(allp) if allp else None,
            "decision_accuracy": round(sum(decisions) / len(decisions), 3) if decisions else None,
            "fatal_recall": round(sum(g for _, g in tf) / len(tf), 3) if tf else None,
            "fatal_false_alarms": sum(g and not w for w, g in fatal_hits),
            "score_mae": round(sum(score_err) / len(score_err), 2) if score_err else None}


def run_bench(card: Scorecard, evon=None, n: int = 40, seed: int = 7, samples: int = 3, concurrency: int = 4, on_result=None):
    calls, truth = build_corpus(n, seed)
    convs = [from_turns(c["call_id"], c["turns"], {k: v for k, v in c.items() if k != "turns"}) for c in calls]
    results = run_batch(convs, card, evon, samples, concurrency, on_result)
    return calls, truth, results, evaluate(results, truth, card)
