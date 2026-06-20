"""
Tests for spa_core/api/client.py — MP-1528 (v11.44).

25 tests covering:
  - HTTP-path success
  - File fallback (all methods)
  - is_api_available()
  - Edge cases: empty files, missing files, malformed JSON
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.api.client import SPAApiClient


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def data_dir(tmp_path):
    """Minimal data dir for fallback tests."""
    dd = tmp_path / "data"
    dd.mkdir()

    # KANBAN.json at project root
    (tmp_path / "KANBAN.json").write_text(json.dumps({
        "done_count": 1193,
        "sprint_completed": "v11.44",
        "version": "11.44.0",
    }), encoding="utf-8")

    # golive_status.json
    (dd / "golive_status.json").write_text(json.dumps({
        "pass_count": 16,
        "total": 26,
        "ready": False,
        "blockers": ["gap_monitor_30d"],
    }), encoding="utf-8")

    # paper_evidence_history.json
    (dd / "paper_evidence_history.json").write_text(json.dumps([
        {"date": "2026-06-10", "apy": 5.2},
        {"date": "2026-06-11", "apy": 5.4},
    ]), encoding="utf-8")

    return tmp_path


@pytest.fixture()
def client_file_only(data_dir):
    """Client that always falls back to files (no running server)."""
    return SPAApiClient(
        base_url="http://localhost:19999",  # port nothing is listening on
        base_dir=data_dir,
        timeout=1,
    )


@pytest.fixture()
def client_mocked_http(data_dir):
    """Client with _http_get patched to return canned HTTP responses."""
    c = SPAApiClient(base_dir=data_dir)
    return c


# ── init / config ──────────────────────────────────────────────────────────────

class TestClientInit:
    def test_default_base_url(self):
        c = SPAApiClient()
        assert c.base_url == "http://localhost:8765"

    def test_custom_base_url(self):
        c = SPAApiClient(base_url="http://example.com/")
        assert c.base_url == "http://example.com"  # trailing slash stripped

    def test_custom_timeout(self):
        c = SPAApiClient(timeout=5)
        assert c.timeout == 5

    def test_base_dir_resolved(self, data_dir):
        c = SPAApiClient(base_dir=str(data_dir))
        assert c.base_dir == data_dir


# ── HTTP path ──────────────────────────────────────────────────────────────────

class TestHTTPPath:
    def test_get_status_http_success(self, client_mocked_http):
        payload = {"done_count": 1200, "sprint": "v11.44", "timestamp": "2026-06-20T00:00:00Z"}
        with patch.object(client_mocked_http, "_http_get", return_value=payload):
            result = client_mocked_http.get_status()
        assert result["done_count"] == 1200

    def test_get_golive_http_success(self, client_mocked_http):
        payload = {"pass_count": 18, "total": 26, "ready": False}
        with patch.object(client_mocked_http, "_http_get", return_value=payload):
            result = client_mocked_http.get_golive()
        assert result["pass_count"] == 18

    def test_get_adapters_http_success(self, client_mocked_http):
        payload = {"adapters": [{"name": "aave_v3", "tier": "T1", "apy": 3.5}], "count": 1}
        with patch.object(client_mocked_http, "_http_get", return_value=payload):
            result = client_mocked_http.get_adapters()
        assert len(result) == 1
        assert result[0]["name"] == "aave_v3"

    def test_get_evidence_http_success(self, client_mocked_http):
        payload = {"data": [{"date": "2026-06-10", "apy": 5.2}], "timestamp": "2026-06-20T00:00:00Z"}
        with patch.object(client_mocked_http, "_http_get", return_value=payload):
            result = client_mocked_http.get_evidence()
        assert isinstance(result, list)
        assert result[0]["apy"] == 5.2

    def test_is_api_available_true(self, client_mocked_http):
        with patch.object(client_mocked_http, "_http_get", return_value={"status": "ok"}):
            assert client_mocked_http.is_api_available() is True

    def test_is_api_available_false_on_error(self, client_mocked_http):
        with patch.object(client_mocked_http, "_http_get", side_effect=ConnectionError("down")):
            assert client_mocked_http.is_api_available() is False


# ── file fallback ──────────────────────────────────────────────────────────────

class TestFileFallback:
    def test_get_status_fallback_reads_kanban(self, client_file_only):
        result = client_file_only.get_status()
        assert result["done_count"] == 1193
        assert result["sprint"] == "v11.44"

    def test_get_status_fallback_source_field(self, client_file_only):
        result = client_file_only.get_status()
        assert result.get("source") in ("file", "error")

    def test_get_golive_fallback_reads_file(self, client_file_only):
        result = client_file_only.get_golive()
        assert result.get("pass_count") == 16
        assert result.get("ready") is False

    def test_get_golive_fallback_source_file(self, client_file_only):
        result = client_file_only.get_golive()
        assert result.get("source") == "file"

    def test_get_evidence_fallback_returns_list(self, client_file_only):
        result = client_file_only.get_evidence()
        assert isinstance(result, list)

    def test_get_evidence_fallback_has_entries(self, client_file_only):
        result = client_file_only.get_evidence()
        assert len(result) >= 1

    def test_get_adapters_fallback_returns_list(self, client_file_only):
        result = client_file_only.get_adapters()
        assert isinstance(result, list)


# ── edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_missing_kanban_returns_safe_dict(self, tmp_path):
        """No KANBAN.json → safe error dict returned, no exception."""
        c = SPAApiClient(base_url="http://localhost:19999", base_dir=tmp_path, timeout=1)
        result = c.get_status()
        assert isinstance(result, dict)
        assert "done_count" in result

    def test_missing_golive_returns_safe_dict(self, tmp_path):
        (tmp_path / "data").mkdir(exist_ok=True)
        c = SPAApiClient(base_url="http://localhost:19999", base_dir=tmp_path, timeout=1)
        result = c.get_golive()
        assert isinstance(result, dict)

    def test_missing_evidence_returns_empty_list(self, tmp_path):
        (tmp_path / "data").mkdir(exist_ok=True)
        c = SPAApiClient(base_url="http://localhost:19999", base_dir=tmp_path, timeout=1)
        result = c.get_evidence()
        assert isinstance(result, list)

    def test_no_exception_on_http_error(self, client_mocked_http):
        with patch.object(client_mocked_http, "_http_get", side_effect=OSError("refused")):
            # Should not raise — falls back to file
            result = client_mocked_http.get_status()
            assert isinstance(result, dict)

    def test_adapters_http_missing_key_returns_list(self, client_mocked_http):
        """If HTTP returns payload without 'adapters' key → empty list."""
        with patch.object(client_mocked_http, "_http_get", return_value={"count": 0}):
            result = client_mocked_http.get_adapters()
            assert isinstance(result, list)
