"""Храповик: файл, который доставка НЕ ВОЗИТ, не имеет права жёстко импортировать `spa_core`.

Ловушка (замер цикла #275, карточка `inbox-kornevoi-init-py-ne-mozhet-doehat-do-pro`).
Автосинк прод-дерева возит из origin ТОЛЬКО перечисленные пути — целиком, каталогами
(`scripts/code_sync_from_origin.sh`, `CODE_PATHS`, строка 36). Файл вне этих путей на
прод не приезжает **по построению**, а не из-за поломки: `git checkout origin/main -- <paths>`
его просто не касается. Значит у такого файла есть свойство, которого нет ни у одного
файла внутри синкаемых каталогов:

    его содержимое в проде заморожено на момент последнего РУЧНОГО касания дерева,
    а `spa_core`, на который он ссылается, обновляется каждый цикл.

Пока такой файл ссылается на `spa_core` жёстко (без `try/except`), разъезд молчит ровно
до первого импорта — и тогда падает `ImportError` в файле, который туда невозможно
доставить. Именно это и случилось: корневой `__init__.py` (Public API v10.0) держал
`from spa_core.adapters.registry import ADAPTER_REGISTRY`, а цикл #275 переименовал этот
объект в `ADAPTER_METADATA`. В репозитории имя починили одной строкой; в прод эта строка
не уехала бы никогда.

Почему это сторож КЛАССА, а не одного файла. Корневой `__init__.py` удалён (он был
дубликатом `spa_core/__init__.py`, читателя не имел и вдобавок ломал `sys.path` pytest —
см. комментарий в `pytest.ini`). Удаление лечит один файл; ловушка же — в расхождении
«механизм доставки ↔ зависимость», и завтра она повторится под другим именем. Поэтому
проверка спрашивает не «есть ли корневой `__init__.py`», а «есть ли ХОТЬ ОДИН
недоставляемый файл с жёсткой зависимостью от `spa_core`», и список доставляемых путей
читает из самого синка — если синк изменят, сторож поедет за ним, а не соврёт.

Почему храповик, а не запрет. Замер даёт 7 файлов в `attic/modules/**` — архив, который
никто не исполняет; запрет в лоб покрасил бы их и научил выключать проверку. Поэтому
база зафиксирована и может ТОЛЬКО уменьшаться: новый файл в классе — красный, починенный
файл обязан выпасть из базы (иначе база превращается в свалку и перестаёт быть замером).

Что считается «жёстким импортом»: модульный `import spa_core…` / `from spa_core… import …`
ВНЕ `try:`-блока. Импорт, обёрнутый в `try/except ImportError`, деградирует громко и
предсказуемо — он не превращает разъезд в аварию, поэтому классом не считается.

Контроли:
  * положительный — синтетическое дерево воспроизводит ровно аварию #275 (корневой
    `__init__.py` с жёстким импортом переименованного символа) и ОБЯЗАНО краснеть;
  * обратный — тот же импорт внутри синкаемого каталога и он же в `try/except`
    краснеть НЕ обязаны;
  * контроль разбора — `CODE_PATHS` обязан читаться из синка непусто (fail-CLOSED:
    не разобрали — красный, а не «доставляется всё»).
"""
from __future__ import annotations

import ast
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "code_sync_from_origin.sh"
BASELINE = Path(__file__).resolve().parent / "undeliverable_hard_import_baseline.json"

# Каталоги, которых нет в вопросе: чужой код, артефакты сборки, не-Python поддеревья.
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", ".venv_test", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages",
    "landing", "cabinet", ".egg-info",
}

_CODE_PATHS_RE = re.compile(r"^\s*CODE_PATHS=\((?P<body>[^)]*)\)", re.MULTILINE)


def delivered_paths(sync_script: Path = SYNC_SCRIPT) -> list[str]:
    """Что автосинк реально возит на прод — читаем из синка, не из памяти.

    Fail-CLOSED: не нашли/не разобрали — исключение. Пустой список молча означал бы
    «доставляется всё», то есть сторож, который никогда не краснеет.
    """
    text = sync_script.read_text(encoding="utf-8")
    match = _CODE_PATHS_RE.search(text)
    if match is None:
        raise AssertionError(
            f"в {sync_script} не найдено объявление CODE_PATHS=(...) — состав доставки "
            "прочитать неоткуда, а угадывать его запрещено (fail-CLOSED)"
        )
    paths = [p for p in match.group("body").split() if p and not p.startswith("#")]
    if not paths:
        raise AssertionError(f"CODE_PATHS в {sync_script} пуст — доставка ничего не возит?")
    return paths


def _is_delivered(rel: str, paths: list[str]) -> bool:
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in paths)


def _iter_py_files(root: Path):
    """Файлы ЭТОГО дерева. Вложенные чекауты (`.claude/worktrees/*`) — чужие копии.

    Признак — свой `.git` (каталог у клона, файл-указатель у worktree), а не имя
    каталога: имена рабочих деревьев случайны (урок цикла #275 — без отсечения
    храповик краснеет в проде на ВЕРНОМ состоянии).
    """
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not (here / d / ".git").exists()
        ]
        for fname in sorted(filenames):
            if fname.endswith(".py"):
                yield here / fname


def _hard_spa_core_imports(source: str) -> list[tuple[int, str]]:
    """Модульные импорты `spa_core…` ВНЕ try-блока: (строка, модуль)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []  # нечитаемый файл — предмет другого сторожа

    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in node.body:
                for inner in ast.walk(stmt):
                    guarded.add(id(inner))

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` (level>0) к пакету spa_core отношения не имеет
            modules = [node.module] if node.level == 0 and node.module else []
        for mod in modules:
            if mod == "spa_core" or mod.startswith("spa_core."):
                found.append((node.lineno, mod))
    return found


def scan(root: Path, paths: list[str]) -> dict[str, list[tuple[int, str]]]:
    """{относительный путь: [(строка, модуль), …]} для НЕдоставляемых файлов."""
    root = root.resolve()
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in _iter_py_files(root):
        rel = path.relative_to(root).as_posix()
        if _is_delivered(rel, paths):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = _hard_spa_core_imports(source)
        if hits:
            offenders[rel] = hits
    return offenders


def _baseline_files() -> set[str]:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return set(data["files"])


class UndeliverableHardImportRatchet(unittest.TestCase):
    def test_code_paths_are_read_from_the_sync_itself(self):
        paths = delivered_paths()
        self.assertIn("spa_core", paths)
        self.assertIn("scripts", paths)
        self.assertIn("tests", paths)

    def test_no_new_undeliverable_file_hard_imports_spa_core(self):
        paths = delivered_paths()
        offenders = scan(REPO_ROOT, paths)
        new = sorted(set(offenders) - _baseline_files())
        self.assertEqual(
            new, [],
            "файл вне доставляемых путей жёстко импортирует spa_core — на прод он не "
            f"приезжает НИ ОДНИМ механизмом, значит эта зависимость разъедется молча: "
            f"{ {k: offenders[k] for k in new} }. Починка: перенести файл в один из "
            f"доставляемых каталогов ({', '.join(paths)}) либо снять жёсткую зависимость. "
            "Добавлять файл в базу, чтобы погасить красный, ЗАПРЕЩЕНО.",
        )

    def test_baseline_only_shrinks(self):
        """Починенный файл обязан выпасть из базы, иначе база — свалка, а не замер."""
        paths = delivered_paths()
        offenders = scan(REPO_ROOT, paths)
        stale = sorted(_baseline_files() - set(offenders))
        self.assertEqual(
            stale, [],
            f"эти файлы больше не в классе — удалите их из {BASELINE.name}: {stale}",
        )

    def test_root_init_is_gone(self):
        """Именно этот файл был аварией #275: недоставляемый, дубликат `spa_core/__init__.py`.

        Проверка узкая НАМЕРЕННО и живёт рядом с широкой: широкая ловит класс, эта
        не даёт вернуть конкретный экземпляр «просто для удобства импорта».
        """
        self.assertFalse(
            (REPO_ROOT / "__init__.py").exists(),
            "корневой __init__.py вернулся: он делает репозиторий импортируемым пакетом, "
            "которого доставка не возит, и дублирует spa_core/__init__.py",
        )

    # ── контроли сканера ────────────────────────────────────────────────────
    def test_positive_control_reproduces_the_275_failure(self):
        """Сканер, никогда не видевший настоящей поломки, — украшение."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "__init__.py").write_text("ADAPTER_METADATA = {}\n")
            (root / "__init__.py").write_text(
                "from spa_core.adapters.registry import ADAPTER_REGISTRY\n"
            )
            offenders = scan(root, ["spa_core", "scripts", "tests"])
        self.assertEqual(
            offenders, {"__init__.py": [(1, "spa_core.adapters.registry")]},
            f"авария #275 не воспроизведена сканером: {offenders}",
        )

    def test_reverse_control_delivered_and_guarded_imports_are_not_offenders(self):
        """Красный на верном состоянии живёт до первого «выключите его»."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core").mkdir()
            # доставляемый файл — вопрос его не касается
            (root / "spa_core" / "mod.py").write_text("from spa_core.utils import atomic\n")
            (root / "scripts").mkdir()
            (root / "scripts" / "s.py").write_text("import spa_core\n")
            # недоставляемый, но деградирует громко и предсказуемо
            (root / "legacy.py").write_text(
                "try:\n    import spa_core\nexcept ImportError:\n    spa_core = None\n"
            )
            # недоставляемый, но про spa_core не знает вовсе
            (root / "plain.py").write_text("import json\nfrom os import path\n")
            offenders = scan(root, ["spa_core", "scripts", "tests"])
        self.assertEqual(offenders, {}, f"ложный красный: {offenders}")

    def test_reverse_control_nested_checkout_is_not_counted(self):
        """Вложенная рабочая копия — чужое дерево со своим синком."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / ".claude" / "worktrees" / "agent-x"
            nested.mkdir(parents=True)
            (nested / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
            (nested / "__init__.py").write_text("import spa_core\n")

            clone = root / "sub" / "nested-clone"
            (clone / ".git").mkdir(parents=True)
            (clone / "__init__.py").write_text("import spa_core\n")

            offenders = scan(root, ["spa_core", "scripts", "tests"])
        self.assertEqual(offenders, {}, f"посчитано чужое дерево: {offenders}")

    def test_parse_control_missing_code_paths_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "sync.sh"
            bad.write_text("#!/bin/bash\nmain() { git fetch; }\n")
            with self.assertRaises(AssertionError):
                delivered_paths(bad)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
