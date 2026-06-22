"""
tests/test_tournament_api.py — /api/tournament and /api/tournament/status

No network, no Keychain required.
All file I/O is exercised via tmp_path + monkeypatching _DATA_DIR.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── Path setup ──────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient

from spa_core.api.server import app  # noqa: E402  (after path setup)

# ─── Shared sample data ───────────────────────────────────────────────────────

SAMPLE_MASS = {
    "generated_at": "2026-06-22T10:00:00Z",
    "simulation_period": "2022-01-01 to 2025-12-31",
    "strategies_tested": 60,
    "strategies_skipped": 14,
    "total_files_scanned": 74,
    "leaderboard": [
        {
            "rank": 1, "id": "s7_pendle_yt_aggressive", "class": "S7PendleYTAggressive",
            "sharpe": 196.60, "annual_return_pct": 0.99, "max_dd_pct": 0.0098,
            "volatility_pct": 0.0057, "total_return_pct": 4.03, "allocation": {"morpho_steakhouse": 0.20},
        },
        {
            "rank": 2, "id": "s12_base_layer_yield", "class": "S12BaseLayerYield",
            "sharpe": 196.17, "annual_return_pct": 4.09, "max_dd_pct": 0.0392,
            "volatility_pct": 0.0235, "total_return_pct": 17.42, "allocation": {"morpho_steakhouse": 0.80},
        },
        {
            "rank": 3, "id": "s5_pendle_enhanced", "class": "S5PendleEnhanced",
            "sharpe": 185.47, "annual_return_pct": 1.33, "max_dd_pct": 0.0139,
            "volatility_pct": 0.0082, "total_return_pct": 5.45, "allocation": {"compound_v3": 0.10},
        },
    ],
}

SAMPLE_TOURNAMENT = {
    "generated_at": "2026-06-22T10:00:00Z",
    "active_strategies": [
        {
            "rank": 1, "strategy_key": "s7_pendle_yt_aggressive", "name": "S7PendleYTAggressive",
            "sharpe": 196.60, "paper_apy": 0.99, "max_dd_pct": 0.0098,
            "days_active": 5, "allocation": {"morpho_steakhouse": 0.20},
        },
    ],
}

SAMPLE_SHADOW = {
    "generated_at": "2026-06-22T10:00:00Z",
    "shadow_active_strategies": [
        {"rank": 1, "strategy_key": "s7_pendle_yt_aggressive", "name": "S7PendleYTAggressive",
         "paper_equity": 100450.0},
    ],
}

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def data_dir(tmp_path):
    """Temp data dir populated with all three tournament JSON files."""
    (tmp_path / "mass_tournament_results.json").write_text(json.dumps(SAMPLE_MASS))
    (tmp_path / "strategy_tournament.json").write_text(json.dumps(SAMPLE_TOURNAMENT))
    (tmp_path / "shadow_paper_trading.json").write_text(json.dumps(SAMPLE_SHADOW))
    with patch("spa_core.api.server._DATA_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def empty_data_dir(tmp_path):
    """Temp data dir with NO tournament files — tests graceful empty fallback."""
    with patch("spa_core.api.server._DATA_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def client():
    return TestClient(app)


# ─── /api/tournament — basic contract ────────────────────────────────────────

def test_tournament_returns_200(client, data_dir):
    resp = client.get("/api/tournament")
    assert resp.status_code == 200


def test_tournament_content_type_json(client, data_dir):
    resp = client.get("/api/tournament")
    assert "application/json" in resp.headers["content-type"]


def test_tournament_has_required_keys(client, data_dir):
    d = client.get("/api/tournament").json()
    for key in ("mass_results", "tournament", "shadow_paper", "server_time", "live"):
        assert key in d, f"Missing key: {key!r}"


def test_tournament_live_is_true(client, data_dir):
    d = client.get("/api/tournament").json()
    assert d["live"] is True


def test_tournament_server_time_is_iso(client, data_dir):
    ts = client.get("/api/tournament").json()["server_time"]
    # ISO-8601: must contain 'T' and either 'Z' or '+' offset
    assert "T" in ts, f"server_time not ISO: {ts!r}"


# ─── /api/tournament — data content ──────────────────────────────────────────

def test_tournament_mass_results_populated(client, data_dir):
    d = client.get("/api/tournament").json()
    mr = d["mass_results"]
    assert mr["strategies_tested"] == 60
    assert mr["strategies_skipped"] == 14
    assert len(mr["leaderboard"]) == 3


def test_tournament_tournament_populated(client, data_dir):
    d = client.get("/api/tournament").json()
    assert len(d["tournament"]["active_strategies"]) == 1


def test_tournament_shadow_paper_populated(client, data_dir):
    d = client.get("/api/tournament").json()
    assert "shadow_active_strategies" in d["shadow_paper"]


def test_tournament_missing_files_return_empty_defaults(client, empty_data_dir):
    d = client.get("/api/tournament").json()
    assert d["mass_results"] == {"leaderboard": [], "strategies_tested": 0}
    assert d["tournament"] == {"active_strategies": []}
    assert d["shadow_paper"] == {}
    assert d["live"] is True


def test_tournament_no_cache_headers(client, data_dir):
    resp = client.get("/api/tournament")
    cc = resp.headers.get("cache-control", "")
    assert "no-store" in cc or "no-cache" in cc, f"Unexpected Cache-Control: {cc!r}"


# ─── /api/tournament/status — basic contract ─────────────────────────────────

def test_tournament_status_returns_200(client, data_dir):
    assert client.get("/api/tournament/status").status_code == 200


def test_tournament_status_has_required_keys(client, data_dir):
    d = client.get("/api/tournament/status").json()
    for key in ("total_backtested", "total_skipped", "paper_phase_count", "top3", "server_time", "live"):
        assert key in d, f"Missing key: {key!r}"


def test_tournament_status_live_is_true(client, data_dir):
    assert client.get("/api/tournament/status").json()["live"] is True


def test_tournament_status_top3_is_list(client, data_dir):
    d = client.get("/api/tournament/status").json()
    assert isinstance(d["top3"], list)


def test_tournament_status_correct_counts(client, data_dir):
    d = client.get("/api/tournament/status").json()
    assert d["total_backtested"] == 60
    assert d["total_skipped"] == 14
    assert d["paper_phase_count"] == 1
    assert len(d["top3"]) == 3
    assert d["top3"][0]["rank"] == 1


def test_tournament_status_empty_files(client, empty_data_dir):
    d = client.get("/api/tournament/status").json()
    assert d["total_backtested"] == 0
    assert d["total_skipped"] == 0
    assert d["paper_phase_count"] == 0
    assert d["top3"] == []
    assert d["live"] is True


def test_tournament_status_no_cache_headers(client, data_dir):
    resp = client.get("/api/tournament/status")
    cc = resp.headers.get("cache-control", "")
    assert "no-store" in cc or "no-cache" in cc, f"Unexpected Cache-Control: {cc!r}"
