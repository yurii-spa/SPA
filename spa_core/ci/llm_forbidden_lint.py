"""LLM-forbidden static lint for deterministic L2/L3 domains (SPA-V416 / MP-309).

Project constitution: ``LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}`` —
the deterministic L2/L3 domains (risk, execution, allocator) make capital-
affecting decisions and therefore must NEVER import an LLM SDK. An LLM may
*advise* (architect / analytics layers); it may never sit on the code path
that scores risk, routes execution, or sizes allocations. This module turns
that constitutional rule into enforceable CI code — the institutional-DD
"prove it" answer.

What it does
============
Recursively AST-parses every ``*.py`` under the forbidden directories
(:data:`FORBIDDEN_DIRS`) and flags any ``import X`` / ``from X import Y``
whose top-level (or dotted-prefix) module is in :data:`FORBIDDEN_IMPORTS`.
Matching is by module prefix, so ``import anthropic``, ``import anthropic.foo``
and ``from anthropic import Anthropic`` are all caught, while a *string* or
*comment* containing the words "import anthropic" is NOT (this is an AST
lint, not a grep). Files that fail to parse are reported in a separate
``parse_errors`` bucket — a syntax error must never hide a violation scan of
the remaining files, nor crash CI with a stack trace.

IMPORTANT — read-only boundary (SPA-BL-011 / LLM_FORBIDDEN_AGENTS):
this linter is **strictly read-only and advisory-on-source**. It only READS
the source text of ``risk/``, ``execution/`` and ``allocator/`` — it never
imports, executes, or modifies them, never touches wallets, money-moving
code, or the feed-health domain. Its single side effect (CLI mode only) is
an atomically-written JSON report. The linter itself is pure stdlib: it does
not import any LLM SDK, web3, requests, or perform any network I/O — the
forbidden modules are searched for *textually via AST*, never imported.

Report schema (``data/llm_forbidden_lint.json``)::

    {
        "generated_at": "...Z",
        "root": "<scanned repo root>",
        "forbidden_imports": [...],
        "scanned_dirs": [...],          # forbidden dirs that actually exist
        "files_scanned": int,
        "violations": [{"file", "line", "module"}],
        "launch_violations": [{"file", "line", "binary", "via"}],
        "parse_errors": [{"file", "error"}],
        "status": "ok" | "violations" | "no_dirs"
    }

CLI::

    python3 -m spa_core.ci.llm_forbidden_lint
    python3 -m spa_core.ci.llm_forbidden_lint --root . \\
        --out data/llm_forbidden_lint.json
    python3 -m spa_core.ci.llm_forbidden_lint --no-write

Exit codes: 0 = ok (clean), 1 = violations found, 2 = no forbidden dirs
found under --root (mis-configured invocation) or unexpected error.
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

log = logging.getLogger("spa.ci.llm_forbidden_lint")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "llm_forbidden_lint.json"

SCHEMA_VERSION = 2

# LLM SDK top-level modules (or dotted prefixes) that must never be imported
# from a deterministic domain. Matching is prefix-based on the dotted path:
# "anthropic", "anthropic.foo", "from anthropic import X" all match
# "anthropic"; "google.generativeai" matches even though "google" alone is
# allowed (google.cloud etc. would be fine).
FORBIDDEN_IMPORTS = frozenset({
    "anthropic",
    "google.generativeai",
    "openai",
    "langchain",
    "litellm",
})

# Deterministic L2/L3 domains, relative to the repo root. Verified to exist
# in this repo (spa_core/feed_health does not exist as a package — the
# feed-health monitors live under spa_core/data_pipeline and are covered by
# SPA-BL-011 freeze, not by this lint's directory list). Only directories
# that actually exist at scan time are scanned; missing ones are skipped.
FORBIDDEN_DIRS: Tuple[str, ...] = (
    "spa_core/risk",        # L2 deterministic risk scoring / policy gate
    "spa_core/execution",   # L3 execution: adapters, router, wallet, safety
    "spa_core/allocator",   # L2 deterministic capital allocator
    "spa_core/monitoring",  # deterministic health/agent monitors — CLAUDE.md
                            # rule#5 LLM-FORBIDDEN; was a silent gap (WS2).
)

# Directory names never descended into.
_SKIP_DIR_NAMES = frozenset({"__pycache__"})


@dataclass(frozen=True)
class Violation:
    """A single forbidden import found in a deterministic domain."""
    file: str    # path relative to the scanned root (posix separators)
    line: int    # 1-based line number of the import statement
    module: str  # the dotted module name as written in the import


@dataclass(frozen=True)
class ParseError:
    """A file that could not be AST-parsed (reported, never fatal)."""
    file: str
    error: str


# ─── Pure analytic core ──────────────────────────────────────────────────────

def _is_forbidden_module(module: str) -> bool:
    """True if ``module`` matches any forbidden entry by dotted prefix."""
    for forbidden in FORBIDDEN_IMPORTS:
        if module == forbidden or module.startswith(forbidden + "."):
            return True
    return False


def find_forbidden_imports(source: str, filename: str = "<string>") -> List[Violation]:
    """AST-scan one Python source string for forbidden LLM imports. Pure.

    Catches ``import X``, ``import X.Y``, ``from X import Y`` and
    ``from X import Y`` where ``X.Y`` itself is the forbidden dotted path
    (e.g. ``from google import generativeai``). Relative imports
    (``from . import x``) can never reach an external SDK and are ignored.
    Comments and string literals are inherently ignored (AST, not grep).

    Raises ``SyntaxError`` on unparseable source — callers decide how to
    bucket that (see :func:`scan_directory`).
    """
    tree = ast.parse(source, filename=filename)
    violations: List[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    violations.append(Violation(filename, node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — cannot be an external SDK
                continue
            module = node.module or ""
            if module and _is_forbidden_module(module):
                violations.append(Violation(filename, node.lineno, module))
                continue
            # `from google import generativeai` — the forbidden dotted path
            # is module + "." + imported name.
            for alias in node.names:
                if module and _is_forbidden_module(f"{module}.{alias.name}"):
                    violations.append(
                        Violation(filename, node.lineno, f"{module}.{alias.name}")
                    )
    return violations


# ─── Door 2: LAUNCHING the LLM as a subprocess ───────────────────────────────
#
# Инвариант #3 запрещает LLM в risk / execution / monitoring / allocator. До
# 2026-10-07 его охраняла ОДНА проба — импорт SDK, — а разговаривает эта
# система с Claude ИНАЧЕ: запускает бинарь `claude -p` подпроцессом
# (`spa_core/telegram/ask_router.py`, `spa_core/owner_queue/history_check.py`,
# `scripts/morning_work_digest.py`, `scripts/cartographer/snapshot.py` — все
# четыре ВНЕ охраняемых каталогов, и это сегодняшнее положение, а не гарантия).
# Замер шага 0-офис 07.10 (`cio_architecture_constraints`, §45): контрольная
# дверь-SDK в `spa_core/risk/` ловится, дверь-subprocess в ТОМ ЖЕ каталоге —
# НЕТ, ноль нарушений. Правило выполнялось случайно: вписать вызов ИИ в
# risk/execution/monitoring можно, и ни одна проверка не покраснела бы.
#
# Решение владельца — карточка
# `owner-decision-ii-ne-puskayut-k-dengam-no-proverka-koto`, `owner_choice: 1`,
# telegram 2026-09-09T06:13:34Z, инжест ADR-291 §2: «считать нарушением и
# запуск программы `claude` из папок риска, исполнения, наблюдения». Инвариант
# #3 этим не расширяется и не ослабляется — он впервые получает проверку на ту
# дверь, которой система пользуется. Ни один порог не изменён, население
# каталогов (:data:`FORBIDDEN_DIRS`) не тронуто.
#
# МЕРА — ПОТОК ЗНАЧЕНИЯ, А НЕ ТОКЕН. Упоминание имени читателем не делает, и
# у этого правила есть два живых отрицательных контроля в самом дереве:
# `spa_core/monitoring/telegram_watcher.py` называет `ANTHROPIC_API_KEY` внутри
# ТЕКСТА ОШИБКИ и запускает `security`; `scripts/fill_agent_passports.py` ищет
# строку `"CLAUDE_BIN"` и запускает `git`. Ни один не нарушитель. Поэтому
# нарушение объявляется только тогда, когда значение, ПРОИСХОДЯЩЕЕ от имени
# бинаря, доходит до argv пускающего вызова.
#
# КОНТЕЙНЕР ЗДЕСЬ ПРИВЯЗКОЙ СЧИТАЕТСЯ — сознательно обратно правилу
# `.claude/rules/deployment.md` («контейнер привязкой НЕ является», класс
# замороженных дат). Там контейнер был совпадением рядом
# (`doc = {"generated_at": …}` возле `age_hours(doc)`); здесь argv ЕСТЬ
# контейнер по построению: живая форма двери — ровно
# `subprocess.run([_CLAUDE, "-p", …])`. Отказать контейнеру в происхождении
# значило бы не увидеть единственную существующую форму.
#
# НЕ ДОКЛАДЫВАЕТ: поток через ПАРАМЕТР функции или через чужой модуль (имя,
# полученное аргументом, здесь не отслеживается) · имя бинаря, собранное из
# частей в рантайме · запуск через ПОСРЕДНИКА — локальную обёртку (`run([...])`
# внутри того же файла) или шелл-скрипт, который сам зовёт `claude` ·
# достижимость самого вызова (дорога есть форма, а не исполнение).

# Население — ЛЮБОЙ бинарь LLM, а не только `claude`. Инвариант #3 запрещает
# «LLM», и сужать его до одного имени значило бы оставить дверь соседу: тот же
# замер 07.10 нашёл `ollama` подпроцессом в `scripts/cartographer/snapshot.py`
# (вне охраняемых каталогов — поэтому не нарушение, но форма та же). Набор
# совпадает с `_LLM_BINARIES` советательного сторожа
# `spa_core/monitoring/cio_architecture_constraints.py`; копией он здесь не
# является по НАЗНАЧЕНИЮ: тот — ADVISORY и мерит ЧУЖУЮ слепоту, этот —
# CI-гейт. Гейт не вправе зависеть от советательного модуля, а список держит
# свой же тест (`test_llm_binaries_cover_the_advisory_guards_set`).
_LLM_BINARY_NAMES = frozenset({"claude", "ollama", "llm"})

# Производные имена бинаря (`claude-code`, `claude_cli`): дверь та же.
_LLM_BINARY_PREFIXES = ("claude",)

# Имя переменной окружения, несущей путь к бинарю (`SPA_CLAUDE_BIN`,
# `CLAUDE_BIN`, `OLLAMA_HOST`). Совпадение ПОЛНОЗНАЧНОЕ: `CLAUDE.md` (точка) и
# фраза "see `claude -p`" (пробелы) якорями не являются — именно это и отделяет
# упоминание от читателя.
_LLM_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*(CLAUDE|OLLAMA)[A-Z0-9_]*$")

# Пускающие вызовы stdlib, по модулю. Список закрыт намеренно: открытый
# («любой вызов с argv-похожим аргументом») краснел бы на невиновных.
_LAUNCH_ATTRS: Dict[str, Tuple[str, ...]] = {
    "subprocess": ("run", "call", "check_call", "check_output", "Popen",
                   "getoutput", "getstatusoutput"),
    "os": ("system", "popen", "execl", "execle", "execlp", "execlpe",
           "execv", "execve", "execvp", "execvpe",
           "posix_spawn", "posix_spawnp",
           "spawnl", "spawnle", "spawnlp", "spawnlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe"),
}

# argv-несущие ключевые аргументы. `env=` намеренно НЕ здесь: имя переменной
# окружения, переданное в `env`, не есть запускаемая программа — считать его
# нарушением значило бы покраснеть на том, кто ИИ как раз не зовёт.
_ARGV_KEYWORDS = frozenset({"args", "cmd", "command", "argv", "file", "path"})


@dataclass(frozen=True)
class LaunchViolation:
    """Запуск бинаря LLM подпроцессом из детерминированного домена."""
    file: str      # путь относительно сканируемого корня (posix)
    line: int      # 1-based строка пускающего вызова
    binary: str    # якорь: имя бинаря / переменной окружения / несущее имя
    via: str       # пускающий вызов, как он разрешён по дереву


def _names_an_llm_binary(value: object) -> bool:
    """True, если СТРОКА целиком называет бинарь LLM или его env-переменную."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return False
    tail = v.rsplit("/", 1)[-1] if "/" in v else v
    if tail in _LLM_BINARY_NAMES:
        return True
    if tail.startswith(_LLM_BINARY_PREFIXES):
        return True
    return bool(_LLM_ENV_NAME.match(v))


def _target_names(node: ast.AST) -> List[str]:
    """Имена, которым присваивает узел (Name → id, Attribute → attr)."""
    targets: List[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
        targets = [node.target]
    names: List[str] = []
    for tgt in targets:
        for sub in ast.walk(tgt):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
            elif isinstance(sub, ast.Attribute):
                names.append(sub.attr)
    return names


def _carries_anchor(node: Optional[ast.AST], derived: "frozenset[str] | set[str]") -> bool:
    """Несёт ли поддерево якорь-литерал или имя, ПРОИСХОДЯЩЕЕ от якоря."""
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and _names_an_llm_binary(sub.value):
            return True
        if isinstance(sub, ast.Name) and sub.id in derived:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in derived:
            return True
    return False


def _derived_names(tree: ast.AST) -> "set[str]":
    """Имена, чьё значение происходит от якоря — до неподвижной точки.

    Неподвижная точка нужна, потому что дверь живёт в два шага:
    ``_CLAUDE = os.environ.get("SPA_CLAUDE_BIN") or "…/claude"`` и затем
    ``argv = [_CLAUDE, "-p"]`` — одношаговая мера увидела бы только первый.
    """
    derived: "set[str]" = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign,
                                     ast.AugAssign, ast.NamedExpr)):
                continue
            if not _carries_anchor(getattr(node, "value", None), derived):
                continue
            for name in _target_names(node):
                if name not in derived:
                    derived.add(name)
                    changed = True
    return derived


def _launch_aliases(tree: ast.AST) -> "tuple[dict, dict]":
    """(псевдоним модуля → модуль, псевдоним функции → точечное имя).

    Измеряется ПО ДЕРЕВУ, а не угадывается: ``import subprocess as sp`` и
    ``from subprocess import run as r`` обе формы живые.
    """
    modules: Dict[str, str] = {}
    funcs: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _LAUNCH_ATTRS:
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and not node.level:
            mod = node.module or ""
            if mod not in _LAUNCH_ATTRS:
                continue
            for alias in node.names:
                if alias.name in _LAUNCH_ATTRS[mod]:
                    funcs[alias.asname or alias.name] = f"{mod}.{alias.name}"
    return modules, funcs


def _launch_name(func: ast.AST, modules: Dict[str, str],
                 funcs: Dict[str, str]) -> Optional[str]:
    """Точечное имя пускающего вызова, либо None — вызов не пускающий."""
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        mod = modules.get(func.value.id)
        if mod and func.attr in _LAUNCH_ATTRS[mod]:
            return f"{mod}.{func.attr}"
        return None
    if isinstance(func, ast.Name):
        return funcs.get(func.id)
    return None


def _program_position(node: ast.AST, shell: bool) -> ast.AST:
    """Та часть argv-носителя, которая и есть ЗАПУСКАЕМАЯ ПРОГРАММА.

    У списка/кортежа это ПЕРВЫЙ элемент, и сужение существенно, а не
    косметично: `subprocess.run(["which", "ollama"])` — проба наличия бинаря,
    а не его запуск, и считать её нарушением значило бы покраснеть на том, кто
    LLM как раз НЕ зовёт (живой пример — `scripts/cartographer/snapshot.py`,
    которого советательный сторож офиса числит дверью именно по этой причине).
    При ``shell=True`` программа не отделена от аргументов вовсе, поэтому
    смотрится всё выражение целиком.
    """
    if shell:
        return node
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        return node.elts[0]
    return node


def _anchor_text(node: ast.AST, derived: "set[str]") -> str:
    """Чем именно назван бинарь в этом вызове — для текста находки."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and _names_an_llm_binary(sub.value):
            return str(sub.value)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in derived:
            return sub.id
        if isinstance(sub, ast.Attribute) and sub.attr in derived:
            return sub.attr
    return "<unnamed>"


def find_llm_subprocess_launches(
    source: str, filename: str = "<string>"
) -> List[LaunchViolation]:
    """AST-поиск запусков бинаря LLM подпроцессом. Чистая функция.

    Поднимает ``SyntaxError`` на неразбираемом источнике — бакетует вызывающий
    (:func:`scan_directory`), и это ТРЕТИЙ ИСХОД, а не «чисто» (инв. #17).
    """
    tree = ast.parse(source, filename=filename)
    modules, funcs = _launch_aliases(tree)
    if not modules and not funcs:
        return []
    derived = _derived_names(tree)
    found: List[LaunchViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        via = _launch_name(node.func, modules, funcs)
        if via is None:
            continue
        shell = any(
            kw.arg == "shell" and isinstance(kw.value, ast.Constant)
            and bool(kw.value.value)
            for kw in node.keywords
        )
        carriers: List[ast.AST] = list(node.args)
        carriers += [kw.value for kw in node.keywords if kw.arg in _ARGV_KEYWORDS]
        hit = next((c for c in carriers
                    if _carries_anchor(_program_position(c, shell), derived)), None)
        if hit is None:
            continue
        hit = _program_position(hit, shell)
        found.append(LaunchViolation(filename, node.lineno,
                                     _anchor_text(hit, derived), via))
    return found



def _iter_py_files(directory: Path) -> Iterable[Path]:
    """Yield ``*.py`` files under ``directory`` recursively, deterministically
    sorted, skipping ``__pycache__``."""
    for path in sorted(directory.rglob("*.py")):
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def scan_directory(
    directory: Path, root: Path
) -> Tuple[int, List[Violation], List[ParseError], List[LaunchViolation]]:
    """Scan one forbidden directory. Read-only: only reads source files.

    Returns ``(files_scanned, violations, parse_errors, launch_violations)``.
    File paths in the results are relative to ``root`` with posix separators.
    A ``SyntaxError`` (or undecodable file) goes to ``parse_errors`` and never
    aborts the scan.

    ОБЕ двери мерятся за ОДИН разбор файла: дверь-SDK (импорт) и дверь-запуск
    (бинарь подпроцессом, решение владельца 2026-09-09). Разбор один, потому
    что два разбора разошлись бы при первой же правке — тот же класс «одно
    правило, две копии», что и два сторожа инварианта #3.
    """
    files_scanned = 0
    violations: List[Violation] = []
    parse_errors: List[ParseError] = []
    launches: List[LaunchViolation] = []
    for path in _iter_py_files(directory):
        rel = path.relative_to(root).as_posix()
        files_scanned += 1
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            violations.extend(find_forbidden_imports(source, rel))
            launches.extend(find_llm_subprocess_launches(source, rel))
        except SyntaxError as exc:
            parse_errors.append(ParseError(rel, f"SyntaxError: {exc.msg} (line {exc.lineno})"))
        except OSError as exc:  # unreadable file — report, do not crash CI
            parse_errors.append(ParseError(rel, f"{type(exc).__name__}: {exc}"))
    return files_scanned, violations, parse_errors, launches


def run_lint(
    root: Union[str, Path] = ".",
    forbidden_dirs: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    """Run the full lint over ``root``. Pure w.r.t. the repo: reads source
    files only, mutates nothing, performs no I/O besides reading.

    ``forbidden_dirs`` defaults to :data:`FORBIDDEN_DIRS`; only directories
    that exist under ``root`` are scanned (missing ones are skipped). If
    *none* exist (or the list is empty) the status is ``"no_dirs"`` — a
    mis-pointed --root must fail loudly in CI rather than report a vacuous
    "ok".

    Returns the report dict (see module docstring for the schema).
    """
    root_path = Path(root).resolve()
    dirs = tuple(FORBIDDEN_DIRS if forbidden_dirs is None else forbidden_dirs)

    scanned_dirs: List[str] = []
    files_scanned = 0
    violations: List[Violation] = []
    parse_errors: List[ParseError] = []
    launches: List[LaunchViolation] = []

    for rel_dir in dirs:
        directory = root_path / rel_dir
        if not directory.is_dir():
            log.debug("forbidden dir missing, skipped: %s", directory)
            continue
        scanned_dirs.append(rel_dir)
        n, v, p, lv = scan_directory(directory, root_path)
        files_scanned += n
        violations.extend(v)
        parse_errors.extend(p)
        launches.extend(lv)

    if not scanned_dirs:
        status = "no_dirs"
    elif violations or launches:
        # Запуск бинаря — такое же нарушение инварианта #3, как импорт SDK
        # (решение владельца 2026-09-09, вариант 1). Отдельный бакет держится
        # потому, что это ДРУГАЯ дверь и читателю надо знать какая; вердикт —
        # общий, иначе вторая дверь была бы «найдено и пропущено».
        status = "violations"
    else:
        status = "ok"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root_path),
        "forbidden_imports": sorted(FORBIDDEN_IMPORTS),
        "scanned_dirs": scanned_dirs,
        "files_scanned": files_scanned,
        "violations": [asdict(v) for v in violations],
        "launch_violations": [asdict(v) for v in launches],
        "parse_errors": [asdict(p) for p in parse_errors],
        "status": status,
    }


# ─── Thin I/O / CLI wrapper ──────────────────────────────────────────────────

def write_report_atomic(report: Dict[str, object], out_path: Union[str, Path]) -> None:
    """Atomically write the report JSON (tmp file + ``os.replace``)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.ci.llm_forbidden_lint",
        description=(
            "Static CI lint: LLM SDK imports are FORBIDDEN in the "
            "deterministic risk/execution/allocator domains (MP-309)."
        ),
    )
    parser.add_argument(
        "--root", default=str(_PROJECT_ROOT),
        help="repo root to scan (default: this checkout's root)",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="report JSON path (default: data/llm_forbidden_lint.json)",
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="do not write the report file, print summary only",
    )
    args = parser.parse_args(argv)

    try:
        report = run_lint(args.root)
    except Exception as exc:  # defensive: CI must get a clean exit code
        print(f"llm_forbidden_lint: ERROR — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not args.no_write:
        try:
            write_report_atomic(report, args.out)
        except OSError as exc:
            print(f"llm_forbidden_lint: cannot write report: {exc}", file=sys.stderr)
            return 2

    status = report["status"]
    print(
        f"llm_forbidden_lint: status={status} "
        f"dirs={len(report['scanned_dirs'])} files={report['files_scanned']} "
        f"violations={len(report['violations'])} "
        f"launch_violations={len(report['launch_violations'])} "
        f"parse_errors={len(report['parse_errors'])}"
    )
    for v in report["violations"]:
        print(f"  VIOLATION {v['file']}:{v['line']} imports {v['module']}")
    for v in report["launch_violations"]:
        print(f"  VIOLATION {v['file']}:{v['line']} launches "
              f"{v['binary']} via {v['via']}")
    for p in report["parse_errors"]:
        print(f"  PARSE_ERROR {p['file']}: {p['error']}")
    if status == "no_dirs":
        print(
            "  no forbidden directories found under --root "
            f"({args.root!r}) — check the invocation", file=sys.stderr,
        )

    return {"ok": 0, "violations": 1}.get(status, 2)


if __name__ == "__main__":
    sys.exit(main())
