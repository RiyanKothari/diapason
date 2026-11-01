"""Bhool Guard: the auditor moved in front of the agent's mouth.

Testing finds violations before launch; QA finds them after the call. Guard stops them while the call is happening:
every line the agent is about to speak is checked in code (about 1 ms per line measured live; no model call except to translate a wrong-language line) and rewritten if it
would break a rule, before it reaches text-to-speech.

- banned phrases (threats), in every script Prisma writes them in      -> the sentence is dropped
- asking for an OTP, CVV, PIN or password                               -> the sentence is dropped
- account details (amount, overdue) before the caller has proven who
  they are, checked against the account's own last 4 digits, which the
  agent knows and the caller must say (digits or number words)         -> replaced by the verification question
- the account's verification digits (never the agent's to say: the
  caller must say them, and reading them out hands them to an attacker)  -> the sentence is dropped
- the first line without the recording disclosure                       -> the disclosure is added
- a reply in another script than a Gujarati, Tamil, Telugu, Kannada,
  Malayalam, Bengali or Punjabi caller's                                -> translated by Evon when one is given
Guard's own lines (the disclosure, the verification question) are said in the caller's language when it knows it.

It is deterministic, so it can't hallucinate a rewrite, and it can't make an agent better at its job: only stop it
saying what it must never say. Endpointing and barge-in failures are engineering, not text, and stay the agent's.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .judge.dates import date_keys
from .judge.loanwords import variants
from .judge.rubric import normalize
from .judge.scripts import OWN_SCRIPT, dominant, spoken_digits

_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")
_SENTENCE = re.compile(r"(?<=[।.!?])\s+")
SCRIPT_LANG = {"gujarati": "gu-IN", "tamil": "ta-IN", "telugu": "te-IN", "kannada": "kn-IN", "malayalam": "ml-IN",
               "bengali": "bn-IN", "gurmukhi": "pa-IN"}
# Named in English and in its own script: asked for "gu-IN", the Evon build on test answered in Kannada 6 times out of 6.
LANG_NAMES = {"gu-IN": "Gujarati (ગુજરાતી), in Gujarati script", "ta-IN": "Tamil (தமிழ்), in Tamil script",
              "te-IN": "Telugu (తెలుగు), in Telugu script", "kn-IN": "Kannada (ಕನ್ನಡ), in Kannada script",
              "ml-IN": "Malayalam (മലയാളം), in Malayalam script", "bn-IN": "Bengali (বাংলা), in Bengali script",
              "pa-IN": "Punjabi (ਪੰਜਾਬੀ), in Gurmukhi script"}
# Languages Guard has its own lines in. Not Latin script: Hinglish and romanized Gujarati are written in it too, so a
# Latin-script caller keeps the agent's language rather than being switched to English.
TEMPLATE_LANG = {"gujarati": "gu", "devanagari": "hi"}


def evon_translator(evon):
    """Guard's `translate` hook on an Evon client: (text, "gu-IN") -> the line in that language."""
    def translate(text: str, lang: str) -> str:
        name = LANG_NAMES.get(lang, lang)
        return evon.chat([{"role": "system", "content": f"Translate the line into {name}, as spoken on a phone call. Keep names "
                                                        "and numbers. Reply with only the translation."},
                          {"role": "user", "content": text}], temperature=0.1, max_tokens=200)
    return translate

LINES = {
    "disclose": {"hi": "यह कॉल quality के लिए record हो सकती है।", "gu": "આ કૉલ quality માટે record થઈ શકે છે.",
                 "en": "This call may be recorded for quality."},
    "verify": {"hi": "आगे बात करने से पहले, कृपया अपने loan ID के आखिरी चार अंक बताइए।",
               "gu": "આગળ વાત કરતા પહેલા, કૃપા કરીને તમારા loan ID ના છેલ્લા ચાર અંક જણાવો.",
               "en": "Before we go on, could you tell me the last four digits of your loan ID?"},
    "safe": {"hi": "अगर कोई परेशानी है तो बताइए, हम मिलकर कोई रास्ता निकालेंगे।",
             "gu": "જો કોઈ તકલીફ હોય તો કહો, આપણે સાથે મળીને રસ્તો કાઢીશું.",
             "en": "If anything is making this difficult, tell me and we'll work out a way together."},
}
SECRET_REQUESTS = ["tell me the OTP", "share the OTP", "tell me the CVV", "tell me your PIN", "tell me your password",
                   "ओटीपी बताइए", "OTP बताइए", "ओटीपी बता दीजिए", "CVV बताइए", "पिन बताइए", "पासवर्ड बताइए",
                   "OTP બતાવો", "ઓટીપી બતાવો", "પાસવર્ડ બતાવો"]
REVEAL = ["rupees", "overdue", "amount", "due date", "outstanding", "balance", "रुपये", "रुपए", "ओवरड्यू", "overdue है", "ओवरड्यू है",
          "बकाया", "राशि", "બાકી", "રૂપિયા", "રકમ"]
_MONEY = re.compile(r"(rs\.?|inr|₹|रु\.?)\s*\d", re.IGNORECASE)        # any amount, even a wrong one ("Rs 450")
RECORD = ["record", "recorded", "रिकॉर्ड", "रेकॉर्ड", "રેકોર્ડ"]


@dataclass
class GuardEvent:
    rule: str
    action: str           # dropped | replaced | added | translated
    before: str
    after: str
    ms: float


@dataclass
class Guard:
    crm: dict
    banned: list[str] = field(default_factory=lambda: ["police", "legal action", "jail", "court"])
    banned_variants: dict = field(default_factory=dict)
    verify_key: str = "loan_id_last4"
    translate: object = None           # optional (text, target_lang) -> text, e.g. Evon; used only on a script mismatch
    verified: bool = False
    disclosed: bool = False
    caller_script: str | None = None
    events: list[GuardEvent] = field(default_factory=list)

    # ------------------------------------------------------------ what the caller said
    def hear(self, caller_text: str) -> None:
        if self._says_digits(caller_text):
            self.verified = True
        self.caller_script = dominant(caller_text) or self.caller_script

    def _says_digits(self, text: str) -> bool:
        want = str(self.crm.get(self.verify_key) or "")
        return want.isdigit() and want in spoken_digits(text)

    def _echoes_id(self, text: str) -> bool:
        """The full verification digits, or a 3+ digit piece of them (seen live: "आपका loan ID 482 है")."""
        want = str(self.crm.get(self.verify_key) or "")
        runs = re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d)", "", text.translate(_DIGITS)))
        return want.isdigit() and (self._says_digits(text) or any(len(r) >= 3 and r in want for r in runs))

    # ------------------------------------------------------------ what the agent is about to say
    def _has(self, phrases: list[str], text: str, extra: dict | None = None) -> str | None:
        padded = f" {normalize(text)} "
        for p in phrases:
            for v in variants(p, extra or {}):
                n = normalize(v)
                if n and (f" {n} " in padded or (" " in n and n in padded)):
                    return v
        return None

    def _reveals(self, text: str) -> str | None:
        plain = text.translate(_DIGITS)
        for key in ("amount_due", "due_date"):
            value = str(self.crm.get(key) or "")
            if value and normalize(value) in normalize(plain):
                return value
        due = date_keys(str(self.crm.get("due_date") or ""))
        said = date_keys(text)
        if due and due <= said:                 # the due date in any script: "28 अक्टूबर" (seen live), "28 ઓક્ટોબર"
            return str(self.crm["due_date"])
        if any(k[0] == "d" for k in said) and any(k[0] == "m" for k in said):
            return text                         # an invented one too: "payment due છે 3 નવેમ્બરે" (seen live, real date 1 Nov)
        if m := _MONEY.search(plain):
            return m.group(0)
        return self._has(REVEAL, text)

    def filter(self, say: str, lang: str = "hi-IN") -> str:
        """The line as it may be spoken. Records every intervention."""
        t0 = time.perf_counter()
        lg = TEMPLATE_LANG.get(self.caller_script or "", (lang or "hi")[:2])
        lg = lg if lg in LINES["verify"] else "hi"
        out = say
        kept = []
        for s in _SENTENCE.split(out.strip()) if out.strip() else []:
            hit = self._has(self.banned, s, self.banned_variants)
            if hit:
                self._log("banned_phrase", "dropped", s, "", t0)
                continue
            hit = self._has(SECRET_REQUESTS, s)
            if hit:
                self._log("secret_request", "dropped", s, "", t0)
                continue
            if self._echoes_id(s):
                self._log("verification_digits", "dropped", s, "", t0)
                continue
            kept.append(s)
        out = " ".join(kept)
        if kept != _SENTENCE.split(say.strip()) and not out:
            out = LINES["safe" if self.verified else "verify"][lg]
        if not self.verified and (hit := self._reveals(out)):
            self._log("account_before_verification", "replaced", out, LINES["verify"][lg], t0)
            out = LINES["verify"][lg]
        if not self.disclosed:
            if not self._has(RECORD, out):
                self._log("missing_disclosure", "added", out, LINES["disclose"][lg], t0)
                out = f"{LINES['disclose'][lg]} {out}".strip()
            self.disclosed = True
        if self.translate and self.caller_script in OWN_SCRIPT and dominant(out) not in (self.caller_script, None):
            target = SCRIPT_LANG[self.caller_script]
            try:
                new = str(self.translate(out, target) or "").strip()
                if new and dominant(new) == self.caller_script:
                    self._log("language_mismatch", "translated", out, new, t0)
                    out = new
                elif new:      # seen live: asked for Gujarati, the model answered in Kannada. Never speak an unchecked translation.
                    self._log("language_mismatch", "translation_rejected", new, out, t0)
            except Exception:
                pass                       # never block speech on a failed translation
        return out

    def _log(self, rule: str, action: str, before: str, after: str, t0: float) -> None:
        self.events.append(GuardEvent(rule, action, before, after, round((time.perf_counter() - t0) * 1000, 3)))
