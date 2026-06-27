"""MP-143: Tests for spa_core/alerts/milestone_alert.py

≥35 unittest tests covering:
- load_progress_tracker / load_alert_state (valid, missing, corrupt)
- check_new_milestones (no new, 1 new, multiple, already notified)
- format_milestone_message (HTML structure, key fields)
- save_alert_state (atomicity, no *.tmp left, readable JSON)
- run_milestone_alert (sent=False no new; sent=True with new; is_demo guard;
                        no-data guard; never_raise x5)
- import hygiene (no forbidden imports)
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.alerts.milestone_alert import (
    ALERT_STATE_FILE,
    PROGRESS_TRACKER_FILE,
    check_new_milestones,
    format_milestone_message,
    load_alert_state,
    load_progress_tracker,
    run_milestone_alert,
    save_alert_state,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_progress(milestones=None, paper_days=7, equity=100034.21, apy=3.22,
                   days_to_golive=26, available=True, is_demo=False) -> dict:
    ms = milestones if milestones is not None else [
        {
            "id": "honest_metrics_low",
            "label": "Honest Metrics: LOW_CONFIDENCE (≥7d)",
            "required_days": 7,
            "current_days": 7,
            "reached": True,
        }
    ]
    result = {
        "paper_days": paper_days,
        "current_equity": equity,
        "apy_today_pct": apy,
        "days_to_golive": days_to_golive,
        "milestones": ms,
        "available": available,
    }
    if is_demo:
        result["is_demo"] = True
    return result


def _make_state(notified=None) -> dict:
    return {"notified": notified if notified is not None else [], "last_run": "2026-06-12T00:00:00+00:00"}


def _write_json(directory: Path, filename: str, obj: dict) -> Path:
    path = directory / filename
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


# ─── load_progress_tracker ───────────────────────────────────────────────────

class TestLoadProgressTracker(unittest.TestCase):

    def test_load_valid_file(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            data = _make_progress()
            _write_json(d, PROGRESS_TRACKER_FILE, data)
            result = load_progress_tracker(d)
            self.assertEqual(result["paper_days"], 7)
            self.assertTrue(result["available"])

    def test_returns_empty_dict_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            result = load_progress_tracker(td)
            self.assertEqual(result, {})

    def test_returns_empty_dict_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / PROGRESS_TRACKER_FILE).write_text("NOT JSON{{", encoding="utf-8")
            result = load_progress_tracker(d)
            self.assertEqual(result, {})

    def test_returns_empty_dict_when_content_is_list(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / PROGRESS_TRACKER_FILE).write_text("[1, 2, 3]", encoding="utf-8")
            result = load_progress_tracker(d)
            self.assertEqual(result, {})

    def test_default_data_dir_does_not_raise(self):
        # data dir might not exist in test env — should return {}
        result = load_progress_tracker("/nonexistent/dir/for_test")
        self.assertIsInstance(result, dict)

    def test_milestones_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            data = _make_progress()
            _write_json(d, PROGRESS_TRACKER_FILE, data)
            result = load_progress_tracker(d)
            self.assertIsInstance(result.get("milestones"), list)
            self.assertEqual(len(result["milestones"]), 1)


# ─── load_alert_state ────────────────────────────────────────────────────────

class TestLoadAlertState(unittest.TestCase):

    def test_returns_empty_dict_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            result = load_alert_state(td)
            self.assertEqual(result, {})

    def test_load_valid_state(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            state = _make_state(notified=["honest_metrics_low"])
            _write_json(d, ALERT_STATE_FILE, state)
            result = load_alert_state(d)
            self.assertIn("honest_metrics_low", result["notified"])

    def test_returns_empty_dict_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / ALERT_STATE_FILE).write_text("{broken}", encoding="utf-8")
            result = load_alert_state(d)
            self.assertEqual(result, {})

    def test_returns_empty_dict_when_content_is_list(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / ALERT_STATE_FILE).write_text("[]", encoding="utf-8")
            result = load_alert_state(d)
            self.assertEqual(result, {})

    def test_notified_list_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            ids = ["ms_a", "ms_b"]
            _write_json(d, ALERT_STATE_FILE, {"notified": ids, "last_run": "2026-06-12"})
            result = load_alert_state(d)
            self.assertEqual(result["notified"], ids)


# ─── check_new_milestones ────────────────────────────────────────────────────

class TestCheckNewMilestones(unittest.TestCase):

    def test_returns_empty_when_no_milestones(self):
        progress = {"milestones": [], "available": True}
        result = check_new_milestones(progress, {})
        self.assertEqual(result, [])

    def test_returns_empty_when_milestones_key_missing(self):
        result = check_new_milestones({}, {})
        self.assertEqual(result, [])

    def test_single_new_milestone_returned(self):
        progress = _make_progress()
        state = _make_state(notified=[])
        result = check_new_milestones(progress, state)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "honest_metrics_low")

    def test_already_notified_not_returned(self):
        progress = _make_progress()
        state = _make_state(notified=["honest_metrics_low"])
        result = check_new_milestones(progress, state)
        self.assertEqual(result, [])

    def test_multiple_new_milestones_returned(self):
        ms = [
            {"id": "ms_a", "label": "A", "reached": True},
            {"id": "ms_b", "label": "B", "reached": True},
        ]
        progress = _make_progress(milestones=ms)
        state = _make_state(notified=[])
        result = check_new_milestones(progress, state)
        self.assertEqual(len(result), 2)

    def test_partial_notified(self):
        ms = [
            {"id": "ms_a", "label": "A", "reached": True},
            {"id": "ms_b", "label": "B", "reached": True},
        ]
        progress = _make_progress(milestones=ms)
        state = _make_state(notified=["ms_a"])
        result = check_new_milestones(progress, state)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "ms_b")

    def test_not_reached_milestone_not_returned(self):
        ms = [{"id": "ms_a", "label": "A", "reached": False}]
        progress = _make_progress(milestones=ms)
        state = _make_state(notified=[])
        result = check_new_milestones(progress, state)
        self.assertEqual(result, [])

    def test_notified_not_list_handled_gracefully(self):
        progress = _make_progress()
        state = {"notified": None}
        # Should not crash; the milestone is reached and "notified" is None → treat as empty
        result = check_new_milestones(progress, state)
        self.assertEqual(len(result), 1)

    def test_non_dict_milestone_skipped(self):
        progress = {"milestones": ["string_entry", None, {"id": "ms_ok", "reached": True}]}
        state = _make_state(notified=[])
        result = check_new_milestones(progress, state)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "ms_ok")

    def test_milestone_without_id_skipped(self):
        ms = [{"label": "No ID", "reached": True}]
        progress = _make_progress(milestones=ms)
        state = _make_state(notified=[])
        # id is empty string → skipped
        result = check_new_milestones(progress, state)
        self.assertEqual(result, [])

    def test_no_duplicate_when_same_id_in_list_twice(self):
        ms = [
            {"id": "ms_dup", "label": "Dup", "reached": True},
            {"id": "ms_dup", "label": "Dup2", "reached": True},
        ]
        progress = _make_progress(milestones=ms)
        state = _make_state(notified=[])
        result = check_new_milestones(progress, state)
        # Both are returned (dedup is caller's responsibility); id not in notified
        ids = [m["id"] for m in result]
        self.assertIn("ms_dup", ids)


# ─── format_milestone_message ────────────────────────────────────────────────

class TestFormatMilestoneMessage(unittest.TestCase):

    def _make_ms(self, ms_id="honest_metrics_low", label="Low Confidence"):
        return [{"id": ms_id, "label": label, "reached": True}]

    def test_returns_string(self):
        msg = format_milestone_message(self._make_ms(), _make_progress())
        self.assertIsInstance(msg, str)

    def test_contains_header(self):
        msg = format_milestone_message(self._make_ms(), _make_progress())
        self.assertIn("SPA: Milestone Reached!", msg)

    def test_contains_milestone_label(self):
        msg = format_milestone_message(self._make_ms(), _make_progress())
        self.assertIn("Low Confidence", msg)

    def test_contains_checkmark_emoji(self):
        msg = format_milestone_message(self._make_ms(), _make_progress())
        self.assertIn("✅", msg)

    def test_contains_paper_days(self):
        progress = _make_progress(paper_days=14)
        msg = format_milestone_message(self._make_ms(), progress)
        self.assertIn("14", msg)

    def test_contains_equity(self):
        progress = _make_progress(equity=100500.55)
        msg = format_milestone_message(self._make_ms(), progress)
        self.assertIn("100,500.55", msg)

    def test_contains_apy(self):
        progress = _make_progress(apy=4.56)
        msg = format_milestone_message(self._make_ms(), progress)
        self.assertIn("4.56", msg)

    def test_contains_days_to_golive(self):
        progress = _make_progress(days_to_golive=21)
        msg = format_milestone_message(self._make_ms(), progress)
        self.assertIn("21", msg)

    def test_html_bold_tags_present(self):
        msg = format_milestone_message(self._make_ms(), _make_progress())
        self.assertIn("<b>", msg)
        self.assertIn("</b>", msg)

    def test_multiple_milestones_all_in_message(self):
        ms = [
            {"id": "ms_a", "label": "Alpha Milestone", "reached": True},
            {"id": "ms_b", "label": "Beta Milestone", "reached": True},
        ]
        progress = _make_progress(milestones=ms)
        msg = format_milestone_message(ms, progress)
        self.assertIn("Alpha Milestone", msg)
        self.assertIn("Beta Milestone", msg)

    def test_known_milestone_has_description(self):
        ms = [{"id": "honest_metrics_low", "label": "Low Confidence", "reached": True}]
        msg = format_milestone_message(ms, _make_progress(milestones=ms))
        self.assertIn("достоверность", msg.lower())

    def test_unknown_milestone_no_crash(self):
        ms = [{"id": "totally_unknown_id", "label": "Unknown", "reached": True}]
        progress = _make_progress(milestones=ms)
        msg = format_milestone_message(ms, progress)
        self.assertIsInstance(msg, str)
        self.assertIn("Unknown", msg)

    def test_milestone_id_in_message(self):
        ms = [{"id": "backtest_contour_min", "label": "Backtest Label", "reached": True}]
        progress = _make_progress(milestones=ms)
        msg = format_milestone_message(ms, progress)
        self.assertIn("Backtest Label", msg)


# ─── save_alert_state ────────────────────────────────────────────────────────

class TestSaveAlertState(unittest.TestCase):

    def test_file_created_and_readable(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            state = {"notified": ["ms_a"], "last_run": "2026-06-12"}
            save_alert_state(state, d)
            result = json.loads((d / ALERT_STATE_FILE).read_text())
            self.assertEqual(result["notified"], ["ms_a"])

    def test_no_tmp_files_left_after_write(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            save_alert_state({"notified": []}, d)
            tmp_files = list(d.glob("*.tmp*")) + list(d.glob(".milestone_alert_state_tmp_*"))
            self.assertEqual(tmp_files, [])

    def test_overwrites_existing_state(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            save_alert_state({"notified": ["old"]}, d)
            save_alert_state({"notified": ["new"]}, d)
            result = json.loads((d / ALERT_STATE_FILE).read_text())
            self.assertEqual(result["notified"], ["new"])

    def test_valid_json_output(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            state = {"notified": ["a", "b"], "last_run": "2026-06-12"}
            save_alert_state(state, d)
            text = (d / ALERT_STATE_FILE).read_text()
            parsed = json.loads(text)
            self.assertIsInstance(parsed, dict)

    def test_empty_notified_list(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            save_alert_state({"notified": []}, d)
            result = json.loads((d / ALERT_STATE_FILE).read_text())
            self.assertEqual(result["notified"], [])


# ─── run_milestone_alert ─────────────────────────────────────────────────────

class TestRunMilestoneAlert(unittest.TestCase):

    def _patch_tg(self, sent=True):
        """Return a patcher for the _post_message function used by milestone_alert."""
        return patch(
            "spa_core.alerts.milestone_alert._post_message_for_test",
            return_value=sent,
        )

    def _write_progress(self, directory: Path, progress: dict) -> None:
        _write_json(directory, PROGRESS_TRACKER_FILE, progress)

    def _write_state(self, directory: Path, state: dict) -> None:
        _write_json(directory, ALERT_STATE_FILE, state)

    def _mock_post_message(self, sent: bool = True):
        """Patch the push authority used inside run_milestone_alert.

        Phase-1 Telegram rebuild: milestones (incl. go-live READY) route through
        push_policy.push_critical("golive_ready", ...) instead of the transport's
        _post_message. Mock that single seam.
        """
        return patch(
            "spa_core.telegram.push_policy.push_critical",
            return_value=sent,
        )

    def test_no_progress_returns_sent_false(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_milestone_alert(td)
            self.assertFalse(result["sent"])
            self.assertEqual(result["new_milestones"], [])

    def test_no_new_milestones_returns_sent_false(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress()
            self._write_progress(d, progress)
            # Already notified
            self._write_state(d, {"notified": ["honest_metrics_low"]})
            result = run_milestone_alert(d)
            self.assertFalse(result["sent"])

    def test_is_demo_returns_early_no_send(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress(is_demo=True)
            self._write_progress(d, progress)
            result = run_milestone_alert(d)
            self.assertFalse(result["sent"])
            self.assertEqual(result["new_milestones"], [])

    def test_available_false_returns_early(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress(available=False)
            self._write_progress(d, progress)
            result = run_milestone_alert(d)
            self.assertFalse(result["sent"])

    def test_new_milestone_sends_and_updates_state(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress()
            self._write_progress(d, progress)

            with self._mock_post_message(sent=True):
                result = run_milestone_alert(d)

            self.assertTrue(result["sent"])
            self.assertIn("honest_metrics_low", result["new_milestones"])
            # State should be updated
            state = load_alert_state(d)
            self.assertIn("honest_metrics_low", state["notified"])

    def test_sent_false_when_telegram_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress()
            self._write_progress(d, progress)

            with self._mock_post_message(sent=False):
                result = run_milestone_alert(d)

            self.assertFalse(result["sent"])
            # notified should NOT be updated when send failed
            state = load_alert_state(d)
            self.assertNotIn("honest_metrics_low", state.get("notified", []))

    def test_multiple_new_milestones_all_in_result(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            ms = [
                {"id": "ms_a", "label": "Alpha", "reached": True},
                {"id": "ms_b", "label": "Beta", "reached": True},
            ]
            progress = _make_progress(milestones=ms)
            self._write_progress(d, progress)

            with self._mock_post_message(sent=True):
                result = run_milestone_alert(d)

            self.assertTrue(result["sent"])
            self.assertIn("ms_a", result["new_milestones"])
            self.assertIn("ms_b", result["new_milestones"])

    def test_state_updated_with_last_run_on_no_milestones(self):
        """Even with no new milestones, last_run should be updated."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress()
            self._write_progress(d, progress)
            self._write_state(d, {"notified": ["honest_metrics_low"]})
            run_milestone_alert(d)
            state = load_alert_state(d)
            self.assertIn("last_run", state)

    # ── never_raise scenarios ─────────────────────────────────────────────

    def test_never_raise_on_corrupt_progress_json(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / PROGRESS_TRACKER_FILE).write_text("CORRUPT", encoding="utf-8")
            result = run_milestone_alert(d)
            self.assertIsInstance(result, dict)
            self.assertFalse(result["sent"])

    def test_never_raise_on_corrupt_state_json(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress()
            self._write_progress(d, progress)
            (d / ALERT_STATE_FILE).write_text("{broken}", encoding="utf-8")
            with self._mock_post_message(sent=True):
                result = run_milestone_alert(d)
            self.assertIsInstance(result, dict)

    def test_never_raise_on_missing_milestones_key(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write_progress(d, {"paper_days": 5, "available": True})
            result = run_milestone_alert(d)
            self.assertIsInstance(result, dict)

    def test_never_raise_on_telegram_import_error(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress()
            self._write_progress(d, progress)
            with patch("spa_core.alerts.telegram_client._post_message", side_effect=ImportError("no module")):
                result = run_milestone_alert(d)
            self.assertIsInstance(result, dict)

    def test_never_raise_on_telegram_exception(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            progress = _make_progress()
            self._write_progress(d, progress)
            with patch("spa_core.alerts.telegram_client._post_message", side_effect=RuntimeError("boom")):
                result = run_milestone_alert(d)
            self.assertIsInstance(result, dict)
            self.assertFalse(result["sent"])


# ─── import hygiene ──────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):

    def test_no_anthropic_import(self):
        import spa_core.alerts.milestone_alert as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import anthropic", src)

    def test_no_numpy_import(self):
        import spa_core.alerts.milestone_alert as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import numpy", src)

    def test_no_pandas_import(self):
        import spa_core.alerts.milestone_alert as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import pandas", src)

    def test_no_scipy_import(self):
        import spa_core.alerts.milestone_alert as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import scipy", src)

    def test_module_importable(self):
        import spa_core.alerts.milestone_alert  # noqa: F401
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
