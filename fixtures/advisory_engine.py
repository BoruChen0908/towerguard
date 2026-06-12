"""Condition-driven advisory rule engine (design §3 + §6).

Replaces the old 45-second timer. The engine subscribes (via mock_katherine) to
the three module topics, keeps the latest event of each, and on every
conflict_geometry event evaluates the design §6 rule table top-to-bottom,
first-match-stops (先中先停):

    C1  cg HIGH, pair not yet issued            → ESCALATE / HIGH
    C2  cg CRITICAL, pair not yet CRITICAL       → ESCALATE / CRITICAL (supersedes C1)
    W   wi ≥ MEDIUM and cg ≥ HIGH co-occur        → ESCALATE (composite: short-staffed + conflict)
    S   td LOW but cg ≥ HIGH (signals disagree)   → SURFACE_CONFLICT
    R   a previously-issued pair drops to LOW     → lifecycle resolved + supersede card

Re-surface only on a change in the world, never on the passage of time
(design core principle): a condition+tier issued once is not re-issued; after a
human handles it (confirm/dismiss key present) a 300 s cooldown applies; a tier
escalation pierces the cooldown and supersedes the prior card.

State ownership (design §4): the Orchestrator owns lifecycle transitions via the
``towerguard:advisory:state:{id}`` key; the dashboard owns confirmed/dismissed.
The two never write the same key, so a human decision is never overwritten.

The engine returns its side effects through the injected Redis client (publish +
XADD) so it is unit-testable end-to-end with fakeredis. All time comes from an
injectable ``clock`` so cooldown tests are deterministic.
"""

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

import redis

from dashboard.shift_stream import (
    KIND_REASSESS,
    KIND_RESOLVE,
    KIND_SUPERSEDE,
    xadd_shift_event,
)
from dashboard.topics import (
    TOPIC_ADVISORY,
    TOPIC_ADVISORY_LIFECYCLE,
    TOPIC_CONFLICT_GEOMETRY,
    TOPIC_TRAFFIC_DENSITY,
    TOPIC_WORKLOAD_INDEX,
)
from fixtures import advisory_builders as ab

logger = logging.getLogger(__name__)

# Human-decision key prefixes (dashboard-owned — see server.py). The engine only
# READS these, to decide whether a condition has been handled (cooldown gate).
CONFIRMED_KEY_PREFIX = "towerguard:confirmed:"
DISMISSED_KEY_PREFIX = "towerguard:dismissed:"
# Orchestrator-owned advisory state key (design §4).
ADVISORY_STATE_KEY_PREFIX = "towerguard:advisory:state:"

# Contract constants (design "given to Katherine" checklist items 4).
COOLDOWN_SECONDS = 300

# Tier ordering for escalation comparisons (higher == worse).
_TIER_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3, "UNKNOWN": -1}

# Rule signal labels — the ``signals`` segment of the condition_key, so the same
# pair under different rules produces distinct conditions.
_SIGNAL_CONFLICT = "conflict_geometry"
_SIGNAL_COMPOSITE = "workload+conflict"
_SIGNAL_SURFACE = "density-vs-conflict"


def _tier_rank(tier: Optional[str]) -> int:
    return _TIER_RANK.get(tier or "", -1)


class _Issued:
    """In-process record of the last advisory issued for a condition_key.

    Holds the advisory id, the tier/severity at issue, the pair callsigns, and
    the issue time (engine clock) for the cooldown gate. Immutable per issue:
    superseding/resolving creates a new record rather than mutating in place.
    """

    __slots__ = ("advisory_id", "tier", "callsigns", "issued_at")

    def __init__(
        self,
        advisory_id: str,
        tier: str,
        callsigns: list[str],
        issued_at: float,
    ) -> None:
        self.advisory_id = advisory_id
        self.tier = tier
        self.callsigns = callsigns
        self.issued_at = issued_at


class AdvisoryEngine:
    """Stateful rule engine. One instance per mock_katherine process."""

    def __init__(
        self,
        redis_client: redis.Redis,
        airport: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._redis = redis_client
        self._airport = airport
        self._clock = clock
        self._lock = threading.Lock()
        # topic -> latest module event seen on the wire.
        self._latest: dict[str, Optional[dict[str, Any]]] = {
            TOPIC_TRAFFIC_DENSITY: None,
            TOPIC_CONFLICT_GEOMETRY: None,
            TOPIC_WORKLOAD_INDEX: None,
        }
        # condition_key -> _Issued (the last card issued for that condition).
        self._issued: dict[str, _Issued] = {}
        # Monotonic advisory id counter (ADV-0001, ADV-0002, ...).
        self._counter = 0

    # -- state ingestion ---------------------------------------------------

    def update_module(self, topic: str, event: dict[str, Any]) -> None:
        """Record the latest event for a module topic (thread-safe)."""
        with self._lock:
            if topic in self._latest:
                self._latest[topic] = event

    def _snapshot(self) -> dict[str, Optional[dict[str, Any]]]:
        return dict(self._latest)

    # -- id allocation -----------------------------------------------------

    def _next_advisory_id(self) -> str:
        self._counter += 1
        return f"ADV-{self._counter:04d}"

    # -- cooldown / dedup gate --------------------------------------------

    def _handled(self, advisory_id: str) -> bool:
        """True if a human has confirmed OR dismissed the given advisory."""
        try:
            confirmed = self._redis.get(f"{CONFIRMED_KEY_PREFIX}{advisory_id}")
            dismissed = self._redis.get(f"{DISMISSED_KEY_PREFIX}{advisory_id}")
        except Exception as exc:  # pragma: no cover - redis blip
            logger.warning("Could not read decision keys for %s: %s", advisory_id, exc)
            return False
        return confirmed is not None or dismissed is not None

    def _suppressed(self, key: str, tier: str, now: float) -> bool:
        """Apply the design §3 dedup + cooldown gate for (condition, tier).

        - Same condition, tier not worse than the last issue → suppress (dedup;
          a tier escalation is never suppressed — it pierces below).
        - Worse tier → not suppressed (C2-style escalation).
        - If the last card was human-handled, a fresh issue of the SAME tier is
          held for COOLDOWN_SECONDS after issue; escalation still pierces.
        """
        prior = self._issued.get(key)
        if prior is None:
            return False
        if _tier_rank(tier) > _tier_rank(prior.tier):
            return False  # escalation always pierces (cooldown + dedup)
        # tier == prior (or lower under same key): dedup unless cooldown lapsed
        # after a human handled it.
        if self._handled(prior.advisory_id):
            return (now - prior.issued_at) < COOLDOWN_SECONDS
        return True  # unhandled same-tier re-fire → never repeat

    # -- side-effect helpers ----------------------------------------------

    def _publish_advisory(self, advisory: dict[str, Any]) -> None:
        self._redis.publish(TOPIC_ADVISORY, json.dumps(advisory, separators=(",", ":")))
        from dashboard.shift_stream import KIND_ADVISORY

        xadd_shift_event(
            self._redis,
            kind=KIND_ADVISORY,
            summary=advisory["summary"],
            ref=advisory["advisory_id"],
            tier=advisory["severity"],
        )

    def _publish_lifecycle(self, event: dict[str, Any], kind: str) -> None:
        self._redis.publish(
            TOPIC_ADVISORY_LIFECYCLE, json.dumps(event, separators=(",", ":"))
        )
        xadd_shift_event(
            self._redis,
            kind=kind,
            summary=(
                f"Advisory {event['advisory_id']} {event['new_state']} "
                f"({event['reason']})"
            ),
            ref=event["advisory_id"],
        )

    def _mark_state(self, advisory_id: str, state: str) -> None:
        """SET the Orchestrator-owned state key (design §4)."""
        try:
            self._redis.set(f"{ADVISORY_STATE_KEY_PREFIX}{advisory_id}", state)
        except Exception as exc:  # pragma: no cover - redis blip
            logger.error(
                "Could not SET advisory state %s=%s: %s", advisory_id, state, exc
            )

    def _supersede_prior(self, prior: _Issued, by_advisory_id: str) -> None:
        """Retire a prior card: state=superseded, XADD supersede, lifecycle event."""
        self._mark_state(prior.advisory_id, ab.LIFECYCLE_SUPERSEDED)
        lifecycle = ab.build_lifecycle_event(
            advisory_id=prior.advisory_id,
            new_state=ab.LIFECYCLE_SUPERSEDED,
            reason=f"superseded_by:{by_advisory_id}",
        )
        self._publish_lifecycle(lifecycle, KIND_SUPERSEDE)

    # -- rule evaluation ---------------------------------------------------

    def on_conflict_event(self, cg_event: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Evaluate the §6 rule table for one cg event; return the issued advisory.

        First-match-stops. Returns the advisory dict if one was issued (for
        logging/tests), or None if every rule was a no-op / suppressed.
        """
        with self._lock:
            self._latest[TOPIC_CONFLICT_GEOMETRY] = cg_event
            td = self._latest[TOPIC_TRAFFIC_DENSITY]
            wi = self._latest[TOPIC_WORKLOAD_INDEX]
            now = self._clock()

            cg_tier = cg_event.get("tier")
            callsigns = ab.pair_callsigns(cg_event)

            # R: a pair we previously escalated has dropped back to LOW.
            resolved = self._maybe_resolve(cg_event, callsigns, now)
            if resolved is not None:
                return None

            # No conflict pair → nothing for the conflict-driven rules to fire on.
            if not callsigns or _tier_rank(cg_tier) < _tier_rank("HIGH"):
                return None

            # S: density says quiet, geometry says imminent — signals disagree.
            if td is not None and td.get("tier") == "LOW":
                return self._issue_surface_conflict(td, cg_event, wi, callsigns, now)

            # W: short-staffed AND a real conflict co-occur (composite escalation).
            if wi is not None and _tier_rank(wi.get("tier")) >= _tier_rank("MEDIUM"):
                return self._issue_composite(td, cg_event, wi, callsigns, now)

            # C1 / C2: plain conflict escalation (HIGH then CRITICAL).
            return self._issue_conflict(td, cg_event, wi, callsigns, now)

    def _maybe_resolve(
        self,
        cg_event: dict[str, Any],
        callsigns: list[str],
        now: float,
    ) -> Optional[dict[str, Any]]:
        """R rule: if this pair was escalated and is now LOW, resolve it.

        Matches any prior issued condition for the pair's callsigns (whatever
        signal label issued it); fires a lifecycle ``resolved`` + XADD resolve
        and clears the in-process record so a future escalation starts fresh.
        """
        cg_tier = cg_event.get("tier")
        if cg_tier != "LOW":
            return None
        pair = ab.pair_callsigns(cg_event)
        # On a LOW event there is no closest_pair, so match on previously-issued
        # records by their stored callsigns instead.
        for key, prior in list(self._issued.items()):
            if not prior.callsigns:
                continue
            # The LOW cg event carries no pair; resolve every still-open card.
            lifecycle = ab.build_lifecycle_event(
                advisory_id=prior.advisory_id,
                new_state=ab.LIFECYCLE_RESOLVED,
                reason="conflict_cleared:tier_dropped_to_LOW",
            )
            self._mark_state(prior.advisory_id, ab.LIFECYCLE_RESOLVED)
            self._publish_lifecycle(lifecycle, KIND_RESOLVE)
            del self._issued[key]
            return lifecycle
        # ``pair`` is intentionally unused beyond the guard above; a LOW event
        # has no closest_pair, so resolution keys off the issued record.
        del pair
        return None

    def _issue(
        self,
        *,
        signals_label: str,
        action: str,
        severity: str,
        summary: str,
        recommended_attention: str,
        callsigns: list[str],
        td: Optional[dict[str, Any]],
        cg: dict[str, Any],
        wi: Optional[dict[str, Any]],
        now: float,
        conflict_block: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Shared issue path: dedup/cooldown gate, supersede, publish, record."""
        key = ab.condition_key(self._airport, signals_label, callsigns)
        if self._suppressed(key, severity, now):
            return None

        prior = self._issued.get(key)
        advisory_id = self._next_advisory_id()
        supersedes = None
        if prior is not None and _tier_rank(severity) > _tier_rank(prior.tier):
            supersedes = [prior.advisory_id]

        advisory = ab.build_advisory(
            advisory_id=advisory_id,
            airport=self._airport,
            action=action,
            severity=severity,
            summary=summary,
            recommended_attention=recommended_attention,
            condition_key=key,
            evidence=ab.build_evidence(td, cg, wi),
            contributing_signals=[
                "traffic_density",
                "conflict_geometry",
                "workload_index",
            ],
            supersedes=supersedes,
            conflict=conflict_block,
        )

        if supersedes is not None and prior is not None:
            self._supersede_prior(prior, advisory_id)

        self._publish_advisory(advisory)
        self._issued[key] = _Issued(advisory_id, severity, callsigns, now)
        return advisory

    def _issue_conflict(self, td, cg, wi, callsigns, now):
        """C1 (HIGH) / C2 (CRITICAL) — plain conflict escalation."""
        tier = cg.get("tier")
        pair = "/".join(callsigns)
        sep = (cg.get("closest_pair") or {}).get("projected_separation_nm")
        ttv = (cg.get("closest_pair") or {}).get("time_to_violation_seconds")
        return self._issue(
            signals_label=_SIGNAL_CONFLICT,
            action="ESCALATE",
            severity=tier,
            summary=f"Projected separation violation ({tier}) for {pair}.",
            recommended_attention=(
                f"{pair} closing to {sep} NM in {ttv} s — verify separation."
            ),
            callsigns=callsigns,
            td=td,
            cg=cg,
            wi=wi,
            now=now,
        )

    def _issue_composite(self, td, cg, wi, callsigns, now):
        """W — workload (≥MEDIUM) AND conflict (≥HIGH) co-occurring."""
        tier = cg.get("tier")
        pair = "/".join(callsigns)
        staffed = wi.get("staffed_controllers")
        recommended = wi.get("recommended_controllers")
        return self._issue(
            signals_label=_SIGNAL_COMPOSITE,
            action="ESCALATE",
            severity=tier,
            summary=(
                f"Conflict during understaffing: {pair} with "
                f"{staffed}/{recommended} controllers on board."
            ),
            recommended_attention=(
                f"{pair} conflict while sector is short-staffed "
                f"({staffed}/{recommended}) — prioritise."
            ),
            callsigns=callsigns,
            td=td,
            cg=cg,
            wi=wi,
            now=now,
        )

    def _issue_surface_conflict(self, td, cg, wi, callsigns, now):
        """S — traffic density LOW but conflict ≥ HIGH: signals disagree."""
        pair = "/".join(callsigns)
        return self._issue(
            signals_label=_SIGNAL_SURFACE,
            action="SURFACE_CONFLICT",
            severity=cg.get("tier"),
            summary=f"Signal conflict on {pair}: low density vs imminent geometry.",
            recommended_attention=(
                f"{pair}: geometry flags a conflict while density reads low — "
                "controller must adjudicate."
            ),
            callsigns=callsigns,
            td=td,
            cg=cg,
            wi=wi,
            now=now,
            conflict_block=ab.build_conflict_block(td, cg),
        )

    # -- re-assess channel (design §4) ------------------------------------

    def on_reassess_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle a controller re-assess request — always reply, never silent.

        Re-evaluates with the CURRENT module snapshot:
          (a) condition still present (cg ≥ HIGH) → a NEW advisory carrying
              ``supersedes`` (the prior card) + ``in_response_to`` (request id);
          (b) condition gone (cg LOW / no pair) → a lifecycle ``resolved`` event
              carrying ``in_response_to``.
        A reassess shift event is XADDed either way.
        """
        with self._lock:
            request_id = request.get("request_id")
            target_id = request.get("advisory_id")
            cg = self._latest[TOPIC_CONFLICT_GEOMETRY]
            td = self._latest[TOPIC_TRAFFIC_DENSITY]
            wi = self._latest[TOPIC_WORKLOAD_INDEX]
            now = self._clock()

            xadd_shift_event(
                self._redis,
                kind=KIND_REASSESS,
                summary=f"Re-assess requested for {target_id} ({request_id})",
                ref=target_id,
            )

            callsigns = ab.pair_callsigns(cg)
            still_active = bool(callsigns) and _tier_rank(cg.get("tier")) >= _tier_rank(
                "HIGH"
            )

            if still_active:
                return self._reassess_reissue(
                    target_id, request_id, td, cg, wi, callsigns, now
                )
            return self._reassess_resolve(target_id, request_id)

    def _reassess_reissue(self, target_id, request_id, td, cg, wi, callsigns, now):
        """(a) condition still present → new advisory, supersedes + in_response_to."""
        key = ab.condition_key(self._airport, _SIGNAL_CONFLICT, callsigns)
        advisory_id = self._next_advisory_id()
        tier = cg.get("tier")
        pair = "/".join(callsigns)
        sep = (cg.get("closest_pair") or {}).get("projected_separation_nm")
        ttv = (cg.get("closest_pair") or {}).get("time_to_violation_seconds")
        advisory = ab.build_advisory(
            advisory_id=advisory_id,
            airport=self._airport,
            action="ESCALATE",
            severity=tier,
            summary=f"Re-assessed: {pair} conflict persists ({tier}).",
            recommended_attention=(
                f"{pair} still closing to {sep} NM in {ttv} s after re-assess."
            ),
            condition_key=key,
            evidence=ab.build_evidence(td, cg, wi),
            contributing_signals=[
                "traffic_density",
                "conflict_geometry",
                "workload_index",
            ],
            supersedes=[target_id] if target_id else None,
            in_response_to=request_id,
        )
        if target_id:
            self._mark_state(target_id, ab.LIFECYCLE_SUPERSEDED)
        self._publish_advisory(advisory)
        self._issued[key] = _Issued(advisory_id, tier, callsigns, now)
        return advisory

    def _reassess_resolve(self, target_id, request_id):
        """(b) condition gone → lifecycle resolved carrying in_response_to."""
        lifecycle = ab.build_lifecycle_event(
            advisory_id=target_id,
            new_state=ab.LIFECYCLE_RESOLVED,
            reason="reassess_cleared:condition_no_longer_present",
            in_response_to=request_id,
        )
        self._mark_state(target_id, ab.LIFECYCLE_RESOLVED)
        self._publish_lifecycle(lifecycle, KIND_RESOLVE)
        # Drop any in-process record for this advisory so it cannot re-fire.
        for k, v in list(self._issued.items()):
            if v.advisory_id == target_id:
                del self._issued[k]
        return lifecycle
