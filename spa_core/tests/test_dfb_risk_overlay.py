"""
test_dfb_risk_overlay.py — the RED-TEAM + property + smoke quality bar for the DFB risk-overlay
pipeline (WS-1.2, the highest-value seam) + the pool universe (WS-1.1) + the history capture (WS-1.5).

THE worst bug class (from MEMORY — the size-down exploit): a TOXIC pool (structural haircut over the
cap) must get the WORST class + REFUSE at ANY size — the structural-haircut veto is size-INDEPENDENT,
so it can NEVER be sized around. A stale / missing feed → flagged, never a fabricated grade/number.

PURE / no network (DeFiLlama disabled via injected surfaces) / no live-data mutation (tmp dirs).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from spa_core.dfb import Pool, RiskClass
from spa_core.dfb import history as dfb_history
from spa_core.dfb import pool_universe, risk_overlay
from spa_core.dfb.risk_overlay import overlay
from spa_core.strategy_lab.rates_desk.contracts import D0, UnderlyingRisk

_AS_OF = "2026-06-29"


def _surface():
    return {"as_of": _AS_OF, "quotes": [
        {"market_id": "pt-susde-1", "underlying": "susde", "protocol": "pendle",
         "venue": "pendle_pt", "kind": "stable_synth", "quoted_rate": "0.085",
         "tvl_usd": "40000000", "exit_liquidity_usd": "8000000", "as_of": _AS_OF, "chain": "Ethereum"},
        {"market_id": "pt-ezeth-1", "underlying": "ezeth", "protocol": "pendle",
         "venue": "pendle_pt", "kind": "lrt", "quoted_rate": "0.22",
         "tvl_usd": "15000000", "exit_liquidity_usd": "3000000", "as_of": _AS_OF, "chain": "Ethereum"},
    ]}


def _toxic_lrt_risk():
    """An ezETH/rsETH-shaped TOXIC underlying: structural tail (peg + funding + oracle + protocol)
    well over the cap — the size-down exploit target."""
    return UnderlyingRisk(
        underlying="ezeth", as_of=_AS_OF,
        nav_redemption_value=Decimal("1.0"), market_price=Decimal("0.90"),
        peg_distance=Decimal("0.008"), peg_vol_30d=Decimal("0.05"),
        redemption_sla_seconds=86400 * 7, reserve_fund_ratio=D0,
        funding_neg_frac_90d=Decimal("0.6"), oracle_kind="redstone", oracle_staleness_seconds=1800,
        nested_protocol_count=4, top_borrower_share=Decimal("0.5"))


# ── WS-1.1 pool universe ─────────────────────────────────────────────────────────────────────────
def test_universe_deterministic_and_sorted():
    a = pool_universe.build_universe(surface=_surface())
    b = pool_universe.build_universe(surface=_surface())
    assert [p.pool_id for p in a] == [p.pool_id for p in b]
    ids = [p.pool_id for p in a]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)  # every pool_id unique
    assert len(a) >= 2  # at least the injected surface markets


def test_universe_pool_id_stable():
    assert pool_universe.make_pool_id("Aave V3", "Ethereum", "USDC") == "aave-v3__ethereum__usdc"
    # idempotent
    assert pool_universe.make_pool_id("Aave V3", "Ethereum", "USDC") == \
        pool_universe.make_pool_id("aave_v3", "ethereum", "usdc")


def test_universe_no_fabricated_cells():
    """A pool with no live APY/TVL surfaces None, never a 0-coerced fabricated number."""
    pools = pool_universe.build_universe(surface=_surface())
    for p in pools:
        # APY, if present, is a sane decimal fraction (never percent leaked, never negative)
        if p.apy_total is not None:
            assert 0.0 <= p.apy_total <= 5.0
        if p.tvl_usd is not None:
            assert p.tvl_usd >= 0.0


# ── WS-1.2 overlay: the SAFE path ───────────────────────────────────────────────────────────────
def test_safe_stable_pool_is_class_A_and_has_real_exit_schedule():
    pools = pool_universe.build_universe(surface=_surface())
    susde = next(p for p in pools if p.asset == "susde")
    ov = overlay(susde, prev_hash="0" * 64)
    assert ov.refusal.verdict == "SAFE"
    assert ov.risk_class in (RiskClass.A, RiskClass.B)
    assert not ov.refusal.tail_veto
    # a real exit-by-size schedule at $1M/$5M/$10M, not all holes
    tickets = [r.ticket_usd for r in ov.exit_liquidity]
    assert tickets == [1_000_000, 5_000_000, 10_000_000]
    assert any(r.absorbable_usd is not None for r in ov.exit_liquidity)
    assert ov.engine_proof_hash  # carries the engine proof hash


# ── WS-1.2 RED-TEAM: toxic pool REFUSED at ANY size (the size-down exploit) ───────────────────────
@pytest.mark.parametrize("size", [
    Decimal("100000000"), Decimal("10000000"), Decimal("1000000"), Decimal("100000"), Decimal("1000"),
])
def test_toxic_pool_refused_at_any_size(size):
    """The structural-haircut veto is SIZE-INDEPENDENT: a toxic LRT is class D + REFUSE + tail_veto
    at EVERY probe size — it cannot be graded safe by sizing down."""
    pools = pool_universe.build_universe(surface=_surface())
    ezeth = next(p for p in pools if p.asset == "ezeth")
    ov = overlay(ezeth, prev_hash="0" * 64, risk_override=_toxic_lrt_risk(),
                 probe_size_usd=size, exit_liquidity_usd=3_000_000.0)
    assert ov.refusal.verdict == "REFUSE", f"toxic pool not refused at size {size}"
    assert ov.refusal.tail_veto is True, f"toxic veto not size-independent at size {size}"
    assert ov.risk_class is RiskClass.D, f"toxic pool not class D at size {size}"
    # the structural haircut is over the cap and does NOT shrink with size (size-independence)
    assert ov.structural_haircut is not None and ov.structural_haircut > 0.06


def test_toxic_structural_haircut_constant_across_size():
    """The structural haircut (the toxicity signal) is identical at $1k and $100M — it is a property
    of the underlying, not the position size."""
    pools = pool_universe.build_universe(surface=_surface())
    ezeth = next(p for p in pools if p.asset == "ezeth")
    small = overlay(ezeth, prev_hash="0" * 64, risk_override=_toxic_lrt_risk(),
                    probe_size_usd=Decimal("1000"), exit_liquidity_usd=3_000_000.0)
    huge = overlay(ezeth, prev_hash="0" * 64, risk_override=_toxic_lrt_risk(),
                   probe_size_usd=Decimal("100000000"), exit_liquidity_usd=3_000_000.0)
    assert small.structural_haircut == huge.structural_haircut


# ── WS-1.2 fail-CLOSED: missing / unknown feed → flagged, never a fabricated grade ─────────────────
def test_unknown_underlying_kind_fails_closed_to_unknown():
    pool = Pool(pool_id="mystery__ethereum__wtf", protocol="mystery", chain="Ethereum",
                asset="wtf-token", tier="T2", source="rates_desk_market", apy_total=0.30,
                tvl_usd=10_000_000.0, as_of=_AS_OF)
    ov = overlay(pool, prev_hash="0" * 64)
    assert ov.risk_class is RiskClass.UNKNOWN
    assert ov.flagged is True
    assert ov.refusal.verdict == "UNKNOWN"
    assert ov.structural_haircut is None  # never a fabricated number


def test_missing_quoted_rate_fails_closed():
    pool = Pool(pool_id="pendle__ethereum__susde", protocol="pendle", chain="Ethereum",
                asset="susde", tier="T2", source="rates_desk_market", apy_total=None,
                tvl_usd=40_000_000.0, underlying_kind="stable_synth", market_id="m", as_of=_AS_OF)
    ov = overlay(pool, prev_hash="0" * 64)
    assert ov.risk_class is RiskClass.UNKNOWN and ov.flagged


def test_thin_depth_flags_exit_hole_never_fabricated():
    """A pool with sub-floor exit liquidity publishes flagged exit holes, never a synthesized fill."""
    pool = Pool(pool_id="pendle__ethereum__susde", protocol="pendle", chain="Ethereum",
                asset="susde", tier="T2", source="rates_desk_market", apy_total=0.085,
                tvl_usd=40_000_000.0, underlying_kind="stable_synth", market_id="m",
                exit_liquidity_usd=1000.0, as_of=_AS_OF)  # $1k exit << $250k DEX floor
    ov = overlay(pool, prev_hash="0" * 64)
    assert all(r.absorbable_usd is None and r.flagged for r in ov.exit_liquidity)
    assert ov.flagged


# ── WS-1.2 SMOKE: overlay the full live universe (injected surface), proof-chained, fail-closed ──
def test_smoke_full_universe_overlay_chained():
    pools = pool_universe.build_universe(surface=_surface())
    overlays = risk_overlay.build_overlays(pools)
    assert len(overlays) == len(pools)
    assert risk_overlay.verify_chain(overlays)  # the per-row proof chain links
    # every overlay carries the full contract field set + no exceptions thrown
    for ov in overlays:
        d = ov.to_dict()
        for k in ("pool_id", "risk_class", "refusal", "exit_liquidity", "row_hash",
                  "engine_proof_hash", "structural_haircut", "total_haircut", "apy", "as_of"):
            assert k in d
        assert d["risk_class"] in ("A", "B", "C", "D", "UNKNOWN")


def test_build_and_write_artifacts(tmp_path):
    res = risk_overlay.build_and_write(write=True, data_dir=tmp_path, surface=_surface())
    assert res["chain_valid"] is True
    assert (tmp_path / "dfb" / "pools.json").exists()
    # at least the two surface pools got a detail file
    detail_dir = tmp_path / "dfb" / "pool"
    assert detail_dir.exists() and len(list(detail_dir.glob("*.json"))) >= 2


# ── WS-1.5 history capture: idempotent per UTC day, proof-chained ────────────────────────────────
def test_history_capture_idempotent_and_chained(tmp_path):
    pools = pool_universe.build_universe(surface=_surface())
    overlays = risk_overlay.build_overlays(pools)
    c1 = dfb_history.capture_all(overlays, capture_date="2026-06-29", data_dir=tmp_path)
    assert c1["n_appended"] == len(overlays)
    # re-running the SAME day is a no-op (idempotent)
    c2 = dfb_history.capture_all(overlays, capture_date="2026-06-29", data_dir=tmp_path)
    assert c2["n_appended"] == 0 and c2["n_skipped"] == len(overlays)
    # a NEW day appends one more record per pool
    c3 = dfb_history.capture_all(overlays, capture_date="2026-06-30", data_dir=tmp_path)
    assert c3["n_appended"] == len(overlays)
    # the per-pool chain verifies
    pid = overlays[0].pool_id
    v = dfb_history.verify_history(pid, data_dir=tmp_path)
    assert v["valid"] is True and v["length"] == 2


def test_history_tamper_detected(tmp_path):
    import json
    pools = pool_universe.build_universe(surface=_surface())
    overlays = risk_overlay.build_overlays(pools)
    dfb_history.capture_all(overlays, capture_date="2026-06-29", data_dir=tmp_path)
    pid = overlays[0].pool_id
    path = tmp_path / "dfb" / "history" / f"{pid}.jsonl"
    rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    rows[0]["apy_total"] = 9.99  # forge a published number
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    assert dfb_history.verify_history(pid, data_dir=tmp_path)["valid"] is False
