"""
test_riskwire_no_fork.py — THE no-fork guarantee for RISKWIRE (WS1.2).

The NON-NEGOTIABLE rule: `spa_core/riskwire/` must NOT define its own risk math. It IMPORTS and
composes the three L3 seeds (each of which itself imports the SPA engine):
  • spa_core.dfb.risk_overlay.overlay                         (per-pool A/B/C/D + refusal + exit-by-size)
  • spa_core.strategy_lab.rwa_backstop.safety_board.classify  (per-RWA-collateral verdict + liq-NAV)
  • spa_core.strategy_lab.underwriting.report.build_report    (per-book hash-anchored killer verdict)

So RiskWire's verdict on a subject == the underlying seed's verdict == the desk's verdict — byte for
byte. The facade is a PRESENTATION + PROVENANCE + PROOF-CHAIN layer; it re-scores nothing.

Guarantees enforced here:
  1. AST guard       — no riskwire module DEFINES a risk-math primitive (refusal / haircut / exit-frac /
                       fair-value / classify) of its own; no module imports spa_core.execution.
  2. import-not-fork — the seed entrypoints riskwire uses ARE the actual seed objects (same identity).
  3. byte-identity   — the facade's verdict on a subject == the seed's verdict on the same inputs:
                         • POOL: measurement.seed_proof_hash == DFB overlay.engine_proof_hash, and
                           measurement.risk_class == overlay.risk_class (byte-identical letter).
                         • RWA:  measurement.native_verdict == safety_board.classify(result) (verbatim).
                         • BOOK: measurement.native_verdict == the underwriting report's killer verdict.
  4. toxic-still-D   — a toxic subject stays class-D + REFUSE + tail_veto (the facade cannot soften it).
  5. fail-CLOSED     — a subject the seed cannot grade → UNKNOWN + flagged, never a fabricated grade.

PURE / no network / no live-data mutation (seed verdicts are injected via overrides where a live feed
would otherwise be required).
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

from spa_core.riskwire import (
    RiskWireClass,
    Subject,
    SubjectKind,
)
from spa_core.riskwire import facade
from spa_core.riskwire import proof as rw_proof
from spa_core.dfb import Pool
from spa_core.dfb import risk_overlay as dfb_overlay
from spa_core.strategy_lab.rwa_backstop import safety_board as rwa_board
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import LiquidationNAVResult, SizedExit
from spa_core.strategy_lab.rates_desk.contracts import D0, UnderlyingKind, UnderlyingRisk
from spa_core.strategy_lab.underwriting import report as uw_report

_RW_DIR = pathlib.Path(facade.__file__).resolve().parent

# Risk-math primitives that ONLY the engine / the seeds may define. If a riskwire module defines a
# function by any of these names it would be FORKING risk math. (Presentation helpers on the facade —
# `measure`, `classify`-free mapping dicts — are allowed; `classify` itself is a BANNED name because
# that is the seed's verdict primitive: the facade must CALL rwa_board.classify, never define one.)
_BANNED_FUNC_DEFS = {
    "evaluate_entry", "evaluate_hold",                  # the refusal gate
    "haircuts", "fair", "baseline_yield",               # the fair-value decomposition
    "dex_exit_frac", "forced_unwind_frac", "concentrated_near_peg_frac",  # slippage primitives
    "compute_market_depth_row", "compute_ticket_row",   # the exit/depth engine
    "classify",                                         # the seed verdict primitive (DFB + RWA board)
    "overlay",                                          # DFB's per-pool verdict entrypoint
}

# Engine/seed math calls that must NEVER appear inside a riskwire module body (call the seed, never
# inline the primitive).
_BANNED_CALLS = {"dex_exit_frac", "forced_unwind_frac", "concentrated_near_peg_frac"}


def _rw_py_files():
    return sorted(p for p in _RW_DIR.glob("*.py"))


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1. AST guard — riskwire defines NO risk math of its own
# ══════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", _rw_py_files(), ids=lambda p: p.name)
def test_riskwire_defines_no_banned_risk_math(path):
    """No riskwire module defines any seed/engine risk-math primitive (it would be a fork)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    forked = defined & _BANNED_FUNC_DEFS
    assert not forked, f"{path.name} FORKS seed/engine risk math by defining {sorted(forked)}"


@pytest.mark.parametrize("path", _rw_py_files(), ids=lambda p: p.name)
def test_riskwire_does_not_inline_engine_slippage_primitive(path):
    """No riskwire module CALLS the engine's slippage primitive directly — it must go through the
    seed (which calls the engine). (A module may IMPORT for documentation; must not invoke.)"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None)
            assert name not in _BANNED_CALLS, (
                f"{path.name} inlines engine slippage primitive {name!r} — must call the seed")


def test_riskwire_no_execution_import():
    """No riskwire module imports spa_core.execution (the read-only / no-execution rule)."""
    for path in _rw_py_files():
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


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2. import-not-fork — the seed entrypoints riskwire uses ARE the actual seed objects
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_facade_imports_the_seeds():
    """The facade must import the ACTUAL seed entrypoints (import-not-fork, same object identity)."""
    src = (_RW_DIR / "facade.py").read_text(encoding="utf-8")
    assert "from spa_core.dfb import risk_overlay" in src
    assert "from spa_core.strategy_lab.rwa_backstop import safety_board" in src
    assert "from spa_core.strategy_lab.underwriting import report" in src
    # the objects the facade calls ARE the seeds' own (not a re-implementation).
    assert facade.dfb_overlay.overlay is dfb_overlay.overlay
    assert facade.rwa_board.classify is rwa_board.classify
    assert facade.uw_report.build_report is uw_report.build_report


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. byte-identity — the facade's verdict == the seed's verdict (per subject kind)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _susde_pool() -> Pool:
    return Pool(
        pool_id="pendle__ethereum__susde", protocol="pendle", chain="Ethereum", asset="susde",
        tier="T2", source="rates_desk_market", apy_total=0.085, tvl_usd=40_000_000.0,
        underlying_kind="stable_synth", market_id="pt-susde-1", exit_liquidity_usd=8_000_000.0,
        as_of="2026-06-29")


def _pool_subject(pool: Pool) -> Subject:
    return Subject(subject_id="pool::" + pool.pool_id.replace("__", "-"), kind=SubjectKind.POOL,
                   display_name=pool.pool_id, provenance="test", native_ref={"pool": pool.to_dict()})


def test_pool_verdict_byte_identical_to_dfb_seed():
    """POOL: the facade's measurement.seed_proof_hash == DFB overlay.engine_proof_hash, and the unified
    risk_class letter == the DFB seed's risk_class letter, byte-identical. The core no-fork guarantee."""
    pool = _susde_pool()
    ov = dfb_overlay.overlay(pool, prev_hash="0" * 64)
    m = facade.measure(_pool_subject(pool))
    assert m.seed_proof_hash == ov.engine_proof_hash                 # engine proof, byte-identical
    assert m.risk_class.value == ov.risk_class.value                 # unified letter == seed letter
    assert m.native_verdict == ov.risk_class.value                   # native preserved verbatim
    assert m.refusal.verdict == ov.refusal.verdict
    assert m.refusal.tail_veto == ov.refusal.tail_veto
    assert m.structural_haircut == ov.structural_haircut
    assert m.total_haircut == ov.total_haircut
    # exit-by-size copied verbatim from the seed (no recompute).
    seed_exit = [(r.ticket_usd, r.dex_exit_frac, r.absorbable_usd) for r in ov.exit_liquidity]
    face_exit = [(r.ticket_usd, r.exit_frac, r.absorbable_usd) for r in m.exit_liquidity_by_size]
    assert face_exit == seed_exit


def _mk_rwa_result(symbol, restricted, redeem_doc, dex_tvl, n_pools, small_frac, ref_frac):
    sized = {
        rwa_board.SMALL_SIZE_USD: SizedExit(
            size_usd=rwa_board.SMALL_SIZE_USD, on_chain_value_frac=small_frac,
            redemption_value_frac=None, liq_nav_frac=(small_frac or 0.0),
            liq_nav_usd=(small_frac or 0.0), binding_leg="dex" if small_frac else "none"),
        rwa_board.REFERENCE_SIZE_USD: SizedExit(
            size_usd=rwa_board.REFERENCE_SIZE_USD, on_chain_value_frac=ref_frac,
            redemption_value_frac=None, liq_nav_frac=(ref_frac or 0.0),
            liq_nav_usd=(ref_frac or 0.0), binding_leg="dex" if ref_frac else "none"),
        10_000_000.0: SizedExit(
            size_usd=10_000_000.0, on_chain_value_frac=None, redemption_value_frac=None,
            liq_nav_frac=0.0, liq_nav_usd=0.0, binding_leg="none"),
    }
    return LiquidationNAVResult(
        symbol=symbol, issuer="x", marketing_nav_usd=1.0, transfer_restricted=restricted,
        on_chain_dex_tvl_usd=dex_tvl, n_dex_pools=n_pools, redemption_documented=redeem_doc,
        redemption_delay_days=1.0, redemption_fee_bps=0.0, sized=sized, data_gaps=[],
        generated_at="2026-06-29")


def _rwa_subject(symbol: str) -> Subject:
    return Subject(subject_id="rwa_collateral::" + symbol.lower(), kind=SubjectKind.RWA_COLLATERAL,
                   display_name=symbol, provenance="test", native_ref={"symbol": symbol})


@pytest.mark.parametrize("verdict_name,restricted,redeem_doc,dex_tvl,n_pools,small,ref,expect_class", [
    ("LIQUID", False, True, 50_000_000.0, 4, 0.999, 0.999, RiskWireClass.A),
    ("THIN", False, True, 5_000_000.0, 2, 0.95, 0.80, RiskWireClass.B),
    ("REDEMPTION_ONLY", True, True, 0.0, 0, None, None, RiskWireClass.C),
    ("UNSAFE", True, False, 0.0, 0, None, None, RiskWireClass.D),
])
def test_rwa_native_verdict_verbatim_from_seed(verdict_name, restricted, redeem_doc, dex_tvl,
                                               n_pools, small, ref, expect_class):
    """RWA: measurement.native_verdict == safety_board.classify(result), byte-for-byte, and the unified
    letter is the documented deterministic map of THAT verdict. The board's verdict is never re-derived."""
    res = _mk_rwa_result(verdict_name, restricted, redeem_doc, dex_tvl, n_pools, small, ref)
    seed_verdict = rwa_board.classify(res)                          # the SEED's own verdict
    assert seed_verdict == verdict_name                            # (sanity: fixture is what we asked)
    m = facade.measure(_rwa_subject(verdict_name), result_override=res)
    assert m.native_verdict == seed_verdict                        # verbatim from the seed
    assert m.risk_class == expect_class                            # documented deterministic map
    # the liquidation-NAV block is the board's OWN record numbers, verbatim.
    record = rwa_board._asset_record(res)
    assert m.liquidation_nav["liq_nav_frac_1m"] == record["liq_nav_frac_1m"]
    assert m.liquidation_nav["marketing_vs_liq_gap_pct_1m"] == record["marketing_vs_liq_gap_pct_1m"]


def test_book_verdict_verbatim_from_underwriting_seed():
    """BOOK: measurement.native_verdict == the underwriting report's killer verdict, verbatim, and
    measurement.seed_proof_hash == the report head_hash (the book's hash anchor)."""
    bsub = Subject(subject_id="book::desk", kind=SubjectKind.BOOK, display_name="desk_underwriting",
                   provenance="test", native_ref={"book_id": "desk_underwriting"})
    report, err = uw_report.build_report(generated_at="2026-06-30T00:00:00Z")
    m = facade.measure(bsub, generated_at="2026-06-30T00:00:00Z")
    if err is not None or report is None:
        # fail-CLOSED path: the facade must be UNKNOWN + flagged (never a fabricated grade).
        assert m.risk_class == RiskWireClass.UNKNOWN and m.flagged
        return
    realized = next((s for s in report["sections"] if s.get("section_id") == "realized"), {})
    assert m.native_verdict == realized.get("verdict")            # verbatim killer verdict
    assert m.seed_proof_hash == report["head_hash"]              # the book's hash anchor


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 4. toxic-still-D — the facade CANNOT soften a toxic subject (size-independent structural veto)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _toxic_overlay():
    """A toxic LRT pool (large peg drawdown) whose DFB overlay REFUSES on the structural tail veto."""
    toxic_risk = UnderlyingRisk(
        underlying="ezeth", as_of="2026-06-29", nav_redemption_value=Decimal("1"),
        market_price=Decimal("0.85"), peg_distance=Decimal("0.15"), peg_vol_30d=Decimal("0.08"),
        redemption_sla_seconds=999999, reserve_fund_ratio=D0, funding_neg_frac_90d=D0,
        oracle_kind="market", oracle_staleness_seconds=86400, nested_protocol_count=5,
        top_borrower_share=Decimal("0.4"))
    pool = Pool(
        pool_id="pendle__ethereum__ezeth", protocol="pendle", chain="Ethereum", asset="ezeth",
        tier="T2", source="rates_desk_market", apy_total=0.25, tvl_usd=30_000_000.0,
        underlying_kind="lrt", market_id="pt-ezeth-1", exit_liquidity_usd=2_000_000.0,
        as_of="2026-06-29")
    ov = dfb_overlay.overlay(pool, prev_hash="0" * 64, risk_override=toxic_risk)
    return pool, ov


def test_toxic_pool_surfaces_class_D_refuse_cannot_be_softened():
    """RED-TEAM: a toxic pool the DFB seed grades D + REFUSE + tail_veto surfaces IDENTICALLY through the
    facade. There is no facade code path that can relax it (the structural veto is size-independent)."""
    pool, ov = _toxic_overlay()
    assert ov.risk_class == dfb_overlay.RiskClass.D          # sanity: the seed itself refused it as D
    assert ov.refusal.verdict == "REFUSE" and ov.refusal.tail_veto
    m = facade.measure(_pool_subject(pool), overlay_override=ov)
    assert m.risk_class == RiskWireClass.D                   # facade surfaces the SAME class
    assert m.refusal.verdict == "REFUSE"
    assert m.refusal.tail_veto is True
    assert m.native_verdict == "D"
    assert m.seed_proof_hash == ov.engine_proof_hash        # same engine proof — no divergence


def test_toxic_rwa_unsafe_surfaces_class_D_refuse():
    """RED-TEAM: an UNSAFE RWA collateral (no executable/documented exit) surfaces class-D + REFUSE +
    tail_veto — the facade cannot present it as safe/thin."""
    res = _mk_rwa_result("UNSAFE", True, False, 0.0, 0, None, None)
    assert rwa_board.classify(res) == rwa_board.UNSAFE
    m = facade.measure(_rwa_subject("UNSAFE"), result_override=res)
    assert m.risk_class == RiskWireClass.D
    assert m.refusal.verdict == "REFUSE" and m.refusal.tail_veto is True
    assert m.native_verdict == "UNSAFE"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 5. fail-CLOSED — a subject the seed cannot grade → UNKNOWN + flagged, never a fabricated grade
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_pool_malformed_identity_fails_closed():
    """A POOL subject with a malformed pool identity → UNKNOWN + flagged (never a grade)."""
    bad = Subject(subject_id="pool::bad", kind=SubjectKind.POOL, display_name="bad",
                  provenance="test", native_ref={"pool": "not-a-dict"})
    m = facade.measure(bad)
    assert m.risk_class == RiskWireClass.UNKNOWN
    assert m.flagged and m.native_verdict == "UNKNOWN"
    assert m.seed_proof_hash == ""              # no fabricated proof


def test_rwa_unknown_symbol_fails_closed():
    """An RWA subject for a symbol not in the registry → UNKNOWN + flagged."""
    bad = Subject(subject_id="rwa_collateral::nope", kind=SubjectKind.RWA_COLLATERAL,
                  display_name="NOPE", provenance="test", native_ref={"symbol": "NOPE"})
    m = facade.measure(bad)
    assert m.risk_class == RiskWireClass.UNKNOWN and m.flagged


def test_unknown_subject_kind_fails_closed():
    """A subject whose kind is not routable → UNKNOWN + flagged (no fabricated grade)."""
    # SubjectKind is an enum; simulate an unroutable kind by monkeypatching a subject-like object.
    class _FakeKind:
        value = "galaxy"
    fake = Subject(subject_id="x::y", kind=SubjectKind.POOL, display_name="x", provenance="t",
                   native_ref={})
    import dataclasses
    fake = dataclasses.replace(fake)
    object.__setattr__(fake, "kind", _FakeKind())   # bypass the enum to hit the unknown-kind branch
    m = facade.measure(fake)
    assert m.risk_class == RiskWireClass.UNKNOWN and m.flagged


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# determinism + chain
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_measurement_deterministic():
    """Same subject → byte-identical measurement (incl. row_hash) across runs."""
    pool = _susde_pool()
    a = facade.measure(_pool_subject(pool)).to_dict()
    b = facade.measure(_pool_subject(pool)).to_dict()
    assert a == b


def test_measure_all_chain_valid():
    """measure_all proof-chains the measurements; the chain verifies fail-CLOSED."""
    pool = _susde_pool()
    subs = [_pool_subject(pool), _rwa_subject("LIQUID")]
    res = _mk_rwa_result("LIQUID", False, True, 50_000_000.0, 4, 0.999, 0.999)
    ms = facade.measure_all(subs, result_override=res)
    assert rw_proof.verify_chain(ms)
    # tamper a row's CONTENT while leaving its stale row_hash → the recompute diverges → chain breaks
    # (tamper-evidence). Flip the grade to a DIFFERENT letter than the seed produced and keep row_hash.
    import dataclasses
    tampered = list(ms)
    forged_class = (RiskWireClass.D if tampered[0].risk_class != RiskWireClass.D
                    else RiskWireClass.A)
    tampered[0] = dataclasses.replace(tampered[0], risk_class=forged_class,
                                      native_verdict=forged_class.value)  # row_hash left stale
    assert not rw_proof.verify_chain(tampered)
