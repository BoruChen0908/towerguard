"""Dynamic relief-briefing assembly (design §6).

The five-section §4 markdown is built from the real shift-events log
(``read_recent``) and the advisory state/decision keys, so every render reflects
the actual shift rather than a fixed template:

  1. Current traffic picture — latest tier per module from tier_change events
  2. Active advisories       — issued, not yet resolved/superseded/expired; each
                               flagged ✓ (confirmed) / ✕ (dismissed) / pending
  3. Notable events          — tier changes this shift, one line each
  4. Weather and NOTAMs      — static demo text (no live source)
  5. Pending actions         — count of advisories awaiting a decision

Pure functions over a list of decoded shift events plus a small "decision
lookup" callback, so the assembly is unit-testable without Redis.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from dashboard.shift_stream import (
    KIND_ADVISORY,
    KIND_EXPIRE,
    KIND_RESOLVE,
    KIND_SUPERSEDE,
    KIND_TIER_CHANGE,
)

# Advisory ids reaching any of these kinds are considered closed (no longer
# "active" for section 2 / pending counting).
_CLOSED_KINDS = frozenset({KIND_RESOLVE, KIND_SUPERSEDE, KIND_EXPIRE})

# Decision callback returns one of these per advisory id.
DECISION_CONFIRMED = "confirmed"
DECISION_DISMISSED = "dismissed"
DECISION_PENDING = "pending"


def _zulu() -> str:
    return datetime.now(timezone.utc).strftime("%H%M")


def _latest_tiers(events: list[dict[str, Any]]) -> dict[str, str]:
    """Most recent tier per module, parsed from tier_change summaries.

    tier_change summaries are ``"<MODULE> <old> → <new> ...`` (see
    mock_katherine._build_tier_change_summary); the tier field carries the new
    tier directly when present, so we prefer it and fall back to parsing.
    """
    tiers: dict[str, str] = {}
    for ev in events:
        if ev.get("kind") != KIND_TIER_CHANGE:
            continue
        summary = ev.get("summary", "")
        # Summary shape: "<MODULE NAME> <OLD> → <NEW> (...)". The module name is
        # multi-word, so take everything before the " <OLD> →" segment rather
        # than just the first token.
        module = (
            summary.split("→", 1)[0].rsplit(" ", 2)[0].strip() if "→" in summary else ""
        )
        # The new tier is the explicit `tier` field (v1.2) or the token after →.
        tier = ev.get("tier")
        if tier is None and "→" in summary:
            tail = summary.split("→", 1)[1].strip()
            tier = tail.split(" ", 1)[0] if tail else None
        if module and tier:
            tiers[module] = tier
    return tiers


def _open_advisories(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Advisory events whose id has not since been resolved/superseded/expired.

    Returns the issuing advisory event for each still-open advisory, in issue
    order (oldest→newest), so the briefing lists them chronologically.
    """
    closed: set[str] = {
        ev.get("ref")
        for ev in events
        if ev.get("kind") in _CLOSED_KINDS and ev.get("ref")
    }
    open_list: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ev in events:
        if ev.get("kind") != KIND_ADVISORY:
            continue
        ref = ev.get("ref")
        if not ref or ref in closed or ref in seen:
            continue
        seen.add(ref)
        open_list.append(ev)
    return open_list


def _decision_mark(decision: str) -> str:
    if decision == DECISION_CONFIRMED:
        return "✓"
    if decision == DECISION_DISMISSED:
        return "✕"
    return "·"


def build_briefing_markdown(
    airport: str,
    events: list[dict[str, Any]],
    decision_of: Callable[[str], str],
) -> str:
    """Assemble the §4 five-section markdown from real shift events.

    Args:
        airport: ICAO for the header line.
        events: decoded shift events (oldest→newest), from read_recent.
        decision_of: callback advisory_id → confirmed|dismissed|pending.
    """
    zulu = _zulu()
    tiers = _latest_tiers(events)
    open_advisories = _open_advisories(events)
    tier_changes = [ev for ev in events if ev.get("kind") == KIND_TIER_CHANGE]

    # Section 1 — current traffic picture
    if tiers:
        traffic_lines = "\n".join(
            f"- {module}: {tier}" for module, tier in tiers.items()
        )
    else:
        traffic_lines = "- No module tier changes recorded yet this shift."

    # Section 2 — active advisories (with decision marks)
    pending = 0
    if open_advisories:
        adv_lines = []
        for ev in open_advisories:
            ref = ev.get("ref", "?")
            decision = decision_of(ref)
            if decision == DECISION_PENDING:
                pending += 1
            mark = _decision_mark(decision)
            adv_lines.append(f"- {mark} {ref}: {ev.get('summary', '')}")
        active_block = "\n".join(adv_lines)
    else:
        active_block = "- No active advisories."

    # Section 3 — notable events this shift (tier changes, one line each)
    if tier_changes:
        notable = "\n".join(f"- {ev.get('summary', '')}" for ev in tier_changes)
    else:
        notable = "- No notable tier changes this shift."

    # Section 5 — pending actions
    if pending:
        pending_line = f"- {pending} advisory(ies) awaiting controller decision."
    else:
        pending_line = "- No advisories awaiting a decision."

    return (
        f"---\n"
        f"## Position Relief Briefing — {airport} {zulu}Z\n"
        f"*AI-generated draft. Outgoing controller must review and confirm.*\n\n"
        f"### 1. Current traffic picture\n"
        f"{traffic_lines}\n\n"
        f"### 2. Active advisories\n"
        f"{active_block}\n\n"
        f"### 3. Notable events this shift\n"
        f"{notable}\n\n"
        f"### 4. Weather and NOTAMs\n"
        f"VFR conditions, no active NOTAMs affecting the field (demo).\n\n"
        f"### 5. Pending actions\n"
        f"{pending_line}\n\n"
        f"---\n"
        f"*Reviewed and confirmed by: ________________  [TIME]__________*\n"
        f"---\n"
    )


def build_briefing_payload(
    briefing_id: str,
    airport: str,
    events: list[dict[str, Any]],
    decision_of: Callable[[str], str],
    advisory_id: Optional[str] = None,
) -> dict[str, str]:
    """Dashboard-contract briefing payload.

    Keeps the frozen {"advisory_id", "markdown"} shape for the SSE bridge, and
    adds a separate ``briefing_id`` (design §6 / Katherine confirm-list item 6):
    the briefing is no longer pinned to one advisory. ``advisory_id`` defaults to
    the briefing_id when no specific advisory anchors it.
    """
    return {
        "advisory_id": advisory_id or briefing_id,
        "briefing_id": briefing_id,
        "markdown": build_briefing_markdown(airport, events, decision_of),
    }
