"""
Tests for MP-677: ProtocolInsuranceAssessor
≥60 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.protocol_insurance_assessor import (
    INSURANCE_PROTOCOLS,
    MAX_ENTRIES,
    InsuranceNeed,
    InsuranceRecommendation,
    ProtocolInsuranceAssessor,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _need(
    position_id="pos_001",
    protocol="aave_v3",
    position_value_usd=100_000.0,
    protocol_risk_score=0.3,
    smart_contract_risk=0.2,
    has_existing_coverage=False,
    existing_coverage_usd=0.0,
) -> InsuranceNeed:
    return InsuranceNeed(
        position_id=position_id,
        protocol=protocol,
        position_value_usd=position_value_usd,
        protocol_risk_score=protocol_risk_score,
        smart_contract_risk=smart_contract_risk,
        has_existing_coverage=has_existing_coverage,
        existing_coverage_usd=existing_coverage_usd,
    )


# ---------------------------------------------------------------------------
# _composite_risk
# ---------------------------------------------------------------------------

class TestCompositeRisk(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_equal_weights(self):
        n = _need(protocol_risk_score=0.4, smart_contract_risk=0.6)
        self.assertAlmostEqual(self.a._composite_risk(n), 0.5)

    def test_zero_both(self):
        n = _need(protocol_risk_score=0.0, smart_contract_risk=0.0)
        self.assertAlmostEqual(self.a._composite_risk(n), 0.0)

    def test_one_both(self):
        n = _need(protocol_risk_score=1.0, smart_contract_risk=1.0)
        self.assertAlmostEqual(self.a._composite_risk(n), 1.0)

    def test_clamp_above_one(self):
        n = _need(protocol_risk_score=1.0, smart_contract_risk=1.0)
        self.assertLessEqual(self.a._composite_risk(n), 1.0)

    def test_clamp_below_zero(self):
        n = _need(protocol_risk_score=0.0, smart_contract_risk=0.0)
        self.assertGreaterEqual(self.a._composite_risk(n), 0.0)

    def test_weighted_formula(self):
        n = _need(protocol_risk_score=0.6, smart_contract_risk=0.2)
        # 0.6*0.5 + 0.2*0.5 = 0.3 + 0.1 = 0.4
        self.assertAlmostEqual(self.a._composite_risk(n), 0.4)

    def test_asymmetric(self):
        n = _need(protocol_risk_score=0.8, smart_contract_risk=0.0)
        self.assertAlmostEqual(self.a._composite_risk(n), 0.4)


# ---------------------------------------------------------------------------
# _recommended_cover
# ---------------------------------------------------------------------------

class TestRecommendedCover(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_basic_formula(self):
        # 100k * 0.5 * 1.5 = 75k
        cover = self.a._recommended_cover(100_000.0, 0.5, 0.0)
        self.assertAlmostEqual(cover, 75_000.0)

    def test_capped_at_position_value(self):
        # 100k * 1.0 * 1.5 = 150k → capped at 100k
        cover = self.a._recommended_cover(100_000.0, 1.0, 0.0)
        self.assertAlmostEqual(cover, 100_000.0)

    def test_existing_coverage_floor(self):
        # risk-weighted = 10k, existing = 50k → result must be ≥ 50k
        cover = self.a._recommended_cover(100_000.0, 0.1, 50_000.0)
        self.assertGreaterEqual(cover, 50_000.0)

    def test_zero_risk_uses_existing_floor(self):
        cover = self.a._recommended_cover(100_000.0, 0.0, 30_000.0)
        self.assertAlmostEqual(cover, 30_000.0)

    def test_zero_risk_zero_existing(self):
        cover = self.a._recommended_cover(100_000.0, 0.0, 0.0)
        self.assertAlmostEqual(cover, 0.0)

    def test_cap_when_existing_above_position(self):
        # existing > position → result capped at position value
        cover = self.a._recommended_cover(100_000.0, 0.1, 200_000.0)
        self.assertAlmostEqual(cover, 100_000.0)


# ---------------------------------------------------------------------------
# _coverage_gap
# ---------------------------------------------------------------------------

class TestCoverageGap(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_positive_gap(self):
        self.assertAlmostEqual(self.a._coverage_gap(80_000.0, 30_000.0), 50_000.0)

    def test_zero_gap_when_equal(self):
        self.assertAlmostEqual(self.a._coverage_gap(50_000.0, 50_000.0), 0.0)

    def test_never_negative(self):
        gap = self.a._coverage_gap(20_000.0, 50_000.0)
        self.assertGreaterEqual(gap, 0.0)

    def test_zero_existing(self):
        self.assertAlmostEqual(self.a._coverage_gap(75_000.0, 0.0), 75_000.0)

    def test_fully_covered_no_gap(self):
        self.assertAlmostEqual(self.a._coverage_gap(0.0, 0.0), 0.0)


# ---------------------------------------------------------------------------
# _expected_annual_loss
# ---------------------------------------------------------------------------

class TestExpectedAnnualLoss(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_basic(self):
        self.assertAlmostEqual(self.a._expected_annual_loss(100_000.0, 0.3), 30_000.0)

    def test_zero_risk(self):
        self.assertAlmostEqual(self.a._expected_annual_loss(100_000.0, 0.0), 0.0)

    def test_full_risk(self):
        self.assertAlmostEqual(self.a._expected_annual_loss(100_000.0, 1.0), 100_000.0)

    def test_proportional(self):
        loss_a = self.a._expected_annual_loss(100_000.0, 0.2)
        loss_b = self.a._expected_annual_loss(200_000.0, 0.2)
        self.assertAlmostEqual(loss_b / loss_a, 2.0)


# ---------------------------------------------------------------------------
# _best_provider
# ---------------------------------------------------------------------------

class TestBestProvider(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_small_cover_lowest_premium(self):
        # 10k cover → all qualify; lowest premium is ribbon_protect (1.5%)
        provider = self.a._best_provider(10_000.0)
        self.assertEqual(provider, "ribbon_protect")

    def test_large_cover_only_nexus_qualifies(self):
        # 900k → only nexus_mutual qualifies (max 1M)
        provider = self.a._best_provider(900_000.0)
        self.assertEqual(provider, "nexus_mutual")

    def test_above_all_fallback_to_highest_max(self):
        # 2M → none qualify → fallback to nexus_mutual (max 1M)
        provider = self.a._best_provider(2_000_000.0)
        self.assertEqual(provider, "nexus_mutual")

    def test_exactly_at_max_cover(self):
        # exactly 500k → nexus(1M), insurace(500k) qualify; ribbon(250k) and unslashed(200k) don't
        # among qualifying: ribbon_protect? No, ribbon max_cover=250k < 500k. So nexus+insurace qualify
        # insurace(2.0%) < nexus(2.6%) → insurace
        provider = self.a._best_provider(500_000.0)
        self.assertEqual(provider, "insurace")

    def test_cover_250k_ribbon_qualifies(self):
        # 250k: nexus(1M), insurace(500k), ribbon(250k) qualify; unslashed(200k) doesn't
        # lowest premium: ribbon(1.5%)
        provider = self.a._best_provider(250_000.0)
        self.assertEqual(provider, "ribbon_protect")

    def test_cover_201k_ribbon_excluded(self):
        # 201k: nexus, insurace, ribbon(250k≥201k) qualify; unslashed(200k) doesn't
        # lowest: ribbon 1.5%
        provider = self.a._best_provider(201_000.0)
        self.assertEqual(provider, "ribbon_protect")

    def test_cover_200k_all_except_unslashed(self):
        # 200k: unslashed max exactly 200k ≥ 200k → qualifies too
        # all qualify; lowest: ribbon 1.5%
        provider = self.a._best_provider(200_000.0)
        self.assertEqual(provider, "ribbon_protect")


# ---------------------------------------------------------------------------
# _annual_premium
# ---------------------------------------------------------------------------

class TestAnnualPremium(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_nexus_premium(self):
        # nexus: 2.6% of 100k = 2600
        self.assertAlmostEqual(self.a._annual_premium(100_000.0, "nexus_mutual"), 2600.0)

    def test_ribbon_premium(self):
        # ribbon: 1.5% of 100k = 1500
        self.assertAlmostEqual(self.a._annual_premium(100_000.0, "ribbon_protect"), 1500.0)

    def test_insurace_premium(self):
        self.assertAlmostEqual(self.a._annual_premium(100_000.0, "insurace"), 2000.0)

    def test_unslashed_premium(self):
        self.assertAlmostEqual(self.a._annual_premium(100_000.0, "unslashed"), 3500.0)

    def test_zero_cover(self):
        self.assertAlmostEqual(self.a._annual_premium(0.0, "nexus_mutual"), 0.0)


# ---------------------------------------------------------------------------
# _is_cost_effective
# ---------------------------------------------------------------------------

class TestIsCostEffective(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_premium_less_than_loss_true(self):
        self.assertTrue(self.a._is_cost_effective(500.0, 1000.0))

    def test_premium_equal_to_loss_false(self):
        self.assertFalse(self.a._is_cost_effective(1000.0, 1000.0))

    def test_premium_greater_than_loss_false(self):
        self.assertFalse(self.a._is_cost_effective(2000.0, 1000.0))

    def test_both_zero_false(self):
        self.assertFalse(self.a._is_cost_effective(0.0, 0.0))


# ---------------------------------------------------------------------------
# _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_low_risk_skip(self):
        # composite < 0.15 → SKIP regardless
        self.assertEqual(self.a._recommendation(0.10, True), "SKIP")

    def test_low_risk_zero_skip(self):
        self.assertEqual(self.a._recommendation(0.0, True), "SKIP")

    def test_cost_effective_cover(self):
        self.assertEqual(self.a._recommendation(0.3, True), "COVER")

    def test_high_risk_not_effective_partial(self):
        self.assertEqual(self.a._recommendation(0.5, False), "PARTIAL")

    def test_medium_risk_not_effective_skip(self):
        # composite=0.25, not cost_effective, < 0.4 → SKIP
        self.assertEqual(self.a._recommendation(0.25, False), "SKIP")

    def test_exactly_015_cost_effective_cover(self):
        # 0.15 is NOT < 0.15 → check cost_effective → COVER
        self.assertEqual(self.a._recommendation(0.15, True), "COVER")

    def test_exactly_04_not_effective_partial(self):
        self.assertEqual(self.a._recommendation(0.4, False), "PARTIAL")

    def test_exactly_015_not_effective_skip(self):
        # 0.15 ≥ 0.15, not cost_effective, 0.15 < 0.4 → SKIP
        self.assertEqual(self.a._recommendation(0.15, False), "SKIP")


# ---------------------------------------------------------------------------
# _rationale
# ---------------------------------------------------------------------------

class TestRationale(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_cover_rationale_mentions_premium_and_loss(self):
        r = self.a._rationale("COVER", 1500.0, 3000.0, 0.3)
        self.assertIn("1500", r)
        self.assertIn("3000", r)
        self.assertIn("cost effective", r)

    def test_partial_rationale_mentions_risk(self):
        r = self.a._rationale("PARTIAL", 5000.0, 3000.0, 0.5)
        self.assertIn("partial", r)
        self.assertIn("50.0%", r)

    def test_skip_rationale_mentions_risk(self):
        r = self.a._rationale("SKIP", 100.0, 50.0, 0.1)
        self.assertIn("10.0%", r)
        self.assertIn("too low", r)


# ---------------------------------------------------------------------------
# assess (full pipeline)
# ---------------------------------------------------------------------------

class TestAssess(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_low_risk_skip(self):
        n = _need(protocol_risk_score=0.1, smart_contract_risk=0.1)
        # composite = 0.1 < 0.15 → SKIP
        rec = self.a.assess(n)
        self.assertEqual(rec.recommendation, "SKIP")

    def test_high_risk_cost_effective_cover(self):
        # High risk, cheap provider → COVER
        n = _need(
            position_value_usd=1_000_000.0,
            protocol_risk_score=0.8,
            smart_contract_risk=0.8,
        )
        rec = self.a.assess(n)
        # composite=0.8, expected_loss=800k, premium is far less → COVER
        self.assertEqual(rec.recommendation, "COVER")
        self.assertTrue(rec.is_cost_effective)

    def test_position_id_preserved(self):
        n = _need(position_id="morpho_usdc_main")
        rec = self.a.assess(n)
        self.assertEqual(rec.position_id, "morpho_usdc_main")

    def test_coverage_gap_never_negative(self):
        n = _need(existing_coverage_usd=1_000_000.0, position_value_usd=100_000.0)
        rec = self.a.assess(n)
        self.assertGreaterEqual(rec.coverage_gap_usd, 0.0)

    def test_recommended_cover_lte_position_value(self):
        n = _need(protocol_risk_score=1.0, smart_contract_risk=1.0,
                  position_value_usd=100_000.0)
        rec = self.a.assess(n)
        self.assertLessEqual(rec.recommended_cover_usd, 100_000.0)

    def test_premium_as_pct_of_position_positive(self):
        n = _need(protocol_risk_score=0.4, smart_contract_risk=0.4)
        rec = self.a.assess(n)
        self.assertGreater(rec.premium_as_pct_of_position, 0.0)

    def test_best_provider_in_known_protocols(self):
        n = _need()
        rec = self.a.assess(n)
        self.assertIn(rec.best_provider, INSURANCE_PROTOCOLS)

    def test_rationale_not_empty(self):
        n = _need()
        rec = self.a.assess(n)
        self.assertGreater(len(rec.rationale), 0)

    def test_zero_position_value(self):
        n = _need(position_value_usd=0.0)
        rec = self.a.assess(n)
        self.assertAlmostEqual(rec.expected_annual_loss_usd, 0.0)
        self.assertAlmostEqual(rec.premium_as_pct_of_position, 0.0)


# ---------------------------------------------------------------------------
# assess_batch
# ---------------------------------------------------------------------------

class TestAssessBatch(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()

    def test_empty_returns_empty(self):
        self.assertEqual(self.a.assess_batch([]), [])

    def test_single(self):
        result = self.a.assess_batch([_need()])
        self.assertEqual(len(result), 1)

    def test_multiple(self):
        needs = [_need(position_id=f"pos_{i}") for i in range(5)]
        result = self.a.assess_batch(needs)
        self.assertEqual(len(result), 5)
        ids = [r.position_id for r in result]
        for i in range(5):
            self.assertIn(f"pos_{i}", ids)

    def test_all_are_recommendations(self):
        needs = [_need(), _need(position_id="p2")]
        result = self.a.assess_batch(needs)
        for r in result:
            self.assertIsInstance(r, InsuranceRecommendation)


# ---------------------------------------------------------------------------
# save_results / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolInsuranceAssessor()
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "insurance_test.json"

    def _make_rec(self, pid="pos_001") -> InsuranceRecommendation:
        return InsuranceRecommendation(
            position_id=pid,
            recommended_cover_usd=50_000.0,
            coverage_gap_usd=50_000.0,
            annual_premium_usd=750.0,
            premium_as_pct_of_position=0.75,
            best_provider="ribbon_protect",
            is_cost_effective=True,
            expected_annual_loss_usd=2_750.0,
            recommendation="COVER",
            rationale="Premium $750/yr is less than expected loss $2750/yr — cost effective",
        )

    def test_load_history_missing_returns_empty(self):
        self.assertEqual(self.a.load_history(self.data_file), [])

    def test_save_creates_file(self):
        self.a.save_results([self._make_rec()], self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_save_and_load_roundtrip(self):
        self.a.save_results([self._make_rec()], self.data_file)
        history = self.a.load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["position_id"], "pos_001")

    def test_ring_buffer_capped_at_max_entries(self):
        for i in range(MAX_ENTRIES + 5):
            self.a.save_results([self._make_rec(pid=f"p{i}")], self.data_file)
        history = self.a.load_history(self.data_file)
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left(self):
        self.a.save_results([self._make_rec()], self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_corrupt_file_returns_empty(self):
        self.data_file.write_text("{ broken json")
        self.assertEqual(self.a.load_history(self.data_file), [])

    def test_save_empty_list(self):
        self.a.save_results([], self.data_file)
        history = self.a.load_history(self.data_file)
        self.assertEqual(history, [])

    def test_accumulation_across_calls(self):
        self.a.save_results([self._make_rec("a")], self.data_file)
        self.a.save_results([self._make_rec("b")], self.data_file)
        history = self.a.load_history(self.data_file)
        self.assertEqual(len(history), 2)

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 3):
            self.a.save_results([self._make_rec(pid=f"p{i}")], self.data_file)
        history = self.a.load_history(self.data_file)
        self.assertEqual(history[-1]["position_id"], f"p{MAX_ENTRIES + 2}")

    def test_saved_entry_has_all_fields(self):
        self.a.save_results([self._make_rec()], self.data_file)
        entry = self.a.load_history(self.data_file)[0]
        for key in [
            "timestamp", "position_id", "recommended_cover_usd",
            "coverage_gap_usd", "annual_premium_usd", "best_provider",
            "is_cost_effective", "expected_annual_loss_usd",
            "recommendation", "rationale",
        ]:
            self.assertIn(key, entry)

    def test_save_batch(self):
        recs = [self._make_rec(pid=f"x{i}") for i in range(4)]
        self.a.save_results(recs, self.data_file)
        self.assertEqual(len(self.a.load_history(self.data_file)), 4)


if __name__ == "__main__":
    unittest.main()
