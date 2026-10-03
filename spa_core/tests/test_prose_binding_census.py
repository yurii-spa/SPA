"""Контроль прибора «сколько привязок конституции держится прозой» (`prose_binding_census`).

Каждый тест — положительный контроль на КОНКРЕТНЫЙ способ соврать, а не проверка,
что функция что-то вернула. Прибор отвечает на заказ G94 п. 3, и соврать он может
ровно пятью способами:

1. **посчитать читателем всякого, у кого токен есть в ФАЙЛЕ.** Докстрока самого
   `s49_criterion_price` упоминает ADR-504 и ADR-505; грep объявил бы её
   читателем привязки ``adr``, которой она не читает. Это главный контроль
   набора (`TokenInTheFileIsNotAReader`);
2. **потерять единственного настоящего читателя**, потому что образец доезжает
   до значения не прямо, а через помощника того же модуля
   (`ReachThroughAHelper`);
3. **слить «поле обходится» и «поля нет»** в одно слово «проза»: цена у них
   разная — заполнить против объявить, — и ADR-506 уже платил за такое слияние
   (`PlaceOfTheBinding`);
4. **выдать «не измерено» за «читателя нет»** (fail-OPEN, тише красного —
   опаснее): вычисленный образец и склейку надо различать
   (`ThirdOutcomeOfTheReaderAxis`);
5. **приложить мерку ПРОЗЫ к ПОЛЮ** и получить ноль читателей там, где их
   несколько (`FieldIsMeasuredByItsOwnRuler`).

# FROZEN-DATE-OK: injected-clock — часы входом: единственный литерал даты здесь
# `_ANCHOR`, и он передаётся прибору аргументом `now=`; ни один вердикт набора
# от календаря не зависит.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import prose_binding_census as pbc  # noqa: E402

#: Единственный литерал даты набора. Передаётся прибору аргументом `now=`.
_ANCHOR = dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=dt.timezone.utc)


class _Stand:
    """Одноразовый стенд: конституция и дерево модулей-кандидатов.

    Стенд собирается ПОД `spa_core/`, потому что именно там прибор ищет
    читателей: положить модуль мимо объявленных корней значило бы проверять
    не ту дорогу.
    """

    def __init__(self, tmp: Path):
        self.root = tmp
        (self.root / "architecture").mkdir(parents=True, exist_ok=True)
        (self.root / "spa_core" / "monitoring").mkdir(parents=True, exist_ok=True)
        (self.root / "spa_core" / "tests").mkdir(parents=True, exist_ok=True)
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        self.agents: list = []
        self.artifacts: list = []

    # ── конституция ──────────────────────────────────────────────────────
    def agent(self, label, *, notes="", governed_by=None, **extra):
        entry = {"label": label, "notes": notes, **extra}
        if governed_by is not None:
            entry["governed_by"] = governed_by
        self.agents.append(entry)

    def artifact(self, path, *, notes="", **extra):
        self.artifacts.append({"path": path, "notes": notes, **extra})

    def write(self, *, body=None) -> Path:
        target = self.root / pbc.MANIFEST_REL
        payload = body if body is not None else {"agents": self.agents,
                                                 "artifacts": self.artifacts}
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return target

    # ── дерево кандидатов ────────────────────────────────────────────────
    def module(self, rel: str, source: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def measure(self, **kw):
        self.write()
        return pbc.measure(self.root, now=_ANCHOR, **kw)

    def prose(self):
        return pbc.prose_readers(self.root)

    def field(self):
        return pbc.field_readers(self.root)


class _StandCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.stand = _Stand(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def row(self, doc, entry, kind):
        return next(r for r in doc["rows"] if r["entry"] == entry and r["kind"] == kind)

    def reader(self, rows, module):
        return next(r for r in rows if r["module"] == module)


#: Модуль-кандидат: называет конституцию и читает её прозу. Что он с прозой
#: ДЕЛАЕТ, подставляется телом — в этом и весь предмет второй оси.
_READER = '''"""{doc}"""
import re

MANIFEST = "architecture/manifest.json"
{const}


def parse(manifest):
    for entry in manifest["artifacts"]:
        note = entry.get("notes")
        {body}
    return None
'''


def _reader(body: str, *, doc="читатель прозы", const="") -> str:
    return _READER.format(body=body, doc=doc, const=const)


# ───────────────────────── ось 1 · место привязки ─────────────────────────

class PlaceOfTheBinding(_StandCase):
    """«Поле обходится» и «поля нет» — РАЗНЫЕ положения дел, и чинятся разным."""

    def test_field_filled_and_prose_silent_is_the_only_healthy_outcome(self):
        self.stand.agent("com.spa.a", governed_by=["ADR-066"], notes="без ссылок")
        doc = self.stand.measure()
        self.assertEqual(self.row(doc, "com.spa.a", "adr")["place"], pbc.IN_FIELD)
        self.assertEqual(doc["on_prose"], 0)
        self.assertEqual(doc["verdict"], "every_binding_in_a_field")

    def test_empty_field_beside_prose_is_a_BYPASS_not_a_missing_field(self):
        """Поле есть и пусто ⇒ читатель поля слеп УЖЕ СЕГОДНЯ, а не завтра."""
        self.stand.agent("com.spa.a", governed_by=[], notes="сделано по ADR-129")
        doc = self.stand.measure()
        row = self.row(doc, "com.spa.a", "adr")
        self.assertEqual(row["place"], pbc.FIELD_BYPASSED)
        self.assertEqual(row["field"], pbc.FIELD_KEY)
        self.assertEqual(row["prose_mentions"], 1)
        self.assertEqual(row["field_mentions"], 0)
        self.assertIn(row, doc["findings"])

    def test_artifact_has_no_field_at_all_so_prose_is_the_only_place(self):
        """У артефакта поля нет — это цена ОБЪЯВИТЬ, а не цена заполнить."""
        self.stand.artifact("data/a.json", notes="заведено ADR-549")
        doc = self.stand.measure()
        row = self.row(doc, "data/a.json", "adr")
        self.assertEqual(row["place"], pbc.NO_FIELD)
        self.assertIsNone(row["field"])
        # Это НЕ находка о небрежности автора: положить было некуда.
        self.assertNotIn(row, doc["findings"])

    def test_both_places_at_once_is_a_SECOND_COPY_finding(self):
        self.stand.agent("com.spa.a", governed_by=["ADR-066"], notes="см. ADR-066")
        doc = self.stand.measure()
        row = self.row(doc, "com.spa.a", "adr")
        self.assertEqual(row["place"], pbc.IN_BOTH)
        self.assertIn(row, doc["findings"])

    def test_bypass_is_ranked_above_second_copy_among_findings(self):
        """Обход поля — потеря СЕГОДНЯ; вторая копия — риск расхождения."""
        self.stand.agent("com.spa.copy", governed_by=["ADR-066"], notes="ADR-066")
        self.stand.agent("com.spa.bypass", governed_by=[], notes="ADR-129")
        doc = self.stand.measure()
        self.assertEqual(doc["findings"][0]["place"], pbc.FIELD_BYPASSED)

    def test_an_entry_binding_nothing_is_not_population(self):
        """Запись без привязок в население не входит — иначе доля прозы врала бы."""
        self.stand.agent("com.spa.quiet", governed_by=[], notes="ничего не решал")
        self.stand.artifact("data/quiet.json", notes="")
        with self.assertRaises(pbc.Unmeasured):
            self.stand.measure()


class KindsAreRecognisedByDeclaredForms(_StandCase):
    """Перечень родов ЗАКРЫТ: открытый растил бы население бесшумно."""

    def test_every_declared_kind_is_found_in_prose(self):
        prose = ("сделано по ADR-549 и ADR-YL-012, критерий §49 `Costs`, "
                 "инв. #17, правило .claude/rules/deployment.md, заказ G94, цикл #762")
        self.stand.artifact("data/a.json", notes=prose)
        doc = self.stand.measure()
        found = {row["kind"] for row in doc["rows"]}
        self.assertEqual(found, {kind.name for kind in pbc.KINDS})

    def test_provenance_and_governance_are_never_summed_into_one_number(self):
        """Номер цикла ничем не управляет: сумма выдала бы историю за правило."""
        self.stand.artifact("data/a.json", notes="цикл #762 и ADR-549")
        doc = self.stand.measure()
        self.assertEqual(doc["by_kind"]["cycle"]["role"], pbc.PROVENANCE)
        self.assertEqual(doc["by_kind"]["adr"]["role"], pbc.GOVERNANCE)
        roles = {doc["by_kind"][name]["role"] for name in doc["by_kind"]}
        self.assertEqual(roles, {pbc.GOVERNANCE, pbc.PROVENANCE})

    def test_a_near_miss_form_is_not_a_binding(self):
        """«ADR» без номера и «инв» без решётки привязками не являются."""
        self.stand.artifact("data/a.json", notes="см. ADR и инв по тексту")
        with self.assertRaises(pbc.Unmeasured):
            self.stand.measure()


# ────────────────────── ось 2 · читатели прозы ───────────────────────────

class TokenInTheFileIsNotAReader(_StandCase):
    """ГЛАВНЫЙ контроль набора: грep объявил бы читателем докстроку.

    Прибор §49 в своей собственной докстроке ссылается на ADR-504 и ADR-505.
    Правило «токен есть в файле» сделало бы его читателем привязки ``adr``,
    которой он не читает ни строкой, — и население читателей выросло бы
    ровно на тех, кто ничего не читает.
    """

    def test_token_only_in_the_docstring_does_not_make_a_parser(self):
        self.stand.module("spa_core/monitoring/greppable.py", _reader(
            'pass', doc="разбор по ADR-504: привязка живёт прозой, инв. #17"))
        rows = self.stand.prose()
        row = self.reader(rows, "spa_core/monitoring/greppable.py")
        self.assertEqual(row["verdict"], pbc.TEXT_CONSUMER)
        self.assertEqual(row["kinds"], [])

    def test_token_in_a_pattern_applied_to_ANOTHER_value_does_not_count(self):
        """Образец, приложенный к чужому значению, этого значения не читает."""
        self.stand.module("spa_core/monitoring/elsewhere.py", _reader(
            'other = entry.get("path") or ""\n'
            '        re.search("ADR-", other)'))
        row = self.reader(self.stand.prose(), "spa_core/monitoring/elsewhere.py")
        self.assertEqual(row["verdict"], pbc.TEXT_CONSUMER)
        self.assertEqual(row["kinds"], [])

    def test_a_module_that_never_names_the_manifest_is_not_a_candidate(self):
        """Прозу читает тот, кто читает КОНСТИТУЦИЮ, а не любой `notes`."""
        self.stand.module("spa_core/monitoring/foreign.py",
                          'import re\n\n\ndef f(d):\n'
                          '    note = d.get("notes")\n'
                          '    return re.search("§49", note)\n')
        self.assertEqual([r["module"] for r in self.stand.prose()], [])

    def test_a_test_file_is_never_counted_as_a_reader_of_the_system(self):
        self.stand.module("spa_core/tests/test_x.py", _reader(
            're.search("§49", note)'))
        self.assertEqual([r["module"] for r in self.stand.prose()], [])

    def test_the_manifest_named_only_in_a_COMMENT_is_not_a_candidate(self):
        """Адрес конституции обязан быть ЛИТЕРАЛОМ, а не упоминанием в тексте.

        Отсев по тексту файла («есть ли подстрока») такой модуль пропустил бы:
        он назвал конституцию, но не открывает её. Мутация «проверку по дереву
        разбора убрать» выживала потому, что в сцене не было ни одного модуля,
        где адрес стоит ТОЛЬКО комментарием.
        """
        self.stand.module("spa_core/monitoring/commented.py",
                          'import re\n\n\n'
                          '# по мотивам architecture/manifest.json, но его не читает\n'
                          'def f(d):\n'
                          '    note = d.get("notes")\n'
                          '    return re.search("§49", note or "")\n')
        self.assertEqual([r["module"] for r in self.stand.prose()], [])


class ReachOfALiteralToTheValue(_StandCase):
    """Четыре объявленные формы «образец доехал», каждая своим контролем."""

    def test_re_call_with_a_literal_pattern(self):
        self.stand.module("spa_core/monitoring/a.py", _reader(
            're.finditer("§49", note)'))
        self.assertEqual(self.reader(self.stand.prose(),
                                     "spa_core/monitoring/a.py")["kinds"], ["s49"])

    def test_module_level_compiled_constant(self):
        self.stand.module("spa_core/monitoring/b.py", _reader(
            '_RX.search(note)', const='_RX = re.compile(r"ADR-(\\d{3})")'))
        self.assertEqual(self.reader(self.stand.prose(),
                                     "spa_core/monitoring/b.py")["kinds"], ["adr"])

    def test_string_method_of_the_value_itself(self):
        self.stand.module("spa_core/monitoring/c.py", _reader(
            'note.startswith("инв. #")'))
        self.assertEqual(self.reader(self.stand.prose(),
                                     "spa_core/monitoring/c.py")["kinds"], ["invariant"])

    def test_membership_test_against_the_value(self):
        self.stand.module("spa_core/monitoring/d.py", _reader(
            'if ".claude/rules/" in note:\n            return note'))
        self.assertEqual(self.reader(self.stand.prose(),
                                     "spa_core/monitoring/d.py")["kinds"], ["rule"])

    def test_a_derived_slice_still_carries_the_value(self):
        """`tail = note[pos:pos + 160]` — живая форма прибора §49."""
        self.stand.module("spa_core/monitoring/e.py", _reader(
            'tail = note[0:160]\n        re.match("§49", tail)'))
        self.assertEqual(self.reader(self.stand.prose(),
                                     "spa_core/monitoring/e.py")["kinds"], ["s49"])


class ReachThroughAHelper(_StandCase):
    """Без шага «вызов своей функции» единственный настоящий читатель пропал бы.

    `s49_criterion_price` читает заметку в `parse_bindings`, а образец ``§49``
    применяет `_iter_mentions` — ДРУГАЯ функция того же модуля. Трассировка,
    не идущая за вызовом, объявила бы его «берущим прозу как текст», то есть
    соврала бы В СТОРОНУ ЗДОРОВЬЯ.
    """

    def test_pattern_applied_inside_a_same_module_helper_counts(self):
        self.stand.module("spa_core/monitoring/hop.py", '''"""читатель через помощника"""
import re

MANIFEST = "architecture/manifest.json"


def _mentions(text):
    return list(re.finditer("§49", text))


def parse(manifest):
    for entry in manifest["artifacts"]:
        note = entry.get("notes")
        _mentions(note)
    return None
''')
        row = self.reader(self.stand.prose(), "spa_core/monitoring/hop.py")
        self.assertEqual(row["verdict"], pbc.BINDING_PARSER)
        self.assertEqual(row["kinds"], ["s49"])

    def test_keyword_argument_carries_the_value_too(self):
        self.stand.module("spa_core/monitoring/kw.py", '''"""читатель через ключевой аргумент"""
import re

MANIFEST = "architecture/manifest.json"


def _mentions(text=None):
    return list(re.finditer("заказ G", text))


def parse(manifest):
    for entry in manifest["artifacts"]:
        note = entry.get("notes")
        _mentions(text=note)
    return None
''')
        self.assertEqual(self.reader(self.stand.prose(),
                                     "spa_core/monitoring/kw.py")["kinds"], ["order"])

    def test_an_unbound_read_is_traced_by_the_read_itself(self):
        """`re.search("ADR-", entry["notes"])` имени не связывает — и всё равно читатель."""
        self.stand.module("spa_core/monitoring/unbound.py", '''"""читатель без имени"""
import re

MANIFEST = "architecture/manifest.json"


def parse(manifest):
    for entry in manifest["agents"]:
        if re.search("ADR-", entry["notes"]):
            return entry
    return None
''')
        row = self.reader(self.stand.prose(), "spa_core/monitoring/unbound.py")
        self.assertEqual(row["verdict"], pbc.BINDING_PARSER)
        self.assertEqual(row["kinds"], ["adr"])


class ThirdOutcomeOfTheReaderAxis(_StandCase):
    """«Не измерено» и «измеренное отсутствие разбора» — РАЗНЫЕ ответы."""

    def test_a_computed_pattern_is_UNMEASURED_not_absent(self):
        """Образец собран вычислением ⇒ токена назвать нечем. Ни да, ни нет."""
        self.stand.module("spa_core/monitoring/computed.py", _reader(
            'head = "§" + "49"\n        re.search(head, note)'))
        row = self.reader(self.stand.prose(), "spa_core/monitoring/computed.py")
        self.assertEqual(row["verdict"], pbc.READER_UNMEASURED)
        self.assertEqual(row["cause"], pbc.PATTERN_NOT_LITERAL)

    def test_unparsable_source_is_UNMEASURED_with_its_own_cause(self):
        self.stand.module("spa_core/monitoring/broken.py",
                          'MANIFEST = "architecture/manifest.json"\n'
                          'def f(:\n    return "notes"\n')
        row = self.reader(self.stand.prose(), "spa_core/monitoring/broken.py")
        self.assertEqual(row["verdict"], pbc.READER_UNMEASURED)
        self.assertEqual(row["cause"], pbc.SOURCE_UNPARSED)

    def test_concatenation_is_a_MEASURED_text_consumer_not_unmeasured(self):
        """Склейка прозу не разбирает — и прятать это под «не измерено» нельзя."""
        self.stand.module("spa_core/monitoring/joined.py", _reader(
            'body = "\\n".join(["notes: ", note or ""])\n        return body'))
        row = self.reader(self.stand.prose(), "spa_core/monitoring/joined.py")
        self.assertEqual(row["verdict"], pbc.TEXT_CONSUMER)
        self.assertEqual(row["cause"], None)
        self.assertIn(pbc.LIMIT_CONCATENATED, row["reach_limits"])

    def test_storing_the_value_is_named_as_a_LIMIT_beside_the_verdict(self):
        """Укладку в контейнер прибор не досматривает — и говорит это вслух."""
        self.stand.module("spa_core/monitoring/stored.py", _reader(
            'bag = []\n        bag.append(note)\n        return bag'))
        row = self.reader(self.stand.prose(), "spa_core/monitoring/stored.py")
        self.assertEqual(row["verdict"], pbc.TEXT_CONSUMER)
        self.assertIn(pbc.LIMIT_STORED, row["reach_limits"])

    def test_handing_the_value_to_imported_code_is_named_too(self):
        self.stand.module("spa_core/monitoring/handed.py", _reader(
            'return json.dumps(note)', const="import json"))
        row = self.reader(self.stand.prose(), "spa_core/monitoring/handed.py")
        self.assertIn(pbc.LIMIT_HANDED_OUT, row["reach_limits"])

    def test_a_limit_never_replaces_a_verdict_for_a_real_parser(self):
        """Читатель, который И разбирает, И складывает: вердикт — разбор."""
        self.stand.module("spa_core/monitoring/mixed.py", _reader(
            'bag = []\n'
            '        bag.append(note)\n'
            '        re.search("§49", note)'))
        row = self.reader(self.stand.prose(), "spa_core/monitoring/mixed.py")
        self.assertEqual(row["verdict"], pbc.BINDING_PARSER)
        self.assertIn(pbc.LIMIT_STORED, row["reach_limits"])


class FieldIsMeasuredByItsOwnRuler(_StandCase):
    """Приложить к полю мерку прозы = получить ноль читателей там, где их несколько."""

    def test_reading_the_field_by_its_key_is_enough_to_be_a_reader(self):
        self.stand.module("spa_core/monitoring/fieldreader.py",
                          'MANIFEST = "architecture/manifest.json"\n\n\n'
                          'def f(d):\n'
                          '    return [x for x in (d.get("governed_by") or [])]\n')
        row = self.reader(self.stand.field(), "spa_core/monitoring/fieldreader.py")
        self.assertEqual(row["verdict"], pbc.KEY_READER)
        self.assertEqual(row["reads"], 1)

    def test_the_same_module_measured_by_the_PROSE_ruler_is_not_a_reader(self):
        """Тот же модуль, тот же вопрос, ДРУГАЯ мерка — и ответ обязан отличаться."""
        self.stand.module("spa_core/monitoring/fieldreader.py",
                          'MANIFEST = "architecture/manifest.json"\n\n\n'
                          'def f(d):\n'
                          '    return [x for x in (d.get("governed_by") or [])]\n')
        self.assertEqual([r["module"] for r in self.stand.prose()], [])
        self.assertEqual([r["module"] for r in self.stand.field()],
                         ["spa_core/monitoring/fieldreader.py"])

    def test_the_field_NAMED_but_never_read_is_not_a_reader(self):
        """Назвать поле в тексте — не прочитать его.

        `architecture_conformance` держит `governed_by` в ПЕРЕЧНЕ курируемых
        ключей и значения поля не читает; счесть его читателем значило бы
        завысить ту самую асимметрию, которую прибор меряет. Мутация «условие
        „чтений нет“ убрать» выживала из-за отсутствия такого модуля в сцене.
        """
        self.stand.module("spa_core/monitoring/names_only.py",
                          'MANIFEST = "architecture/manifest.json"\n'
                          'CURATED = ("layer", "governed_by", "notes")\n\n\n'
                          'def f(d):\n'
                          '    return [k for k in d if k in CURATED]\n')
        self.assertEqual([r["module"] for r in self.stand.field()], [])
        self.assertEqual([r["module"] for r in self.stand.prose()], [])

    def test_the_tally_of_the_field_axis_has_no_parser_bucket(self):
        """Бакет «разбирает» у поля был бы чужим вопросом, и его там нет."""
        self.stand.agent("com.spa.a", governed_by=["ADR-066"], notes="")
        doc = self.stand.measure()
        self.assertNotIn(pbc.BINDING_PARSER, doc["reader_tally"][pbc.FIELD_KEY])
        self.assertIn(pbc.KEY_READER, doc["reader_tally"][pbc.FIELD_KEY])


class KindWithoutAnyParser(_StandCase):
    """Род, живущий в прозе и не читаемый никем, — находка, а не фон."""

    def test_a_kind_with_prose_and_no_parser_is_named(self):
        self.stand.artifact("data/a.json", notes="заведено ADR-549")
        doc = self.stand.measure()
        self.assertEqual(doc["kinds_without_a_prose_parser"], ["adr"])
        self.assertEqual(doc["by_kind"]["adr"]["prose_parsers"], [])
        self.assertFalse(doc["by_kind"]["adr"]["second_reader"])

    def test_one_parser_is_not_a_second_reader(self):
        """Заказ спрашивал про ВТОРОГО читателя: один — это не два."""
        self.stand.artifact("data/a.json", notes="критерий §49 `Costs`")
        self.stand.module("spa_core/monitoring/one.py", _reader(
            're.finditer("§49", note)'))
        doc = self.stand.measure()
        self.assertEqual(len(doc["by_kind"]["s49"]["prose_parsers"]), 1)
        self.assertFalse(doc["by_kind"]["s49"]["second_reader"])
        self.assertEqual(doc["kinds_without_a_prose_parser"], [])

    def test_two_parsers_of_the_same_prose_are_a_SECOND_reader(self):
        """Две копии разбора одной прозы расходятся молча (ADR-220)."""
        self.stand.artifact("data/a.json", notes="критерий §49 `Costs`")
        self.stand.module("spa_core/monitoring/one.py", _reader('re.finditer("§49", note)'))
        self.stand.module("spa_core/monitoring/two.py", _reader('note.count("§49")'))
        doc = self.stand.measure()
        self.assertEqual(len(doc["by_kind"]["s49"]["prose_parsers"]), 2)
        self.assertTrue(doc["by_kind"]["s49"]["second_reader"])


# ──────────────────────── третий исход всего замера ──────────────────────

class NoMeasurementAtAll(_StandCase):
    """Замера нет ВОВСЕ — и это не «привязок ноль»."""

    def test_unreadable_manifest_refuses_with_an_address_AND_the_right_cause(self):
        """Причина обязана быть ИМЕННО «не прочитан».

        Адреса в сообщении недостаточно: при чтении, провалившемся в пустой
        словарь, отказ всё равно случится — но уже по соседней причине
        («нет половин»), и адрес в нём тот же. Мутация «чтение возвращает
        `{}`» выживала ровно на этой слабости утверждения.
        """
        with self.assertRaises(pbc.Unmeasured) as caught:
            pbc.measure(self.stand.root, now=_ANCHOR)
        self.assertIn(pbc.MANIFEST_REL, str(caught.exception))
        self.assertIn("не прочитан", str(caught.exception))

    def test_manifest_without_either_half_refuses(self):
        self.stand.write(body={"schema_version": 1})
        with self.assertRaises(pbc.Unmeasured) as caught:
            pbc.measure(self.stand.root, now=_ANCHOR)
        self.assertIn("половины", str(caught.exception))

    def test_a_member_that_is_not_a_dict_refuses_instead_of_skipping(self):
        self.stand.write(body={"artifacts": ["строка вместо записи"]})
        with self.assertRaises(pbc.Unmeasured) as caught:
            pbc.measure(self.stand.root, now=_ANCHOR)
        self.assertIn("не словарь", str(caught.exception))

    def test_an_entry_without_its_name_refuses_because_the_address_is_unknown(self):
        self.stand.write(body={"artifacts": [{"notes": "ADR-549"}]})
        with self.assertRaises(pbc.Unmeasured) as caught:
            pbc.measure(self.stand.root, now=_ANCHOR)
        self.assertIn("адрес привязки", str(caught.exception))

    def test_main_returns_two_and_says_nothing_was_said(self):
        code = pbc.main(["--root", str(self.stand.root)])
        self.assertEqual(code, 2)

    def test_run_writes_the_refusal_instead_of_crashing_the_bridge(self):
        result = pbc.run(root=self.stand.root, data_dir=self.stand.root / "data",
                         now=_ANCHOR)
        doc = json.loads(Path(result["artifact"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("reason", doc)
        self.assertIn("generated_at", doc)


class ReportNeverPassesOffAbsenceAsCleanliness(_StandCase):

    def test_report_of_a_refusal_says_NOT_MEASURED(self):
        lines = pbc.report({"status": "UNMEASURED", "reason": "конституция не прочитана"})
        self.assertTrue(lines[0].startswith("НЕ ИЗМЕРЕНО"))
        self.assertFalse(any("держится ПРОЗОЙ" in line for line in lines))

    def test_a_doc_without_the_places_list_is_NOT_MEASURED_not_all_in_field(self):
        """Перечня мест нет ⇒ подставить нули значило бы напечатать «всё в поле»."""
        lines = pbc.report({"status": "OK", "population": 9, "on_prose": 9})
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines))
        self.assertFalse(any("в поле 0" in line for line in lines))

    def test_report_names_every_kind_and_its_parsers(self):
        self.stand.artifact("data/a.json", notes="ADR-549, цикл #762")
        doc = self.stand.measure()
        text = "\n".join(pbc.report(doc))
        self.assertIn("род `adr`", text)
        self.assertIn("род `cycle`", text)
        self.assertIn("НИ ОДНОГО", text)
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)

    def test_format_report_indents_for_the_office_step(self):
        self.stand.artifact("data/a.json", notes="ADR-549")
        doc = self.stand.measure()
        self.assertTrue(all(line.startswith("   ") for line in pbc.format_report(doc)))


class ExitCodesSeparateFindingFromClean(_StandCase):

    def test_prose_population_makes_main_return_one(self):
        self.stand.artifact("data/a.json", notes="ADR-549")
        self.stand.write()
        self.assertEqual(pbc.main(["--root", str(self.stand.root)]), 1)

    def test_everything_in_a_field_makes_main_return_zero(self):
        self.stand.agent("com.spa.a", governed_by=["ADR-066"], notes="без ссылок")
        self.stand.write()
        self.assertEqual(pbc.main(["--root", str(self.stand.root)]), 0)

    def test_run_writes_the_artifact_with_its_own_timestamp(self):
        self.stand.artifact("data/a.json", notes="ADR-549")
        self.stand.write()
        result = pbc.run(root=self.stand.root, data_dir=self.stand.root / "data",
                         now=_ANCHOR)
        doc = json.loads(Path(result["artifact"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "OK")
        self.assertEqual(doc["generated_at"], _ANCHOR.isoformat())
        self.assertTrue(result["artifact"].endswith(pbc.ARTIFACT))


# ──────────────────────────── живое дерево ───────────────────────────────

class TheLiveConstitution(unittest.TestCase):
    """Замер на НАСТОЯЩЕМ дереве — иначе стенд проверял бы только стенд."""

    @classmethod
    def setUpClass(cls):
        cls.doc = pbc.measure(_REPO, now=_ANCHOR)

    def test_the_population_is_not_empty_and_adds_up(self):
        self.assertEqual(self.doc["population"], len(self.doc["rows"]))
        self.assertEqual(sum(self.doc["places"].values()), self.doc["population"])
        self.assertGreater(self.doc["population"], 0)

    def test_every_verdict_comes_from_the_declared_sets(self):
        places = {pbc.IN_FIELD, pbc.IN_BOTH, pbc.FIELD_BYPASSED, pbc.NO_FIELD}
        self.assertTrue(all(row["place"] in places for row in self.doc["rows"]))
        verdicts = {pbc.BINDING_PARSER, pbc.TEXT_CONSUMER, pbc.READER_UNMEASURED}
        self.assertTrue(all(row["verdict"] in verdicts
                            for row in self.doc["prose_readers"]))

    def test_the_only_prose_parser_of_the_system_is_found(self):
        """Положительный контроль трассировки на живом коде.

        `s49_criterion_price` читает заметку в одной функции, а образец ``§49``
        применяет в другой. Если шаг «вызов своей функции» сломается, этот тест
        покраснеет — и именно так он и должен себя вести.
        """
        parsers = {row["module"]: row["kinds"] for row in self.doc["prose_readers"]
                   if row["verdict"] == pbc.BINDING_PARSER}
        self.assertIn("spa_core/monitoring/s49_criterion_price.py", parsers)
        self.assertIn("s49", parsers["spa_core/monitoring/s49_criterion_price.py"])

    def test_the_field_axis_finds_more_readers_than_the_prose_axis_parsers(self):
        """Цена прозы, посчитанная в читателях: ключ читают, прозу разбирают редко."""
        field = self.doc["reader_tally"][pbc.FIELD_KEY][pbc.KEY_READER]
        parsers = self.doc["reader_tally"][pbc.PROSE_KEY][pbc.BINDING_PARSER]
        self.assertGreaterEqual(field, parsers)

    def test_the_instrument_declares_its_own_blindness(self):
        self.assertTrue(self.doc["not_reported"])
        self.assertTrue(all(isinstance(line, str) and line
                            for line in self.doc["not_reported"]))


if __name__ == "__main__":
    unittest.main()
