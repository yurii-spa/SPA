"""Батарея к ``weak_axis_mapping_origin`` — заказ G113 п. 3 (ADR-539).

Предмет: откуда взялось ОТОБРАЖЕНИЕ, у которого слабая ось читает имя из
``CLOCK_FIELDS``. У каждого правила спуска контроль в ОБЕ стороны, у каждого
третьего исхода — названная причина, и у живых утверждений про настоящий код —
перемер на настоящем дереве, а не пересказ.

Почему контроли стоят на НАСТОЯЩИХ файлах там, где речь о настоящем коде: ADR-539
записал два случая прозой человека, и сверять эту прозу было некому. Теперь
батарея перемеряет оба каждый прогон — исчезни случай, тест краснеет, и претензия
пересматривается решением, а не ветшает молча.

Время здесь ВХОД, а не окружение: :func:`measure` принимает ``now``, сцены
отметок между собой не сравнивают, и ни один вердикт от календаря не зависит.
"""
# FROZEN-DATE-OK: injected-clock — якорь `_FIXED_NOW` уезжает аргументом
# `measure(..., now=_FIXED_NOW)` и `run(..., now=_FIXED_NOW)`; стенных часов в
# сценах нет, свежесть здесь ничем не меряется.
from __future__ import annotations

import ast
import importlib
import json
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import identity_field_kind as ifk  # noqa: E402
from spa_core.monitoring import weak_axis_mapping_origin as wamo  # noqa: E402

#: Часы — ВХОД. Литерал объявлен один раз и уезжает аргументом (см. пометку выше).
_FIXED_NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)

INPUT, OWN, UNMEASURED = (wamo.INPUT_MAPPING, wamo.OWN_CLOCK_MAPPING,
                          wamo.UNMEASURED)


#: Замер по ВСЕМУ дереву стои́т ~24 с, а проверок про него больше десяти. Кэш
#: здесь не ускорение ради ускорения: без него батарея идёт четыре минуты, то
#: есть не идёт вовсе, и её перестают запускать. Мера чистая при заданном
#: ``now``, поэтому один прогон и много вопросов к нему — то же измерение.
_TREE: dict = {}


def tree_doc():
    if "doc" not in _TREE:
        _TREE["doc"] = wamo.measure(_ROOT, now=_FIXED_NOW)
    return _TREE["doc"]


def sites(source: str, module: str = "сцена.py"):
    """Площадки сцены. Сцена — ТЕКСТ, чтобы правило мерилось, а не пересказывалось."""
    rows, why = wamo.module_sites(textwrap.dedent(source), module)
    assert not why, f"сцена не разобрана: {why}"
    return rows


def one(source: str, module: str = "сцена.py"):
    """Ровно ОДНА площадка. Сцена, давшая две, проверяет не то, что объявлено."""
    rows = sites(source, module)
    assert len(rows) == 1, f"ожидалась одна площадка, получено {len(rows)}: {rows}"
    return rows[0]


class SiteDetection(unittest.TestCase):
    """Население берётся у СОСЕДА, и правило оси не раздвоено."""

    def test_clock_named_read_delegates_to_the_site(self):
        """Правило живёт в ОДНОМ доме: запись — проекция площадки, не второй разбор.

        Контроль существует потому, что две копии одного правила расходятся
        МОЛЧА. Признак делегирования — не длина тела, а то, что «старая» функция
        не трогает данные правила (``CLOCK_FIELDS``) и не разбирает узлы сама.
        """
        src = Path(ifk.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        bodies = {node.name: node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)}
        self.assertIn("clock_named_read_site", bodies)
        shim = bodies["clock_named_read"]
        names = {n.id for n in ast.walk(shim) if isinstance(n, ast.Name)}
        self.assertNotIn("CLOCK_FIELDS", names,
                         "`clock_named_read` снова разбирает узлы сам — правило "
                         "раздвоено, и копии разойдутся молча")
        self.assertIn("clock_named_read_site", names)

    def test_the_two_readings_agree_on_every_shape(self):
        for text in ('rec["timestamp"]', 'rec.get("generated_at")',
                     'rec["as_of"].strip()', 'rec["payload"]', 'rec.get("x")',
                     'now()'):
            with self.subTest(text=text):
                node = ast.parse(text, mode="eval").body
                site = ifk.clock_named_read_site(node)
                self.assertEqual(ifk.clock_named_read(node),
                                 None if site is None else site[2])

    def test_strong_axis_site_is_not_weak_axis_population(self):
        """Площадка, где значение производят СВОИ часы напрямую, слабой не является.

        Иначе прибор докладывал бы о населении НЕ ТОЙ оси, про которую говорит.

        Сцена подобрана ЗАМЕРОМ, а не на глаз: первая редакция ставила чтение
        рядом с `now()` через `or`, и там слабая ось не срабатывала ВООБЩЕ
        (`clock_named_read_site` в развилку не ходит), то есть сцена была пуста
        по другой причине и мутанта «убрать перебитие» пережила. Здесь
        получатель чтения САМ производное часов, поэтому срабатывают ОБЕ оси, и
        проверяется именно то, что сильная перебивает слабую.
        """
        rows = sites('''
            import datetime
            def f():
                doc = datetime.datetime.now()
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(rows, [], "сильная ось перебивает слабую у соседа — "
                                   "здесь обязана перебивать так же")

    def test_the_same_scene_without_the_clock_IS_population(self):
        """Обратная сторона: без своих часов у получателя площадка ЕСТЬ."""
        rows = sites('''
            def f(payload):
                doc = payload
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], INPUT)

    def test_a_non_clock_name_is_not_a_site(self):
        self.assertEqual(sites('def f(rec):\n    return {"date": rec["day"]}\n'), [])


class InputMapping(unittest.TestCase):
    """«Отображение пришло извне» — утверждение о КОДЕ, не догадка."""

    def test_parameter_is_input(self):
        row = one('def f(rec):\n    return {"date": rec["timestamp"]}\n')
        self.assertEqual(row["verdict"], INPUT)
        self.assertIn("параметр объемлющей функции", row["why"])

    def test_keyword_only_and_star_parameters_count_too(self):
        for head in ("def f(*, rec):", "def f(**rec):", "def f(*rec):"):
            with self.subTest(head=head):
                row = one(f'{head}\n    return {{"date": rec["timestamp"]}}\n')
                self.assertEqual(row["verdict"], INPUT)

    def test_element_of_a_parameter_is_input(self):
        row = one('''
            def f(rows):
                out = {}
                for rec in rows:
                    out["date"] = rec["timestamp"]
                return out
        ''')
        self.assertEqual(row["verdict"], INPUT)
        self.assertIn("элемент обхода", row["why"])

    def test_json_parse_is_input(self):
        row = one('''
            import json
            def f(text):
                doc = json.loads(text)
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], INPUT)
        self.assertIn("json.loads()", row["why"])

    def test_a_converter_is_not_a_door_to_the_outside(self):
        """``json.dumps`` наружу не читает. Признак назван поимённо не зря."""
        row = one('''
            import json
            def f(doc):
                text = json.dumps(doc)
                return {"date": text["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertNotIn("разобрано из текста", row["why"])

    def test_part_of_input_is_input(self):
        row = one('''
            def f(payload):
                return {"date": payload["meta"]["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], INPUT)
        self.assertIn("ЧАСТЬ", row["why"])

    def test_get_of_input_is_input(self):
        row = one('''
            def f(payload):
                return {"date": payload.get("meta").get("timestamp")}
        ''')
        self.assertEqual(row["verdict"], INPUT)

    def test_guard_tail_is_not_an_operand(self):
        row = one('''
            def f(payload):
                return {"date": (payload or {})["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], INPUT)

    def test_unpacking_takes_its_own_place_in_the_tuple(self):
        row = one('''
            def f(payload):
                doc, why = payload, None
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], INPUT)
        self.assertIn("место распаковки", row["why"])

    def test_the_other_place_of_the_tuple_is_the_other_answer(self):
        """Обратная сторона распаковки: место решает, и оно не угадывается."""
        row = one('''
            def f(payload):
                why, doc = None, payload
                return {"date": why["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)

    def test_same_module_return_is_followed(self):
        row = one('''
            import json
            def read(path):
                return json.loads(path.read_text())
            def f(path):
                doc = read(path)
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], INPUT)
        self.assertIn("`read()`", row["why"])


class OwnClockMapping(unittest.TestCase):
    """«Отображение собрал я, и имя в нём поставили мои часы»."""

    def test_own_literal_stamped_by_the_wall_clock(self):
        row = one('''
            import datetime
            def f():
                doc = {"generated_at": datetime.datetime.now().isoformat()}
                doc["as_of"] = doc["generated_at"]
                return doc
        ''')
        self.assertEqual(row["verdict"], OWN)
        self.assertIn("своей стенной дверью", row["why"])

    def test_own_literal_whose_field_came_from_outside_is_unmeasured(self):
        """Обратный контроль: собрал здесь ≠ поставил своими часами.

        Сцена даёт ДВЕ площадки, и обе содержательны: сам литерал — чистый
        `input` (он копирует отметку входа), а чтение у собранного документа —
        третий исход. Выбирать площадку надо ПОЛЕМ, а не «первой»: порядок
        строк к предмету отношения не имеет.
        """
        by_field = {r["field"]: r for r in sites('''
            def f(payload):
                doc = {"generated_at": payload["generated_at"]}
                doc["as_of"] = doc["generated_at"]
                return doc
        ''')}
        self.assertEqual(by_field["generated_at"]["verdict"], INPUT)
        row = by_field["as_of"]
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("происхождение самого", row["why"])

    def test_own_literal_without_the_name_is_unmeasured(self):
        row = one('''
            def f():
                doc = {"status": "ok"}
                doc["as_of"] = doc["generated_at"]
                return doc
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("в нём нет", row["why"])

    def test_own_clock_is_NOT_transitive_through_a_part(self):
        """Асимметрия, из-за которой правило и написано.

        ``receipt["meta"]["generated_at"]`` читает имя у ВЛОЖЕННОГО отображения,
        а литерал, который мера открыла, — внешний. Объявить это «своими
        часами» значило бы повторить «контейнер не есть привязка».
        """
        row = one('''
            import datetime
            def f():
                receipt = {"generated_at": datetime.datetime.now().isoformat()}
                receipt["as_of"] = receipt["meta"]["generated_at"]
                return receipt
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("ВЛОЖЕННОМ отображении", row["why"])

    def test_part_of_input_stays_input_so_the_asymmetry_is_one_sided(self):
        """Та же форма со ВХОДОМ даёт `input` — асимметрия намеренная, а не баг."""
        row = one('''
            def f(receipt):
                return {"as_of": receipt["meta"]["generated_at"]}
        ''')
        self.assertEqual(row["verdict"], INPUT)


class ThirdOutcome(unittest.TestCase):
    """«Не измерено» — самостоятельный исход, и у него всегда есть причина."""

    def test_every_unmeasured_names_its_cause(self):
        for scene in (
            'def f():\n    return {"date": GLOBAL_DOC["timestamp"]}\n',
            'def f():\n    try:\n        pass\n    except KeyError as doc:\n'
            '        return {"date": doc["timestamp"]}\n',
        ):
            with self.subTest(scene=scene.splitlines()[0]):
                row = one(scene)
                self.assertEqual(row["verdict"], UNMEASURED)
                self.assertTrue(row["why"].strip(), "третий исход без причины")

    def test_a_parameter_reassigned_in_the_body_is_unmeasured(self):
        """Своим тестом, а не членом `subTest`: мутация имеет право на ИМЯ.

        Пока эти два случая жили подпунктами общего `subTest`, они убивали
        своих мутантов, но короткая сводка печатает падение подтеста как
        `SUBFAILED(...)`, и мутационный стенд, собиравший имена по `FAILED`,
        читал УБИТОГО как выжившего. Дефект был в стенде; разведение по
        отдельным тестам делает находку независимой от формы сводки.
        """
        row = one('def f(rec):\n    rec = {}\n    return {"date": rec["timestamp"]}\n')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("и параметр, и переприсвоено", row["why"])

    def test_a_name_bound_twice_is_unmeasured(self):
        row = one('def f(a, b):\n    doc = a\n    doc = b\n'
                  '    return {"date": doc["timestamp"]}\n')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("связано 2 раз", row["why"])

    def test_closure_over_the_enclosing_function_is_unmeasured(self):
        """Названная односторонность: вложенная область внешних привязок не видит."""
        row = one('''
            def outer(payload):
                doc = payload
                def inner():
                    return {"date": doc["timestamp"]}
                return inner
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("замыкание", row["why"])

    def test_a_name_bound_in_another_function_does_not_leak(self):
        row = one('''
            def other(payload):
                doc = payload
                return doc
            def f():
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)

    def test_imported_callee_is_unmeasured_and_says_why(self):
        row = one('''
            from elsewhere import read_state
            def f():
                doc = read_state()
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("через импорт мера не ходит", row["why"])

    def test_two_definitions_of_the_callee_is_unmeasured(self):
        row = one('''
            import json
            def build(x):
                return json.loads(x)
            class A:
                def build(self, x):
                    return {}
            def f(x):
                doc = build(x)
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("определено 2 раз", row["why"])

    def test_disagreeing_returns_are_unmeasured(self):
        row = one('''
            import json
            def read(x, flag):
                if flag:
                    return json.loads(x)
                return SOMETHING
            def f(x, flag):
                doc = read(x, flag)
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("РАЗНЫЕ ответы", row["why"])

    def test_agreeing_returns_are_resolved(self):
        """Обратная сторона: согласные возвраты дают ответ, а не третий исход."""
        row = one('''
            import json
            def read(x, flag):
                if flag:
                    return json.loads(x)
                return json.loads(x.strip())
            def f(x, flag):
                doc = read(x, flag)
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], INPUT)

    def test_disagreeing_fork_operands_are_unmeasured(self):
        row = one('''
            def f(payload):
                return {"date": (payload or OTHER)["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("РАЗНЫЕ ответы", row["why"])

    def test_a_name_resolving_through_itself_is_unmeasured_not_a_hang(self):
        """И ПРИЧИНА названа именно та: «через себя», а не «спуск глубок».

        Проверять один вердикт тут недостаточно, и это измерено мутацией:
        убери множество `seen`, и предел глубины вернёт тот же `unmeasured` с
        ДРУГОЙ причиной — то есть прибор перестал бы понимать, что он увидел.
        """
        row = one('''
            def f():
                doc = doc.get("inner")
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("разрешается через себя", row["why"])
        self.assertNotIn("глубже", row["why"])

    def test_self_recursive_callee_terminates(self):
        """Та же пара, что у имени: вердикт И причина (см. тест выше)."""
        row = one('''
            def read(x):
                return read(x)
            def f(x):
                doc = read(x)
                return {"date": doc["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("разрешается через себя", row["why"])
        self.assertNotIn("глубже", row["why"])

    def test_tuple_shorter_than_the_unpacking_place(self):
        row = one('''
            def f(payload):
                a, b, c = (payload, None)
                return {"date": c["timestamp"]}
        ''')
        self.assertEqual(row["verdict"], UNMEASURED)
        self.assertIn("короче", row["why"])

    def test_unparsable_module_is_named_not_counted(self):
        rows, why = wamo.module_sites("def f(:\n", "сцена.py")
        self.assertEqual(rows, [])
        self.assertIn("не разобрано", why)


class WholeTree(unittest.TestCase):
    """Замер на НАСТОЯЩЕМ дереве: три исхода у самого прибора."""

    def test_missing_root_is_unmeasured_not_clean(self, ):
        _sites, unmeasured, parsed = wamo.census(_ROOT, roots=("нет-такого-каталога",))
        self.assertEqual(parsed, 0)
        self.assertIn("нет-такого-каталога", unmeasured)

    def test_no_files_parsed_refuses_to_report_a_share(self):
        doc = wamo.measure(_ROOT, now=_FIXED_NOW, roots=("нет-такого-каталога",))
        self.assertFalse(doc["measured"])
        self.assertEqual(doc["status"], "НЕ ИЗМЕРЕНО")
        self.assertIn("ни один файл", doc["reason"])
        self.assertNotIn("share_pct", doc)

    def test_empty_population_is_not_a_zero_share(self):
        """Пустое население ⇒ доли НЕТ. Ноль здесь был бы утверждением о дереве."""
        scene = _ROOT / "spa_core" / "utils"
        self.assertTrue(scene.is_dir())
        doc = wamo.measure(_ROOT, now=_FIXED_NOW, roots=("spa_core/utils",))
        if doc["population"] if doc.get("measured") else None:
            self.skipTest("в этом каталоге население непусто — сцена не та")
        self.assertFalse(doc["measured"])
        self.assertIn("население слабой оси пусто", doc["reason"])

    def test_the_real_tree_is_measured_and_the_population_is_not_tiny(self):
        doc = tree_doc()
        self.assertTrue(doc["measured"], doc.get("reason"))
        self.assertGreater(doc["population"]["sites"], 100)
        self.assertEqual(sum(doc["tally"].values()), doc["population"]["sites"])
        self.assertEqual(doc["generated_at"], "2026-10-11T12:00:00Z")

    def test_the_denominators_are_named_separately(self):
        doc = tree_doc()
        resolved = doc["share_of_resolved_pct"]
        self.assertIsNotNone(resolved)
        self.assertNotEqual(doc["share_pct"][INPUT], resolved[INPUT],
                            "доля среди ВСЕХ и доля среди РАЗРЕШЁННЫХ совпали — "
                            "значит «не измерено» из знаменателя всё-таки вычли")
        self.assertAlmostEqual(sum(doc["share_pct"].values()), 100.0, delta=0.3)

    def test_a_real_own_clock_site_is_re_measured_every_run(self):
        """Положительный контроль на НАСТОЯЩЕМ файле.

        ``card_delivery.deliver`` сам ставит ``generated_at`` своими часами и
        сам же копирует его в ``since`` — ровно та форма, за которую ADR-503
        отверг ``record_generated_at``. Исчезни она — тест краснеет, и число
        «своих часов» пересматривается замером, а не остаётся прозой.
        """
        doc = tree_doc()
        owners = {(r["module"], r["field"]) for r in doc["own_clock_sites"]}
        self.assertIn(("spa_core/monitoring/card_delivery.py", "since"), owners)
        self.assertGreaterEqual(len(doc["own_clock_sites"]), 1)

    def test_a_real_input_site_is_re_measured_every_run(self):
        doc = tree_doc()
        self.assertGreater(doc["tally"][INPUT], doc["tally"][OWN])

    def test_an_absent_named_case_is_reported_absent(self):
        """Обратная сторона: площадки нет ⇒ `present=False` и причина названа.

        Без этого контроля «случай ADR-539 на месте» нельзя отличить от
        «прибор так говорит про любой случай» — то есть утверждение о коде
        подменялось бы утверждением о константе.
        """
        rows = wamo._named_cases([])
        self.assertEqual(len(rows), len(wamo.NAMED_CASES))
        for row in rows:
            self.assertFalse(row["present"])
            self.assertEqual(row["verdict"], UNMEASURED)
            self.assertIsNone(row["line"])
            self.assertIn("площадки нет", row["why"])

    def test_both_cases_ADR_539_checked_by_hand_are_present(self):
        """Случаи ADR-539 обязаны БЫТЬ в населении — иначе мерить нечего."""
        doc = tree_doc()
        for case in doc["named_cases"]:
            with self.subTest(module=case["module"]):
                self.assertTrue(case["present"],
                                f"площадка ADR-539 исчезла: {case['why']}")
                self.assertTrue(case["claim"])

    def test_neither_hand_checked_case_is_reached_by_the_machine(self):
        """ГЛАВНАЯ НАХОДКА, закреплённая тестом.

        Оба случая, которые ADR-539 проверил ЧЕЛОВЕКОМ, машинный признак НЕ
        достаёт: один лежит за импортом, второй — за читателем, набивающим
        список. Красный тест здесь означает «ось стала достигать названного
        случая» — это НЕ поломка, а повод пересмотреть вывод замером.
        """
        doc = tree_doc()
        for case in doc["named_cases"]:
            with self.subTest(module=case["module"]):
                self.assertEqual(case["verdict"], UNMEASURED, case["why"])
        self.assertEqual(doc["verdict"]["named_cases_resolved"], 0)

    def test_the_admitted_names_get_no_measured_evidence(self):
        """Про имена ``_IDENTITY_FIELDS`` ось не говорит НИЧЕГО измеренного."""
        doc = tree_doc()
        self.assertEqual(doc["verdict"]["admitted_names_resolved"], 0)
        self.assertGreaterEqual(doc["admitted_names"]["sites"], 1)

    def test_unmeasured_causes_are_counted_and_named(self):
        doc = tree_doc()
        self.assertTrue(doc["unmeasured_causes"])
        for row in doc["unmeasured_causes"]:
            self.assertTrue(row["cause"].strip())
            self.assertGreater(row["sites"], 0)


class Verdict(unittest.TestCase):
    """Вердикт ВЫЧИСЛЕН из замера, а не объявлен строкой."""

    def _doc(self, tally, admitted_resolved=0, named_resolved=0):
        return {
            "tally": dict(tally),
            "admitted_names": {"sites": 1, "tally": {
                INPUT: admitted_resolved, OWN: 0, UNMEASURED: 1}},
            "named_cases": [{"verdict": INPUT if named_resolved else UNMEASURED}],
        }

    def test_finding_when_the_axis_reads_foreign_more_often(self):
        verdict = wamo._verdict(self._doc({INPUT: 115, OWN: 11, UNMEASURED: 81}))
        self.assertTrue(verdict["finding"])
        self.assertTrue(verdict["axis_reads_foreign_mapping_more_often"])
        self.assertIn("115", verdict["why"])

    def test_no_finding_when_own_clock_is_not_the_smaller_part(self):
        verdict = wamo._verdict(self._doc(
            {INPUT: 2, OWN: 11, UNMEASURED: 0},
            admitted_resolved=1, named_resolved=1))
        self.assertFalse(verdict["finding"], verdict["why"])
        self.assertFalse(verdict["axis_reads_foreign_mapping_more_often"])

    def test_equal_counts_are_not_a_finding_on_that_ground(self):
        """Сравнение, а не порог: равенство в находку не превращается."""
        verdict = wamo._verdict(self._doc(
            {INPUT: 5, OWN: 5, UNMEASURED: 0},
            admitted_resolved=1, named_resolved=1))
        self.assertFalse(verdict["axis_reads_foreign_mapping_more_often"])
        self.assertFalse(verdict["finding"], verdict["why"])

    def test_unresolved_admitted_names_are_a_finding_on_their_own(self):
        verdict = wamo._verdict(self._doc(
            {INPUT: 1, OWN: 11, UNMEASURED: 0}, named_resolved=1))
        self.assertTrue(verdict["finding"])
        self.assertIn("_IDENTITY_FIELDS", verdict["why"])

    def test_unresolved_named_cases_are_a_finding_on_their_own(self):
        verdict = wamo._verdict(self._doc(
            {INPUT: 1, OWN: 11, UNMEASURED: 0}, admitted_resolved=1))
        self.assertTrue(verdict["finding"])
        self.assertIn("ADR-539", verdict["why"])

    def test_the_axis_never_gets_the_right_to_decide_a_name(self):
        """Своим тестом, а не `subTest`: см. пояснение у соседнего контроля —
        падение подтеста печатается как `SUBFAILED`, и мутант выглядел живым."""
        verdict = wamo._verdict(self._doc({INPUT: 115, OWN: 11, UNMEASURED: 81}, 1, 1))
        self.assertFalse(verdict["axis_may_support_a_name_decision"])
        self.assertTrue(verdict["why_it_may_not"].strip())

    def test_the_right_is_denied_even_when_the_axis_looks_good(self):
        verdict = wamo._verdict(self._doc({INPUT: 0, OWN: 11, UNMEASURED: 0}, 1, 1))
        self.assertFalse(verdict["finding"], verdict["why"])
        self.assertFalse(verdict["axis_may_support_a_name_decision"],
                         "право оси не выводится из её счётов — водораздела у "
                         "меры нет ни при каком замере")


class ArtifactAndRendering(unittest.TestCase):
    """Артефакт и отрисовка — у ПРОИЗВОДИТЕЛЯ, и доезжают в обоих исходах."""

    def test_run_writes_the_artifact(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "spa_core").mkdir()
            (root / "spa_core" / "m.py").write_text(
                'def f(rec):\n    return {"date": rec["timestamp"]}\n',
                encoding="utf-8")
            result = wamo.run(root=str(root), now=_FIXED_NOW)
            path = root / "data" / wamo.ARTIFACT
            self.assertTrue(path.exists())
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], wamo.SCHEMA)
            self.assertTrue(result["measured"])

    def test_the_artifact_reaches_the_reader_on_the_third_outcome_too(self):
        """Иначе шаг 0-офис не отличит «не измерено» от «ступень не запускалась»."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            wamo.run(root=str(root), now=_FIXED_NOW)
            doc = json.loads((root / "data" / wamo.ARTIFACT).read_text(encoding="utf-8"))
            self.assertFalse(doc["measured"])
            self.assertTrue(doc["reason"].strip())

    def test_render_names_the_third_outcome_first(self):
        lines = wamo.render({"order": wamo.ORDER, "generated_at": "x",
                             "measured": False, "reason": "каталогов нет"})
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines))

    def test_render_of_the_real_measurement_carries_the_numbers(self):
        doc = tree_doc()
        text = "\n".join(wamo.format_report(doc))
        for needle in ("[ДОЛЯ]", "[ПРИНЯТЫЕ ИМЕНА]", "[СЛУЧАЙ ADR-539]",
                       "[ВЕРДИКТ]", "ЦЕНА ОДНОСТОРОННОСТИ", "ADVISORY"):
            self.assertTrue(needle in text, f"в отчёте нет «{needle}»")

    def test_one_sidedness_is_printed_not_only_stored(self):
        doc = tree_doc()
        text = "\n".join(wamo.render(doc))
        for line in doc["one_sidedness"]:
            self.assertTrue(line in text)

    def test_cli_return_codes_are_three(self):
        self.assertEqual(wamo.main(["--root", "/нет/такого/дерева"]), 2)


class Wiring(unittest.TestCase):
    """Кто это читает — проверено проводкой, а не намерением."""

    def test_the_bridge_produces_the_artifact(self):
        from spa_core.monitoring import findings_bridge as bridge
        self.assertIn(f"data/{wamo.ARTIFACT}", bridge.PRODUCES)
        self.assertIn("weak_axis_mapping_origin", bridge.CENSUS_STAGE)
        self.assertEqual(
            bridge.CENSUS_PRODUCT["weak_axis_mapping_origin"]["artifact"],
            f"data/{wamo.ARTIFACT}")

    def test_the_office_step_knows_the_artifact_and_its_producer(self):
        office = importlib.import_module("scripts.consume_office_reports")
        self.assertIn(wamo.ARTIFACT, office._READ_SCHEMA)
        self.assertEqual(office._PRODUCER[wamo.ARTIFACT],
                         "spa_core/monitoring/weak_axis_mapping_origin.py")

    def test_the_office_branch_is_proven_BY_OUTCOME(self):
        """Не «ветвь есть», а «ветвь ПЕЧАТАЕТ числа замера».

        «``run`` зовёт резолвер» к поведению слепо (ADR-333), поэтому отрисовка
        вызывается по-настоящему и ответ сверяется с настоящим документом.
        """
        office = importlib.import_module("scripts.consume_office_reports")
        doc = tree_doc()
        lines = office._summarize_json(wamo.ARTIFACT, doc)
        text = "\n".join(lines)
        self.assertIn("[ДОЛЯ]", text)
        self.assertIn(str(doc["tally"][INPUT]), text)

    def test_the_manifest_declares_the_artifact(self):
        manifest = json.loads((_ROOT / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        paths = {row.get("path") for row in manifest.get("artifacts", [])}
        self.assertIn(f"data/{wamo.ARTIFACT}", paths)


class Advisory(unittest.TestCase):
    """Прибор только читает, и у него нет права гейтить."""

    def test_llm_is_forbidden_and_declared(self):
        src = Path(wamo.__file__).read_text(encoding="utf-8")
        self.assertIn("# LLM_FORBIDDEN", src)
        for banned in ("anthropic", "openai", "subprocess"):
            self.assertNotIn(banned, src)

    def test_the_module_writes_nothing_but_its_own_artifact(self):
        tree = ast.parse(Path(wamo.__file__).read_text(encoding="utf-8"))
        writes = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "open"]
        self.assertEqual(writes, [])
        self.assertIn("atomic_save", {n.id for n in ast.walk(tree)
                                      if isinstance(n, ast.Name)})

    def test_no_clock_is_read_at_import_time(self):
        """Якорь времени на импорте краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348)."""
        tree = ast.parse(Path(wamo.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                self.assertIsNone(ifk.derivation(getattr(node, "value", None),
                                                 ifk._Scope(frozenset(), frozenset())),
                                  "модульная привязка читает стенные часы на импорте")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
