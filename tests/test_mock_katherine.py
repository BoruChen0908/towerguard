"""Tests for the v1.2 pure advisory builders (no Redis, no state).

The old time-driven build_advisory/build_briefing_* moved into
fixtures/advisory_builders.py + advisory_briefing.py when mock_katherine became
condition-driven; these cover the pure assembly of the new payloads.
"""

from fixtures import advisory_briefing
from fixtures.advisory_builders import (
    build_advisory,
    build_conflict_block,
    build_evidence,
    build_lifecycle_event,
    condition_key,
    pair_callsigns,
)

_CG = {
    "event_type": "conflict_geometry",
    "alert_id": "CG-0007",
    "tier": "HIGH",
    "closest_pair": {
        "callsigns": ["UAL412", "AAL891"],
        "projected_separation_nm": 2.8,
        "icao_minimum_nm": 3.0,
        "time_to_violation_seconds": 70,
    },
}
_TD = {
    "event_type": "traffic_density",
    "alert_id": "TD-0003",
    "tier": "LOW",
    "aircraft_count": 2,
    "score": 0.12,
}
_WI = {
    "event_type": "workload_index",
    "alert_id": "WI-0005",
    "tier": "MEDIUM",
    "staffed_controllers": 31,
    "recommended_controllers": 52,
    "score": 0.45,
}


class TestConditionKey:
    def test_callsigns_sorted_order_independent(self):
        assert pair_callsigns(_CG) == ["AAL891", "UAL412"]

    def test_condition_key_shape(self):
        key = condition_key("KJFK", "conflict_geometry", ["AAL891", "UAL412"])
        assert key == "KJFK:conflict_geometry:AAL891/UAL412"


class TestEvidence:
    def test_evidence_has_three_signals_with_detail(self):
        ev = build_evidence(_TD, _CG, _WI)
        assert len(ev["signals"]) == 3
        for sig in ev["signals"]:
            assert "event_type" in sig
            assert "tier" in sig
            assert "key_values" in sig
            assert sig["detail"]  # one-line detail present

    def test_conflict_signal_detail_puts_number_against_threshold(self):
        ev = build_evidence(_TD, _CG, _WI)
        cg_sig = next(
            s for s in ev["signals"] if s["event_type"] == "conflict_geometry"
        )
        assert "2.8 NM vs ICAO min 3.0" in cg_sig["detail"]


class TestConflictBlock:
    def test_conflict_block_has_exactly_two_contradictory_signals(self):
        block = build_conflict_block(_TD, _CG)
        assert len(block["between"]) == 2
        kinds = {b["event_type"] for b in block["between"]}
        assert kinds == {"conflict_geometry", "traffic_density"}
        assert block["note"]


class TestBuildAdvisory:
    def test_advisory_has_contract_fields_and_escalate(self):
        adv = build_advisory(
            advisory_id="ADV-0001",
            airport="KJFK",
            action="ESCALATE",
            severity="HIGH",
            summary="Projected separation violation.",
            recommended_attention="UAL412/AAL891 closing.",
            condition_key="KJFK:conflict_geometry:AAL891/UAL412",
            evidence=build_evidence(_TD, _CG, _WI),
            contributing_signals=[
                "traffic_density",
                "conflict_geometry",
                "workload_index",
            ],
        )
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
            "condition_key",
            "evidence",
        ):
            assert field in adv
        assert adv["action"] == "ESCALATE"
        assert adv["confirmed_by_controller"] is False

    def test_optional_fields_omitted_when_empty(self):
        adv = build_advisory(
            advisory_id="ADV-0002",
            airport="KJFK",
            action="ESCALATE",
            severity="HIGH",
            summary="x",
            recommended_attention="y",
            condition_key="k",
            evidence={"signals": []},
            contributing_signals=[],
        )
        assert "supersedes" not in adv
        assert "in_response_to" not in adv
        assert "conflict" not in adv

    def test_optional_fields_present_when_given(self):
        adv = build_advisory(
            advisory_id="ADV-0003",
            airport="KJFK",
            action="SURFACE_CONFLICT",
            severity="HIGH",
            summary="x",
            recommended_attention="y",
            condition_key="k",
            evidence={"signals": []},
            contributing_signals=[],
            supersedes=["ADV-0002"],
            in_response_to="RAS-1a2b",
            conflict=build_conflict_block(_TD, _CG),
        )
        assert adv["supersedes"] == ["ADV-0002"]
        assert adv["in_response_to"] == "RAS-1a2b"
        assert adv["conflict"]["between"]


class TestLifecycleEvent:
    def test_lifecycle_event_shape(self):
        ev = build_lifecycle_event(
            advisory_id="ADV-0009",
            new_state="resolved",
            reason="conflict_cleared",
            in_response_to="RAS-1a2b",
        )
        assert ev["type"] == "advisory_lifecycle"
        assert ev["advisory_id"] == "ADV-0009"
        assert ev["new_state"] == "resolved"
        assert ev["in_response_to"] == "RAS-1a2b"
        assert ev["reason"] == "conflict_cleared"
        assert ev["timestamp"]


class TestBriefingAssembly:
    def _events(self):
        return [
            {
                "timestamp": "2026-06-12T18:00:00Z",
                "kind": "tier_change",
                "summary": "CONFLICT GEOMETRY LOW → HIGH (UAL412/AAL891)",
                "ref": "CG-0007",
                "tier": "HIGH",
            },
            {
                "timestamp": "2026-06-12T18:00:05Z",
                "kind": "advisory",
                "summary": "Projected separation violation (HIGH) for AAL891/UAL412.",
                "ref": "ADV-0001",
                "tier": "HIGH",
            },
        ]

    def test_briefing_has_five_sections(self):
        md = advisory_briefing.build_briefing_markdown(
            "KJFK", self._events(), lambda _id: advisory_briefing.DECISION_PENDING
        )
        for heading in (
            "### 1. Current traffic picture",
            "### 2. Active advisories",
            "### 3. Notable events this shift",
            "### 4. Weather and NOTAMs",
            "### 5. Pending actions",
        ):
            assert heading in md
        assert "Position Relief Briefing" in md
        # Section 1 reflects the real tier_change
        assert "CONFLICT GEOMETRY: HIGH" in md
        # Section 2 lists the open advisory, pending mark
        assert "ADV-0001" in md

    def test_resolved_advisory_drops_out_of_active(self):
        events = self._events() + [
            {
                "timestamp": "2026-06-12T18:01:00Z",
                "kind": "resolve",
                "summary": "Advisory ADV-0001 resolved (cleared)",
                "ref": "ADV-0001",
                "tier": None,
            }
        ]
        md = advisory_briefing.build_briefing_markdown(
            "KJFK", events, lambda _id: advisory_briefing.DECISION_PENDING
        )
        # ADV-0001 was resolved → no longer active, no pending decisions
        assert "No active advisories." in md
        assert "No advisories awaiting a decision." in md

    def test_confirmed_advisory_marked_and_not_pending(self):
        md = advisory_briefing.build_briefing_markdown(
            "KJFK", self._events(), lambda _id: advisory_briefing.DECISION_CONFIRMED
        )
        assert "✓ ADV-0001" in md
        assert "No advisories awaiting a decision." in md

    def test_payload_keeps_advisory_id_and_adds_briefing_id(self):
        payload = advisory_briefing.build_briefing_payload(
            "BRF-0001",
            "KJFK",
            self._events(),
            lambda _id: advisory_briefing.DECISION_PENDING,
        )
        assert payload["briefing_id"] == "BRF-0001"
        assert payload["advisory_id"] == "BRF-0001"  # defaults to briefing_id
        assert payload["markdown"].startswith("---")
