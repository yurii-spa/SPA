# LLM_FORBIDDEN
"""Контроли на детектор маркеров `scripts/dead_code_scanner.py::scan_todo_comments`.

Предмет — РАЗЛИЧЕНИЕ МАРКЕРА И ПРОЗЫ, а не счёт находок. Батарея написана по
аварии цикла #1183: сторож `tests/test_dead_code_resolved.py::test_15_todo_count_le_15`
был КРАСНЫМ на контрольном прогоне CI (16 > 15), и пятнадцать из шестнадцати
находок дефектами не были вовсе — детектор искал слова `TODO|FIXME|HACK|XXX` с
`re.IGNORECASE`, а в предметной области SPA «hack» значит ВЗЛОМ ПРОТОКОЛА и
живёт в именах риск-величин (`# Hack risk`, `# hack=50%, loss=90%`). То есть
сторож честно отвечал на свой вопрос («встречается ли подстрока») вместо
нужного («есть ли здесь незакрытая работа»), и красный его цвет был свойством
ЛЕКСИКИ домена, а не состояния кода.

Каждый тест ниже — положительный контроль, который краснеет на РЕАЛЬНОЙ форме
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»); контроли стоят
ПАРАМИ в обе стороны, потому что проверка, зелёная только на целом контуре, не
отличима от проверки, не смотрящей никуда:

* настоящий маркер в заглавной форме — НАХОДКА (иначе починка была бы
  отключением сторожа, инв. #16);
* дословные строки домена, снятые с живого дерева, — НЕ находка;
* «не измерено» отделено от «чисто»: нечитаемый каталог даёт ПУСТОЙ ответ, и
  тест это НАЗЫВАЕТ, а не выдаёт за отсутствие маркеров (инв. #17).

Литеральных дат и литеральных pid здесь нет ПО ПОСТРОЕНИЮ: единственный вход
меры — текст файлов одноразовой сцены.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "dead_code_scanner.py"

#: Дословные строки ЖИВОГО дерева, которые прежняя редакция объявляла маркерами.
#: Это не выдумка сцены, а замер: каждая строка снята с `a19e8ea96`.
PROSE_FROM_THE_LIVE_TREE = (
    '    "available": False,        # Hack risk',
    "    # Hack history",
    "    # Hack penalty multipliers",
    "    # Hack risk window",
    "    # hack=2%, loss=80% -> uncovered_loss=20k*0.02*0.8=320",
    "    # hack 50% + admin key: 25 - 20 - 5 = 0",
    "    tvl_usd=100_000_000,  # hack > tvl",
)

#: Соглашение пишется капслоком — и ровно эти формы обязаны остаться находками.
REAL_MARKERS = (
    "    # TODO: точный оборот = sum(|w_new - w_old|) / 2",
    "    # FIXME: вернуть сюда замер",
    "    # HACK: обход, пока не приедет дверь",
    "    # XXX: это место не объяснено",
)


def _load_scanner():
    """Прибор грузится ПО ПУТИ: `scripts/` пакетом не является.

    Регистрация в ``sys.modules`` ДО ``exec_module`` обязательна и не
    украшение: модуль объявляет ``@dataclass``, а декоратор ищет собственный
    модуль в ``sys.modules`` по ``cls.__module__`` — без записи он получает
    ``None`` и падает ``AttributeError`` ещё на сборе тестов (измерено здесь же).
    """
    spec = importlib.util.spec_from_file_location("_dcs_under_test", _SCRIPT)
    assert spec and spec.loader, f"не загрузился {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dcs = _load_scanner()


def _scene(root: Path, body_lines) -> None:
    """Одноразовая сцена: `spa_core/` и `scripts/` с одним модулем в каждом."""
    for sub in ("spa_core", "scripts"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    body = "\n".join(["def f():"] + list(body_lines) + ["    return 1", ""])
    (root / "spa_core" / "scene.py").write_text(body, encoding="utf-8")
    (root / "scripts" / "other.py").write_text("x = 1\n", encoding="utf-8")


def _found(root: Path):
    return dcs.DeadCodeScanner(base_dir=str(root)).scan_todo_comments()


class MarkerIsDistinguishedFromProse(unittest.TestCase):
    """Пара в обе стороны на ОДНОЙ сцене: проза молчит, маркер говорит."""

    def test_prose_of_the_domain_is_NOT_a_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, PROSE_FROM_THE_LIVE_TREE)
            items = _found(root)
        self.assertEqual(
            [], [i.description for i in items],
            "строки домена («взлом протокола») объявлены маркерами — это ровно "
            "та авария #1183, из-за которой 15 ложных находок красили CI",
        )

    def test_a_real_marker_IS_still_a_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, REAL_MARKERS)
            items = _found(root)
        self.assertEqual(
            len(REAL_MARKERS), len(items),
            "настоящие маркеры потеряны — починка превратилась бы в отключение "
            f"сторожа (инв. #16); найдено: {[i.description for i in items]}",
        )
        tags = sorted({i.description.split(":", 1)[0] for i in items})
        self.assertEqual(["FIXME", "HACK", "TODO", "XXX"], tags)

    def test_both_sides_on_one_scene_do_not_cancel_each_other(self):
        """Маркер и проза РЯДОМ: находка ровно одна, и это маркер."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, list(PROSE_FROM_THE_LIVE_TREE) + [REAL_MARKERS[0]])
            items = _found(root)
        self.assertEqual(1, len(items), [i.description for i in items])
        self.assertTrue(items[0].description.startswith("TODO:"), items[0].description)


class AbsenceOfMeasurementIsNotCleanliness(unittest.TestCase):
    """Третий исход (инв. #17): пустой ответ бывает и у «нет каталога»."""

    def test_a_tree_without_the_scanned_dirs_yields_an_EMPTY_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = _found(Path(tmp))
        self.assertEqual(
            [], items,
            "каталогов нет — ответ пуст, и это НЕ «маркеров нет»: сам прибор "
            "«не измерено» отдельным значением не несёт, поэтому утверждать "
            "чистоту по его пустому ответу нельзя (см. докстроку модуля)",
        )

    def test_the_scene_itself_proves_the_dirs_are_what_is_read(self):
        """Контроль на предпосылку: без этого тест выше ничего не доказывает."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, [REAL_MARKERS[0]])
            self.assertEqual(1, len(_found(root)))
            # тот же корень, но читаемые каталоги унесены ⇒ ответ пуст
            (root / "spa_core" / "scene.py").unlink()
            self.assertEqual([], _found(root))


class TheLiveTreeIsMeasured(unittest.TestCase):
    """Живое дерево: маркеров не больше, чем объявляет сторож счёта."""

    def test_the_live_tree_has_no_prose_counted_as_a_marker(self):
        items = _found(_REPO_ROOT)
        lowercase_hack = [
            i.description for i in items
            if "hack" in i.description.split(":", 1)[-1].lower()
            and not i.description.startswith("HACK:")
        ]
        self.assertEqual(
            [], lowercase_hack,
            "в живом дереве снова считается проза про взлом протокола",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
