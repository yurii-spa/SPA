"""Q2-1 surfacing: GET /api/rates-desk/capacity exposes the N-book portfolio-capacity
aggregate (the honest, machine-checkable scale story + gap to the $10M thesis).

Read-only, graceful, fail-CLOSED, always advisory, never 500. Serves the deterministic
aggregator's output verbatim + an honest reproduce block.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def _write_capacity(data_dir: Path, obj: dict) -> None:
    d = data_dir / "rates_desk"
    d.mkdir(parents=True, exist_ok=True)
    (d / "portfolio_capacity.json").write_text(json.dumps(obj), encoding="utf-8")


def test_capacity_missing_file_is_flagged_never_500(client):
    c, _ = client
    r = c.get("/api/rates-desk/capacity")
    assert r.status_code == 200
    b = r.json()
    assert b["flagged"] is True
    assert b["flag_reason"] == "portfolio_capacity_unavailable"
    assert b["is_advisory"] is True
    assert b["generated_at"] is None
    assert b["reproduce"]["deterministic"] is True


def test_capacity_served_verbatim_with_advisory_and_reproduce(client):
    c, data_dir = client
    _write_capacity(data_dir, {
        "generated_at": "2026-07-10T12:00:00Z",
        "total_deployable_usd": 12_000_000,
        "dollars_above_floor_per_yr": 34_000,
        "n_fundable_books": 3,
        "books_needed_for_10m": 294,
        "gap_to_10m_usd": 9_966_000,
        "pct_of_10m_target": 0.34,
        "books": [{"name": "rates_desk", "deployable_usd": 8_000_000}],
    })
    r = c.get("/api/rates-desk/capacity")
    assert r.status_code == 200
    b = r.json()
    assert b["dollars_above_floor_per_yr"] == 34_000
    assert b["books_needed_for_10m"] == 294
    assert b["gap_to_10m_usd"] == 9_966_000
    assert b["is_advisory"] is True  # always stamped, even if the file omits it
    assert b["reproduce"]["rerun"].startswith("python3 -m spa_core.strategy_lab.portfolio_capacity")
    # Defensive units annotation prevents a 100× overstatement misread of pct_of_10m_target.
    assert "PERCENT" in b["field_units"]["pct_of_10m_target"]


def test_capacity_nan_is_scrubbed_never_500(client):
    c, data_dir = client
    d = data_dir / "rates_desk"
    d.mkdir(parents=True, exist_ok=True)
    # A corrupt aggregate carrying a non-finite must not crash the JSON serializer.
    (d / "portfolio_capacity.json").write_text(
        '{"dollars_above_floor_per_yr": NaN, "books": []}', encoding="utf-8"
    )
    r = c.get("/api/rates-desk/capacity")
    assert r.status_code == 200
