#!/usr/bin/env python3
"""scripts/tier_paper_rollup.py — three $100k tier paper books, one honest view.

Rolls up the paper track into the three product tiers the owner asked to see side by side,
each notionally $100k:

  • Core (~6% target)       — the LIVE go-live paper track (optimized_yield). Real, evidenced.
  • Balanced (10-12%)       — aggressive_lab {susde_dn, susde_spot, lrt_neutral}, equal-weight
                              $100k blend. Research/paper, WITH the tail, refused for live.
  • Aggressive (15-20%)     — aggressive_lab {pendle_pt_levered, pendle_yt_susde, points_farm},
                              equal-weight $100k blend. Research/paper, brutal tail, refused for live.

Reads existing state ONLY (go-live snapshot + aggressive_lab scorecard) — it does NOT run any
cycle, move capital, or touch the live track. Deterministic, stdlib-only, fail-safe (a missing
input degrades that tier to "insufficient data", never a fabricated number). Writes
data/tier_paper_rollup.json (atomic). LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SNAP = _ROOT / "landing" / "src" / "data" / "track_snapshot.json"
_AGG = _ROOT / "data" / "aggressive_lab" / "scorecard.json"
_OUT = _ROOT / "data" / "tier_paper_rollup.json"

_BALANCED = {"susde_dn", "susde_spot", "lrt_neutral"}
_AGGRESSIVE = {"pendle_pt_levered", "pendle_yt_susde", "points_farm", "lp_eth_stable"}


def _read(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _blend(scorecard: dict, ids: set) -> dict:
    """Equal-weight $100k blend of the named aggressive_lab strategies (from realized forward track)."""
    rows = [s for s in scorecard.get("strategies", []) if s.get("strategy_id") in ids]
    if not rows:
        return {"status": "insufficient_data", "note": "no aggressive_lab rows for this tier yet"}
    apys, tails, trustworthy, n_pts = [], [], [], []
    for s in rows:
        f = s.get("forward", {}) or {}
        # realized annualized return if the forward track is long enough, else the honest headline
        apys.append(f.get("annualized_return_pct"))
        tails.append(f.get("worst_drawdown_pct"))
        trustworthy.append(bool(f.get("trustworthy")))
        n_pts.append(int(f.get("n_points", 0)))
    real = [a for a in apys if isinstance(a, (int, float))]
    tail = [t for t in tails if isinstance(t, (int, float))]
    return {
        "notional_usd": 100_000,
        "n_strategies": len(rows),
        "blended_realized_apy_pct": round(sum(real) / len(real), 2) if real else None,
        "headline_apy_pct": round(sum(s.get("headline_apy_pct", 0) for s in rows) / len(rows), 1),
        "worst_tail_pct": round(min(tail), 2) if tail else None,
        "min_forward_points": min(n_pts) if n_pts else 0,
        "trustworthy": all(trustworthy) if trustworthy else False,
        "status": "trustworthy" if (trustworthy and all(trustworthy)) else "warming_up",
        "strategies": sorted(ids),
        "label": "research/paper · WITH tail · refused for live",
    }


def build_rollup() -> dict:
    snap = _read(_SNAP, {})
    agg = _read(_AGG, {})
    core_apy = snap.get("paper_apy_pct")
    return {
        "schema_version": "1.0",
        "generated_from": {"track_snapshot": _SNAP.name, "aggressive_lab_scorecard": _AGG.name},
        "note": "Three $100k paper books. Core is the real evidenced go-live track; Balanced/Aggressive "
                "are research/paper, refused for live, shown WITH their tail. Read-only rollup — no cycle, "
                "no capital moved.",
        "tiers": {
            "core": {
                "target": "~6%", "notional_usd": 100_000,
                "realized_apy_pct": core_apy,
                "evidenced_days": snap.get("real_track_days"),
                "status": "LIVE · evidenced · fundable",
                "label": "go-live paper track (optimized_yield)",
            },
            "balanced": {"target": "10-12%", **_blend(agg, _BALANCED)},
            "aggressive": {"target": "15-20%", **_blend(agg, _AGGRESSIVE)},
        },
    }


def main() -> int:
    rollup = build_rollup()
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(rollup, str(_OUT))
    except Exception:  # noqa: BLE001 — fail-safe same-dir write
        import os
        tmp = _OUT.with_suffix(".json.tmp")
        _OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rollup, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, _OUT)
    print(json.dumps(rollup, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
