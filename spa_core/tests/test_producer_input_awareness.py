#!/usr/bin/env python3
"""Контроль прибора «знает ли производитель, что читает» (ADR-1024, заказ G1012 п. 1).

Каждая проба здесь — ОДНА сцена на настоящем приборе, и у каждой есть обратная
сторона: сцена, на которой ответ ОБЯЗАН быть другим. Пробы 5, 7 и 8 — прямые
положительные контроли на дефекты, найденные ПРОГОНОМ первой редакции по живому
дереву (`open` в режиме записи числился чтением · короткое ``walk`` объявляло
читателем каталогов каждого разборщика AST · докстринг со слэшем засчитывался
именем файла).

Время, личность процесса и git-окружение здесь не участвуют: прибор читает
только исходники сцены (`.claude/rules/deployment.md` — ни одного литерала даты,
ни одного литерального pid).
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from spa_core.monitoring import edition_remeasure as er
from spa_core.monitoring import producer_input_awareness as pia


def _scene(**modules: str) -> pathlib.Path:
    """Одноразовое дерево: ``имя → исходник``. Возвращает корень."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="pia_scene_"))
    for name, src in modules.items():
        (root / f"{name}.py").write_text(src, encoding="utf-8")
    return root


def _entry(module: str) -> er.Entry:
    return er.Entry(("-m", module, "--root", "{root}"))


def _kind(root: pathlib.Path, artifact: str, module: str) -> str:
    doc = pia.measure(root, entries={artifact: _entry(module)})
    return doc["producers"][0]["kind"]


class ProducerKindTest(unittest.TestCase):
    """Род производителя — это ответ про ЦЕНУ дайджеста."""

    def test_a_producer_that_writes_its_input_names_is_cheap(self) -> None:
        root = _scene(cheap='''
import json
def run(root):
    with open(root + "/data/track_snapshot.json") as f:
        return json.load(f)
''')
        self.assertEqual(pia.NAMES, _kind(root, "a.json", "cheap"))

    def test_a_producer_that_enumerates_a_directory_is_runtime_only(self) -> None:
        """Обратная сторона пробы выше: имя файла есть, но набор — рантаймовый."""
        root = _scene(enum='''
from pathlib import Path
def run(root):
    out = []
    for p in Path(root).glob("*.json"):
        out.append(p.read_text())
    return out
''')
        self.assertEqual(pia.RUNTIME_ONLY, _kind(root, "a.json", "enum"))

    def test_a_computed_path_is_runtime_only_too_because_the_price_is_the_same(self) -> None:
        root = _scene(computed='''
from pathlib import Path
def run(root, key):
    target = Path(root) / (key + "-" + str(len(key)))
    return target.read_text()
''')
        self.assertEqual(pia.RUNTIME_ONLY, _kind(root, "a.json", "computed"))

    def test_a_foreign_process_beats_every_other_kind(self) -> None:
        """Хуже побеждает: часть входов — не файлы, и дайджест их не ухватит."""
        root = _scene(foreign='''
import subprocess
def run(root):
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True)
    with open(root + "/data/x.json") as f:
        return f.read(), head
''')
        self.assertEqual(pia.FOREIGN, _kind(root, "a.json", "foreign"))

    def test_a_producer_with_neither_a_name_nor_a_door_is_unmeasured_not_cheap(self) -> None:
        """Третий исход (инв. #17): читает целиком через помощников ⇒ НЕ ИЗМЕРЕНО."""
        root = _scene(viahelper='''
from helper import load
def run(root):
    return load(root)
''', helper='''
def load(root):
    return {}
''')
        doc = pia.measure(root, entries={"a.json": _entry("viahelper")})
        p = doc["producers"][0]
        self.assertEqual(pia.UNMEASURED, p["kind"])
        self.assertIn("через помощников", p["reason"] or "")


class MeasuredDefectsTest(unittest.TestCase):
    """Три дефекта, найденные ПРОГОНОМ первой редакции по живому дереву."""

    def test_an_open_in_write_mode_is_not_a_read_door(self) -> None:
        """`spa_core/utils/atomic.py` числился дверью ЧТЕНИЯ у шестнадцати."""
        root = _scene(writer='''
import json, os
def save(doc, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    os.replace(tmp, path)
''')
        doc = pia.measure(root, entries={"a.json": _entry("writer")})
        p = doc["producers"][0]
        self.assertEqual([], [s for s in p["sites"] if s["kind"] != pia.S_FOREIGN],
                         "запись не является площадкой чтения")
        self.assertEqual(pia.UNMEASURED, p["kind"])

    def test_a_read_in_the_same_file_stays_a_door_so_the_mode_test_is_not_a_blanket(
            self) -> None:
        """Обратная сторона: в том же файле `open(path, "r")` — настоящая дверь."""
        root = _scene(both='''
import json, os
def save(doc, path):
    with open(path, "w") as f:
        json.dump(doc, f)
def load(path):
    with open(path, "r") as f:
        return json.load(f)
''')
        doc = pia.measure(root, entries={"a.json": _entry("both")})
        kinds = [s["kind"] for s in doc["producers"][0]["sites"]]
        self.assertIn(pia.S_CONDUIT, kinds,
                      "чтение по пути-параметру — проводник, а не слепое чтение")

    def test_ast_walk_is_not_a_directory_door(self) -> None:
        """Калибровка #1162: короткое `walk` дало 48 ложных площадок на 16 модулях."""
        root = _scene(parser='''
import ast
def run(root):
    tree = ast.parse(open(root + "/data/x.json").read())
    return [n for n in ast.walk(tree)]
''')
        doc = pia.measure(root, entries={"a.json": _entry("parser")})
        p = doc["producers"][0]
        self.assertEqual(pia.NAMES, p["kind"])
        self.assertNotIn(pia.S_ENUM, [s["kind"] for s in p["sites"]])

    def test_os_walk_IS_a_directory_door_so_the_name_test_is_not_a_blanket(self) -> None:
        """Обратная сторона: полное точечное имя `os.walk` дверью является."""
        root = _scene(walker='''
import os
def run(root):
    for dirpath, dirs, files in os.walk(root):
        pass
''')
        self.assertEqual(pia.RUNTIME_ONLY, _kind(root, "a.json", "walker"))

    def test_a_docstring_that_contains_a_slash_is_not_a_file_name(self) -> None:
        """Первый прогон засчитал ИМЕНЕМ ФАЙЛА докстринг в 1 574 символа."""
        root = _scene(prose='''
"""Проза про spa_core/utils/atomic.py и про data/track_snapshot.json внутри абзаца,
в котором есть пробелы и перевод строки, и который файлом не является."""
def run(root):
    return 1
''')
        doc = pia.measure(root, entries={"a.json": _entry("prose")})
        self.assertEqual(pia.UNMEASURED, doc["producers"][0]["kind"])
        self.assertEqual(0, doc["producers"][0]["file_names_total"])

    def test_a_bare_name_on_one_line_IS_a_file_name_so_the_form_test_is_not_a_blanket(
            self) -> None:
        """Сцена РАЗЛИЧАЮЩАЯ намеренно: ни одного параметра в выражении пути.

        Первая редакция пробы писала `open(root + "/" + REPORT_REL)`, и путь
        содержал ПАРАМЕТР `root` — площадка выходила проводником, а выписанное
        имя бралось из общего списка литералов модуля. Мутация «свои строковые
        константы не читаются» на такой сцене ВЫЖИВАЛА: разницы не было видно.
        Здесь база — не параметр и сама именем файла не является (`"tmp"`),
        поэтому имя может прийти ТОЛЬКО через константу модуля.
        """
        root = _scene(named='''
REPORT_REL = "data/report.json"
BASE = "tmp"
def run():
    return open(BASE + "/" + REPORT_REL).read()
''')
        doc = pia.measure(root, entries={"a.json": _entry("named")})
        p = doc["producers"][0]
        self.assertEqual(pia.NAMES, p["kind"])
        self.assertIn("data/report.json", p["file_names"])
        site = p["sites"][0]
        self.assertEqual(pia.S_NAMED, site["kind"])
        self.assertIn("data/report.json", site["named"],
                      "имя площадки разрешено через константу модуля")

    def test_a_long_unspaced_literal_with_a_slash_is_not_a_file_name(self) -> None:
        """Вторая половина проверки формы: ПРЕДЕЛ ДЛИНЫ, а не только пробелы.

        Мутация «имя файла не обязано быть коротким» выжила на сцене с
        докстрингом: там хватало пробельного признака. Различающая сцена —
        строка БЕЗ пробелов, со слэшем и длиннее предела: так выглядит
        base64-литерал, и файлом он не является.
        """
        blob = ("YWJjZGVm/Z2hpamts" * 20)  # 340 символов, слэши, ни одного пробела
        self.assertGreater(len(blob), pia._NAME_MAX)
        root = _scene(blob=f'''
TOKEN = "{blob}"
def run():
    return TOKEN
''')
        doc = pia.measure(root, entries={"a.json": _entry("blob")})
        self.assertEqual(pia.UNMEASURED, doc["producers"][0]["kind"])
        self.assertEqual(0, doc["producers"][0]["file_names_total"])

    def test_the_same_literal_under_the_limit_IS_a_file_name(self) -> None:
        """Обратная сторона предела: короткий слэшевый литерал именем является."""
        root = _scene(short='''
TOKEN = "data/short.json"
def run():
    return open(TOKEN).read()
''')
        doc = pia.measure(root, entries={"a.json": _entry("short")})
        self.assertEqual(pia.NAMES, doc["producers"][0]["kind"])

    def test_the_probe_does_not_pass_by_substring(self) -> None:
        """ADR-333: ни одна площадка не берётся текстом исходника."""
        root = _scene(mention='''
"""Этот модуль НЕ зовёт glob, rglob, os.walk, subprocess.run и open."""
# glob( rglob( os.walk( subprocess.run( open(
GLOB_HINT = "glob("
def run(root):
    return GLOB_HINT
''')
        doc = pia.measure(root, entries={"a.json": _entry("mention")})
        self.assertEqual([], doc["producers"][0]["sites"])
        self.assertEqual(pia.UNMEASURED, doc["producers"][0]["kind"])


class SurfaceIsTheNeighboursTableTest(unittest.TestCase):
    """Поверхность объявлена ОДИН раз — у соседа (`.claude/rules/adapters.md`)."""

    def test_the_default_table_is_read_at_call_time_not_at_import(self) -> None:
        """Умолчание-ссылка на изменяемый дом — бомба ADR-1023 § 5."""
        root = _scene(cheap='def run(root):\n    return open("data/x.json").read()\n')
        kept = er.ENTRY
        try:
            er.ENTRY = {"only.json": _entry("cheap")}  # type: ignore[assignment]
            doc = pia.measure(root)
        finally:
            er.ENTRY = kept  # type: ignore[assignment]
        self.assertEqual(["only.json"], [p["artifact"] for p in doc["producers"]])

    def test_the_module_holds_no_second_copy_of_the_member_list(self) -> None:
        src = pathlib.Path(pia.__file__).read_text(encoding="utf-8")
        body = src.split('"""', 2)[-1]  # без докстринга: там ссылки допустимы
        for artifact in er.ENTRY:
            self.assertNotIn(f'"{artifact}"', body,
                             f"член {artifact} выписан в приборе — это вторая копия")

    def test_a_refusal_of_the_neighbour_is_carried_with_its_own_reason(self) -> None:
        root = _scene(cheap='def run(root):\n    return open("data/x.json").read()\n')
        why = "производство требует внешнего действия"
        doc = pia.measure(root, entries={"r.json": er.Entry(refusal=why)})
        p = doc["producers"][0]
        self.assertEqual(pia.REFUSED, p["kind"])
        self.assertEqual(why, p["reason"], "причина берётся у таблицы, не выдумывается")

    def test_an_unresolvable_producer_is_unmeasured_and_names_what_was_sought(
            self) -> None:
        root = _scene(cheap='def run(root):\n    return open("data/x.json").read()\n')
        doc = pia.measure(root, entries={"a.json": _entry("no_such_module")})
        p = doc["producers"][0]
        self.assertEqual(pia.UNMEASURED, p["kind"])
        self.assertIn("no_such_module", p["reason"] or "")

    def test_every_measurable_member_of_the_LIVE_table_resolves_to_a_file(self) -> None:
        """Контроль на ЖИВОЙ поверхности: член, чей модуль не разрешился, —
        дефект таблицы, а не свойство прибора."""
        doc = pia.measure(pathlib.Path(pia.__file__).resolve().parents[2])
        unresolved = [p["artifact"] for p in doc["producers"]
                      if p["kind"] == pia.UNMEASURED
                      and "не разрешился" in (p["reason"] or "")]
        self.assertEqual([], unresolved)


class ThreeOutcomesTest(unittest.TestCase):
    """Коды возврата различают ТРИ исхода, и ни один не выдаётся за другой."""

    def test_all_cheap_is_measured_zero(self) -> None:
        root = _scene(cheap='def run(root):\n    return open("data/x.json").read()\n')
        doc = pia.measure(root, entries={"a.json": _entry("cheap")})
        self.assertEqual("measured_zero", pia.verdict(doc))
        self.assertEqual(0, pia.EXIT_CODES[pia.verdict(doc)])

    def test_a_named_price_is_code_one(self) -> None:
        root = _scene(enum='''
from pathlib import Path
def run(root):
    return [p for p in Path(root).iterdir()]
''')
        doc = pia.measure(root, entries={"a.json": _entry("enum")})
        self.assertEqual("price_named", pia.verdict(doc))
        self.assertEqual(1, pia.EXIT_CODES[pia.verdict(doc)])

    def test_an_unmeasured_member_wins_over_a_named_price(self) -> None:
        """fail-CLOSED: пока хоть один член не измерен, цена не объявлена."""
        root = _scene(enum='''
from pathlib import Path
def run(root):
    return [p for p in Path(root).iterdir()]
''')
        doc = pia.measure(root, entries={"a.json": _entry("enum"),
                                         "b.json": _entry("gone")})
        self.assertEqual("unmeasured", pia.verdict(doc))
        self.assertEqual(2, pia.EXIT_CODES[pia.verdict(doc)])

    def test_an_empty_table_refuses_instead_of_answering_zero(self) -> None:
        root = _scene(cheap='def run(root):\n    return open("data/x.json").read()\n')
        with self.assertRaises(pia.Unmeasured):
            pia.measure(root, entries={})

    def test_a_missing_tree_refuses_instead_of_answering_zero(self) -> None:
        with self.assertRaises(pia.Unmeasured):
            pia.measure("/no/such/tree/at/all", entries={"a.json": _entry("x")})


class ReportNamesThingsTest(unittest.TestCase):
    """ADR-1021 § 6: печать обязана НАЗЫВАТЬ, а не только считать."""

    def test_the_report_names_the_producer_and_the_site(self) -> None:
        root = _scene(enum='''
from pathlib import Path
def run(root):
    return [p for p in Path(root).rglob("*.json")]
''')
        doc = pia.measure(root, entries={"zzz-artifact.json": _entry("enum")})
        text = pia.format_report(doc)
        self.assertIn("zzz-artifact.json", text)
        self.assertIn("enum.py", text)
        self.assertIn("rglob", text)

    def test_the_report_names_the_blind_spot_instead_of_swallowing_it(self) -> None:
        root = _scene(seed='''
import helper
def run(root):
    return helper.load(root)
''', helper='''
def load(root):
    return open(root + "/data/x.json").read()
''')
        doc = pia.measure(root, entries={"a.json": _entry("seed")})
        text = pia.format_report(doc)
        self.assertIn("СЛЕПОЕ МЕСТО", text)
        blind = doc["blind_spot"][0]
        self.assertEqual(1, blind["helpers"])
        self.assertGreaterEqual(blind["read_sites"], 1)

    def test_both_directions_of_the_error_are_printed(self) -> None:
        root = _scene(enum='''
from pathlib import Path
def run(root):
    return [p for p in Path(root).iterdir()]
''')
        doc = pia.measure(root, entries={"a.json": _entry("enum")})
        text = pia.format_report(doc)
        self.assertIn("ПОЛ цены", text)
        self.assertIn("ПОТОЛОК", text)

    def test_the_lever_names_a_helper_shared_by_two_producers(self) -> None:
        root = _scene(one='''
import shared
def run(root):
    return shared.load(root)
''', two='''
import shared
def run(root):
    return shared.load(root)
''', shared='''
def load(root):
    return open(root + "/data/x.json").read()
''')
        doc = pia.measure(root, entries={"a.json": _entry("one"),
                                         "b.json": _entry("two")})
        shared = {row["rel"]: row for row in doc["shared_doors"]}
        self.assertIn("shared.py", shared)
        self.assertEqual(["a.json", "b.json"], shared["shared.py"]["producers"])

    def test_a_helper_of_one_producer_is_not_a_lever(self) -> None:
        """Обратная сторона: рычагом является ОБЩИЙ помощник, а не любой."""
        root = _scene(one='''
import private_helper
def run(root):
    return private_helper.load(root)
''', private_helper='''
def load(root):
    return open(root + "/data/x.json").read()
''')
        doc = pia.measure(root, entries={"a.json": _entry("one")})
        self.assertEqual([], doc["shared_doors"])


class CliTest(unittest.TestCase):
    def test_main_returns_the_verdict_code_of_the_live_tree(self) -> None:
        root = str(pathlib.Path(pia.__file__).resolve().parents[2])
        code = pia.main(["--root", root, "--json"])
        self.assertIn(code, (0, 1, 2))

    def test_main_refuses_a_missing_tree_with_code_two(self) -> None:
        self.assertEqual(2, pia.main(["--root", "/no/such/tree/at/all"]))


if __name__ == "__main__":
    unittest.main()
