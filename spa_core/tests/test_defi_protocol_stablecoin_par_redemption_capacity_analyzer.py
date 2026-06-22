"""
Tests for MP-1148: DeFiProtocolStablecoinParRedemptionCapacityAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_stablecoin_par_redemption_capacity_analyzer -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_stablecoin_par_redemption_capacity_analyzer import (
    DeFiProtocolStablecoinParRedemptionCapacityAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    token="USDC",
    position_usd=500_000.0,
    daily_redemption_cap_usd=50_000_000.0,
    liquid_backing_usd=30_000_000_000.0,
    total_supply_usd=32_000_000_000.0,
    redemption_fee_pct=0.0,
    redemption_delay_days=0.0,
    secondary_depth_usd=20_000_000.0,
    secondary_slippage_pct=0.02,
):
    return {
        "token": token,
        "position_usd": position_usd,
        "daily_redemption_cap_usd": daily_redemption_cap_usd,
        "liquid_backing_usd": liquid_backing_usd,
        "total_supply_usd": total_supply_usd,
        "redemption_fee_pct": redemption_fee_pct,
        "redemption_delay_days": redemption_delay_days,
        "secondary_depth_usd": secondary_depth_usd,
        "secondary_slippage_pct": secondary_slippage_pct,
    }


def A():
    return DeFiProtocolStablecoinParRedemptionCapacityAnalyzer()


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid(self):
        self.assertEqual(_f("3.5"), 3.5)
        self.assertEqual(_f(7), 7.0)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_value(self):
        self.assertEqual(_f("abc"), 0.0)
        self.assertEqual(_f([], 1.0), 1.0)

    def test_clamp_bounds(self):
        self.assertEqual(_clamp(5, 0, 10), 5)
        self.assertEqual(_clamp(-1, 0, 10), 0)
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2, 1e9), 5.0)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(10, 0, 1e9), 1e9)

    def test_safe_div_negative_denominator(self):
        self.assertEqual(_safe_div(10, -5, 7.0), 7.0)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_grade_from_score_bands(self):
        self.assertEqual(_grade_from_score(90), "A")
        self.assertEqual(_grade_from_score(72), "B")
        self.assertEqual(_grade_from_score(60), "C")
        self.assertEqual(_grade_from_score(45), "D")
        self.assertEqual(_grade_from_score(10), "F")

    def test_grade_boundaries(self):
        self.assertEqual(_grade_from_score(85), "A")
        self.assertEqual(_grade_from_score(70), "B")
        self.assertEqual(_grade_from_score(55), "C")
        self.assertEqual(_grade_from_score(40), "D")
        self.assertEqual(_grade_from_score(39.9), "F")


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "position_usd", "days_to_par_exit",
            "redemption_capacity_utilization_pct", "backing_coverage_ratio",
            "net_par_proceeds_pct", "supply_share_pct", "recommended_exit_route",
            "par_exit_feasible", "redemption_capacity_score", "classification",
            "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["redemption_capacity_score"], 0.0)
        self.assertLessEqual(self.r["redemption_capacity_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC")

    def test_feasible_is_bool(self):
        self.assertIsInstance(self.r["par_exit_feasible"], bool)

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_ample_capacity_deep_liquid(self):
        r = A().analyze(make_pos())
        self.assertEqual(r["classification"], "AMPLE_CAPACITY")
        self.assertEqual(r["grade"], "A")
        self.assertIn("AMPLE_CAPACITY", r["flags"])

    def test_trapped_no_primary_no_secondary(self):
        r = A().analyze(make_pos(
            daily_redemption_cap_usd=0.0,
            liquid_backing_usd=1.0,  # enough to pass insufficient-data gate
            secondary_depth_usd=0.0,
        ))
        self.assertEqual(r["classification"], "TRAPPED")
        self.assertIn("TRAPPED_AT_PAR", r["flags"])
        self.assertEqual(r["recommended_exit_route"], "TRAPPED")

    def test_tight_slow_queue(self):
        r = A().analyze(make_pos(
            position_usd=2_000_000.0,
            daily_redemption_cap_usd=250_000.0,
            liquid_backing_usd=1_000_000.0,
            redemption_delay_days=3.0,
            secondary_depth_usd=300_000.0,
            secondary_slippage_pct=1.2,
        ))
        self.assertEqual(r["classification"], "TIGHT")

    def test_adequate_mid_range(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            daily_redemption_cap_usd=600_000.0,
            liquid_backing_usd=900_000.0,
            redemption_delay_days=0.0,
            secondary_depth_usd=0.0,
        ))
        # ceil(1.0/0.6)=2 days, backing 0.9 ≥ thin → ADEQUATE
        self.assertEqual(r["classification"], "ADEQUATE")

    def test_constrained_week_range(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            daily_redemption_cap_usd=200_000.0,
            liquid_backing_usd=300_000.0,
            redemption_delay_days=0.0,
            secondary_depth_usd=0.0,
        ))
        # ceil(5)=5 days → CONSTRAINED
        self.assertEqual(r["classification"], "CONSTRAINED")

    def test_classification_is_known_value(self):
        for pos in [make_pos(), make_pos(daily_redemption_cap_usd=0, secondary_depth_usd=0, liquid_backing_usd=1)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "AMPLE_CAPACITY", "ADEQUATE", "CONSTRAINED", "TIGHT",
                "TRAPPED", "INSUFFICIENT_DATA",
            })


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_position(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_position(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_paths_at_all(self):
        r = A().analyze({
            "token": "X",
            "position_usd": 1000.0,
            "daily_redemption_cap_usd": 0.0,
            "liquid_backing_usd": 0.0,
            "secondary_depth_usd": 0.0,
        })
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["redemption_capacity_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_days_to_par_exit_with_delay(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            daily_redemption_cap_usd=500_000.0,
            redemption_delay_days=2.0,
            liquid_backing_usd=2_000_000.0,
            secondary_depth_usd=0.0,
        ))
        # ceil(2) + 2 = 4
        self.assertAlmostEqual(r["days_to_par_exit"], 4.0)

    def test_utilization_pct(self):
        r = A().analyze(make_pos(
            position_usd=100_000.0,
            daily_redemption_cap_usd=200_000.0,
        ))
        self.assertAlmostEqual(r["redemption_capacity_utilization_pct"], 50.0)

    def test_utilization_none_when_no_cap(self):
        r = A().analyze(make_pos(
            daily_redemption_cap_usd=0.0,
            secondary_depth_usd=20_000_000.0,
        ))
        self.assertIsNone(r["redemption_capacity_utilization_pct"])

    def test_backing_coverage_ratio(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            liquid_backing_usd=500_000.0,
        ))
        self.assertAlmostEqual(r["backing_coverage_ratio"], 0.5)

    def test_net_par_proceeds_with_fee(self):
        r = A().analyze(make_pos(redemption_fee_pct=0.25))
        self.assertAlmostEqual(r["net_par_proceeds_pct"], 99.75)

    def test_net_par_proceeds_floored_at_zero(self):
        r = A().analyze(make_pos(redemption_fee_pct=150.0))
        self.assertEqual(r["net_par_proceeds_pct"], 0.0)

    def test_supply_share_pct(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            total_supply_usd=100_000_000.0,
        ))
        self.assertAlmostEqual(r["supply_share_pct"], 1.0)

    def test_supply_share_zero_when_unknown(self):
        r = A().analyze(make_pos(total_supply_usd=0.0))
        self.assertEqual(r["supply_share_pct"], 0.0)

    def test_days_none_when_no_primary_cap(self):
        r = A().analyze(make_pos(
            daily_redemption_cap_usd=0.0,
            secondary_depth_usd=1_000_000.0,
            secondary_slippage_pct=0.05,
        ))
        self.assertIsNone(r["days_to_par_exit"])

    def test_high_fee_flag(self):
        r = A().analyze(make_pos(redemption_fee_pct=0.75))
        self.assertIn("HIGH_REDEMPTION_FEE", r["flags"])

    def test_backing_shortfall_flag(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            liquid_backing_usd=400_000.0,
        ))
        self.assertIn("BACKING_SHORTFALL", r["flags"])

    def test_exceeds_daily_cap_flag(self):
        r = A().analyze(make_pos(
            position_usd=2_000_000.0,
            daily_redemption_cap_usd=250_000.0,
        ))
        self.assertIn("EXCEEDS_DAILY_CAP", r["flags"])

    def test_high_utilization_flag(self):
        r = A().analyze(make_pos(
            position_usd=90_000.0,
            daily_redemption_cap_usd=100_000.0,
        ))
        self.assertIn("HIGH_CAPACITY_UTILIZATION", r["flags"])

    def test_no_primary_redemption_flag(self):
        r = A().analyze(make_pos(
            daily_redemption_cap_usd=0.0,
            secondary_depth_usd=20_000_000.0,
        ))
        self.assertIn("NO_PRIMARY_REDEMPTION", r["flags"])


# ── route selection ───────────────────────────────────────────────────────────

class TestRoute(unittest.TestCase):
    def test_primary_redeem_when_backed(self):
        r = A().analyze(make_pos(
            secondary_depth_usd=0.0,
        ))
        self.assertEqual(r["recommended_exit_route"], "PRIMARY_REDEEM")

    def test_secondary_market_when_primary_unbacked(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            daily_redemption_cap_usd=100_000.0,
            liquid_backing_usd=10_000.0,       # primary not fully backed
            secondary_depth_usd=2_000_000.0,
            secondary_slippage_pct=0.05,       # tight
        ))
        self.assertEqual(r["recommended_exit_route"], "SECONDARY_MARKET")

    def test_split_when_neither_fully_clears(self):
        r = A().analyze(make_pos(
            position_usd=2_000_000.0,
            daily_redemption_cap_usd=250_000.0,
            liquid_backing_usd=1_000_000.0,    # primary partial
            secondary_depth_usd=300_000.0,     # secondary partial
            secondary_slippage_pct=1.2,
        ))
        self.assertEqual(r["recommended_exit_route"], "SPLIT_PRIMARY_AND_SECONDARY")

    def test_trapped_route(self):
        r = A().analyze(make_pos(
            daily_redemption_cap_usd=0.0,
            liquid_backing_usd=1.0,
            secondary_depth_usd=0.0,
        ))
        self.assertEqual(r["recommended_exit_route"], "TRAPPED")

    def test_secondary_preferred_flag(self):
        r = A().analyze(make_pos(
            position_usd=1_000_000.0,
            daily_redemption_cap_usd=100_000.0,
            liquid_backing_usd=10_000.0,
            secondary_depth_usd=2_000_000.0,
            secondary_slippage_pct=0.05,
        ))
        self.assertIn("SECONDARY_PREFERRED", r["flags"])


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_faster_exit_scores_higher(self):
        fast = A().analyze(make_pos(
            position_usd=1_000_000.0, daily_redemption_cap_usd=5_000_000.0,
            liquid_backing_usd=5_000_000.0, secondary_depth_usd=0.0,
        ))
        slow = A().analyze(make_pos(
            position_usd=1_000_000.0, daily_redemption_cap_usd=100_000.0,
            liquid_backing_usd=5_000_000.0, secondary_depth_usd=0.0,
        ))
        self.assertGreater(
            fast["redemption_capacity_score"], slow["redemption_capacity_score"]
        )

    def test_higher_fee_scores_lower(self):
        cheap = A().analyze(make_pos(redemption_fee_pct=0.0))
        pricey = A().analyze(make_pos(redemption_fee_pct=1.0))
        self.assertGreater(
            cheap["redemption_capacity_score"], pricey["redemption_capacity_score"]
        )

    def test_better_backing_scores_higher(self):
        good = A().analyze(make_pos(
            position_usd=1_000_000.0, daily_redemption_cap_usd=200_000.0,
            liquid_backing_usd=1_000_000.0, secondary_depth_usd=0.0,
        ))
        bad = A().analyze(make_pos(
            position_usd=1_000_000.0, daily_redemption_cap_usd=200_000.0,
            liquid_backing_usd=300_000.0, secondary_depth_usd=0.0,
        ))
        self.assertGreater(
            good["redemption_capacity_score"], bad["redemption_capacity_score"]
        )

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(
            position_usd=1.0, daily_redemption_cap_usd=1e12,
            liquid_backing_usd=1e15, redemption_fee_pct=0.0,
            secondary_depth_usd=1e12, secondary_slippage_pct=0.0,
        ))
        self.assertLessEqual(r["redemption_capacity_score"], 100.0)
        self.assertGreaterEqual(r["redemption_capacity_score"], 0.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(token="USDC"),
            make_pos(
                token="Tight", position_usd=2_000_000.0,
                daily_redemption_cap_usd=250_000.0, liquid_backing_usd=1_000_000.0,
                secondary_depth_usd=300_000.0, secondary_slippage_pct=1.2,
            ),
            make_pos(
                token="Trapped", daily_redemption_cap_usd=0.0,
                liquid_backing_usd=1.0, secondary_depth_usd=0.0,
            ),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_constrained_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["redemption_capacity_score"]
                  for p in self.res["positions"]}
        most = agg["most_constrained_position"]
        self.assertEqual(scores[most], min(scores.values()))

    def test_least_constrained_is_highest_score(self):
        agg = self.res["aggregate"]
        self.assertEqual(agg["least_constrained_position"], "USDC")

    def test_trapped_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["trapped_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_redemption_capacity_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_constrained_position"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(position_usd=0.0), make_pos(position_usd=-1.0),
        ])
        self.assertIsNone(res["aggregate"]["least_constrained_position"])
        self.assertEqual(res["aggregate"]["avg_redemption_capacity_score"], 0.0)


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": 3}
            for _ in range(6):
                A().analyze_portfolio([make_pos()], cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_corrupt_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{not valid json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_has_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos(), make_pos(token="B")],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["position_count"], 2)
            self.assertEqual(len(data[0]["snapshots"]), 2)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "token": "S",
            "position_usd": "500000",
            "daily_redemption_cap_usd": "50000000",
            "liquid_backing_usd": "30000000000",
            "secondary_depth_usd": "0",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "token": "S",
            "position_usd": 100_000.0,
            "daily_redemption_cap_usd": 1_000_000.0,
            "liquid_backing_usd": 1_000_000.0,
        })
        self.assertIn("classification", r)

    def test_negative_fee_treated_as_zero(self):
        r = A().analyze(make_pos(redemption_fee_pct=-5.0))
        self.assertEqual(r["net_par_proceeds_pct"], 100.0)

    def test_negative_delay_treated_as_zero(self):
        r = A().analyze(make_pos(
            position_usd=500_000.0, daily_redemption_cap_usd=500_000.0,
            redemption_delay_days=-3.0, liquid_backing_usd=1_000_000.0,
            secondary_depth_usd=0.0,
        ))
        self.assertAlmostEqual(r["days_to_par_exit"], 1.0)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio([make_pos(token=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(daily_redemption_cap_usd=0, secondary_depth_usd=0, liquid_backing_usd=1),
        ])
        json.dumps(res)


if __name__ == "__main__":
    unittest.main()
