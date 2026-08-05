"""
spa_core/tests/test_s22_ethena_yield_max.py

Tests for EthenaYieldMaxStrategy (spa_core/strategies/s22_ethena_yield_max.py).

AUD-18 (задание владельца 2026-08-05) — карточка
`agent-aud18-strategy-unit-tests`.

Замер покрытия ДО этого файла (трассировка исполнения существующим набором
`tests/test_s22_s25_strategies.py`, докстринги исключены) — непокрытыми
оставались ровно ветки ОТКАЗА, то есть поведение системы, когда данных нет:

    ethena_depeg_active  4/6   «адаптера нет» и «адаптер бросил» не исполнялись
    _is_eligible         5/6   «адаптера нет» не исполнялась
    _get_adapter_apy     5/7   внешний сторож отказа не исполнялся
    get_expected_apy     5/6   «аллокация пустая» не исполнялась
    get_health          12/14  статусы critical / degraded не исполнялись
    simulate            14/15  подрезка кольцевого буфера не исполнялась

Три ветки `except: pass` в `_load_adapters` сознательно НЕ покрыты: чтобы их
достать, надо сломать импорт реального адаптера — цена выше пользы, а честнее
сказать это вслух, чем изображать 100 %.

Все адаптеры здесь — локальные заглушки, подставляемые ПОСЛЕ конструктора.
Ноль сети, ноль записи на диск, stdlib, unittest.

Run:
    python3 -m unittest spa_core.tests.test_s22_ethena_yield_max -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s22_ethena_yield_max import (  # noqa: E402
    EthenaYieldMaxStrategy,
    FALLBACK_APY,
    RISK_SCORES,
    SLOTS,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_PCT,
    TIER,
    _HISTORY_MAX,
    _KILL_SLOT,
    _SAFE_HARBOR_SLOTS,
)


# ─── локальные заглушки адаптеров (никакой сети) ──────────────────────────────

class _YieldInfo:
    def __init__(self, apy):
        self.apy = apy


class _FakeAdapter:
    """Минимальный адаптер: здоровый пег, eligible, decimal-APY."""

    def __init__(self, apy_decimal=0.10, peg_healthy=True, eligible=True):
        self._apy = apy_decimal
        self._peg = peg_healthy
        self._eligible = eligible

    def get_yield_info(self):
        return _YieldInfo(self._apy)

    def is_peg_healthy(self):
        return self._peg

    def is_eligible(self):
        return self._eligible


class _ExplodingAdapter:
    """Адаптер, который бросает на любом вопросе."""

    def get_yield_info(self):
        raise RuntimeError("фид недоступен")

    def is_peg_healthy(self):
        raise RuntimeError("фид недоступен")

    def is_eligible(self):
        raise RuntimeError("фид недоступен")


class _PathologicalAdapter(_ExplodingAdapter):
    """Ломается ещё до опроса доходности — на чтении собственного имени.

    Нужен именно такой, чтобы дойти до ВНЕШНЕГО `except` в `_get_adapter_apy`:
    у обычного бросающего адаптера исключение съедается этажом ниже, внутри
    `canonical_apy_decimal` («fail-closed, never raises»).
    """

    @property
    def PROTOCOL(self):
        raise RuntimeError("адаптер сломан на самом опросе")


def _strategy(**adapters) -> EthenaYieldMaxStrategy:
    """Стратегия с ПОЛНОСТЬЮ подменёнными адаптерами (сеть не задействована)."""
    s = EthenaYieldMaxStrategy()
    s._adapters = dict(adapters)
    return s


class TestS22DepegKillSwitch(unittest.TestCase):
    """Ветки отказа стоп-крана депега — «не знаю» НЕ равно «депег»."""

    def test_healthy_peg_means_no_depeg(self):
        self.assertFalse(_strategy(susde=_FakeAdapter(peg_healthy=True)).ethena_depeg_active())

    def test_unhealthy_peg_fires_the_kill_switch(self):
        self.assertTrue(_strategy(susde=_FakeAdapter(peg_healthy=False)).ethena_depeg_active())

    def test_missing_adapter_does_not_fire_documented_behaviour(self):
        """ЗАФИКСИРОВАНО КАК ЕСТЬ (докстринг: «no false kill»).

        Адаптера нет ⇒ депег НЕ объявляется. Это осознанный выбор направления
        ошибки в advisory-стратегии (капитал она не двигает), а НЕ пропуск:
        меняет число, которое стратегия публикует, значит правится только ADR.
        """
        self.assertFalse(_strategy().ethena_depeg_active())

    def test_exploding_adapter_does_not_fire(self):
        self.assertFalse(_strategy(susde=_ExplodingAdapter()).ethena_depeg_active())

    def test_depeg_moves_the_whole_t3_bucket_to_t1(self):
        s = _strategy(susde=_FakeAdapter(peg_healthy=False))
        alloc = s.get_allocation(100_000.0)
        self.assertEqual(alloc.get(SLOTS[_KILL_SLOT]["adapter"], 0.0), 0.0)
        self.assertAlmostEqual(sum(alloc.values()), 100_000.0, places=4)

    def test_depeg_splits_the_bucket_evenly_across_safe_harbour(self):
        s = _strategy(susde=_FakeAdapter(peg_healthy=False))
        alloc = s.get_allocation(100_000.0)
        share = 100_000.0 * SLOTS[_KILL_SLOT]["weight"] / len(_SAFE_HARBOR_SLOTS)
        for slot in _SAFE_HARBOR_SLOTS:
            key = SLOTS[slot]["adapter"]
            expected = 100_000.0 * SLOTS[slot]["weight"] + share
            self.assertAlmostEqual(alloc[key], expected, places=4)

    def test_risk_summary_reports_all_t1_on_depeg(self):
        rs = _strategy(susde=_FakeAdapter(peg_healthy=False)).get_risk_summary()
        self.assertTrue(rs["ethena_depeg"])
        self.assertEqual(rs["t1_weight_pct"], 100.0)
        self.assertEqual(rs["t3_weight_pct"], 0.0)

    def test_no_depeg_keeps_t3_sleeve(self):
        rs = _strategy(susde=_FakeAdapter(peg_healthy=True)).get_risk_summary()
        self.assertFalse(rs["ethena_depeg"])
        self.assertGreater(rs["t3_weight_pct"], 0.0)


class TestS22Allocation(unittest.TestCase):

    def test_weights_sum_to_capital(self):
        alloc = _strategy(susde=_FakeAdapter()).get_allocation(100_000.0)
        self.assertAlmostEqual(sum(alloc.values()), 100_000.0, places=4)

    def test_zero_capital_gives_zeros_for_every_slot(self):
        alloc = _strategy(susde=_FakeAdapter()).get_allocation(0.0)
        self.assertEqual(set(alloc), {SLOTS[s]["adapter"] for s in SLOTS})
        self.assertEqual(set(alloc.values()), {0.0})

    def test_negative_capital_gives_zeros(self):
        self.assertEqual(set(_strategy().get_allocation(-5.0).values()), {0.0})

    def test_slot_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(s["weight"] for s in SLOTS.values()), 1.0, places=9)


class TestS22AdapterApy(unittest.TestCase):
    """Живое число берётся, но отказ фида не превращается в выдуманное."""

    def test_live_decimal_apy_is_converted_to_percent_once(self):
        s = _strategy(susde=_FakeAdapter(apy_decimal=0.10))
        self.assertAlmostEqual(s._get_adapter_apy("susde"), 10.0, places=6)

    def test_exploding_adapter_falls_back_not_crashes(self):
        # Отказ фида гасится ЭТАЖОМ НИЖЕ — в canonical_apy_decimal; сюда
        # приходит уже None, и берётся fallback. Контракт «сломанный адаптер
        # не роняет стратегию и не даёт выдуманного числа» — вот он.
        s = _strategy(susde=_ExplodingAdapter())
        self.assertEqual(s._get_adapter_apy("susde"), FALLBACK_APY["susde"])

    def test_pathological_adapter_reaches_the_outer_guard(self):
        # Единственный путь до внешнего `except` в _get_adapter_apy: адаптер,
        # ломающийся раньше, чем нижний слой успевает поймать отказ.
        s = _strategy(susde=_PathologicalAdapter())
        self.assertEqual(s._get_adapter_apy("susde"), FALLBACK_APY["susde"])

    def test_missing_adapter_uses_fallback(self):
        self.assertEqual(_strategy()._get_adapter_apy("susde"), FALLBACK_APY["susde"])

    def test_unknown_key_yields_zero_not_exception(self):
        self.assertEqual(_strategy()._get_adapter_apy("never_heard_of_it"), 0.0)


class TestS22Eligibility(unittest.TestCase):

    def test_eligible_adapter_is_eligible(self):
        self.assertTrue(_strategy(susde=_FakeAdapter(eligible=True))._is_eligible("susde"))

    def test_ineligible_adapter_is_not(self):
        self.assertFalse(_strategy(susde=_FakeAdapter(eligible=False))._is_eligible("susde"))

    def test_missing_adapter_is_eligible_documented_behaviour(self):
        # Незагруженный адаптер не считается непригодным (иначе health был бы
        # красным на пустом наборе). Фиксируем как есть.
        self.assertTrue(_strategy()._is_eligible("susde"))

    def test_exploding_adapter_is_eligible(self):
        self.assertTrue(_strategy(susde=_ExplodingAdapter())._is_eligible("susde"))


class TestS22Health(unittest.TestCase):
    """Три статуса — до этого файла исполнялся только один."""

    def _all(self, eligible):
        return _strategy(**{
            SLOTS[s]["adapter"]: _FakeAdapter(eligible=eligible) for s in SLOTS
        })

    def test_all_eligible_is_ok(self):
        health = self._all(True).get_health()
        self.assertEqual(health["overall_status"], "ok")
        self.assertEqual(health["eligible_slots"], len(SLOTS))

    def test_none_eligible_is_critical(self):
        health = self._all(False).get_health()
        self.assertEqual(health["overall_status"], "critical")
        self.assertEqual(health["eligible_slots"], 0)

    def test_partial_eligibility_is_degraded(self):
        adapters = {SLOTS[s]["adapter"]: _FakeAdapter(eligible=True) for s in SLOTS}
        adapters[SLOTS["ethena"]["adapter"]] = _FakeAdapter(eligible=False)
        health = _strategy(**adapters).get_health()
        self.assertEqual(health["overall_status"], "degraded")
        self.assertEqual(health["eligible_slots"], len(SLOTS) - 1)

    def test_health_reports_loaded_flag_per_slot(self):
        health = _strategy(susde=_FakeAdapter()).get_health()
        self.assertTrue(health["slots"]["ethena"]["loaded"])
        self.assertFalse(health["slots"]["sky"]["loaded"])

    def test_health_carries_total_slots_and_target(self):
        health = _strategy().get_health()
        self.assertEqual(health["total_slots"], len(SLOTS))
        self.assertEqual(health["target_apy"], TARGET_APY_PCT)


class TestS22ExpectedApy(unittest.TestCase):

    def test_fallbacks_blend_to_slot_weights(self):
        s = _strategy()
        expected = sum(SLOTS[k]["weight"] * FALLBACK_APY[SLOTS[k]["adapter"]] for k in SLOTS)
        self.assertAlmostEqual(s.get_expected_apy(), round(expected, 4), places=4)

    def test_empty_allocation_returns_target_not_zero(self):
        """Ветка «аллокации нет» — возвращается целевой APY, не 0 и не крэш."""
        class _NoAllocation(EthenaYieldMaxStrategy):
            def get_allocation(self, capital_usd):
                return {}

        s = _NoAllocation()
        s._adapters = {}
        self.assertEqual(s.get_expected_apy(), TARGET_APY_PCT)

    def test_depeg_lowers_expected_apy(self):
        # T3-двигатель ушёл в T1-гавань ⇒ ожидаемая доходность обязана упасть.
        healthy = _strategy(susde=_FakeAdapter(peg_healthy=True)).get_expected_apy()
        depegged = _strategy(susde=_FakeAdapter(peg_healthy=False)).get_expected_apy()
        self.assertLess(depegged, healthy)


class TestS22Simulate(unittest.TestCase):

    def test_positions_and_yield_are_consistent(self):
        sim = _strategy().simulate(100_000.0)
        self.assertEqual(sim["status"], "ok")
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=4)
        manual = sum(p["annual_yield_usd"] for p in sim["positions"].values())
        self.assertAlmostEqual(sim["expected_annual_yield_usd"], round(manual, 4), places=3)

    def test_positions_carry_risk_scores(self):
        sim = _strategy().simulate(10_000.0)
        for key, pos in sim["positions"].items():
            self.assertEqual(pos["risk_score"], RISK_SCORES.get(key, 0.0))

    def test_zero_capital_is_no_capital(self):
        sim = _strategy().simulate(0.0)
        self.assertEqual(sim["status"], "no_capital")
        self.assertEqual(sim["allocation"], {})
        self.assertEqual(sim["expected_annual_yield_usd"], 0.0)

    def test_no_capital_run_is_not_recorded_in_history(self):
        s = _strategy()
        s.simulate(0.0)
        self.assertEqual(len(s._simulate_history), 0)

    def test_history_ring_buffer_is_capped(self):
        """Подрезка кольцевого буфера — ветка, которая не исполнялась."""
        s = _strategy()
        s._simulate_history = [{"stub": i} for i in range(_HISTORY_MAX)]
        s.simulate(1_000.0)
        self.assertEqual(len(s._simulate_history), _HISTORY_MAX)
        # выпал самый старый, новейший — на месте
        self.assertNotIn({"stub": 0}, s._simulate_history)
        self.assertEqual(s._simulate_history[-1]["status"], "ok")

    def test_history_grows_below_the_cap(self):
        s = _strategy()
        s.simulate(1_000.0)
        s.simulate(2_000.0)
        self.assertEqual(len(s._simulate_history), 2)


class TestS22ToDict(unittest.TestCase):

    def setUp(self):
        self.s = _strategy(susde=_FakeAdapter())
        self.d = self.s.to_dict()

    def test_identity_fields(self):
        self.assertEqual(self.d["strategy_id"], "S22")
        self.assertEqual(self.d["strategy_name"], STRATEGY_NAME)
        self.assertEqual(self.d["tier"], TIER)
        self.assertEqual(STRATEGY_ID, "S22")

    def test_slots_are_copies(self):
        self.d["slots"]["ethena"]["weight"] = 0.99
        self.d["fallback_apy"]["susde"] = 99.0
        self.assertEqual(SLOTS["ethena"]["weight"], 0.40)
        self.assertEqual(FALLBACK_APY["susde"], 12.0)

    def test_adapters_loaded_reflects_injected_set(self):
        self.assertEqual(self.d["adapters_loaded"], ["susde"])

    def test_json_serialisable(self):
        import json
        self.assertIsInstance(json.dumps(self.d), str)

    def test_t3_cap_note_is_present_advisory_not_a_gate(self):
        # Стратегия сама объявляет, что 40% T3 превышает потолок политики и
        # решение остаётся за гейтом — это не должно тихо исчезнуть.
        note = self.s.get_risk_summary()["t3_cap_note"]
        self.assertIn("advisory", note.lower())


if __name__ == "__main__":
    unittest.main()
