#!/usr/bin/env python3
"""Батарея прибора «модульная числовая постоянная как операнд» (заказ G115 п. 2).

Каждая сцена — контроль В ОБЕ СТОРОНЫ: класс обязан находиться там, где он
есть, и НЕ находиться там, где его нет. Третий исход проверяется отдельно и
никогда не выдаётся за «чисто» (инв. #17).

Дат в фикстурах нет вовсе: предмет прибора — КОД, а не свежесть, и литеральная
дата здесь была бы бомбой от хода календаря (`.claude/rules/deployment.md`).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import identity_field_kind as field_kind
from spa_core.monitoring import modular_constant_operand as mco


def _src(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def _tree(**files: str) -> Path:
    """Одноразовое дерево с файлами по относительным путям."""
    root = Path(tempfile.mkdtemp(prefix="spa_g115p2_"))
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_src(body), encoding="utf-8")
    return root


#: Модуль, у которого класс ЕСТЬ и он прямой: постоянная стои́т в самом
#: выражении поля. Форма взята с живого кода —
#: `claim_release_census.py:404` (`/ _HOUR`), он же в ADR-697 назван поимённо.
DIRECT = """
    _HOUR = 3600.0

    def rows(now, stamp):
        return {"age_hours": (now - stamp).total_seconds() / _HOUR}
"""

#: Модуль, у которого класс ЕСТЬ и он транзитивный: постоянной в выражении поля
#: нет, но имя, которое оно читает, посчитано ИЗ постоянных.
TRANSITIVE = """
    HI = 300
    LO = 60
    SPAN = HI - LO

    def view():
        return {"span": SPAN}
"""

#: Ось видит это УЖЕ сегодня — литерал стои́т в выражении сам.
ALREADY_SEEN = """
    def rows(spent):
        return {"left": 300 - spent}
"""

#: Постоянная стои́т ОДНА. Находкой не является: постоянная не переезжает.
LONE = """
    WINDOW_S = 300

    def view():
        return {"window_s": WINDOW_S}
"""


class TheClassIsFoundWhereItIs(unittest.TestCase):
    """Положительная сторона: класс находится, и находится ИМЕНОВАННО."""

    def test_direct_site_is_found_and_names_the_constant(self):
        sites, consts, why = mco.module_sites(_src(DIRECT))
        self.assertEqual(why, "")
        self.assertEqual(consts, {"_HOUR": "3600.0"})
        self.assertEqual(len(sites), 1, [str(s) for s in sites])
        site = sites[0]
        self.assertEqual(site.field, "age_hours")
        self.assertEqual(site.consts, ("_HOUR",))
        self.assertFalse(site.transitive)
        self.assertIn("3600.0", site.how)

    def test_transitive_site_is_found_and_marked_as_through_a_name(self):
        sites, _consts, why = mco.module_sites(_src(TRANSITIVE))
        self.assertEqual(why, "")
        self.assertEqual([s.field for s in sites], ["span"])
        self.assertTrue(sites[0].transitive)
        self.assertEqual(sites[0].consts, ())

    def test_a_negative_literal_constant_is_numeric_too(self):
        sites, consts, _why = mco.module_sites(_src("""
            FLOOR = -5

            def view(x):
                return {"gap": FLOOR - x}
        """))
        self.assertEqual(consts, {"FLOOR": "-5"})
        self.assertEqual([s.field for s in sites], ["gap"])


class TheClassIsNotFoundWhereItIsNot(unittest.TestCase):
    """Отрицательная сторона — и у каждого отказа НАЗВАННОЕ основание."""

    def test_what_the_axis_already_sees_is_not_in_the_class(self):
        sites, _consts, why = mco.module_sites(_src(ALREADY_SEEN))
        self.assertEqual(why, "")
        self.assertEqual(sites, [], "литерал в выражении — ответ оси, не класс")

    def test_a_constant_standing_alone_is_not_a_site(self):
        sites, consts, _why = mco.module_sites(_src(LONE))
        self.assertEqual(consts, {"WINDOW_S": "300"},
                         "постоянная найдена — молчит именно ПЛОЩАДКА")
        self.assertEqual(sites, [])

    def test_a_name_shadowed_anywhere_is_never_substituted(self):
        sites, consts, _why = mco.module_sites(_src("""
            TIMEOUT = 300

            def a(TIMEOUT, spent):
                return {"left": TIMEOUT - spent}
        """))
        self.assertEqual(consts, {}, "затенённое имя выброшено из постоянных")
        self.assertEqual(sites, [])

    def test_bool_is_excluded_by_type_not_by_subtraction(self):
        sites, consts, _why = mco.module_sites(_src("""
            FLAG = True

            def a(x):
                return {"k": FLAG - x}
        """))
        self.assertEqual(consts, {})
        self.assertEqual(sites, [])

    def test_a_name_rebound_to_a_non_number_is_not_a_constant(self):
        sites, consts, _why = mco.module_sites(_src("""
            X = 300
            X = load()

            def a(spent):
                return {"left": X - spent}
        """))
        self.assertEqual(consts, {})
        self.assertEqual(sites, [])

    def test_a_constant_of_a_function_is_not_modular(self):
        sites, consts, _why = mco.module_sites(_src("""
            def a(spent):
                LIMIT = 300
                return {"left": LIMIT - spent}
        """))
        self.assertEqual(consts, {}, "заказ назвал класс МОДУЛЬНЫМ")
        self.assertEqual(sites, [])

    def test_a_text_constant_is_not_numeric(self):
        sites, consts, _why = mco.module_sites(_src("""
            NAME = "aave"

            def a():
                return {"key": NAME + "_v3"}
        """))
        self.assertEqual(consts, {})
        self.assertEqual(sites, [])


#: Модульное СОСТОЯНИЕ, а не постоянная: единственная модульная привязка —
#: числовой литерал, но имя объявлено ``global`` и ПЕРЕ-СВЯЗАНО в функции.
#: Форма взята с живого кода — `pendle_adapter._LLAMA_FAILED_AT` и
#: `allocator._live_apy_cache_ts`, оба названы в ADR-702 поимённо.
GLOBAL_STATE = """
    _FAILED_AT = 0.0

    def note(now, spent):
        global _FAILED_AT
        _FAILED_AT = now
        return {"gap": _FAILED_AT - spent}
"""

#: Та же форма БЕЗ ``global`` — и постоянная здесь НАСТОЯЩАЯ. Отрицательный
#: контроль второй двери: без него правило «не постоянная» нечем отличить от
#: «любое имя, присвоенное в функции».
GLOBAL_FREE = """
    _FAILED_AT = 0.0

    def note(spent):
        return {"gap": _FAILED_AT - spent}
"""

#: Выброс стои́т ПОСТОЯННОЙ, но НИ ОДНОЙ площадки — расклад живого дерева на
#: 2026-10-12 (1 постоянная, 0 площадок). Форма взята с единственного живого
#: случая, `yield_ladder_builder.capital`: имя есть параметр функции, и в
#: арифметике, пишущей поле, не участвует НИГДЕ.
DROP_COSTS_NO_SITE = """
    TIMEOUT = 300

    def a(TIMEOUT):
        return TIMEOUT
"""

#: Выброс затенения ТЕРЯЕТ площадку: имя затенено параметром в `a`, но в `b`
#: оно читается как настоящая модульная постоянная. Живое дерево таких
#: модулей на 2026-10-12 не содержит ни одного (цена = 0 площадок), поэтому
#: положительный контроль обязан быть собран здесь — иначе измеренный ноль
#: был бы неотличим от неработающей меры.
DROP_LOSES_A_SITE = """
    TIMEOUT = 300

    def a(TIMEOUT, spent):
        return {"shaded": TIMEOUT - spent}

    def b(spent):
        return {"left": TIMEOUT - spent}
"""


class TheSecondOneSidednessIsClosed(unittest.TestCase):
    """Дверь ``global`` — заказом G697 п. 1 НЕ названная, промах в сторону НАХОДКИ.

    ``_shadowed`` оси перечисляет привязки НЕ присваиванием. ``global X`` имя
    не ЗАТЕНЯЕТ — он пере-связывает ТУ ЖЕ модульную привязку, поэтому такое
    имя проходило и `module_constants`, и `shadowed_anywhere`, а подстановка
    его литералом неверна ВЕЗДЕ, включая модульную область.
    """

    def test_a_global_declared_name_is_not_a_constant(self):
        sites, consts, why = mco.module_sites(_src(GLOBAL_STATE))
        self.assertEqual(why, "")
        self.assertEqual(consts, {},
                         "объявленное `global` имя есть модульное СОСТОЯНИЕ")
        self.assertEqual(sites, [])

    def test_the_same_shape_without_global_is_a_real_constant(self):
        """Отрицательный контроль: правило режет ``global``, а не присваивание."""
        sites, consts, why = mco.module_sites(_src(GLOBAL_FREE))
        self.assertEqual(why, "")
        self.assertEqual(consts, {"_FAILED_AT": "0.0"})
        self.assertEqual([s.field for s in sites], ["gap"])

    def test_shadowing_alone_would_have_let_the_state_through(self):
        """Почему дверь ВТОРАЯ, а не та же: затенения у этого имени НЕТ."""
        tree = ast.parse(_src(GLOBAL_STATE))
        self.assertNotIn("_FAILED_AT", mco.shadowed_anywhere(tree),
                         "`global` не есть затенение — направления промаха "
                         "у двух дверей ОБРАТНЫЕ, и слить их нельзя")
        self.assertIn("_FAILED_AT", mco.globals_declared(tree))

    def test_globals_declared_is_empty_where_there_is_no_global(self):
        self.assertEqual(mco.globals_declared(ast.parse(_src(GLOBAL_FREE))),
                         set())

    def test_a_global_declared_name_is_dropped_in_the_module_scope_too(self):
        """Промах был бы ВЕЗДЕ: площадка в модульной области тоже ложная."""
        sites, consts, _why = mco.module_sites(_src("""
            _TS = 0.0

            def bump(now):
                global _TS
                _TS = now

            def view(spent):
                return {"age": _TS - spent}
        """))
        self.assertEqual(consts, {})
        self.assertEqual(sites, [])


class ThePriceOfTheOwnOneSidednessIsMeasured(unittest.TestCase):
    """Заказ G697 п. 1 — ЦЕНА выброса затенённых имён, подстановкой в сам прибор.

    Две величины РАЗВЕДЕНЫ: выброшенная постоянная (ОПЕРАНД) и потерянная
    площадка (ОТВЕТ). Ноль у второй не отменяет ненулевой первой — правило
    ADR-700 п. 3, и на живом дереве 2026-10-12 расклад ровно такой: 1 и 0.
    """

    def test_no_drop_means_no_cost_and_no_reason(self):
        cost = mco.module_shadow_cost(_src(DIRECT))
        self.assertEqual(cost.dropped, ())
        self.assertEqual(cost.lost, ())
        self.assertEqual(cost.reason, "", "третий исход тут не наступал")

    def test_the_shortcut_is_sound_where_the_door_did_not_fire(self):
        """Контроль СОКРАЩЕНИЯ: без выброса ответ обязан быть тот же.

        Второй прогон делается только там, где дверь сработала. Без этого
        контроля сокращение держалось бы на рассуждении, а не на тесте.
        """
        for name, src in (("DIRECT", DIRECT), ("TRANSITIVE", TRANSITIVE),
                          ("LONE", LONE), ("ALREADY_SEEN", ALREADY_SEEN)):
            with self.subTest(scene=name):
                tight, _c, _w = mco.module_sites(_src(src))
                loose, _c2, _w2 = mco.module_sites(_src(src),
                                                   drop_shadowed=False)
                self.assertEqual([(s.field, s.line) for s in tight],
                                 [(s.field, s.line) for s in loose])

    def test_the_cost_names_the_dropped_constant_without_losing_a_site(self):
        """Расклад ЖИВОГО дерева: постоянная выброшена, площадка не потеряна."""
        cost = mco.module_shadow_cost(_src(DROP_COSTS_NO_SITE))
        self.assertEqual(cost.dropped, ("TIMEOUT",))
        self.assertEqual(cost.lost, (),
                         "имя не участвует в арифметике, пишущей поле")
        self.assertEqual(cost.reason, "")

    def test_the_cost_names_a_LOST_site_when_one_is_lost(self):
        """Положительный контроль ОТВЕТА: сцена, где выброс РЕАЛЬНО стои́т площадки."""
        cost = mco.module_shadow_cost(_src(DROP_LOSES_A_SITE))
        self.assertEqual(cost.dropped, ("TIMEOUT",))
        self.assertIn("left:7", cost.lost)
        self.assertEqual(cost.reason, "")

    def test_the_loose_answer_is_an_UPPER_bound_not_the_truth(self):
        """Сказано вслух: без выброса в ЗАТЕНЁННОЙ области площадка ложная.

        Поэтому расстояние между двумя ответами есть цена, а не поправка:
        верхняя граница содержит и настоящую потерю (`left`), и ложную
        (`shaded`, где `TIMEOUT` — параметр).
        """
        cost = mco.module_shadow_cost(_src(DROP_LOSES_A_SITE))
        self.assertEqual(sorted(cost.lost), ["left:7", "shaded:4"])

    def test_dropped_and_lost_are_separate_numbers(self):
        """Слить их в одно число значило бы потерять половину вопроса заказа."""
        doc = mco.tally(None, None, _tree(**{
            "spa_core/a.py": DROP_COSTS_NO_SITE}))
        self.assertEqual(doc["shadow_cost"]["dropped_constants"], 1)
        self.assertEqual(doc["shadow_cost"]["dropped_modules"], 1)
        self.assertEqual(doc["shadow_cost"]["lost_sites"], 0)
        self.assertEqual(doc["shadow_cost"]["lost_modules"], 0)

    def test_the_cost_is_named_by_module_and_name(self):
        doc = mco.tally(None, None, _tree(**{
            "spa_core/a.py": DROP_LOSES_A_SITE}))
        self.assertEqual(doc["shadow_cost"]["dropped_named"],
                         ["spa_core/a.py:TIMEOUT"])
        self.assertIn("spa_core/a.py:left:7", doc["shadow_cost"]["lost_named"])

    def test_a_tree_without_any_drop_reports_zero_cost_not_silence(self):
        doc = mco.tally(None, None, _tree(**{"spa_core/p.py": DIRECT}))
        self.assertEqual(doc["shadow_cost"]["dropped_constants"], 0)
        self.assertEqual(doc["shadow_cost"]["lost_sites"], 0)
        self.assertEqual(doc["shadow_cost"]["unmeasured"], {})

    def test_an_unparsable_module_refuses_the_cost_with_a_named_reason(self):
        cost = mco.module_shadow_cost("def (:")
        self.assertEqual(cost.dropped, ())
        self.assertIn("не разобрано", cost.reason)
        self.assertNotEqual(cost.reason, "", "«цены нет» тут было бы ложью")

    def test_the_report_prints_the_cost_next_to_the_population(self):
        """Заказ дословно: «это надо сказать там, где печатается 33»."""
        doc = mco.tally(None, None, _tree(**{
            "spa_core/a.py": DROP_LOSES_A_SITE}))
        lines = mco.report(doc)
        pop = [i for i, l in enumerate(lines) if l.startswith("  население ")]
        cost = [i for i, l in enumerate(lines) if "ЦЕНА односторонности" in l]
        self.assertTrue(pop and cost, lines)
        self.assertEqual(cost[0], pop[0] + 1,
                         "цена обязана стоять СТРОКОЙ НИЖЕ населения")

    def test_an_old_format_document_says_the_cost_is_unmeasured(self):
        """Раздела нет ⇒ третий исход, а не «цены нет» (инв. #17)."""
        lines = mco.cost_report({"population": 3})
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНА", lines[0])
        self.assertIn("СТАРОГО ОБРАЗЦА", lines[0])

    def test_the_cost_unmeasured_module_is_named_in_the_report(self):
        lines = mco.cost_report({"shadow_cost": {
            "dropped_constants": 0, "dropped_modules": 0, "lost_sites": 0,
            "lost_modules": 0, "dropped_named": [], "lost_named": [],
            "unmeasured": {"spa_core/x.py": "не разобрано: SyntaxError"}}})
        self.assertTrue(any("[ЦЕНА НЕ ИЗМЕРЕНА] spa_core/x.py" in l
                            for l in lines), lines)


class TheTodayAnswerIsTheAxisItself(unittest.TestCase):
    """Прибор НЕ несёт второй копии правила — он зовёт ось.

    Контроль отвечает на вопрос «верно ли повторён прогон оси», и отвечает
    сравнением с НАСТОЯЩИМ ``module_kinds``. Без утверждения о непустоте
    сравнивались бы два пустых списка — поэтому население сцены проверяется
    ОТДЕЛЬНО и до сравнения (урок «сцена обязана нести различимость»).
    """

    SOURCE = """
        import statistics

        TOTAL = 10

        def view(rows, spent):
            share = len(rows) / TOTAL
            return {
                "share": share,
                "left": 300 - spent,
                "mean": statistics.mean(rows),
                "label": f"{share:.1f}%",
                "name": "aave",
            }
    """

    def setUp(self):
        self.source = _src(self.SOURCE)
        self.tree = ast.parse(self.source)

    def _axis_rows(self):
        kinds, why = field_kind.module_kinds(self.source)
        self.assertEqual(why, "")
        rows = []
        for name, evidences in kinds.items():
            for ev in evidences:
                rows.append((name, ev.line, ev.arith or ev.arith_text or ""))
        return sorted(rows)

    def test_the_scene_carries_both_findings_and_silence(self):
        rows = self._axis_rows()
        spoke = [r for r in rows if r[2]]
        silent = [r for r in rows if not r[2]]
        self.assertTrue(spoke, "сцена без находок оси ничего бы не различала")
        self.assertTrue(silent, "сцена без молчания оси тоже ничего бы не различала")

    def test_the_today_answer_equals_the_axis_itself(self):
        mine = sorted(mco._axis_answers(self.tree))
        self.assertEqual(mine, self._axis_rows())

    def test_a_divergent_replication_would_be_caught(self):
        """Положительный контроль САМОГО контроля: сдвиг ответа краснеет."""
        mine = sorted(mco._axis_answers(self.tree))
        broken = [(n, l, "") for n, l, _ in mine]
        self.assertNotEqual(broken, self._axis_rows())


class TheThirdOutcomeIsItsOwnAnswer(unittest.TestCase):
    """«Не измерено» не выдаётся ни за «чисто», ни за ноль (инв. #17)."""

    def test_an_unparsable_module_refuses_with_a_named_reason(self):
        sites, _consts, why = mco.module_sites("def (:")
        self.assertIsNone(sites, "None, а не пустой список: мест не ИЗМЕРЕНО")
        self.assertIn("не разобрано", why)
        self.assertIn("SyntaxError", why)

    def test_a_missing_root_is_named_in_the_census(self):
        doc = mco.census(_tree(**{"spa_core/p.py": DIRECT}))
        self.assertEqual(doc["files_unmeasured"], {"scripts": "каталога нет в дереве"},
                         "каталога нет — причина поимённо, а не молча")
        self.assertEqual(doc["population"], 1)

    def test_a_tree_without_a_single_parsed_file_is_unmeasured(self):
        doc = mco.census(_tree(**{"spa_core/broken.py": "def (:",
                                  "scripts/also.py": "class ("}))
        self.assertEqual(doc["status"], mco.UNMEASURED)
        self.assertIn("ни один файл", doc["reason"])
        self.assertEqual(doc["files_parsed"], 0)
        self.assertEqual(len(doc["files_unmeasured"]), 2)

    def test_no_tree_means_unmeasured_population_not_zero(self):
        doc = mco.tally({"alpha": 2}, ["id"], None)
        self.assertEqual(doc["status"], mco.UNMEASURED)
        self.assertIsNone(doc["population"])
        self.assertIsNone(doc["candidate_hits"])

    def test_no_candidate_list_means_unmeasured_intersection_not_zero(self):
        doc = mco.tally(None, None, _tree(**{"spa_core/p.py": DIRECT}))
        self.assertEqual(doc["population"], 1)
        self.assertIsNone(doc["candidate_hits"],
                          "перечня не дали — это НЕ «ни одного не задето»")
        self.assertIsNone(doc["identity_hits"])

    def test_the_report_says_unmeasured_out_loud(self):
        lines = mco.report(mco.tally({"a": 1}, ["id"], None))
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines), lines)
        self.assertFalse(any(" 0 " in line for line in lines),
                         "ноль вместо «не измерено» — ровно инв. #17")


class TheVerdictsAreDiscriminatedByTheScene(unittest.TestCase):
    """Три вердикта — три РАЗНЫЕ сцены, и счёты у них не равны.

    Равные счёты сделали бы подмену имени вердикта невидимой (урок #786).
    """

    def test_an_empty_class_is_its_own_verdict(self):
        doc = mco.tally({"left": 2}, ["id"],
                        _tree(**{"spa_core/p.py": ALREADY_SEEN,
                                 "scripts/q.py": LONE}))
        self.assertEqual(doc["status"], mco.EMPTY)
        self.assertEqual(doc["population"], 0)
        self.assertEqual(doc["candidate_hits"], 0)

    def test_population_without_a_candidate_is_its_own_verdict(self):
        doc = mco.tally({"nothing_like_it": 2}, ["id"],
                        _tree(**{"spa_core/p.py": DIRECT,
                                 "scripts/q.py": TRANSITIVE}))
        self.assertEqual(doc["status"], mco.POPULATED_NO_CANDIDATE)
        self.assertEqual(doc["population"], 2)
        self.assertEqual(doc["candidate_hits"], 0)
        self.assertEqual(doc["identity_hits"], 0)
        self.assertIn("записать и закрыть", doc["reason"])

    def test_a_touched_candidate_is_its_own_verdict(self):
        doc = mco.tally({"age_hours": 4}, ["id"],
                        _tree(**{"spa_core/p.py": DIRECT}))
        self.assertEqual(doc["status"], mco.POPULATED_CANDIDATE_TOUCHED)
        self.assertEqual(doc["population"], 1)
        self.assertEqual(doc["candidate_hits"], 1)
        self.assertEqual(doc["candidate_sites"],
                         [s for s in doc["candidate_sites"]])
        self.assertTrue(doc["candidate_sites"][0].startswith("spa_core/p.py:"))

    def test_a_touched_identity_field_is_a_finding_too(self):
        doc = mco.tally({}, ["age_hours"], _tree(**{"spa_core/p.py": DIRECT}))
        self.assertEqual(doc["status"], mco.POPULATED_CANDIDATE_TOUCHED)
        self.assertEqual(doc["identity_hits"], 1)
        self.assertEqual(doc["candidate_hits"], 0,
                         "перечень кандидатов ПУСТ — это замер, а не отсутствие")

    def test_direct_and_transitive_are_separate_numbers(self):
        doc = mco.census(_tree(**{"spa_core/p.py": DIRECT,
                                  "scripts/q.py": TRANSITIVE}))
        self.assertEqual((doc["direct"], doc["transitive"]), (1, 1))
        self.assertEqual(doc["population"], doc["direct"] + doc["transitive"])


#: Цепочка в ДВА шага: ``SPAN`` считается из постоянных, ``WIDE`` — из
#: ``SPAN``. Литерала рядом нет НАМЕРЕННО: любой литерал в выражении сделал бы
#: имя посчитанным сразу, и сцена мерила бы один шаг вместо двух.
TWO_HOPS = """
    HI = 300
    LO = 60
    SPAN = HI - LO
    WIDE = SPAN + SPAN

    def view():
        return {"span": WIDE}
"""

#: Шаг НЕ ПО ИМЕНИ: значение приходит из ОБЁРТКИ, чьи привязки ось ищет своей
#: отдельной петлёй. Форма взята с живого кода — `s2_lp_stable.py:163`.
WRAPPER_HOP = """
    RATE = 2.0

    def _scaled(x):
        return x * RATE

    def view(y):
        return {"scaled": _scaled(y)}
"""

#: Выражение ГЛУБЖЕ предела оси: ответ есть, но обход до него не доходит и
#: возвращает `None`, то есть говорит «арифметики нет». Площадка пропадает из
#: населения МОЛЧА — ровно тот третий исход, про который спросил заказ.
DEEPER_THAN_THE_LIMIT = (
    "LIMIT = 5\n\n"
    "def view(x):\n"
    "    return {\"gap\": " + "-(" * 20 + "LIMIT - x" + ")" * 20 + "}\n")

#: Цепочка ДЛИННЕЕ предела раундов: девять шагов при пределе восемь. Петля
#: кончается исчерпанным пределом, и последнее имя остаётся без рода — то же
#: молчание, что у предела глубины, но от другой двери.
LONGER_THAN_THE_ROUNDS = ("C = 5\n" + "a1 = C - C\n"
                          + "".join(f"a{i} = a{i - 1} + a{i - 1}\n"
                                    for i in range(2, 10))
                          + "\ndef view():\n    return {\"f\": a9}\n")


class TheStepsFromTheConstantToTheFieldAreCounted(unittest.TestCase):
    """Заказ G697 п. 3 — СКОЛЬКО ШАГОВ лежит между постоянной и полем.

    Мера — подстановка в дверь самой оси (``rounds=k``), а не второй разбор
    цепочки: при каком ``k`` ответ ПОЯВЛЯЕТСЯ, столько шагов в кратчайшей
    цепочке и есть. Один раунд петли добавляет ровно один шаг по имени.
    """

    def _rows(self, source: str):
        sites, _consts, why = mco.module_sites(source)
        self.assertEqual(why, "")
        rows, reason = mco.module_chain(source, sites)
        return rows, reason

    def test_one_hop_through_a_name_is_one_step(self):
        rows, reason = self._rows(_src(TRANSITIVE))
        self.assertEqual(reason, "")
        self.assertEqual([(r.field, r.steps) for r in rows], [("span", 1)])

    def test_two_hops_through_names_are_two_steps(self):
        """Положительный контроль ДЛИНЫ: сцена, где шагов заведомо два."""
        rows, reason = self._rows(_src(TWO_HOPS))
        self.assertEqual(reason, "")
        self.assertEqual([(r.field, r.steps) for r in rows], [("span", 2)])

    def test_a_step_through_a_wrapper_is_not_a_step_by_name(self):
        """``steps == 0`` — не «шагов нет», а шаг НЕ ПО ИМЕНИ (обёртка)."""
        rows, reason = self._rows(_src(WRAPPER_HOP))
        self.assertEqual(reason, "")
        self.assertEqual([(r.field, r.steps) for r in rows], [("scaled", 0)])

    def test_a_direct_site_has_no_chain_to_measure(self):
        """Отрицательная сторона: постоянная в самом выражении цепочки не имеет."""
        rows, reason = self._rows(_src(DIRECT))
        self.assertEqual((rows, reason), ([], ""),
                         "«мерить нечего» не есть третий исход")

    def test_a_forged_site_is_the_THIRD_outcome_not_zero_steps(self):
        """Площадки, о которой ось молчит, шагов нет — и это НЕ ноль.

        Единственный путь к этому исходу — спросить о площадке, которой нет:
        площадка, найденная прибором, по построению отвечает при полном
        пределе. Контроль нужен затем, чтобы ``steps=None`` не оказался
        недостижимой веткой, которую никто никогда не проверял.
        """
        forged = mco.Site(module="", line=999, field="нет-такого", how="",
                          consts=())
        rows, reason = mco.module_chain(_src(TRANSITIVE), [forged])
        self.assertEqual(reason, "")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].steps, "ноль шагов и НЕТ ответа — разные вещи")
        self.assertIn("полном пределе", rows[0].reason)

    def test_an_unparsable_module_refuses_the_chain_with_a_named_reason(self):
        rows, reason = mco.module_chain("def (:", [])
        self.assertEqual(rows, [])
        self.assertIn("не разобрано", reason)

    def test_the_census_prints_the_spread_not_an_average(self):
        """Заказ спросил «сколько шагов в КАЖДОМ случае» — среднее не ответ."""
        doc = mco.tally(None, None, _tree(**{"spa_core/a.py": TRANSITIVE,
                                             "spa_core/b.py": TWO_HOPS,
                                             "spa_core/c.py": WRAPPER_HOP}))
        chain = doc["chain"]
        self.assertEqual(chain["steps_histogram"], {"0": 1, "1": 1, "2": 1})
        self.assertEqual(chain["max_steps"], 2)
        self.assertEqual(chain["without_name_hop"], 1)
        self.assertEqual(chain["steps_unmeasured"], 0)

    def test_the_report_prints_the_steps_next_to_the_population(self):
        """Цена предела и длина цепочки нужны ТАМ, где читатель видит население."""
        doc = mco.tally(None, None, _tree(**{"spa_core/a.py": TWO_HOPS}))
        lines = mco.report(doc)
        pop = [i for i, l in enumerate(lines) if l.startswith("  население ")]
        steps = [i for i, l in enumerate(lines) if "ШАГИ до поля" in l]
        self.assertTrue(pop and steps, lines)
        self.assertLess(steps[0] - pop[0], 4,
                        "строка шагов обязана стоять РЯДОМ с населением")

    def test_an_old_format_document_says_the_steps_are_unmeasured(self):
        lines = mco.chain_report({"population": 3})
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНЫ", lines[0])
        self.assertIn("СТАРОГО ОБРАЗЦА", lines[0])

    def test_a_tree_without_a_transitive_site_says_zero_not_unmeasured(self):
        doc = mco.tally(None, None, _tree(**{"spa_core/p.py": DIRECT}))
        self.assertEqual(doc["chain"]["rows"], [])
        self.assertEqual(doc["chain"]["unmeasured"], {})
        self.assertTrue(any("равно нулю" in l
                            for l in mco.chain_report(doc)),
                        "«мерить нечего» обязано отличаться от «не измерено»")


class TheAxisOwnLimitsHaveAMeasuredPrice(unittest.TestCase):
    """Заказ G697 п. 3 — ПРЕДЕЛ, в который упёрся обход, есть свой третий исход.

    Оба предела оси возвращают ``None``, то есть говорят «арифметики нет» там,
    где верный ответ «НЕ ИЗМЕРЕНО». Пока цены нет, население класса есть
    нижняя граница неизвестной глубины — ровно та болезнь, которую ADR-702
    вылечил у двери затенения. Двери РАЗВЕДЕНЫ: глубина спуска в одном
    выражении и длина цепочки между именами — разные вопросы.
    """

    def test_a_shallow_converged_module_pays_nothing(self):
        cost = mco.axis_limit_cost(_src(TRANSITIVE))
        self.assertFalse(cost.depth_door)
        self.assertFalse(cost.rounds_door)
        self.assertEqual((cost.depth_hidden, cost.rounds_hidden), ((), ()))
        self.assertEqual(cost.reason, "", "третий исход тут не наступал")

    def test_the_shortcut_is_sound_where_neither_door_fired(self):
        """Контроль СОКРАЩЕНИЯ: без сработавшей двери ответ обязан быть тот же.

        Второй прогон делается только там, где дверь сработала. Без этого
        контроля сокращение держалось бы на рассуждении, а не на тесте.
        """
        for name, source in (("TRANSITIVE", TRANSITIVE), ("TWO_HOPS", TWO_HOPS),
                             ("DIRECT", DIRECT), ("WRAPPER_HOP", WRAPPER_HOP)):
            with self.subTest(scene=name):
                tree = ast.parse(_src(source))
                consts = mco.module_constants(tree)
                clone, _done = mco.substituted(tree, consts)
                tight = mco._axis_answers(clone)
                loose = mco._axis_answers(clone, depth=mco._DEPTH_HEADROOM)
                wide = mco._axis_answers(clone, rounds=64)
                self.assertEqual(tight, loose)
                self.assertEqual(tight, wide)

    def test_the_depth_limit_HIDES_a_site_and_the_price_names_it(self):
        """Положительный контроль: предел глубины съедает настоящую площадку."""
        sites, _consts, why = mco.module_sites(DEEPER_THAN_THE_LIMIT)
        self.assertEqual(why, "")
        self.assertEqual(sites, [],
                         "сцена построена так, что ось МОЛЧИТ — в этом и вред")
        cost = mco.axis_limit_cost(DEEPER_THAN_THE_LIMIT)
        self.assertTrue(cost.depth_door)
        self.assertEqual(cost.depth_hidden, ("gap:4",))
        self.assertEqual(cost.rounds_hidden, (),
                         "вторая дверь тут не при чём — числа РАЗНЫЕ")

    def test_the_rounds_limit_HIDES_a_site_and_the_price_names_it(self):
        """Положительный контроль ВТОРОЙ двери: цепочка длиннее предела раундов."""
        sites, _consts, why = mco.module_sites(LONGER_THAN_THE_ROUNDS)
        self.assertEqual(why, "")
        self.assertEqual(sites, [], "девять шагов при пределе восемь ⇒ молчание")
        cost = mco.axis_limit_cost(LONGER_THAN_THE_ROUNDS)
        self.assertTrue(cost.rounds_door)
        self.assertEqual(len(cost.rounds_hidden), 1, cost.rounds_hidden)
        self.assertTrue(cost.rounds_hidden[0].startswith("f:"),
                        cost.rounds_hidden)
        self.assertEqual(cost.depth_hidden, ())

    def test_the_two_doors_are_separate_numbers_in_the_census(self):
        doc = mco.tally(None, None, _tree(**{
            "spa_core/deep.py": DEEPER_THAN_THE_LIMIT,
            "spa_core/long.py": LONGER_THAN_THE_ROUNDS}))
        lim = doc["axis_limits"]
        self.assertEqual(lim["depth_doors_fired"], 1)
        self.assertEqual(lim["rounds_doors_fired"], 1)
        self.assertEqual(lim["depth_hidden_sites"], 1)
        self.assertEqual(lim["rounds_hidden_sites"], 1)
        self.assertEqual(lim["depth_hidden_named"], ["spa_core/deep.py:gap:4"])
        self.assertTrue(lim["rounds_hidden_named"][0]
                        .startswith("spa_core/long.py:f:"),
                        lim["rounds_hidden_named"])

    def test_the_margin_is_a_NUMBER_not_the_word_enough(self):
        """Запас печатается числом: «хватает» верно в обе стороны сразу."""
        doc = mco.tally(None, None, _tree(**{"spa_core/a.py": TWO_HOPS}))
        lim = doc["axis_limits"]
        self.assertEqual(lim["depth_limit"], field_kind.DEPTH_LIMIT)
        self.assertEqual(lim["rounds_limit"], field_kind.DERIVE_ROUNDS)
        self.assertEqual(lim["depth_margin"],
                         field_kind.DEPTH_LIMIT - lim["deepest_value_expression"])
        self.assertEqual(lim["longest_chain"], 2)
        self.assertEqual(lim["rounds_margin"], field_kind.DERIVE_ROUNDS - 2)
        self.assertTrue(lim["deepest_named"].startswith("spa_core/a.py:"),
                        lim["deepest_named"])

    def test_a_module_outside_the_operand_is_its_own_number(self):
        """«Не спрашивали» и «спросили и ноль» обязаны быть различимы (инв. #17)."""
        doc = mco.tally(None, None, _tree(**{"spa_core/a.py": TRANSITIVE,
                                             "spa_core/b.py": ALREADY_SEEN}))
        lim = doc["axis_limits"]
        self.assertEqual(lim["modules_measured"], 1)
        self.assertEqual(lim["modules_outside_the_operand"], 1,
                         "модуль без постоянных операнда класса не несёт")

    def test_a_finite_headroom_that_runs_out_is_the_THIRD_outcome(self):
        """Нехватка запаса молчит так же, как сам предел — значит это отказ.

        Выдать её за «спрятанных площадок столько» значило бы повторить ровно
        тот дефект, который прибор мерит.
        """
        # Глубина берётся ЧУТЬ выше запаса, а не вдвое: окно этого исхода
        # узкое с ДВУХ сторон. Сверху его режет не прибор, а сам Python —
        # разборщик отказывает примерно на 200 вложенных скобках, а
        # `copy.deepcopy` в :func:`substituted` падает `RecursionError`
        # около 250 уровней (измерено этим же контролем, вынесено в заказ
        # G703 п. 5). Поэтому сцена строится унарными минусами БЕЗ скобок и
        # держится в окне 145…240.
        over = field_kind.DEPTH_LIMIT - mco._DEPTH_HEADROOM + 20
        source = ("LIMIT = 5\n\ndef view(x):\n    return {\"gap\": "
                  + "- " * over + "(LIMIT - x)}\n")
        cost = mco.axis_limit_cost(source)
        self.assertTrue(cost.depth_door)
        self.assertEqual(cost.depth_hidden, (), "ноль тут был бы ложью")
        self.assertIn("запаса по глубине не хватает", cost.reason)

    def test_an_unparsable_module_refuses_the_price_with_a_named_reason(self):
        cost = mco.axis_limit_cost("def (:")
        self.assertEqual((cost.depth_hidden, cost.rounds_hidden), ((), ()))
        self.assertIn("не разобрано", cost.reason)

    def test_an_old_format_document_says_the_price_is_unmeasured(self):
        lines = mco.limit_report({"population": 3})
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНА", lines[0])
        self.assertIn("СТАРОГО ОБРАЗЦА", lines[0])

    def test_the_report_names_both_limits_and_both_hidden_sites(self):
        doc = mco.tally(None, None, _tree(**{
            "spa_core/deep.py": DEEPER_THAN_THE_LIMIT,
            "spa_core/long.py": LONGER_THAN_THE_ROUNDS}))
        lines = "\n".join(mco.limit_report(doc))
        for needle in ("ПРЕДЕЛ ГЛУБИНЫ", "ПРЕДЕЛ РАУНДОВ",
                       "спрятано ГЛУБИНОЙ", "спрятано РАУНДАМИ"):
            self.assertTrue(needle in lines, (needle, lines))

    def test_the_price_unmeasured_module_is_named_in_the_report(self):
        lines = mco.limit_report({"axis_limits": {
            "depth_limit": 16, "deepest_value_expression": 3,
            "deepest_named": "spa_core/a.py:1", "depth_margin": 13,
            "depth_doors_fired": 0, "depth_hidden_sites": 0,
            "depth_hidden_named": [], "rounds_limit": 8, "longest_chain": 1,
            "rounds_margin": 7, "rounds_doors_fired": 0,
            "rounds_hidden_sites": 0, "rounds_hidden_named": [],
            "modules_measured": 1, "modules_outside_the_operand": 0,
            "unmeasured": {"spa_core/x.py": "не разобрано: SyntaxError"}}})
        self.assertTrue(any("[ПРЕДЕЛЫ НЕ ИЗМЕРЕНЫ] spa_core/x.py" in l
                            for l in lines), lines)


class TheAxisLimitsAreDeclaredInputs(unittest.TestCase):
    """Оба предела оси объявлены ИМЕНАМИ и ВХОДАМИ, а петля живёт в одном доме.

    Без этого цену предела пришлось бы мерить вторым разбором правила, а
    второй поиск предмета, уже раскрытого соседом, РАСХОДИТСЯ (урок #820).
    """

    def test_the_wrapper_returns_exactly_what_the_single_home_returns(self):
        tree = ast.parse(_src(TWO_HOPS))
        outer = field_kind._Scope(frozenset(), field_kind.arith_wrappers(tree))
        got = field_kind.scope_derived(tree, outer, field_kind.arith_derivation)
        same, used, converged = field_kind.scope_derived_steps(
            tree, outer, field_kind.arith_derivation)
        self.assertEqual(got, same, "вторая копия петли расходилась бы молча")
        self.assertTrue(converged)
        self.assertGreaterEqual(used, 1)

    def test_the_default_round_limit_is_the_named_constant(self):
        tree = ast.parse(_src(TWO_HOPS))
        wrappers = field_kind.arith_wrappers(tree)
        table = field_kind._scope_table(tree, field_kind.arith_derivation,
                                        wrappers)
        same, _conv = field_kind.scope_table_steps(
            tree, field_kind.arith_derivation, wrappers,
            rounds=field_kind.DERIVE_ROUNDS)
        self.assertEqual({k: v for k, v in table.items()},
                         {k: v for k, v in same.items()})

    def test_zero_rounds_means_NOT_converged_not_a_fixed_point(self):
        """Предел, исчерпанный на нулевом раунде, — не неподвижная точка."""
        tree = ast.parse(_src(TWO_HOPS))
        outer = field_kind._Scope(frozenset(), field_kind.arith_wrappers(tree))
        scope, used, converged = field_kind.scope_derived_steps(
            tree, outer, field_kind.arith_derivation, rounds=0)
        self.assertEqual(used, 0)
        self.assertFalse(converged)
        self.assertEqual(scope.derived, frozenset())

    def test_the_depth_limit_number_is_the_one_the_axis_uses(self):
        """Контроль ДВЕРИ: с одного шага до предела ответ есть, за ним — нет."""
        tree = ast.parse(DEEPER_THAN_THE_LIMIT)
        consts = mco.module_constants(tree)
        clone, _done = mco.substituted(tree, consts)
        scopes = field_kind._scope_table(clone, field_kind.arith_derivation,
                                         field_kind.arith_wrappers(clone))
        value = field_kind.field_assignments(clone)[0][1]
        scope = scopes[id(clone)]
        self.assertIsNone(field_kind.arith_derivation(value, scope, 0),
                          "сцена обязана УПИРАТЬСЯ в предел, иначе она не та")
        self.assertIsNotNone(field_kind.arith_derivation(
            value, scope, -field_kind.DEPTH_LIMIT))


class TheContractIsPinnedVerbatim(unittest.TestCase):
    """Имена ключей и вердиктов — ЛИТЕРАЛЫ (урок #832/#819).

    Сверка документа самого с собой переживает переименование ключа: мутант
    меняет обе половины вместе. Поэтому состав пришпилен словами.
    """

    # Пин РАСШИРЕН заказом G697 п. 1, и это усиление, а не ослабление: ключ
    # `shadow_cost` ДОБАВЛЕН, ни один прежний не убран и не переименован,
    # прежний набор целиком входит в новый, и пин остаётся РАВЕНСТВОМ —
    # лишний ключ по-прежнему краснеет (инв. #16, обоснование в теле
    # изменения; тот же порядок, которым ADR-700 расширял `_BUILT_BY_CALL`).
    DOC_KEYS = {"schema", "status", "reason", "files_parsed", "files_unmeasured",
                "modules_with_constants", "constants_seen", "sites",
                "population", "direct", "transitive", "candidate_hits",
                "candidate_sites", "identity_hits", "identity_sites",
                "candidate_denominator", "what_it_does_not_prove",
                "shadow_cost",
                # Пин РАСШИРЕН заказом G697 п. 3 тем же порядком: ключи
                # `chain` и `axis_limits` ДОБАВЛЕНЫ, ни один прежний не убран
                # и не переименован, пин остаётся РАВЕНСТВОМ (инв. #16).
                "chain", "axis_limits"}

    CHAIN_KEYS = {"rows", "steps_histogram", "max_steps", "without_name_hop",
                  "steps_unmeasured", "unmeasured"}

    CHAIN_ROW_KEYS = {"module", "line", "field", "how", "steps", "reason"}

    LIMIT_KEYS = {"depth_limit", "deepest_value_expression", "deepest_named",
                  "depth_margin", "depth_doors_fired", "depth_hidden_sites",
                  "depth_hidden_named", "rounds_limit", "longest_chain",
                  "rounds_margin", "rounds_doors_fired", "rounds_hidden_sites",
                  "rounds_hidden_named", "modules_measured",
                  "modules_outside_the_operand", "unmeasured"}

    COST_KEYS = {"dropped_constants", "dropped_modules", "lost_sites",
                 "lost_modules", "dropped_named", "lost_named", "unmeasured"}

    SITE_KEYS = {"module", "line", "field", "how", "consts"}

    def setUp(self):
        self.doc = mco.tally({"age_hours": 4}, ["id"],
                             _tree(**{"spa_core/p.py": DIRECT}))

    def test_the_document_carries_exactly_these_keys(self):
        self.assertEqual(set(self.doc), self.DOC_KEYS)

    def test_a_site_carries_exactly_these_keys(self):
        self.assertEqual(set(self.doc["sites"][0]), self.SITE_KEYS)

    def test_the_verdict_words_are_pinned(self):
        self.assertEqual(mco.EMPTY, "EMPTY")
        self.assertEqual(mco.POPULATED_NO_CANDIDATE, "POPULATED_NO_CANDIDATE")
        self.assertEqual(mco.POPULATED_CANDIDATE_TOUCHED,
                         "POPULATED_CANDIDATE_TOUCHED")
        self.assertEqual(mco.UNMEASURED, "UNMEASURED")
        self.assertEqual(mco.SCHEMA, "modular_constant_operand.v1")

    def test_the_roots_are_the_axis_own_roots(self):
        self.assertEqual(mco.DEFAULT_ROOTS, field_kind.DEFAULT_ROOTS,
                         "свой список каталогов мерил бы НЕ ТО население")

    def test_what_it_does_not_prove_is_not_empty(self):
        self.assertTrue(self.doc["what_it_does_not_prove"])
        self.assertTrue(any("не расширена" in s or "ЗАНИЖЕНО" in s
                            for s in self.doc["what_it_does_not_prove"]))

    def test_the_cost_block_carries_exactly_these_keys(self):
        self.assertEqual(set(self.doc["shadow_cost"]), self.COST_KEYS)

    def test_the_chain_block_carries_exactly_these_keys(self):
        self.assertEqual(set(self.doc["chain"]), self.CHAIN_KEYS)

    def test_the_limit_block_carries_exactly_these_keys(self):
        self.assertEqual(set(self.doc["axis_limits"]), self.LIMIT_KEYS)

    def test_a_chain_row_carries_exactly_these_keys(self):
        doc = mco.tally(None, None, _tree(**{"spa_core/a.py": TWO_HOPS}))
        self.assertEqual(set(doc["chain"]["rows"][0]), self.CHAIN_ROW_KEYS)

    def test_both_axis_limits_are_named_in_what_it_does_not_prove(self):
        """Заказ дословно: предел — СВОЙ третий исход, а не «арифметики нет»."""
        clause = [s for s in self.doc["what_it_does_not_prove"]
                  if "предел ГЛУБИНЫ" in s]
        self.assertEqual(len(clause), 1, clause)
        self.assertIn("предел РАУНДОВ", clause[0],
                      "вторая дверь обязана быть названа там же, где первая")
        self.assertIn("СЛАБЕЕ", clause[0],
                      "утверждения двух дверей разной силы, и это сказано")

    def test_the_limit_clause_says_unmeasured_on_an_old_format_document(self):
        clause = mco._limit_clause({})
        self.assertIn("НЕ ИЗМЕРЕНА", clause)
        self.assertNotIn("по СТРУКТУРЕ", clause)

    def test_the_chain_clause_says_what_the_spread_does_NOT_say(self):
        clause = mco._chain_clause(self.doc)
        self.assertIn("КРАТЧАЙШЕЙ", clause,
                      "расклад не говорит «других путей нет»")

    def test_the_caveat_carries_the_measured_number_not_only_prose(self):
        """Заказ G697 п. 1: «если выброшенных единицы — оговорку сократить до числа»."""
        clause = [s for s in self.doc["what_it_does_not_prove"]
                  if "ЗАНИЖЕНО" in s]
        self.assertEqual(len(clause), 1, clause)
        self.assertIn("ВЕЛИЧИНА промаха ИЗМЕРЕНА", clause[0],
                      "оговорка без числа была верна в обе стороны сразу")
        self.assertIn("нижняя граница", clause[0])

    def test_the_caveat_says_unmeasured_on_an_old_format_document(self):
        """Третий исход оговорки: раздела нет ⇒ «НЕ ИЗМЕРЕНА», не возврат к прозе."""
        clause = mco._cost_clause({})
        self.assertIn("НЕ ИЗМЕРЕНА", clause)
        self.assertNotIn("ВЕЛИЧИНА промаха ИЗМЕРЕНА", clause)

    def test_the_second_one_sidedness_is_named_in_what_it_does_not_prove(self):
        self.assertTrue(any("`global`" in s
                            for s in self.doc["what_it_does_not_prove"]),
                        "вторая дверь обязана быть названа там же, где первая")


class TheTestsAreExcludedLikeTheAxisDoes(unittest.TestCase):
    """Фикстура пишет постоянные в поля сознательно — она не население кода."""

    def test_a_test_file_is_not_counted(self):
        doc = mco.census(_tree(**{"spa_core/tests/test_x.py": DIRECT,
                                  "spa_core/p.py": LONE}))
        self.assertEqual(doc["population"], 0)
        self.assertEqual(doc["files_parsed"], 1)


class TheCliSeparatesThreeOutcomes(unittest.TestCase):
    """Код возврата различает «пусто», «есть население» и «НЕ ИЗМЕРЕНО»."""

    def _run(self, root: Path, *extra: str):
        return subprocess.run(
            [sys.executable, "-m", "spa_core.monitoring.modular_constant_operand",
             "--tree-root", str(root), *extra],
            cwd=str(_ROOT), capture_output=True, text=True)

    def test_empty_class_exits_zero(self):
        done = self._run(_tree(**{"spa_core/p.py": ALREADY_SEEN}))
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])

    def test_population_exits_one(self):
        done = self._run(_tree(**{"spa_core/p.py": DIRECT}))
        self.assertEqual(done.returncode, 1, done.stderr[-2000:])

    def test_unmeasured_exits_two(self):
        done = self._run(_tree(**{"spa_core/p.py": "def (:"}))
        self.assertEqual(done.returncode, 2, done.stderr[-2000:])

    def test_json_is_machine_readable(self):
        done = self._run(_tree(**{"spa_core/p.py": DIRECT}), "--json")
        doc = json.loads(done.stdout)
        self.assertEqual(doc["schema"], mco.SCHEMA)
        self.assertEqual(doc["population"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
