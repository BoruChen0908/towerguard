"""Tests for the airport-selection and lineage endpoints in dashboard/server.py.

Covers:
  - GET  /airports                  → config list + selected (default + override)
  - POST /airport/{icao}            → valid SET; 404 on unknown ICAO
  - GET  /lineage                   → 404 when absent (file authored elsewhere)
"""

from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

import config
from dashboard.server import create_app
from dashboard.topics import SELECTED_AIRPORT_KEY


@pytest.fixture()
def client():
    fake = fakeredis.FakeRedis(decode_responses=True)
    with patch("dashboard.server._build_redis_client", return_value=fake):
        app = create_app()
        with TestClient(app) as c:
            c.fake_redis = fake
            yield c


class TestAirports:
    def test_lists_all_configured_airports(self, client):
        body = client.get("/airports").json()
        icaos = {a["icao"] for a in body["airports"]}
        assert icaos == set(config.AIRPORTS.keys())
        # each entry is exactly {icao, name}
        for a in body["airports"]:
            assert set(a.keys()) == {"icao", "name"}

    def test_selected_defaults_when_unset(self, client):
        body = client.get("/airports").json()
        assert body["selected"] == config.DEFAULT_AIRPORT

    def test_selected_reflects_stored_value(self, client):
        client.fake_redis.set(SELECTED_AIRPORT_KEY, "KEWR")
        body = client.get("/airports").json()
        assert body["selected"] == "KEWR"

    def test_selected_falls_back_when_stored_value_unknown(self, client):
        client.fake_redis.set(SELECTED_AIRPORT_KEY, "ZZZZ")
        body = client.get("/airports").json()
        assert body["selected"] == config.DEFAULT_AIRPORT


class TestSelectAirport:
    def test_valid_icao_sets_key(self, client):
        resp = client.post("/airport/KBOS")
        assert resp.status_code == 200
        assert resp.json() == {"airport": "KBOS"}
        assert client.fake_redis.get(SELECTED_AIRPORT_KEY) == "KBOS"

    def test_unknown_icao_returns_404_and_does_not_write(self, client):
        resp = client.post("/airport/ZZZZ")
        assert resp.status_code == 404
        assert client.fake_redis.get(SELECTED_AIRPORT_KEY) is None


class TestLineage:
    def test_missing_lineage_returns_404(self, client):
        # docs/lineage.md is authored by the frontend agent and is not expected
        # to exist in the backend test environment.
        with patch("dashboard.server._LINEAGE_MD") as fake_path:
            fake_path.is_file.return_value = False
            resp = client.get("/lineage")
        assert resp.status_code == 404

    def test_present_lineage_served_as_markdown(self, client, tmp_path):
        md = tmp_path / "lineage.md"
        md.write_text("# Lineage\n\ntraceability", encoding="utf-8")
        with patch("dashboard.server._LINEAGE_MD", md):
            resp = client.get("/lineage")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
        assert "traceability" in resp.text
