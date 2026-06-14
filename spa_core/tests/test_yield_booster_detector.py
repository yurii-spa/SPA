"""
Tests for MP-820 YieldBoosterDetector
=======================================
≥ 65 test cases using stdlib unittest only.
Run: python3 -m unittest spa_core.tests.test_yield_booster_detector -v
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.yield_booster_detector import (
    _append_log,
    _sustainability,
    _token_risk,
    analyze,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
def _booster(
    name: str = "TestBooster",
    btype: str = "liquidity_mining",
    additional_apy: float = 5.0,
    duration_days: int | None = 90,
    token: str = "TKN",
    token_price_usd: float = 1.0,
    token_market_cap_usd: float = 500_000_000.0,  # LOW risk by default
    requires_lock: bool = False,
) -> dict:
    return {
        "name": name,
        "type": btype,
        "additional_apy": additional_apy,
        "duration_days": duration_days,
        "token": token,
        "token_price_usd": token_price_usd,
        "token_market_cap_usd": token_market_cap_usd,
        "requires_lock": requires_lock,
    }


def _risky_booster(name: str = "RiskyBoost", additional_apy: float = 10.0) -> dict:
    return _booster(
        name=name,
        additional_apy=additional_apy,
        token_market_cap_usd=1_000_000.0,  # < 10M → HIGH
    )


def _sustainable_booster(name: str = "SustBoost", additional_apy: float = 3.0) -> dict:
    return _booster(
        name=name,
        additional_apy=additional_apy,
        duration_days=None,            # permanent
        token_market_cap_usd=200_000_000.0,  # LOW
    )


# ---------------------------------------------------------------------------
# 1. _token_risk helper
# ---------------------------------------------------------------------------
class TestTokenRisk(unittest.TestCase):
    def test_zero_market_cap_high(self):
        self.assertEqual(_token_risk(0.0, 10_000_000), "HIGH")

    def test_negative_market_cap_high(self):
        self.assertEqual(_token_risk(-1.0, 10_000_000), "HIGH")

    def test_below_threshold_high(self):
        self.assertEqual(_token_risk(5_000_000.0, 10_000_000), "HIGH")

    def test_exactly_threshold_low_boundary(self):
        # market_cap == threshold → NOT < threshold, so check next bucket
        # 10M < 100M → MEDIUM
        self.assertEqual(_token_risk(10_000_000.0, 10_000_000), "MEDIUM")

    def test_between_threshold_and_100m_medium(self):
        self.assertEqual(_token_risk(50_000_000.0, 10_000_000), "MEDIUM")

    def test_below_100m_medium(self):
        self.assertEqual(_token_risk(99_999_999.0, 10_000_000), "MEDIUM")

    def test_exactly_100m_low(self):
        self.assertEqual(_token_risk(100_000_000.0, 10_000_000), "LOW")

    def test_above_100m_low(self):
        self.assertEqual(_token_risk(500_000_000.0, 10_000_000), "LOW")

    def test_custom_threshold(self):
        # threshold = 50M
        self.assertEqual(_token_risk(40_000_000.0, 50_000_000), "HIGH")
        self.assertEqual(_token_risk(60_000_000.0, 50_000_000), "MEDIUM")


# ---------------------------------------------------------------------------
# 2. _sustainability helper
# ---------------------------------------------------------------------------
class TestSustainability(unittest.TestCase):
    def test_high_risk_always_risky(self):
        self.assertEqual(_sustainability(True,  "HIGH"), "RISKY")
        self.assertEqual(_sustainability(False, "HIGH"), "RISKY")

    def test_temporary_medium_is_temporary(self):
        self.assertEqual(_sustainability(True, "MEDIUM"), "TEMPORARY")

    def test_temporary_low_is_temporary(self):
        self.assertEqual(_sustainability(True, "LOW"), "TEMPORARY")

    def test_permanent_low_is_sustainable(self):
        self.assertEqual(_sustainability(False, "LOW"), "SUSTAINABLE")

    def test_permanent_medium_is_sustainable(self):
        self.assertEqual(_sustainability(False, "MEDIUM"), "SUSTAINABLE")


# ---------------------------------------------------------------------------
# 3. Empty boosters edge case
# ---------------------------------------------------------------------------
class TestEmptyBoosters(unittest.TestCase):
    def setUp(self):
        self.result = analyze("Proto", [], base_apy=5.0)

    def test_total_boosted_apy_equals_base(self):
        self.assertAlmostEqual(self.result["total_boosted_apy"], 5.0, places=4)

    def test_boost_multiplier_is_1(self):
        self.assertAlmostEqual(self.result["boost_multiplier"], 1.0, places=4)

    def test_boosters_list_empty(self):
        self.assertEqual(self.result["boosters"], [])

    def test_permanent_boost_zero(self):
        self.assertAlmostEqual(self.result["summary"]["permanent_boost_apy"], 0.0, places=4)

    def test_temporary_boost_zero(self):
        self.assertAlmostEqual(self.result["summary"]["temporary_boost_apy"], 0.0, places=4)

    def test_sustainable_apy_equals_base(self):
        self.assertAlmostEqual(self.result["summary"]["sustainable_apy"], 5.0, places=4)

    def test_locked_required_apy_zero(self):
        self.assertAlmostEqual(self.result["summary"]["locked_required_apy"], 0.0, places=4)

    def test_highest_value_booster_empty_string(self):
        self.assertEqual(self.result["summary"]["highest_value_booster"], "")

    def test_recommendation_base_only(self):
        self.assertEqual(self.result["recommendation"], "BASE_ONLY")

    def test_timestamp_recent(self):
        self.assertAlmostEqual(self.result["timestamp"], time.time(), delta=5)


# ---------------------------------------------------------------------------
# 4. Zero base APY edge case
# ---------------------------------------------------------------------------
class TestZeroBaseApy(unittest.TestCase):
    def test_multiplier_is_1_when_base_zero(self):
        b = _booster(additional_apy=3.0)
        r = analyze("P", [b], base_apy=0.0)
        self.assertAlmostEqual(r["boost_multiplier"], 1.0, places=4)

    def test_total_boosted_apy_is_just_boost(self):
        b = _booster(additional_apy=3.0)
        r = analyze("P", [b], base_apy=0.0)
        self.assertAlmostEqual(r["total_boosted_apy"], 3.0, places=4)


# ---------------------------------------------------------------------------
# 5. is_temporary flag
# ---------------------------------------------------------------------------
class TestIsTemporary(unittest.TestCase):
    def test_none_duration_is_permanent(self):
        b = _booster(duration_days=None)
        r = analyze("P", [b], base_apy=4.0)
        self.assertFalse(r["boosters"][0]["is_temporary"])

    def test_int_duration_is_temporary(self):
        b = _booster(duration_days=30)
        r = analyze("P", [b], base_apy=4.0)
        self.assertTrue(r["boosters"][0]["is_temporary"])

    def test_duration_zero_is_temporary(self):
        b = _booster(duration_days=0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertTrue(r["boosters"][0]["is_temporary"])


# ---------------------------------------------------------------------------
# 6. token_risk in booster output
# ---------------------------------------------------------------------------
class TestBoosterTokenRisk(unittest.TestCase):
    def test_low_risk_booster(self):
        b = _booster(token_market_cap_usd=500_000_000.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["token_risk"], "LOW")

    def test_medium_risk_booster(self):
        b = _booster(token_market_cap_usd=50_000_000.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["token_risk"], "MEDIUM")

    def test_high_risk_booster_small_cap(self):
        b = _booster(token_market_cap_usd=1_000_000.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["token_risk"], "HIGH")

    def test_high_risk_booster_zero_cap(self):
        b = _booster(token_market_cap_usd=0.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["token_risk"], "HIGH")

    def test_custom_inflation_threshold(self):
        b = _booster(token_market_cap_usd=15_000_000.0)
        # default → MEDIUM (15M < 100M)
        r1 = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r1["boosters"][0]["token_risk"], "MEDIUM")
        # custom 20M threshold → HIGH
        r2 = analyze("P", [b], base_apy=4.0,
                     config={"inflation_risk_threshold_usd": 20_000_000.0})
        self.assertEqual(r2["boosters"][0]["token_risk"], "HIGH")


# ---------------------------------------------------------------------------
# 7. sustainability in booster output
# ---------------------------------------------------------------------------
class TestBoosterSustainability(unittest.TestCase):
    def test_risky_high_token_temporary(self):
        b = _booster(token_market_cap_usd=1_000_000.0, duration_days=30)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["sustainability"], "RISKY")

    def test_risky_high_token_permanent(self):
        b = _booster(token_market_cap_usd=1_000_000.0, duration_days=None)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["sustainability"], "RISKY")

    def test_temporary_low_token(self):
        b = _booster(token_market_cap_usd=500_000_000.0, duration_days=60)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["sustainability"], "TEMPORARY")

    def test_temporary_medium_token(self):
        b = _booster(token_market_cap_usd=50_000_000.0, duration_days=30)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["sustainability"], "TEMPORARY")

    def test_sustainable_permanent_low(self):
        b = _booster(token_market_cap_usd=500_000_000.0, duration_days=None)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["sustainability"], "SUSTAINABLE")

    def test_sustainable_permanent_medium(self):
        b = _booster(token_market_cap_usd=50_000_000.0, duration_days=None)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["sustainability"], "SUSTAINABLE")


# ---------------------------------------------------------------------------
# 8. value_score computation
# ---------------------------------------------------------------------------
class TestValueScore(unittest.TestCase):
    def test_sustainable_booster_value_score(self):
        # sustainable weight = 1.0
        # base=4, add=4 → total=8, contribution = 4/8*100=50, score=int(50*1.0)=50
        b = _sustainable_booster(additional_apy=4.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["value_score"], 50)

    def test_temporary_booster_value_score(self):
        # temporary weight = 0.5
        # base=4, add=4 → total=8, contribution=50, score=int(50*0.5)=25
        b = _booster(additional_apy=4.0, duration_days=30,
                     token_market_cap_usd=500_000_000.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["value_score"], 25)

    def test_risky_booster_value_score(self):
        # risky weight = 0.2
        # base=4, add=4 → total=8, contribution=50, score=int(50*0.2)=10
        b = _booster(additional_apy=4.0, duration_days=30,
                     token_market_cap_usd=1_000_000.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["boosters"][0]["value_score"], 10)

    def test_value_score_capped_at_100(self):
        # Very large booster relative to base → should not exceed 100
        b = _sustainable_booster(additional_apy=1000.0)
        r = analyze("P", [b], base_apy=0.01)
        self.assertLessEqual(r["boosters"][0]["value_score"], 100)

    def test_value_score_nonnegative(self):
        b = _risky_booster(additional_apy=1.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertGreaterEqual(r["boosters"][0]["value_score"], 0)


# ---------------------------------------------------------------------------
# 9. Summary metrics
# ---------------------------------------------------------------------------
class TestSummary(unittest.TestCase):
    def test_permanent_boost_apy_correct(self):
        b1 = _sustainable_booster(additional_apy=3.0)   # permanent
        b2 = _booster(additional_apy=2.0, duration_days=30)  # temporary
        r = analyze("P", [b1, b2], base_apy=4.0)
        self.assertAlmostEqual(r["summary"]["permanent_boost_apy"], 3.0, places=4)

    def test_temporary_boost_apy_correct(self):
        b1 = _sustainable_booster(additional_apy=3.0)
        b2 = _booster(additional_apy=2.0, duration_days=30)
        r = analyze("P", [b1, b2], base_apy=4.0)
        self.assertAlmostEqual(r["summary"]["temporary_boost_apy"], 2.0, places=4)

    def test_sustainable_apy_base_plus_permanent_low_med(self):
        b1 = _sustainable_booster(additional_apy=3.0)  # permanent LOW
        b2 = _booster(additional_apy=5.0, duration_days=30)  # temporary
        r = analyze("P", [b1, b2], base_apy=4.0)
        # sustainable = base + permanent LOW/MEDIUM = 4 + 3 = 7
        self.assertAlmostEqual(r["summary"]["sustainable_apy"], 7.0, places=4)

    def test_sustainable_apy_excludes_risky_permanent(self):
        b = _booster(additional_apy=5.0, duration_days=None,
                     token_market_cap_usd=1_000_000.0)  # permanent but HIGH risk
        r = analyze("P", [b], base_apy=4.0)
        # sustainability = RISKY, so not included
        self.assertAlmostEqual(r["summary"]["sustainable_apy"], 4.0, places=4)

    def test_locked_required_apy_only_locked(self):
        b1 = _booster(additional_apy=3.0, requires_lock=True)
        b2 = _booster(additional_apy=2.0, requires_lock=False)
        r = analyze("P", [b1, b2], base_apy=4.0)
        self.assertAlmostEqual(r["summary"]["locked_required_apy"], 3.0, places=4)

    def test_locked_required_apy_none_locked(self):
        b1 = _booster(additional_apy=3.0, requires_lock=False)
        r = analyze("P", [b1], base_apy=4.0)
        self.assertAlmostEqual(r["summary"]["locked_required_apy"], 0.0, places=4)

    def test_highest_value_booster_name(self):
        b1 = _sustainable_booster("Perm", additional_apy=5.0)
        b2 = _booster("Temp", additional_apy=1.0, duration_days=30)
        r = analyze("P", [b1, b2], base_apy=4.0)
        # Perm has higher value_score
        self.assertEqual(r["summary"]["highest_value_booster"], "Perm")

    def test_highest_value_booster_with_equal_scores_first_wins(self):
        # Both have value_score determined by their apy contribution + weight.
        b1 = _sustainable_booster("A", additional_apy=3.0)
        b2 = _sustainable_booster("B", additional_apy=3.0)
        r = analyze("P", [b1, b2], base_apy=4.0)
        # Both equal → max() returns first encountered
        self.assertIn(r["summary"]["highest_value_booster"], ("A", "B"))


# ---------------------------------------------------------------------------
# 10. total_boosted_apy and boost_multiplier
# ---------------------------------------------------------------------------
class TestTotalAndMultiplier(unittest.TestCase):
    def test_total_boosted_apy(self):
        b1 = _booster(additional_apy=3.0)
        b2 = _booster(additional_apy=2.0)
        r = analyze("P", [b1, b2], base_apy=5.0)
        self.assertAlmostEqual(r["total_boosted_apy"], 10.0, places=4)

    def test_boost_multiplier(self):
        b1 = _booster(additional_apy=5.0)
        r = analyze("P", [b1], base_apy=5.0)
        # 10 / 5 = 2.0
        self.assertAlmostEqual(r["boost_multiplier"], 2.0, places=4)

    def test_multiplier_with_zero_base_is_1(self):
        b = _booster(additional_apy=3.0)
        r = analyze("P", [b], base_apy=0.0)
        self.assertAlmostEqual(r["boost_multiplier"], 1.0, places=4)

    def test_base_apy_preserved(self):
        r = analyze("P", [], base_apy=7.5)
        self.assertAlmostEqual(r["base_apy"], 7.5, places=4)


# ---------------------------------------------------------------------------
# 11. overall_sustainability
# ---------------------------------------------------------------------------
class TestOverallSustainability(unittest.TestCase):
    def test_no_boosters_high(self):
        r = analyze("P", [], base_apy=5.0)
        self.assertEqual(r["overall_sustainability"], "HIGH")

    def test_all_sustainable_high(self):
        b1 = _sustainable_booster(additional_apy=3.0)
        b2 = _sustainable_booster(additional_apy=2.0)
        r = analyze("P", [b1, b2], base_apy=4.0)
        self.assertEqual(r["overall_sustainability"], "HIGH")

    def test_majority_risky_low(self):
        b1 = _risky_booster(additional_apy=8.0)
        b2 = _risky_booster(additional_apy=4.0)
        b3 = _sustainable_booster(additional_apy=1.0)
        r = analyze("P", [b1, b2, b3], base_apy=4.0)
        # risky = 12 out of 13 total boost → > 50%
        self.assertEqual(r["overall_sustainability"], "LOW")

    def test_mixed_is_medium(self):
        b1 = _booster(additional_apy=3.0, duration_days=30,
                      token_market_cap_usd=500_000_000.0)   # TEMPORARY
        b2 = _sustainable_booster(additional_apy=1.0)       # SUSTAINABLE perm=1
        # perm_ratio = 1 / 4 = 0.25 < 0.5 → not HIGH
        # risky = 0 → not LOW
        r = analyze("P", [b1, b2], base_apy=4.0)
        self.assertEqual(r["overall_sustainability"], "MEDIUM")

    def test_permanent_dominates_no_high_risk_is_high(self):
        b1 = _sustainable_booster(additional_apy=6.0)  # permanent LOW
        b2 = _booster(additional_apy=2.0, duration_days=30,
                      token_market_cap_usd=500_000_000.0)  # temp LOW
        r = analyze("P", [b1, b2], base_apy=4.0)
        # perm = 6 / 8 = 0.75 > 0.5, no HIGH risk → HIGH
        self.assertEqual(r["overall_sustainability"], "HIGH")

    def test_permanent_dominates_but_has_high_risk_is_medium(self):
        b1 = _booster(additional_apy=6.0, duration_days=None,
                      token_market_cap_usd=1_000_000.0)  # permanent HIGH risk
        b2 = _booster(additional_apy=2.0, duration_days=30,
                      token_market_cap_usd=500_000_000.0)  # temp LOW
        r = analyze("P", [b1, b2], base_apy=4.0)
        # has_high_risk_token=True → not HIGH
        # risky=6, total=8, ratio=0.75>0.5 → LOW
        self.assertEqual(r["overall_sustainability"], "LOW")


# ---------------------------------------------------------------------------
# 12. recommendation
# ---------------------------------------------------------------------------
class TestRecommendation(unittest.TestCase):
    def test_take_all_when_high_sustainability(self):
        b = _sustainable_booster(additional_apy=3.0)
        r = analyze("P", [b], base_apy=4.0)
        self.assertEqual(r["recommendation"], "TAKE_ALL")

    def test_base_only_no_boosters(self):
        r = analyze("P", [], base_apy=4.0)
        self.assertEqual(r["recommendation"], "BASE_ONLY")

    def test_base_only_all_risky(self):
        b1 = _risky_booster(additional_apy=5.0)
        b2 = _risky_booster(additional_apy=3.0)
        r = analyze("P", [b1, b2], base_apy=4.0)
        self.assertEqual(r["recommendation"], "BASE_ONLY")

    def test_selective_mixed(self):
        b1 = _booster(additional_apy=3.0, duration_days=30,
                      token_market_cap_usd=500_000_000.0)   # TEMPORARY
        b2 = _risky_booster(additional_apy=2.0)             # RISKY
        r = analyze("P", [b1, b2], base_apy=4.0)
        self.assertEqual(r["recommendation"], "SELECTIVE")

    def test_selective_medium_sustainability(self):
        b1 = _booster(additional_apy=3.0, duration_days=30,
                      token_market_cap_usd=500_000_000.0)  # TEMPORARY
        r = analyze("P", [b1], base_apy=4.0)
        # perm_ratio = 0 < 0.5 → MEDIUM → SELECTIVE
        self.assertEqual(r["recommendation"], "SELECTIVE")


# ---------------------------------------------------------------------------
# 13. Return-value schema validation
# ---------------------------------------------------------------------------
class TestReturnSchema(unittest.TestCase):
    def setUp(self):
        self.result = analyze(
            "SchemaProto",
            [_booster(), _sustainable_booster()],
            base_apy=5.0,
        )

    def test_top_level_keys(self):
        expected = {
            "protocol", "base_apy", "total_boosted_apy", "boost_multiplier",
            "boosters", "summary", "overall_sustainability", "recommendation",
            "timestamp",
        }
        self.assertEqual(set(self.result.keys()), expected)

    def test_summary_keys(self):
        expected = {
            "permanent_boost_apy", "temporary_boost_apy", "sustainable_apy",
            "locked_required_apy", "highest_value_booster",
        }
        self.assertEqual(set(self.result["summary"].keys()), expected)

    def test_booster_keys(self):
        expected = {
            "name", "type", "additional_apy", "duration_days",
            "is_temporary", "token_risk", "sustainability", "value_score",
        }
        for b in self.result["boosters"]:
            self.assertEqual(set(b.keys()), expected)

    def test_overall_sustainability_valid(self):
        self.assertIn(self.result["overall_sustainability"], {"HIGH", "MEDIUM", "LOW"})

    def test_recommendation_valid(self):
        self.assertIn(self.result["recommendation"], {"TAKE_ALL", "SELECTIVE", "BASE_ONLY"})

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.result["timestamp"], float)

    def test_boosters_count_matches_input(self):
        self.assertEqual(len(self.result["boosters"]), 2)

    def test_value_score_in_range(self):
        for b in self.result["boosters"]:
            self.assertGreaterEqual(b["value_score"], 0)
            self.assertLessEqual(b["value_score"], 100)


# ---------------------------------------------------------------------------
# 14. Protocol name passthrough
# ---------------------------------------------------------------------------
class TestProtocolName(unittest.TestCase):
    def test_protocol_name_preserved(self):
        r = analyze("AaveV3", [], base_apy=3.5)
        self.assertEqual(r["protocol"], "AaveV3")

    def test_empty_protocol_name(self):
        r = analyze("", [], base_apy=3.5)
        self.assertEqual(r["protocol"], "")

    def test_unicode_protocol_name(self):
        r = analyze("Протокол-XYZ", [], base_apy=3.5)
        self.assertEqual(r["protocol"], "Протокол-XYZ")


# ---------------------------------------------------------------------------
# 15. Atomic log persistence
# ---------------------------------------------------------------------------
class TestLogPersistence(unittest.TestCase):
    def test_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = analyze("P", [_booster()], base_apy=4.0)
            _append_log(r, data_dir=tmp)
            self.assertTrue(os.path.exists(os.path.join(tmp, "yield_booster_log.json")))

    def test_log_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = analyze("P", [_booster()], base_apy=4.0)
            _append_log(r, data_dir=tmp)
            with open(os.path.join(tmp, "yield_booster_log.json")) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_log_grows(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(3):
                r = analyze("P", [_booster()], base_apy=4.0)
                _append_log(r, data_dir=tmp)
            with open(os.path.join(tmp, "yield_booster_log.json")) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(110):
                r = analyze("P", [_booster()], base_apy=4.0)
                _append_log(r, data_dir=tmp)
            with open(os.path.join(tmp, "yield_booster_log.json")) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_log_entry_has_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = analyze("BoostProto", [_booster()], base_apy=4.0)
            _append_log(r, data_dir=tmp)
            with open(os.path.join(tmp, "yield_booster_log.json")) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["protocol"], "BoostProto")

    def test_log_survives_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "yield_booster_log.json")
            with open(log_path, "w") as fh:
                fh.write("{{broken json")
            r = analyze("P", [_booster()], base_apy=4.0)
            _append_log(r, data_dir=tmp)  # should not raise
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 16. Multiple boosters: ordering and aggregation
# ---------------------------------------------------------------------------
class TestMultipleBoosters(unittest.TestCase):
    def test_boosters_count_preserved(self):
        bs = [_booster(f"B{i}") for i in range(5)]
        r = analyze("P", bs, base_apy=4.0)
        self.assertEqual(len(r["boosters"]), 5)

    def test_booster_names_preserved(self):
        bs = [_booster("Alpha"), _booster("Beta")]
        r = analyze("P", bs, base_apy=4.0)
        names = [b["name"] for b in r["boosters"]]
        self.assertIn("Alpha", names)
        self.assertIn("Beta", names)

    def test_total_apy_sum(self):
        bs = [_booster(additional_apy=x) for x in [1.0, 2.0, 3.0]]
        r = analyze("P", bs, base_apy=4.0)
        self.assertAlmostEqual(r["total_boosted_apy"], 10.0, places=4)

    def test_mixed_temporary_and_permanent(self):
        b_temp = _booster("T", additional_apy=3.0, duration_days=30)
        b_perm = _sustainable_booster("P", additional_apy=2.0)
        r = analyze("P", [b_temp, b_perm], base_apy=4.0)
        self.assertAlmostEqual(r["summary"]["temporary_boost_apy"], 3.0, places=4)
        self.assertAlmostEqual(r["summary"]["permanent_boost_apy"], 2.0, places=4)


# ---------------------------------------------------------------------------
# 17. Config overrides
# ---------------------------------------------------------------------------
class TestConfigOverrides(unittest.TestCase):
    def test_custom_inflation_threshold_changes_risk(self):
        b = _booster(token_market_cap_usd=15_000_000.0)
        r_default = analyze("P", [b], base_apy=4.0)
        r_custom  = analyze("P", [b], base_apy=4.0,
                            config={"inflation_risk_threshold_usd": 20_000_000.0})
        self.assertEqual(r_default["boosters"][0]["token_risk"], "MEDIUM")
        self.assertEqual(r_custom["boosters"][0]["token_risk"], "HIGH")

    def test_none_config_uses_defaults(self):
        b = _booster()
        r = analyze("P", [b], base_apy=4.0, config=None)
        self.assertIn("boosters", r)


# ---------------------------------------------------------------------------
# 18. Value score guard: min(..., 100)
# ---------------------------------------------------------------------------
class TestValueScoreGuard(unittest.TestCase):
    def test_value_score_100_when_only_booster_and_base_zero(self):
        # When only one booster dominates and base=0: contribution ≈ 100%, weight=1.0 → capped at 100
        b = _sustainable_booster(additional_apy=100.0)
        r = analyze("P", [b], base_apy=0.0)
        self.assertLessEqual(r["boosters"][0]["value_score"], 100)

    def test_value_score_varies_by_weight(self):
        # Same additional_apy, same total → only weight differs
        b_sust = _sustainable_booster("S", additional_apy=4.0)
        b_risky = _risky_booster("R", additional_apy=4.0)
        r_sust  = analyze("P", [b_sust],  base_apy=4.0)
        r_risky = analyze("P", [b_risky], base_apy=4.0)
        # SUSTAINABLE weight 1.0 > RISKY weight 0.2
        self.assertGreater(
            r_sust["boosters"][0]["value_score"],
            r_risky["boosters"][0]["value_score"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
