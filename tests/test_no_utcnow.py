"""Lint guard (Task 9, Block D hygiene): no bare ``datetime.utcnow()`` in runtime.

``datetime.datetime.utcnow`` is deprecated (Python 3.12) and — critically —
returns a NAIVE datetime whose ``.isoformat()`` differs from the AWARE
``datetime.now(timezone.utc)`` (no ``+00:00`` offset). The codebase persists
those strings to ``data/*.json`` state files, so a careless swap would change
output. All runtime call-sites must go through :func:`spa_core.utils.clock.utcnow`
(a naive-preserving, deprecation-free drop-in).

This test greps ``spa_core/`` + ``scripts/`` for bare ``datetime.utcnow(``
(excluding the clock helper itself and the tests tree) and asserts there are
zero, so the deprecation can never regress.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("spa_core", "scripts")

# Matches both `datetime.utcnow(` and `datetime.datetime.utcnow(` — as CALLS, by AST.
# A text grep (the first form of this guard) also matched docstrings and comments that only
# NAME the deprecated call (e.g. `identity_field_kind.py`, which documents what it detects)
# and kept the guard red on code that has no such call (CI control run #14).
_UTCNOW = re.compile(r"\bdatetime\.utcnow\(")


def utcnow_calls(source: str) -> list[int]:
    """Line numbers of real `datetime.utcnow()` / `datetime.datetime.utcnow()` calls."""
    import ast
    out = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "utcnow"):
            continue
        base = node.func.value
        if (isinstance(base, ast.Name) and base.id == "datetime") or \
                (isinstance(base, ast.Attribute) and base.attr == "datetime"):
            out.append(node.lineno)
    return out


# Files/dirs that are allowed to mention utcnow (helper + the test tree itself).
_ALLOWLIST = {"clock.py"}


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if "tests" in parts:
        return True
    if path.name in _ALLOWLIST:
        return True
    return False


def test_no_bare_utcnow_in_runtime() -> None:
    offenders: list[str] = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if _is_excluded(py):
                continue
            text = py.read_text(encoding="utf-8")
            if not _UTCNOW.search(text):
                continue                     # cheap prefilter; the verdict is the AST below
            try:
                lines = utcnow_calls(text)
            except SyntaxError as exc:       # unparsable file = loud finding, not a pass
                offenders.append(f"{py.relative_to(ROOT)}: NOT MEASURED (syntax error: {exc})")
                continue
            src_lines = text.splitlines()
            for i in lines:
                offenders.append(f"{py.relative_to(ROOT)}:{i}: {src_lines[i - 1].strip()}")

    assert not offenders, (
        "Bare datetime.utcnow() found — use spa_core.utils.clock.utcnow() "
        "(naive-preserving, deprecation-free):\n" + "\n".join(offenders)
    )


def test_the_scanner_sees_a_call_and_ignores_a_mention() -> None:
    """Both directions: a real call is found; a docstring or comment naming it is not."""
    src = (
        '"""Detects datetime.utcnow() usage."""\n'
        "# datetime.utcnow() is deprecated\n"
        "import datetime\n"
        "a = datetime.utcnow()\n"
        "b = datetime.datetime.utcnow()\n"
        "c = clock.utcnow()\n"
    )
    assert utcnow_calls(src) == [4, 5]
