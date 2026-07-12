"""Q2-1 — N-book capacity aggregator (deterministic scale curve, advisory).

The recurring funder objection is that the rates-desk edge is a "$100k–$250k artifact":
a single gated-carry book's above-floor $/yr peaks near ~$5–6k because pouring more AUM into
the same thin Pendle/Ethena pools compresses its APY toward the floor (see `capacity.py`).

This module answers the OTHER question honestly: **what happens as you add MORE distinct gated-carry
books** (different maturities / venues)? It composes two things this repo already measures — it does
NOT invent a new depth model:

  1. `venue_expansion.build_report().live_curve` — the per-book HONEST deployable depth, with the
     same-venue correlation haircut (CORRELATION_HAIRCUT_FRAC) already applied. Books that share a rail
     (e.g. every sUSDe/USDe PT on the Ethena rail) do NOT get additive fresh depth; distinct rails do.
  2. `capacity.py` (`data/rates_desk/capacity.json`) — the single-pool APY→AUM COMPRESSION curve
     (`aum_levels`): how a book's net APY decays toward the floor as its own deployed size grows.

The honest aggregation: group books by rail cluster; a cluster behaves like ONE pool being filled, so
its above-floor spread is read at the CLUSTER's total (haircut) deployable — NOT at each book's size
(that would double-count depth). Distinct rails are additive. The resulting curve shows above-floor
$/yr vs book-count PLATEAUING — and the plateau is set by how many DISTINCT deep rails exist, not by
how many books you stack on one rail. That converts the "artifact" hand-wave into a measured ceiling.

Deterministic, stdlib-only, LLM-forbidden, fail-CLOSED (missing inputs → RAISE, never fabricate).
Advisory: never gates, never moves capital.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.errors import SPAError

_DATA = Path(__file__).resolve().parent.parent.parent.parent / "data"
_CAPACITY_JSON = _DATA / "rates_desk" / "capacity.json"
_OUT_JSON = _DATA / "rates_desk" / "n_book_capacity.json"


def _load_capacity() -> dict:
    """The single-book compression curve. fail-CLOSED: absent/malformed → RAISE."""
    try:
        d = json.loads(_CAPACITY_JSON.read_text())
    except (OSError, ValueError) as e:
        raise SPAError(f"n_book_capacity: capacity.json unreadable ({e}); run capacity.py first") from e
    if not d.get("aum_levels"):
        raise SPAError("n_book_capacity: capacity.json has no aum_levels")
    return d


def _spread_fn(cap: dict):
    """Piecewise-linear above-floor spread (pp) as a function of deployed USD, from the real
    `aum_levels` compression curve. Clamped flat beyond the measured endpoints. Never negative."""
    floor = float(cap["rwa_floor_pct"])
    pts: List[Tuple[float, float]] = sorted(
        (float(r["aum_usd"]), max(0.0, float(r["book_net_apy_pct"]) - floor))
        for r in cap["aum_levels"] if r.get("aum_usd") and r.get("book_net_apy_pct") is not None
    )
    if not pts:
        raise SPAError("n_book_capacity: no usable aum_levels points")

    def spread(size_usd: float) -> float:
        if size_usd <= pts[0][0]:
            return pts[0][1]
        if size_usd >= pts[-1][0]:
            return pts[-1][1]
        for i in range(1, len(pts)):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            if size_usd <= x1:
                t = (size_usd - x0) / (x1 - x0) if x1 > x0 else 0.0
                return y0 + t * (y1 - y0)
        return pts[-1][1]

    return spread, floor


def _live_books() -> Tuple[List[dict], dict]:
    """Per-book honest deployable + rail, from the venue-expansion live curve. fail-CLOSED."""
    from spa_core.strategy_lab.rates_desk import venue_expansion as VE
    lc = VE.build_report(enabled=False).get("live_curve") or {}
    curve = lc.get("curve") or []
    if not curve:
        raise SPAError("n_book_capacity: venue live_curve empty (no fundable PT books)")
    return curve, lc


def build_report(write: bool = True) -> dict:
    """Deterministic N-book above-floor $/yr scale curve. Returns the report dict."""
    cap = _load_capacity()
    spread, floor = _spread_fn(cap)
    books, lc = _live_books()

    # Books arrive depth-sorted. Walk book-count n = 1..N; at each n, regroup the first n books by
    # rail cluster, credit each cluster its HONEST (haircut) deployable, read the compression spread at
    # the cluster total, and sum above-floor $/yr across clusters (distinct rails additive).
    curve: List[dict] = []
    for n in range(1, len(books) + 1):
        prefix = books[:n]
        by_rail: Dict[str, float] = {}
        for b in prefix:
            rail = str(b.get("venue", "?"))
            # `contribution_usd` is the book's haircut-adjusted marginal deployable already; sum it
            # per rail to get the cluster's honest fillable depth.
            by_rail[rail] = by_rail.get(rail, 0.0) + float(b.get("contribution_usd", 0.0))
        deployable = sum(by_rail.values())
        above_floor_usd = 0.0
        for rail, dep in by_rail.items():
            above_floor_usd += dep * spread(dep) / 100.0
        curve.append({
            "n_books": n,
            "n_rails": len(by_rail),
            "deployable_usd": round(deployable, 2),
            "above_floor_usd_per_yr": round(above_floor_usd, 2),
            "blended_above_floor_pct": round(above_floor_usd / deployable * 100.0, 4) if deployable else 0.0,
        })

    plateau = max(curve, key=lambda r: r["above_floor_usd_per_yr"]) if curve else None
    last = curve[-1] if curve else None
    # marginal value of the LAST book added (does stacking still help?)
    marginal_last = round(curve[-1]["above_floor_usd_per_yr"] - curve[-2]["above_floor_usd_per_yr"], 2) \
        if len(curve) >= 2 else None

    report = {
        "model": "n_book_capacity_aggregator",
        "is_advisory": True,
        "deterministic": True,
        "llm_forbidden": True,
        "rwa_floor_pct": floor,
        "n_books_total": len(books),
        "n_distinct_rails": len({str(b.get("venue")) for b in books}),
        "correlation_haircut_frac": lc.get("haircut_frac"),
        "curve": curve,
        "plateau_above_floor_usd_per_yr": plateau["above_floor_usd_per_yr"] if plateau else 0.0,
        "plateau_at_n_books": plateau["n_books"] if plateau else 0,
        "full_book_above_floor_usd_per_yr": last["above_floor_usd_per_yr"] if last else 0.0,
        "marginal_value_of_last_book_usd_per_yr": marginal_last,
        "single_book_source": "data/rates_desk/capacity.json (aum_levels compression)",
        "depth_source": "venue_expansion.live_curve (honest per-book deployable + rail, haircut applied)",
        "note": (
            "Above-floor $/yr grows with book-count only until each rail's shared pool depth saturates; "
            "same-rail books share depth (haircut → compression), so the plateau is set by the number of "
            "DISTINCT deep rails, not by stacking more books on one rail. HONEST: this composes the "
            "existing venue-depth + single-pool compression models; it neither invents new depth nor "
            "asserts scale the pools do not support. Advisory — never gates, never moves capital."
        ),
    }
    if write:
        atomic_save(report, str(_OUT_JSON))
    return report


def main() -> int:
    rep = build_report(write=True)
    print(f"N-book capacity: {rep['n_books_total']} books / {rep['n_distinct_rails']} rails")
    print(f"  plateau above-floor: ${rep['plateau_above_floor_usd_per_yr']:,.0f}/yr "
          f"at n={rep['plateau_at_n_books']} books")
    print(f"  full-book above-floor: ${rep['full_book_above_floor_usd_per_yr']:,.0f}/yr")
    print(f"  marginal value of last book: ${rep['marginal_value_of_last_book_usd_per_yr']:,.2f}/yr")
    print(f"  → wrote {_OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
