"""
spa_core/backtesting/tier1/packages.py — build the offered risk-tier PACKAGES (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. Combines the Tier-1 verdict
(validated strategies + net-of-cost APY + package band) with the correlation analysis
(least-correlated diversified core) into the actual product packages shown to users:

    Conservative / Balanced / Aggressive — each = (validated ∩ diversified core) for that
    tier, with a blended net APY, worst drawdown, capacity and member list.

Output: data/tier1_packages.json. This is the bridge from validation → the risk-tiered
"packages" product (the landing's tiers), backed by real data + OOS + capacity, not raw rank.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path

from spa_core.backtesting.tier1.tail_risk import risk_adjusted_net_apy, strategy_tail_risk

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_VERDICT = _DATA / "tier1_verdict.json"
_CORR = _DATA / "tier1_correlation.json"
_RESULTS = _DATA / "mass_tournament_results.json"
_OUT = _DATA / "tier1_packages.json"

TIER_LABELS = {
    "conservative": "Conservative",
    "balanced": "Balanced",
    "aggressive": "Aggressive",
}


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def build(write: bool = True) -> dict:
    verdict = _load(_VERDICT, {})
    corr = _load(_CORR, {})
    results = _load(_RESULTS, {})
    alloc_map = {e["id"]: e.get("allocation", {}) for e in results.get("leaderboard", [])}
    board = {s["id"]: s for s in verdict.get("leaderboard_tier1", [])}
    pkg_meta = verdict.get("packages", {})

    packages = {}
    for key, label in TIER_LABELS.items():
        band = pkg_meta.get(key, {})
        validated_ids = [sid for sid, s in board.items()
                         if s.get("package") == key and s.get("validated")]
        core = (corr.get("packages", {}).get(key, {}) or {}).get("diversified_subset", []) or []
        # offered = validated AND in the diversified core (fall back to validated if no corr)
        offered = [sid for sid in validated_ids if sid in core] or validated_ids
        members = []
        nets, dds, caps, radj = [], [], [], []
        for sid in offered:
            s = board[sid]
            ra = risk_adjusted_net_apy(s.get("net_apy_pct") or 0.0, alloc_map.get(sid, {}))
            members.append({
                "id": sid,
                "net_apy_pct": s.get("net_apy_pct"),
                "tail_risk_pct": ra["tail_risk_pct"],
                "risk_adjusted_apy_pct": ra["risk_adjusted_apy_pct"],
                "tier_mix": ra["tier_mix"],
                "max_dd_pct": s.get("max_dd_pct"),
                "oos_out_sample_apy_pct": s.get("oos_out_sample_apy_pct"),
                "capacity_aum_usd": s.get("capacity_aum_usd"),
                "grade": s.get("tier1_grade"),
            })
            radj.append(ra["risk_adjusted_apy_pct"])
            if s.get("net_apy_pct") is not None:
                nets.append(s["net_apy_pct"])
            if s.get("max_dd_pct") is not None:
                dds.append(abs(s["max_dd_pct"]))
            if s.get("capacity_aum_usd"):
                caps.append(s["capacity_aum_usd"])
        packages[key] = {
            "label": label,
            "target_apy_band_pct": band.get("net_apy_band"),
            "max_dd_limit_pct": band.get("max_dd_limit"),
            "n_offered": len(members),
            "n_validated_in_band": len(validated_ids),
            "blended_net_apy_pct": round(sum(nets) / len(nets), 3) if nets else None,
            "blended_risk_adjusted_apy_pct": round(sum(radj) / len(radj), 3) if radj else None,
            "worst_dd_pct": round(max(dds), 3) if dds else None,
            "min_capacity_aum_usd": min(caps) if caps else None,
            "strategies": members,
            "status": "available" if members else "no_validated_strategies_yet",
        }

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_packages",
        "llm_forbidden": True,
        "basis": "validated (real-data backtest + net-of-cost + OOS + capacity) ∩ diversified core",
        "regime": verdict.get("regime"),
        "packages": packages,
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1pkg_")
        with os.fdopen(fd, "w") as f:
            json.dump(out, f, indent=2)
        os.replace(tmp, _OUT)
    return out


if __name__ == "__main__":
    o = build()
    for k, p in o["packages"].items():
        print(f"{p['label']}: {p['status']} | offered={p['n_offered']} "
              f"blended_net_apy={p['blended_net_apy_pct']} worst_dd={p['worst_dd_pct']}")
