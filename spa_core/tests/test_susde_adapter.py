#!/usr/bin/env python3
"""Тесты SusdeAdapter — MP-460.

Покрываем:
  TestSusdeInit        (10) — константы: protocol, tier=T3, chain_id, vault, risk_score, caps, apy, tvl
  TestSusdeAPY         (11) — get_apy, fallback, json override, get_apy_pct, health_check
  TestSusdePeg         (12) — is_peg_healthy: missing→True, 1.0→True, в пределах, граница, депег, нечисловое
  TestSusdeEligibility (10) — eligible = peg OK + APY OK; все комбинации
  TestSusdeYieldInfo   ( 8) — get_yield_info: apy десятичной дробью, tier, risk_score, exit_latency
  TestSusdeVsMorpho    ( 9) — vs_morpho_gap: положительный/отрицательный/кастомный
  TestSusdeAllocate    ( 9) — нулевой, negative → ValueError, нормальный, структура ответа
  TestSusdeWithdraw    ( 9) — нулевой, negative → ValueError, normal, insufficient
  TestSusdeCooldown    ( 6) — EXIT_LATENCY_HOURS=168, cooldown_hours(), 7d, не атомарен
  TestSusdeToDict      (11) — все ключи: peg_healthy, eligible, cooldown_hours, t3_cap, protocol, tier=T3
  TestSusdeRegistry    ( 5) — импорт, ADAPTER_REGISTRY, __all__

Итого: 100 тестов.

Запуск:
    python3 -m pytest spa_core/tests/test_susde_adapter.py -q
    python3 -m unittest spa_core.tests.test_susde_adapter -v
    python3 spa_core/tests/test_susde_adapter.py
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
from spa_core.adapters.susde_adapter import SusdeAdapter


# ── вспомогательные фабрики ──────────────────────────────────────────────────

def _make_adapter(
    apy: float | None = 12.0,
    usde_price: float | None = None,
    missing_section: bool = False,
    missing_file: bool = False,
) -> SusdeAdapter:
    """Создаёт адаптер с временным data_dir.

    apy=None         → поле susde.apy отсутствует (тест fallback)
    usde_price=None  → поле usde_price отсутствует (peg считается healthy)
    missing_section  → секция susde полностью отсутствует
    missing_file     → adapter_status.json не существует
    """
    if missing_file:
        return SusdeAdapter(data_dir="/nonexistent_spa_test_susde_xyz")

    tmp = tempfile.mkdtemp()
    if missing_section:
        content: dict = {}
    else:
        section: dict = {}
        if apy is not None:
            section["apy"] = apy
        if usde_price is not None:
            section["usde_price"] = usde_price
        content = {"susde": section}

    (Path(tmp) / "adapter_status.json").write_text(
        json.dumps(content), encoding="utf-8"
    )
    return SusdeAdapter(data_dir=tmp)


def _default() -> SusdeAdapter:
    """Адаптер с apy=12.0, без usde_price (peg healthy, eligible)."""
    return _make_adapter(apy=12.0)


def _no_file() -> SusdeAdapter:
    """Адаптер с несуществующим data_dir → fallback, peg healthy."""
    return _make_adapter(missing_file=True)


# ════════════════════════════════════════════════════════════════════════════
# 1. TestSusdeInit — константы и идентичность
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeInit(unittest.TestCase):
    """10 тестов: все ключевые константы класса."""

    def test_protocol_key(self):
        self.assertEqual(SusdeAdapter.PROTOCOL, "susde")

    def test_protocol_name(self):
        self.assertEqual(
            SusdeAdapter.PROTOCOL_NAME, "Ethena Staked USDe (sUSDe)"
        )

    def test_tier(self):
        self.assertEqual(SusdeAdapter.TIER, "T3")

    def test_chain_id(self):
        self.assertEqual(SusdeAdapter.CHAIN_ID, 1)

    def test_vault_address(self):
        self.assertEqual(
            SusdeAdapter.VAULT_ADDRESS,
            "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497",
        )

    def test_risk_score(self):
        self.assertAlmostEqual(SusdeAdapter.RISK_SCORE, 0.62)

    def test_t3_cap(self):
        self.assertAlmostEqual(SusdeAdapter.T3_CAP, 0.10)

    def test_apy_bounds(self):
        self.assertAlmostEqual(SusdeAdapter.MIN_APY_PCT, 4.0)
        self.assertAlmostEqual(SusdeAdapter.MAX_APY_PCT, 30.0)
        self.assertAlmostEqual(SusdeAdapter.DEFAULT_APY_PCT, 12.0)

    def test_tvl(self):
        self.assertAlmostEqual(SusdeAdapter.TVL_USD, 2_500_000_000)

    def test_inherits_base_adapter(self):
        adapter = _default()
        self.assertIsInstance(adapter, BaseAdapter)


# ════════════════════════════════════════════════════════════════════════════
# 2. TestSusdeAPY — чтение APY и health_check
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeAPY(unittest.TestCase):
    """11 тестов: get_apy, fallback, JSON override, get_apy_pct, health_check."""

    def test_default_apy_from_json(self):
        a = _make_adapter(apy=12.0)
        self.assertAlmostEqual(a.get_apy(), 12.0)

    def test_apy_override_higher(self):
        a = _make_adapter(apy=22.5)
        self.assertAlmostEqual(a.get_apy(), 22.5)

    def test_apy_override_lower(self):
        a = _make_adapter(apy=5.2)
        self.assertAlmostEqual(a.get_apy(), 5.2)

    def test_apy_fallback_missing_field(self):
        # apy=None → поле отсутствует → fallback 12.0
        a = _make_adapter(apy=None)
        self.assertAlmostEqual(a.get_apy(), SusdeAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_missing_section(self):
        a = _make_adapter(missing_section=True)
        self.assertAlmostEqual(a.get_apy(), SusdeAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_no_file(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy(), SusdeAdapter.DEFAULT_APY_PCT)

    def test_get_apy_pct_equals_get_apy(self):
        a = _make_adapter(apy=14.1)
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_get_apy_pct_fallback(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy_pct(), SusdeAdapter.DEFAULT_APY_PCT)

    def test_health_check_ok_in_range(self):
        a = _make_adapter(apy=12.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_ok_at_min_boundary(self):
        a = _make_adapter(apy=4.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_degraded_below_min(self):
        a = _make_adapter(apy=2.0)
        self.assertEqual(a.health_check(), "degraded")


# ════════════════════════════════════════════════════════════════════════════
# 3. TestSusdePeg — peg compliance gate
# ════════════════════════════════════════════════════════════════════════════

class TestSusdePeg(unittest.TestCase):
    """12 тестов: is_peg_healthy при различных значениях usde_price."""

    def test_peg_missing_field_healthy(self):
        """Поле usde_price отсутствует → healthy (нет данных != депег)."""
        a = _make_adapter(usde_price=None)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_missing_section_healthy(self):
        a = _make_adapter(missing_section=True)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_no_file_healthy(self):
        a = _no_file()
        self.assertTrue(a.is_peg_healthy())

    def test_peg_exactly_one_healthy(self):
        a = _make_adapter(usde_price=1.0)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_within_tolerance_above(self):
        """1.008 в пределах 0.01 → healthy."""
        a = _make_adapter(usde_price=1.008)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_within_tolerance_below(self):
        """0.992 в пределах 0.01 → healthy."""
        a = _make_adapter(usde_price=0.992)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_boundary_above(self):
        """Ровно +0.01 → граница, healthy (<=)."""
        a = _make_adapter(usde_price=1.01)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_boundary_below(self):
        """Ровно -0.01 → граница, healthy (<=)."""
        a = _make_adapter(usde_price=0.99)
        self.assertTrue(a.is_peg_healthy())

    def test_peg_depeg_above(self):
        """1.03 за пределами 0.01 → not healthy."""
        a = _make_adapter(usde_price=1.03)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_depeg_below(self):
        """0.95 (депег вниз) → not healthy."""
        a = _make_adapter(usde_price=0.95)
        self.assertFalse(a.is_peg_healthy())

    def test_peg_nonnumeric_safe_healthy(self):
        """Нечисловое значение usde_price → safe healthy."""
        a = _make_adapter(apy=12.0, usde_price="bad")
        self.assertTrue(a.is_peg_healthy())

    def test_peg_returns_bool(self):
        a = _make_adapter(usde_price=1.0)
        self.assertIsInstance(a.is_peg_healthy(), bool)


# ════════════════════════════════════════════════════════════════════════════
# 4. TestSusdeEligibility — is_eligible (peg OK + APY OK)
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeEligibility(unittest.TestCase):
    """10 тестов: is_eligible — все комбинации peg и APY."""

    def test_eligible_peg_ok_apy_ok(self):
        """peg healthy (no field), APY=12.0 → eligible."""
        a = _make_adapter(apy=12.0)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_depeg(self):
        """Депег, APY OK → not eligible."""
        a = _make_adapter(apy=12.0, usde_price=0.95)
        self.assertFalse(a.is_eligible())

    def test_not_eligible_peg_ok_apy_too_low(self):
        """peg OK, APY=2.0 (below MIN) → not eligible."""
        a = _make_adapter(apy=2.0)
        self.assertFalse(a.is_eligible())

    def test_not_eligible_peg_ok_apy_too_high(self):
        """peg OK, APY=35.0 (above MAX) → not eligible."""
        a = _make_adapter(apy=35.0)
        self.assertFalse(a.is_eligible())

    def test_eligible_at_min_apy(self):
        """peg OK, APY=4.0 (MIN boundary) → eligible."""
        a = _make_adapter(apy=4.0)
        self.assertTrue(a.is_eligible())

    def test_eligible_at_max_apy(self):
        """peg OK, APY=30.0 (MAX boundary) → eligible."""
        a = _make_adapter(apy=30.0)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_both_fail(self):
        """Депег + APY=2.0 → not eligible."""
        a = _make_adapter(apy=2.0, usde_price=0.90)
        self.assertFalse(a.is_eligible())

    def test_eligible_no_file(self):
        """Нет файла → peg healthy (default), APY=fallback 12.0 → eligible."""
        a = _no_file()
        self.assertTrue(a.is_eligible())

    def test_eligible_returns_bool(self):
        a = _make_adapter(apy=12.0)
        self.assertIsInstance(a.is_eligible(), bool)

    def test_eligible_peg_at_boundary(self):
        """usde_price=0.99 (граница peg), APY OK → eligible."""
        a = _make_adapter(apy=12.0, usde_price=0.99)
        self.assertTrue(a.is_eligible())


# ════════════════════════════════════════════════════════════════════════════
# 5. TestSusdeYieldInfo — get_yield_info
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeYieldInfo(unittest.TestCase):
    """8 тестов: get_yield_info — apy десятичной дробью, поля."""

    def test_yield_info_type(self):
        a = _default()
        self.assertIsInstance(a.get_yield_info(), YieldInfo)

    def test_yield_info_apy_decimal(self):
        """APY=12.0% → 0.12 в YieldInfo (десятичная дробь)."""
        a = _make_adapter(apy=12.0)
        self.assertAlmostEqual(a.get_yield_info().apy, 0.12)

    def test_yield_info_apy_decimal_override(self):
        a = _make_adapter(apy=18.0)
        self.assertAlmostEqual(a.get_yield_info().apy, 0.18)

    def test_yield_info_protocol(self):
        a = _default()
        self.assertEqual(a.get_yield_info().protocol, "susde")

    def test_yield_info_tier(self):
        a = _default()
        self.assertEqual(a.get_yield_info().tier, "T3")

    def test_yield_info_risk_score(self):
        a = _default()
        self.assertAlmostEqual(a.get_yield_info().risk_score, 0.62)

    def test_yield_info_exit_latency(self):
        a = _default()
        self.assertEqual(a.get_yield_info().exit_latency_hours, 168.0)

    def test_yield_info_tvl(self):
        a = _default()
        self.assertAlmostEqual(a.get_yield_info().tvl_usd, 2_500_000_000)


# ════════════════════════════════════════════════════════════════════════════
# 6. TestSusdeVsMorpho — vs_morpho_gap
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeVsMorpho(unittest.TestCase):
    """9 тестов: vs_morpho_gap (положительный/отрицательный/кастомный)."""

    def test_default_gap_negative_susde_better(self):
        """Morpho 6.5% vs sUSDe 12.0% → gap = -5.5 (sUSDe лучше)."""
        a = _make_adapter(apy=12.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), -5.5)

    def test_gap_positive_morpho_better(self):
        """Morpho 6.5% vs sUSDe 5.0% → gap = +1.5 (Morpho лучше)."""
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 1.5)

    def test_gap_zero_equal(self):
        """Morpho 6.5% vs sUSDe 6.5% → gap = 0.0."""
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.0)

    def test_custom_morpho_apy_higher(self):
        """Кастомный morpho_apy=8.0 vs sUSDe 12.0% → gap = -4.0."""
        a = _make_adapter(apy=12.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=8.0), -4.0)

    def test_custom_morpho_apy_lower(self):
        """Кастомный morpho_apy=4.0 vs sUSDe 12.0% → gap = -8.0."""
        a = _make_adapter(apy=12.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=4.0), -8.0)

    def test_gap_with_fallback_apy(self):
        """Fallback APY=12.0 → gap = 6.5 - 12.0 = -5.5."""
        a = _no_file()
        self.assertAlmostEqual(a.vs_morpho_gap(), -5.5)

    def test_gap_returns_float(self):
        a = _default()
        self.assertIsInstance(a.vs_morpho_gap(), float)

    def test_gap_large_positive(self):
        """Morpho 25% vs sUSDe 12.0% → gap = 13.0."""
        a = _make_adapter(apy=12.0)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=25.0), 13.0)

    def test_gap_default_parameter_is_6_5(self):
        """Дефолтный morpho_apy должен быть 6.5."""
        a = _make_adapter(apy=0.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 6.5)


# ════════════════════════════════════════════════════════════════════════════
# 7. TestSusdeAllocate — paper trading аллокация
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeAllocate(unittest.TestCase):
    """9 тестов: нулевой, negative → ValueError, нормальный, структура ответа."""

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
        self.assertEqual(result["protocol"], "susde")

    def test_allocate_result_has_vault(self):
        a = _default()
        result = a.allocate(1000.0)
        self.assertEqual(
            result["vault"],
            "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497",
        )

    def test_allocate_result_has_amount(self):
        a = _default()
        result = a.allocate(7500.0)
        self.assertAlmostEqual(result["amount"], 7500.0)

    def test_allocate_result_has_apy_pct(self):
        a = _default()
        result = a.allocate(1000.0)
        self.assertIn("apy_pct", result)
        self.assertIsInstance(result["apy_pct"], float)


# ════════════════════════════════════════════════════════════════════════════
# 8. TestSusdeWithdraw — paper trading вывод
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeWithdraw(unittest.TestCase):
    """9 тестов: нулевой, negative → ValueError, normal, insufficient."""

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
        self.assertEqual(result["protocol"], "susde")

    def test_withdraw_result_has_vault(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(1000.0)
        self.assertEqual(
            result["vault"],
            "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497",
        )

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
# 9. TestSusdeCooldown — 7-дневный unstake cooldown (специфика sUSDe)
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeCooldown(unittest.TestCase):
    """6 тестов: EXIT_LATENCY_HOURS=168, cooldown_hours(), 7d, не атомарен."""

    def test_exit_latency_is_168(self):
        """EXIT_LATENCY_HOURS = 168.0 (7 дней)."""
        self.assertEqual(SusdeAdapter.EXIT_LATENCY_HOURS, 168.0)

    def test_cooldown_hours_returns_168(self):
        a = _default()
        self.assertEqual(a.cooldown_hours(), 168.0)

    def test_cooldown_hours_equals_exit_latency(self):
        a = _default()
        self.assertEqual(a.cooldown_hours(), SusdeAdapter.EXIT_LATENCY_HOURS)

    def test_cooldown_hours_returns_float(self):
        a = _default()
        self.assertIsInstance(a.cooldown_hours(), float)

    def test_cooldown_is_seven_days(self):
        """168 часов == 7 суток."""
        a = _default()
        self.assertAlmostEqual(a.cooldown_hours() / 24.0, 7.0)

    def test_cooldown_not_atomic(self):
        """Выход не атомарен: cooldown > 0 (в отличие от ERC-4626 redeem у sFRAX)."""
        a = _default()
        self.assertGreater(a.cooldown_hours(), 0.0)


# ════════════════════════════════════════════════════════════════════════════
# 10. TestSusdeToDict — сериализация
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeToDict(unittest.TestCase):
    """11 тестов: все ключевые поля to_dict(), peg_healthy, eligible, cooldown_hours, t3_cap, protocol, tier=T3."""

    def test_to_dict_has_protocol(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(d["protocol"], "susde")

    def test_to_dict_has_tier_t3(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(d["tier"], "T3")

    def test_to_dict_has_t3_cap(self):
        a = _default()
        d = a.to_dict()
        self.assertIn("t3_cap", d)
        self.assertAlmostEqual(d["t3_cap"], 0.10)

    def test_to_dict_has_cooldown_hours(self):
        a = _default()
        d = a.to_dict()
        self.assertIn("cooldown_hours", d)
        self.assertAlmostEqual(d["cooldown_hours"], 168.0)

    def test_to_dict_has_peg_healthy_true(self):
        """Нет депега → peg_healthy=True в to_dict."""
        a = _make_adapter(apy=12.0)
        d = a.to_dict()
        self.assertIn("peg_healthy", d)
        self.assertTrue(d["peg_healthy"])

    def test_to_dict_has_peg_healthy_false(self):
        """Депег → peg_healthy=False в to_dict."""
        a = _make_adapter(apy=12.0, usde_price=0.95)
        d = a.to_dict()
        self.assertFalse(d["peg_healthy"])

    def test_to_dict_has_eligible_true(self):
        """peg OK, APY=12.0 → eligible=True."""
        a = _default()
        d = a.to_dict()
        self.assertIn("eligible", d)
        self.assertTrue(d["eligible"])

    def test_to_dict_has_eligible_false(self):
        """Депег → eligible=False."""
        a = _make_adapter(apy=12.0, usde_price=0.90)
        d = a.to_dict()
        self.assertFalse(d["eligible"])

    def test_to_dict_all_required_keys_present(self):
        required = {
            "protocol", "protocol_name", "vault_address", "tier", "t3_cap",
            "chain", "chain_id", "asset", "apy_pct", "risk_score",
            "exit_latency_hours", "tvl_usd", "min_apy_pct", "max_apy_pct",
            "peg_healthy", "cooldown_hours", "eligible", "allocated",
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
            "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497",
        )

    def test_to_dict_exit_latency_168(self):
        a = _default()
        d = a.to_dict()
        self.assertAlmostEqual(d["exit_latency_hours"], 168.0)


# ════════════════════════════════════════════════════════════════════════════
# 11. TestSusdeRegistry — регистрация в пакете adapters
# ════════════════════════════════════════════════════════════════════════════

class TestSusdeRegistry(unittest.TestCase):
    """5 тестов: импорт, ADAPTER_REGISTRY, __all__."""

    def test_import_from_package(self):
        from spa_core.adapters import SusdeAdapter as Imported
        self.assertIs(Imported, SusdeAdapter)

    def test_in_adapter_registry(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = [r[0] for r in ADAPTER_REGISTRY]
        self.assertIn("susde", keys)

    def test_registry_tier_t3(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        entry = [r for r in ADAPTER_REGISTRY if r[0] == "susde"][0]
        self.assertEqual(entry[1], "T3")

    def test_registry_class(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        entry = [r for r in ADAPTER_REGISTRY if r[0] == "susde"][0]
        self.assertIs(entry[2], SusdeAdapter)

    def test_in_all(self):
        import spa_core.adapters as pkg
        self.assertIn("SusdeAdapter", pkg.__all__)


# ════════════════════════════════════════════════════════════════════════════
# Точка входа
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
