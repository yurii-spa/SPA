"""Tests for MP-692: PortfolioAttributionEngine (≥65 tests).

Run with:
    python3 -m unittest spa_core.tests.test_portfolio_attribution_engine -v

Pure stdlib unittest — no pytest, no numpy, no pandas.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.portfolio_attribution_engine import (
    AttributionResult,
    MAX_ENTRIES,
    PortfolioAttributionEngine,
    PortfolioAttributionReport,
    Segment,
    _atomic_write,
    _skill_assessment,
    compute_allocation_effect,
    compute_interaction_effect,
    compute_selection_effect,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EPSILON = 1e-9  # floating-point tolerance


def _approx(a: float, b: float, tol: float = 1e-7) -> bool:
    return abs(a - b) < tol


def _make_seg(
    name="SegA",
    pw=0.40,
    bw=0.35,
    pr=5.0,
    br=4.0,
) -> Segment:
    return Segment(
        name=name,
        portfolio_weight=pw,
        benchmark_weight=bw,
        portfolio_return_pct=pr,
        benchmark_return_pct=br,
    )


def _engine(tmp_dir: str) -> PortfolioAttributionEngine:
    return PortfolioAttributionEngine(data_dir=tmp_dir)


# ---------------------------------------------------------------------------
# 1. compute_allocation_effect
# ---------------------------------------------------------------------------


class TestComputeAllocationEffect(unittest.TestCase):

    def test_basic_positive(self):
        # (0.4 - 0.3) * 5.0 = 0.5
        self.assertAlmostEqual(compute_allocation_effect(0.4, 0.3, 5.0), 0.5)

    def test_basic_negative(self):
        # (0.2 - 0.3) * 5.0 = -0.5
        self.assertAlmostEqual(compute_allocation_effect(0.2, 0.3, 5.0), -0.5)

    def test_equal_weights_zero(self):
        self.assertAlmostEqual(compute_allocation_effect(0.3, 0.3, 4.0), 0.0)

    def test_zero_benchmark_return(self):
        # Effect is 0 regardless of weight overweight when benchmark return = 0
        self.assertAlmostEqual(compute_allocation_effect(0.6, 0.2, 0.0), 0.0)

    def test_negative_benchmark_return(self):
        # (0.4 - 0.3) * (-2.0) = -0.2
        self.assertAlmostEqual(compute_allocation_effect(0.4, 0.3, -2.0), -0.2)

    def test_formula_exact(self):
        wp, wb, rb = 0.25, 0.15, 3.6
        expected = (wp - wb) * rb
        self.assertAlmostEqual(compute_allocation_effect(wp, wb, rb), expected)

    def test_underweight_positive_return(self):
        # wp < wb, rb positive → negative allocation effect
        result = compute_allocation_effect(0.1, 0.4, 6.0)
        self.assertLess(result, 0)

    def test_overweight_positive_return(self):
        result = compute_allocation_effect(0.5, 0.2, 4.0)
        self.assertGreater(result, 0)


# ---------------------------------------------------------------------------
# 2. compute_selection_effect
# ---------------------------------------------------------------------------


class TestComputeSelectionEffect(unittest.TestCase):

    def test_basic_positive(self):
        # 0.35 * (5.0 - 4.0) = 0.35
        self.assertAlmostEqual(compute_selection_effect(0.35, 5.0, 4.0), 0.35)

    def test_basic_negative(self):
        # 0.35 * (3.0 - 4.0) = -0.35
        self.assertAlmostEqual(compute_selection_effect(0.35, 3.0, 4.0), -0.35)

    def test_equal_returns_zero(self):
        self.assertAlmostEqual(compute_selection_effect(0.5, 4.0, 4.0), 0.0)

    def test_zero_benchmark_weight(self):
        # wb = 0 → no selection effect
        self.assertAlmostEqual(compute_selection_effect(0.0, 5.0, 4.0), 0.0)

    def test_formula_exact(self):
        wb, rp, rb = 0.4, 6.5, 5.0
        expected = wb * (rp - rb)
        self.assertAlmostEqual(compute_selection_effect(wb, rp, rb), expected)

    def test_scales_with_weight(self):
        r1 = compute_selection_effect(0.2, 5.0, 3.0)
        r2 = compute_selection_effect(0.4, 5.0, 3.0)
        self.assertAlmostEqual(r2, 2 * r1)

    def test_negative_outperformance(self):
        result = compute_selection_effect(0.3, 2.0, 5.0)
        self.assertLess(result, 0)


# ---------------------------------------------------------------------------
# 3. compute_interaction_effect
# ---------------------------------------------------------------------------


class TestComputeInteractionEffect(unittest.TestCase):

    def test_basic_positive(self):
        # (0.4-0.3)*(5.0-4.0) = 0.1*1.0 = 0.1
        self.assertAlmostEqual(compute_interaction_effect(0.4, 0.3, 5.0, 4.0), 0.1)

    def test_equal_weights_zero(self):
        self.assertAlmostEqual(compute_interaction_effect(0.3, 0.3, 5.0, 4.0), 0.0)

    def test_equal_returns_zero(self):
        self.assertAlmostEqual(compute_interaction_effect(0.4, 0.3, 4.0, 4.0), 0.0)

    def test_overweight_underperform_negative(self):
        # (0.5-0.3)*(2.0-5.0) = 0.2*(-3.0) = -0.6
        self.assertAlmostEqual(compute_interaction_effect(0.5, 0.3, 2.0, 5.0), -0.6)

    def test_underweight_outperform_negative(self):
        # (0.1-0.4)*(6.0-4.0) = (-0.3)*2.0 = -0.6
        self.assertAlmostEqual(compute_interaction_effect(0.1, 0.4, 6.0, 4.0), -0.6)

    def test_formula_exact(self):
        wp, wb, rp, rb = 0.35, 0.25, 7.0, 5.5
        expected = (wp - wb) * (rp - rb)
        self.assertAlmostEqual(compute_interaction_effect(wp, wb, rp, rb), expected)

    def test_both_negative_diffs_positive(self):
        # underweight AND underperform → positive interaction
        # (0.1-0.4)*(2.0-5.0) = (-0.3)*(-3.0) = +0.9
        self.assertAlmostEqual(compute_interaction_effect(0.1, 0.4, 2.0, 5.0), 0.9)


# ---------------------------------------------------------------------------
# 4. total_active_return identity
# ---------------------------------------------------------------------------


class TestTotalActiveReturn(unittest.TestCase):

    def _compute_total(self, seg: Segment) -> float:
        alloc = compute_allocation_effect(seg.portfolio_weight, seg.benchmark_weight,
                                          seg.benchmark_return_pct)
        sel = compute_selection_effect(seg.benchmark_weight, seg.portfolio_return_pct,
                                       seg.benchmark_return_pct)
        inter = compute_interaction_effect(seg.portfolio_weight, seg.benchmark_weight,
                                           seg.portfolio_return_pct, seg.benchmark_return_pct)
        return alloc + sel + inter

    def test_identity_equals_rp_minus_rb_times_wp(self):
        """For a single segment with wb=0, total = (rp-rb)*wp."""
        # If wb=0: allocation=(wp)*rb, selection=0, interaction=(wp)*(rp-rb)
        # total = wp*rb + wp*(rp-rb) = wp*rp
        seg = Segment("X", 0.5, 0.0, 8.0, 6.0)
        total = self._compute_total(seg)
        # allocation=0.5*6=3, selection=0, interaction=0.5*2=1 → total=4
        self.assertAlmostEqual(total, 4.0)

    def test_identity_single_segment(self):
        seg = _make_seg()
        total = self._compute_total(seg)
        # expected: portfolio contribution - benchmark contribution
        expected = seg.portfolio_weight * seg.portfolio_return_pct - seg.benchmark_weight * seg.benchmark_return_pct
        self.assertAlmostEqual(total, expected, places=6)

    def test_total_is_sum_of_three(self):
        seg = _make_seg(pw=0.6, bw=0.4, pr=7.0, br=5.0)
        alloc = compute_allocation_effect(seg.portfolio_weight, seg.benchmark_weight,
                                           seg.benchmark_return_pct)
        sel = compute_selection_effect(seg.benchmark_weight, seg.portfolio_return_pct,
                                       seg.benchmark_return_pct)
        inter = compute_interaction_effect(seg.portfolio_weight, seg.benchmark_weight,
                                           seg.portfolio_return_pct, seg.benchmark_return_pct)
        total = alloc + sel + inter
        result = self._compute_total(seg)
        self.assertAlmostEqual(total, result)


# ---------------------------------------------------------------------------
# 5. _skill_assessment
# ---------------------------------------------------------------------------


class TestSkillAssessment(unittest.TestCase):

    def test_alpha_generator(self):
        self.assertEqual(_skill_assessment(1.5, 0.5), "ALPHA_GENERATOR")

    def test_alpha_generator_boundary(self):
        self.assertEqual(_skill_assessment(1.0001, 0.1), "ALPHA_GENERATOR")

    def test_not_alpha_generator_if_selection_negative(self):
        # active > 1 but selection <= 0 → MIXED
        self.assertEqual(_skill_assessment(1.5, -0.1), "MIXED")

    def test_mixed_positive_active(self):
        self.assertEqual(_skill_assessment(0.5, 0.1), "MIXED")

    def test_mixed_small_positive(self):
        self.assertEqual(_skill_assessment(0.001, 0.0), "MIXED")

    def test_beta_follower_zero(self):
        self.assertEqual(_skill_assessment(0.0, -0.2), "BETA_FOLLOWER")

    def test_beta_follower_negative_boundary(self):
        self.assertEqual(_skill_assessment(-0.5, 0.0), "BETA_FOLLOWER")

    def test_underperformer(self):
        self.assertEqual(_skill_assessment(-0.51, 0.0), "UNDERPERFORMER")

    def test_underperformer_large_negative(self):
        self.assertEqual(_skill_assessment(-5.0, 1.0), "UNDERPERFORMER")

    def test_exactly_minus_half_is_beta_follower(self):
        self.assertEqual(_skill_assessment(-0.5, 0.5), "BETA_FOLLOWER")


# ---------------------------------------------------------------------------
# 6. generate_report — single segment
# ---------------------------------------------------------------------------


class TestGenerateReportSingleSegment(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)
        self.seg = _make_seg(name="Aave", pw=0.40, bw=0.35, pr=5.0, br=4.0)
        self.report = self.engine.generate_report("r1", [self.seg])

    def test_report_id(self):
        self.assertEqual(self.report.report_id, "r1")

    def test_total_portfolio_return(self):
        expected = 0.40 * 5.0
        self.assertAlmostEqual(self.report.total_portfolio_return_pct, expected)

    def test_total_benchmark_return(self):
        expected = 0.35 * 4.0
        self.assertAlmostEqual(self.report.total_benchmark_return_pct, expected)

    def test_total_active_return_is_diff(self):
        expected = self.report.total_portfolio_return_pct - self.report.total_benchmark_return_pct
        self.assertAlmostEqual(self.report.total_active_return_pct, expected)

    def test_single_segment_result(self):
        self.assertEqual(len(self.report.segments), 1)

    def test_top_contributor_equals_top_detractor_single(self):
        # Only one segment — both point to it
        self.assertEqual(self.report.top_contributor, "Aave")
        self.assertEqual(self.report.top_detractor, "Aave")

    def test_allocation_total_equals_segment(self):
        seg_alloc = self.report.segments[0].allocation_effect
        self.assertAlmostEqual(self.report.allocation_total, seg_alloc)

    def test_selection_total_equals_segment(self):
        seg_sel = self.report.segments[0].selection_effect
        self.assertAlmostEqual(self.report.selection_total, seg_sel)

    def test_interaction_total_equals_segment(self):
        seg_inter = self.report.segments[0].interaction_effect
        self.assertAlmostEqual(self.report.interaction_total, seg_inter)

    def test_allocation_effect_value(self):
        # (0.40-0.35)*4.0 = 0.05*4=0.20
        self.assertAlmostEqual(self.report.segments[0].allocation_effect, 0.20)

    def test_selection_effect_value(self):
        # 0.35*(5.0-4.0)=0.35
        self.assertAlmostEqual(self.report.segments[0].selection_effect, 0.35)

    def test_interaction_effect_value(self):
        # (0.40-0.35)*(5.0-4.0)=0.05
        self.assertAlmostEqual(self.report.segments[0].interaction_effect, 0.05)

    def test_segment_total_active_return(self):
        seg = self.report.segments[0]
        expected = seg.allocation_effect + seg.selection_effect + seg.interaction_effect
        self.assertAlmostEqual(seg.total_active_return, expected)

    def test_summary_contains_portfolio_return(self):
        self.assertIn("2.00", self.report.summary)  # 0.4*5=2.00

    def test_summary_contains_benchmark_return(self):
        self.assertIn("1.40", self.report.summary)  # 0.35*4=1.40

    def test_summary_contains_contributor(self):
        self.assertIn("Aave", self.report.summary)

    def test_summary_contains_assessment(self):
        self.assertIn(self.report.skill_assessment, self.report.summary)

    def test_empty_segments_raises(self):
        with self.assertRaises(ValueError):
            self.engine.generate_report("bad", [])


# ---------------------------------------------------------------------------
# 7. generate_report — multiple segments
# ---------------------------------------------------------------------------


class TestGenerateReportMultipleSegments(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)
        self.segs = [
            Segment("Aave",     portfolio_weight=0.40, benchmark_weight=0.35, portfolio_return_pct=5.0, benchmark_return_pct=4.0),
            Segment("Compound", portfolio_weight=0.30, benchmark_weight=0.30, portfolio_return_pct=4.8, benchmark_return_pct=4.5),
            Segment("Morpho",   portfolio_weight=0.25, benchmark_weight=0.25, portfolio_return_pct=6.5, benchmark_return_pct=5.8),
            Segment("Cash",     portfolio_weight=0.05, benchmark_weight=0.10, portfolio_return_pct=0.0, benchmark_return_pct=0.0),
        ]
        self.report = self.engine.generate_report("multi", self.segs)

    def test_four_segment_results(self):
        self.assertEqual(len(self.report.segments), 4)

    def test_total_portfolio_return(self):
        expected = sum(s.portfolio_weight * s.portfolio_return_pct for s in self.segs)
        self.assertAlmostEqual(self.report.total_portfolio_return_pct, expected)

    def test_total_benchmark_return(self):
        expected = sum(s.benchmark_weight * s.benchmark_return_pct for s in self.segs)
        self.assertAlmostEqual(self.report.total_benchmark_return_pct, expected)

    def test_total_active_return_is_diff(self):
        expected = self.report.total_portfolio_return_pct - self.report.total_benchmark_return_pct
        self.assertAlmostEqual(self.report.total_active_return_pct, expected)

    def test_allocation_total_is_sum(self):
        expected = sum(r.allocation_effect for r in self.report.segments)
        self.assertAlmostEqual(self.report.allocation_total, expected)

    def test_selection_total_is_sum(self):
        expected = sum(r.selection_effect for r in self.report.segments)
        self.assertAlmostEqual(self.report.selection_total, expected)

    def test_interaction_total_is_sum(self):
        expected = sum(r.interaction_effect for r in self.report.segments)
        self.assertAlmostEqual(self.report.interaction_total, expected)

    def test_top_contributor_is_max(self):
        max_seg = max(self.report.segments, key=lambda r: r.total_active_return)
        self.assertEqual(self.report.top_contributor, max_seg.segment_name)

    def test_top_detractor_is_min(self):
        min_seg = min(self.report.segments, key=lambda r: r.total_active_return)
        self.assertEqual(self.report.top_detractor, min_seg.segment_name)

    def test_segment_names_preserved(self):
        names = [r.segment_name for r in self.report.segments]
        self.assertIn("Aave", names)
        self.assertIn("Cash", names)

    def test_each_segment_total_active_return_is_sum_of_three(self):
        for r in self.report.segments:
            expected = r.allocation_effect + r.selection_effect + r.interaction_effect
            self.assertAlmostEqual(r.total_active_return, expected)


# ---------------------------------------------------------------------------
# 8. skill_assessment integration
# ---------------------------------------------------------------------------


class TestSkillAssessmentIntegration(unittest.TestCase):

    def _report(self, segs):
        tmp = tempfile.mkdtemp()
        engine = _engine(tmp)
        return engine.generate_report("skill_test", segs)

    def test_alpha_generator(self):
        # High active return with strong selection
        segs = [
            Segment("Big", portfolio_weight=0.9, benchmark_weight=0.5, portfolio_return_pct=20.0, benchmark_return_pct=5.0),
        ]
        r = self._report(segs)
        # active = 0.9*20 - 0.5*5 = 18 - 2.5 = 15.5 > 1
        # selection = 0.5*(20-5) = 7.5 > 0 → ALPHA_GENERATOR
        self.assertEqual(r.skill_assessment, "ALPHA_GENERATOR")

    def test_underperformer(self):
        segs = [
            Segment("Loss", portfolio_weight=0.5, benchmark_weight=0.5, portfolio_return_pct=0.0, benchmark_return_pct=5.0),
        ]
        r = self._report(segs)
        # active = 0.5*0 - 0.5*5 = -2.5 < -0.5 → UNDERPERFORMER
        self.assertEqual(r.skill_assessment, "UNDERPERFORMER")

    def test_mixed(self):
        segs = [
            Segment("Mix", portfolio_weight=0.5, benchmark_weight=0.5, portfolio_return_pct=3.0, benchmark_return_pct=2.5),
        ]
        r = self._report(segs)
        # active = 0.5*3 - 0.5*2.5 = 1.5-1.25 = 0.25 > 0, < 1 → MIXED
        self.assertEqual(r.skill_assessment, "MIXED")

    def test_beta_follower(self):
        segs = [
            Segment("Beta", portfolio_weight=0.5, benchmark_weight=0.5, portfolio_return_pct=4.9, benchmark_return_pct=5.0),
        ]
        r = self._report(segs)
        # active = 0.5*4.9 - 0.5*5.0 = -0.05 → BETA_FOLLOWER
        self.assertEqual(r.skill_assessment, "BETA_FOLLOWER")


# ---------------------------------------------------------------------------
# 9. save_results / load_history
# ---------------------------------------------------------------------------


class TestSaveLoadHistory(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)
        self.seg = _make_seg()

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.engine.load_history(), [])

    def test_save_then_load_one_entry(self):
        report = self.engine.generate_report("s1", [self.seg])
        self.engine.save_results(report)
        history = self.engine.load_history()
        self.assertEqual(len(history), 1)

    def test_saved_report_id_preserved(self):
        report = self.engine.generate_report("my_id", [self.seg])
        self.engine.save_results(report)
        history = self.engine.load_history()
        self.assertEqual(history[0]["report_id"], "my_id")

    def test_multiple_saves_accumulate(self):
        for i in range(5):
            r = self.engine.generate_report(f"r{i}", [self.seg])
            self.engine.save_results(r)
        self.assertEqual(len(self.engine.load_history()), 5)

    def test_ring_buffer_capped_at_max(self):
        for i in range(MAX_ENTRIES + 10):
            r = self.engine.generate_report(f"r{i}", [self.seg])
            self.engine.save_results(r)
        self.assertEqual(len(self.engine.load_history()), MAX_ENTRIES)

    def test_ring_buffer_keeps_newest(self):
        for i in range(MAX_ENTRIES + 5):
            r = self.engine.generate_report(f"r{i}", [self.seg])
            self.engine.save_results(r)
        history = self.engine.load_history()
        # The oldest kept should be r5
        self.assertEqual(history[0]["report_id"], "r5")
        self.assertEqual(history[-1]["report_id"], f"r{MAX_ENTRIES + 4}")

    def test_atomic_write_creates_file(self):
        report = self.engine.generate_report("atomic", [self.seg])
        self.engine.save_results(report)
        data_file = Path(self.tmp) / "attribution_log.json"
        self.assertTrue(data_file.exists())

    def test_file_is_valid_json(self):
        report = self.engine.generate_report("json_check", [self.seg])
        self.engine.save_results(report)
        data_file = Path(self.tmp) / "attribution_log.json"
        with open(data_file) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_load_history_corrupt_json_returns_empty(self):
        data_file = Path(self.tmp) / "attribution_log.json"
        data_file.write_text("not-json{{")
        self.assertEqual(self.engine.load_history(), [])

    def test_load_history_non_list_returns_empty(self):
        data_file = Path(self.tmp) / "attribution_log.json"
        data_file.write_text('{"key": "value"}')
        self.assertEqual(self.engine.load_history(), [])

    def test_generated_at_present(self):
        report = self.engine.generate_report("ts", [self.seg])
        self.engine.save_results(report)
        history = self.engine.load_history()
        self.assertIn("generated_at", history[0])
        self.assertIsInstance(history[0]["generated_at"], (int, float))


# ---------------------------------------------------------------------------
# 10. Edge cases & consistency
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = _engine(self.tmp)

    def test_zero_weight_segment(self):
        segs = [
            Segment("A", portfolio_weight=1.0, benchmark_weight=1.0, portfolio_return_pct=5.0, benchmark_return_pct=4.0),
            Segment("B", portfolio_weight=0.0, benchmark_weight=0.0, portfolio_return_pct=3.0, benchmark_return_pct=3.0),
        ]
        r = self.engine.generate_report("zeros", segs)
        # B has no weight → no contribution
        b_result = next(x for x in r.segments if x.segment_name == "B")
        self.assertAlmostEqual(b_result.allocation_effect, 0.0)
        self.assertAlmostEqual(b_result.selection_effect, 0.0)
        self.assertAlmostEqual(b_result.interaction_effect, 0.0)

    def test_report_id_preserved(self):
        r = self.engine.generate_report("unique_id_xyz", [_make_seg()])
        self.assertEqual(r.report_id, "unique_id_xyz")

    def test_two_engines_independent_histories(self):
        tmp1 = tempfile.mkdtemp()
        tmp2 = tempfile.mkdtemp()
        e1 = _engine(tmp1)
        e2 = _engine(tmp2)
        r = e1.generate_report("e1", [_make_seg()])
        e1.save_results(r)
        self.assertEqual(len(e1.load_history()), 1)
        self.assertEqual(len(e2.load_history()), 0)

    def test_data_dir_created_if_missing(self):
        tmp = tempfile.mkdtemp()
        nested = Path(tmp) / "deep" / "nested"
        e = _engine(nested)
        r = e.generate_report("nd", [_make_seg()])
        e.save_results(r)
        self.assertTrue(nested.exists())

    def test_segments_list_in_report_is_list(self):
        r = self.engine.generate_report("lst", [_make_seg()])
        self.assertIsInstance(r.segments, list)

    def test_all_fields_present_in_report(self):
        r = self.engine.generate_report("fields", [_make_seg()])
        self.assertIsNotNone(r.report_id)
        self.assertIsNotNone(r.total_portfolio_return_pct)
        self.assertIsNotNone(r.total_benchmark_return_pct)
        self.assertIsNotNone(r.total_active_return_pct)
        self.assertIsNotNone(r.skill_assessment)
        self.assertIsNotNone(r.summary)

    def test_summary_is_nonempty_string(self):
        r = self.engine.generate_report("sum", [_make_seg()])
        self.assertIsInstance(r.summary, str)
        self.assertGreater(len(r.summary), 0)

    def test_skill_assessment_valid_value(self):
        r = self.engine.generate_report("sk", [_make_seg()])
        self.assertIn(r.skill_assessment,
                      {"ALPHA_GENERATOR", "MIXED", "BETA_FOLLOWER", "UNDERPERFORMER"})

    def test_many_segments_consistency(self):
        segs = [
            Segment(f"S{i}", portfolio_weight=1/10, benchmark_weight=1/10, portfolio_return_pct=float(i), benchmark_return_pct=float(i - 1))
            for i in range(10)
        ]
        r = self.engine.generate_report("many", segs)
        self.assertEqual(len(r.segments), 10)
        # allocation_total should equal sum of per-segment values
        computed = sum(x.allocation_effect for x in r.segments)
        self.assertAlmostEqual(r.allocation_total, computed)


if __name__ == "__main__":
    unittest.main()
