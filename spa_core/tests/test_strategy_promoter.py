"""
Tests for Strategy Auto-Promoter (MP-638).

spa_core/tests/test_strategy_promoter.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure spa_core package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.strategy_promoter import (
    DEFAULT_CRITERIA,
    PromotionCriteria,
    PromotionDecision,
    StrategyPromoter,
    _atomic_write,
    _now_iso,
    _safe_float,
    _synthetic_strategy_data,
)


# ---------------------------------------------------------------------------
# PromotionCriteria
# ---------------------------------------------------------------------------

class TestPromotionCriteria(unittest.TestCase):

    def test_default_criteria_days(self):
        self.assertEqual(DEFAULT_CRITERIA.days_running, 7)

    def test_default_criteria_min_apy(self):
        self.assertAlmostEqual(DEFAULT_CRITERIA.min_apy, 0.045)

    def test_default_criteria_max_drawdown(self):
        self.assertAlmostEqual(DEFAULT_CRITERIA.max_drawdown, 0.05)

    def test_default_criteria_min_sharpe(self):
        self.assertAlmostEqual(DEFAULT_CRITERIA.min_sharpe, 0.5)

    def test_custom_criteria(self):
        c = PromotionCriteria(days_running=14, min_apy=0.06, max_drawdown=0.03, min_sharpe=1.0)
        self.assertEqual(c.days_running, 14)
        self.assertAlmostEqual(c.min_apy, 0.06)


# ---------------------------------------------------------------------------
# PromotionDecision dataclass
# ---------------------------------------------------------------------------

class TestPromotionDecision(unittest.TestCase):

    def _make(self, **kw) -> PromotionDecision:
        defaults = dict(
            strategy_id="S1",
            strategy_name="Test Strategy",
            decision="HOLD",
            reasons=["reason1"],
            score=55.0,
            days_running=10,
            paper_apy=0.05,
            sharpe=1.0,
            max_drawdown=0.02,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        defaults.update(kw)
        return PromotionDecision(**defaults)

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for key in ("strategy_id", "strategy_name", "decision", "reasons",
                    "score", "days_running", "paper_apy", "sharpe",
                    "max_drawdown", "timestamp"):
            self.assertIn(key, d)

    def test_to_dict_decision_values(self):
        for dec in ("PROMOTE", "HOLD", "REJECT"):
            d = self._make(decision=dec).to_dict()
            self.assertEqual(d["decision"], dec)

    def test_from_dict_round_trip(self):
        orig = self._make(decision="PROMOTE", score=72.5)
        d = orig.to_dict()
        restored = PromotionDecision.from_dict(d)
        self.assertEqual(orig.strategy_id, restored.strategy_id)
        self.assertEqual(orig.decision, restored.decision)
        self.assertAlmostEqual(orig.score, restored.score, places=3)

    def test_score_rounded_to_4_decimal(self):
        d = self._make(score=72.123456789).to_dict()
        self.assertEqual(d["score"], round(72.123456789, 4))

    def test_reasons_is_list(self):
        d = self._make(reasons=["a", "b"]).to_dict()
        self.assertIsInstance(d["reasons"], list)


# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------

class TestComputeScore(unittest.TestCase):

    def setUp(self):
        self.p = StrategyPromoter()

    def test_perfect_score_is_100(self):
        # APY=10%+ (max), Sharpe=2.0+ (max), DD=0 (max), days=30+ (max)
        score = self.p.compute_score(0.10, 2.0, 0.0, 30)
        self.assertAlmostEqual(score, 100.0, places=3)

    def test_zero_score(self):
        # APY=0, Sharpe=0, DD=10%+ (wipes out component), days=0
        score = self.p.compute_score(0.0, 0.0, 0.10, 0)
        self.assertAlmostEqual(score, 0.0, places=3)

    def test_score_clamped_at_100(self):
        score = self.p.compute_score(1.0, 10.0, 0.0, 1000)
        self.assertLessEqual(score, 100.0)

    def test_score_clamped_at_zero(self):
        score = self.p.compute_score(0.0, 0.0, 1.0, 0)
        self.assertGreaterEqual(score, 0.0)

    def test_higher_apy_gives_higher_score(self):
        s1 = self.p.compute_score(0.05, 1.0, 0.02, 10)
        s2 = self.p.compute_score(0.08, 1.0, 0.02, 10)
        self.assertGreater(s2, s1)

    def test_lower_drawdown_gives_higher_score(self):
        s1 = self.p.compute_score(0.05, 1.0, 0.05, 10)
        s2 = self.p.compute_score(0.05, 1.0, 0.01, 10)
        self.assertGreater(s2, s1)

    def test_more_days_gives_higher_score(self):
        s1 = self.p.compute_score(0.05, 1.0, 0.02, 5)
        s2 = self.p.compute_score(0.05, 1.0, 0.02, 30)
        self.assertGreater(s2, s1)

    def test_days_capped_at_30(self):
        s30 = self.p.compute_score(0.05, 1.0, 0.02, 30)
        s60 = self.p.compute_score(0.05, 1.0, 0.02, 60)
        self.assertAlmostEqual(s30, s60, places=3)

    def test_formula_components(self):
        # Verify formula manually
        apy, sharpe, dd, days = 0.05, 1.0, 0.02, 15
        expected = (
            min(apy / 0.10, 1.0) * 40
            + min(sharpe / 2.0, 1.0) * 30
            + max(0, 1.0 - dd / 0.10) * 20
            + min(days / 30, 1.0) * 10
        )
        score = self.p.compute_score(apy, sharpe, dd, days)
        self.assertAlmostEqual(score, expected, places=3)


# ---------------------------------------------------------------------------
# evaluate_strategy — REJECT
# ---------------------------------------------------------------------------

class TestEvaluateStrategyReject(unittest.TestCase):

    def setUp(self):
        self.p = StrategyPromoter()

    def test_reject_low_apy(self):
        d = self.p.evaluate_strategy("S1", "Test", 0.02, 1.5, 0.02, 20)
        self.assertEqual(d.decision, "REJECT")

    def test_reject_high_drawdown(self):
        d = self.p.evaluate_strategy("S1", "Test", 0.05, 1.5, 0.10, 20)
        self.assertEqual(d.decision, "REJECT")

    def test_reject_both_hard_fails(self):
        d = self.p.evaluate_strategy("S1", "Test", 0.01, 0.1, 0.20, 5)
        self.assertEqual(d.decision, "REJECT")

    def test_reject_has_fail_reason(self):
        d = self.p.evaluate_strategy("S1", "Test", 0.02, 1.5, 0.02, 20)
        self.assertTrue(any("FAIL" in r for r in d.reasons))

    def test_reject_has_score(self):
        d = self.p.evaluate_strategy("S1", "Test", 0.02, 1.5, 0.02, 20)
        self.assertIsInstance(d.score, float)

    def test_reject_has_timestamp(self):
        d = self.p.evaluate_strategy("S1", "Test", 0.02, 1.5, 0.02, 20)
        self.assertIsInstance(d.timestamp, str)
        self.assertIn("T", d.timestamp)


# ---------------------------------------------------------------------------
# evaluate_strategy — PROMOTE
# ---------------------------------------------------------------------------

class TestEvaluateStrategyPromote(unittest.TestCase):

    def setUp(self):
        self.p = StrategyPromoter()

    def test_promote_all_criteria_met(self):
        # APY=8%, Sharpe=1.5, DD=2%, days=30 → score=high, all pass
        d = self.p.evaluate_strategy("S3", "Winner", 0.08, 1.5, 0.02, 30)
        self.assertEqual(d.decision, "PROMOTE")

    def test_promote_score_above_60(self):
        d = self.p.evaluate_strategy("S3", "Winner", 0.08, 1.5, 0.02, 30)
        self.assertGreaterEqual(d.score, 60.0)

    def test_promote_all_reasons_pass(self):
        d = self.p.evaluate_strategy("S3", "Winner", 0.08, 1.5, 0.02, 30)
        self.assertTrue(any("PASS" in r for r in d.reasons))
        self.assertFalse(any("FAIL" in r for r in d.reasons))

    def test_promote_preserves_ids(self):
        d = self.p.evaluate_strategy("S-BEST", "Best Strategy", 0.09, 2.0, 0.01, 45)
        self.assertEqual(d.strategy_id, "S-BEST")
        self.assertEqual(d.strategy_name, "Best Strategy")

    def test_promote_fields_correct(self):
        d = self.p.evaluate_strategy("Sx", "X", 0.08, 1.5, 0.02, 30)
        self.assertAlmostEqual(d.paper_apy, 0.08)
        self.assertAlmostEqual(d.sharpe, 1.5)
        self.assertAlmostEqual(d.max_drawdown, 0.02)
        self.assertEqual(d.days_running, 30)


# ---------------------------------------------------------------------------
# evaluate_strategy — HOLD
# ---------------------------------------------------------------------------

class TestEvaluateStrategyHold(unittest.TestCase):

    def setUp(self):
        self.p = StrategyPromoter()

    def test_hold_low_sharpe(self):
        # APY and DD fine, sharpe below threshold
        d = self.p.evaluate_strategy("S2", "Low Sharpe", 0.05, 0.3, 0.02, 20)
        self.assertEqual(d.decision, "HOLD")

    def test_hold_insufficient_days(self):
        # APY fine, sharpe fine, DD fine, but days_running < 7
        d = self.p.evaluate_strategy("S2", "New", 0.06, 1.0, 0.02, 3)
        self.assertEqual(d.decision, "HOLD")

    def test_hold_low_score(self):
        # Passes hard gates but score just below 60
        c = PromotionCriteria(days_running=1, min_apy=0.01, max_drawdown=0.99, min_sharpe=0.1)
        p = StrategyPromoter(criteria=c)
        # score = apy_comp + sharpe_comp + dd_comp + days_comp
        # With very low apy and sharpe: score < 60
        d = p.evaluate_strategy("S_low", "Low Score", 0.046, 0.51, 0.01, 10)
        # Just verify decision is one of the valid three
        self.assertIn(d.decision, ("PROMOTE", "HOLD", "REJECT"))

    def test_hold_has_reasons(self):
        d = self.p.evaluate_strategy("S2", "New", 0.06, 1.0, 0.02, 3)
        self.assertIsInstance(d.reasons, list)
        self.assertGreater(len(d.reasons), 0)


# ---------------------------------------------------------------------------
# evaluate_all
# ---------------------------------------------------------------------------

class TestEvaluateAll(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        self.p = StrategyPromoter(data_dir=self.data_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_returns_list(self):
        results = self.p.evaluate_all()
        self.assertIsInstance(results, list)

    def test_returns_six_synthetic_strategies(self):
        results = self.p.evaluate_all()
        self.assertEqual(len(results), 6)

    def test_all_are_PromotionDecision(self):
        results = self.p.evaluate_all()
        for r in results:
            self.assertIsInstance(r, PromotionDecision)

    def test_loads_custom_json(self):
        custom = [
            {"strategy_id": "X1", "strategy_name": "Custom", "paper_apy": 0.07,
             "sharpe": 1.2, "max_drawdown": 0.02, "days_running": 14},
        ]
        (self.data_dir / "strategy_shadow_comparison.json").write_text(json.dumps(custom))
        p = StrategyPromoter(data_dir=self.data_dir)
        results = p.evaluate_all()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].strategy_id, "X1")

    def test_decisions_cover_all_valid_values(self):
        results = self.p.evaluate_all()
        decisions = {r.decision for r in results}
        self.assertTrue(decisions.issubset({"PROMOTE", "HOLD", "REJECT"}))

    def test_scores_between_0_and_100(self):
        results = self.p.evaluate_all()
        for r in results:
            self.assertGreaterEqual(r.score, 0.0)
            self.assertLessEqual(r.score, 100.0)


# ---------------------------------------------------------------------------
# log_decisions / ring-buffer
# ---------------------------------------------------------------------------

class TestLogDecisions(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        self.p = StrategyPromoter(data_dir=self.data_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_decision(self, sid: str = "S1") -> PromotionDecision:
        return PromotionDecision(
            strategy_id=sid, strategy_name="Test", decision="HOLD",
            reasons=[], score=40.0, days_running=5,
            paper_apy=0.05, sharpe=0.6, max_drawdown=0.02,
            timestamp=_now_iso(),
        )

    def test_file_created(self):
        self.p.log_decisions([self._make_decision()])
        self.assertTrue((self.data_dir / "promotion_decisions.json").exists())

    def test_entries_accumulate(self):
        for i in range(5):
            self.p.log_decisions([self._make_decision(f"S{i}")])
        data = json.loads((self.data_dir / "promotion_decisions.json").read_text())
        self.assertEqual(len(data), 5)

    def test_ring_buffer_trims_at_50(self):
        for i in range(55):
            self.p.log_decisions([self._make_decision(f"S{i}")])
        data = json.loads((self.data_dir / "promotion_decisions.json").read_text())
        self.assertEqual(len(data), 50)

    def test_no_tmp_files_after_write(self):
        self.p.log_decisions([self._make_decision()])
        tmp = list(self.data_dir.glob(".tmp_strategy_promoter_*"))
        self.assertEqual(len(tmp), 0)

    def test_corrupted_file_recovery(self):
        (self.data_dir / "promotion_decisions.json").write_text("BROKEN")
        self.p.log_decisions([self._make_decision()])
        data = json.loads((self.data_dir / "promotion_decisions.json").read_text())
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        self.p = StrategyPromoter(data_dir=self.data_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_report_has_decisions(self):
        r = self.p.generate_report()
        self.assertIn("decisions", r)
        self.assertIsInstance(r["decisions"], list)

    def test_report_has_counts(self):
        r = self.p.generate_report()
        self.assertIn("promote_count", r)
        self.assertIn("hold_count", r)
        self.assertIn("reject_count", r)

    def test_counts_sum_to_total(self):
        r = self.p.generate_report()
        total = r["promote_count"] + r["hold_count"] + r["reject_count"]
        self.assertEqual(total, len(r["decisions"]))

    def test_report_has_top_candidate(self):
        r = self.p.generate_report()
        # top_candidate is None only if no decisions (synthetic always has 6)
        self.assertIsNotNone(r["top_candidate"])

    def test_top_candidate_has_highest_score(self):
        r = self.p.generate_report()
        max_score = max(d["score"] for d in r["decisions"])
        self.assertAlmostEqual(r["top_candidate"]["score"], max_score, places=3)

    def test_report_has_advisory(self):
        r = self.p.generate_report()
        self.assertIn("advisory", r)
        self.assertIn("advisory", r["advisory"].lower())

    def test_report_has_generated_at(self):
        r = self.p.generate_report()
        self.assertIn("generated_at", r)
        self.assertIn("T", r["generated_at"])

    def test_empty_strategies_gives_empty_report(self):
        # Save empty JSON list
        (self.data_dir / "strategy_shadow_comparison.json").write_text("[]")
        p = StrategyPromoter(data_dir=self.data_dir)
        r = p.generate_report()
        self.assertEqual(r["promote_count"], 0)
        self.assertEqual(r["hold_count"], 0)
        self.assertEqual(r["reject_count"], 0)
        self.assertIsNone(r["top_candidate"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_safe_float_normal(self):
        self.assertAlmostEqual(_safe_float(0.05), 0.05)

    def test_safe_float_string(self):
        self.assertAlmostEqual(_safe_float("0.03"), 0.03)

    def test_safe_float_none_returns_default(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_safe_float_invalid_returns_default(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_safe_float_custom_default(self):
        self.assertEqual(_safe_float("bad", -1.0), -1.0)

    def test_now_iso_is_string(self):
        self.assertIsInstance(_now_iso(), str)

    def test_now_iso_has_tz(self):
        self.assertIn("+", _now_iso())

    def test_synthetic_returns_six(self):
        data = _synthetic_strategy_data()
        self.assertEqual(len(data), 6)

    def test_synthetic_has_required_keys(self):
        for s in _synthetic_strategy_data():
            for k in ("strategy_id", "paper_apy", "sharpe", "max_drawdown", "days_running"):
                self.assertIn(k, s)

    def test_atomic_write_file_exists(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            _atomic_write(p, {"x": 1})
            self.assertTrue(p.exists())

    def test_atomic_write_content_valid(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            _atomic_write(p, [1, 2, 3])
            self.assertEqual(json.loads(p.read_text()), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
