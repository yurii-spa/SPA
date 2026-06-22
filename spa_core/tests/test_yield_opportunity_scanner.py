"""Unit tests for spa_core.analytics.yield_opportunity_scanner (MP-803).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_yield_opportunity_scanner -v
"""
from __future__ import annotations

import json
import math
import tempfile
import time
import unittest
from pathlib import Path

import spa_core.analytics.yield_opportunity_scanner as yos
from spa_core.analytics.yield_opportunity_scanner import (
    DEFAULT_TOP_N,
    MAX_ENTRIES,
    _apy_score,
    _fit_score,
    _liquidity_score,
    _safety_score,
    analyze,
)


# ---------------------------------------------------------------------------
# Test helpers / fixtures
# ---------------------------------------------------------------------------

def _opp(
    id_: str = "op1",
    protocol: str = "TestProto",
    type_: str = "lending",
    apy: float = 5.0,
    tvl_usd: float = 100_000_000,
    audit_count: int = 2,
    age_days: int = 365,
    min_deposit_usd: float = 100.0,
    lock_days: int = 0,
    chain: str = "ethereum",
) -> dict:
    return {
        "id": id_,
        "protocol": protocol,
        "type": type_,
        "apy": apy,
        "tvl_usd": tvl_usd,
        "audit_count": audit_count,
        "age_days": age_days,
        "min_deposit_usd": min_deposit_usd,
        "lock_days": lock_days,
        "chain": chain,
    }


def _portfolio(
    total_usd: float = 100_000.0,
    preferred_chains: list | None = None,
    max_lock_days: int = 0,
    min_apy: float = 1.0,
) -> dict:
    if preferred_chains is None:
        preferred_chains = ["ethereum"]
    return {
        "total_usd": total_usd,
        "preferred_chains": preferred_chains,
        "max_lock_days": max_lock_days,
        "min_apy": min_apy,
    }


# ---------------------------------------------------------------------------
# 1. _apy_score  (pure function)
# ---------------------------------------------------------------------------

class TestApyScore(unittest.TestCase):

    def test_zero_apy(self):
        self.assertAlmostEqual(_apy_score(0.0), 0.0)

    def test_apy_at_25(self):
        """apy=25 → exactly 40."""
        self.assertAlmostEqual(_apy_score(25.0), 40.0)

    def test_apy_above_25_capped(self):
        """apy=50 → capped at 40."""
        self.assertAlmostEqual(_apy_score(50.0), 40.0)

    def test_apy_at_12_5(self):
        """apy=12.5 → 20."""
        self.assertAlmostEqual(_apy_score(12.5), 20.0)

    def test_apy_at_6_25(self):
        """apy=6.25 → 10."""
        self.assertAlmostEqual(_apy_score(6.25), 10.0)

    def test_apy_very_high(self):
        """apy=1000 → still 40."""
        self.assertAlmostEqual(_apy_score(1000.0), 40.0)

    def test_apy_small_positive(self):
        """apy=0.5 → 0.8."""
        self.assertAlmostEqual(_apy_score(0.5), 0.8)

    def test_apy_exactly_40_boundary(self):
        result = _apy_score(25.0)
        self.assertLessEqual(result, 40.0)

    def test_apy_proportional(self):
        """Score should scale linearly below cap."""
        self.assertAlmostEqual(_apy_score(10.0) * 2, _apy_score(20.0))


# ---------------------------------------------------------------------------
# 2. _safety_score  (pure function)
# ---------------------------------------------------------------------------

class TestSafetyScore(unittest.TestCase):

    def test_zero_audits_zero_age(self):
        self.assertAlmostEqual(_safety_score(0, 0), 0.0)

    def test_audit_contribution_only(self):
        """3 audits, 0 age → 15."""
        self.assertAlmostEqual(_safety_score(3, 0), 15.0)

    def test_age_contribution_at_365(self):
        """0 audits, 365 days → 15."""
        self.assertAlmostEqual(_safety_score(0, 365), 15.0)

    def test_age_capped_at_1(self):
        """age_days beyond 365 still gives 15 max for age component."""
        score_730 = _safety_score(0, 730)
        score_365 = _safety_score(0, 365)
        self.assertAlmostEqual(score_730, score_365)

    def test_combined_audit_and_age(self):
        """2 audits + 365 age → 10 + 15 = 25."""
        self.assertAlmostEqual(_safety_score(2, 365), 25.0)

    def test_capped_at_30(self):
        """6 audits + 365 age → 30 + 15 = 45 → capped 30."""
        self.assertAlmostEqual(_safety_score(6, 365), 30.0)

    def test_partial_age(self):
        """0 audits, 182 days → ~7.5."""
        expected = min(182 / 365 * 15, 15)
        self.assertAlmostEqual(_safety_score(0, 182), expected, places=4)

    def test_max_reasonable(self):
        result = _safety_score(10, 1000)
        self.assertEqual(result, 30.0)


# ---------------------------------------------------------------------------
# 3. _liquidity_score  (pure function)
# ---------------------------------------------------------------------------

class TestLiquidityScore(unittest.TestCase):

    def test_zero_tvl(self):
        self.assertAlmostEqual(_liquidity_score(0.0), 0.0)

    def test_1B_tvl_at_cap(self):
        """TVL=1e9 → exactly 20."""
        self.assertAlmostEqual(_liquidity_score(1_000_000_000), 20.0)

    def test_above_1B_tvl_still_capped(self):
        self.assertAlmostEqual(_liquidity_score(5_000_000_000), 20.0)

    def test_1M_tvl_formula(self):
        """TVL=1e6 → log10(2)/log10(1001)*20."""
        expected = math.log10(2) / math.log10(1001) * 20
        self.assertAlmostEqual(_liquidity_score(1_000_000), expected, places=5)

    def test_negative_tvl_treated_as_zero(self):
        self.assertAlmostEqual(_liquidity_score(-500_000), 0.0)

    def test_monotonic_increase(self):
        """Higher TVL should yield higher liquidity score."""
        self.assertLess(_liquidity_score(1_000_000), _liquidity_score(10_000_000))
        self.assertLess(_liquidity_score(10_000_000), _liquidity_score(100_000_000))

    def test_100M_tvl(self):
        """TVL=100M — between 0 and 20."""
        score = _liquidity_score(100_000_000)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 20.0)

    def test_result_bounded(self):
        for tvl in [0, 1e5, 1e6, 1e8, 1e10]:
            s = _liquidity_score(tvl)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 20.0)


# ---------------------------------------------------------------------------
# 4. _fit_score  (pure function)
# ---------------------------------------------------------------------------

class TestFitScore(unittest.TestCase):

    def test_in_preferred_no_lock(self):
        self.assertAlmostEqual(_fit_score("ethereum", ["ethereum"], 0), 10.0)

    def test_in_preferred_with_lock(self):
        self.assertAlmostEqual(_fit_score("ethereum", ["ethereum"], 7), 7.0)

    def test_not_in_preferred_no_lock(self):
        self.assertAlmostEqual(_fit_score("base", ["ethereum"], 0), 5.0)

    def test_not_in_preferred_with_lock(self):
        self.assertAlmostEqual(_fit_score("base", ["ethereum"], 7), 2.0)

    def test_floor_at_zero(self):
        """Even with not preferred + long lock, score can't go below 0."""
        result = _fit_score("base", [], 100)
        self.assertGreaterEqual(result, 0.0)

    def test_preferred_chains_multiple(self):
        self.assertAlmostEqual(_fit_score("base", ["ethereum", "base"], 0), 10.0)

    def test_lock_days_1_subtracts_3(self):
        """lock_days=1 subtracts 3 from base."""
        self.assertAlmostEqual(_fit_score("ethereum", ["ethereum"], 1), 7.0)

    def test_lock_days_0_no_subtraction(self):
        score0 = _fit_score("ethereum", ["ethereum"], 0)
        score1 = _fit_score("ethereum", ["ethereum"], 1)
        self.assertEqual(score0 - score1, 3.0)


# ---------------------------------------------------------------------------
# 5. Filters
# ---------------------------------------------------------------------------

class TestFilters(unittest.TestCase):

    def test_chain_not_in_preferred_filtered(self):
        opps = [_opp(id_="op1", chain="arbitrum")]
        result = analyze(opps, _portfolio(preferred_chains=["ethereum"]))
        self.assertEqual(result["filtered_out"], 1)
        self.assertEqual(len(result["scored"]), 0)

    def test_lock_days_exceeds_max_filtered(self):
        opps = [_opp(id_="op1", lock_days=30)]
        result = analyze(opps, _portfolio(max_lock_days=0))
        self.assertEqual(result["filtered_out"], 1)
        self.assertEqual(len(result["scored"]), 0)

    def test_apy_below_min_filtered(self):
        opps = [_opp(id_="op1", apy=0.5)]
        result = analyze(opps, _portfolio(min_apy=1.0))
        self.assertEqual(result["filtered_out"], 1)
        self.assertEqual(len(result["scored"]), 0)

    def test_min_deposit_exceeds_total_filtered(self):
        opps = [_opp(id_="op1", min_deposit_usd=200_000)]
        result = analyze(opps, _portfolio(total_usd=100_000))
        self.assertEqual(result["filtered_out"], 1)
        self.assertEqual(len(result["scored"]), 0)

    def test_lock_days_equal_max_passes(self):
        opps = [_opp(id_="op1", lock_days=7)]
        result = analyze(opps, _portfolio(max_lock_days=7))
        self.assertEqual(result["filtered_out"], 0)
        self.assertEqual(len(result["scored"]), 1)

    def test_apy_equal_min_passes(self):
        opps = [_opp(id_="op1", apy=1.0)]
        result = analyze(opps, _portfolio(min_apy=1.0))
        self.assertEqual(result["filtered_out"], 0)
        self.assertEqual(len(result["scored"]), 1)

    def test_min_deposit_equal_total_passes(self):
        opps = [_opp(id_="op1", min_deposit_usd=100_000)]
        result = analyze(opps, _portfolio(total_usd=100_000))
        self.assertEqual(result["filtered_out"], 0)
        self.assertEqual(len(result["scored"]), 1)

    def test_multiple_filter_reasons_each_counted(self):
        """Two opps fail different filters — both counted."""
        opps = [
            _opp(id_="o1", chain="arbitrum"),
            _opp(id_="o2", lock_days=30, chain="ethereum"),
        ]
        result = analyze(opps, _portfolio())
        self.assertEqual(result["filtered_out"], 2)
        self.assertEqual(len(result["scored"]), 0)

    def test_partial_filter_some_pass(self):
        opps = [
            _opp(id_="o1", chain="arbitrum"),   # filtered
            _opp(id_="o2", chain="ethereum"),   # passes
        ]
        result = analyze(opps, _portfolio())
        self.assertEqual(result["filtered_out"], 1)
        self.assertEqual(len(result["scored"]), 1)

    def test_total_scanned_includes_all(self):
        opps = [_opp(id_=f"op{i}", chain="arbitrum") for i in range(5)]
        result = analyze(opps, _portfolio(preferred_chains=["ethereum"]))
        self.assertEqual(result["total_scanned"], 5)
        self.assertEqual(result["filtered_out"], 5)

    def test_total_scanned_correct_with_mixed(self):
        opps = [_opp(id_="p"), _opp(id_="q", chain="base")]
        result = analyze(opps, _portfolio(preferred_chains=["ethereum"]))
        self.assertEqual(result["total_scanned"], 2)


# ---------------------------------------------------------------------------
# 6. Composite score correctness
# ---------------------------------------------------------------------------

class TestCompositeScore(unittest.TestCase):

    def test_score_is_sum_of_components(self):
        opps = [_opp()]
        result = analyze(opps, _portfolio())
        e = result["scored"][0]
        expected = round(e["apy_score"] + e["safety_score"] + e["liquidity_score"] + e["fit_score"], 2)
        self.assertAlmostEqual(e["score"], expected, places=2)

    def test_all_score_fields_present(self):
        opps = [_opp()]
        entry = analyze(opps, _portfolio())["scored"][0]
        for field in ("id", "protocol", "type", "chain", "apy", "score",
                      "apy_score", "safety_score", "liquidity_score",
                      "fit_score", "recommended_allocation_usd"):
            self.assertIn(field, entry, f"Missing field: {field}")

    def test_apy_score_range(self):
        for apy in [0, 1, 5, 10, 25, 50]:
            opps = [_opp(apy=apy)]
            e = analyze(opps, _portfolio(min_apy=0.0))["scored"][0]
            self.assertGreaterEqual(e["apy_score"], 0.0)
            self.assertLessEqual(e["apy_score"], 40.0)

    def test_safety_score_range(self):
        e = analyze([_opp()], _portfolio())["scored"][0]
        self.assertGreaterEqual(e["safety_score"], 0.0)
        self.assertLessEqual(e["safety_score"], 30.0)

    def test_liquidity_score_range(self):
        e = analyze([_opp()], _portfolio())["scored"][0]
        self.assertGreaterEqual(e["liquidity_score"], 0.0)
        self.assertLessEqual(e["liquidity_score"], 20.0)

    def test_fit_score_range(self):
        e = analyze([_opp()], _portfolio())["scored"][0]
        self.assertGreaterEqual(e["fit_score"], 0.0)
        self.assertLessEqual(e["fit_score"], 10.0)

    def test_composite_score_bounded_0_100(self):
        opps = [
            _opp(apy=100, tvl_usd=10_000_000_000, audit_count=10, age_days=9999),
        ]
        e = analyze(opps, _portfolio(min_apy=0))["scored"][0]
        self.assertLessEqual(e["score"], 100.0)
        self.assertGreaterEqual(e["score"], 0.0)

    def test_higher_apy_higher_score_ceteris_paribus(self):
        opps = [_opp(id_="lo", apy=5.0), _opp(id_="hi", apy=20.0)]
        result = analyze(opps, _portfolio(min_apy=0.0))
        scores = {e["id"]: e["score"] for e in result["scored"]}
        self.assertGreater(scores["hi"], scores["lo"])


# ---------------------------------------------------------------------------
# 7. Sorting / top_picks
# ---------------------------------------------------------------------------

class TestTopPicks(unittest.TestCase):

    def test_sorted_descending(self):
        opps = [_opp(id_=f"op{i}", apy=float(i)) for i in range(5)]
        result = analyze(opps, _portfolio(min_apy=0.0))
        scores = [e["score"] for e in result["scored"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_default_top_n_is_5(self):
        opps = [_opp(id_=f"op{i}") for i in range(10)]
        result = analyze(opps, _portfolio())
        self.assertEqual(len(result["top_picks"]), DEFAULT_TOP_N)

    def test_custom_top_n(self):
        opps = [_opp(id_=f"op{i}") for i in range(10)]
        result = analyze(opps, _portfolio(), config={"top_n": 3})
        self.assertEqual(len(result["top_picks"]), 3)

    def test_top_n_larger_than_scored(self):
        opps = [_opp(id_="only")]
        result = analyze(opps, _portfolio(), config={"top_n": 10})
        self.assertEqual(len(result["top_picks"]), 1)

    def test_top_picks_are_highest_scores(self):
        opps = [_opp(id_=f"op{i}", apy=float(i)) for i in range(6)]
        result = analyze(opps, _portfolio(min_apy=0.0), config={"top_n": 3})
        picks = set(result["top_picks"])
        all_ids = {e["id"]: e["score"] for e in result["scored"]}
        pick_min = min(all_ids[i] for i in picks)
        non_pick_max = max(
            (s for i, s in all_ids.items() if i not in picks), default=float("-inf")
        )
        self.assertGreaterEqual(pick_min, non_pick_max)

    def test_top_n_zero_returns_empty_picks(self):
        opps = [_opp(id_="op1")]
        result = analyze(opps, _portfolio(), config={"top_n": 0})
        self.assertEqual(result["top_picks"], [])

    def test_config_none_defaults(self):
        opps = [_opp(id_=f"op{i}") for i in range(10)]
        result = analyze(opps, _portfolio(), config=None)
        self.assertEqual(len(result["top_picks"]), DEFAULT_TOP_N)


# ---------------------------------------------------------------------------
# 8. recommended_allocation_usd
# ---------------------------------------------------------------------------

class TestRecommendedAllocation(unittest.TestCase):

    def test_top_picks_get_nonzero_allocation(self):
        opps = [_opp(id_="op1", apy=5.0)]
        result = analyze(opps, _portfolio(total_usd=100_000))
        e = result["scored"][0]
        self.assertGreater(e["recommended_allocation_usd"], 0.0)

    def test_non_top_picks_get_zero_allocation(self):
        opps = [_opp(id_=f"op{i}", apy=float(i)) for i in range(1, 7)]
        result = analyze(opps, _portfolio(min_apy=0.0), config={"top_n": 3})
        picks = set(result["top_picks"])
        for e in result["scored"]:
            if e["id"] not in picks:
                self.assertEqual(e["recommended_allocation_usd"], 0.0)

    def test_allocation_formula(self):
        """score/100 * total_usd / len(top_picks)."""
        opps = [_opp(id_="op1", apy=10.0, tvl_usd=1_000_000_000,
                     audit_count=3, age_days=400)]
        total_usd = 50_000.0
        result = analyze(opps, _portfolio(total_usd=total_usd), config={"top_n": 1})
        e = result["scored"][0]
        expected = round(e["score"] / 100.0 * total_usd / 1, 2)
        self.assertAlmostEqual(e["recommended_allocation_usd"], expected, places=2)

    def test_allocation_zero_when_empty_scored(self):
        """No opps pass → no allocation issue."""
        result = analyze([], _portfolio())
        # just confirm no error
        self.assertEqual(result["top_picks"], [])

    def test_allocation_scales_with_total_usd(self):
        opps = [_opp(id_="op1")]
        r1 = analyze(opps, _portfolio(total_usd=100_000), config={"top_n": 1})
        r2 = analyze(opps, _portfolio(total_usd=200_000), config={"top_n": 1})
        alloc1 = r1["scored"][0]["recommended_allocation_usd"]
        alloc2 = r2["scored"][0]["recommended_allocation_usd"]
        self.assertAlmostEqual(alloc2, alloc1 * 2, places=2)


# ---------------------------------------------------------------------------
# 9. best_apy / safest
# ---------------------------------------------------------------------------

class TestBestApyAndSafest(unittest.TestCase):

    def test_best_apy_correct_id(self):
        opps = [_opp(id_="lo", apy=3.0), _opp(id_="hi", apy=15.0)]
        result = analyze(opps, _portfolio(min_apy=0.0))
        self.assertEqual(result["best_apy"], "hi")

    def test_safest_correct_id(self):
        opps = [
            _opp(id_="risky", audit_count=0, age_days=30),
            _opp(id_="safe", audit_count=5, age_days=730),
        ]
        result = analyze(opps, _portfolio())
        self.assertEqual(result["safest"], "safe")

    def test_best_apy_none_when_empty(self):
        result = analyze([], _portfolio())
        self.assertIsNone(result["best_apy"])

    def test_safest_none_when_empty(self):
        result = analyze([], _portfolio())
        self.assertIsNone(result["safest"])

    def test_best_apy_single_opp(self):
        opps = [_opp(id_="only", apy=8.0)]
        result = analyze(opps, _portfolio())
        self.assertEqual(result["best_apy"], "only")

    def test_safest_single_opp(self):
        opps = [_opp(id_="only")]
        result = analyze(opps, _portfolio())
        self.assertEqual(result["safest"], "only")


# ---------------------------------------------------------------------------
# 10. Result structure / metadata
# ---------------------------------------------------------------------------

class TestResultStructure(unittest.TestCase):

    def test_required_keys_present(self):
        result = analyze([], _portfolio())
        for key in ("total_scanned", "filtered_out", "scored", "top_picks",
                    "best_apy", "safest", "timestamp"):
            self.assertIn(key, result)

    def test_timestamp_is_float(self):
        result = analyze([], _portfolio())
        self.assertIsInstance(result["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([], _portfolio())
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_scored_is_list(self):
        result = analyze([], _portfolio())
        self.assertIsInstance(result["scored"], list)

    def test_top_picks_is_list(self):
        result = analyze([], _portfolio())
        self.assertIsInstance(result["top_picks"], list)

    def test_total_scanned_zero_for_empty(self):
        result = analyze([], _portfolio())
        self.assertEqual(result["total_scanned"], 0)
        self.assertEqual(result["filtered_out"], 0)

    def test_scored_entries_have_correct_protocol(self):
        opps = [_opp(id_="x", protocol="Aave")]
        entry = analyze(opps, _portfolio())["scored"][0]
        self.assertEqual(entry["protocol"], "Aave")

    def test_scored_entries_have_correct_type(self):
        opps = [_opp(id_="x", type_="vault")]
        entry = analyze(opps, _portfolio())["scored"][0]
        self.assertEqual(entry["type"], "vault")

    def test_scored_entries_have_correct_chain(self):
        opps = [_opp(id_="x", chain="ethereum")]
        entry = analyze(opps, _portfolio())["scored"][0]
        self.assertEqual(entry["chain"], "ethereum")

    def test_scored_entries_have_correct_apy(self):
        opps = [_opp(id_="x", apy=7.5)]
        entry = analyze(opps, _portfolio())["scored"][0]
        self.assertEqual(entry["apy"], 7.5)


# ---------------------------------------------------------------------------
# 11. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_opportunities_no_error(self):
        result = analyze([], _portfolio())
        self.assertEqual(result["total_scanned"], 0)
        self.assertEqual(result["scored"], [])
        self.assertEqual(result["top_picks"], [])

    def test_all_filtered_out_empty_scored(self):
        opps = [_opp(chain="avalanche"), _opp(chain="polygon")]
        result = analyze(opps, _portfolio(preferred_chains=["ethereum"]))
        self.assertEqual(result["scored"], [])
        self.assertEqual(result["top_picks"], [])
        self.assertIsNone(result["best_apy"])
        self.assertIsNone(result["safest"])

    def test_single_opportunity_passes(self):
        opps = [_opp(id_="solo")]
        result = analyze(opps, _portfolio())
        self.assertEqual(len(result["scored"]), 1)
        self.assertEqual(result["top_picks"], ["solo"])

    def test_preferred_chains_empty_filters_all(self):
        opps = [_opp(id_="op1")]
        result = analyze(opps, _portfolio(preferred_chains=[]))
        self.assertEqual(result["filtered_out"], 1)
        self.assertEqual(len(result["scored"]), 0)

    def test_multiple_preferred_chains(self):
        opps = [
            _opp(id_="eth", chain="ethereum"),
            _opp(id_="base", chain="base"),
            _opp(id_="arb", chain="arbitrum"),
        ]
        result = analyze(
            opps,
            _portfolio(preferred_chains=["ethereum", "base"])
        )
        self.assertEqual(result["filtered_out"], 1)
        self.assertEqual(len(result["scored"]), 2)

    def test_zero_total_usd_no_crash(self):
        opps = [_opp(min_deposit_usd=0.0)]
        result = analyze(opps, _portfolio(total_usd=0.0))
        # min_deposit=0 <= total_usd=0 → passes
        self.assertEqual(len(result["scored"]), 1)

    def test_opp_missing_optional_fields_defaults(self):
        """Minimal opportunity dict — only required fields."""
        opp = {"id": "minimal", "chain": "ethereum", "apy": 3.0,
               "min_deposit_usd": 0, "lock_days": 0}
        result = analyze([opp], _portfolio(min_apy=0))
        self.assertEqual(len(result["scored"]), 1)

    def test_apy_zero_passes_zero_min_apy(self):
        opps = [_opp(id_="z", apy=0.0)]
        result = analyze(opps, _portfolio(min_apy=0.0))
        self.assertEqual(len(result["scored"]), 1)


# ---------------------------------------------------------------------------
# 12. Persistence / ring-buffer
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_data_file = yos.DATA_FILE
        yos.DATA_FILE = Path(self._tmpdir) / "data" / "yield_opportunity_scan_log.json"

    def tearDown(self):
        yos.DATA_FILE = self._orig_data_file

    def test_log_file_created_on_first_call(self):
        analyze([], _portfolio())
        self.assertTrue(yos.DATA_FILE.exists())

    def test_log_file_is_list(self):
        analyze([], _portfolio())
        data = json.loads(yos.DATA_FILE.read_text())
        self.assertIsInstance(data, list)

    def test_log_appends_entry(self):
        analyze([], _portfolio())
        analyze([], _portfolio())
        data = json.loads(yos.DATA_FILE.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(MAX_ENTRIES + 5):
            analyze([], _portfolio())
        data = json.loads(yos.DATA_FILE.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_most_recent(self):
        """After 102 calls, the buffer should have exactly MAX_ENTRIES entries."""
        for i in range(MAX_ENTRIES + 2):
            analyze([], _portfolio())
        data = json.loads(yos.DATA_FILE.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_no_tmp_file_left_behind(self):
        analyze([], _portfolio())
        tmp = yos.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_corrupt_log_file_recovers(self):
        yos.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        yos.DATA_FILE.write_text("NOT JSON", encoding="utf-8")
        analyze([], _portfolio())  # should not raise
        data = json.loads(yos.DATA_FILE.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_persistence_never_raises_on_bad_path(self):
        """Even with an unwritable path, analyze() must complete."""
        yos.DATA_FILE = Path("/root/nonexistent/deeply/nested/scan.json")
        try:
            result = analyze([], _portfolio())
            self.assertIn("timestamp", result)
        finally:
            yos.DATA_FILE = Path(self._tmpdir) / "data" / "yield_opportunity_scan_log.json"


# ---------------------------------------------------------------------------
# 13. Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_max_entries_is_100(self):
        self.assertEqual(MAX_ENTRIES, 100)

    def test_default_top_n_is_5(self):
        self.assertEqual(DEFAULT_TOP_N, 5)


if __name__ == "__main__":
    unittest.main()
