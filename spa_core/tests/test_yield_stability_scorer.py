"""
Unit tests for spa_core.analytics.yield_stability_scorer (SPA-V526 / MP-602).

Pure stdlib unittest. All file-touching tests use tempfile so the real
data/yield_stability_report.json is never clobbered.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics import yield_stability_scorer as yss
from spa_core.analytics.yield_stability_scorer import (
    RISK_FREE_PCT,
    MIN_POINTS_HIGH,
    MIN_POINTS_MEDIUM,
    CV_EXCELLENT,
    CV_GOOD,
    CV_FAIR,
    EPS,
    AdapterStability,
    StabilityReport,
    YieldStabilityScorer,
    _mean,
    _stddev,
    _coefficient_of_variation,
    _apy_drawdown_pct,
    _extract_apy_series,
    _stability_score,
    _grade,
    _confidence,
    _is_number,
    _extract_current_apy,
)


# ---------------------------------------------------------------------------
# Helpers to build temp data dirs
# ---------------------------------------------------------------------------

def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _make_history(series_map):
    """series_map: {key: [apy floats]} -> apy_history.json dict."""
    ph = {}
    for key, vals in series_map.items():
        ph[key] = [
            {"ts": f"2026-03-{i + 1:02d}T00:00:00+00:00",
             "apy": v, "tvl_usd": 1000.0}
            for i, v in enumerate(vals)
        ]
    return {"protocol_history": ph, "last_updated": "2026-03-31T00:00:00+00:00"}


# ===========================================================================
# Constants
# ===========================================================================

class TestConstants(unittest.TestCase):
    def test_risk_free_pct(self):
        self.assertEqual(RISK_FREE_PCT, 4.0)

    def test_min_points_high(self):
        self.assertEqual(MIN_POINTS_HIGH, 7)

    def test_min_points_medium(self):
        self.assertEqual(MIN_POINTS_MEDIUM, 3)

    def test_cv_excellent(self):
        self.assertEqual(CV_EXCELLENT, 0.05)

    def test_cv_good(self):
        self.assertEqual(CV_GOOD, 0.15)

    def test_cv_fair(self):
        self.assertEqual(CV_FAIR, 0.30)

    def test_eps(self):
        self.assertEqual(EPS, 1e-9)

    def test_cv_ordering(self):
        self.assertLess(CV_EXCELLENT, CV_GOOD)
        self.assertLess(CV_GOOD, CV_FAIR)

    def test_points_ordering(self):
        self.assertGreater(MIN_POINTS_HIGH, MIN_POINTS_MEDIUM)


# ===========================================================================
# _is_number
# ===========================================================================

class TestIsNumber(unittest.TestCase):
    def test_int(self):
        self.assertTrue(_is_number(5))

    def test_float(self):
        self.assertTrue(_is_number(5.5))

    def test_zero(self):
        self.assertTrue(_is_number(0))

    def test_negative(self):
        self.assertTrue(_is_number(-3.2))

    def test_bool_true_rejected(self):
        self.assertFalse(_is_number(True))

    def test_bool_false_rejected(self):
        self.assertFalse(_is_number(False))

    def test_string_rejected(self):
        self.assertFalse(_is_number("5"))

    def test_none_rejected(self):
        self.assertFalse(_is_number(None))

    def test_nan_rejected(self):
        self.assertFalse(_is_number(float("nan")))

    def test_inf_rejected(self):
        self.assertFalse(_is_number(float("inf")))

    def test_neg_inf_rejected(self):
        self.assertFalse(_is_number(float("-inf")))

    def test_list_rejected(self):
        self.assertFalse(_is_number([1, 2]))


# ===========================================================================
# _mean
# ===========================================================================

class TestMean(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_single(self):
        self.assertEqual(_mean([5.0]), 5.0)

    def test_basic(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_negatives(self):
        self.assertAlmostEqual(_mean([-1.0, 1.0]), 0.0)

    def test_floats(self):
        self.assertAlmostEqual(_mean([2.5, 7.5]), 5.0)

    def test_int_input(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_large(self):
        self.assertAlmostEqual(_mean([10.0] * 100), 10.0)


# ===========================================================================
# _stddev
# ===========================================================================

class TestStddev(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_stddev([]), 0.0)

    def test_single(self):
        self.assertEqual(_stddev([5.0]), 0.0)

    def test_constant(self):
        self.assertEqual(_stddev([3.0, 3.0, 3.0]), 0.0)

    def test_population_two_points(self):
        # population stddev of [2,4] = sqrt(((2-3)^2+(4-3)^2)/2) = 1.0
        self.assertAlmostEqual(_stddev([2.0, 4.0]), 1.0)

    def test_known_value(self):
        # population stddev of [1,2,3,4,5] = sqrt(2) ~ 1.4142
        self.assertAlmostEqual(_stddev([1.0, 2.0, 3.0, 4.0, 5.0]), math.sqrt(2.0))

    def test_nonnegative(self):
        self.assertGreaterEqual(_stddev([1.0, 100.0]), 0.0)


# ===========================================================================
# _coefficient_of_variation
# ===========================================================================

class TestCV(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_coefficient_of_variation([]), 0.0)

    def test_single(self):
        # single point -> stddev 0 -> cv 0
        self.assertEqual(_coefficient_of_variation([5.0]), 0.0)

    def test_constant(self):
        self.assertEqual(_coefficient_of_variation([4.0, 4.0, 4.0]), 0.0)

    def test_mean_zero(self):
        # mean ~ 0 -> guarded -> 0.0
        self.assertEqual(_coefficient_of_variation([-1.0, 1.0]), 0.0)

    def test_known_value(self):
        # [2,4]: stddev=1, mean=3 -> cv = 1/3
        self.assertAlmostEqual(_coefficient_of_variation([2.0, 4.0]), 1.0 / 3.0)

    def test_uses_abs_mean(self):
        cv = _coefficient_of_variation([-2.0, -4.0])
        self.assertAlmostEqual(cv, 1.0 / 3.0)

    def test_nonnegative(self):
        self.assertGreaterEqual(_coefficient_of_variation([5.0, 6.0, 7.0]), 0.0)


# ===========================================================================
# _apy_drawdown_pct
# ===========================================================================

class TestDrawdown(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_apy_drawdown_pct([]), 0.0)

    def test_single(self):
        self.assertEqual(_apy_drawdown_pct([5.0]), 0.0)

    def test_only_rising(self):
        self.assertEqual(_apy_drawdown_pct([1.0, 2.0, 3.0]), 0.0)

    def test_simple_decline(self):
        self.assertAlmostEqual(_apy_drawdown_pct([8.0, 5.0]), 3.0)

    def test_peak_then_trough(self):
        self.assertAlmostEqual(_apy_drawdown_pct([5.0, 8.0, 5.0]), 3.0)

    def test_multiple_peaks(self):
        # peak 10 -> trough 2 -> recover 6 -> ... max dd 8
        self.assertAlmostEqual(_apy_drawdown_pct([10.0, 2.0, 6.0, 9.0]), 8.0)

    def test_recovery_then_bigger_drop(self):
        self.assertAlmostEqual(
            _apy_drawdown_pct([6.0, 8.0, 7.0, 10.0, 3.0]), 7.0
        )

    def test_flat(self):
        self.assertEqual(_apy_drawdown_pct([4.0, 4.0, 4.0]), 0.0)


# ===========================================================================
# _extract_apy_series
# ===========================================================================

class TestExtractApySeries(unittest.TestCase):
    def test_basic(self):
        pts = [{"apy": 1.0}, {"apy": 2.0}, {"apy": 3.0}]
        self.assertEqual(_extract_apy_series(pts), [1.0, 2.0, 3.0])

    def test_preserves_order(self):
        pts = [{"apy": 3.0}, {"apy": 1.0}, {"apy": 2.0}]
        self.assertEqual(_extract_apy_series(pts), [3.0, 1.0, 2.0])

    def test_skip_missing_key(self):
        pts = [{"apy": 1.0}, {"tvl_usd": 5}, {"apy": 2.0}]
        self.assertEqual(_extract_apy_series(pts), [1.0, 2.0])

    def test_skip_bool(self):
        pts = [{"apy": True}, {"apy": 2.0}]
        self.assertEqual(_extract_apy_series(pts), [2.0])

    def test_skip_string(self):
        pts = [{"apy": "x"}, {"apy": 2.0}]
        self.assertEqual(_extract_apy_series(pts), [2.0])

    def test_skip_nan(self):
        pts = [{"apy": float("nan")}, {"apy": 2.0}]
        self.assertEqual(_extract_apy_series(pts), [2.0])

    def test_skip_non_dict(self):
        pts = [{"apy": 1.0}, "junk", 5, {"apy": 2.0}]
        self.assertEqual(_extract_apy_series(pts), [1.0, 2.0])

    def test_non_list_input(self):
        self.assertEqual(_extract_apy_series("nope"), [])

    def test_none_input(self):
        self.assertEqual(_extract_apy_series(None), [])

    def test_empty_list(self):
        self.assertEqual(_extract_apy_series([]), [])

    def test_int_apy(self):
        self.assertEqual(_extract_apy_series([{"apy": 5}]), [5.0])


# ===========================================================================
# _stability_score
# ===========================================================================

class TestStabilityScore(unittest.TestCase):
    def test_zero_cv(self):
        self.assertEqual(_stability_score(0.0), 100.0)

    def test_negative_cv_clamps_high(self):
        self.assertEqual(_stability_score(-0.5), 100.0)

    def test_at_cv_fair_is_zero(self):
        self.assertAlmostEqual(_stability_score(CV_FAIR), 0.0)

    def test_above_cv_fair_is_zero(self):
        self.assertEqual(_stability_score(1.0), 0.0)

    def test_midpoint(self):
        # cv = CV_FAIR/2 -> 50
        self.assertAlmostEqual(_stability_score(CV_FAIR / 2.0), 50.0)

    def test_monotonic_decreasing(self):
        prev = 101.0
        for cv in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.5]:
            s = _stability_score(cv)
            self.assertLessEqual(s, prev)
            prev = s

    def test_in_range(self):
        for cv in [0.0, 0.01, 0.1, 0.3, 0.9, 5.0]:
            s = _stability_score(cv)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_excellent_cv_high_score(self):
        self.assertGreater(_stability_score(CV_EXCELLENT), 80.0)


# ===========================================================================
# _grade
# ===========================================================================

class TestGrade(unittest.TestCase):
    def test_a_at_zero(self):
        self.assertEqual(_grade(0.0), "A")

    def test_a_at_boundary(self):
        self.assertEqual(_grade(CV_EXCELLENT), "A")

    def test_b_just_above_excellent(self):
        self.assertEqual(_grade(CV_EXCELLENT + 0.001), "B")

    def test_b_at_good_boundary(self):
        self.assertEqual(_grade(CV_GOOD), "B")

    def test_c_just_above_good(self):
        self.assertEqual(_grade(CV_GOOD + 0.001), "C")

    def test_c_at_fair_boundary(self):
        self.assertEqual(_grade(CV_FAIR), "C")

    def test_d_just_above_fair(self):
        self.assertEqual(_grade(CV_FAIR + 0.001), "D")

    def test_d_large(self):
        self.assertEqual(_grade(2.0), "D")

    def test_a_small(self):
        self.assertEqual(_grade(0.01), "A")


# ===========================================================================
# _confidence
# ===========================================================================

class TestConfidence(unittest.TestCase):
    def test_unknown_zero(self):
        self.assertEqual(_confidence(0), "UNKNOWN")

    def test_low_one(self):
        self.assertEqual(_confidence(1), "LOW")

    def test_low_two(self):
        self.assertEqual(_confidence(2), "LOW")

    def test_medium_three(self):
        self.assertEqual(_confidence(3), "MEDIUM")

    def test_medium_six(self):
        self.assertEqual(_confidence(6), "MEDIUM")

    def test_high_seven(self):
        self.assertEqual(_confidence(7), "HIGH")

    def test_high_large(self):
        self.assertEqual(_confidence(90), "HIGH")

    def test_boundary_high(self):
        self.assertEqual(_confidence(MIN_POINTS_HIGH), "HIGH")

    def test_boundary_medium(self):
        self.assertEqual(_confidence(MIN_POINTS_MEDIUM), "MEDIUM")


# ===========================================================================
# _extract_current_apy
# ===========================================================================

class TestExtractCurrentApy(unittest.TestCase):
    def test_apy_pct_priority(self):
        self.assertEqual(_extract_current_apy({"apy_pct": 6.0, "apy": 5.0}), 6.0)

    def test_apy_fallback(self):
        self.assertEqual(_extract_current_apy({"apy": 4.8}), 4.8)

    def test_mock_apy_ethereum_usdc(self):
        entry = {"mock_apy": {"ethereum": {"USDC": 4.2, "USDT": 3.8}}}
        self.assertEqual(_extract_current_apy(entry), 4.2)

    def test_mock_apy_other_chain(self):
        entry = {"mock_apy": {"arbitrum": {"DAI": 3.5}}}
        self.assertEqual(_extract_current_apy(entry), 3.5)

    def test_none_when_empty(self):
        self.assertIsNone(_extract_current_apy({}))

    def test_none_when_not_dict(self):
        self.assertIsNone(_extract_current_apy("x"))

    def test_bool_apy_rejected(self):
        self.assertIsNone(_extract_current_apy({"apy": True}))


# ===========================================================================
# Fail-safe loaders
# ===========================================================================

class TestLoaders(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scorer(self):
        return YieldStabilityScorer(data_path=self._tmp)

    def test_missing_apy_history(self):
        self.assertEqual(self._scorer().load_apy_history(), {})

    def test_missing_status(self):
        self.assertEqual(self._scorer().load_adapter_status(), {})

    def test_missing_watchdog(self):
        self.assertEqual(self._scorer().load_watchdog_history(), {})

    def test_empty_dict(self):
        _write_json(os.path.join(self._tmp, "apy_history.json"), {})
        self.assertEqual(self._scorer().load_apy_history(), {})

    def test_malformed_json(self):
        with open(os.path.join(self._tmp, "apy_history.json"), "w") as fh:
            fh.write("{not valid json")
        self.assertEqual(self._scorer().load_apy_history(), {})

    def test_list_instead_of_dict(self):
        _write_json(os.path.join(self._tmp, "apy_history.json"), [1, 2, 3])
        self.assertEqual(self._scorer().load_apy_history(), {})

    def test_string_instead_of_dict(self):
        _write_json(os.path.join(self._tmp, "adapter_status.json"), "hello")
        self.assertEqual(self._scorer().load_adapter_status(), {})

    def test_number_instead_of_dict(self):
        _write_json(os.path.join(self._tmp, "adapter_status.json"), 42)
        self.assertEqual(self._scorer().load_adapter_status(), {})

    def test_valid_history(self):
        _write_json(
            os.path.join(self._tmp, "apy_history.json"),
            _make_history({"a": [1.0, 2.0]}),
        )
        loaded = self._scorer().load_apy_history()
        self.assertIn("protocol_history", loaded)


# ===========================================================================
# _collect_series
# ===========================================================================

class TestCollectSeries(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scorer(self):
        return YieldStabilityScorer(data_path=self._tmp)

    def _hist(self, m):
        _write_json(os.path.join(self._tmp, "apy_history.json"), _make_history(m))

    def _status(self, obj):
        _write_json(os.path.join(self._tmp, "adapter_status.json"), obj)

    def test_empty_universe(self):
        self.assertEqual(self._scorer()._collect_series(), {})

    def test_history_primary(self):
        self._hist({"aave-v3": [5.0, 5.1, 5.2]})
        series = self._scorer()._collect_series()
        self.assertEqual(series["aave-v3"], [5.0, 5.1, 5.2])

    def test_skip_service_keys_in_history(self):
        h = _make_history({"good": [1.0]})
        h["protocol_history"]["_meta"] = [{"apy": 9.0}]
        h["protocol_history"]["schema_version"] = [{"apy": 9.0}]
        _write_json(os.path.join(self._tmp, "apy_history.json"), h)
        series = self._scorer()._collect_series()
        self.assertIn("good", series)
        self.assertNotIn("_meta", series)
        self.assertNotIn("schema_version", series)

    def test_status_seeds_missing_adapter(self):
        self._hist({})
        self._status({"adapters": [{"protocol_key": "compound-v3", "apy_pct": 4.8}]})
        series = self._scorer()._collect_series()
        self.assertEqual(series["compound-v3"], [4.8])

    def test_history_overrides_status(self):
        self._hist({"aave-v3": [5.0, 5.1]})
        self._status({"adapters": [{"protocol_key": "aave-v3", "apy_pct": 99.0}]})
        series = self._scorer()._collect_series()
        # history present -> not overwritten by status current apy
        self.assertEqual(series["aave-v3"], [5.0, 5.1])

    def test_status_zero_point_when_no_apy(self):
        self._hist({})
        self._status({"adapters": [{"protocol_key": "morpho", "foo": 1}]})
        series = self._scorer()._collect_series()
        self.assertEqual(series["morpho"], [])

    def test_top_level_protocol_keys(self):
        self._hist({})
        self._status({"compound_v3": {"apy": 4.8, "protocol": "Compound"}})
        series = self._scorer()._collect_series()
        self.assertIn("compound_v3", series)
        self.assertEqual(series["compound_v3"], [4.8])

    def test_dedup_across_sources(self):
        self._hist({"aave-v3": [5.0]})
        self._status({
            "adapters": [{"protocol_key": "aave-v3", "apy_pct": 5.0}],
            "aave-v3": {"apy": 5.0},
        })
        series = self._scorer()._collect_series()
        # single key, history wins
        self.assertEqual(series["aave-v3"], [5.0])


# ===========================================================================
# score_adapter math
# ===========================================================================

class TestScoreAdapter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.s = YieldStabilityScorer(data_path=self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_hand_computed(self):
        # series [2,4]: mean=3, std=1, cv=1/3, dd=0, latest=4
        a = self.s.score_adapter("x", [2.0, 4.0])
        self.assertEqual(a.n_points, 2)
        self.assertAlmostEqual(a.mean_apy_pct, 3.0)
        self.assertAlmostEqual(a.std_apy_pct, 1.0)
        self.assertAlmostEqual(a.cv, 1.0 / 3.0)
        self.assertAlmostEqual(a.apy_drawdown_pct, 0.0)
        self.assertAlmostEqual(a.latest_apy_pct, 4.0)
        self.assertAlmostEqual(a.excess_yield_pct, 3.0 - RISK_FREE_PCT)

    def test_grade_and_score_consistent(self):
        a = self.s.score_adapter("x", [5.0, 5.0, 5.0])  # cv 0
        self.assertEqual(a.grade, "A")
        self.assertEqual(a.stability_score, 100.0)
        self.assertEqual(a.confidence, "MEDIUM")

    def test_drawdown_computed(self):
        a = self.s.score_adapter("x", [8.0, 5.0, 6.0])
        self.assertAlmostEqual(a.apy_drawdown_pct, 3.0)

    def test_zero_points(self):
        a = self.s.score_adapter("x", [])
        self.assertEqual(a.n_points, 0)
        self.assertEqual(a.confidence, "UNKNOWN")
        self.assertEqual(a.stability_score, 0.0)
        self.assertEqual(a.mean_apy_pct, 0.0)
        self.assertEqual(a.latest_apy_pct, 0.0)

    def test_single_point(self):
        a = self.s.score_adapter("x", [5.0])
        self.assertEqual(a.n_points, 1)
        self.assertEqual(a.confidence, "LOW")
        self.assertEqual(a.std_apy_pct, 0.0)
        self.assertEqual(a.cv, 0.0)
        self.assertEqual(a.stability_score, 100.0)

    def test_high_confidence(self):
        a = self.s.score_adapter("x", [5.0] * 7)
        self.assertEqual(a.confidence, "HIGH")

    def test_bool_filtered(self):
        a = self.s.score_adapter("x", [5.0, True, 5.0])
        self.assertEqual(a.n_points, 2)

    def test_non_list_input(self):
        a = self.s.score_adapter("x", None)
        self.assertEqual(a.n_points, 0)

    def test_rank_none_initially(self):
        a = self.s.score_adapter("x", [5.0])
        self.assertIsNone(a.rank)


# ===========================================================================
# score_all ranking
# ===========================================================================

class TestScoreAll(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _setup(self, hist):
        _write_json(
            os.path.join(self._tmp, "apy_history.json"), _make_history(hist)
        )
        return YieldStabilityScorer(data_path=self._tmp)

    def test_ranks_assigned_1_to_n(self):
        s = self._setup({
            "steady": [5.0, 5.0, 5.0],
            "erratic": [2.0, 8.0, 2.0, 8.0],
            "mid": [5.0, 5.5, 5.0],
        })
        ranked = s.score_all()
        self.assertEqual([a.rank for a in ranked], [1, 2, 3])

    def test_most_stable_first(self):
        s = self._setup({
            "steady": [5.0, 5.0, 5.0],
            "erratic": [1.0, 9.0, 1.0],
        })
        ranked = s.score_all()
        self.assertEqual(ranked[0].adapter_key, "steady")
        self.assertGreaterEqual(ranked[0].stability_score, ranked[1].stability_score)

    def test_zero_points_at_bottom(self):
        # one with data, one empty (via status seed)
        _write_json(
            os.path.join(self._tmp, "apy_history.json"),
            _make_history({"good": [5.0, 5.0]}),
        )
        _write_json(
            os.path.join(self._tmp, "adapter_status.json"),
            {"adapters": [{"protocol_key": "empty", "foo": 1}]},
        )
        s = YieldStabilityScorer(data_path=self._tmp)
        ranked = s.score_all()
        self.assertEqual(ranked[-1].adapter_key, "empty")
        self.assertEqual(ranked[-1].confidence, "UNKNOWN")

    def test_tiebreak_cv(self):
        # both cv 0 -> score 100; tiebreak then excess_yield desc
        s = self._setup({
            "low_yield": [3.0, 3.0, 3.0],
            "high_yield": [9.0, 9.0, 9.0],
        })
        ranked = s.score_all()
        # equal score and cv -> higher excess yield first
        self.assertEqual(ranked[0].adapter_key, "high_yield")

    def test_tiebreak_key_asc(self):
        # identical everything -> key ascending
        s = self._setup({
            "bbb": [5.0, 5.0, 5.0],
            "aaa": [5.0, 5.0, 5.0],
        })
        ranked = s.score_all()
        self.assertEqual(ranked[0].adapter_key, "aaa")
        self.assertEqual(ranked[1].adapter_key, "bbb")

    def test_deterministic(self):
        s = self._setup({"a": [5.0, 6.0], "b": [4.0, 4.5]})
        r1 = [a.adapter_key for a in s.score_all()]
        r2 = [a.adapter_key for a in s.score_all()]
        self.assertEqual(r1, r2)

    def test_empty(self):
        s = self._setup({})
        self.assertEqual(s.score_all(), [])


# ===========================================================================
# get_top_n
# ===========================================================================

class TestGetTopN(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _write_json(
            os.path.join(self._tmp, "apy_history.json"),
            _make_history({
                "a": [5.0, 5.0, 5.0],
                "b": [4.0, 6.0, 4.0],
                "c": [1.0, 9.0, 1.0],
            }),
        )
        self.s = YieldStabilityScorer(data_path=self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_top_2(self):
        self.assertEqual(len(self.s.get_top_n(2)), 2)

    def test_top_n_gt_len(self):
        self.assertEqual(len(self.s.get_top_n(99)), 3)

    def test_zero(self):
        self.assertEqual(self.s.get_top_n(0), [])

    def test_negative(self):
        self.assertEqual(self.s.get_top_n(-5), [])

    def test_one(self):
        top = self.s.get_top_n(1)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].rank, 1)


# ===========================================================================
# get_by_grade
# ===========================================================================

class TestGetByGrade(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _write_json(
            os.path.join(self._tmp, "apy_history.json"),
            _make_history({
                "perfect": [5.0, 5.0, 5.0],       # cv 0 -> A
                "wild": [1.0, 9.0, 1.0, 9.0],     # high cv -> D
            }),
        )
        self.s = YieldStabilityScorer(data_path=self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_grade_a(self):
        res = self.s.get_by_grade("A")
        self.assertTrue(all(a.grade == "A" for a in res))
        self.assertIn("perfect", [a.adapter_key for a in res])

    def test_case_insensitive(self):
        self.assertEqual(
            [a.adapter_key for a in self.s.get_by_grade("a")],
            [a.adapter_key for a in self.s.get_by_grade("A")],
        )

    def test_whitespace(self):
        self.assertEqual(
            [a.adapter_key for a in self.s.get_by_grade(" A ")],
            [a.adapter_key for a in self.s.get_by_grade("A")],
        )

    def test_unknown_grade(self):
        self.assertEqual(self.s.get_by_grade("Z"), [])

    def test_non_string_grade(self):
        self.assertEqual(self.s.get_by_grade(5), [])

    def test_grade_d(self):
        res = self.s.get_by_grade("D")
        self.assertIn("wild", [a.adapter_key for a in res])


# ===========================================================================
# get_report no side-effects + correctness
# ===========================================================================

class TestGetReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _write_json(
            os.path.join(self._tmp, "apy_history.json"),
            _make_history({
                "steady": [5.0, 5.0, 5.0],
                "erratic": [1.0, 9.0, 1.0, 9.0],
            }),
        )
        self.s = YieldStabilityScorer(data_path=self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_file_written(self):
        self.s.get_report()
        self.assertFalse(
            os.path.exists(os.path.join(self._tmp, "yield_stability_report.json"))
        )

    def test_report_type(self):
        self.assertIsInstance(self.s.get_report(), StabilityReport)

    def test_counts(self):
        r = self.s.get_report()
        self.assertEqual(r.total_adapters, 2)
        self.assertEqual(r.scored_count, 2)

    def test_most_least_stable(self):
        r = self.s.get_report()
        self.assertEqual(r.most_stable, "steady")
        self.assertEqual(r.least_stable, "erratic")

    def test_grade_distribution_keys(self):
        r = self.s.get_report()
        self.assertEqual(set(r.grade_distribution.keys()), {"A", "B", "C", "D"})

    def test_grade_distribution_sum(self):
        r = self.s.get_report()
        self.assertEqual(sum(r.grade_distribution.values()), r.scored_count)

    def test_avg_score_in_range(self):
        r = self.s.get_report()
        self.assertGreaterEqual(r.avg_stability_score, 0.0)
        self.assertLessEqual(r.avg_stability_score, 100.0)

    def test_generated_at_iso(self):
        r = self.s.get_report()
        # parseable ISO
        from datetime import datetime
        datetime.fromisoformat(r.generated_at)

    def test_empty_universe_report(self):
        empty = tempfile.mkdtemp()
        try:
            s = YieldStabilityScorer(data_path=empty)
            r = s.get_report()
            self.assertEqual(r.total_adapters, 0)
            self.assertEqual(r.scored_count, 0)
            self.assertIsNone(r.most_stable)
            self.assertIsNone(r.least_stable)
            self.assertEqual(r.avg_stability_score, 0.0)
        finally:
            import shutil
            shutil.rmtree(empty, ignore_errors=True)


# ===========================================================================
# to_dict JSON serializability
# ===========================================================================

class TestToDict(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _write_json(
            os.path.join(self._tmp, "apy_history.json"),
            _make_history({"a": [5.0, 5.5, 5.0], "b": [1.0, 9.0]}),
        )
        self.s = YieldStabilityScorer(data_path=self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_adapter_to_dict_serializable(self):
        a = self.s.score_adapter("x", [5.0, 6.0])
        json.dumps(a.to_dict())

    def test_report_to_dict_serializable(self):
        json.dumps(self.s.get_report().to_dict())

    def test_scorer_to_dict_round_trip(self):
        d = self.s.to_dict()
        s = json.dumps(d)
        back = json.loads(s)
        self.assertEqual(back["total_adapters"], d["total_adapters"])

    def test_adapter_dict_keys(self):
        a = self.s.score_adapter("x", [5.0, 6.0])
        d = a.to_dict()
        for k in ("adapter_key", "n_points", "mean_apy_pct", "std_apy_pct",
                  "cv", "apy_drawdown_pct", "stability_score", "grade",
                  "confidence", "latest_apy_pct", "excess_yield_pct", "rank"):
            self.assertIn(k, d)

    def test_report_dict_keys(self):
        d = self.s.get_report().to_dict()
        for k in ("generated_at", "total_adapters", "scored_count",
                  "most_stable", "least_stable", "avg_stability_score",
                  "grade_distribution", "adapters"):
            self.assertIn(k, d)


# ===========================================================================
# save_report atomic + ring-buffer
# ===========================================================================

class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _write_json(
            os.path.join(self._tmp, "apy_history.json"),
            _make_history({"a": [5.0, 5.0, 5.0], "b": [4.0, 6.0]}),
        )
        self.s = YieldStabilityScorer(data_path=self._tmp)
        self.out = os.path.join(self._tmp, "yield_stability_report.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_creates_file(self):
        self.s.save_report()
        self.assertTrue(os.path.exists(self.out))

    def test_returns_path(self):
        path = self.s.save_report()
        self.assertEqual(os.path.abspath(path), os.path.abspath(self.out))

    def test_structure(self):
        self.s.save_report()
        with open(self.out) as fh:
            data = json.load(fh)
        self.assertIn("latest", data)
        self.assertIn("snapshots", data)

    def test_custom_output_path(self):
        custom = os.path.join(self._tmp, "custom.json")
        path = self.s.save_report(output_path=custom)
        self.assertEqual(path, custom)
        self.assertTrue(os.path.exists(custom))

    def test_ring_buffer_trims_to_30(self):
        for _ in range(35):
            self.s.save_report()
        with open(self.out) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data["snapshots"]), 30)
        self.assertEqual(len(data["snapshots"]), 30)

    def test_no_tmp_leftover(self):
        for _ in range(3):
            self.s.save_report()
        leftovers = [f for f in os.listdir(self._tmp) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_latest_matches_last_snapshot(self):
        self.s.save_report()
        with open(self.out) as fh:
            data = json.load(fh)
        self.assertEqual(
            data["latest"]["total_adapters"],
            data["snapshots"][-1]["total_adapters"],
        )

    def test_corrupt_existing_file_recovers(self):
        with open(self.out, "w") as fh:
            fh.write("{garbage")
        # should not raise; starts fresh ring buffer
        self.s.save_report()
        with open(self.out) as fh:
            data = json.load(fh)
        self.assertEqual(len(data["snapshots"]), 1)

    def test_snapshot_count_field(self):
        self.s.save_report()
        with open(self.out) as fh:
            data = json.load(fh)
        self.assertEqual(data["snapshot_count"], len(data["snapshots"]))


# ===========================================================================
# Edge cases / integration
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scorer(self, hist=None, status=None):
        if hist is not None:
            _write_json(
                os.path.join(self._tmp, "apy_history.json"), _make_history(hist)
            )
        if status is not None:
            _write_json(os.path.join(self._tmp, "adapter_status.json"), status)
        return YieldStabilityScorer(data_path=self._tmp)

    def test_single_adapter(self):
        s = self._scorer(hist={"only": [5.0, 5.0, 5.0]})
        ranked = s.score_all()
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].rank, 1)

    def test_all_unknown(self):
        s = self._scorer(
            hist={},
            status={"adapters": [
                {"protocol_key": "a", "foo": 1},
                {"protocol_key": "b", "bar": 2},
            ]},
        )
        r = s.get_report()
        self.assertEqual(r.scored_count, 0)
        self.assertEqual(r.total_adapters, 2)
        self.assertTrue(all(a["confidence"] == "UNKNOWN" for a in r.adapters))

    def test_fifty_adapters(self):
        hist = {f"adapter-{i:02d}": [5.0 + (i % 3), 5.0, 5.0] for i in range(50)}
        s = self._scorer(hist=hist)
        ranked = s.score_all()
        self.assertEqual(len(ranked), 50)
        self.assertEqual(sorted(a.rank for a in ranked), list(range(1, 51)))

    def test_no_data_files_at_all(self):
        s = YieldStabilityScorer(data_path=self._tmp)
        r = s.get_report()
        self.assertEqual(r.total_adapters, 0)
        json.dumps(r.to_dict())

    def test_real_project_shape_smoke(self):
        # mimic real apy_history (long series) + status universe
        hist = {
            "aave-v3-usdc-ethereum": [5.0 + (i % 5) * 0.1 for i in range(90)],
        }
        status = {
            "adapters": [
                {"protocol_key": "aave-v3", "name": "Aave V3"},
                {"protocol_key": "pendle-pt", "name": "Pendle"},
            ],
            "compound_v3": {"apy": 4.8},
        }
        s = self._scorer(hist=hist, status=status)
        r = s.get_report()
        self.assertGreaterEqual(r.total_adapters, 3)
        json.dumps(r.to_dict())


if __name__ == "__main__":
    unittest.main()
