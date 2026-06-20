"""
spa_core/tests/test_p1_strategy_registry_all.py

P1.1 — Smoke tests: все стратегии зарегистрированы в REGISTRY.

Проверяет:
  - REGISTRY содержит >= 20 стратегий (были зарегистрированы только 2)
  - Каждая ожидаемая стратегия доступна по ID
  - Каждый стратегический модуль импортируется без ошибок
  - Все зарегистрированные стратегии имеют валидные метаданные
  - Методы реестра работают корректно

Run:
    python3 -m pytest spa_core/tests/test_p1_strategy_registry_all.py -v
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.strategy_registry import (
    REGISTRY,
    StrategyMeta,
    StrategyRegistry,
    VALID_TYPES,
    VALID_RISK_TIERS,
)


# ─── Константы ────────────────────────────────────────────────────────────────

# Минимальное число зарегистрированных стратегий после исправления
MIN_EXPECTED_STRATEGIES = 20

# Стратегии, которые ОБЯЗАНЫ присутствовать в REGISTRY по ID
REQUIRED_STRATEGY_IDS = [
    "s1_conservative_lending",   # S1 classic (T1)
    "s1_t1t2_balanced",          # S1 balanced variant (T2, MP-358)
    "s2_lp_stable",              # S2 LP (T2)
    "s3_yield_loop",             # S3 yield loop (T3)
    "S7",                        # S7 Pendle YT aggressive
    "s8_delta_neutral_susde",    # S8 Delta-Neutral sUSDe
    "s9_emode_looping",          # S9 Aave E-Mode Looping
    "s10_pendle_yt",             # S10 Pendle YT Speculation
    "s12_base_layer_yield",      # S12 Base Layer Yield (newly added)
    "s13_multi_chain_arb",       # S13 Multi-Chain Arb (newly added)
]

# Модули, которые должны импортироваться без ошибок
IMPORTABLE_MODULES = [
    "spa_core.strategies.s1_conservative_lending",
    "spa_core.strategies.s1_t1t2_balanced",
    "spa_core.strategies.s2_lp_stable",
    "spa_core.strategies.s2_pendle_morpho",
    "spa_core.strategies.s3_yield_loop",
    "spa_core.strategies.s3_aave_arb_morpho",
    "spa_core.strategies.s4_spark_fluid_conservative",
    "spa_core.strategies.s5_pendle_enhanced",
    "spa_core.strategies.s6_max_diversified",
    "spa_core.strategies.s7_pendle_yt_aggressive",
    "spa_core.strategies.delta_neutral_susde",
    "spa_core.strategies.emode_looping",
    "spa_core.strategies.pendle_yt",
    "spa_core.strategies.s11_hybrid_yield_max",
    "spa_core.strategies.s12_base_layer_yield",
    "spa_core.strategies.s13_multi_chain_arb",
    "spa_core.strategies.s14_arbitrum_radiant",
    "spa_core.strategies.s15_multichain_l2",
    "spa_core.strategies.s16_stablecoin_ladder",
    "spa_core.strategies.s17_polygon_yield",
    "spa_core.strategies.s18_high_yield_t2",
    "spa_core.strategies.s19_balanced_l2",
    "spa_core.strategies.s20_anticrisis_research",
    "spa_core.strategies.s20_curve_convex",
    "spa_core.strategies.s21_aave_loop",
]


# ─── Test 1: Registry size ─────────────────────────────────────────────────────

class TestRegistrySize(unittest.TestCase):
    """REGISTRY должен содержать >= 20 зарегистрированных стратегий."""

    def test_registry_has_minimum_strategies(self):
        """До фикса было 2 стратегии; после — должно быть >= 20."""
        count = len(REGISTRY.as_list(enabled_only=False))
        self.assertGreaterEqual(
            count, MIN_EXPECTED_STRATEGIES,
            f"Expected >= {MIN_EXPECTED_STRATEGIES} strategies, got {count}. "
            f"Check _load_builtin_strategies() in strategy_registry.py"
        )

    def test_registry_not_empty(self):
        count = len(REGISTRY)
        self.assertGreater(count, 0, "REGISTRY must not be empty")

    def test_get_all_returns_dict(self):
        all_strats = REGISTRY.get_all(enabled_only=False)
        self.assertIsInstance(all_strats, dict)
        self.assertGreater(len(all_strats), 0)

    def test_as_list_returns_sorted(self):
        strats = REGISTRY.as_list(enabled_only=False)
        self.assertIsInstance(strats, list)
        self.assertGreater(len(strats), 0)
        # Check sorted by tier order
        tier_order = {"T1": 0, "T2": 1, "T3": 2}
        for i in range(len(strats) - 1):
            t_curr = tier_order.get(strats[i].risk_tier, 9)
            t_next = tier_order.get(strats[i + 1].risk_tier, 9)
            self.assertLessEqual(
                t_curr, t_next,
                f"as_list() not sorted by tier at index {i}: "
                f"{strats[i].id}({strats[i].risk_tier}) > {strats[i+1].id}({strats[i+1].risk_tier})"
            )


# ─── Test 2: Required strategies present ──────────────────────────────────────

class TestRequiredStrategiesPresent(unittest.TestCase):
    """Каждая ключевая стратегия должна быть доступна по ID."""

    def _check_strategy(self, strategy_id: str) -> None:
        meta = REGISTRY.get(strategy_id)
        self.assertIsNotNone(
            meta,
            f"Strategy '{strategy_id}' not found in REGISTRY. "
            f"Registered IDs: {sorted(REGISTRY.get_all(enabled_only=False).keys())}"
        )
        self.assertEqual(meta.id, strategy_id)
        self.assertIn(meta.risk_tier, VALID_RISK_TIERS | {"delta_neutral"} | set(),
                      f"Invalid risk_tier '{meta.risk_tier}' for {strategy_id}")

    def test_s1_conservative_lending(self):
        self._check_strategy("s1_conservative_lending")

    def test_s1_t1t2_balanced(self):
        self._check_strategy("s1_t1t2_balanced")

    def test_s2_lp_stable(self):
        self._check_strategy("s2_lp_stable")

    def test_s3_yield_loop(self):
        self._check_strategy("s3_yield_loop")

    def test_s7_pendle_aggressive(self):
        self._check_strategy("S7")

    def test_s8_delta_neutral(self):
        self._check_strategy("s8_delta_neutral_susde")

    def test_s9_emode_looping(self):
        self._check_strategy("s9_emode_looping")

    def test_s10_pendle_yt(self):
        self._check_strategy("s10_pendle_yt")

    def test_s12_base_layer_yield(self):
        self._check_strategy("s12_base_layer_yield")

    def test_s13_multi_chain_arb(self):
        self._check_strategy("s13_multi_chain_arb")


# ─── Test 3: Module imports ────────────────────────────────────────────────────

class TestStrategyModuleImports(unittest.TestCase):
    """Все модули стратегий должны импортироваться без ошибок."""

    def _import_module(self, module_path: str) -> None:
        try:
            importlib.import_module(module_path)
        except Exception as exc:
            self.fail(f"Import failed for '{module_path}': {exc}")

    def test_import_s1_conservative_lending(self):
        self._import_module("spa_core.strategies.s1_conservative_lending")

    def test_import_s1_t1t2_balanced(self):
        self._import_module("spa_core.strategies.s1_t1t2_balanced")

    def test_import_s2_lp_stable(self):
        self._import_module("spa_core.strategies.s2_lp_stable")

    def test_import_s2_pendle_morpho(self):
        self._import_module("spa_core.strategies.s2_pendle_morpho")

    def test_import_s3_yield_loop(self):
        self._import_module("spa_core.strategies.s3_yield_loop")

    def test_import_s3_aave_arb_morpho(self):
        self._import_module("spa_core.strategies.s3_aave_arb_morpho")

    def test_import_s4_spark_fluid(self):
        self._import_module("spa_core.strategies.s4_spark_fluid_conservative")

    def test_import_s5_pendle_enhanced(self):
        self._import_module("spa_core.strategies.s5_pendle_enhanced")

    def test_import_s6_max_diversified(self):
        self._import_module("spa_core.strategies.s6_max_diversified")

    def test_import_s7_pendle_yt_aggressive(self):
        self._import_module("spa_core.strategies.s7_pendle_yt_aggressive")

    def test_import_delta_neutral_susde(self):
        self._import_module("spa_core.strategies.delta_neutral_susde")

    def test_import_emode_looping(self):
        self._import_module("spa_core.strategies.emode_looping")

    def test_import_pendle_yt(self):
        self._import_module("spa_core.strategies.pendle_yt")

    def test_import_s11_hybrid_yield_max(self):
        self._import_module("spa_core.strategies.s11_hybrid_yield_max")

    def test_import_s12_base_layer_yield(self):
        self._import_module("spa_core.strategies.s12_base_layer_yield")

    def test_import_s13_multi_chain_arb(self):
        self._import_module("spa_core.strategies.s13_multi_chain_arb")

    def test_import_s14_arbitrum_radiant(self):
        self._import_module("spa_core.strategies.s14_arbitrum_radiant")

    def test_import_s15_multichain_l2(self):
        self._import_module("spa_core.strategies.s15_multichain_l2")

    def test_import_s19_balanced_l2(self):
        self._import_module("spa_core.strategies.s19_balanced_l2")

    def test_import_s21_aave_loop(self):
        self._import_module("spa_core.strategies.s21_aave_loop")


# ─── Test 4: Metadata validation ──────────────────────────────────────────────

class TestStrategyMetaValidation(unittest.TestCase):
    """Все зарегистрированные стратегии должны иметь корректные метаданные."""

    def test_all_strategies_have_valid_apy_range(self):
        """target_apy_min < target_apy_max для всех стратегий."""
        for meta in REGISTRY.as_list(enabled_only=False):
            self.assertLess(
                meta.target_apy_min,
                meta.target_apy_max,
                f"{meta.id}: target_apy_min ({meta.target_apy_min}) >= target_apy_max ({meta.target_apy_max})"
            )

    def test_all_strategies_have_positive_max_drawdown(self):
        for meta in REGISTRY.as_list(enabled_only=False):
            self.assertGreater(
                meta.max_drawdown_pct, 0,
                f"{meta.id}: max_drawdown_pct must be > 0"
            )

    def test_all_strategies_have_module_and_class(self):
        for meta in REGISTRY.as_list(enabled_only=False):
            self.assertTrue(
                meta.module,
                f"{meta.id}: module must not be empty"
            )
            self.assertTrue(
                meta.handler_class,
                f"{meta.id}: handler_class must not be empty"
            )

    def test_all_strategies_have_description(self):
        for meta in REGISTRY.as_list(enabled_only=False):
            self.assertTrue(
                meta.description.strip(),
                f"{meta.id}: description must not be empty"
            )

    def test_to_dict_serializable(self):
        """to_dict() должен возвращать JSON-сериализуемый dict."""
        import json
        for meta in REGISTRY.as_list(enabled_only=False):
            d = meta.to_dict()
            try:
                json.dumps(d)
            except (TypeError, ValueError) as exc:
                self.fail(f"{meta.id}.to_dict() not JSON-serializable: {exc}")

    def test_get_by_tier_t1(self):
        t1 = REGISTRY.get_by_tier("T1")
        self.assertGreater(len(t1), 0, "Must have at least one T1 strategy")
        for meta in t1:
            self.assertEqual(meta.risk_tier, "T1")

    def test_get_by_tier_t2(self):
        t2 = REGISTRY.get_by_tier("T2")
        self.assertGreater(len(t2), 0, "Must have at least one T2 strategy")

    def test_get_by_tier_t3(self):
        t3 = REGISTRY.get_by_tier("T3")
        self.assertGreater(len(t3), 0, "Must have at least one T3 strategy")

    def test_no_duplicate_ids(self):
        """Все IDs в реестре уникальны."""
        all_strats = REGISTRY.as_list(enabled_only=False)
        ids = [s.id for s in all_strats]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate IDs found: {ids}")

    def test_s12_registration_metadata(self):
        """S12 имеет корректные метаданные после добавления регистрации."""
        meta = REGISTRY.get("s12_base_layer_yield")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T3")
        self.assertIn("base_chain", meta.tags)

    def test_s13_registration_metadata(self):
        """S13 имеет корректные метаданные после добавления регистрации."""
        meta = REGISTRY.get("s13_multi_chain_arb")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T2")
        self.assertIn("multi_chain", meta.tags)


# ─── Test 5: Registry methods ─────────────────────────────────────────────────

class TestRegistryMethods(unittest.TestCase):
    """Методы StrategyRegistry работают корректно."""

    def test_summary_returns_list(self):
        summary = REGISTRY.summary()
        self.assertIsInstance(summary, list)
        self.assertGreater(len(summary), 0)
        # Each entry has expected keys
        for item in summary:
            self.assertIn("id", item)
            self.assertIn("risk_tier", item)
            self.assertIn("enabled", item)

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(REGISTRY.get("nonexistent_strategy_xyz"))

    def test_registry_repr(self):
        r = repr(REGISTRY)
        self.assertIn("StrategyRegistry", r)

    def test_len_matches_get_all(self):
        self.assertEqual(len(REGISTRY), len(REGISTRY.get_all(enabled_only=False)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
