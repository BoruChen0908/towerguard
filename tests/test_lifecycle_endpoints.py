"""Tests for the v1.2 server endpoints: dismiss reason, reassess, demo flags."""

import json
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from dashboard.server import (
    DISMISS_REASON_KEY_PREFIX,
    REASSESS_COUNT_KEY_PREFIX,
    create_app,
)
from dashboard.shift_stream import KIND_DISMISS, read_recent
from dashboard.topics import DEMO_FLAG_KEY_PREFIX, TOPIC_REASSESS_REQUEST


@pytest.fixture()
def client():
    fake = fakeredis.FakeRedis(decode_responses=True)
    with patch("dashboard.server._build_redis_client", return_value=fake):
        app = create_app()
        with TestClient(app) as c:
            c.fake_redis = fake
            yield c


class TestDismissReason:
    def test_reason_stored_and_folded_into_shift_event(self, client):
        resp = client.post("/dismiss/ADV-0100", json={"reason": "already_separated"})
        assert resp.status_code == 200
        # dismissed_at key stays a bare ISO timestamp (unchanged contract)
        assert resp.json()["dismissed_at"]
        # reason stored under its own key
        assert (
            client.fake_redis.get(f"{DISMISS_REASON_KEY_PREFIX}ADV-0100")
            == "already_separated"
        )
        events = [
            e for e in read_recent(client.fake_redis) if e["kind"] == KIND_DISMISS
        ]
        assert events[0]["summary"].endswith("(already_separated)")

    def test_dismiss_without_body_still_works(self, client):
        resp = client.post("/dismiss/ADV-0101")
        assert resp.status_code == 200
        assert client.fake_redis.get(f"{DISMISS_REASON_KEY_PREFIX}ADV-0101") is None

    def test_unknown_reason_rejected(self, client):
        resp = client.post("/dismiss/ADV-0102", json={"reason": "bogus"})
        assert resp.status_code == 400


class TestReassess:
    def test_reassess_publishes_request_and_returns_ids(self, client):
        captured: list[str] = []
        original = client.fake_redis.publish

        def capture(channel, message):
            if channel == TOPIC_REASSESS_REQUEST:
                captured.append(message)
            return original(channel, message)

        client.fake_redis.publish = capture

        resp = client.post("/reassess/ADV-0200")
        assert resp.status_code == 200
        body = resp.json()
        assert body["advisory_id"] == "ADV-0200"
        assert body["request_id"].startswith("RAS-")
        assert body["requested_at"]
        # request published with the frozen payload shape
        payload = json.loads(captured[0])
        assert payload["type"] == "reassess_request"
        assert payload["advisory_id"] == "ADV-0200"
        assert payload["reason"] == "controller_manual"

    def test_reassess_limited_to_two_then_429(self, client):
        assert client.post("/reassess/ADV-0201").status_code == 200
        assert client.post("/reassess/ADV-0201").status_code == 200
        third = client.post("/reassess/ADV-0201")
        assert third.status_code == 429
        assert third.json() == {"error": "reassess_limit"}
        # counter reflects the three attempts
        assert int(client.fake_redis.get(f"{REASSESS_COUNT_KEY_PREFIX}ADV-0201")) == 3


class TestDemoFlags:
    def test_set_and_get_demo_flag(self, client):
        resp = client.post("/demo/degraded/on")
        assert resp.status_code == 200
        assert resp.json()["flags"]["degraded"] is True
        assert client.fake_redis.get(f"{DEMO_FLAG_KEY_PREFIX}degraded") == "1"

        # off deletes the key
        resp = client.post("/demo/degraded/off")
        assert resp.json()["flags"]["degraded"] is False
        assert client.fake_redis.get(f"{DEMO_FLAG_KEY_PREFIX}degraded") is None

    def test_get_demo_reports_all_flags(self, client):
        client.post("/demo/sparse/on")
        body = client.get("/demo").json()
        assert body["flags"]["sparse"] is True
        assert body["flags"]["degraded"] is False
        assert body["flags"]["workload_surge"] is False

    def test_unknown_flag_404(self, client):
        assert client.post("/demo/bogus/on").status_code == 404

    def test_unknown_state_404(self, client):
        assert client.post("/demo/degraded/maybe").status_code == 404
