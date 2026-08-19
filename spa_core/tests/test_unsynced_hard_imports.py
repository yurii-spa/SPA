"""Сторож: файл, которого автосинк НЕ возит в прод, не смеет жёстко импортировать ``spa_core``.

Вопрос, на который отвечает ИМЕННО этот сторож
----------------------------------------------
«Есть ли в репозитории файл, который **невозможно доставить в прод**, но который при этом
жёстко зависит от кода, доставляемого туда каждый цикл?»

Такой файл протухает **молча и по построению**: `spa_core/` приезжает в прод переименованным,
а он остаётся с прежними именами — и никакой существующий сторож этого не видит.
`deployment_drift_monitor` спрашивает «та ли версия?» (несинкаемого файла в его сравнении нет
вовсе), `deployment_acceptance` — «способен ли флот стартовать?» (импорт-проба берёт
`spa_core.*`, а не корень), `agent_health` — «агенты живы?». Все трое честно отвечают на свой
вопрос, и ни один не отвечает на этот. Правило класса — `.claude/rules/deployment.md`.

Авария, ради которой сторож написан (2026-08-17, цикл #275; перемерено #297 живым эффектом)
-------------------------------------------------------------------------------------------
Корневой ``__init__.py`` репозитория лежит ВНЕ каталогов автосинка ⇒ на прод не приезжает
**по построению**. Цикл #275 переименовал ``ADAPTER_REGISTRY`` → ``ADAPTER_METADATA`` в
``spa_core/adapters/registry.py``; переименование уехало в прод, корневой файл — нет:

    $ python3 -c "import SPA_Claude"          # прод-дерево, 2026-08-19
    ImportError: cannot import name 'ADAPTER_REGISTRY' from 'spa_core.adapters.registry'

Это ЗАМЕР прод-дерева, а не рассуждение. Пакет разрешим (``~/Documents`` на ``sys.path`` —
достаточно одного скрипта, запущенного из домашнего каталога), читателя сегодня нет — но
«читателя нет» есть утверждение о СЕГОДНЯШНЕМ дереве, и проект за этот класс уже платил.

Откуда сторож знает свою область
--------------------------------
Список доставляемого читается из САМОГО скрипта доставки
(``scripts/code_sync_from_origin.sh``, ``CODE_PATHS=(…)``), а не зашит здесь. Иначе сторож
стал бы эхом подопечного: сменился бы список доставки — сторож продолжил бы судить о старом
и остался бы зелёным (класс #197). Заодно это ловит устаревшую посылку исходной карточки:
она говорила «возит только spa_core/ scripts/ tests/», а на деле список уже включает
``architecture`` и два корневых пушера.

Границы, названные вслух (сторож их НЕ покрывает)
-------------------------------------------------
* **Импорт под ``try/except`` не считается находкой.** Критерий взят из карточки дословно
  («без try/except»). Такой импорт деградирует тихо — это ОТДЕЛЬНЫЙ класс, и сторож на него
  не претендует, вместо того чтобы делать вид, что покрывает.
* Не-python поверхности (``.sh``, ``.plist``, ``.yml``) вне области: у них нет импорта.
* ``attic/`` исключён — это код-надгробие; исключение не постулировано, а ЗАРАБОТАНО тестом
  ``test_attic_exclusion_is_earned`` (перестанет быть надгробием — сторож это скажет).
"""

from __future__ import annotations

import ast
import re
import subprocess
import unittest
from pathlib import Path
from typing import Dict, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "code_sync_from_origin.sh"

# Код-надгробие: ретированные модули, оставленные как история. Исключение зарабатывается
# тестом ниже (ни одна исполняемая поверхность их не зовёт), а не объявляется здесь.
TOMBSTONE_DIRS = ("attic",)

_CODE_PATHS_RE = re.compile(r"^\s*CODE_PATHS=\(([^)]*)\)", re.MULTILINE)


class DeliveryScopeUnmeasured(RuntimeError):
    """Область доставки не измерена. Fail-CLOSED: молчаливого «чисто» здесь не бывает."""


def delivered_paths(sync_script: Path = SYNC_SCRIPT) -> List[str]:
    """Что автосинк реально возит в прод — прочитанное из скрипта доставки.

    Не измерили (нет файла / нет присваивания / пустой список) ⇒ исключение, а не пустой
    ответ: пустая область превратила бы сторожа в «находок нет» на любом дереве.
    """
    if not sync_script.is_file():
        raise DeliveryScopeUnmeasured(f"скрипт доставки не найден: {sync_script}")
    match = _CODE_PATHS_RE.search(sync_script.read_text(encoding="utf-8", errors="replace"))
    if not match:
        raise DeliveryScopeUnmeasured(
            f"в {sync_script.name} не найдено присваивание CODE_PATHS=(…) — "
            "область доставки НЕ ИЗМЕРЕНА"
        )
    paths = [chunk.strip().strip("'\"") for chunk in match.group(1).split()]
    paths = [p for p in paths if p]
    if not paths:
        raise DeliveryScopeUnmeasured(f"CODE_PATHS в {sync_script.name} пуст")
    return paths


def _tracked_python_files(root: Path) -> List[Path]:
    """Только git-tracked ``*.py``.

    Через git, а не ``rglob``: обход от корня в ПРОДЕ засчитал бы вложенные рабочие деревья
    (``.claude/worktrees/*``) и дал бы ложный красный на верном состоянии — этот капкан уже
    ловили на храповике определений.
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.py"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise DeliveryScopeUnmeasured(f"git ls-files отказал в {root}: {proc.stderr.strip()}")
    return [root / name for name in proc.stdout.split("\0") if name]


def _is_delivered(rel: Path, delivered: Sequence[str]) -> bool:
    parts = rel.parts
    for path in delivered:
        target = Path(path).parts
        if parts[: len(target)] == target:
            return True
    return False


def _is_tombstone(rel: Path) -> bool:
    return rel.parts and rel.parts[0] in TOMBSTONE_DIRS


def hard_spa_core_imports(source: str) -> List[str]:
    """Импорты ``spa_core`` НА УРОВНЕ МОДУЛЯ и вне ``try``. Синтаксическую ошибку не глотаем."""
    tree = ast.parse(source)
    found: List[str] = []
    for node in tree.body:  # только верхний уровень: тело try/except сюда не попадает
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names
                      if a.name == "spa_core" or a.name.startswith("spa_core.")]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "spa_core" or mod.startswith("spa_core."):
                found.append(mod)
    return sorted(set(found))


def scan(root: Path = REPO_ROOT, sync_script: Path | None = None) -> Dict[str, List[str]]:
    """{путь → жёстко импортируемые модули spa_core} для файлов ВНЕ области доставки."""
    delivered = delivered_paths(sync_script or (root / "scripts" / "code_sync_from_origin.sh"))
    files = _tracked_python_files(root)
    if not files:
        raise DeliveryScopeUnmeasured(
            f"в {root} не найдено НИ ОДНОГО git-tracked *.py — измерение сломано, "
            "а не «находок нет»"
        )
    offenders: Dict[str, List[str]] = {}
    for path in files:
        rel = path.relative_to(root)
        if _is_delivered(rel, delivered) or _is_tombstone(rel):
            continue
        if not path.is_file():
            continue
        try:
            hits = hard_spa_core_imports(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        if hits:
            offenders[str(rel)] = hits
    return offenders


# --------------------------------------------------------------------------------------
# Сам гейт
# --------------------------------------------------------------------------------------
class TestNoUndeliverableHardDependency(unittest.TestCase):
    """Главное утверждение: недоставляемого файла с жёсткой зависимостью быть не должно."""

    def test_no_unsynced_file_hard_imports_spa_core(self) -> None:
        offenders = scan()
        self.assertEqual(
            offenders,
            {},
            "Файл ВНЕ каталогов автосинка жёстко импортирует spa_core — в прод он не "
            "приедет НИ ОДНИМ механизмом и протухнет молча (авария 2026-08-17, корневой "
            f"__init__.py). Найдено: {offenders}. Решение — доставить файл (добавить в "
            "CODE_PATHS скрипта доставки, это прод-дерево ⇒ решение владельца) либо снять "
            "файл, либо убрать жёсткую зависимость. Дописывать исключение сюда — нельзя.",
        )

    def test_the_scan_is_not_vacuously_clean(self) -> None:
        """Зелёный обязан означать «проверено», а не «нечего проверять»."""
        delivered = delivered_paths()
        self.assertIn("spa_core", delivered)
        self.assertTrue(_tracked_python_files(REPO_ROOT))


class TestDeliveryScopeComesFromTheDeliveryScript(unittest.TestCase):
    """Сторож обязан следовать за списком доставки, а не за своей копией списка."""

    def test_scope_is_read_from_the_sync_script(self) -> None:
        delivered = delivered_paths()
        for expected in ("spa_core", "scripts", "tests"):
            self.assertIn(expected, delivered)

    def test_the_card_premise_was_stale_and_the_guard_follows_the_script(self) -> None:
        """Карточка говорила «возит ТОЛЬКО три каталога» — на деле список шире.

        Тест закрепляет не конкретный состав (он вправе меняться), а то, что сторож берёт
        состав ИЗ СКРИПТА: список длиннее трёх, и корневые файлы в нём тоже бывают.
        """
        delivered = delivered_paths()
        self.assertGreater(len(delivered), 3, f"прочитано из скрипта: {delivered}")

    def test_a_changed_script_changes_the_guard_scope(self) -> None:
        with _temp_tree() as tree:
            _write(tree / "scripts" / "code_sync_from_origin.sh",
                   "main() {\n    CODE_PATHS=(spa_core scripts tests tools)\n}\n")
            self.assertEqual(
                delivered_paths(tree / "scripts" / "code_sync_from_origin.sh"),
                ["spa_core", "scripts", "tests", "tools"],
            )

    def test_unmeasurable_scope_fails_closed(self) -> None:
        """Не смогли прочитать список — исключение, а не «всё доставляется»."""
        with _temp_tree() as tree:
            missing = tree / "scripts" / "nope.sh"
            with self.assertRaises(DeliveryScopeUnmeasured):
                delivered_paths(missing)
            _write(tree / "scripts" / "empty.sh", "main() {\n    CODE_PATHS=()\n}\n")
            with self.assertRaises(DeliveryScopeUnmeasured):
                delivered_paths(tree / "scripts" / "empty.sh")
            _write(tree / "scripts" / "none.sh", "main() {\n    echo hi\n}\n")
            with self.assertRaises(DeliveryScopeUnmeasured):
                delivered_paths(tree / "scripts" / "none.sh")


class TestPositiveControlsReplayTheRealFailure(unittest.TestCase):
    """Каждый тест здесь — авария, а не украшение: на неисправленном дереве он краснеет."""

    def test_the_2026_08_17_root_init_is_caught_verbatim(self) -> None:
        """Дословная строка, которая рушит прод-пакет сегодня."""
        hits = hard_spa_core_imports(
            "from __future__ import annotations\n"
            "from spa_core.adapters.registry import ADAPTER_REGISTRY  # noqa: F401\n"
        )
        self.assertEqual(hits, ["spa_core.adapters.registry"])

    def test_a_root_file_outside_the_sync_list_is_reported_by_scan(self) -> None:
        with _temp_tree() as tree:
            _write(tree / "scripts" / "code_sync_from_origin.sh",
                   "main() {\n    CODE_PATHS=(spa_core scripts tests)\n}\n")
            _write(tree / "__init__.py",
                   "from spa_core.adapters.registry import ADAPTER_REGISTRY\n")
            _git_add_all(tree)
            offenders = scan(tree)
            self.assertIn("__init__.py", offenders)
            self.assertEqual(offenders["__init__.py"], ["spa_core.adapters.registry"])

    def test_any_undelivered_directory_is_caught_not_just_the_root(self) -> None:
        """Класс, а не один файл: любой каталог вне списка доставки."""
        with _temp_tree() as tree:
            _write(tree / "scripts" / "code_sync_from_origin.sh",
                   "main() {\n    CODE_PATHS=(spa_core scripts tests)\n}\n")
            _write(tree / "tools" / "helper.py", "import spa_core.risk.policy\n")
            _git_add_all(tree)
            self.assertIn("tools/helper.py", scan(tree))

    def test_scan_fails_closed_on_an_empty_measurement(self) -> None:
        """Ноль найденных файлов — сломанное измерение, а не чистый прогон."""
        with _temp_tree() as tree:
            _write(tree / "scripts" / "code_sync_from_origin.sh",
                   "main() {\n    CODE_PATHS=(spa_core scripts tests)\n}\n")
            _git_add_all(tree)  # ни одного .py, кроме скриптов оболочки
            with self.assertRaises(DeliveryScopeUnmeasured):
                scan(tree)

    def test_scan_fails_closed_outside_a_git_tree(self) -> None:
        with _temp_tree(init_git=False) as tree:
            _write(tree / "scripts" / "code_sync_from_origin.sh",
                   "main() {\n    CODE_PATHS=(spa_core scripts tests)\n}\n")
            with self.assertRaises(DeliveryScopeUnmeasured):
                scan(tree)


class TestReverseControls(unittest.TestCase):
    """Обратная сторона: сторож не должен краснеть на верном состоянии."""

    def test_the_same_import_inside_a_delivered_dir_is_not_a_finding(self) -> None:
        with _temp_tree() as tree:
            _write(tree / "scripts" / "code_sync_from_origin.sh",
                   "main() {\n    CODE_PATHS=(spa_core scripts tests)\n}\n")
            _write(tree / "scripts" / "helper.py",
                   "from spa_core.adapters.registry import ADAPTER_METADATA\n")
            _write(tree / "tools" / "clean.py", "import json\n")
            _git_add_all(tree)
            self.assertEqual(scan(tree), {})

    def test_a_guarded_import_is_out_of_scope_by_design(self) -> None:
        """Граница названа в докстринге модуля: try/except — ОТДЕЛЬНЫЙ класс."""
        self.assertEqual(
            hard_spa_core_imports(
                "try:\n"
                "    from spa_core.adapters import ADAPTER_REGISTRY\n"
                "except ImportError:\n"
                "    ADAPTER_REGISTRY = None\n"
            ),
            [],
        )

    def test_a_function_local_import_is_not_a_module_level_dependency(self) -> None:
        self.assertEqual(
            hard_spa_core_imports("def f():\n    import spa_core.risk.policy\n    return 1\n"),
            [],
        )

    def test_a_lookalike_module_name_is_not_matched(self) -> None:
        self.assertEqual(hard_spa_core_imports("import spa_core_extras\n"), [])
        self.assertEqual(hard_spa_core_imports("from spa_coreutils import x\n"), [])


class TestAtticExclusionIsEarned(unittest.TestCase):
    """Исключение надгробия действует, только пока надгробие остаётся надгробием."""

    def test_attic_exclusion_is_earned(self) -> None:
        attic = REPO_ROOT / "attic"
        if not attic.exists():
            self.skipTest("attic/ снят — исключение больше ничего не исключает")
        self.assertTrue(
            (attic / "MANIFEST.md").is_file(),
            "attic/ исключён как код-надгробие; без MANIFEST.md это уже не надгробие, "
            "а просто каталог вне доставки — исключение перестаёт быть заработанным",
        )

    def test_no_runtime_surface_calls_into_the_tombstone(self) -> None:
        """Проводка надгробия в исполняемую поверхность обязана краснить.

        Именно это делает исключение измеренным: пока `attic/` не зовёт ни один plist,
        ни один workflow и ни одна обёртка агента, его недоставляемость безвредна.
        """
        surfaces: List[Path] = []
        for pattern in ("launchd/*.plist", ".github/workflows/*.yml", "scripts/*.sh"):
            surfaces += sorted(REPO_ROOT.glob(pattern))
        self.assertTrue(surfaces, "исполняемых поверхностей не найдено — измерение сломано")
        callers = [
            str(p.relative_to(REPO_ROOT))
            for p in surfaces
            if "attic" in p.read_text(encoding="utf-8", errors="replace")
        ]
        self.assertEqual(
            callers,
            [],
            "исполняемая поверхность ссылается на attic/ — надгробие перестало быть "
            f"надгробием, исключение сторожа больше не заработано: {callers}",
        )


# --------------------------------------------------------------------------------------
# Хозяйство тестов
# --------------------------------------------------------------------------------------
import contextlib
import os
import tempfile


@contextlib.contextmanager
def _temp_tree(init_git: bool = True):
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        if init_git:
            subprocess.run(["git", "-C", str(tree), "init", "-q"], check=True,
                           capture_output=True)
        yield tree


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git_add_all(tree: Path) -> None:
    subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True, capture_output=True,
                   env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
