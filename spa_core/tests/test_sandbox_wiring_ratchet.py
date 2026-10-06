"""Храповик: харнесс, запускающий subprocess против одноразового дерева/копии,
обязан выставлять маркер песочницы C8(b) (ADR-580) — F8, REVIEW_1 amendment.

## Класс (INC-1, C8 ADR-580)

Производитель, резолвящий `data/`/живое дерево через `spa_core.utils.live_paths`
(`live_data_dir()`/`live_root()` без параметра), по умолчанию уходит в ПРОД —
`DEFAULT_LIVE_ROOT`. Харнесс, который гонит субпроцесс против одноразового
дерева/стенда (копии `data/`, полной копии репозитория, скрипта по пути с
переставленным `PYTHONPATH`), обязан выставить `SPA_SANDBOX=1` (+
`SPA_DATA_DIR`/`SPA_LIVE_ROOT` на СВОЮ песочницу) — иначе читатель без
собственного параметра `data_dir` молча уводит запись в прод (ровно форма
INC-1: `com.spa.decision_loop` → G97-зонд → `owner_decision_pending.json`
получил отметку 2041 года).

## Как ловится (AST, не regex по всему файлу)

Сигнал — функция, которая ОДНОВРЕМЕННО:
  (а) зовёт `subprocess.run`/`Popen`/`call`/`check_call`/`check_output`;
  (б) строит окружение субпроцесса и сама переставляет `PYTHONPATH`
      (`env["PYTHONPATH"] = …`) — признак того, что субпроцесс импортирует
      ДЕРЕВО, на которое указывает `PYTHONPATH`, а не просто вызывает внешний
      бинарник (git, ffmpeg, whisper, …), которому `PYTHONPATH` безразличен.
Среди таких функций ищем текстовое упоминание `SPA_SANDBOX`/`SANDBOX_ENV` —
его отсутствие в теле функции и есть находка. Признак ИСХОДНЫЙ (как у
`test_data_dir_env_ratchet.py`): доказать, что переменная доходит до КАЖДОГО
вызова субпроцесса, статическим разбором нельзя, и сторож, утверждающий это,
был бы сам fail-OPEN.

Замер 2026-10-05 (после F7/F8 починки `python_reader_clock_doors`,
`list_identity_census`, `green_by_construction_census`, `run_identity_key_price`):
population = 7 функций; 5 несут маркер, 2 — в явном allow-list ниже, с разбором
КАЖДОЙ. Новая функция этого класса без маркера и без явной записи в allow-list
красит этот тест.

Перемерено 2026-10-05 (N2, REVIEW_INTEGRATION_2, после фикса `decision_
reproducibility._default_runner`): population та же — 7; маркер несут уже 6,
allow-list — 1 (`underwriting_verify_dryrun._run_verifier_clean`, PYTHONPATH
пуст по построению). Снятие второй записи — УСИЛЕНИЕ, разрешённое правилом
«Запрещено» этого файла ниже и обратным храповиком
`test_allowlist_entries_still_exist_and_still_lack_the_marker` (протухшая
запись обязана быть снята тем же изменением, что её погасило).

## Запрещено

Дописывать функцию в allow-list без разбора ПОЧЕМУ она не течёт в прод —
"кажется, не страшно" причиной не является (то же правило, что у
`entrypoint_import_probe` в `.claude/rules/deployment.md`). Чинить находку —
выставить маркер, а не расширять allow-list.
"""
from __future__ import annotations

import ast
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_PKG_ROOT = _TESTS_DIR.parent                     # spa_core/
_REPO_ROOT = _PKG_ROOT.parent
_SCRIPTS_ROOT = _REPO_ROOT / "scripts"

_SUBPROCESS_CALL_NAMES = {"run", "Popen", "call", "check_call", "check_output"}
_MARKER_SUBSTRINGS = ("SPA_SANDBOX", "SANDBOX_ENV")

#: (путь, имя функции) → разбор, ПОЧЕМУ этой функции маркер C8(b) не нужен.
#: Каждая запись — решение, принятое ЭТИМ файлом, а не предположение.
ALLOWLIST = {
    ("scripts/underwriting_verify_dryrun.py", "_run_verifier_clean"): (
        "PYTHONPATH явно ОПУСТОШЁН (`env[\"PYTHONPATH\"] = \"\"`) — предмет функции "
        "буквально 'NO spa_core importable' (докстринг, `_assert_verifier_has_no_"
        "spa_core_import`). spa_core не импортируется в этом процессе вовсе, поэтому "
        "live_paths там физически не резолвится — маркер защищал бы от риска, которого "
        "здесь нет по конструкции."
    ),
    # N2 (ADR-580 §C8 REVIEW_2, 2026-10-05): запись выше УДАЛЕНА — реальное
    # исправление оказалось доступным (SPA_LIVE_ROOT=sandbox, а не =root), и
    # снятие allow-list entry есть УСИЛЕНИЕ храповика, а не ослабление (явно
    # разрешено правилом «Запрещено» этого файла). Прежний текст аргументировал
    # против SPA_LIVE_ROOT=root — конфигурации, которую маркер C8(b) никогда не
    # требовал: `_default_runner` ставит и SPA_SANDBOX=1, и SPA_LIVE_ROOT на ТУ
    # ЖЕ одноразовую `sandbox`, что уже несёт SPA_DATA_DIR, поэтому
    # `live_root()`, если его позовёт код субъекта, вернёт песочницу, а не
    # прод, независимо от того, чему равен `root`.
}


def _is_subprocess_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Attribute) and f.attr in _SUBPROCESS_CALL_NAMES
            and isinstance(f.value, ast.Name) and f.value.id == "subprocess")


def _sets_pythonpath_key(node: ast.AST) -> bool:
    """``env["PYTHONPATH"] = …`` (или под любым другим именем переменной)."""
    if not isinstance(node, ast.Assign):
        return False
    for target in node.targets:
        if not isinstance(target, ast.Subscript):
            continue
        sl = target.slice
        key = None
        if isinstance(sl, ast.Constant):
            key = sl.value
        elif isinstance(getattr(sl, "value", None), ast.Constant):   # py<3.9 ast.Index
            key = sl.value.value
        if key == "PYTHONPATH":
            return True
    return False


def _scan_file(path: Path) -> list[tuple[str, int]]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (SyntaxError, OSError):
        return []
    lines = src.splitlines()
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_subprocess = any(_is_subprocess_call(n) for n in ast.walk(node))
        has_pythonpath = any(_sets_pythonpath_key(n) for n in ast.walk(node))
        if not (has_subprocess and has_pythonpath):
            continue
        segment = "\n".join(lines[node.lineno - 1:node.end_lineno])
        if not any(marker in segment for marker in _MARKER_SUBSTRINGS):
            found.append((node.name, node.lineno))
    return found


def _candidate_files():
    for root in (_PKG_ROOT, _SCRIPTS_ROOT):
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(_REPO_ROOT).as_posix()
            if "/tests/" in rel or p.name.startswith("test_"):
                continue
            yield p


def _unexplained_findings() -> list[str]:
    out = []
    for path in _candidate_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for name, lineno in _scan_file(path):
            if (rel, name) in ALLOWLIST:
                continue
            out.append(f"{rel}:{lineno} {name}()")
    return out


def test_detector_sees_both_shapes_it_claims_to_see():
    """Положительный контроль самого детектора (ни один сторож без него не считается
    зрячим, `.claude/rules/deployment.md`, «проверка сторожа сторожей»)."""
    src_without_marker = (
        'def run_arm():\n'
        '    env = dict(os.environ)\n'
        '    env["PYTHONPATH"] = str(root)\n'
        '    subprocess.run([x], env=env)\n'
    )
    src_with_marker = (
        'def run_arm():\n'
        '    env = dict(os.environ)\n'
        '    env[live_paths.SANDBOX_ENV] = "1"\n'
        '    env["PYTHONPATH"] = str(root)\n'
        '    subprocess.run([x], env=env)\n'
    )
    src_unrelated_subprocess = (        # calls an external tool, never touches PYTHONPATH
        'def _git():\n'
        '    subprocess.run(["git", "status"], cwd=root)\n'
    )
    tree1 = ast.parse(src_without_marker)
    tree2 = ast.parse(src_with_marker)
    tree3 = ast.parse(src_unrelated_subprocess)

    def _found(tree, src):
        lines = src.splitlines()
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            has_subprocess = any(_is_subprocess_call(n) for n in ast.walk(node))
            has_pythonpath = any(_sets_pythonpath_key(n) for n in ast.walk(node))
            if has_subprocess and has_pythonpath:
                segment = "\n".join(lines[node.lineno - 1:node.end_lineno])
                hits.append(any(m in segment for m in _MARKER_SUBSTRINGS))
        return hits

    assert _found(tree1, src_without_marker) == [False]
    assert _found(tree2, src_with_marker) == [True]
    assert _found(tree3, src_unrelated_subprocess) == []   # not even a candidate


def test_allowlist_entries_still_exist_and_still_lack_the_marker():
    """Храповик в обратную сторону (как у `test_data_dir_env_ratchet.py`): запись
    в allow-list, которая больше не находится детектором (функция починена или
    удалена), — протухшая документация, не защита. Обязана быть снята ТЕМ ЖЕ
    изменением, что убирает находку."""
    all_found = {}
    for path in _candidate_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for name, lineno in _scan_file(path):
            all_found[(rel, name)] = lineno
    for key in ALLOWLIST:
        assert key in all_found, (
            f"allow-list несёт {key}, которого детектор больше не находит — "
            "снять запись ТЕМ ЖЕ изменением, что её погасило")


def test_no_new_subprocess_harness_bypasses_the_sandbox_marker():
    """Единственное утверждение, ради которого файл существует: НИ ОДНА функция,
    запускающая subprocess против переставленного PYTHONPATH, вне allow-list,
    не имеет права молчать о SPA_SANDBOX."""
    findings = _unexplained_findings()
    assert not findings, (
        "Харнесс(ы) запускают subprocess с переставленным PYTHONPATH, не выставляя "
        "SPA_SANDBOX (C8(b), ADR-580) — это класс INC-1 (прод-запись из песочницы):\n  "
        + "\n  ".join(findings)
        + "\n\nЧинить: выставить env[live_paths.SANDBOX_ENV] = \"1\" (+ SPA_DATA_DIR/"
          "SPA_LIVE_ROOT на свою песочницу/копию). Если субпроцесс НЕ может утечь в "
          "прод по другой причине (PYTHONPATH пуст, явный SPA_DATA_DIR раньше маркера, "
          "…) — добавить именованную запись в ALLOWLIST этого файла с разбором ПОЧЕМУ.")
