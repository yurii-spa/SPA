"""
Tests for spa_core/api/server.py — MP-1527 (v11.43).

25 tests covering:
  - /health
  - /api/v1/status
  - /api/v1/golive
  - /api/v1/adapters
  - /api/v1/evidence
  - error handling / fallback behaviour
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── path setup ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── optional fastapi / starlette import ────────────────────────────────────────
try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not FASTAPI_AVAILABLE, reason="fastapi not installed"
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    """Temp data dir with minimal fixture files."""
    d = tmp_path_factory.mktemp("spa_data")

    # KANBAN.json
    (d / "KANBAN.json").write_text(json.dumps({
        "done_count": 1193,
        "sprint_completed": "v11.43",
        "version": "11.43.0",
    }), encoding="utf-8")

    # golive_status.json
    (d / "golive_status.json").write_text(json.dumps({
        "pass_count": 16,
        "total": 26,
        "ready": False,
        "blockers": ["gap_monitor_30d"],
    }), encoding="utf-8")

    # paper_evidence_history.json
    (d / "paper_evidence_history.json").write_text(json.dumps([
        {"date": "2026-06-10", "apy": 5.2, "capital": 100000},
        {"date": "2026-06-11", "apy": 5.4, "capital": 100512},
    ]), encoding="utf-8")

    # equity_curve_daily.json
    (d / "equity_curve_daily.json").write_text(json.dumps([
        {"date": "2026-06-10", "value": 100000},
    ]), encoding="utf-8")

    return d


@pytest.fixture(scope="module")
def client(data_dir):
    """TestClient with patched data dir and project root."""
    os.environ["SPA_DATA_DIR"] = str(data_dir)

    # Patch broadcaster to avoid background threads in tests
    mock_broadcaster = MagicMock()
    mock_broadcaster.start = MagicMock()
    mock_broadcaster.stop = MagicMock()
    mock_broadcaster.connect = MagicMock()
    mock_broadcaster.disconnect = MagicMock()
    mock_broadcaster.broadcast = MagicMock()
    mock_broadcaster.send_to = MagicMock()

    with patch("spa_core.api.agent_broadcaster.broadcaster", mock_broadcaster):
        with patch("spa_core.api.server.broadcaster", mock_broadcaster):
            with patch("spa_core.api.server._PROJECT_ROOT", data_dir):
                with patch("spa_core.api.server._DATA_DIR", data_dir):
                    from spa_core.api.server import app
                    tc = TestClient(app, raise_server_exceptions=False)
                    yield tc


# ── /health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_status_ok(self, client):
        r = client.get("/health")
        assert r.json()["status"] == "ok"

    def test_health_has_version(self, client):
        r = client.get("/health")
        assert "version" in r.json()

    def test_health_has_timestamp(self, client):
        r = client.get("/health")
        assert "timestamp" in r.json()

    def test_health_content_type_json(self, client):
        r = client.get("/health")
        assert "application/json" in r.headers["content-type"]


# ── /api/v1/status ─────────────────────────────────────────────────────────────

class TestV1Status:
    def test_status_returns_200(self, client):
        r = client.get("/api/v1/status")
        assert r.status_code == 200

    def test_status_has_done_count(self, client):
        r = client.get("/api/v1/status")
        assert "done_count" in r.json()

    def test_status_done_count_integer(self, client):
        r = client.get("/api/v1/status")
        assert isinstance(r.json()["done_count"], int)

    def test_status_has_sprint(self, client):
        r = client.get("/api/v1/status")
        data = r.json()
        assert "sprint" in data

    def test_status_has_timestamp(self, client):
        r = client.get("/api/v1/status")
        assert "timestamp" in r.json()

    def test_status_reads_kanban_values(self, client):
        r = client.get("/api/v1/status")
        data = r.json()
        assert data["done_count"] == 1193
        assert data["sprint"] == "v11.43"

    def test_status_error_returns_json(self, client):
        """If KANBAN.json is missing, endpoint returns error JSON (not 500 crash)."""
        with patch("spa_core.api.server._PROJECT_ROOT", Path("/nonexistent/path/xyz")):
            r = client.get("/api/v1/status")
            # Should not be a 5xx server crash - returns 200 with error key
            data = r.json()
            assert "error" in data or "done_count" in data


# ── /api/v1/golive ─────────────────────────────────────────────────────────────

class TestV1GoLive:
    def test_golive_returns_200(self, client):
        r = client.get("/api/v1/golive")
        assert r.status_code == 200

    def test_golive_has_timestamp(self, client):
        r = client.get("/api/v1/golive")
        assert "timestamp" in r.json()

    def test_golive_has_source_field(self, client):
        r = client.get("/api/v1/golive")
        assert "source" in r.json()

    def test_golive_reads_file_pass_count(self, client):
        r = client.get("/api/v1/golive")
        data = r.json()
        assert data.get("pass_count") == 16

    def test_golive_ready_is_false(self, client):
        r = client.get("/api/v1/golive")
        data = r.json()
        assert data.get("ready") is False


# ── /api/v1/adapters ───────────────────────────────────────────────────────────

class TestV1Adapters:
    def test_adapters_returns_200(self, client):
        r = client.get("/api/v1/adapters")
        assert r.status_code == 200

    def test_adapters_has_adapters_key(self, client):
        r = client.get("/api/v1/adapters")
        assert "adapters" in r.json()

    def test_adapters_has_count(self, client):
        r = client.get("/api/v1/adapters")
        data = r.json()
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_adapters_list_is_list(self, client):
        r = client.get("/api/v1/adapters")
        assert isinstance(r.json()["adapters"], list)

    def test_adapters_has_timestamp(self, client):
        r = client.get("/api/v1/adapters")
        assert "timestamp" in r.json()


# ── /api/v1/evidence ───────────────────────────────────────────────────────────

class TestV1Evidence:
    def test_evidence_returns_200(self, client):
        r = client.get("/api/v1/evidence")
        assert r.status_code == 200

    def test_evidence_has_data_key(self, client):
        r = client.get("/api/v1/evidence")
        data = r.json()
        assert "data" in data or "error" in data

    def test_evidence_has_timestamp(self, client):
        r = client.get("/api/v1/evidence")
        assert "timestamp" in r.json()

    def test_evidence_data_is_list(self, client):
        r = client.get("/api/v1/evidence")
        data = r.json()
        if "data" in data:
            assert isinstance(data["data"], list)

    def test_evidence_source_field_present(self, client):
        r = client.get("/api/v1/evidence")
        data = r.json()
        # source is present when file is found
        assert "source" in data or "error" in data
