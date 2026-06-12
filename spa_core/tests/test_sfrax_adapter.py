#!/usr/bin/env python3
"""Тесты SfraxAdapter — MP-430.

Покрываем:
  TestSfraxInit        (12) — константы: protocol, tier=T2, chain_id, vault, risk_score, caps, apy, tvl
  TestSfraxAPY         (12) — get_apy, fallback, json override, get_apy_pct, health_check
  TestSfraxPeg         (13) — is_peg_healthy: missing→True, 1.0→True, в пределах, граница, депег, нечисловое
  TestSfraxEligibility (11) — eligible = peg OK + APY OK; все комбинации
  TestSfraxYieldInfo   ( 8) — get_yield_info: apy десятичной дробью, tier, risk_score, exit_latency
  TestSfraxVsMorpho    (10) — vs_morpho_gap: положительный/отрицательный/кастомный
  TestSfraxAllocate    (10) — нулевой, negative → ValueError, нормальный, структура ответа
  TestSfraxWithdraw    (10) — нулевой, negative → ValueError, normal, insufficient
  TestSfraxToDict      ( 9) — все ключи: peg_healthy, eligible, protocol, tier=T2
  TestSfraxRegistry    ( 5) — импорт, ADAPTER_REGISTRY, __all__

Итого: 100 тестов.

Запуск:
    python3 -m pytest spa_core/tests/test_sfrax_adapter.py -q
    python3 -m unittest spa_core.tests.test_sfrax_adapter -v
    python3 spa_core/tests/test_sfrax_adapter.py
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
from spa_core.adapters.sfrax_adapter import SfraxAdapter


# ── вспомогательные фабрики ──────────────────────────────────────────────────

def _make_adapter(
    apy: float | None = 6.0,
    frax_price: float | None = None,
    missing_section: bool = False,
    missing_file: bool = False,
) -> SfraxAdapter:
    """Создаёт адаптер с временным data_dir.

    apy=None         → поле sfrax.apy отсутствует (тест fallback)
    frax_price=None  → поле frax_price отсутствует (peg считается healthy)
    missing_section  → секция sfrax полностью отсутствует
    missing_file     → adapter_status.json не существует
    """
    if missing_file:
        return SfraxAdapter(data_dir="/nonexistent_spa_test_sfrax_xyz")

    tmp = tempfile.mkdtemp()
    if missing_section:
        content: dict = {}
    else:
        section: dict = {}
        if apy is not None:
            section["apy"] = apy
        if frax_price is not None:
            section["frax_price"] = frax_price
        content = {"sfrax": section}

    (Path(tmp) / "adapter_status.json").write_text(
        json.dumps(content), encoding="utf-8"
    )
    return SfraxAdapter(data_dir=tmp)


def _default() -> SfraxAdapter:
    """Адаптер с apy=6.0, без frax_price (peg healthy, eligible)."""
    return _make_adapter(apy=6.0)


def _no_file() -> SfraxAdapter:
    """Адаптер с несуществующим data_dir → fallback, peg healthy."""
    return _make_adapter(missing_file=True)


# ════════════════════════════════════════════════════════════════════════════
# 1. TestSfraxInit — константы и идентичность
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxInit(unittest.TestCase):
    """12 тестов: все ключевые константы класса."""

    def test_protocol_key(self):
        self.assertEqual(SfraxAdapter.PROTOCOL, "sfrax")

    def test_protocol_name(self):
        self.assertEqual(SfraxAdapter.PROTOCOL_NAME, "Frax Staked FRAX (sFRAX)")

    def test_tier(self):
        self.assertEqual(SfraxAdapter.TIER, "T2")

    def test_chain_id(self):
        self.assertEqual(SfraxAdapter.CHAIN_ID, 1)

    def test_chain(self):
        self.assertEqual(SfraxAdapter.CHAIN, "ethereum")

    def test_vault_address(self):
        self.assertEqual(
            SfraxAdapter.VAULT_ADDRESS,
            "0xA663B02CF0a4b149d2aD41910CB81e23e1c41c32",
        )

    def test_risk_score(self):
        self.assertAlmostEqual(SfraxAdapter.RISK_SCORE, 0.40)

    def test_t2_cap(self):
        self.assertAlmostEqual(SfraxAdapter.T2_CAP, 0.20)

    def test_exit_latency_instant(self):
        self.assertEqual(SfraxAdapter.EXIT_LATENCY_HOURS, 0.0)

    def test_apy_bounds(self):
        self.assertAlmostEqual(SfraxAdapter.MIN_APY_PCT, 3.0)
        self.assertAlmostEqual(SfraxAdapter.MAX_APY_PCT, 12.0)
        self.assertAlmostEqual(SfraxAdapter.DEFAULT_APY_PCT, 6.0)

    def test_tvl(self):
        self.assertAlmostEqual(SfraxAdapter.TVL_USD, 600_000_000)

    def test_inherits_base_adapter(self):
        adapter = _default()
        self.assertIsInstance(adapter, BaseAdapter)


# ════════════════════════════════════════════════════════════════════════════
# 2. TestSfraxAPY — чтение APY и health_check
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxAPY(unittest.TestCase):
    """12 тестов: get_apy, fallback, JSON override, get_apy_pct, health_check."""

    def test_default_apy_from_json(self):
        a = _make_adapter(apy=6.0)
        self.assertAlmostEqual(a.get_apy(), 6.0)

    def test_apy_override_higher(self):
        a = _make_adapter(apy=8.5)
        self.assertAlmostEqual(a.get_apy(), 8.5)

    def test_apy_override_lower(self):
        a = _make_adapter(apy=4.2)
        self.assertAlmostEqual(a.get_apy(), 4.2)

    def test_apy_fallback_missing_field(self):
        # apy=None → поле отсутствует → fallback 6.0
        a = _make_adapter(apy=None)
        self.assertAlmostEqual(a.get_apy(), SfraxAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_missing_section(self):
        a = _make_adapter(missing_section=True)
        self.assertAlmostEqual(a.get_apy(), SfraxAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_no_file(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy(), SfraxAdapter.DEFAULT_APY_PCT)

    def test_get_apy_pct_equals_get_apy(self):
        a = _make_adapter(apy=7.1)
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_get_apy_pct_fallback(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy_pct(), SfraxAdapter.DEFAULT_APY_PCT)

    def test_health_check_ok_in_range(self):
        a = _make_adapter(apy=6.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_ok_at_min_boundary(self):
        a = _make_adapter(apy=3.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_ok_at_max_boundary(self):
        a = _make_adapter(apy=12.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_degraded_below_min(self):
        a = _make_adapter(apy=1.0)
        self.assertEqual(a.health_check(), "degraded")


# ════════════════════════════════════════════════════════════════════════════
# 3. TestSfraxPeg — peg compliance gate
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxPeg(unittest.TestCase):
    """13 тестов: is_peg_healthy при различных значениях frax_price."""

    def test_peg_missing_field_healthy(self):
        """Поле frax_price отсутствует → healthy (нет данных != депег)."""
        a = _make_adapter(frax_price=None)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_missing_section_healthy(self):
        a = _make_adapter(missing_section=True)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_no_file_healthy(self):
        a = _no_file()
        self.assertTrue(a.is_peg_healthy())

    def test_peg_exactly_one_healthy(self):
        a = _make_adapter(frax_price=1.0)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_within_tolerance_above(self):
        """1.004 в пределах 0.005 → healthy."""
        a = _make_adapter(frax_price=1.004)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_within_tolerance_below(self):
        """0.996 в пределах 0.005 → healthy."""
        a = _make_adapter(frax_price=0.996)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_boundary_above(self):
        """Ровно +0.005 → граница, healthy (<=)."""
        a = _make_adapter(frax_price=1.005)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_boundary_below(self):
        """Ровно -0.005 → граница, healthy (<=)."""
        a = _make_adapter(frax_price=0.995)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_depeg_above(self):
        """1.02 за пределами 0.005 → not healthy."""
        a = _make_adapter(frax_price=1.02)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_depeg_below(self):
        """0.97 (депег вниз) → not healthy."""
        a = _make_adapter(frax_price=0.97)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_just_over_boundary(self):
        """1.0051 чуть за границей → not healthy."""
        a = _make_adapter(frax_price=1.0051)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_nonnumeric_safe_healthy(self):
        """Нечисловое значение frax_price → safe healthy."""
        a = _make_adapter(apy=6.0, frax_price="bad")
        self.assertTrue(a.is_peg_healthy())

    def test_peg_returns_bool(self):
        a = _make_adapter(frax_price=1.0)
        self.assertIsInstance(a.is_peg_healthy(), bool)


# ════════════════════════════════════════════════════════════════════════════
# 4. TestSfraxEligibility — is_eligible (peg OK + APY OK)
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxEligibility(unittest.TestCase):
    """11 тестов: is_eligible — все комбинации peg и APY."""

    def test_eligible_peg_ok_apy_ok(self):
        """peg healthy (no field), APY=6.0 → eligible."""
        a = _make_adapter(apy=6.0)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_depeg(self):
        """Депег, APY OK → not eligible."""
        a = _make_adapter(apy=6.0, frax_price=0.95)
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
        """peg OK, APY=12.0 (MAX boundary) → eligible."""
        a = _make_adapter(apy=12.0)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_both_fail(self):
        """Депег + APY=1.0 → not eligible."""
        a = _make_adapter(apy=1.0, frax_price=0.90)
        self.assertFalse(a.is_eligible())

    def test_eligible_no_file(self):
        """Нет файла → peg healthy (default), APY=fallback 6.0 → eligible."""
        a = _no_file()
        self.assertTrue(a.is_eligible())

    def test_eligible_returns_bool(self):
        a = _make_adapter(apy=6.0)
        self.assertIsInstance(a.is_eligible(), bool)

    def test_not_eligible_depeg_just_over(self):
        """frax_price=1.0051 (чуть за порогом), APY OK → not eligible."""
        a = _make_adapter(apy=6.0, frax_price=1.0051)
        self.assertFalse(a.is_eligible())

    def test_eligible_peg_at_boundary(self):
        """frax_price=0.995 (граница peg), APY OK → eligible."""
        a = _make_adapter(apy=6.0, frax_price=0.995)
        self.assertTrue(a.is_eligible())


# ════════════════════════════════════════════════════════════════════════════
# 5. TestSfraxYieldInfo — get_yield_info
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxYieldInfo(unittest.TestCase):
    """8 тестов: get_yield_info — apy десятичной дробью, поля."""

    def test_yield_info_type(self):
        a = _default()
        self.assertIsInstance(a.get_yield_info(), YieldInfo)

    def test_yield_info_apy_decimal(self):
        """APY=6.0% → 0.06 в YieldInfo (десятичная дробь)."""
        a = _make_adapter(apy=6.0)
        self.assertAlmostEqual(a.get_yield_info().apy, 0.06)

    def test_yield_info_apy_decimal_override(self):
        a = _make_adapter(apy=9.0)
        self.assertAlmostEqual(a.get_yield_info().apy, 0.09)

    def test_yield_info_protocol(self):
        a = _default()
        self.assertEqual(a.get_yield_info().protocol, "sfrax")

    def test_yield_info_tier(self):
        a = _default()
        self.assertEqual(a.get_yield_info().tier, "T2")

    def test_yield_info_risk_score(self):
        a = _default()
        self.assertAlmostEqual(a.get_yield_info().risk_score, 0.40)

    def test_yield_info_exit_latency(self):
        a = _default()
        self.assertEqual(a.get_yield_info().exit_latency_hours, 0.0)

    def test_yield_info_tvl(self):
        a = _default()
        self.assertAlmostEqual(a.get_yield_info().tvl_usd, 600_000_000)


# ════════════════════════════════════════════════════════════════════════════
# 6. TestSfraxVsMorpho — vs_morpho_gap
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxVsMorpho(unittest.TestCase):
    """10 тестов: vs_morpho_gap (положительный/отрицательный/кастомный)."""

    def test_default_gap_positive(self):
        """Morpho 6.5% vs sFRAX 6.0% → gap = +0.5 (Morpho лучше)."""
        a = _make_adapter(apy=6.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.5)

    def test_gap_negative_sfrax_better(self):
        """Morpho 6.5% vs sFRAX 7.0% → gap = -0.5 (sFRAX лучше)."""
        a = _make_adapter(apy=7.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), -0.5)

    def test_gap_zero_equal(self):
        """Morpho 6.5% vs sFRAX 6.5% → gap = 0.0."""
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.0)

    def test_custom_morpho_apy_higher(self):
        """Кастомный morpho_apy=8.0 vs sFRAX 6.0% → gap = 2.0."""
        a = _make_adapter(apy=6.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=8.0), 2.0)

    def test_custom_morpho_apy_lower(self):
        """Кастомный morpho_apy=4.0 vs sFRAX 6.0% → gap = -2.0."""
        a = _make_adapter(apy=6.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=4.0), -2.0)

    def test_gap_with_fallback_apy(self):
        """Fallback APY=6.0 → gap = 6.5 - 6.0 = 0.5."""
        a = _no_file()
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.5)

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
        """Morpho 20% vs sFRAX 6.0% → gap = 14.0."""
        a = _make_adapter(apy=6.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=20.0), 14.0)

    def test_gap_default_parameter_is_6_5(self):
        """Дефолтный morpho_apy должен быть 6.5."""
        a = _make_adapter(apy=0.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 6.5)


# ════════════════════════════════════════════════════════════════════════════
# 7. TestSfraxAllocate — paper trading аллокация
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxAllocate(unittest.TestCase):
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
        self.assertEqual(result["protocol"], "sfrax")

    def test_allocate_result_has_vault(self):
        a = _default()
        result = a.allocate(1000.0)
        self.assertEqual(
            result["vault"],
            "0xA663B02CF0a4b149d2aD41910CB81e23e1c41c32",
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
# 8. TestSfraxWithdraw — paper trading вывод
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxWithdraw(unittest.TestCase):
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
        self.assertEqual(result["protocol"], "sfrax")

    def test_withdraw_result_has_vault(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(1000.0)
        self.assertEqual(
            result["vault"],
            "0xA663B02CF0a4b149d2aD41910CB81e23e1c41c32",
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
# 9. TestSfraxToDict — сериализация
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxToDict(unittest.TestCase):
    """9 тестов: все ключевые поля to_dict(), peg_healthy, eligible, protocol, tier=T2."""

    def test_to_dict_has_protocol(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(d["protocol"], "sfrax")

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
        a = _make_adapter(apy=6.0)
        d = a.to_dict()
        self.assertIn("peg_healthy", d)
        self.assertTrue(d["peg_healthy"])

    def test_to_dict_has_peg_healthy_false(self):
        """Депег → peg_healthy=False в to_dict."""
        a = _make_adapter(apy=6.0, frax_price=0.95)
        d = a.to_dict()
        self.assertFalse(d["peg_healthy"])

    def test_to_dict_has_eligible_true(self):
        """peg OK, APY=6.0 → eligible=True."""
        a = _default()
        d = a.to_dict()
        self.assertIn("eligible", d)
        self.assertTrue(d["eligible"])

    def test_to_dict_has_eligible_false(self):
        """Депег → eligible=False."""
        a = _make_adapter(apy=6.0, frax_price=0.90)
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
            "0xA663B02CF0a4b149d2aD41910CB81e23e1c41c32",
        )


# ════════════════════════════════════════════════════════════════════════════
# 10. TestSfraxRegistry — регистрация в пакете adapters
# ════════════════════════════════════════════════════════════════════════════

class TestSfraxRegistry(unittest.TestCase):
    """5 тестов: импорт, ADAPTER_REGISTRY, __all__."""

    def test_import_from_package(self):
        from spa_core.adapters import SfraxAdapter as Imported
        self.assertIs(Imported, SfraxAdapter)

    def test_in_adapter_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [r[0] for r in ADAPTER_REGISTRY]
        self.assertIn("sfrax", keys)

    def test_registry_tier_t2(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        entry = [r for r in ADAPTER_REGISTRY if r[0] == "sfrax"][0]
        self.assertEqual(entry[1], "T2")

    def test_registry_class(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        entry = [r for r in ADAPTER_REGISTRY if r[0] == "sfrax"][0]
        self.assertIs(entry[2], SfraxAdapter)

    def test_in_all(self):
        import spa_core.adapters as pkg
        self.assertIn("SfraxAdapter", pkg.__all__)


# ════════════════════════════════════════════════════════════════════════════
# Точка входа
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
