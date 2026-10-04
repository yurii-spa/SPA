"""/api/v1/packages/status — the fresh public copy of the paper-portfolio status (ADR-537).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def test_status_is_served_uncached_and_sanitised(client):
    c, tmp = client
    (tmp / "agent_health.json").write_text(json.dumps({"agents": []}))
    # ADR-554 DQ-2: real capital 0 is derived from the declared paper execution mode, so the scene declares it
    (tmp / "paper_trading_status.json").write_text(json.dumps({"execution_mode": "read_only_simulation"}))
    (tmp / "defi_engine").mkdir()
    (tmp / "defi_engine" / "status.json").write_text(json.dumps({"execution_mode": "read_only_simulation"}))
    r = c.get("/api/v1/packages/status")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "")
    body = r.json()
    assert body["source"] == "live" and body["live_capital_usd"] == 0
    assert set(body["packages"]) == {"conservative", "balanced", "aggressive"}
    assert body["packages"]["balanced"]["work"]["state"] == "NOT_STARTED"
    assert str(tmp) not in r.text and "com.spa." not in r.text


def test_a_read_failure_is_a_named_503_not_an_empty_all_clear(client, monkeypatch):
    c, _ = client
    from spa_core.defi_engine import package_status as PS

    def boom(*a, **k):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(PS, "build_all", boom)
    r = c.get("/api/v1/packages/status")
    assert r.status_code == 503 and r.json()["packages"] is None
    assert "disk gone" not in r.text, "the raw error stays in the server log"
