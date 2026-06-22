#!/usr/bin/env python3
"""Тесты SparkSusdsAdapter — MP-376.

Покрываем:
  TestSparkInit        (10) — константы: protocol, tier, chain_id, vault, risk_score, caps
  TestSparkAPY         (12) — get_apy, fallback, json override, get_apy_pct, health_check
  TestSparkGSM         (12) — is_gsm_compliant: False/True/boundary/missing
  TestSparkEligibility (10) — eligible = gsm OK + APY OK; все комбинации
  TestSparkVsMorpho    (10) — vs_morpho_gap: положительный/отрицательный/кастомный
  TestSparkAllocate    (10) — нулевой, negative → ValueError, нормальный, структура ответа
  TestSparkWithdraw    (10) — нулевой, negative → ValueError, normal, insufficient
  TestSparkToDict      ( 8) — все ключи: gsm_compliant, eligible, protocol, tier

Итого: 82 теста.

Запуск:
    python3 -m pytest spa_core/tests/test_spark_susds_adapter.py -q
    python3 -m unittest spa_core.tests.test_spark_susds_adapter -v
    python3 spa_core/tests/test_spark_susds_adapter.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Добавляем корень репо в sys.path для прямого запуска файла
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.adapters.base_adapter import BaseAdapter
from spa_core.adapters.spark_susds_adapter import SparkSusdsAdapter


# ── вспомогательные фабрики ──────────────────────────────────────────────────

def _make_adapter(
    apy: float | None = 5.5,
    gsm_hours: float | None = 0,
    missing_section: bool = False,
    missing_file: bool = False,
) -> SparkSusdsAdapter:
    """Создаёт адаптер с временным data_dir.

    apy=None         → поле spark_susds.apy отсутствует (тест fallback)
    missing_section  → секция spark_susds полностью отсутствует
    missing_file     → adapter_status.json не существует
    """
    if missing_file:
        return SparkSusdsAdapter(data_dir="/nonexistent_spa_test_spark_xyz")

    tmp = tempfile.mkdtemp()
    if missing_section:
        content: dict = {}
    else:
        section: dict = {}
        if apy is not None:
            section["apy"] = apy
        if gsm_hours is not None:
            section["gsm_hours"] = gsm_hours
        content = {"spark_susds": section}

    (Path(tmp) / "adapter_status.json").write_text(
        json.dumps(content), encoding="utf-8"
    )
    return SparkSusdsAdapter(data_dir=tmp)


def _default() -> SparkSusdsAdapter:
    """Адаптер с apy=5.5, gsm_hours=0 (не eligible)."""
    return _make_adapter(apy=5.5, gsm_hours=0)


def _eligible() -> SparkSusdsAdapter:
    """Адаптер с apy=5.5, gsm_hours=72 (eligible)."""
    return _make_adapter(apy=5.5, gsm_hours=72)


def _no_file() -> SparkSusdsAdapter:
    """Адаптер с несуществующим data_dir → fallback."""
    return _make_adapter(missing_file=True)


# ════════════════════════════════════════════════════════════════════════════
# 1. TestSparkInit — константы и идентичность
# ════════════════════════════════════════════════════════════════════════════

class TestSparkInit(unittest.TestCase):
    """10 тестов: все ключевые константы класса."""

    def test_protocol_key(self):
        self.assertEqual(SparkSusdsAdapter.PROTOCOL, "spark_susds")

    def test_protocol_name(self):
        self.assertEqual(SparkSusdsAdapter.PROTOCOL_NAME, "Spark Protocol sUSDS")

    def test_tier(self):
        self.assertEqual(SparkSusdsAdapter.TIER, "T1")

    def test_chain_id(self):
        self.assertEqual(SparkSusdsAdapter.CHAIN_ID, 1)

    def test_chain(self):
        self.assertEqual(SparkSusdsAdapter.CHAIN, "ethereum")

    def test_vault_address(self):
        self.assertEqual(
            SparkSusdsAdapter.VAULT_ADDRESS,
            "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD",
        )

    def test_risk_score(self):
        self.assertAlmostEqual(SparkSusdsAdapter.RISK_SCORE, 0.28)

    def test_t1_cap(self):
        self.assertAlmostEqual(SparkSusdsAdapter.T1_CAP, 0.30)

    def test_exit_latency_instant(self):
        self.assertEqual(SparkSusdsAdapter.EXIT_LATENCY_HOURS, 0.0)

    def test_inherits_base_adapter(self):
        adapter = _default()
        self.assertIsInstance(adapter, BaseAdapter)


# ════════════════════════════════════════════════════════════════════════════
# 2. TestSparkAPY — чтение APY и health_check
# ════════════════════════════════════════════════════════════════════════════

class TestSparkAPY(unittest.TestCase):
    """12 тестов: get_apy, fallback, JSON override, get_apy_pct, health_check."""

    def test_default_apy_from_json(self):
        a = _make_adapter(apy=5.5)
        self.assertAlmostEqual(a.get_apy(), 5.5)

    def test_apy_override_higher(self):
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.get_apy(), 6.5)

    def test_apy_override_lower(self):
        a = _make_adapter(apy=4.2)
        self.assertAlmostEqual(a.get_apy(), 4.2)

    def test_apy_fallback_missing_field(self):
        # apy=None → поле отсутствует → fallback 5.5
        a = _make_adapter(apy=None)
        self.assertAlmostEqual(a.get_apy(), SparkSusdsAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_missing_section(self):
        a = _make_adapter(missing_section=True)
        self.assertAlmostEqual(a.get_apy(), SparkSusdsAdapter.DEFAULT_APY_PCT)

    def test_apy_fallback_no_file(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy(), SparkSusdsAdapter.DEFAULT_APY_PCT)

    def test_get_apy_pct_equals_get_apy(self):
        a = _make_adapter(apy=5.8)
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_get_apy_pct_fallback(self):
        a = _no_file()
        self.assertAlmostEqual(a.get_apy_pct(), SparkSusdsAdapter.DEFAULT_APY_PCT)

    def test_health_check_ok_in_range(self):
        a = _make_adapter(apy=5.5)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_ok_at_min_boundary(self):
        a = _make_adapter(apy=4.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_ok_at_max_boundary(self):
        a = _make_adapter(apy=9.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_check_degraded_below_min(self):
        a = _make_adapter(apy=1.0)
        self.assertEqual(a.health_check(), "degraded")


# ════════════════════════════════════════════════════════════════════════════
# 3. TestSparkGSM — GSM compliance gate
# ════════════════════════════════════════════════════════════════════════════

class TestSparkGSM(unittest.TestCase):
    """12 тестов: is_gsm_compliant при различных значениях gsm_hours."""

    def test_gsm_zero_not_compliant(self):
        a = _make_adapter(gsm_hours=0)
        self.assertFalse(a.is_gsm_compliant())

    def test_gsm_missing_field_not_compliant(self):
        a = _make_adapter(gsm_hours=None)
        self.assertFalse(a.is_gsm_compliant())

    def test_gsm_missing_section_not_compliant(self):
        a = _make_adapter(missing_section=True)
        self.assertFalse(a.is_gsm_compliant())

    def test_gsm_no_file_not_compliant(self):
        a = _no_file()
        self.assertFalse(a.is_gsm_compliant())

    def test_gsm_24_not_compliant(self):
        a = _make_adapter(gsm_hours=24)
        self.assertFalse(a.is_gsm_compliant())

    def test_gsm_47_not_compliant(self):
        a = _make_adapter(gsm_hours=47)
        self.assertFalse(a.is_gsm_compliant())

    def test_gsm_47_9_not_compliant(self):
        a = _make_adapter(gsm_hours=47.9)
        self.assertFalse(a.is_gsm_compliant())

    def test_gsm_48_compliant(self):
        a = _make_adapter(gsm_hours=48)
        self.assertTrue(a.is_gsm_compliant())

    def test_gsm_72_compliant(self):
        a = _make_adapter(gsm_hours=72)
        self.assertTrue(a.is_gsm_compliant())

    def test_gsm_100_compliant(self):
        a = _make_adapter(gsm_hours=100)
        self.assertTrue(a.is_gsm_compliant())

    def test_gsm_48_exactly_boundary(self):
        """48 часов — ровно граница, должен быть compliant."""
        a = _make_adapter(gsm_hours=48.0)
        self.assertTrue(a.is_gsm_compliant())

    def test_gsm_returns_bool(self):
        a = _make_adapter(gsm_hours=72)
        result = a.is_gsm_compliant()
        self.assertIsInstance(result, bool)


# ════════════════════════════════════════════════════════════════════════════
# 4. TestSparkEligibility — is_eligible (gsm OK + APY OK)
# ════════════════════════════════════════════════════════════════════════════

class TestSparkEligibility(unittest.TestCase):
    """10 тестов: is_eligible — все комбинации gsm и APY."""

    def test_not_eligible_gsm_fail(self):
        """gsm=0, APY OK → not eligible."""
        a = _make_adapter(apy=5.5, gsm_hours=0)
        self.assertFalse(a.is_eligible())

    def test_eligible_gsm_ok_apy_ok(self):
        """gsm=72, APY=5.5 → eligible."""
        a = _make_adapter(apy=5.5, gsm_hours=72)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_gsm_ok_apy_too_low(self):
        """gsm=72, APY=1.0 (below MIN) → not eligible."""
        a = _make_adapter(apy=1.0, gsm_hours=72)
        self.assertFalse(a.is_eligible())

    def test_not_eligible_gsm_ok_apy_too_high(self):
        """gsm=72, APY=15.0 (above MAX) → not eligible."""
        a = _make_adapter(apy=15.0, gsm_hours=72)
        self.assertFalse(a.is_eligible())

    def test_eligible_at_min_apy_gsm_ok(self):
        """gsm=48, APY=4.0 (MIN boundary) → eligible."""
        a = _make_adapter(apy=4.0, gsm_hours=48)
        self.assertTrue(a.is_eligible())

    def test_eligible_at_max_apy_gsm_ok(self):
        """gsm=48, APY=9.0 (MAX boundary) → eligible."""
        a = _make_adapter(apy=9.0, gsm_hours=48)
        self.assertTrue(a.is_eligible())

    def test_not_eligible_both_fail(self):
        """gsm=0, APY=1.0 → not eligible."""
        a = _make_adapter(apy=1.0, gsm_hours=0)
        self.assertFalse(a.is_eligible())

    def test_not_eligible_no_file(self):
        """Нет файла → gsm не compliant → not eligible."""
        a = _no_file()
        self.assertFalse(a.is_eligible())

    def test_eligible_returns_bool(self):
        a = _make_adapter(apy=5.5, gsm_hours=72)
        self.assertIsInstance(a.is_eligible(), bool)

    def test_not_eligible_gsm_47(self):
        """gsm=47 (ниже порога), APY OK → not eligible."""
        a = _make_adapter(apy=5.5, gsm_hours=47)
        self.assertFalse(a.is_eligible())


# ════════════════════════════════════════════════════════════════════════════
# 5. TestSparkVsMorpho — vs_morpho_gap
# ════════════════════════════════════════════════════════════════════════════

class TestSparkVsMorpho(unittest.TestCase):
    """10 тестов: vs_morpho_gap (положительный/отрицательный/кастомный)."""

    def test_default_gap_positive(self):
        """Morpho 6.5% vs Spark 5.5% → gap = +1.0 (Morpho лучше)."""
        a = _make_adapter(apy=5.5)
        self.assertAlmostEqual(a.vs_morpho_gap(), 1.0)

    def test_gap_negative_spark_better(self):
        """Morpho 6.5% vs Spark 7.0% → gap = -0.5 (Spark лучше)."""
        a = _make_adapter(apy=7.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), -0.5)

    def test_gap_zero_equal(self):
        """Morpho 6.5% vs Spark 6.5% → gap = 0.0."""
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.0)

    def test_custom_morpho_apy_higher(self):
        """Кастомный morpho_apy=8.0 vs Spark 5.5% → gap = 2.5."""
        a = _make_adapter(apy=5.5)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=8.0), 2.5)

    def test_custom_morpho_apy_lower(self):
        """Кастомный morpho_apy=4.0 vs Spark 5.5% → gap = -1.5."""
        a = _make_adapter(apy=5.5)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=4.0), -1.5)

    def test_gap_with_fallback_apy(self):
        """Fallback APY=5.5 → gap = 6.5 - 5.5 = 1.0."""
        a = _no_file()
        self.assertAlmostEqual(a.vs_morpho_gap(), 1.0)

    def test_gap_returns_float(self):
        a = _default()
        self.assertIsInstance(a.vs_morpho_gap(), float)

    def test_gap_symmetry(self):
        """gap(morpho=6.5) = -gap при spark=6.5+delta, morpho=6.5-delta."""
        a1 = _make_adapter(apy=7.5)
        a2 = _make_adapter(apy=5.5)
        # gap1 = 6.5 - 7.5 = -1.0; gap2 = 6.5 - 5.5 = +1.0
        self.assertAlmostEqual(a1.vs_morpho_gap() + a2.vs_morpho_gap(), 0.0)

    def test_gap_large_positive(self):
        """Morpho 20% vs Spark 5.5% → gap = 14.5."""
        a = _make_adapter(apy=5.5)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=20.0), 14.5)

    def test_gap_default_parameter_is_6_5(self):
        """Дефолтный morpho_apy должен быть 6.5."""
        a = _make_adapter(apy=0.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 6.5)


# ════════════════════════════════════════════════════════════════════════════
# 6. TestSparkAllocate — paper trading аллокация
# ════════════════════════════════════════════════════════════════════════════

class TestSparkAllocate(unittest.TestCase):
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
        self.assertEqual(result["protocol"], "spark_susds")

    def test_allocate_result_has_vault(self):
        a = _default()
        result = a.allocate(1000.0)
        self.assertEqual(
            result["vault"],
            "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD",
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
# 7. TestSparkWithdraw — paper trading вывод
# ════════════════════════════════════════════════════════════════════════════

class TestSparkWithdraw(unittest.TestCase):
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
        self.assertEqual(result["protocol"], "spark_susds")

    def test_withdraw_result_has_vault(self):
        a = _default()
        a.allocate(10000.0)
        result = a.withdraw(1000.0)
        self.assertEqual(
            result["vault"],
            "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD",
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
# 8. TestSparkToDict — сериализация
# ════════════════════════════════════════════════════════════════════════════

class TestSparkToDict(unittest.TestCase):
    """8 тестов: все ключевые поля to_dict(), gsm_compliant, eligible, protocol, tier."""

    def test_to_dict_has_protocol(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(d["protocol"], "spark_susds")

    def test_to_dict_has_tier(self):
        a = _default()
        d = a.to_dict()
        self.assertEqual(d["tier"], "T1")

    def test_to_dict_has_gsm_compliant_false(self):
        """gsm_hours=0 → gsm_compliant=False в to_dict."""
        a = _make_adapter(gsm_hours=0)
        d = a.to_dict()
        self.assertIn("gsm_compliant", d)
        self.assertFalse(d["gsm_compliant"])

    def test_to_dict_has_gsm_compliant_true(self):
        """gsm_hours=72 → gsm_compliant=True в to_dict."""
        a = _make_adapter(gsm_hours=72)
        d = a.to_dict()
        self.assertTrue(d["gsm_compliant"])

    def test_to_dict_has_eligible_false(self):
        """gsm=0 → eligible=False."""
        a = _default()
        d = a.to_dict()
        self.assertIn("eligible", d)
        self.assertFalse(d["eligible"])

    def test_to_dict_has_eligible_true(self):
        """gsm=72, APY=5.5 → eligible=True."""
        a = _eligible()
        d = a.to_dict()
        self.assertTrue(d["eligible"])

    def test_to_dict_all_required_keys_present(self):
        required = {
            "protocol", "protocol_name", "vault_address", "tier", "t1_cap",
            "chain", "chain_id", "asset", "apy_pct", "risk_score",
            "exit_latency_hours", "tvl_usd", "min_apy_pct", "max_apy_pct",
            "gsm_compliant", "eligible", "allocated",
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
            "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD",
        )


# ════════════════════════════════════════════════════════════════════════════
# Точка входа
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
