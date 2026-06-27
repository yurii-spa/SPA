#!/usr/bin/env python3
"""
tests/test_morning_digest.py — MP-1493 (Sprint v11.09)

Unit tests for spa_core/alerts/morning_digest.py
25 tests, pure stdlib, offline, no Telegram network calls.

Groups:
    A. Module structure                      (4 tests)
    B. _get_golive_score                     (4 tests)
    C. _get_evidence_progress                (3 tests)
    D. _get_best_apy / _get_best_strategy    (4 tests)
    E. _get_pending_alerts                   (3 tests)
    F. compose()                             (4 tests)
    G. send() + save                         (3 tests)
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

# Patch telegram before import. The patch lives in sys.modules and would
# otherwise leak a MagicMock telegram_client into every test that runs after
# this module (e.g. test_protocol_report's send_protocol_report would see a
# send_message that always returns True). setUpModule/tearDownModule (honoured
# by both unittest and pytest) scope the patch to this module's run only, so
# the real telegram_client is restored afterwards.
_tg_patcher = unittest.mock.patch.dict(
    "sys.modules",
    {
        "spa_core.alerts.telegram_client": unittest.mock.MagicMock(
            send_message=unittest.mock.MagicMock(return_value=True),
        ),
    },
)


def setUpModule():
    """Start the sys.modules patch before this module's tests run."""
    _tg_patcher.start()


def tearDownModule():
    """Stop the patch so the real telegram_client is restored for the rest of
    the test session (prevents cross-module pollution)."""
    _tg_patcher.stop()


# Import the module under test with the patch active so module-level references
# resolve against the mock, then stop it; setUpModule re-applies it for the run.
_tg_patcher.start()
from spa_core.alerts.morning_digest import MorningDigest  # noqa: E402
_tg_patcher.stop()


def _make_digest(tmp_path: pathlib.Path) -> MorningDigest:
    return MorningDigest(base_dir=str(tmp_path))


def _write_json(tmp_path: pathlib.Path, rel_path: str, data) -> None:
    p = tmp_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


# ═══════════════════════════════════════════════════════════════════════════
# Group A — Module structure
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleStructure(unittest.TestCase):

    def test_A1_output_path_defined(self):
        self.assertIn("morning_digest", MorningDigest.OUTPUT_PATH)

    def test_A2_inherits_base_analytics(self):
        from spa_core.base import BaseAnalytics
        self.assertTrue(issubclass(MorningDigest, BaseAnalytics))

    def test_A3_to_dict_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            self.assertIsInstance(d.to_dict(), dict)

    def test_A4_default_data_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            data = d.to_dict()
            self.assertIn("last_sent", data)
            self.assertIn("last_digest", data)
            self.assertIn("send_count", data)


# ═══════════════════════════════════════════════════════════════════════════
# Group B — _get_golive_score
# ═══════════════════════════════════════════════════════════════════════════

class TestGetGoLiveScore(unittest.TestCase):

    def test_B1_returns_int(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            score = d._get_golive_score()
            self.assertIsInstance(score, int)

    def test_B2_zero_when_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            with unittest.mock.patch.dict("sys.modules", {"spa_core.analytics.golive_readiness_report": None}):
                score = d._get_golive_score()
            self.assertEqual(score, 0)

    def test_B3_reads_golive_status_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/golive_status.json", {"passed": 16, "total": 26})
            d = _make_digest(tp)
            with unittest.mock.patch.dict("sys.modules", {"spa_core.analytics.golive_readiness_report": None}):
                score = d._get_golive_score()
            # 16/26 * 100 ≈ 61
            self.assertGreater(score, 50)

    def test_B4_returns_100_when_all_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/golive_status.json", {"passed": 26, "total": 26})
            d = _make_digest(tp)
            with unittest.mock.patch.dict("sys.modules", {"spa_core.analytics.golive_readiness_report": None}):
                score = d._get_golive_score()
            self.assertEqual(score, 100)


# ═══════════════════════════════════════════════════════════════════════════
# Group C — _get_evidence_progress
# ═══════════════════════════════════════════════════════════════════════════

class TestGetEvidenceProgress(unittest.TestCase):

    def test_C1_returns_dict_with_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            result = d._get_evidence_progress()
            self.assertIn("effective_cycles", result)
            self.assertIn("target", result)

    def test_C2_counts_only_honest_track_days(self):
        # Dates 2026-06-01..06-14; only those >= PAPER_REAL_START (06-10) count
        # as honest track days — pre-teardown demo bars are excluded.
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            curve = [{"date": f"2026-06-{i:02d}", "equity": 100000} for i in range(1, 15)]
            _write_json(tp, "data/equity_curve_daily.json", curve)
            d = _make_digest(tp)
            result = d._get_evidence_progress()
            self.assertEqual(result["effective_cycles"], 5.0)  # 06-10..06-14

    def test_C3_zero_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            result = d._get_evidence_progress()
            self.assertEqual(result["effective_cycles"], 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Group D — _get_best_apy / _get_best_strategy
# ═══════════════════════════════════════════════════════════════════════════

class TestGetBestApyAndStrategy(unittest.TestCase):

    def test_D1_best_apy_zero_when_no_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            self.assertEqual(d._get_best_apy(), 0.0)

    def test_D2_best_apy_returns_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/paper_trading_status.json", {
                "positions": [
                    {"current_apy": 4.2},
                    {"current_apy": 6.5},
                    {"current_apy": 3.1},
                ]
            })
            d = _make_digest(tp)
            self.assertAlmostEqual(d._get_best_apy(), 6.5)

    def test_D3_best_strategy_dash_when_no_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            self.assertEqual(d._get_best_strategy(), "—")

    def test_D4_best_strategy_returns_highest_apy_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/tournament_results.json", {
                "strategies": {
                    "S8": {"apy": 0.275, "sharpe": 2.1},
                    "S9": {"apy": 0.058, "sharpe": 1.3},
                }
            })
            d = _make_digest(tp)
            self.assertEqual(d._get_best_strategy(), "S8")


# ═══════════════════════════════════════════════════════════════════════════
# Group E — _get_pending_alerts
# ═══════════════════════════════════════════════════════════════════════════

class TestGetPendingAlerts(unittest.TestCase):

    def test_E1_empty_list_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            self.assertEqual(d._get_pending_alerts(), [])

    def test_E2_returns_alert_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/apy_drift_alerts.json", {
                "alerts": [
                    {"strategy": "S0", "drift_pct": 25.0, "severity": "MEDIUM"}
                ]
            })
            d = _make_digest(tp)
            alerts = d._get_pending_alerts()
            self.assertEqual(len(alerts), 1)

    def test_E3_adds_message_key_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/apy_drift_alerts.json", {
                "alerts": [{"strategy": "S3", "drift_pct": 30.0, "severity": "MEDIUM"}]
            })
            d = _make_digest(tp)
            alerts = d._get_pending_alerts()
            self.assertIn("message", alerts[0])


# ═══════════════════════════════════════════════════════════════════════════
# Group F — compose()
# ═══════════════════════════════════════════════════════════════════════════

class TestCompose(unittest.TestCase):

    def test_F1_returns_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            self.assertIsInstance(d.compose(), str)

    def test_F2_contains_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            import datetime
            today = datetime.date.today().isoformat()
            self.assertIn(today, d.compose())

    def test_F3_contains_golive_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            msg = d.compose()
            self.assertIn("GoLive", msg)

    def test_F4_shows_no_active_alerts_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            msg = d.compose()
            self.assertIn("No active alerts", msg)


# ═══════════════════════════════════════════════════════════════════════════
# Group G — send() + save
# ═══════════════════════════════════════════════════════════════════════════

class TestSend(unittest.TestCase):

    def test_G1_send_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            try:
                d.send()
            except Exception as exc:
                self.fail(f"send() raised: {exc}")

    def test_G2_send_updates_last_sent(self):
        # RETIRED (Phase-1 Telegram rebuild): send() no longer pushes Telegram.
        # It COMPOSES + saves state (last_composed / last_digest) and returns
        # False; it no longer sets "last_sent".
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            self.assertIs(d.send(), False)
            self.assertIsNotNone(d._data["last_composed"])
            self.assertTrue(d._data["last_digest"])

    def test_G3_send_increments_send_count(self):
        # RETIRED: send() does not push, so send_count is NOT incremented.
        # It still composes each call (last_digest set).
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            d.send()
            d.send()
            self.assertEqual(d._data["send_count"], 0)
            self.assertTrue(d._data["last_digest"])


# ═══════════════════════════════════════════════════════════════════════════
# Group H — robustness: compose never crashes; HTML-safe; dry-run
# ═══════════════════════════════════════════════════════════════════════════

class TestRobustness(unittest.TestCase):

    def test_H1_compose_with_all_data_files_missing(self):
        # Regression for the launchd exit=1 crash: compose() must degrade to
        # neutral defaults (not raise) when every data/*.json is absent.
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            with unittest.mock.patch.dict(
                "sys.modules",
                {"spa_core.analytics.golive_readiness_report": None},
            ):
                msg = d.compose()
            self.assertIn("GoLive Score: 0/100", msg)
            self.assertIn("Best APY: 0.00% (—)", msg)

    def test_H2_compose_survives_helper_exception(self):
        # If a single helper blows up, _safe swallows it and the digest still
        # composes with the default for that field.
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            with unittest.mock.patch.object(
                d, "_get_best_apy", side_effect=ValueError("boom")
            ):
                msg = d.compose()
            self.assertIn("Best APY: 0.00%", msg)

    def test_H3_compose_html_escapes_strategy_id(self):
        # Strategy IDs / alert text are HTML-escaped so parse_mode="HTML" is
        # safe (Markdown 400s on `_` and `<>`).
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/tournament_results.json", {
                "strategies": {"a<b>&_c": {"apy": 0.1}},
            })
            d = _make_digest(tp)
            msg = d.compose()
            self.assertNotIn("<b>", msg)
            self.assertIn("&lt;b&gt;", msg)

    def test_H4_compose_html_escapes_alert_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            _write_json(tp, "data/apy_drift_alerts.json", {
                "alerts": [{"message": "drift <script> & stuff"}],
            })
            d = _make_digest(tp)
            msg = d.compose()
            self.assertNotIn("<script>", msg)
            self.assertIn("&lt;script&gt;", msg)

    def test_H5_send_uses_html_parse_mode(self):
        # OBSOLETE intent (Phase-1 Telegram rebuild): send() no longer routes
        # through the telegram client at all — it composes + saves state and
        # returns False without any Telegram call.
        with tempfile.TemporaryDirectory() as tmp:
            d = _make_digest(pathlib.Path(tmp))
            fake = unittest.mock.MagicMock(return_value=True)
            with unittest.mock.patch.dict(
                "sys.modules",
                {"spa_core.alerts.telegram_client":
                    unittest.mock.MagicMock(send_message=fake)},
            ):
                result = d.send()
            self.assertIs(result, False)
            fake.assert_not_called()
            self.assertTrue(d._data["last_digest"])

    def test_H6_dry_run_main_exits_zero_without_sending(self):
        # `python -m spa_core.alerts.morning_digest --dry` composes + exits 0
        # and never calls Telegram.
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.alerts.morning_digest",
                 "--dry", tmp],
                cwd=str(_REPO), capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("dry-run", proc.stdout)
            self.assertNotIn("send()", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
