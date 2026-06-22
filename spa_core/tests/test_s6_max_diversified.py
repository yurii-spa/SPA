"""
spa_core/tests/test_s6_max_diversified.py — MP-397

65+ unittest-кейсов для стратегии S6 Max Diversified.

Классы тестов:
  - TestS6Import (5)              — импорт, константы, аллокация
  - TestS6ComputeWeightedAPY (15) — взвешенный APY, redistribution, edge cases
  - TestS6SimulateDay (10)        — структура ответа, P&L, ключи
  - TestS6Concentration (12)      — check_concentration, T2 лимит, get_t2_exposure
  - TestS6Diversity (8)           — diversity score, vs_baseline, сравнение со стратегиями
  - TestS6VPortfolioFormat (15)   — to_vportfolio_format: ключи, значения, типы

Правила:
  - stdlib only, никаких внешних зависимостей
  - Все тесты изолированы
  - Комментарии на русском
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# ─── sys.path — позволяет запускать из любого CWD ─────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

# ─── Импорты тестируемого модуля ──────────────────────────────────────────────
from spa_core.strategies.s6_max_diversified import (
    STRATEGY_ID,
    ALLOCATION,
    APY_TARGET_PCT,
    PROTOCOL_COUNT,
    RISK_SCORE,
    MAX_T2_ALLOCATION,
    compute_weighted_apy,
    simulate_day,
    check_concentration,
    get_diversity_score,
    vs_baseline_improvement,
    to_vportfolio_format,
    get_t2_exposure,
)


# ─── Вспомогательные данные ───────────────────────────────────────────────────

# Стандартная apy_map — все протоколы присутствуют с дефолтными значениями
APY_MAP_STD = {
    "pendle_pt":         10.0,
    "morpho_steakhouse":  6.5,
    "fluid_fusdc":        6.5,
    "compound_v3":        4.8,
    "aave_arbitrum":      4.6,
}

# APY_MAP без fluid_fusdc (для проверки redistribution)
APY_MAP_NO_FLUID = {
    "pendle_pt":         10.0,
    "morpho_steakhouse":  6.5,
    "compound_v3":        4.8,
    "aave_arbitrum":      4.6,
}

# APY_MAP — все нули
APY_MAP_ZERO = {
    "pendle_pt":         0.0,
    "morpho_steakhouse": 0.0,
    "fluid_fusdc":       0.0,
    "compound_v3":       0.0,
    "aave_arbitrum":     0.0,
}

# APY_MAP — только pendle и morpho
APY_MAP_PENDLE_MORPHO = {
    "pendle_pt":         10.0,
    "morpho_steakhouse":  6.5,
}

# APY_MAP — высокие значения
APY_MAP_HIGH = {
    "pendle_pt":         15.0,
    "morpho_steakhouse":  9.0,
    "fluid_fusdc":        9.0,
    "compound_v3":        7.0,
    "aave_arbitrum":      7.0,
}


# =============================================================================
# БЛОК 1: TestS6Import — Импорт и константы
# =============================================================================

class TestS6Import(unittest.TestCase):
    """Проверяем импорт без ошибок и базовые константы."""

    def test_import_no_error(self):
        """Модуль импортируется без исключений."""
        import spa_core.strategies.s6_max_diversified  # noqa: F401

    def test_strategy_id_is_s6(self):
        """STRATEGY_ID == 'S6'."""
        self.assertEqual(STRATEGY_ID, "S6")

    def test_protocol_count_is_5(self):
        """PROTOCOL_COUNT == 5."""
        self.assertEqual(PROTOCOL_COUNT, 5)

    def test_allocation_sums_to_one(self):
        """ALLOCATION суммируется в 1.0 (с допуском 1e-9)."""
        total = sum(ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_pendle_pt_weight_is_040(self):
        """Доля pendle_pt в ALLOCATION == 0.40."""
        self.assertAlmostEqual(ALLOCATION["pendle_pt"], 0.40, places=9)


# =============================================================================
# БЛОК 2: TestS6ComputeWeightedAPY — Взвешенный APY
# =============================================================================

class TestS6ComputeWeightedAPY(unittest.TestCase):
    """Проверяем функцию compute_weighted_apy."""

    def test_full_apy_map_approx_7_6(self):
        """Полный apy_map → weighted APY ≈ 7.6% (places=1)."""
        result = compute_weighted_apy(APY_MAP_STD)
        self.assertAlmostEqual(result, 7.6, places=1)

    def test_full_apy_map_exact(self):
        """Полный apy_map → weighted APY ≈ 7.635 (places=2)."""
        # 0.40*10.0 + 0.30*6.5 + 0.15*6.5 + 0.10*4.8 + 0.05*4.6
        # = 4.0 + 1.95 + 0.975 + 0.48 + 0.23 = 7.635
        result = compute_weighted_apy(APY_MAP_STD)
        self.assertAlmostEqual(result, 7.635, places=2)

    def test_missing_fluid_fusdc_redistributed_to_morpho(self):
        """Отсутствие fluid_fusdc → вес 0.15 перераспределяется на morpho (6.5)."""
        # Без fluid: 0.40*10.0 + 0.30*6.5 + 0.10*4.8 + 0.05*4.6 = 4.0+1.95+0.48+0.23=6.66
        # Redistribution: +0.15*6.5 = 0.975 → итого 7.635 (то же самое при morpho=6.5)
        result = compute_weighted_apy(APY_MAP_NO_FLUID)
        self.assertAlmostEqual(result, 7.635, places=2)

    def test_all_zeros_returns_zero(self):
        """Все APY равны нулю → weighted APY == 0.0."""
        result = compute_weighted_apy(APY_MAP_ZERO)
        self.assertAlmostEqual(result, 0.0, places=9)

    def test_empty_map_uses_fallback(self):
        """Пустой apy_map → все веса перераспределяются на morpho с FALLBACK."""
        # Все 5 протоколов отсутствуют → redistribution 1.0 * morpho_fallback = 6.5
        result = compute_weighted_apy({})
        self.assertAlmostEqual(result, 6.5, places=9)

    def test_only_pendle_and_morpho(self):
        """Только pendle_pt и morpho_steakhouse — остальные redistributed."""
        # pendle: 0.40*10.0 = 4.0
        # morpho: 0.30*6.5 = 1.95
        # fluid, compound, aave отсутствуют: (0.15+0.10+0.05)*6.5 = 0.30*6.5 = 1.95
        # Итого: 4.0 + 1.95 + 1.95 = 7.9
        result = compute_weighted_apy(APY_MAP_PENDLE_MORPHO)
        self.assertAlmostEqual(result, 7.9, places=9)

    def test_missing_pendle_redistributed(self):
        """Отсутствует pendle_pt → вес 0.40 redistributed на morpho."""
        apy_map = {
            "morpho_steakhouse": 6.5,
            "fluid_fusdc":       6.5,
            "compound_v3":       4.8,
            "aave_arbitrum":     4.6,
        }
        # morpho: 0.30*6.5 = 1.95
        # fluid:  0.15*6.5 = 0.975
        # compound: 0.10*4.8 = 0.48
        # aave:   0.05*4.6 = 0.23
        # pendle missing: 0.40*6.5 = 2.6
        # Итого: 1.95+0.975+0.48+0.23+2.6 = 6.235
        result = compute_weighted_apy(apy_map)
        self.assertAlmostEqual(result, 6.235, places=9)

    def test_missing_compound_redistributed(self):
        """Отсутствует compound_v3 → вес 0.10 redistributed на morpho."""
        apy_map = {
            "pendle_pt":         10.0,
            "morpho_steakhouse":  6.5,
            "fluid_fusdc":        6.5,
            "aave_arbitrum":      4.6,
        }
        # pendle: 0.40*10.0 = 4.0
        # morpho: 0.30*6.5 = 1.95
        # fluid:  0.15*6.5 = 0.975
        # aave:   0.05*4.6 = 0.23
        # compound missing: 0.10*6.5 = 0.65
        # Итого: 4.0+1.95+0.975+0.23+0.65 = 7.805
        result = compute_weighted_apy(apy_map)
        self.assertAlmostEqual(result, 7.805, places=9)

    def test_missing_aave_redistributed(self):
        """Отсутствует aave_arbitrum → вес 0.05 redistributed на morpho."""
        apy_map = {
            "pendle_pt":         10.0,
            "morpho_steakhouse":  6.5,
            "fluid_fusdc":        6.5,
            "compound_v3":        4.8,
        }
        # pendle: 0.40*10.0 = 4.0
        # morpho: 0.30*6.5 = 1.95
        # fluid:  0.15*6.5 = 0.975
        # compound: 0.10*4.8 = 0.48
        # aave missing: 0.05*6.5 = 0.325
        # Итого: 4.0+1.95+0.975+0.48+0.325 = 7.73
        result = compute_weighted_apy(apy_map)
        self.assertAlmostEqual(result, 7.73, places=9)

    def test_returns_float(self):
        """compute_weighted_apy возвращает float."""
        result = compute_weighted_apy(APY_MAP_STD)
        self.assertIsInstance(result, float)

    def test_positive_with_standard_apys(self):
        """Стандартный apy_map → положительный результат."""
        result = compute_weighted_apy(APY_MAP_STD)
        self.assertGreater(result, 0.0)

    def test_higher_apy_map_gives_higher_result(self):
        """Высокий apy_map → результат выше стандартного."""
        result_std = compute_weighted_apy(APY_MAP_STD)
        result_high = compute_weighted_apy(APY_MAP_HIGH)
        self.assertGreater(result_high, result_std)

    def test_lower_apy_map_gives_lower_result(self):
        """Низкий apy_map → результат ниже стандартного."""
        apy_map_low = {k: v * 0.5 for k, v in APY_MAP_STD.items()}
        result_std = compute_weighted_apy(APY_MAP_STD)
        result_low = compute_weighted_apy(apy_map_low)
        self.assertLess(result_low, result_std)

    def test_weighted_sum_manual_check(self):
        """Ручная проверка взвешенной суммы с произвольными значениями."""
        apy_map = {
            "pendle_pt":         8.0,
            "morpho_steakhouse": 5.0,
            "fluid_fusdc":       5.0,
            "compound_v3":       3.0,
            "aave_arbitrum":     3.0,
        }
        # 0.40*8.0 + 0.30*5.0 + 0.15*5.0 + 0.10*3.0 + 0.05*3.0
        # = 3.2 + 1.5 + 0.75 + 0.30 + 0.15 = 5.9
        expected = 0.40 * 8.0 + 0.30 * 5.0 + 0.15 * 5.0 + 0.10 * 3.0 + 0.05 * 3.0
        result = compute_weighted_apy(apy_map)
        self.assertAlmostEqual(result, expected, places=9)

    def test_morpho_fallback_when_missing_and_others_present(self):
        """Morpho отсутствует в apy_map, использует FALLBACK_APY["morpho_steakhouse"]."""
        # morpho отсутствует → его вес 0.30 уходит на morpho fallback = 6.5
        # Остальные присутствуют
        apy_map = {
            "pendle_pt":    10.0,
            "fluid_fusdc":   6.5,
            "compound_v3":   4.8,
            "aave_arbitrum": 4.6,
        }
        # pendle: 0.40*10.0=4.0; fluid: 0.15*6.5=0.975; compound: 0.10*4.8=0.48; aave: 0.05*4.6=0.23
        # morpho missing: 0.30*6.5=1.95
        # Итого: 4.0+1.95+0.975+0.48+0.23 = 7.635
        result = compute_weighted_apy(apy_map)
        self.assertAlmostEqual(result, 7.635, places=9)


# =============================================================================
# БЛОК 3: TestS6SimulateDay — Дневная симуляция
# =============================================================================

class TestS6SimulateDay(unittest.TestCase):
    """Проверяем функцию simulate_day."""

    def _call_std(self):
        """Вызов simulate_day со стандартным apy_map."""
        return simulate_day(APY_MAP_STD)

    def test_keys_present(self):
        """simulate_day возвращает все 7 обязательных ключей."""
        result = self._call_std()
        required_keys = {
            "strategy_id", "daily_pnl", "daily_return_pct",
            "annual_apy_pct", "allocation", "capital", "protocol_count",
        }
        for key in required_keys:
            self.assertIn(key, result, msg=f"Отсутствует ключ: {key}")

    def test_protocol_count_is_5(self):
        """protocol_count == 5."""
        result = self._call_std()
        self.assertEqual(result["protocol_count"], 5)

    def test_strategy_id_is_s6(self):
        """strategy_id == 'S6'."""
        result = self._call_std()
        self.assertEqual(result["strategy_id"], "S6")

    def test_daily_pnl_positive_with_standard_apys(self):
        """daily_pnl > 0 при стандартных APY."""
        result = self._call_std()
        self.assertGreater(result["daily_pnl"], 0.0)

    def test_daily_pnl_formula(self):
        """daily_pnl = capital * daily_return_pct / 100."""
        result = self._call_std()
        expected = result["capital"] * result["daily_return_pct"] / 100.0
        self.assertAlmostEqual(result["daily_pnl"], expected, places=6)

    def test_allocation_matches_constants(self):
        """allocation в ответе соответствует ALLOCATION."""
        result = self._call_std()
        for protocol, weight in ALLOCATION.items():
            self.assertIn(protocol, result["allocation"])
            self.assertAlmostEqual(result["allocation"][protocol], weight, places=9)

    def test_capital_default_100k(self):
        """По умолчанию capital == 100_000.0."""
        result = simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(result["capital"], 100_000.0, places=6)

    def test_custom_capital(self):
        """Кастомный capital передаётся корректно."""
        result = simulate_day(APY_MAP_STD, capital=50_000.0)
        self.assertAlmostEqual(result["capital"], 50_000.0, places=6)

    def test_annual_apy_pct_reasonable(self):
        """annual_apy_pct в разумном диапазоне (> 0% < 50%)."""
        result = self._call_std()
        self.assertGreater(result["annual_apy_pct"], 0.0)
        self.assertLess(result["annual_apy_pct"], 50.0)

    def test_daily_return_pct_is_annual_divided_by_365(self):
        """daily_return_pct == annual_apy_pct / 365."""
        result = self._call_std()
        expected = result["annual_apy_pct"] / 365.0
        self.assertAlmostEqual(result["daily_return_pct"], expected, places=9)


# =============================================================================
# БЛОК 4: TestS6Concentration — Концентрация и T2 лимит
# =============================================================================

class TestS6Concentration(unittest.TestCase):
    """Проверяем функции check_concentration и get_t2_exposure."""

    def test_check_concentration_compliant_default(self):
        """check_concentration() без аргументов → compliant: True."""
        result = check_concentration()
        self.assertTrue(result["compliant"])

    def test_no_violations_in_standard_allocation(self):
        """violations пустой при стандартной аллокации."""
        result = check_concentration()
        self.assertEqual(result["violations"], [])

    def test_max_concentration_is_040(self):
        """max_concentration == 0.40 (pendle_pt)."""
        result = check_concentration()
        self.assertAlmostEqual(result["max_concentration"], 0.40, places=9)

    def test_t2_exposure_is_015(self):
        """Суммарная T2 доля == 0.15 (fluid_fusdc)."""
        t2 = get_t2_exposure()
        self.assertAlmostEqual(t2, 0.15, places=9)

    def test_get_t2_exposure_returns_float(self):
        """get_t2_exposure() возвращает float."""
        self.assertIsInstance(get_t2_exposure(), float)

    def test_t2_within_limit(self):
        """T2 exposure (0.15) ≤ MAX_T2_ALLOCATION (0.20)."""
        t2 = get_t2_exposure()
        self.assertLessEqual(t2, MAX_T2_ALLOCATION)

    def test_returns_dict_with_compliant_key(self):
        """check_concentration возвращает dict с ключом 'compliant'."""
        result = check_concentration()
        self.assertIn("compliant", result)

    def test_returns_dict_with_violations_key(self):
        """check_concentration возвращает dict с ключом 'violations'."""
        result = check_concentration()
        self.assertIn("violations", result)

    def test_returns_dict_with_max_concentration_key(self):
        """check_concentration возвращает dict с ключом 'max_concentration'."""
        result = check_concentration()
        self.assertIn("max_concentration", result)

    def test_custom_allocation_violation_concentration(self):
        """Аллокация с протоколом > 40% → compliant: False, violations непустой."""
        bad_alloc = {
            "pendle_pt":         0.60,  # превышает 40%!
            "morpho_steakhouse": 0.25,
            "fluid_fusdc":       0.10,
            "compound_v3":       0.03,
            "aave_arbitrum":     0.02,
        }
        result = check_concentration(bad_alloc)
        self.assertFalse(result["compliant"])
        self.assertTrue(len(result["violations"]) > 0)

    def test_custom_allocation_t2_violation(self):
        """Аллокация с T2 > 20% → compliant: False."""
        bad_t2_alloc = {
            "pendle_pt":         0.35,
            "morpho_steakhouse": 0.30,
            "fluid_fusdc":       0.25,  # T2 превышает 20%!
            "compound_v3":       0.07,
            "aave_arbitrum":     0.03,
        }
        result = check_concentration(bad_t2_alloc)
        self.assertFalse(result["compliant"])

    def test_compliant_true_by_default(self):
        """Дефолтная аллокация S6 всегда проходит check_concentration."""
        result = check_concentration(ALLOCATION)
        self.assertTrue(result["compliant"])


# =============================================================================
# БЛОК 5: TestS6Diversity — Диверсификация и baseline comparison
# =============================================================================

class TestS6Diversity(unittest.TestCase):
    """Проверяем get_diversity_score и vs_baseline_improvement."""

    def test_diversity_score_is_060(self):
        """Diversity score S6 == 0.60 (1 - 0.40)."""
        score = get_diversity_score()
        self.assertAlmostEqual(score, 0.60, places=9)

    def test_diversity_score_greater_than_05(self):
        """Diversity score > 0.5 (стратегия диверсифицирована)."""
        score = get_diversity_score()
        self.assertGreater(score, 0.5)

    def test_diversity_score_formula(self):
        """Diversity score == 1 - max(ALLOCATION.values())."""
        expected = 1.0 - max(ALLOCATION.values())
        self.assertAlmostEqual(get_diversity_score(), expected, places=9)

    def test_vs_baseline_multiplier_approx_2_3(self):
        """multiplier ≈ 2.3 (7.5 / 3.2 = 2.34...)."""
        result = vs_baseline_improvement()
        self.assertAlmostEqual(result["multiplier"], 7.5 / 3.2, places=5)

    def test_vs_baseline_improvement_pct(self):
        """improvement_pct == 4.3 (7.5 - 3.2)."""
        result = vs_baseline_improvement()
        self.assertAlmostEqual(result["improvement_pct"], 4.3, places=9)

    def test_vs_baseline_strategy_id(self):
        """strategy == 'S6'."""
        result = vs_baseline_improvement()
        self.assertEqual(result["strategy"], "S6")

    def test_vs_baseline_target(self):
        """target == APY_TARGET_PCT == 7.5."""
        result = vs_baseline_improvement()
        self.assertAlmostEqual(result["target"], APY_TARGET_PCT, places=9)

    def test_s6_more_diverse_than_s2_style(self):
        """S6 diversity score (0.60) > S2-style (1 - 0.50 = 0.50)."""
        # S2 имеет 50% pendle → diversity = 0.50
        s2_max_alloc = 0.50
        s2_diversity = 1.0 - s2_max_alloc
        s6_diversity = get_diversity_score()
        self.assertGreater(s6_diversity, s2_diversity)


# =============================================================================
# БЛОК 6: TestS6VPortfolioFormat — VPortfolio совместимость
# =============================================================================

class TestS6VPortfolioFormat(unittest.TestCase):
    """Проверяем функцию to_vportfolio_format."""

    def _get_result(self):
        return to_vportfolio_format()

    def test_returns_dict(self):
        """to_vportfolio_format() возвращает dict."""
        self.assertIsInstance(self._get_result(), dict)

    def test_id_key_present(self):
        """Ключ 'id' присутствует."""
        self.assertIn("id", self._get_result())

    def test_name_key_present(self):
        """Ключ 'name' присутствует."""
        self.assertIn("name", self._get_result())

    def test_allocation_key_present(self):
        """Ключ 'allocation' присутствует."""
        self.assertIn("allocation", self._get_result())

    def test_risk_score_key_present(self):
        """Ключ 'risk_score' присутствует."""
        self.assertIn("risk_score", self._get_result())

    def test_apy_target_key_present(self):
        """Ключ 'apy_target' присутствует."""
        self.assertIn("apy_target", self._get_result())

    def test_protocol_count_key_present(self):
        """Ключ 'protocol_count' присутствует."""
        self.assertIn("protocol_count", self._get_result())

    def test_id_is_s6(self):
        """id == 'S6'."""
        self.assertEqual(self._get_result()["id"], "S6")

    def test_name_is_max_diversified(self):
        """name == 'Max Diversified'."""
        self.assertEqual(self._get_result()["name"], "Max Diversified")

    def test_protocol_count_is_5(self):
        """protocol_count == 5."""
        self.assertEqual(self._get_result()["protocol_count"], 5)

    def test_apy_target_is_75(self):
        """apy_target == 7.5."""
        self.assertAlmostEqual(self._get_result()["apy_target"], 7.5, places=9)

    def test_risk_score_less_than_05(self):
        """risk_score < 0.5 (умеренный риск благодаря диверсификации)."""
        self.assertLess(self._get_result()["risk_score"], 0.5)

    def test_allocation_matches_constants(self):
        """allocation в VPortfolio соответствует ALLOCATION."""
        result = self._get_result()
        for protocol, weight in ALLOCATION.items():
            self.assertIn(protocol, result["allocation"])
            self.assertAlmostEqual(result["allocation"][protocol], weight, places=9)

    def test_risk_score_equals_035(self):
        """risk_score == RISK_SCORE == 0.35."""
        self.assertAlmostEqual(self._get_result()["risk_score"], RISK_SCORE, places=9)

    def test_all_required_keys(self):
        """Все 6 обязательных ключей присутствуют."""
        result = self._get_result()
        for key in ("id", "name", "allocation", "risk_score", "apy_target", "protocol_count"):
            self.assertIn(key, result, msg=f"Отсутствует обязательный ключ: {key}")


# =============================================================================
# Точка входа
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
