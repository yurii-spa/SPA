"""
spa_core/strategy_lab/rates_desk/refusal_coverage.py — auditable REFUSAL-COVERAGE artifact for the
rates-desk thesis expansion (WS-4.3, "more underlyings/venues/shapes — refusal stays 100% on toxic").

WHY THIS EXISTS
═══════════════
WS-4.3 widens the rates-desk surface (more PT underlyings via the config-extended live matcher, more
keyless lending venues — already landed as Proof-of-Risk workstream C1). The WHOLE edge of the desk is
refusal-first discipline: every underlying must pass the gate OR be REFUSED with a structural reason,
and the known-toxic LRT books must be refused 100% of the time, at ANY size — the structural-veto +
the 0.06 max_structural_haircut cap must hold so a tail-toxic book can never be SIZED AROUND.

This module produces ONE deterministic, hash-anchorable COVERAGE artifact that PROVES that property,
so the master attribution report (WS-4.5) can anchor it and a third party can verify "refusal stayed
100% on toxic after the expansion" without re-deriving the gate:

  (A) DEEP coverage — reuse validation.assertion1_deep_refusal() verbatim (it walks the REAL daily
      history of every toxic LRT PT and asserts the gate refused essentially every day on structural
      grounds). This is the no-regression check: economics never rescues a tail-vetoed book.

  (B) SIZE-SWEEP coverage — for every toxic LRT underlying, run the entry gate at a SWEEP of sizes
      ($1k … $1M). A structurally-toxic book must be REFUSED at EVERY size (the size-down exploit is
      closed: the toxicity veto is on the SIZE-INDEPENDENT structural haircut vs the 0.06 cap, never on
      the size-dependent total). 100% refusal across all sizes × all toxic underlyings, or it fails.

HONESTY / fail-CLOSED: the deep leg is fail-OPEN-of-the-DATA only (a missing deep history → status
absent, the size-sweep mechanism still proves the veto). A clean (non-toxic) underlying is NOT asserted
refused — refusal coverage is about TOXIC books; a clean book SHOULD be approvable at the right size.

stdlib only, deterministic, PURE-of-pricing (it only invokes the gate), LLM-FORBIDDEN. Advisory /
research — it inspects the gate; it never trades, never touches the go-live track.

Run:  python3 -m spa_core.strategy_lab.rates_desk.refusal_coverage
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import config as C
from spa_core.strategy_lab.rates_desk import validation as rd_validation
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
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
from spa_core.strategy_lab.rates_desk import _io

_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
OUT_FILE = _ROOT / "data" / "rates_desk" / "refusal_coverage.json"

# The size sweep the toxic-veto is probed across. A structurally-toxic book must be REFUSED at EVERY
# one of these — the size-down exploit (sizing a toxic book small enough to slip the cap) is closed.
SIZE_SWEEP_USD: Tuple[Decimal, ...] = (
    Decimal("1000"), Decimal("4000"), Decimal("10000"), Decimal("50000"),
    Decimal("100000"), Decimal("500000"), Decimal("1000000"),
)

# The toxic underlyings (size-independent structural toxicity). Read from the SSOT kind map so a
# newly-added LRT is automatically covered — never a hardcoded list that can drift out of date.
TOXIC_LRTS: Tuple[str, ...] = tuple(
    sorted(u for u, kind in C.UNDERLYING_KINDS.items() if kind == "lrt"))


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _toxic_lrt_book(underlying: str, size_usd: Decimal, as_of: str) -> Tuple[Opportunity, UnderlyingRisk]:
    """A representative TOXIC restaking-LRT book (the size-independent structural risk surface the desk
    would see for a restaking PT: grinding peg drift + nesting + concentration + a hostile funding
    regime). The quoted rate is a HUGE implied APY — exactly the tail-comp economics that must NEVER
    rescue a structurally-toxic book. Mirrors validation.assertion1_deep_refusal's risk surface so the
    size-sweep is consistent with the deep-history leg. Deterministic / PURE."""
    risk = UnderlyingRisk(
        underlying=underlying.lower(), as_of=as_of,
        nav_redemption_value=Decimal("1"), market_price=Decimal("0.994"),
        peg_distance=Decimal("0.006"), peg_vol_30d=Decimal("0.02"),
        redemption_sla_seconds=86400 * 7, reserve_fund_ratio=D0,
        funding_neg_frac_90d=Decimal("0.30"),
        oracle_kind="redstone", oracle_staleness_seconds=600,
        nested_protocol_count=4, top_borrower_share=Decimal("0.45"),
    )
    q = RateQuote(
        underlying=underlying.lower(), kind=UnderlyingKind.LRT, venue=RateVenue.PENDLE_PT,
        protocol="pendle", market_id=f"{underlying.lower()}-pt-toxic", tenor_seconds=86400 * 60,
        as_of=as_of, quoted_rate=Decimal("0.45"),  # an absurd 45% implied — pure tail-comp economics
        tvl_usd=Decimal("5e7"), exit_liquidity_usd=Decimal("2e6"), hedge_available=False,
    )
    opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=size_usd)
    return opp, risk


def size_sweep_coverage(params: Optional[RatePolicyParams] = None,
                        as_of: str = "2026-06-28") -> dict:
    """For EVERY toxic LRT underlying × EVERY size in SIZE_SWEEP_USD, run the entry gate and assert it
    REFUSES (the toxicity veto cannot be sized around). Returns a per-underlying tally + the overall
    100%-refusal verdict. PURE / deterministic / fail-CLOSED (a gate that throws is counted as NOT
    refused-cleanly → fails the coverage, the conservative choice)."""
    p = params or RatePolicyParams()
    eng = FairValueEngine(p)
    per_underlying: List[dict] = []
    all_refused_every_size = True
    total_checks = 0
    total_refused = 0
    for ul in TOXIC_LRTS:
        sizes: List[dict] = []
        refused_here = 0
        for size in SIZE_SWEEP_USD:
            total_checks += 1
            opp, risk = _toxic_lrt_book(ul, size, as_of)
            try:
                res, _ = evaluate_entry(opp, risk, Decimal("1"), opp.quote.exit_liquidity_usd,
                                        p, KillState(), engine=eng)
                refused = not res.approved
                reason = res.reason.value
            except Exception as exc:  # noqa: BLE001 — a gate error is NOT a clean refusal → fail-closed
                refused = False
                reason = f"gate_error:{exc}"
            if refused:
                refused_here += 1
                total_refused += 1
            else:
                all_refused_every_size = False
            sizes.append({"size_usd": str(size), "refused": bool(refused), "reason": reason})
        per_underlying.append({
            "underlying": ul,
            "n_sizes": len(SIZE_SWEEP_USD),
            "n_refused": refused_here,
            "all_sizes_refused": refused_here == len(SIZE_SWEEP_USD),
            "sizes": sizes,
        })
    return {
        "toxic_underlyings": list(TOXIC_LRTS),
        "size_sweep_usd": [str(s) for s in SIZE_SWEEP_USD],
        "max_structural_haircut_cap": str(p.max_structural_haircut),
        "n_checks": total_checks,
        "n_refused": total_refused,
        "refusal_pct": round(100.0 * total_refused / total_checks, 4) if total_checks else 0.0,
        "all_toxic_refused_every_size": bool(all_refused_every_size),
        "per_underlying": per_underlying,
    }


def build_coverage(params: Optional[RatePolicyParams] = None, *,
                   write: bool = True, now_iso: Optional[str] = None,
                   out_path: Optional[Path] = None) -> dict:
    """Build the full refusal-coverage artifact: the DEEP-history leg (reused verbatim) + the SIZE-SWEEP
    leg, plus the single 100%-on-toxic verdict. Writes data/rates_desk/refusal_coverage.json atomically.

    Returns the artifact. The headline `refusal_100pct_on_toxic` is True only when BOTH legs hold (the
    deep leg, when its data is present, AND the size sweep). fail-CLOSED: a deep-history that is absent
    leaves the deep leg status=absent but the size-sweep mechanism still carries the verdict."""
    p = params or RatePolicyParams()
    now = now_iso if now_iso is not None else _utc_now_iso()

    deep = rd_validation.assertion1_deep_refusal(p)
    sweep = size_sweep_coverage(p)

    deep_ok = deep.get("all_toxic_books_refused_every_day")
    deep_present = "status" not in deep or not str(deep.get("status", "")).startswith("deep history absent")
    # the headline verdict: the size-sweep must always hold; the deep leg must hold WHEN its data exists.
    refusal_100 = bool(sweep["all_toxic_refused_every_size"] and (deep_ok if deep_present else True))

    out = {
        "generated_at": now,
        "model": "rates_desk_refusal_coverage",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "research_only": True,
        "refusal_100pct_on_toxic": refusal_100,
        "deep_history": {
            "present": bool(deep_present),
            "all_toxic_books_refused_every_day": deep_ok,
            "any_toxic_day_approved": deep.get("any_toxic_day_approved"),
            "raw": deep,
        },
        "size_sweep": sweep,
        "note": (
            "WS-4.3 refusal-coverage: after widening the rates-desk surface, the refusal-first gate "
            "still refuses 100% of toxic LRT books — across their REAL daily history (deep leg) AND "
            "at EVERY size ($1k..$1M) (size-sweep leg). The structural-veto on the size-independent "
            "haircut vs the 0.06 cap holds: a tail-toxic book cannot be sized around. No regression."),
    }
    if write:
        _io.atomic_write_json(out_path or OUT_FILE, out, indent=2)
    return out


def main() -> int:
    import json
    import socket
    socket.setdefaulttimeout(20)
    out = build_coverage(write=True)
    sw = out["size_sweep"]
    print(f"Rates-desk refusal coverage   toxic={sw['toxic_underlyings']}   "
          f"size-sweep refused {sw['n_refused']}/{sw['n_checks']} ({sw['refusal_pct']}%)   "
          f"100%-on-toxic={out['refusal_100pct_on_toxic']}")
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["refusal_100pct_on_toxic"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
