"""Tests for spa_core.analytics.chain_concentration (MP-387).

65+ test cases across 8 test classes:
  TestAnalyzerInit          (5)
  TestLoadAllocations       (10)
  TestComputeConcentrations (10)
  TestIsCompliant           (10)
  TestOverConcentrated      (8)
  TestRebalanceSuggestions  (12)
  TestSummary               (5)
  TestSaveReport            (5)
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from spa_core.analytics.chain_concentration import (
    CHAIN_CONCENTRATION_LIMIT,
    CHAINS,
    ChainConcentrationAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _minimal_status(adapters: list) -> dict:
    return {"schema_version": 1, "adapters": adapters}


def _adapter(
    key: str = "test-proto",
    chains: list | None = None,
    cap: float = 0.4,
    tier: str = "T1",
) -> dict:
    return {
        "protocol_key": key,
        "tier": tier,
        "allocation_cap": cap,
        "chains": chains if chains is not None else ["ethereum"],
    }


# ---------------------------------------------------------------------------
# TestAnalyzerInit
# ---------------------------------------------------------------------------

class TestAnalyzerInit(unittest.TestCase):
    """5 tests — construction and module-level constants."""

    def test_default_path(self):
        """Default adapter_status_path is 'data/adapter_status.json'."""
        a = ChainConcentrationAnalyzer()
        self.assertEqual(a._path, "data/adapter_status.json")

    def test_custom_path_stored(self):
        """Custom path is stored verbatim."""
        a = ChainConcentrationAnalyzer(adapter_status_path="/tmp/my_status.json")
        self.assertEqual(a._path, "/tmp/my_status.json")

    def test_instance_type(self):
        """Constructor returns ChainConcentrationAnalyzer instance."""
        a = ChainConcentrationAnalyzer()
        self.assertIsInstance(a, ChainConcentrationAnalyzer)

    def test_limit_constant(self):
        """CHAIN_CONCENTRATION_LIMIT is exactly 0.70."""
        self.assertAlmostEqual(CHAIN_CONCENTRATION_LIMIT, 0.70)

    def test_chains_constant(self):
        """CHAINS contains the five expected chain names."""
        for chain in ("ethereum", "arbitrum", "optimism", "polygon", "base"):
            self.assertIn(chain, CHAINS)


# ---------------------------------------------------------------------------
# TestLoadAllocations
# ---------------------------------------------------------------------------

class TestLoadAllocations(unittest.TestCase):
    """10 tests — reading and parsing adapter_status.json."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.path = self.tmp.name

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_returns_dict(self):
        """load_allocations returns a dict."""
        _write_json(self.path, _minimal_status([_adapter()]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        self.assertIsInstance(a.load_allocations(), dict)

    def test_missing_file_returns_empty(self):
        """Missing file → empty dict (no exception)."""
        a = ChainConcentrationAnalyzer(adapter_status_path="/nonexistent/path.json")
        self.assertEqual(a.load_allocations(), {})

    def test_corrupt_json_returns_empty(self):
        """Unparseable JSON → empty dict."""
        with open(self.path, "w") as fh:
            fh.write("{not valid json !!!")
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        self.assertEqual(a.load_allocations(), {})

    def test_empty_adapters_list_returns_empty(self):
        """Status with empty adapters list → empty dict."""
        _write_json(self.path, _minimal_status([]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        self.assertEqual(a.load_allocations(), {})

    def test_zero_cap_excluded(self):
        """Adapter with allocation_cap == 0 is not counted."""
        _write_json(self.path, _minimal_status([_adapter(cap=0.0)]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        self.assertEqual(a.load_allocations(), {})

    def test_negative_cap_excluded(self):
        """Adapter with negative allocation_cap is ignored."""
        _write_json(self.path, _minimal_status([_adapter(cap=-0.2)]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        self.assertEqual(a.load_allocations(), {})

    def test_single_chain_adapter_full_cap(self):
        """Single-chain adapter: entire cap attributed to that chain."""
        _write_json(self.path, _minimal_status([_adapter(chains=["arbitrum"], cap=0.4)]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        allocs = a.load_allocations()
        self.assertAlmostEqual(allocs.get("arbitrum", 0.0), 0.4)
        self.assertNotIn("ethereum", allocs)

    def test_multi_chain_adapter_splits_evenly(self):
        """Three-chain adapter: cap split into equal thirds."""
        _write_json(self.path, _minimal_status([
            _adapter(chains=["ethereum", "arbitrum", "base"], cap=0.3)
        ]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        allocs = a.load_allocations()
        for chain in ("ethereum", "arbitrum", "base"):
            self.assertAlmostEqual(allocs.get(chain, 0.0), 0.1, places=6)

    def test_same_chain_multiple_adapters_sum(self):
        """Multiple adapters on the same chain accumulate correctly."""
        _write_json(self.path, _minimal_status([
            _adapter(key="a", chains=["ethereum"], cap=0.2),
            _adapter(key="b", chains=["ethereum"], cap=0.3),
        ]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        allocs = a.load_allocations()
        self.assertAlmostEqual(allocs["ethereum"], 0.5, places=6)

    def test_chains_lowercased(self):
        """Chain names are normalised to lowercase."""
        _write_json(self.path, _minimal_status([
            _adapter(chains=["Ethereum", "ARBITRUM"], cap=0.2)
        ]))
        a = ChainConcentrationAnalyzer(adapter_status_path=self.path)
        allocs = a.load_allocations()
        self.assertIn("ethereum", allocs)
        self.assertIn("arbitrum", allocs)
        self.assertNotIn("Ethereum", allocs)


# ---------------------------------------------------------------------------
# TestComputeConcentrations
# ---------------------------------------------------------------------------

class TestComputeConcentrations(unittest.TestCase):
    """10 tests — normalisation logic."""

    def _analyzer(self):
        return ChainConcentrationAnalyzer(adapter_status_path="/dev/null")

    def test_returns_dict(self):
        """compute_concentrations returns a dict."""
        a = self._analyzer()
        self.assertIsInstance(a.compute_concentrations({"ethereum": 1.0}), dict)

    def test_empty_input_returns_empty(self):
        """Empty allocations → empty concentrations."""
        a = self._analyzer()
        self.assertEqual(a.compute_concentrations({}), {})

    def test_single_chain_concentration_one(self):
        """One chain with any positive weight → concentration = 1.0."""
        a = self._analyzer()
        conc = a.compute_concentrations({"ethereum": 5.0})
        self.assertAlmostEqual(conc["ethereum"], 1.0)

    def test_two_equal_chains_half(self):
        """Two equal-weight chains → 0.5 each."""
        a = self._analyzer()
        conc = a.compute_concentrations({"ethereum": 1.0, "arbitrum": 1.0})
        self.assertAlmostEqual(conc["ethereum"], 0.5)
        self.assertAlmostEqual(conc["arbitrum"], 0.5)

    def test_fractions_sum_to_one(self):
        """Concentrations always sum to 1.0."""
        a = self._analyzer()
        allocs = {"ethereum": 1.4, "arbitrum": 0.7, "base": 0.3}
        conc = a.compute_concentrations(allocs)
        self.assertAlmostEqual(sum(conc.values()), 1.0, places=9)

    def test_non_positive_values_excluded(self):
        """Zero and negative weights are excluded from normalisation."""
        a = self._analyzer()
        conc = a.compute_concentrations({"ethereum": 1.0, "arbitrum": 0.0, "base": -1.0})
        self.assertNotIn("arbitrum", conc)
        self.assertNotIn("base", conc)
        self.assertAlmostEqual(conc.get("ethereum", 0.0), 1.0)

    def test_large_absolute_values_normalize(self):
        """Large weights (e.g. USD) normalise correctly."""
        a = self._analyzer()
        allocs = {"ethereum": 70000.0, "arbitrum": 30000.0}
        conc = a.compute_concentrations(allocs)
        self.assertAlmostEqual(conc["ethereum"], 0.70, places=6)
        self.assertAlmostEqual(conc["arbitrum"], 0.30, places=6)

    def test_already_normalised_stays_normalised(self):
        """Input already summing to 1 stays numerically 1."""
        a = self._analyzer()
        allocs = {"ethereum": 0.7, "arbitrum": 0.3}
        conc = a.compute_concentrations(allocs)
        self.assertAlmostEqual(sum(conc.values()), 1.0, places=9)

    def test_returns_float_values(self):
        """Concentration values are floats."""
        a = self._analyzer()
        conc = a.compute_concentrations({"ethereum": 3, "arbitrum": 1})
        for v in conc.values():
            self.assertIsInstance(v, float)

    def test_none_input_calls_load(self):
        """compute_concentrations(None) triggers load_allocations (returns {} for /dev/null)."""
        a = self._analyzer()
        # /dev/null exists but is empty → corrupt → empty allocs → empty conc
        result = a.compute_concentrations(None)
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# TestIsCompliant
# ---------------------------------------------------------------------------

class TestIsCompliant(unittest.TestCase):
    """10 tests — compliance boundary checks."""

    def _a(self):
        return ChainConcentrationAnalyzer(adapter_status_path="/dev/null")

    def test_exactly_limit_is_compliant(self):
        """max fraction == 0.70 → compliant (≤ boundary)."""
        self.assertTrue(self._a().is_compliant({"ethereum": 0.70, "arbitrum": 0.30}))

    def test_above_limit_not_compliant(self):
        """max fraction 0.71 → not compliant."""
        self.assertFalse(self._a().is_compliant({"ethereum": 0.71, "arbitrum": 0.29}))

    def test_below_limit_is_compliant(self):
        """max fraction 0.69 → compliant."""
        self.assertTrue(self._a().is_compliant({"ethereum": 0.69, "arbitrum": 0.31}))

    def test_all_equal_chains_compliant(self):
        """Five equal chains (0.20 each) → compliant."""
        conc = {c: 0.2 for c in CHAINS}
        self.assertTrue(self._a().is_compliant(conc))

    def test_empty_concentrations_is_compliant(self):
        """Empty dict → True (nothing deployed)."""
        self.assertTrue(self._a().is_compliant({}))

    def test_single_chain_at_one_not_compliant(self):
        """Single chain with 100 % → not compliant."""
        self.assertFalse(self._a().is_compliant({"ethereum": 1.0}))

    def test_two_chains_fifty_each_compliant(self):
        """0.50 / 0.50 split → compliant."""
        self.assertTrue(self._a().is_compliant({"ethereum": 0.50, "arbitrum": 0.50}))

    def test_three_chains_30_30_40_compliant(self):
        """Max 0.40 → compliant."""
        self.assertTrue(
            self._a().is_compliant({"ethereum": 0.40, "arbitrum": 0.30, "base": 0.30})
        )

    def test_passes_explicit_concentrations(self):
        """Explicit concentrations param is used (no file IO)."""
        a = ChainConcentrationAnalyzer(adapter_status_path="/nonexistent/file.json")
        self.assertTrue(a.is_compliant({"ethereum": 0.50, "arbitrum": 0.50}))

    def test_returns_bool(self):
        """Return value is a Python bool."""
        result = self._a().is_compliant({"ethereum": 0.60, "arbitrum": 0.40})
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# TestOverConcentrated
# ---------------------------------------------------------------------------

class TestOverConcentrated(unittest.TestCase):
    """8 tests — get_over_concentrated_chains."""

    def _a(self):
        return ChainConcentrationAnalyzer(adapter_status_path="/dev/null")

    def test_returns_list(self):
        """Return value is a list."""
        self.assertIsInstance(
            self._a().get_over_concentrated_chains({"ethereum": 0.50}), list
        )

    def test_empty_when_compliant(self):
        """No chain exceeds limit → empty list."""
        self.assertEqual(
            self._a().get_over_concentrated_chains({"ethereum": 0.65, "arbitrum": 0.35}),
            [],
        )

    def test_over_concentrated_chain_included(self):
        """0.80 ethereum → appears in result."""
        result = self._a().get_over_concentrated_chains({"ethereum": 0.80, "arbitrum": 0.20})
        chains_only = [c for c, _ in result]
        self.assertIn("ethereum", chains_only)

    def test_exactly_limit_not_included(self):
        """0.70 exactly does NOT appear (threshold is strictly >)."""
        result = self._a().get_over_concentrated_chains({"ethereum": 0.70, "arbitrum": 0.30})
        self.assertEqual(result, [])

    def test_sorted_descending(self):
        """Multiple over-concentrated chains sorted by fraction, highest first."""
        conc = {"ethereum": 0.80, "arbitrum": 0.75, "base": 0.05}
        # both ethereum and arbitrum > 0.70 (the fractions here don't sum to 1
        # — compute_concentrations is not called; we pass raw already)
        # We adjust so only ethereum is > 0.70 in a realistic test:
        conc2 = {"ethereum": 0.80, "arbitrum": 0.72}
        result = self._a().get_over_concentrated_chains(conc2)
        fracs = [f for _, f in result]
        self.assertEqual(fracs, sorted(fracs, reverse=True))

    def test_fraction_matches_input(self):
        """Reported fraction equals the input concentration value."""
        result = self._a().get_over_concentrated_chains({"ethereum": 0.75})
        self.assertAlmostEqual(result[0][1], 0.75)

    def test_tuple_format(self):
        """Each entry is a (chain_str, float) tuple."""
        result = self._a().get_over_concentrated_chains({"ethereum": 0.80})
        self.assertEqual(len(result), 1)
        chain, frac = result[0]
        self.assertIsInstance(chain, str)
        self.assertIsInstance(frac, float)

    def test_uses_none_default(self):
        """None argument triggers compute path (no crash, returns list)."""
        # /dev/null → empty → compliant → []
        result = self._a().get_over_concentrated_chains(None)
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# TestRebalanceSuggestions
# ---------------------------------------------------------------------------

class TestRebalanceSuggestions(unittest.TestCase):
    """12 tests — get_rebalance_suggestions."""

    def _a(self):
        return ChainConcentrationAnalyzer(adapter_status_path="/dev/null")

    def test_returns_list(self):
        self.assertIsInstance(
            self._a().get_rebalance_suggestions({"ethereum": 0.60, "arbitrum": 0.40}),
            list,
        )

    def test_empty_when_compliant(self):
        self.assertEqual(
            self._a().get_rebalance_suggestions({"ethereum": 0.65, "arbitrum": 0.35}),
            [],
        )

    def test_ethereum_over_suggests_arbitrum_increase(self):
        """ethereum > 70 % → suggestion to INCREASE arbitrum."""
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.80, "arbitrum": 0.20})
        self.assertEqual(len(sug), 1)
        self.assertEqual(sug[0]["chain"], "arbitrum")
        self.assertEqual(sug[0]["action"], "increase")

    def test_suggestion_has_required_keys(self):
        """Suggestion dict contains action, chain, reason, target_delta."""
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.80, "arbitrum": 0.20})
        self.assertIn("action", sug[0])
        self.assertIn("chain", sug[0])
        self.assertIn("reason", sug[0])
        self.assertIn("target_delta", sug[0])

    def test_ethereum_action_is_increase(self):
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.80})
        self.assertEqual(sug[0]["action"], "increase")

    def test_ethereum_suggestion_chain_is_arbitrum(self):
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.75})
        self.assertEqual(sug[0]["chain"], "arbitrum")

    def test_reason_mentions_ethereum(self):
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.75})
        self.assertIn("ethereum", sug[0]["reason"])

    def test_target_delta_positive(self):
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.80})
        self.assertGreater(sug[0]["target_delta"], 0)

    def test_target_delta_min_five_percent(self):
        """Even tiny excess → target_delta >= 0.05."""
        # ethereum at 0.701: excess ≈ 0.001 but minimum is 0.05
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.701, "arbitrum": 0.299})
        self.assertGreaterEqual(sug[0]["target_delta"], 0.05)

    def test_non_ethereum_over_suggests_reduce(self):
        """Non-ethereum over-concentrated → action = 'reduce'."""
        sug = self._a().get_rebalance_suggestions({"arbitrum": 0.80, "ethereum": 0.20})
        self.assertEqual(len(sug), 1)
        self.assertEqual(sug[0]["action"], "reduce")
        self.assertEqual(sug[0]["chain"], "arbitrum")

    def test_none_uses_default_path(self):
        """None argument triggers compute_concentrations (no crash, returns list)."""
        result = self._a().get_rebalance_suggestions(None)
        self.assertIsInstance(result, list)

    def test_target_delta_equals_excess_large(self):
        """Large excess: target_delta ≈ excess (capped at max(excess, 0.05))."""
        # ethereum = 0.90, excess = 0.20
        sug = self._a().get_rebalance_suggestions({"ethereum": 0.90, "arbitrum": 0.10})
        self.assertAlmostEqual(sug[0]["target_delta"], 0.20, places=3)


# ---------------------------------------------------------------------------
# TestSummary
# ---------------------------------------------------------------------------

class TestSummary(unittest.TestCase):
    """5 tests — summary() schema."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        _write_json(self.tmp.name, _minimal_status([_adapter(chains=["ethereum"], cap=0.4)]))
        self.a = ChainConcentrationAnalyzer(adapter_status_path=self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_returns_dict_with_required_keys(self):
        snap = self.a.summary()
        for key in ("concentrations", "compliant", "suggestions", "timestamp"):
            self.assertIn(key, snap)

    def test_concentrations_is_dict(self):
        self.assertIsInstance(self.a.summary()["concentrations"], dict)

    def test_compliant_is_bool(self):
        self.assertIsInstance(self.a.summary()["compliant"], bool)

    def test_suggestions_is_list(self):
        self.assertIsInstance(self.a.summary()["suggestions"], list)

    def test_timestamp_is_positive_int(self):
        ts = self.a.summary()["timestamp"]
        self.assertIsInstance(ts, int)
        self.assertGreater(ts, 0)


# ---------------------------------------------------------------------------
# TestSaveReport
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):
    """5 tests — atomic write behaviour."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.status_path = os.path.join(self.dir, "adapter_status.json")
        _write_json(self.status_path, _minimal_status([
            _adapter(chains=["ethereum", "arbitrum"], cap=0.4)
        ]))
        self.a = ChainConcentrationAnalyzer(adapter_status_path=self.status_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_file_created(self):
        """save_report creates the output file."""
        out = os.path.join(self.dir, "chain_concentration.json")
        self.a.save_report(out)
        self.assertTrue(os.path.exists(out))

    def test_file_is_valid_json(self):
        """Written file is parseable JSON."""
        out = os.path.join(self.dir, "chain_concentration.json")
        self.a.save_report(out)
        with open(out) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_file_contains_expected_keys(self):
        """Written JSON contains all summary keys."""
        out = os.path.join(self.dir, "chain_concentration.json")
        self.a.save_report(out)
        with open(out) as fh:
            data = json.load(fh)
        for key in ("concentrations", "compliant", "suggestions", "timestamp"):
            self.assertIn(key, data)

    def test_no_leftover_tmp_file(self):
        """No .chain_concentration_* temp file remains after write."""
        out = os.path.join(self.dir, "chain_concentration.json")
        self.a.save_report(out)
        leftovers = [
            f for f in os.listdir(self.dir) if f.startswith(".chain_concentration_")
        ]
        self.assertEqual(leftovers, [])

    def test_custom_path_works(self):
        """save_report respects a custom output path."""
        out = os.path.join(self.dir, "custom_report.json")
        self.a.save_report(out)
        self.assertTrue(os.path.exists(out))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "chain_concentration.json")))


if __name__ == "__main__":
    unittest.main()
