"""Приёмка прибора «рассуживает ли audit_trail знаменатель» (заказ #555).

Каждый тест здесь — положительный контроль на конкретный способ соврать, а не
украшение. Список способов взят не из головы: это ровно те дефекты, которыми
ветка CIO уже болела и которые названы в правилах и в уроках прошлых циклов.

* **«Ось прогонов есть» выдано за ответ.** У носителя настоящая ось (десятки
  прогонов на день) — и ноль ставок. Прибор обязан сказать оба факта и НЕ дать
  первому закрыть второй: необходимое условие не есть достаточное.
* **Классификация по имени принята за вердикт.** Первая редакция слоя 2 искала
  ПОДСТРОКУ и признала ставкой ``strategy_loop_active`` («st-RATE-gy») на живом
  трейле. Токен + род значения закрывают класс; тест держит обе стороны.
* **Ноль наблюдений выдан за отсутствие цензуры.** «Ставок в тексте не нашлось»
  и «ставки есть и они не цензурированы» — РАЗНЫЕ ответы; второй требует
  наблюдений.
* **Цензура померена только предикатом текста.** Строка «значение ниже порога»
  верна по построению; второй, независимый способ — нога профинансирована в том
  же прогоне, а ставки о ней нет.
* **Разрешение сравнено с константой в коде.** Маржа берётся с диска: изменись
  она — прибор обязан сказать новое, а не процитировать ADR.
* **«Не измерено» выдано за ноль.** Нечитаемый носитель, отсутствующий
  знаменатель, отсутствующий артефакт маржей — третий исход с названной
  причиной, а не OK и не 0.
* **Одно наблюдение выдано за неподвижность.** ГРАНИЦА проверена числом: ровно
  два наблюдения — уже рассуживаемая пара, ровно одно — ещё нет.
* **Проводка объявлена, но не исполнена.** Мост объявляет артефакт продуктом и
  обязан ЗВАТЬ прибор; проверяется разбором дерева, а не подстрокой.

# FROZEN-DATE-OK: injected-clock — часы приходят ВХОДОМ: measure(..., now=ANCHOR),
# а все отметки сцен производны от того же якоря ANCHOR (D0/D1/RUN_*).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import audit_trail_rate_input_coverage as mod

#: Якорь. Всё время в этом файле производно ОТ НЕГО и передаётся коду
#: аргументом — ни одна сцена не спрашивает времени у стены.
ANCHOR = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

D0 = (ANCHOR - timedelta(days=2)).date().isoformat()
D1 = (ANCHOR - timedelta(days=1)).date().isoformat()

RUN_A = f"{D0}:aaaaaaaaaaaaaaaa"
RUN_B = f"{D0}:bbbbbbbbbbbbbbbb"
RUN_C = f"{D1}:cccccccccccccccc"


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _journal_row(day: str, book) -> dict:
    return {"cycle_date": day, "book_id": "conservative",
            "current_positions": dict(book), "target_positions": dict(book)}


def _trail_row(run: str, event: str, data: dict) -> dict:
    """Запись трейла в форме живого ``audit_trail.jsonl``."""
    return {"event_id": f"{run}-{event}", "correlation_id": run,
            "snapshot_id": run, "event_type": event,
            "timestamp": f"{run[:10]}T08:00:00+00:00", "data": data,
            "prev_event_id": None}


def _refusal(leg: str, value: str, floor: str = "1.0") -> str:
    """Точная форма строки, которой RiskPolicy печатает отказ по ставке."""
    return f"{leg}: APY {value}% below minimum {floor}% (not attractive)"


def fb_path() -> str:
    """Путь к исходнику моста находок — берётся у самого модуля, не выписан."""
    from spa_core.monitoring import findings_bridge

    return findings_bridge.__file__


class _Scene(unittest.TestCase):
    """Общая сцена: журнал, трейл и ПОДМЕНЁННЫЙ знаменатель.

    Знаменатель подменяется намеренно: канонический производитель
    (``shadow_trigger_eval``) требует половины живого ``data/``, и тянуть его в
    каждую сцену значило бы мерить не то. Проводку к настоящему производителю
    проверяет отдельный тест ниже — ВЫЗОВОМ, а не объявлением.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir(parents=True)
        self._real_scored = mod.scored_days
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: setattr(mod, "scored_days", self._real_scored))

    def pin_denominator(self, days):
        mod.scored_days = lambda _data_dir: (None if days is None else set(days))

    def measure(self):
        return mod.measure(self.data, now=ANCHOR)

    def write_journal(self, rows):
        _write_jsonl(self.data / mod.HISTORY_FILENAME, rows)

    def write_trail(self, rows):
        _write_jsonl(self.data / mod.CARRIER_FILENAME, rows)

    def write_margins(self, margins):
        (self.data / mod.MARGINS_FILENAME).write_text(
            json.dumps({"generated_at": ANCHOR.isoformat(),
                        "protocols": margins}, ensure_ascii=False),
            encoding="utf-8")


# ─────────────────────────── слой 1: ось прогонов ───────────────────────────
class RunAxis(_Scene):
    """Ось прогонов — то, чего не хватило предыдущему кандидату."""

    def test_the_axis_is_measured_and_is_explicitly_not_the_answer(self):
        """Ось есть, ставок нет — и первое НЕ имеет права закрыть второе.

        Это главный способ соврать этим прибором: напечатать «трейл покрывает
        7 дней знаменателя» и умолкнуть. Читатель прочтёт это как «семь дней
        рассужены», хотя рассужено ноль.
        """
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "cycle_start", {"cycle_date": D0}),
            _trail_row(RUN_B, "cycle_start", {"cycle_date": D0}),
        ])
        self.pin_denominator([D0])

        doc = self.measure()
        axis = doc["run_axis"]
        self.assertEqual(axis["denominator_days_touched"], 1)
        self.assertEqual(axis["denominator_days_with_two_or_more_runs"], 1)
        self.assertEqual(axis["runs_per_touched_day"], {D0: 2})
        self.assertIn("не достаточное", axis["not_the_answer"])
        # …и при этом рассужено НОЛЬ, а вердикт — CRITICAL.
        self.assertEqual(doc["coverage"]["pairs_adjudicable"], 0)
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)

    def test_a_day_with_one_run_is_counted_apart_from_a_day_with_two(self):
        """ГРАНИЦА оси названа числом: один прогон — ещё не ось."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0}),
                            _journal_row(D1, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "cycle_start", {"cycle_date": D0}),
            _trail_row(RUN_B, "cycle_start", {"cycle_date": D0}),
            _trail_row(RUN_C, "cycle_start", {"cycle_date": D1}),
        ])
        self.pin_denominator([D0, D1])

        axis = self.measure()["run_axis"]
        self.assertEqual(axis["denominator_days_touched"], 2)
        self.assertEqual(axis["denominator_days_with_two_or_more_runs"], 1)
        self.assertEqual(axis["days_with_two_or_more_runs"], [D0])

    def test_a_day_the_trail_never_saw_is_not_counted_as_touched(self):
        """Отсутствие дня в трейле — отсутствие, а не покрытие."""
        self.write_journal([_journal_row(D1, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "cycle_start", {"cycle_date": D0})])
        self.pin_denominator([D1])

        axis = self.measure()["run_axis"]
        self.assertEqual(axis["denominator_days_touched"], 0)
        self.assertEqual(axis["days_touched"], [])


# ────────────────────── слой 2: объявляет ли запись ставку ──────────────────────
class Quantity(_Scene):
    """Величина — то, чего у носителя нет, и это ответ на заказ."""

    def _one_record(self, data: dict):
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "allocation_proposal", data)])
        self.pin_denominator([D0])

    def test_a_usd_only_record_declares_no_rate(self):
        """Живая форма записи: суммы в долларах и флаги — ставки нет."""
        self._one_record({"target_usd": {"aave_v3": 100.0}, "trimmed": False,
                          "model_used": "optimized_yield"})
        q = self.measure()["quantity"]
        self.assertFalse(q["declares_a_rate"])
        self.assertEqual(q["rate_bearing_paths"], [])

    def test_a_declared_rate_field_flips_the_verdict(self):
        """Обратная сторона: появись поле ставки — прибор обязан это увидеть.

        Без этого теста «ставок нет» было бы утверждением, истинным по
        построению: прибор, всегда отвечающий «нет», не есть прибор.
        """
        self._one_record({"target_usd": {"aave_v3": 100.0},
                          "apy_pct": {"aave_v3": 3.5}})
        q = self.measure()["quantity"]
        self.assertTrue(q["declares_a_rate"])
        self.assertIn("data.apy_pct.aave_v3", q["rate_bearing_paths"])

    def test_the_word_strategy_is_not_a_rate(self):
        """Замер, а не вкус: подстрочный критерий признавал ставкой «strategy».

        Живой трейл несёт ``data.strategy_loop_active`` — булев флаг, в чьём
        имени лежит «st-RATE-gy». Первая редакция слоя 2 объявила его полем
        ставки, и прибор напечатал «запись ставку ОБЪЯВЛЯЕТ». Токен и род
        значения закрывают класс; список исключений лечил бы поводы.
        """
        self._one_record({"strategy_loop_active": False,
                          "target_usd": {"aave_v3": 100.0}})
        q = self.measure()["quantity"]
        self.assertEqual(q["named_like_a_rate"], [])
        self.assertFalse(q["declares_a_rate"])

    def test_a_rate_named_field_that_is_not_a_number_is_rejected_and_named(self):
        """Имя называет ставку, значение — не число. Оба условия обязательны."""
        self._one_record({"apy_status": "unchecked",
                          "target_usd": {"aave_v3": 100.0}})
        q = self.measure()["quantity"]
        self.assertIn("data.apy_status", q["named_like_a_rate"])
        self.assertIn("data.apy_status", q["named_but_not_numeric"])
        self.assertFalse(q["declares_a_rate"])

    def test_the_leaf_population_is_shipped_whole_for_checking(self):
        """Классификацию обязано быть возможно ПРОВЕРИТЬ, а не принять на веру."""
        self._one_record({"target_usd": {"aave_v3": 100.0}, "trimmed": False})
        q = self.measure()["quantity"]
        self.assertIn("data.target_usd.aave_v3", q["leaf_paths"])
        self.assertEqual(q["leaf_paths"]["data.target_usd.aave_v3"]["types"],
                         ["float"])
        self.assertEqual(q["leaf_paths_total"], len(q["leaf_paths"]))


# ───────────────── слой 3: ловушка — числа, ПОХОЖИЕ на ставки ─────────────────
class TextBorneRateCoverage(_Scene):
    """Покрытие считается по ТОМУ ЖЕ правилу, что у ADR-318."""

    def test_two_observations_is_already_adjudicable_and_one_is_not(self):
        """ГРАНИЦА, а не окрестность, и предпосылка названа ЧИСЛОМ.

        У дня РОВНО два прогона; у ноги ``aave_v3`` РОВНО два значения, у ноги
        ``maple`` — РОВНО одно.
        """
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0, "maple": 50.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3"),
                                       _refusal("maple", "0.4")]}),
            _trail_row(RUN_B, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.9")]}),
        ])
        self.pin_denominator([D0])

        cov = self.measure()["coverage"]
        self.assertEqual(cov["pairs_total"], 2)
        self.assertEqual(cov["pairs_adjudicable"], 1)
        self.assertEqual(cov["by_verdict"],
                         {mod.ADJUDICABLE: 1, mod.WHY_LEG_ONCE: 1})
        self.assertEqual(cov["pairs_moved"], 1)

    def test_one_run_on_the_day_is_not_stillness(self):
        """Единственный прогон дня — НАЗВАННЫЙ класс, а не «ставка не двигалась»."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3")]}),
        ])
        self.pin_denominator([D0])

        doc = self.measure()
        self.assertEqual(doc["coverage"]["by_verdict"],
                         {mod.WHY_ONE_SNAPSHOT: 1})
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in doc["findings"]))

    def test_two_equal_observations_are_not_the_same_as_one(self):
        """«Значение одно» и «значений два и они равны» — РАЗНЫЕ ответы."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3")]}),
            _trail_row(RUN_B, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3")]}),
        ])
        self.pin_denominator([D0])

        cov = self.measure()["coverage"]
        self.assertEqual(cov["by_verdict"], {mod.ADJUDICABLE: 1})
        self.assertEqual(cov["pairs_moved"], 0)

    def test_the_surface_being_measured_is_named_in_the_artifact(self):
        """Без этой строки «day_absent_from_carrier=75» читается как ложь.

        Читатель решит, что поле ставки у записи есть, просто не на тех днях, —
        а поля нет вовсе, и мерилась ЗАПАСНАЯ поверхность.
        """
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "cycle_start", {"cycle_date": D0})])
        self.pin_denominator([D0])

        cov = self.measure()["coverage"]
        self.assertIn("ТЕКСТ нарушений", cov["surface"])

    def test_a_refusal_above_the_ceiling_is_read_too(self):
        """У отказа ДВЕ ветки; вторая не должна теряться молча."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict", {"violations": [
                "aave_v3: APY 44.0% exceeds maximum allowed 30.0% (risk too high)"]}),
            _trail_row(RUN_B, "risk_verdict", {"violations": [
                "aave_v3: APY 45.0% exceeds maximum allowed 30.0% (risk too high)"]}),
        ])
        self.pin_denominator([D0])

        doc = self.measure()
        self.assertEqual(doc["coverage"]["by_verdict"], {mod.ADJUDICABLE: 1})
        self.assertTrue(doc["censoring"]["censored"])


# ──────────────── слой 4: цензура и разрешение — запреты вне покрытия ────────────
class Censoring(_Scene):
    """Цензура меряется НА НОСИТЕЛЕ, а не вычитывается из кода писателя."""

    def test_no_observations_is_a_third_outcome_not_absence_of_censoring(self):
        """Ноль наблюдений НЕ есть «цензуры нет» — это третий исход."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "cycle_start", {"cycle_date": D0})])
        self.pin_denominator([D0])

        cens = self.measure()["censoring"]
        self.assertFalse(cens["measured"])
        self.assertIsNone(cens["censored"])
        self.assertIn("НЕ ИЗМЕРЕНА", cens["reason"])

    def test_every_observation_satisfying_its_own_predicate_is_censoring(self):
        """Первый способ: значение удовлетворяет предикату из своего же текста."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3")]}),
        ])
        self.pin_denominator([D0])

        cens = self.measure()["censoring"]
        self.assertTrue(cens["measured"])
        self.assertEqual(cens["observations"], 1)
        self.assertEqual(cens["satisfying_own_refusal_predicate"], 1)
        self.assertTrue(cens["censored"])

    def test_an_observation_inside_the_corridor_breaks_the_censoring_verdict(self):
        """Обратная сторона: ставка ВЫШЕ порога в той же строке ⇒ не цензура.

        Без этого теста «носитель цензурирован» было бы истинным по построению:
        предикат брался бы из текста, который его же и утверждает.
        """
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "7.5")]}),
        ])
        self.pin_denominator([D0])

        cens = self.measure()["censoring"]
        self.assertEqual(cens["satisfying_own_refusal_predicate"], 0)
        self.assertFalse(cens["censored"])

    def test_a_funded_leg_without_a_reported_rate_is_named(self):
        """Второй, НЕЗАВИСИМЫЙ способ — и он воспроизводит живой замер 20.06.

        В прогоне профинансированы две ноги, ставка сообщена об одной. Молчание
        о второй и есть цензура: о ноге, чья ставка прошла коридор, носитель
        молчит именно потому, что она прошла.
        """
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "allocation_proposal",
                       {"target_usd": {"aave_v3": 100.0, "compound_v3": 50.0}}),
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3")]}),
        ])
        self.pin_denominator([D0])

        cens = self.measure()["censoring"]
        self.assertEqual(cens["funded_legs_without_a_reported_rate"],
                         [{"snapshot_id": RUN_A,
                           "funded_without_rate": ["compound_v3"]}])


class Resolution(_Scene):
    """Различает ли сетка печати ту маржу, на которой стоя́т деньги."""

    def _scene(self, value: str, margins):
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", value)]}),
        ])
        self.write_margins(margins)
        self.pin_denominator([D0])

    def test_a_grid_coarser_than_the_deciding_margin_is_named_critical(self):
        """Живая форма: один знак после запятой против маржи 0.0001 пп."""
        self._scene("0.3", [{"protocol": "morpho_blue", "margin_pp": 0.0001,
                             "usd": 9474.0}])
        doc = self.measure()
        res = doc["resolution"]
        self.assertTrue(res["measured"])
        self.assertEqual(res["decimals"], 1)
        self.assertEqual(res["grid_pp"], 0.1)
        self.assertEqual(res["finest_margin_pp"], 0.0001)
        self.assertFalse(res["resolves_the_deciding_margin"])
        self.assertTrue(any("грубее самой узкой маржи" in f
                            for f in doc["findings"]))

    def test_a_grid_finer_than_the_margin_flips_the_verdict(self):
        """Обратная сторона: маржа берётся С ДИСКА, а не из памяти прибора.

        Дай маржам широкое значение — и вердикт обязан перевернуться. Прибор,
        помнящий вывод ADR, перестаёт быть прибором.
        """
        self._scene("0.3", [{"protocol": "aave_v3", "margin_pp": 5.0,
                             "usd": 100.0}])
        res = self.measure()["resolution"]
        self.assertTrue(res["resolves_the_deciding_margin"])

    def test_missing_margins_are_a_third_outcome_not_sufficient_resolution(self):
        """Артефакта маржей нет ⇒ «не измерено» с причиной, а не тихое «хватает»."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3")]}),
        ])
        self.pin_denominator([D0])

        doc = self.measure()
        res = doc["resolution"]
        self.assertFalse(res["measured"])
        self.assertIsNone(res["resolves_the_deciding_margin"])
        self.assertTrue(any(f.startswith("[НЕ ИЗМЕРЕНО]")
                            for f in doc["findings"]))


# ───────────────────── слой 5: сшиваются ли оси прогонов ─────────────────────
class RunAxisJoin(_Scene):
    """Одолжима ли ось прогонов трейла носителю ставок."""

    def _scene(self, rate_carrier_ids):
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "cycle_start", {"cycle_date": D0})])
        _write_jsonl(self.data / mod.RATE_CARRIER_FILENAME,
                     [{"snapshot": sid, "adapter": "aave_v3", "apy": 3.0,
                       "kind": "hint_winner"} for sid in rate_carrier_ids])
        self.pin_denominator([D0])

    def test_disjoint_identifiers_mean_no_join(self):
        """Живая форма: «день:хеш» против отметки стены — общих ноль."""
        self._scene([f"{D0}T09:30:00.000000+00:00"])
        join = self.measure()["run_axis_join"]
        self.assertTrue(join["measured"])
        self.assertEqual(join["shared_run_ids"], 0)
        self.assertFalse(join["joinable_by_identity"])

    def test_a_shared_identifier_flips_the_verdict(self):
        """Обратная сторона: совпади идентификаторы — сшивка возможна."""
        self._scene([RUN_A])
        join = self.measure()["run_axis_join"]
        self.assertEqual(join["shared_run_ids"], 1)
        self.assertTrue(join["joinable_by_identity"])

    def test_a_missing_rate_carrier_is_a_third_outcome(self):
        """Носителя ставок нет ⇒ «не измерено», а не «сшивка невозможна»."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "cycle_start", {"cycle_date": D0})])
        self.pin_denominator([D0])

        join = self.measure()["run_axis_join"]
        self.assertFalse(join["measured"])
        self.assertIsNone(join["joinable_by_identity"])


# ──────────────────────── отказы: третий исход, не ноль ────────────────────────
class Refusals(_Scene):
    """«Нечем измерить» и «измерено, всё тихо» обязаны быть различимы."""

    def test_an_unreadable_trail_is_unmeasured_not_ok(self):
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.pin_denominator([D0])

        doc = self.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertFalse(doc["coverage"]["measured"])
        self.assertTrue(doc["third_outcomes"])

    def test_a_missing_denominator_is_unmeasured_not_full_coverage_of_zero(self):
        """``None`` от производителя ⇒ «не измерено», а не «знаменатель пуст»."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "cycle_start", {"cycle_date": D0})])
        self.pin_denominator(None)

        doc = self.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertFalse(doc["coverage"]["measured"])

    def test_a_broken_line_does_not_take_the_measurement_down(self):
        """Битая строка называется, а не рушит замер и не молчит."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        path = self.data / mod.CARRIER_FILENAME
        path.write_text(
            json.dumps(_trail_row(RUN_A, "cycle_start", {"cycle_date": D0}))
            + "\n{ не json\n", encoding="utf-8")
        self.pin_denominator([D0])

        doc = self.measure()
        self.assertEqual(doc["carrier"]["records"], 1)
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)

    def test_unchecked_is_counted_apart_from_zero(self):
        """Счётчик «не измерено» отдельный: растворив его, мы бы онемели."""
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([_trail_row(RUN_A, "cycle_start", {"cycle_date": D0})])
        self.pin_denominator([D0])

        doc = mod.run(str(self.data.parent), now=ANCHOR, write=False)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
        self.assertGreaterEqual(doc["counts"]["critical"], 1)


# ────────────────────────────── проводка ──────────────────────────────────
class Wiring(_Scene):
    """Прибор обязан ДОХОДИТЬ ДО ЧИТАТЕЛЯ, а не только считать (урок ADR-317)."""

    def _full_scene(self):
        self.write_journal([_journal_row(D0, {"aave_v3": 100.0})])
        self.write_trail([
            _trail_row(RUN_A, "allocation_proposal",
                       {"target_usd": {"aave_v3": 100.0}}),
            _trail_row(RUN_B, "risk_verdict",
                       {"violations": [_refusal("aave_v3", "0.3")]}),
        ])
        self.write_margins([{"protocol": "aave_v3", "margin_pp": 0.0001,
                             "usd": 100.0}])
        self.pin_denominator([D0])

    def test_run_writes_exactly_one_file_its_own(self):
        """Герметичность: прибор не трогает соседних артефактов.

        Проверяется СОСТАВОМ каталога до и после, а не отсутствием исключения:
        «не упало» о записи в чужой файл не говорит ничего.
        """
        self._full_scene()
        before = {p.name for p in self.data.iterdir()}
        mod.run(str(self.data.parent), now=ANCHOR, write=True)
        after = {p.name for p in self.data.iterdir()}
        self.assertEqual(after - before, {mod.OUTPUT_FILENAME})

    def test_the_report_reaches_the_office_reader_by_call(self):
        """Отчёт шага 0-офис зовёт форматтер прибора — вызовом, не объявлением."""
        import scripts.consume_office_reports as office

        self._full_scene()
        doc = mod.run(str(self.data.parent), now=ANCHOR, write=False)
        lines = office._summarize_json(mod.OUTPUT_FILENAME, doc)
        self.assertTrue(lines, "офис не напечатал об этом артефакте ничего")
        self.assertTrue(any("заказ #555" in ln for ln in lines))

    def test_the_office_prints_the_axis_before_the_quantity(self):
        """Порядок строк — часть утверждения, и он закреплён.

        «Ось есть» первой строкой без «величины нет» второй — самый дешёвый
        способ этим прибором соврать.
        """
        import scripts.consume_office_reports as office

        self._full_scene()
        doc = mod.run(str(self.data.parent), now=ANCHOR, write=False)
        lines = office._summarize_json(mod.OUTPUT_FILENAME, doc)
        axis_at = next(i for i, ln in enumerate(lines) if "ось прогонов" in ln)
        qty_at = next(i for i, ln in enumerate(lines) if "величина" in ln)
        self.assertLess(axis_at, qty_at)

    def test_the_bridge_declares_the_artifact_as_its_product(self):
        """Артефакт объявлен продуктом ступени переписей — всеми записями."""
        from spa_core.monitoring import findings_bridge as fb

        self.assertIn(f"data/{mod.OUTPUT_FILENAME}", fb.PRODUCES)
        self.assertIn("audit_trail_rate_input_coverage", fb.CENSUS_STAGE)
        self.assertEqual(
            fb.CENSUS_PRODUCT["audit_trail_rate_input_coverage"]["artifact"],
            f"data/{mod.OUTPUT_FILENAME}")

    def test_the_bridge_really_calls_the_instrument_in_main(self):
        """Мост ЗОВЁТ прибор — проверено разбором дерева, а не подстрокой.

        Мутация «вызов `run()` заменён константой» пережила 231 файл-сторож
        (замер #554), потому что объявление в `PRODUCES` от неё не страдает:
        артефакт просто перестал бы производиться, и молчание прибора стало бы
        неотличимо от «находок нет».
        """
        main = next((n for n in ast.walk(ast.parse(
            Path(fb_path()).read_text(encoding="utf-8")))
            if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
        self.assertIsNotNone(main, "в мосте находок нет функции `main`")

        called = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "audit_trail_rate_input_coverage"
            for node in ast.walk(main))
        self.assertTrue(called,
                        "`main()` моста находок не вызывает "
                        "audit_trail_rate_input_coverage.run — артефакт "
                        "объявлен продуктом, но не производится")

    def test_the_office_knows_the_producer_of_the_artifact(self):
        """Без производителя «артефакта нет» неотличимо от «бегун не пробовал»."""
        import scripts.consume_office_reports as office

        self.assertEqual(office._PRODUCER[mod.OUTPUT_FILENAME],
                         "spa_core/monitoring/audit_trail_rate_input_coverage.py")

    def test_the_canonical_denominator_producer_is_actually_asked(self):
        """Знаменатель берётся у ``shadow_trigger_eval``, а не выписан в код.

        Проверяется ВЫЗОВОМ подменённого производителя: список, скопированный в
        модуль, пережил бы любую правку критерия взвода и молчал бы об этом.
        """
        import sys
        import types

        seen = {}
        fake = types.ModuleType("spa_core.paper_trading.shadow_trigger_eval")

        def evaluate_window(data_dir, write=True):
            seen["data_dir"] = str(data_dir)
            seen["write"] = write
            return {"per_verdict": [
                {"cycle_date": D0, "trivial": False, "outcome": "hit"},
                {"cycle_date": D1, "trivial": True, "outcome": "hit"},
            ]}

        fake.evaluate_window = evaluate_window
        package = __import__("spa_core.paper_trading", fromlist=["x"])
        real_mod = sys.modules.get("spa_core.paper_trading.shadow_trigger_eval")
        real_attr = getattr(package, "shadow_trigger_eval", None)
        sys.modules["spa_core.paper_trading.shadow_trigger_eval"] = fake
        setattr(package, "shadow_trigger_eval", fake)
        try:
            days = self._real_scored(self.data)
        finally:
            if real_mod is not None:
                sys.modules["spa_core.paper_trading.shadow_trigger_eval"] = real_mod
            else:  # pragma: no cover — модуль не был импортирован до теста
                sys.modules.pop("spa_core.paper_trading.shadow_trigger_eval", None)
            if real_attr is not None:
                setattr(package, "shadow_trigger_eval", real_attr)

        self.assertEqual(seen.get("data_dir"), str(self.data))
        self.assertIs(seen.get("write"), False,
                      "знаменатель спрошен с записью — замер обязан быть "
                      "read-only")
        # trivial-день в знаменатель не входит.
        self.assertEqual(days, {D0})

    def test_the_instrument_is_not_in_the_journal_key_readers_census(self):
        """Не-потребитель ключа НЕ вносится в перепись (класс ADR-317).

        Внеси — и ``probe_readers`` выдал бы `insensitive`, ИСТИННЫЙ ПО
        ПОСТРОЕНИЮ, деля знаменатель переписи с настоящими потребителями. Тест
        держит и обратную сторону: если прибор однажды начнёт читать ключ, эта
        проверка обязана покраснеть и потребовать регистрации.
        """
        from spa_core.monitoring import decision_journal_coverage as djc

        key = djc.__dict__.get("RATE_KEY") or "apy_evidenced" + "_pct"
        source = Path(mod.__file__).read_text(encoding="utf-8")
        touches = key in source
        declared = any(r["module"].endswith("audit_trail_rate_input_coverage")
                       for r in djc.READERS)
        self.assertEqual(touches, declared,
                         "прибор обязан числиться в READERS тогда и только "
                         "тогда, когда он касается ключа ставки журнала")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
