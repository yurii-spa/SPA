"""The CI-Lite smoke gate must import symbols that actually exist.

Observed defect: `.github/workflows/ci-lite.yml` imported `SpaError` while the
class is `SPAError` (`spa_core/utils/errors.py`). Every CI-Lite run on main died
at that step with

    ImportError: cannot import name 'SpaError' from 'spa_core.utils.errors'

and — because a failed step aborts the job — every later step of the gate
(forbidden-import check, strategy-registry completeness) never ran at all. A gate
that always fails on its own typo checks nothing; this test makes the workflow's
import list self-verifying so the same class of typo cannot go unnoticed again.

Hermetic: parses the workflow file and imports from the installed package. No
network, no subprocess, no GitHub.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CI_LITE = _ROOT / ".github" / "workflows" / "ci-lite.yml"

# `from spa_core.x.y import a, b` and the parenthesized multi-line form.
_IMPORT_RE = re.compile(
    r"^\s*from\s+(spa_core[\w.]*)\s+import\s+(\(([^)]*)\)|([^\n(]+))",
    re.MULTILINE,
)


def _declared_imports() -> list[tuple[str, str]]:
    """[(module, symbol), ...] for every spa_core import in the workflow."""
    text = _CI_LITE.read_text(encoding="utf-8")
    pairs: list[tuple[str, str]] = []
    for m in _IMPORT_RE.finditer(text):
        module = m.group(1)
        names = m.group(3) if m.group(3) is not None else m.group(4)
        for raw in names.replace("\n", " ").split(","):
            name = raw.strip().split(" as ")[0].strip()
            if name and name != "*":
                pairs.append((module, name))
    return pairs


def test_workflow_declares_imports():
    """Guard the guard: if the parse yields nothing, this test proves nothing."""
    assert _CI_LITE.exists(), f"{_CI_LITE} missing"
    pairs = _declared_imports()
    assert len(pairs) >= 8, f"parsed too few imports from ci-lite.yml: {pairs}"


@pytest.mark.parametrize("module,symbol", _declared_imports())
def test_ci_lite_smoke_symbol_exists(module, symbol):
    mod = importlib.import_module(module)
    assert hasattr(mod, symbol), (
        f"ci-lite.yml imports `{symbol}` from `{module}`, which does not exist — "
        f"the CI-Lite gate will abort on ImportError and every later step of the "
        f"job will silently not run"
    )


def test_spa_error_is_spelled_spaerror():
    """The exact symbol the gate tripped on (spelling is load-bearing)."""
    from spa_core.utils import errors
    assert hasattr(errors, "SPAError")
    assert not hasattr(errors, "SpaError"), (
        "if a `SpaError` alias is ever added, update ci-lite.yml and this test "
        "deliberately — do not let two spellings drift"
    )
