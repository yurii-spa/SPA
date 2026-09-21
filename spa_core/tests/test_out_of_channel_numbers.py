"""Числа вне канала объявления — заказ G59 п. 2.

ADR-436 назвал СЕМЬ мест в ``docs/**``, где стои́т та же форма, что у
объявленного канала правил, и сам же поставил вопрос: правила ли это. Заказ
спрашивает числами — сколько чисел там стои́т и сколько из них совпадает с
порогом, уже известным переписи. Нет совпадений ⇒ канал верно узок; есть ⇒
молчит не предел строки, а ГРАНИЦА канала.

Разница между «цифра равна» и «величина та же» здесь не придирка, а весь
предмет: замер на живом дереве дал 106 совпадений по голой величине на 269
чисел, и порог ``var_horizon_days = 7`` совпадал с номером строки таблицы.
Прибор, докладывающий 106, отвечает на вопрос «встречается ли такая цифра».

Сцены строятся из ``tmp_path``; пороги и маркеры берутся ВЫЧИСЛЕНИЕМ от
констант модуля — литерал здесь был бы второй копией правила, то есть ровно
тем классом, перепись которого этот модуль и есть. Литеральных дат и
литеральных pid в файле нет ни одного.
"""
import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import rule_second_copy_census as census
# Имена, существовавшие на `origin` ДО этой правки, берутся ввозом. Всё
# НОВОЕ зовётся через модуль (`census.X`): иначе ввоз падал бы на сборе, один
# ERROR подменил бы все вердикты файла, и контроль «что именно тут новое»
# перестал бы существовать.
from spa_core.monitoring.rule_second_copy_census import (
    CONSTITUTION_FILE, RISK_POLICY_MODULE, TABLE_CHANNEL_DOCS,
)

#: Порог сцены НЕ перепечатывается литералом там, где его можно вычислить:
#: сцена со своей копией числа молча переживёт смену числа в модуле.
DOC = "docs/scene_table.md"


def _hit(line, lines, text=DOC):
    """Попадание в форме, которую отдаёт координата формы (G58)."""
    return {"text": text, "line": line, "lines": lines}


class _Stand:
    """Дерево с обеими поверхностями решения и одним документом.

    Обе поверхности кладутся ВСЕГДА, а сцена ломает ровно ту, о которой
    спрашивает: стенд, у которого поверхности нет по построению, ответил бы
    «не измерено» на каждый вопрос и не проверял бы ничего.
    """

    def __init__(self, doc_body, *, policy=None, shelf=None):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        policy_path = self.root / RISK_POLICY_MODULE
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            "class RiskConfig:\n"
            "    BASE_CHAIN_CAP: float = 0.20\n"
            "    var_horizon_days: int = 7\n"
            "    min_cash_pct: float = 0.05\n"
            if policy is None else policy, encoding="utf-8")
        shelf_path = self.root / CONSTITUTION_FILE
        shelf_path.parent.mkdir(parents=True, exist_ok=True)
        shelf_path.write_text(
            json.dumps({"chain_caps": {"base_chain_pct": 20.0},
                        "min_cash_buffer_pct": 5.0})
            if shelf is None else shelf, encoding="utf-8")
        doc_path = self.root / DOC
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(doc_body, encoding="utf-8")
        self.lines = len(doc_body.splitlines())

    def measure(self, hits=None):
        return census.out_of_channel_numbers(
            self.root, _hit(1, self.lines) if hits is None else hits)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


def _stand(doc_body, **kw):
    return _Stand(doc_body, **kw)


def _one(rows):
    """Один hit на весь документ сцены."""
    return [{"text": DOC, "line": 1, "lines": rows}]


class EvidenceChannels(unittest.TestCase):
    """Каждый канал свидетельства отвечает на СВОЙ вопрос и не подменяет соседа."""

    def test_bare_equal_digit_is_not_a_finding(self):
        """Номер строки, равный порогу, находкой не является.

        Это вся причина, по которой координата существует: `var_horizon_days
        = 7` равно семёрке в любом тексте, и доклад «совпало» был бы ответом
        на вопрос о ЦИФРЕ.
        """
        body = "| # | что |\n|---|---|\n| 7 | седьмая строка таблицы |\n"
        with _stand(body) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_NARROW)
        self.assertEqual(doc["by_evidence"][census.EV_VALUE], 1)
        self.assertEqual(doc["named"], 0)

    def test_unit_without_a_name_does_not_decide(self):
        """Проценты красной команды порогом книги не являются.

        `peg 3 % + vol 5 %` — сценарий атаки; величина несёт единицу и всё
        равно не предъявлена как НАША. Канал единицы поэтому необходим, но
        не достаточен.
        """
        body = "| id | сцена |\n|---|---|\n| RT-1 | peg 3 % + vol 5 % |\n"
        with _stand(body) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_NARROW)
        self.assertGreaterEqual(doc["by_evidence"][census.EV_UNIT], 1)
        self.assertEqual(doc["named"], 0)

    def test_a_name_without_a_unit_gets_its_own_channel(self):
        """Имя без единицы вердикта не решает — и НЕ пропадает.

        Первая редакция координаты объявила «названными» пять голых `30` из
        строк про бумажный трек: у `min_paper_days_before_live` различающий
        токен ровно один. Выбросить такую пару молча значило бы потерять
        нижнюю границу ответа, поэтому у неё свой канал.
        """
        shelf = json.dumps({"min_cash_buffer_pct": 5.0})
        body = ("| id | что |\n|---|---|\n"
                "| A | min_cash_buffer_pct равен 5 без единицы |\n")
        with _stand(body, shelf=shelf) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["by_evidence"][census.EV_NAME_NO_UNIT], 1)
        self.assertEqual(doc["named"], 0)
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_NARROW)

    def test_name_and_unit_together_are_a_finding(self):
        """Имя И единица вместе — единственное достаточное свидетельство."""
        shelf = json.dumps({"min_cash_buffer_pct": 5.0})
        body = ("| id | что |\n|---|---|\n"
                "| A | min_cash_buffer_pct = 5 % |\n")
        with _stand(body, shelf=shelf) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_SILENT)
        self.assertEqual(doc["by_evidence"][census.EV_NAME_VERBATIM], 1)

    def test_generic_token_alone_names_nothing(self):
        """Слово `max` есть почти у каждого порога и не называет ни одного."""
        body = "| id | что |\n|---|---|\n| A | max 5 % чего-то своего |\n"
        with _stand(body) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["named"], 0)

    def test_a_pair_lands_in_exactly_one_channel(self):
        """Пара считается ОДИН раз — иначе доля названных росла бы сама.

        Сумма по каналам обязана равняться числу совпавших пар.
        """
        shelf = json.dumps({"min_cash_buffer_pct": 5.0})
        body = ("| id | что |\n|---|---|\n"
                "| A | min_cash_buffer_pct = 5 % |\n"
                "| B | седьмая строка, число 7 |\n")
        with _stand(body, shelf=shelf) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(sum(doc["by_evidence"].values()),
                         doc["matched_value"])
        self.assertEqual(len(doc["pairs"]), doc["matched_value"])


class BilingualNaming(unittest.TestCase):
    """Положительный контроль на настоящую находку 21.09.

    `docs/allocation_logic_explicit.md` держит третью копию `BASE_CHAIN_CAP`
    строкой «Base-цепочка | до 20 % … ADR-025». Латинский канал имени её не
    видит: документ написан по-русски, а имя — по-английски. Замер на живом
    дереве: с картой синонимов вердикт `SILENT`, без неё — `NARROW`, то есть
    одноязычный прибор ответил бы «канал верно узок» О СЕБЕ, а не о дереве.
    """

    #: Форма настоящей строки, ради которой канал и заведён.
    SCENE = ("| ID | Исключение | Правило |\n|---|---|---|\n"
             "| EXC-04 | Base-цепочка | до 20 % только после go-live |\n")

    def test_bilingual_channel_finds_the_third_copy(self):
        with _stand(self.SCENE) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_SILENT)
        self.assertEqual(doc["by_evidence"][census.EV_NAME_BILINGUAL], 1)
        self.assertEqual(doc["pairs"][0]["threshold"],
                         "shelf:chain_caps.base_chain_pct")

    def test_without_the_map_the_same_tree_reads_as_narrow(self):
        """Снятие карты обязано ПЕРЕВЕРНУТЬ вердикт, а не смягчить его.

        Контроль на само утверждение ADR: «ноль названных» без двуязычия есть
        свойство прибора. Если вердикт не меняется, утверждение выдумано.
        """
        saved = census._TOKEN_SYNONYMS
        census._TOKEN_SYNONYMS = {}
        try:
            with _stand(self.SCENE) as stand:
                doc = stand.measure(_one(stand.lines))
        finally:
            census._TOKEN_SYNONYMS = saved
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_NARROW)
        self.assertEqual(doc["named"], 0)

    def test_the_map_does_not_name_an_unrelated_row(self):
        """Карта синонимов не обязана красить всё подряд.

        Без этого контроля двуязычие было бы куплено ценой ложных пар, и
        `SILENT` стоял бы на любом русском тексте с процентом.
        """
        body = ("| ID | что |\n|---|---|\n"
                "| A | доходность пула 20 % за период |\n")
        with _stand(body) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["named"], 0)


class PercentReading(unittest.TestCase):
    """Один порог живёт у двух поверхностей в РАЗНЫХ единицах."""

    def test_percent_is_read_as_a_fraction_too(self):
        """`3 %` в документе против `0.03` у RiskPolicy — одна величина.

        Сверка по одной лишь написанной величине связала бы документ только с
        витриной, и ответ «чей это порог» решала бы единица автора.
        """
        policy = ("class RiskConfig:\n"
                  "    max_single_position_drawdown: float = 0.03\n")
        shelf = json.dumps({"unrelated_pct": 999.0})
        body = ("| id | что |\n|---|---|\n"
                "| A | max_single_position_drawdown 3 % |\n")
        with _stand(body, policy=policy, shelf=shelf) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_SILENT)
        self.assertEqual(doc["by_reading"][census.READ_AS_FRACTION], 1)

    def test_the_reading_travels_with_the_pair(self):
        """«20 % = 0.20» никогда не выдаётся за «в документе стои́т 0.20»."""
        policy = "class RiskConfig:\n    BASE_CHAIN_CAP: float = 0.20\n"
        shelf = json.dumps({"unrelated_pct": 999.0})
        body = ("| id | что |\n|---|---|\n"
                "| A | BASE_CHAIN_CAP 20 % |\n")
        with _stand(body, policy=policy, shelf=shelf) as stand:
            doc = stand.measure(_one(stand.lines))
        pair = doc["pairs"][0]
        self.assertEqual(pair["reading"], census.READ_AS_FRACTION)
        self.assertIn("20", pair["number"])

    def test_a_bare_number_is_not_read_as_a_fraction(self):
        """Доля без процента — выдумка: прочтений у голого числа одно."""
        policy = "class RiskConfig:\n    some_share: float = 0.20\n"
        shelf = json.dumps({"unrelated_pct": 999.0})
        body = "| id | что |\n|---|---|\n| A | some_share 20 |\n"
        with _stand(body, policy=policy, shelf=shelf) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["by_reading"][census.READ_AS_FRACTION], 0)


class DateFragments(unittest.TestCase):
    """Обломок ISO-даты числом не является."""

    def test_an_iso_date_contributes_no_numbers(self):
        body = "| id | что |\n|---|---|\n| A | доставлено 2026-07-11 |\n"
        with _stand(body) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["numbers_total"], 0)

    def test_a_number_beside_a_date_still_counts(self):
        """Отсев обязан снять ДАТУ, а не строку с датой.

        Без этого контроля починка «не считать даты» тихо ослепила бы
        координату на каждой строке журнала доставок.
        """
        body = "| id | что |\n|---|---|\n| A | 2026-07-11: порог 5 % |\n"
        with _stand(body) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["numbers_total"], 1)


class ThirdOutcome(unittest.TestCase):
    """Инв. #17: «не измерено» никогда не выдаётся за «совпадений нет»."""

    def test_risk_policy_unreadable_is_unmeasured_not_narrow(self):
        """Без старшей поверхности ответ НЕ «канал верно узок».

        Иначе агент получил бы право чинить то, что чинить не вправе:
        `NARROW` читается как «в `docs/**` порогов нет».
        """
        with _stand("| a |\n|---|\n| 5 % |\n",
                    policy="class RiskConfig:\n    (((\n") as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_UNMEASURED)
        self.assertIn(RISK_POLICY_MODULE, doc["reason"])
        self.assertIsNone(doc["numbers_total"])

    def test_shelf_unreadable_is_a_named_blindness(self):
        """Витрина — вторая поверхность; её потеря сужает ответ до нижней границы."""
        with _stand("| a |\n|---|\n| 5 % |\n", shelf="{не json") as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertNotEqual(doc["verdict"], census.OUT_CHANNEL_UNMEASURED)
        self.assertTrue(any(CONSTITUTION_FILE in b for b in doc["blind"]),
                        doc["blind"])

    def test_an_empty_shelf_without_a_reason_is_not_a_blindness(self):
        """Витрина без чисел — законный ответ, и объявлять слепоту тут не о чем.

        Обратная сторона предыдущего контроля: без неё ветка слепоты кричала
        бы всегда и перестала бы что-либо значить.
        """
        with _stand("| a |\n|---|\n| 5 % |\n", shelf="{}") as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertFalse([b for b in doc["blind"]
                          if CONSTITUTION_FILE in b], doc["blind"])

    def test_an_unreadable_text_is_named_not_counted_as_clean(self):
        with _stand("| a |\n|---|\n| 5 % |\n") as stand:
            doc = stand.measure([{"text": "docs/net.md", "line": 1,
                                  "lines": 3}])
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_UNMEASURED)
        self.assertEqual([r["text"] for r in doc["unreadable"]],
                         ["docs/net.md"])

    def test_one_unreadable_among_readable_does_not_hide_the_rest(self):
        """Часть прочитана ⇒ вердикт есть, но потеря НАЗВАНА."""
        with _stand("| a |\n|---|\n| min_cash_pct 5 % |\n") as stand:
            doc = stand.measure([{"text": DOC, "line": 1, "lines": 3},
                                 {"text": "docs/net.md", "line": 1,
                                  "lines": 3}])
        self.assertEqual(doc["tables_read"], 1)
        self.assertEqual(doc["tables"], 2)
        self.assertEqual(len(doc["unreadable"]), 1)

    def test_no_hits_is_nothing_to_compare_not_narrow(self):
        """Ноль мест вне канала и «там нет порогов» — разные ответы."""
        with _stand("| a |\n|---|\n| 5 % |\n") as stand:
            doc = stand.measure([])
        self.assertEqual(doc["verdict"], census.OUT_CHANNEL_NOTHING)

    def test_enrichment_is_either_measured_or_explained(self):
        """Частота ошибки — число ЛИБО названная причина, третьего нет."""
        with _stand("| a |\n|---|\n| строка без чисел |\n") as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertTrue(doc["enrichment"] is not None
                        or doc["enrichment_reason"],
                        "ни числа, ни причины — это и есть «не измерено», "
                        "выданное за ответ")

    def test_a_zero_denominator_is_a_reason_and_never_a_number(self):
        """Обогащение НЕ выдумывается, когда делить не на что.

        Дыру нашла батарея: слабая проверка «число ЛИБО причина» пропускала
        подстановку `enrichment = 1.0` там, где не названо ни одной строки —
        то есть фальшивое «имя не различает ничего», сочинённое на нулевом
        знаменателе. Это инв. #17 наизнанку: не измерено, выданное за ответ.
        """
        body = ("| # | что |\n|---|---|\n"
                "| 7 | седьмая строка, имён тут нет |\n")
        with _stand(body) as stand:
            doc = stand.measure(_one(stand.lines))
        self.assertEqual(doc["named_rows"], 0)
        self.assertGreater(doc["matched_value"], 0)
        self.assertIsNone(doc["enrichment"])
        self.assertTrue(doc["enrichment_reason"])


class Wiring(unittest.TestCase):
    """Проводка проверяется ФОРМОЙ ВЫЗОВА, а не совпадением подстроки.

    Тест по подстроке пережил бы любое расцепление: имя в файле осталось бы,
    а вызова не было бы.
    """

    @staticmethod
    def _module_tree():
        path = (Path(census.__file__))
        return ast.parse(path.read_text(encoding="utf-8"))

    @staticmethod
    def _function(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"функции {name} в модуле нет")

    def test_measure_calls_the_coordinate(self):
        body = self._function(self._module_tree(), "measure")
        calls = [n for n in ast.walk(body)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "out_of_channel_numbers"]
        self.assertEqual(len(calls), 1,
                         "координата обязана зваться из measure() РОВНО раз")

    def test_measure_publishes_the_key(self):
        doc_keys = [n.value for n in ast.walk(
            self._function(self._module_tree(), "measure"))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertIn("out_of_channel_numbers", doc_keys)

    def test_report_reads_the_key_through_observed(self):
        """Ключ читается `observed`, а не `.get(...) or {}`.

        Именно `or {}` у соседа превращал отсутствие ключа в пустую долю:
        цикл не печатал ни строки, и «не измерено» становилось неотличимо от
        «нечего показать».
        """
        body = self._function(self._module_tree(), "report")
        ok = [n for n in ast.walk(body)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "observed"
              and any(isinstance(a, ast.Constant)
                      and a.value == "out_of_channel_numbers"
                      for a in n.args)]
        self.assertTrue(ok, "секция отчёта читает ключ не через observed()")

    def test_measure_feeds_the_docs_channel(self):
        """Координате подаётся контроль `docs/**`, а не объявленный канал.

        Подать сюда канал правил значило бы ответить на другой вопрос: те
        таблицы читают КАК правила, и молчания границы там нет по построению.
        """
        body = self._function(self._module_tree(), "measure")
        call = [n for n in ast.walk(body)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "out_of_channel_numbers"][0]
        names = [n.value for n in ast.walk(call)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertIn("long_line_hits", names)
        # Имя канала — Name-узел, а не строковый литерал: первая редакция
        # спрашивала только про строки, и подмена `TABLE_CHANNEL_DOCS` на
        # `TABLE_CHANNEL_RULES` пережила батарею. Проверять надо ТО имя,
        # которым канал назван, иначе координата ответила бы на чужой вопрос.
        used = {n.id for n in ast.walk(call) if isinstance(n, ast.Name)}
        self.assertIn("TABLE_CHANNEL_DOCS", used)
        self.assertNotIn("TABLE_CHANNEL_RULES", used)


class ReportSection(unittest.TestCase):
    """Печать обязана звучать при ЛЮБОМ исходе — и не зависеть от соседа."""

    def test_section_prints_without_the_form_coordinate(self):
        """Секция вынесена ЗА блок формы.

        Вложенная внутрь его `else`, она молчала бы у каждого дерева, где
        координата формы не измерена, — ровно ошибка размещения, которую
        соседний сторож поймал у #655.
        """
        lines = census.report({"counts": {}, "rows": [],
                               "out_of_channel_numbers": {
                                   "verdict": census.OUT_CHANNEL_NARROW,
                                   "reason": "причина сцены",
                                   "numbers_total": 3, "matched_value": 1,
                                   "named": 0, "tables": 1, "tables_read": 1,
                                   "by_evidence": {}, "by_reading": {},
                                   "enrichment": None,
                                   "enrichment_reason": "сцена",
                                   "pairs": [], "unreadable": [],
                                   "blind": []}})
        self.assertTrue([ln for ln in lines if "ЧИСЛА ВНЕ КАНАЛА" in ln],
                        "секция не напечатана без координаты формы")

    def test_a_missing_coordinate_is_printed_as_unmeasured(self):
        lines = census.report({"counts": {}, "rows": []})
        self.assertTrue([ln for ln in lines
                         if "ЧИСЛА ВНЕ КАНАЛА" in ln and "НЕ ИЗМЕРЕН" in ln],
                        lines[-6:])

    def test_a_named_pair_reaches_the_printed_report(self):
        """Находка обязана доехать до глаз, а не остаться в артефакте."""
        lines = census.report({"counts": {}, "rows": [],
                               "out_of_channel_numbers": {
                                   "verdict": census.OUT_CHANNEL_SILENT,
                                   "reason": "причина сцены",
                                   "numbers_total": 3, "matched_value": 1,
                                   "named": 1, "tables": 1, "tables_read": 1,
                                   "by_evidence": {}, "by_reading": {},
                                   "enrichment": 2.0,
                                   "enrichment_reason": None,
                                   "pairs": [{
                                       "text": DOC, "line": 7,
                                       "number": "20%",
                                       "threshold": "shelf:chain_caps.base_chain_pct",
                                       "evidence": census.EV_NAME_BILINGUAL,
                                       "reading": census.READ_AS_WRITTEN,
                                       "quote": "строка сцены"}],
                                   "unreadable": [], "blind": []}})
        printed = [ln for ln in lines if "ЧИСЛА · НАЗВАНО" in ln]
        self.assertEqual(len(printed), 1, lines)
        self.assertIn("chain_caps.base_chain_pct", printed[0])

    def test_an_unnamed_pair_does_not_reach_the_named_section(self):
        """Обратная сторона: шум прибора в находки не попадает."""
        lines = census.report({"counts": {}, "rows": [],
                               "out_of_channel_numbers": {
                                   "verdict": census.OUT_CHANNEL_NARROW,
                                   "reason": "причина сцены",
                                   "numbers_total": 3, "matched_value": 1,
                                   "named": 0, "tables": 1, "tables_read": 1,
                                   "by_evidence": {}, "by_reading": {},
                                   "enrichment": None,
                                   "enrichment_reason": "сцена",
                                   "pairs": [{
                                       "text": DOC, "line": 7, "number": "7",
                                       "threshold": "RiskPolicy:var_horizon_days",
                                       "evidence": census.EV_VALUE,
                                       "reading": census.READ_AS_WRITTEN,
                                       "quote": "седьмая строка"}],
                                   "unreadable": [], "blind": []}})
        self.assertFalse([ln for ln in lines if "ЧИСЛА · НАЗВАНО" in ln])


class LiveTree(unittest.TestCase):
    """Вердикт живого дерева закрепляется СВОЙСТВОМ, а не литералом.

    Число пар меняется с каждой правкой документа, и тест, пришпиливший
    «одна», краснел бы от чужого абзаца.
    """

    @classmethod
    def setUpClass(cls):
        root = Path(census.__file__).resolve().parents[2]
        form = census.table_form_census(root)
        hits = (form.get("channels", {}).get(TABLE_CHANNEL_DOCS, {})
                .get("long_line_hits") or [])
        cls.doc = census.out_of_channel_numbers(root, hits)

    def test_the_run_is_not_hollow(self):
        self.assertGreater(self.doc["tables_read"], 0)
        self.assertGreater(self.doc["numbers_total"], 0)

    def test_bare_value_noise_dominates_the_named_channel(self):
        """Свойство, ради которого координата и написана.

        Голых совпадений по величине на живом дереве многократно больше, чем
        названных пар; прибор, докладывающий первое число, отвечает на
        вопрос о цифре, а не о пороге.
        """
        self.assertGreater(self.doc["by_evidence"][census.EV_VALUE],
                           self.doc["named"])

    def test_every_named_pair_bears_a_unit(self):
        for pair in self.doc["pairs"]:
            if pair["evidence"] in census._EV_NAMED:
                self.assertTrue(
                    pair["dollar"] or any(ch in pair["number"]
                                          for ch in "%дчd"),
                    pair)

    def test_the_verdict_follows_the_named_count(self):
        expected = (census.OUT_CHANNEL_SILENT if self.doc["named"]
                    else census.OUT_CHANNEL_NARROW)
        self.assertEqual(self.doc["verdict"], expected)


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
