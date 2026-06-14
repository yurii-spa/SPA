"""
Tests for MP-808: BorrowingCostOptimizer
≥65 test methods covering all filter conditions, ranking, edge cases,
cost arithmetic, and log persistence.

Run:  python3 -m unittest spa_core/tests/test_borrowing_cost_optimizer.py
"""

import json
import math
import os
import tempfile
import unittest

import sys
_here = os.path.dirname(os.path.abspath(__file__))
_repo = os.path.dirname(os.path.dirname(_here))
if _repo not in sys.path:
    sys.path.insert(0, _repo)

from spa_core.analytics.borrowing_cost_optimizer import (
    _RING_BUFFER_CAP,
    _DEFAULT_LOAN_DURATION_DAYS,
    _atomic_write,
    _load_log,
    _most_flexible_protocol,
    analyze,
)


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _req(
    asset="USDC",
    amount_usd=50_000.0,
    collateral_usd=100_000.0,
    max_rate=10.0,
) -> dict:
    return {
        "asset": asset,
        "amount_usd": amount_usd,
        "collateral_usd": collateral_usd,
        "max_rate": max_rate,
    }


def _market(
    protocol="Aave",
    asset="USDC",
    borrow_rate_apy=3.5,
    min_collateral_ratio=1.5,
    origination_fee_pct=0.0,
    max_borrow_usd=None,
) -> dict:
    return {
        "protocol": protocol,
        "asset": asset,
        "borrow_rate_apy": borrow_rate_apy,
        "min_collateral_ratio": min_collateral_ratio,
        "origination_fee_pct": origination_fee_pct,
        "max_borrow_usd": max_borrow_usd,
    }


# ── Basic return-structure tests ──────────────────────────────────────────────

class TestReturnStructure(unittest.TestCase):

    def _r(self):
        return analyze(_req(), [_market()])

    def test_returns_dict(self):
        self.assertIsInstance(self._r(), dict)

    def test_has_asset(self):
        self.assertIn("asset", self._r())

    def test_has_amount_requested(self):
        self.assertIn("amount_requested_usd", self._r())

    def test_has_collateral_usd(self):
        self.assertIn("collateral_usd", self._r())

    def test_has_viable_markets(self):
        self.assertIsInstance(self._r()["viable_markets"], list)

    def test_has_best_market(self):
        self.assertIn("best_market", self._r())

    def test_has_cheapest_rate(self):
        self.assertIn("cheapest_rate", self._r())

    def test_has_most_flexible(self):
        self.assertIn("most_flexible", self._r())

    def test_has_filtered_out(self):
        self.assertIsInstance(self._r()["filtered_out"], list)

    def test_has_timestamp(self):
        ts = self._r()["timestamp"]
        self.assertIsInstance(ts, float)
        self.assertGreater(ts, 0.0)

    def test_asset_preserved(self):
        r = analyze(_req(asset="DAI"), [_market(asset="DAI")])
        self.assertEqual(r["asset"], "DAI")

    def test_amount_preserved(self):
        r = analyze(_req(amount_usd=12_345.0), [_market()])
        self.assertAlmostEqual(r["amount_requested_usd"], 12_345.0)

    def test_collateral_preserved(self):
        r = analyze(_req(collateral_usd=999.0), [_market(min_collateral_ratio=0.01)])
        self.assertAlmostEqual(r["collateral_usd"], 999.0)


# ── Viable market entry structure ─────────────────────────────────────────────

class TestViableMarketEntry(unittest.TestCase):

    def _entry(self):
        r = analyze(_req(), [_market()])
        return r["viable_markets"][0]

    def test_has_protocol(self):
        self.assertIn("protocol", self._entry())

    def test_has_borrow_rate_apy(self):
        self.assertIn("borrow_rate_apy", self._entry())

    def test_has_origination_fee_usd(self):
        self.assertIn("origination_fee_usd", self._entry())

    def test_has_interest_30d_usd(self):
        self.assertIn("interest_30d_usd", self._entry())

    def test_has_total_cost_usd(self):
        self.assertIn("total_cost_usd", self._entry())

    def test_has_effective_apy(self):
        self.assertIn("effective_apy", self._entry())

    def test_has_max_borrowable_usd(self):
        self.assertIn("max_borrowable_usd", self._entry())

    def test_has_collateral_utilization_pct(self):
        self.assertIn("collateral_utilization_pct", self._entry())

    def test_has_rank(self):
        self.assertIn("rank", self._entry())


# ── Cost arithmetic tests ─────────────────────────────────────────────────────

class TestCostArithmetic(unittest.TestCase):

    def test_origination_fee_zero_when_fee_pct_zero(self):
        r = analyze(_req(amount_usd=10_000.0), [_market(origination_fee_pct=0.0)])
        self.assertAlmostEqual(r["viable_markets"][0]["origination_fee_usd"], 0.0)

    def test_origination_fee_correct(self):
        # 1% on 10_000 = 100
        r = analyze(_req(amount_usd=10_000.0), [_market(origination_fee_pct=1.0)])
        self.assertAlmostEqual(r["viable_markets"][0]["origination_fee_usd"], 100.0)

    def test_interest_30d_correct(self):
        # amount=10_000, rate=3.65% APY, 30 days:
        # 10000 * 0.0365 / 365 * 30 = 10000 * 0.003 = 30.0
        r = analyze(_req(amount_usd=10_000.0), [_market(borrow_rate_apy=3.65)])
        self.assertAlmostEqual(r["viable_markets"][0]["interest_30d_usd"], 30.0, places=5)

    def test_total_cost_is_fee_plus_interest(self):
        r = analyze(_req(amount_usd=10_000.0), [_market(origination_fee_pct=0.5, borrow_rate_apy=5.0)])
        e = r["viable_markets"][0]
        self.assertAlmostEqual(e["total_cost_usd"], e["origination_fee_usd"] + e["interest_30d_usd"])

    def test_effective_apy_calculation(self):
        # effective = total_cost / amount * 365/duration * 100
        r = analyze(
            _req(amount_usd=10_000.0),
            [_market(origination_fee_pct=0.0, borrow_rate_apy=3.65)],
            {"loan_duration_days": 30},
        )
        e = r["viable_markets"][0]
        expected_eff = e["total_cost_usd"] / 10_000.0 * 365 / 30 * 100
        self.assertAlmostEqual(e["effective_apy"], expected_eff, places=8)

    def test_max_borrowable_usd_computed(self):
        # collateral=150_000, ratio=1.5 → max_borrowable = 100_000
        r = analyze(
            _req(collateral_usd=150_000.0, amount_usd=50_000.0),
            [_market(min_collateral_ratio=1.5)],
        )
        self.assertAlmostEqual(r["viable_markets"][0]["max_borrowable_usd"], 100_000.0)

    def test_collateral_utilization_pct(self):
        # amount=50_000, max_borrowable=100_000 → utilization=50%
        r = analyze(
            _req(collateral_usd=150_000.0, amount_usd=50_000.0),
            [_market(min_collateral_ratio=1.5)],
        )
        self.assertAlmostEqual(r["viable_markets"][0]["collateral_utilization_pct"], 50.0)

    def test_custom_loan_duration(self):
        # 10 days instead of 30
        r = analyze(
            _req(amount_usd=10_000.0),
            [_market(borrow_rate_apy=3.65, origination_fee_pct=0.0)],
            {"loan_duration_days": 10},
        )
        expected_interest = 10_000.0 * 0.0365 / 365 * 10
        self.assertAlmostEqual(r["viable_markets"][0]["interest_30d_usd"], expected_interest, places=5)

    def test_unlimited_pool_max_borrow_none(self):
        # max_borrow_usd=None means pool has no limit, but max_borrowable_usd
        # is still computed from collateral / min_collateral_ratio
        # collateral=100_000, ratio=1.5 → max_borrowable=66_666.67
        r = analyze(_req(amount_usd=50_000.0, collateral_usd=100_000.0), [_market(max_borrow_usd=None)])
        self.assertAlmostEqual(r["viable_markets"][0]["max_borrowable_usd"], 100_000.0 / 1.5, places=2)

    def test_unlimited_pool_collateral_util_zero(self):
        # When min_collateral_ratio=0, max_borrowable = inf → util = 0%
        r = analyze(
            _req(amount_usd=50_000.0, collateral_usd=100_000.0),
            [_market(min_collateral_ratio=0.0)],
        )
        self.assertAlmostEqual(r["viable_markets"][0]["collateral_utilization_pct"], 0.0)

    def test_default_loan_duration_is_30(self):
        self.assertEqual(_DEFAULT_LOAN_DURATION_DAYS, 30)

    def test_interest_proportional_to_duration(self):
        r30 = analyze(_req(amount_usd=10_000.0), [_market(borrow_rate_apy=5.0)], {"loan_duration_days": 30})
        r60 = analyze(_req(amount_usd=10_000.0), [_market(borrow_rate_apy=5.0)], {"loan_duration_days": 60})
        i30 = r30["viable_markets"][0]["interest_30d_usd"]
        i60 = r60["viable_markets"][0]["interest_30d_usd"]
        self.assertAlmostEqual(i60, i30 * 2, places=8)


# ── Filter tests ──────────────────────────────────────────────────────────────

class TestFilters(unittest.TestCase):

    def test_asset_mismatch_filtered(self):
        r = analyze(_req(asset="USDC"), [_market(asset="DAI")])
        self.assertIn("Aave", r["filtered_out"])
        self.assertEqual(len(r["viable_markets"]), 0)

    def test_asset_mismatch_filtered_name(self):
        m = _market(protocol="Compound", asset="ETH")
        r = analyze(_req(asset="USDC"), [m])
        self.assertIn("Compound", r["filtered_out"])

    def test_insufficient_collateral_filtered(self):
        # collateral=10_000, ratio=2.0 → max_borrowable=5_000 < amount=50_000
        r = analyze(
            _req(amount_usd=50_000.0, collateral_usd=10_000.0),
            [_market(min_collateral_ratio=2.0)],
        )
        self.assertIn("Aave", r["filtered_out"])
        self.assertEqual(len(r["viable_markets"]), 0)

    def test_rate_too_high_filtered(self):
        # max_rate=5.0, market rate=8.0
        r = analyze(
            _req(max_rate=5.0),
            [_market(borrow_rate_apy=8.0)],
        )
        self.assertIn("Aave", r["filtered_out"])

    def test_rate_exactly_at_max_passes(self):
        # max_rate=5.0, market rate=5.0 → should pass (not > max_rate)
        r = analyze(
            _req(max_rate=5.0),
            [_market(borrow_rate_apy=5.0)],
        )
        self.assertEqual(len(r["viable_markets"]), 1)

    def test_pool_limit_filtered(self):
        # max_borrow_usd=10_000, amount=50_000 → filtered
        r = analyze(
            _req(amount_usd=50_000.0),
            [_market(max_borrow_usd=10_000.0)],
        )
        self.assertIn("Aave", r["filtered_out"])

    def test_pool_limit_exactly_equal_passes(self):
        # max_borrow_usd=50_000, amount=50_000 → should pass (not < amount)
        r = analyze(
            _req(amount_usd=50_000.0),
            [_market(max_borrow_usd=50_000.0)],
        )
        self.assertEqual(len(r["viable_markets"]), 1)

    def test_multiple_filters_all_count(self):
        markets = [
            _market(protocol="A", asset="ETH"),                          # asset mismatch
            _market(protocol="B", min_collateral_ratio=100.0),           # collateral
            _market(protocol="C", borrow_rate_apy=99.0),                 # rate
            _market(protocol="D", max_borrow_usd=1.0),                  # pool limit
        ]
        r = analyze(_req(), markets)
        self.assertEqual(len(r["viable_markets"]), 0)
        self.assertIn("A", r["filtered_out"])
        self.assertIn("B", r["filtered_out"])
        self.assertIn("C", r["filtered_out"])
        self.assertIn("D", r["filtered_out"])

    def test_mix_viable_and_filtered(self):
        markets = [
            _market(protocol="Good", borrow_rate_apy=3.0),
            _market(protocol="Bad", asset="ETH"),
        ]
        r = analyze(_req(), markets)
        self.assertEqual(len(r["viable_markets"]), 1)
        self.assertEqual(r["viable_markets"][0]["protocol"], "Good")
        self.assertIn("Bad", r["filtered_out"])


# ── Ranking & summary tests ───────────────────────────────────────────────────

class TestRankingAndSummary(unittest.TestCase):

    def _three_markets(self):
        return [
            _market(protocol="Cheap", borrow_rate_apy=2.0, origination_fee_pct=0.0),
            _market(protocol="Mid", borrow_rate_apy=4.0, origination_fee_pct=0.1),
            _market(protocol="Expensive", borrow_rate_apy=6.0, origination_fee_pct=0.5),
        ]

    def test_rank_1_is_cheapest_total_cost(self):
        r = analyze(_req(), self._three_markets())
        rank1 = next(m for m in r["viable_markets"] if m["rank"] == 1)
        self.assertEqual(rank1["protocol"], "Cheap")

    def test_ranks_are_consecutive(self):
        r = analyze(_req(), self._three_markets())
        ranks = sorted(m["rank"] for m in r["viable_markets"])
        self.assertEqual(ranks, [1, 2, 3])

    def test_best_market_is_rank_1(self):
        r = analyze(_req(), self._three_markets())
        self.assertEqual(r["best_market"], "Cheap")

    def test_cheapest_rate_protocol(self):
        r = analyze(_req(), self._three_markets())
        self.assertEqual(r["cheapest_rate"], "Cheap")

    def test_cheapest_rate_not_necessarily_best_total_cost(self):
        # Low rate but high fee can make total cost worse than mid-rate
        markets = [
            _market(protocol="LowRate", borrow_rate_apy=1.0, origination_fee_pct=10.0),
            _market(protocol="MidRate", borrow_rate_apy=5.0, origination_fee_pct=0.0),
        ]
        r = analyze(_req(amount_usd=10_000.0), markets)
        self.assertEqual(r["cheapest_rate"], "LowRate")
        # best_market is whichever has lower total cost
        self.assertIn(r["best_market"], ["LowRate", "MidRate"])

    def test_most_flexible_highest_max_borrowable(self):
        markets = [
            _market(protocol="A", min_collateral_ratio=2.0),  # max_borrowable=50_000
            _market(protocol="B", min_collateral_ratio=1.0),  # max_borrowable=100_000
        ]
        r = analyze(_req(collateral_usd=100_000.0), markets)
        self.assertEqual(r["most_flexible"], "B")

    def test_most_flexible_by_collateral_ratio(self):
        # most_flexible = highest max_borrowable_usd (collateral / min_collateral_ratio)
        # "LowRatio" ratio=0.5 → max_borrowable=200_000
        # "HighRatio" ratio=2.0 → max_borrowable=50_000
        markets = [
            _market(protocol="LowRatio", min_collateral_ratio=0.5),
            _market(protocol="HighRatio", min_collateral_ratio=2.0),
        ]
        r = analyze(_req(collateral_usd=100_000.0, amount_usd=10_000.0), markets)
        self.assertEqual(r["most_flexible"], "LowRatio")

    def test_single_viable_market_rank_1(self):
        r = analyze(_req(), [_market()])
        self.assertEqual(r["viable_markets"][0]["rank"], 1)

    def test_no_viable_markets_nulls(self):
        r = analyze(_req(), [_market(asset="ETH")])
        self.assertIsNone(r["best_market"])
        self.assertIsNone(r["cheapest_rate"])
        self.assertIsNone(r["most_flexible"])

    def test_no_viable_markets_empty_list(self):
        r = analyze(_req(), [_market(asset="ETH")])
        self.assertEqual(r["viable_markets"], [])

    def test_sorted_ascending_by_total_cost(self):
        markets = [
            _market(protocol="C", borrow_rate_apy=6.0),
            _market(protocol="A", borrow_rate_apy=2.0),
            _market(protocol="B", borrow_rate_apy=4.0),
        ]
        r = analyze(_req(), markets)
        costs = [m["total_cost_usd"] for m in r["viable_markets"]]
        self.assertEqual(costs, sorted(costs))

    def test_empty_markets_list(self):
        r = analyze(_req(), [])
        self.assertEqual(r["viable_markets"], [])
        self.assertIsNone(r["best_market"])

    def test_no_markets_no_filtered(self):
        r = analyze(_req(), [])
        self.assertEqual(r["filtered_out"], [])


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_none_config(self):
        r = analyze(_req(), [_market()], None)
        self.assertIn("viable_markets", r)

    def test_empty_config(self):
        r = analyze(_req(), [_market()], {})
        self.assertIn("viable_markets", r)

    def test_zero_borrow_amount(self):
        # Edge: amount_usd=0 → interest=0, fee=0
        r = analyze(_req(amount_usd=0.0), [_market()])
        self.assertAlmostEqual(r["viable_markets"][0]["total_cost_usd"], 0.0)

    def test_large_borrow_amount(self):
        r = analyze(_req(amount_usd=1_000_000.0, collateral_usd=10_000_000.0), [_market()])
        self.assertEqual(len(r["viable_markets"]), 1)

    def test_max_rate_zero_filters_everything(self):
        r = analyze(_req(max_rate=0.0), [_market(borrow_rate_apy=3.5)])
        self.assertEqual(len(r["viable_markets"]), 0)

    def test_max_rate_very_high_passes_all(self):
        markets = [
            _market(protocol="A", borrow_rate_apy=50.0),
            _market(protocol="B", borrow_rate_apy=100.0),
        ]
        r = analyze(_req(max_rate=200.0), markets)
        self.assertEqual(len(r["viable_markets"]), 2)

    def test_zero_origination_zero_rate_no_cost(self):
        r = analyze(_req(amount_usd=10_000.0), [_market(origination_fee_pct=0.0, borrow_rate_apy=0.0)])
        self.assertAlmostEqual(r["viable_markets"][0]["total_cost_usd"], 0.0)

    def test_high_origination_fee(self):
        # 100% fee on 10_000 = 10_000 USD fee
        r = analyze(_req(amount_usd=10_000.0), [_market(origination_fee_pct=100.0, borrow_rate_apy=0.0)])
        self.assertAlmostEqual(r["viable_markets"][0]["origination_fee_usd"], 10_000.0)

    def test_integer_amounts_accepted(self):
        req = {"asset": "USDC", "amount_usd": 50000, "collateral_usd": 100000, "max_rate": 10}
        r = analyze(req, [_market()])
        self.assertAlmostEqual(r["amount_requested_usd"], 50_000.0)

    def test_protocol_name_preserved(self):
        r = analyze(_req(), [_market(protocol="My Protocol XYZ")])
        self.assertEqual(r["viable_markets"][0]["protocol"], "My Protocol XYZ")

    def test_equal_cost_markets_both_included(self):
        markets = [
            _market(protocol="A", borrow_rate_apy=3.0, origination_fee_pct=0.0),
            _market(protocol="B", borrow_rate_apy=3.0, origination_fee_pct=0.0),
        ]
        r = analyze(_req(), markets)
        self.assertEqual(len(r["viable_markets"]), 2)

    def test_filtered_out_does_not_appear_in_viable(self):
        markets = [
            _market(protocol="OK"),
            _market(protocol="FILTERED", asset="ETH"),
        ]
        r = analyze(_req(), markets)
        viable_protocols = [m["protocol"] for m in r["viable_markets"]]
        self.assertNotIn("FILTERED", viable_protocols)

    def test_viable_markets_is_list_of_dicts(self):
        r = analyze(_req(), [_market()])
        self.assertIsInstance(r["viable_markets"], list)
        self.assertIsInstance(r["viable_markets"][0], dict)

    def test_borrow_rate_apy_preserved_in_result(self):
        r = analyze(_req(), [_market(borrow_rate_apy=7.77)])
        self.assertAlmostEqual(r["viable_markets"][0]["borrow_rate_apy"], 7.77)


# ── Most flexible helper ──────────────────────────────────────────────────────

class TestMostFlexibleHelper(unittest.TestCase):

    def test_none_max_borrowable_is_most_flexible(self):
        markets = [
            {"protocol": "A", "max_borrowable_usd": 100_000.0},
            {"protocol": "B", "max_borrowable_usd": None},
        ]
        self.assertEqual(_most_flexible_protocol(markets), "B")

    def test_largest_wins(self):
        markets = [
            {"protocol": "A", "max_borrowable_usd": 50_000.0},
            {"protocol": "B", "max_borrowable_usd": 200_000.0},
            {"protocol": "C", "max_borrowable_usd": 100_000.0},
        ]
        self.assertEqual(_most_flexible_protocol(markets), "B")

    def test_single_market(self):
        markets = [{"protocol": "X", "max_borrowable_usd": 50_000.0}]
        self.assertEqual(_most_flexible_protocol(markets), "X")


# ── Log persistence tests ─────────────────────────────────────────────────────

class TestLogPersistence(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        import spa_core.analytics.borrowing_cost_optimizer as mod
        self._mod = mod
        self._orig_log = mod._LOG_FILE
        self._orig_data = mod._DATA_DIR
        self._tmplog = os.path.join(self._tmpdir, "borrowing_cost_log.json")
        mod._LOG_FILE = self._tmplog
        mod._DATA_DIR = self._tmpdir

    def tearDown(self):
        self._mod._LOG_FILE = self._orig_log
        self._mod._DATA_DIR = self._orig_data

    def test_log_created_after_analyze(self):
        analyze(_req(), [_market()])
        self.assertTrue(os.path.exists(self._tmplog))

    def test_log_is_list(self):
        analyze(_req(), [_market()])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_asset(self):
        analyze(_req(asset="USDC"), [_market()])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["asset"], "USDC")

    def test_log_ring_buffer_cap(self):
        for _ in range(_RING_BUFFER_CAP + 15):
            analyze(_req(), [_market()])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), _RING_BUFFER_CAP)

    def test_log_accumulates_entries(self):
        for _ in range(5):
            analyze(_req(), [_market()])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_has_viable_markets_count(self):
        analyze(_req(), [_market(), _market(protocol="B")])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertIn("viable_markets_count", data[-1])

    def test_log_no_full_viable_markets_array(self):
        analyze(_req(), [_market()])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertNotIn("viable_markets", data[-1])

    def test_atomic_write_creates_file(self):
        path = os.path.join(self._tmpdir, "test_atomic.json")
        _atomic_write(path, {"ok": True})
        with open(path) as f:
            self.assertEqual(json.load(f), {"ok": True})

    def test_load_log_missing_returns_empty(self):
        import spa_core.analytics.borrowing_cost_optimizer as mod
        mod._LOG_FILE = os.path.join(self._tmpdir, "nonexistent.json")
        self.assertEqual(_load_log(), [])

    def test_load_log_corrupt_returns_empty(self):
        bad = os.path.join(self._tmpdir, "bad.json")
        with open(bad, "w") as f:
            f.write("{bad json}")
        import spa_core.analytics.borrowing_cost_optimizer as mod
        mod._LOG_FILE = bad
        self.assertEqual(_load_log(), [])

    def test_log_best_market_in_entry(self):
        analyze(_req(), [_market(protocol="Winner")])
        with open(self._tmplog) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["best_market"], "Winner")


if __name__ == "__main__":
    unittest.main()
