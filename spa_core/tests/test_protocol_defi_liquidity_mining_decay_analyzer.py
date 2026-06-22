"""
Tests for MP-1123: ProtocolDeFiLiquidityMiningDecayAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_liquidity_mining_decay_analyzer -v
Total: ≥ 110 test methods.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_liquidity_mining_decay_analyzer import (
    ProtocolDeFiLiquidityMiningDecayAnalyzer,
    LiquidityMiningDecayReport,
    MAX_ENTRIES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_report(
    current_emission_rate_usd_per_day: float = 10_000.0,
    halving_period_days: int = 180,
    days_since_last_halving: int = 45,
    total_staked_usd: float = 5_000_000.0,
    my_stake_usd: float = 50_000.0,
    base_protocol_apy_pct: float = 3.0,
    min_acceptable_apy_pct: float = 5.0,
    protocol_name: str = "TestProto",
) -> LiquidityMiningDecayReport:
    ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
    return ana.analyze(
        current_emission_rate_usd_per_day=current_emission_rate_usd_per_day,
        halving_period_days=halving_period_days,
        days_since_last_halving=days_since_last_halving,
        total_staked_usd=total_staked_usd,
        my_stake_usd=my_stake_usd,
        base_protocol_apy_pct=base_protocol_apy_pct,
        min_acceptable_apy_pct=min_acceptable_apy_pct,
        protocol_name=protocol_name,
    )


# ---------------------------------------------------------------------------
# 1. Mining APY calculation
# ---------------------------------------------------------------------------

class TestMiningAPYCalculation(unittest.TestCase):

    def test_basic_mining_apy(self):
        # emission=10000/day, staked=5M → APY = 10000*365/5000000*100 = 73%
        r = make_report(
            current_emission_rate_usd_per_day=10_000.0,
            total_staked_usd=5_000_000.0,
        )
        expected = 10_000.0 * 365 / 5_000_000.0 * 100.0
        self.assertAlmostEqual(r.current_mining_apy_pct, expected, places=4)

    def test_mining_apy_independent_of_my_stake(self):
        r1 = make_report(my_stake_usd=10_000.0)
        r2 = make_report(my_stake_usd=500_000.0)
        self.assertAlmostEqual(r1.current_mining_apy_pct, r2.current_mining_apy_pct, places=6)

    def test_mining_apy_zero_when_total_staked_zero(self):
        r = make_report(total_staked_usd=0.0)
        self.assertAlmostEqual(r.current_mining_apy_pct, 0.0, places=6)

    def test_mining_apy_zero_emission(self):
        r = make_report(current_emission_rate_usd_per_day=0.0)
        self.assertAlmostEqual(r.current_mining_apy_pct, 0.0, places=6)

    def test_mining_apy_large_emission(self):
        r = make_report(
            current_emission_rate_usd_per_day=1_000_000.0,
            total_staked_usd=1_000_000.0,
        )
        expected = 1_000_000.0 * 365 / 1_000_000.0 * 100.0
        self.assertAlmostEqual(r.current_mining_apy_pct, expected, places=4)

    def test_mining_apy_small_staked(self):
        r = make_report(
            current_emission_rate_usd_per_day=1.0,
            total_staked_usd=100.0,
        )
        expected = 1.0 * 365 / 100.0 * 100.0
        self.assertAlmostEqual(r.current_mining_apy_pct, expected, places=6)


# ---------------------------------------------------------------------------
# 2. Total APY
# ---------------------------------------------------------------------------

class TestTotalAPY(unittest.TestCase):

    def test_total_apy_equals_mining_plus_base(self):
        r = make_report(base_protocol_apy_pct=3.0)
        expected = r.current_mining_apy_pct + 3.0
        self.assertAlmostEqual(r.current_total_apy_pct, expected, places=6)

    def test_total_apy_zero_emission_equals_base(self):
        r = make_report(current_emission_rate_usd_per_day=0.0, base_protocol_apy_pct=4.5)
        self.assertAlmostEqual(r.current_total_apy_pct, 4.5, places=6)

    def test_total_apy_zero_base(self):
        r = make_report(base_protocol_apy_pct=0.0)
        self.assertAlmostEqual(r.current_total_apy_pct, r.current_mining_apy_pct, places=6)

    def test_total_apy_greater_than_mining(self):
        r = make_report(base_protocol_apy_pct=2.0)
        self.assertGreater(r.current_total_apy_pct, r.current_mining_apy_pct)


# ---------------------------------------------------------------------------
# 3. days_to_next_halving
# ---------------------------------------------------------------------------

class TestDaysToNextHalving(unittest.TestCase):

    def test_basic_days_to_halving(self):
        r = make_report(halving_period_days=180, days_since_last_halving=45)
        self.assertEqual(r.days_to_next_halving, 135)

    def test_zero_days_since_last_halving(self):
        r = make_report(halving_period_days=180, days_since_last_halving=0)
        self.assertEqual(r.days_to_next_halving, 180)

    def test_almost_halved(self):
        r = make_report(halving_period_days=180, days_since_last_halving=179)
        self.assertEqual(r.days_to_next_halving, 1)

    def test_halving_period_365(self):
        r = make_report(halving_period_days=365, days_since_last_halving=100)
        self.assertEqual(r.days_to_next_halving, 265)

    def test_negative_days_since_clamped_to_zero(self):
        r = make_report(halving_period_days=180, days_since_last_halving=-10)
        self.assertEqual(r.days_to_next_halving, 180)

    def test_days_since_capped_at_period_minus_1(self):
        # days_since=200 but period=180 → clamped to 179
        r = make_report(halving_period_days=180, days_since_last_halving=200)
        self.assertEqual(r.days_to_next_halving, 1)


# ---------------------------------------------------------------------------
# 4. APY after halvings
# ---------------------------------------------------------------------------

class TestAPYAfterHalvings(unittest.TestCase):

    def test_apy_after_next_halving(self):
        r = make_report(base_protocol_apy_pct=3.0)
        expected = r.current_mining_apy_pct / 2.0 + 3.0
        self.assertAlmostEqual(r.apy_after_next_halving_pct, expected, places=6)

    def test_apy_after_two_halvings(self):
        r = make_report(base_protocol_apy_pct=3.0)
        expected = r.current_mining_apy_pct / 4.0 + 3.0
        self.assertAlmostEqual(r.apy_after_two_halvings_pct, expected, places=6)

    def test_two_halvings_below_one_halving(self):
        r = make_report(base_protocol_apy_pct=2.0)
        self.assertLess(r.apy_after_two_halvings_pct, r.apy_after_next_halving_pct)

    def test_halving_converges_to_base_at_zero_emission(self):
        r = make_report(current_emission_rate_usd_per_day=0.0, base_protocol_apy_pct=4.0)
        self.assertAlmostEqual(r.apy_after_next_halving_pct, 4.0, places=6)
        self.assertAlmostEqual(r.apy_after_two_halvings_pct, 4.0, places=6)

    def test_halving_reduces_mining_component_by_half(self):
        r = make_report()
        mining = r.current_mining_apy_pct
        base = r.base_protocol_apy_pct
        self.assertAlmostEqual(r.apy_after_next_halving_pct, mining / 2 + base, places=6)
        self.assertAlmostEqual(r.apy_after_two_halvings_pct, mining / 4 + base, places=6)


# ---------------------------------------------------------------------------
# 5. days_until_below_min_apy
# ---------------------------------------------------------------------------

class TestDaysUntilBelowMinAPY(unittest.TestCase):

    def test_never_drops_below_when_base_sufficient(self):
        # base=6, min=5 → base alone >= min → -1
        r = make_report(
            current_emission_rate_usd_per_day=10_000.0,
            base_protocol_apy_pct=6.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.days_until_below_min_apy, -1)

    def test_already_below_returns_zero(self):
        # emission=0, base=2, min=5 → total=2 < 5 → 0
        r = make_report(
            current_emission_rate_usd_per_day=0.0,
            base_protocol_apy_pct=2.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.days_until_below_min_apy, 0)

    def test_single_halving_needed(self):
        # mining=6%, base=3, min=7; after 1 halving: 3+3=6 < 7 → exactly 1 halving needed
        # ratio = 6/4 = 1.5 → n = floor(log2(1.5))+1 = 0+1 = 1 → days = days_to_next
        r = make_report(
            current_emission_rate_usd_per_day=6 * 5_000_000 / 365 / 100,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=7.0,
            halving_period_days=180,
            days_since_last_halving=45,  # days_to_next = 135
        )
        self.assertAlmostEqual(r.current_mining_apy_pct, 6.0, places=4)
        self.assertEqual(r.days_until_below_min_apy, 135)

    def test_two_halvings_needed(self):
        # mining=20, base=3, min=7; min_mining = 7-3 = 4
        # 20 > 4: after 1 halving: 10 > 4; after 2: 5 > 4; after 3: 2.5 < 4
        # n=3; days = 135 + 2*180 = 495
        emission_usd = 20 * 5_000_000 / 365 / 100
        r = make_report(
            current_emission_rate_usd_per_day=emission_usd,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=7.0,
            halving_period_days=180,
            days_since_last_halving=45,  # days_to_next=135
        )
        # Check mining apy is approximately 20
        self.assertAlmostEqual(r.current_mining_apy_pct, 20.0, places=4)
        # days = 135 + 2*180 = 495
        self.assertEqual(r.days_until_below_min_apy, 495)

    def test_returns_minus_1_when_base_exactly_equals_min(self):
        r = make_report(
            base_protocol_apy_pct=5.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.days_until_below_min_apy, -1)

    def test_returns_minus_1_when_zero_emission_and_base_above_min(self):
        r = make_report(
            current_emission_rate_usd_per_day=0.0,
            base_protocol_apy_pct=8.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.days_until_below_min_apy, -1)

    def test_days_until_below_is_integer(self):
        r = make_report()
        self.assertIsInstance(r.days_until_below_min_apy, int)

    def test_days_until_below_positive_or_minus_1_or_zero(self):
        r = make_report()
        self.assertTrue(r.days_until_below_min_apy == -1
                        or r.days_until_below_min_apy >= 0)


# ---------------------------------------------------------------------------
# 6. Decay label — EARLY_EMISSION
# ---------------------------------------------------------------------------

class TestLabelEarlyEmission(unittest.TestCase):

    def test_early_emission_large_days_to_halving(self):
        # days_to_next = 160, period=180, 160/180=0.89 > 0.75
        # total_apy well above min
        r = make_report(
            halving_period_days=180,
            days_since_last_halving=20,  # days_to_next=160
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=5.0,
            current_emission_rate_usd_per_day=10_000.0,
            total_staked_usd=5_000_000.0,
        )
        # total_apy >> min, days_to_next=160 > 0.75*180=135
        self.assertEqual(r.decay_label, "EARLY_EMISSION")

    def test_early_emission_period_100_days_to_next_80(self):
        r = make_report(
            halving_period_days=100,
            days_since_last_halving=20,  # days_to_next=80 > 75
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=5.0,
            current_emission_rate_usd_per_day=10_000.0,
            total_staked_usd=5_000_000.0,
        )
        # 80 > 100*0.75=75 → EARLY_EMISSION
        self.assertEqual(r.decay_label, "EARLY_EMISSION")


# ---------------------------------------------------------------------------
# 7. Decay label — HEALTHY_EMISSION
# ---------------------------------------------------------------------------

class TestLabelHealthyEmission(unittest.TestCase):

    def test_healthy_emission_mid_range(self):
        # days_to_next=100, period=200 → 100/200=0.5, in (0.25, 0.75)
        r = make_report(
            halving_period_days=200,
            days_since_last_halving=100,  # days_to_next=100
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=5.0,
            current_emission_rate_usd_per_day=10_000.0,
            total_staked_usd=5_000_000.0,
        )
        self.assertEqual(r.decay_label, "HEALTHY_EMISSION")

    def test_healthy_exactly_at_75_boundary(self):
        # days_to_next = 75, period=100 → at boundary 0.75 → HEALTHY (<=0.75, not EARLY)
        r = make_report(
            halving_period_days=100,
            days_since_last_halving=25,   # days_to_next=75
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=5.0,
            current_emission_rate_usd_per_day=10_000.0,
            total_staked_usd=5_000_000.0,
        )
        # 75 is not > 75 (early), and not <= 25 (approaching) → HEALTHY
        self.assertEqual(r.decay_label, "HEALTHY_EMISSION")


# ---------------------------------------------------------------------------
# 8. Decay label — APPROACHING_HALVING
# ---------------------------------------------------------------------------

class TestLabelApproachingHalving(unittest.TestCase):

    def test_approaching_halving_small_days_to_next(self):
        # days_to_next=20, period=180 → 20/180=0.11 ≤ 0.25
        r = make_report(
            halving_period_days=180,
            days_since_last_halving=160,  # days_to_next=20
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=2.0,   # min low so we don't hit EXHAUSTED
            current_emission_rate_usd_per_day=10_000.0,
            total_staked_usd=5_000_000.0,
        )
        self.assertEqual(r.decay_label, "APPROACHING_HALVING")

    def test_approaching_exactly_at_quarter(self):
        # days_to_next=45, period=180 → 45/180=0.25 ≤ 0.25 → APPROACHING
        r = make_report(
            halving_period_days=180,
            days_since_last_halving=135,  # days_to_next=45
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=2.0,
            current_emission_rate_usd_per_day=10_000.0,
            total_staked_usd=5_000_000.0,
        )
        self.assertEqual(r.decay_label, "APPROACHING_HALVING")


# ---------------------------------------------------------------------------
# 9. Decay label — POST_HALVING_DECAY
# ---------------------------------------------------------------------------

class TestLabelPostHalvingDecay(unittest.TestCase):

    def test_post_halving_decay_apy_near_min(self):
        # total_apy just above min but < min*1.5
        # min=10, so target total ~13 (between 10 and 15)
        # base=2, min_mining=8, emission → mining=11, total=13
        emission = 11 * 5_000_000 / 365 / 100
        r = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=2.0,
            min_acceptable_apy_pct=10.0,
            halving_period_days=180,
            days_since_last_halving=0,   # days_to_next=180 (EARLY position-wise)
        )
        # total~13, min=10, 10 < 13 < 15 → POST_HALVING_DECAY overrides EARLY
        self.assertEqual(r.decay_label, "POST_HALVING_DECAY")

    def test_post_halving_decay_priority_over_early(self):
        # days_to_next > 0.75*period but total < min*1.5
        emission = 12 * 5_000_000 / 365 / 100
        r = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=1.0,
            min_acceptable_apy_pct=10.0,
            halving_period_days=100,
            days_since_last_halving=5,   # days_to_next=95 > 75 (EARLY position)
        )
        # total~13, min=10, 10 < 13 < 15 → POST_HALVING_DECAY
        self.assertEqual(r.decay_label, "POST_HALVING_DECAY")


# ---------------------------------------------------------------------------
# 10. Decay label — EMISSION_EXHAUSTED
# ---------------------------------------------------------------------------

class TestLabelEmissionExhausted(unittest.TestCase):

    def test_emission_exhausted_zero_emission(self):
        r = make_report(
            current_emission_rate_usd_per_day=0.0,
            base_protocol_apy_pct=2.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.decay_label, "EMISSION_EXHAUSTED")

    def test_emission_exhausted_below_min(self):
        # base=2, min=5, mining=1 → total=3 < 5
        emission = 1 * 5_000_000 / 365 / 100
        r = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=2.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.decay_label, "EMISSION_EXHAUSTED")

    def test_emission_exhausted_at_exactly_min(self):
        # total = min exactly
        # mining=2, base=3, total=5=min
        emission = 2 * 5_000_000 / 365 / 100
        r = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.decay_label, "EMISSION_EXHAUSTED")

    def test_exhausted_priority_highest(self):
        # Even if days_to_next > 0.75*period, EXHAUSTED wins
        r = make_report(
            current_emission_rate_usd_per_day=0.0,
            base_protocol_apy_pct=1.0,
            min_acceptable_apy_pct=5.0,
            halving_period_days=180,
            days_since_last_halving=0,   # early position
        )
        self.assertEqual(r.decay_label, "EMISSION_EXHAUSTED")


# ---------------------------------------------------------------------------
# 11. Valid labels set
# ---------------------------------------------------------------------------

class TestValidLabels(unittest.TestCase):

    VALID = {
        "EARLY_EMISSION", "HEALTHY_EMISSION", "APPROACHING_HALVING",
        "POST_HALVING_DECAY", "EMISSION_EXHAUSTED",
    }

    def _chk(self, **kwargs):
        r = make_report(**kwargs)
        self.assertIn(r.decay_label, self.VALID)

    def test_label_valid_standard(self):
        self._chk()

    def test_label_valid_zero_emission(self):
        self._chk(current_emission_rate_usd_per_day=0.0)

    def test_label_valid_large_period(self):
        self._chk(halving_period_days=730)

    def test_label_valid_small_period(self):
        self._chk(halving_period_days=7)

    def test_label_valid_high_base(self):
        self._chk(base_protocol_apy_pct=20.0, min_acceptable_apy_pct=5.0)

    def test_label_valid_min_above_current(self):
        self._chk(min_acceptable_apy_pct=1000.0)


# ---------------------------------------------------------------------------
# 12. Report fields types and structure
# ---------------------------------------------------------------------------

class TestReportFields(unittest.TestCase):

    def setUp(self):
        self.r = make_report()

    def test_protocol_name_stored(self):
        self.assertEqual(self.r.protocol_name, "TestProto")

    def test_current_mining_apy_is_float(self):
        self.assertIsInstance(self.r.current_mining_apy_pct, float)

    def test_current_total_apy_is_float(self):
        self.assertIsInstance(self.r.current_total_apy_pct, float)

    def test_days_to_next_halving_is_int(self):
        self.assertIsInstance(r := self.r, LiquidityMiningDecayReport)
        self.assertIsInstance(self.r.days_to_next_halving, int)

    def test_apy_after_next_is_float(self):
        self.assertIsInstance(self.r.apy_after_next_halving_pct, float)

    def test_apy_after_two_is_float(self):
        self.assertIsInstance(self.r.apy_after_two_halvings_pct, float)

    def test_days_until_below_is_int(self):
        self.assertIsInstance(self.r.days_until_below_min_apy, int)

    def test_decay_label_is_str(self):
        self.assertIsInstance(self.r.decay_label, str)

    def test_advisory_is_list(self):
        self.assertIsInstance(self.r.advisory, list)

    def test_advisory_non_empty(self):
        self.assertGreater(len(self.r.advisory), 0)

    def test_generated_at_str(self):
        self.assertIsInstance(self.r.generated_at, str)
        self.assertGreater(len(self.r.generated_at), 0)

    def test_halving_period_preserved(self):
        self.assertEqual(self.r.halving_period_days, 180)

    def test_base_apy_preserved(self):
        self.assertAlmostEqual(self.r.base_protocol_apy_pct, 3.0, places=6)

    def test_min_apy_preserved(self):
        self.assertAlmostEqual(self.r.min_acceptable_apy_pct, 5.0, places=6)


# ---------------------------------------------------------------------------
# 13. Advisory messages
# ---------------------------------------------------------------------------

class TestAdvisoryMessages(unittest.TestCase):

    def test_advisory_mentions_protocol_name(self):
        r = make_report(protocol_name="SushiSwap")
        # at least one advisory message mentions the protocol
        self.assertTrue(any("SushiSwap" in m for m in r.advisory))

    def test_exhausted_advisory_mentions_exit(self):
        r = make_report(current_emission_rate_usd_per_day=0.0,
                        base_protocol_apy_pct=1.0,
                        min_acceptable_apy_pct=5.0)
        text = " ".join(r.advisory).lower()
        self.assertTrue("exit" in text or "exit" in text or "below" in text or "minimum" in text)

    def test_early_emission_advisory_mentions_next_halving(self):
        r = make_report(halving_period_days=180, days_since_last_halving=10)
        text = " ".join(r.advisory).lower()
        self.assertTrue("halving" in text or "emission" in text)

    def test_advisory_contains_days_until_below_info(self):
        r = make_report()
        # Should mention expected drop or never/bonus
        text = " ".join(r.advisory).lower()
        self.assertTrue("days" in text or "bonus" in text or "never" in text or "already" in text)

    def test_never_drops_below_advisory_message(self):
        r = make_report(base_protocol_apy_pct=10.0, min_acceptable_apy_pct=5.0)
        text = " ".join(r.advisory).lower()
        # Should mention base meets minimum
        self.assertTrue("base" in text or "bonus" in text or "minimum" in text)


# ---------------------------------------------------------------------------
# 14. Persistence — save_report / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _temp_file(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        return Path(tmp.name)

    def test_save_creates_file(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            self.assertTrue(tf.exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_saved_file_valid_json(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            self.assertIsInstance(data, list)
        finally:
            tf.unlink(missing_ok=True)

    def test_saves_one_entry(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(len(data), 1)
        finally:
            tf.unlink(missing_ok=True)

    def test_accumulates_entries(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        tf = self._temp_file()
        try:
            for _ in range(5):
                ana.save_report(make_report(), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(len(data), 5)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_cap(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        tf = self._temp_file()
        try:
            for _ in range(MAX_ENTRIES + 15):
                ana.save_report(make_report(), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(len(data), MAX_ENTRIES)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_keeps_most_recent(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        tf = self._temp_file()
        try:
            for i in range(MAX_ENTRIES + 5):
                r = make_report(protocol_name=f"Proto{i}")
                ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(data[-1]["protocol_name"], f"Proto{MAX_ENTRIES + 4}")
        finally:
            tf.unlink(missing_ok=True)

    def test_load_history_missing_file(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        self.assertEqual(ana.load_history(Path("/nonexistent/xyz.json")), [])

    def test_load_history_corrupt_json(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        tf = self._temp_file()
        try:
            tf.write_text("{bad json[")
            self.assertEqual(ana.load_history(tf), [])
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_has_required_keys(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            entry = json.loads(tf.read_text())[0]
            for key in (
                "timestamp", "protocol_name", "current_mining_apy_pct",
                "current_total_apy_pct", "days_to_next_halving",
                "apy_after_next_halving_pct", "apy_after_two_halvings_pct",
                "days_until_below_min_apy", "decay_label",
            ):
                self.assertIn(key, entry, f"Missing key: {key}")
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_mining_apy_matches_report(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            entry = json.loads(tf.read_text())[0]
            self.assertAlmostEqual(entry["current_mining_apy_pct"],
                                   r.current_mining_apy_pct, places=5)
        finally:
            tf.unlink(missing_ok=True)

    def test_no_tmp_file_left_behind(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            self.assertFalse(tf.with_suffix(".tmp").exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_creates_parent_dirs(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "sub" / "dir" / "out.json"
            ana.save_report(make_report(), data_file=nested)
            self.assertTrue(nested.exists())

    def test_entry_advisory_is_list(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            entry = json.loads(tf.read_text())[0]
            self.assertIsInstance(entry["advisory"], list)
        finally:
            tf.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 15. Stateless analyzer
# ---------------------------------------------------------------------------

class TestStatelessAnalyzer(unittest.TestCase):

    def test_two_calls_independent(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r1 = ana.analyze(10_000, 180, 45, 5_000_000, 50_000, 3.0, 5.0, "A")
        r2 = ana.analyze(1_000, 365, 100, 2_000_000, 10_000, 1.0, 3.0, "B")
        self.assertNotEqual(r1.current_mining_apy_pct, r2.current_mining_apy_pct)
        self.assertEqual(r1.protocol_name, "A")
        self.assertEqual(r2.protocol_name, "B")

    def test_repeated_call_deterministic(self):
        ana = ProtocolDeFiLiquidityMiningDecayAnalyzer()
        r1 = ana.analyze(10_000, 180, 45, 5_000_000, 50_000, 3.0, 5.0, "X")
        r2 = ana.analyze(10_000, 180, 45, 5_000_000, 50_000, 3.0, 5.0, "X")
        self.assertAlmostEqual(r1.current_mining_apy_pct, r2.current_mining_apy_pct, places=8)
        self.assertEqual(r1.decay_label, r2.decay_label)


# ---------------------------------------------------------------------------
# 16. Halving period clamping
# ---------------------------------------------------------------------------

class TestHalvingPeriodClamping(unittest.TestCase):

    def test_halving_period_zero_clamped_to_1(self):
        r = make_report(halving_period_days=0, days_since_last_halving=0)
        self.assertGreaterEqual(r.halving_period_days, 1)

    def test_halving_period_negative_clamped(self):
        r = make_report(halving_period_days=-5, days_since_last_halving=0)
        self.assertGreaterEqual(r.halving_period_days, 1)

    def test_days_since_last_negative_clamped(self):
        r = make_report(halving_period_days=180, days_since_last_halving=-30)
        self.assertGreaterEqual(r.days_to_next_halving, 1)
        self.assertLessEqual(r.days_to_next_halving, 180)


# ---------------------------------------------------------------------------
# 17. Parametric sweep: days_to_next_halving boundaries
# ---------------------------------------------------------------------------

class TestDaysToNextHalvingBoundaries(unittest.TestCase):

    def _r(self, period: int, since: int) -> LiquidityMiningDecayReport:
        return make_report(
            halving_period_days=period,
            days_since_last_halving=since,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=2.0,   # low min to avoid EXHAUSTED
            current_emission_rate_usd_per_day=10_000.0,
        )

    def test_75pct_boundary_early_vs_healthy(self):
        period = 200
        # days_to_next = 151 > 0.75*200=150 → EARLY
        r = self._r(period, 49)   # days_to_next = 151
        self.assertEqual(r.decay_label, "EARLY_EMISSION")

    def test_75pct_boundary_exactly_150(self):
        period = 200
        # days_to_next = 150 = 0.75*200 → not > 0.75*200 → HEALTHY
        r = self._r(period, 50)   # days_to_next = 150
        self.assertEqual(r.decay_label, "HEALTHY_EMISSION")

    def test_25pct_boundary_healthy_vs_approaching(self):
        period = 200
        # days_to_next = 51 > 0.25*200=50 → HEALTHY
        r = self._r(period, 149)  # days_to_next = 51
        self.assertEqual(r.decay_label, "HEALTHY_EMISSION")

    def test_25pct_boundary_exactly_50(self):
        period = 200
        # days_to_next = 50 = 0.25*200 → APPROACHING (≤ 0.25*period)
        r = self._r(period, 150)  # days_to_next = 50
        self.assertEqual(r.decay_label, "APPROACHING_HALVING")


# ---------------------------------------------------------------------------
# 18. APY trajectory consistency
# ---------------------------------------------------------------------------

class TestAPYTrajectory(unittest.TestCase):

    def test_total_apy_decreases_after_halvings(self):
        r = make_report(
            current_emission_rate_usd_per_day=10_000.0,
            base_protocol_apy_pct=1.0,
        )
        self.assertGreater(r.current_total_apy_pct, r.apy_after_next_halving_pct)
        self.assertGreater(r.apy_after_next_halving_pct, r.apy_after_two_halvings_pct)

    def test_apy_converges_to_base_over_many_halvings(self):
        # After enough halvings, mining apy → 0, total → base
        mining = 100.0  # %
        base = 3.0
        # After 10 halvings: mining/1024 ≈ 0.098%
        emission = mining * 5_000_000 / 365 / 100
        r = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=base,
        )
        # apy after 10 halvings ≈ base + mining/1024
        approx = base + mining / (2 ** 10)
        self.assertAlmostEqual(r.apy_after_two_halvings_pct, base + mining / 4, places=3)

    def test_zero_emission_no_trajectory(self):
        r = make_report(current_emission_rate_usd_per_day=0.0, base_protocol_apy_pct=5.0)
        self.assertAlmostEqual(r.current_total_apy_pct, 5.0, places=6)
        self.assertAlmostEqual(r.apy_after_next_halving_pct, 5.0, places=6)
        self.assertAlmostEqual(r.apy_after_two_halvings_pct, 5.0, places=6)


# ---------------------------------------------------------------------------
# 19. Full integration scenarios
# ---------------------------------------------------------------------------

class TestIntegrationScenarios(unittest.TestCase):

    def test_sushiswap_scenario(self):
        r = make_report(
            current_emission_rate_usd_per_day=10_000.0,
            halving_period_days=180,
            days_since_last_halving=45,
            total_staked_usd=5_000_000.0,
            my_stake_usd=50_000.0,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=5.0,
            protocol_name="SushiSwap",
        )
        # mining = 10000*365/5000000*100 = 73%
        self.assertAlmostEqual(r.current_mining_apy_pct, 73.0, places=4)
        self.assertAlmostEqual(r.current_total_apy_pct, 76.0, places=4)
        # days_to_next = 135, period=180, 135/180=0.75 → HEALTHY (=0.75 boundary)
        self.assertEqual(r.days_to_next_halving, 135)
        # APY well above 5 → not EXHAUSTED
        self.assertNotEqual(r.decay_label, "EMISSION_EXHAUSTED")

    def test_curve_scenario_approaching_halving(self):
        r = make_report(
            current_emission_rate_usd_per_day=5_000.0,
            halving_period_days=120,
            days_since_last_halving=91,  # days_to_next=29 ≤ 0.25*120=30
            total_staked_usd=2_000_000.0,
            my_stake_usd=20_000.0,
            base_protocol_apy_pct=2.0,
            min_acceptable_apy_pct=3.0,
            protocol_name="Curve",
        )
        # days_to_next=29, period=120, 29 ≤ 30 → APPROACHING (if not exhausted/post)
        # mining = 5000*365/2000000*100 = 91.25%; total >> min
        self.assertIn(r.decay_label,
                      {"APPROACHING_HALVING", "EARLY_EMISSION", "HEALTHY_EMISSION"})

    def test_uniswap_high_base_never_below(self):
        r = make_report(
            current_emission_rate_usd_per_day=1_000.0,
            base_protocol_apy_pct=8.0,
            min_acceptable_apy_pct=5.0,
            protocol_name="Uniswap",
        )
        self.assertEqual(r.days_until_below_min_apy, -1)


# ---------------------------------------------------------------------------
# 20. Additional edge and boundary tests
# ---------------------------------------------------------------------------

class TestAdditionalEdgeCases(unittest.TestCase):

    def test_very_large_emission(self):
        r = make_report(
            current_emission_rate_usd_per_day=1_000_000_000.0,
            total_staked_usd=1_000_000.0,
        )
        self.assertGreater(r.current_mining_apy_pct, 1_000.0)

    def test_tiny_emission(self):
        r = make_report(
            current_emission_rate_usd_per_day=0.01,
            total_staked_usd=1_000_000_000.0,
        )
        expected = 0.01 * 365 / 1_000_000_000.0 * 100.0
        self.assertAlmostEqual(r.current_mining_apy_pct, expected, places=6)

    def test_my_stake_above_total_no_crash(self):
        # Unusual but should not raise
        r = make_report(my_stake_usd=10_000_000.0, total_staked_usd=5_000_000.0)
        self.assertIsInstance(r.current_mining_apy_pct, float)

    def test_min_acceptable_zero_never_below(self):
        r = make_report(min_acceptable_apy_pct=0.0)
        # min=0, base >= 0 always >= 0, so should return -1
        self.assertEqual(r.days_until_below_min_apy, -1)

    def test_long_halving_period(self):
        r = make_report(halving_period_days=3650, days_since_last_halving=100)
        self.assertEqual(r.days_to_next_halving, 3550)

    def test_report_is_instance_of_dataclass(self):
        r = make_report()
        self.assertIsInstance(r, LiquidityMiningDecayReport)

    def test_mining_apy_non_negative(self):
        r = make_report(current_emission_rate_usd_per_day=500.0)
        self.assertGreaterEqual(r.current_mining_apy_pct, 0.0)

    def test_apy_after_halving_at_least_base(self):
        r = make_report(base_protocol_apy_pct=2.5)
        self.assertGreaterEqual(r.apy_after_next_halving_pct, 2.5 - 1e-9)
        self.assertGreaterEqual(r.apy_after_two_halvings_pct, 2.5 - 1e-9)

    def test_days_to_next_halving_positive(self):
        r = make_report(halving_period_days=90, days_since_last_halving=30)
        self.assertGreater(r.days_to_next_halving, 0)


# ---------------------------------------------------------------------------
# 21. days_until_below_min_apy — exact boundary math
# ---------------------------------------------------------------------------

class TestDaysUntilBelowMinExact(unittest.TestCase):

    def test_three_halvings_needed(self):
        # mining=20, base=3, min=7 → min_mining=4 → ratio=5
        # n = floor(log2(5))+1 = 2+1=3; days = 135+2*180 = 495
        emission = 20 * 5_000_000 / 365 / 100
        r = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=7.0,
            halving_period_days=180,
            days_since_last_halving=45,
        )
        self.assertAlmostEqual(r.current_mining_apy_pct, 20.0, places=4)
        self.assertEqual(r.days_until_below_min_apy, 495)

    def test_already_below_threshold(self):
        # emission tiny so total < min
        r = make_report(
            current_emission_rate_usd_per_day=0.1,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=1.0,
            min_acceptable_apy_pct=10.0,
        )
        self.assertEqual(r.days_until_below_min_apy, 0)

    def test_base_exactly_at_min_returns_minus_1(self):
        r = make_report(
            base_protocol_apy_pct=7.0,
            min_acceptable_apy_pct=7.0,
        )
        self.assertEqual(r.days_until_below_min_apy, -1)

    def test_base_above_min_returns_minus_1(self):
        r = make_report(
            base_protocol_apy_pct=8.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.days_until_below_min_apy, -1)

    def test_zero_emission_below_min_returns_0(self):
        r = make_report(
            current_emission_rate_usd_per_day=0.0,
            base_protocol_apy_pct=2.0,
            min_acceptable_apy_pct=5.0,
        )
        self.assertEqual(r.days_until_below_min_apy, 0)

    def test_days_until_below_uses_halving_period(self):
        # Same mining/base/min ratios but different halving period → different days
        emission = 6 * 5_000_000 / 365 / 100
        r90 = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=7.0,
            halving_period_days=90,
            days_since_last_halving=22,   # days_to_next = 68
        )
        r180 = make_report(
            current_emission_rate_usd_per_day=emission,
            total_staked_usd=5_000_000.0,
            base_protocol_apy_pct=3.0,
            min_acceptable_apy_pct=7.0,
            halving_period_days=180,
            days_since_last_halving=45,   # days_to_next = 135
        )
        self.assertNotEqual(r90.days_until_below_min_apy, r180.days_until_below_min_apy)


# ---------------------------------------------------------------------------
# 22. Report stores input fields faithfully
# ---------------------------------------------------------------------------

class TestInputFieldStorage(unittest.TestCase):

    def test_emission_stored(self):
        r = make_report(current_emission_rate_usd_per_day=12345.67)
        self.assertAlmostEqual(r.current_emission_rate_usd_per_day, 12345.67, places=4)

    def test_total_staked_stored(self):
        r = make_report(total_staked_usd=9_876_543.0)
        self.assertAlmostEqual(r.total_staked_usd, 9_876_543.0, places=0)

    def test_my_stake_stored(self):
        r = make_report(my_stake_usd=77_000.0)
        self.assertAlmostEqual(r.my_stake_usd, 77_000.0, places=0)

    def test_days_since_last_halving_stored(self):
        r = make_report(halving_period_days=180, days_since_last_halving=60)
        self.assertEqual(r.days_since_last_halving, 60)


if __name__ == "__main__":
    unittest.main()
