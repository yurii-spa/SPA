"""
spa_core/dfb/risk_overlay.py — WS-1.2 🏆 THE highest-value seam: the per-pool RISK-OVERLAY pipeline.

`overlay(pool) -> PoolOverlay` builds the risk-first verdict object for ONE pool — the single thing
the whole DFB product is downstream of — by CALLING the SPA engine and PRESENTING its outputs. It
defines NO risk math of its own (the NO-FORK rule; AST-asserted by test_dfb_no_fork.py):

  • refusal verdict + reason + tail_veto        → rate_policy.evaluate_entry  (the refusal-first gate)
  • structural_haircut / total_haircut          → the GateResult.decomposition (fair_value_engine)
  • exit-liquidity-by-size @ $1M/$5M/$10M        → depth_at_size.compute_market_depth_row
  • A/B/C/D risk_class                            → classify(): a deterministic PRESENTATION map of the
                                                    engine's OWN verdict + structural haircut + tier
  • engine_proof_hash                             → GateResult.proof_hash() (byte-identical to the desk)
  • row_hash / prev_hash                          → the proof_chain hash pattern (sha256, canonical JSON)

byte-IDENTICAL to the desk: an `overlay()` built on the SAME (market_id, as_of) inputs the desk
evaluates produces the SAME GateResult — therefore the SAME engine_proof_hash. The pool-shaped
entrypoint (mapping a Pool → the engine's Opportunity/UnderlyingRisk inputs) is the ONLY new code;
all judgment is the engine's.

fail-CLOSED (the load-bearing honesty rule): a pool whose UnderlyingKind cannot be resolved, or whose
APY/TVL is missing, is graded `UNKNOWN` + `flagged`, NEVER silently graded safe and NEVER given a
fabricated number. A thin/stale depth → a flagged exit-liquidity hole (never a synthesized fill).

THE RED-TEAM INVARIANT (the worst bug class — the size-down exploit): a TOXIC pool (structural
haircut over the cap) is REFUSED on the SIZE-INDEPENDENT structural veto, so it is class D + REFUSE +
tail_veto at ANY requested size. This is the engine's `evaluate_entry` veto (1a) — DFB just surfaces
it. `overlay()` therefore cannot be made to grade a toxic pool safe by sizing the probe down (the
probe size only moves the size-dependent liquidity haircut, never the toxicity verdict).

stdlib only · deterministic (`as_of` = the DATA date) · LLM-FORBIDDEN · READ-ONLY · advisory.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import List, Optional, Tuple

from spa_core.dfb import (
    RISK_CLASS_LABELS,
    ExitLiquidityRow,
    Pool,
    PoolOverlay,
    RefusalVerdict,
    RiskClass,
)
from spa_core.strategy_lab.rates_desk import config as rd_config
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    GateResult,
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
from spa_core.strategy_lab.rates_desk.depth_at_size import (
    DEPTH_GENESIS_PREV,
    DEPTH_TICKETS_USD,
    compute_market_depth_row,
)
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry

# The per-row proof chain genesis (mirrors the engine's exit-NAV / depth chain genesis).
DFB_GENESIS_PREV = "0" * 64

# The probe size used to ask the gate "would you enter this pool?". DELIBERATELY LARGE ($1M) so the
# size cap binds against real exit liquidity — but the toxicity verdict is SIZE-INDEPENDENT (the
# structural veto), so the grade does not depend on this choice (the red-team asserts exactly that).
DEFAULT_PROBE_SIZE_USD = Decimal("1000000")

# A long but finite synthetic tenor for the PT-shaped probe (well clear of the maturity buffer).
_PROBE_TENOR_SECONDS = 86400 * 180


def _d(x) -> Optional[Decimal]:
    """Coerce to Decimal, None on malformed (fail-CLOSED)."""
    if x is None:
        return None
    try:
        d = x if isinstance(x, Decimal) else Decimal(str(x))
    except Exception:  # noqa: BLE001
        return None
    if d.is_nan() or d.is_infinite():
        return None
    return d


def _resolve_kind(pool: Pool) -> Optional[UnderlyingKind]:
    """Resolve the UnderlyingKind for the pool's asset — the engine input that drives the baseline.

    Priority: (a) the pool's own carried kind (from the rates-desk surface), (b) the rates-desk config
    map. fail-CLOSED: an asset the config does not know → None (the overlay then grades UNKNOWN, never
    guessing a kind, because a wrong kind would pick the wrong baseline and could under-state risk)."""
    if pool.underlying_kind:
        try:
            return UnderlyingKind(pool.underlying_kind)
        except (ValueError, KeyError):
            pass
    try:
        return rd_config.underlying_kind(pool.asset)
    except ValueError:
        return None


def _build_risk(pool: Pool, kind: UnderlyingKind, as_of: str) -> Optional[UnderlyingRisk]:
    """Build the engine's UnderlyingRisk for the pool — at-par for stables, fail-CLOSED for ETH kinds
    whose live peg series we do not carry here (the overlay grades those UNKNOWN rather than fabricate
    a benign peg=0). Uses ONLY documented rates-desk config constants (oracle / sla / nesting /
    concentration) — the SAME ones the desk's UnderlyingRiskFeed uses, so the inputs match the desk."""
    u = pool.asset.lower()
    if kind in (UnderlyingKind.STABLE_RWA, UnderlyingKind.STABLE_SYNTH):
        nav, mkt, peg, vol = Decimal("1"), Decimal("1"), D0, D0
        # synthetic-dollar carry without a live per-underlying peg series uses the config funding
        # signal only; a benign funding_neg_frac is documented per the desk's own default.
        funding_neg = _d(rd_config.reserve_fund_ratio(u))  # placeholder share; replaced below
    elif kind in (UnderlyingKind.LST, UnderlyingKind.LRT):
        # We do NOT carry the live X/ETH peg series in the DFB overlay layer. fail-CLOSED: rather than
        # fabricate peg=0 for an LRT (which would HIDE the toxicity), we require the caller to inject a
        # peg surface (see overlay(risk_override=...)); without it the ETH-kind pool grades UNKNOWN.
        return None
    else:
        return None
    # funding_neg_frac_90d: the desk's systemic signal. We do not pull the 5-venue funding feed in the
    # overlay layer (that is the desk's paper-tick job); a documented conservative default keeps the
    # stable path honest (stables bear no perp leg under FIXED_CARRY → funding term is zeroed anyway).
    return UnderlyingRisk(
        underlying=u,
        as_of=as_of,
        nav_redemption_value=nav,
        market_price=mkt,
        peg_distance=peg,
        peg_vol_30d=vol,
        redemption_sla_seconds=rd_config.redemption_sla_seconds(u),
        reserve_fund_ratio=_d(rd_config.reserve_fund_ratio(u)) or D0,
        funding_neg_frac_90d=D0,
        oracle_kind=rd_config.oracle_kind(u),
        oracle_staleness_seconds=rd_config.oracle_staleness_seconds(u),
        nested_protocol_count=rd_config.nested_protocol_count(u),
        top_borrower_share=_d(rd_config.top_borrower_share(u)) or D0,
    )


def _exit_rows_from_depth(
    pool: Pool, exit_liquidity_usd: Optional[float], tvl_usd: Optional[float],
    as_of: str, params: RatePolicyParams,
) -> Tuple[List[ExitLiquidityRow], bool]:
    """Exit-liquidity-by-size @ $1M/$5M/$10M via the ENGINE's depth_at_size.compute_market_depth_row.
    DFB computes none of these numbers. fail-CLOSED: thin/absent depth → flagged holes. Returns
    (rows, any_flagged)."""
    depth_row = compute_market_depth_row(
        market_id=pool.market_id or pool.pool_id,
        underlying=pool.asset,
        venue=pool.protocol,
        tvl_usd=tvl_usd,
        exit_liquidity_usd=exit_liquidity_usd,
        market_as_of=as_of,
        surface_as_of=as_of,
        params=params,
        prev_hash=DEPTH_GENESIS_PREV,
    )
    rows: List[ExitLiquidityRow] = []
    for t in depth_row.get("tickets", []):
        rows.append(ExitLiquidityRow(
            ticket_usd=int(t.get("ticket_usd")),
            absorbable_usd=t.get("absorbable_usd"),
            dex_exit_frac=t.get("exit_frac"),
            flagged=bool(t.get("absorbable_usd") is None),
        ))
    return rows, bool(depth_row.get("flagged"))


def classify(result: GateResult, params: RatePolicyParams) -> RiskClass:
    """The A/B/C/D PRESENTATION map — composed ENTIRELY from the engine's OWN verdict outputs (the
    GateResult: approved / reason / decomposition). DFB invents NO score. Deterministic.

      • REFUSED on TAIL_VETO (structural toxicity)         → D  (incentive — refused at ANY size)
      • REFUSED on any peg/oracle/stable/funding structural→ D  (a structural tail veto)
      • REFUSED on economics / size / liquidity            → C  (risk-comp / unexitable at size)
      • APPROVED, harvestable net edge over fair value      → A  (alpha)
      • APPROVED, net edge ~ at/under the floor (no edge)   → B  (beta-floor — own-the-floor)

    The D-vs-C split is the load-bearing one: a STRUCTURAL refusal (the size-independent tail) is the
    worst class and CANNOT be sized around (that is the engine's veto 1a). We read it off the engine's
    KillReason — never re-derive toxicity here."""
    structural_reasons = {
        KillReason.TAIL_VETO,        # the structural toxicity veto (1a) OR total-haircut veto (1b)
        KillReason.UNDERLYING_DEPEG,
        KillReason.ORACLE_STALE,
        KillReason.STABLE_DEPEG,
        KillReason.FUNDING_FLIP,
    }
    if not result.approved:
        if result.reason in structural_reasons:
            return RiskClass.D
        return RiskClass.C  # ECONOMICS / SIZE_FLOOR / hold-only kills
    # approved → A vs B on whether the net edge meaningfully clears the floor (own-the-floor = B).
    # net_edge is the engine's fair-cleared, cost-net edge. Edge above the RWA floor → alpha (A).
    if result.net_edge is not None and result.net_edge > params.rwa_floor:
        return RiskClass.A
    return RiskClass.B


def _row_hash(body: dict, prev_hash: str) -> str:
    """sha256 over the canonical sorted-JSON of the published row body + prev_hash — the per-row proof
    chain link (the proof_chain pattern). Reproducible by anyone from the published row."""
    blob = json.dumps({"body": body, "prev_hash": prev_hash}, sort_keys=True,
                       separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _canonical_body(ov: PoolOverlay) -> dict:
    """The signed body = the full published row (to_dict) MINUS the chain-linkage envelope
    (prev_hash / row_hash). The SINGLE definition used by both the writer and the verifier, so a
    third party reproduces row_hash from the published row exactly."""
    return {k: v for k, v in ov.to_dict().items() if k not in ("prev_hash", "row_hash")}


def _finalize(ov: PoolOverlay) -> PoolOverlay:
    """Stamp the row_hash over the overlay's OWN canonical body (computed from to_dict, so verify and
    write agree to the byte). Returns a new frozen overlay with row_hash set."""
    import dataclasses
    rh = _row_hash(_canonical_body(ov), ov.prev_hash)
    return dataclasses.replace(ov, row_hash=rh)


def _flagged_overlay(pool: Pool, as_of: str, prev_hash: str, reason: str,
                     params: RatePolicyParams) -> PoolOverlay:
    """A fully fail-CLOSED overlay row: UNKNOWN grade, REFUSE-side UNKNOWN verdict, exit-liquidity
    holes — NEVER a fabricated grade/number. Still proof-chained (the hole is published, verifiable)."""
    exit_rows, _ = _exit_rows_from_depth(pool, None, pool.tvl_usd, as_of, params)
    return _finalize(PoolOverlay(
        pool_id=pool.pool_id, protocol=pool.protocol, chain=pool.chain, asset=pool.asset,
        tier=pool.tier,
        apy={"total": pool.apy_total, "base": pool.apy_base, "reward": pool.apy_reward},
        tvl_usd=pool.tvl_usd, risk_class=RiskClass.UNKNOWN,
        risk_class_label=RISK_CLASS_LABELS[RiskClass.UNKNOWN],
        structural_haircut=None, total_haircut=None, exit_liquidity=exit_rows,
        refusal=RefusalVerdict(verdict="UNKNOWN", reason=reason, tail_veto=False),
        as_of=as_of, data_source="none", feed_coverage="none", flagged=True, flag_reason=reason,
        engine_proof_hash="", prev_hash=prev_hash, row_hash="",
    ))


def engine_inputs(
    pool: Pool,
    kind: UnderlyingKind,
    risk: UnderlyingRisk,
    as_of: str,
    probe_size_usd: Decimal = DEFAULT_PROBE_SIZE_USD,
    exit_liquidity_usd: Optional[float] = None,
):
    """Build the EXACT kwargs the SPA engine's `evaluate_entry` is called with for this pool. The
    SINGLE place the pool→engine mapping lives — `overlay()` calls this, and `test_dfb_no_fork.py`
    calls this to reconstruct the desk's GateResult and assert byte-identity (so DFB's verdict ==
    the desk's verdict on the same inputs, to the byte). NO risk math — only input shaping.

    exit liquidity (the §9 one-tick exit capacity the depth engine consumes): injected → else the
    pool's own carried surface `exit_liquidity_usd` → else the contemporaneous pool depth from TVL
    (the SAME `rd_config.contemporaneous_pool_depth_usd` the desk's feeds use). The depth engine then
    applies its OWN conservative constant-product fraction on top — DFB adds no slippage math.
    fail-CLOSED: no TVL and no carried exit liquidity → 0 → the gate's liquidity haircut maxes out."""
    exitl = exit_liquidity_usd
    if exitl is None and pool.exit_liquidity_usd is not None:
        exitl = pool.exit_liquidity_usd
    if exitl is None and pool.tvl_usd is not None:
        exitl = float(rd_config.contemporaneous_pool_depth_usd(pool.tvl_usd))
    exit_l_dec = _d(exitl) or D0
    quote = RateQuote(
        underlying=pool.asset.lower(),
        kind=kind,
        venue=RateVenue.PENDLE_PT,
        protocol=pool.protocol,
        market_id=pool.market_id or pool.pool_id,
        tenor_seconds=_PROBE_TENOR_SECONDS,
        as_of=as_of,
        quoted_rate=_d(pool.apy_total) or D0,
        tvl_usd=_d(pool.tvl_usd) or D0,
        exit_liquidity_usd=exit_l_dec,
        hedge_available=False,
    )
    opp = Opportunity(quote=quote, shape=TradeShape.FIXED_CARRY, requested_size_usd=probe_size_usd)
    return {
        "opp": opp,
        "risk": risk,
        "debt_asset_price": Decimal("1"),  # the quote stable at par (overlay grades the carry token)
        "exit_liquidity": exit_l_dec,
        "state": KillState(),
        "_exitl_float": exitl,
    }


def overlay(
    pool: Pool,
    *,
    prev_hash: str = DFB_GENESIS_PREV,
    params: Optional[RatePolicyParams] = None,
    probe_size_usd: Decimal = DEFAULT_PROBE_SIZE_USD,
    risk_override: Optional[UnderlyingRisk] = None,
    exit_liquidity_usd: Optional[float] = None,
) -> PoolOverlay:
    """Build the shared-contract PoolOverlay for ONE pool by CALLING the SPA engine. The seam.

    `risk_override` lets a caller inject an engine UnderlyingRisk (e.g. a live LST/LRT peg surface, or
    a red-team toxic surface) — without it, ETH-kind pools fail-CLOSED to UNKNOWN (we never fabricate
    a peg). `exit_liquidity_usd` injects the §9 one-tick exit capacity (else derived from TVL × the
    impact band, the same conservative proxy the desk uses); thin → a flagged hole.

    Deterministic / fail-CLOSED. Same (pool, as_of, inputs) → byte-identical overlay (incl. hashes)."""
    p = params or RatePolicyParams()
    as_of = pool.as_of or ""
    if not as_of:
        # fail-CLOSED: an undated pool cannot be graded against a contemporaneous surface.
        return _flagged_overlay(pool, as_of or "unknown", prev_hash, "missing_as_of", p)

    kind = _resolve_kind(pool)
    if kind is None:
        return _flagged_overlay(pool, as_of, prev_hash, "unresolved_underlying_kind", p)

    risk = risk_override if risk_override is not None else _build_risk(pool, kind, as_of)
    if risk is None:
        return _flagged_overlay(pool, as_of, prev_hash, "insufficient_risk_surface", p)

    quoted = _d(pool.apy_total)
    if quoted is None:
        return _flagged_overlay(pool, as_of, prev_hash, "missing_quoted_rate", p)

    inputs = engine_inputs(pool, kind, risk, as_of, probe_size_usd, exit_liquidity_usd)
    exit_l_dec = inputs["exit_liquidity"]
    exitl = inputs["_exitl_float"]

    # ── THE ENGINE CALL — the refusal-first gate (no DFB risk math) ──
    result, _state = evaluate_entry(
        opp=inputs["opp"], risk=inputs["risk"], debt_asset_price=inputs["debt_asset_price"],
        exit_liquidity=inputs["exit_liquidity"], params=p, state=inputs["state"],
    )

    decomp = result.decomposition
    structural = float(decomp.structural_haircut)
    total = float(decomp.total_haircut)
    rc = classify(result, p)
    tail_veto = (not result.approved) and (result.reason == KillReason.TAIL_VETO)
    verdict = "SAFE" if result.approved else "REFUSE"

    exit_rows, exit_flagged = _exit_rows_from_depth(pool, exitl, pool.tvl_usd, as_of, p)

    feed_coverage = "full" if (pool.tvl_usd is not None and exitl is not None) else "partial"
    flagged = exit_flagged or feed_coverage != "full"
    flag_reason = "insufficient_contemporaneous_depth" if exit_flagged else (
        "partial_feed_coverage" if flagged else None)

    return _finalize(PoolOverlay(
        pool_id=pool.pool_id, protocol=pool.protocol, chain=pool.chain, asset=pool.asset,
        tier=pool.tier,
        apy={"total": pool.apy_total, "base": pool.apy_base, "reward": pool.apy_reward},
        tvl_usd=pool.tvl_usd, risk_class=rc, risk_class_label=RISK_CLASS_LABELS[rc],
        structural_haircut=round(structural, 8), total_haircut=round(total, 8),
        exit_liquidity=exit_rows,
        refusal=RefusalVerdict(verdict=verdict, reason=result.reason.value, tail_veto=tail_veto),
        as_of=as_of, data_source="live", feed_coverage=feed_coverage,
        flagged=flagged, flag_reason=flag_reason,
        engine_proof_hash=result.proof_hash(), prev_hash=prev_hash, row_hash="",
    ))


def build_overlays(pools, params: Optional[RatePolicyParams] = None) -> List[PoolOverlay]:
    """Overlay EVERY pool, proof-CHAINED (each row's prev_hash = the previous row's row_hash; genesis
    '0'*64). Deterministic order = the universe order. Same inputs → byte-identical chain."""
    p = params or RatePolicyParams()
    out: List[PoolOverlay] = []
    prev = DFB_GENESIS_PREV
    for pool in pools:
        ov = overlay(pool, prev_hash=prev, params=p)
        out.append(ov)
        prev = ov.row_hash
    return out


def verify_chain(overlays: List[PoolOverlay]) -> bool:
    """Verify the per-row proof chain: each row's prev_hash links the previous row's row_hash, and
    each row_hash recomputes from the published body. fail-CLOSED. (genesis '0'*64.)"""
    prev = DFB_GENESIS_PREV
    for ov in overlays:
        if ov.prev_hash != prev:
            return False
        if _row_hash(_canonical_body(ov), ov.prev_hash) != ov.row_hash:
            return False
        prev = ov.row_hash
    return True


# ── writer — data/dfb/pools.json (list) + data/dfb/pool/<pool_id>.json (detail) ─────────────────────
def build_and_write(
    *, write: bool = True, data_dir=None, params: Optional[RatePolicyParams] = None, surface=None,
) -> dict:
    """Build the universe, overlay every pool (proof-chained), and atomically write the shared-contract
    artifacts: data/dfb/pools.json (the screener list) + data/dfb/pool/<pool_id>.json (per-pool detail).
    READ-ONLY everywhere except data/dfb/. Deterministic; same inputs → byte-identical files."""
    import datetime
    from pathlib import Path

    from spa_core.dfb import pool_universe
    from spa_core.strategy_lab.rates_desk import _io

    p = params or RatePolicyParams()
    root = Path(data_dir) if data_dir is not None else (
        Path(__file__).resolve().parents[2] / "data")
    dfb_dir = root / "dfb"
    pool_dir = dfb_dir / "pool"

    pools = pool_universe.build_universe(surface=surface)
    overlays = build_overlays(pools, p)
    rows = [ov.to_dict() for ov in overlays]
    as_of = next((r["as_of"] for r in rows if r.get("as_of")), None)

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "schema": "dfb_pool_overlay_v1",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "no_fork": "risk math imported from spa_core.strategy_lab.rates_desk + spa_core.risk (not copied)",
        "as_of": as_of,
        "tickets_usd": [int(t) for t in DEPTH_TICKETS_USD],
        "n_pools": len(rows),
        "n_flagged": sum(1 for r in rows if r["flagged"]),
        "n_refused": sum(1 for r in rows if r["refusal"]["verdict"] == "REFUSE"),
        "chain_valid": verify_chain(overlays),
        "pools": rows,
        "disclaimer": ("Each pool's risk class / refusal / exit-liquidity-by-size is the SPA risk "
                       "engine's OWN deterministic verdict (imported, not forked) — byte-identical to "
                       "the desk. Holes are published (flagged), never filled with a fabricated grade "
                       "or number. Advisory — moves no capital, never touches the go-live track."),
    }
    if write:
        _io.atomic_write_json(dfb_dir / "pools.json", result, indent=1, default=str)
        for r in rows:
            _io.atomic_write_json(pool_dir / f"{r['pool_id']}.json", r, indent=1, default=str)
    return result
