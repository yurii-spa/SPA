"""Приёмка прибора «что теряет hit_rate от одной строки в день» (заказ #552).

Каждый тест здесь — положительный контроль на конкретный способ соврать, а не
украшение. Список способов взят не из головы: это ровно те дефекты, которыми
ветка CIO уже болела и которые названы в правилах и в памяти цикла.

* **«не измерено» выдано за ноль.** День, которого нет в носителе прогонов,
  обязан быть ТРЕТЬИМ классом, а не «прогон был один»: последнее изготовило бы
  чистый знаменатель из неизмеренного.
* **Отрицательный результат без положительного контроля.** «Вход не двигался»
  неотличимо от «реконструкция сломана», пока реконструкция не подтверждена
  тождеством значения. Контроль обязан УМЕТЬ провалиться — и здесь он проваливается.
* **Контроль, истинный ПО ПОСТРОЕНИЮ.** Ноль сравнимых дней НЕ есть «контроль
  пройден»; ноль сравнимых предметов НЕ есть «подстановка допустима».
* **Проверена сама ГРАНИЦА, а не окрестность** (условие #551): ровно половина
  согласных прогонов — НЕ большинство; прогон РОВНО в отметку сделки видит
  состояние ПОСЛЕ неё.
* **Подстановка соседней величины.** Прибор обязан пересчитывать род величин
  каждый прогон и запрещать подстановку, а не цитировать вывод ADR.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import day_replacement_verdict_loss as mod

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _journal(day: str, positions: dict, *, verdict: str = "HOLD",
             target: dict = None) -> dict:
    return {
        "cycle_date": day,
        "verdict": verdict,
        "current_positions": dict(positions),
        "target_positions": dict(target if target is not None else positions),
    }


def _start(day: str, ts: str, cid: str) -> dict:
    return {"event_type": "cycle_start", "correlation_id": cid,
            "timestamp": ts, "data": {"cycle_date": day}}


def _trade(ts: str, before: dict, after: dict) -> dict:
    return {"event_type": "trade_executed", "correlation_id": "t-" + ts,
            "timestamp": ts,
            "data": {"from_allocation": dict(before), "to_allocation": dict(after)}}


def _proposal(cid: str, target: dict) -> dict:
    return {"event_type": "allocation_proposal", "correlation_id": cid,
            "timestamp": "2026-08-27T00:00:00+00:00",
            "data": {"target_usd": dict(target)}}


class _Scene:
    """Одноразовый каталог данных. Знаменатель hit_rate задаётся ЯВНО.

    Подмена идёт атрибутом пакета, а не только `sys.modules`: при сборе набора
    модуль уже импортирован, и подмена одной лишь записи в `sys.modules`
    оставила бы субъекту старую ссылку (замер: зелёный в одиночку, красный
    в наборе).
    """

    def __init__(self, journal, audit, scored=None):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        _write_jsonl(self.data / mod.HISTORY_FILENAME, journal)
        _write_jsonl(self.data / mod.AUDIT_FILENAME, audit)
        self._scored = scored

    def __enter__(self):
        self._orig = mod._scored_days
        if self._scored is not None:
            mod._scored_days = lambda _d: set(self._scored)
        return self

    def __exit__(self, *exc):
        mod._scored_days = self._orig
        self._tmp.cleanup()
        return False

    def measure(self):
        return mod.measure(self.data, now=NOW)


# ───────────────────────── нормализация книги ─────────────────────────


class NormBookTests(unittest.TestCase):
    def test_zero_leg_and_absent_leg_are_the_same_state(self):
        """Нулевая нога — не движение капитала, а форма записи."""
        self.assertEqual(mod._norm_book({"a": 100.0, "b": 0.0}),
                         mod._norm_book({"a": 100.0}))

    def test_rounding_grid_is_cents_and_the_boundary_is_tested(self):
        """ГРАНИЦА: полцента вниз — то же состояние, полтора — уже другое."""
        base = mod._norm_book({"a": 100.00})
        self.assertEqual(mod._norm_book({"a": 100.004}), base)
        self.assertNotEqual(mod._norm_book({"a": 100.005 + 1e-9}), base)

    def test_unparsable_book_is_none_not_empty(self):
        """Неразобранная книга — не пустая книга: иначе «нет данных» = «всё вышли»."""
        self.assertIsNone(mod._norm_book({"a": "не число"}))
        self.assertIsNone(mod._norm_book(None))
        self.assertIsNotNone(mod._norm_book({}))


# ───────────────────────── реконструкция книги ─────────────────────────


class TimelineTests(unittest.TestCase):
    def test_seed_is_the_first_trades_from_allocation(self):
        """До первой сделки книга известна — её несёт сама первая сделка."""
        audit = [_trade("2026-08-27T10:00:00+00:00", {"a": 10.0}, {"b": 10.0})]
        tl = mod._book_timeline(audit)
        self.assertEqual(mod._state_at(tl, "2026-08-27T09:00:00+00:00"), {"a": 10.0})

    def test_run_exactly_at_the_trade_stamp_sees_the_state_after_it(self):
        """ГРАНИЦА: отметка сделки принадлежит состоянию ПОСЛЕ сделки."""
        ts = "2026-08-27T10:00:00+00:00"
        tl = mod._book_timeline([_trade(ts, {"a": 10.0}, {"b": 10.0})])
        self.assertEqual(mod._state_at(tl, ts), {"b": 10.0})
        # и ровно на микросекунду раньше — состояние ДО
        self.assertEqual(mod._state_at(tl, "2026-08-27T09:59:59.999999+00:00"),
                         {"a": 10.0})

    def test_no_trades_at_all_yields_no_timeline(self):
        """Нет носителя сделок ⇒ состояние не выдумывается."""
        self.assertEqual(mod._book_timeline([]), [])
        self.assertIsNone(mod._state_at([], "2026-08-27T10:00:00+00:00"))


# ──────────────── контроль реконструкции обязан УМЕТЬ упасть ────────────────


class ReconstructionControlTests(unittest.TestCase):
    def _scene(self, journal_positions):
        journal = [_journal("2026-08-27", journal_positions)]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T08:00:00+00:00", "c1"),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
        ]
        return _Scene(journal, audit, scored={"2026-08-27"})

    def test_control_passes_when_the_survivor_state_matches_the_writer(self):
        with self._scene({"b": 100.0}) as scene:
            doc = scene.measure()
        self.assertTrue(doc["reconstruction_control"]["passed"])
        self.assertNotEqual(doc["status"], mod.STATUS_UNMEASURED)

    def test_one_mismatch_refuses_the_whole_layer_fail_closed(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: сломанная реконструкция обязана краснеть.

        Без него «вход не двигался» неотличимо от «прибор считает не то».
        """
        with self._scene({"совсем": 1.0}) as scene:
            doc = scene.measure()
        self.assertFalse(doc["reconstruction_control"]["passed"])
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIsNone(doc["input_movement"])
        self.assertIn("тождеством значения", doc["unmeasured_reason"])

    def test_zero_comparable_days_is_not_a_passed_control(self):
        """Контроль, истинный ПО ПОСТРОЕНИЮ, — украшение: нечего сверять ⇒ не пройден."""
        journal = [_journal("2026-08-27", {"a": 1.0})]
        audit = [_start("2026-08-27", "2026-08-27T08:00:00+00:00", "c1")]
        with _Scene(journal, audit, scored={"2026-08-27"}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["reconstruction_control"]["days_checked"], 0)
        self.assertFalse(doc["reconstruction_control"]["passed"])
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)


# ─────────────────── экспозиция: три класса, и третий не ноль ───────────────


class ExposureTests(unittest.TestCase):
    def _audit_two_days(self):
        return [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T08:00:00+00:00", "c1"),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
            _start("2026-08-28", "2026-08-28T10:00:00+00:00", "c3"),
        ]

    def test_day_absent_from_the_run_carrier_is_a_third_class_not_single_run(self):
        """Молчание носителя — НЕ «прогон был один»."""
        journal = [_journal("2026-08-27", {"b": 100.0}),
                   _journal("2026-08-28", {"b": 100.0}),
                   _journal("2026-08-29", {"b": 100.0})]
        with _Scene(journal, self._audit_two_days(),
                    scored={"2026-08-27", "2026-08-28", "2026-08-29"}) as scene:
            doc = scene.measure()
        exp = doc["exposure"]
        self.assertEqual(exp["scored_days"], 3)
        self.assertEqual(exp["on_multi_run_days"], 1)
        self.assertEqual(exp["on_single_run_days"], 1)
        self.assertEqual(exp["population_unmeasured_days"], 1)
        self.assertEqual(exp["days_population_unmeasured"], ["2026-08-29"])
        # и это названо третьим исходом вслух, а не растворено
        self.assertTrue(any("население прогонов НЕ ИЗМЕРЕНО" in t
                            for t in doc["third_outcomes"]))

    def test_a_run_is_dated_by_its_cycle_date_not_by_its_stamp(self):
        """Прогон, начатый ПОСЛЕ полуночи UTC, принадлежит своему циклу.

        Батарея мутаций поймала это место пустым: все прежние сцены ставили
        отметку в тот же календарный день, что и `cycle_date`, поэтому подмена
        датировки на `timestamp[:10]` была на них НО-ОП. Тест, истинный по
        построению сцены, ничего не проверяет.
        """
        journal = [_journal("2026-08-27", {"b": 100.0})]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T23:50:00+00:00", "c1"),
            # тот же ЦИКЛ, но уже следующие сутки по стенным часам
            _start("2026-08-27", "2026-08-28T00:10:00+00:00", "c2"),
        ]
        with _Scene(journal, audit, scored={"2026-08-27"}) as scene:
            doc = scene.measure()
        day = doc["days"][0]
        self.assertEqual(day["cycle_date"], "2026-08-27")
        self.assertEqual(day["runs"], 2)
        self.assertEqual(day["population_class"], mod.POP_MULTI)
        # и заполуночный прогон не породил дня, которого в журнале нет
        self.assertEqual([d["cycle_date"] for d in doc["days"]], ["2026-08-27"])

    def test_exposed_denominator_is_reported_CRITICAL(self):
        """Отрицательный вердикт обязан иметь пару: сцена, где прибор КРАСНЕЕТ.

        Без неё «CRITICAL не выставляется никогда» — мутация, которую набор
        не отличает от исправного кода (замер батареи: выжила).
        """
        journal = [_journal("2026-08-27", {"b": 100.0}),
                   _journal("2026-08-29", {"b": 100.0})]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T08:00:00+00:00", "c1"),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
        ]
        with _Scene(journal, audit,
                    scored={"2026-08-27", "2026-08-29"}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)
        self.assertTrue(any(x.startswith("[CRITICAL]") for x in doc["findings"]))
        # и вердикт назван утверждением об ЭВИДЕНСЕ, а не о правоте HOLD
        self.assertTrue(any("НЕ о том, что HOLD был неправ" in x
                            for x in doc["findings"]))

    def test_EXACTLY_ONE_exposed_day_is_already_CRITICAL(self):
        """ГРАНИЦА порога, а не две точки по разные стороны (условие #551).

        Найдено батареей цикла #554: мутация `if exposed:` → `if exposed > 1:`
        пережила 9154 теста. Причина — в сценах: у сцены-CRITICAL выше
        экспонированных дней ДВА (27.08 многопрогонный + 29.08 без носителя),
        у сцены-OK — НОЛЬ. Обе меряют «больше нуля» и «ноль», и ни одна не
        меряет САМУ единицу, на которой порог и решает.

        Один день знаменателя, стоящий не на измеренном единственном решении, —
        уже утверждение об эвиденсе критерия взвода. Порог здесь `>= 1`, и
        «почти чисто» отдельным исходом не является.
        """
        journal = [_journal("2026-08-27", {"b": 100.0})]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T08:00:00+00:00", "c1"),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
        ]
        with _Scene(journal, audit, scored={"2026-08-27"}) as scene:
            doc = scene.measure()
        exposure = doc["exposure"]
        # предпосылка сцены названа ЧИСЛОМ: экспонированных дней ровно один
        self.assertEqual(exposure["on_multi_run_days"]
                         + exposure["population_unmeasured_days"], 1)
        self.assertEqual(exposure["scored_days"], 1)
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)

    def test_days_outside_the_denominator_do_not_enter_the_exposure(self):
        """Экспозиция считается по ЗНАМЕНАТЕЛЮ, а не по журналу целиком."""
        journal = [_journal("2026-08-27", {"b": 100.0}),
                   _journal("2026-08-28", {"b": 100.0})]
        with _Scene(journal, self._audit_two_days(),
                    scored={"2026-08-28"}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["exposure"]["scored_days"], 1)
        self.assertEqual(doc["exposure"]["on_multi_run_days"], 0)

    def test_erased_runs_are_counted_under_the_denominator_itself(self):
        journal = [_journal("2026-08-27", {"b": 100.0})]
        with _Scene(journal, self._audit_two_days(),
                    scored={"2026-08-27"}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["exposure"]["erased_runs_under_denominator"], 1)

    def test_all_single_run_and_still_no_movement_is_OK_not_critical(self):
        """Прибор ОБЯЗАН уметь сказать «потери нет» — иначе CRITICAL ничего не значит."""
        journal = [_journal("2026-08-28", {"b": 100.0})]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-28", "2026-08-28T10:00:00+00:00", "c3"),
        ]
        with _Scene(journal, audit, scored={"2026-08-28"}) as scene:
            doc = scene.measure()
        self.assertEqual(doc["status"], mod.STATUS_OK)
        self.assertEqual(doc["exposure"]["on_single_run_days"], 1)


# ──────────────────────── большинство: сама граница ────────────────────────


class MajorityTests(unittest.TestCase):
    def _scene(self, run_stamps, trade_stamps, survivor_positions):
        journal = [_journal("2026-08-27", survivor_positions)]
        audit = []
        prev = {"s0": 100.0}
        for i, ts in enumerate(trade_stamps):
            nxt = {f"s{i + 1}": 100.0}
            audit.append(_trade(ts, prev, nxt))
            prev = nxt
        for i, ts in enumerate(run_stamps):
            audit.append(_start("2026-08-27", ts, f"c{i}"))
        return _Scene(journal, audit, scored={"2026-08-27"})

    def test_exactly_half_agreeing_is_not_a_majority(self):
        """ГРАНИЦА (условие #551): 2 из 4 — НЕ большинство."""
        runs = ["2026-08-27T08:00:00+00:00", "2026-08-27T08:30:00+00:00",
                "2026-08-27T10:00:00+00:00", "2026-08-27T10:30:00+00:00"]
        with self._scene(runs, ["2026-08-27T09:00:00+00:00"],
                         {"s1": 100.0}) as scene:
            doc = scene.measure()
        day = doc["days"][0]
        self.assertEqual(day["runs_disagreeing_with_survivor"], 2)
        self.assertFalse(day["survivor_state_is_majority"])
        self.assertEqual(doc["input_movement"]["days_survivor_state_not_majority"], 1)

    def test_one_more_agreeing_tips_it_over(self):
        """И ровно на единицу дальше границы — большинство появляется."""
        runs = ["2026-08-27T08:00:00+00:00", "2026-08-27T08:30:00+00:00",
                "2026-08-27T10:00:00+00:00", "2026-08-27T10:30:00+00:00",
                "2026-08-27T10:40:00+00:00"]
        with self._scene(runs, ["2026-08-27T09:00:00+00:00"],
                         {"s1": 100.0}) as scene:
            doc = scene.measure()
        day = doc["days"][0]
        self.assertEqual(day["runs_disagreeing_with_survivor"], 2)
        self.assertTrue(day["survivor_state_is_majority"])
        self.assertEqual(doc["input_movement"]["days_survivor_state_not_majority"], 0)


# ──────────────────── род величин: подстановка запрещена ────────────────────


class SubjectDistinctnessTests(unittest.TestCase):
    def _scene(self, live_target, shadow_target):
        journal = [_journal("2026-08-27", {"b": 100.0}, target=shadow_target)]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
            _proposal("c2", live_target),
        ]
        return _Scene(journal, audit, scored={"2026-08-27"})

    def test_diverging_targets_forbid_the_substitution(self):
        with self._scene({"a": 1.0, "b": 2.0}, {"a": 1.0}) as scene:
            doc = scene.measure()
        subject = doc["subject_distinctness"]
        self.assertEqual(subject["different_subject_days"], 1)
        self.assertFalse(subject["substitution_admissible"])
        self.assertTrue(any("подстановка" in t for t in doc["third_outcomes"]))

    def test_the_verdict_is_recomputed_not_quoted(self):
        """Сойдись предметы — прибор ОБЯЗАН это увидеть, а не помнить старый ответ."""
        with self._scene({"a": 1.0}, {"a": 1.0}) as scene:
            doc = scene.measure()
        subject = doc["subject_distinctness"]
        self.assertEqual(subject["different_subject_days"], 0)
        self.assertTrue(subject["substitution_admissible"])
        self.assertFalse(any("подстановка" in t for t in doc["third_outcomes"]))

    def test_zero_comparable_days_is_not_admissible(self):
        """Ноль сравнимых предметов — не «сошлись», а «нечем мерить»."""
        journal = [_journal("2026-08-27", {"b": 100.0})]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
        ]
        with _Scene(journal, audit, scored={"2026-08-27"}) as scene:
            doc = scene.measure()
        subject = doc["subject_distinctness"]
        self.assertEqual(subject["days_compared"], 0)
        self.assertFalse(subject["substitution_admissible"])


# ───────────────────── главный отказ и границы доклада ─────────────────────


class RefusalTests(unittest.TestCase):
    def test_the_main_refusal_is_unconditional(self):
        """Вердикт стёртого прогона не измеряется НИКОГДА — даже на чистой сцене."""
        journal = [_journal("2026-08-28", {"b": 100.0})]
        audit = [_trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
                 _start("2026-08-28", "2026-08-28T10:00:00+00:00", "c3")]
        with _Scene(journal, audit, scored={"2026-08-28"}) as scene:
            doc = scene.measure()
        self.assertTrue(any("вердикты стёртых прогонов НЕ ИЗМЕРЕНЫ"
                            in t for t in doc["third_outcomes"]))

    def test_the_instrument_never_states_an_erased_runs_verdict(self):
        """Граница ответственности — в самом артефакте, а не только в прозе."""
        journal = [_journal("2026-08-27", {"b": 100.0})]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T08:00:00+00:00", "c1"),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
        ]
        with _Scene(journal, audit, scored={"2026-08-27"}) as scene:
            doc = scene.measure()
        blob = json.dumps(doc, ensure_ascii=False)
        # единственный вердикт в артефакте — вердикт ВЫЖИВШЕЙ строки журнала
        self.assertEqual(sum(1 for d in doc["days"] if "journal_verdict" in d),
                         len(doc["days"]))
        self.assertNotIn("erased_verdict", blob)
        self.assertIn("измерены быть не могут", blob)

    def test_missing_carrier_is_unmeasured_with_a_named_reason_not_zeros(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            _write_jsonl(data / mod.HISTORY_FILENAME,
                         [_journal("2026-08-27", {"a": 1.0})])
            doc = mod.measure(data, now=NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIn(mod.AUDIT_FILENAME, doc["unmeasured_reason"])
        self.assertIsNone(doc["exposure"])

    def test_carrier_without_cycle_start_is_unmeasured_not_empty(self):
        journal = [_journal("2026-08-27", {"a": 1.0})]
        audit = [_trade("2026-08-27T09:00:00+00:00", {"a": 1.0}, {"b": 1.0})]
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            _write_jsonl(data / mod.HISTORY_FILENAME, journal)
            _write_jsonl(data / mod.AUDIT_FILENAME, audit)
            doc = mod.measure(data, now=NOW)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIn("cycle_start", doc["unmeasured_reason"])


# ───────────────────────────── проводка ─────────────────────────────


class WiringTests(unittest.TestCase):
    # ЦИКЛ #586 — почему подменяется `evaluate_window`, а не весь модуль.
    # Правило отбора («не trivial и исход hit/miss») до #586 жило ЗДЕСЬ, копией,
    # и эти два теста были единственным его сторожем. Копия убрана: определение
    # знаменателя поднято в самого производителя
    # (`shadow_trigger_eval.scored_days`), потому что второй читатель того же
    # знаменателя появился в этом же цикле (`capital_observability_history`), и
    # ТРЕТЬЕЙ копии правила быть не должно — спор копий был бы молчаливым.
    # Тесты от этого НЕ ослаблены и проверка не снята (инв. #16): оба
    # утверждения ниже сохранены дословно — и `calls`, и отсечение
    # trivial/UNCHECKED, — но добываются они теперь ЧЕРЕЗ настоящий
    # `scored_days`, то есть тем самым путём, которым ходит субъект. Подменять
    # модуль целиком больше нельзя ровно потому, что заглушка не несёт нового
    # публичного входа, и такая подмена проверяла бы форму, которой у субъекта
    # уже нет. Само правило отсечения закреплено вторично и отдельно —
    # `test_capital_observability_history.py::…::test_canonical_producer_keeps_only_scored_days`.
    def test_denominator_comes_from_the_canonical_producer(self):
        """Знаменатель СПРАШИВАЕТСЯ у shadow_trigger_eval, а не выписан сюда.

        Проверяется ФОРМОЙ вызова: подменяется `evaluate_window` именно этого
        модуля, и субъект обязан прийти к нему через канонический `scored_days`.
        """
        # Модуль обязан быть импортирован ДО подмены: субъект берёт его через
        # `from ... import`, и если пакет его ещё не импортировал, тест был бы
        # зелёным в одиночку и красным в наборе (или наоборот).
        from spa_core.paper_trading import shadow_trigger_eval as ste

        calls = []

        def _window(data_dir, *, write=True, **kw):
            calls.append((Path(data_dir), write))
            return {"per_verdict": [
                {"cycle_date": "2026-08-27", "outcome": "hit", "trivial": False},
                {"cycle_date": "2026-08-28", "outcome": "hit", "trivial": True},
                {"cycle_date": "2026-08-29", "outcome": "UNCHECKED",
                 "trivial": False},
            ]}

        with mock.patch.object(ste, "evaluate_window", _window):
            scored = mod._scored_days(Path("/nowhere"))
        self.assertEqual(calls, [(Path("/nowhere"), False)])
        # trivial и UNCHECKED в знаменатель НЕ входят — это определение hit_rate
        self.assertEqual(scored, {"2026-08-27"})

    def test_denominator_failure_is_none_not_an_empty_set(self):
        """Пустое множество читалось бы как «знаменатель пуст» — это разные вещи."""
        from spa_core.paper_trading import shadow_trigger_eval as ste

        with mock.patch.object(ste, "evaluate_window",
                               side_effect=RuntimeError("носитель не прочитан")):
            self.assertIsNone(mod._scored_days(Path("/nowhere")))

    def test_unmeasured_denominator_refuses_the_exposure(self):
        journal = [_journal("2026-08-27", {"b": 100.0})]
        audit = [_trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
                 _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2")]
        with _Scene(journal, audit) as scene:
            scene_scored = mod._scored_days
            mod._scored_days = lambda _d: None
            try:
                doc = scene.measure()
            finally:
                mod._scored_days = scene_scored
        self.assertFalse(doc["exposure"]["measured"])
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)

    def test_run_creates_exactly_one_file_its_own(self):
        """Живое `data/` на запись не открывается — и это проверяется счётом."""
        journal = [_journal("2026-08-28", {"b": 100.0})]
        audit = [_trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
                 _start("2026-08-28", "2026-08-28T10:00:00+00:00", "c3")]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            _write_jsonl(data / mod.HISTORY_FILENAME, journal)
            _write_jsonl(data / mod.AUDIT_FILENAME, audit)
            before = {p.name for p in data.iterdir()}
            orig = mod._scored_days
            mod._scored_days = lambda _d: {"2026-08-28"}
            try:
                doc = mod.run(root=str(root), now=NOW)
            finally:
                mod._scored_days = orig
            after = {p.name for p in data.iterdir()}
        self.assertEqual(after - before, {mod.OUTPUT_FILENAME})
        self.assertEqual(doc["overall"], doc["status"])

    def test_report_leads_with_exposure_not_with_movement(self):
        """Порядок строк — часть смысла: движение без населения читается как замер всего."""
        journal = [_journal("2026-08-27", {"b": 100.0})]
        audit = [
            _trade("2026-08-27T09:00:00+00:00", {"a": 100.0}, {"b": 100.0}),
            _start("2026-08-27", "2026-08-27T08:00:00+00:00", "c1"),
            _start("2026-08-27", "2026-08-27T10:00:00+00:00", "c2"),
        ]
        with _Scene(journal, audit, scored={"2026-08-27"}) as scene:
            lines = mod.format_report(scene.measure())
        self.assertIn("знаменатель", lines[0])
        self.assertTrue(any("НЕ ДОКЛАДЫВАЕТ" in x for x in lines))
        self.assertTrue(any("ADVISORY" in x for x in lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
