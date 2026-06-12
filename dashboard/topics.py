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

# SSE event type ← Redis topic. Topic JSON is forwarded as the SSE `data`
# field verbatim for every type except `briefing` (re-shaped in server.py).
TOPIC_TO_EVENT: dict[str, str] = {
    TOPIC_TRAFFIC_DENSITY: "traffic_density",
    TOPIC_CONFLICT_GEOMETRY: "conflict_geometry",
    TOPIC_WORKLOAD_INDEX: "workload_index",
    TOPIC_ADVISORY: "advisory",
    TOPIC_AIRCRAFT_SNAPSHOT: "aircraft_snapshot",
    TOPIC_BRIEFING: "briefing",
}

SUBSCRIBED_TOPICS: tuple[str, ...] = tuple(TOPIC_TO_EVENT.keys())

# The six SSE event-type strings the frontend listens for (contract-frozen).
SSE_EVENT_TYPES: frozenset[str] = frozenset(TOPIC_TO_EVENT.values())
