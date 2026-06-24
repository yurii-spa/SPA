"""
spa_core/backtesting/tier1/correlation.py — package diversification analysis (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden.

A risk-tier package (Conservative / Balanced / Aggressive) is only genuinely diversified if
its strategies do NOT all move together. Stablecoin yields largely co-move with the DeFi
rate environment, so naively stuffing a package with the top-N net-APY strategies can give
the illusion of diversification while concentrating the same risk.

This computes each strategy's daily blended-yield series from the REAL per-protocol APY
history (data/bee/defillama_apy_history.json), takes first differences (co-movement of rate
CHANGES, not levels), and measures pairwise Pearson correlation. Per package it reports the
average pairwise correlation and a greedy LEAST-CORRELATED subset — the diversified core to
actually offer in that package. Writes data/tier1_correlation.json.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1 import oos as oos_mod

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_RESULTS = _DATA / "mass_tournament_results.json"
_VERDICT = _DATA / "tier1_verdict.json"
_OUT = _DATA / "tier1_correlation.json"

DIVERSIFY_CORR_MAX = 0.7   # add to the diversified subset only if corr < this to all selected
MIN_OVERLAP = 30           # need >= this many overlapping diffs to trust a correlation


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _global_axis(series_map: Dict[str, Dict[str, float]]) -> List[str]:
    dates = set()
    for s in series_map.values():
        dates.update(s.keys())
    return sorted(dates)


def _strategy_diff_series(allocation: dict, series_map, axis: List[str]) -> List[Optional[float]]:
    """Daily change in the allocation-weighted blended APY along the global axis (None gaps)."""
    weights = {k: float(v) for k, v in (allocation or {}).items()
               if k != "cash" and v and k in series_map}
    if not weights:
        return []
    ff = {p: oos_mod._ffill_apy(series_map[p], axis) for p in weights}
    blended: List[Optional[float]] = []
    for i in range(len(axis)):
        num, wsum = 0.0, 0.0
        for p, w in weights.items():
            a = ff[p][i]
            if a is not None:
                num += w * a
                wsum += w
        blended.append(num / wsum if wsum > 0 else None)
    # first differences
    diffs: List[Optional[float]] = [None]
    for i in range(1, len(blended)):
        if blended[i] is None or blended[i - 1] is None:
            diffs.append(None)
        else:
            diffs.append(blended[i] - blended[i - 1])
    return diffs


def _pearson(a: List[Optional[float]], b: List[Optional[float]]) -> Optional[float]:
    xs, ys = [], []
    for x, y in zip(a, b):
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    n = len(xs)
    if n < MIN_OVERLAP:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx * sy)


def _diversified_subset(ids: List[str], corr: Dict[str, Dict[str, float]],
                        rank: Dict[str, float]) -> List[str]:
    """Greedy: take the highest-net-APY strategy, then add the next whose correlation to ALL
    already-selected is < DIVERSIFY_CORR_MAX. Yields the diversified core of the package."""
    ordered = sorted(ids, key=lambda i: rank.get(i, 0.0), reverse=True)
    selected: List[str] = []
    for cand in ordered:
        ok = True
        for s in selected:
            c = corr.get(cand, {}).get(s)
            if c is not None and c >= DIVERSIFY_CORR_MAX:
                ok = False
                break
        if ok:
            selected.append(cand)
    return selected


def analyze(write: bool = True) -> dict:
    results = _load(_RESULTS, {})
    verdict = _load(_VERDICT, {})
    alloc_map = {e["id"]: e.get("allocation", {}) for e in results.get("leaderboard", [])}
    pkg_map = {e["id"]: e.get("package") for e in verdict.get("leaderboard_tier1", [])}
    net_map = {e["id"]: (e.get("net_apy_pct") or 0.0) for e in verdict.get("leaderboard_tier1", [])}

    series_map = oos_mod.load_protocol_series()
    axis = _global_axis(series_map)

    # Only strategies that have an allocation we can build a series for.
    diffs: Dict[str, List[Optional[float]]] = {}
    for sid, alloc in alloc_map.items():
        d = _strategy_diff_series(alloc, series_map, axis)
        if d and any(x is not None for x in d):
            diffs[sid] = d

    packages: Dict[str, dict] = {}
    for pkg in ("conservative", "balanced", "aggressive"):
        members = [sid for sid, p in pkg_map.items() if p == pkg and sid in diffs]
        if len(members) < 2:
            packages[pkg] = {"n": len(members), "members": members,
                             "note": "too few members for correlation"}
            continue
        # pairwise correlation
        corr: Dict[str, Dict[str, float]] = {m: {} for m in members}
        pair_vals: List[float] = []
        max_pair = {"pair": None, "corr": -2.0}
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                c = _pearson(diffs[a], diffs[b])
                if c is None:
                    continue
                corr[a][b] = corr[b][a] = c
                pair_vals.append(c)
                if c > max_pair["corr"]:
                    max_pair = {"pair": [a, b], "corr": round(c, 4)}
        avg_corr = sum(pair_vals) / len(pair_vals) if pair_vals else None
        subset = _diversified_subset(members, corr, net_map)
        packages[pkg] = {
            "n": len(members),
            "avg_pairwise_corr": round(avg_corr, 4) if avg_corr is not None else None,
            "most_correlated_pair": max_pair if max_pair["pair"] else None,
            "diversified_subset": subset,
            "diversified_subset_size": len(subset),
            "diversification_note": (
                f"Of {len(members)} candidates, {len(subset)} form a least-correlated core "
                f"(pairwise corr < {DIVERSIFY_CORR_MAX}). Offer the package from these to avoid "
                "concentrating the same rate risk."
            ),
        }

    out = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "model": "tier1_correlation",
        "llm_forbidden": True,
        "method": "Pearson on daily first-differences of allocation-weighted real APY",
        "diversify_corr_max": DIVERSIFY_CORR_MAX,
        "packages": packages,
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1corr_")
        with os.fdopen(fd, "w") as f:
            json.dump(out, f, indent=2)
        os.replace(tmp, _OUT)
    return out


if __name__ == "__main__":
    a = analyze()
    for pkg, info in a["packages"].items():
        print(f"{pkg}: n={info.get('n')} avg_corr={info.get('avg_pairwise_corr')} "
              f"diversified={info.get('diversified_subset_size')}")
        if info.get("most_correlated_pair"):
            print("   most correlated:", info["most_correlated_pair"])
