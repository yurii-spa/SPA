"""
test_tournament_trust_honesty.py — honesty gate for the public tournament rankings.

Defect (architect P4-1): the mass tournament ranks strategies by Sharpe, but on
near-constant (mock OR stablecoin) returns that Sharpe is mathematically degenerate.
That output flows to the PUBLIC tournament page. No degenerate Sharpe ranking may be
presented as a live/real result.

These tests assert:
  • a degenerate (mock / near-constant) leaderboard → trustworthy=False  (fail-closed)
  • a real, non-degenerate leaderboard → trustworthy=True
  • the producer (MassTournament.run) stamps data_source + trustworthy
  • the API (/api/tournament) surfaces trustworthy and fail-closes a missing flag
  • NO code path emits trustworthy=True from a degenerate/mock leaderboard
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.tier1 import evaluator as ev


# A degenerate leaderboard: huge Sharpe + near-zero vol = near-constant (mock) returns.
_DEGENERATE_BOARD = [
    {"id": "s1", "sharpe": 80.7, "volatility_pct": 0.046, "annual_return_pct": 3.6,
     "max_dd_pct": -0.01, "allocation": {"aave_v3": 1.0}},
    {"id": "s2", "sharpe": 72.4, "volatility_pct": 0.075, "annual_return_pct": 4.1,
     "max_dd_pct": -0.02, "allocation": {"compound_v3": 1.0}},
    {"id": "s3", "sharpe": 66.8, "volatility_pct": 0.084, "annual_return_pct": 4.5,
     "max_dd_pct": -0.03, "allocation": {"yearn_v3": 1.0}},
]

# A plausible (non-degenerate) leaderboard: real DeFi-yield Sharpe band + meaningful vol.
_REAL_BOARD = [
    {"id": "s1", "sharpe": 1.8, "volatility_pct": 6.0, "annual_return_pct": 9.0,
     "max_dd_pct": -4.0, "allocation": {"aave_v3": 1.0}},
    {"id": "s2", "sharpe": 1.2, "volatility_pct": 8.5, "annual_return_pct": 11.0,
     "max_dd_pct": -7.0, "allocation": {"compound_v3": 1.0}},
    {"id": "s3", "sharpe": 0.9, "volatility_pct": 10.0, "annual_return_pct": 7.0,
     "max_dd_pct": -9.0, "allocation": {"yearn_v3": 1.0}},
]


# ── assess_tournament_trust ───────────────────────────────────────────────────

def test_degenerate_board_not_trustworthy():
    stamp = ev.assess_tournament_trust({"leaderboard": _DEGENERATE_BOARD})
    assert stamp["trustworthy"] is False
    assert stamp["data_source_regime"] in ("DEGENERATE_MOCK", "LOW_VOL_YIELD")
    assert stamp["data_quality"]["status"] == "DEGENERATE"
    assert stamp["reason"]


def test_real_board_trustworthy():
    stamp = ev.assess_tournament_trust({"leaderboard": _REAL_BOARD})
    assert stamp["trustworthy"] is True
    assert stamp["data_source_regime"] == "NORMAL"


def test_empty_board_fail_closed():
    stamp = ev.assess_tournament_trust({"leaderboard": []})
    assert stamp["trustworthy"] is False


def test_assess_never_raises_fail_closed():
    # Garbage input must fail-CLOSED, not raise.
    stamp = ev.assess_tournament_trust({"leaderboard": "not-a-list"})
    assert stamp["trustworthy"] is False


def test_no_path_marks_degenerate_as_trustworthy():
    # The core honesty invariant: degenerate data can NEVER be trustworthy=True.
    for board in (_DEGENERATE_BOARD, [], "junk"):
        stamp = ev.assess_tournament_trust({"leaderboard": board})
        assert stamp["trustworthy"] is False


# ── producer stamps the flag ──────────────────────────────────────────────────

def test_producer_stamps_trustworthy(tmp_path):
    from spa_core.backtesting.mass_tournament import MassTournament
    mt = MassTournament()
    result = mt.run(data_dir=str(tmp_path))
    # Top-level + meta both carry the honesty flags.
    assert "trustworthy" in result
    assert "data_source" in result
    assert isinstance(result["trustworthy"], bool)
    assert "trustworthy" in result["meta"]
    assert "data_source_regime" in result["meta"]
    # The real bee data is stablecoin-yield (low-vol) → degenerate → NOT trustworthy.
    # Whatever the regime, a degenerate data_quality must imply trustworthy=False.
    if result["meta"]["data_quality"]["status"] == "DEGENERATE":
        assert result["trustworthy"] is False
    # Written file carries the same stamp.
    import json
    on_disk = json.loads((tmp_path / "mass_tournament_results.json").read_text())
    assert on_disk["trustworthy"] == result["trustworthy"]
    assert on_disk["meta"]["data_source_regime"] == result["meta"]["data_source_regime"]


# ── API surfaces + fail-closes the flag ───────────────────────────────────────

pytest.importorskip("fastapi", reason="fastapi optional dep not installed")
from fastapi.testclient import TestClient  # noqa: E402
import spa_core.api.server as server  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def _write(tmp_path, name, obj):
    import json
    (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")


def test_api_surfaces_trustworthy_true(client):
    c, tmp_path = client
    _write(tmp_path, "mass_tournament_results.json", {
        "leaderboard": [{"id": "s1", "sharpe": 1.5}],
        "strategies_tested": 3,
        "trustworthy": True,
        "data_source": "defillama_real",
        "meta": {"trustworthy": True, "data_source_regime": "NORMAL"},
    })
    d = c.get("/api/tournament").json()
    assert d["trustworthy"] is True
    assert d["meta"]["trustworthy"] is True


def test_api_surfaces_trustworthy_false(client):
    c, tmp_path = client
    _write(tmp_path, "mass_tournament_results.json", {
        "leaderboard": [{"id": "s1", "sharpe": 80.0}],
        "strategies_tested": 3,
        "trustworthy": False,
        "data_source": "defillama_real",
        "meta": {"trustworthy": False, "data_source_regime": "LOW_VOL_YIELD",
                 "trust_reason": "degenerate"},
    })
    d = c.get("/api/tournament").json()
    assert d["trustworthy"] is False
    assert d["meta"]["trustworthy"] is False


def test_api_fail_closed_on_missing_flag(client):
    # A legacy result with NO trustworthy flag must be treated as NOT trustworthy.
    c, tmp_path = client
    _write(tmp_path, "mass_tournament_results.json", {
        "leaderboard": [{"id": "s1", "sharpe": 80.0}],
        "strategies_tested": 3,
    })
    d = c.get("/api/tournament").json()
    assert d["trustworthy"] is False
    assert d["meta"]["trustworthy"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
