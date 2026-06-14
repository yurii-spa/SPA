"""
MP-139 — Backtest vs Paper Contour Analyzer.

Compares what the backtester (strategy_screening.json) predicted vs what is
actually happening in shadow paper trading (shadow_portfolio.json).

Read-only / advisory.  No imports from execution / risk / allocator.
Stdlib only (math, json, os, pathlib, datetime, tempfile).  exit(0) always.
Atomic writes: tmp + os.replace.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_json(path: "str | Path", default=None):
    """Return parsed JSON from *path*, or *default* on any error."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def _atomic_write_json(path: "str | Path", obj) -> None:
    """Write *obj* as JSON to *path* via tmp + os.replace (atomic)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        finally:
            raise


def _extract_strategy_index(name: str) -> "int | None":
    """
    Extract the leading numeric index from a strategy key.

    Examples::
        "s0_baseline"    → 0
        "s1_concentration" → 1
        "S0"             → 0
        "S5"             → 5
    """
    for ch in name:
        if ch.isdigit():
            return int(ch)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_backtest_results(data_dir: "str | Path | None" = None) -> dict:
    """
    Read ``data/strategy_screening.json`` and compute per-strategy ranks.

    Returns
    -------
    dict
        ``{strategy_name: {"passed": bool, "sortino": float|None,
                           "sharpe": float|None, "rank": int}}``

        *rank* is 1-based, sorted by Sharpe descending; ties broken by
        ``total_return_pct`` descending.  Missing file or empty strategies
        section → empty dict.
    """
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    raw = _read_json(data_dir / "strategy_screening.json")
    if not raw or not isinstance(raw, dict):
        return {}

    strategies = raw.get("strategies")
    if not strategies or not isinstance(strategies, dict):
        return {}

    # Gather raw values
    rows: dict[str, dict] = {}
    for name, v in strategies.items():
        if not isinstance(v, dict):
            continue

        sharpe_obj = v.get("sharpe_with_ci")
        sharpe_val: "float | None" = (
            sharpe_obj.get("value") if isinstance(sharpe_obj, dict) else None
        )

        sortino_obj = v.get("sortino")
        sortino_val: "float | None" = (
            sortino_obj.get("value") if isinstance(sortino_obj, dict) else None
        )

        rows[name] = {
            "passed": bool(v.get("passed_screening", False)),
            "sortino": sortino_val,
            "sharpe": sharpe_val,
            "_total_return": float(v.get("total_return_pct", 0.0)),
            "rank": 0,
        }

    # Sort by sharpe desc, then total_return desc (tiebreaker)
    sorted_names = sorted(
        rows.keys(),
        key=lambda n: (
            rows[n]["sharpe"] if rows[n]["sharpe"] is not None else -math.inf,
            rows[n]["_total_return"],
        ),
        reverse=True,
    )
    for rank_idx, name in enumerate(sorted_names, start=1):
        rows[name]["rank"] = rank_idx

    # Remove internal helper field before returning
    result: dict[str, dict] = {}
    for name, row in rows.items():
        result[name] = {
            "passed": row["passed"],
            "sortino": row["sortino"],
            "sharpe": row["sharpe"],
            "rank": row["rank"],
        }

    return result


def load_paper_results(data_dir: "str | Path | None" = None) -> dict:
    """
    Read ``data/shadow_portfolio.json`` and extract per-strategy paper metrics.

    Returns
    -------
    dict
        ``{strategy_name: {"equity": float, "pnl_pct": float, "days": int}}``

        *days* is the length of the ``history`` ring-buffer (= paper-trading
        days elapsed).  Missing file or empty strategies → empty dict.
    """
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    raw = _read_json(data_dir / "shadow_portfolio.json")
    if not raw or not isinstance(raw, dict):
        return {}

    strategies = raw.get("strategies")
    if not strategies or not isinstance(strategies, dict):
        return {}

    days = len(raw.get("history") or [])

    result: dict[str, dict] = {}
    for name, v in strategies.items():
        if not isinstance(v, dict):
            continue
        result[name] = {
            "equity": float(v.get("equity", 0.0)),
            "pnl_pct": float(v.get("total_return_pct", 0.0)),
            "days": days,
        }

    return result


def compute_rank_correlation(
    backtest_ranks: dict,
    paper_ranks: dict,
) -> dict:
    """
    Spearman rank correlation ρ = 1 − 6Σd²/(n(n²−1)) over *common* keys.

    Parameters
    ----------
    backtest_ranks : dict
        ``{strategy_name: rank_int}``
    paper_ranks : dict
        ``{strategy_name: rank_int}``  (same naming scheme as *backtest_ranks*)

    Returns
    -------
    dict
        ``{"rho": float|None, "n": int, "interpretation": str}``

        *interpretation*:
        - ``"CONSISTENT"``     ρ > 0.7
        - ``"WEAK_AGREEMENT"`` ρ > 0.3
        - ``"DIVERGING"``      ρ ≤ 0.3
        - ``"INSUFFICIENT …"`` n < 3
    """
    common = sorted(set(backtest_ranks.keys()) & set(paper_ranks.keys()))
    n = len(common)

    if n < 3:
        return {
            "rho": None,
            "n": n,
            "interpretation": f"INSUFFICIENT — need ≥3 common strategies, got {n}",
        }

    d_sq_sum = sum(
        (int(backtest_ranks[name]) - int(paper_ranks[name])) ** 2
        for name in common
    )

    denominator = n * (n * n - 1)
    if denominator == 0:
        return {
            "rho": None,
            "n": n,
            "interpretation": "INSUFFICIENT — degenerate ranking (n=1)",
        }

    rho = 1.0 - 6.0 * d_sq_sum / denominator
    rho = max(-1.0, min(1.0, rho))  # clamp numerical noise

    if rho > 0.7:
        interpretation = "CONSISTENT"
    elif rho > 0.3:
        interpretation = "WEAK_AGREEMENT"
    else:
        interpretation = "DIVERGING"

    return {"rho": round(rho, 4), "n": n, "interpretation": interpretation}


def compare_strategies(data_dir: "str | Path | None" = None) -> dict:
    """
    Combine backtest + paper data, compute rank correlation, build comparison.

    Strategy matching is by numeric index: ``s0_baseline`` ↔ ``S0``,
    ``s1_concentration`` ↔ ``S1``, etc.

    Returns
    -------
    dict
        Full comparison dict including ``strategies``, ``rank_correlation``,
        ``confidence``, ``summary``, ``advisory``.
    """
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    backtest = load_backtest_results(data_dir)
    paper = load_paper_results(data_dir)

    # Normalise backtest keys to S{n} scheme to align with shadow tracker keys
    bt_norm: dict[str, dict] = {}
    for k, v in backtest.items():
        idx = _extract_strategy_index(k)
        norm_key = f"S{idx}" if idx is not None else k
        bt_norm[norm_key] = v

    # Paper days: all strategies share the same days value
    paper_days: int = 0
    for v in paper.values():
        paper_days = int(v.get("days", 0))
        break

    # Confidence
    if paper_days < 7:
        confidence = "INSUFFICIENT — too few paper days"
    elif paper_days < 14:
        confidence = "LOW — approaching meaningful threshold"
    else:
        confidence = "SUFFICIENT"

    # Paper rank (by pnl_pct descending)
    paper_sorted = sorted(
        paper.keys(),
        key=lambda n: paper[n].get("pnl_pct", 0.0),
        reverse=True,
    )
    paper_rank_map: dict[str, int] = {
        name: rank for rank, name in enumerate(paper_sorted, start=1)
    }

    # Backtest rank map (already S{n} keyed)
    bt_rank_map: dict[str, int] = {k: v["rank"] for k, v in bt_norm.items()}

    # Rank correlation (skip if insufficient paper days)
    if paper_days < 7:
        rank_corr: dict = {
            "rho": None,
            "n": len(bt_norm),
            "interpretation": "INSUFFICIENT — too few paper days",
        }
    else:
        rank_corr = compute_rank_correlation(bt_rank_map, paper_rank_map)

    # Per-strategy detail list (union of all known names, sorted)
    all_names = sorted(
        set(bt_norm.keys()) | set(paper.keys()),
        key=lambda n: (_extract_strategy_index(n) if _extract_strategy_index(n) is not None else 99, n),
    )

    strategies_list: list[dict] = []
    for name in all_names:
        bt_data = bt_norm.get(name, {})
        p_data = paper.get(name, {})

        bt_rank = bt_rank_map.get(name)
        p_rank = paper_rank_map.get(name)

        if bt_rank is not None and p_rank is not None:
            rank_delta = p_rank - bt_rank
            if rank_delta == 0:
                note = "On track"
            elif rank_delta > 0:
                note = f"Underperforming vs backtest by {rank_delta} rank(s)"
            else:
                note = f"Outperforming vs backtest by {abs(rank_delta)} rank(s)"
        elif bt_rank is None:
            rank_delta = None
            note = "No backtest data"
        else:
            rank_delta = None
            note = "No paper data"

        strategies_list.append({
            "name": name,
            "backtest_rank": bt_rank,
            "paper_rank": p_rank,
            "backtest_sharpe": bt_data.get("sharpe"),
            "paper_pnl_pct": p_data.get("pnl_pct"),
            "rank_delta": rank_delta,
            "note": note,
        })

    # Summary string
    rank_parts = []
    for s in strategies_list:
        if s["rank_delta"] is not None:
            delta = s["rank_delta"]
            sign = "+" if delta >= 0 else ""
            rank_parts.append(
                f"{s['name']}={s['paper_rank']} vs backtest={s['backtest_rank']} ({sign}{delta})"
            )
    ranking_str = ", ".join(rank_parts) if rank_parts else "no matched strategies"

    summary = (
        f"{paper_days} paper days (need ≥14 for meaningful correlation). "
        f"Ranking: {ranking_str}"
    )

    if paper_days < 14:
        advisory = (
            "Wait for 14+ paper days before trusting rank correlation. "
            "Current data directional only."
        )
    else:
        rho_disp = rank_corr.get("rho")
        interp = rank_corr.get("interpretation", "")
        advisory = (
            f"Rank correlation ρ={rho_disp}: {interp}. "
            "Monitor for sustained divergence (|rank_delta| > 2)."
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_days": paper_days,
        "confidence": confidence,
        "rank_correlation": rank_corr,
        "strategies": strategies_list,
        "summary": summary,
        "advisory": advisory,
    }


def run_comparison(
    data_dir: "str | Path | None" = None,
    output_path: "str | Path | None" = None,
) -> dict:
    """
    Run :func:`compare_strategies` and atomically write the result.

    Parameters
    ----------
    data_dir : path, optional
        Override data directory (default: ``<repo>/data``).
    output_path : path, optional
        Override output file path (default: ``<data_dir>/backtest_vs_paper.json``).

    Returns
    -------
    dict
        The comparison result dict (same as :func:`compare_strategies`).
    """
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    result = compare_strategies(data_dir)
    out_path = Path(output_path) if output_path else data_dir / "backtest_vs_paper.json"
    _atomic_write_json(out_path, result)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-139 Backtest vs Paper Contour Analyzer — read-only advisory"
    )
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--check",
        action="store_true",
        help="Compute and print without writing (default when neither flag given)",
    )
    grp.add_argument(
        "--run",
        action="store_true",
        help="Compute + atomically write to data/backtest_vs_paper.json",
    )
    parser.add_argument("--data-dir", default=None, help="Override data directory path")
    args = parser.parse_args()

    if args.run:
        result = run_comparison(data_dir=args.data_dir)
        print("Written → data/backtest_vs_paper.json", file=sys.stderr)
    else:
        result = compare_strategies(data_dir=args.data_dir)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0)
