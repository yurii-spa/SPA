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

# Matches both `datetime.utcnow(` and `datetime.datetime.utcnow(`.
_UTCNOW = re.compile(r"\bdatetime\.utcnow\(")

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
            for i, line in enumerate(text.splitlines(), 1):
                if _UTCNOW.search(line):
                    offenders.append(f"{py.relative_to(ROOT)}:{i}: {line.strip()}")

    assert not offenders, (
        "Bare datetime.utcnow() found — use spa_core.utils.clock.utcnow() "
        "(naive-preserving, deprecation-free):\n" + "\n".join(offenders)
    )
