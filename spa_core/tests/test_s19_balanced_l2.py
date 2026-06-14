"""
Tests for S19 Balanced L2 Strategy (MP-608).

90 тестов в 10 группах:
  TestInit                (10) — базовая инициализация, константы класса
  TestAdapterKeys          (8) — проверка ключей в L2_ADAPTERS vs ADAPTER_REGISTRY
  TestGetAllocation       (18) — аллокация: равные доли, перераспределение, edge-cases
  TestGetExpectedAPY      (10) — равновзвешенный APY, edge-cases
  TestGetChainDiversityScore (12) — score, eligible_count, description
  TestGetGasSavingsSummary (10) — avg_savings_pct, chains_breakdown
  TestGetHealth            (8) — структура, all_eligible, overall_status
  TestSimulate             (8) — expected_yield_usd, status, chain_results
  TestToDict               (4) — JSON-serializable, STRATEGY_ID
  TestConstants            (2) — типы TARGET_APY_PCT, RISK_SCORE

Запуск:
    python3 -m unittest spa_core.tests.test_s19_balanced_l2 -v
"""
from __future__ import annotations

import json
import unittest
from typing import Optional

# ─── Mock adapter для тестов без реальной сети ───────────────────────────────

class _MockAdapter:
    """Минимальный mock-адаптер для тестирования S19 в изоляции."""

    def __init__(
        self,
        apy: float = 5.0,
        eligible: bool = True,
        raise_apy: bool = False,
        raise_eligible: bool = False,
    ) -> None:
        self._apy = apy
        self._eligible = eligible
        self._raise_apy = raise_apy
        self._raise_eligible = raise_eligible

    def get_apy(self) -> float:
        if self._raise_apy:
            raise RuntimeError("simulated apy error")
        return self._apy

    def is_eligible(self) -> bool:
        if self._raise_eligible:
            raise RuntimeError("simulated eligible error")
        return self._eligible

    def simulate_deposit(self, amount_usd: float) -> dict:
        return {"status": "ok", "amount_usd": amount_usd, "apy_pct": self._apy}


def _make_strategy(adapter_overrides: Optional[dict] = None):
    """Создать BalancedL2Strategy с mock-адаптерами для изолированных тестов."""
    from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy, FALLBACK_APY
    s = BalancedL2Strategy.__new__(BalancedL2Strategy)
    # Инициализировать с дефолтными mock-адаптерами (все eligible, fallback APY)
    s._adapters = {
        "aave_arbitrum":    _MockAdapter(apy=FALLBACK_APY["aave_arbitrum"],    eligible=True),
        "aave_v3_base":     _MockAdapter(apy=FALLBACK_APY["aave_v3_base"],     eligible=True),
        "aave_v3_optimism": _MockAdapter(apy=FALLBACK_APY["aave_v3_optimism"], eligible=True),
        "aave_v3_polygon":  _MockAdapter(apy=FALLBACK_APY["aave_v3_polygon"],  eligible=True),
    }
    if adapter_overrides:
        s._adapters.update(adapter_overrides)
    return s


# ═══════════════════════════════════════════════════════════════════════════════
# TestInit — 10 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestInit(unittest.TestCase):
    """Базовая инициализация и константы класса."""

    def setUp(self):
        from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy
        self.cls = BalancedL2Strategy

    def test_strategy_id_instance(self):
        s = _make_strategy()
        self.assertEqual(s.STRATEGY_ID, "S19")

    def test_strategy_name_instance(self):
        s = _make_strategy()
        self.assertEqual(s.STRATEGY_NAME, "Balanced L2")

    def test_target_apy_pct_instance(self):
        s = _make_strategy()
        self.assertEqual(s.TARGET_APY_PCT, 5.0)

    def test_risk_score_instance(self):
        s = _make_strategy()
        self.assertEqual(s.RISK_SCORE, 0.26)

    def test_adapters_dict(self):
        s = _make_strategy()
        self.assertIsInstance(s._adapters, dict)

    def test_class_strategy_id(self):
        self.assertEqual(self.cls.STRATEGY_ID, "S19")

    def test_class_strategy_name(self):
        self.assertEqual(self.cls.STRATEGY_NAME, "Balanced L2")

    def test_tier_is_t1(self):
        s = _make_strategy()
        self.assertEqual(s.TIER, "T1")

    def test_instance_creation_no_raise(self):
        # __init__ с реальными адаптерами не должен ронять при недоступных импортах
        from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy
        try:
            s = BalancedL2Strategy()
        except Exception as exc:
            self.fail(f"BalancedL2Strategy() raised unexpectedly: {exc}")

    def test_target_apy_is_float(self):
        s = _make_strategy()
        self.assertIsInstance(s.TARGET_APY_PCT, float)


# ═══════════════════════════════════════════════════════════════════════════════
# TestAdapterKeys — 8 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterKeys(unittest.TestCase):
    """Проверка ключей L2_ADAPTERS совпадают с реальными ключами ADAPTER_REGISTRY."""

    def setUp(self):
        from spa_core.strategies.s19_balanced_l2 import L2_ADAPTERS
        self.L2_ADAPTERS = L2_ADAPTERS

    def test_aave_arbitrum_key_present(self):
        self.assertIn("aave_arbitrum", self.L2_ADAPTERS)

    def test_aave_v3_base_key_present(self):
        self.assertIn("aave_v3_base", self.L2_ADAPTERS)

    def test_aave_v3_optimism_key_present(self):
        self.assertIn("aave_v3_optimism", self.L2_ADAPTERS)

    def test_aave_v3_polygon_key_present(self):
        self.assertIn("aave_v3_polygon", self.L2_ADAPTERS)

    def test_exactly_four_keys(self):
        self.assertEqual(len(self.L2_ADAPTERS), 4)

    def test_all_weights_are_025(self):
        for k, v in self.L2_ADAPTERS.items():
            with self.subTest(key=k):
                self.assertAlmostEqual(v, 0.25, places=10)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.L2_ADAPTERS.values()), 1.0, places=10)

    def test_all_keys_are_strings(self):
        for k in self.L2_ADAPTERS:
            self.assertIsInstance(k, str)


# ═══════════════════════════════════════════════════════════════════════════════
# TestGetAllocation — 18 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetAllocation(unittest.TestCase):
    """Аллокация: равные доли, перераспределение, edge-cases."""

    def test_all_eligible_returns_four_adapters(self):
        s = _make_strategy()
        result = s.get_allocation(100_000)
        self.assertEqual(len(result), 4)

    def test_all_eligible_each_gets_25pct(self):
        s = _make_strategy()
        result = s.get_allocation(100_000)
        for key, amount in result.items():
            self.assertAlmostEqual(amount, 25_000.0, places=6,
                                   msg=f"Expected 25000 for {key}, got {amount}")

    def test_all_eligible_sum_equals_capital(self):
        s = _make_strategy()
        capital = 100_000.0
        result = s.get_allocation(capital)
        self.assertAlmostEqual(sum(result.values()), capital, places=6)

    def test_zero_capital_returns_zeros(self):
        s = _make_strategy()
        result = s.get_allocation(0.0)
        self.assertEqual(len(result), 4)
        for v in result.values():
            self.assertEqual(v, 0.0)

    def test_negative_capital_returns_zeros(self):
        s = _make_strategy()
        result = s.get_allocation(-1000.0)
        self.assertEqual(len(result), 4)
        for v in result.values():
            self.assertEqual(v, 0.0)

    def test_one_ineligible_redistributes_to_three(self):
        s = _make_strategy({"aave_arbitrum": _MockAdapter(eligible=False)})
        result = s.get_allocation(90_000)
        self.assertEqual(len(result), 3)
        self.assertNotIn("aave_arbitrum", result)
        for v in result.values():
            self.assertAlmostEqual(v, 30_000.0, places=6)

    def test_one_ineligible_sum_still_equals_capital(self):
        s = _make_strategy({"aave_v3_base": _MockAdapter(eligible=False)})
        capital = 75_000.0
        result = s.get_allocation(capital)
        self.assertAlmostEqual(sum(result.values()), capital, places=6)

    def test_two_ineligible_redistributes_to_two(self):
        s = _make_strategy({
            "aave_arbitrum": _MockAdapter(eligible=False),
            "aave_v3_base":  _MockAdapter(eligible=False),
        })
        result = s.get_allocation(100_000)
        self.assertEqual(len(result), 2)
        for v in result.values():
            self.assertAlmostEqual(v, 50_000.0, places=6)

    def test_two_ineligible_sum_equals_capital(self):
        s = _make_strategy({
            "aave_v3_optimism": _MockAdapter(eligible=False),
            "aave_v3_polygon":  _MockAdapter(eligible=False),
        })
        capital = 80_000.0
        result = s.get_allocation(capital)
        self.assertAlmostEqual(sum(result.values()), capital, places=6)

    def test_three_ineligible_gives_100pct_to_one(self):
        s = _make_strategy({
            "aave_arbitrum":    _MockAdapter(eligible=False),
            "aave_v3_base":     _MockAdapter(eligible=False),
            "aave_v3_optimism": _MockAdapter(eligible=False),
        })
        result = s.get_allocation(100_000)
        self.assertEqual(len(result), 1)
        self.assertIn("aave_v3_polygon", result)
        self.assertAlmostEqual(result["aave_v3_polygon"], 100_000.0, places=6)

    def test_all_ineligible_returns_empty(self):
        s = _make_strategy({
            "aave_arbitrum":    _MockAdapter(eligible=False),
            "aave_v3_base":     _MockAdapter(eligible=False),
            "aave_v3_optimism": _MockAdapter(eligible=False),
            "aave_v3_polygon":  _MockAdapter(eligible=False),
        })
        result = s.get_allocation(100_000)
        self.assertEqual(result, {})

    def test_values_are_floats(self):
        s = _make_strategy()
        result = s.get_allocation(50_000)
        for v in result.values():
            self.assertIsInstance(v, float)

    def test_keys_are_strings(self):
        s = _make_strategy()
        result = s.get_allocation(50_000)
        for k in result.keys():
            self.assertIsInstance(k, str)

    def test_large_capital(self):
        s = _make_strategy()
        capital = 10_000_000.0
        result = s.get_allocation(capital)
        self.assertAlmostEqual(sum(result.values()), capital, places=4)

    def test_small_capital(self):
        s = _make_strategy()
        capital = 0.01
        result = s.get_allocation(capital)
        self.assertAlmostEqual(sum(result.values()), capital, places=12)

    def test_return_type_is_dict(self):
        s = _make_strategy()
        result = s.get_allocation(1000)
        self.assertIsInstance(result, dict)

    def test_eligible_exception_treated_as_eligible(self):
        # Если is_eligible бросает → считаем True (default-safe)
        s = _make_strategy({"aave_arbitrum": _MockAdapter(raise_eligible=True)})
        result = s.get_allocation(100_000)
        self.assertEqual(len(result), 4)

    def test_zero_capital_not_empty_when_eligible(self):
        s = _make_strategy()
        result = s.get_allocation(0.0)
        # Должен вернуть dict с ключами (не пустой), но нулевыми значениями
        self.assertGreater(len(result), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# TestGetExpectedAPY — 10 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetExpectedAPY(unittest.TestCase):
    """Равновзвешенный APY, edge-cases."""

    def test_returns_float(self):
        s = _make_strategy()
        self.assertIsInstance(s.get_expected_apy(), float)

    def test_positive_with_fallback_apys(self):
        s = _make_strategy()
        self.assertGreater(s.get_expected_apy(), 0.0)

    def test_all_fallback_apys_avg(self):
        # (4.6 + 5.0 + 4.8 + 5.1) / 4 = 4.875
        s = _make_strategy()
        self.assertAlmostEqual(s.get_expected_apy(), 4.875, places=6)

    def test_one_eligible_returns_its_apy(self):
        s = _make_strategy({
            "aave_arbitrum":    _MockAdapter(eligible=False),
            "aave_v3_base":     _MockAdapter(eligible=False),
            "aave_v3_optimism": _MockAdapter(eligible=False),
            "aave_v3_polygon":  _MockAdapter(apy=5.1, eligible=True),
        })
        self.assertAlmostEqual(s.get_expected_apy(), 5.1, places=6)

    def test_all_ineligible_returns_zero(self):
        s = _make_strategy({k: _MockAdapter(eligible=False) for k in
                            ["aave_arbitrum", "aave_v3_base", "aave_v3_optimism", "aave_v3_polygon"]})
        self.assertEqual(s.get_expected_apy(), 0.0)

    def test_two_eligible_avg(self):
        s = _make_strategy({
            "aave_arbitrum":    _MockAdapter(apy=4.0, eligible=True),
            "aave_v3_base":     _MockAdapter(apy=6.0, eligible=True),
            "aave_v3_optimism": _MockAdapter(eligible=False),
            "aave_v3_polygon":  _MockAdapter(eligible=False),
        })
        self.assertAlmostEqual(s.get_expected_apy(), 5.0, places=6)

    def test_in_valid_range(self):
        s = _make_strategy()
        apy = s.get_expected_apy()
        self.assertGreater(apy, 1.0)
        self.assertLess(apy, 30.0)

    def test_deterministic(self):
        s = _make_strategy()
        apy1 = s.get_expected_apy()
        apy2 = s.get_expected_apy()
        self.assertEqual(apy1, apy2)

    def test_non_negative(self):
        s = _make_strategy()
        self.assertGreaterEqual(s.get_expected_apy(), 0.0)

    def test_apy_exception_falls_back_to_fallback(self):
        from spa_core.strategies.s19_balanced_l2 import FALLBACK_APY
        s = _make_strategy({"aave_arbitrum": _MockAdapter(raise_apy=True)})
        apy = s.get_expected_apy()
        # Должен использовать fallback 4.6 для arb вместо raise
        expected = (FALLBACK_APY["aave_arbitrum"] + FALLBACK_APY["aave_v3_base"] +
                    FALLBACK_APY["aave_v3_optimism"] + FALLBACK_APY["aave_v3_polygon"]) / 4
        self.assertAlmostEqual(apy, expected, places=6)


# ═══════════════════════════════════════════════════════════════════════════════
# TestGetChainDiversityScore — 12 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetChainDiversityScore(unittest.TestCase):
    """score, eligible_count, description, chains."""

    def test_returns_dict(self):
        s = _make_strategy()
        self.assertIsInstance(s.get_chain_diversity_score(), dict)

    def test_score_key_present(self):
        s = _make_strategy()
        self.assertIn("score", s.get_chain_diversity_score())

    def test_chains_key_present(self):
        s = _make_strategy()
        self.assertIn("chains", s.get_chain_diversity_score())

    def test_eligible_count_key_present(self):
        s = _make_strategy()
        self.assertIn("eligible_count", s.get_chain_diversity_score())

    def test_description_key_present(self):
        s = _make_strategy()
        self.assertIn("description", s.get_chain_diversity_score())

    def test_all_eligible_score_is_one(self):
        s = _make_strategy()
        result = s.get_chain_diversity_score()
        self.assertAlmostEqual(result["score"], 1.0, places=6)

    def test_all_eligible_description_is_perfect(self):
        s = _make_strategy()
        result = s.get_chain_diversity_score()
        self.assertEqual(result["description"], "Perfect L2 diversity")

    def test_all_eligible_eligible_count_is_four(self):
        s = _make_strategy()
        result = s.get_chain_diversity_score()
        self.assertEqual(result["eligible_count"], 4)

    def test_three_eligible_score_is_075(self):
        s = _make_strategy({"aave_arbitrum": _MockAdapter(eligible=False)})
        result = s.get_chain_diversity_score()
        self.assertAlmostEqual(result["score"], 0.75, places=6)

    def test_two_eligible_score_is_05(self):
        s = _make_strategy({
            "aave_arbitrum": _MockAdapter(eligible=False),
            "aave_v3_base":  _MockAdapter(eligible=False),
        })
        result = s.get_chain_diversity_score()
        self.assertAlmostEqual(result["score"], 0.5, places=6)

    def test_one_eligible_score_is_025(self):
        s = _make_strategy({
            "aave_arbitrum":    _MockAdapter(eligible=False),
            "aave_v3_base":     _MockAdapter(eligible=False),
            "aave_v3_optimism": _MockAdapter(eligible=False),
        })
        result = s.get_chain_diversity_score()
        self.assertAlmostEqual(result["score"], 0.25, places=6)

    def test_chains_has_four_elements(self):
        s = _make_strategy()
        result = s.get_chain_diversity_score()
        self.assertEqual(len(result["chains"]), 4)


# ═══════════════════════════════════════════════════════════════════════════════
# TestGetGasSavingsSummary — 10 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetGasSavingsSummary(unittest.TestCase):
    """avg_savings_pct, chains_breakdown."""

    def test_returns_dict(self):
        s = _make_strategy()
        self.assertIsInstance(s.get_gas_savings_summary(), dict)

    def test_avg_savings_pct_key_present(self):
        s = _make_strategy()
        self.assertIn("avg_savings_pct", s.get_gas_savings_summary())

    def test_chains_breakdown_key_present(self):
        s = _make_strategy()
        self.assertIn("chains_breakdown", s.get_gas_savings_summary())

    def test_avg_savings_pct_positive(self):
        s = _make_strategy()
        self.assertGreater(s.get_gas_savings_summary()["avg_savings_pct"], 0.0)

    def test_chains_breakdown_is_dict(self):
        s = _make_strategy()
        result = s.get_gas_savings_summary()
        self.assertIsInstance(result["chains_breakdown"], dict)

    def test_chains_breakdown_contains_arbitrum(self):
        s = _make_strategy()
        self.assertIn("arbitrum", s.get_gas_savings_summary()["chains_breakdown"])

    def test_chains_breakdown_contains_base(self):
        s = _make_strategy()
        self.assertIn("base", s.get_gas_savings_summary()["chains_breakdown"])

    def test_chains_breakdown_contains_optimism(self):
        s = _make_strategy()
        self.assertIn("optimism", s.get_gas_savings_summary()["chains_breakdown"])

    def test_chains_breakdown_contains_polygon(self):
        s = _make_strategy()
        self.assertIn("polygon", s.get_gas_savings_summary()["chains_breakdown"])

    def test_avg_savings_equals_925_all_eligible(self):
        # (90 + 95 + 95 + 90) / 4 = 92.5
        s = _make_strategy()
        result = s.get_gas_savings_summary()
        self.assertAlmostEqual(result["avg_savings_pct"], 92.5, places=2)


# ═══════════════════════════════════════════════════════════════════════════════
# TestGetHealth — 8 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetHealth(unittest.TestCase):
    """Структура, all_eligible, overall_status."""

    def test_returns_dict(self):
        s = _make_strategy()
        self.assertIsInstance(s.get_health(), dict)

    def test_strategy_id_is_s19(self):
        s = _make_strategy()
        self.assertEqual(s.get_health()["strategy_id"], "S19")

    def test_all_eligible_is_bool(self):
        s = _make_strategy()
        self.assertIsInstance(s.get_health()["all_eligible"], bool)

    def test_overall_status_valid_values(self):
        s = _make_strategy()
        status = s.get_health()["overall_status"]
        self.assertIn(status, ("ok", "warning", "degraded"))

    def test_chain_breakdown_has_four_entries(self):
        s = _make_strategy()
        self.assertEqual(len(s.get_health()["chain_breakdown"]), 4)

    def test_expected_apy_positive(self):
        s = _make_strategy()
        self.assertGreater(s.get_health()["expected_apy"], 0.0)

    def test_all_eligible_true_by_default(self):
        s = _make_strategy()
        self.assertTrue(s.get_health()["all_eligible"])

    def test_overall_status_ok_when_all_eligible(self):
        s = _make_strategy()
        self.assertEqual(s.get_health()["overall_status"], "ok")


# ═══════════════════════════════════════════════════════════════════════════════
# TestSimulate — 8 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimulate(unittest.TestCase):
    """expected_yield_usd, status, chain_results."""

    def test_returns_dict(self):
        s = _make_strategy()
        self.assertIsInstance(s.simulate(100_000), dict)

    def test_total_capital_preserved(self):
        s = _make_strategy()
        result = s.simulate(100_000)
        self.assertEqual(result["total_capital"], 100_000)

    def test_expected_annual_yield_positive(self):
        s = _make_strategy()
        result = s.simulate(100_000)
        self.assertGreater(result["expected_annual_yield_usd"], 0.0)

    def test_expected_apy_pct_positive(self):
        s = _make_strategy()
        result = s.simulate(100_000)
        self.assertGreater(result["expected_apy_pct"], 0.0)

    def test_status_ok(self):
        s = _make_strategy()
        result = s.simulate(100_000)
        self.assertEqual(result["status"], "ok")

    def test_chain_results_has_four_entries(self):
        s = _make_strategy()
        result = s.simulate(100_000)
        self.assertEqual(len(result["chain_results"]), 4)

    def test_allocation_present_in_result(self):
        s = _make_strategy()
        result = s.simulate(100_000)
        self.assertIn("allocation", result)
        self.assertIsInstance(result["allocation"], dict)

    def test_zero_capital_zero_yield(self):
        s = _make_strategy()
        result = s.simulate(0.0)
        self.assertEqual(result["expected_annual_yield_usd"], 0.0)

    def test_yield_calculation_correctness(self):
        # 100_000 USD × 4.875% APY = 4875.0 USD/year
        s = _make_strategy()
        result = s.simulate(100_000)
        expected_yield = 100_000 * 4.875 / 100
        self.assertAlmostEqual(result["expected_annual_yield_usd"], expected_yield, places=2)


# ═══════════════════════════════════════════════════════════════════════════════
# TestToDict — 4 теста
# ═══════════════════════════════════════════════════════════════════════════════

class TestToDict(unittest.TestCase):
    """JSON-serializable, STRATEGY_ID, timestamp."""

    def test_returns_dict(self):
        s = _make_strategy()
        self.assertIsInstance(s.to_dict(), dict)

    def test_json_serializable(self):
        s = _make_strategy()
        try:
            json.dumps(s.to_dict())
        except (TypeError, ValueError) as exc:
            self.fail(f"to_dict() not JSON serializable: {exc}")

    def test_strategy_id_is_s19(self):
        s = _make_strategy()
        self.assertEqual(s.to_dict()["strategy_id"], "S19")

    def test_timestamp_present(self):
        s = _make_strategy()
        self.assertIn("timestamp", s.to_dict())


# ═══════════════════════════════════════════════════════════════════════════════
# TestConstants — 2 теста
# ═══════════════════════════════════════════════════════════════════════════════

class TestConstants(unittest.TestCase):
    """Типы модульных констант."""

    def test_target_apy_pct_is_float(self):
        from spa_core.strategies.s19_balanced_l2 import TARGET_APY_PCT
        self.assertIsInstance(TARGET_APY_PCT, float)

    def test_risk_score_class_attr_is_float(self):
        from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy
        s = BalancedL2Strategy.__new__(BalancedL2Strategy)
        s._adapters = {}
        self.assertIsInstance(s.RISK_SCORE, float)


# ═══════════════════════════════════════════════════════════════════════════════
# Дополнительные тесты (граничные случаи и дополнительная покрываемость)
# ═══════════════════════════════════════════════════════════════════════════════

class TestModuleConstants(unittest.TestCase):
    """Модульные константы: FALLBACK_APY, RISK_SCORES, GAS_INFO."""

    def test_fallback_apy_has_four_entries(self):
        from spa_core.strategies.s19_balanced_l2 import FALLBACK_APY
        self.assertEqual(len(FALLBACK_APY), 4)

    def test_fallback_apy_all_positive(self):
        from spa_core.strategies.s19_balanced_l2 import FALLBACK_APY
        for k, v in FALLBACK_APY.items():
            self.assertGreater(v, 0.0, msg=f"FALLBACK_APY[{k}] should be > 0")

    def test_risk_scores_all_in_range(self):
        from spa_core.strategies.s19_balanced_l2 import RISK_SCORES
        for k, v in RISK_SCORES.items():
            self.assertGreater(v, 0.0, msg=f"RISK_SCORES[{k}] should be > 0")
            self.assertLess(v, 1.0, msg=f"RISK_SCORES[{k}] should be < 1.0")

    def test_gas_info_all_four_adapters(self):
        from spa_core.strategies.s19_balanced_l2 import GAS_INFO
        self.assertEqual(len(GAS_INFO), 4)

    def test_gas_info_all_savings_positive(self):
        from spa_core.strategies.s19_balanced_l2 import GAS_INFO
        for k, v in GAS_INFO.items():
            self.assertGreater(v["savings_pct"], 0.0, msg=f"GAS_INFO[{k}].savings_pct")

    def test_target_apy_min_less_than_max(self):
        from spa_core.strategies.s19_balanced_l2 import TARGET_APY_MIN, TARGET_APY_MAX
        self.assertLess(TARGET_APY_MIN, TARGET_APY_MAX)

    def test_strategy_id_module_level(self):
        from spa_core.strategies.s19_balanced_l2 import STRATEGY_ID
        self.assertEqual(STRATEGY_ID, "S19")

    def test_strategy_name_module_level(self):
        from spa_core.strategies.s19_balanced_l2 import STRATEGY_NAME
        self.assertEqual(STRATEGY_NAME, "Balanced L2")


class TestAllIneligibleEdgeCases(unittest.TestCase):
    """Граничные случаи при полном отсутствии eligible адаптеров."""

    def _all_ineligible(self):
        return _make_strategy({k: _MockAdapter(eligible=False) for k in
                               ["aave_arbitrum", "aave_v3_base", "aave_v3_optimism", "aave_v3_polygon"]})

    def test_allocation_empty_when_all_ineligible(self):
        s = self._all_ineligible()
        self.assertEqual(s.get_allocation(100_000), {})

    def test_expected_apy_zero_when_all_ineligible(self):
        s = self._all_ineligible()
        self.assertEqual(s.get_expected_apy(), 0.0)

    def test_simulate_status_no_eligible_adapters(self):
        s = self._all_ineligible()
        result = s.simulate(100_000)
        self.assertEqual(result["status"], "no_eligible_adapters")

    def test_simulate_yield_zero_when_all_ineligible(self):
        s = self._all_ineligible()
        result = s.simulate(100_000)
        self.assertEqual(result["expected_annual_yield_usd"], 0.0)

    def test_health_all_eligible_false(self):
        s = self._all_ineligible()
        self.assertFalse(s.get_health()["all_eligible"])

    def test_health_status_degraded_when_all_ineligible(self):
        s = self._all_ineligible()
        self.assertEqual(s.get_health()["overall_status"], "degraded")

    def test_diversity_score_zero_when_all_ineligible(self):
        s = self._all_ineligible()
        result = s.get_chain_diversity_score()
        self.assertAlmostEqual(result["score"], 0.0, places=6)

    def test_diversity_description_no_eligible(self):
        s = self._all_ineligible()
        result = s.get_chain_diversity_score()
        self.assertEqual(result["description"], "No eligible L2 chains")


class TestAdapterLoading(unittest.TestCase):
    """Проверка адаптеров в реальном экземпляре (без mock)."""

    def test_adapters_dict_initialized(self):
        from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy
        s = BalancedL2Strategy()
        self.assertIsInstance(s._adapters, dict)

    def test_each_adapter_key_if_loaded_is_valid(self):
        from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy, L2_ADAPTERS
        s = BalancedL2Strategy()
        for key in s._adapters:
            self.assertIn(key, L2_ADAPTERS,
                          msg=f"Loaded adapter key '{key}' not in L2_ADAPTERS")

    def test_health_call_does_not_raise(self):
        from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy
        s = BalancedL2Strategy()
        try:
            s.get_health()
        except Exception as exc:
            self.fail(f"get_health() raised: {exc}")

    def test_to_dict_call_does_not_raise(self):
        from spa_core.strategies.s19_balanced_l2 import BalancedL2Strategy
        s = BalancedL2Strategy()
        try:
            s.to_dict()
        except Exception as exc:
            self.fail(f"to_dict() raised: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
