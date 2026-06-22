"""
Tests for MP-922 DeFiRestakingRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_restaking_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_restaking_risk_analyzer import (
    DeFiRestakingRiskAnalyzer,
    _atomic_append_log,
    _risk_label,
    _HHI_HIGH_CONCENTRATION_THRESHOLD,
    _FEW_OPERATORS_THRESHOLD,
    _HIGH_AVS_THRESHOLD,
    _LONG_WITHDRAWAL_DAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(**kwargs):
    """Return a safe default position dict, overridden by kwargs."""
    defaults = {
        "protocol": "TestProtocol",
        "base_token": "ETH",
        "restaking_protocol": "EigenLayer",
        "slashing_conditions": [],
        "operator_count": 20,
        "operator_concentration_hhi": 1000,
        "base_apy_pct": 4.0,
        "restaking_apy_pct": 2.0,
        "slashing_history_count": 0,
        "tvl_usd": 10_000_000,
        "withdrawal_delay_days": 7,
        "avs_count": 5,
    }
    defaults.update(kwargs)
    return defaults


def _make_analyzer_with_tmplog():
    """Return (analyzer, tmp_dir) using a temp dir for log output."""
    tmp_dir = tempfile.mkdtemp()
    log_path = os.path.join(tmp_dir, "test_restaking_log.json")
    analyzer = DeFiRestakingRiskAnalyzer(log_path=log_path)
    return analyzer, log_path, tmp_dir


# ---------------------------------------------------------------------------
# 1. Module-level helpers
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):

    def test_label_minimal(self):
        self.assertEqual(_risk_label(0.0), "MINIMAL")

    def test_label_minimal_boundary(self):
        self.assertEqual(_risk_label(19.9), "MINIMAL")

    def test_label_low(self):
        self.assertEqual(_risk_label(20.0), "LOW")

    def test_label_low_mid(self):
        self.assertEqual(_risk_label(30.0), "LOW")

    def test_label_low_boundary(self):
        self.assertEqual(_risk_label(39.9), "LOW")

    def test_label_moderate(self):
        self.assertEqual(_risk_label(40.0), "MODERATE")

    def test_label_moderate_mid(self):
        self.assertEqual(_risk_label(55.0), "MODERATE")

    def test_label_moderate_boundary(self):
        self.assertEqual(_risk_label(59.9), "MODERATE")

    def test_label_high(self):
        self.assertEqual(_risk_label(60.0), "HIGH")

    def test_label_high_mid(self):
        self.assertEqual(_risk_label(70.0), "HIGH")

    def test_label_high_boundary(self):
        self.assertEqual(_risk_label(79.9), "HIGH")

    def test_label_critical(self):
        self.assertEqual(_risk_label(80.0), "CRITICAL")

    def test_label_critical_max(self):
        self.assertEqual(_risk_label(100.0), "CRITICAL")


# ---------------------------------------------------------------------------
# 2. Slashing risk score
# ---------------------------------------------------------------------------

class TestSlashingRiskScore(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()

    def test_zero_history_zero_conditions_zero_avs(self):
        pos = _make_position(slashing_history_count=0, slashing_conditions=[], avs_count=0)
        self.assertEqual(self.a.slashing_risk_score(pos), 0.0)

    def test_one_slashing_history_increases_score(self):
        pos0 = _make_position(slashing_history_count=0, slashing_conditions=[], avs_count=0)
        pos1 = _make_position(slashing_history_count=1, slashing_conditions=[], avs_count=0)
        self.assertGreater(self.a.slashing_risk_score(pos1), self.a.slashing_risk_score(pos0))

    def test_more_slashing_history_higher_score(self):
        s1 = self.a.slashing_risk_score(_make_position(slashing_history_count=1))
        s5 = self.a.slashing_risk_score(_make_position(slashing_history_count=5))
        self.assertGreater(s5, s1)

    def test_conditions_increase_score(self):
        pos0 = _make_position(slashing_conditions=[], slashing_history_count=0, avs_count=0)
        pos3 = _make_position(slashing_conditions=["a", "b", "c"], slashing_history_count=0, avs_count=0)
        self.assertGreater(self.a.slashing_risk_score(pos3), self.a.slashing_risk_score(pos0))

    def test_avs_count_increases_score(self):
        pos0 = _make_position(avs_count=0, slashing_history_count=0, slashing_conditions=[])
        pos10 = _make_position(avs_count=10, slashing_history_count=0, slashing_conditions=[])
        self.assertGreater(self.a.slashing_risk_score(pos10), self.a.slashing_risk_score(pos0))

    def test_score_bounded_0_to_100(self):
        pos = _make_position(
            slashing_history_count=999,
            slashing_conditions=["c"] * 100,
            avs_count=999,
        )
        score = self.a.slashing_risk_score(pos)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_negative_history_clamped(self):
        pos = _make_position(slashing_history_count=-5)
        score = self.a.slashing_risk_score(pos)
        self.assertGreaterEqual(score, 0.0)

    def test_negative_avs_clamped(self):
        pos = _make_position(avs_count=-10)
        score = self.a.slashing_risk_score(pos)
        self.assertGreaterEqual(score, 0.0)

    def test_five_conditions_capped_at_40(self):
        pos = _make_position(slashing_conditions=["a"] * 5, slashing_history_count=0, avs_count=0)
        # 5 * 8 = 40 → condition component = 40 * 0.3 = 12
        score = self.a.slashing_risk_score(pos)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_missing_fields_default_zero(self):
        score = self.a.slashing_risk_score({})
        self.assertEqual(score, 0.0)


# ---------------------------------------------------------------------------
# 3. Concentration risk score
# ---------------------------------------------------------------------------

class TestConcentrationRiskScore(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()

    def test_zero_hhi_many_operators_low_risk(self):
        pos = _make_position(operator_concentration_hhi=0, operator_count=100)
        score = self.a.concentration_risk_score(pos)
        self.assertLess(score, 20.0)

    def test_max_hhi_monopoly(self):
        pos = _make_position(operator_concentration_hhi=10000, operator_count=1)
        score = self.a.concentration_risk_score(pos)
        self.assertGreater(score, 80.0)

    def test_zero_operators_penalized(self):
        pos0 = _make_position(operator_count=0, operator_concentration_hhi=0)
        pos50 = _make_position(operator_count=50, operator_concentration_hhi=0)
        self.assertGreater(
            self.a.concentration_risk_score(pos0),
            self.a.concentration_risk_score(pos50),
        )

    def test_score_bounded_0_to_100(self):
        for hhi in [0, 2500, 5000, 7500, 10000]:
            for ops in [0, 1, 5, 10, 50, 100]:
                pos = _make_position(operator_concentration_hhi=hhi, operator_count=ops)
                s = self.a.concentration_risk_score(pos)
                self.assertGreaterEqual(s, 0.0, f"hhi={hhi}, ops={ops}")
                self.assertLessEqual(s, 100.0, f"hhi={hhi}, ops={ops}")

    def test_high_hhi_more_risk_than_low_hhi(self):
        low = self.a.concentration_risk_score(_make_position(operator_concentration_hhi=1000, operator_count=20))
        high = self.a.concentration_risk_score(_make_position(operator_concentration_hhi=8000, operator_count=20))
        self.assertGreater(high, low)

    def test_hhi_clamped_above_10000(self):
        pos = _make_position(operator_concentration_hhi=99999)
        score = self.a.concentration_risk_score(pos)
        self.assertLessEqual(score, 100.0)

    def test_hhi_clamped_below_zero(self):
        pos = _make_position(operator_concentration_hhi=-100)
        score = self.a.concentration_risk_score(pos)
        self.assertGreaterEqual(score, 0.0)

    def test_missing_fields_default(self):
        score = self.a.concentration_risk_score({})
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_few_operators_increases_risk(self):
        s3 = self.a.concentration_risk_score(_make_position(operator_count=3, operator_concentration_hhi=2000))
        s50 = self.a.concentration_risk_score(_make_position(operator_count=50, operator_concentration_hhi=2000))
        self.assertGreater(s3, s50)


# ---------------------------------------------------------------------------
# 4. Withdrawal liquidity risk
# ---------------------------------------------------------------------------

class TestWithdrawalLiquidityRisk(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()

    def test_zero_days_zero_risk(self):
        self.assertEqual(self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=0)), 0.0)

    def test_one_day_low_risk(self):
        score = self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=1))
        self.assertGreater(score, 0.0)
        self.assertLess(score, 20.0)

    def test_7_days_moderate(self):
        score = self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=7))
        self.assertGreater(score, 0.0)
        self.assertLess(score, 60.0)

    def test_14_days_moderate_to_high(self):
        score = self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=14))
        self.assertGreater(score, 30.0)

    def test_30_days_high(self):
        score = self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=30))
        self.assertGreater(score, 60.0)

    def test_90_days_very_high(self):
        score = self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=90))
        self.assertGreater(score, 75.0)

    def test_longer_always_higher_or_equal(self):
        days_list = [0, 1, 3, 7, 14, 21, 30, 90, 180]
        scores = [
            self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=d))
            for d in days_list
        ]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1],
                                  f"days={days_list[i]} score should be ≤ days={days_list[i+1]}")

    def test_negative_days_clamped(self):
        score = self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=-5))
        self.assertEqual(score, 0.0)

    def test_score_bounded(self):
        for days in [0, 1, 7, 14, 30, 90, 365, 9999]:
            s = self.a.withdrawal_liquidity_risk(_make_position(withdrawal_delay_days=days))
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)


# ---------------------------------------------------------------------------
# 5. Flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()

    def test_no_flags_safe_position(self):
        pos = _make_position(
            operator_concentration_hhi=2000,
            slashing_history_count=0,
            withdrawal_delay_days=7,
            operator_count=20,
            avs_count=5,
        )
        self.assertEqual(self.a.compute_flags(pos), [])

    def test_high_concentration_flag(self):
        pos = _make_position(operator_concentration_hhi=_HHI_HIGH_CONCENTRATION_THRESHOLD + 1)
        self.assertIn("HIGH_CONCENTRATION", self.a.compute_flags(pos))

    def test_high_concentration_boundary_exact(self):
        # exactly at threshold → not flagged (must be > threshold)
        pos = _make_position(operator_concentration_hhi=_HHI_HIGH_CONCENTRATION_THRESHOLD)
        self.assertNotIn("HIGH_CONCENTRATION", self.a.compute_flags(pos))

    def test_slashing_history_flag(self):
        pos = _make_position(slashing_history_count=1)
        self.assertIn("SLASHING_HISTORY", self.a.compute_flags(pos))

    def test_no_slashing_history_no_flag(self):
        pos = _make_position(slashing_history_count=0)
        self.assertNotIn("SLASHING_HISTORY", self.a.compute_flags(pos))

    def test_long_withdrawal_flag(self):
        pos = _make_position(withdrawal_delay_days=_LONG_WITHDRAWAL_DAYS + 0.1)
        self.assertIn("LONG_WITHDRAWAL", self.a.compute_flags(pos))

    def test_withdrawal_exactly_at_threshold_no_flag(self):
        pos = _make_position(withdrawal_delay_days=_LONG_WITHDRAWAL_DAYS)
        self.assertNotIn("LONG_WITHDRAWAL", self.a.compute_flags(pos))

    def test_few_operators_flag(self):
        pos = _make_position(operator_count=_FEW_OPERATORS_THRESHOLD - 1)
        self.assertIn("FEW_OPERATORS", self.a.compute_flags(pos))

    def test_enough_operators_no_flag(self):
        pos = _make_position(operator_count=_FEW_OPERATORS_THRESHOLD)
        self.assertNotIn("FEW_OPERATORS", self.a.compute_flags(pos))

    def test_high_avs_exposure_flag(self):
        pos = _make_position(avs_count=_HIGH_AVS_THRESHOLD + 1)
        self.assertIn("HIGH_AVS_EXPOSURE", self.a.compute_flags(pos))

    def test_avs_at_threshold_no_flag(self):
        pos = _make_position(avs_count=_HIGH_AVS_THRESHOLD)
        self.assertNotIn("HIGH_AVS_EXPOSURE", self.a.compute_flags(pos))

    def test_all_flags_triggered(self):
        pos = _make_position(
            operator_concentration_hhi=9000,
            slashing_history_count=5,
            withdrawal_delay_days=30,
            operator_count=3,
            avs_count=20,
        )
        flags = self.a.compute_flags(pos)
        self.assertIn("HIGH_CONCENTRATION", flags)
        self.assertIn("SLASHING_HISTORY", flags)
        self.assertIn("LONG_WITHDRAWAL", flags)
        self.assertIn("FEW_OPERATORS", flags)
        self.assertIn("HIGH_AVS_EXPOSURE", flags)

    def test_flags_returns_list(self):
        pos = _make_position()
        self.assertIsInstance(self.a.compute_flags(pos), list)


# ---------------------------------------------------------------------------
# 6. analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):

    def setUp(self):
        self.a, self.log_path, self.tmp_dir = _make_analyzer_with_tmplog()

    def test_empty_positions_returns_dict(self):
        result = self.a.analyze([], {"log_enabled": False})
        self.assertIsInstance(result, dict)

    def test_empty_positions_has_positions_key(self):
        result = self.a.analyze([], {"log_enabled": False})
        self.assertIn("positions", result)
        self.assertEqual(result["positions"], [])

    def test_empty_positions_has_aggregates(self):
        result = self.a.analyze([], {"log_enabled": False})
        self.assertIn("aggregates", result)

    def test_empty_positions_aggregates_nulled(self):
        agg = self.a.analyze([], {"log_enabled": False})["aggregates"]
        self.assertIsNone(agg["safest_position"])
        self.assertIsNone(agg["riskiest_position"])
        self.assertEqual(agg["total_restaked_usd"], 0.0)
        self.assertEqual(agg["average_total_apy"], 0.0)
        self.assertEqual(agg["critical_count"], 0)

    def test_empty_positions_has_timestamp(self):
        result = self.a.analyze([], {"log_enabled": False})
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], str)


# ---------------------------------------------------------------------------
# 7. analyze() — single position
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):

    def setUp(self):
        self.a, self.log_path, self.tmp_dir = _make_analyzer_with_tmplog()
        self.pos = _make_position(
            protocol="Proto-A",
            base_apy_pct=3.5,
            restaking_apy_pct=2.5,
            tvl_usd=50_000_000,
        )

    def test_single_result_has_one_position(self):
        result = self.a.analyze([self.pos], {"log_enabled": False})
        self.assertEqual(len(result["positions"]), 1)

    def test_total_apy_computed(self):
        result = self.a.analyze([self.pos], {"log_enabled": False})
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_apy_pct"], 6.0, places=4)

    def test_safest_equals_riskiest_for_single(self):
        agg = self.a.analyze([self.pos], {"log_enabled": False})["aggregates"]
        self.assertEqual(agg["safest_position"], agg["riskiest_position"])
        self.assertEqual(agg["safest_position"], "Proto-A")

    def test_total_restaked_usd(self):
        agg = self.a.analyze([self.pos], {"log_enabled": False})["aggregates"]
        self.assertAlmostEqual(agg["total_restaked_usd"], 50_000_000.0, places=1)

    def test_risk_label_present(self):
        result = self.a.analyze([self.pos], {"log_enabled": False})
        p = result["positions"][0]
        self.assertIn(p["risk_label"], {"MINIMAL", "LOW", "MODERATE", "HIGH", "CRITICAL"})

    def test_composite_risk_range(self):
        result = self.a.analyze([self.pos], {"log_enabled": False})
        cr = result["positions"][0]["composite_risk"]
        self.assertGreaterEqual(cr, 0.0)
        self.assertLessEqual(cr, 100.0)

    def test_flags_is_list(self):
        result = self.a.analyze([self.pos], {"log_enabled": False})
        self.assertIsInstance(result["positions"][0]["flags"], list)


# ---------------------------------------------------------------------------
# 8. analyze() — multiple positions
# ---------------------------------------------------------------------------

class TestAnalyzeMultiple(unittest.TestCase):

    def setUp(self):
        self.a, self.log_path, self.tmp_dir = _make_analyzer_with_tmplog()
        self.positions = [
            _make_position(
                protocol="Safe-Pool",
                operator_concentration_hhi=500,
                operator_count=50,
                slashing_history_count=0,
                avs_count=3,
                withdrawal_delay_days=2,
                base_apy_pct=3.0,
                restaking_apy_pct=1.0,
                tvl_usd=100_000_000,
            ),
            _make_position(
                protocol="Risky-Pool",
                operator_concentration_hhi=8000,
                operator_count=3,
                slashing_history_count=3,
                avs_count=20,
                withdrawal_delay_days=90,
                base_apy_pct=8.0,
                restaking_apy_pct=12.0,
                tvl_usd=10_000_000,
            ),
        ]

    def test_two_positions_returned(self):
        result = self.a.analyze(self.positions, {"log_enabled": False})
        self.assertEqual(len(result["positions"]), 2)

    def test_risky_pool_has_higher_composite(self):
        result = self.a.analyze(self.positions, {"log_enabled": False})
        composites = {p["protocol"]: p["composite_risk"] for p in result["positions"]}
        self.assertGreater(composites["Risky-Pool"], composites["Safe-Pool"])

    def test_safest_is_safe_pool(self):
        agg = self.a.analyze(self.positions, {"log_enabled": False})["aggregates"]
        self.assertEqual(agg["safest_position"], "Safe-Pool")

    def test_riskiest_is_risky_pool(self):
        agg = self.a.analyze(self.positions, {"log_enabled": False})["aggregates"]
        self.assertEqual(agg["riskiest_position"], "Risky-Pool")

    def test_total_tvl_sum(self):
        agg = self.a.analyze(self.positions, {"log_enabled": False})["aggregates"]
        self.assertAlmostEqual(agg["total_restaked_usd"], 110_000_000.0, places=1)

    def test_average_total_apy(self):
        agg = self.a.analyze(self.positions, {"log_enabled": False})["aggregates"]
        # (4.0 + 20.0) / 2 = 12.0
        self.assertAlmostEqual(agg["average_total_apy"], 12.0, places=3)

    def test_critical_count_risky(self):
        result = self.a.analyze(self.positions, {"log_enabled": False})
        agg = result["aggregates"]
        # risky pool should be CRITICAL or HIGH depending on scoring
        risky_label = next(p["risk_label"] for p in result["positions"] if p["protocol"] == "Risky-Pool")
        expected_critical = 1 if risky_label == "CRITICAL" else 0
        self.assertEqual(agg["critical_count"], expected_critical)

    def test_critical_count_zero_for_safe_positions(self):
        safe_positions = [
            _make_position(protocol=f"Safe-{i}", operator_count=50, operator_concentration_hhi=500,
                           slashing_history_count=0, avs_count=2, withdrawal_delay_days=0)
            for i in range(3)
        ]
        agg = self.a.analyze(safe_positions, {"log_enabled": False})["aggregates"]
        self.assertEqual(agg["critical_count"], 0)


# ---------------------------------------------------------------------------
# 9. Risk label distribution
# ---------------------------------------------------------------------------

class TestRiskLabelDistribution(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()

    def _position_with_risk(self, target_label):
        """Return a position that should produce approximately the requested label."""
        configs = {
            "MINIMAL": dict(operator_concentration_hhi=300, operator_count=80,
                            slashing_history_count=0, avs_count=1, withdrawal_delay_days=0),
            "LOW": dict(operator_concentration_hhi=1500, operator_count=30,
                        slashing_history_count=0, avs_count=3, withdrawal_delay_days=2),
            "MODERATE": dict(operator_concentration_hhi=4000, operator_count=15,
                             slashing_history_count=0, avs_count=6, withdrawal_delay_days=7),
            "HIGH": dict(operator_concentration_hhi=7000, operator_count=5,
                         slashing_history_count=1, avs_count=9, withdrawal_delay_days=14),
            "CRITICAL": dict(operator_concentration_hhi=9500, operator_count=2,
                             slashing_history_count=5, avs_count=25, withdrawal_delay_days=90),
        }
        return _make_position(**configs[target_label])

    def test_minimal_label_low_risk_position(self):
        pos = self._position_with_risk("MINIMAL")
        result = self.a.analyze([pos], {"log_enabled": False})
        label = result["positions"][0]["risk_label"]
        self.assertIn(label, {"MINIMAL", "LOW"})  # very safe → minimal or low

    def test_critical_label_very_risky(self):
        pos = self._position_with_risk("CRITICAL")
        result = self.a.analyze([pos], {"log_enabled": False})
        label = result["positions"][0]["risk_label"]
        self.assertIn(label, {"HIGH", "CRITICAL"})

    def test_all_labels_are_valid_strings(self):
        valid = {"MINIMAL", "LOW", "MODERATE", "HIGH", "CRITICAL"}
        for label in valid:
            pos = self._position_with_risk(label)
            result = self.a.analyze([pos], {"log_enabled": False})
            got = result["positions"][0]["risk_label"]
            self.assertIn(got, valid)


# ---------------------------------------------------------------------------
# 10. APY computation
# ---------------------------------------------------------------------------

class TestAPYComputation(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()

    def test_total_apy_is_sum(self):
        pos = _make_position(base_apy_pct=5.0, restaking_apy_pct=3.0)
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertAlmostEqual(result["positions"][0]["total_apy_pct"], 8.0, places=4)

    def test_zero_restaking_apy(self):
        pos = _make_position(base_apy_pct=4.5, restaking_apy_pct=0.0)
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertAlmostEqual(result["positions"][0]["total_apy_pct"], 4.5, places=4)

    def test_zero_base_apy(self):
        pos = _make_position(base_apy_pct=0.0, restaking_apy_pct=6.0)
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertAlmostEqual(result["positions"][0]["total_apy_pct"], 6.0, places=4)

    def test_high_total_apy(self):
        pos = _make_position(base_apy_pct=15.0, restaking_apy_pct=10.0)
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertAlmostEqual(result["positions"][0]["total_apy_pct"], 25.0, places=4)

    def test_average_apy_multiple_positions(self):
        positions = [
            _make_position(base_apy_pct=4.0, restaking_apy_pct=0.0),
            _make_position(base_apy_pct=6.0, restaking_apy_pct=2.0),
        ]
        agg = self.a.analyze(positions, {"log_enabled": False})["aggregates"]
        self.assertAlmostEqual(agg["average_total_apy"], 6.0, places=4)


# ---------------------------------------------------------------------------
# 11. Logging behavior
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")
        self.a = DeFiRestakingRiskAnalyzer(log_path=self.log_path)

    def _cfg(self, **kw):
        base = {"log_enabled": True, "log_path": self.log_path}
        base.update(kw)
        return base

    def test_log_file_created_after_analyze(self):
        self.a.analyze([_make_position()], self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json_list(self):
        self.a.analyze([_make_position()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_count_increases(self):
        for _ in range(3):
            self.a.analyze([_make_position()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_capped_at_log_cap(self):
        cap = 5
        a = DeFiRestakingRiskAnalyzer(log_path=self.log_path, log_cap=cap)
        for _ in range(8):
            a.analyze([_make_position()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), cap)

    def test_log_disabled_no_file_created(self):
        log_path = os.path.join(self.tmp_dir, "no_file.json")
        a = DeFiRestakingRiskAnalyzer(log_path=log_path)
        a.analyze([_make_position()], {"log_enabled": False})
        self.assertFalse(os.path.exists(log_path))

    def test_log_entry_has_positions_key(self):
        self.a.analyze([_make_position()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("positions", data[0])

    def test_log_entry_has_aggregates_key(self):
        self.a.analyze([_make_position()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_log_entry_has_timestamp(self):
        self.a.analyze([_make_position()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_atomic_append_log_helper_creates_file(self):
        path = os.path.join(self.tmp_dir, "direct_log.json")
        _atomic_append_log(path, {"key": "value"})
        self.assertTrue(os.path.exists(path))

    def test_atomic_append_log_appends_multiple(self):
        path = os.path.join(self.tmp_dir, "multi_log.json")
        for i in range(3):
            _atomic_append_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_atomic_append_log_ring_buffer_cap(self):
        path = os.path.join(self.tmp_dir, "ring_log.json")
        for i in range(10):
            _atomic_append_log(path, {"i": i}, cap=5)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        self.assertEqual(data[-1]["i"], 9)  # most recent entry last


# ---------------------------------------------------------------------------
# 12. Output structure validation
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()
        self.result = self.a.analyze(
            [
                _make_position(protocol="A", tvl_usd=1_000_000),
                _make_position(protocol="B", tvl_usd=2_000_000),
            ],
            {"log_enabled": False},
        )

    def test_top_level_keys(self):
        for k in ("positions", "aggregates", "timestamp"):
            self.assertIn(k, self.result)

    def test_position_keys(self):
        expected = {
            "protocol", "base_token", "restaking_protocol", "tvl_usd",
            "total_apy_pct", "slashing_risk_score", "concentration_risk_score",
            "withdrawal_liquidity_risk", "composite_risk", "risk_label", "flags",
        }
        for p in self.result["positions"]:
            for k in expected:
                self.assertIn(k, p, f"Missing key {k!r} in position result")

    def test_aggregate_keys(self):
        expected = {
            "safest_position", "riskiest_position", "total_restaked_usd",
            "average_total_apy", "critical_count",
        }
        for k in expected:
            self.assertIn(k, self.result["aggregates"])

    def test_numeric_fields_are_floats(self):
        p = self.result["positions"][0]
        for k in ("total_apy_pct", "slashing_risk_score", "concentration_risk_score",
                   "withdrawal_liquidity_risk", "composite_risk"):
            self.assertIsInstance(p[k], float, f"{k} should be float")

    def test_risk_label_is_string(self):
        for p in self.result["positions"]:
            self.assertIsInstance(p["risk_label"], str)

    def test_flags_is_list_of_strings(self):
        for p in self.result["positions"]:
            self.assertIsInstance(p["flags"], list)
            for f in p["flags"]:
                self.assertIsInstance(f, str)

    def test_critical_count_is_int(self):
        self.assertIsInstance(self.result["aggregates"]["critical_count"], int)


# ---------------------------------------------------------------------------
# 13. Edge cases and robustness
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.a = DeFiRestakingRiskAnalyzer()

    def test_empty_string_protocol(self):
        pos = _make_position(protocol="")
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertEqual(result["positions"][0]["protocol"], "")

    def test_very_large_tvl(self):
        pos = _make_position(tvl_usd=1e15)
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertAlmostEqual(result["aggregates"]["total_restaked_usd"], 1e15, delta=1)

    def test_zero_tvl(self):
        pos = _make_position(tvl_usd=0)
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertEqual(result["aggregates"]["total_restaked_usd"], 0.0)

    def test_position_with_all_zero_fields(self):
        pos = {
            "protocol": "Z", "base_token": "", "restaking_protocol": "",
            "slashing_conditions": [], "operator_count": 0,
            "operator_concentration_hhi": 0, "base_apy_pct": 0,
            "restaking_apy_pct": 0, "slashing_history_count": 0,
            "tvl_usd": 0, "withdrawal_delay_days": 0, "avs_count": 0,
        }
        result = self.a.analyze([pos], {"log_enabled": False})
        p = result["positions"][0]
        self.assertEqual(p["total_apy_pct"], 0.0)

    def test_missing_optional_fields(self):
        pos = {"protocol": "Min"}
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertEqual(len(result["positions"]), 1)

    def test_many_positions(self):
        positions = [_make_position(protocol=f"P{i}", tvl_usd=1000 * i) for i in range(1, 51)]
        result = self.a.analyze(positions, {"log_enabled": False})
        self.assertEqual(len(result["positions"]), 50)

    def test_protocol_passthrough(self):
        pos = _make_position(protocol="UniqueProto", base_token="WBTC")
        result = self.a.analyze([pos], {"log_enabled": False})
        self.assertEqual(result["positions"][0]["protocol"], "UniqueProto")
        self.assertEqual(result["positions"][0]["base_token"], "WBTC")

    def test_config_without_log_enabled_defaults_to_true(self):
        """Default config logs; we just verify it doesn't raise."""
        tmp_dir = tempfile.mkdtemp()
        log_path = os.path.join(tmp_dir, "default_log.json")
        a = DeFiRestakingRiskAnalyzer(log_path=log_path)
        a.analyze([_make_position()], {})  # no log_enabled → defaults True
        self.assertTrue(os.path.exists(log_path))

    def test_all_positions_identical_safe(self):
        positions = [_make_position(protocol=f"P{i}") for i in range(5)]
        result = self.a.analyze(positions, {"log_enabled": False})
        composites = [p["composite_risk"] for p in result["positions"]]
        self.assertEqual(len(set(composites)), 1)  # all same risk

    def test_custom_log_path_via_config(self):
        tmp_dir = tempfile.mkdtemp()
        custom_log = os.path.join(tmp_dir, "custom.json")
        self.a.analyze([_make_position()], {"log_enabled": True, "log_path": custom_log})
        self.assertTrue(os.path.exists(custom_log))


if __name__ == "__main__":
    unittest.main()
