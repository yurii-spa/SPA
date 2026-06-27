"""
test_exit_nav_api.py — the /api/rates-desk/exit-nav endpoint contract.

The flagship LIQUIDATION-NAV-BY-SIZE surface is served on the LIVE public API; it must (1) return
the schedule + book + model + advisory envelope when the engine has written a file, and (2) FAIL
CLOSED gracefully — an empty FLAGGED schedule, 200 not 500 — when the file is absent/corrupt (the
same graceful fallback the dashboard depends on). PURE / hermetic (data dir redirected to tmp).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in (str(_SPA_CORE), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402
from spa_core.strategy_lab.rates_desk.exit_nav import build_exit_nav_schedule  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def _write_schedule(data_dir: Path) -> dict:
    """Build a real schedule (deep pool → real rows) and persist it where the API reads it."""
    surface = {"as_of": "2026-06-25",
               "quotes": [{"market_id": "MKT", "underlying": "usdc",
                           "exit_liquidity_usd": 50_000_000.0}]}
    book = {"market_id": "MKT", "underlying": "usdc", "gross_usd": 10_000_000.0,
            "as_of": "2026-06-25", "source": "hypothetical"}
    out = data_dir / "rates_desk" / "exit_nav.json"
    return build_exit_nav_schedule(write=True, surface=surface, deep={}, book=book, out_path=out)


def test_exit_nav_endpoint_shape(client):
    """With a written schedule, the endpoint serves it with the schedule/book/model/envelope."""
    c, data_dir = client
    written = _write_schedule(data_dir)
    resp = c.get("/api/rates-desk/exit-nav")
    assert resp.status_code == 200, resp.text[:200]
    body = resp.json()
    assert isinstance(body, dict)
    # core surface
    assert body["model"] == written["model"]
    assert body["as_of"] == "2026-06-25"
    assert isinstance(body["schedule"], list) and len(body["schedule"]) == 5
    assert body["book"]["source"] == "hypothetical"
    assert body["is_advisory"] is True
    assert "Oct-2025" in body["validation_ref"]
    assert "meta" in body and body["meta"]["is_backtest"] is True
    # rows carry the conservative-bound proof + provenance
    row = body["schedule"][0]
    for k in ("ticket_usd", "net_proceeds_usd", "haircut_pct", "depth_usd", "proof_hash",
              "model", "data_source", "as_of"):
        assert k in row
    # numbers are sane: net ≤ gross, monotonic haircut
    haircuts = [r["haircut_pct"] for r in body["schedule"]]
    assert haircuts == sorted(haircuts)
    assert all(r["net_proceeds_usd"] <= r["gross_usd"] for r in body["schedule"])


def test_exit_nav_missing_file_graceful(client):
    """No file ⇒ 200 (NOT 500) with an empty FLAGGED schedule + as_of null + advisory envelope."""
    c, _ = client  # hermetic empty data dir
    resp = c.get("/api/rates-desk/exit-nav")
    assert resp.status_code == 200, resp.text[:200]
    body = resp.json()
    assert body["schedule"] == []
    assert body["flagged"] is True
    assert body["as_of"] is None
    assert body["is_advisory"] is True
    assert "validation_ref" in body
    assert "meta" in body


def test_exit_nav_corrupt_file_graceful(client):
    """A corrupt JSON file ⇒ graceful empty flagged schedule, never a 500."""
    c, data_dir = client
    p = data_dir / "rates_desk" / "exit_nav.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not valid json", encoding="utf-8")
    resp = c.get("/api/rates-desk/exit-nav")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schedule"] == []
    assert body["flagged"] is True


def test_exit_nav_verbatim_passthrough(client):
    """The written file is served VERBATIM (engine output == API payload sans added meta)."""
    c, data_dir = client
    written = _write_schedule(data_dir)
    body = c.get("/api/rates-desk/exit-nav").json()
    on_disk = json.loads((data_dir / "rates_desk" / "exit_nav.json").read_text())
    # every schedule proof_hash survives the round-trip unchanged
    assert [r["proof_hash"] for r in body["schedule"]] == [r["proof_hash"] for r in on_disk["schedule"]]
    assert body["schedule"][0]["proof_hash"] == written["schedule"][0]["proof_hash"]
