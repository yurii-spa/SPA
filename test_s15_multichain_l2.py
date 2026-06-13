"""
spa_core/tests/test_s15_multichain_l2.py — MP-591 S15 MultiChain L2 Yield Strategy Tests

Тест-сьют для S15 MultiChainL2Strategy.
Покрытие: 80+ тестов по 7 группам.

Группы:
  TestInit (10)            — создание, _load_adapters, константы модуля
  TestGetAllocation (15)   — правильные weights, перераспределение при недоступном адаптере
  TestGetExpectedAPY (12)  — weighted avg, fallback при пустых адаптерах
  TestGetHealth (12)       — all_eligible=True/False, chain_breakdown структура
  TestGetGasSavings (10)   — avg_savings_pct > 0, shape
  TestSimulate (12)        — expected_annual_yield_usd > 0, allocation sums to capital
  TestToDict (9)           — все поля, JSON serializable

Запуск: python3 -m unittest spa_core.tests.test_s15_multichain_l2 -v
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from spa_core.strategies.s15_multichain_l2 import (
    CHAIN_WEIGHTS,
    DESCRIPTION,
    FALLBACK_APY,
    GAS_INFO,
    MAX_DRAWDOWN_PCT,
    RISK_BLENDED,
    RISK_SCORES,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
    TARGET_APY_PCT,
    TIER,
    WEIGHTED_APY_EXPECTED,
    MultiChainL2Strategy,
    _register,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_adapter(apy: float = 5.0, eligible: bool = True) -> MagicMock:
    """Создаёт mock адаптер с get_apy() и is_eligible()."""
    m = MagicMock()
    m.get_apy.return_value = apy
    m.is_eligible.return_value = eligible
    m.simulate_deposit.return_value = {
        "status": "ok",
        "protocol": "mock",
        "amount_usd": 0,
        "apy_pct": apy,
        "annual_yield_usd": 0,
    }
    return m


def _make_strategy_no_adapters() -> MultiChainL2Strategy:
    """Возвращает стратегию с пустым _adapters (все адаптеры не загружены)."""
    s = MultiChainL2Strategy.__new__(MultiChainL2Strategy)
    s._adapters = {}
    return s


def _make_strategy_all_mocked(
    base_apy: float = 5.0,
    opt_apy: float = 4.8,
    arb_apy: float = 4.6,
    base_eligible: bool = True,
    opt_eligible: bool = True,
    arb_eligible: bool = True,
) -> MultiChainL2Strategy:
    """Возвращает стратегию с моками всех трёх адаптеров."""
    s = MultiChainL2Strategy.__new__(MultiChainL2Strategy)
    s._adapters = {
        "aave_v3_base":     _make_mock_adapter(base_apy, base_eligible),
        "aave_v3_optimism": _make_mock_adapter(opt_apy, opt_eligible),
        "aave_arbitrum":    _make_mock_adapter(arb_apy, arb_eligible),
    }
    return s


# ─── TestInit ────────────────────────────────────────────────────────────────

class TestInit(unittest.TestCase):
    """10 тестов: создание объекта, модульные константы, _load_adapters."""

    def test_instantiation_no_error(self):
        """MultiChainL2Strategy создаётся без исключений."""
        s = MultiChainL2Strategy()
        self.assertIsInstance(s, MultiChainL2Strategy)

    def test_adapters_dict_exists(self):
        """После __init__ _adapters — это dict."""
        s = MultiChainL2Strategy()
        self.assertIsInstance(s._adapters, dict)

    def test_strategy_id_constant(self):
        """STRATEGY_ID == 'S15'."""
        self.assertEqual(STRATEGY_ID, "S15")

    def test_strategy_name_constant(self):
        """STRATEGY_NAME содержит 'MultiChain'."""
        self.assertIn("MultiChain", STRATEGY_NAME)

    def test_tier_constant(self):
        """TIER == 'T1'."""
        self.assertEqual(TIER, "T1")

    def test_target_apy_pct_constant(self):
        """TARGET_APY_PCT == 5.5."""
        self.assertAlmostEqual(TARGET_APY_PCT, 5.5)

    def test_chain_weights_keys(self):
        """CHAIN_WEIGHTS содержит ровно 3 ключа (Base, Optimism, Arbitrum)."""
        expected_keys = {"aave_v3_base", "aave_v3_optimism", "aave_arbitrum"}
        self.assertEqual(set(CHAIN_WEIGHTS.keys()), expected_keys)

    def test_chain_weights_sum_to_one(self):
        """Сумма весов CHAIN_WEIGHTS == 1.0."""
        self.assertAlmostEqual(sum(CHAIN_WEIGHTS.values()), 1.0, places=9)

    def test_class_attributes(self):
        """MultiChainL2Strategy.STRATEGY_ID == 'S15' и RISK_SCORE == RISK_BLENDED."""
        s = MultiChainL2Strategy()
        self.assertEqual(s.STRATEGY_ID, "S15")
        self.assertAlmostEqual(s.RISK_SCORE, RISK_BLENDED)

    def test_load_adapters_graceful_on_import_error(self):
        """_load_adapters не бросает исключений даже при ImportError адаптеров."""
        s = MultiChainL2Strategy.__new__(MultiChainL2Strategy)
        with patch.dict("sys.modules", {
            "spa_core.adapters.aave_v3_base_adapter": None,
            "spa_core.adapters.aave_v3_optimism_adapter": None,
            "spa_core.adapters.aave_arbitrum_adapter": None,
        }):
            try:
                s._adapters = {}
                s._load_adapters()
            except Exception as exc:
                self.fail(f"_load_adapters raised unexpected: {exc}")


# ─── TestGetAllocation ────────────────────────────────────────────────────────

class TestGetAllocation(unittest.TestCase):
    """15 тестов: правильные weights, перераспределение, edge cases."""

    def test_allocation_sum_equals_capital(self):
        """Сумма всех аллокаций == capital_usd."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(sum(result.values()), 100_000, places=4)

    def test_allocation_base_40_pct(self):
        """Base аллокация == 40% при всех eligible."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(result["aave_v3_base"], 40_000, places=4)

    def test_allocation_optimism_35_pct(self):
        """Optimism аллокация == 35% при всех eligible."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(result["aave_v3_optimism"], 35_000, places=4)

    def test_allocation_arbitrum_25_pct(self):
        """Arbitrum аллокация == 25% при всех eligible."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(result["aave_arbitrum"], 25_000, places=4)

    def test_allocation_zero_capital_all_zeros(self):
        """При capital_usd = 0 все аллокации == 0."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(0)
        for v in result.values():
            self.assertEqual(v, 0.0)

    def test_allocation_negative_capital_all_zeros(self):
        """При capital_usd < 0 все аллокации == 0."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(-1000)
        for v in result.values():
            self.assertEqual(v, 0.0)

    def test_allocation_base_not_eligible_redistributed(self):
        """Если Base не eligible, его 40% перераспределяется на Opt+Arb."""
        s = _make_strategy_all_mocked(base_eligible=False)
        result = s.get_allocation(100_000)
        # Base должен отсутствовать (has 0 weight after redistribution)
        self.assertNotIn("aave_v3_base", result)
        # Сумма Opt+Arb == 100_000
        self.assertAlmostEqual(sum(result.values()), 100_000, places=4)
        # Optimism и Arbitrum распределяются пропорционально (35:25)
        opt = result.get("aave_v3_optimism", 0)
        arb = result.get("aave_arbitrum", 0)
        self.assertAlmostEqual(opt / (opt + arb), 35 / 60, places=5)

    def test_allocation_two_not_eligible_all_to_remaining(self):
        """Если два адаптера не eligible, весь капитал идёт третьему."""
        s = _make_strategy_all_mocked(base_eligible=False, opt_eligible=False)
        result = s.get_allocation(100_000)
        self.assertNotIn("aave_v3_base", result)
        self.assertNotIn("aave_v3_optimism", result)
        self.assertAlmostEqual(result.get("aave_arbitrum", 0), 100_000, places=4)

    def test_allocation_no_adapters_uses_default_weights(self):
        """Без загруженных адаптеров (fallback eligible=True) — стандартные веса."""
        s = _make_strategy_no_adapters()
        result = s.get_allocation(100_000)
        # Нет адаптеров → is_eligible fallback=True → все 3 адаптера eligible
        self.assertAlmostEqual(sum(result.values()), 100_000, places=4)

    def test_allocation_very_large_capital(self):
        """При большом капитале ($1B) пропорции сохраняются."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(1_000_000_000)
        self.assertAlmostEqual(result["aave_v3_base"], 400_000_000, places=0)

    def test_allocation_all_not_eligible_returns_empty(self):
        """Если все адаптеры not eligible — возвращает пустой dict."""
        s = _make_strategy_all_mocked(
            base_eligible=False, opt_eligible=False, arb_eligible=False
        )
        result = s.get_allocation(100_000)
        self.assertEqual(result, {})

    def test_allocation_returns_dict(self):
        """get_allocation возвращает dict."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(50_000)
        self.assertIsInstance(result, dict)

    def test_allocation_keys_are_strings(self):
        """Ключи аллокации — строки."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(100_000)
        for k in result.keys():
            self.assertIsInstance(k, str)

    def test_allocation_values_are_floats(self):
        """Значения аллокации — числа."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(100_000)
        for v in result.values():
            self.assertIsInstance(v, (int, float))

    def test_allocation_small_capital(self):
        """При малом капитале ($1) сумма аллокаций == $1."""
        s = _make_strategy_all_mocked()
        result = s.get_allocation(1.0)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)


# ─── TestGetExpectedAPY ───────────────────────────────────────────────────────

class TestGetExpectedAPY(unittest.TestCase):
    """12 тестов: weighted avg, fallback, edge cases."""

    def test_apy_with_all_mocked(self):
        """get_expected_apy с дефолтными APY ≈ 4.83%."""
        s = _make_strategy_all_mocked(5.0, 4.8, 4.6)
        apy = s.get_expected_apy()
        # 0.40*5.0 + 0.35*4.8 + 0.25*4.6 = 4.83
        self.assertAlmostEqual(apy, 4.83, places=2)

    def test_apy_no_adapters_uses_fallback(self):
        """Без загруженных адаптеров get_expected_apy использует FALLBACK_APY."""
        s = _make_strategy_no_adapters()
        apy = s.get_expected_apy()
        # Fallback: 0.40*5.0 + 0.35*4.8 + 0.25*4.6 = 4.83
        self.assertAlmostEqual(apy, 4.83, places=2)

    def test_apy_is_positive(self):
        """get_expected_apy > 0 при нормальных условиях."""
        s = _make_strategy_all_mocked()
        self.assertGreater(s.get_expected_apy(), 0.0)

    def test_apy_all_not_eligible_returns_zero(self):
        """Если нет eligible адаптеров — get_expected_apy == 0.0."""
        s = _make_strategy_all_mocked(
            base_eligible=False, opt_eligible=False, arb_eligible=False
        )
        self.assertEqual(s.get_expected_apy(), 0.0)

    def test_apy_one_ineligible_redistributes_weight(self):
        """Если Base не eligible — APY считается только по Opt+Arb."""
        s = _make_strategy_all_mocked(
            base_apy=5.0, opt_apy=4.8, arb_apy=4.6,
            base_eligible=False
        )
        apy = s.get_expected_apy()
        # eligible: opt=35/(35+25)=0.583, arb=25/(35+25)=0.417
        expected = (35/60)*4.8 + (25/60)*4.6
        self.assertAlmostEqual(apy, expected, places=3)

    def test_apy_returns_float(self):
        """get_expected_apy возвращает float."""
        s = _make_strategy_all_mocked()
        self.assertIsInstance(s.get_expected_apy(), float)

    def test_apy_higher_when_all_high(self):
        """При высоких APY адаптеров — get_expected_apy тоже выше."""
        s_low = _make_strategy_all_mocked(2.0, 2.0, 2.0)
        s_high = _make_strategy_all_mocked(10.0, 10.0, 10.0)
        self.assertGreater(s_high.get_expected_apy(), s_low.get_expected_apy())

    def test_apy_fallback_values_match_constants(self):
        """FALLBACK_APY значения корректны для L2 адаптеров."""
        self.assertAlmostEqual(FALLBACK_APY["aave_v3_base"], 5.0)
        self.assertAlmostEqual(FALLBACK_APY["aave_v3_optimism"], 4.8)
        self.assertAlmostEqual(FALLBACK_APY["aave_arbitrum"], 4.6)

    def test_apy_adapter_returns_zero_uses_fallback(self):
        """Если адаптер get_apy() возвращает 0 — используется FALLBACK_APY."""
        s = _make_strategy_all_mocked(0.0, 4.8, 4.6)
        apy = s.get_expected_apy()
        # base get_apy=0 → fallback 5.0
        # expected: 0.40*5.0 + 0.35*4.8 + 0.25*4.6 = 4.83
        self.assertAlmostEqual(apy, 4.83, places=2)

    def test_apy_when_adapter_raises_exception(self):
        """Если get_apy() адаптера бросает исключение — используется fallback."""
        s = MultiChainL2Strategy.__new__(MultiChainL2Strategy)
        mock = MagicMock()
        mock.get_apy.side_effect = RuntimeError("network error")
        mock.is_eligible.return_value = True
        s._adapters = {
            "aave_v3_base":     mock,
            "aave_v3_optimism": _make_mock_adapter(4.8),
            "aave_arbitrum":    _make_mock_adapter(4.6),
        }
        apy = s.get_expected_apy()
        # base → fallback 5.0
        expected = 0.40*5.0 + 0.35*4.8 + 0.25*4.6
        self.assertAlmostEqual(apy, expected, places=2)

    def test_apy_two_only_eligible_correct_weights(self):
        """При двух eligible адаптерах веса нормализуются корректно."""
        s = _make_strategy_all_mocked(
            base_apy=5.0, opt_apy=4.8, arb_apy=4.6,
            base_eligible=False, opt_eligible=False
        )
        apy = s.get_expected_apy()
        # Только arb eligible → APY == arb APY
        self.assertAlmostEqual(apy, 4.6, places=3)

    def test_apy_weighted_apy_expected_constant(self):
        """WEIGHTED_APY_EXPECTED ≈ 4.83 (расчёт по дефолтным значениям)."""
        self.assertAlmostEqual(WEIGHTED_APY_EXPECTED, 4.83, places=2)


# ─── TestGetHealth ────────────────────────────────────────────────────────────

class TestGetHealth(unittest.TestCase):
    """12 тестов: all_eligible, chain_breakdown, overall_status."""

    def test_health_returns_dict(self):
        """get_health() возвращает dict."""
        s = _make_strategy_all_mocked()
        self.assertIsInstance(s.get_health(), dict)

    def test_health_required_keys(self):
        """get_health() содержит все обязательные ключи."""
        s = _make_strategy_all_mocked()
        h = s.get_health()
        for key in ("strategy_id", "name", "target_apy", "expected_apy",
                    "risk_score", "chain_breakdown", "all_eligible", "overall_status"):
            self.assertIn(key, h, f"Missing key: {key}")

    def test_health_strategy_id(self):
        """get_health strategy_id == 'S15'."""
        s = _make_strategy_all_mocked()
        self.assertEqual(s.get_health()["strategy_id"], "S15")

    def test_health_all_eligible_true(self):
        """Если все адаптеры eligible — all_eligible=True."""
        s = _make_strategy_all_mocked()
        self.assertTrue(s.get_health()["all_eligible"])

    def test_health_all_eligible_false_when_one_not(self):
        """Если хоть один адаптер не eligible — all_eligible=False."""
        s = _make_strategy_all_mocked(base_eligible=False)
        self.assertFalse(s.get_health()["all_eligible"])

    def test_health_chain_breakdown_structure(self):
        """chain_breakdown содержит 3 ключа с полями weight/apy/eligible."""
        s = _make_strategy_all_mocked()
        breakdown = s.get_health()["chain_breakdown"]
        self.assertEqual(len(breakdown), 3)
        for key in ("aave_v3_base", "aave_v3_optimism", "aave_arbitrum"):
            self.assertIn(key, breakdown)
            entry = breakdown[key]
            for field in ("weight", "apy", "eligible"):
                self.assertIn(field, entry)

    def test_health_chain_breakdown_weights(self):
        """chain_breakdown веса соответствуют CHAIN_WEIGHTS."""
        s = _make_strategy_all_mocked()
        breakdown = s.get_health()["chain_breakdown"]
        for key, w in CHAIN_WEIGHTS.items():
            self.assertAlmostEqual(breakdown[key]["weight"], w)

    def test_health_overall_status_ok_when_all_eligible(self):
        """overall_status == 'ok' при всех eligible и APY выше TARGET_APY_MIN."""
        s = _make_strategy_all_mocked(5.0, 4.8, 4.6)
        h = s.get_health()
        # expected_apy 4.83 >= TARGET_APY_MIN 4.0 и all_eligible=True
        self.assertEqual(h["overall_status"], "ok")

    def test_health_overall_status_degraded_when_no_eligible(self):
        """overall_status == 'degraded' если нет eligible адаптеров."""
        s = _make_strategy_all_mocked(
            base_eligible=False, opt_eligible=False, arb_eligible=False
        )
        h = s.get_health()
        self.assertEqual(h["overall_status"], "degraded")

    def test_health_expected_apy_is_float(self):
        """expected_apy в get_health() — float."""
        s = _make_strategy_all_mocked()
        self.assertIsInstance(s.get_health()["expected_apy"], float)

    def test_health_risk_score_match(self):
        """risk_score в get_health() == RISK_BLENDED."""
        s = _make_strategy_all_mocked()
        self.assertAlmostEqual(s.get_health()["risk_score"], RISK_BLENDED)

    def test_health_target_apy_match(self):
        """target_apy в get_health() == TARGET_APY_PCT."""
        s = _make_strategy_all_mocked()
        self.assertAlmostEqual(s.get_health()["target_apy"], TARGET_APY_PCT)


# ─── TestGetGasSavings ────────────────────────────────────────────────────────

class TestGetGasSavings(unittest.TestCase):
    """10 тестов: avg_savings_pct, shape, chains detail."""

    def test_gas_savings_returns_dict(self):
        """get_gas_savings_summary() возвращает dict."""
        s = _make_strategy_all_mocked()
        self.assertIsInstance(s.get_gas_savings_summary(), dict)

    def test_gas_savings_avg_pct_positive(self):
        """avg_savings_pct > 0."""
        s = _make_strategy_all_mocked()
        result = s.get_gas_savings_summary()
        self.assertGreater(result["avg_savings_pct"], 0.0)

    def test_gas_savings_avg_pct_value(self):
        """avg_savings_pct ≈ 93.33% (weighted avg: 0.40*95 + 0.35*95 + 0.25*90)."""
        s = _make_strategy_all_mocked()
        result = s.get_gas_savings_summary()
        expected = 0.40 * 95.0 + 0.35 * 95.0 + 0.25 * 90.0
        self.assertAlmostEqual(result["avg_savings_pct"], expected, places=1)

    def test_gas_savings_required_keys(self):
        """get_gas_savings_summary содержит avg_savings_pct, total_estimated_gas_usd_per_tx, chains."""
        s = _make_strategy_all_mocked()
        result = s.get_gas_savings_summary()
        for key in ("avg_savings_pct", "total_estimated_gas_usd_per_tx", "chains"):
            self.assertIn(key, result)

    def test_gas_savings_chains_has_three_entries(self):
        """chains содержит 3 записи."""
        s = _make_strategy_all_mocked()
        result = s.get_gas_savings_summary()
        self.assertEqual(len(result["chains"]), 3)

    def test_gas_savings_chain_has_savings_pct(self):
        """Каждая цепочка в chains содержит savings_pct."""
        s = _make_strategy_all_mocked()
        for chain_data in s.get_gas_savings_summary()["chains"].values():
            self.assertIn("savings_pct", chain_data)

    def test_gas_savings_base_savings_95(self):
        """Base chain savings_pct == 95.0."""
        s = _make_strategy_all_mocked()
        self.assertAlmostEqual(
            s.get_gas_savings_summary()["chains"]["aave_v3_base"]["savings_pct"],
            95.0
        )

    def test_gas_savings_arbitrum_savings_90(self):
        """Arbitrum savings_pct == 90.0."""
        s = _make_strategy_all_mocked()
        self.assertAlmostEqual(
            s.get_gas_savings_summary()["chains"]["aave_arbitrum"]["savings_pct"],
            90.0
        )

    def test_gas_savings_total_gas_usd_positive(self):
        """total_estimated_gas_usd_per_tx > 0."""
        s = _make_strategy_all_mocked()
        result = s.get_gas_savings_summary()
        self.assertGreater(result["total_estimated_gas_usd_per_tx"], 0.0)

    def test_gas_savings_no_adapters_still_returns_data(self):
        """Без адаптеров get_gas_savings_summary всё равно возвращает данные."""
        s = _make_strategy_no_adapters()
        result = s.get_gas_savings_summary()
        self.assertIsInstance(result, dict)
        self.assertIn("avg_savings_pct", result)
        self.assertGreater(result["avg_savings_pct"], 0.0)


# ─── TestSimulate ─────────────────────────────────────────────────────────────

class TestSimulate(unittest.TestCase):
    """12 тестов: simulate() корректно распределяет капитал и считает yield."""

    def test_simulate_returns_dict(self):
        """simulate() возвращает dict."""
        s = _make_strategy_all_mocked()
        self.assertIsInstance(s.simulate(100_000), dict)

    def test_simulate_required_keys(self):
        """simulate() содержит total_capital, allocation, expected_annual_yield_usd,
        expected_apy_pct, status, chain_results."""
        s = _make_strategy_all_mocked()
        result = s.simulate(100_000)
        for key in ("total_capital", "allocation", "expected_annual_yield_usd",
                    "expected_apy_pct", "status", "chain_results"):
            self.assertIn(key, result)

    def test_simulate_allocation_sums_to_capital(self):
        """Сумма allocation == total_capital."""
        s = _make_strategy_all_mocked()
        result = s.simulate(100_000)
        alloc_sum = sum(result["allocation"].values())
        self.assertAlmostEqual(alloc_sum, 100_000, places=4)

    def test_simulate_expected_annual_yield_positive(self):
        """expected_annual_yield_usd > 0 при capital > 0."""
        s = _make_strategy_all_mocked()
        result = s.simulate(100_000)
        self.assertGreater(result["expected_annual_yield_usd"], 0.0)

    def test_simulate_expected_apy_pct_positive(self):
        """expected_apy_pct > 0."""
        s = _make_strategy_all_mocked()
        result = s.simulate(100_000)
        self.assertGreater(result["expected_apy_pct"], 0.0)

    def test_simulate_yield_matches_expected(self):
        """expected_annual_yield_usd ≈ capital * expected_apy_pct / 100."""
        s = _make_strategy_all_mocked(5.0, 4.8, 4.6)
        capital = 100_000
        result = s.simulate(capital)
        apy = s.get_expected_apy()
        expected_yield = capital * (apy / 100.0)
        self.assertAlmostEqual(
            result["expected_annual_yield_usd"], expected_yield, delta=1.0
        )

    def test_simulate_status_ok(self):
        """status == 'ok' при нормальных условиях."""
        s = _make_strategy_all_mocked()
        self.assertEqual(s.simulate(100_000)["status"], "ok")

    def test_simulate_no_eligible_adapters(self):
        """Если нет eligible — status == 'no_eligible_adapters', yield == 0."""
        s = _make_strategy_all_mocked(
            base_eligible=False, opt_eligible=False, arb_eligible=False
        )
        result = s.simulate(100_000)
        self.assertEqual(result["status"], "no_eligible_adapters")
        self.assertEqual(result["expected_annual_yield_usd"], 0.0)

    def test_simulate_chain_results_keys(self):
        """chain_results содержит записи для eligible адаптеров."""
        s = _make_strategy_all_mocked()
        result = s.simulate(100_000)
        self.assertIsInstance(result["chain_results"], dict)
        for key in ("aave_v3_base", "aave_v3_optimism", "aave_arbitrum"):
            self.assertIn(key, result["chain_results"])

    def test_simulate_chain_result_has_annual_yield(self):
        """Каждая запись chain_results содержит annual_yield_usd."""
        s = _make_strategy_all_mocked()
        result = s.simulate(100_000)
        for entry in result["chain_results"].values():
            self.assertIn("annual_yield_usd", entry)
            self.assertGreaterEqual(entry["annual_yield_usd"], 0.0)

    def test_simulate_zero_capital(self):
        """simulate(0) возвращает allocation с нулями."""
        s = _make_strategy_all_mocked()
        result = s.simulate(0)
        alloc_sum = sum(result["allocation"].values())
        self.assertEqual(alloc_sum, 0.0)

    def test_simulate_large_capital(self):
        """simulate($1M) — сумма аллокации == $1M."""
        s = _make_strategy_all_mocked()
        result = s.simulate(1_000_000)
        self.assertAlmostEqual(sum(result["allocation"].values()), 1_000_000, places=2)


# ─── TestToDict ───────────────────────────────────────────────────────────────

class TestToDict(unittest.TestCase):
    """9 тестов: to_dict() содержит все поля и JSON-сериализуемо."""

    def test_to_dict_returns_dict(self):
        """to_dict() возвращает dict."""
        s = _make_strategy_all_mocked()
        self.assertIsInstance(s.to_dict(), dict)

    def test_to_dict_required_keys(self):
        """to_dict() содержит все обязательные ключи."""
        s = _make_strategy_all_mocked()
        d = s.to_dict()
        for key in ("strategy_id", "strategy_name", "tier", "description",
                    "target_apy_pct", "expected_apy_pct", "risk_score",
                    "chain_weights", "all_eligible", "overall_status",
                    "gas_savings", "adapters_loaded", "timestamp"):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_json_serializable(self):
        """to_dict() полностью JSON-сериализуемо."""
        s = _make_strategy_all_mocked()
        try:
            json.dumps(s.to_dict())
        except (TypeError, ValueError) as exc:
            self.fail(f"to_dict() not JSON serializable: {exc}")

    def test_to_dict_strategy_id_s15(self):
        """to_dict strategy_id == 'S15'."""
        s = _make_strategy_all_mocked()
        self.assertEqual(s.to_dict()["strategy_id"], "S15")

    def test_to_dict_target_apy_pct(self):
        """to_dict target_apy_pct == TARGET_APY_PCT == 5.5."""
        s = _make_strategy_all_mocked()
        self.assertAlmostEqual(s.to_dict()["target_apy_pct"], TARGET_APY_PCT)

    def test_to_dict_chain_weights_correct(self):
        """to_dict chain_weights совпадает с CHAIN_WEIGHTS."""
        s = _make_strategy_all_mocked()
        d = s.to_dict()
        for key, w in CHAIN_WEIGHTS.items():
            self.assertAlmostEqual(d["chain_weights"][key], w)

    def test_to_dict_timestamp_is_iso(self):
        """timestamp содержит 'T' (ISO формат)."""
        s = _make_strategy_all_mocked()
        ts = s.to_dict()["timestamp"]
        self.assertIn("T", ts)

    def test_to_dict_adapters_loaded_list(self):
        """adapters_loaded — список строк."""
        s = _make_strategy_all_mocked()
        loaded = s.to_dict()["adapters_loaded"]
        self.assertIsInstance(loaded, list)
        for item in loaded:
            self.assertIsInstance(item, str)

    def test_to_dict_no_adapters_still_works(self):
        """to_dict() без загруженных адаптеров не бросает исключений."""
        s = _make_strategy_no_adapters()
        try:
            d = s.to_dict()
            json.dumps(d)
        except Exception as exc:
            self.fail(f"to_dict() with no adapters raised: {exc}")


# ─── TestModuleConstants ──────────────────────────────────────────────────────

class TestModuleConstants(unittest.TestCase):
    """5 дополнительных тестов на модульные константы."""

    def test_fallback_apy_keys(self):
        """FALLBACK_APY содержит все 3 ключа."""
        for key in ("aave_v3_base", "aave_v3_optimism", "aave_arbitrum"):
            self.assertIn(key, FALLBACK_APY)

    def test_risk_scores_keys(self):
        """RISK_SCORES содержит все 3 ключа."""
        for key in ("aave_v3_base", "aave_v3_optimism", "aave_arbitrum"):
            self.assertIn(key, RISK_SCORES)

    def test_gas_info_keys(self):
        """GAS_INFO содержит все 3 ключа."""
        for key in ("aave_v3_base", "aave_v3_optimism", "aave_arbitrum"):
            self.assertIn(key, GAS_INFO)

    def test_target_apy_range_valid(self):
        """TARGET_APY_MIN < TARGET_APY_PCT < TARGET_APY_MAX."""
        self.assertLess(TARGET_APY_MIN, TARGET_APY_PCT)
        self.assertLess(TARGET_APY_PCT, TARGET_APY_MAX)

    def test_register_no_error(self):
        """_register() не бросает исключений."""
        try:
            _register()
        except Exception as exc:
            self.fail(f"_register() raised: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
