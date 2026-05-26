"""
Tests for the go-live readiness checker.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from golive.checklist import (
    check_paper_duration,
    check_pnl_positive,
    check_no_critical_alerts,
    check_strategy_performance,
    check_drawdown_acceptable,
    check_diversification,
    check_data_freshness,
    run_full_check,
    _PASS, _FAIL, _WARN, _PENDING,
    MIN_PAPER_DAYS, PAPER_START_DATE,
)


# ─── check_paper_duration ─────────────────────────────────────────────────────

class TestCheckPaperDuration:
    """
    Note: check_paper_duration() uses today's real date relative to PAPER_START_DATE.
    We test the behaviour based on how many days have elapsed since 2026-05-20.
    """

    def test_returns_dict_with_required_keys(self):
        result = check_paper_duration()
        for key in ["name", "status", "value", "threshold", "note"]:
            assert key in result

    def test_value_is_elapsed_days(self):
        result = check_paper_duration()
        start = datetime.fromisoformat(PAPER_START_DATE).replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - start).days
        assert result["value"] == elapsed

    def test_status_is_valid(self):
        result = check_paper_duration()
        assert result["status"] in (_PASS, _FAIL, _PENDING)

    def test_threshold_is_min_paper_days(self):
        result = check_paper_duration()
        assert result["threshold"] == MIN_PAPER_DAYS


# ─── check_pnl_positive ──────────────────────────────────────────────────────

class TestCheckPnlPositive:

    def test_positive_pnl_gives_pass(self):
        portfolio = {"total_pnl_usd": 138.0, "total_capital_usd": 100_000.0}
        result = check_pnl_positive(portfolio)
        assert result["status"] == _PASS

    def test_negative_pnl_gives_fail(self):
        portfolio = {"total_pnl_usd": -500.0, "total_capital_usd": 100_000.0}
        result = check_pnl_positive(portfolio)
        assert result["status"] == _FAIL

    def test_zero_pnl_gives_warn(self):
        portfolio = {"total_pnl_usd": 0.0, "total_capital_usd": 100_000.0}
        result = check_pnl_positive(portfolio)
        assert result["status"] == _WARN

    def test_empty_portfolio_defaults_to_zero_warn(self):
        result = check_pnl_positive({})
        assert result["status"] == _WARN  # pnl=0 → WARN

    def test_returns_required_keys(self):
        result = check_pnl_positive({"total_pnl_usd": 50.0, "total_capital_usd": 10_000.0})
        for key in ["name", "status", "value", "threshold", "note"]:
            assert key in result


# ─── check_no_critical_alerts ────────────────────────────────────────────────

class TestCheckNoCriticalAlerts:

    def test_zero_alerts_gives_pass(self):
        risk_data = {"alerts": []}
        result = check_no_critical_alerts(risk_data)
        assert result["status"] == _PASS
        assert result["value"] == 0

    def test_critical_alert_gives_fail(self):
        risk_data = {"alerts": [
            {"severity": "CRITICAL", "message": "Protocol exploited", "protocol": "test"}
        ]}
        result = check_no_critical_alerts(risk_data)
        assert result["status"] == _FAIL
        assert result["value"] == 1

    def test_warning_only_alert_gives_pass(self):
        """Non-CRITICAL alerts should not trigger FAIL."""
        risk_data = {"alerts": [
            {"severity": "WARNING", "message": "APY dropped", "protocol": "test"}
        ]}
        result = check_no_critical_alerts(risk_data)
        assert result["status"] == _PASS

    def test_multiple_critical_alerts(self):
        risk_data = {"alerts": [
            {"severity": "CRITICAL", "message": "Alert 1"},
            {"severity": "CRITICAL", "message": "Alert 2"},
        ]}
        result = check_no_critical_alerts(risk_data)
        assert result["status"] == _FAIL
        assert result["value"] == 2

    def test_empty_risk_data(self):
        result = check_no_critical_alerts({})
        assert result["status"] == _PASS


# ─── check_strategy_performance ──────────────────────────────────────────────

class TestCheckStrategyPerformance:

    def test_high_sharpe_gives_pass(self):
        backtest_data = {"metrics": {"sharpe_ratio": 2.0}}
        result = check_strategy_performance(backtest_data)
        assert result["status"] == _PASS

    def test_sharpe_exactly_one_gives_pass(self):
        backtest_data = {"metrics": {"sharpe_ratio": 1.0}}
        result = check_strategy_performance(backtest_data)
        assert result["status"] == _PASS

    def test_low_sharpe_gives_fail(self):
        backtest_data = {"metrics": {"sharpe_ratio": 0.3}}
        result = check_strategy_performance(backtest_data)
        assert result["status"] == _FAIL

    def test_marginal_sharpe_gives_warn(self):
        """Sharpe between 0.5 and 1.0 should give WARN."""
        backtest_data = {"metrics": {"sharpe_ratio": 0.7}}
        result = check_strategy_performance(backtest_data)
        assert result["status"] == _WARN

    def test_missing_sharpe_gives_warn(self):
        """Missing backtest data → WARN (not crash)."""
        result = check_strategy_performance({})
        assert result["status"] == _WARN

    def test_none_sharpe_gives_warn(self):
        backtest_data = {"metrics": {"sharpe_ratio": None}}
        result = check_strategy_performance(backtest_data)
        assert result["status"] == _WARN


# ─── check_drawdown_acceptable ───────────────────────────────────────────────

class TestCheckDrawdownAcceptable:

    def test_zero_drawdown_passes(self):
        portfolio = {"total_drawdown_pct": 0.0}
        result = check_drawdown_acceptable(portfolio)
        assert result["status"] == _PASS

    def test_small_drawdown_passes(self):
        portfolio = {"total_drawdown_pct": 0.02}
        result = check_drawdown_acceptable(portfolio)
        assert result["status"] == _PASS

    def test_elevated_drawdown_warns(self):
        portfolio = {"total_drawdown_pct": 0.035}
        result = check_drawdown_acceptable(portfolio)
        assert result["status"] == _WARN

    def test_high_drawdown_fails(self):
        portfolio = {"total_drawdown_pct": 0.05}
        result = check_drawdown_acceptable(portfolio)
        assert result["status"] == _FAIL


# ─── check_diversification ───────────────────────────────────────────────────

class TestCheckDiversification:

    def test_well_diversified_passes(self):
        positions = [
            {"protocol_key": "aave-v3-usdc-ethereum", "amount_usd": 40_000},
            {"protocol_key": "compound-v3-usdc-ethereum", "amount_usd": 35_000},
            {"protocol_key": "maple-usdc-ethereum", "amount_usd": 25_000},
        ]
        result = check_diversification(positions)
        assert result["status"] == _PASS

    def test_concentration_above_45_fails(self):
        positions = [
            {"protocol_key": "aave-v3-usdc-ethereum", "amount_usd": 80_000},
            {"protocol_key": "compound-v3-usdc-ethereum", "amount_usd": 20_000},
        ]
        result = check_diversification(positions)
        assert result["status"] == _FAIL

    def test_single_protocol_warns(self):
        positions = [
            {"protocol_key": "aave-v3-usdc-ethereum", "amount_usd": 40_000},
        ]
        result = check_diversification(positions)
        # Single protocol at 100% concentration → FAIL (> 45%)
        # OR WARN if n_protocols < 2 but max_conc checked first
        assert result["status"] in (_FAIL, _WARN)

    def test_empty_positions(self):
        result = check_diversification([])
        assert result["status"] in (_WARN, _PASS)  # 0 protocols may WARN


# ─── check_data_freshness ────────────────────────────────────────────────────

class TestCheckDataFreshness:

    def test_fresh_data_passes(self):
        """Data from 1 hour ago should PASS."""
        ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = check_data_freshness(ts)
        assert result["status"] == _PASS

    def test_stale_data_warns(self):
        """Data from 8 hours ago should WARN."""
        ts = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        result = check_data_freshness(ts)
        assert result["status"] == _WARN

    def test_very_old_data_fails(self):
        """Data from 24 hours ago should FAIL."""
        ts = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        result = check_data_freshness(ts)
        assert result["status"] == _FAIL

    def test_bad_timestamp_warns(self):
        """Unparseable timestamp → WARN, not crash."""
        result = check_data_freshness("not-a-timestamp")
        assert result["status"] == _WARN


# ─── run_full_check ──────────────────────────────────────────────────────────

class TestRunFullCheck:

    def test_does_not_crash_with_temp_dir(self, temp_data_dir):
        """run_full_check() must complete without raising an exception."""
        result = run_full_check(temp_data_dir)
        assert isinstance(result, dict)

    def test_returns_verdict_key(self, temp_data_dir):
        """Result must have 'verdict' key."""
        result = run_full_check(temp_data_dir)
        assert "verdict" in result

    def test_verdict_is_valid_value(self, temp_data_dir):
        """Verdict must be one of the known values."""
        result = run_full_check(temp_data_dir)
        assert result["verdict"] in ("READY", "ALMOST_READY", "NOT_READY", "BLOCKED")

    def test_returns_criteria_list(self, temp_data_dir):
        """Result must have 'criteria' as a non-empty list."""
        result = run_full_check(temp_data_dir)
        assert "criteria" in result
        assert isinstance(result["criteria"], list)
        assert len(result["criteria"]) == 12  # 12 criteria: paper duration, PnL, alerts, sharpe, policy, drawdown, diversification, freshness, wallet, tournament, APY gap, agent stability

    def test_returns_required_keys(self, temp_data_dir):
        """All required top-level keys must be present."""
        result = run_full_check(temp_data_dir)
        for key in [
            "generated_at", "verdict", "verdict_emoji", "days_remaining",
            "summary", "criteria", "recommendation", "owner_action_required"
        ]:
            assert key in result, f"Missing key: {key}"

    def test_no_crash_with_empty_dir(self, tmp_path):
        """run_full_check() must not crash even with no JSON files present."""
        result = run_full_check(str(tmp_path))
        assert "verdict" in result

    def test_criteria_all_have_required_fields(self, temp_data_dir):
        """Each criterion dict must have name, status, value, threshold, note."""
        result = run_full_check(temp_data_dir)
        for criterion in result["criteria"]:
            for field in ["name", "status", "value", "threshold", "note"]:
                assert field in criterion, f"Missing field '{field}' in criterion: {criterion}"
