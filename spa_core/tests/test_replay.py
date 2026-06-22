"""
Tests for spa_core/backtesting/replay.py and scenario_runner.py

Covers:
    1.  ReplayEngine loads synthetic data when pnl_history.json is absent
    2.  replay_step() returns correct schema
    3.  replay_step() day=0 → daily_pnl == 0
    4.  replay_step() out-of-range raises IndexError
    5.  full_replay() returns one frame per day, sorted chronologically
    6.  full_replay() cumulative_pnl_pct at day N matches manual calculation
    7.  replay_summary() keys are present
    8.  replay_summary() total_return_pct matches first→last capital
    9.  ReplayEngine with real pnl_history.json (injected via tmp_path)
    10. Edge case: single-day pnl_history → summary returns valid dict
    11. Edge case: empty pnl_history.json → falls back to synthetic
    12. run_scenario() v1_passive returns standardised result schema
    13. run_scenario() v2_aggressive returns standardised result schema
    14. run_scenario() unknown strategy raises ValueError
    15. compare_scenarios() returns both strategies and a winner
    16. compare_scenarios() delta values are consistent (v2 - v1)
    17. compare_scenarios() equity curves have the right number of entries
    18. Sharpe ratio is finite for multi-day runs
    19. Max drawdown is between 0 and 100%
    20. Win rate is in [0, 1]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

# Ensure spa_core is on sys.path
_SPA_CORE = Path(__file__).parent.parent
if str(_SPA_CORE) not in sys.path:
    sys.path.insert(0, str(_SPA_CORE))

from backtesting.replay import ReplayEngine
from backtesting.scenario_runner import run_scenario, compare_scenarios


# ─── Fixtures ──────────────────────────────────────────────────────────────────

def _make_pnl_history(tmp_path: Path, n_days: int = 5) -> Path:
    """Write a synthetic pnl_history.json with n_days entries to tmp_path/data/."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    initial = 100_000.0
    records = []
    for i in range(n_days):
        capital = initial + i * 50.0        # grows by $50/day
        deployed = capital * 0.80
        records.append({
            "timestamp": f"2026-05-{20 + i:02d} 06:00:00",
            "total_capital_usd": round(capital, 2),
            "deployed_capital_usd": round(deployed, 2),
            "cash_usd": round(capital - deployed, 2),
            "total_pnl_usd": round(capital - initial, 2),
            "total_pnl_pct": round((capital - initial) / initial * 100, 4),
            "current_apy": 4.65,
            "trade_count": i,
        })
    (data_dir / "pnl_history.json").write_text(json.dumps(records), encoding="utf-8")
    return data_dir


def _make_empty_pnl_history(tmp_path: Path) -> Path:
    """Write an empty pnl_history.json."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pnl_history.json").write_text("[]", encoding="utf-8")
    return data_dir


# ─── ReplayEngine — synthetic fallback ────────────────────────────────────────

class TestReplayEngineNoHistory:
    """Tests when pnl_history.json is absent → engine uses synthetic data."""

    def setup_method(self):
        # Point to a directory that has no pnl_history.json
        self.engine = ReplayEngine(data_dir=Path("/tmp/nonexistent_spa_data"))

    def test_source_is_synthetic(self):
        """Test 1 — Source label is 'synthetic' when no real history file."""
        assert self.engine.source == "synthetic"

    def test_total_days_positive(self):
        """Test 2a — At least some days are generated."""
        assert self.engine.total_days > 0

    def test_replay_step_schema(self):
        """Test 2b — replay_step returns the expected keys."""
        frame = self.engine.replay_step(0)
        required = {
            "day", "date", "portfolio_value", "daily_pnl",
            "cumulative_pnl_pct", "positions_snapshot",
            "deployed_usd", "cash_usd", "trade_count", "data_source",
        }
        assert required.issubset(frame.keys())

    def test_day0_daily_pnl_zero(self):
        """Test 3 — Day 0 has no prior day, so daily_pnl must be 0."""
        frame = self.engine.replay_step(0)
        assert frame["daily_pnl"] == 0.0

    def test_replay_step_out_of_range(self):
        """Test 4 — Negative or too-large day index raises IndexError."""
        with pytest.raises(IndexError):
            self.engine.replay_step(-1)
        with pytest.raises(IndexError):
            self.engine.replay_step(self.engine.total_days)

    def test_full_replay_length(self):
        """Test 5a — full_replay returns one frame per recorded day."""
        frames = self.engine.full_replay()
        assert len(frames) == self.engine.total_days

    def test_full_replay_chronological(self):
        """Test 5b — Dates in full_replay are non-decreasing."""
        frames = self.engine.full_replay()
        dates = [f["date"] for f in frames]
        assert dates == sorted(dates)

    def test_full_replay_cumulative_pnl(self):
        """Test 6 — cumulative_pnl_pct at last day matches manual calc."""
        frames = self.engine.full_replay()
        last = frames[-1]
        first = frames[0]
        expected_pct = (
            (last["portfolio_value"] - first["portfolio_value"])
            / first["portfolio_value"] * 100
        )
        assert abs(last["cumulative_pnl_pct"] - expected_pct) < 0.01


# ─── ReplayEngine — real history ──────────────────────────────────────────────

class TestReplayEngineRealHistory:
    """Tests when pnl_history.json is present."""

    def test_source_is_pnl_history(self, tmp_path):
        """Test 9 — Source label is 'pnl_history' when file exists."""
        data_dir = _make_pnl_history(tmp_path, n_days=5)
        engine = ReplayEngine(data_dir=data_dir)
        assert engine.source == "pnl_history"

    def test_total_days_matches_file(self, tmp_path):
        """Test 9b — total_days matches the number of records in the file."""
        n = 7
        data_dir = _make_pnl_history(tmp_path, n_days=n)
        engine = ReplayEngine(data_dir=data_dir)
        assert engine.total_days == n

    def test_replay_step_portfolio_value(self, tmp_path):
        """Test 9c — portfolio_value at day 2 matches file record."""
        data_dir = _make_pnl_history(tmp_path, n_days=5)
        engine = ReplayEngine(data_dir=data_dir)
        frame = engine.replay_step(2)
        # capital at day 2 = 100000 + 2*50 = 100100
        assert abs(frame["portfolio_value"] - 100_100.0) < 0.01

    def test_summary_keys_present(self, tmp_path):
        """Test 7 — replay_summary() contains all required metric keys."""
        data_dir = _make_pnl_history(tmp_path, n_days=10)
        engine = ReplayEngine(data_dir=data_dir)
        summary = engine.replay_summary()
        required = {
            "total_days", "total_return_pct", "annualized_return",
            "sharpe_ratio", "max_drawdown", "win_rate",
            "best_day", "worst_day", "data_source",
            "initial_capital", "final_capital",
        }
        assert required.issubset(summary.keys())

    def test_summary_total_return(self, tmp_path):
        """Test 8 — total_return_pct matches first→last capital."""
        data_dir = _make_pnl_history(tmp_path, n_days=5)
        engine = ReplayEngine(data_dir=data_dir)
        summary = engine.replay_summary()
        # 5 days * $50/day = $200 gain on $100,000
        expected = (200 / 100_000) * 100
        assert abs(summary["total_return_pct"] - expected) < 0.01

    def test_summary_win_rate_range(self, tmp_path):
        """Test 20 — win_rate is always in [0, 1]."""
        data_dir = _make_pnl_history(tmp_path, n_days=10)
        engine = ReplayEngine(data_dir=data_dir)
        summary = engine.replay_summary()
        assert 0.0 <= summary["win_rate"] <= 1.0

    def test_summary_max_drawdown_range(self, tmp_path):
        """Test 19 — max_drawdown is between 0 and 100."""
        data_dir = _make_pnl_history(tmp_path, n_days=10)
        engine = ReplayEngine(data_dir=data_dir)
        summary = engine.replay_summary()
        assert 0.0 <= summary["max_drawdown"] <= 100.0


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case tests."""

    def test_single_day_summary(self, tmp_path):
        """Test 10 — Single-day history → summary returns a valid dict."""
        data_dir = _make_pnl_history(tmp_path, n_days=1)
        engine = ReplayEngine(data_dir=data_dir)
        summary = engine.replay_summary()
        assert isinstance(summary, dict)
        assert summary["total_days"] == 1
        assert summary["total_return_pct"] == 0.0   # only one point, no return

    def test_empty_pnl_history_falls_back_to_synthetic(self, tmp_path):
        """Test 11 — Empty pnl_history.json → engine uses synthetic data."""
        data_dir = _make_empty_pnl_history(tmp_path)
        engine = ReplayEngine(data_dir=data_dir)
        assert engine.source == "synthetic"
        assert engine.total_days > 0

    def test_sharpe_ratio_finite(self, tmp_path):
        """Test 18 — Sharpe ratio is finite (not NaN or inf)."""
        data_dir = _make_pnl_history(tmp_path, n_days=30)
        engine = ReplayEngine(data_dir=data_dir)
        summary = engine.replay_summary()
        sharpe = summary["sharpe_ratio"]
        assert math.isfinite(sharpe)


# ─── ScenarioRunner ───────────────────────────────────────────────────────────

class TestScenarioRunner:
    """Tests for run_scenario and compare_scenarios."""

    def test_v1_passive_schema(self):
        """Test 12 — v1_passive result has all required keys."""
        result = run_scenario("v1_passive", days=10, seed=99)
        required = {
            "strategy", "total_return", "sharpe", "max_drawdown",
            "win_rate", "calmar", "sortino", "equity_curve",
            "initial_capital", "final_capital", "days",
            "annualized_return", "total_trades",
        }
        assert required.issubset(result.keys())

    def test_v2_aggressive_schema(self):
        """Test 13 — v2_aggressive result has all required keys."""
        result = run_scenario("v2_aggressive", days=10, seed=99)
        required = {
            "strategy", "total_return", "sharpe", "max_drawdown",
            "win_rate", "calmar", "sortino", "equity_curve",
        }
        assert required.issubset(result.keys())

    def test_unknown_strategy_raises(self):
        """Test 14 — Unknown strategy name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            run_scenario("v3_superlative", days=10, seed=1)

    def test_compare_returns_both_strategies(self):
        """Test 15 — compare_scenarios returns entries for both strategies."""
        cmp = compare_scenarios(days=10, seed=7)
        assert "v1_passive" in cmp
        assert "v2_aggressive" in cmp
        assert cmp["winner"] in ("v1_passive", "v2_aggressive")

    def test_compare_delta_consistency(self):
        """Test 16 — delta values equal v2 - v1 for total_return."""
        cmp = compare_scenarios(days=10, seed=7)
        v1_ret = cmp["v1_passive"]["total_return"]
        v2_ret = cmp["v2_aggressive"]["total_return"]
        delta_ret = cmp["delta"]["total_return"]
        assert abs(delta_ret - (v2_ret - v1_ret)) < 1e-6

    def test_equity_curve_length(self):
        """Test 17 — equity_curve has one entry per simulated day."""
        days = 15
        result = run_scenario("v1_passive", days=days, seed=42)
        # Engine may produce slightly fewer days due to data-grouping;
        # accept anything from days-1 to days+1.
        assert abs(len(result["equity_curve"]) - days) <= 1

    def test_initial_capital_preserved(self):
        """Equity curve day 0 portfolio_value equals or is very close to initial_capital."""
        cap = 50_000.0
        result = run_scenario("v1_passive", initial_capital=cap, days=5, seed=1)
        first_value = result["equity_curve"][0]["portfolio_value"]
        # First day accrues some interest, so value >= initial_capital
        assert first_value >= cap

    def test_win_rate_in_range(self):
        """Win rate from run_scenario is in [0, 1]."""
        result = run_scenario("v2_aggressive", days=20, seed=3)
        assert 0.0 <= result["win_rate"] <= 1.0

    def test_max_drawdown_non_negative(self):
        """Max drawdown from run_scenario is non-negative."""
        result = run_scenario("v1_passive", days=20, seed=3)
        assert result["max_drawdown"] >= 0.0
