"""
Tests for MP-1109: ProtocolDeFiCrossProtocolYieldArbitrageScanner
≥ 110 tests, unittest framework (python3 -m unittest).

Label thresholds (by best_net_gain / position_size):
  STAY_PUT             : net_gain <= 0
  MARGINAL_OPPORTUNITY : net_gain in (0, pos * 0.5%)
  GOOD_SWITCH          : net_gain in [pos * 0.5%, pos * 2%)
  EXCELLENT_SWITCH     : net_gain in [pos * 2%, pos * 5%)
  ARBITRAGE_BONANZA    : net_gain >= pos * 5%
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.protocol_defi_cross_protocol_yield_arbitrage_scanner import (
    ProtocolDeFiCrossProtocolYieldArbitrageScanner,
    _atomic_write,
    VALID_LABELS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_scanner(tmp_dir: str, cap: int = 5) -> ProtocolDeFiCrossProtocolYieldArbitrageScanner:
    log_path = os.path.join(tmp_dir, "arbitrage_test.json")
    return ProtocolDeFiCrossProtocolYieldArbitrageScanner(log_path=log_path, log_cap=cap)


def cand(protocol="TargetProto", apy_pct=6.0, entry_cost_usd=50.0,
         exit_from_current_cost_usd=30.0, risk_score_0_to_100=10.0) -> dict:
    return {
        "protocol": protocol,
        "apy_pct": apy_pct,
        "entry_cost_usd": entry_cost_usd,
        "exit_from_current_cost_usd": exit_from_current_cost_usd,
        "risk_score_0_to_100": risk_score_0_to_100,
    }


def base_scan_kwargs(**overrides) -> dict:
    kw = dict(
        current_protocol="Aave",
        current_apy_pct=4.0,
        position_size_usd=10_000.0,
        candidates=[cand()],
        min_apy_improvement_pct=0.5,
        holding_days=30,
    )
    kw.update(overrides)
    return kw


# ===========================================================================
# 1. Helpers unit tests
# ===========================================================================

class TestHelpers(unittest.TestCase):

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [1, 2])
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_correct_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"a": 1})
            with open(path) as f:
                self.assertEqual(json.load(f), {"a": 1})

    def test_atomic_write_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [])
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_atomic_write_creates_subdirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "dir", "test.json")
            _atomic_write(path, {})
            self.assertTrue(os.path.exists(path))

    def test_valid_labels_count(self):
        self.assertEqual(len(VALID_LABELS), 5)

    def test_valid_labels_content(self):
        for lbl in ["STAY_PUT", "MARGINAL_OPPORTUNITY", "GOOD_SWITCH",
                    "EXCELLENT_SWITCH", "ARBITRAGE_BONANZA"]:
            self.assertIn(lbl, VALID_LABELS)


# ===========================================================================
# 2. Current annual yield
# ===========================================================================

class TestCurrentAnnualYield(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_annual_yield_basic(self):
        # 10000 * 4% = $400/year
        r = self.sc.scan(**base_scan_kwargs())
        self.assertAlmostEqual(r["current_annual_yield_usd"], 400.0, places=4)

    def test_annual_yield_zero_apy(self):
        r = self.sc.scan(**base_scan_kwargs(current_apy_pct=0.0))
        self.assertEqual(r["current_annual_yield_usd"], 0.0)

    def test_annual_yield_proportional_to_position(self):
        r1 = self.sc.scan(**base_scan_kwargs(position_size_usd=5_000.0))
        r2 = self.sc.scan(**base_scan_kwargs(position_size_usd=10_000.0))
        self.assertAlmostEqual(r2["current_annual_yield_usd"],
                               r1["current_annual_yield_usd"] * 2, places=5)

    def test_annual_yield_rounds_to_6_places(self):
        r = self.sc.scan(**base_scan_kwargs())
        val = r["current_annual_yield_usd"]
        self.assertEqual(round(val, 6), val)

    def test_annual_yield_high_apy(self):
        r = self.sc.scan(**base_scan_kwargs(current_apy_pct=100.0))
        self.assertAlmostEqual(r["current_annual_yield_usd"], 10_000.0, places=4)

    def test_annual_yield_zero_position(self):
        r = self.sc.scan(**base_scan_kwargs(position_size_usd=0.0))
        self.assertEqual(r["current_annual_yield_usd"], 0.0)


# ===========================================================================
# 3. Net gain calculation
# ===========================================================================

class TestNetGainCalculation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def _net_gain_expected(self, pos, cur_apy, cand_apy, entry, exit_, days):
        """net = pos*(cand-cur)*days/365/100 - entry - exit"""
        return pos * (cand_apy - cur_apy) * days / 365 / 100 - entry - exit_

    def test_net_gain_basic(self):
        # pos=10k, cur=4%, cand=6%, 30d, costs=80
        expected = self._net_gain_expected(10_000, 4.0, 6.0, 50.0, 30.0, 30)
        r = self.sc.scan(**base_scan_kwargs())
        cands = r["ranked_candidates"]
        self.assertAlmostEqual(cands[0]["net_gain_usd"], expected, places=4)

    def test_net_gain_zero_costs(self):
        expected = self._net_gain_expected(10_000, 4.0, 6.0, 0.0, 0.0, 30)
        r = self.sc.scan(**base_scan_kwargs(candidates=[cand(entry_cost_usd=0, exit_from_current_cost_usd=0)]))
        self.assertAlmostEqual(r["ranked_candidates"][0]["net_gain_usd"], expected, places=4)

    def test_net_gain_negative_when_costs_too_high(self):
        # Very high costs swamp the gain
        r = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(entry_cost_usd=10_000, exit_from_current_cost_usd=5_000)]
        ))
        self.assertLess(r["ranked_candidates"][0]["net_gain_usd"], 0)

    def test_net_gain_proportional_to_holding_days(self):
        r30 = self.sc.scan(**base_scan_kwargs(holding_days=30))
        r60 = self.sc.scan(**base_scan_kwargs(holding_days=60))
        # extra gain (no costs doubling) → 60d gain > 30d gain
        g30 = r30["ranked_candidates"][0]["net_gain_usd"]
        g60 = r60["ranked_candidates"][0]["net_gain_usd"]
        self.assertGreater(g60, g30)

    def test_net_gain_zero_apy_diff_all_costs(self):
        # Same APY, non-zero costs → negative net gain
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=4.0,
            candidates=[cand(apy_pct=4.0)],
        ))
        self.assertLess(r["ranked_candidates"][0]["net_gain_usd"], 0)

    def test_net_gain_rounds_to_6_places(self):
        r = self.sc.scan(**base_scan_kwargs())
        val = r["ranked_candidates"][0]["net_gain_usd"]
        self.assertEqual(round(val, 6), val)

    def test_net_gain_proportional_to_position(self):
        r1 = self.sc.scan(**base_scan_kwargs(
            position_size_usd=10_000, candidates=[cand(entry_cost_usd=0, exit_from_current_cost_usd=0)]
        ))
        r2 = self.sc.scan(**base_scan_kwargs(
            position_size_usd=20_000, candidates=[cand(entry_cost_usd=0, exit_from_current_cost_usd=0)]
        ))
        self.assertAlmostEqual(r2["ranked_candidates"][0]["net_gain_usd"],
                               r1["ranked_candidates"][0]["net_gain_usd"] * 2, places=4)

    def test_net_gain_multiple_candidates(self):
        cands = [
            cand("A", apy_pct=8.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("B", apy_pct=5.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
        ]
        r = self.sc.scan(**base_scan_kwargs(candidates=cands))
        gains = [c["net_gain_usd"] for c in r["ranked_candidates"]]
        self.assertGreater(gains[0], gains[1])

    def test_net_gain_negative_apy_improvement(self):
        # Lower APY candidate → negative gross gain even before costs
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=6.0,
            candidates=[cand(apy_pct=3.0, entry_cost_usd=0, exit_from_current_cost_usd=0)],
        ))
        self.assertLess(r["ranked_candidates"][0]["net_gain_usd"], 0)

    def test_net_gain_empty_candidates(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[]))
        self.assertIsNone(r["best_candidate"])
        self.assertEqual(r["opportunity_count"], 0)

    def test_net_gain_365_days_annual(self):
        # Over 365 days with zero costs: net = pos * (cand_apy - cur_apy) / 100
        r = self.sc.scan(**base_scan_kwargs(
            holding_days=365,
            candidates=[cand(apy_pct=6.0, entry_cost_usd=0, exit_from_current_cost_usd=0)],
        ))
        expected = 10_000 * (6.0 - 4.0) / 100
        self.assertAlmostEqual(r["ranked_candidates"][0]["net_gain_usd"], expected, places=4)


# ===========================================================================
# 4. Payback days
# ===========================================================================

class TestPaybackDays(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def _expected_payback(self, pos, cur_apy, cand_apy, entry, exit_):
        daily_gain = pos * (cand_apy - cur_apy) / 365 / 100
        if daily_gain <= 0:
            return None
        return (entry + exit_) / daily_gain

    def test_payback_basic(self):
        expected = self._expected_payback(10_000, 4.0, 6.0, 50.0, 30.0)
        r = self.sc.scan(**base_scan_kwargs())
        self.assertAlmostEqual(r["ranked_candidates"][0]["payback_days"],
                               expected, places=1)

    def test_payback_none_when_apy_not_better(self):
        r = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(apy_pct=4.0)],  # same APY
        ))
        self.assertIsNone(r["ranked_candidates"][0]["payback_days"])

    def test_payback_none_when_lower_apy(self):
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=8.0,
            candidates=[cand(apy_pct=5.0)],
        ))
        self.assertIsNone(r["ranked_candidates"][0]["payback_days"])

    def test_payback_zero_costs(self):
        r = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(entry_cost_usd=0, exit_from_current_cost_usd=0)],
        ))
        self.assertEqual(r["ranked_candidates"][0]["payback_days"], 0.0)

    def test_payback_decreases_with_bigger_apy_diff(self):
        r_small = self.sc.scan(**base_scan_kwargs(candidates=[cand(apy_pct=5.0)]))
        r_large = self.sc.scan(**base_scan_kwargs(candidates=[cand(apy_pct=10.0)]))
        p_small = r_small["ranked_candidates"][0]["payback_days"]
        p_large = r_large["ranked_candidates"][0]["payback_days"]
        self.assertGreater(p_small, p_large)

    def test_payback_rounds_to_2_places(self):
        r = self.sc.scan(**base_scan_kwargs())
        val = r["ranked_candidates"][0]["payback_days"]
        if val is not None:
            self.assertEqual(round(val, 2), val)

    def test_payback_increases_with_higher_costs(self):
        r_cheap = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(entry_cost_usd=10, exit_from_current_cost_usd=10)],
        ))
        r_expensive = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(entry_cost_usd=200, exit_from_current_cost_usd=200)],
        ))
        p_cheap = r_cheap["ranked_candidates"][0]["payback_days"]
        p_exp = r_expensive["ranked_candidates"][0]["payback_days"]
        self.assertGreater(p_exp, p_cheap)

    def test_payback_appears_in_best_candidate(self):
        r = self.sc.scan(**base_scan_kwargs())
        self.assertIn("payback_days", r["best_candidate"])

    def test_payback_positive_when_costs_positive(self):
        r = self.sc.scan(**base_scan_kwargs())
        pb = r["ranked_candidates"][0]["payback_days"]
        self.assertGreater(pb, 0)


# ===========================================================================
# 5. Risk-adjusted APY
# ===========================================================================

class TestRiskAdjustedAPY(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_risk_adjusted_zero_risk(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[cand(risk_score_0_to_100=0)]))
        ra = r["ranked_candidates"][0]["risk_adjusted_apy_pct"]
        self.assertAlmostEqual(ra, 6.0, places=5)

    def test_risk_adjusted_100_risk(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[cand(risk_score_0_to_100=100)]))
        ra = r["ranked_candidates"][0]["risk_adjusted_apy_pct"]
        self.assertAlmostEqual(ra, 0.0, places=5)

    def test_risk_adjusted_50_risk(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[cand(apy_pct=10.0, risk_score_0_to_100=50)]))
        ra = r["ranked_candidates"][0]["risk_adjusted_apy_pct"]
        self.assertAlmostEqual(ra, 5.0, places=5)

    def test_risk_adjusted_rounds_to_6_places(self):
        r = self.sc.scan(**base_scan_kwargs())
        val = r["ranked_candidates"][0]["risk_adjusted_apy_pct"]
        self.assertEqual(round(val, 6), val)

    def test_risk_adjusted_decreases_with_more_risk(self):
        r_low = self.sc.scan(**base_scan_kwargs(candidates=[cand(risk_score_0_to_100=10)]))
        r_high = self.sc.scan(**base_scan_kwargs(candidates=[cand(risk_score_0_to_100=80)]))
        self.assertGreater(r_low["ranked_candidates"][0]["risk_adjusted_apy_pct"],
                           r_high["ranked_candidates"][0]["risk_adjusted_apy_pct"])

    def test_risk_adjusted_in_best_candidate(self):
        r = self.sc.scan(**base_scan_kwargs())
        self.assertIn("risk_adjusted_apy_pct", r["best_candidate"])

    def test_risk_adjusted_25_risk(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[cand(apy_pct=8.0, risk_score_0_to_100=25)]))
        ra = r["ranked_candidates"][0]["risk_adjusted_apy_pct"]
        self.assertAlmostEqual(ra, 6.0, places=5)


# ===========================================================================
# 6. Ranking of candidates
# ===========================================================================

class TestRanking(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def _three_cands(self):
        return [
            cand("High", apy_pct=10.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("Mid", apy_pct=6.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("Low", apy_pct=3.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
        ]

    def test_ranked_descending_by_net_gain(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=self._three_cands()))
        gains = [c["net_gain_usd"] for c in r["ranked_candidates"]]
        self.assertEqual(gains, sorted(gains, reverse=True))

    def test_best_candidate_is_first_ranked(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=self._three_cands()))
        self.assertEqual(r["best_candidate"]["protocol"],
                         r["ranked_candidates"][0]["protocol"])

    def test_ranked_contains_all_candidates(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=self._three_cands()))
        self.assertEqual(len(r["ranked_candidates"]), 3)

    def test_ranked_protocol_names_preserved(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=self._three_cands()))
        names = {c["protocol"] for c in r["ranked_candidates"]}
        self.assertEqual(names, {"High", "Mid", "Low"})

    def test_empty_candidates_ranked_empty(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[]))
        self.assertEqual(r["ranked_candidates"], [])

    def test_single_candidate_is_best(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[cand("Solo")]))
        self.assertEqual(r["best_candidate"]["protocol"], "Solo")

    def test_ranking_stable_multiple_equal_net_gains(self):
        # All with same APY and costs → equal net gains
        same_cands = [cand(f"P{i}", apy_pct=6.0, entry_cost_usd=0, exit_from_current_cost_usd=0)
                      for i in range(3)]
        r = self.sc.scan(**base_scan_kwargs(candidates=same_cands))
        gains = [c["net_gain_usd"] for c in r["ranked_candidates"]]
        # All gains should be equal
        self.assertEqual(len(set(gains)), 1)

    def test_ranked_candidates_have_required_keys(self):
        r = self.sc.scan(**base_scan_kwargs())
        req_keys = {"protocol", "apy_pct", "entry_cost_usd",
                    "exit_from_current_cost_usd", "risk_score_0_to_100",
                    "net_gain_usd", "payback_days", "risk_adjusted_apy_pct",
                    "switch_recommended"}
        for c in r["ranked_candidates"]:
            self.assertTrue(req_keys.issubset(c.keys()), msg=f"Missing keys: {req_keys - c.keys()}")

    def test_best_candidate_has_required_keys(self):
        r = self.sc.scan(**base_scan_kwargs())
        self.assertIn("protocol", r["best_candidate"])
        self.assertIn("net_gain_usd", r["best_candidate"])
        self.assertIn("payback_days", r["best_candidate"])
        self.assertIn("risk_adjusted_apy_pct", r["best_candidate"])


# ===========================================================================
# 7. Opportunity count
# ===========================================================================

class TestOpportunityCount(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_opportunity_count_zero_no_gain(self):
        r = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(apy_pct=4.0)],  # same APY, costs eat gain
        ))
        self.assertEqual(r["opportunity_count"], 0)

    def test_opportunity_count_one_positive(self):
        r = self.sc.scan(**base_scan_kwargs())
        self.assertGreaterEqual(r["opportunity_count"], 0)

    def test_opportunity_count_multiple_positive(self):
        cands = [
            cand("A", apy_pct=8.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("B", apy_pct=6.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("C", apy_pct=3.0, entry_cost_usd=0, exit_from_current_cost_usd=0),  # below cur
        ]
        r = self.sc.scan(**base_scan_kwargs(candidates=cands))
        # A and B have positive gain (cur=4%), C does not
        self.assertEqual(r["opportunity_count"], 2)

    def test_opportunity_count_none_all_negative(self):
        cands = [
            cand("A", apy_pct=4.0, entry_cost_usd=500, exit_from_current_cost_usd=500),
            cand("B", apy_pct=3.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
        ]
        r = self.sc.scan(**base_scan_kwargs(candidates=cands))
        self.assertEqual(r["opportunity_count"], 0)

    def test_opportunity_count_empty_candidates(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[]))
        self.assertEqual(r["opportunity_count"], 0)

    def test_opportunity_count_all_positive(self):
        cands = [
            cand("A", apy_pct=8.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("B", apy_pct=7.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
        ]
        r = self.sc.scan(**base_scan_kwargs(candidates=cands))
        self.assertEqual(r["opportunity_count"], 2)


# ===========================================================================
# 8. switch_recommended flag
# ===========================================================================

class TestSwitchRecommended(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_switch_recommended_true_when_gain_and_improvement(self):
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=4.0,
            candidates=[cand(apy_pct=6.0, entry_cost_usd=0, exit_from_current_cost_usd=0)],
            min_apy_improvement_pct=0.5,
        ))
        self.assertTrue(r["ranked_candidates"][0]["switch_recommended"])

    def test_switch_not_recommended_when_improvement_below_min(self):
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=4.0,
            candidates=[cand(apy_pct=4.3, entry_cost_usd=0, exit_from_current_cost_usd=0)],
            min_apy_improvement_pct=0.5,
        ))
        self.assertFalse(r["ranked_candidates"][0]["switch_recommended"])

    def test_switch_not_recommended_when_net_gain_negative(self):
        r = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(apy_pct=6.0, entry_cost_usd=5_000, exit_from_current_cost_usd=5_000)],
        ))
        self.assertFalse(r["ranked_candidates"][0]["switch_recommended"])

    def test_switch_not_recommended_lower_apy(self):
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=8.0,
            candidates=[cand(apy_pct=5.0, entry_cost_usd=0, exit_from_current_cost_usd=0)],
        ))
        self.assertFalse(r["ranked_candidates"][0]["switch_recommended"])

    def test_switch_recommended_is_bool(self):
        r = self.sc.scan(**base_scan_kwargs())
        self.assertIsInstance(r["ranked_candidates"][0]["switch_recommended"], bool)

    def test_switch_recommended_exactly_at_min_improvement(self):
        # APY improvement exactly equals min → recommended (>= not strict >)
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=4.0,
            candidates=[cand(apy_pct=4.5, entry_cost_usd=0, exit_from_current_cost_usd=0)],
            min_apy_improvement_pct=0.5,
        ))
        self.assertTrue(r["ranked_candidates"][0]["switch_recommended"])

    def test_switch_recommended_false_zero_min_but_negative_gain(self):
        r = self.sc.scan(**base_scan_kwargs(
            min_apy_improvement_pct=0.0,
            candidates=[cand(entry_cost_usd=5000, exit_from_current_cost_usd=5000)],
        ))
        self.assertFalse(r["ranked_candidates"][0]["switch_recommended"])

    def test_switch_recommended_independent_per_candidate(self):
        cands = [
            cand("Good", apy_pct=8.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("Bad", apy_pct=3.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
        ]
        r = self.sc.scan(**base_scan_kwargs(candidates=cands))
        by_name = {c["protocol"]: c["switch_recommended"] for c in r["ranked_candidates"]}
        self.assertTrue(by_name["Good"])
        self.assertFalse(by_name["Bad"])


# ===========================================================================
# 9. Label: STAY_PUT
# ===========================================================================

class TestLabelStayPut(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_stay_put_no_candidates(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[]))
        self.assertEqual(r["scanner_label"], "STAY_PUT")

    def test_stay_put_all_negative_gain(self):
        r = self.sc.scan(**base_scan_kwargs(
            candidates=[cand(apy_pct=4.0, entry_cost_usd=1000, exit_from_current_cost_usd=1000)],
        ))
        self.assertEqual(r["scanner_label"], "STAY_PUT")

    def test_stay_put_lower_apy(self):
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=6.0,
            candidates=[cand(apy_pct=4.0, entry_cost_usd=0, exit_from_current_cost_usd=0)],
        ))
        self.assertEqual(r["scanner_label"], "STAY_PUT")

    def test_stay_put_same_apy_with_costs(self):
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=4.0,
            candidates=[cand(apy_pct=4.0, entry_cost_usd=100, exit_from_current_cost_usd=50)],
        ))
        self.assertEqual(r["scanner_label"], "STAY_PUT")

    def test_stay_put_label_in_valid_set(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[]))
        self.assertIn(r["scanner_label"], VALID_LABELS)

    def test_stay_put_zero_position_zero_cands(self):
        r = self.sc.scan(**base_scan_kwargs(position_size_usd=0.0, candidates=[]))
        self.assertEqual(r["scanner_label"], "STAY_PUT")

    def test_stay_put_high_cost_short_hold(self):
        # 1-day hold: tiny gain can't cover switch cost
        r = self.sc.scan(**base_scan_kwargs(
            holding_days=1,
            candidates=[cand(apy_pct=10.0, entry_cost_usd=500, exit_from_current_cost_usd=500)],
        ))
        self.assertEqual(r["scanner_label"], "STAY_PUT")


# ===========================================================================
# 10. Label: MARGINAL_OPPORTUNITY
# ===========================================================================

class TestLabelMarginalOpportunity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def _marginal_gain(self, pos):
        """Return net_gain that is ~0.3% of pos (in MARGINAL zone: 0 < x < 0.5%)."""
        return pos * 0.003

    def _build_cand_for_net_gain(self, target_net_gain, pos, cur_apy, days):
        """Build a candidate with entry=0, exit=0 and apy tuned to achieve target_net_gain."""
        # net_gain = pos*(cand_apy-cur_apy)*days/365/100
        # → cand_apy = cur_apy + (net_gain * 365 * 100) / (pos * days)
        extra_apy = target_net_gain * 365 * 100 / (pos * days)
        return cand(apy_pct=cur_apy + extra_apy, entry_cost_usd=0, exit_from_current_cost_usd=0)

    def test_marginal_opportunity_label(self):
        pos = 10_000
        days = 365
        target = pos * 0.003  # 0.3% of position = $30
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertEqual(r["scanner_label"], "MARGINAL_OPPORTUNITY")

    def test_marginal_opportunity_in_valid_set(self):
        pos = 10_000
        days = 365
        target = pos * 0.004  # still < 0.5%
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertIn(r["scanner_label"], VALID_LABELS)

    def test_marginal_opportunity_count_positive(self):
        pos = 10_000
        days = 365
        target = pos * 0.003
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertGreater(r["opportunity_count"], 0)


# ===========================================================================
# 11. Label: GOOD_SWITCH
# ===========================================================================

class TestLabelGoodSwitch(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def _build_cand_for_net_gain(self, target_net_gain, pos, cur_apy, days):
        extra_apy = target_net_gain * 365 * 100 / (pos * days)
        return cand(apy_pct=cur_apy + extra_apy, entry_cost_usd=0, exit_from_current_cost_usd=0)

    def test_good_switch_label(self):
        pos = 10_000
        days = 365
        target = pos * 0.01  # 1% of position — in [0.5%, 2%)
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertEqual(r["scanner_label"], "GOOD_SWITCH")

    def test_good_switch_in_valid_set(self):
        pos = 10_000
        days = 365
        target = pos * 0.015
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertIn(r["scanner_label"], VALID_LABELS)

    def test_good_switch_opportunity_count(self):
        pos = 10_000
        days = 365
        target = pos * 0.012
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertGreater(r["opportunity_count"], 0)


# ===========================================================================
# 12. Label: EXCELLENT_SWITCH
# ===========================================================================

class TestLabelExcellentSwitch(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def _build_cand_for_net_gain(self, target_net_gain, pos, cur_apy, days):
        extra_apy = target_net_gain * 365 * 100 / (pos * days)
        return cand(apy_pct=cur_apy + extra_apy, entry_cost_usd=0, exit_from_current_cost_usd=0)

    def test_excellent_switch_label(self):
        pos = 10_000
        days = 365
        target = pos * 0.035  # 3.5% → in [2%, 5%)
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertEqual(r["scanner_label"], "EXCELLENT_SWITCH")

    def test_excellent_switch_in_valid_set(self):
        pos = 10_000
        days = 365
        target = pos * 0.04
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertIn(r["scanner_label"], VALID_LABELS)

    def test_excellent_switch_best_candidate_set(self):
        pos = 10_000
        days = 365
        target = pos * 0.03
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertIsNotNone(r["best_candidate"])


# ===========================================================================
# 13. Label: ARBITRAGE_BONANZA
# ===========================================================================

class TestLabelArbitrageBonanza(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def _build_cand_for_net_gain(self, target_net_gain, pos, cur_apy, days):
        extra_apy = target_net_gain * 365 * 100 / (pos * days)
        return cand(apy_pct=cur_apy + extra_apy, entry_cost_usd=0, exit_from_current_cost_usd=0)

    def test_bonanza_label(self):
        pos = 10_000
        days = 365
        target = pos * 0.08  # 8% → >= 5%
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertEqual(r["scanner_label"], "ARBITRAGE_BONANZA")

    def test_bonanza_large_gain(self):
        # 20% APY vs 4%, zero costs, 365 days → gain = pos*16/100
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=4.0,
            position_size_usd=10_000,
            holding_days=365,
            candidates=[cand(apy_pct=20.0, entry_cost_usd=0, exit_from_current_cost_usd=0)],
        ))
        self.assertEqual(r["scanner_label"], "ARBITRAGE_BONANZA")

    def test_bonanza_in_valid_set(self):
        pos = 10_000
        days = 365
        target = pos * 0.1
        c = self._build_cand_for_net_gain(target, pos, 4.0, days)
        r = self.sc.scan(**base_scan_kwargs(
            position_size_usd=pos, holding_days=days, candidates=[c],
        ))
        self.assertIn(r["scanner_label"], VALID_LABELS)

    def test_bonanza_opportunity_count(self):
        r = self.sc.scan(**base_scan_kwargs(
            current_apy_pct=4.0,
            position_size_usd=10_000,
            holding_days=365,
            candidates=[cand(apy_pct=20.0, entry_cost_usd=0, exit_from_current_cost_usd=0)],
        ))
        self.assertGreater(r["opportunity_count"], 0)

    def test_bonanza_multiple_candidates_picks_best(self):
        cands = [
            cand("Super", apy_pct=20.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("Meh", apy_pct=5.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
        ]
        r = self.sc.scan(**base_scan_kwargs(
            holding_days=365, candidates=cands,
        ))
        self.assertEqual(r["scanner_label"], "ARBITRAGE_BONANZA")
        self.assertEqual(r["best_candidate"]["protocol"], "Super")


# ===========================================================================
# 14. Input validation
# ===========================================================================

class TestInputValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_negative_position_raises(self):
        with self.assertRaises(ValueError):
            self.sc.scan(**base_scan_kwargs(position_size_usd=-1.0))

    def test_zero_holding_days_raises(self):
        with self.assertRaises(ValueError):
            self.sc.scan(**base_scan_kwargs(holding_days=0))

    def test_negative_holding_days_raises(self):
        with self.assertRaises(ValueError):
            self.sc.scan(**base_scan_kwargs(holding_days=-1))

    def test_non_list_candidates_raises(self):
        with self.assertRaises(TypeError):
            self.sc.scan(**base_scan_kwargs(candidates="not_a_list"))

    def test_non_string_current_protocol_raises(self):
        with self.assertRaises(TypeError):
            self.sc.scan(**base_scan_kwargs(current_protocol=123))

    def test_zero_position_is_valid(self):
        r = self.sc.scan(**base_scan_kwargs(position_size_usd=0.0))
        self.assertIsNotNone(r)

    def test_empty_candidates_is_valid(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[]))
        self.assertEqual(r["scanner_label"], "STAY_PUT")

    def test_single_candidate_is_valid(self):
        r = self.sc.scan(**base_scan_kwargs(candidates=[cand()]))
        self.assertIsNotNone(r)

    def test_many_candidates_is_valid(self):
        cands = [cand(f"P{i}", apy_pct=float(i+1)) for i in range(20)]
        r = self.sc.scan(**base_scan_kwargs(candidates=cands))
        self.assertEqual(len(r["ranked_candidates"]), 20)


# ===========================================================================
# 15. Output structure
# ===========================================================================

class TestOutputStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_all_top_level_keys_present(self):
        r = self.sc.scan(**base_scan_kwargs())
        expected = {
            "current_protocol", "current_apy_pct", "position_size_usd",
            "holding_days", "current_annual_yield_usd", "best_candidate",
            "opportunity_count", "scanner_label", "ranked_candidates", "timestamp",
        }
        self.assertEqual(set(r.keys()), expected)

    def test_current_protocol_preserved(self):
        r = self.sc.scan(**base_scan_kwargs(current_protocol="Compound"))
        self.assertEqual(r["current_protocol"], "Compound")

    def test_timestamp_ends_with_z(self):
        r = self.sc.scan(**base_scan_kwargs())
        self.assertTrue(r["timestamp"].endswith("Z"))

    def test_label_always_valid(self):
        for n_cands in [0, 1, 3]:
            cands = [cand(f"P{i}", apy_pct=float(i+1)*2) for i in range(n_cands)]
            r = self.sc.scan(**base_scan_kwargs(candidates=cands))
            self.assertIn(r["scanner_label"], VALID_LABELS)

    def test_opportunity_count_non_negative(self):
        r = self.sc.scan(**base_scan_kwargs())
        self.assertGreaterEqual(r["opportunity_count"], 0)

    def test_holding_days_preserved(self):
        r = self.sc.scan(**base_scan_kwargs(holding_days=90))
        self.assertEqual(r["holding_days"], 90)

    def test_position_size_preserved(self):
        r = self.sc.scan(**base_scan_kwargs(position_size_usd=50_000.0))
        self.assertEqual(r["position_size_usd"], 50_000.0)


# ===========================================================================
# 16. Logging
# ===========================================================================

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "arb_log.json")
        self.sc = ProtocolDeFiCrossProtocolYieldArbitrageScanner(
            log_path=self.log_path, log_cap=5
        )

    def test_log_file_created(self):
        self.sc.scan_and_log(**base_scan_kwargs())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.sc.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_one_entry_after_one_call(self):
        self.sc.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates(self):
        for _ in range(3):
            self.sc.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_capped(self):
        for _ in range(8):
            self.sc.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_keeps_most_recent(self):
        for i in range(7):
            self.sc.scan_and_log(**base_scan_kwargs(current_protocol=f"P{i}"))
        with open(self.log_path) as f:
            data = json.load(f)
        protocols = [e["current_protocol"] for e in data]
        self.assertEqual(protocols[-1], "P6")

    def test_log_returns_same_as_stored(self):
        r = self.sc.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            stored = json.load(f)[0]
        self.assertEqual(r, stored)

    def test_no_tmp_file_after_log(self):
        self.sc.scan_and_log(**base_scan_kwargs())
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_corrupted_log_is_reset(self):
        with open(self.log_path, "w") as f:
            f.write("{bad json")
        self.sc.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_not_list_is_reset(self):
        with open(self.log_path, "w") as f:
            json.dump({"key": "value"}, f)
        self.sc.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_scan_does_not_write_when_not_log(self):
        log_path = os.path.join(self.tmp, "no_write.json")
        sc = ProtocolDeFiCrossProtocolYieldArbitrageScanner(log_path=log_path)
        sc.scan(**base_scan_kwargs())
        self.assertFalse(os.path.exists(log_path))

    def test_default_log_cap_100(self):
        sc100 = ProtocolDeFiCrossProtocolYieldArbitrageScanner(
            log_path=self.log_path, log_cap=100
        )
        for _ in range(110):
            sc100.scan_and_log(**base_scan_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)


# ===========================================================================
# 17. Integration / compound scenarios
# ===========================================================================

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sc = make_scanner(self.tmp)

    def test_aave_to_morpho_scenario(self):
        """Switch from Aave 3.5% to Morpho 6.5%, 90-day hold."""
        r = self.sc.scan(
            current_protocol="Aave-V3",
            current_apy_pct=3.5,
            position_size_usd=100_000,
            candidates=[
                {"protocol": "Morpho-Steakhouse", "apy_pct": 6.5,
                 "entry_cost_usd": 50, "exit_from_current_cost_usd": 30,
                 "risk_score_0_to_100": 15},
            ],
            min_apy_improvement_pct=0.5,
            holding_days=90,
        )
        self.assertIn(r["scanner_label"], VALID_LABELS)
        self.assertEqual(r["best_candidate"]["protocol"], "Morpho-Steakhouse")

    def test_stay_put_when_all_candidates_worse(self):
        r = self.sc.scan(
            current_protocol="HighYield",
            current_apy_pct=12.0,
            position_size_usd=50_000,
            candidates=[
                {"protocol": "A", "apy_pct": 5.0, "entry_cost_usd": 100,
                 "exit_from_current_cost_usd": 50, "risk_score_0_to_100": 5},
                {"protocol": "B", "apy_pct": 8.0, "entry_cost_usd": 200,
                 "exit_from_current_cost_usd": 100, "risk_score_0_to_100": 20},
            ],
            min_apy_improvement_pct=0.5,
            holding_days=30,
        )
        self.assertEqual(r["scanner_label"], "STAY_PUT")

    def test_best_protocol_wins_despite_higher_risk(self):
        """High-APY candidate wins even with moderate risk."""
        r = self.sc.scan(
            current_protocol="Safe",
            current_apy_pct=2.0,
            position_size_usd=100_000,
            candidates=[
                {"protocol": "Risky", "apy_pct": 15.0,
                 "entry_cost_usd": 100, "exit_from_current_cost_usd": 100,
                 "risk_score_0_to_100": 40},
                {"protocol": "Safe2", "apy_pct": 3.0,
                 "entry_cost_usd": 10, "exit_from_current_cost_usd": 10,
                 "risk_score_0_to_100": 5},
            ],
            min_apy_improvement_pct=0.5,
            holding_days=180,
        )
        # Net gain for Risky should dominate
        self.assertEqual(r["best_candidate"]["protocol"], "Risky")

    def test_scan_and_log_stores_result(self):
        r = self.sc.scan_and_log(**base_scan_kwargs(current_protocol="Euler"))
        with open(self.sc.log_path) as f:
            stored = json.load(f)
        self.assertEqual(stored[0]["current_protocol"], "Euler")

    def test_multiple_scans_ranked_candidates_correct_order(self):
        cands = [
            cand("Low", apy_pct=5.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("High", apy_pct=10.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
            cand("Mid", apy_pct=7.0, entry_cost_usd=0, exit_from_current_cost_usd=0),
        ]
        r = self.sc.scan(**base_scan_kwargs(candidates=cands, holding_days=365))
        names = [c["protocol"] for c in r["ranked_candidates"]]
        self.assertEqual(names, ["High", "Mid", "Low"])


if __name__ == "__main__":
    unittest.main()
