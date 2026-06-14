"""
Tests for MP-714: LiquidityMigrationAdvisor
≥65 tests covering all logic paths.
"""
import json
import math
import os
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Patch the data dir to a temp location before import
# ---------------------------------------------------------------------------
_ORIG_LOG_FILE = None


def _make_advisor(tmp_dir: str):
    """Import module with patched _LOG_FILE and _DATA_DIR."""
    import spa_core.analytics.liquidity_migration_advisor as mod
    mod._LOG_FILE = os.path.join(tmp_dir, "migration_advisory_log.json")
    mod._DATA_DIR = tmp_dir
    return mod


class TestEstimateEntryCost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mod = _make_advisor(self.tmp)

    def test_same_chain_lowercase(self):
        self.assertAlmostEqual(self.mod.estimate_entry_cost("ethereum", "ethereum"), 0.10)

    def test_same_chain_mixed_case(self):
        self.assertAlmostEqual(self.mod.estimate_entry_cost("Ethereum", "ethereum"), 0.10)

    def test_same_chain_uppercase(self):
        self.assertAlmostEqual(self.mod.estimate_entry_cost("ARBITRUM", "ARBITRUM"), 0.10)

    def test_different_chain(self):
        self.assertAlmostEqual(self.mod.estimate_entry_cost("ethereum", "arbitrum"), 0.25)

    def test_different_chain_polygon(self):
        self.assertAlmostEqual(self.mod.estimate_entry_cost("ethereum", "polygon"), 0.25)

    def test_different_chain_optimism(self):
        self.assertAlmostEqual(self.mod.estimate_entry_cost("arbitrum", "optimism"), 0.25)


class _Base(unittest.TestCase):
    """Helper to build PoolProfile objects quickly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mod = _make_advisor(self.tmp)

    def pool(self, **kwargs):
        defaults = dict(
            name="USDC-Pool",
            protocol="Aave V3",
            chain="ethereum",
            apy=3.5,
            tvl_usd=50_000_000,
            lock_period_days=0,
            exit_penalty_pct=0.0,
            risk_score=10.0,
            liquidity_depth_usd=40_000_000,
        )
        defaults.update(kwargs)
        return self.mod.PoolProfile(**defaults)

    def analyze(self, current=None, candidate=None, position_usd=50_000):
        c = current or self.pool()
        cd = candidate or self.pool(apy=6.5, protocol="Morpho", name="USDC-Morpho")
        return self.mod.analyze(c, cd, position_usd)


class TestApyGain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mod = _make_advisor(self.tmp)

    def _pool(self, **kw):
        defaults = dict(
            name="P", protocol="X", chain="ethereum", apy=3.5, tvl_usd=1e7,
            lock_period_days=0, exit_penalty_pct=0.0, risk_score=10.0, liquidity_depth_usd=1e7
        )
        defaults.update(kw)
        return self.mod.PoolProfile(**defaults)

    def test_positive_gain(self):
        c = self._pool(apy=3.5)
        cd = self._pool(apy=6.5)
        a = self.mod.analyze(c, cd, 50_000)
        self.assertAlmostEqual(a.apy_gain_pct, 3.0)

    def test_zero_gain(self):
        c = self._pool(apy=5.0)
        cd = self._pool(apy=5.0)
        a = self.mod.analyze(c, cd, 50_000)
        self.assertAlmostEqual(a.apy_gain_pct, 0.0)

    def test_negative_gain(self):
        c = self._pool(apy=6.0)
        cd = self._pool(apy=3.0)
        a = self.mod.analyze(c, cd, 50_000)
        self.assertAlmostEqual(a.apy_gain_pct, -3.0)

    def test_gain_small(self):
        c = self._pool(apy=4.0)
        cd = self._pool(apy=4.5)
        a = self.mod.analyze(c, cd, 50_000)
        self.assertAlmostEqual(a.apy_gain_pct, 0.5)


class TestRiskAdjustedGain(_Base):
    def test_zero_risk_score(self):
        c = self.pool(apy=3.0)
        cd = self.pool(apy=6.0, risk_score=0.0)
        a = self.analyze(c, cd)
        # risk_adjusted_gain = (6.0 - 3.0) / (1 + 0/100) = 3.0
        self.assertAlmostEqual(a.risk_adjusted_gain, 3.0)

    def test_high_risk_score(self):
        c = self.pool(apy=3.0)
        cd = self.pool(apy=6.0, risk_score=100.0)
        a = self.analyze(c, cd)
        # risk_adjusted_gain = 3.0 / 2.0 = 1.5
        self.assertAlmostEqual(a.risk_adjusted_gain, 1.5)

    def test_negative_gain_risk_adjusted(self):
        c = self.pool(apy=6.0)
        cd = self.pool(apy=3.0, risk_score=50.0)
        a = self.analyze(c, cd)
        # (-3.0) / (1 + 0.5) = -2.0
        self.assertAlmostEqual(a.risk_adjusted_gain, -2.0)

    def test_risk_score_50(self):
        c = self.pool(apy=0.0)
        cd = self.pool(apy=3.0, risk_score=50.0)
        a = self.analyze(c, cd)
        self.assertAlmostEqual(a.risk_adjusted_gain, 2.0)


class TestExitCost(_Base):
    def test_exit_cost_includes_gas(self):
        c = self.pool(exit_penalty_pct=0.0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertAlmostEqual(a.exit_cost_pct, 0.0 + 0.10)

    def test_exit_cost_with_penalty(self):
        c = self.pool(exit_penalty_pct=2.0, lock_period_days=30)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertAlmostEqual(a.exit_cost_pct, 2.0 + 0.10)

    def test_exit_cost_large_penalty(self):
        c = self.pool(exit_penalty_pct=5.0, lock_period_days=90)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertAlmostEqual(a.exit_cost_pct, 5.1)


class TestTotalCost(_Base):
    def test_total_cost_usd_same_chain(self):
        c = self.pool(exit_penalty_pct=0.0, chain="ethereum")
        cd = self.pool(apy=8.0, chain="ethereum")
        a = self.analyze(c, cd, position_usd=100_000)
        # exit_cost=0.1, entry_cost=0.1, total=0.2%, cost=200
        self.assertAlmostEqual(a.total_cost_usd, 200.0)

    def test_total_cost_usd_cross_chain(self):
        c = self.pool(exit_penalty_pct=0.0, chain="ethereum")
        cd = self.pool(apy=8.0, chain="arbitrum")
        a = self.analyze(c, cd, position_usd=100_000)
        # exit_cost=0.1, entry_cost=0.25, total=0.35%, cost=350
        self.assertAlmostEqual(a.total_cost_usd, 350.0)

    def test_total_cost_pct_correct(self):
        c = self.pool(exit_penalty_pct=0.0, chain="ethereum")
        cd = self.pool(apy=8.0, chain="ethereum")
        a = self.analyze(c, cd)
        self.assertAlmostEqual(a.total_cost_pct, 0.20)

    def test_total_cost_usd_zero_position(self):
        c = self.pool()
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=0)
        self.assertAlmostEqual(a.total_cost_usd, 0.0)


class TestIsLocked(_Base):
    def test_locked_both_conditions(self):
        c = self.pool(lock_period_days=30, exit_penalty_pct=2.0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertTrue(a.is_locked)

    def test_not_locked_zero_lock_period(self):
        c = self.pool(lock_period_days=0, exit_penalty_pct=2.0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertFalse(a.is_locked)

    def test_not_locked_zero_penalty(self):
        c = self.pool(lock_period_days=30, exit_penalty_pct=0.0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertFalse(a.is_locked)

    def test_not_locked_both_zero(self):
        c = self.pool(lock_period_days=0, exit_penalty_pct=0.0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertFalse(a.is_locked)


class TestBreakevenDays(_Base):
    def test_breakeven_infinite_when_no_gain(self):
        c = self.pool(apy=5.0)
        cd = self.pool(apy=5.0)
        a = self.analyze(c, cd)
        self.assertEqual(a.breakeven_days, float("inf"))

    def test_breakeven_infinite_when_negative_gain(self):
        c = self.pool(apy=8.0)
        cd = self.pool(apy=3.0)
        a = self.analyze(c, cd)
        self.assertEqual(a.breakeven_days, float("inf"))

    def test_breakeven_formula(self):
        # cost = 0.2%, gain = 1%, breakeven = 0.2/1 * 365 = 73 days
        c = self.pool(apy=4.0, exit_penalty_pct=0.0, chain="ethereum")
        cd = self.pool(apy=5.0, chain="ethereum")
        a = self.analyze(c, cd)
        expected = (0.20 / 1.0) * 365
        self.assertAlmostEqual(a.breakeven_days, expected, places=3)

    def test_breakeven_fast(self):
        # cost = 0.2%, gain = 5% → breakeven = 14.6 days
        c = self.pool(apy=1.0, exit_penalty_pct=0.0, chain="ethereum")
        cd = self.pool(apy=6.0, chain="ethereum")
        a = self.analyze(c, cd)
        expected = (0.20 / 5.0) * 365
        self.assertAlmostEqual(a.breakeven_days, expected, places=3)

    def test_breakeven_cross_chain(self):
        # cost = 0.35%, gain = 2% → breakeven = 63.875 days
        c = self.pool(apy=3.0, exit_penalty_pct=0.0, chain="ethereum")
        cd = self.pool(apy=5.0, chain="arbitrum")
        a = self.analyze(c, cd)
        expected = (0.35 / 2.0) * 365
        self.assertAlmostEqual(a.breakeven_days, expected, places=3)


class TestCanExit(_Base):
    def test_can_exit_exact_90_pct(self):
        c = self.pool(liquidity_depth_usd=45_000)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=50_000)
        # 45000 >= 50000 * 0.9 = 45000 → True
        self.assertTrue(a.can_exit)

    def test_can_exit_above_90_pct(self):
        c = self.pool(liquidity_depth_usd=100_000)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertTrue(a.can_exit)

    def test_cannot_exit_below_90_pct(self):
        c = self.pool(liquidity_depth_usd=44_999)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertFalse(a.can_exit)

    def test_cannot_exit_zero_liquidity(self):
        c = self.pool(liquidity_depth_usd=0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertFalse(a.can_exit)


class TestRecommendation(_Base):
    def test_stay_when_no_gain(self):
        c = self.pool(apy=6.0)
        cd = self.pool(apy=5.0)
        a = self.analyze(c, cd)
        self.assertEqual(a.recommendation, "STAY")

    def test_stay_when_zero_gain(self):
        c = self.pool(apy=5.0)
        cd = self.pool(apy=5.0)
        a = self.analyze(c, cd)
        self.assertEqual(a.recommendation, "STAY")

    def test_monitor_when_cannot_exit(self):
        c = self.pool(apy=3.0, liquidity_depth_usd=0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertEqual(a.recommendation, "MONITOR")

    def test_wait_for_unlock_when_locked(self):
        c = self.pool(apy=3.0, lock_period_days=30, exit_penalty_pct=5.0,
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertEqual(a.recommendation, "WAIT_FOR_UNLOCK")

    def test_migrate_now_fast_breakeven(self):
        # gain = 10%, cost = 0.2% → breakeven = 7.3 days < 30
        # risk_adjusted_gain = 10 / (1 + 10/100) = 9.09 > 1
        c = self.pool(apy=0.0, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=10.0, chain="ethereum", risk_score=10.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertEqual(a.recommendation, "MIGRATE_NOW")

    def test_monitor_when_breakeven_under_90(self):
        # gain = 1%, cost = 0.2% → breakeven = 73 days; risk_adjusted_gain ~ 0.909 < 1
        c = self.pool(apy=4.0, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=5.0, chain="ethereum", risk_score=10.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertEqual(a.recommendation, "MONITOR")

    def test_stay_when_breakeven_over_90_and_low_gain(self):
        # gain = 0.5%, cost = 0.2% → breakeven = 146 days; risk_adjusted=0.45 < 1
        c = self.pool(apy=4.5, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=5.0, chain="ethereum", risk_score=10.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertEqual(a.recommendation, "STAY")


class TestConfidence(_Base):
    def test_confidence_high_very_fast_breakeven(self):
        # gain = 10%, breakeven < 14 days → HIGH
        c = self.pool(apy=0.0, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=10.0, chain="ethereum", risk_score=10.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertEqual(a.confidence, "HIGH")
        # Verify breakeven is < 14
        self.assertLess(a.breakeven_days, 14)

    def test_confidence_medium_migrate_now_slower(self):
        # breakeven = 14..29 days, gain > 1, MIGRATE_NOW → MEDIUM
        # gain = 2.8%, cost = 0.2% → breakeven = 26.07 days
        c = self.pool(apy=0.0, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=2.8, chain="ethereum", risk_score=0.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertEqual(a.recommendation, "MIGRATE_NOW")
        self.assertEqual(a.confidence, "MEDIUM")

    def test_confidence_low_for_stay(self):
        c = self.pool(apy=6.0)
        cd = self.pool(apy=5.0)
        a = self.analyze(c, cd)
        self.assertEqual(a.confidence, "LOW")

    def test_confidence_low_for_monitor(self):
        c = self.pool(apy=3.0, liquidity_depth_usd=0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertEqual(a.confidence, "LOW")

    def test_confidence_low_for_wait_unlock(self):
        c = self.pool(apy=3.0, lock_period_days=30, exit_penalty_pct=5.0,
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertEqual(a.confidence, "LOW")


class TestReasons(_Base):
    def test_reasons_non_empty_stay(self):
        c = self.pool(apy=6.0)
        cd = self.pool(apy=3.0)
        a = self.analyze(c, cd)
        self.assertGreater(len(a.reasons), 0)

    def test_reasons_non_empty_monitor(self):
        c = self.pool(apy=3.0, liquidity_depth_usd=0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertGreater(len(a.reasons), 0)

    def test_reasons_non_empty_migrate_now(self):
        c = self.pool(apy=0.0, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=10.0, chain="ethereum", risk_score=10.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertGreater(len(a.reasons), 0)

    def test_reasons_non_empty_wait_for_unlock(self):
        c = self.pool(apy=3.0, lock_period_days=30, exit_penalty_pct=5.0,
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertGreater(len(a.reasons), 0)

    def test_reasons_at_least_two(self):
        c = self.pool(apy=0.0, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=10.0, chain="ethereum", risk_score=10.0)
        a = self.analyze(c, cd, position_usd=50_000)
        self.assertGreaterEqual(len(a.reasons), 2)


class TestWarnings(_Base):
    def test_warning_significant_risk_increase(self):
        c = self.pool(risk_score=10.0)
        cd = self.pool(apy=8.0, risk_score=31.0)  # 31 > 10 + 20
        a = self.analyze(c, cd)
        self.assertTrue(any("risk" in w.lower() for w in a.warnings))

    def test_no_warning_small_risk_increase(self):
        c = self.pool(risk_score=10.0)
        cd = self.pool(apy=8.0, risk_score=29.0)  # only 19 pts above
        a = self.analyze(c, cd)
        risk_warns = [w for w in a.warnings if "risk" in w.lower() and "significant" in w.lower()]
        self.assertEqual(len(risk_warns), 0)

    def test_warning_very_long_breakeven(self):
        # gain tiny → breakeven > 180 days
        c = self.pool(apy=4.9, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=5.0, chain="ethereum")
        a = self.analyze(c, cd)
        self.assertTrue(any("breakeven" in w.lower() or "long" in w.lower() for w in a.warnings))

    def test_warning_low_tvl(self):
        c = self.pool()
        cd = self.pool(apy=8.0, tvl_usd=500_000)  # < 1M
        a = self.analyze(c, cd)
        self.assertTrue(any("tvl" in w.lower() or "low" in w.lower() for w in a.warnings))

    def test_no_warning_high_tvl(self):
        c = self.pool()
        cd = self.pool(apy=8.0, tvl_usd=5_000_000)  # >= 1M
        a = self.analyze(c, cd)
        tvl_warns = [w for w in a.warnings if "tvl" in w.lower()]
        self.assertEqual(len(tvl_warns), 0)

    def test_multiple_warnings(self):
        c = self.pool(risk_score=10.0, apy=4.9, exit_penalty_pct=0.0, chain="ethereum",
                      liquidity_depth_usd=1_000_000)
        cd = self.pool(apy=5.0, risk_score=50.0, tvl_usd=500_000, chain="ethereum")
        a = self.analyze(c, cd)
        # Should have at least 2 warnings: risk + tvl (breakeven might also trigger)
        self.assertGreaterEqual(len(a.warnings), 2)


class TestRankCandidates(_Base):
    def test_rank_by_risk_adjusted_gain(self):
        c = self.pool(apy=3.0)
        cands = [
            self.pool(apy=5.0, risk_score=0.0, name="C1"),    # gain=2, ra=2
            self.pool(apy=8.0, risk_score=100.0, name="C2"),  # gain=5, ra=2.5
            self.pool(apy=6.0, risk_score=20.0, name="C3"),   # gain=3, ra=2.5
        ]
        results = self.mod.rank_candidates(c, cands, 50_000)
        self.assertEqual(len(results), 3)
        # First should have highest risk_adjusted_gain
        gains = [r[0].risk_adjusted_gain for r in results]
        self.assertEqual(gains, sorted(gains, reverse=True))

    def test_rank_returns_pairs(self):
        c = self.pool(apy=3.0)
        cands = [self.pool(apy=5.0, name="C1"), self.pool(apy=8.0, name="C2")]
        results = self.mod.rank_candidates(c, cands, 50_000)
        for analysis, cand in results:
            self.assertIsInstance(analysis, self.mod.MigrationAnalysis)
            self.assertIsInstance(cand, self.mod.PoolProfile)

    def test_rank_empty_candidates(self):
        c = self.pool(apy=3.0)
        results = self.mod.rank_candidates(c, [], 50_000)
        self.assertEqual(results, [])

    def test_rank_single_candidate(self):
        c = self.pool(apy=3.0)
        cands = [self.pool(apy=6.0, name="C1")]
        results = self.mod.rank_candidates(c, cands, 50_000)
        self.assertEqual(len(results), 1)

    def test_rank_best_first(self):
        c = self.pool(apy=0.0)
        # First candidate: gain=1, ra=1/(1+0.5)=0.666..
        # Second candidate: gain=5, ra=5/(1+0.1)=4.54..
        cands = [
            self.pool(apy=1.0, risk_score=50.0, name="Worse"),
            self.pool(apy=5.0, risk_score=10.0, name="Better"),
        ]
        results = self.mod.rank_candidates(c, cands, 50_000)
        self.assertEqual(results[0][1].name, "Better")


class TestSaveLoad(_Base):
    def test_save_creates_file(self):
        a = self.analyze()
        self.mod.save_results(a)
        self.assertTrue(os.path.exists(self.mod._LOG_FILE))

    def test_save_sets_saved_to(self):
        a = self.analyze()
        self.mod.save_results(a)
        self.assertEqual(a.saved_to, self.mod._LOG_FILE)

    def test_load_returns_list(self):
        history = self.mod.load_history()
        self.assertIsInstance(history, list)

    def test_load_empty_initially(self):
        history = self.mod.load_history()
        self.assertEqual(history, [])

    def test_round_trip(self):
        a = self.analyze()
        self.mod.save_results(a)
        history = self.mod.load_history()
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertIn("recommendation", entry)
        self.assertIn("confidence", entry)
        self.assertIn("current", entry)
        self.assertIn("candidate", entry)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            a = self.analyze()
            self.mod.save_results(a)
        history = self.mod.load_history()
        self.assertEqual(len(history), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(115):
            a = self.analyze()
            self.mod.save_results(a)
        history = self.mod.load_history()
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_latest(self):
        # Save 101 entries with distinct position_usd values
        for i in range(101):
            c = self.pool(apy=3.0)
            cd = self.pool(apy=6.0, name=f"C{i}")
            a = self.mod.analyze(c, cd, float(i))
            self.mod.save_results(a)
        history = self.mod.load_history()
        self.assertEqual(len(history), 100)
        # Last saved position_usd was 100 → should be in history
        last = history[-1]
        self.assertAlmostEqual(last["position_usd"], 100.0)

    def test_load_returns_empty_on_missing_file(self):
        # Ensure no log file exists
        if os.path.exists(self.mod._LOG_FILE):
            os.remove(self.mod._LOG_FILE)
        self.assertEqual(self.mod.load_history(), [])

    def test_load_returns_empty_on_corrupt_file(self):
        with open(self.mod._LOG_FILE, "w") as fh:
            fh.write("not valid json")
        self.assertEqual(self.mod.load_history(), [])

    def test_atomic_write(self):
        """Ensure no temp file is left after save."""
        a = self.analyze()
        self.mod.save_results(a)
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_breakeven_inf_serialised_as_none(self):
        """Infinite breakeven should be serialised as None (JSON-safe)."""
        c = self.pool(apy=6.0)
        cd = self.pool(apy=3.0)  # negative gain → inf breakeven
        a = self.mod.analyze(c, cd, 50_000)
        self.mod.save_results(a)
        history = self.mod.load_history()
        self.assertIsNone(history[-1]["breakeven_days"])


class TestEdgeCases(_Base):
    def test_position_usd_zero(self):
        c = self.pool(apy=3.0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd, position_usd=0)
        self.assertAlmostEqual(a.total_cost_usd, 0.0)
        # can_exit: 0 >= 0 * 0.9 = 0 → True
        self.assertTrue(a.can_exit)

    def test_both_same_chain(self):
        c = self.pool(chain="ethereum")
        cd = self.pool(apy=8.0, chain="ethereum")
        a = self.analyze(c, cd)
        self.assertAlmostEqual(a.entry_cost_pct, 0.10)

    def test_recommendation_is_string(self):
        a = self.analyze()
        self.assertIsInstance(a.recommendation, str)

    def test_reasons_are_list_of_strings(self):
        a = self.analyze()
        self.assertIsInstance(a.reasons, list)
        for r in a.reasons:
            self.assertIsInstance(r, str)

    def test_warnings_are_list_of_strings(self):
        a = self.analyze()
        self.assertIsInstance(a.warnings, list)
        for w in a.warnings:
            self.assertIsInstance(w, str)

    def test_is_locked_false_with_only_lock_period(self):
        c = self.pool(lock_period_days=30, exit_penalty_pct=0.0)
        cd = self.pool(apy=8.0)
        a = self.analyze(c, cd)
        self.assertFalse(a.is_locked)


if __name__ == "__main__":
    unittest.main()
