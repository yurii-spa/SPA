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
                "shadow_cost"}

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
