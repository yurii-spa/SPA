"""tests/test_t2_concentration_alert.py — 20 unit tests for the T2 aggregate
concentration early-warning monitor (MP-1263).

Module under test: spa_core/risk/concentration_monitor.py

Coverage:
  * threshold classification (NORMAL/ADVISORY/WARNING/BREACH) incl. boundaries
  * headroom math
  * T2 aggregate computation from USD docs, raw maps, and size_pct lists
  * unknown-protocol → T2 conservative default (matches the audit's 47.14%)
  * the WARNING Telegram message string (exact spec wording)
  * send_alert tiering: ADVISORY log-only, WARNING/BREACH send, NORMAL silent
  * run() end-to-end with a temp data dir; Telegram sender always MOCKED
  * fail-safe behaviour when positions file is missing

stdlib only (unittest); no real network calls. Telegram is always patched.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.risk.concentration_monitor import (  # noqa: E402
    ConcentrationStatus,
    T2ConcentrationAlert,
)

# The real network send, patched in every test that exercises alerting.
_SENDER = "spa_core.alerts.telegram_client.send_message"


def _doc(positions: dict, capital: float = 100_000.0) -> dict:
    """Build a current_positions.json-shaped doc."""
    return {
        "capital_usd": capital,
        "generated_at": "2026-06-20T21:23:06+00:00",
        "positions": positions,
    }


class TestThresholds(unittest.TestCase):
    """Threshold classification and boundary behaviour."""

    def setUp(self) -> None:
        self.alert = T2ConcentrationAlert()

    def test_thresholds_have_expected_values(self) -> None:
        self.assertEqual(self.alert.GRADUAL_WARN, 0.42)
        self.assertEqual(self.alert.WARN_THRESHOLD, 0.45)
        self.assertEqual(self.alert.HARD_CAP, 0.50)

    def test_normal_below_gradual(self) -> None:
        # Single T2 protocol at 30% of capital → NORMAL.
        doc = _doc({"yearn_v3": 30_000.0, "aave_v3": 70_000.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.NORMAL
        )

    def test_advisory_at_42_boundary(self) -> None:
        doc = _doc({"yearn_v3": 42_000.0, "aave_v3": 58_000.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.ADVISORY
        )

    def test_advisory_between_42_and_45(self) -> None:
        doc = _doc({"yearn_v3": 43_500.0, "aave_v3": 56_500.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.ADVISORY
        )

    def test_warning_at_45_boundary(self) -> None:
        doc = _doc({"yearn_v3": 45_000.0, "aave_v3": 55_000.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.WARNING
        )

    def test_warning_at_4714(self) -> None:
        # The compliance-report figure: 47.14% → WARNING.
        doc = _doc({"yearn_v3": 47_140.0, "aave_v3": 52_860.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.WARNING
        )

    def test_breach_at_50_boundary(self) -> None:
        doc = _doc({"yearn_v3": 50_000.0, "aave_v3": 50_000.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.BREACH
        )

    def test_breach_above_50(self) -> None:
        doc = _doc({"yearn_v3": 55_000.0, "aave_v3": 45_000.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.BREACH
        )

    def test_status_severity_ordering(self) -> None:
        self.assertLess(
            ConcentrationStatus.NORMAL.severity, ConcentrationStatus.ADVISORY.severity
        )
        self.assertLess(
            ConcentrationStatus.ADVISORY.severity, ConcentrationStatus.WARNING.severity
        )
        self.assertLess(
            ConcentrationStatus.WARNING.severity, ConcentrationStatus.BREACH.severity
        )


class TestHeadroomAndCompute(unittest.TestCase):
    """Headroom math and T2 aggregate computation across input shapes."""

    def setUp(self) -> None:
        self.alert = T2ConcentrationAlert()

    def test_headroom_at_4714(self) -> None:
        doc = _doc({"yearn_v3": 47_140.0, "aave_v3": 52_860.0})
        self.assertAlmostEqual(self.alert.get_t2_headroom(doc), 0.0286, places=4)

    def test_headroom_never_negative_past_cap(self) -> None:
        doc = _doc({"yearn_v3": 60_000.0, "aave_v3": 40_000.0})
        self.assertEqual(self.alert.get_t2_headroom(doc), 0.0)

    def test_compute_t2_total_usd_mode(self) -> None:
        doc = _doc({"yearn_v3": 20_000.0, "euler_v2": 25_000.0, "aave_v3": 55_000.0})
        frac, cap, t2_usd, protos = self.alert.compute_t2_total(doc)
        self.assertAlmostEqual(frac, 0.45, places=6)
        self.assertEqual(cap, 100_000.0)
        self.assertAlmostEqual(t2_usd, 45_000.0, places=2)
        self.assertEqual(protos, ["euler_v2", "yearn_v3"])

    def test_raw_mapping_without_capital_uses_deployed(self) -> None:
        # No capital_usd key → total = deployed sum.
        frac, cap, _usd, _p = self.alert.compute_t2_total(
            {"yearn_v3": 30_000.0, "aave_v3": 30_000.0}
        )
        self.assertAlmostEqual(frac, 0.5, places=6)
        self.assertEqual(cap, 60_000.0)

    def test_unknown_protocol_defaults_to_t2(self) -> None:
        # An unregistered protocol must count toward T2 (conservative).
        doc = _doc({"totally_unknown_xyz": 46_000.0, "aave_v3": 54_000.0})
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.WARNING
        )

    def test_size_pct_list_form(self) -> None:
        # Spec-shaped list with explicit tier + size_pct fractions.
        positions = [
            {"protocol": "yearn_v3", "tier": "T2", "size_pct": 0.25},
            {"protocol": "euler_v2", "tier": "T2", "size_pct": 0.22},
            {"protocol": "aave_v3", "tier": "T1", "size_pct": 0.53},
        ]
        frac, _cap, _usd, _p = self.alert.compute_t2_total(positions)
        self.assertAlmostEqual(frac, 0.47, places=6)
        self.assertEqual(
            self.alert.check_t2_concentration(positions),
            ConcentrationStatus.WARNING,
        )

    def test_empty_positions_is_normal(self) -> None:
        doc = _doc({}, capital=100_000.0)
        self.assertEqual(
            self.alert.check_t2_concentration(doc), ConcentrationStatus.NORMAL
        )
        self.assertEqual(self.alert.get_t2_headroom(doc), 0.50)


class TestMessageAndAlerting(unittest.TestCase):
    """Message wording and send_alert tiering (Telegram mocked)."""

    def setUp(self) -> None:
        self.alert = T2ConcentrationAlert()

    def test_warning_message_matches_spec(self) -> None:
        doc = _doc({"yearn_v3": 47_140.0, "aave_v3": 52_860.0})
        report = self.alert.build_report(doc)
        self.assertIn("⚠️ T2 CONCENTRATION: 47.14%/50% cap", report.message)
        self.assertIn("2.86% headroom remaining", report.message)
        self.assertIn("New T2 positions blocked", report.message)

    def test_breach_sets_block_flag(self) -> None:
        doc = _doc({"yearn_v3": 52_000.0, "aave_v3": 48_000.0})
        report = self.alert.build_report(doc)
        self.assertTrue(report.block_new_t2)
        self.assertIn("BREACH", report.message)

    def test_warning_triggers_telegram(self) -> None:
        doc = _doc({"yearn_v3": 47_140.0, "aave_v3": 52_860.0})
        report = self.alert.build_report(doc)
        with patch(_SENDER, return_value=True) as send:
            sent = self.alert.send_alert(report)
        self.assertTrue(sent)
        send.assert_called_once()
        # HTML parse_mode (protocol names contain underscores).
        self.assertEqual(send.call_args.kwargs.get("parse_mode"), "HTML")

    def test_advisory_is_log_only_no_telegram(self) -> None:
        doc = _doc({"yearn_v3": 43_000.0, "aave_v3": 57_000.0})
        report = self.alert.build_report(doc)
        with patch(_SENDER, return_value=True) as send:
            sent = self.alert.send_alert(report)
        self.assertFalse(sent)
        send.assert_not_called()

    def test_normal_sends_nothing(self) -> None:
        doc = _doc({"yearn_v3": 10_000.0, "aave_v3": 90_000.0})
        report = self.alert.build_report(doc)
        with patch(_SENDER, return_value=True) as send:
            sent = self.alert.send_alert(report)
        self.assertFalse(sent)
        send.assert_not_called()


class TestRunEndToEnd(unittest.TestCase):
    """run() against a temp data dir; sender always mocked."""

    def test_run_writes_and_alerts_on_warning(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ddir = Path(d)
            (ddir / "current_positions.json").write_text(
                json.dumps(_doc({"yearn_v3": 47_140.0, "aave_v3": 52_860.0})),
                encoding="utf-8",
            )
            with patch(_SENDER, return_value=True) as send:
                out = T2ConcentrationAlert(data_dir=ddir).run(
                    data_dir=ddir, send_telegram=True, write=True
                )
            self.assertEqual(out["status"], "WARNING")
            self.assertAlmostEqual(out["t2_total_pct"], 47.14, places=2)
            self.assertTrue(out["telegram_sent"])
            self.assertTrue(out["available"])
            send.assert_called_once()
            # File written atomically.
            written = json.loads(
                (ddir / "t2_concentration_alert.json").read_text(encoding="utf-8")
            )
            self.assertEqual(written["status"], "WARNING")

    def test_run_missing_file_is_failsafe(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(_SENDER, return_value=True) as send:
                out = T2ConcentrationAlert(data_dir=d).run(
                    data_dir=d, send_telegram=True, write=False
                )
            self.assertFalse(out["available"])
            self.assertEqual(out["status"], "NORMAL")
            self.assertFalse(out["telegram_sent"])
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
