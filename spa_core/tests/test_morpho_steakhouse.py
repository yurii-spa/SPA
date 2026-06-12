#!/usr/bin/env python3
"""Тесты MorphoSteakhouseAdapter — MP-355.

Покрываем:
  - идентичность / тир T1 / метаданные
  - чтение APY из JSON и fallback
  - логику switch_recommendation (порог 50 bps)
  - health_check
  - to_dict структура
  - allocate / withdraw (paper trading)
  - get_yield_info

Запуск:
    python3 -m pytest spa_core/tests/test_morpho_steakhouse.py -q
    python3 -m unittest spa_core.tests.test_morpho_steakhouse -v
    python3 spa_core/tests/test_morpho_steakhouse.py
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
from spa_core.adapters.morpho_steakhouse_adapter import MorphoSteakhouseAdapter


# ── вспомогательные фабрики ──────────────────────────────────────────────────

def _adapter(apy: float | None = None, missing_field: bool = False) -> MorphoSteakhouseAdapter:
    """Создаёт адаптер с временным data_dir.

    apy=None → поле morpho_steakhouse.apy отсутствует (тест fallback)
    missing_field=True → секция morpho_steakhouse отсутствует полностью
    """
    tmp = tempfile.mkdtemp()
    content: dict = {"morpho_steakhouse": {}}
    if missing_field:
        content = {}
    elif apy is not None:
        content["morpho_steakhouse"]["apy"] = apy
    # иначе — поле apy отсутствует → fallback
    (Path(tmp) / "adapter_status.json").write_text(json.dumps(content), encoding="utf-8")
    return MorphoSteakhouseAdapter(data_dir=tmp)


def _default() -> MorphoSteakhouseAdapter:
    """Адаптер с полем apy=6.5 в JSON."""
    return _adapter(apy=6.5)


def _fallback() -> MorphoSteakhouseAdapter:
    """Адаптер без поля apy в JSON → должен отдать fallback 6.5%."""
    return _adapter(apy=None)


def _no_file() -> MorphoSteakhouseAdapter:
    """Адаптер с несуществующим data_dir → fallback."""
    return MorphoSteakhouseAdapter(data_dir="/nonexistent_spa_test_dir_xyz")


# ════════════════════════════════════════════════════════════════════════════
# 1. Идентичность / тир / метаданные
# ════════════════════════════════════════════════════════════════════════════

class TestIdentity(unittest.TestCase):

    def test_protocol_key(self):
        self.assertEqual(MorphoSteakhouseAdapter.PROTOCOL, "morpho_steakhouse")

    def test_vault_address(self):
        self.assertEqual(
            MorphoSteakhouseAdapter.VAULT_ADDRESS,
            "0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB",
        )

    def test_vault_name(self):
        self.assertEqual(MorphoSteakhouseAdapter.VAULT_NAME, "Steakhouse USDC")

    def test_tier_constant_is_t1(self):
        self.assertEqual(MorphoSteakhouseAdapter.TIER, "T1")

    def test_instance_tier_is_t1(self):
        self.assertEqual(_default().tier, "T1")

    def test_t1_cap_is_040(self):
        self.assertAlmostEqual(MorphoSteakhouseAdapter.T1_CAP, 0.40)

    def test_is_base_adapter_subclass(self):
        self.assertIsInstance(_default(), BaseAdapter)

    def test_default_asset_usdc(self):
        adapter = MorphoSteakhouseAdapter()
        self.assertEqual(adapter.asset, "USDC")

    def test_custom_asset(self):
        adapter = MorphoSteakhouseAdapter(asset="USDT")
        self.assertEqual(adapter.asset, "USDT")

    def test_quick_win_flag(self):
        self.assertTrue(MorphoSteakhouseAdapter.QUICK_WIN)
        self.assertTrue(_default().QUICK_WIN)

    def test_bps_gain_200(self):
        self.assertEqual(MorphoSteakhouseAdapter.BPS_GAIN, 200)

    def test_exit_latency_zero(self):
        self.assertEqual(MorphoSteakhouseAdapter.EXIT_LATENCY_HOURS, 0.0)

    def test_risk_score_is_float(self):
        self.assertIsInstance(MorphoSteakhouseAdapter.RISK_SCORE, float)

    def test_risk_score_range(self):
        score = MorphoSteakhouseAdapter.RISK_SCORE
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)


# ════════════════════════════════════════════════════════════════════════════
# 2. APY — чтение из JSON и fallback
# ════════════════════════════════════════════════════════════════════════════

class TestApySource(unittest.TestCase):

    def test_apy_reads_from_json_when_field_present(self):
        """При наличии поля morpho_steakhouse.apy — берётся из JSON."""
        adapter = _adapter(apy=7.2)
        self.assertAlmostEqual(adapter.get_apy_pct(), 7.2)

    def test_apy_fallback_when_field_missing(self):
        """Без поля apy в JSON — используется FALLBACK_APY_PCT."""
        adapter = _fallback()
        self.assertAlmostEqual(adapter.get_apy_pct(), MorphoSteakhouseAdapter.FALLBACK_APY_PCT)

    def test_apy_fallback_value_is_6_5(self):
        """Fallback точно равен 6.5%."""
        self.assertAlmostEqual(MorphoSteakhouseAdapter.FALLBACK_APY_PCT, 6.5)
        self.assertAlmostEqual(_fallback().get_apy_pct(), 6.5)

    def test_apy_fallback_when_json_missing(self):
        """Файл adapter_status.json отсутствует → fallback."""
        self.assertAlmostEqual(_no_file().get_apy_pct(), 6.5)

    def test_apy_fallback_when_json_corrupt(self):
        """Битый JSON → fallback, без исключения."""
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "adapter_status.json").write_text("NOT JSON{{", encoding="utf-8")
        adapter = MorphoSteakhouseAdapter(data_dir=tmp)
        # Не должно бросать исключение
        result = adapter.get_apy_pct()
        self.assertAlmostEqual(result, 6.5)

    def test_apy_fallback_when_section_missing(self):
        """Секция morpho_steakhouse отсутствует → fallback."""
        adapter = _adapter(apy=None, missing_field=True)
        self.assertAlmostEqual(adapter.get_apy_pct(), 6.5)

    def test_apy_fallback_when_field_not_numeric_string(self):
        """Поле apy='garbage' → fallback."""
        tmp = tempfile.mkdtemp()
        content = {"morpho_steakhouse": {"apy": "garbage"}}
        (Path(tmp) / "adapter_status.json").write_text(json.dumps(content), encoding="utf-8")
        adapter = MorphoSteakhouseAdapter(data_dir=tmp)
        self.assertAlmostEqual(adapter.get_apy_pct(), 6.5)

    def test_apy_fallback_when_field_is_null(self):
        """Поле apy=null → fallback."""
        tmp = tempfile.mkdtemp()
        content = {"morpho_steakhouse": {"apy": None}}
        (Path(tmp) / "adapter_status.json").write_text(json.dumps(content), encoding="utf-8")
        adapter = MorphoSteakhouseAdapter(data_dir=tmp)
        self.assertAlmostEqual(adapter.get_apy_pct(), 6.5)

    def test_get_apy_decimal_from_pct(self):
        """get_apy() возвращает десятичную дробь (pct / 100)."""
        adapter = _adapter(apy=6.5)
        self.assertAlmostEqual(adapter.get_apy(), 0.065)

    def test_get_apy_decimal_fallback(self):
        """get_apy() fallback = 0.065."""
        self.assertAlmostEqual(_fallback().get_apy(), 0.065)

    def test_get_apy_pct_returns_float(self):
        """get_apy_pct() всегда возвращает float."""
        self.assertIsInstance(_default().get_apy_pct(), float)
        self.assertIsInstance(_fallback().get_apy_pct(), float)
        self.assertIsInstance(_no_file().get_apy_pct(), float)

    def test_custom_apy_from_json(self):
        """Кастомное значение APY (5.0) читается корректно."""
        adapter = _adapter(apy=5.0)
        self.assertAlmostEqual(adapter.get_apy_pct(), 5.0)
        self.assertAlmostEqual(adapter.get_apy(), 0.05)


# ════════════════════════════════════════════════════════════════════════════
# 3. Switch recommendation
# ════════════════════════════════════════════════════════════════════════════

class TestSwitchRecommendation(unittest.TestCase):

    def test_switch_recommended_default_true(self):
        """6.5% > 3.2% + 0.5% = 3.7% → рекомендуем switch."""
        self.assertTrue(_default().switch_recommended())

    def test_switch_not_recommended_when_morpho_below_threshold(self):
        """Если Morpho APY не превышает Aave + 50 bps — switch не рекомендуется."""
        # Morpho = 3.4%, Aave = 3.2% → 3.4% <= 3.2% + 0.5% = 3.7% → False
        adapter = _adapter(apy=3.4)
        self.assertFalse(adapter.switch_recommended(aave_apy_pct=3.2))

    def test_switch_not_recommended_at_exact_threshold(self):
        """При Morpho = Aave + 50 bps — не превышает (строго >), switch = False."""
        # Morpho = 3.7%, Aave = 3.2%, threshold = 3.2 + 0.5 = 3.7 → 3.7 > 3.7 = False
        adapter = _adapter(apy=3.7)
        self.assertFalse(adapter.switch_recommended(aave_apy_pct=3.2))

    def test_switch_recommended_just_above_threshold(self):
        """Morpho чуть выше порога → True."""
        adapter = _adapter(apy=3.71)
        self.assertTrue(adapter.switch_recommended(aave_apy_pct=3.2))

    def test_switch_recommended_custom_aave_apy(self):
        """switch_recommended принимает кастомный Aave APY."""
        adapter = _adapter(apy=5.0)
        # Aave 4.8 + 0.5 = 5.3 → 5.0 > 5.3 = False
        self.assertFalse(adapter.switch_recommended(aave_apy_pct=4.8))
        # Aave 4.0 + 0.5 = 4.5 → 5.0 > 4.5 = True
        self.assertTrue(adapter.switch_recommended(aave_apy_pct=4.0))

    def test_switch_threshold_is_50bps(self):
        """Порог переключения = 50 bps."""
        self.assertEqual(MorphoSteakhouseAdapter.SWITCH_THRESHOLD_BPS, 50)

    def test_switch_gain_pct_positive(self):
        """Текущая конфигурация даёт положительный выигрыш."""
        self.assertGreater(_default().switch_gain_pct(), 0)

    def test_switch_gain_pct_calculation(self):
        """switch_gain_pct = morpho_apy_pct - aave_benchmark."""
        adapter = _adapter(apy=6.5)
        expected = 6.5 - MorphoSteakhouseAdapter.AAVE_MAINNET_APY_PCT  # 3.3
        self.assertAlmostEqual(adapter.switch_gain_pct(), expected)

    def test_switch_gain_pct_custom_aave(self):
        """switch_gain_pct с кастомным Aave APY."""
        adapter = _adapter(apy=6.0)
        self.assertAlmostEqual(adapter.switch_gain_pct(aave_apy_pct=4.0), 2.0)

    def test_aave_benchmark_constant(self):
        """Эталонный Aave APY = 3.2%."""
        self.assertAlmostEqual(MorphoSteakhouseAdapter.AAVE_MAINNET_APY_PCT, 3.2)


# ════════════════════════════════════════════════════════════════════════════
# 4. health_check
# ════════════════════════════════════════════════════════════════════════════

class TestHealthCheck(unittest.TestCase):

    def test_health_check_returns_dict(self):
        self.assertIsInstance(_default().health_check(), dict)

    def test_health_check_status_ok_with_valid_apy(self):
        hc = _default().health_check()
        self.assertEqual(hc["status"], "ok")

    def test_health_check_contains_required_keys(self):
        hc = _default().health_check()
        for key in ("status", "protocol", "vault", "tier", "apy_pct",
                    "quick_win", "switch_recommended"):
            self.assertIn(key, hc, f"Ключ '{key}' отсутствует в health_check")

    def test_health_check_protocol_key(self):
        hc = _default().health_check()
        self.assertEqual(hc["protocol"], "morpho_steakhouse")

    def test_health_check_vault_address(self):
        hc = _default().health_check()
        self.assertEqual(hc["vault"], MorphoSteakhouseAdapter.VAULT_ADDRESS)

    def test_health_check_tier_t1(self):
        hc = _default().health_check()
        self.assertEqual(hc["tier"], "T1")

    def test_health_check_quick_win_true(self):
        hc = _default().health_check()
        self.assertTrue(hc["quick_win"])

    def test_health_check_switch_recommended_true(self):
        hc = _default().health_check()
        self.assertTrue(hc["switch_recommended"])

    def test_health_check_apy_reasonable(self):
        hc = _default().health_check()
        apy = hc["apy_pct"]
        self.assertGreater(apy, 0)
        self.assertLess(apy, 50)


# ════════════════════════════════════════════════════════════════════════════
# 5. to_dict структура
# ════════════════════════════════════════════════════════════════════════════

class TestToDict(unittest.TestCase):

    def _d(self) -> dict:
        return _default().to_dict()

    def test_to_dict_returns_dict(self):
        self.assertIsInstance(self._d(), dict)

    def test_to_dict_has_protocol(self):
        self.assertEqual(self._d()["protocol"], "morpho_steakhouse")

    def test_to_dict_has_vault_address(self):
        self.assertEqual(self._d()["vault_address"], MorphoSteakhouseAdapter.VAULT_ADDRESS)

    def test_to_dict_has_vault_name(self):
        self.assertEqual(self._d()["vault_name"], "Steakhouse USDC")

    def test_to_dict_tier_is_t1(self):
        self.assertEqual(self._d()["tier"], "T1")

    def test_to_dict_t1_cap(self):
        self.assertAlmostEqual(self._d()["t1_cap"], 0.40)

    def test_to_dict_quick_win_true(self):
        self.assertTrue(self._d()["quick_win"])

    def test_to_dict_bps_gain_200(self):
        self.assertEqual(self._d()["bps_gain"], 200)

    def test_to_dict_strategy_note_present(self):
        note = self._d()["strategy_note"]
        self.assertIsInstance(note, str)
        self.assertGreater(len(note), 10)

    def test_to_dict_strategy_note_content(self):
        note = self._d()["strategy_note"]
        self.assertIn("Quick Win #1", note)
        self.assertIn("Morpho Steakhouse", note)
        self.assertIn("+$1,650/yr", note)

    def test_to_dict_apy_pct_matches_get_apy_pct(self):
        adapter = _default()
        self.assertAlmostEqual(adapter.to_dict()["apy_pct"], adapter.get_apy_pct())

    def test_to_dict_apy_decimal_consistent(self):
        d = self._d()
        self.assertAlmostEqual(d["apy_decimal"], d["apy_pct"] / 100.0)

    def test_to_dict_aave_benchmark(self):
        self.assertAlmostEqual(self._d()["aave_benchmark_apy_pct"], 3.2)

    def test_to_dict_switch_recommended_bool(self):
        self.assertIsInstance(self._d()["switch_recommended"], bool)

    def test_to_dict_allocated_zero_initially(self):
        self.assertAlmostEqual(self._d()["allocated"], 0.0)


# ════════════════════════════════════════════════════════════════════════════
# 6. allocate / withdraw (paper trading)
# ════════════════════════════════════════════════════════════════════════════

class TestAllocateWithdraw(unittest.TestCase):

    def test_allocate_positive_capital_ok(self):
        result = _default().allocate(50_000)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["amount"], 50_000)

    def test_allocate_accumulates(self):
        adapter = _default()
        adapter.allocate(30_000)
        adapter.allocate(20_000)
        self.assertAlmostEqual(adapter._allocated, 50_000)

    def test_allocate_zero_returns_error(self):
        result = _default().allocate(0)
        self.assertEqual(result["status"], "error")

    def test_allocate_negative_returns_error(self):
        result = _default().allocate(-1000)
        self.assertEqual(result["status"], "error")

    def test_allocate_result_has_vault(self):
        result = _default().allocate(10_000)
        self.assertIn("vault", result)
        self.assertEqual(result["vault"], MorphoSteakhouseAdapter.VAULT_ADDRESS)

    def test_withdraw_reduces_balance(self):
        adapter = _default()
        adapter.allocate(50_000)
        result = adapter.withdraw(20_000)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(adapter._allocated, 30_000)

    def test_withdraw_exact_amount(self):
        adapter = _default()
        adapter.allocate(50_000)
        result = adapter.withdraw(50_000)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(adapter._allocated, 0.0)

    def test_withdraw_too_much_returns_error(self):
        adapter = _default()
        adapter.allocate(10_000)
        result = adapter.withdraw(20_000)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "insufficient_balance")

    def test_withdraw_zero_returns_error(self):
        result = _default().withdraw(0)
        self.assertEqual(result["status"], "error")

    def test_withdraw_negative_returns_error(self):
        result = _default().withdraw(-500)
        self.assertEqual(result["status"], "error")


# ════════════════════════════════════════════════════════════════════════════
# 7. get_yield_info
# ════════════════════════════════════════════════════════════════════════════

class TestGetYieldInfo(unittest.TestCase):

    def test_get_yield_info_returns_yield_info(self):
        self.assertIsInstance(_default().get_yield_info(), YieldInfo)

    def test_get_yield_info_protocol(self):
        self.assertEqual(_default().get_yield_info().protocol, "morpho_steakhouse")

    def test_get_yield_info_asset_usdc(self):
        self.assertEqual(_default().get_yield_info().asset, "USDC")

    def test_get_yield_info_tier_t1(self):
        self.assertEqual(_default().get_yield_info().tier, "T1")

    def test_get_yield_info_apy_is_decimal(self):
        info = _default().get_yield_info()
        self.assertAlmostEqual(info.apy, 0.065)

    def test_get_yield_info_risk_score_valid(self):
        info = _default().get_yield_info()
        self.assertIsInstance(info.risk_score, float)
        self.assertGreater(info.risk_score, 0.0)
        self.assertLess(info.risk_score, 1.0)

    def test_get_yield_info_exit_latency_zero(self):
        self.assertEqual(_default().get_yield_info().exit_latency_hours, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
