"""The Inya platform client against a mocked HTTP transport, shaped like docs.gnani.ai's examples."""

import json

import httpx
import pytest

from diapason.inya import Inya, InyaError, agent_fields, crosscheck
from diapason.scenarios import load_suite


def client(handler):
    return Inya("k", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_deploy_trigger_and_logs_follow_the_documented_contract():
    seen = []

    def handler(req):
        seen.append(req)
        body = json.loads(req.content or b"{}")
        if req.method == "POST" and req.url.path.endswith("/agents"):
            return httpx.Response(201, json={"status": "success", "response": {"botId": "b1", "botName": body["botName"]}})
        if req.method == "PUT":
            return httpx.Response(200, json={"status": "success", "response": {"botId": "b1"}})
        if req.url.path.endswith("/trigger_call"):
            return httpx.Response(200, json={"status": "success", "message": "Call is being triggered", "requestId": "r1",
                                             "response": {"clientReferenceId": body.get("clientReferenceId")}})
        return httpx.Response(200, json={"response": {"data": [{"conversationId": "c1", "name": "diapason-x", "transcript": [
            {"role": "assistant", "content": "नमस्ते"}, {"role": "user", "content": "हाँ बोलिए"}]}]}})

    suite = load_suite("suites/proof.yaml")
    inya = client(handler)
    bot = inya.create_agent("diapason-proof-ramesh")
    fields = agent_fields(suite, suite.personas[0])
    inya.update_agent(bot, **fields)
    inya.trigger_call(bot, "4155550100", "+1", "diapason-x", "diapason-x")
    logs = inya.logs(bot, search="diapason-x")

    assert all(r.headers["x-api-key"] == "k" for r in seen)
    put = json.loads(seen[1].content)
    assert "Verify identity" in put["systemPrompt"] and "4821" in put["systemPrompt"]   # SOP and CRM reach the agent
    assert put["botDetails"]["language"] == ["hi-IN", "gu-IN"] and put["languageSwitch"] is True
    trig = seen[2]
    assert trig.url.params["environment"] == "development"                               # Developer-role keys need it
    assert json.loads(trig.content) == {"phone": "4155550100", "countryCode": "+1", "name": "diapason-x",
                                        "clientReferenceId": "diapason-x"}
    assert logs[0]["conversationId"] == "c1"


def test_errors_carry_the_status_and_body():
    inya = client(lambda req: httpx.Response(400, json={"message": "number not whitelisted"}))
    with pytest.raises(InyaError, match="400.*whitelisted"):
        inya.trigger_call("b1", "9800000000", "+91", "x")


def test_crosscheck_scores_each_side_against_the_other_sides_words():
    turns = [{"speaker": "agent", "text": "नमस्ते मैं सहयोग फाइनेंस से"}, {"speaker": "caller", "text": "हाँ बोलिए"},
             {"speaker": "agent", "text": "लोन के आखिरी चार अंक"}, {"speaker": "caller", "text": "चार आठ दो एक"}]
    inya_log = [{"role": "assistant", "content": "नमस्ते मैं सहयोग फाइनेंस से"}, {"role": "user", "content": "हाँ बोलिए"},
                {"role": "assistant", "content": "लोन के आखिरी चार अंक बताइए"}, {"role": "user", "content": "चार आठ दो"}]
    x = crosscheck(turns, inya_log)
    assert x["caller_to_agent"]["pairs"][0]["cer"] == 0.0
    assert x["caller_to_agent"]["pairs"][1]["cer"] > 0           # the agent lost "एक": its ears, measured
    assert x["agent_to_caller"]["pairs"][1]["cer"] > 0           # Diapason's ears missed "बताइए"
    assert x["caller_to_agent"]["unpaired"] == 0
