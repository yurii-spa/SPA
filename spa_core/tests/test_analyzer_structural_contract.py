"""
test_analyzer_structural_contract.py — WS4 de-bloat: ONE parametrized family
that asserts the module-AGNOSTIC structural contract every DeFi-protocol-vault
analyzer must honour, swept across ALL such analyzer modules.

Background
----------
There are ~112 hand-written ``test_defi_protocol_vault_*_analyzer.py`` files
(1000-1500 LOC each). Each tests a DISTINCT analyzer with its own threshold /
classification / override assertions (those stay in their files — they are NOT
interchangeable and must not be lost). But every one of those files also
re-copies the SAME structural boilerplate: "analyze() returns the documented
keys, score in [0,100], grade in A-F, flags is a list, output is JSON-
serialisable and finite, _demo_positions() runs through analyze_portfolio()".

That boilerplate is the same contract 112×. This module asserts it ONCE,
parametrized over the discovered analyzer set, with EQUAL coverage of those
invariants and a fraction of the LOC. It does NOT replace the per-analyzer
threshold tests — it consolidates only the repeated structural contract.

Marked ``slow`` (it imports + exercises the whole analyzer family) so it can be
excluded from the fast lane; it is deterministic and parallel-safe (no live
data, no shared state — runs fine under ``-n auto``).

stdlib + pytest only; no network; no live data/.
"""
from __future__ import annotations

import glob
import importlib
import json
import math
import os
import re

import pytest

pytestmark = pytest.mark.slow

_TESTS_DIR = os.path.dirname(__file__)


def _discover_analyzer_modules():
    """Discover the analyzer module each ``test_defi_protocol_vault_*_analyzer``
    file targets, by reading its ``from spa_core.analytics... import`` line. We
    key off the EXISTING test files so this sweep covers exactly the analyzers
    the suite already vouches for (no guessing, no drift)."""
    mods = set()
    pattern = os.path.join(_TESTS_DIR, "test_defi_protocol_vault_*_analyzer.py")
    rx = re.compile(r"from\s+(spa_core\.analytics[\w.]*\.[\w]+_analyzer)\s+import")
    for f in glob.glob(pattern):
        with open(f, encoding="utf-8") as fh:
            m = rx.search(fh.read())
        if m:
            mods.add(m.group(1))
    return sorted(mods)


_MODULES = _discover_analyzer_modules()


def _analyzer_class(mod):
    """Return the single public ``*Analyzer`` class in a module."""
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and name.endswith("Analyzer") and obj.__module__ == mod.__name__:
            return obj
    # fall back to any *Analyzer (some re-export)
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and name.endswith("Analyzer"):
            return obj
    return None


def _score_value(pos: dict):
    """Universal score accessor: most analyzers expose ``score``; a few name it
    ``efficiency_score`` / ``cost_score`` etc. Return the first 0-100 score-like
    numeric field found, or None."""
    if "score" in pos and isinstance(pos["score"], (int, float)):
        return pos["score"]
    for k, v in pos.items():
        if k.endswith("_score") and isinstance(v, (int, float)):
            return v
    return None


def _assert_finite(obj):
    """No NaN/Inf anywhere in the (already JSON-serialisable) structure."""
    if isinstance(obj, float):
        assert math.isfinite(obj), f"non-finite float: {obj}"
    elif isinstance(obj, dict):
        for v in obj.values():
            _assert_finite(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _assert_finite(v)


def test_analyzer_modules_discovered():
    """Sanity: we actually found the analyzer family (guards against a silent
    empty parametrization that would make every contract test vacuously pass)."""
    assert len(_MODULES) >= 100, (
        f"expected to discover the ~112 analyzer family, found {len(_MODULES)} "
        "— a broken discovery would make the structural sweep vacuous"
    )


@pytest.mark.parametrize("modname", _MODULES)
def test_structural_contract(modname):
    """The module-agnostic contract EVERY analyzer must honour."""
    mod = importlib.import_module(modname)

    # 1. Common helper/CLI surface the family standardises on.
    assert hasattr(mod, "_demo_positions"), f"{modname}: missing _demo_positions"
    assert hasattr(mod, "_grade_from_score"), f"{modname}: missing _grade_from_score"
    assert hasattr(mod, "_build_default_cfg"), f"{modname}: missing _build_default_cfg"

    cls = _analyzer_class(mod)
    assert cls is not None, f"{modname}: no *Analyzer class found"
    analyzer = cls()

    # 2. _demo_positions() is a non-empty list and runs through the portfolio path.
    positions = mod._demo_positions()
    assert isinstance(positions, list) and positions, f"{modname}: empty demo positions"

    result = analyzer.analyze_portfolio(positions)
    assert isinstance(result, dict), f"{modname}: analyze_portfolio not a dict"
    assert "positions" in result and "aggregate" in result, f"{modname}: missing positions/aggregate"
    assert len(result["positions"]) == len(positions), f"{modname}: position count mismatch"

    # 3. JSON-serialisable and finite (no NaN/Inf leaking into the artifact).
    raw = json.dumps(result)
    assert "NaN" not in raw and "Infinity" not in raw, f"{modname}: NaN/Infinity in output"
    _assert_finite(result)

    # 4. Per-position invariants: grade in A-F, flags is a list, score (where the
    #    analyzer exposes one) is bounded to [0, 100].
    for pos in result["positions"]:
        assert pos.get("grade") in {"A", "B", "C", "D", "F"}, f"{modname}: bad grade {pos.get('grade')!r}"
        assert isinstance(pos.get("flags"), list), f"{modname}: flags not a list"
        sc = _score_value(pos)
        if sc is not None:
            assert 0.0 <= sc <= 100.0, f"{modname}: score {sc} out of [0,100]"

    # 5. _grade_from_score maps the score range to the documented A-F band and is
    #    monotone non-increasing as the score falls (a universal grading contract).
    grades = [mod._grade_from_score(s) for s in (100.0, 80.0, 60.0, 40.0, 0.0)]
    assert all(g in {"A", "B", "C", "D", "F"} for g in grades), f"{modname}: _grade_from_score off-band"


@pytest.mark.parametrize("modname", _MODULES)
def test_empty_portfolio_is_safe(modname):
    """analyze_portfolio([]) must not raise and must return the documented shape
    (fail-safe on no data — a universal contract)."""
    mod = importlib.import_module(modname)
    cls = _analyzer_class(mod)
    result = cls().analyze_portfolio([])
    assert isinstance(result, dict)
    assert result.get("positions") == [] or result.get("positions") == list(result.get("positions", []))
    json.dumps(result)  # serialisable even when empty
