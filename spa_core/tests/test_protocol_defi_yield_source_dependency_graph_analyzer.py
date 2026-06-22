"""
Tests for MP-1043 ProtocolDeFiYieldSourceDependencyGraphAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_yield_source_dependency_graph_analyzer import (
    analyze,
    _total_failure_probability_pct,
    _weakest_link,
    _chain_centralization_score,
    _effective_yield_risk_multiplier,
    _dependency_label,
    _apply_depth_limit,
    _recommendations,
    _atomic_log,
    ProtocolDeFiYieldSourceDependencyGraphAnalyzer,
    ALL_LABELS,
    LABEL_ATOMIC_YIELD,
    LABEL_SIMPLE_DEPENDENCY,
    LABEL_MODERATE_CHAIN,
    LABEL_COMPLEX_DEPENDENCY,
    LABEL_DEPENDENCY_NIGHTMARE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _dep(
    name: str = "Proto",
    type_: str = "protocol",
    failure_probability_pct: float = 5.0,
    tvl_usd: float = 100_000_000.0,
    is_centralized: bool = False,
) -> dict:
    return {
        "name": name,
        "type": type_,
        "failure_probability_pct": failure_probability_pct,
        "tvl_usd": tvl_usd,
        "is_centralized": is_centralized,
    }


def _source(
    yield_source_name: str = "TestYield",
    chain: list | None = None,
    max_chain_depth: int = 0,
) -> dict:
    if chain is None:
        chain = [_dep()]
    return {
        "yield_source_name": yield_source_name,
        "dependency_chain": chain,
        "max_chain_depth": max_chain_depth,
    }


# ===========================================================================
# 1. _total_failure_probability_pct
# ===========================================================================

class TestTotalFailureProbabilityPct(unittest.TestCase):
    def test_empty_chain_is_zero(self):
        self.assertAlmostEqual(_total_failure_probability_pct([]), 0.0)

    def test_single_dep(self):
        # 1 dep with 5% failure → total = 5%
        result = _total_failure_probability_pct([_dep(failure_probability_pct=5.0)])
        self.assertAlmostEqual(result, 5.0, places=5)

    def test_two_independent_deps(self):
        # P(survive) = 0.95 * 0.90 = 0.855 → fail = 14.5%
        deps = [
            _dep(failure_probability_pct=5.0),
            _dep(failure_probability_pct=10.0),
        ]
        result = _total_failure_probability_pct(deps)
        expected = (1.0 - 0.95 * 0.90) * 100.0
        self.assertAlmostEqual(result, expected, places=5)

    def test_100_pct_failure_short_circuits(self):
        deps = [
            _dep(failure_probability_pct=100.0),
            _dep(failure_probability_pct=5.0),
        ]
        result = _total_failure_probability_pct(deps)
        self.assertAlmostEqual(result, 100.0, places=5)

    def test_zero_failure_deps(self):
        deps = [_dep(failure_probability_pct=0.0)] * 5
        self.assertAlmostEqual(_total_failure_probability_pct(deps), 0.0)

    def test_more_deps_increases_total_prob(self):
        dep = _dep(failure_probability_pct=10.0)
        r1 = _total_failure_probability_pct([dep])
        r2 = _total_failure_probability_pct([dep, dep])
        r3 = _total_failure_probability_pct([dep, dep, dep])
        self.assertLess(r1, r2)
        self.assertLess(r2, r3)

    def test_always_0_to_100(self):
        for probs in [[5, 3, 4], [50, 50], [1]*10, [99, 99]]:
            deps = [_dep(failure_probability_pct=p) for p in probs]
            r = _total_failure_probability_pct(deps)
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, 100.0)

    def test_negative_prob_clamped_to_zero(self):
        deps = [_dep(failure_probability_pct=-10.0)]
        r = _total_failure_probability_pct(deps)
        self.assertAlmostEqual(r, 0.0)

    def test_above_100_prob_clamped(self):
        deps = [_dep(failure_probability_pct=150.0)]
        r = _total_failure_probability_pct(deps)
        self.assertAlmostEqual(r, 100.0)

    def test_series_formula_verification(self):
        # Manual: 1 - (1-0.10)*(1-0.20)*(1-0.15)
        deps = [
            _dep(failure_probability_pct=10.0),
            _dep(failure_probability_pct=20.0),
            _dep(failure_probability_pct=15.0),
        ]
        expected = (1.0 - 0.90 * 0.80 * 0.85) * 100.0
        r = _total_failure_probability_pct(deps)
        self.assertAlmostEqual(r, expected, places=5)

    def test_five_deps_each_5pct(self):
        deps = [_dep(failure_probability_pct=5.0)] * 5
        expected = (1.0 - 0.95 ** 5) * 100.0
        r = _total_failure_probability_pct(deps)
        self.assertAlmostEqual(r, expected, places=5)


# ===========================================================================
# 2. _weakest_link
# ===========================================================================

class TestWeakestLink(unittest.TestCase):
    def test_empty_chain_returns_empty_dict(self):
        self.assertEqual(_weakest_link([]), {})

    def test_single_dep(self):
        d = _dep(name="A", failure_probability_pct=10.0)
        self.assertEqual(_weakest_link([d]), d)

    def test_picks_highest_prob(self):
        deps = [
            _dep(name="Low", failure_probability_pct=2.0),
            _dep(name="High", failure_probability_pct=25.0),
            _dep(name="Mid", failure_probability_pct=10.0),
        ]
        wl = _weakest_link(deps)
        self.assertEqual(wl["name"], "High")

    def test_tied_picks_one_of_them(self):
        deps = [
            _dep(name="A", failure_probability_pct=10.0),
            _dep(name="B", failure_probability_pct=10.0),
        ]
        wl = _weakest_link(deps)
        self.assertIn(wl["name"], ["A", "B"])

    def test_returns_dict_type(self):
        wl = _weakest_link([_dep()])
        self.assertIsInstance(wl, dict)

    def test_all_zero_returns_first_or_any(self):
        deps = [_dep(failure_probability_pct=0.0) for _ in range(3)]
        wl = _weakest_link(deps)
        self.assertEqual(wl.get("failure_probability_pct"), 0.0)

    def test_preserves_original_dict(self):
        d = _dep(name="Maker", failure_probability_pct=7.5, tvl_usd=5e9)
        wl = _weakest_link([d])
        self.assertAlmostEqual(wl.get("tvl_usd"), 5e9)
        self.assertEqual(wl.get("name"), "Maker")


# ===========================================================================
# 3. _chain_centralization_score
# ===========================================================================

class TestChainCentralizationScore(unittest.TestCase):
    def test_empty_chain_is_zero(self):
        self.assertAlmostEqual(_chain_centralization_score([]), 0.0)

    def test_all_decentralized_is_zero(self):
        deps = [_dep(is_centralized=False)] * 3
        self.assertAlmostEqual(_chain_centralization_score(deps), 0.0)

    def test_all_centralized_is_100(self):
        deps = [_dep(is_centralized=True, tvl_usd=1e8)] * 3
        self.assertAlmostEqual(_chain_centralization_score(deps), 100.0)

    def test_half_tvl_centralized(self):
        deps = [
            _dep(tvl_usd=1e8, is_centralized=True),
            _dep(tvl_usd=1e8, is_centralized=False),
        ]
        score = _chain_centralization_score(deps)
        self.assertAlmostEqual(score, 50.0, places=5)

    def test_count_based_when_no_tvl(self):
        deps = [
            {"name": "A", "is_centralized": True, "tvl_usd": 0.0, "failure_probability_pct": 5.0, "type": "x"},
            {"name": "B", "is_centralized": False, "tvl_usd": 0.0, "failure_probability_pct": 5.0, "type": "x"},
        ]
        score = _chain_centralization_score(deps)
        self.assertAlmostEqual(score, 50.0, places=5)

    def test_always_0_to_100(self):
        for n_central in range(5):
            for n_decent in range(5):
                deps = (
                    [_dep(is_centralized=True, tvl_usd=1e6)] * n_central +
                    [_dep(is_centralized=False, tvl_usd=1e6)] * n_decent
                )
                if deps:
                    s = _chain_centralization_score(deps)
                    self.assertGreaterEqual(s, 0.0)
                    self.assertLessEqual(s, 100.0)

    def test_large_tvl_central_dominates(self):
        deps = [
            _dep(tvl_usd=9e9, is_centralized=True),
            _dep(tvl_usd=1e6, is_centralized=False),
        ]
        score = _chain_centralization_score(deps)
        self.assertGreater(score, 95.0)

    def test_weighted_by_tvl(self):
        deps = [
            _dep(tvl_usd=3e8, is_centralized=True),
            _dep(tvl_usd=7e8, is_centralized=False),
        ]
        score = _chain_centralization_score(deps)
        self.assertAlmostEqual(score, 30.0, places=5)


# ===========================================================================
# 4. _effective_yield_risk_multiplier
# ===========================================================================

class TestEffectiveYieldRiskMultiplier(unittest.TestCase):
    def test_zero_failure_is_one(self):
        self.assertAlmostEqual(_effective_yield_risk_multiplier(0.0), 1.0, places=5)

    def test_50_pct_failure_is_two(self):
        self.assertAlmostEqual(_effective_yield_risk_multiplier(50.0), 2.0, places=5)

    def test_90_pct_failure_is_ten(self):
        self.assertAlmostEqual(_effective_yield_risk_multiplier(90.0), 10.0, places=5)

    def test_99_9_pct_returns_large_value(self):
        m = _effective_yield_risk_multiplier(99.9)
        self.assertGreaterEqual(m, 100.0)

    def test_100_pct_returns_capped_value(self):
        m = _effective_yield_risk_multiplier(100.0)
        self.assertGreaterEqual(m, 1_000.0)

    def test_negative_clamped_to_zero(self):
        self.assertAlmostEqual(_effective_yield_risk_multiplier(-5.0), 1.0, places=5)

    def test_increases_monotonically(self):
        probs = [0.0, 10.0, 25.0, 50.0, 75.0, 90.0, 99.0]
        multipliers = [_effective_yield_risk_multiplier(p) for p in probs]
        for i in range(len(multipliers) - 1):
            self.assertLess(multipliers[i], multipliers[i + 1])

    def test_25_pct_failure(self):
        # 1 / 0.75 ≈ 1.333
        self.assertAlmostEqual(_effective_yield_risk_multiplier(25.0), 1.0 / 0.75, places=5)

    def test_above_100_clamped(self):
        m = _effective_yield_risk_multiplier(150.0)
        self.assertGreaterEqual(m, 1_000.0)


# ===========================================================================
# 5. _apply_depth_limit
# ===========================================================================

class TestApplyDepthLimit(unittest.TestCase):
    def test_zero_depth_returns_full(self):
        chain = [_dep()] * 5
        r = _apply_depth_limit(chain, 0)
        self.assertEqual(len(r), 5)

    def test_negative_depth_returns_full(self):
        chain = [_dep()] * 5
        r = _apply_depth_limit(chain, -1)
        self.assertEqual(len(r), 5)

    def test_exact_depth_limit(self):
        chain = [_dep(name=str(i)) for i in range(5)]
        r = _apply_depth_limit(chain, 3)
        self.assertEqual(len(r), 3)

    def test_depth_larger_than_chain(self):
        chain = [_dep()] * 2
        r = _apply_depth_limit(chain, 10)
        self.assertEqual(len(r), 2)

    def test_depth_one(self):
        chain = [_dep(name=str(i)) for i in range(5)]
        r = _apply_depth_limit(chain, 1)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["name"], "0")

    def test_order_preserved(self):
        names = ["A", "B", "C", "D"]
        chain = [_dep(name=n) for n in names]
        r = _apply_depth_limit(chain, 3)
        self.assertEqual([d["name"] for d in r], ["A", "B", "C"])

    def test_empty_chain(self):
        r = _apply_depth_limit([], 5)
        self.assertEqual(r, [])


# ===========================================================================
# 6. _dependency_label
# ===========================================================================

class TestDependencyLabel(unittest.TestCase):
    def test_empty_chain_is_atomic(self):
        label = _dependency_label([], 0.0, 0.0)
        self.assertEqual(label, LABEL_ATOMIC_YIELD)

    def test_single_dep_low_prob_is_simple(self):
        chain = [_dep(failure_probability_pct=5.0)]
        label = _dependency_label(chain, 5.0, 0.0)
        self.assertEqual(label, LABEL_SIMPLE_DEPENDENCY)

    def test_two_deps_is_moderate(self):
        chain = [_dep(failure_probability_pct=4.0)] * 2
        label = _dependency_label(chain, 7.84, 0.0)
        self.assertEqual(label, LABEL_MODERATE_CHAIN)

    def test_four_deps_is_complex(self):
        chain = [_dep(failure_probability_pct=3.0)] * 4
        label = _dependency_label(chain, 11.47, 0.0)
        self.assertEqual(label, LABEL_COMPLEX_DEPENDENCY)

    def test_high_failure_prob_is_nightmare(self):
        chain = [_dep(failure_probability_pct=30.0)] * 3
        label = _dependency_label(chain, 65.7, 0.0)
        self.assertEqual(label, LABEL_DEPENDENCY_NIGHTMARE)

    def test_high_centralization_is_nightmare(self):
        chain = [_dep()] * 2
        label = _dependency_label(chain, 9.75, 85.0)
        self.assertEqual(label, LABEL_DEPENDENCY_NIGHTMARE)

    def test_30_pct_failure_is_complex(self):
        chain = [_dep(failure_probability_pct=30.0)]
        label = _dependency_label(chain, 30.0, 0.0)
        self.assertEqual(label, LABEL_COMPLEX_DEPENDENCY)

    def test_10_pct_failure_single_dep_is_moderate(self):
        chain = [_dep(failure_probability_pct=10.0)]
        label = _dependency_label(chain, 10.0, 0.0)
        self.assertEqual(label, LABEL_MODERATE_CHAIN)

    def test_all_labels_in_all_labels(self):
        cases = [
            ([], 0.0, 0.0),
            ([_dep(failure_probability_pct=5.0)], 5.0, 0.0),
            ([_dep()] * 2, 9.75, 0.0),
            ([_dep()] * 4, 18.5, 0.0),
            ([_dep(failure_probability_pct=35.0)] * 3, 73.0, 0.0),
        ]
        seen = set()
        for chain, fail_pct, central in cases:
            label = _dependency_label(chain, fail_pct, central)
            self.assertIn(label, ALL_LABELS)
            seen.add(label)
        # At least 4 distinct labels produced
        self.assertGreaterEqual(len(seen), 4)

    def test_boundary_exactly_60_pct_failure(self):
        # > 60 → nightmare; exactly 60 → complex
        chain = [_dep()] * 3
        label_over = _dependency_label(chain, 61.0, 0.0)
        label_exact = _dependency_label(chain, 60.0, 0.0)
        self.assertEqual(label_over, LABEL_DEPENDENCY_NIGHTMARE)
        self.assertNotEqual(label_exact, LABEL_DEPENDENCY_NIGHTMARE)

    def test_boundary_exactly_80_centralization(self):
        chain = [_dep()] * 2
        label_over = _dependency_label(chain, 9.0, 81.0)
        label_exact = _dependency_label(chain, 9.0, 80.0)
        self.assertEqual(label_over, LABEL_DEPENDENCY_NIGHTMARE)
        self.assertNotEqual(label_exact, LABEL_DEPENDENCY_NIGHTMARE)


# ===========================================================================
# 7. _atomic_log
# ===========================================================================

class TestAtomicLogDep(unittest.TestCase):
    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 42})
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["x"], 42)
        os.unlink(path)

    def test_appends_multiple(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_100(self):
        path = _tmp_log()
        for i in range(110):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 109)
        os.unlink(path)

    def test_recovers_from_corrupt(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{INVALID")
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_creates_parent_dirs(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "a", "b", "log.json")
        _atomic_log(path, {"deep": True})
        self.assertTrue(os.path.exists(path))

    def test_oldest_entries_dropped(self):
        path = _tmp_log()
        for i in range(103):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["i"], 3)
        os.unlink(path)


# ===========================================================================
# 8. analyze — integration tests
# ===========================================================================

class TestAnalyze(unittest.TestCase):
    def _cfg(self):
        return {"log_path": _tmp_log()}

    def test_returns_dict(self):
        r = analyze(_source(), config=self._cfg())
        self.assertIsInstance(r, dict)

    def test_required_keys(self):
        r = analyze(_source(), config=self._cfg())
        for key in [
            "yield_source_name",
            "total_failure_probability_pct",
            "weakest_link",
            "chain_centralization_score",
            "effective_yield_risk_multiplier",
            "label",
            "recommendations",
            "timestamp",
        ]:
            self.assertIn(key, r)

    def test_label_in_all_labels(self):
        r = analyze(_source(), config=self._cfg())
        self.assertIn(r["label"], ALL_LABELS)

    def test_empty_chain_atomic(self):
        r = analyze(_source(chain=[]), config=self._cfg())
        self.assertEqual(r["label"], LABEL_ATOMIC_YIELD)
        self.assertAlmostEqual(r["total_failure_probability_pct"], 0.0)

    def test_single_dep_simple(self):
        r = analyze(_source(chain=[_dep(failure_probability_pct=5.0)]), config=self._cfg())
        self.assertEqual(r["label"], LABEL_SIMPLE_DEPENDENCY)

    def test_nightmare_scenario(self):
        chain = [_dep(failure_probability_pct=40.0)] * 3
        r = analyze(_source(chain=chain), config=self._cfg())
        self.assertIn(r["label"], [LABEL_DEPENDENCY_NIGHTMARE, LABEL_COMPLEX_DEPENDENCY])
        self.assertGreater(r["total_failure_probability_pct"], 60.0)

    def test_centralized_deps_nightmare(self):
        chain = [_dep(is_centralized=True, tvl_usd=1e9)] * 3
        r = analyze(_source(chain=chain), config=self._cfg())
        self.assertEqual(r["label"], LABEL_DEPENDENCY_NIGHTMARE)
        self.assertGreater(r["chain_centralization_score"], 80.0)

    def test_max_depth_applied(self):
        chain = [_dep(failure_probability_pct=10.0)] * 5
        r = analyze(_source(chain=chain, max_chain_depth=2), config=self._cfg())
        self.assertEqual(r["effective_depth"], 2)
        self.assertLess(r["total_failure_probability_pct"], 20.0)

    def test_max_depth_zero_uses_full_chain(self):
        chain = [_dep(failure_probability_pct=5.0)] * 4
        r = analyze(_source(chain=chain, max_chain_depth=0), config=self._cfg())
        self.assertEqual(r["effective_depth"], 4)

    def test_weakest_link_correct(self):
        chain = [
            _dep(name="Safe", failure_probability_pct=2.0),
            _dep(name="Risky", failure_probability_pct=30.0),
            _dep(name="Mid", failure_probability_pct=10.0),
        ]
        r = analyze(_source(chain=chain), config=self._cfg())
        self.assertEqual(r["weakest_link"]["name"], "Risky")

    def test_multiplier_is_correct(self):
        chain = [_dep(failure_probability_pct=50.0)]
        r = analyze(_source(chain=chain), config=self._cfg())
        self.assertAlmostEqual(r["effective_yield_risk_multiplier"], 2.0, places=4)

    def test_recommendations_is_list(self):
        r = analyze(_source(), config=self._cfg())
        self.assertIsInstance(r["recommendations"], list)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_source(), config=self._cfg())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_yield_source_name_preserved(self):
        r = analyze(_source(yield_source_name="Pendle-sUSDS"), config=self._cfg())
        self.assertEqual(r["yield_source_name"], "Pendle-sUSDS")

    def test_missing_keys_handled(self):
        r = analyze({}, config=self._cfg())
        self.assertIn("label", r)
        self.assertIn("total_failure_probability_pct", r)

    def test_no_crash_on_empty_dep_dicts(self):
        chain = [{}, {}, {}]
        r = analyze(_source(chain=chain), config=self._cfg())
        self.assertIn("label", r)

    def test_dep_chain_normalised(self):
        dep = {"name": "X", "type": "oracle", "failure_probability_pct": 7.0,
               "tvl_usd": 1e7, "is_centralized": False}
        r = analyze(_source(chain=[dep]), config=self._cfg())
        self.assertEqual(r["dependency_chain"][0]["name"], "X")
        self.assertAlmostEqual(r["dependency_chain"][0]["failure_probability_pct"], 7.0)

    def test_pendle_sUSDS_demo(self):
        chain = [
            {"name": "Sky (sUSDS)", "type": "protocol", "failure_probability_pct": 5.0,
             "tvl_usd": 4e9, "is_centralized": False},
            {"name": "MakerDAO governance", "type": "governance", "failure_probability_pct": 3.0,
             "tvl_usd": 8e9, "is_centralized": False},
            {"name": "Pendle AMM", "type": "protocol", "failure_probability_pct": 4.0,
             "tvl_usd": 5e8, "is_centralized": False},
        ]
        r = analyze({"yield_source_name": "Pendle PT-sUSDS", "dependency_chain": chain, "max_chain_depth": 10},
                    config=self._cfg())
        self.assertIn(r["label"], [LABEL_MODERATE_CHAIN, LABEL_COMPLEX_DEPENDENCY])
        self.assertGreater(r["total_failure_probability_pct"], 0.0)

    def test_moderate_chain_two_deps(self):
        chain = [_dep(failure_probability_pct=5.0)] * 2
        r = analyze(_source(chain=chain), config=self._cfg())
        self.assertEqual(r["label"], LABEL_MODERATE_CHAIN)


# ===========================================================================
# 9. _recommendations
# ===========================================================================

class TestRecommendations(unittest.TestCase):
    def _wl(self):
        return _dep(name="WeakProto", failure_probability_pct=25.0)

    def test_atomic_has_no_deps_message(self):
        recs = _recommendations(LABEL_ATOMIC_YIELD, [], 0.0, 0.0, {}, 1.0)
        self.assertGreater(len(recs), 0)
        self.assertTrue(any("no external" in r.lower() or "no dep" in r.lower() or "minimal" in r.lower() for r in recs))

    def test_nightmare_has_critical_message(self):
        chain = [_dep()] * 3
        recs = _recommendations(LABEL_DEPENDENCY_NIGHTMARE, chain, 65.0, 20.0, self._wl(), 3.0)
        combined = " ".join(recs).lower()
        self.assertIn("critical", combined)

    def test_nightmare_centralization_message(self):
        chain = [_dep()] * 2
        recs = _recommendations(LABEL_DEPENDENCY_NIGHTMARE, chain, 30.0, 85.0, self._wl(), 2.0)
        combined = " ".join(recs).lower()
        self.assertTrue("central" in combined or "actor" in combined)

    def test_complex_message(self):
        chain = [_dep()] * 4
        recs = _recommendations(LABEL_COMPLEX_DEPENDENCY, chain, 35.0, 10.0, self._wl(), 1.5)
        self.assertGreater(len(recs), 0)

    def test_moderate_message(self):
        chain = [_dep()] * 2
        recs = _recommendations(LABEL_MODERATE_CHAIN, chain, 10.0, 0.0, self._wl(), 1.1)
        self.assertGreater(len(recs), 0)

    def test_simple_message(self):
        chain = [_dep()]
        recs = _recommendations(LABEL_SIMPLE_DEPENDENCY, chain, 5.0, 0.0, self._wl(), 1.05)
        self.assertGreater(len(recs), 0)

    def test_high_multiplier_adds_recommendation(self):
        chain = [_dep()] * 2
        recs = _recommendations(LABEL_MODERATE_CHAIN, chain, 15.0, 0.0, self._wl(), 3.5)
        combined = " ".join(recs).lower()
        self.assertTrue("multiplier" in combined or "yield" in combined or "3.5" in combined or "risk" in combined)

    def test_returns_list(self):
        for label in ALL_LABELS:
            chain = [_dep()] if label != LABEL_ATOMIC_YIELD else []
            recs = _recommendations(label, chain, 5.0, 0.0, self._wl(), 1.05)
            self.assertIsInstance(recs, list)

    def test_weakest_link_mentioned(self):
        chain = [_dep(name="SpecificProto")] * 2
        recs = _recommendations(LABEL_MODERATE_CHAIN, chain, 10.0, 0.0,
                                _dep(name="SpecificProto", failure_probability_pct=10.0), 1.1)
        combined = " ".join(recs)
        self.assertIn("SpecificProto", combined)


# ===========================================================================
# 10. ProtocolDeFiYieldSourceDependencyGraphAnalyzer class
# ===========================================================================

class TestClass(unittest.TestCase):
    def test_instantiation(self):
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        cfg = {"log_path": _tmp_log()}
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer(config=cfg)
        r = a.analyze(_source())
        self.assertIsInstance(r, dict)

    def test_label_valid(self):
        cfg = {"log_path": _tmp_log()}
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer(config=cfg)
        r = a.analyze(_source())
        self.assertIn(r["label"], ALL_LABELS)

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer(config=cfg)
        a.analyze(_source())
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer(config=cfg)
        a.analyze(_source(yield_source_name="A"))
        a.analyze(_source(yield_source_name="B"))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_no_config_uses_default(self):
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer()
        r = a.analyze(_source())
        self.assertIn("label", r)

    def test_empty_chain_via_class(self):
        cfg = {"log_path": _tmp_log()}
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer(config=cfg)
        r = a.analyze(_source(chain=[]))
        self.assertEqual(r["label"], LABEL_ATOMIC_YIELD)

    def test_effective_depth_respected(self):
        cfg = {"log_path": _tmp_log()}
        a = ProtocolDeFiYieldSourceDependencyGraphAnalyzer(config=cfg)
        chain = [_dep()] * 5
        r = a.analyze(_source(chain=chain, max_chain_depth=2))
        self.assertEqual(r["effective_depth"], 2)


# ===========================================================================
# 11. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_all_zeros_in_dep(self):
        chain = [{"failure_probability_pct": 0.0, "tvl_usd": 0.0, "is_centralized": False,
                  "name": "Z", "type": "unknown"}]
        r = analyze(_source(chain=chain), config={"log_path": _tmp_log()})
        self.assertAlmostEqual(r["total_failure_probability_pct"], 0.0)

    def test_very_long_chain(self):
        chain = [_dep(failure_probability_pct=1.0)] * 50
        r = analyze(_source(chain=chain), config={"log_path": _tmp_log()})
        self.assertIn(r["label"], ALL_LABELS)
        self.assertGreater(r["total_failure_probability_pct"], 0.0)

    def test_chain_without_tvl_field(self):
        chain = [{"name": "X", "type": "protocol", "failure_probability_pct": 5.0, "is_centralized": True}]
        r = analyze(_source(chain=chain), config={"log_path": _tmp_log()})
        self.assertGreaterEqual(r["chain_centralization_score"], 0.0)

    def test_mixed_types_in_chain(self):
        chain = [
            _dep(name="Oracle", type_="oracle", failure_probability_pct=2.0),
            _dep(name="Bridge", type_="bridge", failure_probability_pct=8.0),
            _dep(name="Governance", type_="governance", failure_probability_pct=3.0),
        ]
        r = analyze(_source(chain=chain), config={"log_path": _tmp_log()})
        self.assertEqual(r["weakest_link"]["name"], "Bridge")

    def test_source_with_no_chain_key(self):
        r = analyze({"yield_source_name": "X"}, config={"log_path": _tmp_log()})
        self.assertEqual(r["label"], LABEL_ATOMIC_YIELD)

    def test_failure_prob_above_100_clamped(self):
        chain = [_dep(failure_probability_pct=200.0)]
        r = analyze(_source(chain=chain), config={"log_path": _tmp_log()})
        self.assertAlmostEqual(r["total_failure_probability_pct"], 100.0)

    def test_multiplier_at_zero_failure(self):
        chain = [_dep(failure_probability_pct=0.0)]
        r = analyze(_source(chain=chain), config={"log_path": _tmp_log()})
        self.assertAlmostEqual(r["effective_yield_risk_multiplier"], 1.0, places=4)

    def test_string_failure_prob(self):
        chain = [{"name": "X", "type": "protocol", "failure_probability_pct": "10",
                  "tvl_usd": 1e8, "is_centralized": False}]
        r = analyze(_source(chain=chain), config={"log_path": _tmp_log()})
        self.assertAlmostEqual(r["total_failure_probability_pct"], 10.0, places=4)


if __name__ == "__main__":
    unittest.main()
