"""Храповик: одно имя — один объект. `ADAPTER_REGISTRY` определён РОВНО ОДИН раз.

Замер 2026-08-12 (цикл #206) и перемер 2026-08-17 (цикл #274): под именем
`ADAPTER_REGISTRY` в дереве жили **три** разных объекта разной формы, с разными
именами протоколов и разного размера:

    spa_core/adapters/__init__.py                — list[tuple], 36 записей, `aave_v3`
    spa_core/adapters/registry.py                — dict, 22 записи, `aave_usdc`
    spa_core/orchestrator/adapter_orchestrator.py — list[tuple], 8 записей

Ошибиться было НЕЛЬЗЯ ГРОМКО: обе списочные формы итерируются, dict тоже, и все
три дают непустой результат. Ровно на этом сгорел `house_view_gap` (цикл #206) —
три месяца объявлял достижимые возможности недостижимыми. И `spa_core.ADAPTER_REGISTRY`
молча отдавал dict, в котором крупнейшей позиции книги (`aave_v3`, 40 %) НЕТ ВОВСЕ.

Цикл #274 развёл имена: dict → `ADAPTER_METADATA`, набор опроса → `POLLED_ADAPTERS`.
Этот храповик держит развод: любое НОВОЕ определение `ADAPTER_REGISTRY` краснеет.

Почему проверка идёт по ДЕРЕВУ, а не по импортам: импорт видит только то, что
кто-то уже импортировал, а вопрос карточки — «сколько разных объектов носят это
имя», и он о ФАЙЛАХ. Сканер — AST, а не текст: упоминание имени в комментарии или
докстринге проводкой не считается (урок цикла #227).

Проверки в обе стороны:
  * определений в дереве ровно одно, и оно в каноническом файле;
  * счёт из `.claude/rules/adapters.md` даёт ОДНО и то же число любым разрешённым
    импортом (`spa_core.adapters`, `spa_core`, корневой пакет);
  * положительный контроль — синтетическое дерево с ДВУМЯ определениями обязано
    краснеть (иначе сканер — украшение);
  * обратный контроль — комментарий/докстринг с этим именем краснеть НЕ обязан.
"""
from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CANONICAL_FILE = "spa_core/adapters/__init__.py"

# Каталоги, которые к рантайму отношения не имеют (чужой код / артефакты сборки).
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    "landing", "cabinet", ".mypy_cache", ".pytest_cache", "site-packages",
}


def _iter_py_files(root: Path):
    """Файлы ЭТОГО дерева — вложенные чекауты репозитория не в счёт.

    Прод-дерево держит рабочие копии внутри себя (`.claude/worktrees/*`), и каждая —
    полная копия репозитория со своим определением реестра. Замер 2026-08-17 (цикл
    #275): без этого отсечения храповик насчитывает в проде **33** определения вместо
    одного и краснеет на ВЕРНОМ состоянии — ровно тот ложный отказ, после которого
    проверку выключают. Признак вложенного чекаута — свой `.git` (каталог у обычного
    клона, файл-указатель у worktree), а не имя каталога: имена деревьев случайны.
    """
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not (here / d / ".git").exists()
        ]
        for fname in filenames:
            if fname.endswith(".py"):
                yield here / fname


def find_definitions(root: Path, name: str) -> list[tuple[str, int]]:
    """Все МОДУЛЬНЫЕ присваивания `name = ...` / `name: T = ...` в дереве.

    Присваивания внутри функций/классов не в счёт (они не создают имя модуля),
    как и `import ... as name` — импорт не порождает нового объекта.
    """
    found: list[tuple[str, int]] = []
    root = root.resolve()  # иначе /tmp vs /private/tmp ломает relative_to (macOS)
    for path in _iter_py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue  # нечитаемый файл — не наша тема, о нём краснеет другой страж
        for node in tree.body:  # ТОЛЬКО верхний уровень модуля
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    rel = path.relative_to(root).as_posix()
                    found.append((rel, node.lineno))
    return found


class OneNameOneObject(unittest.TestCase):
    def test_adapter_registry_defined_exactly_once(self):
        defs = find_definitions(REPO_ROOT, "ADAPTER_REGISTRY")
        self.assertEqual(
            len(defs), 1,
            "имя ADAPTER_REGISTRY определено более одного раза — вернулась авария "
            f"цикла #206 (разные объекты под одним именем): {defs}",
        )
        self.assertEqual(defs[0][0], CANONICAL_FILE,
                         f"канонический реестр переехал: {defs}")

    def test_metadata_and_polled_are_defined_once_too(self):
        """Развод имён не должен сам породить новый дубль."""
        for name, where in (("ADAPTER_METADATA", "spa_core/adapters/registry.py"),
                            ("POLLED_ADAPTERS",
                             "spa_core/orchestrator/adapter_orchestrator.py")):
            with self.subTest(name=name):
                defs = find_definitions(REPO_ROOT, name)
                self.assertEqual(len(defs), 1, f"{name}: {defs}")
                self.assertEqual(defs[0][0], where, f"{name}: {defs}")

    def test_every_allowed_import_gives_the_same_object(self):
        """Проверка количества из `.claude/rules/adapters.md` не должна зависеть
        от того, каким импортом реестр задан."""
        import spa_core
        from spa_core.adapters import ADAPTER_REGISTRY as from_adapters

        self.assertIs(spa_core.ADAPTER_REGISTRY, from_adapters)
        self.assertIsInstance(from_adapters, list)
        self.assertEqual(len(spa_core.ADAPTER_REGISTRY), len(from_adapters))

    def test_metadata_is_a_different_object_and_says_so(self):
        """ADAPTER_METADATA — ДРУГОЙ ответ, и он обязан быть отличим по форме."""
        import spa_core
        from spa_core.adapters.registry import ADAPTER_METADATA

        self.assertIs(spa_core.ADAPTER_METADATA, ADAPTER_METADATA)
        self.assertIsInstance(ADAPTER_METADATA, dict)
        self.assertIsNot(spa_core.ADAPTER_REGISTRY, ADAPTER_METADATA)

    def test_canonical_knows_the_largest_position_of_the_book(self):
        """`aave_v3` — 40 % книги; в dict-реестре его НЕТ (там он `aave_usdc`).

        Это и есть цена путаницы: сверка «книга ↔ реестр», случайно взявшая dict,
        честно доложит, что крупнейшая позиция не зарегистрирована.
        """
        from spa_core.adapters import ADAPTER_REGISTRY
        from spa_core.adapters.registry import ADAPTER_METADATA

        canonical_keys = {entry[0] for entry in ADAPTER_REGISTRY}
        self.assertIn("aave_v3", canonical_keys)
        self.assertNotIn("aave_v3", ADAPTER_METADATA)

    def test_no_compat_aliases_left_behind(self):
        """Псевдоним совместимости — те же два ответа под одним именем, с отсрочкой.

        Развод имён держится ровно до первого «ну добавим алиас, чтобы не чинить
        потребителей». Тогда `orch.ADAPTER_REGISTRY` снова начнёт отвечать — и снова
        не то, что думает читатель. Замер #275: ДВА потребителя обращались к набору
        опроса через псевдоним модуля (`orch.ADAPTER_REGISTRY`), и никакой grep по
        имени объекта их не видел — их поймал только полный прогон.
        """
        from spa_core.adapters import registry as reg_mod
        from spa_core.orchestrator import adapter_orchestrator as orch_mod

        for mod, forbidden in ((reg_mod, "ADAPTER_REGISTRY"),
                               (orch_mod, "ADAPTER_REGISTRY"),
                               (orch_mod, "ADAPTER_METADATA")):
            with self.subTest(module=mod.__name__, name=forbidden):
                self.assertFalse(
                    hasattr(mod, forbidden),
                    f"{mod.__name__}.{forbidden} снова существует — это псевдоним "
                    "совместимости, то есть возврат аварии #206 под другим соусом",
                )

    # ── контроли сканера ────────────────────────────────────────────────────
    def test_positive_control_two_definitions_are_caught(self):
        """Сканер, никогда не видевший настоящей поломки, — украшение."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg" / "a.py").write_text("ADAPTER_REGISTRY = [('x', 'T1', object)]\n")
            (root / "pkg" / "b.py").write_text("ADAPTER_REGISTRY: dict = {'y': {}}\n")
            defs = find_definitions(root, "ADAPTER_REGISTRY")
        self.assertEqual(len(defs), 2, f"дубль не пойман: {defs}")

    def test_positive_control_nested_checkout_is_not_counted(self):
        """Вложенная рабочая копия — НЕ второе определение.

        Замер в прод-дереве (цикл #275): `.claude/worktrees/*` дают 33 определения
        против одного. Пропусти это — и храповик краснеет там, где всё верно, а
        красный на верном состоянии живёт ровно до первого «да выключите его».
        Проверяем ОБА вида чекаута: `.git`-каталог (клон) и `.git`-файл (worktree).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            (root / "pkg" / "a.py").write_text("ADAPTER_REGISTRY = [('x', 'T1', object)]\n")

            clone = root / ".claude" / "worktrees" / "nested-clone"
            (clone / ".git").mkdir(parents=True)
            (clone / "spa_core").mkdir()
            (clone / "spa_core" / "adapters.py").write_text("ADAPTER_REGISTRY = {'y': {}}\n")

            wt = root / "sub" / "nested-worktree"
            wt.mkdir(parents=True)
            (wt / ".git").write_text("gitdir: /elsewhere/.git/worktrees/nested\n")
            (wt / "adapters.py").write_text("ADAPTER_REGISTRY = {'z': {}}\n")

            defs = find_definitions(root, "ADAPTER_REGISTRY")
        self.assertEqual([d[0] for d in defs], ["pkg/a.py"], f"посчитано лишнее: {defs}")

    def test_reverse_control_mentions_are_not_definitions(self):
        """Комментарий, докстринг, импорт-алиас и присваивание ВНУТРИ функции —
        не определения. Иначе храповик начнёт краснеть на разговоры о себе
        (рецидив #227) и его выключат."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text(
                '"""docstring про ADAPTER_REGISTRY."""\n'
                "# ADAPTER_REGISTRY = {}  ← комментарий\n"
                "from x import Y as ADAPTER_REGISTRY\n"
                "def f():\n"
                "    ADAPTER_REGISTRY = []\n"
                "    return ADAPTER_REGISTRY\n"
            )
            defs = find_definitions(root, "ADAPTER_REGISTRY")
        self.assertEqual(defs, [], f"ложное определение: {defs}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
