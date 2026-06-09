"""
test_alerts.py — SPA-V390 Email Alert System tests.

Pure stdlib unittest (no pytest dependency). Covers:
  * alert_config env fallback / dry-run behaviour
  * alert_rules deterministic rule evaluation (incl. real data/*.json)
  * alert_dispatcher dry-run logging, ring buffer cap, SMTP send path
  * run_alerts CLI summary line

Run:
  python3 -m unittest spa_core.tests.test_alerts -v

NOTE: the previous pytest-based tests for DailyReportBuilder / RiskMonitor that
lived in this file are preserved at spa_core/tests/test_alerts_daily_report.py.bak
(this environment has no pytest, so they were not runnable here).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Make the project root importable as `spa_core` package.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.alerts.alert_config import (  # noqa: E402
    AlertConfig,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
)
from spa_core.alerts.alert_dispatcher import (  # noqa: E402
    RING_BUFFER_MAX,
    dispatch_alerts,
)
from spa_core.alerts.alert_rules import (  # noqa: E402
    Alert,
    check_alert_conditions,
)

_DATA = _PROJECT_ROOT / "data"


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _golive(criteria) -> dict:
    return {"verdict": "NOT_READY", "criteria": criteria}


def _crit(cid, name, weight, status, detail="") -> dict:
    return {
        "id": cid,
        "name": name,
        "weight": weight,
        "status": status,
        "detail": detail,
    }


# ---------------------------------------------------------------------------- #
# AlertConfig
# ---------------------------------------------------------------------------- #
class TestAlertConfig(unittest.TestCase):
    def test_alert_config_env_fallback(self):
        """No SMTP env vars → dry_run=True automatically."""
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = AlertConfig.from_env()
        self.assertTrue(cfg.dry_run)
        self.assertFalse(cfg.smtp_configured)
        self.assertEqual(cfg.email_to, [])

    def test_alert_config_full_env_enables_smtp(self):
        env = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "465",
            "SMTP_USER": "bot@example.com",
            "SMTP_PASS": "secret",
            "ALERT_EMAIL_TO": "a@x.com, b@y.com",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = AlertConfig.from_env()
        self.assertFalse(cfg.dry_run)
        self.assertTrue(cfg.smtp_configured)
        self.assertEqual(cfg.email_to, ["a@x.com", "b@y.com"])
        self.assertEqual(cfg.smtp_port, 465)

    def test_alert_config_partial_env_stays_dry(self):
        """Host present but no recipients → still dry_run."""
        env = {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "u", "SMTP_PASS": "p"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = AlertConfig.from_env()
        self.assertTrue(cfg.dry_run)

    def test_alert_config_bad_port_defaults(self):
        env = {
            "SMTP_HOST": "h",
            "SMTP_USER": "u",
            "SMTP_PASS": "p",
            "ALERT_EMAIL_TO": "a@x.com",
            "SMTP_PORT": "not-a-number",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = AlertConfig.from_env()
        self.assertEqual(cfg.smtp_port, 465)

    def test_redacted_masks_password(self):
        cfg = AlertConfig(smtp_pass="topsecret")
        self.assertEqual(cfg.redacted()["smtp_pass"], "***")
        self.assertNotIn("topsecret", json.dumps(cfg.redacted()))

    def test_should_email_threshold(self):
        cfg = AlertConfig(min_email_severity=SEVERITY_WARNING)
        self.assertTrue(cfg.should_email(SEVERITY_CRITICAL))
        self.assertTrue(cfg.should_email(SEVERITY_WARNING))
        self.assertFalse(cfg.should_email(SEVERITY_INFO))


# ---------------------------------------------------------------------------- #
# alert_rules
# ---------------------------------------------------------------------------- #
class TestAlertRules(unittest.TestCase):
    def setUp(self):
        import tempfile

        d = tempfile.mkdtemp(prefix="spa_alerts_test_")
        self.tmp = Path(d)
        self.addCleanup(self._rmtree, d)

    @staticmethod
    def _rmtree(d):
        import shutil

        shutil.rmtree(d, ignore_errors=True)

    def _paths(self, golive=None, orch=None, portfolio=None, write_portfolio=True):
        gp = self.tmp / "golive.json"
        op = self.tmp / "orch.json"
        pp = self.tmp / "portfolio.json"
        _write_json(gp, golive if golive is not None else _golive([]))
        _write_json(op, orch if orch is not None else {"overall_health": {"grade": "A"}})
        if write_portfolio:
            _write_json(pp, portfolio if portfolio is not None else {"positions": []})
        return gp, op, pp

    def test_returns_list_of_alert(self):
        gp, op, pp = self._paths()
        out = check_alert_conditions(gp, op, pp)
        self.assertIsInstance(out, list)
        for a in out:
            self.assertIsInstance(a, Alert)

    def test_critical_on_blocker_fail(self):
        golive = _golive(
            [_crit("C001", "Paper duration", "blocker", "FAIL", "20/30 days")]
        )
        gp, op, pp = self._paths(golive=golive)
        out = check_alert_conditions(gp, op, pp)
        crits = [a for a in out if a.severity == SEVERITY_CRITICAL]
        self.assertEqual(len(crits), 1)
        self.assertIn("C001", crits[0].title)

    def test_info_when_all_blockers_pass(self):
        golive = _golive(
            [
                _crit("C002", "Win rate", "blocker", "PASS"),
                _crit("C008", "Health", "blocker", "PASS"),
            ]
        )
        gp, op, pp = self._paths(golive=golive)
        out = check_alert_conditions(gp, op, pp)
        infos = [a for a in out if a.severity == SEVERITY_INFO]
        self.assertEqual(len(infos), 1)

    def test_no_info_when_no_blockers(self):
        golive = _golive([_crit("C005", "Trading days", "high", "FAIL")])
        gp, op, pp = self._paths(golive=golive)
        out = check_alert_conditions(gp, op, pp)
        self.assertFalse([a for a in out if a.severity == SEVERITY_INFO])

    def test_warning_on_low_health_grade(self):
        gp, op, pp = self._paths(orch={"overall_health": {"grade": "D"}})
        out = check_alert_conditions(gp, op, pp)
        warns = [a for a in out if a.severity == SEVERITY_WARNING and "grade" in a.title]
        self.assertEqual(len(warns), 1)

    def test_no_warning_on_grade_a(self):
        gp, op, pp = self._paths(orch={"summary": {"grade": "A"}})
        out = check_alert_conditions(gp, op, pp)
        self.assertFalse([a for a in out if "grade" in a.title])

    def test_warning_on_negative_sharpe(self):
        golive = _golive(
            [
                _crit(
                    "C004",
                    "Sharpe ratio computed",
                    "medium",
                    "WARN",
                    "Sharpe = -5.38 (negative)",
                )
            ]
        )
        gp, op, pp = self._paths(golive=golive)
        out = check_alert_conditions(gp, op, pp)
        warns = [a for a in out if "Sharpe" in a.title]
        self.assertEqual(len(warns), 1)

    def test_no_warning_on_acceptable_sharpe(self):
        golive = _golive(
            [_crit("C004", "Sharpe ratio", "medium", "PASS", "Sharpe = 1.20")]
        )
        gp, op, pp = self._paths(golive=golive)
        out = check_alert_conditions(gp, op, pp)
        self.assertFalse([a for a in out if "Sharpe" in a.title])

    def test_warning_on_high_drift_explicit_field(self):
        gp, op, pp = self._paths(portfolio={"drift_score": 0.25, "positions": []})
        out = check_alert_conditions(gp, op, pp)
        warns = [a for a in out if "drift" in a.title.lower()]
        self.assertEqual(len(warns), 1)

    def test_drift_computed_from_positions(self):
        portfolio = {
            "positions": [
                {"protocol": "a", "actual_weight": 0.40, "target_weight": 0.20},
                {"protocol": "b", "actual_weight": 0.10, "target_weight": 0.20},
            ]
        }
        gp, op, pp = self._paths(portfolio=portfolio)
        out = check_alert_conditions(gp, op, pp)
        warns = [a for a in out if "drift" in a.title.lower()]
        self.assertEqual(len(warns), 1)

    def test_no_drift_alert_when_on_target(self):
        portfolio = {
            "positions": [
                {"protocol": "a", "actual_weight": 0.20, "target_weight": 0.20},
            ]
        }
        gp, op, pp = self._paths(portfolio=portfolio)
        out = check_alert_conditions(gp, op, pp)
        self.assertFalse([a for a in out if "drift" in a.title.lower()])

    def test_missing_portfolio_file_no_crash(self):
        gp, op, pp = self._paths(write_portfolio=False)
        out = check_alert_conditions(gp, op, pp)
        self.assertIsInstance(out, list)
        self.assertFalse([a for a in out if "drift" in a.title.lower()])

    def test_severity_ordering_critical_first(self):
        golive = _golive(
            [
                _crit("C001", "Paper duration", "blocker", "FAIL"),
                _crit("C004", "Sharpe", "medium", "WARN", "Sharpe = -9.0"),
            ]
        )
        gp, op, pp = self._paths(golive=golive, orch={"overall_health": {"grade": "F"}})
        out = check_alert_conditions(gp, op, pp)
        self.assertEqual(out[0].severity, SEVERITY_CRITICAL)

    def test_missing_files_return_list(self):
        out = check_alert_conditions(
            self.tmp / "nope1.json",
            self.tmp / "nope2.json",
            self.tmp / "nope3.json",
        )
        self.assertIsInstance(out, list)

    def test_alert_rules_from_real_data(self):
        """Read the real data/*.json files; rules must return list[Alert]."""
        golive = _DATA / "golive_readiness.json"
        orch = _DATA / "adapter_orchestrator_status.json"
        portfolio = _DATA / "portfolio_state.json"
        if not golive.exists() or not orch.exists():
            self.skipTest("real data files not present")
        out = check_alert_conditions(golive, orch, portfolio)
        self.assertIsInstance(out, list)
        for a in out:
            self.assertIsInstance(a, Alert)
            self.assertIn(
                a.severity,
                (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO),
            )


# ---------------------------------------------------------------------------- #
# alert_dispatcher
# ---------------------------------------------------------------------------- #
class TestDispatcher(unittest.TestCase):
    def setUp(self):
        import tempfile

        d = tempfile.mkdtemp(prefix="spa_dispatch_test_")
        self.tmp = Path(d)
        self.log_path = self.tmp / "alert_log.json"
        self.addCleanup(self._rmtree, d)

    @staticmethod
    def _rmtree(d):
        import shutil

        shutil.rmtree(d, ignore_errors=True)

    def _alerts(self, n=1, severity=SEVERITY_WARNING):
        return [
            Alert(severity=severity, title=f"t{i}", body=f"b{i}") for i in range(n)
        ]

    def test_dry_run_dispatch(self):
        """dry_run=True → alert_log.json written, SMTP never called."""
        cfg = AlertConfig(dry_run=True)
        with mock.patch(
            "spa_core.alerts.alert_dispatcher.smtplib.SMTP_SSL"
        ) as smtp:
            result = dispatch_alerts(self._alerts(2), cfg, log_path=self.log_path)
        smtp.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertTrue(self.log_path.exists())
        data = json.loads(self.log_path.read_text())
        self.assertEqual(len(data["entries"]), 2)

    def test_ring_buffer_100(self):
        """Log never grows beyond RING_BUFFER_MAX (100) entries."""
        cfg = AlertConfig(dry_run=True)
        for _ in range(60):
            dispatch_alerts(self._alerts(5), cfg, log_path=self.log_path)
        data = json.loads(self.log_path.read_text())
        self.assertEqual(RING_BUFFER_MAX, 100)
        self.assertLessEqual(len(data["entries"]), 100)
        self.assertEqual(len(data["entries"]), 100)

    def test_ring_buffer_keeps_most_recent(self):
        cfg = AlertConfig(dry_run=True)
        dispatch_alerts(
            [Alert(severity=SEVERITY_INFO, title="OLD", body="x")],
            cfg,
            log_path=self.log_path,
        )
        for _ in range(110):
            dispatch_alerts(
                [Alert(severity=SEVERITY_INFO, title="NEW", body="y")],
                cfg,
                log_path=self.log_path,
            )
        data = json.loads(self.log_path.read_text())
        titles = {e["title"] for e in data["entries"]}
        self.assertNotIn("OLD", titles)
        self.assertEqual(len(data["entries"]), 100)

    def test_counts_in_result(self):
        cfg = AlertConfig(dry_run=True)
        alerts = [
            Alert(severity=SEVERITY_CRITICAL, title="c", body="b"),
            Alert(severity=SEVERITY_WARNING, title="w", body="b"),
            Alert(severity=SEVERITY_WARNING, title="w2", body="b"),
        ]
        result = dispatch_alerts(alerts, cfg, log_path=self.log_path)
        self.assertEqual(result["counts"]["CRITICAL"], 1)
        self.assertEqual(result["counts"]["WARNING"], 2)
        self.assertEqual(result["counts"]["INFO"], 0)
        self.assertEqual(result["total"], 3)

    def test_empty_alerts_no_log_write(self):
        cfg = AlertConfig(dry_run=True)
        result = dispatch_alerts([], cfg, log_path=self.log_path)
        self.assertEqual(result["total"], 0)
        self.assertFalse(self.log_path.exists())

    def test_smtp_send_path(self):
        """SMTP configured + not dry-run → SMTP_SSL used, marked sent."""
        cfg = AlertConfig(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user="bot@example.com",
            smtp_pass="secret",
            email_to=["dest@example.com"],
            dry_run=False,
        )
        with mock.patch(
            "spa_core.alerts.alert_dispatcher.smtplib.SMTP_SSL"
        ) as smtp_cls:
            instance = smtp_cls.return_value.__enter__.return_value
            result = dispatch_alerts(
                [Alert(severity=SEVERITY_CRITICAL, title="c", body="b")],
                cfg,
                log_path=self.log_path,
            )
        smtp_cls.assert_called_once()
        instance.login.assert_called_once_with("bot@example.com", "secret")
        instance.send_message.assert_called_once()
        self.assertTrue(result["sent"])
        self.assertEqual(result["sent_via"], "smtp")

    def test_smtp_failure_still_logs(self):
        cfg = AlertConfig(
            smtp_host="h",
            smtp_user="u",
            smtp_pass="p",
            email_to=["d@e.com"],
            dry_run=False,
        )
        with mock.patch(
            "spa_core.alerts.alert_dispatcher.smtplib.SMTP_SSL",
            side_effect=OSError("connection refused"),
        ):
            result = dispatch_alerts(
                [Alert(severity=SEVERITY_CRITICAL, title="c", body="b")],
                cfg,
                log_path=self.log_path,
            )
        self.assertFalse(result["sent"])
        self.assertIsNotNone(result["error"])
        self.assertTrue(self.log_path.exists())

    def test_info_only_not_emailed(self):
        """INFO below min_email_severity → no SMTP send even when configured."""
        cfg = AlertConfig(
            smtp_host="h",
            smtp_user="u",
            smtp_pass="p",
            email_to=["d@e.com"],
            dry_run=False,
            min_email_severity=SEVERITY_WARNING,
        )
        with mock.patch(
            "spa_core.alerts.alert_dispatcher.smtplib.SMTP_SSL"
        ) as smtp_cls:
            result = dispatch_alerts(
                [Alert(severity=SEVERITY_INFO, title="i", body="b")],
                cfg,
                log_path=self.log_path,
            )
        smtp_cls.assert_not_called()
        self.assertFalse(result["sent"])
        self.assertTrue(self.log_path.exists())

    def test_atomic_write_no_tmp_leftover(self):
        cfg = AlertConfig(dry_run=True)
        dispatch_alerts(self._alerts(1), cfg, log_path=self.log_path)
        leftovers = list(self.tmp.glob("*.tmp"))
        self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------- #
# run_alerts CLI
# ---------------------------------------------------------------------------- #
class TestRunAlertsCli(unittest.TestCase):
    def test_run_returns_summary_dict(self):
        from spa_core.alerts import run_alerts

        with mock.patch.dict(os.environ, {}, clear=True):
            result = run_alerts.run(dry_run=True, verbose=False)
        self.assertIn("counts", result)
        self.assertIn("total", result)
        self.assertTrue(result["dry_run"])

    def test_main_exit_code_zero_on_dry_run(self):
        from spa_core.alerts import run_alerts

        with mock.patch.dict(os.environ, {}, clear=True):
            code = run_alerts.main(["--dry-run"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
