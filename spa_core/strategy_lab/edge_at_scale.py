"""
spa_core/strategy_lab/edge_at_scale.py — ROUND-2 WS-1.3: the SCALE-HONEST edge curve.

THE QUESTION (the only edge that matters survives at fundable size)
═══════════════════════════════════════════════════════════════════
The WS-1.2 optimizer's uplift is measured in WEIGHT space (per-protocol cap = a FRACTION of the
book). Weight-fraction caps are scale-INVARIANT, so a naive A/B says "the uplift is the same at
$100k and $10M". That is FALSE and dishonest at scale, because the binding constraint at size is
NOT the weight cap — it is the ABSOLUTE pool-capacity cap (MP-209 / ADR-009): a position may not
exceed 1% of a pool's TVL (3% for a T1 pool over $1B).

At $100k a 20%-weight slug into a $50M-TVL T2 pool is $20k = 0.04% of TVL — far under the 1% cap,
so the optimizer's high-yield picks fit. At $10M the SAME 20% weight is $2M = 4% of a $50M pool —
OVER the 1% cap. The capacity cap then CLAMPS that position to $500k (1% of $50M), and the freed
capital spills to the next-best pool (lower yield) or to cash. The high-yield concentration the
optimizer's edge DEPENDS ON is exactly what capacity-capping dissolves → the edge COMPRESSES with
AUM. This module measures that compression on the REAL caps and reports the AUM at which the
selection uplift falls below a fundable-materiality threshold (default 0.25pp).

METHOD (deterministic, stdlib, the REAL capacity machinery — not a re-derivation)
═════════════════════════════════════════════════════════════════════════════════
For each AUM in {$100k, $1M, $10M} (owner-tunable):
  1. score the live held-universe through BOTH allocation surfaces (legacy / optimizer) → weights,
  2. convert weights → dollar positions at that AUM,
  3. apply the REAL ``spa_core.risk.capacity_limits.apply_capacity_caps`` (1% TVL / 3% T1>$1B) using
     each pool's LIVE TVL,
  4. capital clamped OUT by the caps becomes CASH (an honest yield drag — it earns 0, not the pool
     APY) — we do NOT re-optimize the spill (the honest worst case: capped capital sits idle until a
     re-balance, and even re-deployed it goes to a lower-yield pool, so cash is the conservative,
     fundable-honest floor on the post-cap yield),
  5. recompute realized yield-on-CAPITAL for each book AFTER caps → the scale-bound uplift.

The uplift vs AUM curve + the break-even AUM (uplift < threshold) is the honest answer.

HONESTY / fail-CLOSED
═════════════════════
  • the TVL used is the LIVE per-pool TVL (from the adapter universe), NEVER a fabricated huge TVL
    that would make the caps never bind. A missing TVL is treated as the $5M risk-floor (conservative
    — small pool → caps bind sooner, the honest worst case), never as infinite capacity.
  • an empty/unreadable universe → status 'unavailable' (null curve), never a fabricated edge.
  • the edge can HONESTLY compress to ≤ 0 at scale — that is a VALUABLE finding, reported plainly,
    never floored at the small-AUM number.

stdlib only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN. Advisory; reads the live universe
READ-ONLY; never moves capital, never touches the go-live track.

Run:  python3 -m spa_core.strategy_lab.edge_at_scale
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.risk import capacity_limits as cap
from spa_core.strategy_lab.realized_ab import (
    DATA_DIR,
    EQUITY_CURVE,
    build_universe,
    latest_live_universe,
    load_registry_apy,
)

OUT_FILE = DATA_DIR / "edge_at_scale.json"

# Owner-tunable AUM ladder (USD). The fundable-size question lives at $10M (the $100M valuation
# thesis manages external AUM at this order). Pinned + documented.
AUM_LADDER_USD: Tuple[float, ...] = (100_000.0, 1_000_000.0, 10_000_000.0)

# Materiality threshold: below this risk-adjusted uplift (percentage points of APY-on-capital) the
# optimizer's edge is not worth the operational complexity at that size. 0.25pp = 25bps/yr.
MATERIALITY_PP = 0.25

# The TVL to assume for a pool whose live TVL is missing — the repo $5M risk-floor (conservative:
# a small pool makes the capacity cap bind SOONER, the honest worst case). Never infinite.
DEFAULT_TVL_USD = 5_000_000.0

# READ-ONLY live-TVL source: the adapter orchestrator status (read-only domain). The realized_ab
# universe carries a FLAT placeholder TVL ($500M) because the WS-1.2 A/B only exercised weight-cap
# geometry — but the SCALE question is precisely about ABSOLUTE pool capacity, so edge_at_scale MUST
# use each pool's REAL live TVL. Missing/non-finite → DEFAULT_TVL_USD (conservative).
_ORCH_STATUS = DATA_DIR / "adapter_orchestrator_status.json"

_EPS = 1e-12


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_live_tvl(orch_status_path: Path = _ORCH_STATUS) -> Dict[str, float]:
    """protocol → live TVL (USD) from the read-only adapter orchestrator status. Missing/corrupt
    → {} (callers fall back to the conservative DEFAULT_TVL_USD). READ-ONLY; never written."""
    import json as _json
    out: Dict[str, float] = {}
    try:
        doc = _json.loads(orch_status_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    ads = doc.get("adapters") if isinstance(doc, dict) else None
    if not isinstance(ads, list):
        return out
    for a in ads:
        if not isinstance(a, dict):
            continue
        proto = a.get("protocol")
        tvl = a.get("tvl_usd")
        if proto and _finite(tvl) and float(tvl) > 0:
            out[str(proto)] = float(tvl)
    return out


def _apply_live_tvl(adapters: List[dict], live_tvl: Dict[str, float]) -> List[dict]:
    """Overlay each pool's REAL live TVL onto the universe (the realized_ab universe carries a flat
    placeholder). Missing → conservative DEFAULT_TVL_USD. Returns a new list (PURE)."""
    out: List[dict] = []
    for a in adapters:
        b = dict(a)
        tvl = live_tvl.get(a["protocol"])
        b["tvl_usd"] = float(tvl) if _finite(tvl) and tvl and tvl > 0 else DEFAULT_TVL_USD
        out.append(b)
    return out


def _book_weights(adapters: List[dict]) -> Dict[str, Dict[str, float]]:
    """Score the universe through both surfaces → {book: {protocol: weight}}. Sandbox allocator."""
    from spa_core.allocator.allocator import StrategyAllocator
    import json as _json
    with tempfile.TemporaryDirectory(prefix="spa_edge_scale_") as d:
        sandbox = Path(d)
        (sandbox / "status.json").write_text(_json.dumps({"adapters": adapters}), encoding="utf-8")

        def _alloc(model: str, objective):
            return StrategyAllocator(
                status_path=sandbox / "status.json",
                risk_scores_path=sandbox / "risk_scores.json",
                registry_path=sandbox / "_no_registry.json",
                strategy_loop_enabled=False,
                live_apy_provider={},
                objective=objective,
            ).allocate(model=model)

        legacy = _alloc("risk_adjusted", None)
        opt = _alloc("optimized_yield", "max_yield")
    return {"legacy": dict(legacy.target_weights), "optimized": dict(opt.target_weights)}


def _realized_yield_after_caps(
    weights: Dict[str, float],
    aum_usd: float,
    apy_map: Dict[str, float],
    tvl_map: Dict[str, float],
    tier_map: Dict[str, str],
) -> dict:
    """Apply the REAL capacity caps to the book at this AUM and return the post-cap realized
    yield-on-CAPITAL (%). Capital clamped out of a pool becomes idle cash (earns 0) — the honest,
    conservative drag. Returns diagnostics so the binding is auditable."""
    # weight → dollars at this AUM
    dollars = {p: w * aum_usd for p, w in weights.items() if w > _EPS}
    # per-pool effective max_pct (1% T2 / 3% T1>$1B), using the LIVE TVL
    capped: Dict[str, float] = {}
    n_capped = 0
    capped_out_usd = 0.0
    for p, amt in dollars.items():
        tvl = tvl_map.get(p, DEFAULT_TVL_USD)
        if not _finite(tvl) or tvl <= 0:
            tvl = DEFAULT_TVL_USD
        max_pct = cap.effective_max_pct(p, tier_map.get(p, "T2"), tvl)
        max_deployable = tvl * max_pct
        if amt > max_deployable:
            capped_out_usd += (amt - max_deployable)
            capped[p] = max_deployable
            n_capped += 1
        else:
            capped[p] = amt
    deployed_usd = sum(capped.values())
    # realized $/yr at each pool's APY; un-deployed capital (capped-out + original cash) earns 0.
    annual_income = sum(capped[p] * (max(apy_map.get(p, 0.0), 0.0) / 100.0) for p in capped)
    yield_on_capital_pct = (annual_income / aum_usd * 100.0) if aum_usd > 0 else 0.0
    return {
        "yield_on_capital_pct": round(yield_on_capital_pct, 6),
        "deployed_usd": round(deployed_usd, 2),
        "deployed_frac": round(deployed_usd / aum_usd, 6) if aum_usd > 0 else 0.0,
        "capital_capped_out_usd": round(capped_out_usd, 2),
        "n_positions_capacity_capped": n_capped,
    }


def edge_curve(
    adapters: List[dict],
    *,
    aum_ladder: Tuple[float, ...] = AUM_LADDER_USD,
    materiality_pp: float = MATERIALITY_PP,
) -> dict:
    """Compute the uplift-vs-AUM curve + the break-even AUM. PURE given the universe."""
    apy_map = {a["protocol"]: float(a["apy_pct"]) for a in adapters}
    tier_map = {a["protocol"]: str(a.get("tier", "T2")) for a in adapters}
    tvl_map = {a["protocol"]: float(a.get("tvl_usd", DEFAULT_TVL_USD)) for a in adapters}
    weights = _book_weights(adapters)

    points: List[dict] = []
    for aum in aum_ladder:
        leg = _realized_yield_after_caps(weights["legacy"], aum, apy_map, tvl_map, tier_map)
        opt = _realized_yield_after_caps(weights["optimized"], aum, apy_map, tvl_map, tier_map)
        uplift_pp = round(opt["yield_on_capital_pct"] - leg["yield_on_capital_pct"], 6)
        points.append({
            "aum_usd": aum,
            "legacy_yield_on_capital_pct": leg["yield_on_capital_pct"],
            "optimized_yield_on_capital_pct": opt["yield_on_capital_pct"],
            "uplift_pp": uplift_pp,
            "uplift_material": bool(uplift_pp >= materiality_pp),
            "legacy_diag": leg,
            "optimized_diag": opt,
        })

    # break-even AUM: the smallest AUM at which uplift drops below materiality. If the uplift is
    # material at every tested AUM → None (survives across the ladder); if material at NONE → the
    # smallest AUM (it never clears the bar). Honest either way.
    break_even = None
    for pt in points:
        if not pt["uplift_material"]:
            break_even = pt["aum_usd"]
            break
    edge_survives_at_max = bool(points and points[-1]["uplift_material"])

    return {
        "materiality_pp": materiality_pp,
        "aum_ladder_usd": list(aum_ladder),
        "curve": points,
        "edge_below_materiality_at_aum_usd": break_even,
        "edge_survives_at_max_aum": edge_survives_at_max,
        "max_aum_tested_usd": aum_ladder[-1] if aum_ladder else None,
    }


def build_edge_at_scale(
    *,
    data_dir: Optional[Path] = None,
    equity_path: Optional[Path] = None,
    registry_path: Optional[Path] = None,
    aum_ladder: Tuple[float, ...] = AUM_LADDER_USD,
    materiality_pp: float = MATERIALITY_PP,
    live_tvl: Optional[Dict[str, float]] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Build the scale-honest edge curve from the live universe. Writes data/edge_at_scale.json
    atomically (unless write=False). Fail-CLOSED on an unreadable/empty universe.

    ``live_tvl`` injects the per-pool TVL map (tests/hermetic). None → read the read-only adapter
    orchestrator status (each pool's REAL live TVL — the binding constraint at scale)."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    eq_path = Path(equity_path) if equity_path is not None else (root / "equity_curve_daily.json")
    reg_path = Path(registry_path) if registry_path is not None else (root / "adapter_registry.json")

    base = {
        "generated_at": now_iso if now_iso is not None else _utc_now_iso(),
        "model": "edge_at_scale",
        "llm_forbidden": True,
        "deterministic": True,
        "advisory": True,
        "basis": (
            "Scale-honest edge curve: the WS-1.2 optimizer uplift recomputed at each AUM AFTER the "
            "REAL MP-209/ADR-009 pool-capacity caps (1% TVL, 3% T1>$1B) bind. Capacity-capped capital "
            "becomes idle cash (earns 0) — the honest, conservative drag. The edge that matters "
            "survives at fundable size."
        ),
    }

    universe_day, reason = latest_live_universe(eq_path)
    if reason is not None:
        return {**base, "status": "unavailable", "reason": reason, "curve": [],
                "edge_below_materiality_at_aum_usd": None, "edge_survives_at_max_aum": None}
    registry = load_registry_apy(reg_path)
    adapters = build_universe(universe_day, registry)
    if not adapters:
        return {**base, "status": "unavailable", "reason": "empty_universe", "curve": [],
                "edge_below_materiality_at_aum_usd": None, "edge_survives_at_max_aum": None}

    # overlay REAL per-pool live TVL — the binding constraint at scale (the placeholder flat TVL the
    # realized_ab universe carries would make the caps never bind, which is dishonest at $10M).
    tvl_map = live_tvl if live_tvl is not None else load_live_tvl(root / "adapter_orchestrator_status.json")
    adapters = _apply_live_tvl(adapters, tvl_map)

    curve = edge_curve(adapters, aum_ladder=aum_ladder, materiality_pp=materiality_pp)
    out = {**base, "status": "ok", "universe_date": str(universe_day.get("date")),
           "live_tvl_used": {a["protocol"]: round(a["tvl_usd"], 2) for a in adapters}, **curve}
    if write:
        atomic_save(out, str(root / "edge_at_scale.json"))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    import json
    p = argparse.ArgumentParser(description="Scale-honest edge curve (WS-1.3).")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    rep = build_edge_at_scale(write=not args.dry_run)
    if rep.get("status") != "ok":
        print(json.dumps(rep, indent=2, default=str))
        return 0
    print(f"Edge-at-scale (materiality {rep['materiality_pp']}pp)   universe {rep['universe_date']}")
    print(f"{'AUM':>14s} {'legacy%':>10s} {'optimized%':>12s} {'uplift_pp':>10s} {'capped$':>14s} material")
    print("-" * 80)
    for pt in rep["curve"]:
        print(f"${pt['aum_usd']:>13,.0f} {pt['legacy_yield_on_capital_pct']:>10.4f} "
              f"{pt['optimized_yield_on_capital_pct']:>12.4f} {pt['uplift_pp']:>10.4f} "
              f"${pt['optimized_diag']['capital_capped_out_usd']:>13,.0f} "
              f"{'YES' if pt['uplift_material'] else 'no'}")
    be = rep["edge_below_materiality_at_aum_usd"]
    if be is None:
        print(f"\nEdge SURVIVES across the ladder (uplift ≥ {rep['materiality_pp']}pp up to "
              f"${rep['max_aum_tested_usd']:,.0f}).")
    else:
        print(f"\nEdge falls BELOW {rep['materiality_pp']}pp at AUM ${be:,.0f}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
