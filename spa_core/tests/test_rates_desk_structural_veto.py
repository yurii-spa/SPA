"""
spa_core/tests/test_rates_desk_structural_veto.py — RED-TEAM FAIL #1 regression suite.

The bug: the rates-desk gate computed the TAIL_VETO on `total_haircut`, which INCLUDES the size-dependent
liquidity haircut. A tail-toxic book (ezETH/LRT) could therefore be SIZED DOWN until its liquidity
haircut shrank enough to drop total_haircut under the cap → APPROVED (proven: decision_log seq=63 ezETH,
approved at $4,062.50). Sizing down must shrink the POSITION, never the TOXICITY verdict.

The fix: the toxicity veto is now computed on the SIZE-INDEPENDENT `structural_haircut` (peg + funding +
oracle + protocol, EXCLUDING liquidity) against `max_structural_haircut`. A structurally-toxic book is
REFUSED at ANY size; the total-haircut economics check is kept ADDITIONALLY (a book can also fail on
size/liquidity), but toxicity can no longer be sized around.

These tests FAIL on the old behavior and PASS on the fix:
  • a tail-toxic book is REFUSED at EVERY size incl. tiny ($1k, $4k, $100k) — exploit closed.
  • the regenerated decision log has ZERO approved rows on known-toxic LRT underlyings across the
    full history (and the historical seq=63-equivalent ezETH is REFUSED).
  • a genuinely-clean book (real stable carry, structural < cap) still APPROVES at appropriate size.
  • refusal-first ordering preserved; the structural veto is the FIRST veto.

Run:
    python3 -m pytest spa_core/tests/test_rates_desk_structural_veto.py -p no:randomly -q
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

from spa_core.strategy_lab.rates_desk import config as rd_config
from spa_core.strategy_lab.rates_desk import proof_chain
from spa_core.strategy_lab.rates_desk.contracts import (
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry

P = RatePolicyParams()
ENG = FairValueEngine(P)
_ROOT = Path(__file__).resolve().parents[2]
_REAL_LOG = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"

# the canonical known-toxic restaking (LRT) underlyings — none may EVER carry an approved row.
TOXIC_LRTS = ("ezeth", "eeth", "weeth", "rseth", "pufeth", "rsweth", "ageth", "ezsol")


def _toxic_ezeth_exploit_risk(underlying: str = "ezeth") -> UnderlyingRisk:
    """The EXACT seq=63-style exploit surface: a MODERATE peg distance UNDER the 1% hard depeg gate (so
    that gate does not catch it) + peg volatility that drives the peg haircut up, with the documented
    config LRT constants (nesting/concentration/oracle) → structural_haircut ~0.097 (above the 0.09 cap),
    but peg_distance 0.008 < 0.01 so UNDERLYING_DEPEG does NOT fire — the structural veto must."""
    return UnderlyingRisk(
        underlying=underlying, as_of="2024-09-01",
        nav_redemption_value=D("1"), market_price=D("0.992"),
        peg_distance=D("0.008"), peg_vol_30d=D("0.016"),
        redemption_sla_seconds=rd_config.redemption_sla_seconds(underlying),
        reserve_fund_ratio=D(str(rd_config.reserve_fund_ratio(underlying))),
        funding_neg_frac_90d=D("0.05"),
        oracle_kind=rd_config.oracle_kind(underlying),
        oracle_staleness_seconds=rd_config.oracle_staleness_seconds(underlying),
        nested_protocol_count=rd_config.nested_protocol_count(underlying),
        top_borrower_share=D(str(rd_config.top_borrower_share(underlying))),
    )


def _quote(underlying: str, exit_liq: D, kind=UnderlyingKind.LRT) -> RateQuote:
    return RateQuote(
        underlying=underlying, kind=kind, venue=RateVenue.PENDLE_PT, protocol="pendle",
        market_id=f"PT-{underlying}", tenor_seconds=86400 * 60, as_of="2024-09-01",
        quoted_rate=D("0.35"), tvl_usd=D("5e7"), exit_liquidity_usd=exit_liq, hedge_available=False)


def _entry(risk, size: str, exit_liq: D = D("65000"), kind=UnderlyingKind.LRT, **econ):
    q = _quote(risk.underlying, exit_liq, kind)
    opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=D(size))
    return evaluate_entry(opp, risk, D("1"), q.exit_liquidity_usd, P, KillState(), engine=ENG, **econ)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1. the SIZE-DOWN exploit is closed — toxic refused at EVERY size
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_toxic_lrt_refused_at_every_size_incl_tiny():
    """A tail-toxic LRT (structural haircut ~0.097 > the 0.09 cap) is REFUSED at EVERY requested size —
    $1k, $4,062.5 (the seq=63 exploit size), $50k, $100k. The size-down-to-approve exploit is closed:
    sizing down shrinks the POSITION, never the toxicity verdict."""
    risk = _toxic_ezeth_exploit_risk()
    # confirm the surface is the exploit shape: structural over cap, peg under the 1% depeg gate.
    dec = ENG.fair(risk=risk, kind=UnderlyingKind.LRT, tenor_seconds=86400 * 60,
                   hedge_available=False, position_size_usd=D("1000"),
                   exit_liquidity_usd=D("65000"), as_of="2024-09-01")
    assert dec.structural_haircut > P.max_structural_haircut, "fixture must be structurally toxic"
    assert risk.peg_distance < P.max_peg_distance, "fixture must slip UNDER the 1% depeg gate"

    for size in ("1000", "4062.5", "50000", "100000"):
        res, _ = _entry(risk, size)
        assert res.approved is False, f"toxic LRT approved at size {size} — exploit reopened"
        assert res.reason == KillReason.TAIL_VETO, f"wrong reason at size {size}: {res.reason}"
        assert res.approved_size_usd == D("0")


def test_structural_veto_is_size_invariant():
    """The structural_haircut (the toxicity signal) is IDENTICAL across sizes — it is what the veto reads,
    so the verdict cannot move with size. (The liquidity haircut DOES shrink with size; that is fine — it
    is no longer part of the toxicity verdict.)"""
    risk = _toxic_ezeth_exploit_risk()
    structs = set()
    for size in ("1000", "4062.5", "100000"):
        dec = ENG.fair(risk=risk, kind=UnderlyingKind.LRT, tenor_seconds=86400 * 60,
                       hedge_available=False, position_size_usd=D(size),
                       exit_liquidity_usd=D("65000"), as_of="2024-09-01")
        structs.add(dec.structural_haircut)
    assert len(structs) == 1, "structural haircut must be size-INDEPENDENT"


def test_every_toxic_lrt_underlying_refused_at_tiny_size():
    """Every canonical RESTAKING-LRT underlying (config kind == 'lrt': ezETH/rsETH — the books carrying
    the restaking/nesting tail) on the exploit surface is refused even at a tiny ticket. (eeth/weeth are
    config-classified PLAIN LSTs, not restaking LRTs, so they carry a lighter structural tail and are not
    in this structural-refusal set; the public-log scan below still proves NONE of them carries an
    approved row.)"""
    lrts = [u for u, kind in rd_config.UNDERLYING_KINDS.items() if kind == "lrt"]
    assert set(lrts) == {"ezeth", "rseth"}, "config LRT set changed — revisit this test"
    for u in lrts:
        risk = _toxic_ezeth_exploit_risk(u)
        res, _ = _entry(risk, "1000")
        assert res.approved is False, f"{u} approved at $1k"
        assert res.reason == KillReason.TAIL_VETO


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2. NO over-correction — a genuinely-clean book still APPROVES
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _clean_susde_risk() -> UnderlyingRisk:
    return UnderlyingRisk(
        underlying="susde", as_of="2025-01-01", nav_redemption_value=D("1"), market_price=D("1"),
        peg_distance=D("0"), peg_vol_30d=D("0"), redemption_sla_seconds=86400,
        reserve_fund_ratio=D("0.05"), funding_neg_frac_90d=D("0.05"), oracle_kind="chainlink",
        oracle_staleness_seconds=300, nested_protocol_count=1, top_borrower_share=D("0.1"))


def test_clean_stable_carry_still_approves():
    """A genuinely-clean stable-synth carry (structural haircut ~0.015 << cap) still APPROVES at a real
    size — the fix did not just refuse everything."""
    risk = _clean_susde_risk()
    dec = ENG.fair(risk=risk, kind=UnderlyingKind.STABLE_SYNTH, tenor_seconds=86400 * 60,
                   hedge_available=True, position_size_usd=D("100000"),
                   exit_liquidity_usd=D("2e6"), as_of="2025-01-01")
    assert dec.structural_haircut < P.max_structural_haircut
    res, _ = _entry(risk, "100000", exit_liq=D("2e6"), kind=UnderlyingKind.STABLE_SYNTH,
                    trailing_yield=D("0.10"), boros_forward=D("0.12"))
    assert res.approved is True
    assert res.reason == KillReason.NONE
    assert res.approved_size_usd > D("0")


def test_clean_carry_survives_hostile_funding_regime():
    """Even a clean stable book whose 90d-neg-funding fraction is high still APPROVES as a FIXED_CARRY
    (held-to-maturity) book. SHAPE-CORRECT (the wstETH fix): a FIXED_CARRY PT has NO perp/forward-funding
    leg → its funding_flip_haircut is exactly 0, so a hostile funding regime cannot inflate its structural
    haircut at all (the held-to-maturity rate is locked at purchase). Its structural ≈ 0.0153 sits far
    below the cap. (Sustained hostile funding on a funding-BEARING shape is governed by the FUNDING_FLIP
    hysteresis streak, not this veto.)"""
    risk = UnderlyingRisk(
        underlying="susde", as_of="2025-06-01", nav_redemption_value=D("1"), market_price=D("1"),
        peg_distance=D("0"), peg_vol_30d=D("0"), redemption_sla_seconds=86400,
        reserve_fund_ratio=D("0.05"), funding_neg_frac_90d=D("0.30"),  # hostile but sub-streak
        oracle_kind="chainlink", oracle_staleness_seconds=300, nested_protocol_count=1,
        top_borrower_share=D("0.1"))
    # SHAPE-CORRECT: FIXED_CARRY has no funding leg → funding_flip_haircut == 0 regardless of the regime.
    dec = ENG.fair(risk=risk, kind=UnderlyingKind.STABLE_SYNTH, tenor_seconds=86400 * 60,
                   hedge_available=True, position_size_usd=D("100000"),
                   exit_liquidity_usd=D("2e6"), as_of="2025-06-01", shape=TradeShape.FIXED_CARRY)
    assert dec.funding_flip_haircut == D("0"), "FIXED_CARRY (no perp leg) must zero the funding haircut"
    assert dec.structural_haircut < P.max_structural_haircut
    res, _ = _entry(risk, "100000", exit_liq=D("2e6"), kind=UnderlyingKind.STABLE_SYNTH,
                    trailing_yield=D("0.10"), boros_forward=D("0.12"))
    assert res.approved is True, "hostile-but-clean FIXED_CARRY carry must not be over-refused"
    # And fail-CLOSED: WITHOUT a declared shape the funding haircut is KEPT (saturates here) — an
    # undeclared shape never silently drops a real risk.
    dec_no_shape = ENG.fair(risk=risk, kind=UnderlyingKind.STABLE_SYNTH, tenor_seconds=86400 * 60,
                            hedge_available=True, position_size_usd=D("100000"),
                            exit_liquidity_usd=D("2e6"), as_of="2025-06-01")
    assert dec_no_shape.funding_flip_haircut == P.cap_funding, "undeclared shape must KEEP funding (fail-closed)"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. refusal-first ordering preserved — structural veto is FIRST
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_structural_veto_precedes_economics_on_toxic_book():
    """A toxic book with SPECTACULAR economics (35% quote) is refused on the STRUCTURAL veto, never on
    economics — refusal-before-economics holds (economics would have APPROVED the 35% quote)."""
    risk = _toxic_ezeth_exploit_risk()
    res, _ = _entry(risk, "1000")
    assert res.reason == KillReason.TAIL_VETO  # NOT economics, NOT none


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 4. the regenerated PUBLIC decision log has ZERO toxic-LRT approvals
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _load_real_log():
    if not _REAL_LOG.exists():
        return None
    return [json.loads(ln) for ln in _REAL_LOG.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_regenerated_log_has_zero_toxic_lrt_approvals():
    """The committed public decision_log.jsonl must contain NO approved row on any known-toxic LRT
    underlying across the FULL history (the regeneration through the corrected gate flipped them)."""
    rows = _load_real_log()
    if rows is None:
        import pytest
        pytest.skip("canonical decision_log.jsonl absent")
    toxic_approved = [r for r in rows
                      if r.get("approved") and r.get("underlying", "").lower() in TOXIC_LRTS]
    assert toxic_approved == [], f"toxic-LRT approvals in the public log: {toxic_approved}"


def _seq63_style_approved_ezeth_row() -> dict:
    """A synthetic seq=63-style mirror row: an APPROVED ezETH FIXED_CARRY whose STORED decomposition
    is structurally toxic (peg+oracle+protocol sum > max_structural_haircut = 0.06) — i.e. exactly the
    formerly-approved-at-$4,062.50 exploit shape. Regeneration MUST flip it to a tail_veto refusal.

    Hermetic on purpose: the earlier assertion read the live committed decision_log.jsonl for a specific
    historical ezETH 2024-09-01 row, but that log is a runtime-appended, ring-buffered forward mirror
    (the com.spa.rates_desk_paper agent rewrites it) — the historical seq=63 rows age out, so pinning a
    specific live row is stale-test-drift. The BEHAVIOR under test (a seq=63-equivalent toxic ezETH is
    flipped to a lineage-marked refusal by the corrected gate) is exercised deterministically here."""
    return {
        "ts": "2024-09-01T00:00:00Z",
        "as_of": "2024-09-01",
        "underlying": "ezETH",
        "shape": TradeShape.FIXED_CARRY.value,   # no funding leg
        "approved": True,
        "kind": "APPROVAL",
        "reason": "none",
        "approved_size_usd": "4062.50",
        "net_edge": "0.02",
        "proof_hash": "deadbeef" * 8,
        "decomposition": {
            "fair_yield": "0.05",
            "peg_haircut": "0.05",       # peg + oracle + protocol = 0.09 > 0.06 cap
            "oracle_haircut": "0.02",
            "protocol_haircut": "0.02",
            "funding_flip_haircut": "0.03",  # excluded for FIXED_CARRY (no funding leg)
        },
        "detail": {"quoted_rate": "0.07"},
    }


def test_seq63_equivalent_ezeth_is_refused_by_regeneration():
    """The specific red-team exploit row (ezETH, as_of 2024-09-01, formerly APPROVED at $4,062.50) is
    flipped to a lineage-marked tail_veto REFUSAL when run through the corrected regeneration gate."""
    row = _seq63_style_approved_ezeth_row()
    # sanity: the raw row IS an approved toxic ezETH (the exploit precondition).
    assert row["approved"] is True and row["underlying"].lower() == "ezeth"

    out = proof_chain.regenerate_log([row])
    ez = [r for r in out if r.get("underlying", "").lower() == "ezeth"
          and r.get("as_of") == "2024-09-01"]
    assert ez, "expected the ezETH 2024-09-01 row in the regenerated output"
    assert all(not r.get("approved") for r in ez), "the ezETH 2024-09-01 row is still approved"
    # carries the regeneration lineage marker (the flipped seq=63 row)
    flipped = [r for r in ez if "regenerated_from_proof_hash" in (r.get("detail") or {})]
    assert flipped, "the flipped seq=63 ezETH row is missing its regeneration marker"
    assert flipped[0]["reason"] == "tail_veto"
    assert flipped[0]["approved_size_usd"] == "0"


def test_canonical_log_has_no_toxic_ezeth_approval_if_present():
    """Guard on the LIVE committed log (runtime-appended): IF an ezETH 2024-09-01 row is present it must
    be a refusal. Skips when absent (the forward mirror has rotated past it) — the flip behavior itself is
    proven hermetically in test_seq63_equivalent_ezeth_is_refused_by_regeneration."""
    rows = _load_real_log()
    if rows is None:
        import pytest
        pytest.skip("canonical decision_log.jsonl absent")
    ez = [r for r in rows if r.get("underlying", "").lower() == "ezeth"
          and r.get("as_of") == "2024-09-01"]
    if not ez:
        import pytest
        pytest.skip("no ezETH 2024-09-01 row in the current forward mirror (rotated) — flip proven hermetically")
    assert all(not r.get("approved") for r in ez), "an ezETH 2024-09-01 row is still approved in the live log"


def test_regeneration_is_deterministic_and_idempotent(tmp_path):
    """Regenerating the corrected log twice yields byte-identical output (PURE), and re-running it on an
    already-corrected log is a no-op (0 flips, still 0 toxic approvals)."""
    rows = _load_real_log()
    if rows is None:
        import pytest
        pytest.skip("canonical decision_log.jsonl absent")
    out1 = proof_chain.regenerate_log(rows)
    out2 = proof_chain.regenerate_log(rows)
    assert out1 == out2, "regeneration is not deterministic"
    # second pass over the already-corrected output flips nothing more
    out3 = proof_chain.regenerate_log(out1)
    n_flipped_again = sum(
        1 for r in out1 if r.get("approved")
        and proof_chain.corrected_decision_body(r).get("approved") is False)
    assert n_flipped_again == 0
    toxic_left = [r for r in out3 if r.get("approved")
                  and r.get("underlying", "").lower() in TOXIC_LRTS]
    assert toxic_left == []


def test_regenerate_preserves_clean_decision_bodies():
    """Regeneration NEVER alters a clean (structurally-safe) decision body — only toxic approvals flip.
    Verified on a hermetic 3-row set (clean approval, clean refusal, toxic approval)."""
    clean_appr = {
        "ts": "2025-01-01T00:00:00+00:00", "kind": "ENTRY", "approved": True, "reason": "none",
        "as_of": "2025-01-01", "underlying": "susde", "shape": "fixed_carry", "net_edge": "0.05",
        "approved_size_usd": "100000",
        "decomposition": {"underlying": "susde", "as_of": "2025-01-01", "baseline": "0.10",
                          "peg_haircut": "0.0", "funding_flip_haircut": "0.0",
                          "oracle_haircut": "0.003", "liquidity_haircut": "0.003",
                          "protocol_haircut": "0.012", "structural_haircut": "0.015",
                          "total_haircut": "0.018", "fair_yield": "0.082"},
        "detail": {"quoted_rate": "0.12"}, "proof_hash": "clean1"}
    clean_ref = dict(clean_appr, kind="REFUSAL", approved=False, reason="economics",
                     approved_size_usd="0", proof_hash="clean2")
    toxic_appr = {
        "ts": "2024-09-01T00:00:00+00:00", "kind": "ENTRY", "approved": True, "reason": "none",
        "as_of": "2024-09-01", "underlying": "ezeth", "shape": "fixed_carry", "net_edge": "0.42",
        "approved_size_usd": "4062.5",
        "decomposition": {"underlying": "ezeth", "as_of": "2024-09-01", "baseline": "0.029",
                          "peg_haircut": "0.064", "funding_flip_haircut": "0.0",
                          "oracle_haircut": "0.0067", "liquidity_haircut": "0.015",
                          "protocol_haircut": "0.026", "structural_haircut": "0.0967",
                          "total_haircut": "0.1117", "fair_yield": "-0.0827"},
        "detail": {"quoted_rate": "0.35"}, "proof_hash": "toxic1"}

    assert proof_chain.corrected_decision_body(clean_appr)["approved"] is True
    assert proof_chain.corrected_decision_body(clean_appr) == proof_chain._payload_of(clean_appr)
    assert proof_chain.corrected_decision_body(clean_ref) == proof_chain._payload_of(clean_ref)
    flipped = proof_chain.corrected_decision_body(toxic_appr)
    assert flipped["approved"] is False
    assert flipped["reason"] == "tail_veto"
    assert flipped["approved_size_usd"] == "0"
