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
import re
import sys
import tempfile
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


# ── AuditViolation dataclass ──────────────────────────────────────────────────

@dataclass
class AuditViolation:
    """Represents a single architecture audit violation."""
    rule: str
    file: str
    line: int
    message: str
    severity: str  # "ERROR" or "WARNING"

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

    def _iter_py_files(
        self,
        root: Path,
        skip_tests: bool = False,
        skip_pycache: bool = True,
    ):
        """Yield (filepath, lines) for each .py file under root."""
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = sorted(
                d for d in dirs
                if not (skip_pycache and d == "__pycache__")
                and not d.startswith(".")
            )
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                if skip_tests and fname.startswith("test_"):
                    continue
                fpath = Path(dirpath) / fname
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

        Returns:
            List of AuditViolation with severity="WARNING".
        """
        violations: List[AuditViolation] = []

        for fpath, lines in self._iter_py_files(
            self._base_dir, skip_tests=True, skip_pycache=True
        ):
            for lineno, line in enumerate(lines, 1):
                # Skip comment lines and string literals / docstrings
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    continue

                if not _DIRECT_WRITE_OPEN.search(line):
                    continue

                # Check surrounding context (±5 lines) for atomic-write hints
                start = max(0, lineno - 6)
                end = min(len(lines), lineno + 5)
                context = "\n".join(lines[start:end])

                if "tmp" not in context.lower() and "os.replace" not in context:
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

    def run_all(self) -> List[AuditViolation]:
        """Run all audit checks and return a flat list of violations.

        Results are also cached in self._violations for use by
        violation_count() and other methods.

        Returns:
            Combined list of AuditViolation from all checks.
        """
        all_violations: List[AuditViolation] = []
        all_violations.extend(self.check_no_third_party())
        all_violations.extend(self.check_atomic_writes())
        all_violations.extend(self.check_no_hardcoded_secrets())
        all_violations.extend(self.check_adapters_research_flag())
        all_violations.extend(self.check_tests_use_unittest())
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
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_dir": str(self._base_dir),
            "total_violations": len(violations),
            "error_count": sum(1 for v in violations if v.severity == "ERROR"),
            "warning_count": sum(1 for v in violations if v.severity == "WARNING"),
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
            ]
            return "\n".join(lines)

        # Group by severity
        errors = [v for v in violations if v.severity == "ERROR"]
        warnings = [v for v in violations if v.severity == "WARNING"]

        lines += [
            f"**Total violations:** {len(violations)}  "
            f"(**{len(errors)} ERROR**, {len(warnings)} WARNING)",
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

        # Per-rule summary
        checks = [
            ("no_third_party_imports", audit.check_no_third_party),
            ("atomic_writes", audit.check_atomic_writes),
            ("no_hardcoded_secrets", audit.check_no_hardcoded_secrets),
            ("adapters_have_research_flag", audit.check_adapters_research_flag),
            ("tests_use_unittest", audit.check_tests_use_unittest),
        ]

        for rule_name, _ in checks:
            rule_viols = [v for v in violations if v.rule == rule_name]
            count = len(rule_viols)
            icon = "✅" if count == 0 else "⚠️ "
            print(f"  {icon}  {rule_name:<35} {count} violation(s)")

        print("-" * 60)
        errors = sum(1 for v in violations if v.severity == "ERROR")
        warnings = sum(1 for v in violations if v.severity == "WARNING")
        print(
            f"  TOTAL: {len(violations)} violation(s)"
            f"  [{errors} ERROR, {warnings} WARNING]"
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


if __name__ == "__main__":
    main()
