"""
test_dfb_no_fork.py — THE no-fork guarantee for DFB.

The NON-NEGOTIABLE rule: `spa_core/dfb/` must NOT define its own risk math. It IMPORTS and composes
the SPA engine (rate_policy / fair_value_engine / depth_at_size / exit_nav / proof_chain /
risk.policy / the A/B/C/D taxonomy). So the desk's verdict and DFB's verdict on the SAME pool are
always BYTE-IDENTICAL — the two products can never drift.

Three guarantees, all enforced here:
  1. AST guard      — DFB defines NO refusal / haircut / exit-fraction / fair-value math of its own
                      (no banned-name function defs; no forbidden engine-math calls outside the
                      engine; the risk_overlay module DOES import the engine entrypoints).
  2. byte-identity  — DFB's `overlay(pool).engine_proof_hash` == the engine's own
                      `evaluate_entry(...).proof_hash()` reconstructed from DFB's engine_inputs.
  3. import-not-fork — every engine risk entrypoint DFB uses is the ACTUAL engine object (same
                      module identity), not a re-implementation.

PURE / no network / no live-data mutation.
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

from spa_core.dfb import Pool
from spa_core.dfb import risk_overlay as ro
from spa_core.strategy_lab.rates_desk import depth_at_size as engine_depth
from spa_core.strategy_lab.rates_desk import rate_policy as engine_policy
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry

_DFB_DIR = pathlib.Path(ro.__file__).resolve().parent

# Risk-math primitives that ONLY the engine may define. If DFB defines a function by any of these
# names it would be FORKING the engine's math. (Presentation helpers like `classify` are allowed —
# they compose engine OUTPUTS; they are not in this banned set.)
_BANNED_FUNC_DEFS = {
    "evaluate_entry", "evaluate_hold",            # the refusal gate
    "haircuts", "fair", "baseline_yield",         # the fair-value decomposition
    "dex_exit_frac", "forced_unwind_frac", "concentrated_near_peg_frac",  # slippage primitives
    "compute_market_depth_row", "compute_ticket_row",  # the exit/depth engine
}

# Engine-math calls that must NEVER appear inside a DFB module body (DFB must call the engine, never
# inline the primitive itself).
_BANNED_CALLS = {"dex_exit_frac", "forced_unwind_frac", "concentrated_near_peg_frac"}


def _dfb_py_files():
    return sorted(p for p in _DFB_DIR.glob("*.py"))


@pytest.mark.parametrize("path", _dfb_py_files(), ids=lambda p: p.name)
def test_dfb_defines_no_banned_risk_math(path):
    """No DFB module defines any of the engine's risk-math primitives (it would be a fork)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    forked = defined & _BANNED_FUNC_DEFS
    assert not forked, f"{path.name} FORKS engine risk math by defining {sorted(forked)}"


@pytest.mark.parametrize("path", _dfb_py_files(), ids=lambda p: p.name)
def test_dfb_does_not_inline_engine_slippage_primitive(path):
    """No DFB module CALLS the engine's slippage primitive directly — it must go through the engine's
    compute_market_depth_row / compute_ticket_row (which apply it). (A DFB module may IMPORT them for
    documentation, but must not invoke them — asserted on Call nodes only.)"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None)
            assert name not in _BANNED_CALLS, (
                f"{path.name} inlines engine slippage primitive {name!r} — must call the engine")


def test_dfb_no_execution_import():
    """No DFB module imports spa_core.execution (the read-only / no-execution rule)."""
    for path in _dfb_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for m in mods:
                assert "spa_core.execution" not in (m or ""), (
                    f"{path.name} imports execution domain ({m})")


def test_risk_overlay_imports_the_engine():
    """risk_overlay must import the actual engine entrypoints (import-not-fork)."""
    src = (_DFB_DIR / "risk_overlay.py").read_text(encoding="utf-8")
    assert "from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry" in src
    assert "compute_market_depth_row" in src
    # the entrypoints DFB uses ARE the engine's own objects (same identity), not a re-implementation.
    assert ro.evaluate_entry is engine_policy.evaluate_entry
    assert ro.compute_market_depth_row is engine_depth.compute_market_depth_row


def test_dfb_verdict_byte_identical_to_desk():
    """DFB's overlay(pool).engine_proof_hash == the desk's evaluate_entry(...).proof_hash() on the
    SAME inputs (reconstructed via DFB's own engine_inputs). The core no-fork guarantee."""
    pool = Pool(
        pool_id="pendle__ethereum__susde", protocol="pendle", chain="Ethereum", asset="susde",
        tier="T2", source="rates_desk_market", apy_total=0.085, tvl_usd=40_000_000.0,
        underlying_kind="stable_synth", market_id="pt-susde-1", exit_liquidity_usd=8_000_000.0,
        as_of="2026-06-29")
    ov = ro.overlay(pool, prev_hash="0" * 64)
    kind = ro._resolve_kind(pool)
    risk = ro._build_risk(pool, kind, "2026-06-29")
    inp = ro.engine_inputs(pool, kind, risk, "2026-06-29")
    res, _ = evaluate_entry(
        opp=inp["opp"], risk=inp["risk"], debt_asset_price=inp["debt_asset_price"],
        exit_liquidity=inp["exit_liquidity"], params=RatePolicyParams(), state=inp["state"])
    assert ov.engine_proof_hash == res.proof_hash()
    assert ov.refusal.verdict == ("SAFE" if res.approved else "REFUSE")
    assert ov.structural_haircut == round(float(res.decomposition.structural_haircut), 8)


def test_overlay_deterministic():
    """Same pool → byte-identical overlay (incl. every hash) across runs."""
    pool = Pool(
        pool_id="pendle__ethereum__susde", protocol="pendle", chain="Ethereum", asset="susde",
        tier="T2", source="rates_desk_market", apy_total=0.085, tvl_usd=40_000_000.0,
        underlying_kind="stable_synth", market_id="pt-susde-1", exit_liquidity_usd=8_000_000.0,
        as_of="2026-06-29")
    a = ro.overlay(pool, prev_hash="0" * 64).to_dict()
    b = ro.overlay(pool, prev_hash="0" * 64).to_dict()
    assert a == b
