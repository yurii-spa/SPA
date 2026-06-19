"""
tests/test_s20_anticrisis_research.py — Unit tests for RS-001 Anti-Crisis (S20)

Covers:
  - RESEARCH_ONLY flag
  - Module-level constants
  - AntiCrisisResearchStrategy.allocate()
  - AntiCrisisResearchStrategy.blended_apy()
  - AntiCrisisResearchStrategy.strict_eligible_fraction()
  - AntiCrisisResearchStrategy.research_exclusion_report()
  - AntiCrisisResearchStrategy.risk_warning()
  - AntiCrisisResearchStrategy.to_dict()
  - RS001ShadowTracker ring-buffer, atomic writes, compute(), record()
  - Edge cases: zero capital, negative capital, None live_apy, negative APY

Usage:
    python3 -m unittest tests/test_s20_anticrisis_research.py -v

Date: 2026-06-19 (MP-1302, Sprint v9.18)
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategies.s20_anticrisis_research import (
    RESEARCH_ONLY,
    RESEARCH_WEIGHTS,
    RESEARCH_EXCLUSION_REASONS,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY,
    AntiCrisisResearchStrategy,
)
from spa_core.analytics.strategy_rs001_tracker import (
    RING_BUFFER_CAP,
    RS001ShadowTracker,
)


# ─── Helper ────────────────────────────────────────────────────────────────────

def _make_tracker(tmpdir: str) -> RS001ShadowTracker:
    """Create a tracker pointing to a fresh temporary directory."""
    return RS001ShadowTracker(data_dir=tmpdir)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Module-level constants
# ══════════════════════════════════════════════════════════════════════════════

class TestModuleConstants(unittest.TestCase):
    """Tests for module-level constants in s20_anticrisis_research."""

    def test_research_only_is_true(self):
        """RESEARCH_ONLY must be True — hard-coded, never override."""
        self.assertTrue(RESEARCH_ONLY)

    def test_research_only_is_bool(self):
        """RESEARCH_ONLY must be exactly bool True, not just truthy."""
        self.assertIs(RESEARCH_ONLY, True)

    def test_strategy_id(self):
        """STRATEGY_ID must be 'S20'."""
        self.assertEqual(STRATEGY_ID, "S20")

    def test_strategy_name_contains_rs001(self):
        """STRATEGY_NAME must reference RS-001."""
        self.assertIn("RS-001", STRATEGY_NAME)

    def test_target_apy(self):
        """TARGET_APY must be 18.2."""
        self.assertAlmostEqual(TARGET_APY, 18.2, places=5)

    def test_research_weights_has_six_slots(self):
        """RESEARCH_WEIGHTS must define exactly 6 allocation slots."""
        self.assertEqual(len(RESEARCH_WEIGHTS), 6)

    def test_research_weights_keys_expected(self):
        """RESEARCH_WEIGHTS must contain all expected slot keys."""
        expected = {
            "gmx_btc_exposure",
            "gmx_eth_exposure",
            "btc_stable_pool",
            "eth_aggressive_pool",
            "gold_proxy",
            "stablecoin_t1",
        }
        self.assertEqual(set(RESEARCH_WEIGHTS.keys()), expected)

    def test_research_weights_sum_to_one(self):
        """All weights in RESEARCH_WEIGHTS must sum to 1.0."""
        total = sum(v["weight"] for v in RESEARCH_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_exclusion_reasons_count(self):
        """RESEARCH_EXCLUSION_REASONS must contain exactly 5 excluded sources."""
        self.assertEqual(len(RESEARCH_EXCLUSION_REASONS), 5)

    def test_stablecoin_not_excluded(self):
        """stablecoin_t1 must NOT appear in RESEARCH_EXCLUSION_REASONS."""
        self.assertNotIn("stablecoin_t1", RESEARCH_EXCLUSION_REASONS)


# ══════════════════════════════════════════════════════════════════════════════
# 2. AntiCrisisResearchStrategy.allocate()
# ══════════════════════════════════════════════════════════════════════════════

class TestAllocate(unittest.TestCase):

    def setUp(self):
        self.strategy = AntiCrisisResearchStrategy()

    def test_allocate_returns_dict(self):
        result = self.strategy.allocate(50_000.0)
        self.assertIsInstance(result, dict)

    def test_allocate_contains_all_slots(self):
        result = self.strategy.allocate(50_000.0)
        for slot in RESEARCH_WEIGHTS:
            self.assertIn(slot, result)

    def test_allocate_weights_sum_to_one(self):
        result = self.strategy.allocate(50_000.0)
        total_weight = sum(result[s]["weight"] for s in RESEARCH_WEIGHTS)
        self.assertAlmostEqual(total_weight, 1.0, places=9)

    def test_allocate_amounts_sum_to_capital(self):
        capital = 100_000.0
        result = self.strategy.allocate(capital)
        total_alloc = sum(result[s]["amount"] for s in RESEARCH_WEIGHTS)
        self.assertAlmostEqual(total_alloc, capital, places=4)

    def test_allocate_zero_capital_returns_zero_amounts(self):
        result = self.strategy.allocate(0.0)
        for slot in RESEARCH_WEIGHTS:
            self.assertAlmostEqual(result[slot]["amount"], 0.0, places=9)

    def test_allocate_negative_capital_returns_zero_amounts(self):
        """Negative capital must produce zero allocations (no shorts)."""
        result = self.strategy.allocate(-10_000.0)
        for slot in RESEARCH_WEIGHTS:
            self.assertAlmostEqual(result[slot]["amount"], 0.0, places=9)

    def test_allocate_meta_key_present(self):
        result = self.strategy.allocate(50_000.0)
        self.assertIn("_meta", result)

    def test_allocate_meta_research_only_true(self):
        result = self.strategy.allocate(50_000.0)
        self.assertTrue(result["_meta"]["research_only"])

    def test_allocate_meta_strategy_id(self):
        result = self.strategy.allocate(50_000.0)
        self.assertEqual(result["_meta"]["strategy_id"], "S20")

    def test_allocate_meta_total_capital(self):
        result = self.strategy.allocate(75_000.0)
        self.assertAlmostEqual(result["_meta"]["total_capital"], 75_000.0)

    def test_allocate_with_live_apy_override(self):
        """live_apy dict should override stablecoin_t1 APY."""
        result = self.strategy.allocate(50_000.0, live_apy={"stablecoin_t1": 4.5})
        self.assertAlmostEqual(result["stablecoin_t1"]["apy"], 4.5, places=9)

    def test_allocate_slot_status_fields(self):
        """Each slot must have a 'status' field."""
        result = self.strategy.allocate(50_000.0)
        for slot in RESEARCH_WEIGHTS:
            self.assertIn("status", result[slot])

    def test_allocate_stablecoin_t1_weight(self):
        result = self.strategy.allocate(100_000.0)
        self.assertAlmostEqual(result["stablecoin_t1"]["weight"], 0.15, places=9)

    def test_allocate_btc_stable_pool_weight(self):
        result = self.strategy.allocate(100_000.0)
        self.assertAlmostEqual(result["btc_stable_pool"]["weight"], 0.35, places=9)


# ══════════════════════════════════════════════════════════════════════════════
# 3. AntiCrisisResearchStrategy.blended_apy()
# ══════════════════════════════════════════════════════════════════════════════

class TestBlendedApy(unittest.TestCase):

    def setUp(self):
        self.strategy = AntiCrisisResearchStrategy()

    def test_blended_apy_with_none_uses_placeholders(self):
        """blended_apy(None) must use placeholder APYs → ~18.2%."""
        result = self.strategy.blended_apy(None)
        self.assertAlmostEqual(result, 18.2, places=4)

    def test_blended_apy_default_approx_target(self):
        """Default blended_apy() must approximate TARGET_APY 18.2%."""
        result = self.strategy.blended_apy()
        self.assertAlmostEqual(result, TARGET_APY, places=4)

    def test_blended_apy_returns_float(self):
        result = self.strategy.blended_apy()
        self.assertIsInstance(result, float)

    def test_blended_apy_with_live_override_stablecoin(self):
        """Providing a live stablecoin APY changes blended result."""
        base = self.strategy.blended_apy()
        result = self.strategy.blended_apy({"stablecoin_t1": 10.0})
        # 10.0 * 0.15 replaces 3.0 * 0.15 → base + (10-3)*0.15 = base + 1.05
        self.assertAlmostEqual(result, base + (10.0 - 3.0) * 0.15, places=4)

    def test_blended_apy_mathematical_correctness(self):
        """Manual weighted sum must match blended_apy()."""
        expected = (
            0.20 * 15.0 +   # gmx_btc
            0.10 * 15.0 +   # gmx_eth
            0.35 * 25.0 +   # btc_stable_pool
            0.05 * 45.0 +   # eth_aggressive_pool
            0.15 * 15.0 +   # gold_proxy
            0.15 *  3.0     # stablecoin_t1
        )
        result = self.strategy.blended_apy()
        self.assertAlmostEqual(result, expected, places=4)

    def test_blended_apy_with_all_overrides(self):
        """If every slot is overridden to 0.0, blended_apy must be 0.0."""
        overrides = {slot: 0.0 for slot in RESEARCH_WEIGHTS}
        result = self.strategy.blended_apy(overrides)
        self.assertAlmostEqual(result, 0.0, places=9)

    def test_blended_apy_negative_override_allowed(self):
        """Negative APY override should propagate to result (no clamp)."""
        overrides = {slot: -5.0 for slot in RESEARCH_WEIGHTS}
        result = self.strategy.blended_apy(overrides)
        self.assertLess(result, 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 4. strict_eligible_fraction()
# ══════════════════════════════════════════════════════════════════════════════

class TestStrictEligibleFraction(unittest.TestCase):

    def setUp(self):
        self.strategy = AntiCrisisResearchStrategy()

    def test_strict_eligible_fraction_value(self):
        """Must return exactly 0.15 (stablecoin_t1 weight)."""
        self.assertAlmostEqual(self.strategy.strict_eligible_fraction(), 0.15, places=9)

    def test_strict_eligible_fraction_type(self):
        result = self.strategy.strict_eligible_fraction()
        self.assertIsInstance(result, float)

    def test_strict_eligible_fraction_less_than_one(self):
        self.assertLess(self.strategy.strict_eligible_fraction(), 1.0)

    def test_strict_eligible_fraction_greater_than_zero(self):
        self.assertGreater(self.strategy.strict_eligible_fraction(), 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 5. research_exclusion_report()
# ══════════════════════════════════════════════════════════════════════════════

class TestResearchExclusionReport(unittest.TestCase):

    def setUp(self):
        self.strategy = AntiCrisisResearchStrategy()
        self.report = self.strategy.research_exclusion_report()

    def test_report_is_dict(self):
        self.assertIsInstance(self.report, dict)

    def test_report_excluded_count(self):
        """Must report exactly 5 excluded sources."""
        self.assertEqual(self.report["excluded_count"], 5)

    def test_report_eligible_count(self):
        """Must report exactly 1 eligible source (stablecoin_t1)."""
        self.assertEqual(self.report["eligible_count"], 1)

    def test_report_excluded_has_gmx_btc(self):
        self.assertIn("gmx_btc_exposure", self.report["excluded"])

    def test_report_excluded_has_gmx_eth(self):
        self.assertIn("gmx_eth_exposure", self.report["excluded"])

    def test_report_excluded_has_btc_pool(self):
        self.assertIn("btc_stable_pool", self.report["excluded"])

    def test_report_excluded_has_eth_agg(self):
        self.assertIn("eth_aggressive_pool", self.report["excluded"])

    def test_report_excluded_has_gold(self):
        self.assertIn("gold_proxy", self.report["excluded"])

    def test_report_eligible_has_stablecoin(self):
        self.assertIn("stablecoin_t1", self.report["eligible"])

    def test_report_excluded_entries_have_reason(self):
        for slot, info in self.report["excluded"].items():
            self.assertIn("reason", info)
            self.assertIsInstance(info["reason"], str)
            self.assertGreater(len(info["reason"]), 0)

    def test_report_methodology_field(self):
        self.assertIn("methodology", self.report)
        self.assertIsInstance(self.report["methodology"], str)


# ══════════════════════════════════════════════════════════════════════════════
# 6. risk_warning()
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskWarning(unittest.TestCase):

    def setUp(self):
        self.strategy = AntiCrisisResearchStrategy()

    def test_risk_warning_not_empty(self):
        warning = self.strategy.risk_warning()
        self.assertIsInstance(warning, str)
        self.assertGreater(len(warning), 0)

    def test_risk_warning_mentions_research(self):
        warning = self.strategy.risk_warning()
        self.assertIn("RESEARCH", warning.upper())

    def test_risk_warning_mentions_placeholder(self):
        warning = self.strategy.risk_warning()
        self.assertIn("placeholder", warning.lower())

    def test_risk_warning_mentions_capital(self):
        warning = self.strategy.risk_warning()
        self.assertTrue(
            "capital" in warning.lower() or "real" in warning.lower()
        )


# ══════════════════════════════════════════════════════════════════════════════
# 7. to_dict()
# ══════════════════════════════════════════════════════════════════════════════

class TestToDict(unittest.TestCase):

    def setUp(self):
        self.strategy = AntiCrisisResearchStrategy()
        self.d = self.strategy.to_dict()

    def test_to_dict_returns_dict(self):
        self.assertIsInstance(self.d, dict)

    def test_to_dict_strategy_id(self):
        self.assertEqual(self.d["strategy_id"], "S20")

    def test_to_dict_research_only(self):
        self.assertTrue(self.d["research_only"])

    def test_to_dict_has_risk_warning(self):
        self.assertIn("risk_warning", self.d)
        self.assertGreater(len(self.d["risk_warning"]), 0)

    def test_to_dict_has_exclusion_report(self):
        self.assertIn("exclusion_report", self.d)

    def test_to_dict_has_strict_eligible_fraction(self):
        self.assertIn("strict_eligible_fraction", self.d)
        self.assertAlmostEqual(self.d["strict_eligible_fraction"], 0.15, places=9)


# ══════════════════════════════════════════════════════════════════════════════
# 8. RS001ShadowTracker — ring-buffer, atomic writes
# ══════════════════════════════════════════════════════════════════════════════

class TestRS001ShadowTracker(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.tracker = _make_tracker(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_compute_returns_dict(self):
        entry = self.tracker.compute()
        self.assertIsInstance(entry, dict)

    def test_compute_entry_has_date(self):
        entry = self.tracker.compute()
        self.assertIn("date", entry)

    def test_compute_entry_has_blended_apy(self):
        entry = self.tracker.compute()
        self.assertIn("rs001_blended_apy", entry)

    def test_compute_entry_blended_apy_approx_18(self):
        entry = self.tracker.compute()
        self.assertAlmostEqual(entry["rs001_blended_apy"], 18.2, places=2)

    def test_compute_entry_has_daily_return(self):
        entry = self.tracker.compute()
        self.assertIn("rs001_daily_return", entry)

    def test_compute_entry_daily_return_positive(self):
        entry = self.tracker.compute()
        self.assertGreater(entry["rs001_daily_return"], 0.0)

    def test_compute_entry_has_strict_eligible_fraction(self):
        entry = self.tracker.compute()
        self.assertIn("strict_eligible_fraction", entry)
        self.assertAlmostEqual(entry["strict_eligible_fraction"], 0.15, places=4)

    def test_record_writes_file(self):
        data_file = Path(self._tmpdir) / "rs001_shadow.json"
        self.assertFalse(data_file.exists())
        self.tracker.record()
        self.assertTrue(data_file.exists())

    def test_record_file_valid_json(self):
        self.tracker.record()
        data_file = Path(self._tmpdir) / "rs001_shadow.json"
        with open(data_file, "r") as fh:
            data = json.load(fh)
        self.assertIn("entries", data)

    def test_record_appends_entries(self):
        self.tracker.record()
        entries = self.tracker.read_all()
        self.assertEqual(len(entries), 1)

    def test_ring_buffer_cap_enforced(self):
        """Ring-buffer must not exceed RING_BUFFER_CAP=100 entries."""
        # Insert 105 fake entries directly via _save
        fake_entries = [
            {"date": f"2026-01-{i:02d}", "capital_hypothetical": 50000.0}
            for i in range(1, 106)
        ]
        # _trim them to cap
        trimmed = RS001ShadowTracker._trim(fake_entries, RING_BUFFER_CAP)
        self.assertEqual(len(trimmed), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_most_recent(self):
        """After trimming 105→100, newest entries must survive."""
        fake_entries = [
            {"date": f"2026-01-{i:02d}", "capital_hypothetical": float(i)}
            for i in range(1, 106)
        ]
        trimmed = RS001ShadowTracker._trim(fake_entries, RING_BUFFER_CAP)
        # Last entry should be the newest (index 104 → capital 105.0)
        self.assertAlmostEqual(trimmed[-1]["capital_hypothetical"], 105.0)

    def test_ring_buffer_cap_constant(self):
        """RING_BUFFER_CAP must be 100."""
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_summary_returns_dict(self):
        summary = self.tracker.summary()
        self.assertIsInstance(summary, dict)

    def test_summary_empty_when_no_data(self):
        summary = self.tracker.summary()
        self.assertEqual(summary["entry_count"], 0)
        self.assertIsNone(summary["latest_entry"])

    def test_summary_after_record(self):
        self.tracker.record()
        summary = self.tracker.summary()
        self.assertEqual(summary["entry_count"], 1)
        self.assertIsNotNone(summary["latest_entry"])

    def test_idempotent_same_day_record(self):
        """Recording twice on the same date must not create duplicate entries."""
        self.tracker.record()
        self.tracker.record()
        entries = self.tracker.read_all()
        # Same date → only one entry
        dates = [e["date"] for e in entries]
        self.assertEqual(len(dates), len(set(dates)))

    def test_capital_compounds_across_days(self):
        """Second record (different date) must use previous capital as base."""
        # First record
        entry1 = self.tracker.record()
        capital_after_day1 = entry1["capital_hypothetical"]
        # Inject a second entry with a different date by manipulating internal data
        entries = self.tracker.read_all()
        entries[-1]["date"] = "2020-01-01"  # make it look like yesterday
        entries[-1]["capital_hypothetical"] = capital_after_day1
        self.tracker._save(entries)
        # Second record — should compound from capital_after_day1
        entry2 = self.tracker.record()
        self.assertAlmostEqual(
            entry2["capital_hypothetical"],
            capital_after_day1 * (1 + entry2["rs001_daily_return"]),
            places=2,
        )

    def test_read_all_returns_list(self):
        result = self.tracker.read_all()
        self.assertIsInstance(result, list)

    def test_read_all_empty_before_record(self):
        result = self.tracker.read_all()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
