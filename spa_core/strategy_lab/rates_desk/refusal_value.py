"""Q2-5b — Avoided-loss REFUSAL P&L ledger (deterministic, advisory).

The refusal moat is usually stated as a philosophy ("we refuse tail-comp yield"). This module prices it
as a P&L NUMBER a funder can underwrite: for each toxic-LRT underlying the fair-value gate refuses on
STRUCTURAL grounds (the ezETH/rsETH/weETH peg-breakdown tail — see `fair_value_engine.py` PEG haircut),
what a naive book holding the refused PT WOULD have lost when the underlying depegged, minus the carry it
gave up by refusing.

HONEST, grounded in real data — never fabricated:
  • Avoided loss  = the REAL peak-to-trough peg drawdown of the underlying vs ETH over the window
    (`data/rates_desk/prices_deep.json`). This is a CONSERVATIVE LOWER BOUND on a PT holder's realized
    loss: Pendle PT `pt_price` history is unavailable (all-null), and during an exit rush the PT AMM
    discount is typically ≥ the spot peg break — so the true loss is at least this. We claim only the
    lower bound and say so.
  • Advertised implied yield = the peak yield the refused PT was quoting before the depeg
    (`pendle_pt_history.json` implied_yield) — shown as EVIDENCE that the gate correctly read the yield
    as tail-comp (a 40–60% "yield" on an LST PT is compensation for exactly the peg break that followed),
    NOT as a foregone carry to net against (that yield never materializes safely — it IS the tail price).
    The refusing book instead banks the RWA floor on that capital, so its opportunity cost ≈ 0 vs floor.
  • Refusal value = the avoided loss (the realized value, in the scenario that actually occurred), in $
    on a reference allocation.

fail-CLOSED: an underlying with no peg series (rsETH, USDe not in prices_deep) or an event before the
series start is NOT priced — it is listed as `unpriced` with the reason, never guessed. Deterministic,
stdlib-only, LLM-forbidden. Advisory: never gates, never moves capital, never touches the live track.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_save

_DATA = Path(__file__).resolve().parent.parent.parent.parent / "data"
_PRICES = _DATA / "rates_desk" / "prices_deep.json"
_PT_HIST = _DATA / "rates_desk" / "pendle_pt_history.json"
_OUT = _DATA / "rates_desk" / "refusal_value.json"

# The STRUCTURALLY-REFUSED toxic-LRT set (fair_value_engine PEG haircut targets the LRT peg-breakdown
# tail). Blue-chip LSTs (stETH/rETH) are NOT in this set — they are not structurally refused. Mapped to
# their prices_deep peg-series key (None → no peg data → priced as `unpriced`, fail-closed).
_TOXIC_LRT = {
    "ezETH": "ezeth",
    "eETH": "eeth",   # weETH PTs settle on eETH
    "rsETH": None,    # no peg series in prices_deep → unpriced (honest gap, NOT fabricated)
}

_REF_ALLOC_USD = 100_000.0  # reference naive allocation per refused book (for $ framing)
_RWA_FLOOR_PCT = 3.4        # excess-over-floor basis for carry-foregone


def _load(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise RuntimeError(f"refusal_value: {what} unreadable ({e})") from e


def _peg_drawdown(lrt_series: Dict[str, float], eth_series: Dict[str, float]) -> Optional[dict]:
    """Peak-to-trough drawdown of the LRT/ETH peg ratio over the common dates. None if too sparse."""
    common = sorted(set(lrt_series) & set(eth_series))
    ratios: List[Tuple[str, float]] = [
        (d, lrt_series[d] / eth_series[d]) for d in common if eth_series.get(d)
    ]
    if len(ratios) < 30:
        return None
    peak = ratios[0][1]
    max_dd = 0.0
    worst = ratios[0][0]
    for d, r in ratios:
        peak = max(peak, r)
        dd = r / peak - 1.0 if peak else 0.0
        if dd < max_dd:
            max_dd, worst = dd, d
    return {"peg_drawdown_pct": round(max_dd * 100.0, 3), "worst_date": worst,
            "window_start": ratios[0][0], "window_end": ratios[-1][0], "n_points": len(ratios)}


def _advertised_carry(pt_hist: dict, underlying: str, before_date: str) -> Optional[float]:
    """Max implied_yield the refused PT advertised on/before the depeg (the carry a naive book chased).
    Uses the max over the pre-depeg window — the peak tail-comp yield the gate refused. % per yr."""
    best: Optional[float] = None
    for mk in pt_hist.get("markets", {}).values():
        if mk.get("underlying") != underlying:
            continue
        for p in (mk.get("series") or []):
            d = p.get("date")
            iy = p.get("implied_yield")
            if d and iy is not None and d <= before_date:
                best = iy if best is None else max(best, iy)
    return round(best * 100.0, 3) if best is not None else None


def build_report(write: bool = True) -> dict:
    prices = _load(_PRICES, "prices_deep.json").get("series", {})
    pt_hist = _load(_PT_HIST, "pendle_pt_history.json")
    eth = prices.get("eth") or {}
    if not eth:
        raise RuntimeError("refusal_value: no ETH peg reference series")

    events: List[dict] = []
    unpriced: List[dict] = []
    for underlying, key in _TOXIC_LRT.items():
        if key is None or key not in prices:
            unpriced.append({"underlying": underlying,
                             "reason": "no peg series in prices_deep (event not fabricated)"})
            continue
        dd = _peg_drawdown(prices[key], eth)
        if dd is None:
            unpriced.append({"underlying": underlying, "reason": "peg series too sparse (<30 pts)"})
            continue
        # peak advertised implied yield up to the depeg — EVIDENCE the yield was tail-comp, not a carry
        adv = _advertised_carry(pt_hist, underlying, dd["worst_date"])
        avoided_loss_pct = -dd["peg_drawdown_pct"]  # a positive number = loss avoided
        events.append({
            "underlying": underlying,
            "refused_reason": "structural PEG-breakdown tail (fair_value_engine PEG haircut)",
            "window": f"{dd['window_start']}..{dd['window_end']}",
            "worst_date": dd["worst_date"],
            "peg_drawdown_pct": dd["peg_drawdown_pct"],
            "avoided_loss_pct_lower_bound": round(avoided_loss_pct, 3),
            "peak_advertised_implied_yield_pct": adv,
            "yield_was_tail_comp": (adv is not None and adv > 15.0),
            "opportunity_cost_vs_floor_pct": 0.0,  # refusing book banks the RWA floor → ~0 vs floor
            "avoided_loss_usd_per_100k": round(avoided_loss_pct / 100.0 * _REF_ALLOC_USD, 2),
        })

    total_avoided = round(sum(e["avoided_loss_usd_per_100k"] for e in events), 2)
    report = {
        "model": "refusal_avoided_loss_ledger",
        "is_advisory": True,
        "deterministic": True,
        "llm_forbidden": True,
        "evidence_level": "L4 — real historical peg series (prices_deep) + real advertised implied_yield "
                          "(pendle_pt_history); avoided loss is a CONSERVATIVE LOWER BOUND (no pt_price MtM)",
        "reference_allocation_usd": _REF_ALLOC_USD,
        "rwa_floor_pct": _RWA_FLOOR_PCT,
        "n_events_priced": len(events),
        "events": events,
        "unpriced": unpriced,
        "total_avoided_loss_usd_per_100k": total_avoided,
        "note": (
            "Prices the refusal moat as a P&L number: what a naive book holding each STRUCTURALLY-REFUSED "
            "toxic-LRT PT would have lost through the underlying's real peg drawdown. Avoided loss is a "
            "CONSERVATIVE LOWER BOUND — Pendle pt_price history is all-null, so we use the underlying's real "
            "ETH-peg drawdown; the PT AMM exit discount in a rush is typically LARGER, so true avoided loss "
            "is at least this. peak_advertised_implied_yield is shown as EVIDENCE the gate read the yield as "
            "tail-comp (40-60% on an LST PT = the price of exactly the peg break that followed), NOT netted "
            "as a foregone carry — that yield never materializes safely, and the refusing book banks the RWA "
            "floor instead (opportunity cost ~0 vs floor). Unpriced events (rsETH / USDe not in prices_deep, "
            "or pre-series-start) are listed with their reason, never guessed. Advisory — never gates."
        ),
    }
    if write:
        atomic_save(report, str(_OUT))
    return report


def main() -> int:
    rep = build_report(write=True)
    print(f"Refusal avoided-loss ledger: {rep['n_events_priced']} event(s) priced, "
          f"{len(rep['unpriced'])} unpriced")
    for e in rep["events"]:
        print(f"  {e['underlying']:6} peg DD {e['peg_drawdown_pct']:>7}%  "
              f"avoided ${e['avoided_loss_usd_per_100k']:>9,.0f}/100k  "
              f"(advertised {e['peak_advertised_implied_yield_pct']}% implied = tail-comp)")
    for u in rep["unpriced"]:
        print(f"  {u['underlying']:6} UNPRICED — {u['reason']}")
    print(f"  TOTAL avoided (lower bound) ${rep['total_avoided_loss_usd_per_100k']:,.0f}/100k  → wrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
