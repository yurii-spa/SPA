#!/usr/bin/env python3
"""
MP-309: CI Lint — LLM SDK forbidden in L2/L3 modules.

Scans specified directory trees for forbidden LLM SDK imports.
Forbidden in: spa_core/risk, spa_core/execution, spa_core/monitoring,
              spa_core/allocator, spa_core/adapters

Usage:
    python scripts/lint_llm_forbidden.py           # default scan
    python scripts/lint_llm_forbidden.py --strict  # also checks spa_agents/ for SDK imports

Exit codes:
    0 — clean (no violations)
    1 — violations found
    2 — НЕ ИЗМЕРЕНО: вторую дверь спросить было нечем (инв. #17) — не «чисто»

Двери ДВЕ, и обе обязательны (решение владельца 2026-09-09, вариант 1, инжест
ADR-291 §2):
  1. импорт SDK — исторический регексп этого файла;
  2. ЗАПУСК бинаря `claude` подпроцессом — правило живёт ОДНОЙ копией в
     `spa_core/ci/llm_forbidden_lint.find_llm_subprocess_launches` (AST, поток
     значения). Вторая копия здесь разошлась бы с первой при первой же правке:
     ровно так два сторожа инварианта #3 и разошлись — AST-сторож существовал,
     но CI звал ТОЛЬКО этот файл, и дверь-запуск не охранял никто.
"""

import argparse
import os
import re
import sys

# launchd/CI зовут скрипт ПО ПУТИ: `sys.path[0]` — каталог `scripts/`, и без
# этого блока импорт `spa_core` ниже умер бы на первой строке (класс ADR-347 /
# ADR-370, храповик `path_launch_import_baseline.json`).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from spa_core.ci.llm_forbidden_lint import find_llm_subprocess_launches
    _DOOR2_IMPORT_ERROR = None
except Exception as _exc:  # noqa: BLE001 — любая причина равно означает «нечем спросить»
    find_llm_subprocess_launches = None  # type: ignore[assignment]
    _DOOR2_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

# ── Forbidden patterns ────────────────────────────────────────────────────────
FORBIDDEN_PATTERNS = [
    re.compile(r'^\s*import\s+anthropic\b'),
    re.compile(r'^\s*from\s+anthropic\b'),
    re.compile(r'^\s*import\s+openai\b'),
    re.compile(r'^\s*from\s+openai\b'),
    re.compile(r'^\s*import\s+google\.generativeai\b'),
    re.compile(r'^\s*from\s+google\.generativeai\b'),
    re.compile(r'^\s*import\s+langchain\b'),
    re.compile(r'^\s*from\s+langchain\b'),
    re.compile(r'^\s*import\s+llama\b'),
    re.compile(r'^\s*from\s+llama\b'),
]

# Patterns checked only in --strict mode (spa_agents/): same SDK set
STRICT_PATTERNS = FORBIDDEN_PATTERNS  # same list — SDK use forbidden there too

# ── Directory targets ─────────────────────────────────────────────────────────
SCAN_DIRS_DEFAULT = [
    "spa_core/risk",
    "spa_core/execution",
    "spa_core/monitoring",
    "spa_core/allocator",
    "spa_core/adapters",
]

SCAN_DIRS_STRICT_EXTRA = [
    "spa_agents",
]


def _is_test_file(filename: str) -> bool:
    """Return True for test_*.py files (should be skipped)."""
    return filename.startswith("test_") and filename.endswith(".py")


def _should_skip(dirpath: str, filename: str) -> bool:
    """Return True if the file should be skipped entirely."""
    # Skip __pycache__ directories
    if "__pycache__" in dirpath.split(os.sep):
        return True
    # Skip compiled bytecode
    if filename.endswith(".pyc"):
        return True
    # Skip test files
    if _is_test_file(filename):
        return True
    # Only scan .py files
    if not filename.endswith(".py"):
        return True
    return False


def scan_file(filepath: str, patterns: list) -> list:
    """
    Scan a single .py file for forbidden import patterns.

    Returns list of (lineno, matched_text) tuples for violations.
    """
    violations = []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.rstrip("\n")
                # Strip inline comments: find '#' that is not inside a string.
                # Simple heuristic: if '#' appears before any import keyword
                # position AND the line (stripped) starts with '#', skip entirely.
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    # Entire line is a comment — skip
                    continue
                for pattern in patterns:
                    if pattern.match(line):
                        violations.append((lineno, line.strip()))
                        break  # one violation per line is enough
    except OSError as exc:
        print(f"WARNING: cannot read {filepath}: {exc}", file=sys.stderr)
    return violations


def scan_directory(dirpath: str, patterns: list, base_dir: str) -> tuple:
    """
    Walk dirpath, scan all eligible .py files.

    Returns (file_count, violations_list) where violations_list contains
    (rel_filepath, lineno, matched_text).
    """
    file_count = 0
    violations = []

    if not os.path.isdir(dirpath):
        # Directory doesn't exist — not an error, just skip
        return file_count, violations

    for root, dirs, files in os.walk(dirpath):
        # Prune __pycache__ from traversal in-place
        dirs[:] = [d for d in dirs if d != "__pycache__"]

        for filename in sorted(files):
            if _should_skip(root, filename):
                continue

            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, base_dir)
            file_count += 1

            file_violations = scan_file(full_path, patterns)
            for lineno, matched_text in file_violations:
                violations.append((rel_path, lineno, matched_text))

    return file_count, violations


def run_lint(base_dir: str, strict: bool = False) -> tuple:
    """Дверь ПЕРВАЯ (импорт SDK) — и только она.

    Returns (total_files, total_violations_list).

    ⚠️ Это ПОЛОВИНА правила инварианта #3. Полный вердикт — :func:`run_all`
    (её зовёт :func:`main`): вторая дверь, запуск бинаря подпроцессом, мерится
    отдельной функцией, и «зелёный run_lint» о ней не говорит НИЧЕГО. Строка
    стои́т здесь потому, что именно такое прочтение («сторож зелёный ⇒ правило
    охраняется») и держало дверь-запуск открытой с MP-309 по 2026-10-07.
    """
    targets = list(SCAN_DIRS_DEFAULT)
    if strict:
        targets += SCAN_DIRS_STRICT_EXTRA

    total_files = 0
    all_violations = []

    for rel_dir in targets:
        full_dir = os.path.join(base_dir, rel_dir)
        file_count, violations = scan_directory(full_dir, FORBIDDEN_PATTERNS, base_dir)
        total_files += file_count
        all_violations.extend(violations)

    return total_files, all_violations


def run_launch_lint(base_dir: str, strict: bool = False) -> tuple:
    """Дверь ВТОРАЯ: запуск бинаря LLM подпроцессом из охраняемых каталогов.

    Returns ``(total_files, launch_violations, unmeasured)`` where
    ``launch_violations`` is a list of ``(rel_path, lineno, text)`` and
    ``unmeasured`` is ``None`` or the named reason the door could not be asked.

    Отсутствие инструмента — САМОСТОЯТЕЛЬНЫЙ третий исход (инв. #17), а не
    пустой список: пустой список здесь неотличим от «просканировано и чисто»,
    и это ровно тот fail-OPEN, тише красного теста, из-за которого дверь и
    прожила открытой.
    """
    if find_llm_subprocess_launches is None:
        return 0, [], (
            "spa_core.ci.llm_forbidden_lint не импортируется "
            f"({_DOOR2_IMPORT_ERROR}) — дверь-запуск НЕ ИЗМЕРЕНА"
        )

    targets = list(SCAN_DIRS_DEFAULT)
    if strict:
        targets += SCAN_DIRS_STRICT_EXTRA

    total_files = 0
    violations = []
    for rel_dir in targets:
        full_dir = os.path.join(base_dir, rel_dir)
        if not os.path.isdir(full_dir):
            continue
        for root, dirs, files in os.walk(full_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for filename in sorted(files):
                if _should_skip(root, filename):
                    continue
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, base_dir)
                total_files += 1
                try:
                    source = open(full_path, encoding="utf-8",
                                  errors="replace").read()
                    found = find_llm_subprocess_launches(source, rel_path)
                except SyntaxError as exc:
                    return total_files, violations, (
                        f"{rel_path}: SyntaxError на строке {exc.lineno} — "
                        "файл не разобран, дверь-запуск по нему НЕ ИЗМЕРЕНА"
                    )
                except OSError as exc:
                    return total_files, violations, (
                        f"{rel_path}: {type(exc).__name__}: {exc} — "
                        "файл не прочитан, дверь-запуск по нему НЕ ИЗМЕРЕНА"
                    )
                for lv in found:
                    violations.append((
                        rel_path, lv.line,
                        f"launches {lv.binary} via {lv.via}",
                    ))
    return total_files, violations, None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint for forbidden LLM SDK imports in L2/L3 SPA modules."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also scan spa_agents/ (agents must use urllib.request, not SDK)",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Base directory of the SPA project (default: directory of this script's parent)",
    )
    args = parser.parse_args(argv)

    # Resolve base directory
    if args.base_dir:
        base_dir = os.path.abspath(args.base_dir)
    else:
        # scripts/lint_llm_forbidden.py → parent = project root
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(script_dir)

    total_files, violations = run_lint(base_dir, strict=args.strict)
    launch_files, launch_violations, unmeasured = run_launch_lint(
        base_dir, strict=args.strict)

    # Print violations — door 1 (SDK import) then door 2 (subprocess launch)
    for rel_path, lineno, matched_text in violations:
        print(f"VIOLATION: {rel_path}:{lineno}: {matched_text}")
    for rel_path, lineno, matched_text in launch_violations:
        print(f"VIOLATION: {rel_path}:{lineno}: {matched_text}")

    # Print summary
    print(f"Scanned {total_files} files, found {len(violations)} violations")
    if unmeasured is None:
        print(f"Launch door: scanned {launch_files} files, "
              f"found {len(launch_violations)} violations")
    else:
        print(f"Launch door: НЕ ИЗМЕРЕНО — {unmeasured}", file=sys.stderr)

    if unmeasured is not None:
        # Третий исход НИКОГДА не выдаётся за «чисто»: нарушения двери-SDK
        # печатаются и остаются видимыми, но вердикт прогона — «не измерено».
        return 2
    return 1 if (violations or launch_violations) else 0


if __name__ == "__main__":
    sys.exit(main())
