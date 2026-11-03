"""
scripts/edge_crisis_recovery_profile.py — #153 CRP: Crisis Recovery Profile

IDEA: Size positions INVERSE to post-crisis recovery time, not by crisis depth (maxDD).
A book that loses 10% but recovers in 30 days is DIFFERENT from a book that loses 5% and
takes 300 days to recover (or never does). Current sizers (QUIET-N, CADS) use crisis DEPTH.
This uses crisis RECOVERY SPEED.

MECHANICS:
  For each book × each crisis it participated in:
    1. pre_crisis_peak = equity the day BEFORE the crisis window starts
    2. trough = min equity during the window
    3. recovery_day = first day AFTER window end where equity >= pre_crisis_peak
       If never recovered within backtest horizon: infinity (penalised as 2× remaining days)
  recovery_velocity(book) = 1 / mean(recovery_days across all crises with a loss > 0)
  Weights proportional to recovery_velocity, capped at MAX_BOOK_WEIGHT.

HYPOTHESIS: Books that recover quickly offer better risk-adjusted returns than books with
comparable APY but slower recovery (because slow recovery = permanent capital haircut risk).

BASELINE: equal-weight portfolio of 5 non-thin books.
COMPETITOR: CRP-weighted portfolio.
TRAIN/TEST SPLIT: 2025-06-30 (same as #151).

All numbers are [backtest] — NOT realized.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── constants ──────────────────────────────────────────────────────────────────
MAX_BOOK_WEIGHT = 0.40       # cap per book
INF_PENALTY_MULTIPLIER = 2   # infinity = 2x remaining backtest days
ENTRY_TOLL_BPS = 96          # basis points one-time deployment cost (#149 convention)
ELIGIBLE_BOOKS = [
    "susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"
]  # thin_new excluded (no backtest)

TRAIN_END = datetime.date(2025, 6, 30)
TEST_START = datetime.date(2025, 7, 1)

CRISIS_WINDOWS = [
    {"key": "eth_crash_2024_08",    "from": datetime.date(2024, 8, 1),  "to": datetime.date(2024, 8, 31)},
    {"key": "usde_unwind_2025_10",  "from": datetime.date(2025, 10, 1), "to": datetime.date(2025, 10, 31)},
    {"key": "rseth_depeg_2026_04",  "from": datetime.date(2026, 4, 1),  "to": datetime.date(2026, 4, 30)},
]


# ── data loading ───────────────────────────────────────────────────────────────

def _load_series(data_dir: Path, book_id: str) -> List[dict]:
    p = data_dir / book_id / "realized_series.jsonl"
    rows = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_backtest_series(data_dir: Path, book_id: str) -> List[Tuple[datetime.date, float]]:
    """Return [(date, equity_usd)] for backtest phase only, sorted by date."""
    rows = _load_series(data_dir, book_id)
    result = []
    for r in rows:
        if r.get("phase") == "backtest":
            result.append((datetime.date.fromisoformat(r["date"]), float(r["equity_usd"])))
    result.sort()
    return result


# ── recovery profile computation ───────────────────────────────────────────────

def compute_recovery_days(
    series: List[Tuple[datetime.date, float]],
    crisis: dict,
) -> Optional[float]:
    """
    For one book × one crisis window, compute how many days after the window end
    until the equity returns to the pre-crisis peak (or None if no loss in that window).

    Returns:
        float: days to recovery (0 if instantaneous, large if slow)
        None: the book had no loss in this window (> 0 loss criterion: equity drop > 0.01%)
    """
    crisis_from = crisis["from"]
    crisis_to = crisis["to"]

    # Build a quick date→equity lookup
    eq_map: Dict[datetime.date, float] = {d: e for d, e in series}
    dates = sorted(eq_map.keys())

    # Find the last date before the crisis starts
    pre_dates = [d for d in dates if d < crisis_from]
    if not pre_dates:
        return None  # book didn't exist before crisis
    pre_peak_date = max(pre_dates)
    pre_peak_equity = eq_map[pre_peak_date]

    # Find trough during the window
    window_dates = [d for d in dates if crisis_from <= d <= crisis_to]
    if not window_dates:
        return None  # crisis window not in this series
    trough_equity = min(eq_map[d] for d in window_dates)

    # Check if there was a meaningful loss
    loss_frac = (pre_peak_equity - trough_equity) / pre_peak_equity
    if loss_frac < 0.0001:  # < 0.01% — no meaningful loss
        return None

    # Find first day AFTER the window where equity >= pre_peak
    post_dates = [d for d in dates if d > crisis_to]
    trough_date = min(window_dates, key=lambda d: eq_map[d])

    for d in sorted(post_dates):
        if eq_map[d] >= pre_peak_equity:
            return float((d - trough_date).days)

    # Never recovered: penalise
    remaining_days = len(post_dates)
    return float(remaining_days * INF_PENALTY_MULTIPLIER)


def recovery_velocity(
    series: List[Tuple[datetime.date, float]],
    crises: List[dict],
    series_end: datetime.date,
) -> Tuple[float, List[dict]]:
    """
    Compute recovery velocity (1/mean_recovery_days) for the crises BEFORE series_end.
    Returns (velocity, crisis_details_list).
    velocity = 0.0 means infinitely slow (never recovered).
    """
    details = []
    recovery_days_list = []
    horizon_days = (series_end - datetime.date(2024, 7, 1)).days

    for crisis in crises:
        # Only use crises that start before series_end (for train/test split)
        if crisis["from"] >= series_end:
            continue
        rd = compute_recovery_days(series, crisis)
        if rd is None:
            details.append({
                "crisis": crisis["key"],
                "status": "no_loss",
                "recovery_days": None,
            })
            continue
        if rd >= horizon_days:
            details.append({
                "crisis": crisis["key"],
                "status": "never_recovered",
                "recovery_days": float("inf"),
            })
            recovery_days_list.append(float(horizon_days * INF_PENALTY_MULTIPLIER))
        else:
            details.append({
                "crisis": crisis["key"],
                "status": "recovered",
                "recovery_days": rd,
            })
            recovery_days_list.append(rd)

    if not recovery_days_list:
        # No crises participated in — treat as very fast (same as best observed)
        return float("inf"), details

    mean_rd = sum(recovery_days_list) / len(recovery_days_list)
    velocity = 1.0 / mean_rd if mean_rd > 0 else float("inf")
    return velocity, details


# ── portfolio simulation ────────────────────────────────────────────────────────

def _daily_return(series: List[Tuple[datetime.date, float]], d: datetime.date) -> Optional[float]:
    """Return fractional daily return for date d. None if date or prev date missing."""
    eq_map: Dict[datetime.date, float] = {day: eq for day, eq in series}
    dates_sorted = sorted(eq_map.keys())
    if d not in eq_map:
        return None
    idx = dates_sorted.index(d)
    if idx == 0:
        return None
    prev_eq = eq_map[dates_sorted[idx - 1]]
    return (eq_map[d] - prev_eq) / prev_eq if prev_eq > 0 else None


def run_portfolio(
    series_map: Dict[str, List[Tuple[datetime.date, float]]],
    weights: Dict[str, float],
    start: datetime.date,
    end: datetime.date,
    toll_bps: float = ENTRY_TOLL_BPS,
) -> Tuple[float, float, float]:
    """
    Simulate a static-weight portfolio from start to end.
    Returns (apy_pct [backtest], max_drawdown_pct [backtest], calmar [backtest]).
    """
    # Collect all dates in range
    all_dates = set()
    for sid, ser in series_map.items():
        if weights.get(sid, 0.0) > 0:
            for d, _ in ser:
                if start <= d <= end:
                    all_dates.add(d)
    dates = sorted(all_dates)
    if len(dates) < 2:
        return 0.0, 0.0, float("nan")

    portfolio = 100_000.0
    # Apply entry toll on day 1 (full portfolio)
    portfolio *= 1.0 - (toll_bps / 10_000.0)

    peak = portfolio
    max_dd = 0.0

    for d in dates[1:]:
        daily_port_ret = 0.0
        total_weight = 0.0
        for sid, w in weights.items():
            if w <= 0:
                continue
            r = _daily_return(series_map[sid], d)
            if r is not None:
                daily_port_ret += w * r
                total_weight += w
        if total_weight > 0:
            daily_port_ret /= total_weight
        portfolio *= 1.0 + daily_port_ret
        if portfolio > peak:
            peak = portfolio
        dd = (peak - portfolio) / peak
        if dd > max_dd:
            max_dd = dd

    days = (dates[-1] - dates[0]).days
    years = days / 365.25
    if years <= 0 or portfolio <= 0:
        return 0.0, max_dd * 100, float("nan")
    apy = ((portfolio / 100_000.0) ** (1.0 / years) - 1.0) * 100.0
    max_dd_pct = max_dd * 100.0
    calmar = apy / max_dd_pct if max_dd_pct > 0.0001 else float("nan")
    return apy, max_dd_pct, calmar


def normalize_weights(raw: Dict[str, float], cap: float = MAX_BOOK_WEIGHT) -> Dict[str, float]:
    """Iterative normalization with per-book cap."""
    w = {k: v for k, v in raw.items() if v > 0}
    if not w:
        return {}
    total = sum(w.values())
    if total <= 0:
        return {}
    w = {k: v / total for k, v in w.items()}
    # Iterative capping
    for _ in range(100):
        capped = {k: min(v, cap) for k, v in w.items()}
        total_capped = sum(capped.values())
        if total_capped <= 0:
            return capped
        w = {k: v / total_capped for k, v in capped.items()}
        if all(v <= cap + 1e-9 for v in w.values()):
            break
    return w


# ── main report ────────────────────────────────────────────────────────────────

def crp_report(data_dir: Path, *, now: Optional[datetime.date] = None) -> dict:
    """Run the full CRP analysis. Returns a structured report dict."""
    _ = now  # reserved for test injection; not used for statics

    series_map: Dict[str, List[Tuple[datetime.date, float]]] = {}
    for sid in ELIGIBLE_BOOKS:
        series_map[sid] = load_backtest_series(data_dir, sid)

    backtest_end = datetime.date(2026, 5, 31)

    # ── TRAIN: compute recovery velocities using crises up to TRAIN_END ────────
    train_crises = [c for c in CRISIS_WINDOWS if c["from"] < TRAIN_END]
    velocity_train: Dict[str, float] = {}
    profile_details: Dict[str, list] = {}

    for sid in ELIGIBLE_BOOKS:
        vel, details = recovery_velocity(series_map[sid], train_crises, TRAIN_END)
        velocity_train[sid] = vel
        profile_details[sid] = details

    # Handle "inf" velocities (no crises hit): assign the max finite velocity
    finite_vels = [v for v in velocity_train.values() if v != float("inf")]
    max_finite = max(finite_vels) if finite_vels else 1.0
    velocity_capped = {k: (v if v != float("inf") else max_finite) for k, v in velocity_train.items()}

    crp_weights_train = normalize_weights(velocity_capped)
    ew_weights = {sid: 1.0 / len(ELIGIBLE_BOOKS) for sid in ELIGIBLE_BOOKS}

    # ── Run portfolios (TRAIN period) ─────────────────────────────────────────
    crp_train = run_portfolio(series_map, crp_weights_train, datetime.date(2024, 7, 1), TRAIN_END)
    ew_train  = run_portfolio(series_map, ew_weights,        datetime.date(2024, 7, 1), TRAIN_END)

    # ── Run portfolios (TEST period) ──────────────────────────────────────────
    crp_test  = run_portfolio(series_map, crp_weights_train, TEST_START, backtest_end)
    ew_test   = run_portfolio(series_map, ew_weights,        TEST_START, backtest_end)

    # ── Full period ───────────────────────────────────────────────────────────
    crp_full  = run_portfolio(series_map, crp_weights_train, datetime.date(2024, 7, 1), backtest_end)
    ew_full   = run_portfolio(series_map, ew_weights,        datetime.date(2024, 7, 1), backtest_end)

    # Compute per-book recovery detail summary
    recovery_summary = {}
    for sid in ELIGIBLE_BOOKS:
        details = profile_details[sid]
        recovery_days_list = [
            d["recovery_days"] for d in details
            if d["status"] in ("recovered", "never_recovered")
        ]
        if recovery_days_list:
            finite_rds = [r for r in recovery_days_list if r != float("inf")]
            mean_rd = (sum(finite_rds) / len(finite_rds)) if finite_rds else None
            never_recovered_count = sum(1 for d in details if d["status"] == "never_recovered")
        else:
            mean_rd = None
            never_recovered_count = 0
        recovery_summary[sid] = {
            "velocity": velocity_train[sid],
            "weight_crp": crp_weights_train.get(sid, 0.0),
            "mean_recovery_days": mean_rd,
            "never_recovered_count": never_recovered_count,
            "crisis_details": details,
        }

    return {
        "idea": "CRP — Crisis Recovery Profile",
        "idea_number": 153,
        "sizer": "inverse recovery time (train crises only)",
        "train_end": TRAIN_END.isoformat(),
        "test_start": TEST_START.isoformat(),
        "books": ELIGIBLE_BOOKS,
        "crp_weights": crp_weights_train,
        "ew_weights": ew_weights,
        "recovery_summary": recovery_summary,
        "results": {
            "train": {"crp": crp_train, "ew": ew_train},
            "test":  {"crp": crp_test,  "ew": ew_test},
            "full":  {"crp": crp_full,  "ew": ew_full},
        },
        "evidence_level": "L0 — backtest only, deterministic fixture, NOT realized",
    }


def print_report(r: dict) -> None:
    res = r["results"]

    print("=" * 72)
    print(f"  #153 CRP — Crisis Recovery Profile  [backtest / bt]")
    print("=" * 72)
    print(f"  Idea: size books INVERSE to post-crisis recovery time, not maxDD depth.")
    print(f"  Hypothesis: faster recovery → better risk-adjusted capital efficiency.")
    print()

    print("── Recovery profile (TRAIN crises: eth_crash_2024_08 + usde_unwind_2025_10) ──")
    print(f"  {'book':<18} {'vel×1000':>10} {'CRP w%':>8} {'EW w%':>7}  {'mean_recov_days':>16}  {'never':>5}")
    print(f"  {'-'*18} {'-'*10} {'-'*8} {'-'*7}  {'-'*16}  {'-'*5}")
    for sid in ELIGIBLE_BOOKS:
        rs = r["recovery_summary"][sid]
        vel_k = rs["velocity"] * 1000 if rs["velocity"] != float("inf") else float("inf")
        vel_str = f"{vel_k:10.3f}" if vel_k != float("inf") else "      ∞   "
        mrd = rs["mean_recovery_days"]
        mrd_str = f"{mrd:16.1f}" if mrd is not None else "            None"
        print(f"  {sid:<18} {vel_str} {rs['weight_crp']*100:7.1f}% {r['ew_weights'][sid]*100:6.1f}%  {mrd_str}  {rs['never_recovered_count']:5d}")

    print()
    print("── Portfolio results (TRAIN 2024-07-01..2025-06-30) [bt] ──────────────────")
    print(f"  {'portfolio':<12} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8}")
    for name, key in [("CRP-weighted", "crp"), ("EW-5", "ew")]:
        apy, dd, cal = res["train"][key]
        cal_str = f"{cal:8.3f}" if cal == cal else "    NONE"
        print(f"  {name:<12} {apy:8.2f}% {dd:7.2f}% {cal_str}")

    print()
    print("── Portfolio results (TEST 2025-07-01..2026-05-31) [bt] ───────────────────")
    print(f"  {'portfolio':<12} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8}")
    for name, key in [("CRP-weighted", "crp"), ("EW-5", "ew")]:
        apy, dd, cal = res["test"][key]
        cal_str = f"{cal:8.3f}" if cal == cal else "    NONE"
        print(f"  {name:<12} {apy:8.2f}% {dd:7.2f}% {cal_str}")

    print()
    print("── Full period 2024-07-01..2026-05-31 (843 days) [bt] ─────────────────────")
    print(f"  {'portfolio':<12} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8}")
    for name, key in [("CRP-weighted", "crp"), ("EW-5", "ew")]:
        apy, dd, cal = res["full"][key]
        cal_str = f"{cal:8.3f}" if cal == cal else "    NONE"
        print(f"  {name:<12} {apy:8.2f}% {dd:7.2f}% {cal_str}")

    # Verdict
    print()
    crp_test_apy, crp_test_dd, crp_test_cal = res["test"]["crp"]
    ew_test_apy, ew_test_dd, ew_test_cal = res["test"]["ew"]
    delta_apy = crp_test_apy - ew_test_apy
    print("── Verdict ──────────────────────────────────────────────────────────────────")
    print(f"  ΔAPY (CRP vs EW) in TEST: {delta_apy:+.2f} pp")
    if crp_test_cal == crp_test_cal and ew_test_cal == ew_test_cal:
        delta_cal = crp_test_cal - ew_test_cal
        print(f"  ΔCalmar (CRP vs EW) in TEST: {delta_cal:+.3f}")
    crp_full_apy, crp_full_dd, crp_full_cal = res["full"]["crp"]
    ew_full_apy, ew_full_dd, ew_full_cal = res["full"]["ew"]
    print(f"  CRP full: APY {crp_full_apy:.2f}%  maxDD {crp_full_dd:.2f}%  Calmar {crp_full_cal:.3f}")
    print(f"  EW full:  APY {ew_full_apy:.2f}%  maxDD {ew_full_dd:.2f}%  Calmar {ew_full_cal:.3f}")
    print()
    print("  HONEST CAVEATS:")
    print("  (a) All numbers are [backtest] from deterministic fixture — NOT realized")
    print("  (b) Recovery measured on FIXTURE which has continuous drift — real books may")
    print("      not recover (permanent capital loss). This UNDERSTATES recovery risk.")
    print("  (c) Only 2 train crises used for sizing. 3rd (rsETH 2026-04) hits in TEST.")
    print("  (d) Fixture has only 6 books; real-panel recovery profiles may differ.")
    print("  (e) Sizer is strictly ADVISORY; IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True")
    print(f"\n  Evidence level: {r['evidence_level']}")
    print("=" * 72)


if __name__ == "__main__":
    import tempfile
    import os

    # Use fixture data
    from spa_core.strategy_lab.aggressive_lab.fixtures import materialize

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = materialize(Path(tmp))
        report = crp_report(data_dir)
        print_report(report)
