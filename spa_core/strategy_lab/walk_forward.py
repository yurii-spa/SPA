"""
spa_core/strategy_lab/walk_forward.py — LAB-SLEEVE walk-forward + capacity.

The MISSING half of the promotion loop. promotion.py scores each LAB SLEEVE (variant_n,
eth_lst_neutral, btc_neutral, rwa_sleeve, engine_a/b/c, …) but its walk-forward + capacity
criteria came back PENDING because the only WF source (data/tier1_walk_forward.json) is keyed
by TOURNAMENT-strategy ids (s27/s65/live_portfolio), NOT lab-sleeve ids. So no lab sleeve could
ever reach PAPER_CANDIDATE on real evidence.

This module closes that gap by computing walk-forward + capacity FOR the lab sleeves themselves,
reusing the existing Tier-1 method (spa_core.backtesting.tier1.walk_forward_full):

PART A — ROLLING WALK-FORWARD on each sleeve's own daily EQUITY series.
    The lab backtest already persists a per-sleeve `equity_series` in
    data/strategy_lab_backtest.json. We run consecutive train/test windows over THAT curve
    (same train/test/step + return-band + consistency rule as walk_forward_full: a window
    "holds" when the test annualized return is positive AND within +/-RETURN_BAND of the train
    return; `wf_robust` when >= WF_CONSISTENCY_PASS of windows hold). This re-uses
    walk_forward_full._windows / _annualized_return_pct / _max_drawdown_pct verbatim — no
    re-implementation of the method.

PART B — CAPACITY (max-safe-AUM) for the sleeve.
    Lab sleeves are abstract strategy BOOKS, not multi-pool weight dicts, so we cannot reuse
    capacity_at_aum() (which needs per-protocol weights vs per-pool TVLs). Instead we size the
    sleeve against the DEPTH of the venue(s) it deploys into, taken from a per-sleeve config
    `capacity` block: max_safe_aum_usd = market_tvl_usd * max_pool_pct (default 2%, the same cap
    walk_forward_full uses). FAIL-CLOSED: a sleeve with no capacity config gets max_safe_aum_usd
    = None → its capacity criterion stays PENDING (we never claim unbounded capacity).

OUTPUT (data/strategy_lab_walk_forward.json), keyed BY LAB-SLEEVE ID, in the FLATTENED shape
promotion.score_sleeve already understands:
    {sleeve_id: {
        "status": "ok"|"insufficient_history"|"insufficient_data",
        "consistency_pct": float|None,
        "wf_robust": bool|None,
        "n_windows": int,
        "max_safe_aum_usd": float|None,
        "capacity": {"status": ..., "max_safe_aum_usd": float|None, ...},
        "walk_forward": {... full window detail ...},
    }}

stdlib only. Deterministic. LLM FORBIDDEN. Atomic writes (tmp + shutil.move, repo rule #4).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from spa_core.strategy_lab import config as lab_config

# Reuse the Tier-1 walk-forward METHOD (windows, returns, drawdown, thresholds) — do NOT
# re-implement it. Only the data source (a sleeve equity series vs a multi-pool blend) differs.
from spa_core.backtesting.tier1.walk_forward_full import (
    MIN_TEST_RETURN_PCT,
    RETURN_BAND,
    STEP_DAYS,
    TEST_DAYS,
    TRAIN_DAYS,
    WF_CONSISTENCY_PASS,
    _annualized_return_pct,
    _max_drawdown_pct,
    _windows,
)

_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
_DATA = _ROOT / "data"
DEFAULT_BACKTEST = _DATA / "strategy_lab_backtest.json"
DEFAULT_OUT = _DATA / "strategy_lab_walk_forward.json"

# Default cap on any single position as a fraction of the venue depth (mirrors
# walk_forward_full.CAPACITY_MAX_POOL_PCT = 2%). Overridable per-sleeve via config.
DEFAULT_MAX_POOL_PCT = 0.02


# ── atomic JSON write (repo rule #4) ──────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        shutil.move(tmp, str(path))  # atomic, cross-device safe
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


# ── PART A — rolling walk-forward on a sleeve's equity series ──────────────────────────────────
def walk_forward_equity(
    equity_series: Sequence[float],
    train: int = TRAIN_DAYS,
    test: int = TEST_DAYS,
    step: int = STEP_DAYS,
) -> dict:
    """Rolling walk-forward on a sleeve's own compounded EQUITY series.

    Reuses the Tier-1 method (walk_forward_full): for each consecutive train/test window,
    compute train- and test-period annualized return + the test max drawdown; a window "holds"
    when the test return is positive AND within +/-RETURN_BAND of the train return; `wf_robust`
    when >= WF_CONSISTENCY_PASS of windows hold.

    Args:
        equity_series: the sleeve's daily equity values (>=2 points, monotonic by index).
        train/test/step: window sizes (default = the Tier-1 values).

    Returns (FAIL-CLOSED on too-short / empty input — never fabricates a pass):
        {status, n_points, train, test, step, n_windows, consistency_pct, wf_robust, windows}
    """
    eq = [float(x) for x in (equity_series or []) if x is not None]
    n = len(eq)
    if n < 2:
        return {
            "status": "insufficient_data", "n_points": n, "train": train, "test": test,
            "step": step, "n_windows": 0, "consistency_pct": None, "wf_robust": None,
            "windows": [],
        }
    if n < train + test:
        return {
            "status": "insufficient_history", "n_points": n, "train": train, "test": test,
            "step": step, "needed_points": train + test, "n_windows": 0,
            "consistency_pct": None, "wf_robust": None, "windows": [],
        }

    windows: List[dict] = []
    holds = 0
    for (tr_lo, tr_hi, te_lo, te_hi) in _windows(n, train, test, step):
        train_eq = eq[tr_lo:tr_hi]
        test_eq = eq[te_lo:te_hi]
        tr_ret = _annualized_return_pct(train_eq)
        te_ret = _annualized_return_pct(test_eq)
        te_dd = _max_drawdown_pct(test_eq)
        lo_band = tr_ret * (1.0 - RETURN_BAND)
        hi_band = tr_ret * (1.0 + RETURN_BAND)
        in_band = (lo_band <= te_ret <= hi_band) if tr_ret > 0 else (te_ret >= 0)
        positive = te_ret > MIN_TEST_RETURN_PCT
        held = bool(positive and in_band)
        if held:
            holds += 1
        windows.append({
            "train_idx": [tr_lo, tr_hi],
            "test_idx": [te_lo, te_hi],
            "train_return_pct": round(tr_ret, 4),
            "test_return_pct": round(te_ret, 4),
            "test_max_dd_pct": round(te_dd, 4),
            "in_band": bool(in_band),
            "positive": bool(positive),
            "holds": held,
        })

    n_windows = len(windows)
    if n_windows == 0:
        return {
            "status": "insufficient_history", "n_points": n, "train": train, "test": test,
            "step": step, "n_windows": 0, "consistency_pct": None, "wf_robust": None,
            "windows": [],
        }
    consistency = holds / n_windows
    return {
        "status": "ok",
        "n_points": n,
        "train": train, "test": test, "step": step,
        "n_windows": n_windows,
        "consistency_pct": round(consistency * 100.0, 2),
        "wf_robust": bool(consistency >= WF_CONSISTENCY_PASS),
        "windows": windows,
    }


# ── PART B — capacity (max-safe-AUM) for a sleeve ──────────────────────────────────────────────
def capacity_for_sleeve(cap_cfg: Optional[dict]) -> dict:
    """Max-safe-AUM for a sleeve from its config `capacity` block.

    A lab sleeve is an abstract book, so capacity = how much AUM it can deploy before a single
    position would exceed the liquidity cap of the venue(s) it trades:
        max_safe_aum_usd = market_tvl_usd * max_pool_pct
    where market_tvl_usd is the aggregate depth of the sleeve's venue(s) and max_pool_pct is the
    single-position cap (default 2%, the same cap walk_forward_full uses).

    FAIL-CLOSED: no capacity config / no positive market_tvl_usd → max_safe_aum_usd = None
    (capacity criterion stays PENDING; we never claim unbounded capacity).

    Returns {status, market_tvl_usd, max_pool_pct, max_safe_aum_usd}.
    """
    if not isinstance(cap_cfg, dict):
        return {"status": "insufficient_data", "market_tvl_usd": None,
                "max_pool_pct": None, "max_safe_aum_usd": None}
    tvl = cap_cfg.get("market_tvl_usd")
    try:
        tvl = float(tvl) if tvl is not None else None
    except (TypeError, ValueError):
        tvl = None
    if tvl is None or tvl <= 0:
        return {"status": "insufficient_data", "market_tvl_usd": None,
                "max_pool_pct": None, "max_safe_aum_usd": None}
    pct = cap_cfg.get("max_pool_pct", DEFAULT_MAX_POOL_PCT)
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = DEFAULT_MAX_POOL_PCT
    if pct <= 0:
        pct = DEFAULT_MAX_POOL_PCT
    max_safe = tvl * pct
    return {
        "status": "ok",
        "market_tvl_usd": round(tvl, 2),
        "max_pool_pct": round(pct * 100.0, 4),
        "max_safe_aum_usd": round(max_safe, 2),
    }


def _capacity_cfg_for(sid: str, config: dict) -> Optional[dict]:
    """The per-sleeve `capacity` config block, if present.

    Looks first at strategies[sid]["capacity"], then at a top-level capacity[sid] map — either
    placement is accepted so the SSOT config can carry capacity wherever it is cleanest.
    """
    strategies = (config or {}).get("strategies", {}) or {}
    blk = strategies.get(sid)
    if isinstance(blk, dict) and isinstance(blk.get("capacity"), dict):
        return blk["capacity"]
    top = (config or {}).get("capacity")
    if isinstance(top, dict) and isinstance(top.get(sid), dict):
        return top[sid]
    return None


# ── per-sleeve flattened block (the shape promotion.score_sleeve reads) ─────────────────────────
def _sleeve_block(equity_series: Sequence[float], cap_cfg: Optional[dict]) -> dict:
    wf = walk_forward_equity(equity_series)
    cap = capacity_for_sleeve(cap_cfg)
    # Flattened shape so promotion.score_sleeve reads status/consistency_pct/wf_robust at the
    # TOP level and capacity.max_safe_aum_usd via .get("capacity"). The full window/capacity
    # detail is nested for auditing.
    return {
        "status": wf["status"],
        "consistency_pct": wf.get("consistency_pct"),
        "wf_robust": wf.get("wf_robust"),
        "n_windows": wf.get("n_windows", 0),
        "max_safe_aum_usd": cap.get("max_safe_aum_usd"),
        "capacity": cap,
        "walk_forward": wf,
    }


# ── full report ────────────────────────────────────────────────────────────────────────────────
def build_report(
    write: bool = True,
    backtest_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    config: Optional[dict] = None,
    backtest: Optional[dict] = None,
) -> dict:
    """Compute lab-sleeve walk-forward + capacity for EVERY sleeve in the lab backtest and
    (optionally) write data/strategy_lab_walk_forward.json atomically, KEYED BY SLEEVE ID.

    Args:
        write:         write the JSON when True (default). False = compute only.
        backtest_path: override the backtest JSON path (tests/hermetic).
        out_path:      override the output path.
        config:        a full lab config dict (tests/hermetic). None → load the SSOT.
        backtest:      an injected backtest result dict (tests/determinism). When given it is
                       used verbatim and backtest_path is ignored.

    Returns:
        {generated_at, model, llm_forbidden, method, n_sleeves, sleeves:{sleeve_id:{...}}}
    Fail-CLOSED: a missing backtest → an empty sleeves map (we never fabricate WF evidence).
    The benchmark row (rwa_floor) is excluded — it is a reference, not a promotable sleeve.
    """
    cfg = config if config is not None else lab_config.load_config()
    bt = backtest if backtest is not None else _read_json(
        Path(backtest_path) if backtest_path else DEFAULT_BACKTEST
    )

    sleeves: Dict[str, dict] = {}
    if isinstance(bt, dict):
        strategies = bt.get("strategies", {}) or {}
        for sid in sorted(strategies.keys()):
            blk = strategies[sid]
            if not isinstance(blk, dict):
                continue
            if blk.get("is_benchmark"):
                continue
            equity_series = blk.get("equity_series") or []
            cap_cfg = _capacity_cfg_for(sid, cfg)
            sleeves[sid] = _sleeve_block(equity_series, cap_cfg)

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "strategy_lab_walk_forward",
        "llm_forbidden": True,
        "method": {
            "part_a": (
                f"rolling walk-forward on each sleeve's own equity series; train={TRAIN_DAYS} "
                f"test={TEST_DAYS} step={STEP_DAYS}; window holds when test annualized return "
                f"> 0 AND within +/-{int(RETURN_BAND * 100)}% of train return; wf_robust when "
                f">= {int(WF_CONSISTENCY_PASS * 100)}% of windows hold "
                "(reuses spa_core.backtesting.tier1.walk_forward_full)"
            ),
            "part_b": (
                "capacity = market_tvl_usd * max_pool_pct (default 2%) from the per-sleeve "
                "config 'capacity' block; absent config → None (PENDING, fail-closed)"
            ),
        },
        "n_sleeves": len(sleeves),
        "sleeves": sleeves,
    }

    if write:
        _atomic_write_json(Path(out_path) if out_path else DEFAULT_OUT, report)
    return report


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────
def _print_table(report: dict) -> None:
    print("Strategy Lab — Lab-Sleeve Walk-Forward + Capacity")
    print(report["method"]["part_a"])
    print(report["method"]["part_b"])
    print()
    hdr = f"{'sleeve':22s} {'status':22s} {'wf%':>7s} {'robust':>7s} {'nwin':>5s} {'maxAUM($)':>16s}"
    print(hdr)
    print("-" * len(hdr))
    for sid in sorted(report.get("sleeves", {}).keys()):
        b = report["sleeves"][sid]
        wf = b.get("consistency_pct")
        wf_s = f"{wf:7.2f}" if isinstance(wf, (int, float)) else f"{'—':>7s}"
        rob = b.get("wf_robust")
        rob_s = ("yes" if rob else "no") if rob is not None else "—"
        aum = b.get("max_safe_aum_usd")
        aum_s = f"{aum:16,.0f}" if isinstance(aum, (int, float)) else f"{'—':>16s}"
        print(f"{sid:22s} {str(b.get('status')):22s} {wf_s} {rob_s:>7s} "
              f"{b.get('n_windows', 0):5d} {aum_s}")


def main() -> int:
    report = build_report(write=True)
    _print_table(report)
    print(f"\nWrote {DEFAULT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
