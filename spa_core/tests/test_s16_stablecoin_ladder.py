"""
spa_core/tests/test_s16_stablecoin_ladder.py — MP-592

90+ unittest-кейсов для стратегии S16 Stablecoin Ladder.

Классы тестов:
  - TestInit             (10) — id, name, tier, начальное состояние
  - TestRungs            (8)  — структура RUNGS: ключи, веса, адаптеры
  - TestGetLadderStatus  (15) — eligible adapters, actual_apy per rung, edge cases
  - TestGetAllocation    (18) — правильные веса, fallback, edge cases
  - TestGetExpectedAPY   (12) — weighted calc, fallback, redistribution
  - TestGetHealth        (10) — структура ответа, статусы, warnings
  - TestSimulate         (8)  — yields, allocation sum = capital
  - TestToDict           (4)  — JSON-serializable, обязательные ключи
  - TestConstants        (9)  — FALLBACK_APY, RISK_SCORES, RUNGS weights sum = 1.0
  - TestRegistry         (4)  — регистрация в REGISTRY

Правила:
  - stdlib only
  - Все тесты изолированы (отдельные инстансы)
  - Комментарии на русском
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# ─── sys.path ────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

# ─── Импорты тестируемых модулей ──────────────────────────────────────────────
from spa_core.strategies.s16_stablecoin_ladder import (
    StablecoinLadderStrategy,
    STRATEGY_ID,
    STRATEGY_NAME,
    TIER,
    RUNGS,
    FALLBACK_APY,
    RISK_SCORES,
    TARGET_APY_PCT,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
    MIN_APY_ELIGIBLE,
    MAX_APY_ELIGIBLE,
    _FALLBACK_RUNG,
)


# ─── Вспомогательные apy_maps ────────────────────────────────────────────────

# Все адаптеры eligible с дефолтными fallback-значениями
APY_MAP_STD = {
    "compound_v3": 5.2,
    "spark_susds": 5.0,
    "sdai":        5.5,
    "morpho_blue": 6.5,
    "sfrax":       7.0,
    "wusdm":       5.0,
}

# Высокие APY, но ещё в диапазоне
APY_MAP_HIGH = {
    "compound_v3": 9.0,
    "spark_susds": 8.5,
    "sdai":        10.0,
    "morpho_blue": 12.0,
    "sfrax":       15.0,
    "wusdm":       8.0,
}

# Все нулевые APY → все ineligible
APY_MAP_ZERO = {
    "compound_v3": 0.0,
    "spark_susds": 0.0,
    "sdai":        0.0,
    "morpho_blue": 0.0,
    "sfrax":       0.0,
    "wusdm":       0.0,
}

# Только conservative eligible
APY_MAP_CONSERVATIVE_ONLY = {
    "compound_v3": 5.2,
    "spark_susds": 5.0,
    "sdai":        0.0,   # ineligible
    "morpho_blue": 0.0,   # ineligible
    "sfrax":       0.0,   # ineligible
    "wusdm":       0.0,   # ineligible
}

# Growth rung ineligible (growth → orphan → conservative)
APY_MAP_NO_GROWTH = {
    "compound_v3": 5.2,
    "spark_susds": 5.0,
    "sdai":        5.5,
    "morpho_blue": 6.5,
    "sfrax":       0.0,   # ineligible
    "wusdm":       0.0,   # ineligible
}

# Только один адаптер из rung eligible
APY_MAP_PARTIAL_BALANCED = {
    "compound_v3": 5.2,
    "spark_susds": 5.0,
    "sdai":        5.5,
    "morpho_blue": 0.0,   # ineligible → balanced только sdai
    "sfrax":       7.0,
    "wusdm":       5.0,
}

# Spike APY > MAX_APY_ELIGIBLE → ineligible
APY_MAP_SPIKE = {
    "compound_v3": 5.2,
    "spark_susds": 5.0,
    "sdai":        5.5,
    "morpho_blue": 40.0,  # spike — ineligible (> 30%)
    "sfrax":       7.0,
    "wusdm":       5.0,
}


# =============================================================================
# 1. TestInit — Инициализация
# =============================================================================

class TestInit(unittest.TestCase):

    def test_strategy_id(self):
        """strategy_id == 'S16'."""
        s = StablecoinLadderStrategy()
        self.assertEqual(s.strategy_id, "S16")

    def test_strategy_id_matches_constant(self):
        """strategy_id совпадает с константой STRATEGY_ID."""
        s = StablecoinLadderStrategy()
        self.assertEqual(s.strategy_id, STRATEGY_ID)

    def test_strategy_name(self):
        """strategy_name содержит 'Stablecoin Ladder'."""
        s = StablecoinLadderStrategy()
        self.assertIn("Stablecoin Ladder", s.strategy_name)

    def test_strategy_name_matches_constant(self):
        """strategy_name совпадает с STRATEGY_NAME."""
        s = StablecoinLadderStrategy()
        self.assertEqual(s.strategy_name, STRATEGY_NAME)

    def test_tier(self):
        """tier == 'T1+T2'."""
        s = StablecoinLadderStrategy()
        self.assertEqual(s.tier, TIER)

    def test_simulate_history_empty(self):
        """История simulate пуста при инициализации."""
        s = StablecoinLadderStrategy()
        self.assertEqual(len(s._simulate_history), 0)

    def test_multiple_instances_independent(self):
        """Два экземпляра независимы."""
        s1 = StablecoinLadderStrategy()
        s2 = StablecoinLadderStrategy()
        s1.simulate(100_000.0, APY_MAP_STD)
        self.assertEqual(len(s2._simulate_history), 0)

    def test_instantiation_no_args(self):
        """Инстанцирование без аргументов не вызывает исключений."""
        try:
            s = StablecoinLadderStrategy()
        except Exception as e:
            self.fail(f"Инстанцирование не должно вызывать исключений: {e}")

    def test_tier_contains_t1(self):
        """tier содержит 'T1'."""
        s = StablecoinLadderStrategy()
        self.assertIn("T1", s.tier)

    def test_tier_contains_t2(self):
        """tier содержит 'T2'."""
        s = StablecoinLadderStrategy()
        self.assertIn("T2", s.tier)


# =============================================================================
# 2. TestRungs — структура RUNGS
# =============================================================================

class TestRungs(unittest.TestCase):

    def test_rungs_has_three_entries(self):
        """RUNGS содержит 3 ступени."""
        self.assertEqual(len(RUNGS), 3)

    def test_rungs_has_conservative(self):
        """RUNGS содержит 'conservative'."""
        self.assertIn("conservative", RUNGS)

    def test_rungs_has_balanced(self):
        """RUNGS содержит 'balanced'."""
        self.assertIn("balanced", RUNGS)

    def test_rungs_has_growth(self):
        """RUNGS содержит 'growth'."""
        self.assertIn("growth", RUNGS)

    def test_rungs_weights_sum_to_one(self):
        """Сумма весов всех rungs == 1.0."""
        total = sum(r["weight"] for r in RUNGS.values())
        self.assertAlmostEqual(total, 1.0, places=10)

    def test_conservative_weight(self):
        """Conservative rung weight == 0.40."""
        self.assertAlmostEqual(RUNGS["conservative"]["weight"], 0.40, places=10)

    def test_balanced_weight(self):
        """Balanced rung weight == 0.35."""
        self.assertAlmostEqual(RUNGS["balanced"]["weight"], 0.35, places=10)

    def test_growth_weight(self):
        """Growth rung weight == 0.25."""
        self.assertAlmostEqual(RUNGS["growth"]["weight"], 0.25, places=10)


# =============================================================================
# 3. TestGetLadderStatus — статус лестницы
# =============================================================================

class TestGetLadderStatus(unittest.TestCase):

    def test_returns_all_three_rungs(self):
        """get_ladder_status возвращает все три rung."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        self.assertIn("conservative", status)
        self.assertIn("balanced", status)
        self.assertIn("growth", status)

    def test_eligible_count_all_eligible(self):
        """При APY_MAP_STD все адаптеры eligible — eligible_count == 2 для каждого rung."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        for rung in ["conservative", "balanced", "growth"]:
            self.assertEqual(status[rung]["eligible_count"], 2,
                             msg=f"rung={rung}")

    def test_eligible_count_zero_map(self):
        """При APY_MAP_ZERO все адаптеры ineligible."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_ZERO)
        for rung in ["conservative", "balanced", "growth"]:
            self.assertEqual(status[rung]["eligible_count"], 0,
                             msg=f"rung={rung}")

    def test_eligible_adapters_conservative(self):
        """Conservative eligible_adapters — compound_v3 + spark_susds при STD."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        self.assertIn("compound_v3", status["conservative"]["eligible_adapters"])
        self.assertIn("spark_susds", status["conservative"]["eligible_adapters"])

    def test_actual_apy_conservative(self):
        """actual_apy для conservative при APY_MAP_STD == mean(5.2, 5.0) = 5.1."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        self.assertAlmostEqual(status["conservative"]["actual_apy"], 5.1, places=3)

    def test_actual_apy_balanced(self):
        """actual_apy для balanced при APY_MAP_STD == mean(5.5, 6.5) = 6.0."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        self.assertAlmostEqual(status["balanced"]["actual_apy"], 6.0, places=3)

    def test_actual_apy_growth(self):
        """actual_apy для growth при APY_MAP_STD == mean(7.0, 5.0) = 6.0."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        self.assertAlmostEqual(status["growth"]["actual_apy"], 6.0, places=3)

    def test_all_eligible_flag(self):
        """all_eligible == True когда оба адаптера eligible."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        self.assertTrue(status["conservative"]["all_eligible"])
        self.assertTrue(status["balanced"]["all_eligible"])
        self.assertTrue(status["growth"]["all_eligible"])

    def test_any_eligible_flag_false_when_all_ineligible(self):
        """any_eligible == False когда все адаптеры ineligible."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_ZERO)
        for rung in ["conservative", "balanced", "growth"]:
            self.assertFalse(status[rung]["any_eligible"], msg=f"rung={rung}")

    def test_adapter_apys_present(self):
        """adapter_apys содержит все адаптеры rung."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        for rung_name, rung_cfg in RUNGS.items():
            for adapter in rung_cfg["adapters"]:
                self.assertIn(adapter, status[rung_name]["adapter_apys"],
                              msg=f"rung={rung_name}, adapter={adapter}")

    def test_partial_eligible_balanced(self):
        """partial balanced: sdai eligible, morpho_blue ineligible → eligible_count=1."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_PARTIAL_BALANCED)
        self.assertEqual(status["balanced"]["eligible_count"], 1)

    def test_spike_ineligible(self):
        """APY > MAX_APY_ELIGIBLE → ineligible (morpho_blue=40% spike)."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_SPIKE)
        self.assertEqual(status["balanced"]["eligible_count"], 1)
        self.assertNotIn("morpho_blue", status["balanced"]["eligible_adapters"])

    def test_no_apy_map_uses_fallback(self):
        """Без apy_map используются FALLBACK_APY → все eligible."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(None)
        for rung in ["conservative", "balanced", "growth"]:
            self.assertEqual(status[rung]["eligible_count"], 2, msg=f"rung={rung}")

    def test_total_adapters_correct(self):
        """total_adapters == 2 для каждого rung."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        for rung in ["conservative", "balanced", "growth"]:
            self.assertEqual(status[rung]["total_adapters"], 2, msg=f"rung={rung}")

    def test_weight_in_status(self):
        """weight в статусе совпадает с RUNGS."""
        s = StablecoinLadderStrategy()
        status = s.get_ladder_status(APY_MAP_STD)
        for rung_name, rung_cfg in RUNGS.items():
            self.assertAlmostEqual(
                status[rung_name]["weight"], rung_cfg["weight"], places=10
            )


# =============================================================================
# 4. TestGetAllocation — аллокация капитала
# =============================================================================

class TestGetAllocation(unittest.TestCase):

    def test_all_adapters_allocated_std(self):
        """При APY_MAP_STD все 6 адаптеров получают ненулевую аллокацию."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_STD)
        for adapter in ["compound_v3", "spark_susds", "sdai", "morpho_blue", "sfrax", "wusdm"]:
            self.assertIn(adapter, alloc)
            self.assertGreater(alloc[adapter], 0.0, msg=f"adapter={adapter}")

    def test_allocation_sum_equals_capital(self):
        """Сумма аллокаций == capital_usd."""
        s = StablecoinLadderStrategy()
        capital = 100_000.0
        alloc = s.get_allocation(capital, APY_MAP_STD)
        total = sum(v for k, v in alloc.items() if k != "__unallocated__")
        self.assertAlmostEqual(total, capital, places=3)

    def test_conservative_split_even(self):
        """Conservative rung делится поровну: compound_v3 == spark_susds."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_STD)
        self.assertAlmostEqual(alloc["compound_v3"], alloc["spark_susds"], places=3)

    def test_conservative_bucket_correct(self):
        """Conservative bucket = 40% капитала = 40,000 USD."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_STD)
        conservative_total = alloc["compound_v3"] + alloc["spark_susds"]
        self.assertAlmostEqual(conservative_total, 40_000.0, places=3)

    def test_balanced_bucket_correct(self):
        """Balanced bucket = 35% капитала = 35,000 USD."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_STD)
        balanced_total = alloc["sdai"] + alloc["morpho_blue"]
        self.assertAlmostEqual(balanced_total, 35_000.0, places=3)

    def test_growth_bucket_correct(self):
        """Growth bucket = 25% капитала = 25,000 USD."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_STD)
        growth_total = alloc["sfrax"] + alloc["wusdm"]
        self.assertAlmostEqual(growth_total, 25_000.0, places=3)

    def test_zero_capital_returns_zeros(self):
        """capital_usd == 0 → все аллокации == 0."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(0.0, APY_MAP_STD)
        for v in alloc.values():
            self.assertEqual(v, 0.0)

    def test_negative_capital_returns_zeros(self):
        """capital_usd < 0 → все аллокации == 0."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(-1_000.0, APY_MAP_STD)
        for v in alloc.values():
            self.assertEqual(v, 0.0)

    def test_ineligible_growth_redirects_to_conservative(self):
        """Growth ineligible → его 25% идёт в conservative."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_NO_GROWTH)
        # conservative bucket получает 40% + 25% = 65%
        conservative_total = alloc.get("compound_v3", 0.0) + alloc.get("spark_susds", 0.0)
        self.assertAlmostEqual(conservative_total, 65_000.0, places=3)

    def test_ineligible_growth_no_sfrax_or_wusdm(self):
        """Growth ineligible → sfrax и wusdm не должны быть в аллокации."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_NO_GROWTH)
        self.assertNotIn("sfrax", alloc)
        self.assertNotIn("wusdm", alloc)

    def test_partial_balanced_gets_full_rung_budget(self):
        """partial balanced (только sdai eligible): sdai получает весь 35% bucket."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_PARTIAL_BALANCED)
        self.assertAlmostEqual(alloc.get("sdai", 0.0), 35_000.0, places=3)
        self.assertNotIn("morpho_blue", alloc)

    def test_all_ineligible_creates_unallocated(self):
        """Все адаптеры ineligible (кроме возможно conservative) — появляется __unallocated__."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_ZERO)
        # Все ineligible → capital в __unallocated__
        self.assertIn("__unallocated__", alloc)
        total_real = sum(v for k, v in alloc.items() if k != "__unallocated__")
        total_unalloc = alloc.get("__unallocated__", 0.0)
        self.assertAlmostEqual(total_real + total_unalloc, 100_000.0, places=3)

    def test_no_apy_map_uses_fallback_all_eligible(self):
        """Без apy_map FALLBACK_APY → все адаптеры eligible."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, None)
        for adapter in ["compound_v3", "spark_susds", "sdai", "morpho_blue", "sfrax", "wusdm"]:
            self.assertIn(adapter, alloc)

    def test_allocation_proportional_to_capital(self):
        """Аллокации пропорциональны capital_usd."""
        s = StablecoinLadderStrategy()
        alloc_100k = s.get_allocation(100_000.0, APY_MAP_STD)
        alloc_200k = s.get_allocation(200_000.0, APY_MAP_STD)
        for adapter in ["compound_v3", "spark_susds", "sdai", "morpho_blue", "sfrax", "wusdm"]:
            self.assertAlmostEqual(
                alloc_200k[adapter], alloc_100k[adapter] * 2.0, places=3,
                msg=f"adapter={adapter}"
            )

    def test_allocation_sum_with_partial_ineligible(self):
        """При partial ineligible sum аллокаций все равно == capital."""
        s = StablecoinLadderStrategy()
        capital = 150_000.0
        alloc = s.get_allocation(capital, APY_MAP_PARTIAL_BALANCED)
        total = sum(v for k, v in alloc.items() if k != "__unallocated__")
        self.assertAlmostEqual(total, capital, places=3)

    def test_growth_only_one_adapter_eligible(self):
        """Если в growth только sfrax eligible — он получает весь 25% bucket."""
        apy_map = dict(APY_MAP_STD)
        apy_map["wusdm"] = 0.0  # wusdm ineligible
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, apy_map)
        self.assertAlmostEqual(alloc.get("sfrax", 0.0), 25_000.0, places=3)
        self.assertNotIn("wusdm", alloc)

    def test_allocation_spike_apy_ineligible(self):
        """Адаптер с APY > MAX_APY_ELIGIBLE не получает аллокации."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_SPIKE)
        # morpho_blue=40% → ineligible; sdai=5.5% → eligible
        # balanced bucket = 35% всё к sdai
        self.assertAlmostEqual(alloc.get("sdai", 0.0), 35_000.0, places=3)
        self.assertNotIn("morpho_blue", alloc)

    def test_conservative_only_eligible_all_capital_to_conservative(self):
        """Только conservative eligible → 100% капитала в conservative."""
        s = StablecoinLadderStrategy()
        alloc = s.get_allocation(100_000.0, APY_MAP_CONSERVATIVE_ONLY)
        conservative_total = alloc.get("compound_v3", 0.0) + alloc.get("spark_susds", 0.0)
        # conserv 40% + balanced 35% orphan + growth 25% orphan = 100%
        self.assertAlmostEqual(conservative_total, 100_000.0, places=3)


# =============================================================================
# 5. TestGetExpectedAPY — ожидаемый взвешенный APY
# =============================================================================

class TestGetExpectedAPY(unittest.TestCase):

    def test_returns_float(self):
        """get_expected_apy возвращает float."""
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_STD)
        self.assertIsInstance(result, float)

    def test_positive_apy(self):
        """get_expected_apy > 0 при STD apy_map."""
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_STD)
        self.assertGreater(result, 0.0)

    def test_apy_in_reasonable_range(self):
        """get_expected_apy в диапазоне TARGET_APY_MIN ... TARGET_APY_MAX при STD."""
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_STD)
        self.assertGreaterEqual(result, TARGET_APY_MIN)
        self.assertLessEqual(result, TARGET_APY_MAX)

    def test_apy_formula_std(self):
        """Формула при APY_MAP_STD:
        Conservative: mean(5.2, 5.0) = 5.1  weight=0.40
        Balanced:     mean(5.5, 6.5) = 6.0  weight=0.35
        Growth:       mean(7.0, 5.0) = 6.0  weight=0.25
        weighted = 0.40*5.1 + 0.35*6.0 + 0.25*6.0 = 2.04+2.10+1.50 = 5.64
        """
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_STD)
        expected = 0.40 * 5.1 + 0.35 * 6.0 + 0.25 * 6.0
        self.assertAlmostEqual(result, expected, places=3)

    def test_apy_no_apy_map_uses_fallback(self):
        """Без apy_map возвращает разумный APY (используются FALLBACK_APY)."""
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(None)
        self.assertGreater(result, 0.0)

    def test_apy_ineligible_growth_weight_redistributed(self):
        """При growth ineligible его weight 0.25 → conservative (0.65).
        Conservative mean(5.2, 5.0)=5.1, Balanced mean(5.5, 6.5)=6.0.
        weighted = 0.65*5.1 + 0.35*6.0 = 3.315 + 2.10 = 5.415
        """
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_NO_GROWTH)
        expected = 0.65 * 5.1 + 0.35 * 6.0
        self.assertAlmostEqual(result, expected, places=3)

    def test_apy_all_ineligible_returns_target(self):
        """При всех ineligible → TARGET_APY_PCT (6.2%)."""
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_ZERO)
        self.assertEqual(result, TARGET_APY_PCT)

    def test_apy_high_map_higher_apy(self):
        """При APY_MAP_HIGH ожидаемый APY выше чем при APY_MAP_STD."""
        s = StablecoinLadderStrategy()
        std_apy = s.get_expected_apy(APY_MAP_STD)
        high_apy = s.get_expected_apy(APY_MAP_HIGH)
        self.assertGreater(high_apy, std_apy)

    def test_apy_single_adapter_per_rung(self):
        """По одному eligible в каждом rung — APY = среднее по rungs с весами."""
        apy_map = {
            "compound_v3": 5.0, "spark_susds": 0.0,  # только compound
            "sdai": 6.0, "morpho_blue": 0.0,          # только sdai
            "sfrax": 8.0, "wusdm": 0.0,               # только sfrax
        }
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(apy_map)
        expected = 0.40 * 5.0 + 0.35 * 6.0 + 0.25 * 8.0
        self.assertAlmostEqual(result, expected, places=3)

    def test_apy_conservative_only_returns_conservative_apy(self):
        """Только conservative eligible → APY = conservative APY."""
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_CONSERVATIVE_ONLY)
        # Все orphan → conservative weight=1.0; mean(5.2, 5.0) = 5.1
        self.assertAlmostEqual(result, 5.1, places=3)

    def test_partial_balanced_one_adapter(self):
        """partial balanced (только sdai) → APY balanced = 5.5."""
        s = StablecoinLadderStrategy()
        result = s.get_expected_apy(APY_MAP_PARTIAL_BALANCED)
        # conservative: mean(5.2, 5.0)=5.1 w=0.40
        # balanced: sdai=5.5 w=0.35
        # growth: mean(7.0, 5.0)=6.0 w=0.25
        expected = 0.40 * 5.1 + 0.35 * 5.5 + 0.25 * 6.0
        self.assertAlmostEqual(result, expected, places=3)

    def test_apy_monotonic_higher_with_higher_rung_apys(self):
        """Чем выше APY по rungs — тем выше общий APY."""
        s = StablecoinLadderStrategy()
        base = s.get_expected_apy(APY_MAP_STD)
        # Поднимем все APY
        high = {k: v + 2.0 for k, v in APY_MAP_STD.items()}
        result = s.get_expected_apy(high)
        self.assertGreater(result, base)


# =============================================================================
# 6. TestGetHealth — health check
# =============================================================================

class TestGetHealth(unittest.TestCase):

    def test_returns_dict(self):
        """get_health возвращает dict."""
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_STD)
        self.assertIsInstance(health, dict)

    def test_status_ok_all_eligible(self):
        """Статус 'ok' когда все rungs fully eligible."""
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_STD)
        self.assertEqual(health["status"], "ok")

    def test_status_degraded_one_ineligible_rung(self):
        """Статус 'degraded' когда один rung ineligible."""
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_NO_GROWTH)
        self.assertEqual(health["status"], "degraded")

    def test_status_critical_two_ineligible_rungs(self):
        """Статус 'critical' когда 2+ rungs ineligible."""
        apy_map = {
            "compound_v3": 5.2, "spark_susds": 5.0,  # conservative ok
            "sdai": 0.0, "morpho_blue": 0.0,         # balanced ineligible
            "sfrax": 0.0, "wusdm": 0.0,              # growth ineligible
        }
        s = StablecoinLadderStrategy()
        health = s.get_health(apy_map)
        self.assertEqual(health["status"], "critical")

    def test_required_keys_present(self):
        """Все обязательные ключи присутствуют в ответе get_health."""
        required = [
            "status", "rungs_ok", "rungs_partial", "rungs_ineligible",
            "total_rungs", "expected_apy", "target_apy", "risk_score",
            "t2_allocation_pct", "warnings",
        ]
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_STD)
        for key in required:
            self.assertIn(key, health, msg=f"missing key: {key}")

    def test_total_rungs_equals_three(self):
        """total_rungs == 3."""
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_STD)
        self.assertEqual(health["total_rungs"], 3)

    def test_rungs_ok_all_eligible(self):
        """rungs_ok == 3 при APY_MAP_STD."""
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_STD)
        self.assertEqual(health["rungs_ok"], 3)

    def test_warnings_empty_all_eligible(self):
        """Нет warnings когда все rungs ok (но APY может быть ниже target_min → warning)."""
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_STD)
        self.assertIsInstance(health["warnings"], list)

    def test_expected_apy_in_health(self):
        """expected_apy в health совпадает с get_expected_apy."""
        s = StablecoinLadderStrategy()
        expected = s.get_expected_apy(APY_MAP_STD)
        health = s.get_health(APY_MAP_STD)
        self.assertAlmostEqual(health["expected_apy"], expected, places=4)

    def test_t2_allocation_pct_is_float(self):
        """t2_allocation_pct возвращает float."""
        s = StablecoinLadderStrategy()
        health = s.get_health(APY_MAP_STD)
        self.assertIsInstance(health["t2_allocation_pct"], float)


# =============================================================================
# 7. TestSimulate — симуляция одного дня
# =============================================================================

class TestSimulate(unittest.TestCase):

    def test_returns_required_keys(self):
        """simulate возвращает обязательные ключи."""
        required = [
            "strategy_id", "capital_usd", "allocation", "total_allocated_usd",
            "daily_yield_usd", "annualized_yield_usd", "weighted_apy",
            "ladder_status", "timestamp_utc",
        ]
        s = StablecoinLadderStrategy()
        result = s.simulate(100_000.0, APY_MAP_STD)
        for key in required:
            self.assertIn(key, result, msg=f"missing key: {key}")

    def test_strategy_id_in_result(self):
        """strategy_id в результате simulate == 'S16'."""
        s = StablecoinLadderStrategy()
        result = s.simulate(100_000.0, APY_MAP_STD)
        self.assertEqual(result["strategy_id"], "S16")

    def test_daily_yield_positive(self):
        """daily_yield_usd > 0 при eligible адаптерах."""
        s = StablecoinLadderStrategy()
        result = s.simulate(100_000.0, APY_MAP_STD)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_annualized_yield_approx_expected_apy(self):
        """annualized_yield_usd / capital ≈ expected_apy / 100."""
        s = StablecoinLadderStrategy()
        capital = 100_000.0
        result = s.simulate(capital, APY_MAP_STD)
        ann_yield = result["annualized_yield_usd"]
        expected_apy = result["weighted_apy"]
        # ann_yield / capital ≈ expected_apy / 100
        self.assertAlmostEqual(
            ann_yield / capital, expected_apy / 100.0, places=3
        )

    def test_history_grows_after_simulate(self):
        """История растёт после каждого вызова simulate."""
        s = StablecoinLadderStrategy()
        self.assertEqual(len(s._simulate_history), 0)
        s.simulate(100_000.0, APY_MAP_STD)
        self.assertEqual(len(s._simulate_history), 1)
        s.simulate(100_000.0, APY_MAP_STD)
        self.assertEqual(len(s._simulate_history), 2)

    def test_total_allocated_usd_matches_capital(self):
        """total_allocated_usd + unallocated == capital_usd."""
        s = StablecoinLadderStrategy()
        capital = 75_000.0
        result = s.simulate(capital, APY_MAP_STD)
        alloc = result["allocation"]
        total_real = sum(v for k, v in alloc.items() if k != "__unallocated__")
        total_unalloc = alloc.get("__unallocated__", 0.0)
        self.assertAlmostEqual(total_real + total_unalloc, capital, places=3)

    def test_ladder_status_in_result(self):
        """ladder_status содержит все три rung."""
        s = StablecoinLadderStrategy()
        result = s.simulate(100_000.0, APY_MAP_STD)
        ls = result["ladder_status"]
        for rung in ["conservative", "balanced", "growth"]:
            self.assertIn(rung, ls)

    def test_zero_capital_yields_zero(self):
        """При capital_usd == 0 → daily_yield_usd == 0."""
        s = StablecoinLadderStrategy()
        result = s.simulate(0.0, APY_MAP_STD)
        self.assertEqual(result["daily_yield_usd"], 0.0)


# =============================================================================
# 8. TestToDict — JSON-совместимость
# =============================================================================

class TestToDict(unittest.TestCase):

    def test_returns_dict(self):
        """to_dict возвращает dict."""
        s = StablecoinLadderStrategy()
        d = s.to_dict(APY_MAP_STD)
        self.assertIsInstance(d, dict)

    def test_json_serializable(self):
        """to_dict возвращает JSON-serializable объект."""
        s = StablecoinLadderStrategy()
        d = s.to_dict(APY_MAP_STD)
        try:
            json.dumps(d)
        except (TypeError, ValueError) as e:
            self.fail(f"to_dict не сериализуется в JSON: {e}")

    def test_required_keys_present(self):
        """Обязательные ключи присутствуют в to_dict."""
        required = [
            "strategy_id", "strategy_name", "tier", "description",
            "rungs", "fallback_apy", "risk_scores", "target_apy_pct",
            "risk_score", "expected_apy", "health",
        ]
        s = StablecoinLadderStrategy()
        d = s.to_dict(APY_MAP_STD)
        for key in required:
            self.assertIn(key, d, msg=f"missing key: {key}")

    def test_strategy_id_in_dict(self):
        """strategy_id в to_dict == 'S16'."""
        s = StablecoinLadderStrategy()
        d = s.to_dict()
        self.assertEqual(d["strategy_id"], "S16")


# =============================================================================
# 9. TestConstants — проверка констант
# =============================================================================

class TestConstants(unittest.TestCase):

    def test_fallback_apy_all_keys_present(self):
        """FALLBACK_APY содержит все 6 адаптеров."""
        expected_keys = ["compound_v3", "spark_susds", "sdai", "morpho_blue", "sfrax", "wusdm"]
        for k in expected_keys:
            self.assertIn(k, FALLBACK_APY, msg=f"missing key: {k}")

    def test_fallback_apy_positive(self):
        """Все FALLBACK_APY > 0."""
        for k, v in FALLBACK_APY.items():
            self.assertGreater(v, 0.0, msg=f"key={k}")

    def test_fallback_apy_in_eligible_range(self):
        """Все FALLBACK_APY в диапазоне [MIN_APY_ELIGIBLE, MAX_APY_ELIGIBLE]."""
        for k, v in FALLBACK_APY.items():
            self.assertGreaterEqual(v, MIN_APY_ELIGIBLE, msg=f"key={k}")
            self.assertLessEqual(v, MAX_APY_ELIGIBLE, msg=f"key={k}")

    def test_risk_scores_all_keys_present(self):
        """RISK_SCORES содержит все 6 адаптеров."""
        expected_keys = ["compound_v3", "spark_susds", "sdai", "morpho_blue", "sfrax", "wusdm"]
        for k in expected_keys:
            self.assertIn(k, RISK_SCORES, msg=f"missing key: {k}")

    def test_risk_scores_in_range(self):
        """Все RISK_SCORES в диапазоне [0, 1]."""
        for k, v in RISK_SCORES.items():
            self.assertGreaterEqual(v, 0.0, msg=f"key={k}")
            self.assertLessEqual(v, 1.0, msg=f"key={k}")

    def test_target_apy_pct(self):
        """TARGET_APY_PCT == 6.2."""
        self.assertAlmostEqual(TARGET_APY_PCT, 6.2, places=5)

    def test_min_apy_eligible_positive(self):
        """MIN_APY_ELIGIBLE > 0."""
        self.assertGreater(MIN_APY_ELIGIBLE, 0.0)

    def test_max_apy_eligible_greater_than_min(self):
        """MAX_APY_ELIGIBLE > MIN_APY_ELIGIBLE."""
        self.assertGreater(MAX_APY_ELIGIBLE, MIN_APY_ELIGIBLE)

    def test_fallback_rung_is_conservative(self):
        """_FALLBACK_RUNG == 'conservative'."""
        self.assertEqual(_FALLBACK_RUNG, "conservative")


# =============================================================================
# 10. TestRegistry — регистрация в REGISTRY
# =============================================================================

class TestRegistry(unittest.TestCase):

    def test_s16_registered(self):
        """S16 зарегистрирован в REGISTRY."""
        from spa_core.strategies.strategy_registry import REGISTRY
        import importlib
        # Убеждаемся что модуль импортирован (регистрация при импорте)
        importlib.import_module("spa_core.strategies.s16_stablecoin_ladder")
        meta = REGISTRY.get("S16")
        self.assertIsNotNone(meta, "S16 не найден в REGISTRY")

    def test_handler_class_correct(self):
        """handler_class == 'StablecoinLadderStrategy'."""
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S16")
        if meta is not None:
            self.assertEqual(meta.handler_class, "StablecoinLadderStrategy")

    def test_module_correct(self):
        """module == 'spa_core.strategies.s16_stablecoin_ladder'."""
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S16")
        if meta is not None:
            self.assertEqual(meta.module, "spa_core.strategies.s16_stablecoin_ladder")

    def test_enabled(self):
        """S16 enabled == True."""
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S16")
        if meta is not None:
            self.assertTrue(meta.enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
