"""Перепись входов, собранных ВЫЗОВОМ: контроль на КАЖДУЮ дверь, в обе стороны.

Заказ **G45 п. 1** приказа владельца «Portfolio CIO», решение — ADR-421.

## Почему сцены, а не живое дерево

Вердикт переписи зависит от ДЕРЕВА (`present_here` спрашивает файловую
систему), поэтому проверять её на рабочем репозитории значило бы привязать
тест к тому, какие каталоги сегодня лежат рядом — ровно класс
«вердикт решает окружение». Каждая сцена строится в одноразовом каталоге и
ломает РОВНО ОДНО своё условие; живое `data/` не читается ни одной проверкой.

## Контроль в обе стороны

У каждой двери есть парная сцена: та же сцена БЕЗ защиты обязана дать другой
вердикт. Сцена, зелёная при любой защите, доказывала бы только то, что разбор
дошёл до конца.

Литеральных дат нет вовсе: время у прибора — вход (`now=`).
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — литерал ровно один (`_NOW`), и он не «сегодня», а ЯКОРЬ:
# каждая сцена строит своё дерево заново и отметок времени не несёт вовсе, а сам якорь
# уезжает параметром в `C.measure(root, now=_NOW)` и `C.run(root, now=_NOW)`. Стенных часов
# ни одна проверка не спрашивает, поэтому от сдвига календаря вердикт не зависит ничем.
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import call_sourced_input_census as C

_NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)   # время — ВХОД, не часы


def _tree(guard_source: str, *, dirs=(), files=()) -> Path:
    """Одноразовое дерево: каталог сторожей + названные каталоги и файлы."""
    root = Path(tempfile.mkdtemp(prefix="csi_scene_"))
    (root / "tests").mkdir()
    (root / "tests" / "test_scene.py").write_text(guard_source, encoding="utf-8")
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
    for f, body in files:
        target = root / f
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


def _rows(root: Path):
    return C.measure(root, now=_NOW)["rows"]


def _one(root: Path) -> dict:
    rows = _rows(root)
    assert len(rows) == 1, f"сцена обязана дать РОВНО одну строку, дала {len(rows)}"
    return rows[0]


_HEAD = "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"


class DoorNone(unittest.TestCase):
    """Проверки отсутствия нет вовсе."""

    SRC = _HEAD + """
def test_files():
    for p in (ROOT / "payload").rglob("*.json"):
        assert p.stat().st_size > 0
"""

    def test_present_path_is_latent_not_a_finding(self):
        row = _one(_tree(self.SRC, dirs=("payload",)))
        self.assertEqual(row["door"], C.DOOR_NONE)
        self.assertEqual(row["present_here"], C.PRESENT_YES)
        self.assertFalse(row["finding"],
                         "обход существующего каталога находкой не является — "
                         "иначе перепись объявила бы находкой всякий rglob")

    def test_absent_path_is_a_finding_today(self):
        """ОБРАТНАЯ СТОРОНА той же сцены: нет каталога — нет и наблюдения."""
        row = _one(_tree(self.SRC))
        self.assertEqual(row["door"], C.DOOR_NONE)
        self.assertEqual(row["present_here"], C.PRESENT_NO)
        self.assertTrue(row["finding"])

    def test_the_two_scenes_differ_only_in_the_directory(self):
        """Контроль на украшение: вердикт двинул КАТАЛОГ, а не текст сцены."""
        with_dir = _one(_tree(self.SRC, dirs=("payload",)))
        without = _one(_tree(self.SRC))
        self.assertEqual(with_dir["door"], without["door"])
        self.assertNotEqual(with_dir["finding"], without["finding"])


class DoorRefuses(unittest.TestCase):
    def test_skip_on_absent_directory(self):
        src = _HEAD + """
import pytest

def test_files():
    base = ROOT / "payload"
    if not base.is_dir():
        pytest.skip("нет каталога — смотреть нечего")
    for p in base.rglob("*.json"):
        assert p.stat().st_size > 0
"""
        row = _one(_tree(src))
        self.assertEqual(row["door"], C.DOOR_REFUSES)
        self.assertIn("skip", row["door_evidence"])
        self.assertFalse(row["finding"])

    def test_raise_counts_as_refusal(self):
        src = _HEAD + """
def test_files():
    base = ROOT / "payload"
    if not base.is_dir():
        raise AssertionError("каталога нет")
    for p in base.rglob("*.json"):
        assert p
"""
        self.assertEqual(_one(_tree(src))["door"], C.DOOR_REFUSES)

    def test_unittest_assertion_is_a_refusal_too(self):
        """Замер 19.09: контроль на вхолостую у нас пишется `self.assertTrue(...)`.

        Перепись, знавшая только оператор `assert`, объявила находкой исправного
        сторожа `test_agent_servers_bind_loopback` — и это поймал прогон, а не
        чтение. Проверка закрепляет ИМЕННО ту форму.
        """
        src = _HEAD + """
import unittest

def _collect():
    base = ROOT / "payload"
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*.json")]

class T(unittest.TestCase):
    def test_rule(self):
        for p in _collect():
            self.assertTrue(p.exists())

    def test_not_vacuous(self):
        self.assertTrue(_collect(), "ни одного файла — проверка выше вхолостую")
"""
        row = _one(_tree(src, dirs=("payload",)))
        self.assertEqual(row["door"], C.DOOR_REFUSES)
        self.assertIn("assertTrue", row["door_evidence"])

    def test_without_that_control_the_same_scene_is_a_finding(self):
        """ОБРАТНАЯ СТОРОНА: снят ровно контроль на вхолостую — вердикт сменился."""
        src = _HEAD + """
import unittest

def _collect():
    base = ROOT / "payload"
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*.json")]

class T(unittest.TestCase):
    def test_rule(self):
        for p in _collect():
            self.assertTrue(p.exists())
"""
        row = _one(_tree(src, dirs=("payload",)))
        self.assertEqual(row["door"], C.DOOR_EMPTY)
        self.assertTrue(row["finding"])

    def test_two_hop_sentinel_is_followed_to_the_caller(self):
        """Дверь может стоять на два шага: помощник вернул `None`, отказал звавший."""
        src = _HEAD + """
import json, pytest
LOG = ROOT / "payload" / "log.jsonl"

def _load():
    if not LOG.exists():
        return None
    return [json.loads(ln) for ln in LOG.read_text().splitlines() if ln.strip()]

def test_rule():
    rows = _load()
    if rows is None:
        pytest.skip("журнала нет")
    assert rows
"""
        row = _one(_tree(src))
        self.assertEqual(row["door"], C.DOOR_REFUSES)
        self.assertIn("_load()", row["door_evidence"])

    def test_the_same_sentinel_unhandled_is_not_a_refusal(self):
        """ОБРАТНАЯ СТОРОНА: часовой возвращается, звавший его не спрашивает."""
        src = _HEAD + """
import json
LOG = ROOT / "payload" / "log.jsonl"

def _load():
    if not LOG.exists():
        return []
    return [json.loads(ln) for ln in LOG.read_text().splitlines() if ln.strip()]

def test_rule():
    rows = _load()
    for row in rows:
        assert "id" in row
"""
        row = _one(_tree(src))
        self.assertEqual(row["door"], C.DOOR_EMPTY)
        self.assertTrue(row["finding"])


class DoorSubstitutes(unittest.TestCase):
    SRC = _HEAD + """
import json
LOG = ROOT / "payload" / "log.jsonl"

def test_rule(tmp_path):
    if LOG.exists():
        rows = [json.loads(ln) for ln in LOG.read_text().splitlines() if ln.strip()]
    else:
        fixture = tmp_path / "log.jsonl"
        fixture.write_text('{"id": 1}\\n')
        rows = [{"id": 1}]
    assert all("id" in r for r in rows)
"""

    def test_fixture_fallback_is_a_finding_even_when_the_path_is_present(self):
        row = _one(_tree(self.SRC, files=(("payload/log.jsonl", '{"id": 1}\n'),)))
        self.assertEqual(row["door"], C.DOOR_SUBSTITUTES)
        self.assertEqual(row["present_here"], C.PRESENT_YES)
        self.assertTrue(row["finding"],
                        "подстановка — находка ВСЕГДА: предмет меняется молча, "
                        "а оба исхода дают passed")

    def test_declaring_the_fallback_in_prose_does_not_change_the_verdict(self):
        """Инв. #17: докстрока не есть отдельное ЗНАЧЕНИЕ исхода."""
        src = self.SRC.replace(
            'def test_rule(tmp_path):\n',
            'def test_rule(tmp_path):\n    """Falls back to a hermetic fixture."""\n')
        row = _one(_tree(src, files=(("payload/log.jsonl", '{"id": 1}\n'),)))
        self.assertEqual(row["door"], C.DOOR_SUBSTITUTES)
        self.assertTrue(row["finding"])
        self.assertTrue(row["declared_in_docstring"],
                        "объявление обязано быть ЗАПИСАНО — оно делит осознанный "
                        "приём и недосмотр на разные карточки")

    def test_undeclared_fallback_carries_an_empty_declaration_field(self):
        row = _one(_tree(self.SRC, files=(("payload/log.jsonl", '{"id": 1}\n'),)))
        self.assertEqual(row["declared_in_docstring"], "")


class DoorElsewhere(unittest.TestCase):
    """Пустой вход краснит модуль — но краснотой СОСЕДА, не потребителя."""

    SRC = _HEAD + """
BASE = {"a.md", "b.md"}

def _collect():
    base = ROOT / "payload"
    if not base.is_dir():
        return set()
    return {p.name for p in base.iterdir()}

def test_offenders():
    offenders = sorted(n for n in _collect() if n.startswith("x"))
    assert not offenders

def test_no_ghosts():
    ghosts = sorted(n for n in BASE if n not in _collect())
    assert not ghosts
"""

    def test_neighbour_inversion_is_named_and_is_not_a_finding(self):
        row = _one(_tree(self.SRC, dirs=("payload",)))
        self.assertEqual(row["door"], C.DOOR_ELSEWHERE)
        self.assertFalse(row["finding"])
        self.assertIn("нет в перечне", row["door_evidence"])

    def test_without_the_ghost_neighbour_the_same_scene_is_a_finding(self):
        """ОБРАТНАЯ СТОРОНА: убран ровно сосед-инвертор."""
        src = self.SRC[:self.SRC.index("def test_no_ghosts")]
        row = _one(_tree(src, dirs=("payload",)))
        self.assertEqual(row["door"], C.DOOR_EMPTY)
        self.assertTrue(row["finding"])


class PopulationBoundaries(unittest.TestCase):
    def test_fixture_directory_is_excluded_and_counted(self):
        src = _HEAD + """
def test_rule(tmp_path):
    (tmp_path / "a.json").write_text("{}")
    for p in tmp_path.iterdir():
        assert p.suffix == ".json"
"""
        doc = C.measure(_tree(src), now=_NOW)
        self.assertEqual(doc["rows"], [])
        self.assertEqual(doc["places"][C.PLACE_FIXTURE], 1,
                         "исключение обязано быть ВИДИМЫМ, а не молчаливым")

    def test_missing_root_and_rootless_tree_give_different_reasons(self):
        """Два «не измерено» — две причины. Иначе они неразличимы (инв. #17).

        Батарея мутаций показала, что одного `assertRaises` мало: отказ
        приходит и от ввезённого читателя населения, поэтому снятие СВОЕЙ
        проверки корня не меняло ни одного вердикта. Различает их ПРИЧИНА.
        """
        missing = Path(tempfile.mkdtemp(prefix="csi_gone_")) / "нет-такого"
        rootless = Path(tempfile.mkdtemp(prefix="csi_rootless_"))
        with self.assertRaises(C.NotMeasured) as gone:
            C.measure(missing, now=_NOW)
        with self.assertRaises(C.NotMeasured) as empty:
            C.measure(rootless, now=_NOW)
        self.assertIn("корень дерева не прочитан", str(gone.exception))
        self.assertIn("сторож", str(empty.exception))
        self.assertNotEqual(str(gone.exception), str(empty.exception))

    def test_ast_walk_is_not_a_tree_scan(self):
        src = _HEAD + """
import ast

def test_rule():
    tree = ast.parse("x = 1")
    for node in ast.walk(tree):
        assert node is not None
"""
        doc = C.measure(_tree(src), now=_NOW)
        self.assertEqual(doc["sites_seen"], 0,
                         "разбор дерева исходника источником перечня не является")

    def test_unresolved_path_is_a_third_outcome_not_a_zero(self):
        src = _HEAD + """
def _scan(base):
    for p in base.rglob("*.py"):
        assert p
"""
        doc = C.measure(_tree(src), now=_NOW)
        self.assertEqual(doc["rows"], [])
        self.assertEqual(doc["places"][C.PLACE_UNRESOLVED], 1)
        self.assertAlmostEqual(doc["unresolved_share"], 1.0)

    def test_report_names_the_unresolved_share(self):
        """Перепись без доли неразобранного читать нельзя — доля в отчёте."""
        src = _HEAD + """
def _scan(base):
    for p in base.rglob("*.py"):
        assert p
"""
        lines = C.report(C.measure(_tree(src), now=_NOW))
        self.assertTrue(any("НЕ ВЫЧИСЛЕН путь" in ln for ln in lines))

    def test_path_outside_the_repository_is_its_own_class(self):
        src = _HEAD + """
from pathlib import Path

def test_rule():
    for p in Path("/etc").rglob("*.conf"):
        assert p
"""
        doc = C.measure(_tree(src), now=_NOW)
        self.assertEqual(doc["places"][C.PLACE_OUTSIDE], 1)
        self.assertEqual(doc["rows"], [])

    def test_wrappers_do_not_split_the_population(self):
        """`sorted(...)` и `.splitlines()` перечень переупаковывают, не рождают."""
        src = _HEAD + """
def test_rule():
    for p in sorted((ROOT / "payload").rglob("*.json")):
        assert p

def test_lines():
    for line in (ROOT / "payload" / "x.txt").read_text().splitlines():
        assert line
"""
        doc = C.measure(_tree(src, dirs=("payload",)), now=_NOW)
        kinds = sorted(r["kind"] for r in doc["rows"])
        self.assertEqual(kinds, [C.KIND_READ, C.KIND_TREE])

    def test_unreadable_guard_is_recorded_not_dropped(self):
        root = _tree(_HEAD)
        (root / "tests" / "test_broken.py").write_text("def (:\n", encoding="utf-8")
        doc = C.measure(root, now=_NOW)
        self.assertEqual([u["guard"] for u in doc["unreadable"]],
                         ["tests/test_broken.py"])
        self.assertIn("SyntaxError", doc["unreadable"][0]["reason"])


class ThirdOutcome(unittest.TestCase):
    def test_tree_without_guard_directories_refuses_loudly(self):
        root = Path(tempfile.mkdtemp(prefix="csi_empty_"))
        with self.assertRaises(C.NotMeasured):
            C.measure(root, now=_NOW)

    def test_run_writes_an_unmeasured_document_not_an_empty_census(self):
        root = Path(tempfile.mkdtemp(prefix="csi_empty_"))
        dest = root / "out.json"
        outcome = C.run(root, dest=dest, now=_NOW)
        self.assertFalse(outcome["measured"])
        doc = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertTrue(doc["reason"])
        self.assertEqual(doc["rows"], [])

    def test_report_of_an_unmeasured_document_says_so_first(self):
        root = Path(tempfile.mkdtemp(prefix="csi_empty_"))
        lines = C.report(C.run(root, write=False, now=_NOW)["doc"])
        self.assertTrue(lines[0].startswith("НЕ ИЗМЕРЕНО"))

    def test_exit_codes_separate_the_three_outcomes(self):
        clean = _tree(_HEAD + """
import pytest

def test_rule():
    base = ROOT / "payload"
    if not base.is_dir():
        pytest.skip("нет каталога")
    for p in base.rglob("*.json"):
        assert p
""")
        finding = _tree(DoorSubstitutes.SRC,
                        files=(("payload/log.jsonl", '{"id": 1}\n'),))
        empty = Path(tempfile.mkdtemp(prefix="csi_empty_"))
        self.assertEqual(C.main(["--root", str(clean), "--no-write"]), 0)
        self.assertEqual(C.main(["--root", str(finding), "--no-write"]), 1)
        self.assertEqual(C.main(["--root", str(empty), "--no-write"]), 2)


class TimeIsAnInput(unittest.TestCase):
    def test_generated_at_comes_from_the_argument(self):
        doc = C.measure(_tree(_HEAD), now=_NOW)
        self.assertEqual(doc["generated_at"], _NOW.isoformat())


if __name__ == "__main__":
    unittest.main()
