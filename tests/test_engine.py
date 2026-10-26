"""End-to-end call loop against a scripted agent, fully offline and in real time."""

import asyncio

from bhool.call.engine import run_call
from bhool.channel import PRESETS
from bhool.fakes import ScriptedAgent, ScriptedBrain, fake_hear, fake_speak
from bhool.scenarios import Behaviour, Persona, Scenario


def scenario(behaviour: Behaviour, channel="clean") -> Scenario:
    return Scenario(id="t", persona=Persona(id="p", description="d"), behaviour=behaviour,
                    channel=PRESETS[channel], seed=1)


def call(agent, brain, behaviour, channel="clean", tmp=None):
    return asyncio.run(run_call(scenario(behaviour, channel), agent, brain, fake_speak(), fake_hear(),
                                out_dir=tmp, max_duration_s=40, agent_silent_timeout_s=6))


def test_cooperative_call_measures_agent_latency(tmp_path):
    agent = ScriptedAgent(latency_s=0.7, end_silence_s=0.5, replies=5)
    brain = ScriptedBrain(["हाँ बोलिए", "मेरा loan ID चार आठ दो एक है", "ठीक है, bye"])
    rec = call(agent, brain, Behaviour(id="b", instructions="x"), tmp=tmp_path)
    assert rec.end_reason == "caller_hangup"
    speakers = [t.speaker for t in rec.turns]
    assert speakers[0] == "agent" and speakers.count("caller") == 3
    # The fake replies end_silence (0.5) + latency (0.7) after the caller stops.
    lat = rec.metrics.response_latencies_s
    assert len(lat) >= 2 and all(abs(x - 1.2) < 0.15 for x in lat), lat
    assert rec.metrics.unanswered_turns == 0
    assert (tmp_path / "t" / "run0" / "mix.wav").exists()


def test_agent_hangup_with_disposition():
    agent = ScriptedAgent(replies=1, slots={"loan_id_last4": "4821"})
    rec = call(agent, ScriptedBrain(["हाँ", "और कुछ?", "ठीक है"]), Behaviour(id="b", instructions="x"))
    assert rec.end_reason == "agent_hangup"
    assert rec.dispositions == [{"type": "disposition", "slots": {"loan_id_last4": "4821"}}]


def test_barge_in_yielding_agent_passes():
    agent = ScriptedAgent(reply_s=6.0, greeting_s=6.0, yields=True, yield_s=0.3, replies=2)
    rec = call(agent, ScriptedBrain(["हाँ", "ठीक है bye"]), Behaviour(id="b", instructions="x", interrupt_prob=1.0))
    assert any(e["type"] == "barge_in_attempt" for e in rec.events)
    assert rec.metrics.barge_ins >= 1
    assert rec.metrics.barge_ins_ignored == 0


def test_barge_in_stubborn_agent_is_caught():
    agent = ScriptedAgent(reply_s=6.0, greeting_s=6.0, yields=False, replies=2)
    rec = call(agent, ScriptedBrain(["हाँ", "ठीक है bye"]), Behaviour(id="b", instructions="x", interrupt_prob=1.0))
    assert rec.metrics.barge_ins >= 1
    assert rec.metrics.barge_ins_ignored >= 1


def test_noisy_channel_still_runs():
    agent = ScriptedAgent(replies=5)
    rec = call(agent, ScriptedBrain(["हाँ", "bye"]), Behaviour(id="b", instructions="x"), channel="landline")
    assert rec.end_reason in {"caller_hangup", "agent_hangup"}
    assert rec.metrics.caller_turns >= 1
