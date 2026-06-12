"""Tests for fixtures/mock_katherine.py builder functions (pure, no Redis)."""

from fixtures.mock_katherine import (
    build_advisory,
    build_briefing_markdown,
    build_briefing_payload,
)

_CONFLICT = {
    "event_type": "conflict_geometry",
    "tier": "HIGH",
    "closest_pair": {
        "callsigns": ["UAL412", "AAL891"],
        "projected_separation_nm": 2.8,
        "icao_minimum_nm": 3.0,
        "time_to_violation_seconds": 70,
    },
}


class TestBuildAdvisory:
    def test_advisory_has_contract_fields_and_escalate(self):
        adv = build_advisory("ADV-0001", _CONFLICT)
        for field in (
            "advisory_id",
            "timestamp",
            "airport",
            "action",
            "severity",
            "confidence",
            "summary",
            "contributing_signals",
            "recommended_attention",
            "human_override_required",
            "confirmed_by_controller",
            "generated_at",
        ):
            assert field in adv
        assert adv["action"] == "ESCALATE"
        assert adv["confirmed_by_controller"] is False
        # References the recent conflict pair
        assert "UAL412/AAL891" in adv["recommended_attention"]

    def test_advisory_without_conflict_uses_fallback(self):
        adv = build_advisory("ADV-0002", None)
        assert adv["action"] == "ESCALATE"
        assert adv["recommended_attention"]


class TestBuildBriefing:
    def test_briefing_has_five_sections(self):
        md = build_briefing_markdown("ADV-0001", _CONFLICT)
        for heading in (
            "### 1. Current traffic picture",
            "### 2. Active advisories",
            "### 3. Notable events this shift",
            "### 4. Weather and NOTAMs",
            "### 5. Pending actions",
        ):
            assert heading in md
        assert "Position Relief Briefing" in md
        assert "UAL412/AAL891" in md

    def test_briefing_payload_shape(self):
        payload = build_briefing_payload("ADV-0003", _CONFLICT)
        assert set(payload.keys()) == {"advisory_id", "markdown"}
        assert payload["advisory_id"] == "ADV-0003"
        assert payload["markdown"].startswith("---")
