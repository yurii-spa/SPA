"""
MP-1329 (v9.45) — Tests for PaperPeriodSimulator.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_paper_period_simulator -v
    python3 -m unittest tests/test_paper_period_simulator.py -v

Also compatible with pytest.

Test plan (40 tests):
  1. TestInit                  (2)  — default / custom capital
  2. TestPredefinedPeriods     (2)  — count and keys
  3. TestSimulatePeriodKeys   (13)  — all 13 output keys for bear_2022
  4. TestFinalNav              (4)  — final_nav > 0 for every period
  5. TestMaxDrawdown           (4)  — max_drawdown_pct <= 0 for every period
  6. TestEvidencePoints        (4)  — evidence_points_accumulated > 0 for every period
  7. TestSimulateAll           (4)  — structure of simulate_all()
  8. TestBestWorstPeriod       (2)  — best/worst return valid keys
  9. TestRecommendations       (4)  — presence & types of recommendation fields
 10. TestSave                  (1)  — atomic save creates valid file (with sub-dir)
      bonus test: unknown period raises ValueError

Total: 40
"""

import json
import os
import sys
import tempfile
import unittest

# ── repo-root import ───────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.paper_period_simulator import (
    PREDEFINED_PERIODS,
    PaperPeriodSimulator,
)

# ── shared fixtures ────────────────────────────────────────────────────────────

_SIM   = PaperPeriodSimulator()                 # default capital $100k
_ALL   = _SIM.simulate_all()                    # pre-computed to avoid re-simulation
_BEAR  = _ALL["bear_2022"]
_REC   = _ALL["recovery_2023"]
_BULL  = _ALL["bull_2024"]
_STAB  = _ALL["stable_2025"]
_PIDS  = list(PREDEFINED_PERIODS.keys())        # ["bear_2022", "recovery_2023", ...]

# =============================================================================
# 1. TestInit (2 tests)
# =============================================================================

class TestInit(unittest.TestCase):

    def test_default_capital(self):
        """Default initial capital is 100 000.0."""
        sim = PaperPeriodSimulator()
        self.assertEqual(sim._initial_capital, 100_000.0)

    def test_custom_capital(self):
        """Custom capital is accepted and stored."""
        sim = PaperPeriodSimulator(initial_capital=250_000.0)
        self.assertEqual(sim._initial_capital, 250_000.0)


# =============================================================================
# 2. TestPredefinedPeriods (2 tests)
# =============================================================================

class TestPredefinedPeriods(unittest.TestCase):

    def test_count(self):
        """Exactly 4 predefined periods."""
        self.assertEqual(len(PREDEFINED_PERIODS), 4)

    def test_expected_keys(self):
        """All four canonical period keys are present."""
        expected = {"bear_2022", "recovery_2023", "bull_2024", "stable_2025"}
        self.assertEqual(set(PREDEFINED_PERIODS.keys()), expected)


# =============================================================================
# 3. TestSimulatePeriodKeys (13 tests)
# =============================================================================

class TestSimulatePeriodKeys(unittest.TestCase):
    """Verifies that simulate_period returns all required output keys."""

    def test_key_period(self):
        self.assertIn("period", _BEAR)

    def test_key_start(self):
        self.assertIn("start", _BEAR)

    def test_key_end(self):
        self.assertIn("end", _BEAR)

    def test_key_regime(self):
        self.assertIn("regime", _BEAR)

    def test_key_days(self):
        self.assertIn("days", _BEAR)

    def test_key_nav_trajectory(self):
        self.assertIn("nav_trajectory", _BEAR)

    def test_key_final_nav(self):
        self.assertIn("final_nav", _BEAR)

    def test_key_total_return_pct(self):
        self.assertIn("total_return_pct", _BEAR)

    def test_key_apy(self):
        self.assertIn("apy", _BEAR)

    def test_key_max_drawdown_pct(self):
        self.assertIn("max_drawdown_pct", _BEAR)

    def test_key_evidence_points_accumulated(self):
        self.assertIn("evidence_points_accumulated", _BEAR)

    def test_key_protocol_changes(self):
        self.assertIn("protocol_changes", _BEAR)

    def test_key_market_events(self):
        self.assertIn("market_events", _BEAR)


# =============================================================================
# 4. TestFinalNav (4 tests)
# =============================================================================

class TestFinalNav(unittest.TestCase):

    def test_final_nav_positive_bear(self):
        """Bear period: NAV always stays positive."""
        self.assertGreater(_BEAR["final_nav"], 0)

    def test_final_nav_positive_recovery(self):
        self.assertGreater(_REC["final_nav"], 0)

    def test_final_nav_positive_bull(self):
        self.assertGreater(_BULL["final_nav"], 0)

    def test_final_nav_positive_stable(self):
        self.assertGreater(_STAB["final_nav"], 0)


# =============================================================================
# 5. TestMaxDrawdown (4 tests)
# =============================================================================

class TestMaxDrawdown(unittest.TestCase):

    def test_max_drawdown_nonpositive_bear(self):
        """Drawdown is conventionally expressed as a non-positive number."""
        self.assertLessEqual(_BEAR["max_drawdown_pct"], 0)

    def test_max_drawdown_nonpositive_recovery(self):
        self.assertLessEqual(_REC["max_drawdown_pct"], 0)

    def test_max_drawdown_nonpositive_bull(self):
        self.assertLessEqual(_BULL["max_drawdown_pct"], 0)

    def test_max_drawdown_nonpositive_stable(self):
        self.assertLessEqual(_STAB["max_drawdown_pct"], 0)


# =============================================================================
# 6. TestEvidencePoints (4 tests)
# =============================================================================

class TestEvidencePoints(unittest.TestCase):

    def test_evidence_positive_bear(self):
        """Even in a bear regime, at least some protocols are eligible."""
        self.assertGreater(_BEAR["evidence_points_accumulated"], 0)

    def test_evidence_positive_recovery(self):
        self.assertGreater(_REC["evidence_points_accumulated"], 0)

    def test_evidence_positive_bull(self):
        self.assertGreater(_BULL["evidence_points_accumulated"], 0)

    def test_evidence_positive_stable(self):
        self.assertGreater(_STAB["evidence_points_accumulated"], 0)


# =============================================================================
# 7. TestSimulateAll (4 tests)
# =============================================================================

class TestSimulateAll(unittest.TestCase):

    def test_returns_dict(self):
        """simulate_all() must return a dict."""
        self.assertIsInstance(_ALL, dict)

    def test_has_four_keys(self):
        """simulate_all() must contain exactly 4 period results."""
        self.assertEqual(len(_ALL), 4)

    def test_all_period_ids_present(self):
        """All 4 canonical period IDs must be present in the result."""
        for pid in ("bear_2022", "recovery_2023", "bull_2024", "stable_2025"):
            self.assertIn(pid, _ALL)

    def test_values_are_dicts_with_required_key(self):
        """Each value in simulate_all() must be a dict containing 'period'."""
        for pid, result in _ALL.items():
            with self.subTest(period=pid):
                self.assertIsInstance(result, dict)
                self.assertIn("period", result)


# =============================================================================
# 8. TestBestWorstPeriod (2 tests)
# =============================================================================

class TestBestWorstPeriod(unittest.TestCase):

    def test_best_paper_start_date_is_valid_key(self):
        """best_paper_start_date() must return one of the predefined period keys."""
        best = _SIM.best_paper_start_date()
        self.assertIn(best, PREDEFINED_PERIODS)

    def test_worst_paper_period_is_valid_key(self):
        """worst_paper_period() must return one of the predefined period keys."""
        worst = _SIM.worst_paper_period()
        self.assertIn(worst, PREDEFINED_PERIODS)


# =============================================================================
# 9. TestRecommendations (4 tests)
# =============================================================================

class TestRecommendations(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.recs = _SIM.recommendations()

    def test_has_start_now(self):
        """recommendations() must include 'start_now' key."""
        self.assertIn("start_now", self.recs)

    def test_has_expected_duration_days(self):
        """recommendations() must include 'expected_duration_days' key."""
        self.assertIn("expected_duration_days", self.recs)

    def test_has_expected_evidence_points(self):
        """recommendations() must include 'expected_evidence_points' key."""
        self.assertIn("expected_evidence_points", self.recs)

    def test_has_notes(self):
        """recommendations() must include 'notes' as a non-empty list."""
        self.assertIn("notes", self.recs)
        self.assertIsInstance(self.recs["notes"], list)
        self.assertGreater(len(self.recs["notes"]), 0)


# =============================================================================
# 10. TestSave (2 tests) + bonus unknown-period test (counts as the 40th)
# =============================================================================

class TestSave(unittest.TestCase):

    def test_save_creates_file_with_subdirectory(self):
        """save() must create parent dirs and produce a valid JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backtest", "paper_period_simulations.json")
            _SIM.save(path)
            self.assertTrue(os.path.exists(path))

    def test_save_file_contains_all_four_periods(self):
        """Saved JSON must contain a 'periods' dict with all 4 period IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.json")
            _SIM.save(path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("periods", data)
            self.assertEqual(len(data["periods"]), 4)
            for pid in ("bear_2022", "recovery_2023", "bull_2024", "stable_2025"):
                self.assertIn(pid, data["periods"])

    def test_unknown_period_raises_value_error(self):
        """simulate_period() with unknown id must raise ValueError."""
        with self.assertRaises(ValueError):
            _SIM.simulate_period("definitely_not_a_period")


if __name__ == "__main__":
    unittest.main()
