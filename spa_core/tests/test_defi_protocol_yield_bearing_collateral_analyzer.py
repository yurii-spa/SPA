"""
Tests for MP-1050 DeFiProtocolYieldBearingCollateralAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
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

from spa_core.analytics.defi_protocol_yield_bearing_collateral_analyzer import (
    DeFiProtocolYieldBearingCollateralAnalyzer,
    analyze,
    _net_carry,
    _yield_offset_ratio,
    _carry_trade_score,
    _oracle_risk_score,
    _carry_label,
    _build_recommendations,
    _atomic_log,
    LABEL_OPTIMAL_CARRY,
    LABEL_POSITIVE_CARRY,
    LABEL_NEUTRAL,
    LABEL_NEGATIVE_CARRY,
    LABEL_CARRY_TRAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _default_analyze(**kwargs):
    defaults = dict(
        collateral_token="stETH",
        underlying_apy_pct=4.0,
        borrow_rate_pct=3.0,
        ltv_pct=70.0,
        position_size_usd=100_000.0,
        collateral_rebasing=True,
        liquidation_premium_pct=5.0,
        oracle_lag_seconds=0.0,
    )
    defaults.update(kwargs)
    a = DeFiProtocolYieldBearingCollateralAnalyzer(log_path=_tmp_log())
    return a.analyze(**defaults)


# ===========================================================================
# 1. _net_carry helper
# ===========================================================================
class TestNetCarry(unittest.TestCase):

    def test_positive_carry(self):
        self.assertAlmostEqual(_net_carry(5.0, 3.0), 2.0)

    def test_zero_carry(self):
        self.assertAlmostEqual(_net_carry(3.0, 3.0), 0.0)

    def test_negative_carry(self):
        self.assertAlmostEqual(_net_carry(2.0, 4.0), -2.0)

    def test_high_yield(self):
        self.assertAlmostEqual(_net_carry(20.0, 5.0), 15.0)

    def test_zero_borrow(self):
        self.assertAlmostEqual(_net_carry(5.0, 0.0), 5.0)

    def test_large_negative(self):
        self.assertAlmostEqual(_net_carry(0.0, 10.0), -10.0)


# ===========================================================================
# 2. _yield_offset_ratio helper
# ===========================================================================
class TestYieldOffsetRatio(unittest.TestCase):

    def test_full_offset(self):
        # yield == borrow => ratio 1.0
        r = _yield_offset_ratio(5.0, 5.0)
        self.assertAlmostEqual(r, 1.0)

    def test_over_offset(self):
        # yield > borrow => capped at 2.0
        r = _yield_offset_ratio(10.0, 3.0)
        self.assertGreaterEqual(r, 1.0)

    def test_zero_borrow(self):
        # zero borrow cost → full offset (1.0)
        r = _yield_offset_ratio(5.0, 0.0)
        self.assertAlmostEqual(r, 1.0)

    def test_partial_offset(self):
        r = _yield_offset_ratio(2.0, 4.0)
        self.assertAlmostEqual(r, 0.5)

    def test_cap_at_two(self):
        # ratio 100/1 = 100, but capped at 2
        r = _yield_offset_ratio(100.0, 1.0)
        self.assertAlmostEqual(r, 2.0)

    def test_zero_yield(self):
        r = _yield_offset_ratio(0.0, 5.0)
        self.assertAlmostEqual(r, 0.0)


# ===========================================================================
# 3. _carry_trade_score helper
# ===========================================================================
class TestCarryTradeScore(unittest.TestCase):

    def test_range_0_100(self):
        for nc in [-15, -5, 0, 5, 15, 25]:
            for yo in [0.0, 0.5, 1.0, 2.0]:
                for ltv in [10, 50, 80, 99]:
                    for reb in [True, False]:
                        s = _carry_trade_score(float(nc), yo, float(ltv), reb)
                        self.assertGreaterEqual(s, 0.0)
                        self.assertLessEqual(s, 100.0)

    def test_high_score_good_carry(self):
        s = _carry_trade_score(20.0, 2.0, 80.0, True)
        self.assertGreater(s, 70.0)

    def test_low_score_bad_carry(self):
        s = _carry_trade_score(-10.0, 0.0, 10.0, False)
        self.assertLess(s, 20.0)

    def test_rebasing_bonus(self):
        s_reb = _carry_trade_score(5.0, 1.0, 70.0, True)
        s_no  = _carry_trade_score(5.0, 1.0, 70.0, False)
        self.assertGreater(s_reb, s_no)

    def test_higher_ltv_higher_score(self):
        s_low = _carry_trade_score(5.0, 1.0, 30.0, False)
        s_hi  = _carry_trade_score(5.0, 1.0, 90.0, False)
        self.assertGreater(s_hi, s_low)


# ===========================================================================
# 4. _oracle_risk_score helper
# ===========================================================================
class TestOracleRiskScore(unittest.TestCase):

    def test_range_0_100(self):
        for lag in [0, 30, 100, 300, 900, 1800, 3600]:
            for ltv in [10, 50, 80, 95]:
                for lp in [0, 5, 15]:
                    s = _oracle_risk_score(float(lag), float(ltv), float(lp))
                    self.assertGreaterEqual(s, 0.0)
                    self.assertLessEqual(s, 100.0)

    def test_zero_lag_low_ltv(self):
        s = _oracle_risk_score(0.0, 20.0, 10.0)
        self.assertLess(s, 15.0)

    def test_high_lag_high_ltv(self):
        s = _oracle_risk_score(3600.0, 90.0, 0.0)
        self.assertGreater(s, 70.0)

    def test_liq_premium_reduces_risk(self):
        s_low  = _oracle_risk_score(600.0, 70.0, 0.0)
        s_high = _oracle_risk_score(600.0, 70.0, 15.0)
        self.assertGreater(s_low, s_high)

    def test_medium_lag_range(self):
        s30  = _oracle_risk_score(30.0,  50.0, 5.0)
        s300 = _oracle_risk_score(300.0, 50.0, 5.0)
        self.assertLess(s30, s300)


# ===========================================================================
# 5. _carry_label helper
# ===========================================================================
class TestCarryLabel(unittest.TestCase):

    def test_optimal_carry(self):
        label = _carry_label(80.0, 5.0)
        self.assertEqual(label, LABEL_OPTIMAL_CARRY)

    def test_positive_carry(self):
        label = _carry_label(55.0, 2.0)
        self.assertEqual(label, LABEL_POSITIVE_CARRY)

    def test_neutral(self):
        label = _carry_label(30.0, 0.5)
        self.assertEqual(label, LABEL_NEUTRAL)

    def test_negative_carry_score_below_25(self):
        label = _carry_label(10.0, -1.0)
        self.assertEqual(label, LABEL_NEGATIVE_CARRY)

    def test_carry_trap_very_negative(self):
        label = _carry_label(5.0, -6.0)
        self.assertEqual(label, LABEL_CARRY_TRAP)

    def test_carry_trap_threshold(self):
        # exactly -5 is still NEGATIVE_CARRY
        label_exact = _carry_label(10.0, -5.0)
        self.assertEqual(label_exact, LABEL_NEGATIVE_CARRY)
        # -5.01 → CARRY_TRAP
        label_trap = _carry_label(10.0, -5.01)
        self.assertEqual(label_trap, LABEL_CARRY_TRAP)

    def test_neutral_zero_net_carry(self):
        label = _carry_label(30.0, 0.0)
        self.assertEqual(label, LABEL_NEUTRAL)


# ===========================================================================
# 6. _build_recommendations helper
# ===========================================================================
class TestBuildRecommendations(unittest.TestCase):

    def test_carry_trap_rec(self):
        recs = _build_recommendations(LABEL_CARRY_TRAP, -7.0, 20.0, 60.0, True)
        self.assertTrue(any("Avoid" in r for r in recs))

    def test_high_oracle_risk_rec(self):
        recs = _build_recommendations(LABEL_NEUTRAL, 1.0, 75.0, 60.0, False)
        self.assertTrue(any("oracle" in r.lower() for r in recs))

    def test_high_ltv_rec(self):
        recs = _build_recommendations(LABEL_POSITIVE_CARRY, 2.0, 30.0, 85.0, False)
        self.assertTrue(any("LTV" in r or "ltv" in r.lower() for r in recs))

    def test_rebasing_rec(self):
        recs = _build_recommendations(LABEL_OPTIMAL_CARRY, 5.0, 20.0, 70.0, True)
        self.assertTrue(any("rebase" in r.lower() for r in recs))

    def test_optimal_carry_positive_rec(self):
        recs = _build_recommendations(LABEL_OPTIMAL_CARRY, 5.0, 20.0, 70.0, False)
        self.assertTrue(any("carry" in r.lower() or "favourable" in r.lower() for r in recs))

    def test_always_returns_list(self):
        recs = _build_recommendations(LABEL_NEUTRAL, 0.5, 20.0, 50.0, False)
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)


# ===========================================================================
# 7. DeFiProtocolYieldBearingCollateralAnalyzer.analyze — output structure
# ===========================================================================
class TestAnalyzeOutputStructure(unittest.TestCase):

    def setUp(self):
        self.result = _default_analyze()

    def test_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_required_keys(self):
        for key in [
            "collateral_token", "underlying_apy_pct", "borrow_rate_pct",
            "ltv_pct", "position_size_usd", "collateral_rebasing",
            "liquidation_premium_pct", "oracle_lag_seconds",
            "net_carry_pct", "yield_offset_ratio", "carry_trade_score",
            "oracle_risk_score", "label", "borrow_usd",
            "annual_yield_usd", "annual_borrow_cost_usd", "annual_net_pnl_usd",
            "recommendations", "ts",
        ]:
            self.assertIn(key, self.result, f"Missing key: {key}")

    def test_carry_trade_score_range(self):
        self.assertGreaterEqual(self.result["carry_trade_score"], 0.0)
        self.assertLessEqual(self.result["carry_trade_score"], 100.0)

    def test_oracle_risk_score_range(self):
        self.assertGreaterEqual(self.result["oracle_risk_score"], 0.0)
        self.assertLessEqual(self.result["oracle_risk_score"], 100.0)

    def test_label_valid(self):
        valid = {LABEL_OPTIMAL_CARRY, LABEL_POSITIVE_CARRY, LABEL_NEUTRAL,
                 LABEL_NEGATIVE_CARRY, LABEL_CARRY_TRAP}
        self.assertIn(self.result["label"], valid)

    def test_recommendations_nonempty_list(self):
        self.assertIsInstance(self.result["recommendations"], list)
        self.assertGreater(len(self.result["recommendations"]), 0)

    def test_ts_reasonable(self):
        now = int(time.time())
        self.assertLessEqual(abs(self.result["ts"] - now), 5)

    def test_input_echo(self):
        self.assertEqual(self.result["collateral_token"], "stETH")
        self.assertAlmostEqual(self.result["underlying_apy_pct"], 4.0)
        self.assertAlmostEqual(self.result["borrow_rate_pct"], 3.0)

    def test_borrow_usd_computation(self):
        r = _default_analyze(ltv_pct=70.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["borrow_usd"], 70_000.0)

    def test_annual_yield_computation(self):
        r = _default_analyze(underlying_apy_pct=5.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["annual_yield_usd"], 5000.0)

    def test_annual_borrow_cost_computation(self):
        r = _default_analyze(borrow_rate_pct=4.0, ltv_pct=50.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["annual_borrow_cost_usd"], 2000.0)

    def test_net_pnl_matches(self):
        r = _default_analyze(
            underlying_apy_pct=5.0, borrow_rate_pct=4.0,
            ltv_pct=50.0, position_size_usd=100_000.0,
        )
        expected = r["annual_yield_usd"] - r["annual_borrow_cost_usd"]
        self.assertAlmostEqual(r["annual_net_pnl_usd"], expected)


# ===========================================================================
# 8. Label scenarios
# ===========================================================================
class TestAnalyzeLabelScenarios(unittest.TestCase):

    def test_optimal_carry_scenario(self):
        r = _default_analyze(
            underlying_apy_pct=15.0, borrow_rate_pct=3.0,
            ltv_pct=80.0, collateral_rebasing=True,
        )
        self.assertEqual(r["label"], LABEL_OPTIMAL_CARRY)

    def test_carry_trap_scenario(self):
        r = _default_analyze(underlying_apy_pct=1.0, borrow_rate_pct=8.0)
        self.assertEqual(r["label"], LABEL_CARRY_TRAP)

    def test_negative_carry_scenario(self):
        r = _default_analyze(
            underlying_apy_pct=2.0, borrow_rate_pct=5.0,
            ltv_pct=50.0, collateral_rebasing=False,
        )
        self.assertIn(r["label"], {LABEL_NEGATIVE_CARRY, LABEL_CARRY_TRAP})

    def test_positive_carry_scenario(self):
        r = _default_analyze(underlying_apy_pct=7.0, borrow_rate_pct=3.0, ltv_pct=60.0)
        self.assertIn(r["label"], {LABEL_POSITIVE_CARRY, LABEL_OPTIMAL_CARRY})

    def test_neutral_scenario(self):
        r = _default_analyze(underlying_apy_pct=3.0, borrow_rate_pct=3.0, ltv_pct=40.0)
        self.assertIn(r["label"], {LABEL_NEUTRAL, LABEL_POSITIVE_CARRY, LABEL_NEGATIVE_CARRY})


# ===========================================================================
# 9. Collateral tokens variety
# ===========================================================================
class TestCollateralTokens(unittest.TestCase):

    def _run(self, token):
        r = _default_analyze(collateral_token=token)
        self.assertEqual(r["collateral_token"], token)
        self.assertIn("label", r)

    def test_steth(self):    self._run("stETH")
    def test_ausdc(self):    self._run("aUSDC")
    def test_sdai(self):     self._run("sDAI")
    def test_wsteth(self):   self._run("wstETH")
    def test_reth(self):     self._run("rETH")
    def test_frax(self):     self._run("sFRAX")
    def test_cbeth(self):    self._run("cbETH")


# ===========================================================================
# 10. Edge cases
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_zero_underlying_apy(self):
        r = _default_analyze(underlying_apy_pct=0.0, borrow_rate_pct=0.0)
        self.assertAlmostEqual(r["net_carry_pct"], 0.0)

    def test_zero_position_size(self):
        r = _default_analyze(position_size_usd=0.0)
        self.assertAlmostEqual(r["borrow_usd"], 0.0)
        self.assertAlmostEqual(r["annual_yield_usd"], 0.0)

    def test_100_ltv(self):
        r = _default_analyze(ltv_pct=100.0)
        self.assertAlmostEqual(r["borrow_usd"], r["position_size_usd"])

    def test_very_high_oracle_lag(self):
        r = _default_analyze(oracle_lag_seconds=86400.0)
        self.assertGreater(r["oracle_risk_score"], 60.0)

    def test_no_rebasing(self):
        r = _default_analyze(collateral_rebasing=False)
        self.assertFalse(r["collateral_rebasing"])

    def test_large_liquidation_premium(self):
        r = _default_analyze(liquidation_premium_pct=20.0)
        s_low = _oracle_risk_score(300.0, 70.0, 0.0)
        s_hi  = _oracle_risk_score(300.0, 70.0, 20.0)
        self.assertGreater(s_low, s_hi)

    def test_large_position(self):
        r = _default_analyze(position_size_usd=10_000_000.0)
        self.assertGreater(r["annual_yield_usd"], 0)

    def test_tiny_position(self):
        r = _default_analyze(position_size_usd=1.0)
        self.assertGreater(r["carry_trade_score"], 0)


# ===========================================================================
# 11. Validation errors
# ===========================================================================
class TestValidationErrors(unittest.TestCase):

    def test_invalid_ltv_zero(self):
        with self.assertRaises(ValueError):
            _default_analyze(ltv_pct=0.0)

    def test_invalid_ltv_over_100(self):
        with self.assertRaises(ValueError):
            _default_analyze(ltv_pct=101.0)

    def test_negative_position_size(self):
        with self.assertRaises(ValueError):
            _default_analyze(position_size_usd=-1.0)

    def test_negative_oracle_lag(self):
        with self.assertRaises(ValueError):
            _default_analyze(oracle_lag_seconds=-1.0)


# ===========================================================================
# 12. Module-level analyze() function
# ===========================================================================
class TestModuleLevelAnalyze(unittest.TestCase):

    def test_returns_dict(self):
        r = analyze(
            collateral_token="sDAI",
            underlying_apy_pct=5.0,
            borrow_rate_pct=3.0,
            ltv_pct=75.0,
            position_size_usd=50_000.0,
            log_path=_tmp_log(),
        )
        self.assertIsInstance(r, dict)
        self.assertIn("label", r)

    def test_label_is_string(self):
        r = analyze(
            collateral_token="aUSDC",
            underlying_apy_pct=4.5,
            borrow_rate_pct=3.5,
            ltv_pct=80.0,
            position_size_usd=20_000.0,
            log_path=_tmp_log(),
        )
        self.assertIsInstance(r["label"], str)


# ===========================================================================
# 13. Logging
# ===========================================================================
class TestAtomicLog(unittest.TestCase):

    def test_creates_log_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))

    def test_appends_entries(self):
        path = _tmp_log()
        _atomic_log(path, {"a": 1})
        _atomic_log(path, {"b": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(110):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 104)

    def test_log_via_analyze(self):
        path = _tmp_log()
        a = DeFiProtocolYieldBearingCollateralAnalyzer(log_path=path)
        a.analyze(
            collateral_token="stETH",
            underlying_apy_pct=5.0,
            borrow_rate_pct=3.0,
            ltv_pct=70.0,
            position_size_usd=50_000.0,
            log=True,
        )
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["collateral_token"], "stETH")

    def test_existing_invalid_json_reset(self):
        path = _tmp_log()
        with open(path, "w") as f:
            f.write("not json")
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_no_log_by_default(self):
        path = _tmp_log()
        a = DeFiProtocolYieldBearingCollateralAnalyzer(log_path=path)
        a.analyze(
            collateral_token="stETH",
            underlying_apy_pct=5.0,
            borrow_rate_pct=3.0,
            ltv_pct=70.0,
            position_size_usd=50_000.0,
            log=False,
        )
        self.assertFalse(os.path.exists(path))


# ===========================================================================
# 14. Net carry pct consistency
# ===========================================================================
class TestNetCarryConsistency(unittest.TestCase):

    def test_net_carry_matches_inputs(self):
        r = _default_analyze(underlying_apy_pct=6.0, borrow_rate_pct=2.0)
        self.assertAlmostEqual(r["net_carry_pct"], 4.0)

    def test_yield_offset_ratio_consistent(self):
        r = _default_analyze(underlying_apy_pct=3.0, borrow_rate_pct=6.0)
        expected = _yield_offset_ratio(3.0, 6.0)
        self.assertAlmostEqual(r["yield_offset_ratio"], round(expected, 4))

    def test_carry_score_consistent(self):
        r = _default_analyze(
            underlying_apy_pct=4.0, borrow_rate_pct=3.0,
            ltv_pct=70.0, collateral_rebasing=True,
        )
        nc = _net_carry(4.0, 3.0)
        yo = _yield_offset_ratio(4.0, 3.0)
        score = _carry_trade_score(nc, yo, 70.0, True)
        self.assertAlmostEqual(r["carry_trade_score"], round(score, 2))

    def test_oracle_score_consistent(self):
        r = _default_analyze(oracle_lag_seconds=300.0, ltv_pct=70.0, liquidation_premium_pct=5.0)
        expected = _oracle_risk_score(300.0, 70.0, 5.0)
        self.assertAlmostEqual(r["oracle_risk_score"], round(expected, 2))


# ===========================================================================
# 15. Additional coverage
# ===========================================================================
class TestAdditionalCoverage(unittest.TestCase):

    def test_very_low_ltv(self):
        r = _default_analyze(ltv_pct=1.0)
        self.assertGreater(r["carry_trade_score"], 0.0)

    def test_high_underlying_apy(self):
        r = _default_analyze(underlying_apy_pct=30.0, borrow_rate_pct=3.0)
        self.assertIn(r["label"], {LABEL_OPTIMAL_CARRY, LABEL_POSITIVE_CARRY})

    def test_equal_rates_neutral(self):
        r = _default_analyze(underlying_apy_pct=4.0, borrow_rate_pct=4.0, ltv_pct=50.0)
        self.assertAlmostEqual(r["net_carry_pct"], 0.0)

    def test_recs_is_list_of_strings(self):
        r = _default_analyze()
        for rec in r["recommendations"]:
            self.assertIsInstance(rec, str)

    def test_float_precision_output(self):
        r = _default_analyze(underlying_apy_pct=3.333, borrow_rate_pct=1.111)
        # Should be rounded to 4 decimal places
        nc = r["net_carry_pct"]
        self.assertEqual(nc, round(nc, 4))

    def test_multiple_runs_independent(self):
        r1 = _default_analyze(underlying_apy_pct=5.0, borrow_rate_pct=2.0)
        r2 = _default_analyze(underlying_apy_pct=2.0, borrow_rate_pct=5.0)
        self.assertNotEqual(r1["label"], r2["label"])

    def test_collateral_token_preserved(self):
        for tok in ["stETH", "aUSDC", "sDAI", "rETH"]:
            r = _default_analyze(collateral_token=tok)
            self.assertEqual(r["collateral_token"], tok)

    def test_oracle_lag_zero_low_risk(self):
        r = _default_analyze(oracle_lag_seconds=0.0, ltv_pct=30.0, liquidation_premium_pct=10.0)
        self.assertLess(r["oracle_risk_score"], 20.0)

    def test_net_pnl_positive_when_positive_carry(self):
        r = _default_analyze(
            underlying_apy_pct=10.0, borrow_rate_pct=3.0,
            ltv_pct=50.0, position_size_usd=100_000.0,
        )
        self.assertGreater(r["annual_net_pnl_usd"], 0.0)

    def test_net_pnl_negative_when_negative_carry(self):
        r = _default_analyze(
            underlying_apy_pct=1.0, borrow_rate_pct=8.0,
            ltv_pct=80.0, position_size_usd=100_000.0,
        )
        self.assertLess(r["annual_net_pnl_usd"], 0.0)

    def test_deterministic(self):
        r1 = _default_analyze(underlying_apy_pct=5.0, borrow_rate_pct=3.0)
        r2 = _default_analyze(underlying_apy_pct=5.0, borrow_rate_pct=3.0)
        self.assertEqual(r1["label"], r2["label"])
        self.assertEqual(r1["net_carry_pct"], r2["net_carry_pct"])


if __name__ == "__main__":
    unittest.main()
