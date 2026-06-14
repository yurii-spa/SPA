#!/usr/bin/env python3
"""Тесты WusdmAdapter — MP-559.

Покрываем:
  TestWusdmInit        (12) — константы: protocol, tier=T2, chain_id, vault, risk_score, caps, apy, tvl
  TestWusdmAPY         (12) — get_apy, fallback, json override, get_apy_pct, health_check
  TestWusdmPeg         (13) — is_peg_healthy: missing→True, 1.0→True, в пределах, граница, депег, нечисловое
  TestWusdmEligibility (11) — eligible = peg OK + APY OK; все комбинации
  TestWusdmYieldInfo   ( 8) — get_yield_info: apy десятичной дробью, tier, risk_score, exit_latency
  TestWusdmVsMorpho    (10) — vs_morpho_gap: положительный/отрицательный/кастомный
  TestWusdmAllocate    (10) — нулевой, negative → ValueError, нормальный, структура ответа
  TestWusdmWithdraw    (10) — нулевой, negative → ValueError, normal, insufficient
  TestWusdmToDict      ( 9) — все ключи: peg_healthy, eligible, protocol, tier=T2
  TestWusdmRegistry    ( 5) — импорт, ADAPTER_REGISTRY, __all__

Итого: 100 тестов.

Запуск:
    python3 -m pytest spa_core/tests/test_wusdm_adapter.py -q
    python3 -m unittest spa_core.tests.test_wusdm_adapter -v
    python3 spa_core/tests/test_wusdm_adapter.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Добавляем корень репо в sys.path для прямого запуска файла
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapters.base_adapter import BaseAdapter, YieldInfo
from spa_core.adapters.wusdm_adapter import WusdmAdapter


# ── вспомогательные фабрики ──────────────────────────────────────────────────

def _make_adapter(
    apy: float | None = 5.0,
    usdm_price: float | None = None,
    missing_section: bool = False,
    missing_file: bool = False,
) -> WusdmAdapter:
    """Создаёт адаптер с временным data_dir.

    apy=None         → поле wusdm.apy отсутствует (тест fallback)
    usdm_price=None  → поле usdm_price отсутствует (peg считается healthy)
    missing_section  → секция wusdm полностью отсутствует
    missing_file     → adapter_status.json не существует
    """
    if missing_file:
        return WusdmAdapter(data_dir="/nonexistent_spa_test_wusdm_xyz")

    tmp = tempfile.mkdtemp()
    if missing_section:
        content: dict = {}
    else:
        section: dict = {}
        if apy is not None:
            section["apy"] = apy
        if usdm_price is not None:
            section["usdm_price"] = usdm_price
        content = {"wusdm": section}

    (Path(tmp) / "adapter_status.json").write_text(
        json.dumps(content), encoding="utf-8"
    )
    return WusdmAdapter(data_dir=tmp)


def _default() -> WusdmAdapter:
    """Адаптер с apy=5.0, без usdm_price (peg healthy, eligible)."""
    return _make_adapter(apy=5.0)


def _no_file() -> WusdmAdapter:
    """Адаптер с несуществующим data_dir → fallback, peg healthy."""
    return _make_adapter(missing_file=True)


# ════════════════════════════════════════════════════════════════════════════
# 1. TestWusdmInit — константы и идентичность
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmInit(unittest.TestCase):
    """12 тестов: все ключевые константы класса."""

    def test_protocol_key(self):
        self.assertEqual(WusdmAdapter.PROTOCOL, "wusdm")

    def test_protocol_name(self):
        self.assertEqual(
            WusdmAdapter.PROTOCOL_NAME,
            "Mountain Protocol Wrapped USDM (wUSDM)",
        )

    def test_tier(self):
        self.assertEqual(WusdmAdapter.TIER, "T2")

    def test_chain_id(self):
        self.assertEqual(WusdmAdapter.CHAIN_ID, 1)

    def test_chain(self):
        self.assertEqual(WusdmAdapter.CHAIN, "ethereum")

    def test_vault_address(self):
        self.assertEqual(
            WusdmAdapter.VAULT_ADDRESS,
            "0x57F5E098CaD7A3D1Eed53991D4d66C45C9Af7812",
        )

    def test_risk_score(self):
        self.assertAlmostEqual(WusdmAdapter.RISK_SCORE, 0.45)

    def test_t2_cap(self):
        self.assertAlmostEqual(WusdmAdapter.T2_CAP, 0.20)

    def test_exit_latency_instant(self):
        self.assertEqual(WusdmAdapter.EXIT_LATENCY_HOURS, 0.0)

    def test_apy_bounds(self):
        self.assertAlmostEqual(WusdmAdapter.MIN_APY_PCT, 3.0)
        self.assertAlmostEqual(WusdmAdapter.MAX_APY_PCT, 10.0)
        self.assertAlmostEqual(WusdmAdapter.DEFAULT_APY_PCT, 5.0)

    def test_tvl(self):
        self.assertAlmostEqual(WusdmAdapter.TVL_USD, 200_000_000)

    def test_inherits_base_adapter(self):
        adapter = _default()
        self.assertIsInstance(adapter, BaseAdapter)


# ════════════════════════════════════════════════════════════════════════════
# 2. TestWusdmAPY — чтение APY и health_check
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmAPY(unittest.TestCase):
    """12 тестов: get_apy, fallback, JSON override, get_apy_pct, health_check."""

    def test_default_apy_from_json(self):
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.get_apy(), 5.0)

    def test_apy_override_higher(self):
        a = _make_adapter(apy=7.5)
        self.assertAlmostEqual(a.get_apy(), 7.5)

    def test_apy_override_lower(self):
        a = _make_adapter(apy=4.2)
        self.assertAlmostEqual(a.get_apy(), 4.2)

    def test_apy_fallback_missing_field(self):
        # apy=None → поле отсутствует → fallback 5.0
        a = _make_adapter(apy=None)
        self.assertAlmostEqual(a.get_apy(), WusdmAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_missing_section(self):
        a = _make_adapter(missing_section=True)
        self.assertAlmostEqual(a.get_apy(), WusdmAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_no_file(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy(), WusdmAdapter.DEFAULT_APY_PCT)

    def test_get_apy_pct_equals_get_apy(self):
        a = _make_adapter(apy=6.1)
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_get_apy_pct_fallback(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy_pct(), WusdmAdapter.DEFAULT_APY_PCT)

    def test_health_check_ok_in_range(self):
        a = _make_adapter(apy=5.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_ok_at_min_boundary(self):
        a = _make_adapter(apy=3.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_ok_at_max_boundary(self):
        a = _make_adapter(apy=10.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_degraded_below_min(self):
        a = _make_adapter(apy=1.0)
        self.assertEqual(a.health_check(), "degraded")


# ════════════════════════════════════════════════════════════════════════════
# 3. TestWusdmPeg — peg compliance gate
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmPeg(unittest.TestCase):
    """13 тестов: is_peg_healthy при различных значениях usdm_price."""

    def test_peg_missing_field_healthy(self):
        """Поле usdm_price отсутствует → healthy (нет данных != депег)."""
        a = _make_adapter(usdm_price=None)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_missing_section_healthy(self):
        a = _make_adapter(missing_section=True)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_no_file_healthy(self):
        a = _no_file()
        self.assertTrue(a.is_peg_healthy())

    def test_peg_exactly_one_healthy(self):
        a = _make_adapter(usdm_price=1.0)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_within_tolerance_above(self):
        """1.004 в пределах 0.005 → healthy."""
        a = _make_adapter(usdm_price=1.004)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_within_tolerance_below(self):
        """0.996 в пределах 0.005 → healthy."""
        a = _make_adapter(usdm_price=0.996)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_boundary_above(self):
        """Ровно +0.005 → граница, healthy (<=)."""
        a = _make_adapter(usdm_price=1.005)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_boundary_below(self):
        """Ровно -0.005 → граница, healthy (<=)."""
        a = _make_adapter(usdm_price=0.995)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_depeg_above(self):
        """1.02 за пределами 0.005 → not healthy."""
        a = _make_adapter(usdm_price=1.02)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_depeg_below(self):
        """0.97 (депег вниз) → not healthy."""
        a = _make_adapter(usdm_price=0.97)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_just_over_boundary(self):
        """1.0051 чуть за границей → not healthy."""
        a = _make_adapter(usdm_price=1.0051)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_nonnumeric_safe_healthy(self):
        """Нечисловое значение usdm_price → safe healthy."""
        a = _make_adapter(apy=5.0, usdm_price="bad")
        self.assertTrue(a.is_peg_healthy())

    def test_peg_returns_bool(self):
        a = _make_adapter(usdm_price=1.0)
        self.assertIsInstance(a.is_peg_healthy(), bool)


# ════════════════════════════════════════════════════════════════════════════
# 4. TestWusdmEligibility — is_eligible (peg OK + APY OK)
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmEligibility(unittest.TestCase):
    """11 тестов: is_eligible — все комбинации peg и APY."""

    def test_eligible_peg_ok_apy_ok(self):
        """peg healthy (no field), APY=5.0 → eligible."""
        a = _make_adapter(apy=5.0)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_depeg(self):
        """Депег, APY OK → not eligible."""
        a = _make_adapter(apy=5.0, usdm_price=0.95)
        self.assertFalse(a.is_eligible())

    def test_not_eligible_peg_ok_apy_too_low(self):
        """peg OK, APY=1.0 (below MIN) → not eligible."""
        a = _make_adapter(apy=1.0)
        self.assertFalse(a.is_eligible())

    def test_not_eligible_peg_ok_apy_too_high(self):
        """peg OK, APY=20.0 (above MAX) → not eligible."""
        a = _make_adapter(apy=20.0)
        self.assertFalse(a.is_eligible())

    def test_eligible_at_min_apy(self):
        """peg OK, APY=3.0 (MIN boundary) → eligible."""
        a = _make_adapter(apy=3.0)
        self.assertTrue(a.is_eligible())

    def test_eligible_at_max_apy(self):
        """peg OK, APY=10.0 (MAX boundary) → eligible."""
        a = _make_adapter(apy=10.0)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_both_fail(self):
        """Депег + APY=1.0 → not eligible."""
        a = _make_adapter(apy=1.0, usdm_price=0.90)
        self.assertFalse(a.is_eligible())

    def test_eligible_no_file(self):
        """Нет файла → peg healthy (default), APY=fallback 5.0 → eligible."""
        a = _no_file()
        self.assertTrue(a.is_eligible())

    def test_eligible_returns_bool(self):
        a = _make_adapter(apy=5.0)
        self.assertIsInstance(a.is_eligible(), bool)

    def test_not_eligible_depeg_just_over(self):
        """usdm_price=1.0051 (чуть за порогом), APY OK → not eligible."""
        a = _make_adapter(apy=5.0, usdm_price=1.0051)
        self.assertFalse(a.is_eligible())

    def test_eligible_peg_at_boundary(self):
        """usdm_price=0.995 (граница peg), APY OK → eligible."""
        a = _make_adapter(apy=5.0, usdm_price=0.995)
        self.assertTrue(a.is_eligible())


# ════════════════════════════════════════════════════════════════════════════
# 5. TestWusdmYieldInfo — get_yield_info
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmYieldInfo(unittest.TestCase):
    """8 тестов: get_yield_info — apy десятичной дробью, поля."""

    def test_yield_info_type(self):
        a = _default()
        self.assertIsInstance(a.get_yield_info(), YieldInfo)

    def test_yield_info_apy_decimal(self):
        """APY=5.0% → 0.05 в YieldInfo (десятичная дробь)."""
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.get_yield_info().apy, 0.05)

    def test_yield_info_apy_decimal_override(self):
        a = _make_adapter(apy=9.0)
        self.assertAlmostEqual(a.get_yield_info().apy, 0.09)

    def test_yield_info_protocol(self):
        a = _default()
        self.assertEqual(a.get_yield_info().protocol, "wusdm")

    def test_yield_info_tier(self):
        a = _default()
        self.assertEqual(a.get_yield_info().tier, "T2")

    def test_yield_info_risk_score(self):
        a = _default()
        self.assertAlmostEqual(a.get_yield_info().risk_score, 0.45)

    def test_yield_info_exit_latency(self):
        a = _default()
        self.assertEqual(a.get_yield_info().exit_latency_hours, 0.0)

    def test_yield_info_tvl(self):
        a = _default()
        self.assertAlmostEqual(a.get_yield_info().tvl_usd, 200_000_000)


# ════════════════════════════════════════════════════════════════════════════
# 6. TestWusdmVsMorpho — vs_morpho_gap
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmVsMorpho(unittest.TestCase):
    """10 тестов: vs_morpho_gap (положительный/отрицательный/кастомный)."""

    def test_default_gap_positive(self):
        """Morpho 6.5% vs wUSDM 5.0% → gap = +1.5 (Morpho лучше)."""
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 1.5)

    def test_gap_negative_wusdm_better(self):
        """Morpho 6.5% vs wUSDM 7.0% → gap = -0.5 (wUSDM лучше)."""
        a = _make_adapter(apy=7.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), -0.5)

    def test_gap_zero_equal(self):
        """Morpho 6.5% vs wUSDM 6.5% → gap = 0.0."""
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.0)

    def test_custom_morpho_apy_higher(self):
        """Кастомный morpho_apy=8.0 vs wUSDM 5.0% → gap = 3.0."""
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=8.0), 3.0)

    def test_custom_morpho_apy_lower(self):
        """Кастомный morpho_apy=4.0 vs wUSDM 5.0% → gap = -1.0."""
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=4.0), -1.0)

    def test_gap_with_fallback_apy(self):
        """Fallback APY=5.0 → gap = 6.5 - 5.0 = 1.5."""
        a = _no_file()
        self.assertAlmostEqual(a.vs_morpho_gap(), 1.5)

    def test_gap_returns_float(self):
        a = _default()
        self.assertIsInstance(a.vs_morpho_gap(), float)

    def test_gap_symmetry(self):
        """gap(morpho=6.5) симметричен относительно 6.5."""
        a1 = _make_adapter(apy=7.5)
        a2 = _make_adapter(apy=5.5)
        # gap1 = 6.5 - 7.5 = -1.0; gap2 = 6.5 - 5.5 = +1.0
        self.assertAlmostEqual(a1.vs_morpho_gap() + a2.vs_morpho_gap(), 0.0)

    def test_gap_large_positive(self):
        """Morpho 20% vs wUSDM 5.0% → gap = 15.0."""
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=20.0), 15.0)

    def test_gap_default_parameter_is_6_5(self):
        """Дефолтный morpho_apy должен быть 6.5."""
        a = _make_adapter(apy=0.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 6.5)


# ════════════════════════════════════════════════════════════════════════════
# 7. TestWusdmAllocate — paper trading аллокация
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmAllocate(unittest.TestCase):
    """10 тестов: нулевой, negative → ValueError, нормальный, структура ответа."""

    def test_allocate_negative_raises(self):
        a = _default()
        with self.assertRaises(ValueError):
            a.allocate(-1000.0)

    def test_allocate_zero_raises(self):
        a = _default()
        with self.assertRaises(ValueError):
            a.allocate(0.0)

    def test_allocate_normal_returns_ok(self):
        a = _default()
        result = a.allocate(10000.0)
        self.assertEqual(result["status"], "ok")

    def test_allocate_updates_allocated(self):
        a = _default()
        a.allocate(10000.0)
        self.assertAlmostEqual(a._allocated, 10000.0)

    def test_allocate_cumulative(self):
        a = _default()
        a.allocate(10000.0)
        a.allocate(5000.0)
        self.assertAlmostEqual(a._allocated, 15000.0)

    def test_allocate_result_has_protocol(self):
        a = _default()
        result = a.allocate(1000.0)
        self.assertEqual(result["protocol"], "wusdm")

    def test_allocate_result_has_vault(self):
        a = _default()
        result = a.allocate(1000.0)
        self.assertEqual(
            result["vault"],
            "0x57F5E098CaD7A3D1Eed53991D4d66C45C9Af7812",
        )

    def test_allocate_result_has_amount(self):
        a = _default()
        result = a.allocate(7500.0)
        self.assertAlmostEqual(result["amount"], 7500.0)

    def test_allocate_result_has_allocated_total(self):
        a = _default()
        result = a.allocate(5000.0)
        self.assertAlmostEqual(result["allocated_total"], 5000.0)

    def test_allocate_result_has_apy_pct(self):
        a = _default()
        result = a.allocate(1000.0)
        self.assertIn("apy_pct", result)
        self.assertIsInstance(result["apy_pct"], float)


# ════════════════════════════════════════════════════════════════════════════
# 8. TestWusdmWithdraw — paper trading вывод
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmWithdraw(unittest.TestCase):
    """10 тестов: нулевой, negative → ValueError, normal, insufficient."""

    def test_withdraw_negative_raises(self):
        a = _default()
        a.allocate(10000.0)
        with self.assertRaises(ValueError):
            a.withdraw(-500.0)

    def test_withdraw_zero_raises(self):
        a = _default()
        a.allocate(10000.0)
        with self.assertRaises(ValueError):
            a.withdraw(0.0)

    def test_withdraw_normal_returns_ok(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(5000.0)
        self.assertEqual(result["status"], "ok")

    def test_withdraw_updates_allocated(self):
        a = _default()
        a.allocate(10000.0)
        a.withdraw(3000.0)
        self.assertAlmostEqual(a._allocated, 7000.0)

    def test_withdraw_insufficient_returns_error(self):
        a = _default()
        a.allocate(1000.0)
        result = a.withdraw(9999.0)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "insufficient_balance")

    def test_withdraw_result_has_protocol(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(1000.0)
        self.assertEqual(result["protocol"], "wusdm")

    def test_withdraw_result_has_vault(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(1000.0)
        self.assertEqual(
            result["vault"],
            "0x57F5E098CaD7A3D1Eed53991D4d66C45C9Af7812",
        )

    def test_withdraw_result_has_amount(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(4000.0)
        self.assertAlmostEqual(result["amount"], 4000.0)

    def test_withdraw_result_has_allocated_remaining(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(4000.0)
        self.assertAlmostEqual(result["allocated_remaining"], 6000.0)

    def test_withdraw_exact_full_amount(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(10000.0)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(a._allocated, 0.0)


# ════════════════════════════════════════════════════════════════════════════
# 9. TestWusdmToDict — сериализация
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmToDict(unittest.TestCase):
    """9 тестов: все ключевые поля to_dict(), peg_healthy, eligible, protocol, tier=T2."""

    def test_to_dict_has_protocol(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(d["protocol"], "wusdm")

    def test_to_dict_has_tier_t2(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(d["tier"], "T2")

    def test_to_dict_has_t2_cap(self):
        a = _default()
        d = a.to_dict()
        self.assertIn("t2_cap", d)
        self.assertAlmostEqual(d["t2_cap"], 0.20)

    def test_to_dict_has_peg_healthy_true(self):
        """Нет депега → peg_healthy=True в to_dict."""
        a = _make_adapter(apy=5.0)
        d = a.to_dict()
        self.assertIn("peg_healthy", d)
        self.assertTrue(d["peg_healthy"])

    def test_to_dict_has_peg_healthy_false(self):
        """Депег → peg_healthy=False в to_dict."""
        a = _make_adapter(apy=5.0, usdm_price=0.95)
        d = a.to_dict()
        self.assertFalse(d["peg_healthy"])

    def test_to_dict_has_eligible_true(self):
        """peg OK, APY=5.0 → eligible=True."""
        a = _default()
        d = a.to_dict()
        self.assertIn("eligible", d)
        self.assertTrue(d["eligible"])

    def test_to_dict_has_eligible_false(self):
        """Депег → eligible=False."""
        a = _make_adapter(apy=5.0, usdm_price=0.90)
        d = a.to_dict()
        self.assertFalse(d["eligible"])

    def test_to_dict_all_required_keys_present(self):
        required = {
            "protocol", "protocol_name", "vault_address", "tier", "t2_cap",
            "chain", "chain_id", "asset", "apy_pct", "risk_score",
            "exit_latency_hours", "tvl_usd", "min_apy_pct", "max_apy_pct",
            "peg_healthy", "eligible", "allocated",
        }
        a = _default()
        d = a.to_dict()
        for key in required:
            self.assertIn(key, d, f"Missing key in to_dict(): {key!r}")

    def test_to_dict_vault_address_correct(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(
            d["vault_address"],
            "0x57F5E098CaD7A3D1Eed53991D4d66C45C9Af7812",
        )


# ════════════════════════════════════════════════════════════════════════════
# 10. TestWusdmRegistry — регистрация в пакете adapters
# ════════════════════════════════════════════════════════════════════════════

class TestWusdmRegistry(unittest.TestCase):
    """5 тестов: импорт, ADAPTER_REGISTRY, __all__."""

    def test_import_from_package(self):
        from spa_core.adapters import WusdmAdapter as Imported
        self.assertIs(Imported, WusdmAdapter)

    def test_in_adapter_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [r[0] for r in ADAPTER_REGISTRY]
        self.assertIn("wusdm", keys)

    def test_registry_tier_t2(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        entry = [r for r in ADAPTER_REGISTRY if r[0] == "wusdm"][0]
        self.assertEqual(entry[1], "T2")

    def test_registry_class(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        entry = [r for r in ADAPTER_REGISTRY if r[0] == "wusdm"][0]
        self.assertIs(entry[2], WusdmAdapter)

    def test_in_all(self):
        import spa_core.adapters as pkg
        self.assertIn("WusdmAdapter", pkg.__all__)


# ════════════════════════════════════════════════════════════════════════════
# Точка входа
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
