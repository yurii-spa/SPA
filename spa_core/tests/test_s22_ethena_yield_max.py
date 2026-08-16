"""
spa_core/tests/test_s22_ethena_yield_max.py

Tests for EthenaYieldMaxStrategy (spa_core/strategies/s22_ethena_yield_max.py).

AUD-18 — coverage for previously untested tournament strategies.

Offline-safe: real adapters are never constructed — `_load_adapters` is
patched to a no-op and fake adapters are injected, so no network access
occurs regardless of environment.

Run:
    python3 -m unittest spa_core.tests.test_s22_ethena_yield_max -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s22_ethena_yield_max import (
    EthenaYieldMaxStrategy,
    FALLBACK_APY,
    SLOTS,
    STRATEGY_ID,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
    TIER,
    _norm_apy_pct,
)


# ─── fakes ────────────────────────────────────────────────────────────────────

class _FakeAdapter:
    """Deterministic in-memory stand-in for susde / spark_susds / aave_v3."""

    def __init__(self, apy=12.0, peg_healthy=True, eligible=True):
        self._apy = apy
        self._peg_healthy = peg_healthy
        self._eligible = eligible

    def get_apy(self):
        return self._apy

    def is_peg_healthy(self):
        return self._peg_healthy

    def is_eligible(self):
        return self._eligible


def _make_strategy(adapters=None) -> EthenaYieldMaxStrategy:
    """Build a strategy without touching real adapters (offline-safe)."""
    with patch.object(EthenaYieldMaxStrategy, "_load_adapters", lambda self: None):
        strat = EthenaYieldMaxStrategy()
    strat._adapters = dict(adapters or {})
    return strat


# ─── module constants ─────────────────────────────────────────────────────────

class TestModuleConstants(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(STRATEGY_ID, "S22")
        self.assertEqual(TIER, "T3")

    def test_apy_targets_ordered(self):
        self.assertLess(TARGET_APY_MIN, TARGET_APY_MAX)

    def test_slot_weights_sum_to_one(self):
        self.assertAlmostEqual(
            sum(s["weight"] for s in SLOTS.values()), 1.0, places=9
        )

    def test_t1_anchor_is_60pct(self):
        t1 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T1")
        self.assertAlmostEqual(t1, 0.60, places=9)


# ─── _norm_apy_pct ────────────────────────────────────────────────────────────

class TestNormApyPct(unittest.TestCase):
    def test_decimal_scaled_to_percent(self):
        self.assertAlmostEqual(_norm_apy_pct(0.065, 4.2), 6.5, places=9)

    def test_percent_passed_through(self):
        self.assertAlmostEqual(_norm_apy_pct(6.5, 4.2), 6.5, places=9)

    def test_none_uses_fallback(self):
        self.assertEqual(_norm_apy_pct(None, 4.2), 4.2)

    def test_zero_uses_fallback(self):
        self.assertEqual(_norm_apy_pct(0.0, 4.2), 4.2)

    def test_negative_uses_fallback(self):
        self.assertEqual(_norm_apy_pct(-3.0, 4.2), 4.2)

    def test_bool_uses_fallback(self):
        # bool is an int subclass — must NOT be treated as a numeric APY.
        self.assertEqual(_norm_apy_pct(True, 4.2), 4.2)

    def test_nan_and_inf_use_fallback(self):
        self.assertEqual(_norm_apy_pct(float("nan"), 4.2), 4.2)
        self.assertEqual(_norm_apy_pct(float("inf"), 4.2), 4.2)

    def test_string_uses_fallback(self):
        self.assertEqual(_norm_apy_pct("12", 4.2), 4.2)


# ─── allocation ───────────────────────────────────────────────────────────────

class TestGetAllocationNormal(unittest.TestCase):
    def setUp(self):
        self.strat = _make_strategy()  # no adapters → no depeg, fallback APY

    def test_split_matches_slot_weights(self):
        alloc = self.strat.get_allocation(100_000.0)
        self.assertAlmostEqual(alloc["susde"], 40_000.0, places=2)
        self.assertAlmostEqual(alloc["spark_susds"], 30_000.0, places=2)
        self.assertAlmostEqual(alloc["aave_v3"], 30_000.0, places=2)

    def test_allocation_sums_to_capital(self):
        alloc = self.strat.get_allocation(100_000.0)
        self.assertAlmostEqual(sum(alloc.values()), 100_000.0, places=2)

    def test_zero_capital_all_zero(self):
        alloc = self.strat.get_allocation(0.0)
        self.assertTrue(all(v == 0.0 for v in alloc.values()))

    def test_negative_capital_all_zero(self):
        alloc = self.strat.get_allocation(-10.0)
        self.assertTrue(all(v == 0.0 for v in alloc.values()))

    def test_deterministic(self):
        self.assertEqual(
            self.strat.get_allocation(50_000.0),
            self.strat.get_allocation(50_000.0),
        )


class TestDepegKillSwitch(unittest.TestCase):
    def test_no_adapter_means_no_false_kill(self):
        self.assertFalse(_make_strategy().ethena_depeg_active())

    def test_healthy_peg_keeps_susde_bucket(self):
        strat = _make_strategy({"susde": _FakeAdapter(peg_healthy=True)})
        self.assertFalse(strat.ethena_depeg_active())
        alloc = strat.get_allocation(100_000.0)
        self.assertAlmostEqual(alloc["susde"], 40_000.0, places=2)

    def test_depeg_rotates_susde_bucket_to_safe_harbor(self):
        strat = _make_strategy({"susde": _FakeAdapter(peg_healthy=False)})
        self.assertTrue(strat.ethena_depeg_active())
        alloc = strat.get_allocation(100_000.0)
        # 40% Ethena bucket redistributed 50/50 into Sky + Aave.
        self.assertNotIn("susde", alloc)
        self.assertAlmostEqual(alloc["spark_susds"], 50_000.0, places=2)
        self.assertAlmostEqual(alloc["aave_v3"], 50_000.0, places=2)
        self.assertAlmostEqual(sum(alloc.values()), 100_000.0, places=2)

    def test_adapter_exception_fails_safe_no_kill(self):
        class _Broken:
            def is_peg_healthy(self):
                raise RuntimeError("feed down")

        strat = _make_strategy({"susde": _Broken()})
        self.assertFalse(strat.ethena_depeg_active())

    def test_depeg_risk_summary_goes_full_t1(self):
        strat = _make_strategy({"susde": _FakeAdapter(peg_healthy=False)})
        summary = strat.get_risk_summary()
        self.assertTrue(summary["ethena_depeg"])
        self.assertAlmostEqual(summary["t1_weight_pct"], 100.0, places=2)
        self.assertAlmostEqual(summary["t3_weight_pct"], 0.0, places=2)


# ─── APY ──────────────────────────────────────────────────────────────────────

class TestExpectedApy(unittest.TestCase):
    def test_fallback_blend_matches_docstring(self):
        # 0.40*12.0 + 0.30*6.5 + 0.30*4.2 = 8.01
        strat = _make_strategy()
        self.assertAlmostEqual(strat.get_expected_apy(), 8.01, places=2)

    def test_fake_adapter_apy_overrides_fallback(self):
        strat = _make_strategy({"susde": _FakeAdapter(apy=20.0)})
        expected = 0.40 * 20.0 + 0.30 * FALLBACK_APY["spark_susds"] \
            + 0.30 * FALLBACK_APY["aave_v3"]
        self.assertAlmostEqual(strat.get_expected_apy(), expected, places=2)

    def test_decimal_adapter_apy_normalized(self):
        # Older adapters return decimals; 0.12 must be read as 12%.
        strat = _make_strategy({"susde": _FakeAdapter(apy=0.12)})
        self.assertAlmostEqual(strat.get_expected_apy(), 8.01, places=2)

    def test_broken_adapter_get_apy_uses_fallback(self):
        class _Broken:
            def get_apy(self):
                raise RuntimeError("feed down")

        strat = _make_strategy({"susde": _Broken()})
        self.assertAlmostEqual(strat.get_expected_apy(), 8.01, places=2)


# ─── health / simulate / to_dict ──────────────────────────────────────────────

class TestHealth(unittest.TestCase):
    def test_all_slots_eligible_is_ok(self):
        health = _make_strategy().get_health()
        self.assertEqual(health["overall_status"], "ok")
        self.assertEqual(health["eligible_slots"], health["total_slots"])

    def test_one_ineligible_slot_degrades(self):
        strat = _make_strategy({"susde": _FakeAdapter(eligible=False)})
        health = strat.get_health()
        self.assertEqual(health["overall_status"], "degraded")
        self.assertFalse(health["slots"]["ethena"]["eligible"])


class TestSimulate(unittest.TestCase):
    def setUp(self):
        self.strat = _make_strategy()

    def test_positions_sum_to_capital(self):
        result = self.strat.simulate(100_000.0)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(sum(result["allocation"].values()),
                               100_000.0, places=2)

    def test_yield_consistent_with_positions(self):
        result = self.strat.simulate(100_000.0)
        total = sum(p["annual_yield_usd"] for p in result["positions"].values())
        self.assertAlmostEqual(
            result["expected_annual_yield_usd"], total, places=2
        )

    def test_zero_capital_is_no_capital(self):
        result = self.strat.simulate(0.0)
        self.assertEqual(result["status"], "no_capital")
        self.assertEqual(result["allocation"], {})

    def test_history_ring_appends(self):
        before = len(self.strat._simulate_history)
        self.strat.simulate(10_000.0)
        self.assertEqual(len(self.strat._simulate_history), before + 1)


class TestToDictAndContract(unittest.TestCase):
    def test_to_dict_keys(self):
        d = _make_strategy().to_dict()
        for key in ("strategy_id", "strategy_name", "tier", "slots",
                    "fallback_apy", "risk_scores", "target_apy_min",
                    "target_apy_max", "expected_apy", "health",
                    "risk_summary", "timestamp"):
            self.assertIn(key, d)
        self.assertEqual(d["strategy_id"], "S22")
        self.assertEqual(d["tier"], "T3")

    def test_no_execution_import(self):
        import spa_core.strategies.s22_ethena_yield_max as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("spa_core.execution", source)

    def test_advisory_gate_note_present(self):
        # approved=False is never overridden — the module must say so.
        summary = _make_strategy().get_risk_summary()
        self.assertIn("t3_cap_note", summary)


class TestRegistryIntegration(unittest.TestCase):
    def test_registered_in_tournament_registry(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S22")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T3")
        self.assertEqual(meta.handler_class, "EthenaYieldMaxStrategy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
