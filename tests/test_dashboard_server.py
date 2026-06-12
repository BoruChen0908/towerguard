"""Tests for dashboard/server.py and dashboard/bridge.py.

Covers:
  - GET /health (redis up / down)
  - POST /confirm idempotency (repeat click returns the original timestamp)
  - SSE cache replay: a new client is seeded with the last message per type
  - bridge dispatch caches and fans out to registered clients
"""

import asyncio
import json
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from dashboard.bridge import PubSubBridge, SSEMessage
from dashboard.server import CONFIRMED_KEY_PREFIX, create_app


# ---------------------------------------------------------------------------
# HTTP endpoints (TestClient drives the real lifespan with fakeredis patched in)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """TestClient with a fakeredis-backed app.

    Patches _build_redis_client so the lifespan wires up fakeredis instead of a
    live server. The bridge's subscribe runs against fakeredis (no messages are
    published in these tests, so the listen thread just blocks harmlessly).
    """
    fake = fakeredis.FakeRedis(decode_responses=True)
    with patch("dashboard.server._build_redis_client", return_value=fake):
        app = create_app()
        with TestClient(app) as c:
            c.fake_redis = fake  # expose for assertions
            yield c


class TestHealth:
    def test_health_redis_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["redis"] is True

    def test_health_redis_down(self, client):
        # Force ping to fail → redis: False, still status ok
        with patch.object(client.fake_redis, "ping", side_effect=Exception("down")):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["redis"] is False


class TestConfirm:
    def test_confirm_writes_key_and_returns_timestamp(self, client):
        resp = client.post("/confirm/ADV-0001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["advisory_id"] == "ADV-0001"
        assert body["confirmed_at"]  # non-empty ISO string
        # Key persisted with the contract prefix
        stored = client.fake_redis.get(f"{CONFIRMED_KEY_PREFIX}ADV-0001")
        assert stored == body["confirmed_at"]

    def test_confirm_is_idempotent(self, client):
        first = client.post("/confirm/ADV-0002").json()
        second = client.post("/confirm/ADV-0002").json()
        # Repeat click returns the original timestamp, not a new one
        assert first["confirmed_at"] == second["confirmed_at"]


# ---------------------------------------------------------------------------
# SSE cache replay (bridge-level, deterministic)
# ---------------------------------------------------------------------------


class TestBridgeReplay:
    def test_new_client_replays_cached_last_message_per_type(self):
        """register() seeds a new queue with the cached last message of each
        type so a freshly connected dashboard renders immediately."""
        loop = asyncio.new_event_loop()
        try:
            fake = fakeredis.FakeRedis(decode_responses=True)
            bridge = PubSubBridge(fake, loop)

            # Simulate two cached types having arrived before the client connects.
            td = SSEMessage(event="traffic_density", data='{"tier":"HIGH"}')
            adv = SSEMessage(event="advisory", data='{"action":"ESCALATE"}')
            bridge._cache["traffic_density"] = td
            bridge._cache["advisory"] = adv

            queue = bridge.register()

            # The new client's queue holds exactly the two cached messages.
            replayed = []
            while not queue.empty():
                replayed.append(queue.get_nowait())
            events = {m.event for m in replayed}
            assert events == {"traffic_density", "advisory"}
        finally:
            loop.close()

    def test_dispatch_caches_and_fans_out(self):
        """_dispatch updates the cache and delivers to a registered client."""
        loop = asyncio.new_event_loop()
        try:
            fake = fakeredis.FakeRedis(decode_responses=True)
            bridge = PubSubBridge(fake, loop)
            queue = bridge.register()  # empty cache → no replay

            msg = SSEMessage(event="workload_index", data='{"tier":"MEDIUM"}')
            bridge._dispatch(msg)
            # call_soon_threadsafe was scheduled on the loop; run pending callbacks
            loop.call_soon(loop.stop)
            loop.run_forever()

            assert bridge._cache["workload_index"] == msg
            assert queue.get_nowait() == msg
        finally:
            loop.close()

    def test_briefing_payload_normalised(self):
        """A briefing message is reshaped to {advisory_id, markdown}."""
        raw = {
            "type": "message",
            "channel": "towerguard:briefing",
            "data": json.dumps(
                {"advisory_id": "ADV-0007", "markdown": "## hi", "extra": "x"}
            ),
        }
        msg = PubSubBridge._to_sse_message(raw)
        assert msg is not None
        assert msg.event == "briefing"
        parsed = json.loads(msg.data)
        assert parsed == {"advisory_id": "ADV-0007", "markdown": "## hi"}

    def test_unknown_channel_ignored(self):
        raw = {"type": "message", "channel": "towerguard:unknown", "data": "{}"}
        assert PubSubBridge._to_sse_message(raw) is None
