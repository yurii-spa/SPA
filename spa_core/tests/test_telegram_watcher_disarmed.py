#!/usr/bin/env python3
"""ADR-113 — the Telegram watcher reads the chat and repairs nothing.

Owner decision of 2026-08-21 12:34Z (card
``owner-decision-peresprashivayu-sudba-storozha-telegram``, **вариант 2**):
keep the watcher, disarm it.

The loop this closes
--------------------
``spa_core/monitoring/telegram_watcher.py`` ended its per-alert branch with
``run_auto_fix(text, token=token, chat_id=chat_id)``: text that arrived in the
owner's chat was handed to an LLM which rewrote production code and pushed it.
The owner called this the riskiest loop in the system, and it also stands
against invariant #3 (no LLM in monitoring).

ADR-106 removed the entry point from ``auto_fixer`` itself. That did **not**
touch this half: the watcher called the repair *inside its own process*, so it
never needed an entry point. The agent is not loaded today — but the loop was
assembled and waiting for one ``launchctl bootstrap``.

Why the by-name test is not enough
----------------------------------
``test_module_does_not_reference_the_auto_fixer`` reads the AST, so it catches a
re-import by name. It cannot catch a rewiring through a different name, and it
would pass on a module that imports the repair under an alias. So the second
test measures the EFFECT, and it has to do it in a child process: the old code
bound ``run_auto_fix`` at IMPORT time, so a spy installed after the import — the
only thing an in-process ``monkeypatch`` can do — would watch the wrong object
and stay green on the armed module. The child installs the spy in
``sys.modules`` BEFORE the import, which is the only vantage point from which
the armed and the disarmed module look different.

Both tests are positive controls: verified red against the armed module
(``docs/journal/2026-W34.md``).
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import spa_core.monitoring.telegram_watcher as tw

_MODULE_PATH = Path(tw.__file__)
# .../<repo>/spa_core/monitoring/telegram_watcher.py → monitoring → spa_core → repo
_REPO = _MODULE_PATH.resolve().parents[2]


# ═══════════════════════════════════════════════════════════════════════════
# 1. By name — nothing in the executable module mentions the repair
# ═══════════════════════════════════════════════════════════════════════════

def test_module_does_not_reference_the_auto_fixer():
    """No import of ``auto_fixer``, no call to anything called ``*auto_fix*``.

    The AST is read, not the text: the module's own docstring explains at
    length what used to be here and why it is gone, and a prose grep would
    either flag that explanation or force us to delete the explanation. Code is
    the thing under test; prose is the thing we want to keep.
    """
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))

    imported: list[str] = []
    called: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "auto_fixer" in node.module:
                imported.append(f"from {node.module} import ...")
            for alias in node.names:
                if "auto_fix" in alias.name:
                    imported.append(f"from {node.module} import {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "auto_fix" in alias.name:
                    imported.append(f"import {alias.name}")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute)
                else ""
            )
            if "auto_fix" in name:
                called.append(f"{name}() at line {node.lineno}")

    assert not imported, (
        f"the watcher imports the auto-fixer again: {imported}. ADR-113 removed "
        f"the import so there is no name to re-bind"
    )
    assert not called, (
        f"the watcher calls the auto-fixer again: {called}. This is the loop the "
        f"owner named the riskiest in the system"
    )


def test_the_repair_library_itself_is_untouched():
    """The owner chose "disarm", not "delete" — a green suite must not be able
    to mean that variant 1 was delivered instead.

    ADR-106 kept ``auto_fixer`` as an importable library with no entry point.
    If this file's other tests went green because somebody deleted the module,
    that would be a DIFFERENT decision than the one the owner made, delivered
    silently. So: the library still imports, and it still has no ``main``.
    """
    import spa_core.devtools.auto_fixer as af

    assert hasattr(af, "run_auto_fix"), (
        "the repair library was deleted — that is owner variant 1, and the "
        "owner chose variant 2"
    )
    assert not hasattr(af, "main"), (
        "ADR-106 took the entry point away; it must stay away"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 2. By effect — a spy installed BEFORE the import is never called
# ═══════════════════════════════════════════════════════════════════════════

_CHILD = textwrap.dedent(
    '''
    """Run the watcher with a booby-trapped auto_fixer already in sys.modules.

    Written as a child process on purpose: the armed module bound
    ``run_auto_fix`` at import time, so the spy has to exist BEFORE the import.
    """
    import json, sys, time, types
    from pathlib import Path

    repo, tmp = sys.argv[1], Path(sys.argv[2])
    sys.path.insert(0, repo)

    sentinel = tmp / "REPAIR_WAS_CALLED"

    # The trap. If the watcher still reaches for a repair, this fires and
    # leaves a file behind — evidence that survives the process.
    fake = types.ModuleType("spa_core.devtools.auto_fixer")
    def run_auto_fix(alert_text, **kwargs):
        sentinel.write_text(alert_text[:200], encoding="utf-8")
        return True
    fake.run_auto_fix = run_auto_fix
    sys.modules["spa_core.devtools.auto_fixer"] = fake

    import spa_core.monitoring.telegram_watcher as tw

    # Keep the watcher's scratch files inside the sandbox.
    tw.TMP_PREFIX_SEEN = str(tmp / "seen_")
    tw.TMP_PREFIX_COOLDOWN = str(tmp / "cooldown_")

    updates = [{
        "update_id": 1,
        "message": {
            "date": int(time.time()),
            "text": "❌ CRITICAL: cycle_runner crashed with Traceback",
        },
    }]
    detected = tw.process_updates(updates, token="t", chat_id="c")

    print(json.dumps({
        "detected": detected,
        "repair_called": sentinel.exists(),
        "repair_saw": sentinel.read_text(encoding="utf-8") if sentinel.exists() else "",
    }))
    '''
)


def _run_child(tmp_path: Path) -> dict:
    driver = tmp_path / "drive_watcher.py"
    driver.write_text(_CHILD, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(driver), str(_REPO), str(tmp_path)],
        capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, (
        f"the child could not even run the watcher:\n{proc.stdout}\n{proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_an_alert_never_reaches_a_repair(tmp_path):
    """THE test. A real CRITICAL alert goes in; no repair comes out."""
    out = _run_child(tmp_path)

    assert out["repair_called"] is False, (
        f"the watcher handed chat text to the repair path — the loop is armed "
        f"again. It was given: {out['repair_saw']!r}"
    )


def test_the_alert_is_still_detected(tmp_path):
    """The other direction, and the reason "disarm" is not "delete".

    Without this, gutting ``process_updates`` into ``return 0`` would satisfy
    every assertion above. The owner kept the watcher because reading the chat
    is worth something: the alert must still be recognised and counted.
    """
    out = _run_child(tmp_path)

    assert out["detected"] == 1, (
        f"the watcher stopped seeing alerts (detected={out['detected']}); "
        f"variant 2 keeps the reading, it only removes the repairing"
    )


def test_the_count_now_means_alerts_not_repairs(tmp_path):
    """A number whose name outlived its meaning is a lie waiting to be read.

    ``process_updates`` used to return "repairs triggered", and it only ever
    counted an alert when ``run_auto_fix`` returned True. With the repair gone
    that number would have been permanently 0 while alerts kept arriving —
    a watcher reporting "nothing happened" on a day full of alarms. It now
    returns what it does: alerts detected.
    """
    assert "alerts DETECTED" in (tw.process_updates.__doc__ or ""), (
        "the return value must document what it counts"
    )
    out = _run_child(tmp_path)
    assert out["detected"] > 0 and out["repair_called"] is False, (
        "an alert was seen and nothing was repaired — that is the whole "
        "contract of the disarmed watcher"
    )
