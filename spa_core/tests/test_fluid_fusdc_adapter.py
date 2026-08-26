"""Tests for FluidFUSDCAdapter (MP-377) — 85+ тестов.

Покрывает:
  TestFluidInit       (10) — константы, protocol, tier, addresses, risk_score
  TestFluidAPY        (15) — raw_apy, fallback, spike detection, normalization
  TestFluidSpike      (12) — is_spike True/False, граничные значения
  TestFluidGSM        (10) — gsm=0 → False, gsm=48 → True, gsm=47 → False
  TestFluidEligibility(10) — gsm+apy matrix все комбинации
  TestFluidHealthCheck (8) — "ok", "spike", "degraded" для разных APY
  TestFluidVsOthers   (10) — vs_morpho_gap, vs_spark_gap, sign check
  TestFluidAllocate   (10) — нормальный, нулевой, negative→ValueError
  TestFluidToDict     (10) — все ключи включая spike_detected, gsm_compliant
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.adapters.fluid_fusdc_adapter import FluidFUSDCAdapter


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

from spa_core.tests._freshness import ts


def _make_data_dir(apy: float = 6.5, gsm_hours: float = 0,
                   live_tvl: bool = True) -> Path:
    """Creates a temporary directory with adapter_status.json for testing.

    ADR-137: ``live_tvl`` управляет ВТОРОЙ половиной общего ключа допуска —
    наблюдался ли размер пула. Литерал наблюдением не считается, поэтому
    решает ``tvl_source == "live"`` (ADR-064), а не величина числа. По
    умолчанию True: подавляющее большинство тестов файла проверяют не допуск,
    и им нужен рабочий адаптер, а не отказ по несмежной причине.
    """
    tmp = tempfile.mkdtemp()
    status = {
        "fluid_fusdc": {
            "apy": apy,
            "tier": "T2",
            "tvl_usd": 2_000_000_000,
            **({"tvl_source": "live"} if live_tvl else {}),
            "chain": "ethereum",
            "vault_address": "0x9Fb7b4477576Fe5B32be4C1843aFB1e55F251B33",
            "gsm_hours": gsm_hours,
            # ИЗМЕНЕНИЕ ФИКСТУРЫ (2026-08-05, правило 16 — обоснование):
            # гейт GSM теперь проверяет возраст подтверждения наравне со
            # значением (карточка agent-gsm-hours-producer п.3) — остановившийся
            # производитель не должен держать ворота открытыми. Значение и
            # отметка времени в проде пишутся всегда вместе, поэтому фикстура без
            # отметки описывала несуществующее состояние. Утверждения тестов НЕ
            # менялись; проверки протухания — в test_gsm_hours_producer.py.
            "gsm_hours_as_of": ts(1),
            "status": "research",
            "note": "T2 cap 20% single, GSM compliance gate required",
        }
    }
    path = Path(tmp) / "adapter_status.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(status, fh)
    return Path(tmp)


def _make_adapter(apy: float = 6.5, gsm_hours: float = 0,
                  live_tvl: bool = True) -> FluidFUSDCAdapter:
    return FluidFUSDCAdapter(
        data_dir=_make_data_dir(apy=apy, gsm_hours=gsm_hours, live_tvl=live_tvl))


def _make_empty_data_dir() -> Path:
    """Creates a temporary directory WITHOUT adapter_status.json."""
    return Path(tempfile.mkdtemp())


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidInit — 10 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidInit(unittest.TestCase):
    """Constants, protocol identity, tier, addresses, risk_score."""

    def setUp(self):
        self.adapter = FluidFUSDCAdapter()

    def test_protocol_key(self):
        self.assertEqual(self.adapter.PROTOCOL, "fluid_fusdc")

    def test_protocol_name(self):
        self.assertEqual(self.adapter.PROTOCOL_NAME, "Fluid Protocol fUSDC")

    def test_vault_address(self):
        self.assertEqual(
            self.adapter.VAULT_ADDRESS,
            "0x9Fb7b4477576Fe5B32be4C1843aFB1e55F251B33",
        )

    def test_tier_class(self):
        self.assertEqual(self.adapter.TIER, "T2")

    def test_tier_instance(self):
        self.assertEqual(self.adapter.tier, "T2")

    def test_t2_cap_single(self):
        self.assertAlmostEqual(self.adapter.T2_CAP_SINGLE, 0.20)

    def test_t2_cap_total(self):
        self.assertAlmostEqual(self.adapter.T2_CAP_TOTAL, 0.50)

    def test_risk_score(self):
        self.assertAlmostEqual(self.adapter.RISK_SCORE, 0.38)

    def test_chain(self):
        self.assertEqual(self.adapter.CHAIN, "ethereum")

    def test_chain_id(self):
        self.assertEqual(self.adapter.CHAIN_ID, 1)


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidAPY — 15 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidAPY(unittest.TestCase):
    """Raw APY reading, fallback, spike normalization, get_apy, get_apy_pct."""

    def test_get_raw_apy_normal(self):
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.get_raw_apy(), 6.5)

    def test_get_raw_apy_low(self):
        a = _make_adapter(apy=3.1)
        self.assertAlmostEqual(a.get_raw_apy(), 3.1)

    def test_get_raw_apy_high_before_spike(self):
        a = _make_adapter(apy=14.9)
        self.assertAlmostEqual(a.get_raw_apy(), 14.9)

    def test_get_raw_apy_spike(self):
        # Raw should return spike value unchanged
        a = _make_adapter(apy=20.0)
        self.assertAlmostEqual(a.get_raw_apy(), 20.0)

    def test_get_raw_apy_fallback_missing_file(self):
        # ADR-063: раньше здесь ожидалась подстановка DEFAULT_APY_PCT при
        # отсутствии данных. Это прямо противоречило правилу адаптеров
        # («никаких fake-fallback'ов: нет данных ⇒ None»): выдуманное число
        # уходило потребителям с меткой live и ранжировало money-path капитал.
        # Проверка та же — «что будет без данных», ожидание честное.
        # Изменение теста одобрено владельцем 2026-08-02 (инвариант 16).
        a = FluidFUSDCAdapter(data_dir=_make_empty_data_dir())
        self.assertIsNone(a.get_raw_apy())
    def test_get_raw_apy_fallback_value(self):
        self.assertAlmostEqual(FluidFUSDCAdapter.DEFAULT_APY_PCT, 6.5)

    def test_get_apy_normal_passthrough(self):
        a = _make_adapter(apy=7.0)
        self.assertAlmostEqual(a.get_apy(), 7.0)

    def test_get_apy_spike_normalized(self):
        a = _make_adapter(apy=20.0)
        self.assertAlmostEqual(a.get_apy(), FluidFUSDCAdapter.SPIKE_NORM_PCT)

    def test_get_apy_spike_norm_value(self):
        self.assertAlmostEqual(FluidFUSDCAdapter.SPIKE_NORM_PCT, 9.0)

    def test_get_apy_pct_equals_get_apy(self):
        a = _make_adapter(apy=5.5)
        self.assertAlmostEqual(a.get_apy_pct(), a.get_apy())

    def test_get_apy_pct_spike(self):
        a = _make_adapter(apy=18.0)
        self.assertAlmostEqual(a.get_apy_pct(), 9.0)

    def test_get_apy_min_boundary(self):
        a = _make_adapter(apy=3.0)
        self.assertAlmostEqual(a.get_apy(), 3.0)

    def test_get_apy_max_boundary(self):
        a = _make_adapter(apy=10.0)
        self.assertAlmostEqual(a.get_apy(), 10.0)

    def test_get_apy_returns_float(self):
        a = _make_adapter(apy=6.5)
        self.assertIsInstance(a.get_apy(), float)

    def test_get_apy_fallback_is_float(self):
        # ADR-063: раньше здесь ожидалась подстановка DEFAULT_APY_PCT при
        # отсутствии данных. Это прямо противоречило правилу адаптеров
        # («никаких fake-fallback'ов: нет данных ⇒ None»): выдуманное число
        # уходило потребителям с меткой live и ранжировало money-path капитал.
        # Проверка та же — «что будет без данных», ожидание честное.
        # Изменение теста одобрено владельцем 2026-08-02 (инвариант 16).
        a = FluidFUSDCAdapter(data_dir=_make_empty_data_dir())
        self.assertIsNone(a.get_apy())


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidSpike — 12 tests
# ─────────────────────────────────────────────────────────────────────────────
class TestFluidSpike(unittest.TestCase):
    """is_spike detection: boundary values, explicit apy argument."""

    def test_spike_false_normal(self):
        a = _make_adapter(apy=6.5)
        self.assertFalse(a.is_spike())

    def test_spike_false_below_threshold(self):
        a = _make_adapter(apy=14.9)
        self.assertFalse(a.is_spike())

    def test_spike_false_at_exact_threshold(self):
        # 15.0 exact → NOT a spike (strict >)
        a = _make_adapter(apy=15.0)
        self.assertFalse(a.is_spike())

    def test_spike_true_just_above_threshold(self):
        a = _make_adapter(apy=15.001)
        self.assertTrue(a.is_spike())

    def test_spike_true_high(self):
        a = _make_adapter(apy=22.0)
        self.assertTrue(a.is_spike())

    def test_spike_explicit_arg_false(self):
        a = _make_adapter()
        self.assertFalse(a.is_spike(apy=10.0))

    def test_spike_explicit_arg_true(self):
        a = _make_adapter()
        self.assertTrue(a.is_spike(apy=15.5))

    def test_spike_explicit_boundary_exact(self):
        a = _make_adapter()
        self.assertFalse(a.is_spike(apy=15.0))

    def test_spike_threshold_constant(self):
        self.assertAlmostEqual(FluidFUSDCAdapter.SPIKE_THRESHOLD_PCT, 15.0)

    def test_spike_false_zero(self):
        a = _make_adapter()
        self.assertFalse(a.is_spike(apy=0.0))

    def test_spike_false_negative(self):
        a = _make_adapter()
        self.assertFalse(a.is_spike(apy=-1.0))

    def test_spike_returns_bool(self):
        a = _make_adapter(apy=20.0)
        result = a.is_spike()
        self.assertIsInstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidGSM — 10 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidGSMGateRemoved(unittest.TestCase):
    """Гейт «48 часов» СНЯТ — решение владельца 2026-08-25, вариант A (ADR-137).

    ПРАВКА НАМЕРЕННАЯ (инвариант #16). Раньше здесь было десять тестов на пороге
    48 часов. Порог был правилом **Maker/Sky** (число из контракта Maker
    ``DSPause``), а не Fluid: собственную задержку управления Fluid мы не читали
    никогда — ни в коде, ни в данных её нет. Проверка поэтому отвечала «не
    подтверждено» ВСЕГДА, и протокол на $150.3M живого размера при 4.82 %
    годовых был закрыт для капитала не по риску, а по чужому имени правила.
    Владелец снял её как неприменимую.

    Утверждения не выброшены, а ЗАМЕНЕНЫ на утверждения о снятии: тесты ниже
    краснеют, если гейт вернётся молча — в любом из двух видов, которыми такое
    обычно возвращается.
    """

    def test_the_alien_gate_is_gone_from_the_class(self):
        """Не «возвращает True», а ОТСУТСТВУЕТ.

        Оставить метод, всегда отвечающий True, было бы литералом ``True`` в
        одежде проверки риска — ровно тот класс дефекта, который описан в
        ``status_reader.tvl_floor_verdict``. Аллокатор к тому же спрашивает гейт
        через ``hasattr``: метод-пустышка означал бы «гейт есть и пройден».
        """
        self.assertFalse(hasattr(FluidFUSDCAdapter, "is_gsm_compliant"),
                         "чужой гейт вернулся на адаптер")

    def test_gsm_hours_in_data_changes_nothing(self):
        """Даже если производитель снова начнёт писать поле — оно не судит Fluid."""
        for hours in (0, 47, 48, 1000):
            with self.subTest(gsm_hours=hours):
                a = _make_adapter(apy=6.5, gsm_hours=hours)
                self.assertTrue(a.is_eligible(),
                                f"gsm_hours={hours} всё ещё влияет на допуск")

    def test_report_names_the_gate_as_not_applicable(self):
        """Инв. #17: исчезнувшее поле читатель принял бы за «проверка прошла»."""
        d = _make_adapter().to_dict()
        self.assertIn("gsm_gate", d)
        self.assertIn("not_applicable", d["gsm_gate"])
        self.assertNotIn("gsm_compliant", d,
                         "старый ключ вернулся — читатель решит, что гейт жив")


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidEligibility — 10 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidEligibility(unittest.TestCase):
    """Общий ключ допуска (ADR-137): живая доходность И живой размер пула.

    ПРАВКА НАМЕРЕННАЯ (инв. #16): матрица «GSM × APY» заменена матрицей
    «живой APY × живой TVL». Ни одно утверждение не ослаблено — без наблюдения
    Fluid по-прежнему НЕ финансируется; снят чужой гейт, а не осторожность.
    """

    def test_not_eligible_apy_too_low(self):
        self.assertFalse(_make_adapter(apy=2.0).is_eligible())

    def test_not_eligible_apy_too_high(self):
        # 12.0 > MAX_APY=10.0, но ≤ 15.0 spike → get_apy() = 12.0 → не eligible
        self.assertFalse(_make_adapter(apy=12.0).is_eligible())

    def test_eligible_apy_in_range_with_live_tvl(self):
        self.assertTrue(_make_adapter(apy=6.5).is_eligible())

    def test_eligible_at_min_apy(self):
        self.assertTrue(_make_adapter(apy=3.0).is_eligible())

    def test_eligible_at_max_apy(self):
        self.assertTrue(_make_adapter(apy=10.0).is_eligible())

    def test_spike_apy_normalised_into_range_is_eligible(self):
        # raw 20.0 > 15.0 spike → get_apy() = 9.0 ∈ [3.0, 10.0] → eligible
        self.assertTrue(_make_adapter(apy=20.0).is_eligible())

    def test_not_eligible_without_live_apy(self):
        """Fail-CLOSED: нет наблюдения доходности ⇒ капитал не идёт."""
        a = FluidFUSDCAdapter(data_dir=_make_empty_data_dir())
        self.assertIsNone(a.get_apy())
        self.assertFalse(a.is_eligible())

    def test_not_eligible_without_live_tvl(self):
        """Вторая половина ключа. Литерал $2 млрд наблюдением НЕ является.

        Тот же дефект, что у ``moonwell_base``: константа класса $500M против
        $2.6M наблюдаемых. Размер пула обязан быть НАБЛЮДЁН (``tvl_source ==
        "live"``, ADR-064), иначе допуска нет.
        """
        a = _make_adapter(apy=6.5, live_tvl=False)
        self.assertIsNotNone(a.get_apy(), "APY должен быть живым — предмет теста в TVL")
        self.assertFalse(a.is_eligible())
        self.assertEqual(a.TVL_USD, 2_000_000_000,
                         "константа на месте — и всё равно не открывает ворота")


    def test_eligible_returns_bool(self):
        a = _make_adapter(apy=6.5, gsm_hours=48)
        self.assertIsInstance(a.is_eligible(), bool)

    def test_not_eligible_empty_file(self):
        a = FluidFUSDCAdapter(data_dir=_make_empty_data_dir())
        # gsm_hours=0 by default → not gsm_compliant → not eligible
        self.assertFalse(a.is_eligible())


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidHealthCheck — 8 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidHealthCheck(unittest.TestCase):
    """health_check() returns 'ok', 'spike', or 'degraded'."""

    def test_health_ok_normal(self):
        a = _make_adapter(apy=6.5)
        self.assertEqual(a.health_check(), "ok")

    def test_health_ok_at_min(self):
        a = _make_adapter(apy=3.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_ok_at_max(self):
        a = _make_adapter(apy=10.0)
        self.assertEqual(a.health_check(), "ok")

    def test_health_spike(self):
        a = _make_adapter(apy=18.0)
        self.assertEqual(a.health_check(), "spike")

    def test_health_spike_just_above_threshold(self):
        a = _make_adapter(apy=15.001)
        self.assertEqual(a.health_check(), "spike")

    def test_health_degraded_too_low(self):
        a = _make_adapter(apy=1.5)
        self.assertEqual(a.health_check(), "degraded")

    def test_health_degraded_between_max_and_spike(self):
        # 12.0 is above MAX_APY (10.0) but ≤ SPIKE_THRESHOLD (15.0)
        a = _make_adapter(apy=12.0)
        self.assertEqual(a.health_check(), "degraded")

    def test_health_returns_string(self):
        a = _make_adapter(apy=6.5)
        self.assertIsInstance(a.health_check(), str)


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidVsOthers — 10 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidVsOthers(unittest.TestCase):
    """vs_morpho_gap, vs_spark_gap: sign and value checks."""

    def test_vs_morpho_gap_default_equal(self):
        # Fluid=6.5 default, Morpho=6.5 default → gap = 0
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.vs_morpho_gap(), 0.0)

    def test_vs_morpho_gap_fluid_better(self):
        # Fluid=7.5 > Morpho=6.5 → gap = 6.5 - 7.5 = -1.0 (negative = fluid better)
        a = _make_adapter(apy=7.5)
        self.assertAlmostEqual(a.vs_morpho_gap(), -1.0)

    def test_vs_morpho_gap_morpho_better(self):
        # Fluid=5.0 < Morpho=6.5 → gap = 6.5 - 5.0 = +1.5 (positive = morpho better)
        a = _make_adapter(apy=5.0)
        self.assertAlmostEqual(a.vs_morpho_gap(), 1.5)

    def test_vs_morpho_gap_custom_morpho(self):
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.vs_morpho_gap(morpho_apy=8.0), 1.5)

    def test_vs_morpho_gap_returns_float(self):
        a = _make_adapter(apy=6.5)
        self.assertIsInstance(a.vs_morpho_gap(), float)

    def test_vs_spark_gap_fluid_better(self):
        # Fluid=7.0 > Spark=5.5 → gap = 5.5 - 7.0 = -1.5 (negative = fluid better)
        a = _make_adapter(apy=7.0)
        self.assertAlmostEqual(a.vs_spark_gap(), -1.5)

    def test_vs_spark_gap_spark_better(self):
        # Fluid=4.0 < Spark=5.5 → gap = 5.5 - 4.0 = +1.5 (positive = spark better)
        a = _make_adapter(apy=4.0)
        self.assertAlmostEqual(a.vs_spark_gap(), 1.5)

    def test_vs_spark_gap_custom_spark(self):
        a = _make_adapter(apy=6.5)
        self.assertAlmostEqual(a.vs_spark_gap(spark_apy=6.5), 0.0)

    def test_vs_spark_gap_returns_float(self):
        a = _make_adapter(apy=6.5)
        self.assertIsInstance(a.vs_spark_gap(), float)

    def test_vs_morpho_sign_convention(self):
        # Negative gap means fluid is better (higher APY)
        a = _make_adapter(apy=8.0)
        gap = a.vs_morpho_gap(morpho_apy=6.5)
        self.assertLess(gap, 0)


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidAllocate — 10 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidAllocate(unittest.TestCase):
    """allocate() and withdraw() paper trading mechanics."""

    def test_allocate_positive(self):
        a = _make_adapter()
        result = a.allocate(10_000)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["amount"], 10_000)

    def test_allocate_accumulates(self):
        a = _make_adapter()
        a.allocate(10_000)
        a.allocate(5_000)
        self.assertAlmostEqual(a._allocated, 15_000)

    def test_allocate_zero_noop(self):
        a = _make_adapter()
        result = a.allocate(0)
        self.assertEqual(result["status"], "noop")
        self.assertAlmostEqual(a._allocated, 0.0)

    def test_allocate_negative_raises(self):
        a = _make_adapter()
        with self.assertRaises(ValueError):
            a.allocate(-1)

    def test_allocate_result_has_vault(self):
        a = _make_adapter()
        result = a.allocate(1000)
        self.assertIn("vault", result)
        self.assertEqual(result["vault"], FluidFUSDCAdapter.VAULT_ADDRESS)

    def test_withdraw_positive(self):
        a = _make_adapter()
        a.allocate(10_000)
        result = a.withdraw(3_000)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(a._allocated, 7_000)

    def test_withdraw_insufficient_balance(self):
        a = _make_adapter()
        a.allocate(5_000)
        result = a.withdraw(6_000)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "insufficient_balance")

    def test_withdraw_zero_error(self):
        a = _make_adapter()
        a.allocate(5_000)
        result = a.withdraw(0)
        self.assertEqual(result["status"], "error")

    def test_withdraw_negative_error(self):
        a = _make_adapter()
        a.allocate(5_000)
        result = a.withdraw(-100)
        self.assertEqual(result["status"], "error")

    def test_allocate_then_full_withdraw(self):
        a = _make_adapter()
        a.allocate(50_000)
        result = a.withdraw(50_000)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(a._allocated, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidToDict — 10 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidToDict(unittest.TestCase):
    """to_dict() contains all required keys and correct values."""

    REQUIRED_KEYS = [
        "protocol", "protocol_name", "vault_address", "chain", "chain_id",
        "tier", "t2_cap_total", "t2_cap_single", "asset", "risk_score",
        "exit_latency_hours", "tvl_usd", "raw_apy_pct", "apy_pct",
        "apy_decimal", "spike_detected", "spike_threshold_pct", "spike_norm_pct",
        # ADR-137: "gsm_compliant" заменён на "gsm_gate" (называет исход словом)
        # и добавлен "live_tvl_usd" — вторая половина общего ключа допуска.
        "gsm_gate", "live_tvl_usd", "eligible", "min_apy_pct", "max_apy_pct",
        "vs_morpho_gap", "vs_spark_gap", "health", "allocated",
    ]

    def setUp(self):
        self.adapter = _make_adapter(apy=6.5, gsm_hours=0)
        self.d = self.adapter.to_dict()

    def test_all_required_keys_present(self):
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, self.d, f"Missing key: {key}")

    def test_protocol_value(self):
        self.assertEqual(self.d["protocol"], "fluid_fusdc")

    def test_tier_value(self):
        self.assertEqual(self.d["tier"], "T2")

    def test_spike_detected_false_normal(self):
        self.assertFalse(self.d["spike_detected"])

    def test_spike_detected_true_high_apy(self):
        a = _make_adapter(apy=20.0)
        d = a.to_dict()
        self.assertTrue(d["spike_detected"])

    def test_gsm_gate_is_named_not_applicable(self):
        """ADR-137: гейта нет, и отчёт говорит это СЛОВОМ, а не молчанием."""
        self.assertIn("not_applicable", self.d["gsm_gate"])

    def test_live_tvl_is_none_when_not_observed(self):
        """Инв. #17: не наблюдался ≠ ноль."""
        d = _make_adapter(apy=6.5, live_tvl=False).to_dict()
        self.assertIsNone(d["live_tvl_usd"])
        self.assertFalse(d["eligible"])

    def test_eligible_false_without_live_observation(self):
        """ADR-137: правка НАМЕРЕННАЯ (инв. #16).

        Утверждение «не eligible» сохранено дословно, изменилась ПРИЧИНА:
        раньше её давал чужой гейт (``gsm_hours=0``), теперь — отсутствие
        наблюдения. Отказ по-прежнему обязан происходить, и он происходит.
        """
        a = FluidFUSDCAdapter(data_dir=_make_empty_data_dir())
        self.assertFalse(a.to_dict()["eligible"])

    def test_eligible_true_when_conditions_met(self):
        # Условия допуска теперь: живой APY в диапазоне И живой TVL.
        d = _make_adapter(apy=6.5).to_dict()
        self.assertTrue(d["eligible"])

    def test_apy_decimal_consistent(self):
        # apy_decimal = apy_pct / 100
        self.assertAlmostEqual(self.d["apy_decimal"], self.d["apy_pct"] / 100.0)


# ─────────────────────────────────────────────────────────────────────────────
# TestFluidYieldInfo — 5 extra tests (BaseAdapter contract)
# ─────────────────────────────────────────────────────────────────────────────

class TestFluidYieldInfo(unittest.TestCase):
    """get_yield_info returns valid YieldInfo with correct fields."""

    def test_yield_info_protocol(self):
        a = _make_adapter(apy=6.5)
        yi = a.get_yield_info()
        self.assertEqual(yi.protocol, "fluid_fusdc")

    def test_yield_info_tier(self):
        a = _make_adapter()
        yi = a.get_yield_info()
        self.assertEqual(yi.tier, "T2")

    def test_yield_info_apy_decimal(self):
        a = _make_adapter(apy=6.5)
        yi = a.get_yield_info()
        self.assertAlmostEqual(yi.apy, 0.065)

    def test_yield_info_tvl(self):
        a = _make_adapter()
        yi = a.get_yield_info()
        self.assertEqual(yi.tvl_usd, 2_000_000_000)

    def test_yield_info_exit_latency(self):
        a = _make_adapter()
        yi = a.get_yield_info()
        self.assertAlmostEqual(yi.exit_latency_hours, 0.0)


if __name__ == "__main__":
    unittest.main()
