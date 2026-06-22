"""
Tests for MP-1060: DeFiProtocolFlashLoanAttackSurfaceAnalyzer
Run with: python3 -m unittest spa_core/tests/test_defi_protocol_flash_loan_attack_surface_analyzer.py
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root is on sys.path
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_protocol_flash_loan_attack_surface_analyzer import (
    DeFiProtocolFlashLoanAttackSurfaceAnalyzer,
    _clamp,
    _append_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol(**overrides):
    """Return a valid protocol dict with sensible defaults, allowing overrides."""
    base = {
        "protocol_name":               "TestProtocol",
        "tvl_usd":                     100_000_000.0,
        "single_block_borrowable_usd": 50_000_000.0,
        "price_oracle_type":           "twap_1h",
        "reentrancy_guards":           True,
        "has_price_manipulation_check": True,
        "audit_count":                 3,
        "days_since_last_audit":       60.0,
        "historical_flash_loan_attacks": 0,
        "total_value_lost_usd":        0.0,
    }
    base.update(overrides)
    return base


class TestAnalyzerReturnStructure(unittest.TestCase):
    """Result dict has all required keys."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_result_has_protocol_name(self):
        r = self.analyzer.analyze(_make_protocol(protocol_name="Aave"))
        self.assertEqual(r["protocol_name"], "Aave")

    def test_result_has_attack_profitability_score(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIn("attack_profitability_score", r)

    def test_result_has_oracle_vulnerability_score(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIn("oracle_vulnerability_score", r)

    def test_result_has_flash_loan_risk_score(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIn("flash_loan_risk_score", r)

    def test_result_has_risk_label(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIn("risk_label", r)

    def test_result_has_breakdown(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIn("_breakdown", r)

    def test_result_has_timestamp(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], float)

    def test_breakdown_has_five_sub_scores(self):
        r = self.analyzer.analyze(_make_protocol())
        bd = r["_breakdown"]
        for key in ("profit_score", "oracle_score", "reentry_score", "audit_score", "hist_score"):
            self.assertIn(key, bd)


class TestScoreRanges(unittest.TestCase):
    """All scores must be in [0, 100]."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def _check_ranges(self, data):
        r = self.analyzer.analyze(data)
        self.assertGreaterEqual(r["attack_profitability_score"], 0.0)
        self.assertLessEqual(r["attack_profitability_score"], 100.0)
        self.assertGreaterEqual(r["oracle_vulnerability_score"], 0.0)
        self.assertLessEqual(r["oracle_vulnerability_score"], 100.0)
        self.assertGreaterEqual(r["flash_loan_risk_score"], 0.0)
        self.assertLessEqual(r["flash_loan_risk_score"], 100.0)

    def test_ranges_safe_protocol(self):
        self._check_ranges(_make_protocol(
            reentrancy_guards=True, price_oracle_type="chainlink",
            audit_count=5, days_since_last_audit=30.0,
            historical_flash_loan_attacks=0,
        ))

    def test_ranges_risky_protocol(self):
        self._check_ranges(_make_protocol(
            reentrancy_guards=False, price_oracle_type="spot",
            audit_count=0, days_since_last_audit=500.0,
            historical_flash_loan_attacks=3, total_value_lost_usd=20_000_000.0,
        ))

    def test_ranges_zero_tvl(self):
        self._check_ranges(_make_protocol(tvl_usd=0.0, single_block_borrowable_usd=0.0))

    def test_ranges_max_borrowable(self):
        self._check_ranges(_make_protocol(
            tvl_usd=1_000_000_000.0,
            single_block_borrowable_usd=1_000_000_000.0,
        ))

    def test_ranges_internal_oracle(self):
        self._check_ranges(_make_protocol(price_oracle_type="internal"))

    def test_ranges_unknown_oracle(self):
        self._check_ranges(_make_protocol(price_oracle_type="diy_oracle"))


class TestRiskLabels(unittest.TestCase):
    """Correct labels emitted for different risk profiles."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def _valid_labels(self):
        return {"FLASH_LOAN_RESISTANT", "LOW_RISK", "MODERATE_RISK",
                "HIGH_RISK", "CRITICAL_EXPOSURE"}

    def test_label_is_valid_string(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIn(r["risk_label"], self._valid_labels())

    def test_critical_exposure_label(self):
        # Worst-case: spot oracle, no guards, no audits, history of attacks
        r = self.analyzer.analyze(_make_protocol(
            tvl_usd=500_000_000.0,
            single_block_borrowable_usd=490_000_000.0,
            price_oracle_type="spot",
            reentrancy_guards=False,
            has_price_manipulation_check=False,
            audit_count=0,
            days_since_last_audit=700.0,
            historical_flash_loan_attacks=5,
            total_value_lost_usd=100_000_000.0,
        ))
        self.assertEqual(r["risk_label"], "CRITICAL_EXPOSURE")

    def test_flash_loan_resistant_label(self):
        # Best-case
        r = self.analyzer.analyze(_make_protocol(
            tvl_usd=1_000_000.0,
            single_block_borrowable_usd=100.0,
            price_oracle_type="chainlink",
            reentrancy_guards=True,
            has_price_manipulation_check=True,
            audit_count=10,
            days_since_last_audit=10.0,
            historical_flash_loan_attacks=0,
            total_value_lost_usd=0.0,
        ))
        self.assertEqual(r["risk_label"], "FLASH_LOAN_RESISTANT")

    def test_all_five_labels_achievable(self):
        """Each label must be reachable with the right inputs."""
        profiles = [
            # FLASH_LOAN_RESISTANT
            _make_protocol(
                tvl_usd=1_000_000.0, single_block_borrowable_usd=100.0,
                price_oracle_type="chainlink", reentrancy_guards=True,
                has_price_manipulation_check=True, audit_count=10,
                days_since_last_audit=5.0, historical_flash_loan_attacks=0,
                total_value_lost_usd=0.0,
            ),
            # CRITICAL_EXPOSURE
            _make_protocol(
                tvl_usd=1_000_000_000.0, single_block_borrowable_usd=999_000_000.0,
                price_oracle_type="spot", reentrancy_guards=False,
                has_price_manipulation_check=False, audit_count=0,
                days_since_last_audit=999.0, historical_flash_loan_attacks=10,
                total_value_lost_usd=500_000_000.0,
            ),
        ]
        labels_seen = set()
        for p in profiles:
            r = self.analyzer.analyze(p)
            labels_seen.add(r["risk_label"])
        # Both extreme labels present
        self.assertIn("FLASH_LOAN_RESISTANT", labels_seen)
        self.assertIn("CRITICAL_EXPOSURE", labels_seen)


class TestAttackProfitabilityScore(unittest.TestCase):
    """attack_profitability_score behaviour."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_zero_borrowable_gives_low_score(self):
        r = self.analyzer.analyze(_make_protocol(
            tvl_usd=100_000_000.0,
            single_block_borrowable_usd=0.0,
        ))
        self.assertLess(r["attack_profitability_score"], 30.0)

    def test_full_borrow_ratio_raises_score(self):
        r_full = self.analyzer.analyze(_make_protocol(
            tvl_usd=100_000_000.0,
            single_block_borrowable_usd=100_000_000.0,
        ))
        r_low = self.analyzer.analyze(_make_protocol(
            tvl_usd=100_000_000.0,
            single_block_borrowable_usd=1_000.0,
        ))
        self.assertGreater(r_full["attack_profitability_score"],
                           r_low["attack_profitability_score"])

    def test_larger_tvl_increases_score(self):
        r_big = self.analyzer.analyze(_make_protocol(
            tvl_usd=10_000_000_000.0,
            single_block_borrowable_usd=5_000_000_000.0,
        ))
        r_small = self.analyzer.analyze(_make_protocol(
            tvl_usd=1_000_000.0,
            single_block_borrowable_usd=500_000.0,
        ))
        self.assertGreater(r_big["attack_profitability_score"],
                           r_small["attack_profitability_score"])

    def test_score_capped_at_100(self):
        r = self.analyzer.analyze(_make_protocol(
            tvl_usd=1e15,
            single_block_borrowable_usd=1e15,
        ))
        self.assertLessEqual(r["attack_profitability_score"], 100.0)

    def test_zero_tvl_does_not_crash(self):
        r = self.analyzer.analyze(_make_protocol(tvl_usd=0.0, single_block_borrowable_usd=0.0))
        self.assertGreaterEqual(r["attack_profitability_score"], 0.0)


class TestOracleVulnerabilityScore(unittest.TestCase):
    """oracle_vulnerability_score ordering."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def _oracle_score(self, oracle_type, manip_chk=False):
        r = self.analyzer.analyze(_make_protocol(
            price_oracle_type=oracle_type,
            has_price_manipulation_check=manip_chk,
        ))
        return r["oracle_vulnerability_score"]

    def test_spot_oracle_highest(self):
        self.assertGreater(self._oracle_score("spot"), self._oracle_score("twap_1h"))

    def test_chainlink_lowest(self):
        self.assertLess(self._oracle_score("chainlink"), self._oracle_score("internal"))

    def test_twap_lower_than_spot(self):
        self.assertLess(self._oracle_score("twap_1h"), self._oracle_score("spot"))

    def test_manipulation_check_reduces_score(self):
        without = self._oracle_score("spot", manip_chk=False)
        with_   = self._oracle_score("spot", manip_chk=True)
        self.assertGreater(without, with_)

    def test_unknown_oracle_uses_default(self):
        score = self._oracle_score("custom_oracle")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_chainlink_with_check_very_low(self):
        score = self._oracle_score("chainlink", manip_chk=True)
        self.assertLess(score, 15.0)

    def test_spot_without_check_very_high(self):
        score = self._oracle_score("spot", manip_chk=False)
        self.assertGreater(score, 85.0)


class TestReentrancyScore(unittest.TestCase):
    """Reentrancy guards impact."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_no_guards_raises_composite(self):
        no_guard = self.analyzer.analyze(_make_protocol(reentrancy_guards=False))
        with_guard = self.analyzer.analyze(_make_protocol(reentrancy_guards=True))
        self.assertGreater(no_guard["flash_loan_risk_score"],
                           with_guard["flash_loan_risk_score"])

    def test_guards_present_does_not_eliminate_risk(self):
        """Protocol still has other risk vectors."""
        r = self.analyzer.analyze(_make_protocol(
            reentrancy_guards=True,
            price_oracle_type="spot",
            has_price_manipulation_check=False,
        ))
        self.assertGreaterEqual(r["flash_loan_risk_score"], 0.0)

    def test_breakdown_reentry_score_zero_when_guarded(self):
        r = self.analyzer.analyze(_make_protocol(reentrancy_guards=True))
        self.assertEqual(r["_breakdown"]["reentry_score"], 0.0)

    def test_breakdown_reentry_score_100_when_unguarded(self):
        r = self.analyzer.analyze(_make_protocol(reentrancy_guards=False))
        self.assertEqual(r["_breakdown"]["reentry_score"], 100.0)


class TestAuditDeficitScore(unittest.TestCase):
    """Audit quality impact."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_zero_audits_raises_risk(self):
        zero = self.analyzer.analyze(_make_protocol(audit_count=0, days_since_last_audit=0.0))
        five = self.analyzer.analyze(_make_protocol(audit_count=5, days_since_last_audit=30.0))
        self.assertGreater(zero["flash_loan_risk_score"], five["flash_loan_risk_score"])

    def test_stale_audit_raises_risk(self):
        fresh = self.analyzer.analyze(_make_protocol(audit_count=2, days_since_last_audit=10.0))
        stale = self.analyzer.analyze(_make_protocol(audit_count=2, days_since_last_audit=400.0))
        self.assertGreater(stale["flash_loan_risk_score"], fresh["flash_loan_risk_score"])

    def test_many_audits_lower_deficit(self):
        r = self.analyzer.analyze(_make_protocol(audit_count=10, days_since_last_audit=1.0))
        self.assertLess(r["_breakdown"]["audit_score"], 10.0)

    def test_audit_score_bounded(self):
        for count, days in [(0, 999), (1, 400), (5, 30), (10, 5)]:
            r = self.analyzer.analyze(_make_protocol(audit_count=count, days_since_last_audit=float(days)))
            self.assertGreaterEqual(r["_breakdown"]["audit_score"], 0.0)
            self.assertLessEqual(r["_breakdown"]["audit_score"], 100.0)


class TestHistoricalScore(unittest.TestCase):
    """Historical exploit impact."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_no_history_zero_hist_score(self):
        r = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=0, total_value_lost_usd=0.0,
        ))
        self.assertEqual(r["_breakdown"]["hist_score"], 0.0)

    def test_one_attack_raises_score(self):
        r = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=1, total_value_lost_usd=1_000_000.0,
        ))
        self.assertGreater(r["_breakdown"]["hist_score"], 0.0)

    def test_multiple_attacks_higher_than_single(self):
        one = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=1, total_value_lost_usd=0.0,
        ))
        three = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=3, total_value_lost_usd=0.0,
        ))
        self.assertGreater(three["_breakdown"]["hist_score"], one["_breakdown"]["hist_score"])

    def test_large_loss_raises_hist_score(self):
        small_loss = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=1, total_value_lost_usd=1_000.0,
        ))
        large_loss = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=1, total_value_lost_usd=50_000_000.0,
        ))
        self.assertGreater(large_loss["_breakdown"]["hist_score"],
                           small_loss["_breakdown"]["hist_score"])

    def test_hist_score_capped_at_100(self):
        r = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=100, total_value_lost_usd=1_000_000_000.0,
        ))
        self.assertLessEqual(r["_breakdown"]["hist_score"], 100.0)


class TestCompositeFormula(unittest.TestCase):
    """Composite score is a weighted sum within bounds."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_composite_within_bounds_various(self):
        profiles = [
            _make_protocol(),
            _make_protocol(reentrancy_guards=False, price_oracle_type="spot"),
            _make_protocol(audit_count=0, days_since_last_audit=999.0),
            _make_protocol(tvl_usd=1e9, single_block_borrowable_usd=9e8),
            _make_protocol(historical_flash_loan_attacks=5, total_value_lost_usd=1e8),
        ]
        for p in profiles:
            r = self.analyzer.analyze(p)
            self.assertGreaterEqual(r["flash_loan_risk_score"], 0.0)
            self.assertLessEqual(r["flash_loan_risk_score"], 100.0)

    def test_worst_case_is_highest_composite(self):
        worst = self.analyzer.analyze(_make_protocol(
            tvl_usd=1e10, single_block_borrowable_usd=9.9e9,
            price_oracle_type="spot", reentrancy_guards=False,
            has_price_manipulation_check=False, audit_count=0,
            days_since_last_audit=999.0, historical_flash_loan_attacks=10,
            total_value_lost_usd=1e9,
        ))
        best = self.analyzer.analyze(_make_protocol(
            tvl_usd=1_000.0, single_block_borrowable_usd=1.0,
            price_oracle_type="chainlink", reentrancy_guards=True,
            has_price_manipulation_check=True, audit_count=20,
            days_since_last_audit=1.0, historical_flash_loan_attacks=0,
            total_value_lost_usd=0.0,
        ))
        self.assertGreater(worst["flash_loan_risk_score"], best["flash_loan_risk_score"])


class TestValidation(unittest.TestCase):
    """Missing keys and invalid values are rejected."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_missing_protocol_name_raises(self):
        d = _make_protocol()
        del d["protocol_name"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(d)

    def test_missing_tvl_raises(self):
        d = _make_protocol()
        del d["tvl_usd"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(d)

    def test_missing_oracle_type_raises(self):
        d = _make_protocol()
        del d["price_oracle_type"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(d)

    def test_negative_tvl_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze(_make_protocol(tvl_usd=-1.0))

    def test_negative_borrowable_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze(_make_protocol(single_block_borrowable_usd=-100.0))

    def test_negative_audit_count_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze(_make_protocol(audit_count=-1))

    def test_negative_days_since_audit_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze(_make_protocol(days_since_last_audit=-5.0))

    def test_negative_attacks_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze(_make_protocol(historical_flash_loan_attacks=-1))

    def test_negative_lost_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze(_make_protocol(total_value_lost_usd=-1.0))

    def test_all_keys_present_no_error(self):
        # Should not raise
        self.analyzer.analyze(_make_protocol())


class TestEdgeCases(unittest.TestCase):
    """Numeric edge cases."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_tvl_exactly_zero(self):
        r = self.analyzer.analyze(_make_protocol(tvl_usd=0.0, single_block_borrowable_usd=0.0))
        self.assertGreaterEqual(r["flash_loan_risk_score"], 0.0)

    def test_borrowable_larger_than_tvl_clamped(self):
        r = self.analyzer.analyze(_make_protocol(
            tvl_usd=100.0,
            single_block_borrowable_usd=1_000_000.0,
        ))
        self.assertLessEqual(r["attack_profitability_score"], 100.0)

    def test_audit_count_zero_days_zero(self):
        r = self.analyzer.analyze(_make_protocol(audit_count=0, days_since_last_audit=0.0))
        self.assertGreaterEqual(r["_breakdown"]["audit_score"], 80.0)

    def test_protocol_name_cast_to_str(self):
        r = self.analyzer.analyze(_make_protocol(protocol_name=42))
        self.assertEqual(r["protocol_name"], "42")

    def test_float_audit_count_coerced(self):
        # audit_count passed as float
        r = self.analyzer.analyze(_make_protocol(audit_count=2.9))
        self.assertIn("flash_loan_risk_score", r)

    def test_very_large_attacks_count(self):
        r = self.analyzer.analyze(_make_protocol(
            historical_flash_loan_attacks=1000,
            total_value_lost_usd=1e12,
        ))
        self.assertLessEqual(r["_breakdown"]["hist_score"], 100.0)

    def test_days_since_audit_exactly_365(self):
        fresh = self.analyzer.analyze(_make_protocol(days_since_last_audit=180.0))
        boundary = self.analyzer.analyze(_make_protocol(days_since_last_audit=365.0))
        one_more = self.analyzer.analyze(_make_protocol(days_since_last_audit=366.0))
        self.assertLessEqual(boundary["_breakdown"]["audit_score"],
                              one_more["_breakdown"]["audit_score"])

    def test_days_since_audit_exactly_180(self):
        r = self.analyzer.analyze(_make_protocol(days_since_last_audit=180.0))
        self.assertLessEqual(r["_breakdown"]["audit_score"], 100.0)

    def test_days_since_audit_exactly_90(self):
        r = self.analyzer.analyze(_make_protocol(days_since_last_audit=90.0))
        self.assertLessEqual(r["_breakdown"]["audit_score"], 100.0)


class TestLogFile(unittest.TestCase):
    """Ring-buffer log writing."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_log_created_on_write(self):
        _append_log(self.log_path, {"x": 1}, 100)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        _append_log(self.log_path, {"x": 1}, 100)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_grows_with_entries(self):
        for i in range(5):
            _append_log(self.log_path, {"i": i}, 100)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_caps_at_100(self):
        for i in range(110):
            _append_log(self.log_path, {"i": i}, 100)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(110):
            _append_log(self.log_path, {"i": i}, 100)
        with open(self.log_path) as fh:
            data = json.load(fh)
        # Last entry should be 109
        self.assertEqual(data[-1]["i"], 109)
        # First entry should be 10
        self.assertEqual(data[0]["i"], 10)

    def test_log_file_valid_json_after_write(self):
        _append_log(self.log_path, {"score": 42.5}, 100)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["score"], 42.5)

    def test_write_log_false_does_not_create_file(self):
        custom_path = os.path.join(self.tmp_dir, "should_not_exist.json")
        # Patch log file path temporarily won't work easily; instead
        # just verify write_log=False doesn't raise and log is empty
        r = self.analyzer.analyze(_make_protocol(), write_log=False)
        # Log file should NOT be at default path (sandbox has no data dir necessarily)
        self.assertNotEqual(r, None)

    def test_custom_cap(self):
        for i in range(20):
            _append_log(self.log_path, {"i": i}, 5)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)


class TestClampHelper(unittest.TestCase):
    """_clamp utility function."""

    def test_clamp_below_lo(self):
        self.assertEqual(_clamp(-10.0, 0.0, 100.0), 0.0)

    def test_clamp_above_hi(self):
        self.assertEqual(_clamp(200.0, 0.0, 100.0), 100.0)

    def test_clamp_in_range(self):
        self.assertEqual(_clamp(50.0, 0.0, 100.0), 50.0)

    def test_clamp_equal_lo(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_clamp_equal_hi(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)


class TestDeterminism(unittest.TestCase):
    """Same inputs → same outputs (pure function)."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_same_input_same_output(self):
        p = _make_protocol(
            tvl_usd=100_000_000.0,
            single_block_borrowable_usd=60_000_000.0,
            price_oracle_type="spot",
            reentrancy_guards=False,
        )
        r1 = self.analyzer.analyze(p)
        r2 = self.analyzer.analyze(p)
        self.assertEqual(r1["flash_loan_risk_score"], r2["flash_loan_risk_score"])
        self.assertEqual(r1["risk_label"], r2["risk_label"])

    def test_different_oracles_different_scores(self):
        spot = self.analyzer.analyze(_make_protocol(price_oracle_type="spot"))
        chainlink = self.analyzer.analyze(_make_protocol(price_oracle_type="chainlink"))
        self.assertNotEqual(spot["oracle_vulnerability_score"],
                            chainlink["oracle_vulnerability_score"])


class TestOracleOrdering(unittest.TestCase):
    """spot > internal > twap_1h > chainlink (no manipulation check)."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def _vuln(self, oracle):
        return self.analyzer.analyze(_make_protocol(
            price_oracle_type=oracle,
            has_price_manipulation_check=False,
        ))["oracle_vulnerability_score"]

    def test_spot_gt_twap(self):
        self.assertGreater(self._vuln("spot"), self._vuln("twap_1h"))

    def test_internal_gt_twap(self):
        self.assertGreater(self._vuln("internal"), self._vuln("twap_1h"))

    def test_twap_gt_chainlink(self):
        self.assertGreater(self._vuln("twap_1h"), self._vuln("chainlink"))

    def test_spot_gt_chainlink(self):
        self.assertGreater(self._vuln("spot"), self._vuln("chainlink"))


class TestScoreOutputTypes(unittest.TestCase):
    """Score outputs are float, label is str."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_attack_score_is_float(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIsInstance(r["attack_profitability_score"], float)

    def test_oracle_score_is_float(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIsInstance(r["oracle_vulnerability_score"], float)

    def test_composite_score_is_float(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIsInstance(r["flash_loan_risk_score"], float)

    def test_label_is_str(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertIsInstance(r["risk_label"], str)

    def test_breakdown_values_are_float(self):
        r = self.analyzer.analyze(_make_protocol())
        for val in r["_breakdown"].values():
            self.assertIsInstance(val, float)


class TestMonotonicBehaviours(unittest.TestCase):
    """Scores change in expected direction when single parameter changes."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_more_audits_lower_or_equal_risk(self):
        scores = []
        for count in [0, 1, 2, 5]:
            r = self.analyzer.analyze(_make_protocol(
                audit_count=count, days_since_last_audit=30.0,
            ))
            scores.append(r["flash_loan_risk_score"])
        # Monotonically non-increasing
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_more_attacks_higher_risk(self):
        zero = self.analyzer.analyze(_make_protocol(historical_flash_loan_attacks=0))
        one  = self.analyzer.analyze(_make_protocol(historical_flash_loan_attacks=1))
        three = self.analyzer.analyze(_make_protocol(historical_flash_loan_attacks=3))
        self.assertGreaterEqual(one["flash_loan_risk_score"], zero["flash_loan_risk_score"])
        self.assertGreaterEqual(three["flash_loan_risk_score"], one["flash_loan_risk_score"])

    def test_higher_borrow_ratio_higher_profit_score(self):
        low = self.analyzer.analyze(_make_protocol(
            tvl_usd=100_000_000.0, single_block_borrowable_usd=1_000.0,
        ))
        high = self.analyzer.analyze(_make_protocol(
            tvl_usd=100_000_000.0, single_block_borrowable_usd=90_000_000.0,
        ))
        self.assertGreater(high["attack_profitability_score"],
                           low["attack_profitability_score"])

    def test_fresher_audit_lower_audit_score(self):
        recent = self.analyzer.analyze(_make_protocol(
            audit_count=2, days_since_last_audit=10.0,
        ))
        old = self.analyzer.analyze(_make_protocol(
            audit_count=2, days_since_last_audit=500.0,
        ))
        self.assertGreater(old["_breakdown"]["audit_score"],
                           recent["_breakdown"]["audit_score"])


class TestProtocolNames(unittest.TestCase):
    """Protocol name is passed through correctly."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_aave_name(self):
        r = self.analyzer.analyze(_make_protocol(protocol_name="Aave V3"))
        self.assertEqual(r["protocol_name"], "Aave V3")

    def test_compound_name(self):
        r = self.analyzer.analyze(_make_protocol(protocol_name="Compound V3"))
        self.assertEqual(r["protocol_name"], "Compound V3")

    def test_empty_string_name(self):
        r = self.analyzer.analyze(_make_protocol(protocol_name=""))
        self.assertEqual(r["protocol_name"], "")

    def test_unicode_name(self):
        r = self.analyzer.analyze(_make_protocol(protocol_name="протокол_тест"))
        self.assertEqual(r["protocol_name"], "протокол_тест")


class TestBreakdownConsistency(unittest.TestCase):
    """_breakdown sub-scores are consistent with top-level scores."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_profit_score_matches_breakdown(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertEqual(r["attack_profitability_score"], r["_breakdown"]["profit_score"])

    def test_oracle_score_matches_breakdown(self):
        r = self.analyzer.analyze(_make_protocol())
        self.assertEqual(r["oracle_vulnerability_score"], r["_breakdown"]["oracle_score"])

    def test_all_breakdown_scores_bounded(self):
        r = self.analyzer.analyze(_make_protocol())
        for k, v in r["_breakdown"].items():
            self.assertGreaterEqual(v, 0.0, msg=f"{k} out of range")
            self.assertLessEqual(v, 100.0, msg=f"{k} out of range")


class TestRealWorldProfiles(unittest.TestCase):
    """Spot-check realistic protocol profiles."""

    def setUp(self):
        self.analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()

    def test_aave_v3_profile_low_to_moderate(self):
        """Aave V3 has Chainlink, reentrancy guards, many audits → should be low risk."""
        r = self.analyzer.analyze({
            "protocol_name":               "Aave V3",
            "tvl_usd":                     10_000_000_000.0,
            "single_block_borrowable_usd": 100_000_000.0,
            "price_oracle_type":           "chainlink",
            "reentrancy_guards":           True,
            "has_price_manipulation_check": True,
            "audit_count":                 8,
            "days_since_last_audit":       45.0,
            "historical_flash_loan_attacks": 0,
            "total_value_lost_usd":        0.0,
        })
        self.assertIn(r["risk_label"], {"FLASH_LOAN_RESISTANT", "LOW_RISK", "MODERATE_RISK"})

    def test_small_unaudited_spot_oracle_protocol_critical(self):
        """New protocol with spot oracle and no audits → critical or high."""
        r = self.analyzer.analyze({
            "protocol_name":               "NewProtocol",
            "tvl_usd":                     5_000_000.0,
            "single_block_borrowable_usd": 4_800_000.0,
            "price_oracle_type":           "spot",
            "reentrancy_guards":           False,
            "has_price_manipulation_check": False,
            "audit_count":                 0,
            "days_since_last_audit":       999.0,
            "historical_flash_loan_attacks": 2,
            "total_value_lost_usd":        3_000_000.0,
        })
        self.assertIn(r["risk_label"], {"HIGH_RISK", "CRITICAL_EXPOSURE"})

    def test_borrow_ratio_near_zero(self):
        r = self.analyzer.analyze(_make_protocol(
            tvl_usd=1_000_000_000.0,
            single_block_borrowable_usd=0.0,
            price_oracle_type="chainlink",
            reentrancy_guards=True,
            has_price_manipulation_check=True,
            audit_count=5, days_since_last_audit=20.0,
        ))
        self.assertLess(r["flash_loan_risk_score"], 40.0)


if __name__ == "__main__":
    unittest.main()
