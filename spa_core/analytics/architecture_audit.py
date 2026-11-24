"""
spa_core/analytics/architecture_audit.py

Self-audit of the SPA codebase.
Checks compliance with SPA RULES.md conventions.

Usage:
  python3 -m spa_core.analytics.architecture_audit
  python3 -m spa_core.analytics.architecture_audit --json
  python3 -m spa_core.analytics.architecture_audit --save

Output (terminal):
  Architecture Audit Report
  ─────────────────────────────────────────────────
  ✅  no_third_party_imports    0 violations
  ⚠️   atomic_writes             2 violations (WARNING)
  ✅  no_hardcoded_secrets      0 violations
  ✅  adapters_have_research_flag  0 violations
  ✅  tests_use_unittest         0 violations
  ─────────────────────────────────────────────────
  TOTAL: 2 violations

MP-1374 (v9.90)
stdlib only. Read-only advisory. LLM FORBIDDEN.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import io
import re
import sys
import tempfile
import tokenize
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ── Repo-root resolution ──────────────────────────────────────────────────────

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent.parent  # spa_core/analytics/.. → spa_core/.. → repo
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── Constants ─────────────────────────────────────────────────────────────────

AUDIT_RULES = [
    "no_third_party_imports",
    "atomic_writes",
    "no_llm_in_analytics",
    "no_hardcoded_secrets",
    "adapters_have_research_flag",
    "tests_use_unittest",
    "no_print_in_modules",  # use logging instead
]

#: Правило, ОБЪЯВЛЕННОЕ в :data:`AUDIT_RULES` и намеренно НЕ исполняемое, —
#: вместе с причиной. Это ТРЕТИЙ ИСХОД инварианта #17, а не ноль: до ADR-1091
#: такое правило печаталось в отчёте «0 violation(s)» наравне с правилом,
#: которое по дереву действительно прошло и ничего не нашло, — то есть «не
#: измерено» было неотличимо от «измерено и равно нулю» (карточка
#: `inbox-audit-obyavlyaet-sem-pravil-a-ispolnyaet`, заказ G1075 п. 4).
#:
#: Имя из :data:`AUDIT_RULES` снимать ЗАПРЕЩЕНО вместо объявления здесь:
#: снятие стирает ВОПРОС, а объявление делает долг названным и читаемым
#: машиной (перепись `scripts/test_membership_door_census.py`).
RULE_NOT_IMPLEMENTED: dict[str, str] = {
    "no_print_in_modules": (
        "НЕ РЕАЛИЗОВАНО намеренно: замер 2026-11-24 по этому же дереву — "
        "5548 зовов print() в 1176 из 2237 НЕ-тестовых модулей spa_core/ "
        "(52,6 % модулей). print() в этом проекте есть ШТАТНАЯ форма отчёта "
        "CLI: протокол цикла судит каждый обязательный шаг по НАПЕЧАТАННОЙ "
        "строке вердикта, а инвариант #17 требует от производителя числа "
        "печатать три различимых исхода. Правило «вместо print — logging» "
        "половиной дерева не исполняется и никогда не исполнялось; "
        "потолок на 5548 мог бы только УБЫВАТЬ (инв. #16) и тем давил бы "
        "следующие сессии переписывать отчёты CLI в логи — изменение, "
        "которого никто не заказывал и на котором стои́т протокол. "
        "Перевод правила в исполняемое — решение владельца, не сессии; "
        "ни один другой сторож дерева на этот вопрос тоже не отвечает "
        "(замер: ни одного упоминания no_print вне этого модуля и его проб)."
    ),
}

#: Исходы, в которых аудит докладывает о правиле. ТРИ, а не два (инв. #17).
SEVERITIES: tuple[str, ...] = ("ERROR", "WARNING", "UNMEASURED")

#: Каталог, о котором спрашивает правило ``no_llm_in_analytics``.
#:
#: ЗАМЕР 2026-11-24, ради которого правило и реализовано: обе существующие
#: двери запрета LLM — ``find_forbidden_imports`` (импорт SDK) и
#: ``find_llm_subprocess_launches`` (запуск бинаря подпроцессом) — живут в
#: ``spa_core/ci/llm_forbidden_lint`` ОДНОЙ копией каждая, но перечни
#: каталогов, которые их ЗОВУТ (``FORBIDDEN_DIRS`` там же и
#: ``SCAN_DIRS_DEFAULT`` в ``scripts/lint_llm_forbidden.py``), называют
#: risk · execution · monitoring · allocator · adapters · governance · tuner —
#: и НЕ называют ``spa_core/analytics``. То есть вопрос «нет ли LLM в
#: аналитике» не задавал НИКТО, и правило — не дубль, а единственный читатель
#: этого поддерева. Копии самого правила здесь нет: обе двери ввозятся
#: (разойдись копия с оригиналом — охранялись бы разные вопросы, ровно так
#: два сторожа инварианта #3 и разошлись до ADR-291 §2).
_LLM_SCAN_SUBDIR = "analytics"

# Known third-party packages that must NOT appear in SPA runtime code.
# Only well-known offenders are listed; ambiguous short names are excluded
# to avoid false positives on local same-name modules.
_KNOWN_THIRD_PARTY: frozenset[str] = frozenset({
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "pandas",
    "numpy",
    "scipy",
    "matplotlib",
    "seaborn",
    "sklearn",
    "tensorflow",
    "torch",
    "web3",
    "eth_account",
    "eth_abi",
    "brownie",
    "flask",
    "fastapi",
    "django",
    "starlette",
    "uvicorn",
    "celery",
    "redis",
    "boto3",
    "botocore",
    "pymongo",
    "sqlalchemy",
    "alembic",
    "pydantic",
    "yaml",
    "toml",
    "dotenv",
    "click",
    "typer",
    "rich",
    "tqdm",
    "loguru",
})

# Subdirectories of spa_core that are PURE BUSINESS LOGIC and must be stdlib-only.
# These are the modules that run in the daily paper-trading cycle.
# Excluded from third-party import checking:
#   - adapters/      : DeFiLlama feed may use requests for HTTP
#   - execution/     : Legitimately uses web3 for blockchain signing
#   - database/      : Legitimately uses sqlalchemy/alembic
#   - family_fund/api/: Legitimately uses fastapi
#   - data_pipeline/ : May use requests for data fetching
#   - analytics/     : Read-only advisory, large and heterogeneous
_STDLIB_ONLY_SUBDIRS: tuple[str, ...] = (
    "allocator",
    "paper_trading",
    "risk",
    "strategies",
)

# Patterns that suggest a value is a fake/test placeholder, not a real secret
_FAKE_PATTERNS = re.compile(
    r"fake|test|mock|dummy|example|placeholder|xxx|yyy|your_|sample|demo",
    re.IGNORECASE,
)

# Publicly-documented, well-known local-dev test keys that are NOT real secrets.
# These ship in Anvil/Hardhat/Ganache by default and are intentionally used by
# inert fault-injection drills (e.g. the signer-leak drill). Whitelisting is
# tightly scoped to these exact literals so a genuine hardcoded key is still
# flagged — we match the literal, not a broad pattern.
_KNOWN_TEST_KEYS: frozenset[str] = frozenset({
    # Anvil/Hardhat deterministic dev account #0 private key (public, in docs).
    "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
})

# Patterns that look like hardcoded secret VALUES (not variable names).
# Matches: db_password = "value123!!", api_key = "secretValue99"
# Requires the secret keyword to appear in the variable name (not just a word)
# and the assigned value must be a string literal of 8+ chars.
_SECRET_ASSIGNMENT = re.compile(
    r"""(?x)
    (?:password|secret|api_key|apikey|private_key)  # keyword in var name
    [^=\n]*                                          # rest of var name / spaces
    =\s*                                             # assignment operator
    (['"])[^'"]{8,}\1                                # string literal >= 8 chars
    """,
    re.IGNORECASE,
)

# Pattern: bare open(path, "w") — but NOT fdopen, os.fdopen, etc.
# Word boundary before "open" ensures we skip fdopen, os.fdopen.
_DIRECT_WRITE_OPEN = re.compile(r"""\bopen\s*\(.+,\s*['"]w['"]\)""")

_UNPARSED = "НЕ РАЗОБРАНО"


def _string_token_spans(src: str):
    """Отрезки колонок, занятые токенами STRING, по номерам строк.

    Отвечает на вопрос «лежит ли совпадение ВНУТРИ строкового литерала», то
    есть является ли найденный текст ЗОВОМ или ТЕКСТОМ. Третий исход назван
    отдельно: ``None`` = поток токенов не разобран, и тогда ответа НЕТ ни в
    одну сторону (инв. #17).
    """
    spans: dict = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.STRING:
                continue
            (row_a, col_a), (row_b, col_b) = tok.start, tok.end
            if row_a == row_b:
                spans.setdefault(row_a, []).append((col_a, col_b))
                continue
            # Многострочный литерал: первая строка — от своей колонки до конца,
            # середина — целиком, последняя — до своей колонки.
            spans.setdefault(row_a, []).append((col_a, None))
            for row in range(row_a + 1, row_b):
                spans.setdefault(row, []).append((0, None))
            spans.setdefault(row_b, []).append((0, col_b))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None
    return spans


def _match_is_inside_a_string(spans, lineno: int, start: int, end: int) -> bool:
    """Целиком ли совпадение ``[start, end)`` лежит внутри токена STRING."""
    for col_a, col_b in spans.get(lineno, ()):
        if col_a <= start and (col_b is None or end <= col_b):
            return True
    return False


# ── AuditViolation dataclass ──────────────────────────────────────────────────

@dataclass
class AuditViolation:
    """Represents a single architecture audit violation."""
    rule: str
    file: str
    line: int
    message: str
    #: Один из :data:`SEVERITIES`. ``"UNMEASURED"`` — третий исход инв. #17:
    #: правило о ЭТОМ файле вопрос задать НЕ СМОГЛО (источник не разобран),
    #: и это не «нарушение» и не «чисто».
    severity: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── ArchitectureAudit class ───────────────────────────────────────────────────

class ArchitectureAudit:
    """Audits the SPA codebase for compliance with RULES.md conventions."""

    def __init__(self, base_dir: str = "spa_core") -> None:
        """
        Args:
            base_dir: Root directory of the spa_core package (relative to
                      repo root or absolute). Defaults to 'spa_core'.
        """
        base_path = Path(base_dir)
        if not base_path.is_absolute():
            candidate = _REPO_ROOT / base_dir
            if candidate.exists():
                base_path = candidate
            else:
                base_path = Path(os.getcwd()) / base_dir
        self._base_dir: Path = base_path
        self._repo_root: Path = _REPO_ROOT
        self._violations: List[AuditViolation] = []

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_test_file(self, fpath: Path, walk_root: Path) -> tuple[bool, str]:
        """ОДНА дверь вопроса «это тест?» — и она спрашивает о МЕСТЕ, не только об имени.

        Прежняя редакция объявляла ``skip_tests`` как «тесты я не смотрю», а решала
        вопрос ``fname.startswith("test_")`` — то есть отвечала об ИМЕНИ. Соврать так
        можно в обе стороны, и первая сторона стоила красного ``main``: замер на
        вершине ``cd9610c40`` (состояние ДО ADR-1088) — правило ``atomic_writes``
        доложило **7** нарушений при потолке 5, и **2** из них были строки ТЕКСТА
        внутри исходника плагина, который прибор ``spa_core/tests/_mtime_clock_door.py``
        выкладывает в одноразовое дерево. Помощник в каталоге тестов — тест, как бы он
        ни назывался; таких помощников в ``spa_core/tests/`` **64** (замер 24.11).

        Вопрос задаётся о пути, ВЗЯТОМ ОТНОСИТЕЛЬНО корня, а не об абсолютном: иначе
        дерево, лежащее по пути с компонентом ``tests`` (``/private/tmp/tests/…``),
        пропустило бы ВЕСЬ репозиторий молча — та же ловушка «литерал пути = слабая
        дверь», только наоборот.

        Исходы различимы (инв. #17): ответ дан по пути от корня репозитория · по пути
        от корня обхода (файл вне репозитория) · место не установлено, и тогда
        отвечает ТОЛЬКО имя — третий исход НАЗВАН, а не выдан за первые два.
        """
        for base, basis in ((self._repo_root, "repo"), (walk_root, "root")):
            try:
                rel = fpath.relative_to(base)
            except ValueError:
                continue
            in_tests_tree = "tests" in rel.parent.parts
            return (in_tests_tree or rel.name.startswith("test_")), basis
        return fpath.name.startswith("test_"), "name-only"

    def _iter_py_files(
        self,
        root: Path,
        skip_tests: bool = False,
        skip_pycache: bool = True,
    ):
        """Yield (filepath, lines) for each .py file under root."""
        root = Path(root)
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = sorted(
                d for d in dirs
                if not (skip_pycache and d == "__pycache__")
                and not d.startswith(".")
            )
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                fpath = Path(dirpath) / fname
                if skip_tests and self._is_test_file(fpath, root)[0]:
                    continue
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    yield fpath, content.splitlines()
                except OSError:
                    continue

    def _rel(self, path: Path) -> str:
        """Return path relative to repo root for compact display."""
        try:
            return str(path.relative_to(self._repo_root))
        except ValueError:
            return str(path)

    # ── Rule checks ───────────────────────────────────────────────────────────

    def check_no_third_party(self) -> List[AuditViolation]:
        """Check for non-stdlib, non-spa_core imports in SPA runtime files.

        Only scans the critical runtime subdirectories (adapters, analytics,
        paper_trading, risk, strategies, allocator, data_pipeline) where
        the stdlib-only rule strictly applies. Excludes execution/, database/,
        and family_fund/api/ which may legitimately use web3/sqlalchemy/fastapi.

        Only flags imports of well-known third-party packages from the curated
        _KNOWN_THIRD_PARTY list to avoid false positives on internal modules
        with short names.

        Returns:
            List of AuditViolation with severity="ERROR".
        """
        violations: List[AuditViolation] = []

        try:
            stdlib_names = sys.stdlib_module_names  # Python 3.10+
        except AttributeError:
            stdlib_names = frozenset()

        # Only scan the pure business-logic subdirectories
        scan_roots = []
        for subdir in _STDLIB_ONLY_SUBDIRS:
            candidate = self._base_dir / subdir
            if candidate.exists():
                scan_roots.append(candidate)

        for scan_root in scan_roots:
            for fpath, lines in self._iter_py_files(scan_root, skip_tests=False):
                src = "\n".join(lines)
                try:
                    tree = ast.parse(src, filename=str(fpath))
                except SyntaxError:
                    continue

                for node in ast.walk(tree):
                    top_module: Optional[str] = None

                    if isinstance(node, ast.ImportFrom) and node.module:
                        top_module = node.module.split(".")[0]
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            top_module = alias.name.split(".")[0]

                    if top_module is None:
                        continue
                    if top_module.startswith("spa_core"):
                        continue
                    if top_module in stdlib_names:
                        continue
                    if top_module in _KNOWN_THIRD_PARTY:
                        lineno = getattr(node, "lineno", 0)
                        violations.append(AuditViolation(
                            rule="no_third_party_imports",
                            file=self._rel(fpath),
                            line=lineno,
                            message=(
                                f"Third-party import '{top_module}' found in "
                                f"runtime code — stdlib only rule applies here"
                            ),
                            severity="ERROR",
                        ))

        return violations

    def check_atomic_writes(self) -> List[AuditViolation]:
        """Check for direct open(path, 'w') without an atomic tmp+os.replace pattern.

        A non-atomic write to a state file can corrupt data if the process
        is interrupted mid-write. The safe pattern is:
            tmp → write → os.replace(tmp, target)

        Предмет правила — ЗОВ, а не ТЕКСТ (ADR-1088). Прежняя редакция
        объявляла, что пропускает «string literals / docstrings», но мерила
        это началом строки (``startswith('\"\"\"')``), поэтому строка ВНУТРИ
        многострочного литерала считалась кодом. Замер 2026-11-24: из 7
        доложенных нарушений **3** лежали внутри литерала — проза докстринга
        `monitoring/decision_reproducibility.py` (она ОБЪЯСНЯЕТ опасность
        такой записи) и два отрезка исходника плагина, который прибор
        `spa_core/tests/_mtime_clock_door.py` выкладывает в одноразовое дерево.
        Теперь вопрос задаётся ТОКЕНАМИ, и исходов три (инв. #17):
        попадание в коде = нарушение · попадание внутри литерала = НЕ
        нарушение (это текст) · поток токенов не разобран = нарушение с
        НАЗВАННОЙ причиной, fail-CLOSED, потому что ответа нет ни в одну
        сторону. Замер поверхности: 2301 файл, не токенизируется 0.

        Returns:
            List of AuditViolation with severity="WARNING".
        """
        violations: List[AuditViolation] = []

        for fpath, lines in self._iter_py_files(
            self._base_dir, skip_tests=True, skip_pycache=True
        ):
            spans = _string_token_spans("\n".join(lines))

            for lineno, line in enumerate(lines, 1):
                # Skip comment lines and string literals / docstrings
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    continue

                match = _DIRECT_WRITE_OPEN.search(line)
                if match is None:
                    continue

                # Check surrounding context (±5 lines) for atomic-write hints
                start = max(0, lineno - 6)
                end = min(len(lines), lineno + 5)
                context = "\n".join(lines[start:end])

                if "tmp" in context.lower() or "os.replace" in context:
                    continue

                if spans is None:
                    violations.append(AuditViolation(
                        rule="atomic_writes",
                        file=self._rel(fpath),
                        line=lineno,
                        message=(
                            f"{_UNPARSED}: поток токенов файла не разобран — "
                            "зов это или текст внутри литерала, не измерено"
                        ),
                        severity="WARNING",
                    ))
                    continue

                if _match_is_inside_a_string(
                    spans, lineno, match.start(), match.end()
                ):
                    # Текст внутри литерала зовом не является — ни докстринг,
                    # ни исходник, который модуль выкладывает другим деревом.
                    continue

                violations.append(AuditViolation(
                    rule="atomic_writes",
                    file=self._rel(fpath),
                    line=lineno,
                    message=(
                        "Direct open(path, 'w') without atomic tmp+os.replace pattern"
                    ),
                    severity="WARNING",
                ))

        return violations

    def check_no_hardcoded_secrets(self) -> List[AuditViolation]:
        """Check for hardcoded credential values in non-test source files.

        Scans for patterns like: password = "abc123"
        Does NOT flag:
        - Environment variable reads (os.environ, os.getenv)
        - Keychain/security tool calls
        - Variable NAMES that contain 'secret' without a string assignment
        - Lines matching the _FAKE_PATTERNS (test fixtures)
        - Files in test directories

        Returns:
            List of AuditViolation with severity="ERROR".
        """
        violations: List[AuditViolation] = []

        # Only check the pure business-logic subdirs.
        # api/, family_fund/api/, execution/ may legitimately store tokens
        # via framework-standard auth mechanisms (Bearer headers, env vars).
        scan_roots = []
        for subdir in _STDLIB_ONLY_SUBDIRS:
            candidate = self._base_dir / subdir
            if candidate.exists():
                scan_roots.append(candidate)

        for scan_root in scan_roots:
            for fpath, lines in self._iter_py_files(
                scan_root, skip_tests=True, skip_pycache=True
            ):
                for lineno, line in enumerate(lines, 1):
                    stripped = line.strip()
                    # Skip comment lines and docstring lines
                    if stripped.startswith("#"):
                        continue
                    if stripped.startswith('"""') or stripped.startswith("'''"):
                        continue
                    # Skip lines that are examples/patterns
                    if "like:" in line.lower() or "e.g." in line.lower():
                        continue

                    if not _SECRET_ASSIGNMENT.search(line):
                        continue
                    # Skip lines that look like test/fake placeholders
                    if _FAKE_PATTERNS.search(line):
                        continue
                    # Skip publicly-documented local-dev test keys (Anvil/Hardhat
                    # default accounts) used by inert fault-injection drills. The
                    # match is on the exact literal — a real key is still flagged.
                    if any(k in line for k in _KNOWN_TEST_KEYS):
                        continue
                    # Skip lines that reference environment variables
                    if "os.environ" in line or "os.getenv" in line:
                        continue
                    # Skip lines that reference keychain/security commands
                    if "keychain" in line.lower() or "security" in line.lower():
                        continue

                    violations.append(AuditViolation(
                        rule="no_hardcoded_secrets",
                        file=self._rel(fpath),
                        line=lineno,
                        message="Potential hardcoded credential value detected",
                        severity="ERROR",
                    ))

        return violations

    def check_adapters_research_flag(self) -> List[AuditViolation]:
        """Verify that research-category adapters define RESEARCH_ONLY = True.

        Adapters with 'research' in their filename claim to be read-only
        advisory modules and must explicitly declare:
            RESEARCH_ONLY: bool = True

        Returns:
            List of AuditViolation with severity="ERROR".
        """
        violations: List[AuditViolation] = []
        adapters_dir = self._base_dir / "adapters"

        if not adapters_dir.exists():
            return violations

        for fpath in sorted(adapters_dir.glob("*.py")):
            if "research" not in fpath.stem:
                continue  # Only check research-tagged adapters

            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Must define RESEARCH_ONLY = True (not just in a comment)
            has_flag = bool(
                re.search(r"RESEARCH_ONLY\s*(?::\s*bool\s*)?=\s*True", content)
            )
            if not has_flag:
                violations.append(AuditViolation(
                    rule="adapters_have_research_flag",
                    file=self._rel(fpath),
                    line=0,
                    message=(
                        "Research adapter is missing 'RESEARCH_ONLY = True' declaration"
                    ),
                    severity="ERROR",
                ))

        return violations

    def check_no_llm_in_analytics(self) -> List[AuditViolation]:
        """Инвариант #3 для поддерева ``spa_core/analytics``: ни SDK, ни бинаря.

        **Спрашивается ЗОВ и ИМПОРТ, а не ТЕКСТ.** Оба вопроса задаются
        ЕДИНСТВЕННЫМИ дверями из ``spa_core.ci.llm_forbidden_lint`` —
        :func:`find_forbidden_imports` (``import anthropic`` и родня, по AST) и
        :func:`find_llm_subprocess_launches` (запуск бинаря ``claude``/``llm``/
        ``ollama`` подпроцессом, по AST с потоком значения). Своей копии
        правила здесь НЕТ намеренно: разойдись копия с оригиналом — два
        сторожа одного инварианта охраняли бы РАЗНЫЕ вопросы, и ровно так они
        уже расходились до ADR-291 §2 (дверь-SDK ловилась, дверь-запуск не
        охранялась никем). Урок ADR-1088 тем же исполнен по построению: AST не
        видит содержимое строковых литералов как импорт или зов, поэтому три
        из семи «нарушений» того замера родиться здесь не могут.

        **Почему правило не дубль, а единственный читатель.** Замер
        2026-11-24: перечни каталогов, ЗОВУЩИЕ обе двери
        (``llm_forbidden_lint.FORBIDDEN_DIRS`` и
        ``scripts/lint_llm_forbidden.SCAN_DIRS_DEFAULT``), называют risk ·
        execution · monitoring · allocator · adapters · governance · tuner и
        НЕ называют ``spa_core/analytics``. Население поддерева на день
        реализации — **0** нарушений по обеим дверям из 798 не-тестовых
        файлов, то есть правило закрывает ЛАТЕНТНУЮ слепоту, а не гасит живое
        нарушение (тот же род усиления, что ADR-958; инв. #16 про ослабление и
        к этому не относится).

        **Три исхода различимы (инв. #17).** Нарушение ⇒ ``ERROR``. Чисто ⇒
        пустой список, и это «измерено и равно нулю». Источник не разобран
        (``SyntaxError``) либо ввоз двери не удался ⇒ ``UNMEASURED`` с
        названной причиной — НЕ ноль и НЕ нарушение. Каталога нет в дереве ⇒
        тоже ``UNMEASURED``: «нечего смотреть» и «смотреть не стали»
        неразличимы иначе.

        Returns:
            Список :class:`AuditViolation` с severity ``ERROR`` либо
            ``UNMEASURED``.
        """
        rule = "no_llm_in_analytics"
        violations: List[AuditViolation] = []

        try:
            from spa_core.ci.llm_forbidden_lint import (
                find_forbidden_imports,
                find_llm_subprocess_launches,
            )
        except Exception as exc:  # noqa: BLE001 — любая причина = «нечем спросить»
            return [AuditViolation(
                rule=rule,
                file=str(self._base_dir / _LLM_SCAN_SUBDIR),
                line=0,
                message=(
                    f"НЕ ИЗМЕРЕНО: дверь запрета LLM не ввезена "
                    f"({type(exc).__name__}: {exc}) — это не «чисто»"
                ),
                severity="UNMEASURED",
            )]

        scan_root = self._base_dir / _LLM_SCAN_SUBDIR
        if not scan_root.is_dir():
            return [AuditViolation(
                rule=rule,
                file=self._rel(scan_root),
                line=0,
                message=(
                    "НЕ ИЗМЕРЕНО: каталога нет в дереве — «нечего смотреть» "
                    "не есть «смотрели и чисто»"
                ),
                severity="UNMEASURED",
            )]

        for fpath, _lines in self._iter_py_files(scan_root, skip_tests=True):
            rel = self._rel(fpath)
            try:
                source = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                violations.append(AuditViolation(
                    rule=rule, file=rel, line=0,
                    message=f"НЕ ИЗМЕРЕНО: файл не прочитан ({exc})",
                    severity="UNMEASURED",
                ))
                continue
            try:
                imports = find_forbidden_imports(source, filename=rel)
                launches = find_llm_subprocess_launches(source, filename=rel)
            except SyntaxError as exc:
                violations.append(AuditViolation(
                    rule=rule, file=rel, line=getattr(exc, "lineno", 0) or 0,
                    message=f"НЕ ИЗМЕРЕНО: источник не разобран ({exc.msg})",
                    severity="UNMEASURED",
                ))
                continue

            for viol in imports:
                violations.append(AuditViolation(
                    rule=rule, file=rel, line=viol.line,
                    message=(
                        "LLM SDK imported in spa_core/analytics: "
                        f"{viol.module} — инвариант #3"
                    ),
                    severity="ERROR",
                ))
            for launch in launches:
                violations.append(AuditViolation(
                    rule=rule, file=rel, line=launch.line,
                    message=(
                        "LLM binary launched as a subprocess in "
                        f"spa_core/analytics: {launch.binary} "
                        f"via {launch.via} — инвариант #3"
                    ),
                    severity="ERROR",
                ))

        return violations

    def check_tests_use_unittest(self) -> List[AuditViolation]:
        """Verify that test files in tests/ use a recognized test framework.

        SPA convention: tests should use stdlib unittest. Pure function-based
        tests (no import of unittest OR pytest) are flagged as they may not
        be discovered reliably by standard test runners.

        A test file is considered compliant if it:
          * imports unittest or pytest, OR
          * defines pytest-style ``def test_*`` functions or a ``class Test*``, OR
          * is a RE-EXPORT SHIM that re-exports ``test_*`` functions from another
            test module (a thin file whose tests are the canonical ones it
            imports — pytest still collects them at the shim's path).

        Genuinely empty/broken test files (no framework, no tests, no re-export)
        are still flagged.

        Returns:
            List of AuditViolation with severity="WARNING".
        """
        violations: List[AuditViolation] = []
        tests_dir = self._repo_root / "tests"

        if not tests_dir.exists():
            return violations

        for fpath in sorted(tests_dir.glob("test_*.py")):
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            has_unittest = "import unittest" in content
            has_pytest = "import pytest" in content
            # Also accept pure pytest-style function tests (def test_...)
            has_test_func = bool(re.search(r"^def test_", content, re.MULTILINE))
            has_test_class = bool(re.search(r"class Test", content))
            # Accept re-export shims: a file that imports test_* functions from
            # another module re-exports collectable tests at its own path.
            is_reexport_shim = self._is_test_reexport_shim(content)

            # Skip stub/empty files (e.g. "MOVED" placeholders with only comments)
            non_comment_lines = [
                ln for ln in content.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            is_stub = len(non_comment_lines) < 5

            if not is_stub and not has_unittest and not has_pytest \
                    and not has_test_func and not has_test_class \
                    and not is_reexport_shim:
                violations.append(AuditViolation(
                    rule="tests_use_unittest",
                    file=self._rel(fpath),
                    line=0,
                    message="Test file has no test framework (unittest/pytest) or test functions",
                    severity="WARNING",
                ))

        return violations

    @staticmethod
    def _is_test_reexport_shim(content: str) -> bool:
        """True iff ``content`` is a re-export shim for tests from another module.

        A re-export shim re-exports one or more ``test_*`` callables via a
        ``from <module> import (...)`` statement (or ``import *``) where the
        source module is itself a test module (its dotted path ends in a
        ``test_*`` component). pytest collects the re-exported ``test_*`` names
        at the shim's own path, so the shim runs real tests — it is NOT an empty
        file. Parsed via AST so it cannot be fooled by tests merely mentioned in
        comments/strings.
        """
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return False

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            # Source must be a test module (last dotted component is a test_*).
            if not node.module.split(".")[-1].startswith("test_"):
                continue
            for alias in node.names:
                # `from test_mod import *` OR an explicit `test_*` name.
                if alias.name == "*" or alias.name.startswith("test_"):
                    return True
        return False

    # ── Aggregate API ─────────────────────────────────────────────────────────

    def rule_checks(self) -> List[tuple]:
        """Пара «имя правила → исполняющий метод» — ОДНА копия на весь модуль.

        До ADR-1091 копий было ДВЕ: список зовов в :meth:`run_all` и список
        кортежей в :func:`main`. Разойдись они — отчёт печатал бы про правила,
        которых прогон не делал, или наоборот; и именно расхождение этих двух
        мест пряталось за «семь объявлено, пять исполнено». Перепись
        ``scripts/test_membership_door_census.py`` читает пару ИМЕННО отсюда
        (кортеж ``("имя", <что-то>.check_xxx)``), а не по совпадению имени
        метода — имя метода объявлением не является (урок #1218).
        """
        return [
            ("no_third_party_imports", self.check_no_third_party),
            ("atomic_writes", self.check_atomic_writes),
            ("no_llm_in_analytics", self.check_no_llm_in_analytics),
            ("no_hardcoded_secrets", self.check_no_hardcoded_secrets),
            ("adapters_have_research_flag", self.check_adapters_research_flag),
            ("tests_use_unittest", self.check_tests_use_unittest),
        ]

    def rule_status(self) -> "dict[str, dict]":
        """Статус КАЖДОГО объявленного правила — три различимых исхода (инв. #17).

        * ``ENFORCED``         — у правила есть исполняющий метод;
        * ``NOT_IMPLEMENTED``  — правило объявлено и намеренно не исполняется,
          причина названа в :data:`RULE_NOT_IMPLEMENTED`;
        * ``UNMEASURED``       — имя объявлено, метода нет И причины нет: это
          МОЛЧАЛИВАЯ дыра, ровно та, из-за которой ADR-1091 и написан.

        Fail-CLOSED: третий исход никогда не сводится к первым двум и никогда
        не печатается нулём.
        """
        methods = dict(self.rule_checks())
        out: "dict[str, dict]" = {}
        for rule in AUDIT_RULES:
            if rule in methods:
                out[rule] = {"status": "ENFORCED", "reason": None}
            elif rule in RULE_NOT_IMPLEMENTED:
                out[rule] = {
                    "status": "NOT_IMPLEMENTED",
                    "reason": RULE_NOT_IMPLEMENTED[rule],
                }
            else:
                out[rule] = {
                    "status": "UNMEASURED",
                    "reason": (
                        "правило объявлено в AUDIT_RULES, исполняющего метода "
                        "нет и причина не названа — вопрос «реализовано ли "
                        "оно» задать НЕЧЕМ"
                    ),
                }
        return out

    def unmeasured_rules(self) -> List[str]:
        """Имена правил, у которых долг НЕ НАЗВАН. Пусто — норма."""
        return [r for r, row in self.rule_status().items()
                if row["status"] == "UNMEASURED"]

    def run_all(self) -> List[AuditViolation]:
        """Run all audit checks and return a flat list of violations.

        Проходит по ЕДИНСТВЕННОЙ двери :meth:`rule_checks`, поэтому «правило
        объявлено, но не прогнано» перестаёт быть возможным молча.

        Results are also cached in self._violations for use by
        violation_count() and other methods.

        Returns:
            Combined list of AuditViolation from all checks.
        """
        all_violations: List[AuditViolation] = []
        for _rule, check in self.rule_checks():
            all_violations.extend(check())
        for rule in self.unmeasured_rules():
            all_violations.append(AuditViolation(
                rule=rule,
                file=self._rel(self._base_dir),
                line=0,
                message=(
                    "НЕ ИЗМЕРЕНО: правило объявлено в AUDIT_RULES, метода нет "
                    "и причина не названа в RULE_NOT_IMPLEMENTED — ноль в "
                    "отчёте был бы неотличим от «прошли и чисто» (инв. #17)"
                ),
                severity="UNMEASURED",
            ))
        self._violations = all_violations
        return all_violations

    def violation_count(self, severity: Optional[str] = None) -> int:
        """Count violations, optionally filtered by severity.

        Args:
            severity: If provided, only count violations with this severity
                      ("ERROR" or "WARNING"). If None, count all violations.

        Returns:
            Integer count of matching violations.
        """
        if not self._violations:
            return 0
        if severity is None:
            return len(self._violations)
        return sum(1 for v in self._violations if v.severity == severity)

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(
        self,
        violations: List[AuditViolation],
        path: str = "data/audit/architecture_audit.json",
    ) -> str:
        """Atomically write audit results to JSON.

        Args:
            violations: List of AuditViolation to persist.
            path:       Output path (relative to repo root or absolute).

        Returns:
            Absolute path where the file was written.
        """
        out_path = Path(path)
        if not out_path.is_absolute():
            out_path = self._repo_root / path

        out_path.parent.mkdir(parents=True, exist_ok=True)

        from datetime import datetime, timezone
        unmeasured = [v for v in violations if v.severity == "UNMEASURED"]
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_dir": str(self._base_dir),
            # «нарушений» столько, сколько ИЗМЕРЕНО; «не измерено» —
            # ОТДЕЛЬНОЕ значение, а не часть нуля (инв. #17).
            "total_violations": len(violations) - len(unmeasured),
            "error_count": sum(1 for v in violations if v.severity == "ERROR"),
            "warning_count": sum(1 for v in violations if v.severity == "WARNING"),
            "unmeasured_count": len(unmeasured),
            # Статус КАЖДОГО объявленного правила — чтобы читатель артефакта
            # мог отличить «прошло и чисто» от «не исполнялось вовсе».
            "rules": self.rule_status(),
            "violations": [v.to_dict() for v in violations],
        }

        atomic_save(payload, str(out_path))
        return str(out_path)

    def to_markdown(self, violations: List[AuditViolation]) -> str:
        """Render audit results as a Markdown report.

        Args:
            violations: List of AuditViolation to render.

        Returns:
            Markdown string with a summary table and violation details.
        """
        lines = [
            "# SPA Architecture Audit Report",
            "",
        ]

        if not violations:
            lines += [
                "✅ **No violations found.** Codebase is compliant with RULES.md.",
                "",
                # Заголовок ОБЯЗАТЕЛЕН и в этой ветке: «нарушений нет» само по
                # себе не говорит, какие правила вообще исполнялись, — а это и
                # есть вопрос, из-за которого ADR-1091 написан.
                "## Статус объявленных правил",
                "",
                "| Rule | Статус | Причина |",
                "|------|--------|---------|",
            ]
            for rule, row in self.rule_status().items():
                reason = (row["reason"] or "—").replace("\n", " ")
                lines.append(f"| `{rule}` | {row['status']} | {reason} |")
            lines.append("")
            return "\n".join(lines)

        # Group by severity — ТРИ исхода, не два (инв. #17)
        errors = [v for v in violations if v.severity == "ERROR"]
        warnings = [v for v in violations if v.severity == "WARNING"]
        unmeasured = [v for v in violations if v.severity == "UNMEASURED"]

        lines += [
            f"**Total violations:** {len(violations) - len(unmeasured)}  "
            f"(**{len(errors)} ERROR**, {len(warnings)} WARNING)  "
            f"· **НЕ ИЗМЕРЕНО: {len(unmeasured)}**",
            "",
            "## Violations",
            "",
            "| Severity | Rule | File | Line | Message |",
            "|----------|------|------|------|---------|",
        ]

        for v in sorted(violations, key=lambda x: (x.severity, x.rule, x.file, x.line)):
            sev_icon = "🔴 ERROR" if v.severity == "ERROR" else "⚠️ WARNING"
            lines.append(
                f"| {sev_icon} | `{v.rule}` | `{v.file}` | {v.line} | {v.message} |"
            )

        # Rule summary
        from collections import Counter
        rule_counts = Counter(v.rule for v in violations)
        lines += [
            "",
            "## Summary by Rule",
            "",
            "| Rule | Count |",
            "|------|-------|",
        ]
        for rule, count in sorted(rule_counts.items()):
            lines.append(f"| `{rule}` | {count} |")

        # Статус КАЖДОГО объявленного правила. Правило, которое не исполнялось,
        # в таблице выше просто ОТСУТСТВУЕТ — ровно так же, как правило,
        # прошедшее по дереву без находок. Эта таблица их различает.
        lines += [
            "",
            "## Статус объявленных правил",
            "",
            "| Rule | Статус | Причина |",
            "|------|--------|---------|",
        ]
        for rule, row in self.rule_status().items():
            reason = (row["reason"] or "—").replace("\n", " ")
            lines.append(f"| `{rule}` | {row['status']} | {reason} |")

        return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SPA Architecture Audit — checks RULES.md compliance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output instead of human-readable",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to data/audit/architecture_audit.json",
    )
    parser.add_argument(
        "--base-dir",
        default="spa_core",
        help="spa_core directory to audit (default: spa_core)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    audit = ArchitectureAudit(base_dir=args.base_dir)
    violations = audit.run_all()

    if args.json:
        from datetime import datetime, timezone
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_violations": len(violations),
            "violations": [v.to_dict() for v in violations],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("=" * 60)
        print("  SPA Architecture Audit Report")
        print("=" * 60)

        # Per-rule summary — по ОБЪЯВЛЕНИЮ (AUDIT_RULES), не по списку зовов.
        # Нереализованное правило печатается СВОИМ значением, а не нулём:
        # «не проверяли» и «проверили, чисто» до ADR-1091 давали одну строку.
        statuses = audit.rule_status()
        for rule_name in AUDIT_RULES:
            row = statuses[rule_name]
            if row["status"] == "ENFORCED":
                rule_viols = [
                    v for v in violations
                    if v.rule == rule_name and v.severity != "UNMEASURED"
                ]
                unmeasured_here = [
                    v for v in violations
                    if v.rule == rule_name and v.severity == "UNMEASURED"
                ]
                count = len(rule_viols)
                icon = "✅" if count == 0 else "⚠️ "
                tail = (f"  (+{len(unmeasured_here)} НЕ ИЗМЕРЕНО)"
                        if unmeasured_here else "")
                print(f"  {icon}  {rule_name:<35} {count} violation(s){tail}")
            elif row["status"] == "NOT_IMPLEMENTED":
                print(f"  ⬜  {rule_name:<35} НЕ РЕАЛИЗОВАНО (объявлено, "
                      f"причина названа)")
            else:
                print(f"  🚫  {rule_name:<35} НЕ ИЗМЕРЕНО: метода нет и "
                      f"причина не названа")

        print("-" * 60)
        errors = sum(1 for v in violations if v.severity == "ERROR")
        warnings = sum(1 for v in violations if v.severity == "WARNING")
        unmeasured = sum(1 for v in violations if v.severity == "UNMEASURED")
        print(
            f"  TOTAL: {len(violations) - unmeasured} violation(s)"
            f"  [{errors} ERROR, {warnings} WARNING]"
            f"  · НЕ ИЗМЕРЕНО: {unmeasured}"
        )
        print()

        if violations:
            print("Details:")
            for v in sorted(violations, key=lambda x: (x.file, x.line)):
                print(f"  [{v.severity}] {v.file}:{v.line}  {v.message}")
                print(f"          rule: {v.rule}")
        else:
            print("  ✅  No violations — codebase is RULES.md compliant.")

    if args.save:
        saved_path = audit.save(violations)
        print(f"\nSaved → {saved_path}", flush=True)
        md_path = str(saved_path).replace(".json", ".md")
        md_content = audit.to_markdown(violations)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(Path(saved_path).parent), suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(md_content)
            os.replace(tmp_path, md_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        print(f"Saved → {md_path}", flush=True)

    # Код возврата: МОЛЧАЛИВАЯ дыра (имя объявлено, ни метода, ни причины) —
    # это «НЕ ИЗМЕРЕНО», и выдавать её за успех нельзя (инв. #17). Объявленный
    # НЕ РЕАЛИЗОВАННЫМ пункт кодом не краснит: он есть названный долг, а
    # постоянный ненулевой код был бы так же бесполезен, как постоянный ноль.
    silent = audit.unmeasured_rules()
    if silent:
        print(
            "НЕ ИЗМЕРЕНО: у правил "
            + ", ".join(silent)
            + " нет ни метода, ни причины в RULE_NOT_IMPLEMENTED",
            file=sys.stderr,
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
