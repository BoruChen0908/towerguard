"""Tests for the optional LLM augmentation layer (Option B).

The deterministic engine owns every decision and guardrail; the LLM only
rewrites the human-facing advisory text and the briefing prose, and always
degrades to the deterministic template. These tests assert exactly that:

  - config gate is OFF unless explicitly enabled AND a key is present
  - the engine, given a phraser, publishes the LLM text in summary /
    recommended_attention while every decision/lifecycle field is unchanged
  - a phraser that raises (or absent) leaves the deterministic template intact
  - AdvisoryPhraser / BriefingNarrator fall back to the template off, on parse
    failure, and (for the briefing) when a required marker is dropped
"""

import json

import fakeredis
import pytest

import config
from agents import llm_client
from agents.narrator import BriefingNarrator
from agents.orchestrator import AdvisoryPhraser
from dashboard.shift_stream import KIND_ADVISORY, read_recent
from dashboard.topics import TOPIC_ADVISORY
from fixtures.advisory_engine import AdvisoryEngine


@pytest.fixture()
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _cg_high(alert="CG-0001"):
    closest = {
        "callsigns": ["AAL891", "UAL412"],
        "projected_separation_nm": 2.8,
        "icao_minimum_nm": 3.0,
        "time_to_violation_seconds": 50,
    }
    return {
        "event_type": "conflict_geometry",
        "alert_id": alert,
        "airport": "KJFK",
        "tier": "HIGH",
        "closest_pair": closest,
        "all_conflicts": [closest],
    }


def _td(tier="MEDIUM"):
    return {
        "event_type": "traffic_density",
        "alert_id": "TD-0001",
        "tier": tier,
        "aircraft_count": 80,
        "score": 0.7,
    }


def _advisories(fake_redis):
    msgs = []

    original = fake_redis.publish

    def cap(channel, message):
        if channel == TOPIC_ADVISORY:
            msgs.append(json.loads(message))
        return original(channel, message)

    fake_redis.publish = cap
    return msgs


# --- fakes -----------------------------------------------------------------


class _FakePhraser:
    def __init__(self, summary, attention):
        self._s, self._a = summary, attention

    def phrase(self, **_kwargs):
        return self._s, self._a


class _RaisingPhraser:
    def phrase(self, **_kwargs):
        raise RuntimeError("boom")


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _FakeClient:
    """Stand-in Anthropic client returning a canned messages.create() response."""

    def __init__(self, text):
        self._text = text
        self.messages = self

    def create(self, **_kwargs):
        return _Resp(self._text)


# --- config gate -----------------------------------------------------------


class TestConfigGate:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("TOWERGUARD_USE_LLM", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert config.llm_enabled() is False

    def test_needs_key_even_when_enabled(self, monkeypatch):
        monkeypatch.setenv("TOWERGUARD_USE_LLM", "1")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert config.llm_enabled() is False

    def test_on_with_both(self, monkeypatch):
        monkeypatch.setenv("TOWERGUARD_USE_LLM", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert config.llm_enabled() is True

    def test_model_override(self, monkeypatch):
        monkeypatch.setenv("TOWERGUARD_LLM_MODEL", "claude-haiku-4-5")
        assert config.llm_model() == "claude-haiku-4-5"


# --- engine integration ----------------------------------------------------


class TestEngineWithPhraser:
    def test_published_advisory_uses_llm_text(self, fake_redis):
        adv_msgs = _advisories(fake_redis)
        engine = AdvisoryEngine(
            fake_redis,
            "KJFK",
            phraser=_FakePhraser("LLM SUMMARY", "LLM ATTENTION"),
        )
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        adv = engine.on_conflict_event(_cg_high())

        # Human-facing text is the LLM's...
        assert adv["summary"] == "LLM SUMMARY"
        assert adv["recommended_attention"] == "LLM ATTENTION"
        assert adv_msgs[0]["summary"] == "LLM SUMMARY"
        # ...while every decision / guardrail field is the engine's, untouched.
        assert adv["action"] == "ESCALATE"
        assert adv["severity"] == "HIGH"
        assert adv["condition_key"] == "KJFK:conflict_geometry:AAL891/UAL412"
        assert len(adv["evidence"]["signals"]) == 3
        assert adv["human_override_required"] is True
        assert adv["confirmed_by_controller"] is False
        # The advisory shift event mirrors the LLM summary.
        adv_events = [e for e in read_recent(fake_redis) if e["kind"] == KIND_ADVISORY]
        assert adv_events[0]["summary"] == "LLM SUMMARY"

    def test_phraser_exception_falls_back_to_template(self, fake_redis):
        engine = AdvisoryEngine(fake_redis, "KJFK", phraser=_RaisingPhraser())
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        adv = engine.on_conflict_event(_cg_high())
        # Deterministic template text survives; advisory still issued correctly.
        assert "AAL891/UAL412" in adv["summary"]
        assert adv["severity"] == "HIGH"
        assert adv["action"] == "ESCALATE"

    def test_no_phraser_is_deterministic(self, fake_redis):
        engine = AdvisoryEngine(fake_redis, "KJFK")
        engine.update_module("towerguard:traffic_density", _td("MEDIUM"))
        adv = engine.on_conflict_event(_cg_high())
        assert adv["summary"] == (
            "Projected separation violation (HIGH) for AAL891/UAL412."
        )


# --- AdvisoryPhraser --------------------------------------------------------


class TestAdvisoryPhraser:
    def _args(self):
        return dict(
            action="ESCALATE",
            severity="HIGH",
            callsigns=["AAL891", "UAL412"],
            evidence={"signals": []},
            fallback_summary="FB SUMMARY",
            fallback_attention="FB ATTENTION",
        )

    def test_returns_fallback_when_off(self, monkeypatch):
        monkeypatch.setattr(llm_client, "available", lambda: False)
        s, a = AdvisoryPhraser().phrase(**self._args())
        assert (s, a) == ("FB SUMMARY", "FB ATTENTION")

    def test_uses_llm_json_when_on(self, monkeypatch):
        monkeypatch.setattr(llm_client, "available", lambda: True)
        monkeypatch.setattr(
            llm_client,
            "get_client",
            lambda: _FakeClient(
                json.dumps({"summary": "S!", "recommended_attention": "A!"})
            ),
        )
        s, a = AdvisoryPhraser().phrase(**self._args())
        assert (s, a) == ("S!", "A!")

    def test_bad_json_falls_back(self, monkeypatch):
        monkeypatch.setattr(llm_client, "available", lambda: True)
        monkeypatch.setattr(llm_client, "get_client", lambda: _FakeClient("not json"))
        s, a = AdvisoryPhraser().phrase(**self._args())
        assert (s, a) == ("FB SUMMARY", "FB ATTENTION")

    def test_partial_json_falls_back(self, monkeypatch):
        monkeypatch.setattr(llm_client, "available", lambda: True)
        monkeypatch.setattr(
            llm_client,
            "get_client",
            lambda: _FakeClient(json.dumps({"summary": "only summary"})),
        )
        s, a = AdvisoryPhraser().phrase(**self._args())
        assert (s, a) == ("FB SUMMARY", "FB ATTENTION")


# --- BriefingNarrator -------------------------------------------------------


_TEMPLATE = (
    "---\n## Position Relief Briefing — KJFK 1842Z\n"
    "*AI-generated draft. Outgoing controller must review and confirm.*\n\n"
    "### 1. Current traffic picture\n- TRAFFIC DENSITY: HIGH\n\n"
    "---\n*Reviewed and confirmed by: ____  [TIME]____*\n---\n"
)


class TestBriefingNarrator:
    def test_returns_template_when_off(self, monkeypatch):
        monkeypatch.setattr(llm_client, "available", lambda: False)
        assert BriefingNarrator().render(_TEMPLATE) == _TEMPLATE

    def test_uses_llm_when_markers_present(self, monkeypatch):
        rewritten = (
            "## Position Relief Briefing\n"
            "*AI-generated draft. Outgoing controller must review and confirm.*\n"
            "Traffic is HIGH.\n*Reviewed and confirmed by: ___*"
        )
        monkeypatch.setattr(llm_client, "available", lambda: True)
        monkeypatch.setattr(llm_client, "get_client", lambda: _FakeClient(rewritten))
        assert BriefingNarrator().render(_TEMPLATE) == rewritten

    def test_missing_marker_falls_back(self, monkeypatch):
        # Rewrite dropped the draft disclaimer / confirmation line → discard it.
        monkeypatch.setattr(llm_client, "available", lambda: True)
        monkeypatch.setattr(
            llm_client, "get_client", lambda: _FakeClient("Just some prose, no markers.")
        )
        assert BriefingNarrator().render(_TEMPLATE) == _TEMPLATE
