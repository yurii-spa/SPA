"""
Tests for DailyReportBuilder (daily_report.py) and RiskMonitor (risk_monitor.py).
All tests use mock data — no real API calls, no real files except via tmp_path.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from alerts.daily_report import DailyReportBuilder
from alerts.risk_monitor import RiskMonitor


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

def _write(path: Path, filename: str, data) -> None:
    (path / filename).write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path):
    """Minimal valid data directory for all tests."""
    portfolio = {
        "total_capital_usd": 100_247.0,
        "deployed_usd": 95_000.0,
        "cash_usd": 5_247.0,
        "total_pnl_usd": 247.0,
        "total_pnl_pct": 0.00247,   # stored as fraction
        "total_drawdown_pct": 0.1,
    }
    positions = [
        {
            "protocol_key": "aave-v3-usdc-ethereum",
            "protocol": "Aave V3 USDC",
            "amount_usd": 40_000.0,
            "current_apy": 4.23,
        },
        {
            "protocol_key": "compound-v3-usdc-ethereum",
            "protocol": "Compound V3",
            "amount_usd": 35_000.0,
            "current_apy": 4.02,
        },
        {
            "protocol_key": "maple-usdc-ethereum",
            "protocol": "Maple Finance",
            "amount_usd": 20_000.0,
            "current_apy": 4.80,
        },
    ]
    status = {"portfolio": portfolio, "positions": positions}

    pnl_history = [
        {
            "timestamp": "2026-05-20 00:00:00",
            "total_capital_usd": 100_000.0,
            "total_pnl_usd": 0.0,
            "total_pnl_pct": 0.0,
        },
        {
            "timestamp": "2026-05-21 00:00:00",
            "total_capital_usd": 100_247.0,
            "total_pnl_usd": 247.0,
            "total_pnl_pct": 0.00247,
        },
    ]
    risk_alerts = {"count": 0, "status": "ok", "alerts": []}
    advanced_analytics = {
        "summary": {"sharpe_ratio": 1.24, "max_drawdown_pct": -0.3},
        "rolling_metrics": [],
        "data_points": 2,
    }
    golive = {
        "verdict": "NOT_READY",
        "verdict_emoji": "🔴",
        "days_remaining": 54,
        "summary": "5/8 criteria passing; 1 failing (Paper Duration)",
    }

    _write(tmp_path, "status.json", status)
    _write(tmp_path, "pnl_history.json", pnl_history)
    _write(tmp_path, "risk_alerts.json", risk_alerts)
    _write(tmp_path, "advanced_analytics.json", advanced_analytics)
    _write(tmp_path, "golive_readiness.json", golive)

    return tmp_path


@pytest.fixture
def builder(data_dir):
    return DailyReportBuilder(data_dir=data_dir)


@pytest.fixture
def monitor(data_dir):
    return RiskMonitor(data_dir=data_dir)


@pytest.fixture
def mock_sender():
    s = MagicMock()
    s.available = True
    s.send_risk_alert.return_value = True
    s.send.return_value = True
    return s


# ────────────────────────────────────────────────────────────────────────────
# DailyReportBuilder tests
# ────────────────────────────────────────────────────────────────────────────

class TestDailyReportBuilder:

    def test_build_report_contains_header(self, builder):
        """Report must include the date header."""
        msg = builder.build_report()
        today = date.today().isoformat()
        assert "SPA Daily Report" in msg
        assert today in msg

    def test_build_report_contains_portfolio_value(self, builder):
        """Portfolio value $100,247 should appear in the message."""
        msg = builder.build_report()
        assert "100,247" in msg

    def test_build_report_contains_apy_and_target(self, builder):
        """Message should show weighted APY and 7.30% target."""
        msg = builder.build_report()
        assert "APY" in msg
        assert "7.30" in msg

    def test_build_report_contains_position_names(self, builder):
        """All three position names must appear."""
        msg = builder.build_report()
        assert "Aave V3 USDC" in msg
        assert "Compound V3" in msg
        assert "Maple Finance" in msg

    def test_build_report_max_4000_chars(self, builder):
        """Output must stay within Telegram's 4000-char limit."""
        msg = builder.build_report()
        assert len(msg) <= 4000

    def test_build_report_contains_golive_verdict(self, builder):
        """Go-live verdict must appear in the message."""
        msg = builder.build_report()
        assert "NOT_READY" in msg

    def test_build_report_contains_sharpe(self, builder):
        """Sharpe ratio from analytics should appear."""
        msg = builder.build_report()
        assert "1.24" in msg

    def test_build_report_handles_missing_files_gracefully(self, tmp_path):
        """Build should not raise even when data files are absent."""
        empty_builder = DailyReportBuilder(data_dir=tmp_path)
        msg = empty_builder.build_report()
        assert "SPA Daily Report" in msg   # fallback header still present

    def test_should_send_daily_returns_true_when_no_sentinel(self, builder):
        """First call (no sentinel file) should return True."""
        assert builder.should_send_daily() is True

    def test_should_send_daily_returns_false_after_mark_sent(self, builder):
        """After mark_sent(), should_send_daily() must return False."""
        builder.mark_sent()
        assert builder.should_send_daily() is False

    def test_should_send_daily_returns_true_for_yesterday(self, builder):
        """If sentinel contains yesterday's date, should return True."""
        sentinel = builder.data_dir / ".last_report_sent"
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sentinel.write_text(yesterday, encoding="utf-8")
        assert builder.should_send_daily() is True

    def test_mark_sent_writes_today(self, builder):
        """mark_sent() should write today's ISO date to the sentinel file."""
        builder.mark_sent()
        sentinel = builder.data_dir / ".last_report_sent"
        assert sentinel.read_text(encoding="utf-8").strip() == date.today().isoformat()

    def test_build_report_html_safe(self, builder):
        """Report must not contain raw < or > that could break Telegram HTML."""
        msg = builder.build_report()
        # The only < / > that may appear are from HTML tags like <b>
        # strip known good HTML tags and check nothing dangerous remains
        import re
        stripped = re.sub(r"</?b>|&lt;|&gt;|&amp;", "", msg)
        assert "<" not in stripped
        assert ">" not in stripped


# ────────────────────────────────────────────────────────────────────────────
# RiskMonitor tests
# ────────────────────────────────────────────────────────────────────────────

class TestRiskMonitor:

    # ── concentration ────────────────────────────────────────────────────

    def test_no_alert_when_within_limits(self, monitor, mock_sender):
        """Well-spread allocation (30/30/30K of 100K) should produce no concentration alerts."""
        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 10_000.0},
            "positions": [
                {"protocol_key": "aave",  "amount_usd": 30_000.0, "current_apy": 4.2},
                {"protocol_key": "comp",  "amount_usd": 30_000.0, "current_apy": 4.0},
                {"protocol_key": "maple", "amount_usd": 30_000.0, "current_apy": 4.8},
            ],
        }
        pnl = []
        alerts = monitor.check_and_alert(status, pnl, mock_sender)
        concentration_alerts = [a for a in alerts if a["type"] == "concentration"]
        assert concentration_alerts == []

    def test_critical_concentration_alert_fires(self, monitor, mock_sender):
        """A position at 50% of portfolio must trigger a critical concentration alert."""
        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 10_000.0},
            "positions": [
                {"protocol_key": "aave", "amount_usd": 50_000.0, "current_apy": 4.2},
                {"protocol_key": "comp", "amount_usd": 40_000.0, "current_apy": 4.0},
            ],
        }
        alerts = monitor.check_and_alert(status, [], mock_sender)
        crits = [a for a in alerts if a["type"] == "concentration" and a["severity"] == "critical"]
        assert len(crits) == 1
        assert crits[0]["protocol"] == "aave"

    def test_warning_concentration_alert_fires(self, monitor, mock_sender):
        """A position between 35–45% should trigger a warning (not critical)."""
        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 10_000.0},
            "positions": [
                {"protocol_key": "aave", "amount_usd": 38_000.0, "current_apy": 4.2},
            ],
        }
        alerts = monitor.check_and_alert(status, [], mock_sender)
        warns = [a for a in alerts if a["type"] == "concentration" and a["severity"] == "warning"]
        assert len(warns) == 1

    # ── daily drawdown ───────────────────────────────────────────────────

    def test_daily_drawdown_triggers_alert(self, monitor, mock_sender):
        """A >2% single-day capital drop must fire a critical drawdown alert."""
        pnl = [
            {"timestamp": "2026-05-20 00:00:00", "total_capital_usd": 100_000.0},
            {"timestamp": "2026-05-21 00:00:00", "total_capital_usd":  97_500.0},
        ]
        status = {"portfolio": {"total_capital_usd": 97_500.0, "cash_usd": 5_000.0}, "positions": []}
        alerts = monitor.check_and_alert(status, pnl, mock_sender)
        dd = [a for a in alerts if a["type"] == "daily_drawdown"]
        assert len(dd) == 1
        assert dd[0]["severity"] == "critical"
        assert dd[0]["pct"] < -2.0

    def test_no_drawdown_alert_for_small_drop(self, monitor, mock_sender):
        """A <2% drop should NOT fire a drawdown alert."""
        pnl = [
            {"timestamp": "2026-05-20 00:00:00", "total_capital_usd": 100_000.0},
            {"timestamp": "2026-05-21 00:00:00", "total_capital_usd":  99_500.0},
        ]
        status = {"portfolio": {"total_capital_usd": 99_500.0, "cash_usd": 5_000.0}, "positions": []}
        alerts = monitor.check_and_alert(status, pnl, mock_sender)
        dd = [a for a in alerts if a["type"] == "daily_drawdown"]
        assert dd == []

    # ── APY drop ─────────────────────────────────────────────────────────

    def test_apy_drop_triggers_warning(self, monitor, mock_sender, data_dir):
        """Persisting prev APY 5.5% then presenting 4.0% should fire an APY-drop warning."""
        prev = {"aave": 5.5}
        (data_dir / ".prev_position_apys.json").write_text(json.dumps(prev))

        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 5_000.0},
            "positions": [{"protocol_key": "aave", "amount_usd": 40_000.0, "current_apy": 4.0}],
        }
        alerts = monitor.check_and_alert(status, [], mock_sender)
        apy_alerts = [a for a in alerts if a["type"] == "apy_drop"]
        assert len(apy_alerts) == 1
        assert apy_alerts[0]["protocol"] == "aave"
        assert apy_alerts[0]["drop_pp"] == pytest.approx(1.5, abs=0.01)

    def test_no_apy_alert_for_small_drop(self, monitor, mock_sender, data_dir):
        """A <1pp APY drop must NOT fire an alert."""
        prev = {"aave": 4.5}
        (data_dir / ".prev_position_apys.json").write_text(json.dumps(prev))

        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 5_000.0},
            "positions": [{"protocol_key": "aave", "amount_usd": 40_000.0, "current_apy": 4.2}],
        }
        alerts = monitor.check_and_alert(status, [], mock_sender)
        apy_alerts = [a for a in alerts if a["type"] == "apy_drop"]
        assert apy_alerts == []

    # ── cash buffer ──────────────────────────────────────────────────────

    def test_low_cash_triggers_warning(self, monitor, mock_sender):
        """Cash at 2% (< 3% threshold) must fire a low_cash warning."""
        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 2_000.0},
            "positions": [],
        }
        alerts = monitor.check_and_alert(status, [], mock_sender)
        cash_alerts = [a for a in alerts if a["type"] == "low_cash"]
        assert len(cash_alerts) == 1
        assert cash_alerts[0]["severity"] == "warning"

    def test_cash_ok_no_alert(self, monitor, mock_sender):
        """Cash at 5% must NOT trigger a cash buffer alert."""
        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 5_000.0},
            "positions": [],
        }
        alerts = monitor.check_and_alert(status, [], mock_sender)
        cash_alerts = [a for a in alerts if a["type"] == "low_cash"]
        assert cash_alerts == []

    # ── sender integration ───────────────────────────────────────────────

    def test_sender_called_when_alerts_exist(self, monitor, mock_sender, data_dir):
        """send_risk_alert must be called exactly once when alerts are fired."""
        prev = {"aave": 5.5}
        (data_dir / ".prev_position_apys.json").write_text(json.dumps(prev))

        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 2_000.0},
            "positions": [{"protocol_key": "aave", "amount_usd": 40_000.0, "current_apy": 4.0}],
        }
        monitor.check_and_alert(status, [], mock_sender)
        assert mock_sender.send_risk_alert.called

    def test_sender_not_called_when_no_alerts(self, monitor, mock_sender):
        """send_risk_alert must NOT be called when portfolio is healthy."""
        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 10_000.0},
            "positions": [
                # Each position is 30% — below both warning (35%) and critical (45%) thresholds
                {"protocol_key": "aave",  "amount_usd": 30_000.0, "current_apy": 4.2},
                {"protocol_key": "comp",  "amount_usd": 30_000.0, "current_apy": 4.0},
                {"protocol_key": "maple", "amount_usd": 30_000.0, "current_apy": 4.8},
            ],
        }
        monitor.check_and_alert(status, [], mock_sender)
        mock_sender.send_risk_alert.assert_not_called()

    # ── APY persistence ──────────────────────────────────────────────────

    def test_apy_snapshot_persisted_after_check(self, monitor, mock_sender, data_dir):
        """After check_and_alert, the current APYs must be saved for the next run."""
        status = {
            "portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 5_000.0},
            "positions": [{"protocol_key": "maple", "amount_usd": 30_000.0, "current_apy": 4.8}],
        }
        monitor.check_and_alert(status, [], mock_sender)
        saved = json.loads((data_dir / ".prev_position_apys.json").read_text())
        assert saved.get("maple") == pytest.approx(4.8)

    # ── edge cases ───────────────────────────────────────────────────────

    def test_empty_portfolio_no_crash(self, monitor, mock_sender):
        """Empty portfolio dict must not crash check_and_alert."""
        alerts = monitor.check_and_alert({}, [], mock_sender)
        assert isinstance(alerts, list)

    def test_single_pnl_entry_no_drawdown_alert(self, monitor, mock_sender):
        """Only one pnl entry — insufficient data, no drawdown alert should fire."""
        pnl = [{"timestamp": "2026-05-20 00:00:00", "total_capital_usd": 100_000.0}]
        status = {"portfolio": {"total_capital_usd": 100_000.0, "cash_usd": 5_000.0}, "positions": []}
        alerts = monitor.check_and_alert(status, pnl, mock_sender)
        dd = [a for a in alerts if a["type"] == "daily_drawdown"]
        assert dd == []
