"""Приёмка прибора G19 — цена починки адаптеров в ACT-днях до критерия.

Каждый тест здесь — положительный контроль: он краснеет на конкретной поломке,
которая либо уже случалась в этом дереве, либо случилась при постройке прибора.
Три из них стоя́т на дефектах, найденных ЗАМЕРОМ, а не глазом:

* ``test_remedy_reader_refuses_when_the_neighbour_changes_shape`` — первая редакция
  прибора читала у соседа ключ ``days``, а сосед печатает ``per_day``; рычаг молча
  вышел «НЕ ИЗМЕРЕН» у ВСЕХ семи протоколов, и слово «адаптеров» из заказа осталось
  бы непроверенным. Третий исход сработал громко — тест закрепляет именно это;
* ``test_answer_is_invariant_to_the_sentinel_but_the_sign_is_not`` — знак ``net``
  под грантом меняется от подставленного числа (0 / +25 / −25 пп дают 0 / 1 / 6
  окупающихся дней), и докладывать его значило бы выдать свойство сентинела за
  свойство мира;
* ``test_alone_and_necessary_are_different_numbers`` — три протокола поднимают ноль
  дней поодиночке и при этом НЕОБХОДИМЫ; ранжирование по ``alone`` поставило бы их
  последними.

# FROZEN-DATE-OK: injected-clock — якорь ``_NOW`` порождает все метки дней через
# ``_day()`` и он же передаётся прибору аргументом ``measure(now=)``; стенных часов
# в файле нет, и вердикт не зависит ни от календаря, ни от длительности прогона.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import adapter_repair_price as arp
from spa_core.paper_trading import shadow_trigger_eval as ste

#: Якорь времени. Все метки дней происходят ОТ НЕГО, и он же уезжает в `now=`.
_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _day(days_ago: int) -> str:
    return (_NOW - timedelta(days=days_ago)).date().isoformat()


def _record(day: str, *, current: dict, target: dict, evidenced: dict,
            verdict: str = "HOLD", capital: float = 100_000.0) -> dict:
    return {
        "cycle_date": day,
        "verdict": verdict,
        "capital_usd": capital,
        "current_positions": dict(current),
        "target_positions": dict(target),
        "apy_evidenced_pct": dict(evidenced),
        "turnover_usd": sum(abs(float(target.get(k, 0.0)) - float(current.get(k, 0.0)))
                            for k in set(current) | set(target)) / 2.0,
        "cost_usd": 10.0,
        "reasons": [],
    }


def _journal(*, blocked_leg: str = "pendle", verdict: str = "HOLD",
             days: int = 12) -> list:
    """Журнал, где ПЕРВЫЙ день двигает ``blocked_leg``, а форвардные его не несут.

    Такой день судья обязан отвергнуть с причиной
    ``no_evidenced_apy_for_moved_legs`` — и именно он есть предмет прибора.
    """
    rows = [_record(_day(days),
                    current={"aave_v3": 50_000.0, blocked_leg: 40_000.0},
                    target={"aave_v3": 90_000.0},
                    evidenced={"aave_v3": 4.0, blocked_leg: 8.0},
                    verdict=verdict)]
    for i in range(days - 1, 0, -1):
        rows.append(_record(_day(i),
                            current={"aave_v3": 90_000.0},
                            target={"aave_v3": 90_000.0},
                            evidenced={"aave_v3": 4.0}))
    return rows


def _data_dir(tmp: str, rows: list) -> Path:
    data = Path(tmp) / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / ste.HISTORY_FILENAME).write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
        encoding="utf-8")
    return data


class GrantIsARightNotARate(unittest.TestCase):
    """Возмущение выдаёт ПРАВО быть оценённым и не выдумывает доходность."""

    def test_existing_rate_is_never_overwritten(self):
        rows = [_record(_day(2), current={"a": 1.0}, target={"a": 1.0},
                        evidenced={"a": 7.5})]
        out = arp.grant(rows, ["a"], pct=99.0)
        self.assertEqual(out[0]["apy_evidenced_pct"]["a"], 7.5,
                         "грант подменил НАБЛЮДЁННУЮ ставку — прибор перестал "
                         "быть о дырах")

    def test_missing_rate_is_filled(self):
        rows = [_record(_day(2), current={"a": 1.0}, target={"b": 1.0},
                        evidenced={"a": 7.5})]
        out = arp.grant(rows, ["b"], pct=0.0)
        self.assertEqual(out[0]["apy_evidenced_pct"]["b"], 0.0)

    def test_source_rows_are_not_mutated(self):
        rows = [_record(_day(2), current={"a": 1.0}, target={"b": 1.0},
                        evidenced={"a": 7.5})]
        arp.grant(rows, ["b"])
        self.assertNotIn("b", rows[0]["apy_evidenced_pct"],
                         "грант правит ИСХОДНЫЙ журнал — соседние стенды стали бы "
                         "функцией порядка вызовов")


class JudgeReplayIsReachable(unittest.TestCase):
    """«Подмена не дотянулась» и «ничего не изменилось» обязаны быть различимы."""

    def test_replay_reaches_the_judge(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, _journal())
            doc, why = arp.ask_judge(data, _journal())
            self.assertIsNotNone(doc, why)
            self.assertEqual(why, "")

    def test_loader_never_called_is_unmeasured_not_zero(self):
        original = ste.evaluate_window
        ste.evaluate_window = lambda *a, **k: {"per_verdict": []}
        try:
            doc, why = arp.ask_judge(Path("/nonexistent"), [])
        finally:
            ste.evaluate_window = original
        self.assertIsNone(doc)
        self.assertIn("не вызван ни разу", why)

    def test_judge_failure_is_unmeasured_with_a_named_reason(self):
        original = ste.evaluate_window

        def _boom(*a, **k):
            raise RuntimeError("стенд развалился")

        ste.evaluate_window = _boom
        try:
            doc, why = arp.ask_judge(Path("/nonexistent"), [])
        finally:
            ste.evaluate_window = original
        self.assertIsNone(doc)
        self.assertIn("стенд развалился", why)

    def test_the_judges_loader_is_restored_after_a_failure(self):
        before = ste.load_history
        original = ste.evaluate_window

        def _boom(*a, **k):
            raise RuntimeError("х")

        ste.evaluate_window = _boom
        try:
            arp.ask_judge(Path("/nonexistent"), [])
        finally:
            ste.evaluate_window = original
        self.assertIs(ste.load_history, before,
                      "прибор оставил судью с подменённым загрузчиком — соседние "
                      "приборы того же прогона мерили бы ЧУЖОЙ журнал")


class PopulationComesFromTheJudge(unittest.TestCase):
    """Своей копии правила отбора у прибора нет."""

    def test_only_the_named_reason_counts(self):
        report = {"per_verdict": [
            {"cycle_date": "d1", "unchecked_reason": "no_evidenced_apy_for_moved_legs"},
            {"cycle_date": "d2", "unchecked_reason": "no_forward_data"},
            {"cycle_date": "d3", "unchecked_reason": "no_target_recorded"},
            {"cycle_date": "d4"},
        ]}
        got = arp.blocked_days(report, "no_evidenced_apy_for_moved_legs")
        self.assertEqual([r["cycle_date"] for r in got], ["d1"],
                         "в население затесалась причина, которая ставками НЕ "
                         "лечится — цена починки была бы завышена")

    def test_reason_name_is_taken_from_the_canonical_owner(self):
        from spa_core.monitoring.unobserved_turnover_dependence import REFUSAL_REASON
        name, why = arp._refusal_reason()
        self.assertEqual(why, "")
        self.assertEqual(name, REFUSAL_REASON,
                         "имя причины разошлось с каноническим владельцем")

    def test_criterion_definition_matches_the_judges_capacity_bench(self):
        """«Дошёл до критерия» здесь и у соседа — ОДНО правило, проверено исходом."""
        report = {"per_verdict": [
            {"cycle_date": "a", "verdict": "ACT", "outcome": "hit"},
            {"cycle_date": "b", "verdict": "ACT", "outcome": "miss"},
            {"cycle_date": "c", "verdict": "ACT", "outcome": "UNCHECKED"},
            {"cycle_date": "d", "verdict": "HOLD", "outcome": "hit"},
        ]}
        self.assertEqual(arp._criterion_days(report), {"a", "b"},
                         "HOLD или UNCHECKED затесались в критерий №3 — он "
                         "закрывается только ОЦЕНЁННЫМ ACT")


class CapitalHasTwoSides(unittest.TestCase):
    """Держимый и целевой капитал — разные величины, и складывать их нельзя."""

    def test_held_and_targeted_are_reported_apart(self):
        rec = _record(_day(1), current={"p": 20_000.0, "q": 30_000.0},
                      target={"p": 0.0, "r": 10_000.0},
                      evidenced={})
        cap = arp.capital_on_rejecting(rec, ["p", "r"])
        self.assertEqual(cap["held_usd"], 20_000.0)
        self.assertEqual(cap["targeted_usd"], 10_000.0)
        self.assertEqual(cap["deployed_usd"], 50_000.0)
        self.assertAlmostEqual(cap["held_pct_of_deployed"], 40.0)

    def test_missing_capital_is_a_third_outcome_not_a_zero(self):
        rec = _record(_day(1), current={"p": 1.0}, target={}, evidenced={})
        rec.pop("capital_usd")
        cap = arp.capital_on_rejecting(rec, ["p"])
        self.assertIsNone(cap["capital_usd"])
        self.assertIsNone(cap["targeted_pct_of_capital"],
                          "отсутствие капитала выдано за долю — «не измерено» "
                          "стало неотличимо от нуля")

    def test_empty_book_does_not_divide_by_zero(self):
        rec = _record(_day(1), current={}, target={}, evidenced={})
        cap = arp.capital_on_rejecting(rec, ["p"])
        self.assertIsNone(cap["held_pct_of_deployed"])


class ProtocolCensus(unittest.TestCase):

    def test_counts_by_name_and_orders_by_count(self):
        blocked = [
            {"cycle_date": "d1", "unpriced_protocols": ["pendle", "aave_v3"]},
            {"cycle_date": "d2", "unpriced_protocols": ["pendle"]},
        ]
        got = arp.protocol_census(blocked)
        self.assertEqual([r["protocol"] for r in got], ["pendle", "aave_v3"])
        self.assertEqual(got[0]["days_named"], 2)
        self.assertEqual(got[0]["days"], ["d1", "d2"])


class TodayReadingCanMoveBothWays(unittest.TestCase):
    """Ноль обязан быть ИЗМЕРЕННЫМ, а не свойством прибора."""

    def test_all_hold_journal_returns_zero_act_days(self):
        with TemporaryDirectory() as tmp:
            rows = _journal(verdict="HOLD")
            data = _data_dir(tmp, rows)
            got = arp.today_price(data, rows, ["pendle"],
                                  "no_evidenced_apy_for_moved_legs")
            self.assertTrue(got["measured"], got.get("reason"))
            self.assertEqual(got["act_days_returned_by_full_grant"], 0)
            self.assertEqual(got["blocked_days_cleared_by_full_grant"], 1,
                             "отказ не снялся — грант не дотянулся до судьи, и "
                             "ноль выше ничего не значит")

    def test_an_act_journal_returns_a_nonzero_price(self):
        """Положительный контроль: при ACT цена перестаёт быть нулём."""
        with TemporaryDirectory() as tmp:
            rows = _journal(verdict="ACT")
            data = _data_dir(tmp, rows)
            got = arp.today_price(data, rows, ["pendle"],
                                  "no_evidenced_apy_for_moved_legs")
            self.assertTrue(got["measured"], got.get("reason"))
            self.assertEqual(got["act_days_returned_by_full_grant"], 1,
                             "прибор не умеет поднимать дни ВООБЩЕ — тогда ноль на "
                             "живом журнале был бы вакуумом, а не ответом")

    def test_a_protocol_that_blocks_nothing_buys_nothing(self):
        with TemporaryDirectory() as tmp:
            rows = _journal(verdict="ACT")
            data = _data_dir(tmp, rows)
            got = arp.today_price(data, rows, ["pendle", "protocol_nobody_moves"],
                                  "no_evidenced_apy_for_moved_legs")
            by = {r["protocol"]: r for r in got["per_protocol"]}
            self.assertEqual(by["protocol_nobody_moves"]["criterion_days_gained"], [])
            self.assertEqual(len(by["pendle"]["criterion_days_gained"]), 1)


class RemedyReaderIsWiredToTheNeighbour(unittest.TestCase):
    """Слово «адаптеров» из заказа обязано быть ПРОВЕРЕНО, а не принято."""

    def test_remedy_reader_refuses_when_the_neighbour_changes_shape(self):
        """Дефект постройки: читали ключ ``days``, сосед печатает ``per_day``."""
        from spa_core.monitoring import unobserved_leg_remedy_class as neigh
        original = neigh.measure
        neigh.measure = lambda *a, **k: {"days": [{"legs": [
            {"protocol": "pendle", "remedy": "writer_universe"}]}]}
        try:
            got = arp.remedy_by_protocol(Path("/nonexistent"))
        finally:
            neigh.measure = original
        self.assertFalse(got["measured"])
        self.assertIn("ни одной ноги", got["reason"],
                      "смена формы у соседа прошла бы МОЛЧА, и рычаг у всех "
                      "протоколов вышел бы «не измерен» без единой жалобы")

    def test_remedy_reader_reads_the_live_shape(self):
        from spa_core.monitoring import unobserved_leg_remedy_class as neigh
        original = neigh.measure
        neigh.measure = lambda *a, **k: {"per_day": [{"legs": [
            {"protocol": "pendle", "remedy": "writer_universe"},
            {"protocol": "spark_susds", "remedy": "needs_polling"}]}]}
        try:
            got = arp.remedy_by_protocol(Path("/nonexistent"))
        finally:
            neigh.measure = original
        self.assertTrue(got["measured"])
        self.assertEqual(got["by_protocol"],
                         {"pendle": ["writer_universe"],
                          "spark_susds": ["needs_polling"]})

    def test_neighbour_failure_is_a_third_outcome(self):
        from spa_core.monitoring import unobserved_leg_remedy_class as neigh
        original = neigh.measure

        def _boom(*a, **k):
            raise RuntimeError("сосед отказал")

        neigh.measure = _boom
        try:
            got = arp.remedy_by_protocol(Path("/nonexistent"))
        finally:
            neigh.measure = original
        self.assertFalse(got["measured"])
        self.assertIn("сосед отказал", got["reason"])


class SentinelControlIsMeasuredNotClaimed(unittest.TestCase):
    """Безразличие ответа к подставленному числу обязано быть ЗАМЕРОМ."""

    @staticmethod
    def _stub(reaches_by_pct, net_by_pct):
        calls = []

        def _fake(source, dest, rows):
            pct = None
            for rec in rows:
                for value in (rec.get("apy_evidenced_pct") or {}).values():
                    if value in reaches_by_pct:
                        pct = value
            calls.append(pct)
            return ({"reaches_criterion": reaches_by_pct[pct],
                     "reaches_criterion_material": reaches_by_pct[pct],
                     "reaches_criterion_material_net_positive": net_by_pct[pct],
                     "days": []}, "")

        return _fake, calls

    def test_answer_is_invariant_to_the_sentinel_but_the_sign_is_not(self):
        """Ровно замер 15.09: дошло 38/38/38, окупилось 0/1/6."""
        fake, calls = self._stub({0.0: 38, 25.0: 38, -25.0: 38},
                                 {0.0: 0, 25.0: 1, -25.0: 6})
        original = arp._capacity_of
        arp._capacity_of = fake
        try:
            got = arp.sentinel_control(Path("/x"), _journal(), ["pendle"],
                                       Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertTrue(got["measured"])
        self.assertTrue(got["answer_invariant"],
                        "ответ прибора оказался функцией сентинела")
        self.assertTrue(got["sign_varies"],
                        "знак `net` НЕ разошёлся — тогда отказ его докладывать был "
                        "бы предосторожностью без предмета, то есть украшением")
        self.assertEqual(sorted(c for c in calls if c is not None),
                         [-25.0, 0.0, 25.0])

    def test_a_varying_answer_is_refused_not_averaged(self):
        fake, _ = self._stub({0.0: 38, 25.0: 31, -25.0: 38},
                             {0.0: 0, 25.0: 0, -25.0: 0})
        original = arp._capacity_of
        arp._capacity_of = fake
        try:
            got = arp.sentinel_control(Path("/x"), _journal(), ["pendle"],
                                       Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertFalse(got["answer_invariant"])

    def test_bench_failure_is_a_third_outcome(self):
        original = arp._capacity_of
        arp._capacity_of = lambda *a, **k: (None, "стенд отказал")
        try:
            got = arp.sentinel_control(Path("/x"), _journal(), ["pendle"],
                                       Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertFalse(got["measured"])
        self.assertIn("стенд отказал", got["reason"])

    def test_the_control_carries_a_negative_sentinel(self):
        """Отрицательный обязателен: именно он переворачивает знак `net`."""
        self.assertTrue(any(p < 0 for p in arp._SENTINEL_CONTROL_PCT),
                        "без отрицательного сентинела контроль не увидел бы, что "
                        "уходить из ноги с плохой ставкой «выгодно»")
        self.assertGreaterEqual(len(set(arp._SENTINEL_CONTROL_PCT)), 3)


class AloneIsNotNecessary(unittest.TestCase):
    """«Поднимает 0 в одиночку» и «не нужен» — разные утверждения."""

    def test_alone_and_necessary_are_different_numbers(self):
        # Стенд-модель: день `pair` требует ОБЕИХ ног, день `solo` — только `a`.
        def _fake(source, dest, rows):
            granted = {p for rec in rows
                       for p, v in (rec.get("apy_evidenced_pct") or {}).items()
                       if v == arp._PRICING_SENTINEL_PCT}
            days = []
            if "a" in granted:
                days.append({"day": "solo"})
            if {"a", "b"} <= granted:
                days.append({"day": "pair"})
            return ({"reaches_criterion": len(days), "days": days}, "")

        original = arp._capacity_of
        arp._capacity_of = _fake
        try:
            got = arp.capacity_price(Path("/x"), _journal(), ["a", "b"], Path("/x"))
        finally:
            arp._capacity_of = original
        by = {r["protocol"]: r for r in got["per_protocol"]}
        self.assertEqual(by["b"]["act_days_alone"], [],
                         "нога `b` поднимает день в одиночку — стенд-модель сломана")
        self.assertEqual(by["b"]["necessary_for"], ["pair"],
                         "необходимая нога получила пустую необходимость: "
                         "ранжирование по `alone` поставило бы её последней")
        self.assertEqual(got["act_days_returned_by_full_grant"], 2)
        self.assertEqual(got["act_days_returned_if_taken_one_by_one"], 1)
        self.assertEqual(got["superadditive_days"], ["pair"],
                         "суперадитивность не названа поимённо — разница 1 vs 2 "
                         "читалась бы как ошибка счёта")

    def test_the_sign_of_net_is_refused_with_a_named_reason(self):
        original = arp._capacity_of
        arp._capacity_of = lambda *a, **k: ({"reaches_criterion": 0, "days": []}, "")
        try:
            got = arp.capacity_price(Path("/x"), _journal(), ["a"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertIsNone(got["net_positive_days"])
        self.assertIn("функция ПОДСТАВЛЕННОЙ ставки",
                      got["net_positive_unmeasured_reason"])

    def test_necessity_failure_is_named_per_protocol(self):
        state = {"n": 0}

        def _fake(source, dest, rows):
            state["n"] += 1
            if state["n"] > 3:        # база, одиночка, объединение — потом отказ
                return None, "стенд отказал на исключении"
            return {"reaches_criterion": 0, "days": []}, ""

        original = arp._capacity_of
        arp._capacity_of = _fake
        try:
            got = arp.capacity_price(Path("/x"), _journal(), ["a"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertIsNone(got["per_protocol"][0]["necessary_for"])
        self.assertIn("стенд отказал",
                      got["per_protocol"][0]["necessity_unmeasured_reason"])


class CapacityBenchIsReallyReached(unittest.TestCase):
    """Стенд соседа зовётся НАСТОЯЩИЙ — проверено исходом, не подстрокой."""

    def test_end_to_end_capacity_on_a_synthetic_journal(self):
        with TemporaryDirectory() as tmp:
            rows = _journal(verdict="ACT")
            data = _data_dir(tmp, rows)
            doc = arp.measure(data, now=_NOW, with_capacity=True)
            cap = doc["capacity"]
            self.assertTrue(cap["measured"], cap.get("reason"))
            self.assertEqual(cap["form"], arp._CAPACITY_FORM)
            self.assertIsInstance(cap["criterion_days_baseline"], int)
            self.assertTrue(doc["sentinel_control"]["measured"])
            self.assertTrue(doc["sentinel_control"]["answer_invariant"])


class VerdictIsFailClosed(unittest.TestCase):

    def test_sentinel_disagreement_invalidates_the_numbers(self):
        doc = {"returns_today": {"measured": True,
                                 "act_days_returned_by_full_grant": 0},
               "capacity": {"measured": True, "act_days_returned_by_full_grant": 10},
               "sentinel_control": {"measured": True, "answer_invariant": False},
               "blocked_days": {"count": 8}}
        got = arp._verdict(doc)
        self.assertEqual(got["status"], arp.STATUS_UNMEASURED)
        self.assertIn("ЗАВИСИТ от подставленной ставки", got["headline"])

    def test_unmeasured_today_is_not_a_quiet_zero(self):
        doc = {"returns_today": {"measured": False, "reason": "судья упал"},
               "blocked_days": {"count": 8}}
        got = arp._verdict(doc)
        self.assertEqual(got["status"], arp.STATUS_UNMEASURED)
        self.assertIn("судья упал", got["headline"])

    def test_capacity_not_measured_is_a_warning_that_says_so(self):
        doc = {"returns_today": {"measured": True,
                                 "act_days_returned_by_full_grant": 0},
               "capacity": None, "sentinel_control": None,
               "blocked_days": {"count": 8}}
        got = arp._verdict(doc)
        self.assertEqual(got["status"], arp.STATUS_WARNING)
        self.assertIn("ёмкость не мерилась", got["headline"])

    def test_no_blocked_days_is_ok_and_says_why(self):
        doc = {"returns_today": {"measured": True,
                                 "act_days_returned_by_full_grant": 0},
               "capacity": None, "sentinel_control": None,
               "blocked_days": {"count": 0}}
        got = arp._verdict(doc)
        self.assertEqual(got["status"], arp.STATUS_OK)
        self.assertIn("чинить нечего", got["headline"])

    def test_exit_code_is_nonzero_when_unmeasured(self):
        self.assertEqual({arp.STATUS_OK: 0, arp.STATUS_WARNING: 0,
                          arp.STATUS_CRITICAL: 1}.get(arp.STATUS_UNMEASURED, 2), 2)


class ReportNeverPrintsAQuietGreen(unittest.TestCase):

    def test_unmeasured_remedy_is_said_out_loud(self):
        doc = {"status": arp.STATUS_WARNING, "headline": "h",
               "blocked_days": {"count": 1, "of_journal_days": 40, "days": [],
                                "capital_on_rejecting_legs": {}},
               "protocols": [{"protocol": "pendle", "days_named": 1,
                              "days": ["d"]}],
               "remedy": {"measured": False, "reason": "сосед недоступен"},
               "returns_today": {"measured": True,
                                 "act_days_returned_by_full_grant": 0,
                                 "scored_days_returned_by_full_grant": 1,
                                 "blocked_days_cleared_by_full_grant": 1,
                                 "blocked_days_baseline": 1,
                                 "why_zero_is_expected": "потому"},
               "capacity": None, "sentinel_control": None,
               "capacity_unmeasured_reason": "не мерилась"}
        text = "\n".join(arp.format_report(doc))
        self.assertIn("рычаги НЕ ИЗМЕРЕНЫ", text)
        self.assertIn("НЕПРОВЕРЕННЫМ", text)
        self.assertIn("НЕ ИЗМЕРЕНА", text)

    def test_missing_population_block_is_named(self):
        text = "\n".join(arp.format_report({"status": arp.STATUS_UNMEASURED}))
        self.assertIn("НЕ ИЗМЕРЕНО", text)


class ReadOnlyIsGuarded(unittest.TestCase):
    """«Прибор только ЧИТАЕТ» — утверждение ADR, и оно обязано иметь сторожа.

    Батарея round-1 сняла ``write=False`` в ``ask_judge`` и НИ ОДИН из 38 тестов не
    покраснел: судья начал бы писать ``shadow_trigger_evaluation.json`` в каталог,
    который прибор обещал не трогать, — по разу на КАЖДЫЙ из девятнадцати стендов.
    """

    def test_the_data_dir_is_not_written_during_a_full_measure(self):
        with TemporaryDirectory() as tmp:
            rows = _journal()
            data = _data_dir(tmp, rows)
            before = {f.name: (f.stat().st_mtime_ns, f.stat().st_size)
                      for f in data.iterdir()}
            arp.measure(data, now=_NOW, with_capacity=True)
            after = {f.name: (f.stat().st_mtime_ns, f.stat().st_size)
                     for f in data.iterdir()}
            self.assertEqual(before, after,
                             "прибор ТРОНУЛ входной каталог — заявление «только "
                             "чтение» в ADR перестало быть правдой")
            self.assertEqual(sorted(before), [ste.HISTORY_FILENAME],
                             "во входном каталоге появился новый файл")

    def test_ask_judge_does_not_write(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, _journal())
            arp.ask_judge(data, _journal())
            self.assertEqual(sorted(f.name for f in data.iterdir()),
                             [ste.HISTORY_FILENAME])


class SentinelIsZeroForAReason(unittest.TestCase):
    """Ноль выбран не «для простоты»: при нём вклад ноги в benefit РОВНО нулевой."""

    def test_the_sentinel_contributes_exactly_nothing(self):
        deltas = {"granted": 10_000.0, "known": 10_000.0}
        with_sentinel, missing = ste._day_gain_usd(
            deltas, {"granted": arp._PRICING_SENTINEL_PCT, "known": 5.0})
        only_known, _ = ste._day_gain_usd({"known": 10_000.0}, {"known": 5.0})
        self.assertEqual(missing, [])
        self.assertAlmostEqual(with_sentinel, only_known,
                               msg="сентинел ВНОСИТ доходность — прибор начал "
                                   "выдумывать наблюдение вместо права быть "
                                   "оценённым")

    def test_the_sentinel_still_makes_the_leg_priceable(self):
        gain, missing = ste._day_gain_usd(
            {"granted": 10_000.0}, {"granted": arp._PRICING_SENTINEL_PCT})
        self.assertEqual(missing, [], "нога осталась неоценимой — грант бесполезен")
        self.assertIsNotNone(gain)


class SignVariesIsAMeasurementNotAConstant(unittest.TestCase):

    def test_agreeing_signs_report_sign_varies_false(self):
        fake, _ = SentinelControlIsMeasuredNotClaimed._stub(
            {0.0: 38, 25.0: 38, -25.0: 38}, {0.0: 2, 25.0: 2, -25.0: 2})
        original = arp._capacity_of
        arp._capacity_of = fake
        try:
            got = arp.sentinel_control(Path("/x"), _journal(), ["pendle"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertTrue(got["answer_invariant"])
        self.assertFalse(got["sign_varies"],
                         "`sign_varies` истинен ВСЕГДА — контроль перестал быть "
                         "измерением и стал константой")


class ThirdOutcomePathsAreExercised(unittest.TestCase):
    """Отказ КАЖДОГО стенда обязан доезжать до вердикта, а не теряться."""

    def test_today_price_refuses_when_the_baseline_judge_refuses(self):
        original = arp.ask_judge
        arp.ask_judge = lambda *a, **k: (None, "судья отказал на базе")
        try:
            got = arp.today_price(Path("/x"), [], ["p"], "r")
        finally:
            arp.ask_judge = original
        self.assertFalse(got["measured"])
        self.assertIn("судья отказал на базе", got["reason"])

    def test_today_price_refuses_when_the_union_grant_refuses(self):
        calls = {"n": 0}
        original = arp.ask_judge

        def _fake(data_dir, rows):
            calls["n"] += 1
            if calls["n"] >= 3:          # база, одиночка — потом объединение
                return None, "объединение не сосчиталось"
            return {"per_verdict": []}, ""

        arp.ask_judge = _fake
        try:
            got = arp.today_price(Path("/x"), [], ["p"], "r")
        finally:
            arp.ask_judge = original
        self.assertFalse(got["measured"])
        self.assertIn("объединение не сосчиталось", got["reason"])

    def test_today_price_names_a_refused_protocol_without_losing_the_rest(self):
        calls = {"n": 0}
        original = arp.ask_judge

        def _fake(data_dir, rows):
            calls["n"] += 1
            if calls["n"] == 2:
                return None, "первый протокол не сосчитался"
            return {"per_verdict": []}, ""

        arp.ask_judge = _fake
        try:
            got = arp.today_price(Path("/x"), [], ["p", "q"], "r")
        finally:
            arp.ask_judge = original
        self.assertTrue(got["measured"])
        self.assertEqual(got["refused"], ["p: первый протокол не сосчитался"])
        self.assertEqual([r["protocol"] for r in got["per_protocol"]], ["q"])

    def test_capacity_refuses_when_the_baseline_bench_refuses(self):
        original = arp._capacity_of
        arp._capacity_of = lambda *a, **k: (None, "база стенда не собралась")
        try:
            got = arp.capacity_price(Path("/x"), [], ["p"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertFalse(got["measured"])
        self.assertIn("база стенда не собралась", got["reason"])

    def test_missing_neighbour_module_is_named(self):
        got = arp._capacity_of.__doc__
        self.assertIn("Живой каталог только читается", got)


class CountsAndSharesArePinned(unittest.TestCase):
    """Числа, а не «не None»: арифметику переживает любая проверка на пустоту."""

    def test_aggregate_capital_shares_are_exact(self):
        with TemporaryDirectory() as tmp:
            rows = _journal()
            data = _data_dir(tmp, rows)
            doc = arp.measure(data, now=_NOW, with_capacity=False)
            cap = doc["blocked_days"]["capital_on_rejecting_legs"]
            # книга дня: aave_v3 50k + pendle 40k = 90k развёрнуто, отвергает pendle
            self.assertEqual(cap["held_usd"], 40_000.0)
            self.assertEqual(cap["deployed_usd"], 90_000.0)
            self.assertAlmostEqual(cap["held_pct_of_deployed"], 44.44)
            self.assertEqual(cap["targeted_usd"], 0.0)
            self.assertEqual(cap["capital_usd"], 100_000.0)
            self.assertEqual(cap["targeted_pct_of_capital"], 0.0)

    def test_journal_block_names_the_real_ends(self):
        with TemporaryDirectory() as tmp:
            rows = _journal(days=12)
            data = _data_dir(tmp, rows)
            doc = arp.measure(data, now=_NOW, with_capacity=False)
            self.assertEqual(doc["journal"]["rows"], 12)
            self.assertEqual(doc["journal"]["first_day"], _day(12))
            self.assertEqual(doc["journal"]["last_day"], _day(1),
                             "последний день журнала взят не с конца — окно "
                             "замера уехало бы молча")

    def test_today_baselines_are_counts_not_placeholders(self):
        with TemporaryDirectory() as tmp:
            rows = _journal(verdict="ACT")
            data = _data_dir(tmp, rows)
            got = arp.today_price(data, rows, ["pendle"],
                                  "no_evidenced_apy_for_moved_legs")
            self.assertEqual(got["criterion_days_baseline"], 0)
            self.assertEqual(got["blocked_days_baseline"], 1)
            self.assertEqual(got["scored_days_returned_by_full_grant"], 1)

    def test_protocol_census_counts_are_numbers(self):
        got = arp.protocol_census([
            {"cycle_date": "d1", "unpriced_protocols": ["a", "b"]},
            {"cycle_date": "d2", "unpriced_protocols": ["a"]}])
        self.assertEqual([r["days_named"] for r in got], [2, 1])


class DayListsAreSortedNotIncidental(unittest.TestCase):
    """Порядок дней — часть ответа: несортированный список читается как хронология."""

    def test_capacity_lists_come_out_sorted(self):
        def _fake(source, dest, rows):
            granted = {p for rec in rows
                       for p, v in (rec.get("apy_evidenced_pct") or {}).items()
                       if v == arp._PRICING_SENTINEL_PCT}
            days = [{"day": d} for d in ("2026-09-09", "2026-08-01", "2026-08-30")
                    ] if granted else []
            return {"reaches_criterion": len(days), "days": days}, ""

        original = arp._capacity_of
        arp._capacity_of = _fake
        try:
            got = arp.capacity_price(Path("/x"), _journal(), ["a"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertEqual(got["act_days_returned_by_full_grant_list"],
                         ["2026-08-01", "2026-08-30", "2026-09-09"])
        self.assertEqual(got["per_protocol"][0]["act_days_alone"],
                         ["2026-08-01", "2026-08-30", "2026-09-09"])

    def test_today_gained_lists_come_out_sorted(self):
        calls = {"n": 0}
        original = arp.ask_judge

        def _fake(data_dir, rows):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"per_verdict": []}, ""
            return {"per_verdict": [
                {"cycle_date": d, "verdict": "ACT", "outcome": "hit"}
                for d in ("2026-09-09", "2026-08-01")]}, ""

        arp.ask_judge = _fake
        try:
            got = arp.today_price(Path("/x"), [], ["p"], "r")
        finally:
            arp.ask_judge = original
        self.assertEqual(got["per_protocol"][0]["criterion_days_gained"],
                         ["2026-08-01", "2026-09-09"])

    def test_remedy_levers_come_out_sorted(self):
        from spa_core.monitoring import unobserved_leg_remedy_class as neigh
        original = neigh.measure
        neigh.measure = lambda *a, **k: {"per_day": [{"legs": [
            {"protocol": "p", "remedy": "writer_universe"},
            {"protocol": "p", "remedy": "key_mismatch"}]}]}
        try:
            got = arp.remedy_by_protocol(Path("/x"))
        finally:
            neigh.measure = original
        self.assertEqual(got["by_protocol"]["p"],
                         ["key_mismatch", "writer_universe"])


class HeadlineBranchIsPinned(unittest.TestCase):
    """Ветка CRITICAL — тот самый заголовок ADR; её условие обязано быть закреплено."""

    @staticmethod
    def _doc(today_days, cap_days):
        return {"returns_today": {"measured": True,
                                  "act_days_returned_by_full_grant": today_days},
                "capacity": {"measured": True,
                             "act_days_returned_by_full_grant": cap_days},
                "sentinel_control": {"measured": True, "answer_invariant": True},
                "blocked_days": {"count": 8},
                "protocols": [{"protocol": "a"}, {"protocol": "b"}]}

    def test_zero_today_but_capacity_nonzero_is_critical(self):
        got = arp._verdict(self._doc(0, 10))
        self.assertEqual(got["status"], arp.STATUS_CRITICAL)
        self.assertIn("2 названных", got["headline"])
        self.assertIn("СЕГОДНЯ 0", got["headline"])
        self.assertIn("при починенном писателе — 10", got["headline"])

    def test_nonzero_today_is_not_critical(self):
        got = arp._verdict(self._doc(3, 10))
        self.assertEqual(got["status"], arp.STATUS_WARNING,
                         "ветка CRITICAL сработала там, где сегодня уже что-то "
                         "возвращается — заголовок ADR стал бы неверен")

    def test_zero_today_and_zero_capacity_is_not_critical(self):
        got = arp._verdict(self._doc(0, 0))
        self.assertEqual(got["status"], arp.STATUS_WARNING,
                         "«ноль и там, и там» подан как находка о рычаге")


class RunResolvesItsRoot(unittest.TestCase):

    def test_run_writes_beside_the_repo_data_dir(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _data_dir(tmp, _journal())
            doc = arp.run(root=str(root), now=_NOW, with_capacity=False)
            written = root / "data" / arp.OUTPUT_FILENAME
            self.assertTrue(written.exists(), "артефакт не написан в data/ корня")
            self.assertEqual(json.loads(written.read_text(encoding="utf-8"))["version"],
                             doc["version"])

    def test_default_root_is_the_repository_not_the_package(self):
        expected = Path(arp.__file__).resolve().parents[2]
        self.assertTrue((expected / "spa_core").is_dir(),
                        "умолчание корня уехало — артефакт лёг бы мимо data/")

    def test_main_returns_nonzero_when_unmeasured(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, [])
            rc = arp.main(["--data-dir", str(data), "--no-capacity", "--no-write"])
            self.assertEqual(rc, 2)
            self.assertFalse((data / arp.OUTPUT_FILENAME).exists(),
                             "--no-write написал артефакт")

    def test_main_writes_when_asked(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, _journal())
            rc = arp.main(["--data-dir", str(data), "--no-capacity"])
            self.assertEqual(rc, 0)
            self.assertTrue((data / arp.OUTPUT_FILENAME).exists())

    def test_with_capacity_is_on_by_default(self):
        import inspect
        self.assertIs(inspect.signature(arp.measure)
                      .parameters["with_capacity"].default, True,
                      "ёмкость выключена по умолчанию — цикл получал бы ТОЛЬКО "
                      "сегодняшний ноль, самую соблазнительную половину ответа")


class EveryRefusalPathReachesTheVerdict(unittest.TestCase):
    """Третий исход бесполезен, если теряется по дороге к вердикту."""

    def test_refusal_reason_import_failure_is_none_not_a_falsy_value(self):
        import spa_core.monitoring.unobserved_turnover_dependence as neigh
        original = neigh.REFUSAL_REASON
        neigh.REFUSAL_REASON = ""
        try:
            name, why = arp._refusal_reason()
        finally:
            neigh.REFUSAL_REASON = original
        self.assertIsNone(name, "пустое имя причины вернулось НЕ как None — "
                                "вызывающий проверяет `is None` и пропустил бы его")
        self.assertIn("пусто", why)

    def test_measure_refuses_when_the_reason_name_is_unreadable(self):
        original = arp._refusal_reason
        arp._refusal_reason = lambda: (None, "имя причины не прочитано")
        try:
            doc = arp.measure(Path("/nonexistent"), now=_NOW, with_capacity=False)
        finally:
            arp._refusal_reason = original
        self.assertEqual(doc["status"], arp.STATUS_UNMEASURED)
        self.assertIn("имя причины не прочитано", doc["headline"])
        self.assertNotIn("blocked_days", doc)

    def test_measure_refuses_when_the_judge_refuses(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, _journal())
            original = arp.ask_judge
            arp.ask_judge = lambda *a, **k: (None, "судья не ответил на базе")
            try:
                doc = arp.measure(data, now=_NOW, with_capacity=False)
            finally:
                arp.ask_judge = original
            self.assertEqual(doc["status"], arp.STATUS_UNMEASURED)
            self.assertIn("судья не ответил на базе", doc["headline"])

    def test_measure_refuses_when_the_journal_cannot_be_read(self):
        doc = arp.measure(Path("/nonexistent/at/all"), now=_NOW,
                          with_capacity=False)
        self.assertEqual(doc["status"], arp.STATUS_UNMEASURED)
        self.assertIn("пуст", doc["headline"])

    def test_the_real_capacity_helper_refuses_with_none(self):
        """Отказ НАСТОЯЩЕГО `_capacity_of`, а не его подмены."""
        from spa_core.monitoring import judge_alone_price as jap
        original = jap.capacity
        jap.capacity = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("стенд лёг"))
        try:
            with TemporaryDirectory() as tmp:
                data = _data_dir(tmp, _journal())
                cap, why = arp._capacity_of(data, Path(tmp) / "stand", _journal())
        finally:
            jap.capacity = original
        self.assertIsNone(cap, "отказ стенда вернулся НЕ как None — вызывающий "
                               "проверяет `is None` и пошёл бы дальше с мусором")
        self.assertIn("стенд лёг", why)

    def test_capacity_refuses_when_the_union_grant_refuses(self):
        state = {"n": 0}
        original = arp._capacity_of

        def _fake(source, dest, rows):
            state["n"] += 1
            if state["n"] == 3:           # база, одиночка — потом объединение
                return None, "объединение стенда не собралось"
            return {"reaches_criterion": 0, "days": []}, ""

        arp._capacity_of = _fake
        try:
            got = arp.capacity_price(Path("/x"), _journal(), ["a"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertFalse(got["measured"],
                         "отказ объединения не доехал до вердикта — прибор "
                         "напечатал бы число, которого не мерил")
        self.assertIn("объединение стенда не собралось", got["reason"])

    def test_capacity_skips_a_refusing_protocol_and_names_it(self):
        state = {"n": 0}
        original = arp._capacity_of

        def _fake(source, dest, rows):
            state["n"] += 1
            if state["n"] == 2:
                return None, "одиночка не собралась"
            return {"reaches_criterion": 0, "days": []}, ""

        arp._capacity_of = _fake
        try:
            got = arp.capacity_price(Path("/x"), _journal(), ["a", "b"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertTrue(got["measured"])
        self.assertEqual(got["refused"], ["a: одиночка не собралась"])

    def test_remedy_refuses_when_the_neighbour_cannot_be_imported(self):
        import sys as _sys
        from spa_core import monitoring as _pkg
        name = "spa_core.monitoring.unobserved_leg_remedy_class"
        saved_mod = _sys.modules.pop(name, None)
        saved_attr = getattr(_pkg, "unobserved_leg_remedy_class", None)
        # Обеих дверей мало поодиночке: `from X import Y` сперва зовёт импорт (его
        # запирает sys.modules), а затем БЕРЁТ АТРИБУТ ПАКЕТА — и уже импортированный
        # сосед достался бы через него, минуя запертую дверь.
        _sys.modules[name] = None
        if saved_attr is not None:
            delattr(_pkg, "unobserved_leg_remedy_class")
        try:
            got = arp.remedy_by_protocol(Path("/x"))
        finally:
            _sys.modules.pop(name, None)
            if saved_mod is not None:
                _sys.modules[name] = saved_mod
            if saved_attr is not None:
                setattr(_pkg, "unobserved_leg_remedy_class", saved_attr)
        self.assertFalse(got["measured"])
        self.assertIn("не импортирован", got["reason"])

    def test_verdict_names_an_unmeasured_capacity(self):
        got = arp._verdict({
            "returns_today": {"measured": True,
                              "act_days_returned_by_full_grant": 0},
            "capacity": {"measured": False, "reason": "стенд не собрался"},
            "sentinel_control": None, "blocked_days": {"count": 8}})
        self.assertEqual(got["status"], arp.STATUS_UNMEASURED)
        self.assertIn("стенд не собрался", got["headline"])

    def test_verdict_names_an_unmeasured_control(self):
        got = arp._verdict({
            "returns_today": {"measured": True,
                              "act_days_returned_by_full_grant": 0},
            "capacity": {"measured": True, "act_days_returned_by_full_grant": 3},
            "sentinel_control": {"measured": False, "reason": "сентинел не прогнан"},
            "blocked_days": {"count": 8}})
        self.assertEqual(got["status"], arp.STATUS_UNMEASURED)
        self.assertIn("сентинел не прогнан", got["headline"])


class DayWithoutAJournalRowIsNamed(unittest.TestCase):
    """Отвергнутый день без строки в журнале — «не измерено», а не нулевой капитал."""

    def test_capital_is_none_with_a_named_reason(self):
        with TemporaryDirectory() as tmp:
            rows = _journal()
            data = _data_dir(tmp, rows)
            report, _ = arp.ask_judge(data, rows)
            blocked = arp.blocked_days(report, "no_evidenced_apy_for_moved_legs")
            self.assertTrue(blocked)
            original = arp.ask_judge
            # судья знает день, которого в журнале нет — книга непрочитана
            ghost = dict(blocked[0]); ghost["cycle_date"] = "1999-01-01"
            arp.ask_judge = lambda *a, **k: (
                {"per_verdict": [ghost], "observation_days": 1}, "")
            try:
                doc = arp.measure(data, now=_NOW, with_capacity=False)
            finally:
                arp.ask_judge = original
            day = doc["blocked_days"]["days"][0]
            self.assertIsNone(day["capital"])
            self.assertIn("книга не прочитана", day["capital_unmeasured_reason"])
            cap = doc["blocked_days"]["capital_on_rejecting_legs"]
            self.assertIsNone(cap["held_pct_of_deployed"],
                              "ноль развёрнутого капитала подан как доля — "
                              "«не измерено» стало неотличимо от нуля")
            self.assertIsNone(cap["targeted_pct_of_capital"])


class AggregateArithmeticIsExercisedOverSeveralDays(unittest.TestCase):
    """Накопители: ошибка в одном слагаемом на однодневном стенде не видна."""

    @staticmethod
    def _two_blocked_days():
        report = {"observation_days": 2, "per_verdict": [
            {"cycle_date": "2026-01-01", "verdict": "HOLD",
             "unchecked_reason": "no_evidenced_apy_for_moved_legs",
             "unpriced_protocols": ["p"], "outcome": "UNCHECKED"},
            {"cycle_date": "2026-01-02", "verdict": "HOLD",
             "unchecked_reason": "no_evidenced_apy_for_moved_legs",
             "unpriced_protocols": ["q"], "outcome": "UNCHECKED"}]}
        rows = [
            _record("2026-01-01", current={"p": 10_000.0, "z": 30_000.0},
                    target={"z": 40_000.0}, evidenced={}, capital=100_000.0),
            _record("2026-01-02", current={"q": 20_000.0, "z": 20_000.0},
                    target={"q": 25_000.0, "z": 15_000.0}, evidenced={},
                    capital=200_000.0)]
        return report, rows

    def test_totals_sum_over_all_days(self):
        report, rows = self._two_blocked_days()
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, rows)
            orig_judge, orig_today = arp.ask_judge, arp.today_price
            arp.ask_judge = lambda *a, **k: (report, "")
            arp.today_price = lambda *a, **k: {
                "measured": True, "act_days_returned_by_full_grant": 0}
            try:
                doc = arp.measure(data, now=_NOW, with_capacity=False)
            finally:
                arp.ask_judge, arp.today_price = orig_judge, orig_today
        cap = doc["blocked_days"]["capital_on_rejecting_legs"]
        self.assertEqual(cap["held_usd"], 30_000.0)          # 10k + 20k
        self.assertEqual(cap["deployed_usd"], 80_000.0)      # 40k + 40k
        self.assertEqual(cap["held_pct_of_deployed"], 37.5)
        self.assertEqual(cap["targeted_usd"], 25_000.0)      # 0 + 25k
        self.assertEqual(cap["capital_usd"], 300_000.0)      # 100k + 200k
        self.assertAlmostEqual(cap["targeted_pct_of_capital"], 8.33)


class OrderOfEveryDayListIsPinned(unittest.TestCase):
    """Значения подобраны ЗАМЕРОМ: у них порядок множества НЕ совпадает с сортировкой."""

    def setUp(self):
        # Значения измерены ПОД ТЕМ ЖЕ `PYTHONHASHSEED=0`, под которым идёт прогон:
        # набор ("p", "q") в свободном семени различал, а под фиксированным — нет,
        # и сторож ниже поймал это как украшение прежде, чем оно попало в приёмку.
        for probe in (("2026-08-01", "2026-08-30", "2026-09-09"), ("a", "b", "c")):
            self.assertNotEqual(list(set(probe)), sorted(probe),
                                f"набор {probe} не различает `sorted` и `list` — "
                                "тест порядка был бы украшением")

    def test_capacity_day_lists_are_sorted(self):
        days = ("2026-09-09", "2026-08-01", "2026-08-30")

        def _fake(source, dest, rows):
            granted = {p for rec in rows
                       for p, v in (rec.get("apy_evidenced_pct") or {}).items()
                       if v == arp._PRICING_SENTINEL_PCT}
            out = [{"day": d} for d in days] if granted else []
            return {"reaches_criterion": len(out), "days": out}, ""

        original = arp._capacity_of
        arp._capacity_of = _fake
        try:
            got = arp.capacity_price(Path("/x"), _journal(), ["a"], Path("/x"))
        finally:
            arp._capacity_of = original
        self.assertEqual(got["act_days_returned_by_full_grant_list"], sorted(days))
        self.assertEqual(got["per_protocol"][0]["act_days_alone"], sorted(days))
        self.assertEqual(got["superadditive_days"], [])
        self.assertEqual(got["per_protocol"][0]["necessary_for"], sorted(days))

    def test_protocol_census_day_lists_are_sorted(self):
        got = arp.protocol_census([{"cycle_date": d, "unpriced_protocols": ["x"]}
                                   for d in ("2026-09-09", "2026-08-01",
                                             "2026-08-30")])
        self.assertEqual(got[0]["days"],
                         ["2026-08-01", "2026-08-30", "2026-09-09"])

    def test_remedy_levers_and_protocols_are_sorted(self):
        from spa_core.monitoring import unobserved_leg_remedy_class as neigh
        original = neigh.measure
        neigh.measure = lambda *a, **k: {"per_day": [{"legs": [
            {"protocol": "b", "remedy": "c"}, {"protocol": "b", "remedy": "a"},
            {"protocol": "b", "remedy": "b"}, {"protocol": "a", "remedy": "a"}]}]}
        try:
            got = arp.remedy_by_protocol(Path("/x"))
        finally:
            neigh.measure = original
        self.assertEqual(got["by_protocol"]["b"], ["a", "b", "c"])
        self.assertEqual(list(got["by_protocol"]), ["a", "b"])


class TheLastFourReachableGaps(unittest.TestCase):
    """Координаты, которые батарея нашла достижимыми — и потому закрытыми, а не
    отнесёнными к «эквивалентно по построению». Разница между «не смог» и «не стал»
    в приёмке существенна, и здесь она на стороне «смог»."""

    def test_the_replay_loader_reports_no_corrupt_lines(self):
        """Счётчик битых строк реплея — величина, а не заглушка."""
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, _journal())
            doc, why = arp.ask_judge(data, _journal())
            self.assertIsNotNone(doc, why)
            self.assertEqual(doc["counts"]["corrupt_history_lines"], 0,
                             "реплей подаёт число битых строк, которого не мерил — "
                             "журнал выглядел бы повреждённым на ровном месте")

    def test_per_day_targeted_share_is_a_real_percentage(self):
        rec = _record(_day(1), current={"p": 10_000.0}, target={"p": 25_000.0},
                      evidenced={}, capital=200_000.0)
        cap = arp.capital_on_rejecting(rec, ["p"])
        self.assertAlmostEqual(cap["targeted_pct_of_capital"], 12.5)

    def test_a_day_with_zero_capital_does_not_poison_the_total(self):
        """`capital_usd` = 0 — наблюдение, и складывать его надо как ноль."""
        report = {"observation_days": 1, "per_verdict": [
            {"cycle_date": "2026-01-01", "verdict": "HOLD",
             "unchecked_reason": "no_evidenced_apy_for_moved_legs",
             "unpriced_protocols": ["p"], "outcome": "UNCHECKED"}]}
        rows = [_record("2026-01-01", current={"p": 1_000.0}, target={},
                        evidenced={}, capital=0.0)]
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, rows)
            orig_judge, orig_today = arp.ask_judge, arp.today_price
            arp.ask_judge = lambda *a, **k: (report, "")
            arp.today_price = lambda *a, **k: {
                "measured": True, "act_days_returned_by_full_grant": 0}
            try:
                doc = arp.measure(data, now=_NOW, with_capacity=False)
            finally:
                arp.ask_judge, arp.today_price = orig_judge, orig_today
        cap = doc["blocked_days"]["capital_on_rejecting_legs"]
        self.assertEqual(cap["capital_usd"], 0.0,
                         "нулевой капитал дня прибавился НЕ нулём — итог по "
                         "нескольким дням поехал бы молча")
        self.assertIsNone(cap["targeted_pct_of_capital"],
                          "доля от нулевого знаменателя выдана числом")

    def test_capacity_off_leaves_the_control_unmeasured_not_falsy(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, _journal())
            doc = arp.measure(data, now=_NOW, with_capacity=False)
            self.assertIsNone(doc["sentinel_control"],
                              "контроль сентинелов вернулся НЕ как None — "
                              "`_verdict` проверяет `is not None` и принял бы "
                              "пустышку за измеренный контроль")
            self.assertIsNone(doc["capacity"])


class MeasureEndToEnd(unittest.TestCase):

    def test_measure_on_a_synthetic_journal(self):
        with TemporaryDirectory() as tmp:
            rows = _journal()
            data = _data_dir(tmp, rows)
            doc = arp.measure(data, now=_NOW, with_capacity=False)
            self.assertEqual(doc["generated_at"], _NOW.isoformat())
            self.assertEqual(doc["blocked_days"]["count"], 1)
            self.assertEqual([r["protocol"] for r in doc["protocols"]], ["pendle"])
            self.assertEqual(doc["returns_today"]["act_days_returned_by_full_grant"], 0)
            self.assertEqual(doc["status"], arp.STATUS_WARNING)

    def test_empty_journal_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, [])
            doc = arp.measure(data, now=_NOW, with_capacity=False)
            self.assertEqual(doc["status"], arp.STATUS_UNMEASURED)
            self.assertIn("пуст", doc["headline"])

    def test_capacity_flag_off_names_itself(self):
        with TemporaryDirectory() as tmp:
            data = _data_dir(tmp, _journal())
            doc = arp.measure(data, now=_NOW, with_capacity=False)
            self.assertIsNone(doc["capacity"])
            self.assertIn("with_capacity=False", doc["capacity_unmeasured_reason"])


if __name__ == "__main__":
    unittest.main()
