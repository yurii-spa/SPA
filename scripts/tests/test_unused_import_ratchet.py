"""
scripts/tests/test_unused_import_ratchet.py — Sprint T10 (2026-06-27)

Unused-import RATCHET over SPA's MONEY-PATH + actively-edited dirs.

Runs ``pyflakes`` over the money-path packages and counts the
``imported but unused`` warnings. Asserts the count stays ``<=`` a pinned
ceiling — a one-way ratchet so it can only go DOWN, never up. This guards
against an accidental re-introduction of dead imports on the code that
actually moves capital (cycle/allocator/risk/api-routers/strategy-lab/alerts).

  Mirrors the ceiling style of ``tests/test_dead_code_resolved.py`` —
  a regression guardrail, NOT a hard zero.

─── Pinned count history ─────────────────────────────────────────────────────
  * 2026-06-27 (Sprint T10): cleaned 126 → 36. Ceiling pinned at **36**.

Why the floor is 36 and not 0 — every remaining warning is a DELIBERATE,
documented re-export / back-compat surface that MUST stay (removing it would
break ``from <module> import X`` callers/tests byte-for-byte):

  * spa_core/alerts/__init__.py        (1)  — ``telegram_client`` re-exported as a
       package attribute so tests can monkeypatch
       ``spa_core.alerts.telegram_client.send_message`` (``# noqa: F401``).
  * spa_core/alerts/risk_monitor.py    (24) — threshold-constant + alert-class
       re-export block from ``apy_feed_monitors`` kept byte-for-byte so the ~10
       test files + export_data that do ``from alerts.risk_monitor import <CONST>``
       keep working (``# noqa: F401``).
  * spa_core/paper_trading/cycle_runner.py (10) — documented back-compat surface;
       tests do ``from ...cycle_runner import <name>`` for the extracted
       _cycle_io / equity / cycle_reporting helpers (``# noqa: F401``).
  * spa_core/risk/scoring_engine.py    (1)  — ``import urllib.error`` kept
       intentionally for exception-handler safety; pyflakes flags only the
       redundant binding.

To LOWER the ceiling: clean more genuinely-unused imports, then drop CEILING to
the new observed count. To RAISE it: don't — that defeats the ratchet. If a NEW
legitimate re-export must be added, document it here and bump CEILING by exactly
that count, with a dated note above.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Money-path + actively-edited dirs under ratchet.
MONEY_PATH_DIRS = [
    "spa_core/paper_trading/",
    "spa_core/allocator/",
    "spa_core/risk/",
    "spa_core/api/routers/",
    "spa_core/strategy_lab/",
    "spa_core/alerts/",
]

# Pinned ceiling — 2026-06-27 (Sprint T10): observed 36 after the clean.
# RATCHET: this may only ever be LOWERED, never raised (see module docstring).
CEILING = 36


def _unused_import_count() -> int:
    """Run pyflakes over the money-path dirs; count 'imported but unused'."""
    targets = [str(REPO / d) for d in MONEY_PATH_DIRS]
    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", *targets],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=120,
    )
    # pyflakes exits non-zero when it finds warnings — that's expected.
    out = result.stdout
    return sum(1 for line in out.splitlines() if "imported but unused" in line)


class TestUnusedImportRatchet:
    def test_pyflakes_available(self):
        """pyflakes must be importable — the ratchet depends on it."""
        proc = subprocess.run(
            [sys.executable, "-m", "pyflakes", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, (
            "pyflakes is not available — the unused-import ratchet cannot run. "
            f"stderr: {proc.stderr.strip()!r}"
        )

    def test_money_path_unused_imports_le_ceiling(self):
        """Unused-import count over money-path dirs must stay <= the pinned ceiling.

        This is a one-way ratchet: it can only go down. A FAILURE means new
        unused imports were introduced on the capital-moving code path — remove
        them (do NOT raise CEILING).
        """
        count = _unused_import_count()
        assert count <= CEILING, (
            f"Unused-import count on money-path dirs rose to {count} "
            f"(ceiling {CEILING}). New dead imports were introduced — remove them. "
            f"Do NOT raise the ceiling; the ratchet only goes down."
        )

    def test_ceiling_is_tight(self):
        """The ceiling must not drift far above the actual count.

        If the real count has dropped well below CEILING, LOWER the ceiling so
        the ratchet keeps biting. Allow a small buffer (4) for transient churn.
        """
        count = _unused_import_count()
        assert count >= CEILING - 4, (
            f"Unused-import count dropped to {count}, well under the ceiling "
            f"{CEILING}. Lower CEILING to {count} so the ratchet stays tight."
        )
