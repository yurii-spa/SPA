"""Какую БАЗУ берёт читатель переписи и каким ИМЕНЕМ её зовёт — заказ **G65 п. 1**.

ADR-442 измерил расхождение у САМОЙ базы: пары, доходящие до книг, и строки с
меткой ``GENUINE`` — разные множества (4 и 4, пересечение 3). Он прямо сказал,
чего не спрашивал: КТО из читателей переписи какую базу берёт. Заказ G65 п. 1
требует спросить поимённо трёх — секцию отчёта, мост находок, шаг 0-офис, — и
назвать того, кто берёт одну базу, а зовёт её именем другой: это вторая копия
правила, только снаружи прибора, в словаре.

Тесты держат ровно это:

* что ИМЯ числа берётся из текста ВПЛОТНУЮ к нему, а не из всей строки;
* что многозначность токена выведена из ЗАМЕРА смежности, а не из объявленной
  таблицы — объявленный двум базам токен, вставший рядом с одной, находкой НЕ
  становится;
* что координатой значения считается ПОСЛЕДНЯЯ применённая, а не любая в цепи
  (иначе каждое поле каждой пары приписалось бы базе книг — «контейнер
  привязкой не является», `.claude/rules/deployment.md`);
* что чужое чтение (соседская перепись со своим ключом ``pairs``) в замер НЕ
  попадает — иначе прибор выдумал бы находку ровно того класса, что ищет;
* что каждое отсутствие осталось ОТДЕЛЬНЫМ значением (инв. #17): нет файла,
  не разобран, нет области, делегирует, не читает ничего — пять разных
  исходов, и ни один не ноль.

Каждый тест — обратная сторона: сцена строится так, чтобы утверждение можно
было ОПРОВЕРГНУТЬ. Литеральных дат и литеральных pid здесь нет: мера не
спрашивает ни часов, ни ОС.
"""

import ast
import unittest
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as mod
from spa_core.monitoring.rule_second_copy_census import (
    BASE_BOOKS_PAIRS,
    BASE_GENUINE,
    BASE_GUARD_EXECUTOR,
    CENSUS_BASES,
    CENSUS_CONSUMERS,
    CONSUMER_DELEGATES,
    CONSUMER_NO_READ,
    CONSUMER_READS,
    CONSUMER_UNMEASURED,
    NAMING_AMBIGUOUS,
    NAMING_CROSS,
    NAMING_SINGLE,
    NAMING_UNNAMED,
    NAME_WINDOW_CHARS,
    PRODUCER,
    consumer_base_naming,
    report,
)

_ROOT = Path(__file__).resolve().parents[2]

#: Пути реестра — читаются из него самого, а не переписываются сюда: вторая
#: копия этого списка была бы ровно тем дефектом, который перепись и ищет.
_PATH_OF = {spec["key"]: spec["path"] for spec in CENSUS_CONSUMERS}


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _scene(root: Path, *, report_src: str = "", bridge_src: str = "",
           office_src: str = "") -> dict:
    """Дерево из трёх объявленных читателей и замер по нему."""
    _write(root, _PATH_OF["report_section"], report_src)
    _write(root, _PATH_OF["findings_bridge"], bridge_src)
    _write(root, _PATH_OF["office_step"], office_src)
    return consumer_base_naming(root)


def _by_key(doc: dict, key: str) -> dict:
    for consumer in doc["consumers"]:
        if consumer["key"] == key:
            return consumer
    raise AssertionError(f"читателя {key!r} нет в замере")


def _verdicts(consumer: dict):
    return [item["verdict"] for item in (consumer.get("numbers") or [])]


# --- сцены-исходники ------------------------------------------------------
#
# Сцена пишется как настоящий модуль: прибор разбирает AST, и подделать его
# строкой-заглушкой нельзя — это и есть смысл положительного контроля.

_NAMES_ITS_OWN_BASE = '''
def report(doc):
    counts = doc.get("counts")
    return [f"две копии {counts.get('two_copies')} шт."]
'''

_NAMES_ANOTHER_BASE = '''
def report(doc):
    sides = doc.get("sides")
    return [f"две копии {sides.get('GENUINE')} шт."]
'''

_ONE_TOKEN_TWO_BASES = '''
def report(doc):
    counts = doc.get("counts")
    today = doc.get("pairs_today")
    return [f"пар {counts.get('two_copies')} шт.",
            f"пар {today.get('pairs')} шт."]
'''

_NUMBER_WITHOUT_A_NAME = '''
def report(doc):
    counts = doc.get("counts")
    return [f"[УЧЁТ] {counts.get('two_copies')}"]
'''

_CONTAINER_IS_NOT_A_BINDING = '''
def report(doc):
    channel = doc.get("channel")
    out = []
    for pair in channel.get("pairs"):
        out.append(f"пар {pair.get('name')} шт.")
    return out
'''

_READS_A_NEIGHBOURS_PAIRS = '''
import json


def main():
    other = json.loads("{}")
    counts = other.get("counts")
    print(f"пар {counts.get('pairs')} шт.")
'''

_DELEGATES_ONLY = '''
def render(data):
    from spa_core.monitoring.rule_second_copy_census import format_report as _r
    return _r(data)
'''

_READS_NOTHING = '''
def report(doc):
    return ["здесь переписи нет вовсе"]


def format_report(doc):
    return report(doc)


def main():
    print("здесь переписи нет вовсе")
'''

#: Читатель, у которого ЕСТЬ своё число И ввезён отрисовщик производителя.
#: Своя база должна победить: делегирование — исход для того, у кого её нет.
_READS_AND_DELEGATES = '''
from spa_core.monitoring.rule_second_copy_census import format_report


def report(doc):
    counts = doc.get("counts")
    return [f"две копии {counts.get('two_copies')}"] + format_report(doc)
'''

#: Цепь привязок, записанная ОБРАТНО порядку обхода: за один проход
#: последнее звено не разрешается, за два — разрешается.
_BINDING_CHAIN_IN_REVERSE = '''
def report(doc):
    deep = mid.get("two_copies")
    mid = doc.get("counts")
    return [f"две копии {deep}"]
'''

#: Токен, ОБЪЯВЛЕННЫЙ двум базам, но вставший рядом с ОДНОЙ.
_DECLARED_TWICE_ADJACENT_ONCE = '''
def report(doc):
    counts = doc.get("counts")
    return [f"пар {counts.get('two_copies')} шт."]
'''

#: Тот же токен рядом с базой, которой он НЕ объявлен, — и рядом с той,
#: которой объявлен. Порядок проверок вердикта решает исход.
_AMBIGUOUS_TOKEN_ON_A_FOREIGN_BASE = '''
def report(doc):
    counts = doc.get("counts")
    sides = doc.get("sides")
    return [f"пар {sides.get('GENUINE')} шт.",
            f"пар {counts.get('two_copies')} шт."]
'''

_BRIDGE_CALLS_RUN = '''
from spa_core.monitoring import rule_second_copy_census


def main(args):
    _rsc = rule_second_copy_census.run(root=args.root)
    _rc = _rsc["doc"].get("counts")
    _two = _rc.get("two_copies")
    print(f"правил в двух копиях {int(_two)}")
'''


class ConsumerBaseNamingScenes(unittest.TestCase):
    """Сцены: что прибор говорит о каждом объявленном исходе."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_reader_naming_its_own_base_is_not_a_finding(self):
        doc = _scene(self.root, report_src=_NAMES_ITS_OWN_BASE,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(section["status"], CONSUMER_READS)
        self.assertEqual(_verdicts(section), [NAMING_SINGLE])
        self.assertEqual(doc["findings"], [])
        self.assertEqual(doc["naming"][NAMING_SINGLE], 1)

    def test_a_reader_naming_another_base_is_named_CROSS(self):
        """Обратная сторона предыдущего: сменилось ТОЛЬКО имя базы."""
        doc = _scene(self.root, report_src=_NAMES_ANOTHER_BASE,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(_verdicts(section), [NAMING_CROSS])
        self.assertEqual(len(doc["findings"]), 1)
        self.assertEqual(doc["findings"][0]["base"], BASE_GENUINE)
        self.assertEqual(doc["findings"][0]["verdict"], NAMING_CROSS)

    def test_ambiguity_comes_from_MEASURED_adjacency_not_from_the_table(self):
        """Один токен рядом с ДВУМЯ базами — находка; рядом с одной — нет.

        Токен «пар» объявлен ДВУМ базам. Если бы многозначность бралась из
        объявления, он краснел бы в обеих сценах одинаково, и мера отвечала бы
        на свой вопрос, а не на нужный.
        """
        doc_two = _scene(self.root, report_src=_ONE_TOKEN_TWO_BASES,
                         bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        self.assertEqual(doc_two["ambiguous_tokens"], ["пар"])
        self.assertEqual(_verdicts(_by_key(doc_two, "report_section")),
                         [NAMING_AMBIGUOUS, NAMING_AMBIGUOUS])

        doc_one = _scene(self.root, report_src=_NAMES_ITS_OWN_BASE,
                         bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        self.assertEqual(doc_one["ambiguous_tokens"], [])
        self.assertIn("две копии", doc_one["token_adjacency"])
        self.assertEqual(doc_one["token_adjacency"]["две копии"],
                         [BASE_GUARD_EXECUTOR])

    def test_adjacency_is_recorded_for_both_bases_of_the_ambiguous_token(self):
        doc = _scene(self.root, report_src=_ONE_TOKEN_TWO_BASES,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        self.assertEqual(doc["token_adjacency"]["пар"],
                         sorted([BASE_BOOKS_PAIRS, BASE_GUARD_EXECUTOR]))

    def test_a_number_with_no_adjacent_token_is_UNNAMED_not_a_finding(self):
        doc = _scene(self.root, report_src=_NUMBER_WITHOUT_A_NAME,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        self.assertEqual(_verdicts(_by_key(doc, "report_section")),
                         [NAMING_UNNAMED])
        self.assertEqual(doc["findings"], [])
        self.assertEqual(doc["naming"][NAMING_UNNAMED], 1)

    def test_container_is_not_a_binding(self):
        """``pair['name']`` не есть координата ``pairs``.

        Объединение ключей цепи приписало бы базе книг каждое поле каждой
        пары; ровно эта форма уже стоила нам бомбы (правило доставки, раздел
        про инъекцию часов).
        """
        doc = _scene(self.root, report_src=_CONTAINER_IS_NOT_A_BINDING,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(section["numbers"], [])
        self.assertEqual(doc["ambiguous_tokens"], [])

    def test_a_neighbours_pairs_is_not_counted_as_ours(self):
        """Чужой ключ ``pairs`` без происхождения от переписи — не наш.

        Без этого вопроса прибор выдумал бы находку того самого класса, что
        ищет: соседская перепись у моста тоже печатает «пар».
        """
        doc = _scene(self.root, report_src=_READS_NOTHING,
                     bridge_src=_READS_A_NEIGHBOURS_PAIRS,
                     office_src=_READS_NOTHING)
        bridge = _by_key(doc, "findings_bridge")
        self.assertEqual(bridge["status"], CONSUMER_NO_READ)
        self.assertEqual(doc["findings"], [])

    def test_a_reader_that_only_delegates_is_DELEGATES_not_zero(self):
        doc = _scene(self.root, report_src=_READS_NOTHING,
                     bridge_src=_READS_NOTHING, office_src=_DELEGATES_ONLY)
        office = _by_key(doc, "office_step")
        self.assertEqual(office["status"], CONSUMER_DELEGATES)
        self.assertEqual(office["delegates_via"], ["_r"])

    def test_delegation_carries_the_ambiguity_only_when_there_IS_one(self):
        """Обе стороны: делегат несёт чужое имя лишь когда оно многозначно."""
        loud = _scene(self.root, report_src=_ONE_TOKEN_TWO_BASES,
                      bridge_src=_READS_NOTHING, office_src=_DELEGATES_ONLY)
        self.assertEqual(loud["carries_ambiguity_by_delegation"],
                         ["office_step"])

        quiet = _scene(self.root, report_src=_NAMES_ITS_OWN_BASE,
                       bridge_src=_READS_NOTHING, office_src=_DELEGATES_ONLY)
        self.assertEqual(quiet["carries_ambiguity_by_delegation"], [])

    def test_a_reader_that_neither_reads_nor_delegates_is_NO_READ(self):
        doc = _scene(self.root, report_src=_READS_NOTHING,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        for key in _PATH_OF:
            self.assertEqual(_by_key(doc, key)["status"], CONSUMER_NO_READ)

    def test_a_bridge_that_calls_run_is_anchored_by_the_call(self):
        """У чужого модуля якорь — вызов ``run`` производителя, не параметр."""
        doc = _scene(self.root, report_src=_READS_NOTHING,
                     bridge_src=_BRIDGE_CALLS_RUN, office_src=_READS_NOTHING)
        bridge = _by_key(doc, "findings_bridge")
        self.assertEqual(bridge["status"], CONSUMER_READS)
        self.assertEqual(bridge["bases_read"], [BASE_GUARD_EXECUTOR])
        self.assertEqual(_verdicts(bridge), [NAMING_SINGLE])

    def test_a_reader_with_its_OWN_base_is_READS_even_when_it_also_delegates(self):
        """Делегирование — исход для того, у кого своей базы НЕТ."""
        doc = _scene(self.root, report_src=_READS_AND_DELEGATES,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(section["status"], CONSUMER_READS)
        self.assertTrue(section["delegates_via"])
        self.assertEqual(section["bases_read"], [BASE_GUARD_EXECUTOR])

    def test_a_binding_chain_needs_more_than_one_pass(self):
        """Неподвижная точка ищется, а не один проход «на глазок»."""
        doc = _scene(self.root, report_src=_BINDING_CHAIN_IN_REVERSE,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(_verdicts(section), [NAMING_SINGLE])
        self.assertEqual(section["numbers"][0]["coordinate"], "two_copies")

    def test_a_token_declared_to_two_bases_but_seen_at_one_is_NOT_ambiguous(self):
        """Прямая обратная сторона замера: «пар» объявлен двум, встал у одной.

        Бралась бы многозначность из ОБЪЯВЛЕНИЯ — он краснел бы и здесь, и
        мера отвечала бы на свой вопрос вместо нужного.
        """
        doc = _scene(self.root, report_src=_DECLARED_TWICE_ADJACENT_ONCE,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        self.assertEqual(doc["token_adjacency"]["пар"], [BASE_GUARD_EXECUTOR])
        self.assertEqual(doc["ambiguous_tokens"], [])
        self.assertEqual(_verdicts(_by_key(doc, "report_section")),
                         [NAMING_SINGLE])

    def test_ambiguity_is_judged_BEFORE_cross_naming(self):
        """Число, названное многозначным словом, многозначно — не «чужим именем».

        Порядок проверок решает исход: при обратном порядке число базы
        `genuine_label`, названное словом «пар», объявлялось бы CROSS, и
        находка о МНОГОЗНАЧНОСТИ слова растворилась бы в соседнем классе.
        """
        doc = _scene(self.root,
                     report_src=_AMBIGUOUS_TOKEN_ON_A_FOREIGN_BASE,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        self.assertEqual(doc["ambiguous_tokens"], ["пар"])
        self.assertEqual(_verdicts(_by_key(doc, "report_section")),
                         [NAMING_AMBIGUOUS, NAMING_AMBIGUOUS])
        self.assertEqual(doc["naming"][NAMING_CROSS], 0)

    def test_a_coordinate_claimed_by_TWO_bases_is_skipped_not_guessed(self):
        """Одна координата у двух баз — отказ, а не выбор наугад.

        Реестр подменяется на время замера: сегодня такой координаты нет, и
        ветка осталась бы непроверенной — то есть сторожем без зубов.
        """
        saved = mod.CENSUS_BASES
        mod.CENSUS_BASES = (
            {"key": BASE_GUARD_EXECUTOR, "what": "к",
             "coordinates": ("two_copies",), "tokens": ("две копии",)},
            {"key": BASE_BOOKS_PAIRS, "what": "к",
             "coordinates": ("two_copies",), "tokens": ("пар",)},
        )
        try:
            doc = _scene(self.root, report_src=_NAMES_ITS_OWN_BASE,
                         bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        finally:
            mod.CENSUS_BASES = saved
        self.assertEqual(_by_key(doc, "report_section")["numbers"], [])
        self.assertEqual(doc["findings"], [])

    def test_missing_file_is_UNMEASURED_with_a_reason(self):
        _write(self.root, _PATH_OF["report_section"], _READS_NOTHING)
        _write(self.root, _PATH_OF["findings_bridge"], _READS_NOTHING)
        doc = consumer_base_naming(self.root)      # шага 0-офис на диске НЕТ
        office = _by_key(doc, "office_step")
        self.assertEqual(office["status"], CONSUMER_UNMEASURED)
        self.assertIn("не прочитан", office["reason"])
        self.assertNotIn("numbers", office)

    def test_unparsable_file_is_UNMEASURED_and_not_NO_READ(self):
        doc = _scene(self.root, report_src="def report(doc:\n",
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(section["status"], CONSUMER_UNMEASURED)
        self.assertIn("не разобран", section["reason"])

    def test_declared_scope_absent_is_UNMEASURED_not_NO_READ(self):
        """Область объявлена, а функции нет — это «не смотрели», не «пусто»."""
        doc = _scene(self.root, report_src="def render(doc):\n    return []\n",
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(section["status"], CONSUMER_UNMEASURED)
        self.assertIn("области", section["reason"])

    def test_reads_outside_an_fstring_are_counted_not_dropped(self):
        source = ('def report(doc):\n'
                  '    counts = doc.get("counts")\n'
                  '    return [str(counts.get("two_copies"))]\n')
        doc = _scene(self.root, report_src=source,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        section = _by_key(doc, "report_section")
        self.assertEqual(section["numbers"], [])
        self.assertEqual(section["reads_outside_fstring"], 1)

    def _named_at_distance(self, padding: int) -> list:
        """Одна и та же сцена, у которой токен отодвигается от числа."""
        source = ('def report(doc):\n'
                  '    counts = doc.get("counts")\n'
                  '    return [f"две копии' + " " * padding +
                  '{counts.get(\'two_copies\')}"]\n')
        doc = _scene(self.root, report_src=source,
                     bridge_src=_READS_NOTHING, office_src=_READS_NOTHING)
        return _verdicts(_by_key(doc, "report_section"))

    def test_a_token_INSIDE_the_name_window_names_the_number(self):
        self.assertEqual(self._named_at_distance(1), [NAMING_SINGLE])

    def test_the_same_token_OUTSIDE_the_window_does_not(self):
        """Обратная сторона: сцена отличается ТОЛЬКО расстоянием."""
        self.assertEqual(self._named_at_distance(NAME_WINDOW_CHARS + 5),
                         [NAMING_UNNAMED])

    def test_the_window_is_a_DECLARED_size_and_widening_it_is_visible(self):
        """Расстояние здесь АБСОЛЮТНО и от самой константы не зависит.

        Тест, меряющий окно через `NAME_WINDOW_CHARS`, расширяется вместе с
        ним и потому молчит о расширении — это сторож, судящий по собственной
        мерке. Здесь расстояние 120 символов названо числом: сдвиг окна к
        такой ширине обязан быть ВИДЕН, а не пройти молча.
        """
        self.assertLess(NAME_WINDOW_CHARS, 120)
        self.assertEqual(self._named_at_distance(120), [NAMING_UNNAMED])


class TerminalCoordinate(unittest.TestCase):
    """Координата значения — ПОСЛЕДНЯЯ применённая, и обёртки прозрачны."""

    def _coord(self, expr: str, binding=None):
        node = ast.parse(expr, mode="eval").body
        return mod._terminal_coordinate(node, {}, binding or {})

    def test_last_subscript_wins(self):
        self.assertEqual(self._coord('a["pairs"]["name"]'), "name")

    def test_get_chain_takes_the_outermost(self):
        self.assertEqual(self._coord('a.get("channel").get("pairs")'), "pairs")

    def test_observed_reads_its_second_argument(self):
        self.assertEqual(self._coord('observed(doc, "counts", kind=dict)'),
                         "counts")

    def test_int_and_or_and_ternary_are_transparent(self):
        binding = {"x": "two_copies"}
        self.assertEqual(self._coord("int(x)", binding), "two_copies")
        self.assertEqual(self._coord("x or 0", binding), "two_copies")
        self.assertEqual(
            self._coord("'НЕ ИЗМЕРЕНО' if x is None else int(x)", binding),
            "two_copies")

    def test_module_constant_resolves_to_its_value(self):
        node = ast.parse('counts.get(CLASS)', mode="eval").body
        self.assertEqual(
            mod._terminal_coordinate(node, {"CLASS": "two_copies"}, {}),
            "two_copies")

    def test_an_unreadable_expression_is_a_third_outcome_not_a_guess(self):
        self.assertIsNone(self._coord("a", {"a": None}))
        self.assertIsNone(
            mod._terminal_coordinate(ast.parse("f()", mode="eval").body,
                                     {}, {}))

    def test_deep_ternary_nesting_returns_a_third_outcome_not_RecursionError(self):
        """Предел вложенности — отказ, а не срыв рекурсии.

        Обе стороны: на глубине ВНУТРИ предела координата ещё находится, за
        пределом — отдаётся третий исход, и ни одна сторона не падает.
        """
        binding = {"x": "two_copies"}
        inside = "int(x)"
        for _ in range(mod._TERNARY_NESTING_LIMIT - 2):
            inside = f"({inside} if x else 0)"
        self.assertEqual(self._coord(inside, binding), "two_copies")

        beyond = "int(x)"
        for _ in range(mod._TERNARY_NESTING_LIMIT + 5):
            beyond = f"({beyond} if x else 0)"
        self.assertIsNone(self._coord(beyond, binding))


class RegistryRefusal(unittest.TestCase):
    """Пустой реестр — ОТКАЗ, а не «расхождений нет»."""

    def test_empty_base_registry_refuses(self):
        saved = mod.CENSUS_BASES
        mod.CENSUS_BASES = ()
        try:
            doc = consumer_base_naming(_ROOT)
        finally:
            mod.CENSUS_BASES = saved
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("пуст", doc["reason"])

    def test_empty_consumer_registry_refuses(self):
        saved = mod.CENSUS_CONSUMERS
        mod.CENSUS_CONSUMERS = ()
        try:
            doc = consumer_base_naming(_ROOT)
        finally:
            mod.CENSUS_CONSUMERS = saved
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("пуст", doc["reason"])

    def test_every_declared_base_has_at_least_one_coordinate_and_token(self):
        for base in CENSUS_BASES:
            self.assertTrue(base["coordinates"], base["key"])
            self.assertTrue(base["tokens"], base["key"])

    def test_every_declared_consumer_names_an_existing_file(self):
        for spec in CENSUS_CONSUMERS:
            self.assertTrue((_ROOT / spec["path"]).exists(), spec["path"])


class LiveTree(unittest.TestCase):
    """Живой контроль: на НАСТОЯЩЕМ дереве мера не холостая."""

    @classmethod
    def setUpClass(cls):
        cls.doc = consumer_base_naming(_ROOT)

    def test_measured_on_the_real_tree(self):
        self.assertEqual(self.doc["status"], "MEASURED")
        self.assertEqual(len(self.doc["consumers"]), len(CENSUS_CONSUMERS))

    def test_the_office_step_delegates_and_has_no_base_of_its_own(self):
        office = _by_key(self.doc, "office_step")
        self.assertEqual(office["status"], CONSUMER_DELEGATES)
        self.assertEqual(office["numbers"], [])
        self.assertTrue(office["delegates_via"])

    def test_the_bridge_takes_a_THIRD_base_neither_pairs_nor_genuine(self):
        """Ответ заказу: мост берёт не ту базу, о которой заказ спрашивал."""
        bridge = _by_key(self.doc, "findings_bridge")
        self.assertEqual(bridge["status"], CONSUMER_READS)
        self.assertEqual(bridge["bases_read"], [BASE_GUARD_EXECUTOR])
        self.assertNotIn(BASE_BOOKS_PAIRS, bridge["bases_read"])
        self.assertNotIn(BASE_GENUINE, bridge["bases_read"])

    def test_the_report_section_reads_all_three_bases(self):
        section = _by_key(self.doc, "report_section")
        self.assertEqual(sorted(section["bases_read"]),
                         sorted([BASE_BOOKS_PAIRS, BASE_GENUINE,
                                 BASE_GUARD_EXECUTOR]))

    def test_the_word_for_pairs_is_ambiguous_on_the_real_tree(self):
        self.assertIn("пар", self.doc["ambiguous_tokens"])
        self.assertEqual(self.doc["token_adjacency"]["пар"],
                         sorted([BASE_BOOKS_PAIRS, BASE_GUARD_EXECUTOR]))

    def test_findings_name_the_line_and_the_coordinate(self):
        self.assertTrue(self.doc["findings"])
        for item in self.doc["findings"]:
            self.assertIsInstance(item["line"], int)
            self.assertTrue(item["coordinate"])
            self.assertIn(item["verdict"], (NAMING_AMBIGUOUS, NAMING_CROSS))

    def test_the_blind_spots_are_named_aloud(self):
        self.assertTrue(self.doc["blind"])
        self.assertTrue(any("f-строк" in line for line in self.doc["blind"]))


class Wiring(unittest.TestCase):
    """Координата доезжает до документа и до глаз."""

    def test_the_report_prints_the_section_and_it_is_not_hollow(self):
        doc = {"status": "CLEAN", "counts": {}, "rows": [],
               "consumer_base_naming": consumer_base_naming(_ROOT)}
        lines = [line for line in report(doc)
                 if line.startswith("[БАЗА ЧИТАТЕЛЯ")]
        self.assertGreaterEqual(len(lines), 6)
        self.assertTrue(any("МНОГОЗНАЧНО" in line for line in lines))
        self.assertTrue(any("ДЕЛЕГИРУЕТ" in line for line in lines))

    def test_the_report_says_NOT_MEASURED_when_the_key_is_absent(self):
        lines = report({"status": "CLEAN", "counts": {}, "rows": []})
        said = [line for line in lines if line.startswith("[БАЗА ЧИТАТЕЛЯ")]
        self.assertEqual(len(said), 1)
        self.assertIn("НЕ ИЗМЕРЕНА", said[0])

    def test_the_report_repeats_the_refusal_reason(self):
        doc = {"status": "CLEAN", "counts": {}, "rows": [],
               "consumer_base_naming": {"status": "UNMEASURED",
                                        "reason": "реестр пуст"}}
        said = [line for line in report(doc)
                if line.startswith("[БАЗА ЧИТАТЕЛЯ")]
        self.assertEqual(len(said), 1)
        self.assertIn("реестр пуст", said[0])

    def test_measure_carries_the_key_into_the_document(self):
        source = (_ROOT / PRODUCER).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "consumer_base_naming"
            for node in ast.walk(tree))
        self.assertTrue(called, "координата не зовётся из measure()")
        self.assertIn('"consumer_base_naming": base_naming', source)


if __name__ == "__main__":
    unittest.main()
