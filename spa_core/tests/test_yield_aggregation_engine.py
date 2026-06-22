"""
Tests for MP-715: YieldAggregationEngine
≥65 tests covering all logic paths.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone


def _make_engine(tmp_dir: str):
    """Import module with patched _LOG_FILE and _DATA_DIR."""
    import spa_core.analytics.yield_aggregation_engine as mod
    mod._LOG_FILE = os.path.join(tmp_dir, "yield_aggregation_log.json")
    mod._DATA_DIR = tmp_dir
    return mod


_NOW = datetime.now(timezone.utc).isoformat()


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mod = _make_engine(self.tmp)

    def entry(self, **kwargs):
        defaults = dict(
            source="aave_v3",
            protocol="Aave V3",
            pool="USDC",
            chain="ethereum",
            apy=3.5,
            tvl_usd=50_000_000,
            risk_score=10.0,
            liquidity_usd=40_000_000,
            last_updated_iso=_NOW,
        )
        defaults.update(kwargs)
        return self.mod.YieldEntry(**defaults)

    def default_entries(self):
        return [
            self.entry(source="aave_v3", protocol="Aave V3", pool="USDC", chain="ethereum", apy=3.5, tvl_usd=50_000_000, risk_score=10.0),
            self.entry(source="compound_v3", protocol="Compound V3", pool="USDC", chain="ethereum", apy=4.8, tvl_usd=30_000_000, risk_score=15.0),
            self.entry(source="morpho", protocol="Morpho", pool="USDC", chain="ethereum", apy=6.5, tvl_usd=20_000_000, risk_score=20.0),
            self.entry(source="aave_arb", protocol="Aave V3", pool="USDC-ARB", chain="arbitrum", apy=4.6, tvl_usd=10_000_000, risk_score=18.0),
        ]


class TestRiskAdjustedApy(_Base):
    def test_risk_zero(self):
        e = self.entry(apy=5.0, risk_score=0.0)
        self.assertAlmostEqual(self.mod.risk_adjusted_apy(e), 5.0)

    def test_risk_100(self):
        e = self.entry(apy=10.0, risk_score=100.0)
        self.assertAlmostEqual(self.mod.risk_adjusted_apy(e), 5.0)

    def test_risk_50(self):
        e = self.entry(apy=3.0, risk_score=50.0)
        self.assertAlmostEqual(self.mod.risk_adjusted_apy(e), 2.0)

    def test_risk_10(self):
        e = self.entry(apy=5.5, risk_score=10.0)
        expected = 5.5 / 1.1
        self.assertAlmostEqual(self.mod.risk_adjusted_apy(e), expected)

    def test_risk_25(self):
        e = self.entry(apy=5.0, risk_score=25.0)
        expected = 5.0 / 1.25
        self.assertAlmostEqual(self.mod.risk_adjusted_apy(e), expected)


class TestComputeMedian(_Base):
    def test_single_element(self):
        self.assertAlmostEqual(self.mod.compute_median([7.0]), 7.0)

    def test_odd_list(self):
        self.assertAlmostEqual(self.mod.compute_median([1.0, 3.0, 5.0]), 3.0)

    def test_even_list(self):
        self.assertAlmostEqual(self.mod.compute_median([1.0, 3.0, 5.0, 7.0]), 4.0)

    def test_unsorted_odd(self):
        self.assertAlmostEqual(self.mod.compute_median([5.0, 1.0, 3.0]), 3.0)

    def test_unsorted_even(self):
        self.assertAlmostEqual(self.mod.compute_median([7.0, 1.0, 5.0, 3.0]), 4.0)

    def test_empty_list(self):
        self.assertAlmostEqual(self.mod.compute_median([]), 0.0)

    def test_two_elements(self):
        self.assertAlmostEqual(self.mod.compute_median([2.0, 4.0]), 3.0)

    def test_identical_elements(self):
        self.assertAlmostEqual(self.mod.compute_median([5.0, 5.0, 5.0]), 5.0)


class TestAggregateFilters(_Base):
    def test_min_tvl_filter(self):
        entries = [
            self.entry(tvl_usd=500_000, protocol="Small"),
            self.entry(tvl_usd=5_000_000, protocol="Large"),
        ]
        view = self.mod.aggregate(entries, min_tvl_usd=1_000_000)
        self.assertEqual(view.total_entries, 1)
        self.assertEqual(view.top_by_apy[0].protocol, "Large")

    def test_max_risk_filter(self):
        entries = [
            self.entry(risk_score=80.0, protocol="Risky"),
            self.entry(risk_score=20.0, protocol="Safe"),
        ]
        view = self.mod.aggregate(entries, max_risk_score=50.0)
        self.assertEqual(view.total_entries, 1)
        self.assertEqual(view.top_by_apy[0].protocol, "Safe")

    def test_chain_filter(self):
        entries = [
            self.entry(chain="ethereum", protocol="Eth"),
            self.entry(chain="arbitrum", protocol="Arb"),
        ]
        view = self.mod.aggregate(entries, allowed_chains=["ethereum"])
        self.assertEqual(view.total_entries, 1)
        self.assertEqual(view.top_by_apy[0].protocol, "Eth")

    def test_chain_filter_case_insensitive(self):
        entries = [
            self.entry(chain="Ethereum", protocol="Eth"),
            self.entry(chain="arbitrum", protocol="Arb"),
        ]
        view = self.mod.aggregate(entries, allowed_chains=["ethereum"])
        self.assertEqual(view.total_entries, 1)

    def test_no_chain_filter_keeps_all(self):
        entries = self.default_entries()
        view = self.mod.aggregate(entries)
        self.assertEqual(view.total_entries, 4)

    def test_all_filters_combined(self):
        entries = [
            self.entry(chain="ethereum", tvl_usd=5_000_000, risk_score=10.0, protocol="Pass"),
            self.entry(chain="arbitrum", tvl_usd=5_000_000, risk_score=10.0, protocol="WrongChain"),
            self.entry(chain="ethereum", tvl_usd=500_000, risk_score=10.0, protocol="LowTVL"),
            self.entry(chain="ethereum", tvl_usd=5_000_000, risk_score=80.0, protocol="HighRisk"),
        ]
        view = self.mod.aggregate(entries, min_tvl_usd=1_000_000, max_risk_score=50.0, allowed_chains=["ethereum"])
        self.assertEqual(view.total_entries, 1)
        self.assertEqual(view.top_by_apy[0].protocol, "Pass")

    def test_filters_applied_stored(self):
        view = self.mod.aggregate([], min_tvl_usd=1_000_000, max_risk_score=50.0, allowed_chains=["ethereum"])
        self.assertEqual(view.filters_applied["min_tvl"], 1_000_000)
        self.assertEqual(view.filters_applied["max_risk"], 50.0)
        self.assertEqual(view.filters_applied["chains"], ["ethereum"])

    def test_filters_applied_empty_chains(self):
        view = self.mod.aggregate([])
        self.assertEqual(view.filters_applied["chains"], [])


class TestAggregateRankings(_Base):
    def test_top_by_apy_sorted_desc(self):
        entries = [self.entry(apy=float(i)) for i in range(15)]
        view = self.mod.aggregate(entries)
        apys = [e.apy for e in view.top_by_apy]
        self.assertEqual(apys, sorted(apys, reverse=True))

    def test_top_by_apy_max_10(self):
        entries = [self.entry(apy=float(i)) for i in range(20)]
        view = self.mod.aggregate(entries)
        self.assertEqual(len(view.top_by_apy), 10)

    def test_top_by_apy_fewer_than_10(self):
        entries = [self.entry(apy=float(i)) for i in range(3)]
        view = self.mod.aggregate(entries)
        self.assertEqual(len(view.top_by_apy), 3)

    def test_top_by_risk_adjusted_uses_formula(self):
        # risk_score=0 → ra = apy; risk_score=100 → ra = apy/2
        entries = [
            self.entry(apy=10.0, risk_score=100.0, protocol="A"),  # ra=5
            self.entry(apy=6.0, risk_score=0.0, protocol="B"),     # ra=6
        ]
        view = self.mod.aggregate(entries)
        self.assertEqual(view.top_by_risk_adjusted[0].protocol, "B")

    def test_top_by_risk_adjusted_max_10(self):
        entries = [self.entry(apy=float(i)) for i in range(20)]
        view = self.mod.aggregate(entries)
        self.assertEqual(len(view.top_by_risk_adjusted), 10)

    def test_top_by_tvl_sorted_desc(self):
        entries = [self.entry(tvl_usd=float(i * 1_000_000)) for i in range(15)]
        view = self.mod.aggregate(entries)
        tvls = [e.tvl_usd for e in view.top_by_tvl]
        self.assertEqual(tvls, sorted(tvls, reverse=True))

    def test_top_by_tvl_max_10(self):
        entries = [self.entry(tvl_usd=float(i * 1_000_000)) for i in range(15)]
        view = self.mod.aggregate(entries)
        self.assertEqual(len(view.top_by_tvl), 10)


class TestAggregateStatistics(_Base):
    def test_avg_apy(self):
        entries = [self.entry(apy=2.0), self.entry(apy=4.0), self.entry(apy=6.0)]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.avg_apy, 4.0)

    def test_median_apy_odd(self):
        entries = [self.entry(apy=1.0), self.entry(apy=5.0), self.entry(apy=9.0)]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.median_apy, 5.0)

    def test_median_apy_even(self):
        entries = [self.entry(apy=2.0), self.entry(apy=4.0),
                   self.entry(apy=6.0), self.entry(apy=8.0)]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.median_apy, 5.0)

    def test_max_apy(self):
        entries = [self.entry(apy=1.0), self.entry(apy=9.0), self.entry(apy=5.0)]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.max_apy, 9.0)

    def test_min_apy(self):
        entries = [self.entry(apy=1.0), self.entry(apy=9.0), self.entry(apy=5.0)]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.min_apy, 1.0)

    def test_avg_risk_score(self):
        entries = [self.entry(risk_score=10.0), self.entry(risk_score=30.0)]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.avg_risk_score, 20.0)

    def test_zero_stats_on_empty(self):
        view = self.mod.aggregate([])
        self.assertAlmostEqual(view.avg_apy, 0.0)
        self.assertAlmostEqual(view.median_apy, 0.0)
        self.assertAlmostEqual(view.max_apy, 0.0)
        self.assertAlmostEqual(view.min_apy, 0.0)
        self.assertAlmostEqual(view.avg_risk_score, 0.0)


class TestAggregateUniqueCounts(_Base):
    def test_unique_protocols(self):
        entries = [
            self.entry(protocol="Aave"),
            self.entry(protocol="Aave"),
            self.entry(protocol="Compound"),
        ]
        view = self.mod.aggregate(entries)
        self.assertEqual(view.unique_protocols, 2)

    def test_unique_chains(self):
        entries = [
            self.entry(chain="ethereum"),
            self.entry(chain="ethereum"),
            self.entry(chain="arbitrum"),
        ]
        view = self.mod.aggregate(entries)
        self.assertEqual(view.unique_chains, 2)

    def test_unique_single(self):
        entries = [self.entry(protocol="Aave", chain="ethereum")]
        view = self.mod.aggregate(entries)
        self.assertEqual(view.unique_protocols, 1)
        self.assertEqual(view.unique_chains, 1)

    def test_unique_zero_empty(self):
        view = self.mod.aggregate([])
        self.assertEqual(view.unique_protocols, 0)
        self.assertEqual(view.unique_chains, 0)


class TestByChain(_Base):
    def test_by_chain_keys(self):
        entries = [
            self.entry(chain="ethereum", apy=4.0, tvl_usd=10_000_000),
            self.entry(chain="arbitrum", apy=5.0, tvl_usd=5_000_000),
        ]
        view = self.mod.aggregate(entries)
        self.assertIn("ethereum", view.by_chain)
        self.assertIn("arbitrum", view.by_chain)

    def test_by_chain_count(self):
        entries = [
            self.entry(chain="ethereum"),
            self.entry(chain="ethereum"),
            self.entry(chain="arbitrum"),
        ]
        view = self.mod.aggregate(entries)
        self.assertEqual(view.by_chain["ethereum"]["count"], 2)
        self.assertEqual(view.by_chain["arbitrum"]["count"], 1)

    def test_by_chain_avg_apy(self):
        entries = [
            self.entry(chain="ethereum", apy=4.0),
            self.entry(chain="ethereum", apy=6.0),
        ]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.by_chain["ethereum"]["avg_apy"], 5.0)

    def test_by_chain_total_tvl(self):
        entries = [
            self.entry(chain="ethereum", tvl_usd=10_000_000),
            self.entry(chain="ethereum", tvl_usd=20_000_000),
        ]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.by_chain["ethereum"]["total_tvl"], 30_000_000)

    def test_by_chain_empty(self):
        view = self.mod.aggregate([])
        self.assertEqual(view.by_chain, {})


class TestFindArbitrage(_Base):
    def test_finds_same_pool_different_chains(self):
        entries = [
            self.entry(pool="USDC", chain="ethereum", apy=4.0, source="aave_eth"),
            self.entry(pool="USDC", chain="arbitrum", apy=6.0, source="aave_arb"),
        ]
        view = self.mod.aggregate(entries)
        arb = self.mod.find_arbitrage(view, min_spread_pct=0.5)
        self.assertEqual(len(arb), 1)
        self.assertAlmostEqual(arb[0][2], 2.0)  # spread = |6 - 4|

    def test_no_arbitrage_spread_too_small(self):
        entries = [
            self.entry(pool="USDC", chain="ethereum", apy=4.0, source="a"),
            self.entry(pool="USDC", chain="arbitrum", apy=4.3, source="b"),
        ]
        view = self.mod.aggregate(entries)
        arb = self.mod.find_arbitrage(view, min_spread_pct=0.5)
        self.assertEqual(len(arb), 0)

    def test_no_arbitrage_same_chain(self):
        entries = [
            self.entry(pool="USDC", chain="ethereum", apy=4.0, source="a"),
            self.entry(pool="USDC", chain="ethereum", apy=8.0, source="b"),
        ]
        view = self.mod.aggregate(entries)
        arb = self.mod.find_arbitrage(view, min_spread_pct=0.5)
        self.assertEqual(len(arb), 0)

    def test_arbitrage_case_insensitive_pool_name(self):
        entries = [
            self.entry(pool="usdc", chain="ethereum", apy=4.0, source="a"),
            self.entry(pool="USDC", chain="arbitrum", apy=7.0, source="b"),
        ]
        view = self.mod.aggregate(entries)
        arb = self.mod.find_arbitrage(view, min_spread_pct=0.5)
        self.assertEqual(len(arb), 1)

    def test_arbitrage_sorted_by_spread_desc(self):
        entries = [
            self.entry(pool="USDC", chain="ethereum", apy=4.0, source="a"),
            self.entry(pool="USDC", chain="arbitrum", apy=8.0, source="b"),   # spread=4
            self.entry(pool="DAI", chain="ethereum", apy=3.0, source="c"),
            self.entry(pool="DAI", chain="polygon", apy=4.5, source="d"),    # spread=1.5
        ]
        view = self.mod.aggregate(entries)
        arb = self.mod.find_arbitrage(view, min_spread_pct=0.5)
        self.assertGreaterEqual(len(arb), 2)
        spreads = [x[2] for x in arb]
        self.assertEqual(spreads, sorted(spreads, reverse=True))

    def test_no_arbitrage_empty_view(self):
        view = self.mod.aggregate([])
        arb = self.mod.find_arbitrage(view, min_spread_pct=0.5)
        self.assertEqual(arb, [])

    def test_arbitrage_tuple_format(self):
        entries = [
            self.entry(pool="USDC", chain="ethereum", apy=3.0, source="a"),
            self.entry(pool="USDC", chain="arbitrum", apy=6.0, source="b"),
        ]
        view = self.mod.aggregate(entries)
        arb = self.mod.find_arbitrage(view, min_spread_pct=0.5)
        a_entry, b_entry, spread = arb[0]
        self.assertIsInstance(a_entry, self.mod.YieldEntry)
        self.assertIsInstance(b_entry, self.mod.YieldEntry)
        self.assertIsInstance(spread, float)


class TestSaveLoad(_Base):
    def test_save_creates_file(self):
        view = self.mod.aggregate(self.default_entries())
        self.mod.save_results(view)
        self.assertTrue(os.path.exists(self.mod._LOG_FILE))

    def test_save_sets_saved_to(self):
        view = self.mod.aggregate(self.default_entries())
        self.mod.save_results(view)
        self.assertEqual(view.saved_to, self.mod._LOG_FILE)

    def test_load_empty_initially(self):
        self.assertEqual(self.mod.load_history(), [])

    def test_round_trip(self):
        view = self.mod.aggregate(self.default_entries())
        self.mod.save_results(view)
        history = self.mod.load_history()
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertIn("total_entries", entry)
        self.assertIn("top_by_apy", entry)
        self.assertIn("by_chain", entry)
        self.assertIn("filters_applied", entry)

    def test_top_by_apy_serialised_as_list(self):
        view = self.mod.aggregate(self.default_entries())
        self.mod.save_results(view)
        history = self.mod.load_history()
        self.assertIsInstance(history[0]["top_by_apy"], list)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            view = self.mod.aggregate(self.default_entries())
            self.mod.save_results(view)
        self.assertEqual(len(self.mod.load_history()), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(115):
            view = self.mod.aggregate(self.default_entries())
            self.mod.save_results(view)
        self.assertEqual(len(self.mod.load_history()), 100)

    def test_ring_buffer_keeps_latest(self):
        # Save 101 entries with distinct total_entries values
        for i in range(101):
            entries = [self.entry(protocol=f"P{j}") for j in range(i % 5 + 1)]
            view = self.mod.aggregate(entries)
            view.total_entries = i  # override for tracking
            self.mod.save_results(view)
        history = self.mod.load_history()
        self.assertEqual(len(history), 100)
        # The last saved entry had total_entries=100
        self.assertEqual(history[-1]["total_entries"], 100)

    def test_load_returns_empty_on_missing_file(self):
        if os.path.exists(self.mod._LOG_FILE):
            os.remove(self.mod._LOG_FILE)
        self.assertEqual(self.mod.load_history(), [])

    def test_load_returns_empty_on_corrupt_file(self):
        with open(self.mod._LOG_FILE, "w") as fh:
            fh.write("not json")
        self.assertEqual(self.mod.load_history(), [])

    def test_atomic_write_no_tmp_files(self):
        view = self.mod.aggregate(self.default_entries())
        self.mod.save_results(view)
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


class TestEdgeCases(_Base):
    def test_empty_entries_total_zero(self):
        view = self.mod.aggregate([])
        self.assertEqual(view.total_entries, 0)

    def test_empty_entries_top_lists_empty(self):
        view = self.mod.aggregate([])
        self.assertEqual(view.top_by_apy, [])
        self.assertEqual(view.top_by_risk_adjusted, [])
        self.assertEqual(view.top_by_tvl, [])

    def test_single_entry_stats(self):
        entries = [self.entry(apy=5.0, risk_score=20.0)]
        view = self.mod.aggregate(entries)
        self.assertAlmostEqual(view.avg_apy, 5.0)
        self.assertAlmostEqual(view.median_apy, 5.0)
        self.assertAlmostEqual(view.max_apy, 5.0)
        self.assertAlmostEqual(view.min_apy, 5.0)
        self.assertAlmostEqual(view.avg_risk_score, 20.0)

    def test_all_filtered_out(self):
        entries = [self.entry(tvl_usd=500_000)]
        view = self.mod.aggregate(entries, min_tvl_usd=1_000_000)
        self.assertEqual(view.total_entries, 0)
        self.assertAlmostEqual(view.avg_apy, 0.0)

    def test_apy_entry_fields_preserved(self):
        e = self.entry(apy=7.7, protocol="TestProto", pool="USDC-Test")
        view = self.mod.aggregate([e])
        self.assertEqual(view.top_by_apy[0].protocol, "TestProto")
        self.assertAlmostEqual(view.top_by_apy[0].apy, 7.7)

    def test_total_entries_matches_filtered_count(self):
        entries = [self.entry(tvl_usd=5_000_000) for _ in range(7)]
        entries += [self.entry(tvl_usd=500_000) for _ in range(3)]
        view = self.mod.aggregate(entries, min_tvl_usd=1_000_000)
        self.assertEqual(view.total_entries, 7)


if __name__ == "__main__":
    unittest.main()
