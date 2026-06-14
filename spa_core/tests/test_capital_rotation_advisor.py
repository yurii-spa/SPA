"""
Tests for MP-646: CapitalRotationAdvisor  (≥65 tests)
Pure stdlib unittest — no pytest dependency.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.capital_rotation_advisor import (
    AdapterSnapshot,
    CapitalRotationAdvisor,
    RotationAction,
    RotationReport,
    MAX_ENTRIES,
    MIN_APY_GAIN_BPS,
    ROTATION_COST_BPS,
    MIN_DAYS_BEFORE_ROTATE,
)


def _snap(adapter_id, apy, alloc=10000.0, tier="T1",
          lock_days=0, risk_score=10.0, days_in=20, expected_apy=None):
    return AdapterSnapshot(
        adapter_id=adapter_id,
        current_apy=apy,
        expected_apy=apy if expected_apy is None else expected_apy,
        current_allocation_usd=alloc,
        tier=tier,
        lock_days_remaining=lock_days,
        protocol_risk_score=risk_score,
        days_in_position=days_in,
    )


def _advisor(data_file=None):
    if data_file is None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        data_file = Path(path)
    return CapitalRotationAdvisor(data_file=data_file)


# ===========================================================================
# 1. _apy_gain_bps (net) and _gross_gain_bps
# ===========================================================================

class TestApyGainBps(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_positive_net_when_candidate_higher(self):
        cur = _snap("a", 0.04)
        cand = _snap("b", 0.06)
        # gross = 200bps; net = 190
        self.assertAlmostEqual(self.adv._apy_gain_bps(cur, cand), 190.0, places=4)

    def test_net_equals_gross_minus_cost(self):
        cur = _snap("a", 0.04)
        cand = _snap("b", 0.05)
        gross = self.adv._gross_gain_bps(cur, cand)
        net = self.adv._apy_gain_bps(cur, cand)
        self.assertAlmostEqual(net, gross - ROTATION_COST_BPS, places=6)

    def test_net_negative_when_equal_apy(self):
        cur = _snap("a", 0.05)
        cand = _snap("b", 0.05)
        net = self.adv._apy_gain_bps(cur, cand)
        self.assertAlmostEqual(net, -ROTATION_COST_BPS, places=6)

    def test_net_negative_when_candidate_lower(self):
        cur = _snap("a", 0.07)
        cand = _snap("b", 0.04)
        self.assertLess(self.adv._apy_gain_bps(cur, cand), 0)

    def test_gross_positive_when_candidate_higher(self):
        cur = _snap("a", 0.04)
        cand = _snap("b", 0.05)
        self.assertAlmostEqual(self.adv._gross_gain_bps(cur, cand), 100.0, places=4)

    def test_gross_zero_when_equal_apy(self):
        cur = _snap("a", 0.05)
        cand = _snap("b", 0.05)
        self.assertAlmostEqual(self.adv._gross_gain_bps(cur, cand), 0.0, places=6)


# ===========================================================================
# 2. _find_best
# ===========================================================================

class TestFindBest(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_no_candidates_returns_none(self):
        cur = _snap("a", 0.05)
        self.assertIsNone(self.adv._find_best([], cur))

    def test_same_adapter_excluded(self):
        cur = _snap("a", 0.05)
        cands = [_snap("a", 0.10)]
        self.assertIsNone(self.adv._find_best(cands, cur))

    def test_lower_apy_excluded(self):
        cur = _snap("a", 0.08)
        cands = [_snap("b", 0.06)]
        self.assertIsNone(self.adv._find_best(cands, cur))

    def test_picks_highest_net_score(self):
        cur = _snap("a", 0.04)
        cands = [
            _snap("b", 0.07, risk_score=10.0),   # score=0.07-0.01=0.06
            _snap("c", 0.08, risk_score=5.0),    # score=0.08-0.005=0.075
        ]
        best = self.adv._find_best(cands, cur)
        self.assertEqual(best.adapter_id, "c")

    def test_risk_penalty_demotes_high_apy(self):
        cur = _snap("a", 0.04)
        cands = [
            _snap("b", 0.09, risk_score=100.0),  # score=0.09-0.1=-0.01
            _snap("c", 0.07, risk_score=5.0),    # score=0.07-0.005=0.065
        ]
        best = self.adv._find_best(cands, cur)
        self.assertEqual(best.adapter_id, "c")

    def test_single_eligible_returned(self):
        cur = _snap("a", 0.04)
        cands = [_snap("b", 0.06)]
        best = self.adv._find_best(cands, cur)
        self.assertEqual(best.adapter_id, "b")

    def test_equal_apy_picks_lower_risk(self):
        cur = _snap("a", 0.04)
        cands = [_snap("b", 0.07, risk_score=0.0), _snap("c", 0.07, risk_score=50.0)]
        best = self.adv._find_best(cands, cur)
        self.assertEqual(best.adapter_id, "b")


# ===========================================================================
# 3. analyze — verdict
# ===========================================================================

class TestAnalyzeVerdicts(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_empty_current_returns_hold(self):
        report = self.adv.analyze([], [_snap("c", 0.08)])
        self.assertEqual(report.verdict, "HOLD")

    def test_no_candidates_returns_hold(self):
        report = self.adv.analyze([_snap("a", 0.05)], [])
        self.assertEqual(report.verdict, "HOLD")

    def test_below_threshold_returns_hold(self):
        # 34bps gross → 24 net < 25 threshold → no action
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.0434)]
        report = self.adv.analyze(cur, cands)
        self.assertEqual(report.verdict, "HOLD")

    def test_immediate_verdict_rotate_now(self):
        # 60bps gross → 50 net → IMMEDIATE
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.046)]
        report = self.adv.analyze(cur, cands)
        self.assertEqual(report.verdict, "ROTATE_NOW")

    def test_soon_verdict_rotate_soon(self):
        # 35bps gross → 25 net → SOON
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.0435)]
        report = self.adv.analyze(cur, cands)
        self.assertEqual(report.verdict, "ROTATE_SOON")

    def test_all_locked_verdict_locked(self):
        cur = [_snap("a", 0.04, lock_days=30, days_in=20)]
        cands = [_snap("b", 0.08)]
        report = self.adv.analyze(cur, cands)
        self.assertEqual(report.verdict, "LOCKED")

    def test_free_action_overrides_locked(self):
        cur = [
            _snap("a", 0.04, lock_days=0, days_in=20),
            _snap("b", 0.03, lock_days=30, days_in=20),
        ]
        cands = [_snap("c", 0.08)]
        report = self.adv.analyze(cur, cands)
        self.assertIn(report.verdict, ("ROTATE_NOW", "ROTATE_SOON"))


# ===========================================================================
# 4. Lock handling
# ===========================================================================

class TestAnalyzeLockHandling(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_locked_creates_blocked_action(self):
        cur = [_snap("a", 0.04, lock_days=14, days_in=20)]
        cands = [_snap("b", 0.08)]
        report = self.adv.analyze(cur, cands)
        self.assertTrue(any(a.blocked_by_lock for a in report.actions))

    def test_locked_action_urgency_is_soon(self):
        cur = [_snap("a", 0.04, lock_days=14, days_in=20)]
        cands = [_snap("b", 0.08)]
        report = self.adv.analyze(cur, cands)
        locked = [a for a in report.actions if a.blocked_by_lock]
        self.assertTrue(all(a.urgency == "SOON" for a in locked))

    def test_locked_reason_mentions_days(self):
        cur = [_snap("a", 0.04, lock_days=14, days_in=20)]
        cands = [_snap("b", 0.08)]
        report = self.adv.analyze(cur, cands)
        locked = [a for a in report.actions if a.blocked_by_lock]
        self.assertTrue(any("14" in a.reason for a in locked))

    def test_locked_small_gain_no_action(self):
        # 20bps gross ≤ 25 threshold → no locked action
        cur = [_snap("a", 0.04, lock_days=14, days_in=20)]
        cands = [_snap("b", 0.042)]
        report = self.adv.analyze(cur, cands)
        self.assertEqual(len(report.actions), 0)

    def test_locked_excluded_from_annual_gain(self):
        cur = [_snap("a", 0.04, lock_days=14, days_in=20, alloc=10000)]
        cands = [_snap("b", 0.10)]
        report = self.adv.analyze(cur, cands)
        self.assertAlmostEqual(report.estimated_annual_gain_usd, 0.0, places=2)


# ===========================================================================
# 5. days_in_position guard
# ===========================================================================

class TestDaysGuard(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_below_min_skipped(self):
        cur = [_snap("a", 0.04, days_in=MIN_DAYS_BEFORE_ROTATE - 1)]
        cands = [_snap("b", 0.10)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertEqual(len(free), 0)

    def test_exactly_min_not_skipped(self):
        cur = [_snap("a", 0.04, days_in=MIN_DAYS_BEFORE_ROTATE)]
        cands = [_snap("b", 0.10)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertGreaterEqual(len(free), 1)

    def test_above_min_processes(self):
        cur = [_snap("a", 0.04, days_in=MIN_DAYS_BEFORE_ROTATE + 5)]
        cands = [_snap("b", 0.10)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertGreaterEqual(len(free), 1)


# ===========================================================================
# 6. Action construction details
# ===========================================================================

class TestActionConstruction(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_from_to_set_correctly(self):
        cur = [_snap("pos_a", 0.04, days_in=20)]
        cands = [_snap("cand_b", 0.08)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertEqual(free[0].from_adapter, "pos_a")
        self.assertEqual(free[0].to_adapter, "cand_b")

    def test_amount_equals_position_allocation(self):
        cur = [_snap("a", 0.04, alloc=33333.0, days_in=20)]
        cands = [_snap("b", 0.08)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertAlmostEqual(free[0].amount_usd, 33333.0, places=2)

    def test_reason_mentions_bps(self):
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.10)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertIn("bps", free[0].reason)

    def test_actions_sorted_by_gain_descending(self):
        cur = [_snap("a", 0.03, alloc=10000, days_in=20),
               _snap("b", 0.04, alloc=10000, days_in=20)]
        cands = [_snap("x", 0.10), _snap("y", 0.08)]
        report = self.adv.analyze(cur, cands)
        gains = [a.apy_gain_bps for a in report.actions]
        self.assertEqual(gains, sorted(gains, reverse=True))

    def test_immediate_threshold_exactly_50bps_net(self):
        # gross=60 → net=50 → IMMEDIATE
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.046)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertEqual(free[0].urgency, "IMMEDIATE")

    def test_soon_when_net_below_50(self):
        # gross=35 → net=25 → SOON
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.0435)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertEqual(free[0].urgency, "SOON")

    def test_exact_25bps_net_creates_action(self):
        # gross=35 → net=25 exactly → action created
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.0435)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertEqual(len(free), 1)

    def test_24bps_net_no_action(self):
        # gross=34 → net=24 < 25 → no action
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.0434)]
        report = self.adv.analyze(cur, cands)
        free = [a for a in report.actions if not a.blocked_by_lock]
        self.assertEqual(len(free), 0)

    def test_no_self_rotation_in_actions(self):
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("a", 0.10)]  # same id → find_best returns None
        report = self.adv.analyze(cur, cands)
        for a in report.actions:
            self.assertNotEqual(a.from_adapter, a.to_adapter)


# ===========================================================================
# 7. estimated_annual_gain & total_capital
# ===========================================================================

class TestFinancials(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_annual_gain_calculation(self):
        alloc = 50000.0
        cur = [_snap("a", 0.04, alloc=alloc, days_in=20)]
        cands = [_snap("b", 0.10)]  # 600 gross → 590 net
        report = self.adv.analyze(cur, cands)
        expected = alloc * 590 / 10000
        self.assertAlmostEqual(report.estimated_annual_gain_usd, expected, delta=0.1)

    def test_annual_gain_zero_when_no_actions(self):
        report = self.adv.analyze([_snap("a", 0.04)], [])
        self.assertAlmostEqual(report.estimated_annual_gain_usd, 0.0, places=2)

    def test_annual_gain_excludes_locked(self):
        cur = [_snap("a", 0.04, lock_days=30, days_in=20, alloc=10000)]
        cands = [_snap("b", 0.10)]
        report = self.adv.analyze(cur, cands)
        self.assertAlmostEqual(report.estimated_annual_gain_usd, 0.0, places=2)

    def test_total_capital_sum(self):
        cur = [_snap("a", 0.04, alloc=30000, days_in=20),
               _snap("b", 0.05, alloc=20000, days_in=20)]
        report = self.adv.analyze(cur, [])
        self.assertAlmostEqual(report.total_capital_usd, 50000.0, places=2)

    def test_total_capital_empty_is_zero(self):
        report = self.adv.analyze([], [])
        self.assertAlmostEqual(report.total_capital_usd, 0.0, places=2)


# ===========================================================================
# 8. top_opportunity
# ===========================================================================

class TestTopOpportunity(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_none_when_no_actions(self):
        report = self.adv.analyze([], [])
        self.assertIsNone(report.top_opportunity)

    def test_is_best_to_adapter(self):
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("best", 0.12)]
        report = self.adv.analyze(cur, cands)
        self.assertEqual(report.top_opportunity, "best")

    def test_matches_first_sorted_action(self):
        cur = [_snap("a", 0.04, alloc=10000, days_in=20),
               _snap("b", 0.03, alloc=10000, days_in=20)]
        cands = [_snap("great", 0.12), _snap("good", 0.08)]
        report = self.adv.analyze(cur, cands)
        self.assertEqual(report.top_opportunity, report.actions[0].to_adapter)


# ===========================================================================
# 9. Persistence (save_report & load_history)
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "rotation.json"
        self.adv = CapitalRotationAdvisor(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        self.adv.save_report(self.adv.analyze([], []))
        self.assertTrue(self.data_file.exists())

    def test_save_writes_valid_json(self):
        self.adv.save_report(self.adv.analyze([], []))
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_entry_has_expected_keys(self):
        self.adv.save_report(self.adv.analyze([], []))
        entry = json.loads(self.data_file.read_text())[0]
        for key in ("timestamp", "total_capital_usd", "action_count",
                    "estimated_annual_gain_usd", "verdict", "top_opportunity"):
            self.assertIn(key, entry)

    def test_save_multiple_appends(self):
        for _ in range(5):
            self.adv.save_report(self.adv.analyze([], []))
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_max(self):
        for _ in range(MAX_ENTRIES + 15):
            self.adv.save_report(self.adv.analyze([], []))
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_save_is_atomic_no_tmp_left(self):
        self.adv.save_report(self.adv.analyze([], []))
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())

    def test_load_history_missing_returns_empty(self):
        self.assertEqual(self.adv.load_history(), [])

    def test_load_history_returns_saved_data(self):
        self.adv.save_report(self.adv.analyze([], []))
        h = self.adv.load_history()
        self.assertEqual(len(h), 1)

    def test_load_history_corrupted_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("BAD_JSON{[}")
        self.assertEqual(self.adv.load_history(), [])

    def test_save_action_count_correct(self):
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.10)]
        report = self.adv.analyze(cur, cands)
        self.adv.save_report(report)
        entry = json.loads(self.data_file.read_text())[0]
        self.assertEqual(entry["action_count"], len(report.actions))


# ===========================================================================
# 10. get_immediate_actions
# ===========================================================================

class TestGetImmediateActions(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()

    def test_only_immediate_unlocked_returned(self):
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.10)]  # 600 gross → 590 net → IMMEDIATE
        report = self.adv.analyze(cur, cands)
        imm = self.adv.get_immediate_actions(report)
        self.assertTrue(all(a.urgency == "IMMEDIATE" for a in imm))
        self.assertTrue(all(not a.blocked_by_lock for a in imm))

    def test_soon_excluded(self):
        cur = [_snap("a", 0.04, days_in=20)]
        cands = [_snap("b", 0.0435)]  # 25 net → SOON
        report = self.adv.analyze(cur, cands)
        self.assertEqual(len(self.adv.get_immediate_actions(report)), 0)

    def test_locked_immediate_excluded(self):
        locked_action = RotationAction(
            from_adapter="a", to_adapter="b", amount_usd=10000,
            reason="test", apy_gain_bps=100.0, urgency="IMMEDIATE",
            blocked_by_lock=True,
        )
        report = RotationReport(
            timestamp=time.time(), total_capital_usd=10000,
            actions=[locked_action], estimated_annual_gain_usd=0,
            verdict="LOCKED", top_opportunity=None,
        )
        self.assertEqual(len(self.adv.get_immediate_actions(report)), 0)

    def test_empty_report_returns_empty(self):
        report = RotationReport(
            timestamp=time.time(), total_capital_usd=0,
            actions=[], estimated_annual_gain_usd=0,
            verdict="HOLD", top_opportunity=None,
        )
        self.assertEqual(self.adv.get_immediate_actions(report), [])

    def test_returns_list(self):
        report = self.adv.analyze([], [])
        self.assertIsInstance(self.adv.get_immediate_actions(report), list)


# ===========================================================================
# 11. Full scenario: 3 positions, 4 candidates
# ===========================================================================

class TestFullScenario(unittest.TestCase):

    def setUp(self):
        self.adv = _advisor()
        self.current = [
            _snap("aave",     0.035, alloc=40000, days_in=20),
            _snap("compound", 0.048, alloc=35000, days_in=20),
            _snap("morpho",   0.065, alloc=25000, days_in=20),
        ]
        self.candidates = [
            _snap("euler",  0.072, risk_score=20.0),
            _snap("yearn",  0.055, risk_score=15.0),
            _snap("maple",  0.090, risk_score=25.0),
            _snap("pendle", 0.045, risk_score=10.0),
        ]
        self.report = self.adv.analyze(self.current, self.candidates)

    def test_actions_sorted_descending(self):
        gains = [a.apy_gain_bps for a in self.report.actions]
        self.assertEqual(gains, sorted(gains, reverse=True))

    def test_verdict_not_hold(self):
        self.assertNotEqual(self.report.verdict, "HOLD")

    def test_total_capital_correct(self):
        self.assertAlmostEqual(self.report.total_capital_usd, 100000.0, places=2)

    def test_no_locked_actions(self):
        locked = [a for a in self.report.actions if a.blocked_by_lock]
        self.assertEqual(len(locked), 0)

    def test_aave_gets_rotated(self):
        froms = [a.from_adapter for a in self.report.actions]
        self.assertIn("aave", froms)

    def test_maple_is_top_opportunity(self):
        self.assertEqual(self.report.top_opportunity, "maple")

    def test_annual_gain_positive(self):
        self.assertGreater(self.report.estimated_annual_gain_usd, 0)

    def test_all_actions_have_reason(self):
        for a in self.report.actions:
            self.assertTrue(a.reason)

    def test_no_self_rotation(self):
        for a in self.report.actions:
            self.assertNotEqual(a.from_adapter, a.to_adapter)


if __name__ == "__main__":
    unittest.main()
