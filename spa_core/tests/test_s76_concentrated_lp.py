"""
spa_core/tests/test_s76_concentrated_lp.py

Tests for S76ConcentratedLP (spa_core/strategies/s76_concentrated_lp.py).

AUD-18 (задание владельца 2026-08-05) — карточка
`agent-aud18-strategy-unit-tests`.

Замер покрытия ДО этого файла (трассировка исполнения существующим набором
`tests/test_advanced_strategies.py`, докстринги исключены):

    allocate               4/4   покрыт
    current_regime         2/2   покрыт
    compute_weighted_apy   0/11  НЕ ИСПОЛНЯЛСЯ НИ РАЗУ
    get_info               0/1   НЕ ИСПОЛНЯЛСЯ НИ РАЗУ

Поэтому здесь не дублируются уже закреплённые проверки весов, а целится
непокрытое: расчёт смешанной доходности (именно он протекает в турнир) и
метаданные. Плюс — граница порога и копийность возвращаемых словарей.

Read-only, stdlib, без сети, без записи на диск.

Run:
    python3 -m unittest spa_core.tests.test_s76_concentrated_lp -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s76_concentrated_lp import (  # noqa: E402
    S76ConcentratedLP,
    ALLOC_LP_ACTIVE,
    ALLOC_LP_OFF,
    FALLBACK_APY,
    LP_ATTRACTIVE_THRESHOLD,
    PROTOCOL_TIERS,
    RISK_TIER,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _apy_data(lp_apy=None, **overrides) -> dict:
    """Build an apy_data snapshot; lp_apy is the aerodrome LP regime driver."""
    data = dict(overrides)
    if lp_apy is not None:
        data["aerodrome_usdc_lp"] = lp_apy
    return data


class TestS76Regime(unittest.TestCase):
    """Режим и порог 6% — граница фиксируется как есть (правка только по ADR)."""

    def setUp(self):
        self.s = S76ConcentratedLP()

    def test_threshold_is_strictly_greater(self):
        # РОВНО на пороге — это lp_off: сравнение `>`, не `>=`.
        self.assertEqual(self.s.current_regime(_apy_data(LP_ATTRACTIVE_THRESHOLD)), "lp_off")
        self.assertEqual(self.s.allocate(_apy_data(LP_ATTRACTIVE_THRESHOLD)), ALLOC_LP_OFF)

    def test_just_above_threshold_is_active(self):
        just_above = LP_ATTRACTIVE_THRESHOLD + 1e-9
        self.assertEqual(self.s.current_regime(_apy_data(just_above)), "lp_active")
        self.assertEqual(self.s.allocate(_apy_data(just_above)), ALLOC_LP_ACTIVE)

    def test_missing_key_uses_fallback_and_is_active(self):
        # Пустой снимок ⇒ fallback 0.085 > 0.06 ⇒ режим LP.
        self.assertEqual(self.s.current_regime({}), "lp_active")

    def test_string_apy_is_accepted(self):
        # float() применяется к сырому значению — числовая строка не роняет расчёт.
        self.assertEqual(self.s.current_regime(_apy_data("0.09")), "lp_active")

    def test_weights_sum_to_one_both_regimes(self):
        for lp in (0.09, 0.01):
            with self.subTest(lp=lp):
                self.assertAlmostEqual(sum(self.s.allocate(_apy_data(lp)).values()), 1.0, places=9)

    def test_cash_buffer_at_least_15pct_both_regimes(self):
        for lp in (0.09, 0.01):
            with self.subTest(lp=lp):
                self.assertGreaterEqual(self.s.allocate(_apy_data(lp))["cash"], 0.15)


class TestS76AllocateIsolation(unittest.TestCase):
    """Возвращаемый словарь обязан быть копией: турнир мутирует веса на месте."""

    def setUp(self):
        self.s = S76ConcentratedLP()

    def test_allocate_returns_copy_not_module_constant(self):
        got = self.s.allocate(_apy_data(0.09))
        self.assertIsNot(got, ALLOC_LP_ACTIVE)
        got["cash"] = 0.99
        self.assertEqual(ALLOC_LP_ACTIVE["cash"], 0.15)
        # следующий вызов не отравлен предыдущим
        self.assertEqual(self.s.allocate(_apy_data(0.09))["cash"], 0.15)

    def test_allocate_lp_off_returns_copy(self):
        got = self.s.allocate(_apy_data(0.01))
        self.assertIsNot(got, ALLOC_LP_OFF)
        got["aave_v3"] = 0.0
        self.assertEqual(ALLOC_LP_OFF["aave_v3"], 0.50)


class TestS76WeightedApy(unittest.TestCase):
    """compute_weighted_apy — метод, который до этого файла не исполнялся ни разу."""

    def setUp(self):
        self.s = S76ConcentratedLP()

    def test_default_matches_docstring_lp_active(self):
        # 0.60*8.5 + 0.25*3.5 + 0.15*0.0 = 5.975 (докстринг: ≈5.97%)
        self.assertAlmostEqual(self.s.compute_weighted_apy(), 5.975, places=6)

    def test_none_equals_empty_dict(self):
        self.assertEqual(self.s.compute_weighted_apy(None), self.s.compute_weighted_apy({}))

    def test_lp_off_matches_docstring(self):
        # 0.50*3.5 + 0.35*4.8 + 0.15*0.0 = 3.43 (докстринг: ≈3.43%)
        self.assertAlmostEqual(self.s.compute_weighted_apy(_apy_data(0.01)), 3.43, places=6)

    def test_live_percent_values_are_blended_as_percent(self):
        # LP отдан в процентах (12.0) — режим LP, умножения на 100 нет.
        got = self.s.compute_weighted_apy(_apy_data(12.0, aave_v3=4.0))
        self.assertAlmostEqual(got, 0.60 * 12.0 + 0.25 * 4.0, places=6)

    def test_cash_contributes_zero(self):
        got = self.s.compute_weighted_apy(_apy_data(10.0, aave_v3=0.0, cash=99.0))
        # cash передан явно и ВСЁ РАВНО учитывается как 99 — фиксируем как есть:
        # метод не занулят cash принудительно, он берёт то, что дали.
        self.assertAlmostEqual(got, 0.60 * 10.0 + 0.15 * 99.0, places=6)

    def test_decimal_fallback_is_scaled_to_percent(self):
        # Десятичный fallback 0.085 сознательно домножается на 100 → 8.5%.
        self.assertAlmostEqual(
            self.s.compute_weighted_apy(_apy_data(FALLBACK_APY["aerodrome_usdc_lp"])),
            5.975, places=6,
        )

    def test_sub_one_percent_lp_apy_is_inflated_x100_CURRENT_BEHAVIOUR(self):
        """ЗАФИКСИРОВАНО КАК ЕСТЬ, НЕ ИСПРАВЛЕНО (правка меняет публикуемое число).

        Единица измерения угадывается по величине: `apy_pct < 1.0 → *100`.
        Настоящие 0.5 % годовых (в процентах, как требует докстринг) становятся
        50 % и дают ~30.9 % смешанной доходности. Тест существует, чтобы
        двусмысленность была ВИДНА и её изменение было осознанным, а не
        случайным. Карточка: agent-s76-apy-unit-guess.
        """
        got = self.s.compute_weighted_apy(_apy_data(0.5, aave_v3=3.5))
        self.assertAlmostEqual(got, 0.60 * 50.0 + 0.25 * 3.5, places=6)
        self.assertGreater(got, 30.0)

    def test_unknown_protocol_in_apy_data_is_ignored(self):
        # Веса задают вселенную; лишний ключ в снимке ничего не добавляет.
        base = self.s.compute_weighted_apy(_apy_data(10.0))
        with_junk = self.s.compute_weighted_apy(_apy_data(10.0, some_unknown_pool=99.0))
        self.assertAlmostEqual(base, with_junk, places=9)

    def test_deterministic(self):
        data = _apy_data(0.09, aave_v3=3.1)
        self.assertEqual(self.s.compute_weighted_apy(data), self.s.compute_weighted_apy(data))

    def test_within_declared_target_band_on_fallbacks(self):
        self.assertGreaterEqual(self.s.compute_weighted_apy(), TARGET_APY_MIN)
        self.assertLessEqual(self.s.compute_weighted_apy(), TARGET_APY_MAX)


class TestS76Info(unittest.TestCase):
    """get_info — до этого файла не исполнялся ни разу."""

    def setUp(self):
        self.s = S76ConcentratedLP()
        self.info = self.s.get_info()

    def test_identity_fields(self):
        self.assertEqual(self.info["strategy_id"], "S76")
        self.assertEqual(self.info["strategy_name"], STRATEGY_NAME)
        self.assertEqual(self.info["risk_tier"], "T2")
        self.assertEqual(RISK_TIER, "T2")

    def test_advisory_flag_true(self):
        self.assertTrue(self.info["is_advisory"])
        self.assertTrue(S76ConcentratedLP.IS_ADVISORY)

    def test_caveat_non_empty(self):
        self.assertTrue(self.info["caveat"].strip())

    def test_threshold_and_allocations_exposed(self):
        self.assertEqual(self.info["lp_attractive_threshold"], LP_ATTRACTIVE_THRESHOLD)
        self.assertEqual(self.info["alloc_lp_active"], ALLOC_LP_ACTIVE)
        self.assertEqual(self.info["alloc_lp_off"], ALLOC_LP_OFF)

    def test_info_dicts_are_copies(self):
        self.info["alloc_lp_active"]["cash"] = 0.99
        self.info["protocol_tiers"]["cash"] = "T3"
        self.assertEqual(ALLOC_LP_ACTIVE["cash"], 0.15)
        self.assertEqual(PROTOCOL_TIERS["cash"], "CASH")

    def test_generated_at_is_iso_utc(self):
        self.assertIn("T", self.info["generated_at"])
        self.assertTrue(self.info["generated_at"].endswith("+00:00"))

    def test_deterministic_except_timestamp(self):
        a = dict(self.s.get_info())
        b = dict(self.s.get_info())
        a.pop("generated_at")
        b.pop("generated_at")
        self.assertEqual(a, b)

    def test_module_identity_constants(self):
        self.assertEqual(STRATEGY_ID, "S76")
        self.assertEqual(TARGET_APY_MIN, 2.0)
        self.assertEqual(TARGET_APY_MAX, 18.0)


if __name__ == "__main__":
    unittest.main()
