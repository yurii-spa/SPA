"""Приёмка прибора заказа #567 — утверждения, судящие о структуре ПОДСТРОКОЙ.

Каждый положительный контроль здесь — воспроизведение настоящей аварии, а не
украшение:

* сцена `truncating` — буквально дефект приёмки ADR-333
  (`assertIn('"x": ("status", "counts",', src)`): снятие ключа за концом
  литерала оставляло тест зелёным;
* сцена `stable` — ОБРАТНЫЙ контроль к ней: без него находка висела бы над
  любым литералом со скобкой;
* сцена «две области видимости» — дефект ПЕРВОЙ редакции самого прибора:
  плоский словарь «имя → зов чтения» отдавал всем сайтам ПОСЛЕДНЕГО соседа,
  то есть приписывал утверждению чужой файл;
* сцена «кириллица перед структурой» — урок `ast.col_offset` (смещение в
  БАЙТАХ): символьная нарезка съела бы часть узла и замер бы онемел;
* сцены `existence_only` и «отрицательный предикат» — ловушка №1 заказа:
  сложить их с обрывом значило бы уверенно ответить не на тот вопрос.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import substring_structure_assertions as M

REPO = Path(__file__).resolve().parents[2]


def _tree(tmp: Path, *, neighbour: str, check: str,
          neighbour_rel: str = "spa_core/monitoring/n.py",
          check_rel: str = "spa_core/tests/test_probe.py") -> Path:
    nb = tmp / neighbour_rel
    nb.parent.mkdir(parents=True, exist_ok=True)
    (nb.parent / "__init__.py").write_text("", encoding="utf-8")
    nb.write_text(neighbour, encoding="utf-8")
    ck = tmp / check_rel
    ck.parent.mkdir(parents=True, exist_ok=True)
    ck.write_text(check, encoding="utf-8")
    return tmp


_NEIGHBOUR_SCHEMA = '''\
_READ_SCHEMA = {
    "a.json": ("status", "counts", "blindness"),
}
'''


class TestTheAccidentReplayed(unittest.TestCase):
    """ADR-333: подстрока, обрывающаяся на середине кортежа."""

    def _measure(self, check_src: str, neighbour: str = _NEIGHBOUR_SCHEMA) -> dict:
        with TemporaryDirectory() as td:
            root = _tree(Path(td), neighbour=neighbour, check=check_src)
            return M.measure(root)

    def test_a_literal_cut_mid_tuple_is_proven_truncating(self):
        doc = self._measure('''\
from pathlib import Path
import unittest

class T(unittest.TestCase):
    def test_schema(self):
        src = (Path(__file__).resolve().parents[2]
               / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
        self.assertIn('"a.json": ("status", "counts",', src)
''')
        self.assertEqual(doc["counts"]["population"], 1, doc["findings"])
        self.assertEqual(doc["counts"]["truncating"], 1, doc["findings"])
        self.assertEqual(doc["status"], M.STATUS_CRITICAL)

    def test_the_fix_is_proven_stable_reverse_control(self):
        """Обратный контроль: литерал, покрывающий кортеж ДО КОНЦА."""
        doc = self._measure('''\
from pathlib import Path
import unittest

class T(unittest.TestCase):
    def test_schema(self):
        src = (Path(__file__).resolve().parents[2]
               / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
        self.assertIn('"a.json": ("status", "counts", "blindness")', src)
''')
        self.assertEqual(doc["counts"]["population"], 1, doc["findings"])
        self.assertEqual(doc["counts"]["truncating"], 0, doc["findings"])
        self.assertEqual(doc["counts"]["stable"], 1, doc["findings"])
        self.assertEqual(doc["status"], M.STATUS_OK)

    def test_the_two_verdicts_come_from_the_same_code_path(self):
        """Оба исхода достижимы — значит замер не истинен по построению."""
        cut = self._measure('''\
from pathlib import Path
import unittest

class T(unittest.TestCase):
    def test_schema(self):
        src = (Path(__file__).resolve().parents[2]
               / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
        self.assertIn('"a.json": ("status", "counts",', src)
''')
        whole = self._measure('''\
from pathlib import Path
import unittest

class T(unittest.TestCase):
    def test_schema(self):
        src = (Path(__file__).resolve().parents[2]
               / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
        self.assertIn('"a.json": ("status", "counts", "blindness")', src)
''')
        self.assertNotEqual(cut["counts"]["truncating"], whole["counts"]["truncating"])


class TestTrapOneCountedApart(unittest.TestCase):
    """Ловушка №1 заказа: не всякий `assertIn` — дефект."""

    def _measure(self, check_src: str) -> dict:
        with TemporaryDirectory() as td:
            root = _tree(Path(td), neighbour=_NEIGHBOUR_SCHEMA, check=check_src)
            return M.measure(root)

    def test_a_container_haystack_is_not_the_subject(self):
        doc = self._measure('''\
import unittest

class T(unittest.TestCase):
    def test_keys(self):
        self.assertIn("a.json", {"a.json": 1, "b.json": 2})
''')
        self.assertEqual(doc["counts"]["population"], 0, doc["findings"])
        self.assertEqual(doc["haystack_kinds"].get("container"), 1, doc["haystack_kinds"])

    def test_a_negative_predicate_is_not_the_subject(self):
        doc = self._measure('''\
from pathlib import Path
import unittest

class T(unittest.TestCase):
    def test_absent(self):
        src = (Path(__file__).resolve().parents[2]
               / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
        self.assertNotIn('"z.json": ("status",', src)
''')
        self.assertEqual(doc["counts"]["population"], 0, doc["findings"])
        self.assertTrue(any("ОТРИЦАТЕЛЬНЫЙ" in k for k in doc["excluded_classes"]),
                        doc["excluded_classes"])

    def test_a_literal_stopping_at_the_open_bracket_claims_existence(self):
        doc = self._measure('''\
from pathlib import Path
import unittest

class T(unittest.TestCase):
    def test_call_present(self):
        src = (Path(__file__).resolve().parents[2]
               / "spa_core" / "monitoring" / "m.py").read_text(encoding="utf-8")
        self.assertIn("wire_it(", src)
''')
        # соседа m.py нет — сайт обязан выпасть с НАЗВАННОЙ причиной, а не молча
        self.assertEqual(doc["counts"]["population"], 0, doc["findings"])
        self.assertTrue(doc["excluded_classes"], doc["excluded_classes"])

    def test_existence_only_is_its_own_verdict_not_truncation(self):
        with TemporaryDirectory() as td:
            root = _tree(Path(td),
                         neighbour='def make(a, b):\n    return a\n\nwire_it = make\nwire_it(1, 2)\n',
                         check='''\
from pathlib import Path
import unittest

class T(unittest.TestCase):
    def test_call_present(self):
        src = (Path(__file__).resolve().parents[2]
               / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
        self.assertIn("wire_it(", src)
''')
            doc = M.measure(root)
        self.assertEqual(doc["counts"]["population"], 1, doc["findings"])
        self.assertEqual(doc["counts"]["existence_only"], 1, doc["findings"])
        self.assertEqual(doc["counts"]["truncating"], 0, doc["findings"])


class TestScopeOfTheNeighbour(unittest.TestCase):
    """Дефект ПЕРВОЙ редакции прибора: плоский словарь имён отдавал чужой файл."""

    def test_two_functions_binding_the_same_name_get_their_own_neighbour(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "spa_core" / "monitoring").mkdir(parents=True)
            (tmp / "spa_core" / "monitoring" / "__init__.py").write_text("", encoding="utf-8")
            (tmp / "spa_core" / "monitoring" / "one.py").write_text(
                'CFG = {"k": ("a", "b")}\n', encoding="utf-8")
            (tmp / "spa_core" / "monitoring" / "two.py").write_text(
                'CFG = {"k": ("a", "b")}\n', encoding="utf-8")
            (tmp / "spa_core" / "tests").mkdir(parents=True)
            (tmp / "spa_core" / "tests" / "test_probe.py").write_text('''\
from pathlib import Path

_MON = Path(__file__).resolve().parents[1] / "monitoring"

def test_one():
    src = (_MON / "one.py").read_text(encoding="utf-8")
    assert '"k": ("a",' in src

def test_two():
    src = (_MON / "two.py").read_text(encoding="utf-8")
    assert '"k": ("a",' in src
''', encoding="utf-8")
            doc = M.measure(tmp)
        neighbours = sorted(s["neighbour"] for s in doc["population"])
        self.assertEqual(
            neighbours,
            ["spa_core/monitoring/one.py", "spa_core/monitoring/two.py"],
            f"плоский словарь имён приписал бы обоим ОДНОГО соседа: {neighbours}")


    def test_within_one_scope_the_LAST_read_above_the_site_wins(self):
        """Остаток, вскрытый выжившей мутацией батареи #568.

        Область видимости отделяет функции друг от друга, но ВНУТРИ одной
        функции `src` может быть перечитан дважды. Правило «берём последнее
        присваивание ВЫШЕ сайта» до этого теста не было закреплено ничем:
        мутация, снявшая условие `line <= site_line`, пережила батарею — и это
        утверждение о ТЕСТАХ, а не о коде.
        """
        probe = 'from pathlib import Path\n\n_MON = Path(__file__).resolve().parents[1] / "monitoring"\n\ndef test_both():\n    src = (_MON / "one.py").read_text(encoding="utf-8")\n    assert \'"k": ("a",\' in src\n    src = (_MON / "two.py").read_text(encoding="utf-8")\n    assert \'"k": ("b",\' in src\n'
        with TemporaryDirectory() as td:
            tmp = Path(td)
            mon = tmp / "spa_core" / "monitoring"
            mon.mkdir(parents=True)
            (mon / "__init__.py").write_text("", encoding="utf-8")
            (mon / "one.py").write_text('CFG = {"k": ("a", "b")}\n', encoding="utf-8")
            (mon / "two.py").write_text('CFG = {"k": ("b", "c")}\n', encoding="utf-8")
            tests = tmp / "spa_core" / "tests"
            tests.mkdir(parents=True)
            (tests / "test_probe.py").write_text(probe, encoding="utf-8")
            doc = M.measure(tmp)
        by_line = {s["line"]: s["neighbour"] for s in doc["population"]}
        self.assertEqual(by_line.get(7), "spa_core/monitoring/one.py",
                         f"первый сайт обязан читать ПЕРВОГО соседа: {by_line}")
        self.assertEqual(by_line.get(9), "spa_core/monitoring/two.py",
                         f"второй сайт обязан читать ВТОРОГО соседа: {by_line}")


    def test_a_name_bound_in_a_SIBLING_function_is_never_borrowed(self):
        """Вторая половина разрешения по области видимости, отдельным замером.

        Правило «последнее присваивание ВЫШЕ сайта» и фильтр ОБЛАСТИ ВИДИМОСТИ
        избыточны на обычной паре функций — мутация, снявшая фильтр, пережила
        батарею #568 именно поэтому. Здесь они РАЗДЕЛЕНЫ: у сайта в `test_b`
        своего присваивания выше НЕТ, а в соседней функции — есть. Заимствовать
        его значило бы приписать утверждению чужой файл; правильный ответ —
        отказ с названной причиной, а не сосед.
        """
        probe = 'from pathlib import Path\n\n_MON = Path(__file__).resolve().parents[1] / "monitoring"\n\ndef test_a():\n    src = (_MON / "one.py").read_text(encoding="utf-8")\n    assert src\n\ndef test_b():\n    assert \'"k": ("a",\' in src\n    src = (_MON / "two.py").read_text(encoding="utf-8")\n'
        with TemporaryDirectory() as td:
            tmp = Path(td)
            mon = tmp / "spa_core" / "monitoring"
            mon.mkdir(parents=True)
            (mon / "__init__.py").write_text("", encoding="utf-8")
            (mon / "one.py").write_text('CFG = {"k": ("a", "b")}\n', encoding="utf-8")
            (mon / "two.py").write_text('CFG = {"k": ("a", "b")}\n', encoding="utf-8")
            tests = tmp / "spa_core" / "tests"
            tests.mkdir(parents=True)
            (tests / "test_probe.py").write_text(probe, encoding="utf-8")
            doc = M.measure(tmp)
        self.assertEqual(
            [s.get("neighbour") for s in doc["population"]], [],
            "имя, привязанное в СОСЕДНЕЙ функции, заимствовано — "
            "утверждению приписан чужой файл")
        self.assertTrue(doc["excluded_classes"],
                        "отказ обязан быть НАЗВАН, а не молчалив")


class TestByteOffsets(unittest.TestCase):
    """`ast.col_offset` — смещение в БАЙТАХ; символьная нарезка онемела бы."""

    def test_cyrillic_before_the_structure_does_not_break_the_probe(self):
        neighbour = (
            '# комментарий с кириллицей, много букв, чтобы сместить байты\n'
            'ТАБЛИЦА = {"ключ": ("статус", "счётчики", "слепота")}\n')
        with TemporaryDirectory() as td:
            root = _tree(Path(td), neighbour=neighbour, check='''\
from pathlib import Path

def test_it():
    src = (Path(__file__).resolve().parents[2]
           / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
    assert '"ключ": ("статус", "счётчики",' in src
''')
            doc = M.measure(root)
        self.assertEqual(doc["counts"]["population"], 1, doc["findings"])
        self.assertEqual(doc["counts"]["truncating"], 1, doc["findings"])


class TestThirdOutcome(unittest.TestCase):
    """«Не измерено» никогда не выдаётся за «устойчиво»."""

    def test_several_matches_of_the_literal_refuse_a_verdict(self):
        neighbour = ('A = {"k": ("a", "b")}\n'
                     'B = {"k": ("a", "b")}\n')
        with TemporaryDirectory() as td:
            root = _tree(Path(td), neighbour=neighbour, check='''\
from pathlib import Path

def test_it():
    src = (Path(__file__).resolve().parents[2]
           / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
    assert '"k": ("a",' in src
''')
            doc = M.measure(root)
        self.assertEqual(doc["counts"]["population"], 1, doc["findings"])
        self.assertEqual(doc["counts"]["stable"], 0, doc["findings"])
        self.assertEqual(doc["counts"]["unmeasured"], 1, doc["findings"])
        reason = doc["truncation"]["unmeasured"][0]["reason"]
        self.assertIn("раз", reason)

    def test_an_unparseable_neighbour_refuses_a_verdict(self):
        with TemporaryDirectory() as td:
            nb = Path(td) / "n.py"
            nb.write_text('CFG = {"k": ("a", "b")}\ndef broken(:\n',
                          encoding="utf-8")
            probe = M.truncation_probe('"k": ("a",', nb)
        self.assertEqual(probe["verdict"], "unmeasured")
        self.assertIn("AST", probe["reason"])

    def test_a_missing_neighbour_refuses_a_verdict(self):
        with TemporaryDirectory() as td:
            probe = M.truncation_probe('"k": ("a",', Path(td) / "absent.py")
        self.assertEqual(probe["verdict"], "unmeasured")

    def test_unmeasured_is_counted_apart_from_stable_in_the_doc(self):
        doc = M.measure(REPO)
        self.assertIn("unmeasured", doc["counts"])
        self.assertIn("stable", doc["counts"])
        self.assertNotEqual(id(doc["truncation"]["stable"]),
                            id(doc["truncation"]["unmeasured"]))


class TestMarkers(unittest.TestCase):

    def test_the_three_markers_named_by_the_order(self):
        self.assertEqual(M.literal_markers('"k": ("a",'),
                         ["unclosed_bracket", "trailing_comma", "colon_inside"])
        self.assertEqual(M.literal_markers('plain text'), [])

    def test_a_bracket_inside_a_quote_is_not_an_open_bracket(self):
        self.assertNotIn("unclosed_bracket", M.literal_markers('x = "(" + y'))


class TestRecallRoadIsASuperset(unittest.TestCase):
    """Полнота населения — ОТДЕЛЬНОЕ утверждение, доказанное второй дорогой."""

    def test_every_population_site_is_visible_to_the_recall_road(self):
        doc = M.measure(REPO)
        self.assertEqual(doc["recall"]["population_outside_recall"], [],
                         "надмножество нарушено — сверка не состоялась")

    def test_the_residue_is_reconciled_by_named_reasons(self):
        doc = M.measure(REPO)
        self.assertEqual(doc["counts"]["residue_unreconciled"], 0,
                         doc["recall"]["residue_reasons"])
        self.assertTrue(doc["recall"]["residue_reasons"])


class TestArtifactAndWiring(unittest.TestCase):

    def test_run_writes_the_artifact_and_returns_it(self):
        with TemporaryDirectory() as td:
            root = _tree(Path(td), neighbour=_NEIGHBOUR_SCHEMA, check='''\
import unittest

class T(unittest.TestCase):
    def test_nothing(self):
        self.assertIn("a", ["a"])
''')
            doc = M.run(root=str(root), data_dir=str(root / "data"))
            written = json.loads((root / "data" / M.OUTPUT_FILENAME)
                                 .read_text(encoding="utf-8"))
        self.assertEqual(written["status"], doc["status"])

    def test_the_office_schema_declares_every_top_level_key_BY_NAME(self):
        """Структурно, не подстрокой — ровно тот дефект, что мы и меряем."""
        office = REPO / "scripts" / "consume_office_reports.py"
        tree = ast.parse(office.read_text(encoding="utf-8"))
        schema = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                    and node.target.id == "_READ_SCHEMA":
                schema = node.value
            elif isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "_READ_SCHEMA"
                    for t in node.targets):
                schema = node.value
        self.assertIsNotNone(schema, "_READ_SCHEMA не найден в шаге 0-офис")
        declared = None
        for key, value in zip(schema.keys, schema.values):
            if isinstance(key, ast.Constant) and key.value == M.OUTPUT_FILENAME:
                declared = tuple(e.value for e in value.elts)
        self.assertIsNotNone(declared,
                             f"{M.OUTPUT_FILENAME} не объявлен в схеме шага 0-офис")
        for key in ("status", "counts", "population", "truncation",
                    "haystack_kinds", "findings", "advisory"):
            self.assertIn(key, declared, f"ключ {key} не объявлен схемой")

    def test_the_artifact_has_BOTH_manifest_homes(self):
        """Паспорт артефакта — ДВЕ записи: `artifacts[]` и `produces[]`."""
        manifest = json.loads((REPO / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        blob = json.dumps(manifest, ensure_ascii=False)
        self.assertIn(f"data/{M.OUTPUT_FILENAME}", blob)
        artifacts = [a for a in manifest.get("artifacts", [])
                     if a.get("path") == f"data/{M.OUTPUT_FILENAME}"]
        self.assertEqual(len(artifacts), 1, "нет записи в artifacts[]")
        produced = [
            a for a in manifest.get("agents", [])
            if any(isinstance(x, dict)
                   and x.get("artifact") == f"data/{M.OUTPUT_FILENAME}"
                   for x in (a.get("produces") or []))
        ]
        self.assertEqual(len(produced), 1,
                         "артефакт не назван ни в одном `produces[]` — второй дом пуст")

    def test_the_bridge_stage_calls_this_census(self):
        src = (REPO / "spa_core" / "monitoring" / "findings_bridge.py") \
            .read_text(encoding="utf-8")
        tree = ast.parse(src)
        called = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "run"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "substring_structure_assertions"
            for n in ast.walk(tree))
        self.assertTrue(called, "ступень переписей не зовёт прибор заказа #567")


class TestTheInstrumentMutatesNothing(unittest.TestCase):
    """Возмущение живёт В ПАМЯТИ: ни один файл дерева не меняется."""

    def test_the_neighbour_file_is_byte_identical_after_the_probe(self):
        with TemporaryDirectory() as td:
            root = _tree(Path(td), neighbour=_NEIGHBOUR_SCHEMA, check='''\
from pathlib import Path

def test_it():
    src = (Path(__file__).resolve().parents[2]
           / "spa_core" / "monitoring" / "n.py").read_text(encoding="utf-8")
    assert '"a.json": ("status", "counts",' in src
''')
            nb = root / "spa_core" / "monitoring" / "n.py"
            before = nb.read_bytes()
            M.measure(root)
            self.assertEqual(nb.read_bytes(), before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
