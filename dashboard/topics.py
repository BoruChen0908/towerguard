"""SSE event types and the Redis topic → event-type mapping (frozen by contract).

The six SSE event types and their wire names are pinned by the dashboard
interface contract agreed with the frontend agent. The first five mirror
Redis pub/sub topics one-to-one and are forwarded verbatim; `briefing` is a
demo-internal topic re-shaped into {"advisory_id", "markdown"} before forwarding
(see server.py).
"""

# Redis pub/sub topics the bridge subscribes to.
# The first four are contract topics (contact.md §1); the last two are
# demo-internal topics not in Katherine's contract.
TOPIC_TRAFFIC_DENSITY = "towerguard:traffic_density"
TOPIC_CONFLICT_GEOMETRY = "towerguard:conflict_geometry"
TOPIC_WORKLOAD_INDEX = "towerguard:workload_index"
TOPIC_ADVISORY = "towerguard:advisory"
TOPIC_AIRCRAFT_SNAPSHOT = "towerguard:aircraft_snapshot"  # demo-internal
TOPIC_BRIEFING = "towerguard:briefing"  # demo-internal
# v1.2: Orchestrator-owned advisory state transitions (resolved/superseded/
# expired). The bridge forwards this topic's JSON verbatim as an
# `advisory_lifecycle` SSE event so the dashboard can collapse/relabel cards.
TOPIC_ADVISORY_LIFECYCLE = "towerguard:advisory_lifecycle"

# SSE event type ← Redis topic. Topic JSON is forwarded as the SSE `data`
# field verbatim for every type except `briefing` (re-shaped in server.py).
TOPIC_TO_EVENT: dict[str, str] = {
    TOPIC_TRAFFIC_DENSITY: "traffic_density",
    TOPIC_CONFLICT_GEOMETRY: "conflict_geometry",
    TOPIC_WORKLOAD_INDEX: "workload_index",
    TOPIC_ADVISORY: "advisory",
    TOPIC_AIRCRAFT_SNAPSHOT: "aircraft_snapshot",
    TOPIC_BRIEFING: "briefing",
    TOPIC_ADVISORY_LIFECYCLE: "advisory_lifecycle",
}

SUBSCRIBED_TOPICS: tuple[str, ...] = tuple(TOPIC_TO_EVENT.keys())

# SSE event type for the shift-events Redis Stream (contact.md §1). It does not
# map to a pub/sub topic — the bridge sources it from a XREAD on the stream —
# so it lives outside TOPIC_TO_EVENT but is still a frontend-visible event type.
EVENT_SHIFT_EVENT = "shift_event"

# The SSE event-type strings the frontend listens for (contract-frozen):
# the six pub/sub-backed types plus the stream-backed shift_event.
SSE_EVENT_TYPES: frozenset[str] = frozenset(TOPIC_TO_EVENT.values()) | {
    EVENT_SHIFT_EVENT
}

# Redis String key holding the operator-selected airport ICAO (functional A).
# The runner polls this every few seconds; the dashboard SETs it on switch.
SELECTED_AIRPORT_KEY = "towerguard:selected_airport"

# v1.2 re-assess channel: the dashboard publishes a reassess_request here (via
# POST /reassess); the Orchestrator (mock_katherine engine) subscribes and must
# always reply on TOPIC_ADVISORY / TOPIC_ADVISORY_LIFECYCLE. It is a pure
# request channel — NOT forwarded to SSE — so it stays out of TOPIC_TO_EVENT.
TOPIC_REASSESS_REQUEST = "towerguard:reassess_request"

# v1.2 director switches. The dashboard SET/DELetes towerguard:demo:{flag} for
# flag ∈ {degraded, sparse, workload_surge}; the runner reads them each cycle.
DEMO_FLAG_KEY_PREFIX = "towerguard:demo:"
DEMO_FLAGS: tuple[str, ...] = ("degraded", "sparse", "workload_surge")
