"""
Tests for the email alerts module — build functions and send_alert.
"""

import sys
import os
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from alerts.email_sender import build_risk_alert_email, send_alert


# ─── Sample data ──────────────────────────────────────────────────────────────

_SAMPLE_ALERTS = [
    {"severity": "critical", "protocol": "aave-v3-usdc-ethereum", "message": "TVL dropped 50%"},
    {"severity": "warning",  "protocol": "maple-usdc-ethereum",   "message": "APY below threshold"},
]

_SAMPLE_PORTFOLIO = {
    "total_capital_usd": 100_000.0,
    "cash_usd": 5_000.0,
    "invested_usd": 95_000.0,
    "total_pnl_usd": 138.0,
    "total_pnl_pct": 0.138,
}


# ─── build_risk_alert_email tests ─────────────────────────────────────────────

class TestBuildRiskAlertEmail:

    def test_returns_3_tuple(self):
        """build_risk_alert_email() must return a (subject, html, text) 3-tuple."""
        result = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_subject_is_string(self):
        subject, html, text = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert isinstance(subject, str)
        assert len(subject) > 0

    def test_html_is_string(self):
        subject, html, text = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert isinstance(html, str)
        assert len(html) > 0

    def test_text_is_string(self):
        subject, html, text = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_subject_contains_alert_count(self):
        """Subject should mention the number of alerts."""
        subject, _, _ = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        count = len(_SAMPLE_ALERTS)
        assert str(count) in subject, f"Alert count {count} not found in subject: {subject}"

    def test_html_contains_spa_branding(self):
        """HTML should reference the SPA bot / agent name."""
        _, html, _ = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        # Check for any SPA reference
        assert "SPA" in html or "Smart Passive" in html

    def test_html_contains_protocol_names(self):
        """HTML should include the protocol names from alerts."""
        _, html, _ = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert "aave-v3-usdc-ethereum" in html
        assert "maple-usdc-ethereum" in html

    def test_text_contains_protocol_names(self):
        """Plain text body should include protocol names."""
        _, _, text = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert "aave-v3-usdc-ethereum" in text

    def test_html_is_valid_html(self):
        """HTML output should at least start with DOCTYPE or <html."""
        _, html, _ = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert html.strip().startswith("<!DOCTYPE html") or html.strip().startswith("<html")

    def test_empty_alerts_list_no_crash(self):
        """Empty alerts list → no crash, still returns 3-tuple."""
        result = build_risk_alert_email([], _SAMPLE_PORTFOLIO)
        assert len(result) == 3
        subject, html, text = result
        assert "0" in subject  # count should be 0

    def test_empty_portfolio_no_crash(self):
        """Empty portfolio dict → no crash."""
        result = build_risk_alert_email(_SAMPLE_ALERTS, {})
        assert len(result) == 3

    def test_html_contains_dashboard_link(self):
        """HTML should contain the dashboard URL."""
        _, html, _ = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert "github.io" in html or "dashboard" in html.lower()

    def test_text_contains_portfolio_value(self):
        """Plain text should reference the portfolio total value."""
        _, _, text = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        # $100,000.00 or similar
        assert "100,000" in text or "100000" in text

    def test_critical_severity_highlighted(self):
        """CRITICAL severity should appear prominently in the output."""
        _, html, text = build_risk_alert_email(_SAMPLE_ALERTS, _SAMPLE_PORTFOLIO)
        assert "CRITICAL" in html.upper() or "critical" in html.lower()

    def test_single_alert(self):
        """Single alert → subject says '1 alert'."""
        alerts = [{"severity": "critical", "protocol": "test", "message": "test msg"}]
        subject, _, _ = build_risk_alert_email(alerts, _SAMPLE_PORTFOLIO)
        assert "1" in subject


# ─── send_alert tests ─────────────────────────────────────────────────────────

class TestSendAlert:

    def test_returns_false_without_env_vars(self):
        """send_alert() with no env vars set must return False without raising."""
        # Ensure env vars are cleared
        for var in ["SPA_ALERT_EMAIL", "SPA_ALERT_PASSWORD", "SPA_NOTIFY_EMAIL"]:
            os.environ.pop(var, None)

        result = send_alert("Test Subject", "<p>HTML</p>", "Plain text")
        assert result is False

    def test_no_exception_without_env_vars(self):
        """send_alert() must never raise even with missing config."""
        for var in ["SPA_ALERT_EMAIL", "SPA_ALERT_PASSWORD", "SPA_NOTIFY_EMAIL"]:
            os.environ.pop(var, None)

        # Should not raise
        try:
            send_alert("Subject", "<p>Body</p>", "Plain body")
        except Exception as exc:
            pytest.fail(f"send_alert() raised unexpectedly: {exc}")

    def test_returns_bool(self):
        """send_alert() must always return a bool."""
        for var in ["SPA_ALERT_EMAIL", "SPA_ALERT_PASSWORD", "SPA_NOTIFY_EMAIL"]:
            os.environ.pop(var, None)

        result = send_alert("Subj", "<b>html</b>", "text")
        assert isinstance(result, bool)

    def test_empty_sender_returns_false(self):
        """Empty sender string → must return False."""
        os.environ["SPA_ALERT_EMAIL"] = ""
        os.environ["SPA_ALERT_PASSWORD"] = "password"
        try:
            result = send_alert("Subj", "<b>html</b>", "text")
            assert result is False
        finally:
            os.environ.pop("SPA_ALERT_EMAIL", None)
            os.environ.pop("SPA_ALERT_PASSWORD", None)

    def test_empty_password_returns_false(self):
        """Empty password string → must return False."""
        os.environ["SPA_ALERT_EMAIL"] = "test@example.com"
        os.environ["SPA_ALERT_PASSWORD"] = ""
        try:
            result = send_alert("Subj", "<b>html</b>", "text")
            assert result is False
        finally:
            os.environ.pop("SPA_ALERT_EMAIL", None)
            os.environ.pop("SPA_ALERT_PASSWORD", None)
