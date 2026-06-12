"""Pure builders for v1.2 advisory payloads — no Redis, no state.

These assemble the advisory dict (contact.md §3 + the v1.2 optional fields:
condition_key / supersedes / in_response_to / evidence / conflict) and the
advisory_lifecycle event (design §4). Keeping them pure makes the rule engine's
output deterministic and unit-testable field-by-field.

Evidence (design §2): each contributing signal carries its event_type, alert_id,
tier, the key numeric values, and a one-line ``detail`` that puts the number
against its threshold (e.g. "2.8 NM vs ICAO min 3.0"). SURFACE_CONFLICT cards
additionally carry a ``conflict.between`` block naming exactly the two
contradictory signals — the AI explicitly refuses to arbitrate.
"""

from datetime import datetime, timezone
from typing import Any, Optional

import config

# Lifecycle states the Orchestrator owns (design §4 state machine).
LIFECYCLE_RESOLVED = "resolved"
LIFECYCLE_SUPERSEDED = "superseded"
LIFECYCLE_EXPIRED = "expired"

# Confidence band labels (design §2 Tier 1 — never expose the raw float).
_CONFIDENCE_BY_TIER = {
    "CRITICAL": "High",
    "HIGH": "High",
    "MEDIUM": "Med",
    "LOW": "Low",
}


def utc_now_iso() -> str:
    """Current UTC time as ISO 8601 (matches the module envelope format)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# condition_key
# ---------------------------------------------------------------------------


def pair_callsigns(cg_event: Optional[dict[str, Any]]) -> list[str]:
    """Sorted callsigns of the conflict's closest pair, or [] if none.

    Sorting makes the condition_key order-independent so the same two aircraft
    never produce two distinct conditions (design §3).
    """
    if not cg_event:
        return []
    pair = cg_event.get("closest_pair")
    if isinstance(pair, dict) and pair.get("callsigns"):
        return sorted(pair["callsigns"])
    return []


def condition_key(airport: str, signals: str, callsigns: list[str]) -> str:
    """Build ``{airport}:{signals}:{sorted_callsigns}`` (design §3)."""
    return f"{airport}:{signals}:{'/'.join(callsigns)}"


# ---------------------------------------------------------------------------
# Evidence / conflict blocks (design §2)
# ---------------------------------------------------------------------------


def _signal(
    event: Optional[dict[str, Any]],
    key_values: dict[str, Any],
    detail: str,
) -> dict[str, Any]:
    """One evidence signal: event_type/alert_id/tier + values + one-line detail."""
    event = event or {}
    return {
        "event_type": event.get("event_type"),
        "alert_id": event.get("alert_id"),
        "tier": event.get("tier"),
        "key_values": key_values,
        "detail": detail,
    }


def _conflict_detail(cg_event: Optional[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """key_values + one-line detail for the conflict_geometry signal."""
    pair = (cg_event or {}).get("closest_pair") or {}
    sep = pair.get("projected_separation_nm")
    minimum = pair.get("icao_minimum_nm", config.CG_TERMINAL_SEPARATION_NM)
    ttv = pair.get("time_to_violation_seconds")
    key_values = {
        "projected_separation_nm": sep,
        "icao_minimum_nm": minimum,
        "time_to_violation_seconds": ttv,
    }
    if sep is None:
        return key_values, "No projected separation conflict in the window."
    return (
        key_values,
        f"{sep} NM vs ICAO min {minimum} NM, first violation in {ttv} s.",
    )


def _density_detail(td_event: Optional[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """key_values + one-line detail for the traffic_density signal."""
    td = td_event or {}
    count = td.get("aircraft_count")
    score = td.get("score")
    key_values = {"aircraft_count": count, "score": score}
    return key_values, f"{count} aircraft within 50 NM, density score {score}."


def _workload_detail(wi_event: Optional[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """key_values + one-line detail for the workload_index signal."""
    wi = wi_event or {}
    staffed = wi.get("staffed_controllers")
    recommended = wi.get("recommended_controllers")
    score = wi.get("score")
    short = None
    if isinstance(staffed, int) and isinstance(recommended, int):
        short = max(0, recommended - staffed)
    key_values = {
        "staffed_controllers": staffed,
        "recommended_controllers": recommended,
        "score": score,
    }
    return (
        key_values,
        f"{staffed}/{recommended} controllers on board (short {short}), "
        f"workload score {score}.",
    )


def build_evidence(
    td_event: Optional[dict[str, Any]],
    cg_event: Optional[dict[str, Any]],
    wi_event: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Evidence snapshot of the three modules at advisory time (design §2)."""
    cg_kv, cg_detail = _conflict_detail(cg_event)
    td_kv, td_detail = _density_detail(td_event)
    wi_kv, wi_detail = _workload_detail(wi_event)
    return {
        "signals": [
            _signal(cg_event, cg_kv, cg_detail),
            _signal(td_event, td_kv, td_detail),
            _signal(wi_event, wi_kv, wi_detail),
        ]
    }


def build_conflict_block(
    td_event: Optional[dict[str, Any]],
    cg_event: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """The SURFACE_CONFLICT ``conflict.between`` block — exactly two signals.

    Names the two contradictory claims (low traffic density vs an imminent
    geometric conflict) without preferring either; the AI refuses to arbitrate.
    """
    cg = cg_event or {}
    td = td_event or {}
    pair = cg.get("closest_pair") or {}
    callsigns = "/".join(pair.get("callsigns", []))
    sep = pair.get("projected_separation_nm")
    ttv = pair.get("time_to_violation_seconds")
    return {
        "between": [
            {
                "event_type": cg.get("event_type"),
                "alert_id": cg.get("alert_id"),
                "tier": cg.get("tier"),
                "claim": (
                    f"Imminent separation conflict: {callsigns} to {sep} NM in {ttv} s."
                ),
            },
            {
                "event_type": td.get("event_type"),
                "alert_id": td.get("alert_id"),
                "tier": td.get("tier"),
                "claim": (
                    f"Low traffic load: {td.get('aircraft_count')} aircraft, "
                    f"density tier {td.get('tier')}."
                ),
            },
        ],
        "note": (
            "Signals disagree on threat level. AI declines to arbitrate — "
            "controller judgement required."
        ),
    }


# ---------------------------------------------------------------------------
# Advisory + lifecycle assembly (contact.md §3 / design §4)
# ---------------------------------------------------------------------------


def build_advisory(
    *,
    advisory_id: str,
    airport: str,
    action: str,
    severity: str,
    summary: str,
    recommended_attention: str,
    condition_key: str,
    evidence: dict[str, Any],
    contributing_signals: list[str],
    confidence: float = 0.9,
    supersedes: Optional[list[str]] = None,
    in_response_to: Optional[str] = None,
    conflict: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble a contract §3 advisory plus the v1.2 optional fields.

    The v1.2 fields (condition_key / supersedes / in_response_to / evidence /
    conflict) are all optional downstream; supersedes / in_response_to / conflict
    are omitted entirely when empty so the wire payload stays minimal.
    """
    now = utc_now_iso()
    advisory: dict[str, Any] = {
        "advisory_id": advisory_id,
        "timestamp": now,
        "airport": airport,
        "action": action,
        "severity": severity,
        "confidence": confidence,
        "confidence_band": _CONFIDENCE_BY_TIER.get(severity, "Med"),
        "summary": summary,
        "contributing_signals": contributing_signals,
        "recommended_attention": recommended_attention,
        "human_override_required": True,
        "confirmed_by_controller": False,
        "generated_at": now,
        "condition_key": condition_key,
        "evidence": evidence,
    }
    if supersedes:
        advisory["supersedes"] = supersedes
    if in_response_to is not None:
        advisory["in_response_to"] = in_response_to
    if conflict is not None:
        advisory["conflict"] = conflict
    return advisory


def build_lifecycle_event(
    *,
    advisory_id: str,
    new_state: str,
    reason: str,
    in_response_to: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble an advisory_lifecycle event (design §4 / frozen contract)."""
    return {
        "type": "advisory_lifecycle",
        "advisory_id": advisory_id,
        "new_state": new_state,
        "in_response_to": in_response_to,
        "reason": reason,
        "timestamp": utc_now_iso(),
    }
