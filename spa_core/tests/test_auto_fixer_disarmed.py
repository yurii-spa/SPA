#!/usr/bin/env python3
"""ADR-106 — the code auto-fixer has no trigger left.

Owner decision of 2026-08-21 09:39Z (card
``own-56-avtopochinshchik-ostalsya-bez-vyzyvayushchih``, **вариант 2**):
keep ``spa_core/devtools/auto_fixer.py`` as a library, remove its entry point.

Why this needs a guard at all
-----------------------------
The dangerous property was never "this module exists" — it was "this module is
one line away from running". ``python3 -m spa_core.devtools.auto_fixer`` asked
Claude to rewrite production code, applied the patch and pushed it. The caller
that used to drive it was retired, which is precisely what made it worse, not
better: a module nobody calls, with a trigger still attached, is the class we
had already been burned by on ``bot_commands``. A comment saying "disarmed"
survives exactly until the next person adds a convenient ``main()``.

The tests below therefore check the property, not the prose: the module must
not be startable, and its library surface must still be intact (option 2 was
"disarm", not "delete" — a test that passed because the file vanished would be
enforcing the wrong decision).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_MODULE = "spa_core.devtools.auto_fixer"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _REPO_ROOT / "spa_core" / "devtools" / "auto_fixer.py"


def test_module_has_no_main_guard():
    """No ``if __name__ == "__main__"`` — the card's literal acceptance criterion."""
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    guards = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and any(
            isinstance(n, ast.Name) and n.id == "__name__"
            for n in ast.walk(node.test)
        )
    ]
    assert not guards, (
        "auto_fixer has a __main__ guard again — the loop the owner closed "
        "(LLM rewrites prod code and pushes it) is one command line away"
    )


def test_module_has_no_cli_entry_function():
    """No ``main()`` either.

    Deleting only the guard would leave ``python3 -c 'from
    spa_core.devtools.auto_fixer import main; main()'`` — a trigger with an
    extra step, not a trigger removed.
    """
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "main" not in names, (
        "auto_fixer defines main() again — option 2 was 'take the trigger off', "
        "and a callable entry point IS the trigger"
    )


def test_running_the_module_as_a_program_does_nothing():
    """The effect, measured in a child process rather than inferred from source.

    ``python3 -m spa_core.devtools.auto_fixer`` must import cleanly and exit
    without doing any work. This is the check that survives a refactor which
    moves the entry point somewhere the AST scan above does not look.
    """
    proc = subprocess.run(
        [sys.executable, "-m", _MODULE],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"running the disarmed module failed (rc={proc.returncode}); it should "
        f"be an inert import\nstderr: {proc.stderr[-2000:]}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    for marker in ("applying fix", "pushing", "claude", "usage:"):
        assert marker not in combined, (
            f"running the module produced {marker!r} — it still behaves like a "
            f"program\noutput: {combined[-2000:]}"
        )


def test_library_surface_is_intact():
    """Option 2 was disarm, NOT delete — the functions must still be here.

    Without this, the suite would go green if someone deleted the file, i.e. it
    would silently enforce option 1 (a different decision, which the owner did
    not choose).
    """
    import importlib

    mod = importlib.import_module(_MODULE)
    assert callable(getattr(mod, "run_auto_fix", None)), (
        "run_auto_fix is gone — the owner chose to keep the library, so its "
        "disappearance is a decision nobody made"
    )
