"""tests/test_perf_budget.py — regression gate wrapper for the perf budget (WS-6.5).

# LLM_FORBIDDEN

Runs ``scripts/perf_budget.py`` in-process over a SMALL iteration count and asserts
every measured money-path / endpoint surface is under its documented budget. This
turns the perf budget into a CI-gated regression check (a slowdown that pushes a
surface over budget fails the suite) without flapping on machine jitter — the gate
compares the MEDIAN against a ceiling with generous headroom.

Hermetic: perf_budget benches against SANDBOX tmp data dirs only; the live
``data/`` is never read or written. Deterministic inputs; timing is the only
non-determinism, absorbed by the headroom.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import perf_budget  # noqa: E402


def test_perf_budget_all_surfaces_under_budget():
    """Every benched surface (cycle / allocator / reconcile / key endpoints) is
    under its documented latency budget. A small iteration count keeps the test
    fast while still measuring the warm path (median after warm-up)."""
    report = perf_budget.run_budget(iterations=5)
    assert report["rows"], "perf_budget produced no measurements"
    over = report["over_budget"]
    assert not over, (
        "perf budget regression — surfaces over their documented ceiling: "
        + ", ".join(
            f"{r['surface']}={r['median_ms']}ms (budget {r['budget_ms']}ms)"
            for r in report["rows"] if not r["ok"]
        )
    )
    assert report["pass"] is True


def test_perf_budget_is_hermetic_no_live_data(tmp_path):
    """The perf harness must never mutate the live equity track. We snapshot the
    canonical file (if present) and assert it is byte-identical after a run."""
    eq = _REPO_ROOT / "data" / "equity_curve_daily.json"
    before = eq.read_bytes() if eq.exists() else None
    perf_budget.run_budget(iterations=3)
    after = eq.read_bytes() if eq.exists() else None
    assert before == after, "perf_budget mutated the live equity_curve track!"
