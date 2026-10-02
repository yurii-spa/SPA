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
4. **Ось «посчитано» (заказ G91 п. 3) и её правило — отдельный вопрос.** Слово
   заказа «ЗАМЕР» измеримо машиной; правило «посчитано ⇒ личностью быть не
   вправе» отвергнуто, и вердикт ВЫЧИСЛЯЕТСЯ из двух условий, а не объявлен
   строкой. Оба контрпримера — на живом коде и перемеряются каждый прогон.

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


# ── ось «посчитано» (заказ G91 п. 3) ─────────────────────────────────────────

def arith(source: str, field: str):
    """Сильное прочтение оси для одного поля — множество записей находки."""
    rows, why = kind.module_kinds(source, {field})
    assert not why, why
    return {r.arith for r in rows.get(field, []) if r.arith}


def formatted(source: str, field: str):
    """СЛАБОЕ прочтение: текст, собранный из посчитанного числа."""
    rows, why = kind.module_kinds(source, {field})
    assert not why, why
    return {r.arith_text for r in rows.get(field, []) if r.arith_text}


class TheCountedAxisMeasuresWhatItClaims(unittest.TestCase):
    """Каждое правило сильного прочтения — с контролем в обе стороны."""

    def test_a_count_is_a_measure(self):
        self.assertEqual(arith('def f(xs):\n    return {"n": len(xs)}\n', "n"),
                         {"len()"})

    def test_a_sum_and_a_rounding_are_measures(self):
        self.assertEqual(arith('def f(xs):\n    return {"n": sum(xs)}\n', "n"),
                         {"sum()"})
        self.assertEqual(arith('def f(x):\n    return {"n": round(x, 4)}\n', "n"),
                         {"round()"})

    def test_a_CONVERTER_of_a_given_value_is_NOT_a_measure(self):
        """Обратный контроль: ``int("3")`` переводит ДАННОЕ значение и ничего
        не считает. Признак по «числовому виду» утащил бы и его."""
        self.assertEqual(arith('def f(raw):\n    return {"n": int(raw)}\n', "n"),
                         set())

    def test_max_and_min_CHOOSE_and_are_not_measures(self):
        """``max`` отдаёт один из поданных элементов, и выбранным вполне может
        оказаться ИМЯ. Поэтому их нет в словаре арифметических дверей."""
        self.assertEqual(arith('def f(xs):\n    return {"n": max(xs)}\n', "n"),
                         set())

    def test_a_LITERAL_number_standing_alone_is_a_CONSTANT_not_a_measure(self):
        """``{"window_s": 300}`` — постоянная: координата по ней не переезжает.

        Прямой контроль к следующему тесту: находкой литерал делает только
        соседство с оператором, то есть ВЫЧИСЛЕНИЕ.
        """
        self.assertEqual(arith('def f():\n    return {"window_s": 300}\n',
                               "window_s"), set())

    def test_a_literal_number_NEXT_TO_an_operator_IS_a_measure(self):
        self.assertEqual(arith('def f(i):\n    return {"n": i + 1}\n', "n"),
                         {"literal:1"})

    def test_the_OPERAND_names_the_kind_and_not_the_OPERATOR(self):
        """``/`` в этом дереве чаще склейка путей, чем деление.

        Обратный контроль к предыдущему: тот же оператор, операнд не числовой ⇒
        находки нет. Обвинять оператор значило бы объявить замером каждый
        ``root / "data"``.
        """
        self.assertEqual(arith('def f(root):\n    return {"path": root / "data"}\n',
                               "path"), set())
        self.assertEqual(arith('def f(a, b):\n    return {"n": a - b}\n', "n"),
                         set())

    def test_a_BOOL_is_not_a_number_even_though_python_says_it_is(self):
        """``True`` есть ``int`` по наследству. Тип спрашивается точным
        совпадением — иначе флаг уехал бы в арифметику."""
        self.assertEqual(arith('def f(x):\n    return {"n": x * True}\n', "n"),
                         set())

    def test_a_wrapper_that_RETURNS_a_count_is_a_door(self):
        src = ('def _n(xs):\n    return len(xs)\n'
               'def f(xs):\n    return {"n": _n(xs)}\n')
        self.assertEqual(arith(src, "n"), {"_n()"})

    def test_a_function_that_merely_COUNTS_INSIDE_is_NOT_a_door(self):
        """Обратный контроль к обёртке: признак — РЕЗУЛЬТАТ, а не «в теле есть».

        Это ровно цена первой редакции соседней оси (``check_sky_status_live``).
        """
        src = ('def _n(xs):\n    seen = len(xs)\n    return xs\n'
               'def f(xs):\n    return {"n": _n(xs)}\n')
        self.assertEqual(arith(src, "n"), set())

    def test_a_count_bound_to_a_name_reaches_the_field(self):
        src = ('def f(xs):\n    n = len(xs)\n    return {"n": n}\n')
        self.assertEqual(arith(src, "n"), {"name:n"})

    def test_a_PARAMETER_shadows_the_outer_binding(self):
        """Область видимости — часть правильности замера, а не украшение."""
        src = ('DATA = [1, 2]\n'
               'n = len(DATA)\n'
               'def b(n):\n    return {"n": n}\n')
        self.assertEqual(arith(src, "n"), set())

    def test_the_MODULE_binding_reaches_a_function_that_does_NOT_shadow_it(self):
        """Обратный контроль к затенению: без параметра привязка модуля доходит."""
        src = ('DATA = [1, 2]\n'
               'n = len(DATA)\n'
               'def b():\n    return {"n": n}\n')
        self.assertEqual(arith(src, "n"), {"name:n"})

    def test_a_count_INSIDE_A_CONTAINER_does_not_make_the_container_a_measure(self):
        """Контейнер привязкой не является (`.claude/rules/deployment.md`)."""
        src = ('def f(xs):\n    return {"row": {"n": len(xs)}}\n')
        self.assertEqual(arith(src, "row"), set())

    def test_a_count_passed_as_an_ARGUMENT_does_not_make_the_call_a_measure(self):
        """Вызов, которому счёт ушёл аргументом, — его ПОТРЕБИТЕЛЬ."""
        src = ('def f(xs):\n    return {"row": build(total=len(xs))}\n')
        self.assertEqual(arith(src, "row"), set())


class TheCONDITIONisNotTheVALUE(unittest.TestCase):
    """``a if test else b``: значение приходит из ветвей и НИКОГДА из условия.

    Положительный контроль — настоящая ложная находка собственного прогона:
    ``stability_tracker.py:202`` склеивает СТРОКИ, а посчитанным числом там
    оказался счётчик в развилке.
    """

    def test_a_number_in_the_CONDITION_is_not_the_value(self):
        src = ('def f(xs):\n    k = len(xs)\n'
               '    return {"m": "a" if k else "b"}\n')
        self.assertEqual(arith(src, "m"), set())

    def test_a_number_in_a_BRANCH_is_the_value(self):
        src = ('def f(xs, flag):\n    k = len(xs)\n'
               '    return {"m": k if flag else 0}\n')
        self.assertEqual(arith(src, "m"), {"name:k"})

    def test_the_rule_is_ONE_copy_and_the_clock_axis_obeys_it_too(self):
        """Тот же дефект жил на оси часов, и лечится он одной копией правила."""
        src = ('import datetime\n'
               'def f():\n    t = datetime.datetime.now()\n'
               '    return {"m": "a" if t else "b"}\n')
        self.assertNotIn(kind.WALL_CLOCK, verdicts(src, "m"))
        src2 = ('import datetime\n'
                'def f(flag):\n    t = datetime.datetime.now()\n'
                '    return {"m": t if flag else None}\n')
        self.assertIn(kind.WALL_CLOCK, verdicts(src2, "m"))

    def test_the_false_finding_is_measured_CLEAN_on_the_real_file(self):
        src = (_TREE / "spa_core/paper_trading/stability_tracker.py"
               ).read_text(encoding="utf-8")
        self.assertEqual(arith(src, "message"), set())

    def test_value_children_names_the_branches_and_not_the_test(self):
        node = ast.parse("a if t else b").body[0].value
        got = {getattr(n, "id", None) for n in kind.value_children(node)}
        self.assertEqual(got, {"a", "b"})


class TheWEAKreadingIsKeptSeparate(unittest.TestCase):
    """f-строка рода НЕ называет, и это измерено на живом коде поимённо."""

    def test_text_assembled_from_a_count_is_the_WEAK_reading(self):
        src = ('def f(xs):\n    k = len(xs)\n    return {"m": f"{k} rows"}\n')
        self.assertEqual(arith(src, "m"), set())
        self.assertEqual(formatted(src, "m"), {"f-string(name:k)"})

    def test_a_GENERATED_NAME_and_a_FORMATTED_MEASURE_are_indistinguishable(self):
        """Два живых случая одной формы — и потому прочтение слабое.

        ``f"protocol_{i % 12}"`` — имя; ``f"{pct:.1f}%"`` — замер. AST их не
        различает, поэтому держать оба в СИЛЬНОМ прочтении значило бы обвинять
        имя за то, что в нём есть номер.
        """
        name_src = ('def f(i):\n    return {"protocol": f"protocol_{i % 12}"}\n')
        meas_src = ('def f(x, t):\n    pct = 100.0 * x / t\n'
                    '    return {"share": f"{pct:.1f}%"}\n')
        self.assertEqual(arith(name_src, "protocol"), set())
        self.assertEqual(arith(meas_src, "share"), set())
        self.assertTrue(formatted(name_src, "protocol"))
        self.assertTrue(formatted(meas_src, "share"))

    def test_str_of_a_number_is_TEXT_and_belongs_to_the_weak_reading(self):
        """Расхождение, найденное МУТАЦИЕЙ: держать один список форматировщиков
        на обе оси значило бы, что ``str(len(xs))`` сильное, а ``f"{len(xs)}"``
        слабое — одна мысль в двух вердиктах."""
        src = ('def f(xs):\n    return {"m": str(len(xs))}\n')
        self.assertEqual(arith(src, "m"), set())
        self.assertEqual(formatted(src, "m"), {"str(len())"})

    def test_int_of_a_number_STAYS_a_number(self):
        """Обратный контроль: числовой форматировщик числа не отнимает."""
        src = ('def f(xs):\n    return {"m": int(len(xs) / 2)}\n')
        self.assertEqual(arith(src, "m"), {"len()"})

    def test_a_text_with_NO_number_in_it_is_neither_reading(self):
        src = ('def f(who):\n    return {"m": f"hello {who}"}\n')
        self.assertEqual(arith(src, "m"), set())
        self.assertEqual(formatted(src, "m"), set())

    def test_the_f_string_is_asked_its_SUBSTITUTIONS_and_not_its_subtree(self):
        """Обход всем поддеревом утащил бы числа из вложенного контейнера."""
        src = ('def f():\n    return {"m": f"{ {\'n\': len([1])} }"}\n')
        self.assertEqual(arith(src, "m"), set())
        self.assertEqual(formatted(src, "m"), set())

    def test_the_weak_reading_descends_THROUGH_str_around_a_fork(self):
        """Дыра собственного прогона: между ``str()`` и f-строкой стои́т ``or``."""
        src = ('def f(row, moves):\n'
               '    return {"trade_id": str(row.get("trade_id") or f"#{len(moves) + 1}")}\n')
        self.assertEqual(formatted(src, "trade_id"), {'str(f-string(len()))'})

    def test_the_two_readings_never_double_count_one_site(self):
        """Сильное молчит ⇒ спрашивается слабое. Оба сразу — невозможно.

        Сцена подобрана ЗАМЕРОМ, а не на глаз: мутация «считать всегда оба»
        пережила две предыдущие редакции этого теста, потому что в них не было
        места, годного обоим прочтениям СРАЗУ, и мутант оказывался
        равносильным. Здесь годно: у ``len(xs) or f"{k}"`` сильное прочтение
        находит счёт в первом операнде, слабое — f-строку во втором.
        """
        src = ('def f(xs):\n    k = len(xs)\n'
               '    return {"a": len(xs) or f"{k}", "b": f"{k}"}\n')
        rows, _ = kind.module_kinds(src, {"a", "b"})
        self.assertTrue(rows["a"][0].arith, "сцена обязана быть годной сильному")
        value = ast.parse('len(xs) or f"{k}"').body[0].value
        scope = kind._Scope(frozenset({"k"}), frozenset())
        self.assertTrue(kind.arith_formatted(value, scope),
                        "сцена обязана быть годной и слабому — "
                        "иначе мутант равносилен")
        for name, evs in rows.items():
            for ev in evs:
                with self.subTest(field=name):
                    self.assertFalse(ev.arith and ev.arith_text)

    def test_the_weak_reading_has_its_own_verdict_in_the_census(self):
        with _tmptree() as root:
            (root / "spa_core").mkdir()
            (root / "spa_core" / "m.py").write_text(
                'def f(xs):\n    k = len(xs)\n    return {"m": f"{k} rows"}\n',
                encoding="utf-8")
            doc = kind.census(("m",), root, roots=("spa_core",))
        row = doc["fields"]["m"]
        self.assertEqual(row["arithmetic_verdict"], kind.ARITH_FORMATTED)
        self.assertEqual(row["arithmetic_count"], 0)
        self.assertEqual(row["arithmetic_formatted_count"], 1)


class TheCensusCarriesTheAxisAllTheWayToTheSwod(unittest.TestCase):
    """Проводка оси доказывается ИСХОДОМ: находка обязана дойти до свода.

    Положительный контроль — настоящий дефект первой редакции: свод пересобирал
    ``Evidence`` перечислением полей, новое поле оси в конструктор не попало, и
    КАЖДАЯ находка приезжала как ``not_arithmetic``, то есть «измерено и ноль».
    Молчаливый ноль вместо находки — ровно инв. #17.
    """

    def test_a_finding_reaches_the_census_verdict(self):
        with _tmptree() as root:
            (root / "spa_core").mkdir()
            (root / "spa_core" / "m.py").write_text(
                'def f(xs):\n    return {"n": len(xs)}\n', encoding="utf-8")
            doc = kind.census(("n",), root, roots=("spa_core",))
        row = doc["fields"]["n"]
        self.assertEqual(row["arithmetic_verdict"], kind.ARITH_DERIVED)
        self.assertEqual(row["arithmetic_count"], 1)
        self.assertTrue(row["arithmetic_sites"])
        self.assertIn("spa_core/m.py", row["arithmetic_sites"][0])

    def test_the_sites_carry_the_FILE_and_not_an_empty_address(self):
        """Адрес дописывается к готовой улике, а не перечисляется заново."""
        with _tmptree() as root:
            (root / "spa_core").mkdir()
            (root / "spa_core" / "m.py").write_text(
                'def f(xs):\n    return {"n": sum(xs)}\n', encoding="utf-8")
            doc = kind.census(("n",), root, roots=("spa_core",))
        self.assertRegex(doc["fields"]["n"]["arithmetic_sites"][0],
                         r"^spa_core/m\.py:\d+ sum\(\)$")

    def test_the_clean_name_is_NOT_ARITH_and_not_unmeasured(self):
        with _tmptree() as root:
            (root / "spa_core").mkdir()
            (root / "spa_core" / "m.py").write_text(
                'def f(x):\n    return {"n": x}\n', encoding="utf-8")
            doc = kind.census(("n",), root, roots=("spa_core",))
        self.assertEqual(doc["fields"]["n"]["arithmetic_verdict"], kind.NOT_ARITH)

    def test_no_producer_is_UNMEASURED_on_the_axis_too(self):
        """«Писателя не нашли» и «арифметики нет» — разные ответы (инв. #17)."""
        with _tmptree() as root:
            (root / "spa_core").mkdir()
            (root / "spa_core" / "m.py").write_text(
                'def f(x):\n    return x\n', encoding="utf-8")
            doc = kind.census(("absent_name",), root, roots=("spa_core",))
        row = doc["fields"]["absent_name"]
        self.assertEqual(row["arithmetic_verdict"], kind.UNMEASURED)
        self.assertTrue(row["why_arithmetic_unmeasured"])

    def test_the_two_axes_keep_SEPARATE_scope_tables(self):
        """Общая таблица объявила бы стенным всё посчитанное и наоборот."""
        src = ('import datetime\n'
               'def f(xs):\n'
               '    t = datetime.datetime.now()\n'
               '    k = len(xs)\n'
               '    return {"a": t, "b": k}\n')
        rows, _ = kind.module_kinds(src, {"a", "b"})
        a, = rows["a"]
        b, = rows["b"]
        self.assertEqual((a.verdict, a.arith), (kind.WALL_CLOCK, ""))
        self.assertEqual((b.verdict, b.arith), (kind.NOT_DERIVED, "name:k"))

    def test_both_axes_can_be_true_of_ONE_site_at_once(self):
        """Возраст в часах: и часы, и арифметика. Склейка сделала бы вторую
        находку невидимой ровно там, где она дороже всего."""
        src = ('import datetime\n'
               'def f(then):\n'
               '    now = datetime.datetime.now()\n'
               '    return {"age_h": (now - then).total_seconds() / 3600}\n')
        ev, = kind.module_kinds(src, {"age_h"})[0]["age_h"]
        self.assertEqual(ev.verdict, kind.WALL_CLOCK)
        self.assertTrue(ev.arith)


class TheCountedRuleIsRefusedByMeasurement(unittest.TestCase):
    """Вердикт правила ВЫЧИСЛЯЕТСЯ из двух условий, а не объявлен строкой."""

    @classmethod
    def setUpClass(cls):
        names = kind.MEASURE_RULE_SUBJECTS + tuple(_IDENTITY_FIELDS)
        cls.doc = kind.census(names, _TREE)
        cls.rule = kind.measure_rule(cls.doc)

    def test_the_verdict_is_REFUSED_on_the_live_tree(self):
        self.assertEqual(self.rule["verdict"], "REFUSED")
        self.assertTrue(self.rule["why"])

    def test_the_axis_DOES_the_work_it_was_named_for(self):
        """Первое условие выполнено: имя, названное заказом замером, поймано."""
        self.assertTrue(self.rule["axis_does_work"])
        self.assertIn("realised_usd_per_day", self.rule["subjects_caught"])

    def test_the_refusal_rests_on_the_SECOND_condition_being_broken(self):
        """Поймано УЖЕ ПРИНЯТОЕ имя ⇒ импликация ложна в нужную сторону."""
        self.assertFalse(self.rule["axis_spares_admitted"])
        self.assertTrue(set(self.rule["admitted_names_caught"])
                        & set(_IDENTITY_FIELDS))

    def test_every_counterexample_is_REPRODUCED_on_real_code(self):
        for case in kind.MEASURE_RULE_COUNTEREXAMPLES:
            with self.subTest(field=case["field"]):
                path = _TREE / case["producer"]
                self.assertTrue(path.is_file(), f"нет файла {case['producer']}")
                self.assertTrue(
                    arith(path.read_text(encoding="utf-8"), case["field"]),
                    f"{case['field']} у {case['producer']} больше не посчитан — "
                    f"отказ правила обязан быть пересмотрен РЕШЕНИЕМ")
                self.assertIn(case["field"], _IDENTITY_FIELDS)

    def test_the_computed_ORDINAL_counterexample_is_an_admitted_identity(self):
        """``day = best_idx + 1`` — вычисленный НОМЕР, и он именно называет,
        который это элемент ряда. Гейт по оси выбросил бы принятое имя."""
        src = (_TREE / "spa_core/backtesting/replay.py").read_text(encoding="utf-8")
        self.assertTrue(arith(src, "day"))
        self.assertIn("day", _MEASURED_IDENTITY_FIELDS)

    def test_the_SAME_NAME_is_a_count_at_one_producer_and_a_name_at_others(self):
        """Род есть свойство МЕСТА, а ``_IDENTITY_FIELDS`` — множество ИМЁН.

        Правило по имени неисполнимо не из осторожности, а по несовпадению
        granularity, и вот оно поимённо.
        """
        src = (_TREE / "scripts/check_undelivered_work.py").read_text(encoding="utf-8")
        self.assertTrue(arith(src, "code"))
        self.assertIn("code", _IDENTITY_FIELDS)

    def test_the_one_sidedness_is_MEASURED_and_not_merely_declared(self):
        """Ось молчит о числе, пришедшем готовым из чужого модуля.

        ``best_net_usd`` заказ назвал замером, и он им является — но у
        производителя стои́т ``.get("net_usd")``, то есть чтение. Промах назван.
        """
        self.assertIn("best_net_usd", self.rule["subjects_missed_by_the_axis"])
        self.assertTrue(self.rule["one_sidedness"])
        src = (_TREE / "spa_core/monitoring/criterion_sign_price.py"
               ).read_text(encoding="utf-8")
        self.assertEqual(arith(src, "best_net_usd"), set())

    def test_an_unmeasured_name_is_neither_a_vote_FOR_nor_AGAINST(self):
        """Третий исход не голосует (инв. #17)."""
        doc = {"fields": {"realised_usd_per_day":
                          {"arithmetic_verdict": kind.UNMEASURED}}}
        rule = kind.measure_rule(doc)
        self.assertFalse(rule["axis_does_work"])
        self.assertIn("realised_usd_per_day", rule["subjects_unmeasured"])
        self.assertEqual(rule["subjects_caught"], [])

    def test_asking_NOTHING_is_UNMEASURED_and_not_a_verdict(self):
        rule = kind.measure_rule({"fields": {}})
        self.assertEqual(rule["verdict"], kind.UNMEASURED)
        self.assertIsNone(rule["axis_does_work"])

    def test_the_rule_would_be_ACCEPTED_only_if_BOTH_conditions_held(self):
        """Положительный контроль самого вычисления: вердикт не прибит гвоздём.

        Сцена сочинённая — и именно поэтому она доказывает, что ``REFUSED`` выше
        есть ЗАМЕР живого дерева, а не константа.
        """
        fields = {n: {"arithmetic_verdict": kind.NOT_ARITH}
                  for n in _IDENTITY_FIELDS}
        fields["realised_usd_per_day"] = {"arithmetic_verdict": kind.ARITH_DERIVED}
        rule = kind.measure_rule({"fields": fields})
        self.assertEqual(rule["verdict"], "ACCEPTED")

    def test_the_module_still_offers_no_gate_for_the_new_axis_either(self):
        public = {n for n in dir(kind) if not n.startswith("_")}
        forbidden = {"reject_measure", "is_measure_unfit", "drop_measures",
                     "apply_measure_rule", "unfit_by_arithmetic"}
        self.assertEqual(public & forbidden, set())


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
