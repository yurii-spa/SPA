"""
Tests for MP-784: YieldCompressorScore
≥65 unit tests, stdlib unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.yield_compressor_score import (
    LOG_CAP,
    REGIME_COMPRESSING,
    REGIME_EXPANDING,
    REGIME_SEVERELY_COMPRESSED,
    REGIME_STABLE,
    YieldCompressorScore,
    _atomic_append,
)
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROTO_A = {"protocol": "Aave", "apy_30d_ago": 4.0, "apy_now": 3.0, "tvl_usd": 8_000_000, "category": "lending"}
PROTO_B = {"protocol": "Compound", "apy_30d_ago": 6.0, "apy_now": 5.0, "tvl_usd": 6_000_000, "category": "lending"}
PROTO_C = {"protocol": "Morpho", "apy_30d_ago": 8.0, "apy_now": 6.5, "tvl_usd": 5_000_000, "category": "vault"}
PROTO_FLAT = {"protocol": "Flat", "apy_30d_ago": 5.0, "apy_now": 5.0, "tvl_usd": 3_000_000, "category": "lending"}
PROTO_EXPAND = {"protocol": "Expand", "apy_30d_ago": 3.0, "apy_now": 5.0, "tvl_usd": 2_000_000, "category": "lending"}


def _scorer(**kw) -> YieldCompressorScore:
    return YieldCompressorScore(**kw)


class TestYieldCompressorScoreBasic(unittest.TestCase):
    # --- T001 ---
    def test_compute_returns_dict(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertIsInstance(r, dict)

    # --- T002 ---
    def test_compute_has_per_protocol(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertIn("per_protocol", r)

    # --- T003 ---
    def test_compute_has_market(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertIn("market", r)

    # --- T004 ---
    def test_compute_has_outliers(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertIn("outliers", r)

    # --- T005 ---
    def test_compute_has_timestamp(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertIn("timestamp", r)

    # --- T006 ---
    def test_per_protocol_count(self):
        s = _scorer()
        r = s.compute([PROTO_A, PROTO_B, PROTO_C])
        self.assertEqual(len(r["per_protocol"]), 3)

    # --- T007 ---
    def test_per_protocol_fields(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        p = r["per_protocol"][0]
        for field in ("protocol", "apy_30d_ago", "apy_now", "tvl_usd", "category",
                      "compression_pct", "compression_rate_per_day"):
            self.assertIn(field, p)

    # --- T008 ---
    def test_compression_pct_formula(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        # (4.0 - 3.0)/4.0 * 100 = 25.0
        self.assertAlmostEqual(r["per_protocol"][0]["compression_pct"], 25.0, places=3)

    # --- T009 ---
    def test_compression_rate_per_day_formula(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertAlmostEqual(r["per_protocol"][0]["compression_rate_per_day"], 25.0 / 30.0, places=5)

    # --- T010 ---
    def test_compression_zero_when_flat(self):
        s = _scorer()
        r = s.compute([PROTO_FLAT])
        self.assertAlmostEqual(r["per_protocol"][0]["compression_pct"], 0.0, places=4)

    # --- T011 ---
    def test_compression_negative_when_expanding(self):
        s = _scorer()
        r = s.compute([PROTO_EXPAND])
        self.assertLess(r["per_protocol"][0]["compression_pct"], 0.0)

    # --- T012 ---
    def test_apy_zero_ago_no_crash(self):
        s = _scorer()
        proto = {"protocol": "X", "apy_30d_ago": 0.0, "apy_now": 3.0, "tvl_usd": 1_000_000, "category": "lend"}
        r = s.compute([proto])
        self.assertAlmostEqual(r["per_protocol"][0]["compression_pct"], 0.0, places=4)

    # --- T013 ---
    def test_market_avg_compression_pct_present(self):
        s = _scorer()
        r = s.compute([PROTO_A, PROTO_B])
        self.assertIn("avg_compression_pct", r["market"])

    # --- T014 ---
    def test_market_compression_score_present(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertIn("market_compression_score", r["market"])

    # --- T015 ---
    def test_market_compression_score_range(self):
        s = _scorer()
        r = s.compute([PROTO_A, PROTO_B, PROTO_C])
        score = r["market"]["market_compression_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    # --- T016 ---
    def test_regime_in_market(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertIn("compression_regime", r["market"])

    # --- T017 ---
    def test_protocol_count_in_market(self):
        s = _scorer()
        r = s.compute([PROTO_A, PROTO_B])
        self.assertEqual(r["market"]["protocol_count"], 2)

    # --- T018 ---
    def test_empty_protocols_returns_valid(self):
        s = _scorer()
        r = s.compute([])
        self.assertEqual(r["per_protocol"], [])
        self.assertEqual(r["market"]["protocol_count"], 0)

    # --- T019 ---
    def test_empty_outliers_is_list(self):
        s = _scorer()
        r = s.compute([])
        self.assertIsInstance(r["outliers"], list)


class TestYieldCompressorRegimes(unittest.TestCase):
    # --- T020 ---
    def test_regime_expanding(self):
        # All expanding → avg compression < 0 → score < 50 → check
        s = _scorer()
        protos = [
            {"protocol": f"P{i}", "apy_30d_ago": 2.0, "apy_now": 8.0, "tvl_usd": 1e6, "category": "x"}
            for i in range(5)
        ]
        r = s.compute(protos)
        self.assertIn(r["market"]["compression_regime"],
                      [REGIME_EXPANDING, REGIME_STABLE])

    # --- T021 ---
    def test_regime_severely_compressed(self):
        # Very high compression → score → SEVERELY_COMPRESSED
        s = _scorer()
        protos = [
            {"protocol": f"P{i}", "apy_30d_ago": 20.0, "apy_now": 2.0, "tvl_usd": 1e6, "category": "x"}
            for i in range(5)
        ]
        r = s.compute(protos)
        self.assertEqual(r["market"]["compression_regime"], REGIME_SEVERELY_COMPRESSED)

    # --- T022 ---
    def test_regime_compressing_moderate(self):
        # avg ~20% compression → score ~60 → COMPRESSING
        s = _scorer()
        protos = [
            {"protocol": f"P{i}", "apy_30d_ago": 10.0, "apy_now": 8.0, "tvl_usd": 1e6, "category": "x"}
            for i in range(4)
        ]
        r = s.compute(protos)
        # 20% compression → score = 50 + 20*0.5 = 60 → COMPRESSING
        self.assertEqual(r["market"]["compression_regime"], REGIME_COMPRESSING)

    # --- T023 ---
    def test_regime_stable_zero(self):
        s = _scorer()
        r = s.compute([PROTO_FLAT])
        # 0% compression → score = 50 → STABLE
        self.assertEqual(r["market"]["compression_regime"], REGIME_STABLE)

    # --- T024 ---
    def test_score_to_regime_boundaries(self):
        from spa_core.analytics.yield_compressor_score import YieldCompressorScore as Y
        self.assertEqual(Y._score_to_regime(0.0), REGIME_EXPANDING)
        self.assertEqual(Y._score_to_regime(24.9), REGIME_EXPANDING)
        self.assertEqual(Y._score_to_regime(25.0), REGIME_STABLE)
        self.assertEqual(Y._score_to_regime(49.9), REGIME_STABLE)
        self.assertEqual(Y._score_to_regime(50.0), REGIME_COMPRESSING)
        self.assertEqual(Y._score_to_regime(75.0), REGIME_COMPRESSING)
        self.assertEqual(Y._score_to_regime(75.1), REGIME_SEVERELY_COMPRESSED)
        self.assertEqual(Y._score_to_regime(100.0), REGIME_SEVERELY_COMPRESSED)

    # --- T025 ---
    def test_get_market_regime_before_compute(self):
        s = _scorer()
        self.assertEqual(s.get_market_regime(), REGIME_STABLE)

    # --- T026 ---
    def test_get_market_regime_after_compute(self):
        s = _scorer()
        s.compute([PROTO_FLAT])
        self.assertEqual(s.get_market_regime(), REGIME_STABLE)

    # --- T027 ---
    def test_get_market_regime_expanding_case(self):
        s = _scorer()
        protos = [{"protocol": "X", "apy_30d_ago": 2.0, "apy_now": 50.0, "tvl_usd": 1e6, "category": "x"}]
        s.compute(protos)
        self.assertEqual(s.get_market_regime(), REGIME_EXPANDING)


class TestYieldCompressorOutliers(unittest.TestCase):
    # --- T028 ---
    def test_outliers_detected_when_one_dominates(self):
        s = _scorer()
        protos = [
            {"protocol": "Normal1", "apy_30d_ago": 5.0, "apy_now": 4.8, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Normal2", "apy_30d_ago": 5.0, "apy_now": 4.8, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Big", "apy_30d_ago": 10.0, "apy_now": 1.0, "tvl_usd": 1e6, "category": "x"},
        ]
        r = s.compute(protos)
        outlier_names = [o["protocol"] for o in r["outliers"]]
        self.assertIn("Big", outlier_names)

    # --- T029 ---
    def test_no_outliers_when_all_equal(self):
        s = _scorer()
        protos = [
            {"protocol": f"P{i}", "apy_30d_ago": 5.0, "apy_now": 4.0, "tvl_usd": 1e6, "category": "x"}
            for i in range(4)
        ]
        r = s.compute(protos)
        self.assertEqual(r["outliers"], [])

    # --- T030 ---
    def test_get_compressed_outliers_before_compute(self):
        s = _scorer()
        self.assertEqual(s.get_compressed_outliers(), [])

    # --- T031 ---
    def test_get_compressed_outliers_after_compute(self):
        s = _scorer()
        protos = [
            {"protocol": "Normal", "apy_30d_ago": 5.0, "apy_now": 4.8, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Spike", "apy_30d_ago": 10.0, "apy_now": 0.5, "tvl_usd": 1e6, "category": "x"},
        ]
        s.compute(protos)
        out = s.get_compressed_outliers()
        self.assertIsInstance(out, list)

    # --- T032 ---
    def test_outlier_fields(self):
        s = _scorer()
        protos = [
            {"protocol": "N", "apy_30d_ago": 5.0, "apy_now": 4.9, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Spike", "apy_30d_ago": 10.0, "apy_now": 0.1, "tvl_usd": 1e6, "category": "x"},
        ]
        r = s.compute(protos)
        if r["outliers"]:
            o = r["outliers"][0]
            self.assertIn("protocol", o)
            self.assertIn("compression_pct", o)
            self.assertIn("vs_market_avg", o)

    # --- T033 ---
    def test_no_outliers_when_all_expanding(self):
        s = _scorer()
        protos = [
            {"protocol": f"P{i}", "apy_30d_ago": 3.0, "apy_now": 6.0, "tvl_usd": 1e6, "category": "x"}
            for i in range(3)
        ]
        r = s.compute(protos)
        # avg < 0 → outlier threshold logic → no outliers
        self.assertEqual(r["outliers"], [])


class TestYieldCompressorPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- T034 ---
    def test_save_before_compute_raises(self):
        s = YieldCompressorScore(data_dir=self.tmpdir)
        with self.assertRaises(SPAError):
            s.save()

    # --- T035 ---
    def test_save_creates_file(self):
        s = YieldCompressorScore(data_dir=self.tmpdir)
        s.compute([PROTO_A])
        s.save()
        path = os.path.join(self.tmpdir, "yield_compressor_log.json")
        self.assertTrue(os.path.exists(path))

    # --- T036 ---
    def test_save_returns_path(self):
        s = YieldCompressorScore(data_dir=self.tmpdir)
        s.compute([PROTO_A])
        path = s.save()
        self.assertIsInstance(path, str)
        self.assertTrue(os.path.exists(path))

    # --- T037 ---
    def test_save_content_is_list(self):
        s = YieldCompressorScore(data_dir=self.tmpdir)
        s.compute([PROTO_A])
        s.save()
        path = os.path.join(self.tmpdir, "yield_compressor_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    # --- T038 ---
    def test_save_appends_multiple_entries(self):
        s = YieldCompressorScore(data_dir=self.tmpdir)
        s.compute([PROTO_A])
        s.save()
        s.compute([PROTO_B])
        s.save()
        path = os.path.join(self.tmpdir, "yield_compressor_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    # --- T039 ---
    def test_ring_buffer_caps_at_100(self):
        s = YieldCompressorScore(data_dir=self.tmpdir)
        for i in range(110):
            s.compute([PROTO_A])
            s.save()
        path = os.path.join(self.tmpdir, "yield_compressor_log.json")
        with open(path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    # --- T040 ---
    def test_save_with_data_dir_arg(self):
        s = YieldCompressorScore()
        s.compute([PROTO_A])
        path = s.save(data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(path))

    # --- T041 ---
    def test_atomic_append_helper(self):
        path = os.path.join(self.tmpdir, "test_log.json")
        _atomic_append(path, {"x": 1}, cap=5)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    # --- T042 ---
    def test_atomic_append_caps(self):
        path = os.path.join(self.tmpdir, "test_log.json")
        for i in range(10):
            _atomic_append(path, {"i": i}, cap=5)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    # --- T043 ---
    def test_atomic_append_recovers_corrupt_file(self):
        path = os.path.join(self.tmpdir, "corrupt.json")
        with open(path, "w") as f:
            f.write("NOT_JSON{{")
        _atomic_append(path, {"ok": True}, cap=10)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"ok": True}])

    # --- T044 ---
    def test_save_overwrites_non_list_log(self):
        path = os.path.join(self.tmpdir, "yield_compressor_log.json")
        with open(path, "w") as f:
            json.dump({"bad": "data"}, f)
        s = YieldCompressorScore(data_dir=self.tmpdir)
        s.compute([PROTO_A])
        s.save()
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


class TestYieldCompressorMultipleProtocols(unittest.TestCase):
    # --- T045 ---
    def test_avg_compression_across_protocols(self):
        s = _scorer()
        protos = [
            {"protocol": "A", "apy_30d_ago": 10.0, "apy_now": 8.0, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "B", "apy_30d_ago": 10.0, "apy_now": 9.0, "tvl_usd": 1e6, "category": "x"},
        ]
        r = s.compute(protos)
        # A: 20%, B: 10% → avg = 15%
        self.assertAlmostEqual(r["market"]["avg_compression_pct"], 15.0, places=3)

    # --- T046 ---
    def test_single_protocol_avg_equals_its_own(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertAlmostEqual(
            r["market"]["avg_compression_pct"],
            r["per_protocol"][0]["compression_pct"],
            places=3,
        )

    # --- T047 ---
    def test_large_batch_no_crash(self):
        s = _scorer()
        protos = [
            {"protocol": f"P{i}", "apy_30d_ago": float(i+1), "apy_now": float(i), "tvl_usd": 1e6, "category": "x"}
            for i in range(1, 50)
        ]
        r = s.compute(protos)
        self.assertEqual(len(r["per_protocol"]), 49)

    # --- T048 ---
    def test_protocol_names_preserved(self):
        s = _scorer()
        r = s.compute([PROTO_A, PROTO_B])
        names = [p["protocol"] for p in r["per_protocol"]]
        self.assertIn("Aave", names)
        self.assertIn("Compound", names)

    # --- T049 ---
    def test_categories_preserved(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertEqual(r["per_protocol"][0]["category"], "lending")

    # --- T050 ---
    def test_tvl_preserved(self):
        s = _scorer()
        r = s.compute([PROTO_A])
        self.assertAlmostEqual(r["per_protocol"][0]["tvl_usd"], 8_000_000.0, places=0)

    # --- T051 ---
    def test_compute_updates_last_result(self):
        s = _scorer()
        s.compute([PROTO_A])
        self.assertIsNotNone(s._last_result)
        s.compute([PROTO_B])
        self.assertEqual(s._last_result["per_protocol"][0]["protocol"], "Compound")

    # --- T052 ---
    def test_score_clamp_lower(self):
        s = _scorer()
        # APY tripled → big negative compression → score clamps to 0
        protos = [{"protocol": "X", "apy_30d_ago": 1.0, "apy_now": 100.0, "tvl_usd": 1e6, "category": "x"}]
        r = s.compute(protos)
        self.assertGreaterEqual(r["market"]["market_compression_score"], 0.0)

    # --- T053 ---
    def test_score_clamp_upper(self):
        s = _scorer()
        # APY collapses to near zero → huge compression → score clamps to 100
        protos = [{"protocol": "X", "apy_30d_ago": 100.0, "apy_now": 0.001, "tvl_usd": 1e6, "category": "x"}]
        r = s.compute(protos)
        self.assertLessEqual(r["market"]["market_compression_score"], 100.0)

    # --- T054 ---
    def test_missing_fields_fallback(self):
        s = _scorer()
        r = s.compute([{"protocol": "Bare"}])
        self.assertEqual(len(r["per_protocol"]), 1)
        self.assertAlmostEqual(r["per_protocol"][0]["compression_pct"], 0.0)

    # --- T055 ---
    def test_float_precision_roundtrip(self):
        s = _scorer()
        p = {"protocol": "Prec", "apy_30d_ago": 7.777, "apy_now": 5.555, "tvl_usd": 1e6, "category": "x"}
        r = s.compute([p])
        # Verify no exception and value is finite
        self.assertTrue(abs(r["per_protocol"][0]["compression_pct"]) < 1000)

    # --- T056 ---
    def test_negative_apy_ago_handled(self):
        s = _scorer()
        p = {"protocol": "Neg", "apy_30d_ago": -2.0, "apy_now": 1.0, "tvl_usd": 1e6, "category": "x"}
        r = s.compute([p])
        self.assertIsInstance(r["per_protocol"][0]["compression_pct"], float)

    # --- T057 ---
    def test_zero_tvl_no_crash(self):
        s = _scorer()
        p = {"protocol": "Z", "apy_30d_ago": 5.0, "apy_now": 4.0, "tvl_usd": 0.0, "category": "x"}
        r = s.compute([p])
        self.assertEqual(len(r["per_protocol"]), 1)

    # --- T058 ---
    def test_mixed_compressed_and_expanding(self):
        s = _scorer()
        protos = [
            {"protocol": "Comp", "apy_30d_ago": 10.0, "apy_now": 5.0, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Exp",  "apy_30d_ago": 3.0,  "apy_now": 8.0, "tvl_usd": 1e6, "category": "x"},
        ]
        r = s.compute(protos)
        # Avg: (50 + -166.67) / 2 ~ negative → EXPANDING
        self.assertIsInstance(r["market"]["compression_regime"], str)

    # --- T059 ---
    def test_regime_constants_are_strings(self):
        self.assertIsInstance(REGIME_EXPANDING, str)
        self.assertIsInstance(REGIME_STABLE, str)
        self.assertIsInstance(REGIME_COMPRESSING, str)
        self.assertIsInstance(REGIME_SEVERELY_COMPRESSED, str)

    # --- T060 ---
    def test_regime_constants_distinct(self):
        regimes = {REGIME_EXPANDING, REGIME_STABLE, REGIME_COMPRESSING, REGIME_SEVERELY_COMPRESSED}
        self.assertEqual(len(regimes), 4)

    # --- T061 ---
    def test_log_cap_constant(self):
        self.assertEqual(LOG_CAP, 100)

    # --- T062 ---
    def test_compression_pct_exact_half(self):
        s = _scorer()
        p = {"protocol": "H", "apy_30d_ago": 10.0, "apy_now": 5.0, "tvl_usd": 1e6, "category": "x"}
        r = s.compute([p])
        self.assertAlmostEqual(r["per_protocol"][0]["compression_pct"], 50.0, places=3)

    # --- T063 ---
    def test_compute_empty_outliers_list_type(self):
        s = _scorer()
        r = s.compute([PROTO_FLAT])
        self.assertIsInstance(r["outliers"], list)

    # --- T064 ---
    def test_multiple_outliers_all_included(self):
        # 3 near-flat + 2 heavily compressed: avg ~(2+2+2+95+97.5)/5 ≈ 39.7%
        # threshold = 79.4%; Big1=95% and Big2=97.5% both exceed → 2 outliers
        s = _scorer()
        protos = [
            {"protocol": "Tiny1", "apy_30d_ago": 5.0, "apy_now": 4.9, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Tiny2", "apy_30d_ago": 5.0, "apy_now": 4.9, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Tiny3", "apy_30d_ago": 5.0, "apy_now": 4.9, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Big1", "apy_30d_ago": 10.0, "apy_now": 0.5, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Big2", "apy_30d_ago": 20.0, "apy_now": 0.5, "tvl_usd": 1e6, "category": "x"},
        ]
        r = s.compute(protos)
        outlier_names = [o["protocol"] for o in r["outliers"]]
        self.assertGreaterEqual(len(outlier_names), 1)
        self.assertIn("Big1", outlier_names)
        self.assertIn("Big2", outlier_names)

    # --- T065 ---
    def test_compute_idempotent_second_call(self):
        s = _scorer()
        r1 = s.compute([PROTO_A])
        r2 = s.compute([PROTO_A])
        self.assertEqual(
            r1["per_protocol"][0]["compression_pct"],
            r2["per_protocol"][0]["compression_pct"],
        )

    # --- T066 ---
    def test_outlier_vs_market_avg_field(self):
        s = _scorer()
        protos = [
            {"protocol": "Tiny", "apy_30d_ago": 5.0, "apy_now": 4.9, "tvl_usd": 1e6, "category": "x"},
            {"protocol": "Huge", "apy_30d_ago": 10.0, "apy_now": 0.1, "tvl_usd": 1e6, "category": "x"},
        ]
        r = s.compute(protos)
        for o in r["outliers"]:
            self.assertIn("vs_market_avg", o)
            self.assertGreater(o["vs_market_avg"], 0.0)

    # --- T067 ---
    def test_data_dir_passed_to_init(self):
        s = YieldCompressorScore(data_dir="/tmp/test_spa")
        self.assertEqual(s._data_dir, "/tmp/test_spa")


if __name__ == "__main__":
    unittest.main()
