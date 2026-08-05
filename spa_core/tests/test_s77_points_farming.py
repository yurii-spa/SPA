"""
spa_core/tests/test_s77_points_farming.py

Tests for S77PointsFarming (spa_core/strategies/s77_points_farming.py).

AUD-18 (задание владельца 2026-08-05) — карточка
`agent-aud18-strategy-unit-tests`.

Замер покрытия ДО этого файла (трассировка исполнения существующим набором
`tests/test_advanced_strategies.py`, докстринги исключены):

    allocate                     1/1  покрыт
    compute_weighted_apy         7/7  покрыт
    compute_points_adjusted_apy  3/3  покрыт
    active_campaigns             1/1  покрыт
    get_info                     0/1  НЕ ИСПОЛНЯЛСЯ НИ РАЗУ

Строки исполнялись — но семантика «поинты могут стоить НОЛЬ» ничем не
закреплена: premium=0.0 отличается от premium=None только тем, что в коде
написано `is not None`, а не `if premium`. Регрессия в одну строку молча
превратила бы честный ноль в +11 % «премии». Здесь это положительный контроль.

Read-only, stdlib, без сети, без записи на диск.

Run:
    python3 -m unittest spa_core.tests.test_s77_points_farming -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s77_points_farming import (  # noqa: E402
    S77PointsFarming,
    ALLOCATION,
    FALLBACK_APY,
    POINTS_APY_PREMIUM_PCT,
    PROTOCOL_TIERS,
    REWARD_CAMPAIGNS,
    RISK_TIER,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
)

# 0.40*6.5 + 0.25*14.0 + 0.20*4.2 + 0.15*0.0 = 6.94 %
_BASE_APY = sum(ALLOCATION[p] * FALLBACK_APY[p] for p in ALLOCATION)


class TestS77Allocation(unittest.TestCase):

    def setUp(self):
        self.s = S77PointsFarming()

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.s.allocate({}).values()), 1.0, places=9)

    def test_cash_buffer_15pct(self):
        self.assertGreaterEqual(self.s.allocate({})["cash"], 0.15)

    def test_static_allocation_ignores_apy_data(self):
        self.assertEqual(self.s.allocate({"morpho_steakhouse": 99.0}), self.s.allocate({}))

    def test_allocate_returns_copy_not_module_constant(self):
        got = self.s.allocate({})
        self.assertIsNot(got, ALLOCATION)
        got["cash"] = 0.99
        self.assertEqual(ALLOCATION["cash"], 0.15)
        self.assertEqual(self.s.allocate({})["cash"], 0.15)

    def test_t3_sleeve_present_and_bounded(self):
        alloc = self.s.allocate({})
        t3 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T3")
        self.assertGreater(t3, 0.0)
        self.assertLessEqual(t3, 0.25)


class TestS77BaseApy(unittest.TestCase):

    def setUp(self):
        self.s = S77PointsFarming()

    def test_base_apy_matches_docstring(self):
        self.assertAlmostEqual(self.s.compute_weighted_apy(), 6.94, places=6)
        self.assertAlmostEqual(self.s.compute_weighted_apy(), _BASE_APY, places=9)

    def test_base_apy_excludes_points_premium(self):
        # Базовая доходность НЕ включает премию — это разные числа.
        self.assertNotAlmostEqual(
            self.s.compute_weighted_apy(),
            self.s.compute_points_adjusted_apy(),
            places=6,
        )

    def test_none_equals_empty_dict(self):
        self.assertEqual(self.s.compute_weighted_apy(None), self.s.compute_weighted_apy({}))

    def test_live_values_override_fallbacks(self):
        got = self.s.compute_weighted_apy({"morpho_steakhouse": 0.0})
        self.assertAlmostEqual(got, _BASE_APY - ALLOCATION["morpho_steakhouse"] * 6.5, places=9)

    def test_base_apy_at_or_above_declared_floor(self):
        self.assertGreaterEqual(self.s.compute_weighted_apy(), TARGET_APY_MIN)


class TestS77PointsPremium(unittest.TestCase):
    """Поинты могут стоить НОЛЬ — этот случай обязан быть выразим."""

    def setUp(self):
        self.s = S77PointsFarming()

    def test_default_premium_is_added(self):
        self.assertAlmostEqual(
            self.s.compute_points_adjusted_apy(), _BASE_APY + POINTS_APY_PREMIUM_PCT, places=9
        )

    def test_explicit_zero_premium_means_zero_not_default(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ.

        `premium=0.0` — это «поинты оказались бесполезны», а не «премия не
        задана». Различие держится ровно на `is not None`; замена на `if premium`
        молча вернула бы +11 % там, где честный ответ — базовая доходность.
        """
        got = self.s.compute_points_adjusted_apy(points_premium_pct=0.0)
        self.assertAlmostEqual(got, _BASE_APY, places=9)
        self.assertAlmostEqual(got, self.s.compute_weighted_apy(), places=9)
        self.assertNotAlmostEqual(got, _BASE_APY + POINTS_APY_PREMIUM_PCT, places=6)

    def test_negative_premium_is_passed_through(self):
        # Кампания может обернуться убытком по токену — число не клампится.
        self.assertAlmostEqual(
            self.s.compute_points_adjusted_apy(points_premium_pct=-3.0),
            _BASE_APY - 3.0, places=9,
        )

    def test_peak_premium_stays_within_declared_ceiling(self):
        peak = self.s.compute_points_adjusted_apy(points_premium_pct=TARGET_APY_MAX - _BASE_APY)
        self.assertLessEqual(peak, TARGET_APY_MAX + 1e-9)

    def test_apy_data_and_premium_compose(self):
        got = self.s.compute_points_adjusted_apy({"spark_susds": 0.0}, points_premium_pct=5.0)
        expected = (_BASE_APY - ALLOCATION["spark_susds"] * FALLBACK_APY["spark_susds"]) + 5.0
        self.assertAlmostEqual(got, expected, places=9)

    def test_deterministic(self):
        self.assertEqual(
            self.s.compute_points_adjusted_apy(), self.s.compute_points_adjusted_apy()
        )


class TestS77Campaigns(unittest.TestCase):

    def setUp(self):
        self.s = S77PointsFarming()

    def test_campaigns_cover_every_non_cash_protocol(self):
        for protocol in ALLOCATION:
            if protocol == "cash":
                continue
            self.assertIn(protocol, self.s.active_campaigns())

    def test_campaigns_returns_copy(self):
        got = self.s.active_campaigns()
        self.assertIsNot(got, REWARD_CAMPAIGNS)
        got["morpho_steakhouse"] = "МУСОР"
        self.assertNotEqual(REWARD_CAMPAIGNS["morpho_steakhouse"], "МУСОР")


class TestS77Info(unittest.TestCase):
    """get_info — до этого файла не исполнялся ни разу."""

    def setUp(self):
        self.s = S77PointsFarming()
        self.info = self.s.get_info()

    def test_identity_fields(self):
        self.assertEqual(self.info["strategy_id"], "S77")
        self.assertEqual(self.info["strategy_name"], STRATEGY_NAME)
        self.assertEqual(self.info["risk_tier"], "T3")
        self.assertEqual(RISK_TIER, "T3")

    def test_advisory_flag_true(self):
        self.assertTrue(self.info["is_advisory"])
        self.assertTrue(S77PointsFarming.IS_ADVISORY)

    def test_caveat_names_the_zero_points_risk(self):
        # Честный хвост обязан быть в тексте, а не только в докстринге модуля.
        self.assertIn("may be 0", self.info["caveat"])

    def test_premium_exposed_and_matches_module(self):
        self.assertEqual(self.info["points_apy_premium_pct"], POINTS_APY_PREMIUM_PCT)

    def test_info_dicts_are_copies(self):
        self.info["allocation"]["cash"] = 0.99
        self.info["reward_campaigns"]["spark_susds"] = "МУСОР"
        self.info["fallback_apy"]["cash"] = 99.0
        self.assertEqual(ALLOCATION["cash"], 0.15)
        self.assertNotEqual(REWARD_CAMPAIGNS["spark_susds"], "МУСОР")
        self.assertEqual(FALLBACK_APY["cash"], 0.0)

    def test_deterministic_except_timestamp(self):
        a = dict(self.s.get_info())
        b = dict(self.s.get_info())
        a.pop("generated_at", None)
        b.pop("generated_at", None)
        self.assertEqual(a, b)

    def test_module_identity_constants(self):
        self.assertEqual(STRATEGY_ID, "S77")
        self.assertEqual(TARGET_APY_MIN, 5.0)
        self.assertEqual(TARGET_APY_MAX, 40.0)


if __name__ == "__main__":
    unittest.main()
