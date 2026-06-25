"""
spa_core/strategy_lab/rates_desk/surface_io.py — (de)serialize a cached RateSurface + scan it.

Rebuilds the contract dataclasses (RateQuote / UnderlyingRisk) from the cached
data/rates_desk/rate_surface.json (written by feeds.build_surface(cache=True)) and runs the pure
OpportunityEngine over them so the API can serve the CURRENT opportunity scan without a live network
fetch at request time. Inverse of feeds._quote_to_dict / feeds._risk_to_dict.

PURE: deserialization + scan are deterministic given the cached file. No clock for the scan (`as_of`
comes from the file). stdlib only, LLM-FORBIDDEN, fail-CLOSED (a malformed row is skipped, never
fabricated).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple

from spa_core.strategy_lab.rates_desk.contracts import (
    RateQuote,
    RateVenue,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.opportunity_engine import OpportunityEngine, RateSurface

_KIND_BY_VALUE = {k.value: k for k in UnderlyingKind}
_VENUE_BY_VALUE = {v.value: v for v in RateVenue}


def _D(x, default: str = "0") -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:  # noqa: BLE001
        return Decimal(default)


def quote_from_dict(d: dict) -> RateQuote:
    """Rebuild a RateQuote from a cached _quote_to_dict row. fail-CLOSED: bad kind/venue raises."""
    return RateQuote(
        underlying=str(d["underlying"]), kind=_KIND_BY_VALUE[d["kind"]],
        venue=_VENUE_BY_VALUE[d["venue"]], protocol=str(d.get("protocol", "")),
        market_id=str(d["market_id"]), tenor_seconds=int(d.get("tenor_seconds", 0)),
        as_of=str(d.get("as_of", "")), quoted_rate=_D(d.get("quoted_rate")),
        tvl_usd=_D(d.get("tvl_usd")), exit_liquidity_usd=_D(d.get("exit_liquidity_usd")),
        hedge_available=bool(d.get("hedge_available", False)),
        utilization=_D(d.get("utilization")), ltv=_D(d.get("ltv")),
        cap_headroom_usd=_D(d.get("cap_headroom_usd")),
    )


def risk_from_dict(d: dict) -> UnderlyingRisk:
    """Rebuild an UnderlyingRisk from a cached _risk_to_dict row."""
    return UnderlyingRisk(
        underlying=str(d["underlying"]), as_of=str(d.get("as_of", "")),
        nav_redemption_value=_D(d.get("nav_redemption_value"), "1"),
        market_price=_D(d.get("market_price"), "1"),
        peg_distance=_D(d.get("peg_distance")), peg_vol_30d=_D(d.get("peg_vol_30d")),
        redemption_sla_seconds=int(d.get("redemption_sla_seconds", 0)),
        reserve_fund_ratio=_D(d.get("reserve_fund_ratio")),
        funding_neg_frac_90d=_D(d.get("funding_neg_frac_90d")),
        oracle_kind=str(d.get("oracle_kind", "unknown")),
        oracle_staleness_seconds=int(d.get("oracle_staleness_seconds", 0)),
        nested_protocol_count=int(d.get("nested_protocol_count", 0)),
        top_borrower_share=_D(d.get("top_borrower_share")),
    )


def surface_from_cached(raw: dict) -> Tuple[RateSurface, Dict[str, UnderlyingRisk]]:
    """Build a (RateSurface, risks) pair from the cached rate_surface.json dict. Quotes are partitioned
    by venue into the surface's leg dicts (one per underlying; highest-tenor PT wins on collision).
    fail-CLOSED: a malformed quote row is skipped (never fabricated)."""
    as_of = str(raw.get("as_of", ""))
    pt_quotes: Dict[str, RateQuote] = {}
    lending_quotes: Dict[str, RateQuote] = {}
    boros_quotes: Dict[str, RateQuote] = {}
    supply_quotes: Dict[str, RateQuote] = {}
    for row in raw.get("quotes", []) or []:
        try:
            q = quote_from_dict(row)
        except Exception:  # noqa: BLE001 — skip a malformed row, never fabricate
            continue
        u = q.underlying
        if q.venue == RateVenue.PENDLE_PT:
            prev = pt_quotes.get(u)
            if prev is None or q.tenor_seconds > prev.tenor_seconds:
                pt_quotes[u] = q
        elif q.venue == RateVenue.LENDING:
            # a ':supply' market_id is the supply leg; everything else is the borrow leg
            if q.market_id.endswith(":supply"):
                supply_quotes.setdefault(u, q)
            else:
                lending_quotes.setdefault(u, q)
        elif q.venue == RateVenue.BOROS:
            boros_quotes.setdefault(u, q)
    surface = RateSurface(as_of=as_of, pt_quotes=pt_quotes, lending_quotes=lending_quotes,
                          boros_quotes=boros_quotes, supply_quotes=supply_quotes)
    risks: Dict[str, UnderlyingRisk] = {}
    for u, rd in (raw.get("underlying_risk", {}) or {}).items():
        try:
            risks[str(u)] = risk_from_dict(rd)
        except Exception:  # noqa: BLE001
            continue
    return surface, risks


def scan_cached_surface(raw: dict) -> dict:
    """Run the pure OpportunityEngine over a cached surface and return a JSON-safe scan summary
    (ranked by net_edge DESC). Deterministic. fail-CLOSED: a missing risk surface for an underlying
    simply drops its opportunities (the engine skips it)."""
    surface, risks = surface_from_cached(raw)
    as_of = surface.as_of
    engine = OpportunityEngine()
    scanned = engine.scan_detailed(surface, risks, as_of)
    opps: List[dict] = []
    for so in scanned:
        e = so.edge
        opps.append({
            "underlying": e.underlying,
            "shape": e.shape.value,
            "as_of": e.as_of,
            "venue": e.venue or so.opportunity.quote.venue.value,
            "market_id": so.opportunity.quote.market_id,
            "fair_yield": str(e.fair_yield),
            "reference_rate": str(e.reference_rate),
            "gross_edge": str(e.gross_edge),
            "net_edge": str(e.net_edge),
            "cost_total": str(e.cost_total),
            "raw_max_size_usd": str(e.raw_max_size_usd),
            "requested_size_usd": str(so.opportunity.requested_size_usd),
            "tenor_days": so.opportunity.quote.tenor_seconds // 86400,
            "hedge_available": so.opportunity.quote.hedge_available,
            "detail": dict(sorted(e.detail.items())),
        })
    return {
        "generated_at": raw.get("generated_at"),
        "as_of": as_of,
        "mode": raw.get("mode"),
        "n_opportunities": len(opps),
        "opportunities": opps,
    }
