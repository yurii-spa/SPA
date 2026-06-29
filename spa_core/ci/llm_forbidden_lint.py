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
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

log = logging.getLogger("spa.ci.llm_forbidden_lint")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "llm_forbidden_lint.json"

SCHEMA_VERSION = 1

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


def _iter_py_files(directory: Path) -> Iterable[Path]:
    """Yield ``*.py`` files under ``directory`` recursively, deterministically
    sorted, skipping ``__pycache__``."""
    for path in sorted(directory.rglob("*.py")):
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def scan_directory(
    directory: Path, root: Path
) -> Tuple[int, List[Violation], List[ParseError]]:
    """Scan one forbidden directory. Read-only: only reads source files.

    Returns ``(files_scanned, violations, parse_errors)``. File paths in the
    results are relative to ``root`` with posix separators. A ``SyntaxError``
    (or undecodable file) goes to ``parse_errors`` and never aborts the scan.
    """
    files_scanned = 0
    violations: List[Violation] = []
    parse_errors: List[ParseError] = []
    for path in _iter_py_files(directory):
        rel = path.relative_to(root).as_posix()
        files_scanned += 1
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            violations.extend(find_forbidden_imports(source, rel))
        except SyntaxError as exc:
            parse_errors.append(ParseError(rel, f"SyntaxError: {exc.msg} (line {exc.lineno})"))
        except OSError as exc:  # unreadable file — report, do not crash CI
            parse_errors.append(ParseError(rel, f"{type(exc).__name__}: {exc}"))
    return files_scanned, violations, parse_errors


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

    for rel_dir in dirs:
        directory = root_path / rel_dir
        if not directory.is_dir():
            log.debug("forbidden dir missing, skipped: %s", directory)
            continue
        scanned_dirs.append(rel_dir)
        n, v, p = scan_directory(directory, root_path)
        files_scanned += n
        violations.extend(v)
        parse_errors.extend(p)

    if not scanned_dirs:
        status = "no_dirs"
    elif violations:
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
        f"parse_errors={len(report['parse_errors'])}"
    )
    for v in report["violations"]:
        print(f"  VIOLATION {v['file']}:{v['line']} imports {v['module']}")
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
