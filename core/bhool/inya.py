"""Gnani's Inya agent platform, from the outside (docs.gnani.ai, Agent Builder Platform API).

Bhool uses it three ways:
- **deploy**: turn a suite's SOP into an Inya agent (Create Agent + Update Agent), so the agent under test is built
  on Gnani's own platform rather than by Bhool;
- **call**: ask Inya to phone Bhool's number with that agent (Trigger Test Call), and run a Bhool caller on the line;
- **cross-check**: fetch Inya's own log of the same call and set it beside Bhool's. Bhool knows exactly what its
  caller said and Inya knows exactly what its agent said, so each side's speech recognition over a real phone line is
  measured against the other side's ground truth.
"""

from __future__ import annotations

import os
import time

import httpx

from .bench import cer

BASE = "https://api.inya.ai/platform/v1"


class InyaError(RuntimeError):
    pass


class Inya:
    def __init__(self, api_key: str | None = None, environment: str | None = None, http: httpx.Client | None = None):
        self.key = api_key or os.environ.get("INYA_API_KEY", "")
        if not self.key:
            raise InyaError("set INYA_API_KEY in .env (an Inya API key with the agents permission)")
        self.env = environment or os.environ.get("INYA_ENVIRONMENT", "development")
        self.http = http or httpx.Client(timeout=30)

    def _req(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, f"{BASE}{path}", headers={"x-api-key": self.key}, **kw)
        if r.status_code >= 300:
            raise InyaError(f"Inya {method} {path}: HTTP {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def create_agent(self, name: str, description: str = "") -> str:
        return self._req("POST", "/agents", json={"botName": name, "description": description})["response"]["botId"]

    def update_agent(self, bot_id: str, **fields) -> dict:
        return self._req("PUT", f"/agents/{bot_id}", json=fields)

    def trigger_call(self, bot_id: str, phone: str, country_code: str, name: str, ref: str = "") -> dict:
        body = {"phone": phone, "countryCode": country_code, "name": name}
        if ref:
            body["clientReferenceId"] = ref
        return self._req("POST", f"/agents/{bot_id}/trigger_call", params={"environment": self.env}, json=body)

    def logs(self, bot_id: str | None = None, since: float | None = None, search: str = "", page_size: int = 20) -> list[dict]:
        body: dict = {"pageNo": 1, "pageSize": page_size}
        if search:
            body["searchTerm"] = search
        if since:
            body["filter"] = {"startDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))}
        params = {"environment": self.env} | ({"botId": bot_id} if bot_id else {})
        return self._req("POST", "/conversations/logs", params=params, json=body).get("response", {}).get("data", [])

    def stats(self, conversation_id: str) -> dict:
        return self._req("GET", f"/conversations/{conversation_id}/stats", params={"environment": self.env})

    def audio(self, conversation_id: str) -> bytes:
        r = self.http.get(f"{BASE}/conversations/{conversation_id}/audio", headers={"x-api-key": self.key},
                          params={"environment": self.env})
        if r.status_code >= 300:
            raise InyaError(f"Inya audio: HTTP {r.status_code} {r.text[:200]}")
        return r.content

    def find_call(self, bot_id: str, name: str, since: float, wait_s: float = 120, every_s: float = 10) -> dict | None:
        """The conversation Inya logged for a call Bhool triggered (matched by the callee label Bhool sent)."""
        end = time.time() + wait_s
        while True:
            for c in self.logs(bot_id, since=since - 60, search=name):
                if c.get("name") == name and c.get("transcript"):
                    return c
            if time.time() >= end:
                return None
            time.sleep(every_s)


def agent_fields(suite, persona) -> dict:
    """An Inya agent built from a suite's SOP, with one persona's account record as its CRM. Only fields the Update
    Agent API documents; voice and models are left to the platform's defaults unless the suite names them."""
    crm = "\n".join(f"- {k}: {v}" for k, v in persona.crm.items())
    a = suite.agent
    prompt = (f"You are {a.name}, a voice agent on a phone call.\n\nRules (follow them exactly):\n{a.sop.strip()}\n\n"
              f"Account record for this call (never read any of it out before the caller has verified):\n{crm}\n\n"
              "Speak briefly, one or two sentences a turn, in the caller's language.")
    langs = [lg for lg in a.languages][:3] or ["hi-IN"]
    lender = persona.crm.get("lender", a.name)
    return {"systemPrompt": prompt, "greetingMessage": f"नमस्ते, मैं {lender} से बोल रही हूँ। यह call record हो सकती है।",
            "description": f"Bhool Bhulaiya test agent for suite {suite.name}", "botDetails": {"language": langs},
            "languageSwitch": len(langs) > 1}


def crosscheck(turns: list, inya_transcript: list[dict]) -> dict:
    """Each side's speech recognition against the other side's ground truth, turn by turn in order.

    caller -> agent: what Bhool's caller said (exact text it sent to Timbre) vs what Inya's agent heard (user turns).
    agent -> caller: what Inya's agent said (its own log, assistant turns) vs what Bhool's caller heard (Prisma).
    """
    def side(who):
        return [t.text if hasattr(t, "text") else t["text"] for t in turns
                if (t.speaker if hasattr(t, "speaker") else t["speaker"]) == who]
    said, heard_by_bhool = side("caller"), side("agent")
    heard_by_agent = [m.get("content", "") for m in inya_transcript if m.get("role") == "user"]
    said_by_agent = [m.get("content", "") for m in inya_transcript if m.get("role") == "assistant"]

    def pairs(ref, hyp):
        rows = [{"ref": r, "hyp": h, "cer": round(cer(r, h), 3)} for r, h in zip(ref, hyp)]
        return {"pairs": rows, "unpaired": abs(len(ref) - len(hyp)),
                "cer": round(sum(r["cer"] for r in rows) / len(rows), 3) if rows else None}

    return {"caller_to_agent": pairs(said, heard_by_agent), "agent_to_caller": pairs(said_by_agent, heard_by_bhool)}
