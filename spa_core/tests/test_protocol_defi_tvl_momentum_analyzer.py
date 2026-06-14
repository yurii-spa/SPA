"""
MP-1135 Tests: ProtocolDeFiTvlMomentumAnalyzer

Run: python3 -m unittest spa_core.tests.test_protocol_defi_tvl_momentum_analyzer -v
"""

import json
import os
import tempfile
import unittest
from typing import Any, Dict

from spa_core.analytics.protocol_defi_tvl_momentum_analyzer import (
    ProtocolDeFiTvlMomentumAnalyzer,
    _momentum_score,
    _pct_change,
    _tvl_label,
    _yield_dilution_risk,
    main,
)

# ── helpers ──────────────────────────────────────────────────────────────────

def run(
    tvl_now: float = 500_000_000.0,
    tvl_7d: float = 480_000_000.0,
    tvl_30d: float = 420_000_000.0,
    tvl_90d: float = 350_000_000.0,
    protocol: str = "test-protocol",
    yield_type: str = "lending",
    cfg: Dict[str, Any] = None,
) -> Dict[str, Any]:
    if cfg is None:
        cfg = {}
    az = ProtocolDeFiTvlMomentumAnalyzer()
    return az.analyze(
        tvl_now_usd=tvl_now,
        tvl_7d_ago_usd=tvl_7d,
        tvl_30d_ago_usd=tvl_30d,
        tvl_90d_ago_usd=tvl_90d,
        protocol_name=protocol,
        yield_type=yield_type,
        config=cfg,
    )


# ── TestOutputShape ───────────────────────────────────────────────────────────

class TestOutputShape(unittest.TestCase):

    def setUp(self):
        self.out = run()

    def test_required_keys_present(self):
        expected = {
            "protocol_name", "yield_type",
            "tvl_now_usd", "tvl_7d_ago_usd", "tvl_30d_ago_usd", "tvl_90d_ago_usd",
            "tvl_change_7d_pct", "tvl_change_30d_pct", "tvl_change_90d_pct",
            "momentum_score", "yield_dilution_risk", "tvl_label", "timestamp",
        }
        self.assertEqual(expected, set(self.out.keys()))

    def test_tvl_change_7d_pct_is_float(self):
        self.assertIsInstance(self.out["tvl_change_7d_pct"], float)

    def test_tvl_change_30d_pct_is_float(self):
        self.assertIsInstance(self.out["tvl_change_30d_pct"], float)

    def test_tvl_change_90d_pct_is_float(self):
        self.assertIsInstance(self.out["tvl_change_90d_pct"], float)

    def test_momentum_score_is_int(self):
        self.assertIsInstance(self.out["momentum_score"], int)

    def test_yield_dilution_risk_is_str(self):
        self.assertIsInstance(self.out["yield_dilution_risk"], str)

    def test_tvl_label_is_str(self):
        self.assertIsInstance(self.out["tvl_label"], str)

    def test_timestamp_is_nonempty_str(self):
        self.assertTrue(self.out["timestamp"])

    def test_protocol_name_echoed(self):
        out = run(protocol="Aave-V3")
        self.assertEqual(out["protocol_name"], "Aave-V3")

    def test_yield_type_echoed(self):
        out = run(yield_type="fees")
        self.assertEqual(out["yield_type"], "fees")

    def test_tvl_now_echoed(self):
        out = run(tvl_now=123_456_789.0)
        self.assertAlmostEqual(out["tvl_now_usd"], 123_456_789.0, places=1)

    def test_tvl_7d_echoed(self):
        out = run(tvl_7d=200_000_000.0)
        self.assertAlmostEqual(out["tvl_7d_ago_usd"], 200_000_000.0, places=1)

    def test_tvl_30d_echoed(self):
        out = run(tvl_30d=300_000_000.0)
        self.assertAlmostEqual(out["tvl_30d_ago_usd"], 300_000_000.0, places=1)

    def test_tvl_90d_echoed(self):
        out = run(tvl_90d=250_000_000.0)
        self.assertAlmostEqual(out["tvl_90d_ago_usd"], 250_000_000.0, places=1)


# ── TestTvlChangePct ──────────────────────────────────────────────────────────

class TestTvlChangePct7d(unittest.TestCase):

    def test_zero_7d_change(self):
        out = run(tvl_now=100.0, tvl_7d=100.0)
        self.assertAlmostEqual(out["tvl_change_7d_pct"], 0.0, places=4)

    def test_positive_7d_change(self):
        # (110 - 100)/100 * 100 = 10%
        out = run(tvl_now=110.0, tvl_7d=100.0)
        self.assertAlmostEqual(out["tvl_change_7d_pct"], 10.0, places=4)

    def test_negative_7d_change(self):
        # (90 - 100)/100 * 100 = -10%
        out = run(tvl_now=90.0, tvl_7d=100.0)
        self.assertAlmostEqual(out["tvl_change_7d_pct"], -10.0, places=4)

    def test_7d_change_100pct(self):
        out = run(tvl_now=200.0, tvl_7d=100.0)
        self.assertAlmostEqual(out["tvl_change_7d_pct"], 100.0, places=4)

    def test_7d_change_negative_50pct(self):
        out = run(tvl_now=50.0, tvl_7d=100.0)
        self.assertAlmostEqual(out["tvl_change_7d_pct"], -50.0, places=4)

    def test_7d_zero_tvl_ago_returns_zero(self):
        out = run(tvl_7d=0.0)
        self.assertAlmostEqual(out["tvl_change_7d_pct"], 0.0, places=4)


class TestTvlChangePct30d(unittest.TestCase):

    def test_zero_30d_change(self):
        out = run(tvl_now=500.0, tvl_30d=500.0)
        self.assertAlmostEqual(out["tvl_change_30d_pct"], 0.0, places=4)

    def test_positive_30d_change_19pct(self):
        out = run(tvl_now=119.0, tvl_30d=100.0)
        self.assertAlmostEqual(out["tvl_change_30d_pct"], 19.0, places=4)

    def test_negative_30d_change(self):
        out = run(tvl_now=800.0, tvl_30d=1_000.0)
        self.assertAlmostEqual(out["tvl_change_30d_pct"], -20.0, places=4)

    def test_30d_change_large_growth(self):
        out = run(tvl_now=1_000.0, tvl_30d=200.0)
        self.assertAlmostEqual(out["tvl_change_30d_pct"], 400.0, places=4)

    def test_30d_zero_tvl_ago_returns_zero(self):
        out = run(tvl_30d=0.0)
        self.assertAlmostEqual(out["tvl_change_30d_pct"], 0.0, places=4)

    def test_pct_change_helper_symmetric(self):
        # 100→150 is +50%, 150→100 is -33.33%
        self.assertAlmostEqual(_pct_change(100.0, 150.0), 50.0, places=4)
        self.assertAlmostEqual(_pct_change(150.0, 100.0), -100.0 / 3.0, places=4)


class TestTvlChangePct90d(unittest.TestCase):

    def test_zero_90d_change(self):
        out = run(tvl_now=200.0, tvl_90d=200.0)
        self.assertAlmostEqual(out["tvl_change_90d_pct"], 0.0, places=4)

    def test_positive_90d_change(self):
        out = run(tvl_now=300.0, tvl_90d=200.0)
        self.assertAlmostEqual(out["tvl_change_90d_pct"], 50.0, places=4)

    def test_negative_90d_change(self):
        out = run(tvl_now=100.0, tvl_90d=400.0)
        self.assertAlmostEqual(out["tvl_change_90d_pct"], -75.0, places=4)

    def test_90d_zero_tvl_ago_returns_zero(self):
        out = run(tvl_90d=0.0)
        self.assertAlmostEqual(out["tvl_change_90d_pct"], 0.0, places=4)

    def test_90d_change_formula(self):
        now, ago = 7_500_000.0, 5_000_000.0
        expected = (now - ago) / ago * 100.0
        out = run(tvl_now=now, tvl_90d=ago)
        self.assertAlmostEqual(out["tvl_change_90d_pct"], expected, places=4)


# ── TestMomentumScore ─────────────────────────────────────────────────────────

class TestMomentumScore(unittest.TestCase):

    def test_neutral_score_when_all_flat(self):
        score = _momentum_score(0.0, 0.0, 0.0)
        self.assertEqual(score, 50)

    def test_score_above_50_when_growing(self):
        score = _momentum_score(10.0, 10.0, 10.0)
        self.assertGreater(score, 50)

    def test_score_below_50_when_declining(self):
        score = _momentum_score(-10.0, -10.0, -10.0)
        self.assertLess(score, 50)

    def test_score_clamped_at_100_max(self):
        score = _momentum_score(1000.0, 1000.0, 1000.0)
        self.assertEqual(score, 100)

    def test_score_clamped_at_0_min(self):
        score = _momentum_score(-1000.0, -1000.0, -1000.0)
        self.assertEqual(score, 0)

    def test_score_is_int(self):
        score = _momentum_score(5.0, 3.0, 1.0)
        self.assertIsInstance(score, int)

    def test_score_formula_manual_check(self):
        # raw = 50 + (10*50 + 5*30 + 2*20)/100 = 50 + (500+150+40)/100 = 50 + 6.9 = 56.9 → 56
        score = _momentum_score(10.0, 5.0, 2.0)
        self.assertEqual(score, 56)

    def test_score_formula_all_negative(self):
        # raw = 50 + (-20*50 + -10*30 + -5*20)/100 = 50 + (-1000-300-100)/100 = 50 - 14 = 36
        score = _momentum_score(-20.0, -10.0, -5.0)
        self.assertEqual(score, 36)

    def test_score_from_output_matches_helper(self):
        out = run(tvl_now=110.0, tvl_7d=100.0, tvl_30d=90.0, tvl_90d=80.0)
        c7 = out["tvl_change_7d_pct"]
        c30 = out["tvl_change_30d_pct"]
        c90 = out["tvl_change_90d_pct"]
        expected = _momentum_score(c7, c30, c90)
        self.assertEqual(out["momentum_score"], expected)

    def test_score_neutral_output(self):
        out = run(tvl_now=100.0, tvl_7d=100.0, tvl_30d=100.0, tvl_90d=100.0)
        self.assertEqual(out["momentum_score"], 50)

    def test_score_weight_7d_dominates(self):
        # 7d weight=50, 30d=30, 90d=20 → large 7d change should push score most
        score_7d = _momentum_score(100.0, 0.0, 0.0)
        score_30d = _momentum_score(0.0, 100.0, 0.0)
        score_90d = _momentum_score(0.0, 0.0, 100.0)
        self.assertGreater(score_7d, score_30d)
        self.assertGreater(score_30d, score_90d)

    def test_score_range_0_to_100(self):
        for change in [-200.0, -50.0, 0.0, 50.0, 200.0]:
            s = _momentum_score(change, change, change)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_score_increasing_with_better_momentum(self):
        s1 = _momentum_score(-10.0, -10.0, -10.0)
        s2 = _momentum_score(0.0, 0.0, 0.0)
        s3 = _momentum_score(10.0, 10.0, 10.0)
        self.assertLess(s1, s2)
        self.assertLess(s2, s3)

    def test_output_score_growing_protocol(self):
        # TVL growing strongly over all periods
        out = run(tvl_now=1_000.0, tvl_7d=900.0, tvl_30d=700.0, tvl_90d=500.0)
        self.assertGreater(out["momentum_score"], 50)

    def test_output_score_declining_protocol(self):
        out = run(tvl_now=500.0, tvl_7d=600.0, tvl_30d=700.0, tvl_90d=900.0)
        self.assertLess(out["momentum_score"], 50)

    def test_score_small_growth_above_50(self):
        score = _momentum_score(1.0, 1.0, 1.0)
        self.assertGreater(score, 50)

    def test_score_small_decline_below_50(self):
        score = _momentum_score(-1.0, -1.0, -1.0)
        self.assertLess(score, 50)

    def test_score_0_is_int_zero(self):
        score = _momentum_score(-5000.0, -5000.0, -5000.0)
        self.assertEqual(score, 0)

    def test_score_100_is_int_hundred(self):
        score = _momentum_score(5000.0, 5000.0, 5000.0)
        self.assertEqual(score, 100)


# ── TestYieldDilutionRisk ─────────────────────────────────────────────────────

class TestYieldDilutionRisk(unittest.TestCase):

    def test_low_below_10pct(self):
        self.assertEqual(_yield_dilution_risk(5.0), "LOW")

    def test_low_zero_pct(self):
        self.assertEqual(_yield_dilution_risk(0.0), "LOW")

    def test_low_negative_change(self):
        # TVL falling doesn't dilute yield
        self.assertEqual(_yield_dilution_risk(-50.0), "LOW")

    def test_medium_exactly_10pct(self):
        self.assertEqual(_yield_dilution_risk(10.0), "MEDIUM")

    def test_medium_25pct(self):
        self.assertEqual(_yield_dilution_risk(25.0), "MEDIUM")

    def test_medium_just_below_50pct(self):
        self.assertEqual(_yield_dilution_risk(49.9), "MEDIUM")

    def test_high_exactly_50pct(self):
        self.assertEqual(_yield_dilution_risk(50.0), "HIGH")

    def test_high_100pct(self):
        self.assertEqual(_yield_dilution_risk(100.0), "HIGH")

    def test_high_just_below_200pct(self):
        self.assertEqual(_yield_dilution_risk(199.9), "HIGH")

    def test_critical_exactly_200pct(self):
        self.assertEqual(_yield_dilution_risk(200.0), "CRITICAL")

    def test_critical_500pct(self):
        self.assertEqual(_yield_dilution_risk(500.0), "CRITICAL")

    def test_from_output_low(self):
        # tvl_now == tvl_30d → 0% change → LOW
        out = run(tvl_now=100.0, tvl_30d=100.0)
        self.assertEqual(out["yield_dilution_risk"], "LOW")

    def test_from_output_medium(self):
        out = run(tvl_now=120.0, tvl_30d=100.0)  # +20%
        self.assertEqual(out["yield_dilution_risk"], "MEDIUM")

    def test_from_output_high(self):
        out = run(tvl_now=160.0, tvl_30d=100.0)  # +60%
        self.assertEqual(out["yield_dilution_risk"], "HIGH")

    def test_from_output_critical(self):
        out = run(tvl_now=400.0, tvl_30d=100.0)  # +300%
        self.assertEqual(out["yield_dilution_risk"], "CRITICAL")

    def test_valid_risk_values(self):
        valid = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        for change in [-100.0, 0.0, 9.9, 10.0, 49.9, 50.0, 199.9, 200.0, 500.0]:
            self.assertIn(_yield_dilution_risk(change), valid)


# ── TestTvlLabel ──────────────────────────────────────────────────────────────

class TestTvlLabel(unittest.TestCase):

    def test_rapid_growth_above_50pct(self):
        self.assertEqual(_tvl_label(51.0), "RAPID_GROWTH")

    def test_rapid_growth_exactly_50pct_not_rapid(self):
        # >50 → RAPID_GROWTH; ==50 → HEALTHY_GROWTH (>10% check)
        self.assertEqual(_tvl_label(50.0), "HEALTHY_GROWTH")

    def test_rapid_growth_100pct(self):
        self.assertEqual(_tvl_label(100.0), "RAPID_GROWTH")

    def test_healthy_growth_10_to_50(self):
        self.assertEqual(_tvl_label(30.0), "HEALTHY_GROWTH")

    def test_healthy_growth_exactly_10pct(self):
        # > 10 → HEALTHY_GROWTH; ==10 is not >10 so STABLE
        self.assertEqual(_tvl_label(10.0), "STABLE")

    def test_healthy_growth_just_above_10pct(self):
        self.assertEqual(_tvl_label(10.1), "HEALTHY_GROWTH")

    def test_stable_zero_pct(self):
        self.assertEqual(_tvl_label(0.0), "STABLE")

    def test_stable_negative_5pct(self):
        self.assertEqual(_tvl_label(-5.0), "STABLE")

    def test_stable_exactly_negative_10pct(self):
        # >= -10 → STABLE
        self.assertEqual(_tvl_label(-10.0), "STABLE")

    def test_declining_just_below_negative_10pct(self):
        self.assertEqual(_tvl_label(-10.1), "DECLINING")

    def test_declining_20pct(self):
        self.assertEqual(_tvl_label(-20.0), "DECLINING")

    def test_declining_exactly_negative_30pct(self):
        # >= -30 → DECLINING
        self.assertEqual(_tvl_label(-30.0), "DECLINING")

    def test_rapid_decline_below_negative_30pct(self):
        self.assertEqual(_tvl_label(-31.0), "RAPID_DECLINE")

    def test_rapid_decline_negative_80pct(self):
        self.assertEqual(_tvl_label(-80.0), "RAPID_DECLINE")

    def test_from_output_rapid_growth(self):
        out = run(tvl_now=200.0, tvl_30d=100.0)  # +100%
        self.assertEqual(out["tvl_label"], "RAPID_GROWTH")

    def test_from_output_healthy_growth(self):
        out = run(tvl_now=125.0, tvl_30d=100.0)  # +25%
        self.assertEqual(out["tvl_label"], "HEALTHY_GROWTH")

    def test_from_output_stable(self):
        out = run(tvl_now=105.0, tvl_30d=100.0)  # +5%
        self.assertEqual(out["tvl_label"], "STABLE")

    def test_from_output_declining(self):
        out = run(tvl_now=85.0, tvl_30d=100.0)  # -15%
        self.assertEqual(out["tvl_label"], "DECLINING")

    def test_from_output_rapid_decline(self):
        out = run(tvl_now=50.0, tvl_30d=100.0)  # -50%
        self.assertEqual(out["tvl_label"], "RAPID_DECLINE")

    def test_valid_label_set(self):
        valid = {"RAPID_GROWTH", "HEALTHY_GROWTH", "STABLE", "DECLINING", "RAPID_DECLINE"}
        for change in [-50.0, -30.0, -10.0, 0.0, 10.0, 50.0, 100.0]:
            self.assertIn(_tvl_label(change), valid)


# ── TestEdgeCases ─────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_all_tvl_equal_no_crash(self):
        out = run(tvl_now=100.0, tvl_7d=100.0, tvl_30d=100.0, tvl_90d=100.0)
        self.assertEqual(out["momentum_score"], 50)
        self.assertEqual(out["tvl_label"], "STABLE")
        self.assertEqual(out["yield_dilution_risk"], "LOW")

    def test_zero_tvl_now_no_crash(self):
        out = run(tvl_now=0.0)
        self.assertIsInstance(out["momentum_score"], int)

    def test_zero_all_tvl_no_crash(self):
        out = run(tvl_now=0.0, tvl_7d=0.0, tvl_30d=0.0, tvl_90d=0.0)
        for k in ("tvl_change_7d_pct", "tvl_change_30d_pct", "tvl_change_90d_pct"):
            self.assertAlmostEqual(out[k], 0.0, places=4)

    def test_very_large_tvl_no_crash(self):
        out = run(tvl_now=1e12, tvl_7d=9e11, tvl_30d=8e11, tvl_90d=5e11)
        self.assertIsInstance(out["momentum_score"], int)

    def test_pct_change_helper_zero_denom(self):
        self.assertEqual(_pct_change(0.0, 100.0), 0.0)

    def test_pct_change_helper_negative_old(self):
        # |old| used in denominator → same result as positive old
        result = _pct_change(-100.0, 0.0)
        self.assertAlmostEqual(result, 100.0, places=4)  # (0-(-100))/100*100 = 100%

    def test_empty_protocol_name(self):
        out = run(protocol="")
        self.assertEqual(out["protocol_name"], "")

    def test_yield_type_staking(self):
        out = run(yield_type="staking")
        self.assertEqual(out["yield_type"], "staking")

    def test_yield_type_emissions(self):
        out = run(yield_type="emissions")
        self.assertEqual(out["yield_type"], "emissions")

    def test_yield_type_fees(self):
        out = run(yield_type="fees")
        self.assertEqual(out["yield_type"], "fees")

    def test_tvl_all_rounds_to_2_places(self):
        out = run(tvl_now=123456789.123)
        self.assertEqual(out["tvl_now_usd"], round(123456789.123, 2))

    def test_changes_round_to_6_places(self):
        out = run(tvl_now=110.0, tvl_7d=100.0)
        # 10.000000% rounded to 6 places
        self.assertAlmostEqual(out["tvl_change_7d_pct"], 10.0, places=5)

    def test_score_not_negative(self):
        out = run(tvl_now=1.0, tvl_7d=1000.0, tvl_30d=1000.0, tvl_90d=1000.0)
        self.assertGreaterEqual(out["momentum_score"], 0)

    def test_score_not_above_100(self):
        out = run(tvl_now=1e9, tvl_7d=1.0, tvl_30d=1.0, tvl_90d=1.0)
        self.assertLessEqual(out["momentum_score"], 100)


# ── TestLogWriting ────────────────────────────────────────────────────────────

class TestLogWriting(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "tvl_momentum_log.json")

    def _cfg(self) -> Dict[str, Any]:
        return {"write_log": True, "log_path": self.log_path}

    def test_log_created_on_write(self):
        run(cfg=self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_json_list(self):
        run(cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_has_required_keys(self):
        run(cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        entry = data[0]
        for key in ("ts", "protocol_name", "yield_type", "tvl_now_usd",
                    "momentum_score", "yield_dilution_risk", "tvl_label"):
            self.assertIn(key, entry)

    def test_no_log_without_write_flag(self):
        run()
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_appends_multiple_entries(self):
        for _ in range(4):
            run(cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 4)

    def test_ring_buffer_cap_100(self):
        cfg = {"write_log": True, "log_path": self.log_path, "log_cap": 100}
        for _ in range(105):
            run(cfg=cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_custom_cap(self):
        cfg = {"write_log": True, "log_path": self.log_path, "log_cap": 5}
        for _ in range(9):
            run(cfg=cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 5)

    def test_ring_buffer_keeps_newest(self):
        cfg = {"write_log": True, "log_path": self.log_path, "log_cap": 3}
        for i in range(6):
            run(protocol=f"proto-{i}", cfg=cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        names = [e["protocol_name"] for e in data]
        self.assertIn("proto-5", names)
        self.assertNotIn("proto-0", names)

    def test_no_tmp_file_after_write(self):
        run(cfg=self._cfg())
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_corrupt_log_file_reset(self):
        with open(self.log_path, "w") as fh:
            fh.write("{not valid json}")
        run(cfg=self._cfg())  # must not crash
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_log_entry_momentum_score_value(self):
        run(tvl_now=100.0, tvl_7d=100.0, tvl_30d=100.0, tvl_90d=100.0, cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["momentum_score"], 50)

    def test_log_entry_protocol_name(self):
        run(protocol="morpho-blue", cfg=self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol_name"], "morpho-blue")


# ── TestCLI ───────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):

    def test_main_check_exits_zero(self):
        rc = main(["--check"])
        self.assertEqual(rc, 0)

    def test_main_no_args_exits_zero(self):
        rc = main([])
        self.assertEqual(rc, 0)

    def test_main_run_writes_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main(["--run", "--data-dir", tmp])
            self.assertEqual(rc, 0)
            log_path = os.path.join(tmp, "tvl_momentum_log.json")
            self.assertTrue(os.path.exists(log_path))

    def test_main_invalid_arg_exits_zero(self):
        rc = main(["--unknown-xyz-flag"])
        self.assertEqual(rc, 0)

    def test_main_run_log_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            main(["--run", "--data-dir", tmp])
            log_path = os.path.join(tmp, "tvl_momentum_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 0)


# ── TestPctChangeHelper ───────────────────────────────────────────────────────

class TestPctChangeHelper(unittest.TestCase):

    def test_zero_old_returns_zero(self):
        self.assertEqual(_pct_change(0.0, 100.0), 0.0)

    def test_same_values_returns_zero(self):
        self.assertAlmostEqual(_pct_change(50.0, 50.0), 0.0, places=6)

    def test_double_returns_100(self):
        self.assertAlmostEqual(_pct_change(50.0, 100.0), 100.0, places=6)

    def test_half_returns_negative_50(self):
        self.assertAlmostEqual(_pct_change(100.0, 50.0), -50.0, places=6)

    def test_triple_returns_200(self):
        self.assertAlmostEqual(_pct_change(100.0, 300.0), 200.0, places=6)

    def test_negative_old_abs_denominator(self):
        # |old| = 100; (0 - (-100))/100 * 100 = 100%
        self.assertAlmostEqual(_pct_change(-100.0, 0.0), 100.0, places=6)

    def test_large_values(self):
        result = _pct_change(1e9, 2e9)
        self.assertAlmostEqual(result, 100.0, places=4)


if __name__ == "__main__":
    unittest.main()
