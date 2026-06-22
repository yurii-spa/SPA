"""
Tests for MP-778: ProtocolTVLFilter
spa_core/tests/test_protocol_tvl_filter.py

≥ 65 tests covering:
  - filter_protocols() stateless function
  - ProtocolTVLFilter class (filter, qualified, rejection summary)
  - tvl_quality_score computation
  - Ring-buffer log (cap 100)
  - Atomic write (tmp + os.replace)
  - Edge cases: empty input, zero TVL, exact boundary values
  - Criteria override
  - Multiple rejection reasons
"""

import json
import os
import sys
import tempfile
import unittest

# Allow running from project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from spa_core.analytics.protocol_tvl_filter import (
    DEFAULT_MAX_TVL_DROP_30D_PCT,
    DEFAULT_MAX_TVL_DROP_7D_PCT,
    DEFAULT_MIN_TVL_USD,
    LOG_MAX_ENTRIES,
    ProtocolTVLFilter,
    _atomic_write,
    _compute_tvl_quality_score,
    _load_log,
    filter_protocols,
)
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol(
    name: str = "TestProtocol",
    tvl_usd: float = 50_000_000.0,
    tvl_7d: float = 0.0,
    tvl_30d: float = 0.0,
    chain: str = "ethereum",
    category: str = "lending",
) -> dict:
    return {
        "protocol": name,
        "tvl_usd": tvl_usd,
        "tvl_7d_change_pct": tvl_7d,
        "tvl_30d_change_pct": tvl_30d,
        "chain": chain,
        "category": category,
    }


# ---------------------------------------------------------------------------
# 1. tvl_quality_score
# ---------------------------------------------------------------------------

class TestTVLQualityScore(unittest.TestCase):

    def test_perfect_score_large_tvl_no_drop(self):
        score = _compute_tvl_quality_score(10_000_000_000, 0.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=1)

    def test_score_bounded_max_100(self):
        score = _compute_tvl_quality_score(1_000_000_000_000, 10.0, 10.0)
        self.assertLessEqual(score, 100.0)

    def test_score_bounded_min_0(self):
        score = _compute_tvl_quality_score(0, -100.0, -100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_zero_tvl_gives_zero_size_component(self):
        # Only stability score possible; but at max drops → 0 total
        score = _compute_tvl_quality_score(0, -20.0, -40.0)
        self.assertAlmostEqual(score, 0.0, places=1)

    def test_score_1m_tvl_stable(self):
        # $1M → size=0; stable → 50 stability
        score = _compute_tvl_quality_score(1_000_000, 0.0, 0.0)
        self.assertAlmostEqual(score, 50.0, places=1)

    def test_score_10b_tvl_stable(self):
        score = _compute_tvl_quality_score(10_000_000_000, 0.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=1)

    def test_score_decreases_with_7d_drop(self):
        s0 = _compute_tvl_quality_score(100_000_000, 0.0, 0.0)
        s1 = _compute_tvl_quality_score(100_000_000, -10.0, 0.0)
        self.assertGreater(s0, s1)

    def test_score_decreases_with_30d_drop(self):
        s0 = _compute_tvl_quality_score(100_000_000, 0.0, 0.0)
        s1 = _compute_tvl_quality_score(100_000_000, 0.0, -20.0)
        self.assertGreater(s0, s1)

    def test_score_positive_change_same_as_zero(self):
        # Positive gains don't add beyond max stability
        s0 = _compute_tvl_quality_score(100_000_000, 0.0, 0.0)
        s1 = _compute_tvl_quality_score(100_000_000, 5.0, 10.0)
        self.assertAlmostEqual(s0, s1, places=2)

    def test_score_at_exact_7d_threshold(self):
        # At exactly -20% 7d drop: score_7d = 0
        score = _compute_tvl_quality_score(100_000_000, -20.0, 0.0)
        # size ~= 50*(log10(100M)-6)/4 = 50*(8-6)/4 = 25; 30d=25; 7d=0 → 50
        self.assertAlmostEqual(score, 50.0, places=1)

    def test_score_at_exact_30d_threshold(self):
        score = _compute_tvl_quality_score(100_000_000, 0.0, -40.0)
        # size=25; 7d=25; 30d=0 → 50
        self.assertAlmostEqual(score, 50.0, places=1)

    def test_score_is_float(self):
        score = _compute_tvl_quality_score(50_000_000, -5.0, -10.0)
        self.assertIsInstance(score, float)

    def test_score_midsize_tvl(self):
        # $100M: log10=8, size=50*(8-6)/4=25
        score = _compute_tvl_quality_score(100_000_000, 0.0, 0.0)
        self.assertAlmostEqual(score, 75.0, places=1)  # 25 + 25 + 25


# ---------------------------------------------------------------------------
# 2. filter_protocols() — stateless function
# ---------------------------------------------------------------------------

class TestFilterProtocolsFunction(unittest.TestCase):

    def test_returns_dict_keys(self):
        result = filter_protocols([])
        required_keys = {
            "passed_protocols", "rejected_protocols",
            "pass_rate_pct", "avg_tvl_of_passed",
            "criteria_used", "timestamp_utc", "total_evaluated",
        }
        self.assertTrue(required_keys.issubset(result.keys()))

    def test_empty_input_pass_rate_zero(self):
        result = filter_protocols([])
        self.assertEqual(result["pass_rate_pct"], 0.0)
        self.assertEqual(result["total_evaluated"], 0)
        self.assertEqual(result["avg_tvl_of_passed"], 0.0)

    def test_all_pass(self):
        protocols = [
            _make_protocol("A", tvl_usd=50_000_000),
            _make_protocol("B", tvl_usd=100_000_000),
        ]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["passed_protocols"]), 2)
        self.assertEqual(len(result["rejected_protocols"]), 0)
        self.assertAlmostEqual(result["pass_rate_pct"], 100.0)

    def test_low_tvl_rejected(self):
        protocols = [_make_protocol("Tiny", tvl_usd=1_000_000)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["rejected_protocols"]), 1)
        self.assertIn("tvl_usd", result["rejected_protocols"][0]["rejection_reason"])

    def test_7d_drop_rejected(self):
        protocols = [_make_protocol("Crashing", tvl_usd=50_000_000, tvl_7d=-25.0)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["rejected_protocols"]), 1)
        reason = result["rejected_protocols"][0]["rejection_reason"]
        self.assertIn("tvl_7d_change_pct", reason)

    def test_30d_drop_rejected(self):
        protocols = [_make_protocol("Sinking", tvl_usd=50_000_000, tvl_30d=-50.0)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["rejected_protocols"]), 1)
        reason = result["rejected_protocols"][0]["rejection_reason"]
        self.assertIn("tvl_30d_change_pct", reason)

    def test_multiple_rejection_reasons(self):
        protocols = [_make_protocol("Bad", tvl_usd=500_000, tvl_7d=-30.0, tvl_30d=-60.0)]
        result = filter_protocols(protocols)
        reason = result["rejected_protocols"][0]["rejection_reason"]
        self.assertIn("tvl_usd", reason)
        self.assertIn("tvl_7d_change_pct", reason)
        self.assertIn("tvl_30d_change_pct", reason)

    def test_pass_rate_calculation(self):
        protocols = [
            _make_protocol("A", tvl_usd=50_000_000),
            _make_protocol("B", tvl_usd=500_000),   # fails TVL
        ]
        result = filter_protocols(protocols)
        self.assertAlmostEqual(result["pass_rate_pct"], 50.0)

    def test_avg_tvl_of_passed(self):
        protocols = [
            _make_protocol("A", tvl_usd=100_000_000),
            _make_protocol("B", tvl_usd=200_000_000),
        ]
        result = filter_protocols(protocols)
        self.assertAlmostEqual(result["avg_tvl_of_passed"], 150_000_000.0)

    def test_avg_tvl_zero_when_none_pass(self):
        protocols = [_make_protocol("Bad", tvl_usd=500_000)]
        result = filter_protocols(protocols)
        self.assertEqual(result["avg_tvl_of_passed"], 0.0)

    def test_tvl_quality_score_added_to_each_protocol(self):
        protocols = [_make_protocol("A", tvl_usd=50_000_000)]
        result = filter_protocols(protocols)
        passed = result["passed_protocols"]
        self.assertIn("tvl_quality_score", passed[0])

    def test_tvl_quality_score_in_rejected_too(self):
        protocols = [_make_protocol("Bad", tvl_usd=500_000)]
        result = filter_protocols(protocols)
        rejected = result["rejected_protocols"]
        self.assertIn("tvl_quality_score", rejected[0])

    def test_criteria_override_min_tvl(self):
        protocols = [_make_protocol("Mid", tvl_usd=5_000_000)]
        # Default would reject (< $10M), but custom allows $1M+
        result = filter_protocols(protocols, criteria={"min_tvl_usd": 1_000_000})
        self.assertEqual(len(result["passed_protocols"]), 1)

    def test_criteria_override_7d_drop(self):
        protocols = [_make_protocol("Dropping", tvl_usd=50_000_000, tvl_7d=-15.0)]
        # Default max_drop_7d=-20%; tighter custom: -10%
        result = filter_protocols(protocols, criteria={"max_tvl_drop_7d_pct": -10.0})
        self.assertEqual(len(result["rejected_protocols"]), 1)

    def test_criteria_override_30d_drop(self):
        protocols = [_make_protocol("TrendDown", tvl_usd=50_000_000, tvl_30d=-35.0)]
        result = filter_protocols(protocols, criteria={"max_tvl_drop_30d_pct": -30.0})
        self.assertEqual(len(result["rejected_protocols"]), 1)

    def test_exact_min_tvl_boundary_passes(self):
        # Exactly at min_tvl_usd should pass
        protocols = [_make_protocol("Exact", tvl_usd=DEFAULT_MIN_TVL_USD)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["passed_protocols"]), 1)

    def test_just_below_min_tvl_rejected(self):
        protocols = [_make_protocol("Below", tvl_usd=DEFAULT_MIN_TVL_USD - 1)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["rejected_protocols"]), 1)

    def test_exact_7d_boundary_passes(self):
        # Exactly at DEFAULT_MAX_TVL_DROP_7D_PCT should NOT trigger rejection
        protocols = [_make_protocol("Edge7d", tvl_usd=50_000_000, tvl_7d=DEFAULT_MAX_TVL_DROP_7D_PCT)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["passed_protocols"]), 1)

    def test_just_below_7d_boundary_rejected(self):
        protocols = [_make_protocol("Under7d", tvl_usd=50_000_000, tvl_7d=DEFAULT_MAX_TVL_DROP_7D_PCT - 0.01)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["rejected_protocols"]), 1)

    def test_timestamp_utc_present(self):
        result = filter_protocols([])
        self.assertIn("timestamp_utc", result)
        self.assertIsInstance(result["timestamp_utc"], float)
        self.assertGreater(result["timestamp_utc"], 0)

    def test_criteria_used_in_result(self):
        result = filter_protocols([], criteria={"min_tvl_usd": 5_000_000})
        self.assertEqual(result["criteria_used"]["min_tvl_usd"], 5_000_000)

    def test_original_dict_not_mutated(self):
        p = _make_protocol("A", tvl_usd=50_000_000)
        original_keys = set(p.keys())
        filter_protocols([p])
        self.assertEqual(set(p.keys()), original_keys)

    def test_chain_and_category_preserved_in_passed(self):
        p = _make_protocol("A", tvl_usd=50_000_000, chain="polygon", category="amm")
        result = filter_protocols([p])
        passed = result["passed_protocols"][0]
        self.assertEqual(passed["chain"], "polygon")
        self.assertEqual(passed["category"], "amm")

    def test_mixed_batch(self):
        protocols = [
            _make_protocol("Good1", tvl_usd=100_000_000),
            _make_protocol("Good2", tvl_usd=500_000_000),
            _make_protocol("Bad1", tvl_usd=1_000_000),
            _make_protocol("Bad2", tvl_usd=50_000_000, tvl_7d=-30.0),
        ]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["passed_protocols"]), 2)
        self.assertEqual(len(result["rejected_protocols"]), 2)
        self.assertEqual(result["total_evaluated"], 4)


# ---------------------------------------------------------------------------
# 3. ProtocolTVLFilter class
# ---------------------------------------------------------------------------

class TestProtocolTVLFilterClass(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.f = ProtocolTVLFilter(data_dir=self.tmpdir)

    def test_filter_protocols_returns_result(self):
        protocols = [_make_protocol("A", tvl_usd=50_000_000)]
        result = self.f.filter_protocols(protocols)
        self.assertIn("passed_protocols", result)

    def test_get_qualified_protocols_empty_before_filter(self):
        self.assertEqual(self.f.get_qualified_protocols(), [])

    def test_get_qualified_protocols_after_filter(self):
        protocols = [
            _make_protocol("A", tvl_usd=50_000_000),
            _make_protocol("B", tvl_usd=500_000),
        ]
        self.f.filter_protocols(protocols)
        qualified = self.f.get_qualified_protocols()
        self.assertEqual(len(qualified), 1)
        self.assertEqual(qualified[0]["protocol"], "A")

    def test_get_rejection_summary_before_filter(self):
        summary = self.f.get_rejection_summary()
        self.assertEqual(summary["rejected_count"], 0)
        self.assertEqual(summary["rejection_reasons"], [])
        self.assertEqual(summary["pass_rate_pct"], 0.0)

    def test_get_rejection_summary_after_filter(self):
        protocols = [
            _make_protocol("A", tvl_usd=50_000_000),
            _make_protocol("Bad", tvl_usd=500_000),
        ]
        self.f.filter_protocols(protocols)
        summary = self.f.get_rejection_summary()
        self.assertEqual(summary["rejected_count"], 1)
        self.assertEqual(len(summary["rejection_reasons"]), 1)
        self.assertEqual(summary["rejection_reasons"][0]["protocol"], "Bad")
        self.assertAlmostEqual(summary["pass_rate_pct"], 50.0)

    def test_save_creates_log_file(self):
        self.f.filter_protocols([_make_protocol("A", tvl_usd=50_000_000)])
        log_path = self.f.save()
        self.assertTrue(os.path.exists(log_path))

    def test_save_log_is_valid_json(self):
        self.f.filter_protocols([_make_protocol("A", tvl_usd=50_000_000)])
        log_path = self.f.save()
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_save_appends_entry(self):
        self.f.filter_protocols([_make_protocol("A", tvl_usd=50_000_000)])
        self.f.save()
        self.f.filter_protocols([_make_protocol("B", tvl_usd=100_000_000)])
        log_path = self.f.save()
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_save_without_filter_raises(self):
        with self.assertRaises(SPAError):
            self.f.save()

    def test_run_and_save_combined(self):
        protocols = [_make_protocol("A", tvl_usd=50_000_000)]
        result = self.f.run_and_save(protocols)
        self.assertIn("passed_protocols", result)
        log_path = os.path.join(self.tmpdir, "protocol_tvl_filter_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_criteria_passed_to_filter(self):
        protocols = [_make_protocol("Mid", tvl_usd=5_000_000)]
        self.f.filter_protocols(protocols, criteria={"min_tvl_usd": 1_000_000})
        qualified = self.f.get_qualified_protocols()
        self.assertEqual(len(qualified), 1)

    def test_filter_overwrites_previous_result(self):
        self.f.filter_protocols([_make_protocol("A", tvl_usd=50_000_000)])
        self.f.filter_protocols([_make_protocol("Bad", tvl_usd=100)])
        qualified = self.f.get_qualified_protocols()
        self.assertEqual(len(qualified), 0)


# ---------------------------------------------------------------------------
# 4. Ring-buffer cap
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_ring_buffer_capped_at_100(self):
        f = ProtocolTVLFilter(data_dir=self.tmpdir)
        protocols = [_make_protocol("A", tvl_usd=50_000_000)]
        # Write 110 entries
        for i in range(110):
            f.filter_protocols(protocols)
            f.save()
        log_path = os.path.join(self.tmpdir, "protocol_tvl_filter_log.json")
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)

    def test_ring_buffer_keeps_last_entries(self):
        f = ProtocolTVLFilter(data_dir=self.tmpdir)
        # First 5 with 1 protocol, then 100 more with 2
        for i in range(5):
            f.filter_protocols([_make_protocol(f"A{i}", tvl_usd=50_000_000)])
            f.save()
        for i in range(100):
            f.filter_protocols([
                _make_protocol("X", tvl_usd=50_000_000),
                _make_protocol("Y", tvl_usd=100_000_000),
            ])
            f.save()
        log_path = os.path.join(self.tmpdir, "protocol_tvl_filter_log.json")
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)
        # All remaining entries should have 2 passed protocols
        for entry in data:
            self.assertEqual(entry["total_evaluated"], 2)

    def test_ring_buffer_exactly_100_no_trim(self):
        f = ProtocolTVLFilter(data_dir=self.tmpdir)
        protocols = [_make_protocol("A", tvl_usd=50_000_000)]
        for i in range(100):
            f.filter_protocols(protocols)
            f.save()
        log_path = os.path.join(self.tmpdir, "protocol_tvl_filter_log.json")
        with open(log_path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)


# ---------------------------------------------------------------------------
# 5. Atomic write helpers
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_atomic_write_creates_file(self):
        path = os.path.join(self.tmpdir, "test.json")
        _atomic_write(path, [{"key": "value"}])
        self.assertTrue(os.path.exists(path))

    def test_atomic_write_no_tmp_leftover(self):
        path = os.path.join(self.tmpdir, "test.json")
        _atomic_write(path, [])
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_atomic_write_valid_json(self):
        path = os.path.join(self.tmpdir, "test.json")
        payload = [{"a": 1}, {"b": 2}]
        _atomic_write(path, payload)
        with open(path, "r") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, payload)

    def test_atomic_write_overwrites(self):
        path = os.path.join(self.tmpdir, "test.json")
        _atomic_write(path, [1, 2, 3])
        _atomic_write(path, [4, 5])
        with open(path, "r") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, [4, 5])

    def test_atomic_write_creates_parent_dir(self):
        path = os.path.join(self.tmpdir, "sub", "dir", "test.json")
        _atomic_write(path, [])
        self.assertTrue(os.path.exists(path))

    def test_load_log_returns_empty_for_nonexistent(self):
        result = _load_log(os.path.join(self.tmpdir, "nonexistent.json"))
        self.assertEqual(result, [])

    def test_load_log_returns_empty_for_invalid_json(self):
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "w") as fh:
            fh.write("NOT JSON {{{{")
        result = _load_log(path)
        self.assertEqual(result, [])

    def test_load_log_returns_empty_for_non_list_json(self):
        path = os.path.join(self.tmpdir, "obj.json")
        with open(path, "w") as fh:
            json.dump({"key": "val"}, fh)
        result = _load_log(path)
        self.assertEqual(result, [])

    def test_load_log_reads_list(self):
        path = os.path.join(self.tmpdir, "log.json")
        payload = [{"x": 1}, {"y": 2}]
        with open(path, "w") as fh:
            json.dump(payload, fh)
        result = _load_log(path)
        self.assertEqual(result, payload)


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_zero_tvl_rejected(self):
        protocols = [_make_protocol("Zero", tvl_usd=0.0)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["rejected_protocols"]), 1)

    def test_negative_tvl_rejected(self):
        protocols = [_make_protocol("Neg", tvl_usd=-1_000)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["rejected_protocols"]), 1)

    def test_large_tvl_passes(self):
        protocols = [_make_protocol("Huge", tvl_usd=100_000_000_000)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["passed_protocols"]), 1)

    def test_7d_positive_gain_passes(self):
        protocols = [_make_protocol("Gaining", tvl_usd=50_000_000, tvl_7d=10.0)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["passed_protocols"]), 1)

    def test_30d_positive_gain_passes(self):
        protocols = [_make_protocol("Gaining30", tvl_usd=50_000_000, tvl_30d=15.0)]
        result = filter_protocols(protocols)
        self.assertEqual(len(result["passed_protocols"]), 1)

    def test_single_protocol_all_pass(self):
        protocols = [_make_protocol("Solo", tvl_usd=500_000_000)]
        result = filter_protocols(protocols)
        self.assertAlmostEqual(result["pass_rate_pct"], 100.0)

    def test_single_protocol_all_fail(self):
        protocols = [_make_protocol("Tiny", tvl_usd=100)]
        result = filter_protocols(protocols)
        self.assertAlmostEqual(result["pass_rate_pct"], 0.0)

    def test_rejection_reason_is_string(self):
        protocols = [_make_protocol("Bad", tvl_usd=100)]
        result = filter_protocols(protocols)
        self.assertIsInstance(result["rejected_protocols"][0]["rejection_reason"], str)

    def test_quality_score_between_0_and_100(self):
        cases = [
            (0, -100, -100),
            (1_000_000, 0, 0),
            (100_000_000, -10, -20),
            (10_000_000_000, 5, 10),
        ]
        for tvl, c7, c30 in cases:
            score = _compute_tvl_quality_score(tvl, c7, c30)
            self.assertGreaterEqual(score, 0.0, f"Score={score} for {tvl},{c7},{c30}")
            self.assertLessEqual(score, 100.0, f"Score={score} for {tvl},{c7},{c30}")

    def test_empty_criteria_uses_defaults(self):
        protocols = [_make_protocol("A", tvl_usd=50_000_000)]
        result1 = filter_protocols(protocols, criteria={})
        result2 = filter_protocols(protocols)
        self.assertEqual(result1["passed_protocols"][0]["protocol"],
                         result2["passed_protocols"][0]["protocol"])

    def test_protocol_name_preserved_in_rejected(self):
        protocols = [_make_protocol("SpecialName", tvl_usd=100)]
        result = filter_protocols(protocols)
        self.assertEqual(result["rejected_protocols"][0]["protocol"], "SpecialName")

    def test_multiple_protocols_avg_tvl_correct(self):
        protocols = [
            _make_protocol("A", tvl_usd=40_000_000),
            _make_protocol("B", tvl_usd=60_000_000),
            _make_protocol("C", tvl_usd=100_000_000),
        ]
        result = filter_protocols(protocols)
        expected_avg = (40_000_000 + 60_000_000 + 100_000_000) / 3
        self.assertAlmostEqual(result["avg_tvl_of_passed"], expected_avg, places=0)

    def test_total_evaluated_includes_all(self):
        protocols = [
            _make_protocol("A", tvl_usd=50_000_000),
            _make_protocol("B", tvl_usd=100),
            _make_protocol("C", tvl_usd=200_000_000, tvl_7d=-30.0),
        ]
        result = filter_protocols(protocols)
        self.assertEqual(result["total_evaluated"], 3)

    def test_default_constants_values(self):
        self.assertEqual(DEFAULT_MIN_TVL_USD, 10_000_000.0)
        self.assertEqual(DEFAULT_MAX_TVL_DROP_7D_PCT, -20.0)
        self.assertEqual(DEFAULT_MAX_TVL_DROP_30D_PCT, -40.0)
        self.assertEqual(LOG_MAX_ENTRIES, 100)


if __name__ == "__main__":
    unittest.main()
