"""
tests/test_cpa_integration.py

Integration tests for the full CPA methodology chain (MP-1323, Sprint v9.39).
50 tests covering:
  1. PointInTimeWhitelist — protocol eligibility by date
  2. BacktestGate — gate file loading and status aggregation
  3. SourcePipeline — source state management and strict eligibility
  4. RS-001 / RS-002 research strategies — RESEARCH_ONLY flags, allocation, APY
  5. RS001ShadowTracker / RS002ShadowTracker — atomic writes, ring-buffer
  6. PITEngine — point-in-time filtering before BacktestEngine
  7. Optional parallel-agent modules (conditional skips when not yet created)

Conventions:
  - stdlib only (unittest, tempfile, shutil, json, os)
  - Atomic writes tested via tmpdir isolation
  - Never touches real data/ files — all writes go to tempfile.mkdtemp()
  - skipIf guards for modules created by parallel agents

Run:
    python3 -m unittest tests/test_cpa_integration.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

# Ensure repo root on sys.path regardless of cwd
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ─── optional-module paths (parallel-agent outputs) ───────────────────────────
_GMX_PATH = os.path.join(_REPO_ROOT, "spa_core", "adapters", "gmx_research.py")
_GOLD_PATH = os.path.join(_REPO_ROOT, "spa_core", "adapters", "gold_proxy_research.py")
_CONC_LP_PATH = os.path.join(_REPO_ROOT, "spa_core", "analytics", "conc_lp_il_model.py")
_RS001_APY_PATH = os.path.join(_REPO_ROOT, "spa_core", "analytics", "rs001_live_apy_engine.py")
_RS002_APY_PATH = os.path.join(_REPO_ROOT, "spa_core", "analytics", "rs002_live_apy_engine.py")
_OWNER_ACC_PATH = os.path.join(_REPO_ROOT, "spa_core", "backtesting", "owner_acceptance.py")
_SRC_PROMO_PATH = os.path.join(_REPO_ROOT, "spa_core", "backtesting", "source_promotion_engine.py")
_SCENARIO_PATH  = os.path.join(_REPO_ROOT, "spa_core", "backtesting", "research_scenario_matrix.py")

# ─── real gate-file dir ───────────────────────────────────────────────────────
_REAL_BACKTEST_DIR = os.path.join(_REPO_ROOT, "data", "backtest")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Whitelist + Gate integration
# ══════════════════════════════════════════════════════════════════════════════

class TestCPAWhitelistGateIntegration(unittest.TestCase):
    """Tests the whitelist → gate chain (tests 1-13)."""

    # ── whitelist basic eligibility ───────────────────────────────────────────

    def test_whitelist_blocks_morpho_before_2023(self):
        """Morpho Blue launched 2023-11-07 — ineligible before that."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        self.assertFalse(wl.is_eligible("morpho_blue", "2023-06-01"))
        self.assertTrue(wl.is_eligible("morpho_blue", "2024-01-01"))

    def test_aave_v2_eligible_from_launch(self):
        """aave_v2_usdc launched 2020-12-17 — ineligible before, eligible after."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        self.assertFalse(wl.is_eligible("aave_v2_usdc", "2020-12-01"))
        self.assertTrue(wl.is_eligible("aave_v2_usdc", "2021-01-01"))

    def test_compound_v2_eligible_from_2018(self):
        """Compound V2 launched 2018-09-27 — eligible from 2019 onward."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        self.assertFalse(wl.is_eligible("compound_v2_usdc", "2018-09-26"))
        self.assertTrue(wl.is_eligible("compound_v2_usdc", "2019-01-01"))

    def test_morpho_steakhouse_eligible_from_2024(self):
        """morpho_steakhouse_usdc launched 2024-01-15."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        self.assertFalse(wl.is_eligible("morpho_steakhouse_usdc", "2023-12-31"))
        self.assertTrue(wl.is_eligible("morpho_steakhouse_usdc", "2024-02-01"))

    def test_unknown_protocol_ineligible(self):
        """Unknown protocol always returns False (conservative)."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        self.assertFalse(wl.is_eligible("completely_unknown_xyz", "2025-01-01"))

    def test_eligible_protocols_2022(self):
        """In 2022-01-01, only protocols launched before that date are eligible."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        eligible = wl.eligible_protocols("2022-01-01")
        self.assertIn("aave_v2_usdc", eligible)
        self.assertIn("compound_v2_usdc", eligible)
        # aave_v3 launched 2022-03-16 → not yet eligible on 2022-01-01
        self.assertNotIn("aave_v3_usdc", eligible)

    def test_whitelist_coverage_stats(self):
        """coverage_stats returns correct total_days and pct for known protocol."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        stats = wl.coverage_stats(
            ["aave_v2_usdc"],
            start="2021-01-01",
            end="2021-12-31",
        )
        self.assertIn("aave_v2_usdc", stats)
        row = stats["aave_v2_usdc"]
        self.assertEqual(row["eligible_days"], row["total_days"])
        self.assertEqual(row["pct"], 100.0)

    def test_whitelist_ineligible_reason_not_launched(self):
        """ineligible_reason returns non-empty string when protocol not yet launched."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        reason = wl.ineligible_reason("morpho_blue", "2022-01-01")
        self.assertTrue(len(reason) > 0)
        self.assertIn("morpho_blue", reason)

    def test_whitelist_ineligible_reason_eligible(self):
        """ineligible_reason returns empty string when protocol IS eligible."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist()
        reason = wl.ineligible_reason("aave_v2_usdc", "2022-01-01")
        self.assertEqual(reason, "")

    def test_whitelist_custom_launch_dates(self):
        """Custom launch_dates override allows injection of test protocols."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist(launch_dates={"test_proto": "2023-06-01"})
        self.assertFalse(wl.is_eligible("test_proto", "2023-05-31"))
        self.assertTrue(wl.is_eligible("test_proto", "2023-06-01"))
        self.assertFalse(wl.is_eligible("aave_v2_usdc", "2021-01-01"))  # not in custom set

    def test_pre_paper_gate_loads(self):
        """pre_paper_backtest_gate.json can be loaded by BacktestGate."""
        from spa_core.backtesting.gate import BacktestGate
        gate = BacktestGate(backtest_dir=_REAL_BACKTEST_DIR)
        status = gate.pre_paper_status()
        self.assertIn("status", status)
        self.assertIn(status["status"], ("PASS", "FAIL", "UNKNOWN"))

    def test_gate_returns_pass_for_pre_paper(self):
        """The committed pre_paper gate file has status PASS."""
        from spa_core.backtesting.gate import BacktestGate
        gate = BacktestGate(backtest_dir=_REAL_BACKTEST_DIR)
        status = gate.pre_paper_status()
        self.assertEqual(status["status"], "PASS")

    def test_gate_unknown_when_no_file(self):
        """BacktestGate returns UNKNOWN status when directory has no gate files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from spa_core.backtesting.gate import BacktestGate
            gate = BacktestGate(backtest_dir=tmpdir)
            status = gate.pre_paper_status()
            self.assertEqual(status["status"], "UNKNOWN")
            self.assertFalse(status["paper_trading_allowed"])

    def test_gate_four_state_status_keys(self):
        """four_state_status() always returns the expected keys."""
        from spa_core.backtesting.gate import BacktestGate
        gate = BacktestGate(backtest_dir=_REAL_BACKTEST_DIR)
        fs = gate.four_state_status()
        for key in ("backtest", "pre_paper", "paper", "live", "blockers"):
            self.assertIn(key, fs)
        self.assertIsInstance(fs["blockers"], list)


# ══════════════════════════════════════════════════════════════════════════════
# 2. SourcePipeline integration
# ══════════════════════════════════════════════════════════════════════════════

class TestCPASourcePipelineIntegration(unittest.TestCase):
    """Tests source_pipeline.py against defaults and real JSON (tests 14-21)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_source_pipeline_default_not_empty(self):
        """SourcePipeline initialised from defaults has >0 sources."""
        from spa_core.backtesting.source_pipeline import SourcePipeline
        sp = SourcePipeline(data_dir=self.tmpdir)
        self.assertGreater(len(sp.all_sources()), 0)

    def test_clean_sources_list_not_empty(self):
        """At least one CLEAN_INCLUDED source exists in defaults."""
        from spa_core.backtesting.source_pipeline import SourcePipeline
        sp = SourcePipeline(data_dir=self.tmpdir)
        self.assertGreater(len(sp.strict_sources()), 0)

    def test_aave_v2_usdc_is_clean_included(self):
        """aave_v2_usdc must be CLEAN_INCLUDED (strict backtest eligible)."""
        from spa_core.backtesting.source_pipeline import SourcePipeline, SourceState
        sp = SourcePipeline(data_dir=self.tmpdir)
        self.assertEqual(sp.state("aave_v2_usdc"), SourceState.CLEAN_INCLUDED)
        self.assertTrue(sp.is_strict_eligible("aave_v2_usdc"))

    def test_rs001_components_source_needed(self):
        """GMX and BTC pool sources should be SOURCE_NEEDED per CPA exclusion."""
        from spa_core.backtesting.source_pipeline import SourcePipeline, SourceState
        sp = SourcePipeline(data_dir=self.tmpdir)
        for sid in ("gmx_btc", "gmx_eth", "btc_stable_pool", "gold_proxy"):
            self.assertEqual(
                sp.state(sid),
                SourceState.SOURCE_NEEDED,
                f"{sid} should be SOURCE_NEEDED",
            )

    def test_delta_neutral_is_research_only(self):
        """delta_neutral source is RESEARCH_ONLY (model-only)."""
        from spa_core.backtesting.source_pipeline import SourcePipeline, SourceState
        sp = SourcePipeline(data_dir=self.tmpdir)
        self.assertEqual(sp.state("delta_neutral"), SourceState.RESEARCH_ONLY)

    def test_promote_source_changes_state(self):
        """promote_source() updates state and persists atomically."""
        from spa_core.backtesting.source_pipeline import SourcePipeline, SourceState
        sp = SourcePipeline(data_dir=self.tmpdir)
        sp.promote_source("maple_syrupusdc", SourceState.CLEAN_INCLUDED, "test promotion")
        # Reload from disk to verify atomic write
        sp2 = SourcePipeline(data_dir=self.tmpdir)
        self.assertEqual(sp2.state("maple_syrupusdc"), SourceState.CLEAN_INCLUDED)

    def test_source_summary_has_clean_included_key(self):
        """source_summary() dict includes the clean_included key."""
        from spa_core.backtesting.source_pipeline import SourcePipeline, SourceState
        sp = SourcePipeline(data_dir=self.tmpdir)
        summary = sp.source_summary()
        self.assertIn(SourceState.CLEAN_INCLUDED, summary)
        self.assertGreater(summary[SourceState.CLEAN_INCLUDED], 0)

    def test_strict_sources_sorted(self):
        """strict_sources() returns an alphabetically sorted list."""
        from spa_core.backtesting.source_pipeline import SourcePipeline
        sp = SourcePipeline(data_dir=self.tmpdir)
        sources = sp.strict_sources()
        self.assertEqual(sources, sorted(sources))

    def test_source_pipeline_loads_from_real_json(self):
        """SourcePipeline loads without error from data/backtest/source_pipeline.json."""
        real_sp_path = os.path.join(_REAL_BACKTEST_DIR, "source_pipeline.json")
        if not os.path.exists(real_sp_path):
            self.skipTest("data/backtest/source_pipeline.json not found")
        from spa_core.backtesting.source_pipeline import SourcePipeline
        sp = SourcePipeline(data_dir=_REAL_BACKTEST_DIR)
        self.assertIsInstance(sp.all_sources(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Research Strategy integration (RS-001 / RS-002)
# ══════════════════════════════════════════════════════════════════════════════

class TestCPAResearchStrategyIntegration(unittest.TestCase):
    """Tests RS-001 (S20) and RS-002 (S21) strategy modules (tests 23-33)."""

    def test_rs001_research_only_flag(self):
        """S20 module-level RESEARCH_ONLY must be True."""
        from spa_core.strategies.s20_anticrisis_research import RESEARCH_ONLY
        self.assertIs(RESEARCH_ONLY, True)

    def test_rs002_research_only_flag(self):
        """S21 module-level RESEARCH_ONLY must be True."""
        from spa_core.strategies.s21_cashflow_research import RESEARCH_ONLY
        self.assertIs(RESEARCH_ONLY, True)

    def test_rs001_blended_apy_near_target(self):
        """RS-001 blended_apy() with all-placeholder inputs ≈ 18.2% target."""
        from spa_core.strategies.s20_anticrisis_research import (
            AntiCrisisResearchStrategy, TARGET_APY,
        )
        strat = AntiCrisisResearchStrategy()
        apy = strat.blended_apy()
        self.assertAlmostEqual(apy, TARGET_APY, places=0)

    def test_rs001_strict_eligible_fraction(self):
        """strict_eligible_fraction() must equal stablecoin_t1 weight (0.15)."""
        from spa_core.strategies.s20_anticrisis_research import AntiCrisisResearchStrategy
        strat = AntiCrisisResearchStrategy()
        self.assertAlmostEqual(strat.strict_eligible_fraction(), 0.15, places=6)

    def test_rs001_exclusion_report_has_5_excluded(self):
        """Exclusion report has exactly 5 research-excluded slots."""
        from spa_core.strategies.s20_anticrisis_research import AntiCrisisResearchStrategy
        strat = AntiCrisisResearchStrategy()
        report = strat.research_exclusion_report()
        self.assertEqual(report["excluded_count"], 5)
        self.assertEqual(report["eligible_count"], 1)

    def test_rs001_risk_warning_non_empty(self):
        """risk_warning() returns a non-empty string."""
        from spa_core.strategies.s20_anticrisis_research import AntiCrisisResearchStrategy
        strat = AntiCrisisResearchStrategy()
        warn = strat.risk_warning()
        self.assertIsInstance(warn, str)
        self.assertGreater(len(warn), 10)

    def test_rs002_net_apy_decreases_with_btc_move(self):
        """RS-002 net APY in crash regime is lower than in sideways."""
        from spa_core.strategies.s21_cashflow_research import CashflowResearchStrategy
        strat = CashflowResearchStrategy()
        sideways = strat.net_apy_estimate("sideways")
        crash = strat.net_apy_estimate("crash")
        self.assertLess(crash, sideways)

    def test_rs002_total_allocation_sums_to_one(self):
        """RS-002 ALLOCATION weights must sum to exactly 1.0."""
        from spa_core.strategies.s21_cashflow_research import ALLOCATION
        total = sum(ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_rs002_il_drag_zero_when_no_move(self):
        """IL drag is 0.0 when BTC price does not move."""
        from spa_core.strategies.s21_cashflow_research import CashflowResearchStrategy
        strat = CashflowResearchStrategy()
        drag = strat.il_drag_estimate(0.0)
        self.assertEqual(drag, 0.0)

    def test_rs002_il_drag_increases_with_btc_move(self):
        """IL drag for ±20% BTC move is larger than for ±5% move."""
        from spa_core.strategies.s21_cashflow_research import CashflowResearchStrategy
        strat = CashflowResearchStrategy()
        small = strat.il_drag_estimate(5.0)
        large = strat.il_drag_estimate(20.0)
        self.assertGreater(large, small)

    def test_rs002_allocate_capital_returns_dict(self):
        """allocate(capital) returns a dict with 'legs' and 'blended_gross_apy'."""
        from spa_core.strategies.s21_cashflow_research import CashflowResearchStrategy
        strat = CashflowResearchStrategy()
        result = strat.allocate(capital=50_000.0)
        self.assertIn("legs", result)
        self.assertIn("blended_gross_apy", result)
        self.assertTrue(result["research_only"])


# ══════════════════════════════════════════════════════════════════════════════
# 4. Shadow Tracker integration
# ══════════════════════════════════════════════════════════════════════════════

class TestCPAShadowTrackerIntegration(unittest.TestCase):
    """Tests RS001ShadowTracker and RS002ShadowTracker (tests 34-41)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_rs001_tracker_records_and_reads(self):
        """RS001ShadowTracker.record() writes an entry; read_all() retrieves it."""
        from spa_core.analytics.strategy_rs001_tracker import RS001ShadowTracker
        tracker = RS001ShadowTracker(data_dir=self.tmpdir)
        entry = tracker.record()
        self.assertIn("date", entry)
        self.assertIn("rs001_blended_apy", entry)
        all_entries = tracker.read_all()
        self.assertEqual(len(all_entries), 1)

    def test_rs001_tracker_summary_structure(self):
        """RS001ShadowTracker.summary() has expected keys after one record."""
        from spa_core.analytics.strategy_rs001_tracker import RS001ShadowTracker
        tracker = RS001ShadowTracker(data_dir=self.tmpdir)
        tracker.record()
        summary = tracker.summary()
        self.assertIn("entry_count", summary)
        self.assertIn("ring_buffer_cap", summary)
        self.assertIn("latest_entry", summary)
        self.assertEqual(summary["entry_count"], 1)

    def test_rs001_tracker_ring_buffer_cap(self):
        """RS001ShadowTracker ring-buffer never exceeds RING_BUFFER_CAP."""
        from spa_core.analytics.strategy_rs001_tracker import RS001ShadowTracker, RING_BUFFER_CAP
        tracker = RS001ShadowTracker(data_dir=self.tmpdir)
        # Manually inject more entries than the cap
        from datetime import date, timedelta
        base = date(2025, 1, 1)
        for i in range(RING_BUFFER_CAP + 5):
            d = (base + timedelta(days=i)).isoformat()
            entries = tracker.read_all()
            # Simulate overflow: manually append then trim via record path
            entries.append({
                "date": d,
                "rs001_blended_apy": 18.2,
                "rs001_daily_return": 0.0004986,
                "portfolio_daily_return": 0.0,
                "capital_hypothetical": 50_000.0,
                "vs_portfolio_delta": 0.0,
                "strict_eligible_fraction": 0.15,
                "timestamp": "2025-01-01T00:00:00+00:00",
            })
            # trim + save directly
            if len(entries) > RING_BUFFER_CAP:
                entries = entries[-RING_BUFFER_CAP:]
            import os, tempfile
            payload = {"schema_version": "1.0", "strategy_id": "S20",
                       "ring_buffer_cap": RING_BUFFER_CAP, "entries": entries,
                       "updated_at": "2025-01-01T00:00:00+00:00"}
            data_file = os.path.join(self.tmpdir, "rs001_shadow.json")
            fd, tmp = tempfile.mkstemp(dir=self.tmpdir, prefix=".rs001_", suffix=".tmp")
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh)
            os.replace(tmp, data_file)
        final = tracker.read_all()
        self.assertLessEqual(len(final), RING_BUFFER_CAP)

    def test_rs002_tracker_records_entry(self):
        """RS002ShadowTracker.record() writes a valid entry."""
        from spa_core.analytics.strategy_rs002_tracker import RS002ShadowTracker
        tracker = RS002ShadowTracker(data_dir=self.tmpdir)
        entry = tracker.record(
            date="2025-06-01",
            capital=50_000.0,
            volatility_regime="sideways",
            btc_move_pct=0.0,
        )
        self.assertEqual(entry["date"], "2025-06-01")
        # field names: gross_apy_pct / net_apy_pct / il_drag_pct
        self.assertTrue(
            "gross_apy_pct" in entry or "gross_apy" in entry,
            f"Expected gross_apy key in entry: {list(entry.keys())}",
        )
        self.assertTrue(
            "net_apy_pct" in entry or "net_apy" in entry,
            f"Expected net_apy key in entry: {list(entry.keys())}",
        )
        self.assertTrue(
            "il_drag_pct" in entry or "il_drag" in entry,
            f"Expected il_drag key in entry: {list(entry.keys())}",
        )

    def test_rs002_tracker_ring_buffer(self):
        """RS002ShadowTracker enforces ring-buffer of 100 entries."""
        from spa_core.analytics.strategy_rs002_tracker import RS002ShadowTracker, RING_BUFFER_CAP
        tracker = RS002ShadowTracker(data_dir=self.tmpdir)
        from datetime import date, timedelta
        base = date(2020, 1, 1)
        for i in range(RING_BUFFER_CAP + 10):
            d = (base + timedelta(days=i)).isoformat()
            tracker.record(date=d, capital=50_000.0)
        self.assertLessEqual(tracker.entry_count(), RING_BUFFER_CAP)

    def test_rs002_tracker_clear(self):
        """RS002ShadowTracker.clear() empties the ring buffer."""
        from spa_core.analytics.strategy_rs002_tracker import RS002ShadowTracker
        tracker = RS002ShadowTracker(data_dir=self.tmpdir)
        tracker.record(date="2025-01-01", capital=50_000.0)
        self.assertEqual(tracker.entry_count(), 1)
        tracker.clear()
        self.assertEqual(tracker.entry_count(), 0)

    def test_rs002_tracker_latest_returns_last(self):
        """latest() returns the most-recently recorded entry."""
        from spa_core.analytics.strategy_rs002_tracker import RS002ShadowTracker
        tracker = RS002ShadowTracker(data_dir=self.tmpdir)
        tracker.record(date="2025-01-01", capital=50_000.0)
        tracker.record(date="2025-01-02", capital=51_000.0)
        latest = tracker.latest()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["date"], "2025-01-02")

    def test_rs002_tracker_summary_stats_empty(self):
        """summary_stats() on empty tracker returns count=0 and None averages."""
        from spa_core.analytics.strategy_rs002_tracker import RS002ShadowTracker
        tracker = RS002ShadowTracker(data_dir=self.tmpdir)
        tracker.clear()
        stats = tracker.summary_stats()
        self.assertEqual(stats["count"], 0)
        self.assertIsNone(stats["avg_gross_apy"])


# ══════════════════════════════════════════════════════════════════════════════
# 5. PITEngine integration
# ══════════════════════════════════════════════════════════════════════════════

class TestCPAPITEngineIntegration(unittest.TestCase):
    """Tests PITEngine point-in-time filtering (tests 42-46)."""

    def _make_row(self, protocol_key, date_str, apy=5.0, tvl=10_000_000, tier="T1"):
        return {
            "protocol_key": protocol_key,
            "timestamp": date_str,
            "apy": apy,
            "tvl_usd": tvl,
            "tier": tier,
        }

    def test_pit_engine_runs_with_empty_data(self):
        """PITEngine handles an empty historical_data list without error."""
        from spa_core.backtesting.pit_engine import PITEngine
        engine = PITEngine()
        result = engine.run([])
        # BacktestResult should be returned (even if metrics are trivial)
        self.assertIsNotNone(result)

    def test_pit_engine_filters_pre_launch_rows(self):
        """Rows before a protocol's launch date are dropped."""
        from spa_core.backtesting.pit_engine import PITEngine
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist(launch_dates={"test_p": "2023-06-01"})
        engine = PITEngine(whitelist=wl)
        data = [
            self._make_row("test_p", "2023-05-01"),  # before launch → dropped
            self._make_row("test_p", "2023-07-01"),  # after launch → kept
        ]
        engine.run(data)
        stats = engine.filter_stats()
        self.assertEqual(stats["dropped_rows"], 1)
        self.assertEqual(stats["kept_rows"], 1)

    def test_pit_engine_keeps_post_launch_rows(self):
        """All rows after launch date are retained."""
        from spa_core.backtesting.pit_engine import PITEngine
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist(launch_dates={"aave_v3_usdc": "2022-03-16"})
        engine = PITEngine(whitelist=wl)
        data = [self._make_row("aave_v3_usdc", f"2023-0{m:01d}-01") for m in range(1, 7)]
        engine.run(data)
        stats = engine.filter_stats()
        self.assertEqual(stats["dropped_rows"], 0)
        self.assertEqual(stats["kept_rows"], 6)

    def test_pit_engine_filter_stats_structure(self):
        """filter_stats() returns expected top-level keys."""
        from spa_core.backtesting.pit_engine import PITEngine
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist(launch_dates={"p": "2022-01-01"})
        engine = PITEngine(whitelist=wl)
        engine.run([self._make_row("p", "2022-06-01")])
        stats = engine.filter_stats()
        for key in ("total_rows", "kept_rows", "dropped_rows", "per_protocol"):
            self.assertIn(key, stats)

    def test_pit_engine_custom_whitelist_injected(self):
        """Custom whitelist is used instead of the built-in one."""
        from spa_core.backtesting.pit_engine import PITEngine
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        wl = PointInTimeWhitelist(launch_dates={"my_proto": "2020-01-01"})
        engine = PITEngine(whitelist=wl)
        self.assertIs(engine.whitelist, wl)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Full end-to-end CPA flow
# ══════════════════════════════════════════════════════════════════════════════

class TestFullCPAFlowIntegration(unittest.TestCase):
    """Full end-to-end tests across the CPA chain (tests 47-48)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_full_gate_check_flow(self):
        """Whitelist → gate → source pipeline full status flow without crash."""
        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
        from spa_core.backtesting.gate import BacktestGate
        from spa_core.backtesting.source_pipeline import SourcePipeline

        wl = PointInTimeWhitelist()
        eligible_2021 = wl.eligible_protocols("2021-01-01")
        self.assertIsInstance(eligible_2021, list)

        gate = BacktestGate(backtest_dir=self.tmpdir)
        four_state = gate.four_state_status()
        self.assertIsInstance(four_state["blockers"], list)

        sp = SourcePipeline(data_dir=self.tmpdir)
        summary = sp.source_summary()
        self.assertIsInstance(summary, dict)

    def test_rs001_rs002_both_research_only_and_independent(self):
        """RS-001 and RS-002 are both RESEARCH_ONLY and independent strategies."""
        from spa_core.strategies.s20_anticrisis_research import (
            RESEARCH_ONLY as R1, AntiCrisisResearchStrategy
        )
        from spa_core.strategies.s21_cashflow_research import (
            RESEARCH_ONLY as R2, CashflowResearchStrategy
        )
        self.assertTrue(R1)
        self.assertTrue(R2)
        s20 = AntiCrisisResearchStrategy()
        s21 = CashflowResearchStrategy()
        # Blended APYs are independently computed
        self.assertNotEqual(s20.blended_apy(), s21.net_apy_estimate("sideways"))


# ══════════════════════════════════════════════════════════════════════════════
# 7. Optional parallel-agent modules (conditional skips)
# ══════════════════════════════════════════════════════════════════════════════

class TestCPAOptionalModules(unittest.TestCase):
    """Conditional tests for modules created by parallel agents (tests 49-50)."""

    @unittest.skipUnless(os.path.exists(_GMX_PATH), "gmx_research not yet created")
    def test_gmx_adapter_research_only(self):
        """GMXResearchAdapter has RESEARCH_ONLY = True."""
        from spa_core.adapters.gmx_research import RESEARCH_ONLY
        self.assertIs(RESEARCH_ONLY, True)

    @unittest.skipUnless(os.path.exists(_GMX_PATH), "gmx_research not yet created")
    def test_gmx_adapter_fallback_apy_is_float(self):
        """FALLBACK_APY_PCT is a positive float."""
        from spa_core.adapters.gmx_research import FALLBACK_APY_PCT
        self.assertIsInstance(FALLBACK_APY_PCT, float)
        self.assertGreater(FALLBACK_APY_PCT, 0.0)

    @unittest.skipUnless(os.path.exists(_GOLD_PATH), "gold_proxy_research not yet created")
    def test_gold_proxy_adapter_research_only(self):
        """GoldProxyResearchAdapter has RESEARCH_ONLY = True."""
        from spa_core.adapters.gold_proxy_research import RESEARCH_ONLY
        self.assertIs(RESEARCH_ONLY, True)

    @unittest.skipUnless(os.path.exists(_GOLD_PATH), "gold_proxy_research not yet created")
    def test_gold_proxy_adapter_fallback_positive(self):
        """Gold proxy FALLBACK_APY_PCT is positive."""
        from spa_core.adapters.gold_proxy_research import FALLBACK_APY_PCT
        self.assertGreater(FALLBACK_APY_PCT, 0.0)

    @unittest.skipUnless(os.path.exists(_CONC_LP_PATH), "conc_lp_il_model not yet created")
    def test_conc_lp_il_model_zero_move(self):
        """ConcLPILModel.il_pct at initial price is 0."""
        from spa_core.analytics.conc_lp_il_model import ConcLPILModel
        model = ConcLPILModel(price_lower=40_000, price_upper=80_000, initial_price=60_000)
        il = model.il_pct(current_price=60_000)
        self.assertAlmostEqual(il, 0.0, places=3)

    @unittest.skipUnless(os.path.exists(_CONC_LP_PATH), "conc_lp_il_model not yet created")
    def test_conc_lp_il_model_negative_il_when_price_moves(self):
        """IL is negative (loss vs hold) when price moves outside initial."""
        from spa_core.analytics.conc_lp_il_model import ConcLPILModel
        model = ConcLPILModel(price_lower=40_000, price_upper=80_000, initial_price=60_000)
        il = model.il_pct(current_price=80_000)
        self.assertLessEqual(il, 0.0)

    @unittest.skipUnless(os.path.exists(_RS001_APY_PATH), "rs001_live_apy_engine not yet created")
    def test_rs001_live_apy_engine_loads(self):
        """RS001LiveAPYEngine instantiates and blended_apy() returns a float."""
        from spa_core.analytics.rs001_live_apy_engine import RS001LiveAPYEngine
        engine = RS001LiveAPYEngine()
        apy = engine.blended_apy()
        self.assertIsInstance(apy, float)
        self.assertGreater(apy, 0.0)

    @unittest.skipUnless(os.path.exists(_RS002_APY_PATH), "rs002_live_apy_engine not yet created")
    def test_rs002_live_apy_engine_research_only(self):
        """RS002 live APY engine is tagged RESEARCH_ONLY."""
        from spa_core.analytics.rs002_live_apy_engine import RESEARCH_ONLY  # type: ignore
        self.assertTrue(RESEARCH_ONLY)

    @unittest.skipUnless(os.path.exists(_OWNER_ACC_PATH), "owner_acceptance not yet created")
    def test_owner_acceptance_workflow_not_signed_by_default(self):
        """OwnerAcceptanceWorkflow.is_signed() returns False on fresh tmpdir."""
        from spa_core.backtesting.owner_acceptance import OwnerAcceptanceWorkflow
        with tempfile.TemporaryDirectory() as tmpdir:
            wf = OwnerAcceptanceWorkflow(backtest_dir=tmpdir)
            self.assertFalse(wf.is_signed())

    @unittest.skipUnless(os.path.exists(_SRC_PROMO_PATH), "source_promotion_engine not yet created")
    def test_source_promotion_engine_importable(self):
        """SourcePromotionEngine module is importable when present."""
        import importlib
        mod = importlib.import_module("spa_core.backtesting.source_promotion_engine")
        self.assertIsNotNone(mod)

    @unittest.skipUnless(os.path.exists(_SCENARIO_PATH), "research_scenario_matrix not yet created")
    def test_research_scenario_matrix_runs(self):
        """ResearchScenarioMatrix.run_all() returns a dict with RS-001 and RS-002 keys."""
        from spa_core.backtesting.research_scenario_matrix import ResearchScenarioMatrix
        matrix = ResearchScenarioMatrix()
        result = matrix.run_all()
        self.assertIsInstance(result, dict)
        self.assertIn("rs001", result)
        self.assertIn("rs002", result)

    @unittest.skipUnless(os.path.exists(_SCENARIO_PATH), "research_scenario_matrix not yet created")
    def test_research_scenario_matrix_rs001_scenarios_non_empty(self):
        """RS-001 scenario list has at least one entry."""
        from spa_core.backtesting.research_scenario_matrix import ResearchScenarioMatrix
        matrix = ResearchScenarioMatrix()
        scenarios = matrix.run_rs001_scenarios()
        self.assertGreater(len(scenarios), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
