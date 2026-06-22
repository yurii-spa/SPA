"""
Tests for MP-828 CrossProtocolYieldOptimizer.
Run: python3 -m unittest spa_core.tests.test_cross_protocol_yield_optimizer -v
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import spa_core.analytics.cross_protocol_yield_optimizer as opt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opp(protocol="Aave", apy=5.0, risk=20, min_dep=500.0, max_cap=None):
    return {
        "protocol": protocol,
        "apy": apy,
        "risk_score": risk,
        "min_deposit_usd": min_dep,
        "max_capacity_usd": max_cap,
    }


def _run(capital, opps, constraints=None):
    with patch.object(opt, "_append_log", return_value=None):
        return opt.analyze(capital, opps, constraints)


# ---------------------------------------------------------------------------
# TestZeroAndEmpty
# ---------------------------------------------------------------------------

class TestZeroAndEmpty(unittest.TestCase):
    def test_empty_opportunities(self):
        r = _run(10000, [])
        self.assertEqual(r["allocation"], [])
        self.assertAlmostEqual(r["blended_apy"], 0.0)

    def test_zero_capital(self):
        r = _run(0, [_opp()])
        self.assertEqual(r["allocation"], [])
        self.assertAlmostEqual(r["unallocated_usd"], 0.0)

    def test_zero_capital_blended_apy_zero(self):
        r = _run(0, [_opp()])
        self.assertAlmostEqual(r["blended_apy"], 0.0)

    def test_total_opportunities_empty(self):
        r = _run(10000, [])
        self.assertEqual(r["total_opportunities"], 0)

    def test_optimization_method_always_present(self):
        r = _run(0, [])
        self.assertEqual(r["optimization_method"], "risk_adjusted_ranking")


# ---------------------------------------------------------------------------
# TestFiltering
# ---------------------------------------------------------------------------

class TestFiltering(unittest.TestCase):
    def test_filter_high_risk(self):
        opps = [_opp("Safe", risk=50), _opp("Risky", risk=80)]
        r = _run(10000, opps)
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertNotIn("Risky", protocols)

    def test_filter_exactly_at_max_risk_allowed(self):
        # default max_risk = 70 → risk=70 should pass
        r = _run(10000, [_opp("X", risk=70)])
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertIn("X", protocols)

    def test_filter_risk_71_excluded(self):
        r = _run(10000, [_opp("X", risk=71)])
        self.assertEqual(r["allocation"], [])

    def test_filter_low_apy(self):
        opps = [_opp("A", apy=5.0), _opp("B", apy=-1.0)]
        r = _run(10000, opps, {"min_apy": 0.0})
        # -1 < 0 should be filtered but default min_apy=0; -1 < 0 fails
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertNotIn("B", protocols)

    def test_filter_custom_min_apy(self):
        opps = [_opp("A", apy=3.0), _opp("B", apy=6.0)]
        r = _run(10000, opps, {"min_apy": 5.0})
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertNotIn("A", protocols)
        self.assertIn("B", protocols)

    def test_filter_min_deposit_too_high(self):
        # capital=10000, max_positions=5 → threshold=2000
        # min_deposit=3000 → filtered out
        opps = [_opp("A", min_dep=3000), _opp("B", min_dep=500)]
        r = _run(10000, opps)
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertNotIn("A", protocols)

    def test_filter_min_deposit_at_threshold_passes(self):
        # threshold = 10000/5 = 2000, min_dep=2000 → passes
        r = _run(10000, [_opp("A", min_dep=2000)])
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertIn("A", protocols)

    def test_filtered_opportunities_count(self):
        opps = [_opp("A", risk=50), _opp("B", risk=80)]
        r = _run(10000, opps)
        self.assertEqual(r["filtered_opportunities"], 1)

    def test_total_opportunities_count(self):
        opps = [_opp("A"), _opp("B"), _opp("C")]
        r = _run(10000, opps)
        self.assertEqual(r["total_opportunities"], 3)

    def test_all_filtered_out(self):
        r = _run(10000, [_opp("X", risk=90)])
        self.assertEqual(r["allocation"], [])
        self.assertAlmostEqual(r["unallocated_usd"], 10000.0, places=2)


# ---------------------------------------------------------------------------
# TestSorting
# ---------------------------------------------------------------------------

class TestSorting(unittest.TestCase):
    def test_sorted_by_risk_adjusted_apy(self):
        # A: apy=10, risk=50 → ra=5.0; B: apy=8, risk=10 → ra=7.2
        # B should be preferred (higher ra_apy)
        opps = [_opp("A", apy=10, risk=50), _opp("B", apy=8, risk=10)]
        r = _run(10000, opps, {"max_positions": 1})
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertEqual(protocols[0], "B")

    def test_high_apy_low_risk_first(self):
        opps = [
            _opp("Low", apy=3, risk=5),    # ra = 2.85
            _opp("High", apy=20, risk=0),  # ra = 20.0
        ]
        r = _run(10000, opps, {"max_positions": 1})
        protocols = [a["protocol"] for a in r["allocation"]]
        self.assertEqual(protocols[0], "High")

    def test_risk_adjusted_apy_field_correct(self):
        r = _run(10000, [_opp("X", apy=10.0, risk=20)])
        a = r["allocation"][0]
        self.assertAlmostEqual(a["risk_adjusted_apy"], 10.0 * 0.80, places=4)

    def test_risk_adjusted_apy_zero_risk(self):
        r = _run(10000, [_opp("X", apy=10.0, risk=0)])
        a = r["allocation"][0]
        self.assertAlmostEqual(a["risk_adjusted_apy"], 10.0, places=4)

    def test_risk_adjusted_apy_100_risk(self):
        # risk=100 → ra_apy = 0; should still pass filter if max_risk=100
        r = _run(10000, [_opp("X", apy=10.0, risk=100)],
                 {"max_risk_score": 100})
        a = r["allocation"][0]
        self.assertAlmostEqual(a["risk_adjusted_apy"], 0.0, places=4)

    def test_max_positions_limits_allocation(self):
        opps = [_opp(str(i), apy=5+i, risk=10) for i in range(10)]
        r = _run(10000, opps, {"max_positions": 3})
        self.assertLessEqual(len(r["allocation"]), 3)


# ---------------------------------------------------------------------------
# TestAllocation
# ---------------------------------------------------------------------------

class TestAllocation(unittest.TestCase):
    def test_single_opportunity_gets_full_capital(self):
        r = _run(10000, [_opp("A", apy=5, risk=20)],
                 {"max_single_position_pct": 100.0})
        a = r["allocation"][0]
        self.assertAlmostEqual(a["allocated_usd"], 10000.0, places=2)

    def test_two_equal_split(self):
        opps = [_opp("A", apy=5), _opp("B", apy=5)]
        r = _run(10000, opps, {"max_single_position_pct": 100.0})
        allocs = sorted(a["allocated_usd"] for a in r["allocation"])
        self.assertAlmostEqual(allocs[0], 5000.0, places=2)
        self.assertAlmostEqual(allocs[1], 5000.0, places=2)

    def test_max_capacity_cap(self):
        # A has max_capacity=3000, base=5000 → capped at 3000
        opps = [_opp("A", apy=10, max_cap=3000), _opp("B", apy=5)]
        r = _run(10000, opps)
        alloc_A = next(a["allocated_usd"] for a in r["allocation"] if a["protocol"] == "A")
        self.assertLessEqual(alloc_A, 3000.0 + 1e-6)

    def test_max_single_pct_cap(self):
        # max_positions=2 → base=5000, but pct cap=40% of 10000=4000
        opps = [_opp("A", apy=10), _opp("B", apy=5)]
        r = _run(10000, opps, {"max_single_position_pct": 40.0})
        for a in r["allocation"]:
            self.assertLessEqual(a["allocated_usd"], 4000.0 + 1e-6)

    def test_allocation_pct_sums_reasonably(self):
        opps = [_opp("A", apy=8), _opp("B", apy=6)]
        r = _run(10000, opps)
        total_pct = sum(a["allocation_pct"] for a in r["allocation"])
        self.assertLessEqual(total_pct, 100.01)

    def test_expected_annual_yield(self):
        # 10000 @ 10% APY → 1000/year
        r = _run(10000, [_opp("A", apy=10, risk=0)],
                 {"max_single_position_pct": 100.0})
        a = r["allocation"][0]
        self.assertAlmostEqual(a["expected_annual_yield_usd"], 1000.0, places=2)

    def test_unallocated_plus_allocated_equals_capital(self):
        opps = [_opp("A", apy=8), _opp("B", apy=6)]
        r = _run(10000, opps)
        total_alloc = sum(a["allocated_usd"] for a in r["allocation"])
        self.assertAlmostEqual(total_alloc + r["unallocated_usd"], 10000.0, places=4)

    def test_min_allocation_skip(self):
        # capital=1000, max_positions=5 → base=200 < min_allocation=500 → all skipped
        r = _run(1000, [_opp("A")], {"min_allocation_usd": 500.0, "max_positions": 5})
        self.assertEqual(r["allocation"], [])

    def test_allocation_keys(self):
        r = _run(10000, [_opp("A", apy=5)])
        expected_keys = {
            "protocol", "allocated_usd", "allocation_pct",
            "apy", "risk_score", "expected_annual_yield_usd",
            "risk_adjusted_apy",
        }
        self.assertEqual(set(r["allocation"][0].keys()), expected_keys)

    def test_excess_redistributed_to_uncapped(self):
        # A capped at 3000 (max_cap=3000), B uncapped → B gets 5000 + excess=2000
        opps = [_opp("A", apy=10, max_cap=3000), _opp("B", apy=5, max_cap=None)]
        r = _run(10000, opps, {"max_single_position_pct": 100.0})
        alloc_B = next((a["allocated_usd"] for a in r["allocation"] if a["protocol"] == "B"), 0)
        # B should get 5000 + 2000 = 7000
        self.assertAlmostEqual(alloc_B, 7000.0, places=2)

    def test_no_max_capacity_means_unlimited(self):
        r = _run(10000, [_opp("A", apy=10, max_cap=None)],
                 {"max_single_position_pct": 100.0})
        a = r["allocation"][0]
        self.assertAlmostEqual(a["allocated_usd"], 10000.0, places=2)

    def test_allocation_pct_correct(self):
        opps = [_opp("A", apy=5)]
        r = _run(10000, opps, {"max_single_position_pct": 100.0})
        a = r["allocation"][0]
        expected_pct = a["allocated_usd"] / 10000.0 * 100.0
        self.assertAlmostEqual(a["allocation_pct"], expected_pct, places=2)


# ---------------------------------------------------------------------------
# TestBlendedMetrics
# ---------------------------------------------------------------------------

class TestBlendedMetrics(unittest.TestCase):
    def test_blended_apy_zero_when_no_allocation(self):
        r = _run(10000, [_opp("X", risk=80)])
        self.assertAlmostEqual(r["blended_apy"], 0.0)

    def test_blended_apy_single_position(self):
        # 10000 @ 10% APY → blended = 10000*10%/10000*100 = 10%
        r = _run(10000, [_opp("A", apy=10, risk=0)],
                 {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["blended_apy"], 10.0, places=2)

    def test_expected_total_yield(self):
        r = _run(10000, [_opp("A", apy=10, risk=0)],
                 {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["expected_total_annual_yield_usd"], 1000.0, places=2)

    def test_portfolio_risk_score_zero_when_no_allocation(self):
        r = _run(10000, [_opp("X", risk=90)])
        self.assertAlmostEqual(r["portfolio_risk_score"], 0.0)

    def test_portfolio_risk_score_single(self):
        r = _run(10000, [_opp("A", apy=5, risk=30)],
                 {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["portfolio_risk_score"], 30.0, places=2)

    def test_blended_risk_adjusted_apy_single(self):
        # apy=10, risk=20 → ra=8.0
        r = _run(10000, [_opp("A", apy=10, risk=20)],
                 {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["blended_risk_adjusted_apy"], 8.0, places=2)

    def test_portfolio_risk_weighted_avg(self):
        # Two equal positions: risk 20 and 60 → avg = 40
        opps = [_opp("A", apy=8, risk=20), _opp("B", apy=8, risk=60)]
        r = _run(10000, opps, {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["portfolio_risk_score"], 40.0, places=2)

    def test_expected_total_yield_two_positions(self):
        # A: 5000 @ 8% = 400; B: 5000 @ 4% = 200 → total = 600
        opps = [_opp("A", apy=8, risk=10), _opp("B", apy=4, risk=10)]
        r = _run(10000, opps, {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["expected_total_annual_yield_usd"], 600.0, places=2)


# ---------------------------------------------------------------------------
# TestOutputShape
# ---------------------------------------------------------------------------

class TestOutputShape(unittest.TestCase):
    def setUp(self):
        self.r = _run(10000, [_opp("A")])

    def test_top_level_keys(self):
        expected = {
            "capital_usd", "total_opportunities", "filtered_opportunities",
            "allocation", "unallocated_usd", "expected_total_annual_yield_usd",
            "blended_apy", "blended_risk_adjusted_apy", "portfolio_risk_score",
            "optimization_method", "timestamp",
        }
        self.assertEqual(set(self.r.keys()), expected)

    def test_capital_usd_returned(self):
        self.assertAlmostEqual(self.r["capital_usd"], 10000.0)

    def test_allocation_is_list(self):
        self.assertIsInstance(self.r["allocation"], list)

    def test_optimization_method_value(self):
        self.assertEqual(self.r["optimization_method"], "risk_adjusted_ranking")

    def test_timestamp_present(self):
        self.assertGreater(self.r["timestamp"], 0)

    def test_returns_dict(self):
        self.assertIsInstance(self.r, dict)


# ---------------------------------------------------------------------------
# TestConstraints
# ---------------------------------------------------------------------------

class TestConstraints(unittest.TestCase):
    def test_default_max_positions_5(self):
        opps = [_opp(str(i), apy=5+i) for i in range(10)]
        r = _run(50000, opps)
        self.assertLessEqual(len(r["allocation"]), 5)

    def test_custom_max_positions_2(self):
        opps = [_opp(str(i), apy=5+i) for i in range(10)]
        r = _run(50000, opps, {"max_positions": 2})
        self.assertLessEqual(len(r["allocation"]), 2)

    def test_custom_max_risk_score(self):
        # custom max_risk=30 → risk=40 filtered out
        r = _run(10000, [_opp("X", risk=40)], {"max_risk_score": 30})
        self.assertEqual(r["allocation"], [])

    def test_custom_min_apy(self):
        r = _run(10000, [_opp("X", apy=2.0)], {"min_apy": 3.0})
        self.assertEqual(r["allocation"], [])

    def test_min_apy_exactly_passes(self):
        r = _run(10000, [_opp("X", apy=3.0)], {"min_apy": 3.0})
        self.assertEqual(len(r["allocation"]), 1)

    def test_custom_min_allocation_usd(self):
        # base = 10000/2 = 5000 >= 500 → both pass; with min=6000 → both fail
        r = _run(10000, [_opp("A"), _opp("B")], {"min_allocation_usd": 6000.0})
        self.assertEqual(r["allocation"], [])

    def test_max_single_position_pct_applied(self):
        r = _run(10000, [_opp("A")], {"max_single_position_pct": 30.0})
        if r["allocation"]:
            a = r["allocation"][0]
            self.assertLessEqual(a["allocated_usd"], 3000.0 + 1e-6)

    def test_none_constraints_uses_defaults(self):
        r = _run(10000, [_opp("A")], None)
        self.assertIn("allocation", r)

    def test_empty_constraints_uses_defaults(self):
        r = _run(10000, [_opp("A")], {})
        self.assertIn("allocation", r)


# ---------------------------------------------------------------------------
# TestLogging
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):
    def _tmp_log(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        return path

    def test_log_file_created(self):
        tmp = self._tmp_log()
        with patch.object(opt, "LOG_PATH", tmp):
            opt.analyze(10000, [_opp()])
        self.assertTrue(os.path.exists(tmp))
        os.unlink(tmp)

    def test_log_contains_entry(self):
        tmp = self._tmp_log()
        with patch.object(opt, "LOG_PATH", tmp):
            opt.analyze(10000, [_opp()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)
        os.unlink(tmp)

    def test_log_appends(self):
        tmp = self._tmp_log()
        with patch.object(opt, "LOG_PATH", tmp):
            opt.analyze(10000, [_opp()])
            opt.analyze(10000, [_opp()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)
        os.unlink(tmp)

    def test_log_ring_buffer_capped_at_100(self):
        tmp = self._tmp_log()
        with patch.object(opt, "LOG_PATH", tmp):
            for _ in range(105):
                opt.analyze(10000, [_opp()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)
        os.unlink(tmp)

    def test_log_entry_has_capital(self):
        tmp = self._tmp_log()
        with patch.object(opt, "LOG_PATH", tmp):
            opt.analyze(10000, [_opp()])
        with open(tmp) as fh:
            data = json.load(fh)
        self.assertIn("capital_usd", data[0])
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# TestSpecificScenarios
# ---------------------------------------------------------------------------

class TestSpecificScenarios(unittest.TestCase):
    def test_five_opportunities_max_three(self):
        opps = [_opp(str(i), apy=float(i+1), risk=10) for i in range(5)]
        r = _run(15000, opps, {"max_positions": 3})
        self.assertLessEqual(len(r["allocation"]), 3)

    def test_greedy_picks_best_ra_apy(self):
        # Best risk-adjusted: C: 20%*(1-0.1)=18; A: 10%*0.9=9; B: 15%*0.5=7.5
        opps = [
            _opp("A", apy=10, risk=10),
            _opp("B", apy=15, risk=50),
            _opp("C", apy=20, risk=10),
        ]
        r = _run(15000, opps, {"max_positions": 1})
        self.assertEqual(r["allocation"][0]["protocol"], "C")

    def test_large_capital_single_opp(self):
        r = _run(100000, [_opp("Aave", apy=5, risk=10)],
                 {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["allocation"][0]["allocated_usd"], 100000.0, places=2)

    def test_unallocated_when_all_capped(self):
        # both capped at 40% of 10000 = 4000 each → total=8000 → unallocated=2000
        opps = [_opp("A", apy=8), _opp("B", apy=6)]
        r = _run(10000, opps, {"max_single_position_pct": 40.0})
        # A and B each get 4000 (or 5000 if not limited)
        total_alloc = sum(a["allocated_usd"] for a in r["allocation"])
        self.assertAlmostEqual(total_alloc + r["unallocated_usd"], 10000.0, places=4)

    def test_opportunity_with_exact_capacity_equal_base(self):
        # base=5000, max_cap=5000, pct_cap disabled → not capped → each gets 5000
        r = _run(10000, [_opp("A", apy=5, max_cap=5000), _opp("B", apy=5, max_cap=5000)],
                 {"max_single_position_pct": 100.0})
        alloc_A = next(a["allocated_usd"] for a in r["allocation"] if a["protocol"] == "A")
        self.assertAlmostEqual(alloc_A, 5000.0, places=2)

    def test_filtered_count_correct_with_mixed_filters(self):
        opps = [
            _opp("A", apy=5, risk=20),   # passes
            _opp("B", apy=5, risk=80),   # fails risk
            _opp("C", apy=5, risk=30),   # passes
            _opp("D", apy=-1, risk=20),  # fails apy
        ]
        r = _run(10000, opps)
        self.assertEqual(r["filtered_opportunities"], 2)

    def test_blended_apy_weighted_correctly(self):
        # Two equal positions (pct cap=100%), A@10%, B@6%
        # yield=5000*10%+5000*6%=500+300=800 → blended=8%
        opps = [_opp("A", apy=10, risk=10), _opp("B", apy=6, risk=10)]
        r = _run(10000, opps, {"max_single_position_pct": 100.0})
        self.assertAlmostEqual(r["blended_apy"], 8.0, places=2)


if __name__ == "__main__":
    unittest.main()
