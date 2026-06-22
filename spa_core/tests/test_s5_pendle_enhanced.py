"""
spa_core/tests/test_s5_pendle_enhanced.py — Тесты для MP-396 S5 Pendle PT Enhanced

70+ тестов в 7 классах:
  TestS5Import            — импорт и константы (5 тестов)
  TestS5ComputeWeightedAPY — compute_weighted_apy (15 тестов)
  TestS5SimulateDay        — simulate_day (12 тестов)
  TestS5Eligibility        — is_eligible (10 тестов)
  TestS5VsS2               — vs_s2_comparison (12 тестов)
  TestS5VPortfolioFormat   — to_vportfolio_format (8 тестов)
  TestS5Advantage          — get_pendle_advantage (8 тестов)
"""

import unittest


# ─── TestS5Import ─────────────────────────────────────────────────────────────

class TestS5Import(unittest.TestCase):
    """Тесты импорта модуля и корректности констант."""

    def test_import_no_error(self):
        """Модуль импортируется без исключений."""
        import spa_core.strategies.s5_pendle_enhanced  # noqa: F401

    def test_strategy_id_is_s5(self):
        """STRATEGY_ID == 'S5'."""
        from spa_core.strategies.s5_pendle_enhanced import STRATEGY_ID
        self.assertEqual(STRATEGY_ID, "S5")

    def test_strategy_name(self):
        """STRATEGY_NAME содержит 'Pendle PT Enhanced'."""
        from spa_core.strategies.s5_pendle_enhanced import STRATEGY_NAME
        self.assertEqual(STRATEGY_NAME, "Pendle PT Enhanced")

    def test_allocation_sums_to_one(self):
        """ALLOCATION суммируется в 1.0."""
        from spa_core.strategies.s5_pendle_enhanced import ALLOCATION
        total = sum(ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_pendle_pt_weight_is_65_pct(self):
        """pendle_pt доля = 0.65."""
        from spa_core.strategies.s5_pendle_enhanced import ALLOCATION
        self.assertAlmostEqual(ALLOCATION["pendle_pt"], 0.65, places=9)

    def test_morpho_weight_is_25_pct(self):
        """morpho_steakhouse доля = 0.25."""
        from spa_core.strategies.s5_pendle_enhanced import ALLOCATION
        self.assertAlmostEqual(ALLOCATION["morpho_steakhouse"], 0.25, places=9)

    def test_compound_weight_is_10_pct(self):
        """compound_v3 доля = 0.10."""
        from spa_core.strategies.s5_pendle_enhanced import ALLOCATION
        self.assertAlmostEqual(ALLOCATION["compound_v3"], 0.10, places=9)

    def test_min_pendle_apy_is_6(self):
        """MIN_PENDLE_APY_PCT == 6.0."""
        from spa_core.strategies.s5_pendle_enhanced import MIN_PENDLE_APY_PCT
        self.assertAlmostEqual(MIN_PENDLE_APY_PCT, 6.0, places=9)

    def test_apy_target_is_8_5(self):
        """APY_TARGET_PCT == 8.5."""
        from spa_core.strategies.s5_pendle_enhanced import APY_TARGET_PCT
        self.assertAlmostEqual(APY_TARGET_PCT, 8.5, places=9)

    def test_risk_score_range(self):
        """RISK_SCORE в диапазоне (0.25, 0.60)."""
        from spa_core.strategies.s5_pendle_enhanced import RISK_SCORE
        self.assertGreater(RISK_SCORE, 0.25)
        self.assertLess(RISK_SCORE, 0.60)

    def test_class_instantiable(self):
        """Класс S5PendleEnhanced создаётся без ошибок."""
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced
        s5 = S5PendleEnhanced()
        self.assertIsNotNone(s5)

    def test_tier_limit_value(self):
        """TIER_LIMIT == 'T1_ONLY'."""
        from spa_core.strategies.s5_pendle_enhanced import TIER_LIMIT
        self.assertEqual(TIER_LIMIT, "T1_ONLY")

    def test_max_drawdown_pct(self):
        """MAX_DRAWDOWN_PCT == 5.0."""
        from spa_core.strategies.s5_pendle_enhanced import MAX_DRAWDOWN_PCT
        self.assertAlmostEqual(MAX_DRAWDOWN_PCT, 5.0, places=9)


# ─── TestS5ComputeWeightedAPY ─────────────────────────────────────────────────

class TestS5ComputeWeightedAPY(unittest.TestCase):
    """Тесты метода compute_weighted_apy."""

    def setUp(self):
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced
        self.s5 = S5PendleEnhanced()

    def _std_map(self):
        return {"pendle_pt": 10.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}

    def test_standard_apy_map(self):
        """Стандартный apy_map → ≈ 8.605%."""
        apy = self.s5.compute_weighted_apy(self._std_map())
        expected = 0.65 * 10.0 + 0.25 * 6.5 + 0.10 * 4.8
        self.assertAlmostEqual(apy, expected, places=6)

    def test_standard_apy_approx_8_6(self):
        """Стандартный apy_map > 8.5%."""
        apy = self.s5.compute_weighted_apy(self._std_map())
        self.assertGreater(apy, 8.5)

    def test_higher_pendle_increases_apy(self):
        """При pendle_pt=12.0 APY выше стандартного."""
        high_map = {"pendle_pt": 12.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        apy_high = self.s5.compute_weighted_apy(high_map)
        apy_std  = self.s5.compute_weighted_apy(self._std_map())
        self.assertGreater(apy_high, apy_std)

    def test_pendle_below_threshold_zero_contribution(self):
        """При pendle_pt < 6.0 вклад Pendle = 0."""
        low_map = {"pendle_pt": 5.99, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        apy = self.s5.compute_weighted_apy(low_map)
        expected = 0.25 * 6.5 + 0.10 * 4.8  # только Morpho + Compound
        self.assertAlmostEqual(apy, expected, places=6)

    def test_pendle_at_exact_threshold_eligible(self):
        """При pendle_pt=6.0 (точно на пороге) — включается в расчёт."""
        edge_map = {"pendle_pt": 6.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        apy = self.s5.compute_weighted_apy(edge_map)
        expected = 0.65 * 6.0 + 0.25 * 6.5 + 0.10 * 4.8
        self.assertAlmostEqual(apy, expected, places=6)

    def test_empty_apy_map_returns_zero(self):
        """Пустой apy_map → 0.0."""
        apy = self.s5.compute_weighted_apy({})
        self.assertAlmostEqual(apy, 0.0, places=9)

    def test_partial_apy_map_only_morpho(self):
        """Только morpho_steakhouse в apy_map → вклад только Morpho."""
        partial = {"morpho_steakhouse": 6.5}
        apy = self.s5.compute_weighted_apy(partial)
        expected = 0.25 * 6.5
        self.assertAlmostEqual(apy, expected, places=6)

    def test_partial_apy_map_pendle_compound(self):
        """Только pendle_pt + compound_v3 → вклад этих двух."""
        partial = {"pendle_pt": 10.0, "compound_v3": 4.8}
        apy = self.s5.compute_weighted_apy(partial)
        expected = 0.65 * 10.0 + 0.10 * 4.8
        self.assertAlmostEqual(apy, expected, places=6)

    def test_very_high_pendle_apy(self):
        """Очень высокий Pendle APY корректно умножается на вес."""
        high = {"pendle_pt": 20.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        apy = self.s5.compute_weighted_apy(high)
        expected = 0.65 * 20.0 + 0.25 * 6.5 + 0.10 * 4.8
        self.assertAlmostEqual(apy, expected, places=6)

    def test_zero_morpho_apy(self):
        """Нулевой morpho APY — его вклад = 0."""
        zero_morpho = {"pendle_pt": 10.0, "morpho_steakhouse": 0.0, "compound_v3": 4.8}
        apy = self.s5.compute_weighted_apy(zero_morpho)
        expected = 0.65 * 10.0 + 0.25 * 0.0 + 0.10 * 4.8
        self.assertAlmostEqual(apy, expected, places=6)

    def test_s5_apy_greater_than_s2_with_std_map(self):
        """S5 APY > S2 APY при стандартных значениях."""
        s5_apy = self.s5.compute_weighted_apy(self._std_map())
        # S2 ≈ 7.0%
        self.assertGreater(s5_apy, 7.0)

    def test_returns_float(self):
        """compute_weighted_apy возвращает float."""
        apy = self.s5.compute_weighted_apy(self._std_map())
        self.assertIsInstance(apy, float)

    def test_pendle_just_above_threshold(self):
        """pendle_pt=6.01 → включается в расчёт."""
        edge_map = {"pendle_pt": 6.01, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        apy = self.s5.compute_weighted_apy(edge_map)
        expected = 0.65 * 6.01 + 0.25 * 6.5 + 0.10 * 4.8
        self.assertAlmostEqual(apy, expected, places=6)

    def test_all_zero_apy(self):
        """Все APY = 0 → 0.0."""
        zero_map = {"pendle_pt": 0.0, "morpho_steakhouse": 0.0, "compound_v3": 0.0}
        apy = self.s5.compute_weighted_apy(zero_map)
        self.assertAlmostEqual(apy, 0.0, places=9)

    def test_only_compound_in_map(self):
        """Только compound_v3 в apy_map."""
        partial = {"compound_v3": 4.8}
        apy = self.s5.compute_weighted_apy(partial)
        expected = 0.10 * 4.8
        self.assertAlmostEqual(apy, expected, places=6)


# ─── TestS5SimulateDay ────────────────────────────────────────────────────────

class TestS5SimulateDay(unittest.TestCase):
    """Тесты метода simulate_day."""

    def setUp(self):
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced
        self.s5 = S5PendleEnhanced()

    def _std_map(self):
        return {"pendle_pt": 10.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}

    def test_returns_dict(self):
        """simulate_day возвращает dict."""
        result = self.s5.simulate_day(self._std_map())
        self.assertIsInstance(result, dict)

    def test_has_strategy_id_key(self):
        """Результат содержит ключ 'strategy_id'."""
        result = self.s5.simulate_day(self._std_map())
        self.assertIn("strategy_id", result)

    def test_strategy_id_is_s5(self):
        """strategy_id == 'S5'."""
        result = self.s5.simulate_day(self._std_map())
        self.assertEqual(result["strategy_id"], "S5")

    def test_has_daily_pnl_key(self):
        """Результат содержит ключ 'daily_pnl'."""
        result = self.s5.simulate_day(self._std_map())
        self.assertIn("daily_pnl", result)

    def test_has_daily_return_pct_key(self):
        """Результат содержит ключ 'daily_return_pct'."""
        result = self.s5.simulate_day(self._std_map())
        self.assertIn("daily_return_pct", result)

    def test_has_annual_apy_pct_key(self):
        """Результат содержит ключ 'annual_apy_pct'."""
        result = self.s5.simulate_day(self._std_map())
        self.assertIn("annual_apy_pct", result)

    def test_has_allocation_key(self):
        """Результат содержит ключ 'allocation'."""
        result = self.s5.simulate_day(self._std_map())
        self.assertIn("allocation", result)

    def test_has_capital_key(self):
        """Результат содержит ключ 'capital'."""
        result = self.s5.simulate_day(self._std_map())
        self.assertIn("capital", result)

    def test_daily_pnl_formula(self):
        """daily_pnl = capital * annual_apy / 36500."""
        capital = 100_000.0
        result = self.s5.simulate_day(self._std_map(), capital=capital)
        annual_apy = result["annual_apy_pct"]
        expected_pnl = capital * annual_apy / 365.0 / 100.0
        self.assertAlmostEqual(result["daily_pnl"], expected_pnl, places=6)

    def test_daily_return_times_365_equals_annual_apy(self):
        """daily_return_pct × 365 ≈ annual_apy_pct."""
        result = self.s5.simulate_day(self._std_map())
        annual_reconstructed = result["daily_return_pct"] * 365
        self.assertAlmostEqual(annual_reconstructed, result["annual_apy_pct"], places=6)

    def test_capital_50k_half_pnl_vs_100k(self):
        """capital=50_000 → daily_pnl вдвое меньше, чем capital=100_000."""
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced
        s5a = S5PendleEnhanced(capital=100_000.0)
        s5b = S5PendleEnhanced(capital=50_000.0)
        res_100k = s5a.simulate_day(self._std_map(), capital=100_000.0)
        res_50k  = s5b.simulate_day(self._std_map(), capital=50_000.0)
        self.assertAlmostEqual(res_50k["daily_pnl"], res_100k["daily_pnl"] / 2.0, places=6)

    def test_allocation_in_result_matches_constant(self):
        """allocation в результате совпадает с модульной константой ALLOCATION."""
        from spa_core.strategies.s5_pendle_enhanced import ALLOCATION
        result = self.s5.simulate_day(self._std_map())
        for key, weight in ALLOCATION.items():
            self.assertAlmostEqual(result["allocation"][key], weight, places=9)

    def test_positive_pnl_with_valid_apy(self):
        """daily_pnl > 0 при ненулевом APY."""
        result = self.s5.simulate_day(self._std_map())
        self.assertGreater(result["daily_pnl"], 0.0)

    def test_zero_apy_map_zero_pnl(self):
        """Нулевой apy_map → daily_pnl ≈ 0."""
        zero_map = {"pendle_pt": 0.0, "morpho_steakhouse": 0.0, "compound_v3": 0.0}
        result = self.s5.simulate_day(zero_map, capital=100_000.0)
        self.assertAlmostEqual(result["daily_pnl"], 0.0, places=9)


# ─── TestS5Eligibility ────────────────────────────────────────────────────────

class TestS5Eligibility(unittest.TestCase):
    """Тесты метода is_eligible."""

    def setUp(self):
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced
        self.s5 = S5PendleEnhanced()

    def _std_map(self):
        return {"pendle_pt": 10.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}

    def test_eligible_with_full_std_map(self):
        """Полный стандартный apy_map → True."""
        self.assertTrue(self.s5.is_eligible(self._std_map()))

    def test_eligible_pendle_exactly_at_threshold(self):
        """pendle_pt=6.0 (точно на пороге) → True."""
        m = {"pendle_pt": 6.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        self.assertTrue(self.s5.is_eligible(m))

    def test_not_eligible_pendle_below_threshold(self):
        """pendle_pt=5.99 → False."""
        m = {"pendle_pt": 5.99, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        self.assertFalse(self.s5.is_eligible(m))

    def test_not_eligible_without_pendle_in_map(self):
        """Без pendle_pt в apy_map → False."""
        m = {"morpho_steakhouse": 6.5, "compound_v3": 4.8}
        self.assertFalse(self.s5.is_eligible(m))

    def test_not_eligible_empty_map(self):
        """Пустой apy_map → False."""
        self.assertFalse(self.s5.is_eligible({}))

    def test_eligible_high_pendle(self):
        """pendle_pt=15.0 → True."""
        m = {"pendle_pt": 15.0}
        self.assertTrue(self.s5.is_eligible(m))

    def test_not_eligible_zero_pendle(self):
        """pendle_pt=0.0 → False."""
        m = {"pendle_pt": 0.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        self.assertFalse(self.s5.is_eligible(m))

    def test_returns_bool(self):
        """is_eligible возвращает bool."""
        result = self.s5.is_eligible(self._std_map())
        self.assertIsInstance(result, bool)

    def test_pendle_just_above_threshold(self):
        """pendle_pt=6.01 → True."""
        m = {"pendle_pt": 6.01}
        self.assertTrue(self.s5.is_eligible(m))

    def test_pendle_just_below_threshold(self):
        """pendle_pt=5.999 → False."""
        m = {"pendle_pt": 5.999}
        self.assertFalse(self.s5.is_eligible(m))


# ─── TestS5VsS2 ───────────────────────────────────────────────────────────────

class TestS5VsS2(unittest.TestCase):
    """Тесты метода vs_s2_comparison."""

    def setUp(self):
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced
        self.s5 = S5PendleEnhanced()

    def _std_map(self):
        return {"pendle_pt": 10.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}

    def test_returns_dict(self):
        """vs_s2_comparison возвращает dict."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertIsInstance(result, dict)

    def test_has_s5_apy_key(self):
        """Результат содержит ключ 's5_apy'."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertIn("s5_apy", result)

    def test_has_s2_apy_key(self):
        """Результат содержит ключ 's2_apy'."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertIn("s2_apy", result)

    def test_has_gap_pct_key(self):
        """Результат содержит ключ 'gap_pct'."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertIn("gap_pct", result)

    def test_has_winner_key(self):
        """Результат содержит ключ 'winner'."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertIn("winner", result)

    def test_s5_wins_with_std_map(self):
        """При стандартных APY winner == 'S5'."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertEqual(result["winner"], "S5")

    def test_gap_positive_with_std_map(self):
        """gap_pct > 0 при стандартных APY (S5 > S2)."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertGreater(result["gap_pct"], 0.0)

    def test_s5_apy_approx_8_6(self):
        """s5_apy ≈ 8.605 при стандартных APY."""
        result = self.s5.vs_s2_comparison(self._std_map())
        expected_s5 = 0.65 * 10.0 + 0.25 * 6.5 + 0.10 * 4.8
        self.assertAlmostEqual(result["s5_apy"], expected_s5, places=6)

    def test_s2_apy_approx_7(self):
        """s2_apy ≈ 7.0 при стандартных APY."""
        result = self.s5.vs_s2_comparison(self._std_map())
        expected_s2 = 0.50 * 10.0 + 0.35 * 6.5 + 0.15 * 4.8
        self.assertAlmostEqual(result["s2_apy"], expected_s2, places=6)

    def test_gap_equals_s5_minus_s2(self):
        """gap_pct == s5_apy - s2_apy."""
        result = self.s5.vs_s2_comparison(self._std_map())
        self.assertAlmostEqual(
            result["gap_pct"],
            result["s5_apy"] - result["s2_apy"],
            places=9,
        )

    def test_s2_wins_when_pendle_below_threshold(self):
        """При pendle_pt < 6.0 S5 теряет Pendle-вклад → S2 может победить."""
        low_map = {"pendle_pt": 5.0, "morpho_steakhouse": 6.5, "compound_v3": 4.8}
        result = self.s5.vs_s2_comparison(low_map)
        # S5 без Pendle: 0.25*6.5+0.10*4.8=2.105
        # S2 без фильтра (S2 не фильтрует): 0.50*5.0+0.35*6.5+0.15*4.8=2.5+2.275+0.72=5.495
        self.assertEqual(result["winner"], "S2")

    def test_winner_s5_when_gap_positive(self):
        """winner == 'S5' тогда и только тогда, когда gap_pct > 0."""
        result = self.s5.vs_s2_comparison(self._std_map())
        if result["gap_pct"] > 0:
            self.assertEqual(result["winner"], "S5")
        else:
            self.assertEqual(result["winner"], "S2")


# ─── TestS5VPortfolioFormat ───────────────────────────────────────────────────

class TestS5VPortfolioFormat(unittest.TestCase):
    """Тесты метода to_vportfolio_format."""

    def setUp(self):
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced
        self.s5 = S5PendleEnhanced()

    def test_returns_dict(self):
        """to_vportfolio_format() возвращает dict."""
        result = self.s5.to_vportfolio_format()
        self.assertIsInstance(result, dict)

    def test_id_is_s5(self):
        """id == 'S5'."""
        result = self.s5.to_vportfolio_format()
        self.assertEqual(result["id"], "S5")

    def test_name_is_pendle_pt_enhanced(self):
        """name == 'Pendle PT Enhanced'."""
        result = self.s5.to_vportfolio_format()
        self.assertEqual(result["name"], "Pendle PT Enhanced")

    def test_allocation_sums_to_one(self):
        """allocation суммируется в 1.0."""
        result = self.s5.to_vportfolio_format()
        total = sum(result["allocation"].values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_risk_score_in_range(self):
        """risk_score в диапазоне (0, 1)."""
        result = self.s5.to_vportfolio_format()
        self.assertGreater(result["risk_score"], 0.0)
        self.assertLess(result["risk_score"], 1.0)

    def test_apy_target_equals_constant(self):
        """apy_target == APY_TARGET_PCT."""
        from spa_core.strategies.s5_pendle_enhanced import APY_TARGET_PCT
        result = self.s5.to_vportfolio_format()
        self.assertAlmostEqual(result["apy_target"], APY_TARGET_PCT, places=9)

    def test_tier_field_present(self):
        """'tier' присутствует в результате."""
        result = self.s5.to_vportfolio_format()
        self.assertIn("tier", result)

    def test_has_strategy_id_field(self):
        """'strategy_id' присутствует в результате."""
        result = self.s5.to_vportfolio_format()
        self.assertIn("strategy_id", result)

    def test_strategy_id_equals_id(self):
        """strategy_id совпадает с id."""
        result = self.s5.to_vportfolio_format()
        self.assertEqual(result["strategy_id"], result["id"])

    def test_current_equity_positive(self):
        """current_equity > 0 при ненулевом капитале."""
        result = self.s5.to_vportfolio_format()
        self.assertGreater(result["current_equity"], 0.0)


# ─── TestS5Advantage ──────────────────────────────────────────────────────────

class TestS5Advantage(unittest.TestCase):
    """Тесты метода get_pendle_advantage."""

    def setUp(self):
        from spa_core.strategies.s5_pendle_enhanced import S5PendleEnhanced, APY_TARGET_PCT
        self.s5 = S5PendleEnhanced()
        self.apy_target = APY_TARGET_PCT

    def test_advantage_positive_vs_aave_baseline(self):
        """get_pendle_advantage() > 0 vs Aave baseline 3.2%."""
        advantage = self.s5.get_pendle_advantage(3.2)
        self.assertGreater(advantage, 0.0)

    def test_advantage_formula_exact(self):
        """get_pendle_advantage(3.2) == APY_TARGET_PCT - 3.2."""
        advantage = self.s5.get_pendle_advantage(3.2)
        expected = self.apy_target - 3.2
        self.assertAlmostEqual(advantage, expected, places=9)

    def test_advantage_default_baseline_is_3_2(self):
        """Дефолтный baseline == 3.2%."""
        advantage_explicit = self.s5.get_pendle_advantage(3.2)
        advantage_default  = self.s5.get_pendle_advantage()
        self.assertAlmostEqual(advantage_explicit, advantage_default, places=9)

    def test_advantage_vs_higher_baseline(self):
        """advantage < 0 если baseline > APY_TARGET_PCT."""
        advantage = self.s5.get_pendle_advantage(self.apy_target + 1.0)
        self.assertLess(advantage, 0.0)

    def test_advantage_vs_equal_baseline(self):
        """advantage == 0 если baseline == APY_TARGET_PCT."""
        advantage = self.s5.get_pendle_advantage(self.apy_target)
        self.assertAlmostEqual(advantage, 0.0, places=9)

    def test_advantage_vs_zero_baseline(self):
        """advantage == APY_TARGET_PCT если baseline == 0."""
        advantage = self.s5.get_pendle_advantage(0.0)
        self.assertAlmostEqual(advantage, self.apy_target, places=9)

    def test_returns_float(self):
        """get_pendle_advantage возвращает float."""
        advantage = self.s5.get_pendle_advantage()
        self.assertIsInstance(advantage, float)

    def test_advantage_vs_s0_is_about_5_3(self):
        """advantage vs S0 (3.2%) ≈ 5.3 процентных пункта."""
        advantage = self.s5.get_pendle_advantage(3.2)
        # 8.5 - 3.2 = 5.3
        self.assertAlmostEqual(advantage, 5.3, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
