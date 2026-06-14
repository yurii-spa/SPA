"""
Tests for MP-873 RestakingRiskAnalyzer
≥65 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.restaking_risk_analyzer import (
    analyze,
    _slashing_component,
    _avs_component,
    _operator_component,
    _delay_component,
    _depeg_component,
    _restaking_risk_score,
    _risk_label,
    _build_recommendations,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pos(
    protocol: str = "EtherFi",
    slashing_exposure_pct: float = 0.0,
    avs_count: int = 0,
    operator_concentration_pct: float = 0.0,
    withdrawal_delay_days: float = 0.0,
    lrt_depeg_pct: float = 0.0,
) -> dict:
    return {
        "protocol": protocol,
        "slashing_exposure_pct": slashing_exposure_pct,
        "avs_count": avs_count,
        "operator_concentration_pct": operator_concentration_pct,
        "withdrawal_delay_days": withdrawal_delay_days,
        "lrt_depeg_pct": lrt_depeg_pct,
    }


# ===========================================================================
# 1. _slashing_component
# ===========================================================================

class TestSlashingComponent(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_slashing_component(0.0), 0.0)

    def test_full(self):
        self.assertEqual(_slashing_component(100.0), 100.0)

    def test_half(self):
        self.assertEqual(_slashing_component(50.0), 50.0)

    def test_clamp_above_100(self):
        self.assertEqual(_slashing_component(150.0), 100.0)

    def test_clamp_negative(self):
        self.assertEqual(_slashing_component(-10.0), 0.0)

    def test_monotonic(self):
        self.assertLess(_slashing_component(10.0), _slashing_component(40.0))


# ===========================================================================
# 2. _avs_component
# ===========================================================================

class TestAvsComponent(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_avs_component(0), 0.0)

    def test_negative(self):
        self.assertEqual(_avs_component(-3), 0.0)

    def test_one_positive(self):
        self.assertGreater(_avs_component(1), 0.0)

    def test_monotonic(self):
        self.assertLess(_avs_component(2), _avs_component(10))

    def test_bounded(self):
        self.assertLessEqual(_avs_component(1000), 100.0)

    def test_saturates_high(self):
        self.assertGreater(_avs_component(50), 99.0)


# ===========================================================================
# 3. _operator_component
# ===========================================================================

class TestOperatorComponent(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_operator_component(0.0), 0.0)

    def test_full(self):
        self.assertEqual(_operator_component(100.0), 100.0)

    def test_clamp_above(self):
        self.assertEqual(_operator_component(120.0), 100.0)

    def test_clamp_negative(self):
        self.assertEqual(_operator_component(-5.0), 0.0)

    def test_monotonic(self):
        self.assertLess(_operator_component(20.0), _operator_component(80.0))


# ===========================================================================
# 4. _delay_component
# ===========================================================================

class TestDelayComponent(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_delay_component(0.0), 0.0)

    def test_negative(self):
        self.assertEqual(_delay_component(-5.0), 0.0)

    def test_thirty_days_full(self):
        self.assertAlmostEqual(_delay_component(30.0), 100.0)

    def test_fifteen_days_half(self):
        self.assertAlmostEqual(_delay_component(15.0), 50.0)

    def test_clamp_above(self):
        self.assertEqual(_delay_component(90.0), 100.0)

    def test_monotonic(self):
        self.assertLess(_delay_component(5.0), _delay_component(20.0))


# ===========================================================================
# 5. _depeg_component
# ===========================================================================

class TestDepegComponent(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_depeg_component(0.0), 0.0)

    def test_abs_value_positive(self):
        self.assertAlmostEqual(_depeg_component(2.5), 50.0)

    def test_abs_value_negative(self):
        self.assertAlmostEqual(_depeg_component(-2.5), 50.0)

    def test_five_pct_full(self):
        self.assertAlmostEqual(_depeg_component(5.0), 100.0)

    def test_clamp_above(self):
        self.assertEqual(_depeg_component(20.0), 100.0)

    def test_monotonic(self):
        self.assertLess(_depeg_component(0.5), _depeg_component(3.0))


# ===========================================================================
# 6. _restaking_risk_score
# ===========================================================================

class TestRestakingRiskScore(unittest.TestCase):
    def test_all_zero(self):
        self.assertEqual(_restaking_risk_score(0.0, 0, 0.0, 0.0, 0.0), 0.0)

    def test_all_max(self):
        s = _restaking_risk_score(100.0, 1000, 100.0, 90.0, 20.0)
        self.assertAlmostEqual(s, 100.0, places=1)

    def test_bounded_0_100(self):
        s = _restaking_risk_score(50.0, 8, 65.0, 21.0, 1.8)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_monotonic_in_slashing(self):
        low = _restaking_risk_score(10.0, 0, 0.0, 0.0, 0.0)
        high = _restaking_risk_score(80.0, 0, 0.0, 0.0, 0.0)
        self.assertLess(low, high)

    def test_monotonic_in_avs(self):
        low = _restaking_risk_score(0.0, 1, 0.0, 0.0, 0.0)
        high = _restaking_risk_score(0.0, 20, 0.0, 0.0, 0.0)
        self.assertLess(low, high)

    def test_monotonic_in_operator(self):
        low = _restaking_risk_score(0.0, 0, 10.0, 0.0, 0.0)
        high = _restaking_risk_score(0.0, 0, 90.0, 0.0, 0.0)
        self.assertLess(low, high)

    def test_monotonic_in_delay(self):
        low = _restaking_risk_score(0.0, 0, 0.0, 2.0, 0.0)
        high = _restaking_risk_score(0.0, 0, 0.0, 28.0, 0.0)
        self.assertLess(low, high)

    def test_monotonic_in_depeg(self):
        low = _restaking_risk_score(0.0, 0, 0.0, 0.0, 0.5)
        high = _restaking_risk_score(0.0, 0, 0.0, 0.0, 4.0)
        self.assertLess(low, high)

    def test_slashing_weight(self):
        # slashing=100 alone → 0.30*100 = 30
        s = _restaking_risk_score(100.0, 0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s, 30.0)

    def test_operator_weight(self):
        # operator=100 alone → 0.20*100 = 20
        s = _restaking_risk_score(0.0, 0, 100.0, 0.0, 0.0)
        self.assertAlmostEqual(s, 20.0)


# ===========================================================================
# 7. _risk_label
# ===========================================================================

class TestRiskLabel(unittest.TestCase):
    def test_low(self):
        self.assertEqual(_risk_label(0.0), "LOW")

    def test_low_just_below_25(self):
        self.assertEqual(_risk_label(24.99), "LOW")

    def test_moderate_at_25(self):
        self.assertEqual(_risk_label(25.0), "MODERATE")

    def test_moderate_just_below_50(self):
        self.assertEqual(_risk_label(49.99), "MODERATE")

    def test_elevated_at_50(self):
        self.assertEqual(_risk_label(50.0), "ELEVATED")

    def test_elevated_just_below_75(self):
        self.assertEqual(_risk_label(74.99), "ELEVATED")

    def test_critical_at_75(self):
        self.assertEqual(_risk_label(75.0), "CRITICAL")

    def test_critical_at_100(self):
        self.assertEqual(_risk_label(100.0), "CRITICAL")


# ===========================================================================
# 8. _build_recommendations
# ===========================================================================

class TestBuildRecommendations(unittest.TestCase):
    def test_operator_concentration_high(self):
        recs = _build_recommendations(0.0, 0, 60.0, 0.0, 0.0, "MODERATE")
        self.assertTrue(any("Diversify" in r for r in recs))

    def test_operator_concentration_at_threshold_not_triggered(self):
        # > 50 strictly required
        recs = _build_recommendations(0.0, 0, 50.0, 0.0, 0.0, "LOW")
        self.assertFalse(any("Diversify" in r for r in recs))

    def test_avs_high(self):
        recs = _build_recommendations(0.0, 8, 0.0, 0.0, 0.0, "MODERATE")
        self.assertTrue(any("AVS" in r for r in recs))

    def test_avs_at_threshold_not_triggered(self):
        recs = _build_recommendations(0.0, 5, 0.0, 0.0, 0.0, "LOW")
        self.assertFalse(any("AVS exposure" in r for r in recs))

    def test_slashing_high(self):
        recs = _build_recommendations(60.0, 0, 0.0, 0.0, 0.0, "MODERATE")
        self.assertTrue(any("Slashing exposure" in r for r in recs))

    def test_depeg_high_negative(self):
        recs = _build_recommendations(0.0, 0, 0.0, 0.0, -1.5, "MODERATE")
        self.assertTrue(any("depeg" in r.lower() for r in recs))

    def test_depeg_below_threshold(self):
        recs = _build_recommendations(0.0, 0, 0.0, 0.0, 0.5, "LOW")
        self.assertFalse(any("depeg" in r.lower() for r in recs))

    def test_delay_high(self):
        recs = _build_recommendations(0.0, 0, 0.0, 21.0, 0.0, "MODERATE")
        self.assertTrue(any("delay" in r.lower() for r in recs))

    def test_no_triggers_returns_monitor(self):
        recs = _build_recommendations(0.0, 0, 0.0, 0.0, 0.0, "LOW")
        self.assertEqual(len(recs), 1)
        self.assertIn("acceptable", recs[0].lower())

    def test_critical_no_factor_fallback(self):
        recs = _build_recommendations(0.0, 0, 0.0, 0.0, 0.0, "CRITICAL")
        self.assertTrue(any("Critical" in r for r in recs))

    def test_recommendations_nonempty_always(self):
        recs = _build_recommendations(60.0, 8, 60.0, 21.0, 2.0, "CRITICAL")
        self.assertGreater(len(recs), 0)

    def test_multiple_triggers(self):
        recs = _build_recommendations(60.0, 8, 60.0, 21.0, 2.0, "CRITICAL")
        self.assertGreaterEqual(len(recs), 4)


# ===========================================================================
# 9. analyze() — basic structure
# ===========================================================================

class TestAnalyzeStructure(unittest.TestCase):
    def setUp(self):
        self.r = analyze(_pos(), config={"log_path": _tmp_log()})

    def test_top_level_keys(self):
        expected = {
            "protocol",
            "slashing_exposure_pct",
            "avs_count",
            "operator_concentration_pct",
            "withdrawal_delay_days",
            "lrt_depeg_pct",
            "components",
            "restaking_risk_score",
            "label",
            "recommendations",
            "timestamp",
        }
        self.assertEqual(set(self.r.keys()), expected)

    def test_component_keys(self):
        expected = {"slashing", "avs", "operator", "delay", "depeg"}
        self.assertEqual(set(self.r["components"].keys()), expected)

    def test_score_float(self):
        self.assertIsInstance(self.r["restaking_risk_score"], float)

    def test_label_valid(self):
        self.assertIn(self.r["label"], {"LOW", "MODERATE", "ELEVATED", "CRITICAL"})

    def test_recommendations_list(self):
        self.assertIsInstance(self.r["recommendations"], list)
        self.assertGreater(len(self.r["recommendations"]), 0)

    def test_timestamp_float(self):
        self.assertIsInstance(self.r["timestamp"], float)


# ===========================================================================
# 10. analyze() — zero / safe position
# ===========================================================================

class TestAnalyzeSafe(unittest.TestCase):
    def setUp(self):
        self.r = analyze(_pos(), config={"log_path": _tmp_log()})

    def test_score_zero(self):
        self.assertEqual(self.r["restaking_risk_score"], 0.0)

    def test_label_low(self):
        self.assertEqual(self.r["label"], "LOW")

    def test_components_zero(self):
        for v in self.r["components"].values():
            self.assertEqual(v, 0.0)

    def test_monitor_recommendation(self):
        self.assertIn("acceptable", self.r["recommendations"][0].lower())


# ===========================================================================
# 11. analyze() — critical position
# ===========================================================================

class TestAnalyzeCritical(unittest.TestCase):
    def setUp(self):
        self.r = analyze(
            _pos(
                slashing_exposure_pct=90.0,
                avs_count=20,
                operator_concentration_pct=90.0,
                withdrawal_delay_days=30.0,
                lrt_depeg_pct=5.0,
            ),
            config={"log_path": _tmp_log()},
        )

    def test_score_high(self):
        self.assertGreaterEqual(self.r["restaking_risk_score"], 75.0)

    def test_label_critical(self):
        self.assertEqual(self.r["label"], "CRITICAL")

    def test_many_recommendations(self):
        self.assertGreaterEqual(len(self.r["recommendations"]), 4)


# ===========================================================================
# 12. analyze() — missing fields default safely
# ===========================================================================

class TestAnalyzeDefaults(unittest.TestCase):
    def test_empty_dict(self):
        r = analyze({}, config={"log_path": _tmp_log()})
        self.assertEqual(r["restaking_risk_score"], 0.0)
        self.assertEqual(r["protocol"], "UNKNOWN")

    def test_partial_dict(self):
        r = analyze({"operator_concentration_pct": 80.0}, config={"log_path": _tmp_log()})
        self.assertGreater(r["restaking_risk_score"], 0.0)

    def test_none_config_uses_default_path(self):
        r = analyze(_pos())
        self.assertIn("restaking_risk_score", r)


# ===========================================================================
# 13. analyze() — timestamp recency
# ===========================================================================

class TestAnalyzeTimestamp(unittest.TestCase):
    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_pos(), config={"log_path": _tmp_log()})
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)


# ===========================================================================
# 14. Atomic log
# ===========================================================================

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


class TestAtomicLog(unittest.TestCase):
    def _make_log_path(self, tmp_dir: str) -> str:
        return os.path.join(tmp_dir, "test_restaking_log.json")

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"a": 1})
            _atomic_log(path, {"b": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(110):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_oldest_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(105):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["i"], 5)

    def test_corrupted_file_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            with open(path, "w") as f:
                f.write("INVALID JSON <<<")
            _atomic_log(path, {"ok": True})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_analyze_writes_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            analyze(_pos(), config={"log_path": path})
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


# ===========================================================================
# 15. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_negative_inputs_clamped(self):
        r = analyze(
            _pos(slashing_exposure_pct=-10.0, operator_concentration_pct=-5.0),
            config={"log_path": _tmp_log()},
        )
        self.assertEqual(r["components"]["slashing"], 0.0)
        self.assertEqual(r["components"]["operator"], 0.0)

    def test_extreme_inputs_bounded(self):
        r = analyze(
            _pos(
                slashing_exposure_pct=9999.0,
                avs_count=99999,
                operator_concentration_pct=9999.0,
                withdrawal_delay_days=9999.0,
                lrt_depeg_pct=9999.0,
            ),
            config={"log_path": _tmp_log()},
        )
        self.assertLessEqual(r["restaking_risk_score"], 100.0)
        self.assertEqual(r["label"], "CRITICAL")

    def test_depeg_sign_preserved_in_output(self):
        r = analyze(_pos(lrt_depeg_pct=-2.0), config={"log_path": _tmp_log()})
        self.assertEqual(r["lrt_depeg_pct"], -2.0)

    def test_only_avs(self):
        r = analyze(_pos(avs_count=8), config={"log_path": _tmp_log()})
        self.assertGreater(r["restaking_risk_score"], 0.0)

    def test_score_consistent_with_components(self):
        r = analyze(_pos(operator_concentration_pct=100.0), config={"log_path": _tmp_log()})
        # operator component 100 → contributes 0.20*100 = 20
        self.assertAlmostEqual(r["restaking_risk_score"], 20.0)

    def test_label_matches_score(self):
        r = analyze(
            _pos(slashing_exposure_pct=100.0, operator_concentration_pct=100.0),
            config={"log_path": _tmp_log()},
        )
        # 30 + 20 = 50 → ELEVATED
        self.assertEqual(r["label"], "ELEVATED")


if __name__ == "__main__":
    unittest.main()
