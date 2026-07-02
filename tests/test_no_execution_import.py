"""SECURITY-003 — no research-layer CODE imports the runtime execution path.

research/ is the only new research CODE. Assert no .py file under research/
imports `spa_core.execution` (nor `spa_core.risk`, the deterministic gate) so
the research layer stays provably decoupled from money-path runtime.

Research-layer only: no spa_core import, no data mutation, no cycle run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = REPO_ROOT / "research"

FORBIDDEN = [
    re.compile(r"^\s*import\s+spa_core\.execution"),
    re.compile(r"^\s*from\s+spa_core\.execution\b"),
    re.compile(r"^\s*import\s+spa_core\.risk"),
    re.compile(r"^\s*from\s+spa_core\.risk\b"),
]

PY_FILES = sorted(RESEARCH_DIR.rglob("*.py"))


def test_research_py_files_discovered():
    assert PY_FILES, "no research/*.py files found (expected the validator + lifecycle checker)"


@pytest.mark.parametrize("py_file", PY_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_execution_or_risk_import(py_file: Path):
    text = py_file.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), start=1):
        for rx in FORBIDDEN:
            assert not rx.match(line), (
                f"{py_file.relative_to(REPO_ROOT)}:{i} imports runtime money-path: {line.strip()}"
            )
