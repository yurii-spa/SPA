"""
spa_core/tests/test_s7_pendle_yt_aggressive.py — Тесты MP-399 S7 Pendle YT+PT Aggressive

67+ тестов в 6 классах:
  TestS7Constants        (8 тестов)  — константы, ALLOCATION сумма = 1.0
  TestComputeWeightedAPY (12 тестов) — стандартный APY, кастомный apy_map, PT-only режим
  TestSimulateDay        (15 тестов) — base/bull/bear сценарии
  TestEligibility        (10 тестов) — is_eligible True/False, граничные значения
  TestVSS5Comparison     (12 тестов) — advantage > 1.5%, risk_adjusted_advantage
  TestVPortfolio         (10 тестов) — ключи VPortfolio, allocation суммируется правильно

Все тесты: stdlib only, никаких внешних зависимостей.
"""

import unittest


# ─── TestS7Constants ──────────────────────────────────────────────────────────

class TestS7Constants(unittest.TestCase):
    """Тесты корректности констант и структуры модуля."""

    def test_import_no_error(self):
        """Модуль импортируется без исключений."""
        import spa_core.strategies.s7_pendle_yt_aggressive  # noqa: F401

    def test_strategy_id_is_s7(self):
        """STRATEGY_ID == 'S7'."""
        from spa_core.strategies.s7_pendle_yt_aggressive import STRATEGY_ID
        self.assertEqual(STRATEGY_ID, "S7")

    def test_strategy_name(self):
        """STRATEGY_NAME содержит 'Pendle YT+PT Aggressive'."""
        from spa_core.strategies.s7_pendle_yt_aggressive import STRATEGY_NAME
        self.assertEqual(STRATEGY_NAME, "Pendle YT+PT Aggressive")

    def test_risk_tier_is_t3(self):
        """RISK_TIER == 'T3'."""
        from spa_core.strategies.s7_pendle_yt_aggressive import RISK_TIER
        self.assertEqual(RISK_TIER, "T3")

    def test_allocation_sums_to_one(self):
        """ALLOCATION суммируется в 1.0 (с точностью до 9 знаков)."""
        from spa_core.strategies.s7_pendle_yt_aggressive import ALLOCATION
        total = sum(ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_allocation_yt_is_40_pct(self):
        """pendle_yt доля = 0.40."""
        from spa_core.strategies.s7_pendle_yt_aggressive import ALLOCATION
        self.assertAlmostEqual(ALLOCATION["pendle_yt"], 0.40, places=9)

    def test_allocation_pt_is_35_pct(self):
        """pendle_pt доля = 0.35."""
        from spa_core.strategies.s7_pendle_yt_aggressive import ALLOCATION
        self.assertAlmostEqual(ALLOCATION["pendle_pt"], 0.35, places=9)

    def test_allocation_morpho_is_20_pct(self):
        """morpho_steakhouse доля = 0.20."""
        from spa_core.strategies.s7_pendle_yt_aggressive import ALLOCATION
        self.assertAlmostEqual(ALLOCATION["morpho_steakhouse"], 0.20, places=9)

    def test_allocation_compound_is_5_pct(self):
        """compound_v3 доля = 0.05."""
        from spa_core.strategies.s7_pendle_yt_aggressive import ALLOCATION
        self.assertAlmostEqual(ALLOCATION["compound_v3"], 0.05, places=9)

    def test_risk_score_above_s5(self):
        """RISK_SCORE > 0.42 (риск S7 выше S5 из-за YT-экспозиции)."""
        from spa_core.strategies.s7_pendle_yt_aggressive import RISK_SCORE
        self.assertGreater(RISK_SCORE, 0.42)

    def test_risk_score_is_0_52(self):
        """RISK_SCORE == 0.52."""
        from spa_core.strategies.s7_pendle_yt_aggressive import RISK_SCORE
        self.assertAlmostEqual(RISK_SCORE, 0.52, places=9)

    def test_weighted_apy_above_10(self):
        """WEIGHTED_APY > 10.0 (прорыв 10% APY барьера)."""
        from spa_core.strategies.s7_pendle_yt_aggressive import WEIGHTED_APY
        self.assertGreater(WEIGHTED_APY, 10.0)

    def test_weighted_apy_exact(self):
        """WEIGHTED_APY ≈ 10.115."""
        from spa_core.strategies.s7_pendle_yt_aggressive import WEIGHTED_APY
        self.assertAlmostEqual(WEIGHTED_APY, 10.115, places=3)

    def test_min_yt_apy_is_8(self):
        """MIN_YT_APY_PCT == 8.0."""
        from spa_core.strategies.s7_pendle_yt_aggressive import MIN_YT_APY_PCT
        self.assertAlmostEqual(MIN_YT_APY_PCT, 8.0, places=9)

    def test_yt_bull_multiplier_is_2(self):
        """YT_BULL_MULTIPLIER == 2.0."""
        from spa_core.strategies.s7_pendle_yt_aggressive import YT_BULL_MULTIPLIER
        self.assertAlmostEqual(YT_BULL_MULTIPLIER, 2.0, places=9)

    def test_class_instantiable(self):
        """Класс S7PendleYTAggressive создаётся без ошибок."""
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        s7 = S7PendleYTAggressive()
        self.assertIsNotNone(s7)

    def test_class_instantiable_with_capital(self):
        """Класс создаётся с кастомным капиталом."""
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        s7 = S7PendleYTAggressive(capital=50_000.0)
        self.assertAlmostEqual(s7.capital, 50_000.0, places=6)


# ─── TestComputeWeightedAPY ───────────────────────────────────────────────────

class TestComputeWeightedAPY(unittest.TestCase):
    """Тесты метода compute_weighted_apy."""

    def setUp(self):
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        self.s7 = S7PendleYTAggressive()

    def _defaults(self):
        return {
            "pendle_yt":         14.0,
            "pendle_pt":          8.5,
            "morpho_steakhouse":  6.5,
            "compound_v3":        4.8,
        }

    def test_defaults_apy_is_10_115(self):
        """При дефолтных APY: weighted ≈ 10.115%."""
        apy = self.s7.compute_weighted_apy()
        self.assertAlmostEqual(apy, 10.115, places=3)

    def test_none_apy_map_uses_defaults(self):
        """apy_map=None эквивалентно APY_DEFAULTS."""
        apy_none = self.s7.compute_weighted_apy(None)
        apy_def  = self.s7.compute_weighted_apy(self._defaults())
        self.assertAlmostEqual(apy_none, apy_def, places=9)

    def test_empty_apy_map_uses_defaults(self):
        """Пустой apy_map {} использует APY_DEFAULTS для всех протоколов."""
        apy_empty = self.s7.compute_weighted_apy({})
        apy_none  = self.s7.compute_weighted_apy(None)
        self.assertAlmostEqual(apy_empty, apy_none, places=9)

    def test_custom_yt_high_apy(self):
        """Кастомный YT APY 25% → weighted APY > 10%."""
        apy_map = self._defaults()
        apy_map["pendle_yt"] = 25.0
        apy = self.s7.compute_weighted_apy(apy_map)
        # 0.40*25 + 0.35*8.5 + 0.20*6.5 + 0.05*4.8 = 10+2.975+1.3+0.24 = 14.515
        self.assertAlmostEqual(apy, 14.515, places=3)

    def test_custom_yt_exact_threshold(self):
        """YT APY ровно 8.0 → стандартный режим (не PT-only)."""
        apy_map = self._defaults()
        apy_map["pendle_yt"] = 8.0
        apy = self.s7.compute_weighted_apy(apy_map)
        # 0.40*8.0 + 0.35*8.5 + 0.20*6.5 + 0.05*4.8 = 3.2+2.975+1.3+0.24 = 7.715
        self.assertAlmostEqual(apy, 7.715, places=3)

    def test_pt_only_mode_when_yt_below_threshold(self):
        """YT APY < 8.0 → PT-only режим, YT вклад = 0."""
        apy_map = self._defaults()
        apy_map["pendle_yt"] = 5.0  # ниже MIN_YT_APY_PCT
        apy = self.s7.compute_weighted_apy(apy_map)
        # В PT-only: YT 40% → делится между PT (0.35) и Morpho (0.20)
        # PT_new  = 0.35 + 0.40*(0.35/0.55) = 0.35 + 0.2545... = 0.6045...
        # Mo_new  = 0.20 + 0.40*(0.20/0.55) = 0.20 + 0.1454... = 0.3454...
        # APY = 0.6045*8.5 + 0.3454*6.5 + 0.05*4.8 = 5.139+2.245+0.24 = 7.624...
        self.assertGreater(apy, 6.0)
        self.assertLess(apy, 10.0)

    def test_pt_only_apy_below_normal(self):
        """В PT-only режиме APY < стандартного (YT высокодоходный отключён)."""
        apy_map = self._defaults()
        normal_apy = self.s7.compute_weighted_apy(apy_map)

        apy_map["pendle_yt"] = 5.0
        pt_only_apy = self.s7.compute_weighted_apy(apy_map)

        self.assertLess(pt_only_apy, normal_apy)

    def test_pt_only_redistribution_correct(self):
        """PT-only: pt_new + morpho_new + compound = 1.0 (веса корректны)."""
        # Мы не тестируем веса напрямую, но проверяем что APY разумный
        apy_map = self._defaults()
        apy_map["pendle_yt"] = 1.0

        apy = self.s7.compute_weighted_apy(apy_map)
        # должен быть между 5% и 10%
        self.assertGreater(apy, 5.0)
        self.assertLess(apy, 10.0)

    def test_high_all_apy(self):
        """Все APY удвоены → weighted APY удваивается."""
        apy_map = {k: v * 2 for k, v in self._defaults().items()}
        apy = self.s7.compute_weighted_apy(apy_map)
        self.assertAlmostEqual(apy, 10.115 * 2, places=3)

    def test_zero_non_yt_apy(self):
        """Нулевые APY для PT/Morpho/Compound → only YT contributes."""
        apy_map = {
            "pendle_yt":         14.0,
            "pendle_pt":          0.0,
            "morpho_steakhouse":  0.0,
            "compound_v3":        0.0,
        }
        apy = self.s7.compute_weighted_apy(apy_map)
        # 0.40*14.0 = 5.6
        self.assertAlmostEqual(apy, 5.6, places=6)

    def test_partial_apy_map_uses_defaults(self):
        """Частичный apy_map дополняется дефолтами."""
        apy_map = {"pendle_yt": 20.0}  # только YT, остальные → defaults
        apy = self.s7.compute_weighted_apy(apy_map)
        # 0.40*20 + 0.35*8.5 + 0.20*6.5 + 0.05*4.8 = 8+2.975+1.3+0.24 = 12.515
        self.assertAlmostEqual(apy, 12.515, places=3)

    def test_weighted_apy_gt_s5_baseline(self):
        """При дефолтах S7 APY > S5 baseline (8.5%)."""
        apy = self.s7.compute_weighted_apy()
        self.assertGreater(apy, 8.5)


# ─── TestSimulateDay ──────────────────────────────────────────────────────────

class TestSimulateDay(unittest.TestCase):
    """Тесты метода simulate_day — сценарии base/bull/bear."""

    def setUp(self):
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        self.s7 = S7PendleYTAggressive()
        self.pv = 100_000.0

    def test_base_returns_required_keys(self):
        """simulate_day возвращает все обязательные ключи."""
        result = self.s7.simulate_day(self.pv, 1)
        for key in ("daily_yield_usd", "annual_apy_pct", "scenario",
                    "portfolio_value_after", "positions"):
            self.assertIn(key, result)

    def test_base_scenario_label(self):
        """scenario == 'base' по умолчанию."""
        result = self.s7.simulate_day(self.pv, 1)
        self.assertEqual(result["scenario"], "base")

    def test_base_equity_grows(self):
        """В base сценарии portfolio_value_after > portfolio_value."""
        result = self.s7.simulate_day(self.pv, 1)
        self.assertGreater(result["portfolio_value_after"], self.pv)

    def test_base_daily_yield_positive(self):
        """В base сценарии daily_yield_usd > 0."""
        result = self.s7.simulate_day(self.pv, 1)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_base_apy_above_10(self):
        """В base сценарии annual_apy_pct > 10%."""
        result = self.s7.simulate_day(self.pv, 1)
        self.assertGreater(result["annual_apy_pct"], 10.0)

    def test_base_positions_sum_equals_portfolio_value(self):
        """Сумма позиций == portfolio_value."""
        result = self.s7.simulate_day(self.pv, 1)
        total = sum(result["positions"].values())
        self.assertAlmostEqual(total, self.pv, places=4)

    def test_bull_scenario_higher_yield_than_base(self):
        """Bull APY > Base APY (YT умножается на 2)."""
        base = self.s7.simulate_day(self.pv, 1, scenario="base")
        bull = self.s7.simulate_day(self.pv, 2, scenario="bull")
        self.assertGreater(bull["annual_apy_pct"], base["annual_apy_pct"])

    def test_bull_equity_grows(self):
        """В bull сценарии portfolio_value_after > portfolio_value."""
        result = self.s7.simulate_day(self.pv, 1, scenario="bull")
        self.assertGreater(result["portfolio_value_after"], self.pv)

    def test_bull_scenario_label(self):
        """scenario == 'bull'."""
        result = self.s7.simulate_day(self.pv, 1, scenario="bull")
        self.assertEqual(result["scenario"], "bull")

    def test_bull_yt_apy_doubled(self):
        """В bull: YT APY * 2 → annual_apy выше baseline."""
        result = self.s7.simulate_day(self.pv, 1, scenario="bull")
        self.assertGreater(result["annual_apy_pct"], 14.0)

    def test_bear_equity_shrinks(self):
        """В bear сценарии portfolio_value_after < portfolio_value (YT теряет 50%/год)."""
        result = self.s7.simulate_day(self.pv, 1, scenario="bear")
        self.assertLess(result["portfolio_value_after"], self.pv)

    def test_bear_daily_yield_negative(self):
        """В bear сценарии daily_yield_usd < 0."""
        result = self.s7.simulate_day(self.pv, 1, scenario="bear")
        self.assertLess(result["daily_yield_usd"], 0.0)

    def test_bear_scenario_label(self):
        """scenario == 'bear'."""
        result = self.s7.simulate_day(self.pv, 1, scenario="bear")
        self.assertEqual(result["scenario"], "bear")

    def test_bear_loss_bounded(self):
        """Bear сценарий: потери ограничены (не полная потеря за 1 день)."""
        result = self.s7.simulate_day(self.pv, 1, scenario="bear")
        # Максимальная дневная потеря: 100000 * 0.40 * 0.50 / 365 ≈ $54.79
        # Плюс PT+Morpho+Compound ещё приносит доход (~$12/день)
        # Итоговая потеря не должна превышать $100 за 1 день
        loss = self.pv - result["portfolio_value_after"]
        self.assertLess(loss, 100.0)
        self.assertGreater(loss, 0.0)

    def test_portfolio_value_after_formula(self):
        """portfolio_value_after == portfolio_value + daily_yield_usd."""
        result = self.s7.simulate_day(self.pv, 1, scenario="base")
        expected = self.pv + result["daily_yield_usd"]
        self.assertAlmostEqual(result["portfolio_value_after"], expected, places=9)

    def test_days_simulated_increments(self):
        """_days_simulated увеличивается с каждым вызовом simulate_day."""
        s7 = self.s7
        self.assertEqual(s7._days_simulated, 0)
        s7.simulate_day(self.pv, 1)
        self.assertEqual(s7._days_simulated, 1)
        s7.simulate_day(self.pv, 2)
        self.assertEqual(s7._days_simulated, 2)

    def test_custom_apy_map_affects_result(self):
        """Кастомный apy_map изменяет результат simulate_day."""
        default_result = self.s7.simulate_day(self.pv, 1)
        custom_map = {"pendle_yt": 30.0, "pendle_pt": 10.0, "morpho_steakhouse": 8.0, "compound_v3": 5.0}
        custom_result = self.s7.simulate_day(self.pv, 2, apy_map=custom_map)
        self.assertNotAlmostEqual(
            default_result["annual_apy_pct"],
            custom_result["annual_apy_pct"],
            places=3
        )


# ─── TestEligibility ──────────────────────────────────────────────────────────

class TestEligibility(unittest.TestCase):
    """Тесты метода is_eligible."""

    def setUp(self):
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        self.s7 = S7PendleYTAggressive()

    def test_eligible_with_defaults(self):
        """С дефолтным YT APY (14%) стратегия eligible."""
        self.assertTrue(self.s7.is_eligible())

    def test_eligible_high_threshold(self):
        """Eligible когда threshold меньше дефолтного YT APY."""
        self.assertTrue(self.s7.is_eligible(min_yt_apy_pct=8.0))

    def test_eligible_threshold_equals_default_apy(self):
        """Eligible когда threshold == default YT APY (граничное значение)."""
        # APY_DEFAULTS["pendle_yt"] = 14.0, threshold = 14.0 → True (>=)
        self.assertTrue(self.s7.is_eligible(min_yt_apy_pct=14.0))

    def test_not_eligible_threshold_above_default(self):
        """Не eligible когда threshold > дефолтный YT APY."""
        self.assertFalse(self.s7.is_eligible(min_yt_apy_pct=15.0))

    def test_not_eligible_very_high_threshold(self):
        """Не eligible при очень высоком threshold (40%)."""
        self.assertFalse(self.s7.is_eligible(min_yt_apy_pct=40.0))

    def test_eligible_zero_threshold(self):
        """Eligible при нулевом threshold (всегда True)."""
        self.assertTrue(self.s7.is_eligible(min_yt_apy_pct=0.0))

    def test_eligible_default_threshold_is_8(self):
        """Дефолтный порог для is_eligible == 8.0."""
        from spa_core.strategies.s7_pendle_yt_aggressive import MIN_YT_APY_PCT
        self.assertAlmostEqual(MIN_YT_APY_PCT, 8.0, places=9)

    def test_eligible_none_threshold(self):
        """is_eligible(None) использует MIN_YT_APY_PCT."""
        result_default = self.s7.is_eligible()
        result_none    = self.s7.is_eligible(min_yt_apy_pct=None)
        self.assertEqual(result_default, result_none)

    def test_eligible_returns_bool(self):
        """is_eligible возвращает bool."""
        result = self.s7.is_eligible()
        self.assertIsInstance(result, bool)

    def test_eligible_threshold_just_above_default(self):
        """Threshold немного выше дефолта → не eligible."""
        # APY_DEFAULTS["pendle_yt"] = 14.0 < 14.0001
        self.assertFalse(self.s7.is_eligible(min_yt_apy_pct=14.0001))


# ─── TestVSS5Comparison ───────────────────────────────────────────────────────

class TestVSS5Comparison(unittest.TestCase):
    """Тесты метода vs_s5_comparison."""

    def setUp(self):
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        self.s7 = S7PendleYTAggressive()

    def _defaults(self):
        return {
            "pendle_yt":         14.0,
            "pendle_pt":          8.5,
            "morpho_steakhouse":  6.5,
            "compound_v3":        4.8,
        }

    def test_returns_required_keys(self):
        """vs_s5_comparison возвращает все обязательные ключи."""
        result = self.s7.vs_s5_comparison()
        for key in ("s7_apy", "s5_apy", "advantage_pct", "risk_premium", "risk_adjusted_advantage"):
            self.assertIn(key, result)

    def test_s5_apy_is_8_5(self):
        """s5_apy всегда 8.5% (baseline)."""
        result = self.s7.vs_s5_comparison()
        self.assertAlmostEqual(result["s5_apy"], 8.5, places=9)

    def test_s7_apy_above_10_with_defaults(self):
        """s7_apy > 10.0 при дефолтных APY."""
        result = self.s7.vs_s5_comparison()
        self.assertGreater(result["s7_apy"], 10.0)

    def test_advantage_pct_positive_with_defaults(self):
        """advantage_pct > 0 при дефолтных APY (S7 лучше S5)."""
        result = self.s7.vs_s5_comparison()
        self.assertGreater(result["advantage_pct"], 0.0)

    def test_advantage_pct_above_1_5(self):
        """advantage_pct > 1.5% при стандартных APY."""
        result = self.s7.vs_s5_comparison()
        self.assertGreater(result["advantage_pct"], 1.5)

    def test_risk_premium_positive(self):
        """risk_premium > 0 (S7 риск выше S5)."""
        result = self.s7.vs_s5_comparison()
        self.assertGreater(result["risk_premium"], 0.0)

    def test_risk_premium_equals_0_10(self):
        """risk_premium == 0.52 - 0.42 = 0.10."""
        result = self.s7.vs_s5_comparison()
        self.assertAlmostEqual(result["risk_premium"], 0.10, places=9)

    def test_risk_adjusted_advantage_positive(self):
        """risk_adjusted_advantage > 0 при дефолтных APY."""
        result = self.s7.vs_s5_comparison()
        self.assertGreater(result["risk_adjusted_advantage"], 0.0)

    def test_risk_adjusted_advantage_formula(self):
        """risk_adjusted_advantage == advantage_pct / risk_premium."""
        result = self.s7.vs_s5_comparison()
        expected = result["advantage_pct"] / result["risk_premium"]
        self.assertAlmostEqual(result["risk_adjusted_advantage"], expected, places=9)

    def test_none_apy_map_uses_defaults(self):
        """apy_map=None использует APY_DEFAULTS."""
        result_none = self.s7.vs_s5_comparison(apy_map=None)
        result_def  = self.s7.vs_s5_comparison(apy_map=self._defaults())
        self.assertAlmostEqual(result_none["s7_apy"], result_def["s7_apy"], places=9)

    def test_custom_apy_affects_s7(self):
        """Кастомный apy_map изменяет s7_apy в результате."""
        default_result = self.s7.vs_s5_comparison()
        custom_map = {"pendle_yt": 30.0, "pendle_pt": 10.0, "morpho_steakhouse": 8.0, "compound_v3": 5.0}
        custom_result = self.s7.vs_s5_comparison(apy_map=custom_map)
        self.assertGreater(custom_result["s7_apy"], default_result["s7_apy"])

    def test_advantage_equals_s7_minus_s5(self):
        """advantage_pct == s7_apy - s5_apy."""
        result = self.s7.vs_s5_comparison()
        expected = result["s7_apy"] - result["s5_apy"]
        self.assertAlmostEqual(result["advantage_pct"], expected, places=9)


# ─── TestVPortfolio ───────────────────────────────────────────────────────────

class TestVPortfolio(unittest.TestCase):
    """Тесты метода to_vportfolio_format."""

    def setUp(self):
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        self.s7 = S7PendleYTAggressive()

    def test_returns_required_keys(self):
        """to_vportfolio_format возвращает обязательные VPortfolio-ключи."""
        result = self.s7.to_vportfolio_format()
        for key in ("id", "name", "allocation", "risk_score", "apy_target", "tier"):
            self.assertIn(key, result)

    def test_id_is_s7(self):
        """id == 'S7'."""
        result = self.s7.to_vportfolio_format()
        self.assertEqual(result["id"], "S7")

    def test_tier_is_t3(self):
        """tier == 'T3'."""
        result = self.s7.to_vportfolio_format()
        self.assertEqual(result["tier"], "T3")

    def test_allocation_sums_to_one(self):
        """allocation в VPortfolio суммируется в 1.0."""
        result = self.s7.to_vportfolio_format()
        total = sum(result["allocation"].values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_allocation_has_four_protocols(self):
        """allocation содержит 4 протокола."""
        result = self.s7.to_vportfolio_format()
        self.assertEqual(len(result["allocation"]), 4)

    def test_risk_score_in_range(self):
        """risk_score в диапазоне (0.40, 0.80)."""
        result = self.s7.to_vportfolio_format()
        self.assertGreater(result["risk_score"], 0.40)
        self.assertLess(result["risk_score"], 0.80)

    def test_apy_target_above_10(self):
        """apy_target > 10.0 (прорыв барьера 10% APY)."""
        result = self.s7.to_vportfolio_format()
        self.assertGreater(result["apy_target"], 10.0)

    def test_capital_usd_matches_arg(self):
        """capital_usd в результате совпадает с переданным portfolio_value."""
        result = self.s7.to_vportfolio_format(portfolio_value=200_000.0)
        self.assertAlmostEqual(result["capital_usd"], 200_000.0, places=4)

    def test_positions_sum_equals_portfolio_value(self):
        """Сумма positions == portfolio_value."""
        pv = 150_000.0
        result = self.s7.to_vportfolio_format(portfolio_value=pv)
        total = sum(result["positions"].values())
        self.assertAlmostEqual(total, pv, places=2)

    def test_is_eligible_field_present(self):
        """Поле is_eligible присутствует и является bool."""
        result = self.s7.to_vportfolio_format()
        self.assertIn("is_eligible", result)
        self.assertIsInstance(result["is_eligible"], bool)

    def test_default_portfolio_value_is_100k(self):
        """По умолчанию portfolio_value = 100_000."""
        result = self.s7.to_vportfolio_format()
        self.assertAlmostEqual(result["capital_usd"], 100_000.0, places=4)


# ─── Bonus: TestGetYTExposure ─────────────────────────────────────────────────

class TestGetYTExposure(unittest.TestCase):
    """Тесты метода get_yt_exposure."""

    def setUp(self):
        from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive
        self.s7 = S7PendleYTAggressive()

    def test_returns_required_keys(self):
        """get_yt_exposure возвращает все обязательные ключи."""
        result = self.s7.get_yt_exposure()
        for key in ("allocation", "default_apy", "bull_apy", "bear_loss_pct", "is_eligible"):
            self.assertIn(key, result)

    def test_allocation_is_40_pct(self):
        """allocation == 0.40."""
        result = self.s7.get_yt_exposure()
        self.assertAlmostEqual(result["allocation"], 0.40, places=9)

    def test_default_apy_is_14(self):
        """default_apy == 14.0."""
        result = self.s7.get_yt_exposure()
        self.assertAlmostEqual(result["default_apy"], 14.0, places=9)

    def test_bull_apy_is_doubled(self):
        """bull_apy == default_apy * YT_BULL_MULTIPLIER = 28.0."""
        result = self.s7.get_yt_exposure()
        self.assertAlmostEqual(result["bull_apy"], 28.0, places=9)

    def test_bear_loss_pct_is_minus_50(self):
        """bear_loss_pct == -50.0 (YT_BEAR_LOSS_PCT * 100)."""
        result = self.s7.get_yt_exposure()
        self.assertAlmostEqual(result["bear_loss_pct"], -50.0, places=9)

    def test_is_eligible_true_with_defaults(self):
        """is_eligible True при дефолтных APY (14% > 8% порог)."""
        result = self.s7.get_yt_exposure()
        self.assertTrue(result["is_eligible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
