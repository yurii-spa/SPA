"""Unit tests for spa_core/analytics/scenario_simulator.py (MP-586).

Run:
    python3 -m pytest tests/test_scenario_simulator.py -v
    python3 -m unittest tests.test_scenario_simulator -v

Coverage target: 85+ tests across all public / private helpers.
Pure stdlib — no third-party dependencies.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path when run directly
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.scenario_simulator import (
    DISCLAIMER,
    HISTORY_MAX,
    PEG_BREAK_RETURN_PCT,
    SCHEMA_VERSION,
    ScenarioResult,
    ScenarioSimulator,
    _applies_peg_break,
    _compute_shock_multiplier,
    _get_adapter_apy_pct,
    _get_adapter_id,
    _get_adapter_tier,
    _is_wildcard_key,
    _matches_wildcard,
    _normalise_weights,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

def _make_adapter(
    adapter_id: str = "test_adapter",
    apy: float = 5.0,
    tvl: float = 10_000_000.0,
    tier: str = "T1",
    chain: str = "ethereum",
) -> dict:
    return {
        "adapter_id": adapter_id,
        "apy": apy,
        "tvl": tvl,
        "tier": tier,
        "chain": chain,
    }


def _simple_portfolio():
    """(weights, adapters) with 2 T1 adapters, equal weight."""
    adapters = [
        _make_adapter("aave_v3", apy=4.0, tvl=8e9, tier="T1"),
        _make_adapter("compound_v3", apy=5.0, tvl=3e9, tier="T1"),
    ]
    weights = {"aave_v3": 0.5, "compound_v3": 0.5}
    return weights, adapters


def _default_sim(tmp_path=None) -> ScenarioSimulator:
    if tmp_path:
        return ScenarioSimulator(data_dir=str(tmp_path))
    return ScenarioSimulator()


# ===========================================================================
# 1. ScenarioResult
# ===========================================================================
class TestScenarioResult(unittest.TestCase):

    def test_create_all_fields(self):
        r = ScenarioResult("s", 1.5, "worst_a", "best_a", ["b1"], ["w1"])
        self.assertEqual(r.scenario_name, "s")
        self.assertAlmostEqual(r.portfolio_return_pct, 1.5)
        self.assertEqual(r.worst_adapter, "worst_a")
        self.assertEqual(r.best_adapter, "best_a")
        self.assertEqual(r.breached_limits, ["b1"])
        self.assertEqual(r.warnings, ["w1"])

    def test_default_empty_lists(self):
        r = ScenarioResult("s", 0.0, "", "")
        self.assertEqual(r.breached_limits, [])
        self.assertEqual(r.warnings, [])

    def test_to_dict_keys(self):
        r = ScenarioResult("my_sc", 2.5, "w", "b", ["lim"], ["warn"])
        d = r.to_dict()
        for key in ("scenario_name", "portfolio_return_pct",
                    "worst_adapter", "best_adapter",
                    "breached_limits", "warnings"):
            self.assertIn(key, d)

    def test_to_dict_values(self):
        r = ScenarioResult("sc", 3.141592653589793, "wa", "ba", [], [])
        d = r.to_dict()
        self.assertEqual(d["scenario_name"], "sc")
        self.assertAlmostEqual(d["portfolio_return_pct"], 3.141593, places=4)

    def test_to_dict_copies_lists(self):
        limits = ["x"]
        r = ScenarioResult("sc", 0.0, "", "", limits, [])
        d = r.to_dict()
        d["breached_limits"].append("y")
        self.assertEqual(limits, ["x"], "to_dict should copy, not share")

    def test_to_dict_is_json_serialisable(self):
        r = ScenarioResult("test", -12.3, "a", "b", ["c"], ["d"])
        json.dumps(r.to_dict())  # must not raise

    def test_multiple_limits_and_warnings(self):
        r = ScenarioResult("s", 0.0, "", "", ["l1", "l2"], ["w1", "w2", "w3"])
        self.assertEqual(len(r.breached_limits), 2)
        self.assertEqual(len(r.warnings), 3)

    def test_negative_return_allowed(self):
        r = ScenarioResult("bad", -99.0, "x", "y")
        self.assertLess(r.portfolio_return_pct, 0)


# ===========================================================================
# 2. _safe_float
# ===========================================================================
class TestSafeFloat(unittest.TestCase):

    def test_int(self):
        self.assertEqual(_safe_float(3), 3.0)

    def test_float(self):
        self.assertAlmostEqual(_safe_float(1.5), 1.5)

    def test_bool_true(self):
        self.assertEqual(_safe_float(True), 1.0)

    def test_bool_false(self):
        self.assertEqual(_safe_float(False), 0.0)

    def test_none_returns_default(self):
        self.assertEqual(_safe_float(None, 7.0), 7.0)

    def test_nan_returns_default(self):
        import math
        self.assertEqual(_safe_float(math.nan, -1.0), -1.0)

    def test_inf_returns_default(self):
        import math
        self.assertEqual(_safe_float(math.inf, -2.0), -2.0)

    def test_string_parseable(self):
        self.assertAlmostEqual(_safe_float("3.14"), 3.14)

    def test_invalid_string(self):
        self.assertEqual(_safe_float("abc", 5.0), 5.0)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)


# ===========================================================================
# 3. _normalise_weights
# ===========================================================================
class TestNormaliseWeights(unittest.TestCase):

    def test_sums_to_one(self):
        w = _normalise_weights({"a": 1.0, "b": 3.0})
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_preserves_proportions(self):
        w = _normalise_weights({"a": 1.0, "b": 1.0})
        self.assertAlmostEqual(w["a"], 0.5)
        self.assertAlmostEqual(w["b"], 0.5)

    def test_empty_returns_empty(self):
        self.assertEqual(_normalise_weights({}), {})

    def test_negative_clipped_to_zero(self):
        w = _normalise_weights({"a": 2.0, "b": -1.0})
        self.assertGreaterEqual(w["b"], 0.0)

    def test_all_zero_equal_share(self):
        w = _normalise_weights({"a": 0.0, "b": 0.0})
        self.assertAlmostEqual(w["a"], 0.5)
        self.assertAlmostEqual(w["b"], 0.5)

    def test_single_adapter(self):
        w = _normalise_weights({"x": 42.0})
        self.assertAlmostEqual(w["x"], 1.0)

    def test_already_normalised(self):
        w = _normalise_weights({"a": 0.3, "b": 0.7})
        self.assertAlmostEqual(w["a"], 0.3)
        self.assertAlmostEqual(w["b"], 0.7)

    def test_large_values_normalised(self):
        w = _normalise_weights({"a": 1000.0, "b": 2000.0, "c": 7000.0})
        self.assertAlmostEqual(sum(w.values()), 1.0)


# ===========================================================================
# 4. _get_adapter_id
# ===========================================================================
class TestGetAdapterId(unittest.TestCase):

    def test_dict_adapter_id(self):
        self.assertEqual(_get_adapter_id({"adapter_id": "aave"}), "aave")

    def test_dict_id_fallback(self):
        self.assertEqual(_get_adapter_id({"id": "compound"}), "compound")

    def test_dict_name_fallback(self):
        self.assertEqual(_get_adapter_id({"name": "morpho"}), "morpho")

    def test_object_with_attribute(self):
        class A:
            adapter_id = "euler"
        self.assertEqual(_get_adapter_id(A()), "euler")

    def test_unknown_fallback(self):
        self.assertEqual(_get_adapter_id({}), "unknown")


# ===========================================================================
# 5. _get_adapter_tier
# ===========================================================================
class TestGetAdapterTier(unittest.TestCase):

    def test_T1_exact(self):
        self.assertEqual(_get_adapter_tier({"tier": "T1"}), "T1")

    def test_T2_exact(self):
        self.assertEqual(_get_adapter_tier({"tier": "T2"}), "T2")

    def test_T3_exact(self):
        self.assertEqual(_get_adapter_tier({"tier": "T3"}), "T3")

    def test_tier1_word(self):
        self.assertEqual(_get_adapter_tier({"tier": "TIER1"}), "T1")

    def test_numeric_string_1(self):
        self.assertEqual(_get_adapter_tier({"tier": "1"}), "T1")

    def test_default_T2(self):
        self.assertEqual(_get_adapter_tier({}), "T2")

    def test_unknown_maps_T2(self):
        self.assertEqual(_get_adapter_tier({"tier": "unknown"}), "T2")


# ===========================================================================
# 6. _get_adapter_apy_pct
# ===========================================================================
class TestGetAdapterApyPct(unittest.TestCase):

    def test_pct_value(self):
        self.assertAlmostEqual(_get_adapter_apy_pct({"apy": 3.5}), 3.5)

    def test_decimal_fraction_converted(self):
        self.assertAlmostEqual(_get_adapter_apy_pct({"apy": 0.035}), 3.5)

    def test_zero(self):
        self.assertAlmostEqual(_get_adapter_apy_pct({"apy": 0.0}), 0.0)

    def test_missing_returns_zero(self):
        self.assertAlmostEqual(_get_adapter_apy_pct({}), 0.0)

    def test_negative_decimal(self):
        val = _get_adapter_apy_pct({"apy": -0.01})
        self.assertAlmostEqual(val, -1.0)

    def test_high_value_unchanged(self):
        self.assertAlmostEqual(_get_adapter_apy_pct({"apy": 25.0}), 25.0)


# ===========================================================================
# 7. _is_wildcard_key
# ===========================================================================
class TestIsWildcardKey(unittest.TestCase):

    def test_star(self):
        self.assertTrue(_is_wildcard_key("*"))

    def test_T1(self):
        self.assertTrue(_is_wildcard_key("T1"))

    def test_T2(self):
        self.assertTrue(_is_wildcard_key("T2"))

    def test_T3(self):
        self.assertTrue(_is_wildcard_key("T3"))

    def test_mainnet(self):
        self.assertTrue(_is_wildcard_key("mainnet"))

    def test_usdc(self):
        self.assertTrue(_is_wildcard_key("usdc"))

    def test_l2(self):
        self.assertTrue(_is_wildcard_key("l2"))

    def test_exact_adapter_id_is_not_wildcard(self):
        self.assertFalse(_is_wildcard_key("aave_v3"))

    def test_random_string_not_wildcard(self):
        self.assertFalse(_is_wildcard_key("compound_usdc"))

    def test_case_insensitive_T1_lower(self):
        self.assertTrue(_is_wildcard_key("t1"))


# ===========================================================================
# 8. _matches_wildcard
# ===========================================================================
class TestMatchesWildcard(unittest.TestCase):

    def test_star_matches_any(self):
        a = _make_adapter("anything", tier="T2")
        self.assertTrue(_matches_wildcard("*", a))

    def test_T1_matches_T1_adapter(self):
        a = _make_adapter("aave", tier="T1")
        self.assertTrue(_matches_wildcard("T1", a))

    def test_T1_no_match_T2(self):
        a = _make_adapter("maple", tier="T2")
        self.assertFalse(_matches_wildcard("T1", a))

    def test_T2_matches_T2(self):
        a = _make_adapter("maple", tier="T2")
        self.assertTrue(_matches_wildcard("T2", a))

    def test_T3_matches_T3(self):
        a = _make_adapter("pendle", tier="T3")
        self.assertTrue(_matches_wildcard("T3", a))

    def test_usdc_matches_by_id(self):
        a = _make_adapter("morpho_usdc_vault", tier="T1")
        self.assertTrue(_matches_wildcard("usdc", a))

    def test_usdc_no_match_non_usdc(self):
        a = _make_adapter("aave_v3", tier="T1")
        self.assertFalse(_matches_wildcard("usdc", a))

    def test_mainnet_matches_ethereum_chain(self):
        a = _make_adapter("aave_v3", chain="ethereum")
        self.assertTrue(_matches_wildcard("mainnet", a))

    def test_mainnet_matches_empty_chain(self):
        a = _make_adapter("aave_v3", chain="")
        self.assertTrue(_matches_wildcard("mainnet", a))

    def test_mainnet_no_match_arbitrum(self):
        a = _make_adapter("aave_arb", chain="arbitrum")
        self.assertFalse(_matches_wildcard("mainnet", a))

    def test_l2_matches_arbitrum(self):
        a = _make_adapter("aave_arb", chain="arbitrum")
        self.assertTrue(_matches_wildcard("l2", a))

    def test_l2_matches_base(self):
        a = _make_adapter("moonwell_base", chain="base")
        self.assertTrue(_matches_wildcard("l2", a))

    def test_l2_no_match_mainnet(self):
        a = _make_adapter("aave_v3", chain="ethereum")
        self.assertFalse(_matches_wildcard("l2", a))


# ===========================================================================
# 9. _compute_shock_multiplier
# ===========================================================================
class TestComputeShockMultiplier(unittest.TestCase):

    def _aave(self):
        return _make_adapter("aave_v3", tier="T1", chain="ethereum")

    def test_no_shocks_returns_one(self):
        self.assertAlmostEqual(_compute_shock_multiplier(self._aave(), {}), 1.0)

    def test_star_wildcard(self):
        self.assertAlmostEqual(
            _compute_shock_multiplier(self._aave(), {"*": 0.5}), 0.5
        )

    def test_tier_wildcard_T1(self):
        self.assertAlmostEqual(
            _compute_shock_multiplier(self._aave(), {"T1": 2.0}), 2.0
        )

    def test_tier_wildcard_T1_no_match_T2(self):
        a = _make_adapter("maple", tier="T2")
        self.assertAlmostEqual(
            _compute_shock_multiplier(a, {"T1": 0.1}), 1.0
        )

    def test_exact_id_overrides_wildcard(self):
        mult = _compute_shock_multiplier(
            self._aave(), {"*": 0.5, "aave_v3": 0.9}
        )
        self.assertAlmostEqual(mult, 0.9)

    def test_multiple_wildcards_compounded(self):
        # T1 = 0.5 and * = 0.8 → 0.4
        mult = _compute_shock_multiplier(self._aave(), {"T1": 0.5, "*": 0.8})
        self.assertAlmostEqual(mult, 0.4)

    def test_zero_multiplier(self):
        mult = _compute_shock_multiplier(self._aave(), {"*": 0.0})
        self.assertAlmostEqual(mult, 0.0)

    def test_large_multiplier(self):
        mult = _compute_shock_multiplier(self._aave(), {"T1": 10.0})
        self.assertAlmostEqual(mult, 10.0)

    def test_unrecognised_key_no_match(self):
        # Non-wildcard, non-matching key → 1.0
        mult = _compute_shock_multiplier(self._aave(), {"some_other_adapter": 0.1})
        self.assertAlmostEqual(mult, 1.0)


# ===========================================================================
# 10. _applies_peg_break
# ===========================================================================
class TestAppliesPegBreak(unittest.TestCase):

    def _usdc_adapter(self):
        return _make_adapter("morpho_usdc_vault", tier="T1", chain="ethereum")

    def test_exact_id_match(self):
        a = _make_adapter("morpho_usdc_vault")
        self.assertTrue(_applies_peg_break(a, ["morpho_usdc_vault"]))

    def test_exact_id_no_match(self):
        a = _make_adapter("aave_v3")
        self.assertFalse(_applies_peg_break(a, ["morpho_usdc_vault"]))

    def test_star_wildcard_matches_all(self):
        a = _make_adapter("any_adapter")
        self.assertTrue(_applies_peg_break(a, ["*"]))

    def test_usdc_wildcard_matches_usdc(self):
        self.assertTrue(_applies_peg_break(self._usdc_adapter(), ["usdc"]))

    def test_usdc_wildcard_no_match_non_usdc(self):
        a = _make_adapter("aave_v3", chain="ethereum")
        self.assertFalse(_applies_peg_break(a, ["usdc"]))

    def test_empty_peg_breaks(self):
        a = _make_adapter("aave_v3")
        self.assertFalse(_applies_peg_break(a, []))

    def test_multiple_entries_any_match(self):
        a = _make_adapter("aave_v3", tier="T1")
        self.assertTrue(_applies_peg_break(a, ["compound_v3", "T1"]))


# ===========================================================================
# 11. ScenarioSimulator.run_scenario — basic
# ===========================================================================
class TestRunScenarioBasic(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()

    def _sc(self, apy_shocks=None, tvl_shocks=None, peg_breaks=None, name="test"):
        return {
            "name": name,
            "apy_shocks": apy_shocks or {},
            "tvl_shocks": tvl_shocks or {},
            "peg_breaks": peg_breaks or [],
        }

    def test_returns_scenario_result(self):
        w, a = _simple_portfolio()
        r = self.sim.run_scenario(self._sc(), w, a)
        self.assertIsInstance(r, ScenarioResult)

    def test_scenario_name_preserved(self):
        w, a = _simple_portfolio()
        r = self.sim.run_scenario(self._sc(name="my_test"), w, a)
        self.assertEqual(r.scenario_name, "my_test")

    def test_no_shock_returns_weighted_apy(self):
        # 50% aave at 4%, 50% compound at 5% → 4.5%
        w, a = _simple_portfolio()
        r = self.sim.run_scenario(self._sc(), w, a)
        self.assertAlmostEqual(r.portfolio_return_pct, 4.5, places=4)

    def test_apy_shock_half_reduces_return(self):
        w, a = _simple_portfolio()
        r = self.sim.run_scenario(self._sc(apy_shocks={"*": 0.5}), w, a)
        self.assertAlmostEqual(r.portfolio_return_pct, 2.25, places=4)

    def test_apy_spike_increases_return(self):
        w, a = _simple_portfolio()
        r = self.sim.run_scenario(self._sc(apy_shocks={"T1": 3.0}), w, a)
        self.assertAlmostEqual(r.portfolio_return_pct, 13.5, places=4)

    def test_worst_adapter_identified(self):
        w, a = _simple_portfolio()
        # aave at 4%, compound at 5% → aave is worst
        r = self.sim.run_scenario(self._sc(), w, a)
        self.assertEqual(r.worst_adapter, "aave_v3")

    def test_best_adapter_identified(self):
        w, a = _simple_portfolio()
        r = self.sim.run_scenario(self._sc(), w, a)
        self.assertEqual(r.best_adapter, "compound_v3")

    def test_peg_break_lowers_return(self):
        adapters = [_make_adapter("usdc_pool", apy=5.0, tvl=1e9, tier="T2")]
        weights = {"usdc_pool": 1.0}
        r = self.sim.run_scenario(
            self._sc(peg_breaks=["usdc_pool"]), weights, adapters
        )
        self.assertAlmostEqual(r.portfolio_return_pct, PEG_BREAK_RETURN_PCT)

    def test_peg_break_warning_present(self):
        adapters = [_make_adapter("usdc_pool", apy=5.0, tvl=1e9, tier="T2")]
        weights = {"usdc_pool": 1.0}
        r = self.sim.run_scenario(
            self._sc(peg_breaks=["usdc_pool"]), weights, adapters
        )
        self.assertTrue(any("peg break" in w.lower() for w in r.warnings))

    def test_no_adapters_returns_zero(self):
        r = self.sim.run_scenario(self._sc(), {}, [])
        self.assertAlmostEqual(r.portfolio_return_pct, 0.0)
        self.assertTrue(r.warnings)

    def test_no_overlap_weights_adapters_warning(self):
        adapters = [_make_adapter("aave")]
        weights = {"compound": 1.0}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertEqual(r.portfolio_return_pct, 0.0)
        self.assertTrue(r.warnings)

    def test_extreme_apy_warning(self):
        adapters = [_make_adapter("crazy_pool", apy=5.0, tvl=1e9, tier="T1")]
        weights = {"crazy_pool": 1.0}
        sc = self._sc(apy_shocks={"T1": 10.0})  # 5 * 10 = 50% > 3*30=90? No.
        # 5 * 10 = 50; extreme threshold = 30*3 = 90; no warning
        r = self.sim.run_scenario(sc, weights, adapters)
        # Now use very high APY to trigger warning
        adapters2 = [_make_adapter("crazy", apy=40.0, tvl=1e9, tier="T1")]
        weights2 = {"crazy": 1.0}
        sc2 = self._sc(apy_shocks={"T1": 3.0})  # 40*3 = 120 > 90
        r2 = self.sim.run_scenario(sc2, weights2, adapters2)
        self.assertTrue(any("extreme" in w.lower() for w in r2.warnings))

    def test_severe_return_warning(self):
        adapters = [_make_adapter("a", apy=1.0, tvl=1e9, tier="T1")]
        weights = {"a": 1.0}
        sc = self._sc(apy_shocks={"*": 0.01})  # 1.0 * 0.01 = 0.01% not severe
        # Use peg break for severe return
        adapters2 = [_make_adapter("a", apy=5.0, tvl=1e9, tier="T1")]
        weights2 = {"a": 1.0}
        sc2 = self._sc(peg_breaks=["a"])  # -50% < -10%
        r = self.sim.run_scenario(sc2, weights2, adapters2)
        self.assertTrue(any("severe" in w.lower() for w in r.warnings))


# ===========================================================================
# 12. ScenarioSimulator.run_scenario — risk-limit breaches
# ===========================================================================
class TestRunScenarioBreaches(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()

    def _sc(self, **kw):
        return {"name": "breach_test", "apy_shocks": {}, "tvl_shocks": {},
                "peg_breaks": [], **kw}

    def test_tvl_floor_breach(self):
        # TVL shock drives pool below $5M
        adapters = [_make_adapter("small_pool", apy=3.0, tvl=6_000_000.0, tier="T1")]
        weights = {"small_pool": 1.0}
        sc = self._sc(tvl_shocks={"*": 0.5})  # 6M * 0.5 = 3M < 5M
        r = self.sim.run_scenario(sc, weights, adapters)
        self.assertTrue(
            any("tvl floor" in b.lower() for b in r.breached_limits),
            f"Expected TVL floor breach; got: {r.breached_limits}"
        )

    def test_tvl_above_floor_no_breach(self):
        adapters = [_make_adapter("big_pool", apy=3.0, tvl=50_000_000.0, tier="T1")]
        weights = {"big_pool": 1.0}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertFalse(any("tvl floor" in b.lower() for b in r.breached_limits))

    def test_t1_per_protocol_cap_breach(self):
        # 3 adapters, one T1 with weight 50% > 40% cap
        adapters = [
            _make_adapter("a", apy=4.0, tvl=1e9, tier="T1"),
            _make_adapter("b", apy=4.0, tvl=1e9, tier="T1"),
            _make_adapter("c", apy=4.0, tvl=1e9, tier="T1"),
        ]
        weights = {"a": 5.0, "b": 3.0, "c": 2.0}  # a = 50%
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertTrue(
            any("per-protocol" in b.lower() for b in r.breached_limits)
        )

    def test_t1_per_protocol_no_breach(self):
        adapters = [
            _make_adapter("a", apy=4.0, tvl=1e9, tier="T1"),
            _make_adapter("b", apy=4.0, tvl=1e9, tier="T1"),
            _make_adapter("c", apy=4.0, tvl=1e9, tier="T1"),
        ]
        weights = {"a": 1.0, "b": 1.0, "c": 1.0}  # ~33% each
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertFalse(any("per-protocol" in b.lower() for b in r.breached_limits))

    def test_t2_total_cap_breach(self):
        # 2 T2 adapters at 40% each = 80% > 50%
        adapters = [
            _make_adapter("a", apy=5.0, tvl=1e9, tier="T2"),
            _make_adapter("b", apy=5.0, tvl=1e9, tier="T2"),
            _make_adapter("c", apy=4.0, tvl=1e9, tier="T1"),
        ]
        weights = {"a": 0.4, "b": 0.4, "c": 0.2}  # T2 total = 80%
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertTrue(
            any("t2" in b.lower() for b in r.breached_limits)
        )

    def test_kill_switch_triggered(self):
        # peg break on 100% of portfolio → -50% < -5%
        adapters = [_make_adapter("full_loss", apy=5.0, tvl=1e9, tier="T1")]
        weights = {"full_loss": 1.0}
        sc = self._sc(peg_breaks=["full_loss"])
        r = self.sim.run_scenario(sc, weights, adapters)
        self.assertTrue(
            any("kill switch" in b.lower() for b in r.breached_limits)
        )

    def test_no_kill_switch_on_positive_return(self):
        adapters = [_make_adapter("good", apy=10.0, tvl=1e9, tier="T1")]
        weights = {"good": 1.0}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertFalse(any("kill switch" in b.lower() for b in r.breached_limits))

    def test_zero_tvl_causes_warning_not_breach(self):
        adapters = [_make_adapter("unk", apy=5.0, tvl=0.0, tier="T1")]
        weights = {"unk": 1.0}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        # Should warn but not breach (TVL unknown)
        self.assertTrue(any("tvl" in w.lower() for w in r.warnings))
        self.assertFalse(any("tvl floor" in b.lower() for b in r.breached_limits))


# ===========================================================================
# 13. ScenarioSimulator.get_builtin_scenarios
# ===========================================================================
class TestGetBuiltinScenarios(unittest.TestCase):

    def setUp(self):
        self.scenarios = ScenarioSimulator.get_builtin_scenarios()

    def test_returns_list(self):
        self.assertIsInstance(self.scenarios, list)

    def test_at_least_5_scenarios(self):
        self.assertGreaterEqual(len(self.scenarios), 5)

    def test_all_have_name(self):
        for sc in self.scenarios:
            self.assertIn("name", sc)
            self.assertTrue(sc["name"])

    def test_defi_bear_present(self):
        names = [sc["name"] for sc in self.scenarios]
        self.assertIn("defi_bear", names)

    def test_usdc_depeg_present(self):
        names = [sc["name"] for sc in self.scenarios]
        self.assertIn("usdc_depeg", names)

    def test_eth_crash_present(self):
        names = [sc["name"] for sc in self.scenarios]
        self.assertIn("eth_crash", names)

    def test_black_swan_present(self):
        names = [sc["name"] for sc in self.scenarios]
        self.assertIn("black_swan", names)

    def test_all_have_required_keys(self):
        for sc in self.scenarios:
            for key in ("apy_shocks", "tvl_shocks", "peg_breaks"):
                self.assertIn(key, sc, f"Missing '{key}' in scenario '{sc.get('name')}'")

    def test_peg_breaks_is_list(self):
        for sc in self.scenarios:
            self.assertIsInstance(sc["peg_breaks"], list)

    def test_apy_shocks_is_dict(self):
        for sc in self.scenarios:
            self.assertIsInstance(sc["apy_shocks"], dict)

    def test_returns_fresh_list_each_call(self):
        a = ScenarioSimulator.get_builtin_scenarios()
        b = ScenarioSimulator.get_builtin_scenarios()
        a.append({"name": "injected"})
        self.assertNotIn({"name": "injected"}, b)


# ===========================================================================
# 14. ScenarioSimulator.run_all_scenarios
# ===========================================================================
class TestRunAllScenarios(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()
        self.weights, self.adapters = _simple_portfolio()

    def test_returns_list(self):
        results = self.sim.run_all_scenarios(self.weights, self.adapters)
        self.assertIsInstance(results, list)

    def test_count_matches_builtin(self):
        results = self.sim.run_all_scenarios(self.weights, self.adapters)
        self.assertEqual(
            len(results),
            len(ScenarioSimulator.get_builtin_scenarios())
        )

    def test_all_are_scenario_results(self):
        for r in self.sim.run_all_scenarios(self.weights, self.adapters):
            self.assertIsInstance(r, ScenarioResult)

    def test_empty_adapters_still_returns_list(self):
        results = self.sim.run_all_scenarios({}, [])
        self.assertIsInstance(results, list)
        self.assertTrue(results)

    def test_scenario_names_unique(self):
        results = self.sim.run_all_scenarios(self.weights, self.adapters)
        names = [r.scenario_name for r in results]
        self.assertEqual(len(names), len(set(names)))


# ===========================================================================
# 15. ScenarioSimulator.get_simulation_report
# ===========================================================================
class TestGetSimulationReport(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()
        self.weights, self.adapters = _simple_portfolio()
        self.report = self.sim.get_simulation_report(self.weights, self.adapters)

    def test_required_keys_present(self):
        for key in (
            "generated_at", "schema_version", "n_scenarios", "results",
            "worst_case", "best_case", "avg_return_pct",
            "scenarios_with_breaches", "scenarios_with_warnings",
            "custom_scenario_count", "disclaimer",
        ):
            self.assertIn(key, self.report)

    def test_schema_version(self):
        self.assertEqual(self.report["schema_version"], SCHEMA_VERSION)

    def test_n_scenarios_positive(self):
        self.assertGreater(self.report["n_scenarios"], 0)

    def test_results_length_matches_n_scenarios(self):
        self.assertEqual(len(self.report["results"]), self.report["n_scenarios"])

    def test_worst_case_is_min_return(self):
        returns = [r["portfolio_return_pct"] for r in self.report["results"]]
        self.assertAlmostEqual(
            self.report["worst_case"]["portfolio_return_pct"],
            min(returns),
            places=4,
        )

    def test_best_case_is_max_return(self):
        returns = [r["portfolio_return_pct"] for r in self.report["results"]]
        self.assertAlmostEqual(
            self.report["best_case"]["portfolio_return_pct"],
            max(returns),
            places=4,
        )

    def test_avg_return_calculation(self):
        returns = [r["portfolio_return_pct"] for r in self.report["results"]]
        expected_avg = sum(returns) / len(returns)
        self.assertAlmostEqual(self.report["avg_return_pct"], expected_avg, places=4)

    def test_disclaimer_present(self):
        self.assertEqual(self.report["disclaimer"], DISCLAIMER)

    def test_custom_scenarios_included(self):
        custom = [{"name": "my_custom", "apy_shocks": {"*": 0.8},
                   "tvl_shocks": {}, "peg_breaks": []}]
        report = self.sim.get_simulation_report(
            self.weights, self.adapters, custom_scenarios=custom
        )
        names = [r["scenario_name"] for r in report["results"]]
        self.assertIn("my_custom", names)

    def test_custom_count_reported(self):
        custom = [{"name": "c1", "apy_shocks": {}, "tvl_shocks": {},
                   "peg_breaks": []}]
        report = self.sim.get_simulation_report(
            self.weights, self.adapters, custom_scenarios=custom
        )
        self.assertEqual(report["custom_scenario_count"], 1)

    def test_no_custom_count_zero(self):
        self.assertEqual(self.report["custom_scenario_count"], 0)

    def test_is_json_serialisable(self):
        json.dumps(self.report)  # must not raise

    def test_empty_adapters_report(self):
        r = self.sim.get_simulation_report({}, [])
        self.assertEqual(r["n_scenarios"], len(ScenarioSimulator.get_builtin_scenarios()))
        # All returns should be 0.0
        for res in r["results"]:
            self.assertAlmostEqual(res["portfolio_return_pct"], 0.0)


# ===========================================================================
# 16. ScenarioSimulator.save_report (atomic write + ring-buffer)
# ===========================================================================
class TestSaveReport(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.sim = ScenarioSimulator(data_dir=self._tmpdir)
        self.weights, self.adapters = _simple_portfolio()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _report(self, tag="test"):
        r = self.sim.get_simulation_report(self.weights, self.adapters)
        r["_tag"] = tag
        return r

    def test_file_created(self):
        out = self.sim.save_report(self._report())
        self.assertTrue(out.exists())

    def test_returns_path(self):
        out = self.sim.save_report(self._report())
        self.assertIsInstance(out, Path)

    def test_valid_json_written(self):
        self.sim.save_report(self._report())
        out = Path(self._tmpdir) / "scenario_report.json"
        data = json.loads(out.read_text())
        self.assertIn("results", data)

    def test_history_accumulates(self):
        self.sim.save_report(self._report("first"))
        self.sim.save_report(self._report("second"))
        out = Path(self._tmpdir) / "scenario_report.json"
        data = json.loads(out.read_text())
        self.assertIn("history", data)
        self.assertGreaterEqual(len(data["history"]), 1)

    def test_history_ring_buffer_capped(self):
        # Write HISTORY_MAX + 2 reports
        for i in range(HISTORY_MAX + 2):
            self.sim.save_report(self._report(f"run_{i}"))
        out = Path(self._tmpdir) / "scenario_report.json"
        data = json.loads(out.read_text())
        self.assertLessEqual(len(data["history"]), HISTORY_MAX)

    def test_no_tmp_files_left_behind(self):
        self.sim.save_report(self._report())
        tmp_files = list(Path(self._tmpdir).glob(".scenario_report_tmp_*"))
        self.assertEqual(len(tmp_files), 0, "Temp files should be cleaned up")


# ===========================================================================
# 17. Defi-bear builtin scenario correctness
# ===========================================================================
class TestDefiBeareScenario(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()

    def _run_bear(self, adapters, weights):
        sc = next(s for s in ScenarioSimulator.get_builtin_scenarios()
                  if s["name"] == "defi_bear")
        return self.sim.run_scenario(sc, weights, adapters)

    def test_return_is_half_of_no_shock(self):
        adapters = [_make_adapter("a", apy=10.0, tvl=1e9, tier="T1")]
        weights = {"a": 1.0}
        # defi_bear: apy_shocks {"*": 0.5} → 10 * 0.5 = 5%
        r = self._run_bear(adapters, weights)
        self.assertAlmostEqual(r.portfolio_return_pct, 5.0, places=4)

    def test_scenario_name(self):
        w, a = _simple_portfolio()
        r = self._run_bear(a, w)
        self.assertEqual(r.scenario_name, "defi_bear")

    def test_no_peg_break(self):
        w, a = _simple_portfolio()
        r = self._run_bear(a, w)
        self.assertFalse(any("peg break" in w.lower() for w in r.warnings))


# ===========================================================================
# 18. Black-swan builtin scenario correctness
# ===========================================================================
class TestBlackSwanScenario(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()

    def _run_bs(self, adapters, weights):
        sc = next(s for s in ScenarioSimulator.get_builtin_scenarios()
                  if s["name"] == "black_swan")
        return self.sim.run_scenario(sc, weights, adapters)

    def test_very_low_return(self):
        adapters = [_make_adapter("a", apy=10.0, tvl=1e9, tier="T1")]
        weights = {"a": 1.0}
        # black_swan: apy * 0.2 = 2%
        r = self._run_bs(adapters, weights)
        self.assertAlmostEqual(r.portfolio_return_pct, 2.0, places=4)

    def test_tvl_breach_if_small_pool(self):
        # 6M * 0.3 = 1.8M < 5M → TVL breach
        adapters = [_make_adapter("small", apy=5.0, tvl=6_000_000.0, tier="T1")]
        weights = {"small": 1.0}
        r = self._run_bs(adapters, weights)
        self.assertTrue(
            any("tvl floor" in b.lower() for b in r.breached_limits)
        )


# ===========================================================================
# 19. Rate-spike builtin scenario
# ===========================================================================
class TestRateSpikeScenario(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()

    def _run_rs(self, adapters, weights):
        sc = next(s for s in ScenarioSimulator.get_builtin_scenarios()
                  if s["name"] == "rate_spike")
        return self.sim.run_scenario(sc, weights, adapters)

    def test_t1_apy_triples(self):
        adapters = [_make_adapter("aave", apy=5.0, tvl=1e9, tier="T1")]
        weights = {"aave": 1.0}
        r = self._run_rs(adapters, weights)
        self.assertAlmostEqual(r.portfolio_return_pct, 15.0, places=4)

    def test_t2_apy_increases(self):
        adapters = [_make_adapter("maple", apy=8.0, tvl=1e9, tier="T2")]
        weights = {"maple": 1.0}
        r = self._run_rs(adapters, weights)
        self.assertAlmostEqual(r.portfolio_return_pct, 12.0, places=4)


# ===========================================================================
# 20. Edge cases and integration
# ===========================================================================
class TestEdgeCasesIntegration(unittest.TestCase):

    def setUp(self):
        self.sim = ScenarioSimulator()

    def _sc(self, **kw):
        return {"name": "edge", "apy_shocks": {}, "tvl_shocks": {},
                "peg_breaks": [], **kw}

    def test_decimal_apy_adapter_normalised(self):
        # APY stored as decimal 0.05 → 5%
        adapters = [{"adapter_id": "dec", "apy": 0.05, "tvl": 1e9, "tier": "T1"}]
        weights = {"dec": 1.0}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertAlmostEqual(r.portfolio_return_pct, 5.0, places=4)

    def test_object_adapter_supported(self):
        class Obj:
            adapter_id = "obj_adapter"
            apy = 6.0
            tvl = 1e9
            tier = "T1"
            chain = "ethereum"
        weights = {"obj_adapter": 1.0}
        r = self.sim.run_scenario(self._sc(), weights, [Obj()])
        self.assertAlmostEqual(r.portfolio_return_pct, 6.0, places=4)

    def test_single_adapter_portfolio(self):
        adapters = [_make_adapter("solo", apy=7.5, tvl=1e9, tier="T1")]
        weights = {"solo": 1.0}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertEqual(r.worst_adapter, "solo")
        self.assertEqual(r.best_adapter, "solo")

    def test_mixed_tier_portfolio(self):
        adapters = [
            _make_adapter("t1a", apy=4.0, tvl=2e9, tier="T1"),
            _make_adapter("t2a", apy=8.0, tvl=1e8, tier="T2"),
        ]
        weights = {"t1a": 0.7, "t2a": 0.3}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        expected = 0.7 * 4.0 + 0.3 * 8.0
        self.assertAlmostEqual(r.portfolio_return_pct, expected, places=4)

    def test_run_all_then_report_consistent(self):
        w, a = _simple_portfolio()
        all_results = self.sim.run_all_scenarios(w, a)
        report = self.sim.get_simulation_report(w, a)
        self.assertEqual(len(all_results), report["n_scenarios"])

    def test_custom_scenario_in_report_affects_avg(self):
        adapters = [_make_adapter("x", apy=10.0, tvl=1e9, tier="T1")]
        weights = {"x": 1.0}
        # Custom scenario: APY * 0 = 0
        custom = [{"name": "zero_out", "apy_shocks": {"*": 0.0},
                   "tvl_shocks": {}, "peg_breaks": []}]
        report = self.sim.get_simulation_report(weights, adapters,
                                                custom_scenarios=custom)
        returns = [r["portfolio_return_pct"] for r in report["results"]]
        self.assertIn(0.0, returns)

    def test_weights_with_string_values(self):
        # Weights provided as strings should be converted
        adapters = [_make_adapter("a", apy=5.0, tvl=1e9)]
        weights = {"a": "1.0"}
        r = self.sim.run_scenario(self._sc(), weights, adapters)
        self.assertAlmostEqual(r.portfolio_return_pct, 5.0, places=4)

    def test_scenario_with_no_name_gets_default(self):
        adapters = [_make_adapter("a", apy=3.0, tvl=1e9)]
        weights = {"a": 1.0}
        sc = {"apy_shocks": {}, "tvl_shocks": {}, "peg_breaks": []}
        r = self.sim.run_scenario(sc, weights, adapters)
        self.assertTrue(r.scenario_name)  # not empty

    def test_multiple_peg_breaks_partial(self):
        # 2 adapters, one peg break → partial loss
        adapters = [
            _make_adapter("pegged", apy=5.0, tvl=1e9, tier="T1"),
            _make_adapter("safe", apy=5.0, tvl=1e9, tier="T1"),
        ]
        weights = {"pegged": 0.5, "safe": 0.5}
        sc = self._sc(peg_breaks=["pegged"])
        r = self.sim.run_scenario(sc, weights, adapters)
        # 0.5 * (-50) + 0.5 * 5 = -25 + 2.5 = -22.5
        self.assertAlmostEqual(r.portfolio_return_pct, -22.5, places=4)

    def test_tvl_shock_does_not_affect_return(self):
        # TVL shock should not change the portfolio return, only trigger checks
        adapters = [_make_adapter("a", apy=5.0, tvl=100_000_000.0, tier="T1")]
        weights = {"a": 1.0}
        sc_no_tvl = self._sc()
        sc_tvl = self._sc(tvl_shocks={"*": 0.5})
        r1 = self.sim.run_scenario(sc_no_tvl, weights, adapters)
        r2 = self.sim.run_scenario(sc_tvl, weights, adapters)
        self.assertAlmostEqual(r1.portfolio_return_pct,
                               r2.portfolio_return_pct, places=4)


# ===========================================================================
# 21. Import hygiene
# ===========================================================================
class TestImportHygiene(unittest.TestCase):

    def _module_source(self):
        import spa_core.analytics.scenario_simulator as m
        return Path(m.__file__).read_text(encoding="utf-8")

    def test_no_requests_import(self):
        src = self._module_source()
        self.assertNotIn("import requests", src)

    def test_no_numpy_import(self):
        src = self._module_source()
        self.assertNotIn("import numpy", src)
        self.assertNotIn("from numpy", src)

    def test_no_execution_import(self):
        src = self._module_source()
        self.assertNotIn("from spa_core.execution", src)
        self.assertNotIn("import spa_core.execution", src)

    def test_no_web3_import(self):
        src = self._module_source()
        self.assertNotIn("import web3", src)

    def test_no_eval_or_exec(self):
        src = self._module_source()
        # Only function calls, not the eval/exec builtins
        for bad in ("eval(", "exec("):
            self.assertNotIn(bad, src)


# ===========================================================================
if __name__ == "__main__":
    unittest.main()
