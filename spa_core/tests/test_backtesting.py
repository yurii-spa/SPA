"""
Tests for the backtesting module — metrics, data loader, and BacktestEngine.
"""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.metrics import sharpe_ratio, max_drawdown, win_rate, total_return_pct
from backtesting.data_loader import generate_synthetic_history
from backtesting.engine import BacktestEngine


# ─── Metrics tests ────────────────────────────────────────────────────────────

class TestSharpeRatio:

    def test_consistently_positive_returns_high_sharpe(self):
        """Strongly positive daily returns with tiny noise → very high Sharpe ratio.

        Note: perfectly constant returns yield std=0 which the function safely returns
        as 0.0.  We use near-constant returns with tiny variance so std > 0 and the
        high signal-to-noise ratio is captured as a large Sharpe.
        """
        import random
        rng = random.Random(0)
        # Strong positive mean (~0.08%/day) with tiny noise → Sharpe >> 5
        returns = [0.0008 + rng.gauss(0, 0.00002) for _ in range(200)]
        result = sharpe_ratio(returns)
        assert result > 5.0, f"Expected high Sharpe for strongly positive returns, got {result}"

    def test_zero_returns_gives_zero_or_low_sharpe(self):
        """All-zero returns → Sharpe = 0 (no std dev)."""
        returns = [0.0] * 100
        result = sharpe_ratio(returns)
        assert result == 0.0

    def test_fewer_than_2_returns_gives_zero(self):
        """Fewer than 2 data points → return 0.0."""
        assert sharpe_ratio([]) == 0.0
        assert sharpe_ratio([0.001]) == 0.0

    def test_mixed_returns(self):
        """Mixed positive and negative returns — Sharpe should be finite."""
        import random
        rng = random.Random(42)
        returns = [rng.gauss(0.0003, 0.001) for _ in range(100)]
        result = sharpe_ratio(returns)
        assert isinstance(result, float)
        assert not (result != result)  # not NaN

    def test_higher_risk_free_lowers_sharpe(self):
        """Higher risk-free rate should reduce Sharpe ratio."""
        returns = [0.0005] * 200
        sharpe_low  = sharpe_ratio(returns, risk_free_rate=0.01)
        sharpe_high = sharpe_ratio(returns, risk_free_rate=0.10)
        assert sharpe_low >= sharpe_high


class TestMaxDrawdown:

    def test_known_drawdown_100_90_95(self):
        """Equity 100→90→95: max drawdown = 10%."""
        curve = [100.0, 90.0, 95.0]
        result = max_drawdown(curve)
        assert result == pytest.approx(0.10, abs=1e-6), f"Expected 0.10, got {result}"

    def test_monotonically_rising_no_drawdown(self):
        """Monotonically rising equity → drawdown = 0."""
        curve = [100.0, 101.0, 102.0, 103.0]
        assert max_drawdown(curve) == 0.0

    def test_empty_curve_returns_zero(self):
        assert max_drawdown([]) == 0.0

    def test_single_value_returns_zero(self):
        assert max_drawdown([100.0]) == 0.0

    def test_large_drawdown_detected(self):
        """50% drawdown should be detected."""
        curve = [100.0, 50.0, 60.0]
        result = max_drawdown(curve)
        assert result == pytest.approx(0.50, abs=1e-6)

    def test_multiple_drawdowns_returns_max(self):
        """Returns the maximum of multiple drawdown periods."""
        curve = [100.0, 90.0, 100.0, 70.0, 80.0]
        result = max_drawdown(curve)
        # Drawdown1 = 10%, Drawdown2 = 30%
        assert result == pytest.approx(0.30, abs=1e-6)


class TestWinRate:

    def test_all_winning_trades(self):
        trades = [{"pnl": 10.0}, {"pnl": 5.0}, {"pnl": 1.0}]
        assert win_rate(trades) == 1.0

    def test_all_losing_trades(self):
        trades = [{"pnl": -5.0}, {"pnl": -2.0}]
        assert win_rate(trades) == 0.0

    def test_zero_pnl_counts_as_loss(self):
        """Trades with pnl=0 are conservative — counted as losses."""
        trades = [{"pnl": 1.0}, {"pnl": 0.0}]
        assert win_rate(trades) == pytest.approx(0.5)

    def test_empty_trades_returns_zero(self):
        assert win_rate([]) == 0.0

    def test_mixed_50_50(self):
        trades = [{"pnl": 10.0}, {"pnl": -5.0}]
        assert win_rate(trades) == pytest.approx(0.5)


class TestTotalReturnPct:

    def test_positive_return(self):
        result = total_return_pct(100_000, 103_450)
        assert result == pytest.approx(3.45, abs=0.01)

    def test_negative_return(self):
        result = total_return_pct(100_000, 95_000)
        assert result == pytest.approx(-5.0, abs=0.01)

    def test_zero_initial_capital(self):
        assert total_return_pct(0, 1000) == 0.0

    def test_breakeven_zero_return(self):
        assert total_return_pct(100_000, 100_000) == 0.0


# ─── Data loader tests ────────────────────────────────────────────────────────

class TestGenerateSyntheticHistory:

    def test_generates_correct_number_of_records(self):
        """generate_synthetic_history(days=30, seed=42) → exactly 30×7 = 210 records."""
        history = generate_synthetic_history(days=30, seed=42)
        assert len(history) == 30 * 7, f"Expected 210 records, got {len(history)}"

    def test_default_90_days(self):
        """Default call generates 90×7 = 630 records."""
        history = generate_synthetic_history(seed=42)
        assert len(history) == 90 * 7

    def test_seed_reproducibility(self):
        """Same seed must produce identical output."""
        h1 = generate_synthetic_history(days=10, seed=99)
        h2 = generate_synthetic_history(days=10, seed=99)
        assert h1 == h2

    def test_different_seeds_differ(self):
        """Different seeds should produce different results."""
        h1 = generate_synthetic_history(days=10, seed=1)
        h2 = generate_synthetic_history(days=10, seed=2)
        assert h1 != h2

    def test_record_has_required_keys(self):
        """Each record must have the 5 required keys."""
        history = generate_synthetic_history(days=5, seed=42)
        for record in history:
            for key in ["timestamp", "protocol_key", "apy", "tvl_usd", "tier"]:
                assert key in record, f"Missing key '{key}' in record: {record}"

    def test_apy_positive(self):
        """All APY values must be positive."""
        history = generate_synthetic_history(days=30, seed=42)
        for record in history:
            assert record["apy"] > 0, f"Non-positive APY: {record}"

    def test_tvl_positive(self):
        """All TVL values must be positive."""
        history = generate_synthetic_history(days=30, seed=42)
        for record in history:
            assert record["tvl_usd"] > 0, f"Non-positive TVL: {record}"

    def test_sorted_by_date_protocol(self):
        """Output must be sorted by (timestamp, protocol_key)."""
        history = generate_synthetic_history(days=10, seed=42)
        keys = [(r["timestamp"], r["protocol_key"]) for r in history]
        assert keys == sorted(keys), "History is not sorted by (timestamp, protocol_key)"

    def test_seven_unique_protocols(self):
        """Exactly 7 unique protocol_keys in the output."""
        history = generate_synthetic_history(days=5, seed=42)
        protocols = {r["protocol_key"] for r in history}
        assert len(protocols) == 7, f"Expected 7 protocols, got {len(protocols)}"


# ─── BacktestEngine tests ─────────────────────────────────────────────────────

class TestBacktestEngine:

    def test_run_returns_backtest_result(self):
        """run() must return a BacktestResult object."""
        from backtesting.engine import BacktestResult
        engine = BacktestEngine()
        history = generate_synthetic_history(days=10, seed=42)
        result = engine.run(history)
        assert isinstance(result, BacktestResult)

    def test_equity_curve_length_matches_days(self):
        """equity_curve must have exactly one entry per trading day."""
        engine = BacktestEngine()
        history = generate_synthetic_history(days=10, seed=42)
        result = engine.run(history)
        assert len(result.equity_curve) == 10, (
            f"Expected 10 equity curve entries, got {len(result.equity_curve)}"
        )

    def test_metrics_has_expected_keys(self):
        """metrics dict must contain all required keys."""
        engine = BacktestEngine()
        history = generate_synthetic_history(days=10, seed=42)
        result = engine.run(history)
        required_keys = [
            "sharpe_ratio", "max_drawdown_pct", "total_return_pct",
            "annualised_return_pct", "win_rate", "total_trades",
            "initial_capital_usd", "final_capital_usd",
        ]
        for key in required_keys:
            assert key in result.metrics, f"Missing metrics key: {key}"

    def test_capital_grows_with_positive_apy(self):
        """With stable positive APY, final capital must exceed initial."""
        engine = BacktestEngine()
        history = generate_synthetic_history(days=30, seed=42)
        result = engine.run(history, initial_capital=100_000.0)
        assert result.metrics["final_capital_usd"] >= result.metrics["initial_capital_usd"]

    def test_empty_history_returns_valid_result(self):
        """Empty history → valid BacktestResult with zero metrics."""
        engine = BacktestEngine()
        result = engine.run([])
        assert result.days == 0
        assert result.equity_curve == []
        assert result.metrics["total_trades"] == 0

    def test_equity_curve_entry_keys(self):
        """Each equity curve entry must have required keys."""
        engine = BacktestEngine()
        history = generate_synthetic_history(days=5, seed=42)
        result = engine.run(history)
        for entry in result.equity_curve:
            for key in ["date", "total_capital", "deployed", "cash", "pnl_pct"]:
                assert key in entry, f"Missing equity curve key: {key}"

    def test_capital_never_negative(self):
        """Capital must never go negative."""
        engine = BacktestEngine()
        history = generate_synthetic_history(days=30, seed=42)
        result = engine.run(history, initial_capital=100_000.0)
        for entry in result.equity_curve:
            assert entry["total_capital"] > 0, f"Negative capital on {entry['date']}"

    def test_policy_version_stored(self):
        """policy_version must be stored in the result."""
        engine = BacktestEngine()
        history = generate_synthetic_history(days=5, seed=42)
        result = engine.run(history, policy_version="v1.0-test")
        assert result.policy_version == "v1.0-test"
