"""Приёмка заказа **G91 п. 1** — род поля-кандидата в личность МАШИННЫМ признаком.

Батарея отвечает на три разных вопроса, и смешивать их нельзя:

1. **Признак измеряет то, что заявлено.** У каждого правила спуска есть контроль
   в обе стороны, и каждый обратный контроль воспроизводит ЛОЖНУЮ НАХОДКУ первой
   редакции меры на живом коде (обёртка-«содержит», область видимости, аргумент
   вместо получателя, контейнер вместо привязки).
2. **Третий исход назван.** «Не разобрано» и «производителя не нашли» —
   самостоятельные ответы, ни один не выдаётся за «чисто» (инв. #17).
3. **Правило «род ⇒ годность» отвергнуто ЗАМЕРОМ.** Оба контрпримера
   перемеряются здесь живым прогоном по настоящему коду. Исчезни они — тест
   краснеет, и отказ пересматривается решением, а не ветшает молча.

LLM здесь запрещён. Литеральных дат в файле нет: мера читает исходники и часов
не спрашивает вовсе, поэтому классу замороженных дат эта батарея не принадлежит.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from spa_core.monitoring import identity_field_kind as kind
from spa_core.monitoring.run_identity_key_price import (
    CLOCK_FIELDS, _IDENTITY_FIELDS, _MEASURED_IDENTITY_FIELDS,
)

_TREE = Path(__file__).resolve().parents[2]


def kinds(source: str, field: str):
    """Все вердикты для одного поля в одном исходнике."""
    rows, why = kind.module_kinds(source, {field})
    assert not why, why
    return [(r.verdict, r.how) for r in rows.get(field, [])]


def verdicts(source: str, field: str):
    return {v for v, _ in kinds(source, field)}


class SignMeasuresWhatItClaims(unittest.TestCase):
    """Правила спуска — каждое с обратным контролем."""

    def test_a_direct_wall_clock_door_is_derivation(self):
        src = ('import datetime\n'
               'def build():\n'
               '    return {"f": datetime.datetime.now().isoformat()}\n')
        self.assertEqual(verdicts(src, "f"), {kind.WALL_CLOCK})

    def test_a_wrapper_that_RETURNS_the_clock_is_a_door(self):
        src = ('import datetime\n'
               'def _utcnow():\n'
               '    return datetime.datetime.now(datetime.timezone.utc)\n'
               'def build():\n'
               '    return {"f": _utcnow()}\n')
        self.assertEqual(verdicts(src, "f"), {kind.WALL_CLOCK})

    def test_a_wrapper_that_merely_TOUCHES_the_clock_is_NOT_a_door(self):
        """Обратный контроль, воспроизводящий ложную находку на `sky_monitor`.

        ``check_sky_status_live()`` трогает часы внутри, а отдаёт словарь
        состояния. Первая редакция объявляла стенным её результат — и вместе с
        ним поле ``source``, к часам не относящееся вовсе.
        """
        src = ('import datetime\n'
               'def probe():\n'
               '    started = datetime.datetime.now()\n'
               '    return {"source": "live", "ok": True}\n'
               'def build():\n'
               '    status = probe()\n'
               '    return {"source": status.get("source")}\n')
        self.assertEqual(verdicts(src, "source"), {kind.NOT_DERIVED})

    def test_a_container_holding_a_stamp_is_not_itself_a_stamp(self):
        """«Контейнер не есть привязка» — то же правило, что у injected-clock."""
        src = ('import datetime\n'
               'def build():\n'
               '    doc = {"generated_at": datetime.datetime.now().isoformat()}\n'
               '    return {"f": doc}\n')
        self.assertEqual(verdicts(src, "f"), {kind.NOT_DERIVED})

    def test_a_call_GIVEN_the_clock_as_an_argument_is_not_derivation(self):
        """Обратный контроль, воспроизводящий ложную находку на `offsite_backup`.

        ``read_observation(data_dir, now=now)`` — потребитель часов, не их
        производитель. Считать иначе значило бы объявить стенным всякий
        результат, к которому часы когда-либо прикасались.
        """
        src = ('import datetime\n'
               'def build(read_observation, data_dir):\n'
               '    now = datetime.datetime.now()\n'
               '    obs = read_observation(data_dir, now=now)\n'
               '    return {"day": obs.day}\n')
        self.assertEqual(verdicts(src, "day"), {kind.NOT_DERIVED})

    def test_a_binding_in_ANOTHER_scope_does_not_poison_a_loop_variable(self):
        """Обратный контроль, воспроизводящий ложную находку на `nav_proof`.

        Там ``p = build_proof(...)`` в одной функции объявляло стенным
        ``{"protocol": p}`` в ДРУГОЙ, где ``p`` — переменная обхода.
        """
        src = ('import datetime\n'
               'def _stamp():\n'
               '    return datetime.datetime.now()\n'
               'def outer():\n'
               '    p = _stamp()\n'
               '    return p\n'
               'def hashed(positions):\n'
               '    return {"items": [{"protocol": p} for p in sorted(positions)]}\n')
        self.assertEqual(verdicts(src, "protocol"), {kind.NOT_DERIVED})

    def test_rebinding_the_SAME_name_in_ONE_scope_is_a_NAMED_limit(self):
        """Граница, названная вслух: порядок двух привязок одного имени внутри
        области мера не знает — она не следит за потоком управления.

        Выбранная сторона — НАХОДКА, и выбор обоснован, а не удобен: ось не есть
        гейт (``FITNESS_RULE`` отвергнут), поэтому ложная находка стоит строки в
        отчёте, а ложное «чисто» спрятало бы настоящие часы. Цена ЗАМЕРЕНА: из
        52 находок по ``_IDENTITY_FIELDS`` ни одна на этой неоднозначности не
        стои́т — ни у одной привязки нет конкурирующего нечасового связывания того
        же имени в той же области.

        МЕЖДУ областями неоднозначности нет, и это закреплено отдельным тестом
        (``test_a_binding_in_ANOTHER_scope_does_not_poison_a_loop_variable``).
        """
        src = ('import datetime\n'
               'def build(rows):\n'
               '    day = datetime.date.today().isoformat()\n'
               '    out = []\n'
               '    for day in rows:\n'
               '        out.append({"day": day})\n'
               '    return out\n')
        self.assertEqual(verdicts(src, "day"), {kind.WALL_CLOCK})

    def test_a_for_target_ALONE_is_not_a_clock(self):
        """Обратная сторона той же границы: без присваивания часов в области
        переменная обхода чистая — то есть затенение работает, а не отключено."""
        src = ('def build(rows):\n'
               '    out = []\n'
               '    for day in rows:\n'
               '        out.append({"day": day})\n'
               '    return out\n')
        self.assertEqual(verdicts(src, "day"), {kind.NOT_DERIVED})

    def test_a_PARAMETER_shadows_a_module_level_clock_binding(self):
        """Затенение — отдельное правило от разделения областей, и оба нужны.

        Мутант «затенение отключено» переживал батарею, пока контроль стоял
        только на РАЗНЫХ функциях: там имя не доходит до внутренней области по
        построению. Отравляет именно МОДУЛЬНАЯ привязка, и её обязан снимать
        параметр.
        """
        src = ('import datetime\n'
               'NOW = datetime.datetime.now()\n'
               'def build(NOW):\n'
               '    return {"day": NOW}\n')
        self.assertEqual(verdicts(src, "day"), {kind.NOT_DERIVED})

    def test_a_COMPREHENSION_target_shadows_a_module_level_clock_binding(self):
        """Та же форма, что у настоящей ложной находки на `nav_proof`: имя
        обхода против одноимённой внешней привязки."""
        src = ('import datetime\n'
               'p = datetime.datetime.now()\n'
               'def hashed(positions):\n'
               '    return {"items": [{"protocol": p} for p in sorted(positions)]}\n')
        self.assertEqual(verdicts(src, "protocol"), {kind.NOT_DERIVED})

    def test_a_call_whose_ARGUMENT_is_the_clock_stays_clean_through_a_plain_name(self):
        """Обратная сторона «аргумент не есть происхождение» на ВЫЗОВЕ-ИМЕНИ.

        Прежний контроль проверял только путь через атрибут, и мутант,
        открывавший аргументы, оказывался эквивалентным.
        """
        src = ('import datetime\n'
               'def build(read):\n'
               '    now = datetime.datetime.now()\n'
               '    return {"day": read(now)}\n')
        self.assertEqual(verdicts(src, "day"), {kind.NOT_DERIVED})

    def test_a_parameter_named_now_is_not_a_clock_by_its_name(self):
        src = ('def build(now):\n'
               '    return {"f": now}\n')
        self.assertEqual(verdicts(src, "f"), {kind.NOT_DERIVED})

    def test_an_fstring_assembled_from_the_clock_IS_derivation(self):
        src = ('import datetime\n'
               'def build(then):\n'
               '    age = (datetime.datetime.now() - then).total_seconds()\n'
               '    return {"message": f"stale for {age:.1f}s"}\n')
        self.assertEqual(verdicts(src, "message"), {kind.WALL_CLOCK})

    def test_a_method_on_the_clock_and_a_formatter_of_it_are_derivation(self):
        src = ('import datetime\n'
               'def build():\n'
               '    now = datetime.datetime.now()\n'
               '    return {"a": now.strftime("%Y-%m-%d"), "b": str(now)}\n')
        self.assertEqual(verdicts(src, "a"), {kind.WALL_CLOCK})
        self.assertEqual(verdicts(src, "b"), {kind.WALL_CLOCK})

    def test_fromisoformat_converts_an_INPUT_and_is_not_a_door(self):
        src = ('import datetime\n'
               'def build(text):\n'
               '    return {"f": datetime.datetime.fromisoformat(text).isoformat()}\n')
        self.assertEqual(verdicts(src, "f"), {kind.NOT_DERIVED})

    def test_subscript_assignment_and_setdefault_are_producer_forms_too(self):
        src = ('import datetime\n'
               'def build():\n'
               '    doc = {}\n'
               '    doc["a"] = datetime.datetime.now().isoformat()\n'
               '    doc.setdefault("b", datetime.datetime.now().isoformat())\n'
               '    return doc\n')
        self.assertEqual(verdicts(src, "a"), {kind.WALL_CLOCK})
        self.assertEqual(verdicts(src, "b"), {kind.WALL_CLOCK})

    def test_a_computed_key_is_not_a_field_name(self):
        src = ('import datetime\n'
               'def build(k):\n'
               '    return {k: datetime.datetime.now().isoformat()}\n')
        rows, why = kind.module_kinds(src, None)
        self.assertEqual(why, "")
        self.assertEqual(rows, {})


class TheWeakAxisIsKeptSeparate(unittest.TestCase):
    """Ось, названную заказом дословно, нельзя складывать с сильной."""

    def test_reading_a_CLOCK_FIELDS_name_is_the_weak_axis_not_the_strong_one(self):
        src = ('def build(rec):\n'
               '    return {"f": rec["timestamp"], "g": rec.get("generated_at")}\n')
        self.assertEqual(verdicts(src, "f"), {kind.CLOCK_NAMED_READ})
        self.assertEqual(verdicts(src, "g"), {kind.CLOCK_NAMED_READ})

    def test_a_name_outside_CLOCK_FIELDS_is_not_the_weak_axis(self):
        self.assertNotIn("apy", CLOCK_FIELDS)
        src = ('def build(rec):\n'
               '    return {"f": rec["apy"]}\n')
        self.assertEqual(verdicts(src, "f"), {kind.NOT_DERIVED})

    def test_the_strong_axis_wins_when_BOTH_match_the_SAME_expression(self):
        """Предпочтение осей проверяется там, где обе подходят к ОДНОМУ
        выражению. Прежний контроль разводил их по разным ветвям ``or``, и
        мутант с перевёрнутым порядком был эквивалентным: слабая ось в ``BoolOp``
        не спускается и до сильной дело доходило само.
        """
        src = ('import datetime\n'
               'def _stamped():\n'
               '    return datetime.datetime.now()\n'
               'def build():\n'
               '    return {"f": _stamped().get("generated_at")}\n')
        self.assertIsNotNone(kind.clock_named_read(
            ast.parse('_stamped().get("generated_at")').body[0].value),
            "предпосылка контроля: слабая ось обязана подходить тоже")
        self.assertEqual(verdicts(src, "f"), {kind.WALL_CLOCK})


class ThirdOutcomeIsNamed(unittest.TestCase):
    """«Не измерено» — отдельный ответ, и он никогда не «чисто»."""

    def test_unparseable_source_is_unmeasured_with_a_named_reason(self):
        rows, why = kind.module_kinds("def broken(:\n", None)
        self.assertEqual(rows, {})
        self.assertTrue(why)
        self.assertIn("не разобрано", why)

    def test_a_missing_root_is_recorded_and_names_stay_unmeasured(self):
        with _tmptree() as root:
            doc = kind.census(("code",), root, roots=("nowhere",))
        self.assertEqual(doc["files_parsed"], 0)
        self.assertIn("nowhere", doc["files_unmeasured"])
        self.assertEqual(doc["fields"]["code"]["verdict"], kind.UNMEASURED)
        self.assertTrue(doc["fields"]["code"]["why_unmeasured"])

    def test_a_field_with_no_producer_is_unmeasured_not_clean(self):
        """Разные ответы: «писателя не нашли» ≠ «писателей проверили, часов нет»."""
        with _tmptree() as root:
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "m.py").write_text('def build():\n    return {"code": "x"}\n',
                                      encoding="utf-8")
            doc = kind.census(("code", "absent_field"), root, roots=("pkg",))
        self.assertEqual(doc["files_parsed"], 1)
        self.assertEqual(doc["fields"]["code"]["verdict"], kind.NOT_DERIVED)
        self.assertEqual(doc["fields"]["absent_field"]["verdict"], kind.UNMEASURED)
        self.assertNotEqual(doc["fields"]["code"]["verdict"],
                            doc["fields"]["absent_field"]["verdict"])

    def test_a_clean_field_is_counted_not_dropped(self):
        """Первая редакция ОТБРАСЫВАЛА чистые строки, и перепись читала их
        отсутствие как «производителя не нашли»: одиннадцать имён
        `_IDENTITY_FIELDS` получали `unmeasured` при живом чистом замере."""
        with _tmptree() as root:
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "m.py").write_text('def build():\n    return {"code": "x"}\n',
                                      encoding="utf-8")
            doc = kind.census(("code",), root, roots=("pkg",))
        self.assertEqual(doc["fields"]["code"]["not_derived_count"], 1)

    def test_exit_code_is_two_on_unmeasured_and_zero_otherwise(self):
        with _tmptree() as root:
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "m.py").write_text('def build():\n    return {"code": "x"}\n',
                                      encoding="utf-8")
            clean = kind.census(("code",), root, roots=("pkg",))
            missing = kind.census(("absent_field",), root, roots=("pkg",))
        self.assertEqual(_exit_for(clean), 0)
        self.assertEqual(_exit_for(missing), 2)


def _exit_for(doc: dict) -> int:
    """Та же формула, что у ``main`` — вердикт читается из документа."""
    unmeasured = sum(1 for r in doc["fields"].values()
                     if r["verdict"] == kind.UNMEASURED)
    return 2 if (unmeasured or not doc["files_parsed"]) else 0


class TheFitnessRuleIsRefusedByMeasurement(unittest.TestCase):
    """Отказ стои́т на ЖИВОМ замере, а не на прозе ADR."""

    def test_the_rule_is_refused_in_the_document_itself(self):
        self.assertEqual(kind.FITNESS_RULE["verdict"], "REFUSED")
        self.assertTrue(kind.FITNESS_RULE["why"])
        doc = kind.census(("code",), _TREE, roots=("spa_core/utils",))
        self.assertEqual(doc["fitness_rule"]["verdict"], "REFUSED")

    def test_every_counterexample_is_REPRODUCED_on_real_code(self):
        for case in kind.FITNESS_RULE["counterexamples"]:
            with self.subTest(field=case["field"]):
                path = _TREE / case["producer"]
                self.assertTrue(path.is_file(), f"нет файла {case['producer']}")
                got = verdicts(path.read_text(encoding="utf-8"), case["field"])
                self.assertIn(case["expect_verdict"], got,
                              f"{case['field']} у {case['producer']}: {got}")

    def test_the_sign_MISSES_the_very_name_the_ADR_rejected_by_this_reasoning(self):
        """ADR-503 отверг ``record_generated_at`` рассуждением «копирует часы».

        Стенными часами производителя оно не производится вовсе: там чтение
        отметки ВХОДНОЙ записи. Признак не ловит тот самый случай.
        """
        src = (_TREE / "spa_core/monitoring/decision_record_run_identity.py"
               ).read_text(encoding="utf-8")
        got = verdicts(src, "record_generated_at")
        self.assertIn(kind.CLOCK_NAMED_READ, got)
        self.assertNotIn(kind.WALL_CLOCK, got)

    def test_the_sign_CATCHES_a_name_admitted_by_measurement(self):
        """``day`` принят в `_MEASURED_IDENTITY_FIELDS` замером ADR-503 — и
        при этом производится стенными часами. Гейт по признаку выбросил бы его."""
        self.assertIn("day", _MEASURED_IDENTITY_FIELDS)
        src = (_TREE / "spa_core/strategy_lab/swarm/dwell_hysteresis_forward.py"
               ).read_text(encoding="utf-8")
        self.assertIn(kind.WALL_CLOCK, verdicts(src, "day"))

    def test_the_weak_axis_has_a_measured_false_finding_on_real_code(self):
        """``export_data`` кладёт в ``date`` значение ``rec["timestamp"]``, где
        ``rec`` — точка синтетической ИСТОРИИ: календарная дата наблюдения, а не
        момент производства. Слабая ось признаком годности быть не может."""
        src = (_TREE / "spa_core/export_data.py").read_text(encoding="utf-8")
        rows = kinds(src, "date")
        self.assertIn(kind.CLOCK_NAMED_READ, {v for v, _ in rows})
        self.assertNotIn(kind.WALL_CLOCK, {v for v, _ in rows})

    def test_the_module_offers_no_fitness_gate(self):
        """У меры нет ни одной двери, превращающей ось в отказ имени.

        Проверяется составом публичного имени, а не обещанием: появись здесь
        функция-гейт — тест краснеет, и решение принимается ADR-ом.
        """
        public = {n for n in dir(kind) if not n.startswith("_")}
        forbidden = {"unfit_for_identity", "reject", "is_unfit", "gate",
                     "filter_identity_fields", "approved"}
        self.assertEqual(public & forbidden, set())

    def test_importing_the_measure_does_not_touch_the_identity_tuple(self):
        """Мера только читает: кортеж личностей от её импорта не меняется."""
        from spa_core.monitoring import run_identity_key_price as g16
        self.assertEqual(g16._IDENTITY_FIELDS, _IDENTITY_FIELDS)
        self.assertEqual(tuple(_IDENTITY_FIELDS)[-len(_MEASURED_IDENTITY_FIELDS):],
                         tuple(_MEASURED_IDENTITY_FIELDS))


class FormerFalseFindingsStayClean(unittest.TestCase):
    """Три ложные находки первой редакции — на живом коде, поимённо."""

    CASES = (
        ("spa_core/backtesting/tier1/nav_proof.py", "protocol"),
        ("spa_core/data_pipeline/sky_monitor.py", "source"),
        ("spa_core/monitoring/offsite_backup_observability.py", "day"),
    )

    def test_each_former_false_finding_is_measured_clean(self):
        for rel, field in self.CASES:
            with self.subTest(module=rel, field=field):
                path = _TREE / rel
                self.assertTrue(path.is_file(), f"нет файла {rel}")
                got = verdicts(path.read_text(encoding="utf-8"), field)
                self.assertNotIn(kind.WALL_CLOCK, got)


class DoorVocabularyIsAsked_NotGuessed(unittest.TestCase):

    def test_clock_wrappers_are_found_to_a_fixed_point(self):
        src = ('import datetime\n'
               'def a():\n'
               '    return datetime.datetime.now()\n'
               'def b():\n'
               '    return a()\n'
               'def c():\n'
               '    return b()\n')
        tree = ast.parse(src)
        self.assertEqual(kind.clock_wrappers(tree), frozenset({"a", "b", "c"}))

    def test_a_function_returning_an_input_is_not_a_wrapper(self):
        src = ('import datetime\n'
               'def a(x):\n'
               '    seen = datetime.datetime.now()\n'
               '    return x\n')
        self.assertEqual(kind.clock_wrappers(ast.parse(src)), frozenset())

    def test_door_call_needs_both_the_root_and_the_method(self):
        self.assertTrue(kind.door_call(ast.parse("datetime.now()").body[0].value))
        self.assertIsNone(kind.door_call(ast.parse("session.now()").body[0].value))
        self.assertIsNone(kind.door_call(ast.parse("datetime.parse()").body[0].value))


class _tmptree:
    """Одноразовое дерево. Живого дерева сцены не касаются по построению."""

    def __enter__(self) -> Path:
        import tempfile
        self._td = tempfile.TemporaryDirectory(prefix="spa_ifk_")
        return Path(self._td.name)

    def __exit__(self, *exc) -> None:
        self._td.cleanup()


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
