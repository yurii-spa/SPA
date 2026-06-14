"""
tests/test_s13_multi_chain_arb.py — S13 Multi-Chain Yield Arbitrage

Unit-тесты для S13 Multi-Chain Yield Arbitrage strategy.
37 тестов, покрывающих: константы (10), get_phase (5),
compute_chain_yields (5), select_allocation Phase 1 (5),
select_allocation Phase 2 (5), run_day интеграция (5),
to_dict/edge-cases (2).

Запуск:
    python3 -m pytest tests/test_s13_multi_chain_arb.py -v
    python3 tests/test_s13_multi_chain_arb.py
"""
import unittest
import sys
import os

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.expanduser("~/Documents/SPA_Claude"))

from spa_core.strategies.s13_multi_chain_arb import (
    MultiChainArbStrategy,
    STRATEGY_ID,
    STRATEGY_NAME,
    TIER,
    RISK_SCORE,
    TARGET_APY_PCT,
    DESCRIPTION,
    PHASE2_DATE,
    SPREAD_THRESHOLD_PCT,
    BASE_MAX_ALLOCATION,
    PHASE1_WEIGHTS,
    ETH_WEIGHTS,
    BASE_WEIGHTS,
    _weighted_apy,
    _DEFAULT_APY,
)


# ─── Блок 1: Константы (10 тестов) ───────────────────────────────────────────

class TestS13Constants(unittest.TestCase):
    """Тесты 1–10: Константы модуля."""

    def test_strategy_id(self):
        """STRATEGY_ID должен быть 's13_multi_chain_arb'."""
        self.assertEqual(STRATEGY_ID, "s13_multi_chain_arb")

    def test_strategy_name(self):
        """STRATEGY_NAME должен содержать 'S13'."""
        self.assertIn("S13", STRATEGY_NAME)

    def test_tier_is_T2(self):
        """TIER должен быть 'T2'."""
        self.assertEqual(TIER, "T2")

    def test_risk_score_value(self):
        """RISK_SCORE должен быть 0.45."""
        self.assertAlmostEqual(RISK_SCORE, 0.45, places=5)

    def test_risk_score_in_range(self):
        """RISK_SCORE должен быть в диапазоне 0.0–1.0."""
        self.assertGreaterEqual(RISK_SCORE, 0.0)
        self.assertLessEqual(RISK_SCORE, 1.0)

    def test_target_apy_value(self):
        """TARGET_APY_PCT должен быть 8.5."""
        self.assertAlmostEqual(TARGET_APY_PCT, 8.5, places=5)

    def test_phase2_date_format(self):
        """PHASE2_DATE должен быть ISO-форматом 'YYYY-MM-DD'."""
        import re
        self.assertRegex(PHASE2_DATE, r"^\d{4}-\d{2}-\d{2}$")

    def test_phase2_date_value(self):
        """PHASE2_DATE должен быть '2026-08-01'."""
        self.assertEqual(PHASE2_DATE, "2026-08-01")

    def test_spread_threshold_value(self):
        """SPREAD_THRESHOLD_PCT должен быть 1.5."""
        self.assertAlmostEqual(SPREAD_THRESHOLD_PCT, 1.5, places=5)

    def test_base_max_allocation(self):
        """BASE_MAX_ALLOCATION должен быть 0.30."""
        self.assertAlmostEqual(BASE_MAX_ALLOCATION, 0.30, places=5)


# ─── Блок 2: get_phase (5 тестов) ────────────────────────────────────────────

class TestS13GetPhase(unittest.TestCase):
    """Тесты 11–15: get_phase() логика."""

    def setUp(self):
        self.strategy = MultiChainArbStrategy()

    def test_phase1_before_phase2_date(self):
        """Дата до 2026-08-01 → phase1."""
        self.assertEqual(self.strategy.get_phase("2026-06-12"), "phase1")

    def test_phase1_day_before_go_live(self):
        """2026-07-31 (день до go-live) → phase1."""
        self.assertEqual(self.strategy.get_phase("2026-07-31"), "phase1")

    def test_phase2_on_go_live_date(self):
        """2026-08-01 (точная дата go-live) → phase2."""
        self.assertEqual(self.strategy.get_phase("2026-08-01"), "phase2")

    def test_phase2_after_go_live(self):
        """Дата после 2026-08-01 → phase2."""
        self.assertEqual(self.strategy.get_phase("2026-12-01"), "phase2")

    def test_phase_default_is_phase1_today(self):
        """Сегодня (2026-06-12) без аргумента → phase1 (до go-live)."""
        # Сегодня 2026-06-12, PHASE2_DATE = 2026-08-01 → phase1
        result = self.strategy.get_phase()
        self.assertEqual(result, "phase1")


# ─── Блок 3: compute_chain_yields (5 тестов) ─────────────────────────────────

class TestS13ComputeChainYields(unittest.TestCase):
    """Тесты 16–20: compute_chain_yields()."""

    def setUp(self):
        self.strategy = MultiChainArbStrategy()

    def test_returns_three_chains(self):
        """compute_chain_yields() должен вернуть словарь с ключами eth, arb, base."""
        result = self.strategy.compute_chain_yields({})
        self.assertIn("eth", result)
        self.assertIn("arb", result)
        self.assertIn("base", result)

    def test_defaults_used_when_apy_map_empty(self):
        """При пустом apy_map все значения должны быть > 0 (используют дефолты)."""
        result = self.strategy.compute_chain_yields({})
        self.assertGreater(result["eth"], 0.0)
        self.assertGreater(result["arb"], 0.0)
        self.assertGreater(result["base"], 0.0)

    def test_uses_provided_apy_for_eth(self):
        """Переданные ETH APY должны влиять на eth в результате."""
        apy_map = {"aave_v3": 10.0, "compound_v3": 10.0, "morpho_blue": 10.0}
        result = self.strategy.compute_chain_yields(apy_map)
        # При всех ETH = 10.0, взвешенный ETH = 10.0
        self.assertAlmostEqual(result["eth"], 10.0, places=3)

    def test_arb_uses_aave_v3_arbitrum(self):
        """aave_v3_arbitrum в apy_map должен использоваться для arb."""
        apy_map = {"aave_v3_arbitrum": 7.5}
        result = self.strategy.compute_chain_yields(apy_map)
        self.assertAlmostEqual(result["arb"], 7.5, places=4)

    def test_base_uses_base_adapters(self):
        """Base adapters в apy_map должны влиять на base в результате."""
        apy_map = {"aave_v3_base": 8.0, "morpho_blue_base": 8.0}
        result = self.strategy.compute_chain_yields(apy_map)
        # BASE_WEIGHTS: aave_v3_base=0.50, morpho_blue_base=0.50 → avg = 8.0
        self.assertAlmostEqual(result["base"], 8.0, places=3)


# ─── Блок 4: select_allocation Phase 1 (5 тестов) ───────────────────────────

class TestS13SelectAllocationPhase1(unittest.TestCase):
    """Тесты 21–25: select_allocation() в Phase 1."""

    def setUp(self):
        self.strategy = MultiChainArbStrategy()
        self.chain_yields = {"eth": 5.0, "arb": 5.2, "base": 9.0}  # huge spread

    def test_phase1_always_eth_only(self):
        """Phase 1: аллокация всегда ETH (никаких Base адаптеров)."""
        weights = self.strategy.select_allocation(self.chain_yields, "phase1")
        self.assertNotIn("aave_v3_base", weights)
        self.assertNotIn("morpho_blue_base", weights)

    def test_phase1_contains_eth_adapters(self):
        """Phase 1: веса должны содержать ETH адаптеры."""
        weights = self.strategy.select_allocation(self.chain_yields, "phase1")
        self.assertIn("aave_v3", weights)
        self.assertIn("compound_v3", weights)
        self.assertIn("morpho_blue", weights)

    def test_phase1_weights_sum_to_one(self):
        """Phase 1: сумма весов должна быть 1.0."""
        weights = self.strategy.select_allocation(self.chain_yields, "phase1")
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)

    def test_phase1_ignores_spread(self):
        """Phase 1: даже при огромном спреде (Base 20% > ETH) — 0% Base."""
        huge_spread = {"eth": 3.0, "arb": 5.0, "base": 20.0}
        weights = self.strategy.select_allocation(huge_spread, "phase1")
        self.assertNotIn("aave_v3_base", weights)
        self.assertNotIn("morpho_blue_base", weights)

    def test_phase1_matches_phase1_weights_constant(self):
        """Phase 1: веса должны совпадать с PHASE1_WEIGHTS."""
        weights = self.strategy.select_allocation(self.chain_yields, "phase1")
        for adapter, w in PHASE1_WEIGHTS.items():
            self.assertAlmostEqual(weights[adapter], w, places=5)


# ─── Блок 5: select_allocation Phase 2 (5 тестов) ───────────────────────────

class TestS13SelectAllocationPhase2(unittest.TestCase):
    """Тесты 26–30: select_allocation() в Phase 2 (cross-chain арбитраж)."""

    def setUp(self):
        self.strategy = MultiChainArbStrategy()

    def test_phase2_no_spread_uses_eth_only(self):
        """Phase 2: ETH APY >= Base APY → 100% ETH (нет спреда)."""
        chain_yields = {"eth": 7.0, "arb": 5.2, "base": 6.0}
        # 6.0 < 7.0 + 1.5 = 8.5 → нет спреда
        weights = self.strategy.select_allocation(chain_yields, "phase2")
        self.assertNotIn("aave_v3_base", weights)
        self.assertNotIn("morpho_blue_base", weights)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)

    def test_phase2_spread_activates_base(self):
        """Phase 2: Base APY > ETH APY + 1.5% → Base allocation активна."""
        chain_yields = {"eth": 5.0, "arb": 5.2, "base": 7.0}
        # 7.0 > 5.0 + 1.5 = 6.5 → спред активен
        weights = self.strategy.select_allocation(chain_yields, "phase2")
        # Должны быть Base адаптеры
        self.assertIn("aave_v3_base", weights)
        self.assertIn("morpho_blue_base", weights)

    def test_phase2_base_allocation_capped_at_30pct(self):
        """Phase 2: суммарная доля Base адаптеров <= BASE_MAX_ALLOCATION (30%)."""
        chain_yields = {"eth": 3.0, "arb": 5.2, "base": 10.0}
        weights = self.strategy.select_allocation(chain_yields, "phase2")
        base_total = sum(
            w for k, w in weights.items()
            if k in BASE_WEIGHTS
        )
        self.assertLessEqual(base_total, BASE_MAX_ALLOCATION + 1e-9)

    def test_phase2_weights_sum_to_one_with_spread(self):
        """Phase 2 с активным спредом: сумма весов = 1.0."""
        chain_yields = {"eth": 4.0, "arb": 5.2, "base": 8.0}
        weights = self.strategy.select_allocation(chain_yields, "phase2")
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)

    def test_phase2_exact_threshold_no_spread(self):
        """Phase 2: Base APY == ETH APY + threshold → спред НЕ активируется (граничное условие)."""
        chain_yields = {"eth": 5.0, "arb": 5.2, "base": 6.5}
        # 6.5 == 5.0 + 1.5 = 6.5 → НЕ строго больше → нет спреда
        weights = self.strategy.select_allocation(chain_yields, "phase2")
        self.assertNotIn("aave_v3_base", weights)
        self.assertNotIn("morpho_blue_base", weights)


# ─── Блок 6: run_day интеграция (5 тестов) ───────────────────────────────────

class TestS13RunDay(unittest.TestCase):
    """Тесты 31–35: run_day() интеграционные."""

    def setUp(self):
        self.strategy = MultiChainArbStrategy()
        self.capital  = 100_000.0

    def test_run_day_returns_dict(self):
        """run_day() должен возвращать dict."""
        result = self.strategy.run_day("2026-06-12", {}, self.capital)
        self.assertIsInstance(result, dict)

    def test_run_day_has_required_keys(self):
        """run_day() результат должен содержать все обязательные ключи."""
        result = self.strategy.run_day("2026-06-12", {}, self.capital)
        required = [
            "strategy_id", "date", "phase", "apy_pct",
            "allocation_pct", "chain_spreads", "best_chain", "capital",
        ]
        for key in required:
            self.assertIn(key, result, msg=f"Missing key: {key}")

    def test_run_day_phase1_today(self):
        """run_day() с датой 2026-06-12 → phase='phase1'."""
        result = self.strategy.run_day("2026-06-12", {}, self.capital)
        self.assertEqual(result["phase"], "phase1")

    def test_run_day_phase2_after_go_live(self):
        """run_day() с датой 2026-08-01 → phase='phase2'."""
        result = self.strategy.run_day("2026-08-01", {}, self.capital)
        self.assertEqual(result["phase"], "phase2")

    def test_run_day_apy_positive(self):
        """run_day() должен вернуть apy_pct > 0."""
        result = self.strategy.run_day("2026-06-12", {}, self.capital)
        self.assertGreater(result["apy_pct"], 0.0)

    def test_run_day_strategy_id_matches(self):
        """run_day() strategy_id должен совпадать с константой."""
        result = self.strategy.run_day("2026-06-12", {}, self.capital)
        self.assertEqual(result["strategy_id"], STRATEGY_ID)

    def test_run_day_best_chain_valid(self):
        """run_day() best_chain должен быть одним из: eth, arb, base."""
        result = self.strategy.run_day("2026-06-12", {}, self.capital)
        self.assertIn(result["best_chain"], ["eth", "arb", "base"])

    def test_run_day_capital_preserved(self):
        """run_day() capital в результате должен совпадать с переданным."""
        result = self.strategy.run_day("2026-06-12", {}, self.capital)
        self.assertAlmostEqual(result["capital"], self.capital)

    def test_run_day_with_live_apy_map(self):
        """run_day() с live APY-данными должен использовать их корректно."""
        live = {
            "aave_v3":          3.5,
            "compound_v3":      4.8,
            "morpho_blue":      6.5,
            "aave_v3_arbitrum": 5.2,
            "aave_v3_base":     4.5,
            "morpho_blue_base": 6.2,
        }
        result = self.strategy.run_day("2026-06-12", live, self.capital)
        self.assertGreater(result["apy_pct"], 0.0)
        self.assertIn("eth", result["chain_spreads"])

    def test_run_day_phase2_cross_chain_spread(self):
        """Phase 2 с достаточным спредом: Base адаптеры попадают в allocation_pct."""
        live = {
            "aave_v3":          3.0,
            "compound_v3":      3.0,
            "morpho_blue":      3.0,
            "aave_v3_base":     8.0,
            "morpho_blue_base": 8.0,
        }
        # eth_avg = 3.0, base_avg = 8.0, spread = 5.0 > 1.5 → Base активна
        result = self.strategy.run_day("2026-08-15", live, self.capital)
        self.assertEqual(result["phase"], "phase2")
        alloc = result["allocation_pct"]
        has_base = "aave_v3_base" in alloc or "morpho_blue_base" in alloc
        self.assertTrue(has_base, "Phase 2 with large spread should allocate to Base")


# ─── Блок 7: to_dict / edge cases (2 теста) ──────────────────────────────────

class TestS13ToDictAndEdgeCases(unittest.TestCase):
    """Тесты 36–37: to_dict() и граничные случаи."""

    def setUp(self):
        self.strategy = MultiChainArbStrategy()

    def test_to_dict_has_required_keys(self):
        """to_dict() должен содержать все обязательные метаданные."""
        info = self.strategy.to_dict()
        required = [
            "strategy_id", "name", "tier", "risk_score",
            "target_apy_pct", "description",
            "phase2_date", "spread_threshold_pct", "base_max_allocation",
        ]
        for key in required:
            self.assertIn(key, info, msg=f"Missing key: {key}")

    def test_to_dict_values_match_constants(self):
        """to_dict() значения должны совпадать с модульными константами."""
        info = self.strategy.to_dict()
        self.assertEqual(info["strategy_id"], STRATEGY_ID)
        self.assertEqual(info["tier"], TIER)
        self.assertAlmostEqual(info["risk_score"], RISK_SCORE, places=5)
        self.assertAlmostEqual(info["target_apy_pct"], TARGET_APY_PCT, places=5)
        self.assertEqual(info["phase2_date"], PHASE2_DATE)
        self.assertAlmostEqual(info["spread_threshold_pct"], SPREAD_THRESHOLD_PCT, places=5)
        self.assertAlmostEqual(info["base_max_allocation"], BASE_MAX_ALLOCATION, places=5)


# ─── Дополнительные тесты (для достижения 35+) ───────────────────────────────

class TestS13WeightsInvariants(unittest.TestCase):
    """Тесты 38–40: Инварианты весов."""

    def test_phase1_weights_sum_to_one(self):
        """PHASE1_WEIGHTS должны суммироваться в 1.0."""
        self.assertAlmostEqual(sum(PHASE1_WEIGHTS.values()), 1.0, places=5)

    def test_eth_weights_sum_to_one(self):
        """ETH_WEIGHTS должны суммироваться в 1.0."""
        self.assertAlmostEqual(sum(ETH_WEIGHTS.values()), 1.0, places=5)

    def test_base_weights_sum_to_one(self):
        """BASE_WEIGHTS должны суммироваться в 1.0."""
        self.assertAlmostEqual(sum(BASE_WEIGHTS.values()), 1.0, places=5)

    def test_phase1_no_base_adapters(self):
        """PHASE1_WEIGHTS не должны содержать Base chain адаптеры."""
        self.assertNotIn("aave_v3_base", PHASE1_WEIGHTS)
        self.assertNotIn("morpho_blue_base", PHASE1_WEIGHTS)

    def test_default_apy_all_positive(self):
        """Все значения _DEFAULT_APY должны быть > 0."""
        for adapter, apy in _DEFAULT_APY.items():
            self.assertGreater(apy, 0.0, msg=f"{adapter} default APY <= 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
