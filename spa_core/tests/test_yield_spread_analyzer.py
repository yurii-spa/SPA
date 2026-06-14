"""
Tests for MP-664 YieldSpreadAnalyzer (spa_core/analytics/yield_spread_analyzer.py)
Pure stdlib unittest — do NOT use pytest or any external deps.
Run: python3 -m unittest spa_core.tests.test_yield_spread_analyzer -v

All persistence tests are tempfile-based; the production data/ directory is
never written.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.yield_spread_analyzer import (  # noqa: E402
    SpreadPoint,
    SpreadReport,
    YieldSpreadAnalyzer,
    _classify_valuation,
    _DEFAULT_BENCHMARK_APY,
    _RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyzer(tmp_dir: str, benchmark=0.045) -> YieldSpreadAnalyzer:
    return YieldSpreadAnalyzer(data_dir=tmp_dir, benchmark_apy=benchmark)


# ===========================================================================
# 1. compute_spread math
# ===========================================================================

class TestComputeSpread(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _make_analyzer(self.tmp)

    def test_basic_positive(self):
        # (0.09 - 0.045) * 10000 = 450
        self.assertAlmostEqual(self.a.compute_spread(0.09, 0.045), 450.0, places=4)

    def test_zero_spread(self):
        self.assertAlmostEqual(self.a.compute_spread(0.045, 0.045), 0.0, places=6)

    def test_negative_spread(self):
        # (0.03 - 0.045) * 10000 = -150
        self.assertAlmostEqual(self.a.compute_spread(0.03, 0.045), -150.0, places=4)

    def test_one_pct_is_100_bps(self):
        self.assertAlmostEqual(self.a.compute_spread(0.055, 0.045), 100.0, places=4)

    def test_high_apy(self):
        self.assertAlmostEqual(self.a.compute_spread(0.50, 0.045), 4550.0, places=4)

    def test_zero_benchmark(self):
        self.assertAlmostEqual(self.a.compute_spread(0.10, 0.0), 1000.0, places=4)

    def test_rounded_to_6dp(self):
        result = self.a.compute_spread(0.0451234567, 0.045)
        self.assertEqual(result, round(result, 6))

    def test_returns_float(self):
        self.assertIsInstance(self.a.compute_spread(0.05, 0.045), float)

    def test_non_numeric_apy_defaults_zero(self):
        # apy "junk" → 0; (0 - 0.045)*10000 = -450
        self.assertAlmostEqual(self.a.compute_spread("junk", 0.045), -450.0, places=4)

    def test_non_numeric_benchmark_defaults_zero(self):
        # benchmark "junk" → 0; (0.05 - 0)*10000 = 500
        self.assertAlmostEqual(self.a.compute_spread(0.05, "junk"), 500.0, places=4)

    def test_negative_apy(self):
        self.assertAlmostEqual(self.a.compute_spread(-0.01, 0.045), -550.0, places=4)

    def test_no_float_drift(self):
        # 0.1 - 0.045 in float would otherwise carry drift; rounding to 6dp tames it
        result = self.a.compute_spread(0.1, 0.045)
        self.assertAlmostEqual(result, 550.0, places=4)


# ===========================================================================
# 2. _classify_valuation boundaries
# ===========================================================================

class TestClassifyValuation(unittest.TestCase):

    def test_rich_above_300(self):
        self.assertEqual(_classify_valuation(301.0), "RICH")

    def test_rich_large(self):
        self.assertEqual(_classify_valuation(5000.0), "RICH")

    def test_fair_at_300_boundary(self):
        # 300 exactly → FAIR (RICH is strictly > 300)
        self.assertEqual(_classify_valuation(300.0), "FAIR")

    def test_fair_mid(self):
        self.assertEqual(_classify_valuation(150.0), "FAIR")

    def test_fair_at_50_boundary(self):
        # 50 exactly → FAIR (inclusive lower bound)
        self.assertEqual(_classify_valuation(50.0), "FAIR")

    def test_thin_just_below_50(self):
        self.assertEqual(_classify_valuation(49.99), "THIN")

    def test_thin_mid(self):
        self.assertEqual(_classify_valuation(25.0), "THIN")

    def test_thin_at_zero_boundary(self):
        # 0 exactly → THIN (inclusive lower bound)
        self.assertEqual(_classify_valuation(0.0), "THIN")

    def test_negative_just_below_zero(self):
        self.assertEqual(_classify_valuation(-0.01), "NEGATIVE")

    def test_negative_large(self):
        self.assertEqual(_classify_valuation(-500.0), "NEGATIVE")

    def test_returns_str(self):
        self.assertIsInstance(_classify_valuation(100.0), str)


# ===========================================================================
# 3. analyze
# ===========================================================================

class TestAnalyze(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _make_analyzer(self.tmp)

    def test_returns_list(self):
        result = self.a.analyze({"aave": 0.06})
        self.assertIsInstance(result, list)

    def test_returns_spread_points(self):
        result = self.a.analyze({"aave": 0.06})
        self.assertIsInstance(result[0], SpreadPoint)

    def test_empty_map(self):
        self.assertEqual(self.a.analyze({}), [])

    def test_sorted_by_adapter(self):
        result = self.a.analyze({"zeta": 0.06, "alpha": 0.06})
        ids = [s.adapter_id for s in result]
        self.assertEqual(ids, sorted(ids))

    def test_spread_computed(self):
        result = self.a.analyze({"aave": 0.09})
        self.assertAlmostEqual(result[0].spread_bps, 450.0, places=4)

    def test_valuation_assigned_rich(self):
        result = self.a.analyze({"aave": 0.09})
        self.assertEqual(result[0].valuation, "RICH")

    def test_valuation_assigned_fair(self):
        result = self.a.analyze({"aave": 0.06})  # +150 bps
        self.assertEqual(result[0].valuation, "FAIR")

    def test_valuation_assigned_thin(self):
        result = self.a.analyze({"aave": 0.047})  # +20 bps
        self.assertEqual(result[0].valuation, "THIN")

    def test_valuation_assigned_negative(self):
        result = self.a.analyze({"aave": 0.03})  # -150 bps
        self.assertEqual(result[0].valuation, "NEGATIVE")

    def test_benchmark_override(self):
        # With benchmark 0.08, apy 0.09 → +100 bps (FAIR), not RICH
        result = self.a.analyze({"aave": 0.09}, benchmark_apy=0.08)
        self.assertAlmostEqual(result[0].spread_bps, 100.0, places=4)
        self.assertEqual(result[0].valuation, "FAIR")

    def test_benchmark_field_set(self):
        result = self.a.analyze({"aave": 0.09})
        self.assertAlmostEqual(result[0].benchmark_apy, 0.045, places=6)

    def test_benchmark_override_field_set(self):
        result = self.a.analyze({"aave": 0.09}, benchmark_apy=0.06)
        self.assertAlmostEqual(result[0].benchmark_apy, 0.06, places=6)

    def test_apy_preserved(self):
        result = self.a.analyze({"aave": 0.0777})
        self.assertAlmostEqual(result[0].apy, 0.0777, places=6)

    def test_non_numeric_apy_defaults_zero(self):
        result = self.a.analyze({"aave": "junk"})
        self.assertEqual(result[0].apy, 0.0)

    def test_non_dict_map_safe(self):
        self.assertEqual(self.a.analyze("not-a-dict"), [])

    def test_timestamp_present(self):
        result = self.a.analyze({"aave": 0.06})
        self.assertTrue(result[0].timestamp)

    def test_bad_benchmark_override_falls_back(self):
        # benchmark override "junk" → falls back to instance benchmark (0.045)
        result = self.a.analyze({"aave": 0.09}, benchmark_apy="junk")
        self.assertAlmostEqual(result[0].benchmark_apy, 0.045, places=6)


# ===========================================================================
# 4. generate_report
# ===========================================================================

class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _make_analyzer(self.tmp)

    def test_report_has_keys(self):
        rep = self.a.generate_report({})
        for k in ("generated_at", "adapter_count", "benchmark_apy", "spreads",
                  "best_spread", "worst_spread", "mean_spread_bps",
                  "valuation_counts", "advisory"):
            self.assertIn(k, rep)

    def test_empty_map_zero_adapters(self):
        rep = self.a.generate_report({})
        self.assertEqual(rep["adapter_count"], 0)
        self.assertEqual(rep["spreads"], [])

    def test_empty_best_worst_mean_none(self):
        rep = self.a.generate_report({})
        self.assertIsNone(rep["best_spread"])
        self.assertIsNone(rep["worst_spread"])
        self.assertIsNone(rep["mean_spread_bps"])

    def test_empty_advisory_clean(self):
        rep = self.a.generate_report({})
        self.assertIn("No adapters", rep["advisory"])

    def test_best_spread_is_max(self):
        # aave +450, comp +150, lossy -150 → best = 450
        rep = self.a.generate_report({"aave": 0.09, "comp": 0.06, "lossy": 0.03})
        self.assertAlmostEqual(rep["best_spread"], 450.0, places=4)

    def test_worst_spread_is_min(self):
        rep = self.a.generate_report({"aave": 0.09, "comp": 0.06, "lossy": 0.03})
        self.assertAlmostEqual(rep["worst_spread"], -150.0, places=4)

    def test_mean_spread(self):
        # (450 + 150 - 150) / 3 = 150
        rep = self.a.generate_report({"aave": 0.09, "comp": 0.06, "lossy": 0.03})
        self.assertAlmostEqual(rep["mean_spread_bps"], 150.0, places=4)

    def test_single_adapter_best_equals_worst(self):
        rep = self.a.generate_report({"aave": 0.09})
        self.assertAlmostEqual(rep["best_spread"], rep["worst_spread"], places=6)

    def test_adapter_count(self):
        rep = self.a.generate_report({"a": 0.06, "b": 0.07, "c": 0.05})
        self.assertEqual(rep["adapter_count"], 3)

    def test_valuation_counts_sum(self):
        rep = self.a.generate_report({"a": 0.09, "b": 0.06, "c": 0.03})
        self.assertEqual(sum(rep["valuation_counts"].values()), 3)

    def test_negative_flagged_in_advisory(self):
        rep = self.a.generate_report({"lossy": 0.03})
        self.assertIn("lossy", rep["advisory"])
        self.assertIn("NEGATIVE", rep["advisory"])

    def test_no_negative_clean_advisory(self):
        rep = self.a.generate_report({"aave": 0.09})
        self.assertIn("No adapters", rep["advisory"])

    def test_benchmark_in_report(self):
        rep = self.a.generate_report({"aave": 0.09})
        self.assertAlmostEqual(rep["benchmark_apy"], 0.045, places=6)

    def test_benchmark_override_in_report(self):
        rep = self.a.generate_report({"aave": 0.09}, benchmark_apy=0.07)
        self.assertAlmostEqual(rep["benchmark_apy"], 0.07, places=6)

    def test_override_affects_spreads(self):
        rep = self.a.generate_report({"aave": 0.09}, benchmark_apy=0.08)
        self.assertAlmostEqual(rep["spreads"][0]["spread_bps"], 100.0, places=4)

    def test_all_valuation_labels_present(self):
        rep = self.a.generate_report({})
        for label in ("RICH", "FAIR", "THIN", "NEGATIVE"):
            self.assertIn(label, rep["valuation_counts"])

    def test_report_json_serialisable(self):
        rep = self.a.generate_report({"a": 0.09, "b": 0.03})
        json.dumps(rep)

    def test_spreads_sorted(self):
        rep = self.a.generate_report({"zeta": 0.06, "alpha": 0.06})
        ids = [s["adapter_id"] for s in rep["spreads"]]
        self.assertEqual(ids, sorted(ids))

    def test_non_dict_map_safe(self):
        rep = self.a.generate_report("not-a-dict")
        self.assertEqual(rep["adapter_count"], 0)


# ===========================================================================
# 5. Persistence (save_report ring-buffer, atomic write)
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _make_analyzer(self.tmp)

    def _out_path(self) -> Path:
        return Path(self.tmp) / "yield_spread_report.json"

    def test_stub_created_on_init(self):
        self.assertTrue(self._out_path().exists())

    def test_stub_is_empty_list(self):
        with open(self._out_path()) as fh:
            self.assertEqual(json.load(fh), [])

    def test_save_creates_file(self):
        self.a.save_report(self.a.generate_report({}))
        self.assertTrue(self._out_path().exists())

    def test_save_appends_entry(self):
        self.a.save_report(self.a.generate_report({}))
        with open(self._out_path()) as fh:
            self.assertEqual(len(json.load(fh)), 1)

    def test_multiple_saves_append(self):
        for _ in range(4):
            self.a.save_report(self.a.generate_report({}))
        with open(self._out_path()) as fh:
            self.assertEqual(len(json.load(fh)), 4)

    def test_ring_buffer_caps(self):
        for _ in range(_RING_BUFFER_MAX + 10):
            self.a.save_report(self.a.generate_report({}))
        with open(self._out_path()) as fh:
            self.assertLessEqual(len(json.load(fh)), _RING_BUFFER_MAX)

    def test_ring_buffer_exactly_max(self):
        for _ in range(_RING_BUFFER_MAX):
            self.a.save_report(self.a.generate_report({}))
        with open(self._out_path()) as fh:
            self.assertEqual(len(json.load(fh)), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_latest_count(self):
        for _ in range(_RING_BUFFER_MAX + 7):
            self.a.save_report(self.a.generate_report({}))
        with open(self._out_path()) as fh:
            self.assertEqual(len(json.load(fh)), _RING_BUFFER_MAX)

    def test_no_tmp_left_behind(self):
        self.a.save_report(self.a.generate_report({}))
        leftover = list(Path(self.tmp).glob("*.tmp")) + list(Path(self.tmp).glob(".tmp*"))
        self.assertEqual(leftover, [])

    def test_save_returns_path(self):
        path = self.a.save_report(self.a.generate_report({}))
        self.assertEqual(path, str(self._out_path()))

    def test_file_valid_json_list(self):
        self.a.save_report(self.a.generate_report({}))
        with open(self._out_path()) as fh:
            self.assertIsInstance(json.load(fh), list)

    def test_corrupt_file_recovered(self):
        with open(self._out_path(), "w") as fh:
            fh.write("CORRUPT {{{")
        self.a.save_report(self.a.generate_report({}))
        with open(self._out_path()) as fh:
            self.assertEqual(len(json.load(fh)), 1)

    def test_production_data_untouched(self):
        prod = _ROOT / "data" / "yield_spread_report.json"
        before = prod.read_text() if prod.exists() else None
        self.a.save_report(self.a.generate_report({}))
        after = prod.read_text() if prod.exists() else None
        self.assertEqual(before, after)


# ===========================================================================
# 6. SpreadPoint dataclass round-trip
# ===========================================================================

class TestSpreadPointDataclass(unittest.TestCase):

    def _make(self):
        return SpreadPoint(
            adapter_id="aave", apy=0.09, benchmark_apy=0.045,
            spread_bps=450.0, valuation="RICH", timestamp="2026-06-13T00:00:00",
        )

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for k in ("adapter_id", "apy", "benchmark_apy", "spread_bps",
                  "valuation", "timestamp"):
            self.assertIn(k, d)

    def test_round_trip(self):
        p = self._make()
        p2 = SpreadPoint.from_dict(p.to_dict())
        self.assertEqual(p2.adapter_id, "aave")
        self.assertEqual(p2.valuation, "RICH")
        self.assertAlmostEqual(p2.apy, 0.09, places=6)
        self.assertAlmostEqual(p2.benchmark_apy, 0.045, places=6)
        self.assertAlmostEqual(p2.spread_bps, 450.0, places=4)

    def test_apy_rounded(self):
        p = SpreadPoint(
            adapter_id="a", apy=0.123456789, benchmark_apy=0.045,
            spread_bps=10.0, valuation="THIN", timestamp="t",
        )
        self.assertEqual(p.to_dict()["apy"], round(0.123456789, 6))

    def test_spread_rounded(self):
        p = SpreadPoint(
            adapter_id="a", apy=0.05, benchmark_apy=0.045,
            spread_bps=49.1234567, valuation="THIN", timestamp="t",
        )
        self.assertEqual(p.to_dict()["spread_bps"], round(49.1234567, 6))

    def test_from_dict_defaults(self):
        p = SpreadPoint.from_dict({})
        self.assertEqual(p.adapter_id, "")
        self.assertEqual(p.apy, 0.0)
        self.assertEqual(p.benchmark_apy, 0.0)
        self.assertEqual(p.spread_bps, 0.0)
        self.assertEqual(p.valuation, "THIN")

    def test_from_dict_bad_values_default(self):
        p = SpreadPoint.from_dict({"apy": "junk", "spread_bps": "junk"})
        self.assertEqual(p.apy, 0.0)
        self.assertEqual(p.spread_bps, 0.0)

    def test_from_dict_coerces_adapter_id(self):
        p = SpreadPoint.from_dict({"adapter_id": 42})
        self.assertEqual(p.adapter_id, "42")


# ===========================================================================
# 7. SpreadReport dataclass round-trip
# ===========================================================================

class TestSpreadReportDataclass(unittest.TestCase):

    def _make(self):
        sp = SpreadPoint(
            adapter_id="aave", apy=0.09, benchmark_apy=0.045,
            spread_bps=450.0, valuation="RICH", timestamp="t",
        )
        return SpreadReport(
            generated_at="2026-06-13T00:00:00",
            spreads=[sp],
            best_spread=450.0,
            worst_spread=450.0,
            mean_spread_bps=450.0,
            advisory="advisory text",
        )

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for k in ("generated_at", "spreads", "best_spread",
                  "worst_spread", "mean_spread_bps", "advisory"):
            self.assertIn(k, d)

    def test_round_trip(self):
        r = self._make()
        r2 = SpreadReport.from_dict(r.to_dict())
        self.assertEqual(r2.generated_at, "2026-06-13T00:00:00")
        self.assertEqual(len(r2.spreads), 1)
        self.assertEqual(r2.spreads[0].adapter_id, "aave")
        self.assertAlmostEqual(r2.best_spread, 450.0, places=4)
        self.assertAlmostEqual(r2.worst_spread, 450.0, places=4)
        self.assertAlmostEqual(r2.mean_spread_bps, 450.0, places=4)

    def test_none_stats_preserved(self):
        r = SpreadReport(
            generated_at="t", spreads=[],
            best_spread=None, worst_spread=None, mean_spread_bps=None,
            advisory="x",
        )
        d = r.to_dict()
        self.assertIsNone(d["best_spread"])
        self.assertIsNone(d["worst_spread"])
        self.assertIsNone(d["mean_spread_bps"])
        r2 = SpreadReport.from_dict(d)
        self.assertIsNone(r2.best_spread)
        self.assertIsNone(r2.worst_spread)
        self.assertIsNone(r2.mean_spread_bps)

    def test_from_dict_defaults(self):
        r = SpreadReport.from_dict({})
        self.assertEqual(r.generated_at, "")
        self.assertEqual(r.spreads, [])
        self.assertIsNone(r.best_spread)

    def test_from_dict_non_list_spreads_safe(self):
        r = SpreadReport.from_dict({"spreads": "not-a-list"})
        self.assertEqual(r.spreads, [])

    def test_from_dict_skips_non_dict_spreads(self):
        r = SpreadReport.from_dict({"spreads": ["bad", {"adapter_id": "ok"}]})
        self.assertEqual(len(r.spreads), 1)
        self.assertEqual(r.spreads[0].adapter_id, "ok")


# ===========================================================================
# 8. Class constants / configuration
# ===========================================================================

class TestClassConstants(unittest.TestCase):

    def test_ring_buffer_size_is_30(self):
        self.assertEqual(YieldSpreadAnalyzer.RING_BUFFER_SIZE, 30)

    def test_module_ring_buffer_is_30(self):
        self.assertEqual(_RING_BUFFER_MAX, 30)

    def test_output_filename(self):
        self.assertEqual(YieldSpreadAnalyzer.OUTPUT_FILE, "yield_spread_report.json")

    def test_default_benchmark_is_0_045(self):
        self.assertAlmostEqual(_DEFAULT_BENCHMARK_APY, 0.045, places=6)

    def test_default_instance_benchmark(self):
        a = YieldSpreadAnalyzer(data_dir=tempfile.mkdtemp())
        self.assertAlmostEqual(a.benchmark_apy, 0.045, places=6)

    def test_custom_benchmark_stored(self):
        a = YieldSpreadAnalyzer(data_dir=tempfile.mkdtemp(), benchmark_apy=0.05)
        self.assertAlmostEqual(a.benchmark_apy, 0.05, places=6)


# ===========================================================================
# 9. Integration-style scenarios
# ===========================================================================

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _make_analyzer(self.tmp)

    def test_full_cycle_generate_and_save(self):
        apy = {"aave": 0.09, "comp": 0.06, "morpho": 0.047, "lossy": 0.03}
        rep = self.a.generate_report(apy)
        path = self.a.save_report(rep)
        self.assertTrue(Path(path).exists())
        with open(path) as fh:
            saved = json.load(fh)
        self.assertEqual(saved[-1]["adapter_count"], 4)

    def test_all_bands_covered(self):
        apy = {"rich": 0.10, "fair": 0.06, "thin": 0.047, "neg": 0.03}
        rep = self.a.generate_report(apy)
        vals = {s["adapter_id"]: s["valuation"] for s in rep["spreads"]}
        self.assertEqual(vals["rich"], "RICH")
        self.assertEqual(vals["fair"], "FAIR")
        self.assertEqual(vals["thin"], "THIN")
        self.assertEqual(vals["neg"], "NEGATIVE")

    def test_many_adapters(self):
        apy = {f"ad{i}": 0.05 + i * 0.001 for i in range(40)}
        rep = self.a.generate_report(apy)
        self.assertEqual(rep["adapter_count"], 40)

    def test_zero_benchmark_all_positive(self):
        a = _make_analyzer(self.tmp, benchmark=0.0)
        rep = a.generate_report({"aave": 0.05})
        self.assertAlmostEqual(rep["spreads"][0]["spread_bps"], 500.0, places=4)
        self.assertEqual(rep["valuation_counts"]["NEGATIVE"], 0)


if __name__ == "__main__":
    unittest.main()
