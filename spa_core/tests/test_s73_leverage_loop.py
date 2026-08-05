"""
spa_core/tests/test_s73_leverage_loop.py

Tests for S73LeverageLoop (spa_core/strategies/s73_leverage_loop.py).

AUD-18 (задание владельца 2026-08-05) — карточка
`agent-aud18-strategy-unit-tests`.

Замер покрытия ДО этого файла (трассировка исполнения существующим набором
`tests/test_advanced_strategies.py`, докстринги исключены):

    allocate               1/1   покрыт
    effective_apy          1/1   покрыт
    is_eligible            1/1   покрыт
    compute_weighted_apy   0/7   НЕ ИСПОЛНЯЛСЯ НИ РАЗУ
    get_info               0/2   НЕ ИСПОЛНЯЛСЯ НИ РАЗУ

Существующий набор проверяет формулу плеча, но НЕ проверяет, что эта формула
вообще доходит до портфельного числа: ветка «взять живой aave_v3_wsteth» и
ветка «посчитать самому» не исполнялись ни разу.

Read-only, stdlib, без сети, без записи на диск.

Run:
    python3 -m unittest spa_core.tests.test_s73_leverage_loop -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s73_leverage_loop import (  # noqa: E402
    S73LeverageLoop,
    ALLOCATION,
    BORROW_RATE_DEFAULT,
    FALLBACK_APY,
    LEVERAGE_RATIO,
    LIQUIDATION_THRESHOLD,
    PROTOCOL_TIERS,
    RISK_TIER,
    STAKING_APY_DEFAULT,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
)

# 3.5*2 − 1.5*1 = 5.5 % — «эффективная» доходность петли на дефолтных ставках
_DEFAULT_EFFECTIVE_APY = (
    STAKING_APY_DEFAULT * LEVERAGE_RATIO - BORROW_RATE_DEFAULT * (LEVERAGE_RATIO - 1.0)
)


class TestS73Allocation(unittest.TestCase):

    def setUp(self):
        self.s = S73LeverageLoop()

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.s.allocate({}).values()), 1.0, places=9)

    def test_cash_buffer_15pct(self):
        self.assertGreaterEqual(self.s.allocate({})["cash"], 0.15)

    def test_allocation_ignores_apy_data(self):
        # Статическая аллокация: снимок APY на веса не влияет.
        self.assertEqual(self.s.allocate({"aave_v3_wsteth": 99.0}), self.s.allocate({}))

    def test_allocate_returns_copy_not_module_constant(self):
        got = self.s.allocate({})
        self.assertIsNot(got, ALLOCATION)
        got["cash"] = 0.99
        self.assertEqual(ALLOCATION["cash"], 0.15)
        self.assertEqual(self.s.allocate({})["cash"], 0.15)


class TestS73EffectiveApy(unittest.TestCase):

    def setUp(self):
        self.s = S73LeverageLoop()

    def test_default_rates_give_5_5_pct(self):
        self.assertAlmostEqual(
            self.s.effective_apy(STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT), 5.5, places=9
        )

    def test_negative_spread_can_go_negative(self):
        # borrow 8% при стейкинге 3.5% и плече 2x: 7.0 − 8.0 = −1.0
        self.assertAlmostEqual(self.s.effective_apy(3.5, 8.0), -1.0, places=9)

    def test_zero_borrow_is_pure_leverage(self):
        self.assertAlmostEqual(self.s.effective_apy(4.0, 0.0), 4.0 * LEVERAGE_RATIO, places=9)

    def test_higher_borrow_never_increases_net(self):
        self.assertLess(self.s.effective_apy(3.5, 3.0), self.s.effective_apy(3.5, 1.0))


class TestS73WeightedApy(unittest.TestCase):
    """compute_weighted_apy — метод, который до этого файла не исполнялся ни разу."""

    def setUp(self):
        self.s = S73LeverageLoop()

    def test_default_uses_effective_apy_not_fallback_table(self):
        # 0.85 * 5.5 = 4.675 — считается формулой плеча, а НЕ FALLBACK_APY (7.5).
        expected = ALLOCATION["aave_v3_wsteth"] * _DEFAULT_EFFECTIVE_APY
        self.assertAlmostEqual(self.s.compute_weighted_apy(), expected, places=9)
        self.assertNotAlmostEqual(
            self.s.compute_weighted_apy(),
            ALLOCATION["aave_v3_wsteth"] * FALLBACK_APY["aave_v3_wsteth"],
            places=6,
        )

    def test_none_equals_empty_dict(self):
        self.assertEqual(self.s.compute_weighted_apy(None), self.s.compute_weighted_apy({}))

    def test_live_value_overrides_the_formula(self):
        got = self.s.compute_weighted_apy({"aave_v3_wsteth": 10.0})
        self.assertAlmostEqual(got, ALLOCATION["aave_v3_wsteth"] * 10.0, places=9)

    def test_negative_live_value_pulls_portfolio_negative(self):
        # Отрицательный спред обязан доходить до портфельного числа, а не гаситься.
        got = self.s.compute_weighted_apy({"aave_v3_wsteth": -2.0})
        self.assertAlmostEqual(got, ALLOCATION["aave_v3_wsteth"] * -2.0, places=9)
        self.assertLess(got, 0.0)

    def test_cash_never_contributes(self):
        # cash захардкожен в 0% — что бы ни лежало в снимке.
        self.assertEqual(
            self.s.compute_weighted_apy({"aave_v3_wsteth": 5.0, "cash": 99.0}),
            self.s.compute_weighted_apy({"aave_v3_wsteth": 5.0}),
        )

    def test_string_value_is_accepted(self):
        self.assertAlmostEqual(
            self.s.compute_weighted_apy({"aave_v3_wsteth": "8.0"}),
            ALLOCATION["aave_v3_wsteth"] * 8.0, places=9,
        )

    def test_deterministic(self):
        data = {"aave_v3_wsteth": 6.25}
        self.assertEqual(self.s.compute_weighted_apy(data), self.s.compute_weighted_apy(data))

    def test_default_within_declared_band(self):
        self.assertGreaterEqual(self.s.compute_weighted_apy(), TARGET_APY_MIN)
        self.assertLessEqual(self.s.compute_weighted_apy(), TARGET_APY_MAX)


class TestS73Eligibility(unittest.TestCase):

    def setUp(self):
        self.s = S73LeverageLoop()

    def test_exactly_at_minimum_is_eligible(self):
        # Граница включающая: `>=`. Фиксируем как есть.
        self.assertTrue(self.s.is_eligible(min_capital_usd=50_000.0, capital_usd=50_000.0))

    def test_one_cent_below_minimum_is_not(self):
        self.assertFalse(self.s.is_eligible(min_capital_usd=50_000.0, capital_usd=49_999.99))


class TestS73Info(unittest.TestCase):
    """get_info — до этого файла не исполнялся ни разу."""

    def setUp(self):
        self.s = S73LeverageLoop()
        self.info = self.s.get_info()

    def test_identity_fields(self):
        self.assertEqual(self.info["strategy_id"], "S73")
        self.assertEqual(self.info["strategy_name"], STRATEGY_NAME)
        self.assertEqual(self.info["risk_tier"], "T3")
        self.assertEqual(RISK_TIER, "T3")

    def test_advisory_flag_true(self):
        self.assertTrue(self.info["is_advisory"])
        self.assertTrue(S73LeverageLoop.IS_ADVISORY)

    def test_reports_effective_apy_consistent_with_formula(self):
        # Число в метаданных обязано совпадать с тем, что считает формула.
        self.assertAlmostEqual(
            self.info["effective_apy_default"], _DEFAULT_EFFECTIVE_APY, places=9
        )

    def test_declared_expected_apy_matches_the_formula(self):
        # EXPECTED_APY_PCT — это не отдельная константа «на глаз»: она обязана
        # совпадать с 3.5*2 − 1.5*1, иначе стратегия обещает не то, что считает.
        self.assertAlmostEqual(
            S73LeverageLoop.EXPECTED_APY_PCT, _DEFAULT_EFFECTIVE_APY, places=9
        )

    def test_leverage_parameters_exposed(self):
        self.assertEqual(LEVERAGE_RATIO, 2.0)
        self.assertEqual(LIQUIDATION_THRESHOLD, 0.825)
        self.assertEqual(self.info["leverage_ratio"], LEVERAGE_RATIO)
        self.assertEqual(self.info["liquidation_threshold"], LIQUIDATION_THRESHOLD)
        self.assertEqual(self.info["staking_apy_default"], STAKING_APY_DEFAULT)
        self.assertEqual(self.info["borrow_rate_default"], BORROW_RATE_DEFAULT)

    def test_caveat_non_empty(self):
        self.assertTrue(self.info["caveat"].strip())

    def test_info_dicts_are_copies(self):
        self.info["allocation"]["cash"] = 0.99
        self.info["protocol_tiers"]["cash"] = "T3"
        self.info["fallback_apy"]["cash"] = 99.0
        self.assertEqual(ALLOCATION["cash"], 0.15)
        self.assertEqual(PROTOCOL_TIERS["cash"], "CASH")
        self.assertEqual(FALLBACK_APY["cash"], 0.0)

    def test_deterministic_except_timestamp(self):
        a = dict(self.s.get_info())
        b = dict(self.s.get_info())
        a.pop("generated_at", None)
        b.pop("generated_at", None)
        self.assertEqual(a, b)

    def test_module_identity_constants(self):
        self.assertEqual(STRATEGY_ID, "S73")
        self.assertEqual(TARGET_APY_MIN, 4.0)
        self.assertEqual(TARGET_APY_MAX, 12.0)


if __name__ == "__main__":
    unittest.main()
