"""Приёмка прибора «двигался ли ВТОРОЙ вход тени — ставки» (заказ #554).

Каждый тест здесь — положительный контроль на конкретный способ соврать, а не
украшение. Список способов взят не из головы: это ровно те дефекты, которыми
ветка CIO уже болела и которые названы в правилах и в уроках предыдущих циклов.

* **«не измерено» выдано за ноль.** День знаменателя, которого нет в носителе,
  обязан быть НАЗВАННЫМ классом, а не «ставка не двигалась»: последнее
  изготовило бы покой из отсутствия наблюдения.
* **Одно наблюдение выдано за неподвижность.** «Значение одно» и «значений два и
  они равны» — РАЗНЫЕ ответы, и различает их только счёт наблюдений.
* **Проверена сама ГРАНИЦА, а не окрестность** (условие #551): ровно ДВА
  наблюдения — уже рассуживаемая пара, ровно ОДНО — ещё нет. Предпосылка каждой
  сцены названа ЧИСЛОМ, а не подразумевается.
* **Доля перенесена с чужого населения.** Движение на днях носителя, которых нет
  в знаменателе, не имеет права поднять ни одну цифру знаменателя.
* **Контроль, истинный ПО ПОСТРОЕНИЮ.** Ноль сравнимых пар НЕ есть «род совпал»:
  это третий исход с названной причиной.
* **Ловушка заказа доказывается ЗАМЕРОМ, а не памятью.** Дай ряду два значения
  на один (адаптер, день) — и прибор обязан сказать новое, а не процитировать
  вывод ADR-316.
* **Отказ носителя выдан за покой.** Нечитаемый носитель ⇒ UNMEASURED, а не OK.

# FROZEN-DATE-OK: injected-clock — часы приходят ВХОДОМ: measure(..., now=ANCHOR),
# а все отметки носителей производны от того же якоря ANCHOR (D0/D1/SNAP_*).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import intraday_rate_input_movement as mod

#: Якорь. Всё время в этом файле производно ОТ НЕГО и передаётся коду
#: аргументом — ни одна сцена не спрашивает времени у стены.
ANCHOR = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

D0 = (ANCHOR - timedelta(days=2)).date().isoformat()
D1 = (ANCHOR - timedelta(days=1)).date().isoformat()

SNAP_A = (ANCHOR - timedelta(days=2, hours=6)).isoformat()
SNAP_B = (ANCHOR - timedelta(days=2, hours=1)).isoformat()
SNAP_C = (ANCHOR - timedelta(days=1, hours=6)).isoformat()
SNAP_D = (ANCHOR - timedelta(days=1, hours=1)).isoformat()


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _journal_row(day: str, book, rates=None) -> dict:
    return {
        "cycle_date": day,
        "book_id": "conservative",
        "current_positions": dict(book),
        "target_positions": dict(book),
        "apy_evidenced_pct": dict(rates or {}),
    }


def _carrier_row(snapshot: str, adapter: str, apy, kind: str = "hint_winner") -> dict:
    return {"observed_at": snapshot, "snapshot": snapshot, "kind": kind,
            "adapter": adapter, "pool": None, "apy": apy}


def fb_path() -> str:
    """Путь к исходнику моста находок — берётся у самого модуля, не выписан."""
    from spa_core.monitoring import findings_bridge

    return findings_bridge.__file__


def _series(points) -> dict:
    """Ряд по дням в форме живого ``apy_series_daily.json``."""
    return {"generated_at": ANCHOR.isoformat(), "series": points}


class _Scene(unittest.TestCase):
    """Общая сцена: журнал, носитель, ряд и ПОДМЕНЁННЫЙ знаменатель.

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


class Coverage(_Scene):
    """Слой 1 — первый результат заказа: что носитель РЕАЛЬНО покрывает."""

    def test_a_denominator_day_absent_from_the_carrier_is_not_stillness(self):
        """День вне носителя — НАЗВАННЫЙ класс, а не «ставка не двигалась».

        Ровно этим прибор и был бы бесполезен: молчание носителя, посчитанное
        покоем, изготавливает чистый ответ из отсутствия наблюдения.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0, "maple": 50.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [])
        self.pin_denominator([D0])

        doc = self.measure()
        cov = doc["coverage"]
        self.assertEqual(cov["pairs_total"], 2)
        self.assertEqual(cov["pairs_adjudicable"], 0)
        self.assertEqual(cov["pairs_moved"], 0)
        self.assertEqual(cov["by_verdict"], {mod.WHY_DAY_ABSENT: 2})
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in doc["findings"]))

    def test_two_observations_is_already_adjudicable_and_one_is_not(self):
        """ГРАНИЦА, а не окрестность: 2 наблюдения — да, 1 — ещё нет.

        Предпосылка обеих сцен названа ЧИСЛОМ: у дня РОВНО два снимка, у ноги
        `aave_v3` РОВНО два значения, у ноги `maple` — РОВНО одно.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0, "maple": 50.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.0),
            _carrier_row(SNAP_B, "aave_v3", 3.5),
            _carrier_row(SNAP_A, "maple", 4.0),
        ])
        self.pin_denominator([D0])

        cov = self.measure()["coverage"]
        self.assertEqual(cov["pairs_total"], 2)
        self.assertEqual(cov["pairs_adjudicable"], 1)
        self.assertEqual(cov["by_verdict"],
                         {mod.ADJUDICABLE: 1, mod.WHY_LEG_ONCE: 1})

    def test_equal_values_twice_is_measured_stillness_not_absence(self):
        """Два РАВНЫХ наблюдения — рассуженная пара с ответом «не двигалась».

        Обратная сторона предыдущего теста: если бы прибор различал только
        «есть значение / нет значения», измеренный покой стал бы неотличим от
        неизмеренного, и слой 1 потерял бы весь смысл.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.25),
            _carrier_row(SNAP_B, "aave_v3", 3.25),
        ])
        self.pin_denominator([D0])

        cov = self.measure()["coverage"]
        self.assertEqual(cov["pairs_adjudicable"], 1)
        self.assertEqual(cov["pairs_moved"], 0)
        self.assertEqual(cov["by_verdict"], {mod.ADJUDICABLE: 1})

    def test_an_unchecked_carrier_row_is_not_an_observation(self):
        """Строка ``unchecked`` говорит «наблюдения НЕ БЫЛО» — она не покрытие.

        Считать её вторым наблюдением значило бы изготовить рассуженную пару
        из отказа фида — та же подстановка, только на входе прибора.

        **Строка фикстуры НЕСЁТ ЧИСЛО намеренно, и это не описка.** Замер
        живого носителя 10.09: из 21 строки ``unchecked`` ставку не несёт НИ
        ОДНА, поэтому фикстура, скопированная с живой, доказывала бы не тот
        отбор — её отвергал бы фильтр по ЗНАЧЕНИЮ, а не по РОДУ строки, и
        мутация «снять проверку рода» пережила бы тест (замер батареи #555:
        именно так она его и пережила). Утверждение здесь сильнее: решает
        ``kind``, а не наличие числа.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.0),
            _carrier_row(SNAP_B, "aave_v3", 9.9, kind="unchecked"),
        ])
        self.pin_denominator([D0])

        cov = self.measure()["coverage"]
        self.assertEqual(cov["pairs_adjudicable"], 0)
        self.assertEqual(cov["by_verdict"], {mod.WHY_ONE_SNAPSHOT: 1})

    def test_a_leg_the_carrier_never_polls_is_its_own_named_class(self):
        """Нога вне носителя — свой класс: чинится СОСТАВОМ опрашиваемых.

        Растворив её в «дня нет» или в «единственный снимок», прибор потерял бы
        единственное, что по этой паре можно починить.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0, "pendle": 50.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.0),
            _carrier_row(SNAP_B, "aave_v3", 3.5),
        ])
        self.pin_denominator([D0])

        cov = self.measure()["coverage"]
        self.assertEqual(cov["by_verdict"],
                         {mod.ADJUDICABLE: 1, mod.WHY_LEG_ABSENT: 1})


class PopulationBoundary(_Scene):
    """Слой 2 — доля с чужого населения на знаменатель НЕ переносится."""

    def test_movement_outside_the_denominator_never_raises_the_denominator(self):
        """Носитель видит движение — но НЕ на дне знаменателя.

        Это тот самый перенос доли, против которого написан заказ: населения
        два, и цифра одного не имеет права стать ответом о другом.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME, [
            _journal_row(D0, {"aave_v3": 100.0}),
            _journal_row(D1, {"aave_v3": 100.0}),
        ])
        # Движение есть — но на D1, которого в знаменателе нет.
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_C, "aave_v3", 3.0),
            _carrier_row(SNAP_D, "aave_v3", 9.0),
        ])
        self.pin_denominator([D0])

        doc = self.measure()
        self.assertEqual(doc["coverage"]["pairs_adjudicable"], 0)
        self.assertEqual(doc["coverage"]["pairs_moved"], 0)
        mv = doc["movement_outside_denominator"]
        self.assertEqual(mv["days_measured"], 1)
        self.assertEqual(mv["days_also_in_denominator"], 0)
        self.assertEqual(mv["adapter_days_moved"], 1)
        self.assertEqual(mv["widest_spread_pp"], 6.0)
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)


class KindControl(_Scene):
    """Слой 3 — род величин, и он обязан УМЕТЬ провалиться."""

    def test_zero_comparable_pairs_is_a_third_outcome_not_a_pass(self):
        """Ноль сравнений НЕ есть «род совпал» — контроль, истинный по построению.

        Урок цикла #553 дословно: контроль, который не мог провалиться, —
        украшение. Здесь у журнала нет ставок вовсе, сравнивать не с чем.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0}, rates={})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.0),
            _carrier_row(SNAP_B, "aave_v3", 3.5),
        ])
        self.pin_denominator([D0])

        kind = self.measure()["kind_control"]
        self.assertFalse(kind["measured"])
        self.assertIsNone(kind["same_subject"])
        self.assertEqual(kind["pairs_compared"], 0)

    def test_the_control_really_fails_when_the_subjects_diverge(self):
        """Расхождение обязано БЫТЬ поймано, а не сглажено округлением."""
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0},
                                   rates={"aave_v3": 5.2651})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 2.5804),
            _carrier_row(SNAP_B, "aave_v3", 2.5804),
        ])
        self.pin_denominator([D0])

        kind = self.measure()["kind_control"]
        self.assertTrue(kind["measured"])
        self.assertFalse(kind["same_subject"])
        self.assertEqual(kind["diverged"], 1)

    def test_the_control_passes_when_the_last_snapshot_matches_the_journal(self):
        """Обратная сторона: совпадение обязано читаться как совпадение.

        Сверяется ПОСЛЕДНИЙ снимок дня — не первый: именно он ближе всего к
        строке, которую писатель оставил за день.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0},
                                   rates={"aave_v3": 3.5})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.0),
            _carrier_row(SNAP_B, "aave_v3", 3.5),
        ])
        self.pin_denominator([D0])

        kind = self.measure()["kind_control"]
        self.assertTrue(kind["same_subject"])
        self.assertEqual(kind["matched"], 1)


class SubstitutionTrap(_Scene):
    """Слой 4 — ловушка заказа меряется, а не вспоминается."""

    def _minimal_scene(self):
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [])
        self.pin_denominator([D0])

    def test_one_point_per_adapter_day_forbids_substitution(self):
        self._minimal_scene()
        (self.data / mod.SERIES_FILENAME).write_text(
            json.dumps(_series({"aave_v3": [[D0, 3.0], [D1, 3.4]]})),
            encoding="utf-8")

        trap = self.measure()["substitution_trap"]
        self.assertTrue(trap["measured"])
        self.assertEqual(trap["max_points_per_adapter_day"], 1)
        self.assertFalse(trap["substitution_admissible"])

    def test_the_verdict_comes_from_disk_not_from_the_adr(self):
        """Дай ряду ДВА значения на один день — вердикт обязан перевернуться.

        Без этого теста «подстановка запрещена» была бы цитатой из ADR-316, а
        не замером: прибор, помнящий старый ответ, перестаёт быть прибором.
        """
        self._minimal_scene()
        (self.data / mod.SERIES_FILENAME).write_text(
            json.dumps(_series({"aave_v3": [[D0, 3.0], [D0, 3.9]]})),
            encoding="utf-8")

        trap = self.measure()["substitution_trap"]
        self.assertEqual(trap["max_points_per_adapter_day"], 2)
        self.assertTrue(trap["substitution_admissible"])

    def test_an_unreadable_series_is_unmeasured_not_permission(self):
        self._minimal_scene()
        (self.data / mod.SERIES_FILENAME).write_text("{ не json",
                                                     encoding="utf-8")

        trap = self.measure()["substitution_trap"]
        self.assertFalse(trap["measured"])
        self.assertIsNone(trap["substitution_admissible"])


class Refusals(_Scene):
    """Третий исход не растворяется ни в OK, ни в нуле."""

    def test_an_unreadable_carrier_is_unmeasured_not_ok(self):
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0})])
        (self.data / mod.CARRIER_FILENAME).write_text("{ не json\n",
                                                      encoding="utf-8")
        self.pin_denominator([D0])

        doc = self.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertFalse(doc["carrier"]["measured"])

    def test_an_unmeasured_denominator_is_not_an_empty_denominator(self):
        """Канонический производитель не ответил ⇒ UNMEASURED, а не «пуст».

        Пустое множество здесь читалось бы как полное покрытие нуля — самый
        тихий из способов соврать.
        """
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.0),
            _carrier_row(SNAP_B, "aave_v3", 3.5),
        ])
        self.pin_denominator(None)

        doc = self.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertFalse(doc["coverage"]["measured"])
        self.assertEqual(doc["population"]["scoreable"], 0)

    def test_an_empty_denominator_is_not_a_clean_pass(self):
        """Ни одного дня знаменателя ⇒ мерить нечего, и это НЕ ``OK``."""
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [])
        self.pin_denominator([])

        doc = self.measure()
        self.assertEqual(doc["coverage"]["pairs_total"], 0)
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)

    def test_a_missing_journal_refuses_loudly(self):
        self.pin_denominator([D0])
        doc = self.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc["journal_rows"], 0)


class Wiring(_Scene):
    """Проводка проверяется ВЫЗОВОМ, а не упоминанием имени.

    Урок #465 дословно: тест проводки по подстроке переживает любое
    расплетение. Поэтому здесь — три слоя, и каждый вызывается.
    """

    def _full_scene(self):
        _write_jsonl(self.data / mod.HISTORY_FILENAME,
                     [_journal_row(D0, {"aave_v3": 100.0},
                                   rates={"aave_v3": 3.5})])
        _write_jsonl(self.data / mod.CARRIER_FILENAME, [
            _carrier_row(SNAP_A, "aave_v3", 3.0),
            _carrier_row(SNAP_B, "aave_v3", 3.5),
        ])
        (self.data / mod.SERIES_FILENAME).write_text(
            json.dumps(_series({"aave_v3": [[D0, 3.0]]})), encoding="utf-8")
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
        self.assertTrue(any("заказ #554" in ln for ln in lines))

    def test_the_bridge_declares_the_artifact_as_its_product(self):
        """Артефакт объявлен продуктом ступени переписей — обеими записями."""
        from spa_core.monitoring import findings_bridge as fb

        self.assertIn(f"data/{mod.OUTPUT_FILENAME}", fb.PRODUCES)
        self.assertIn("intraday_rate_input_movement", fb.CENSUS_STAGE)
        self.assertEqual(
            fb.CENSUS_PRODUCT["intraday_rate_input_movement"]["artifact"],
            f"data/{mod.OUTPUT_FILENAME}")

    def test_the_bridge_really_calls_the_instrument_in_main(self):
        """Мост ЗОВЁТ прибор — проверено разбором дерева, а не подстрокой.

        Мутация «вызов `run()` заменён константой» пережила 231 файл-сторож
        (замер #554), потому что объявление в `PRODUCES` от неё не страдает:
        артефакт просто перестал бы производиться, и молчание прибора стало бы
        неотличимо от «находок нет». Грепом по имени это не ловится — тест
        проводки по подстроке переживает любое расплетение (урок #465).

        Общее лечение класса — карточка
        `inbox-provodka-priborov-perepisi-ne-proveryaet`; здесь закрыта своя
        координата, чтобы новый прибор не пополнил население дефекта.
        """
        import ast

        src = Path(fb_path()).read_text(encoding="utf-8")
        tree = ast.parse(src)
        main = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
        self.assertIsNotNone(main, "в мосте находок нет функции `main`")

        called = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "intraday_rate_input_movement"
            for node in ast.walk(main))
        self.assertTrue(called,
                        "`main()` моста находок не вызывает "
                        "intraday_rate_input_movement.run — артефакт объявлен "
                        "продуктом, но не производится")

    def test_the_canonical_denominator_producer_is_actually_asked(self):
        """Знаменатель берётся у ``shadow_trigger_eval``, а не выписан в код.

        Проверяется ВЫЗОВОМ подменённого производителя: список, скопированный
        в модуль, пережил бы любую правку критерия взвода и молчал бы об этом.
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
        real_mod = sys.modules.get("spa_core.paper_trading.shadow_trigger_eval")
        real_attr = getattr(
            __import__("spa_core.paper_trading", fromlist=["x"]),
            "shadow_trigger_eval", None)
        sys.modules["spa_core.paper_trading.shadow_trigger_eval"] = fake
        setattr(__import__("spa_core.paper_trading", fromlist=["x"]),
                "shadow_trigger_eval", fake)
        try:
            days = self._real_scored(self.data)
        finally:
            if real_mod is not None:
                sys.modules["spa_core.paper_trading.shadow_trigger_eval"] = real_mod
            else:  # pragma: no cover — модуль не был импортирован до теста
                sys.modules.pop("spa_core.paper_trading.shadow_trigger_eval", None)
            if real_attr is not None:
                setattr(__import__("spa_core.paper_trading", fromlist=["x"]),
                        "shadow_trigger_eval", real_attr)

        self.assertEqual(seen["write"], False,
                         "производитель знаменателя вызван НА ЗАПИСЬ — "
                         "замер обязан быть read-only")
        self.assertEqual(days, {D0},
                         "тривиальный день не имеет права попасть в знаменатель")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
