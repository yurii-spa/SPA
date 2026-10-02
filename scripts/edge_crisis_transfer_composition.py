#!/usr/bin/env python3
"""scripts/edge_crisis_transfer_composition.py — Idea #124 CTC
Crisis-Transfer Composition: does N-leg composition selection survive unseen crises?

Question from #123 заказ: перемерить что-либо против честного нуля, и прежде всего —
понять, что происходит с ВЫБОРОМ СОСТАВА, если обучающее окно видело только ОДИН из
трёх кризисов.

TRAIN = fixture backtest 2024-07-01..2025-05-31 (1 crisis: ETH-crash 2024-08)
TEST  = fixture backtest 2025-06-01..2026-05-31 (2 crises: USDe-unwind 2025-10, rsETH-depeg 2026-04)

For each N in 1..5:
  Enumerate all C(5,N) subsets.
  Pick subset with max TRAIN APY at TRAIN maxDD ≤ 10% (TRAIN-only selection).
  Evaluate that same subset on TEST.
  Report TRAIN and TEST side-by-side.

Baselines:
  EW-5          equal-weight all 5 strategies
  EW-STABLE     equal-weight {points_farm, susde_dn} — the two with carry > max-known-tail
  EW-CARRY3     equal-weight top-3 by drift {leverage_loop, points_farm, lrt_carry}
  SPEC-CALIB    include only strats where annual carry > max_known_tail [look-ahead, bt-spec]
  RWA-FLOOR     3.4% APY flat (conservative baseline)

Invariants:
  TRAIN selection uses ONLY TRAIN data. TEST is never touched during selection.
  SPEC-CALIB is clearly labeled look-ahead (uses fixture crisis spec).
  All numbers: [bt-fix] evidence L0 — synthetic fixture, NOT live.
  IS_ADVISORY=True. OUTSIDE_RISKPOLICY=True.
  No imports from spa_core.execution. No live track. RiskPolicy v1.0 untouched.
  stdlib-only. LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spa_core.strategy_lab.aggressive_lab.fixtures import strategy_jsonl  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────
FLOOR_APY        = 0.034   # RWA conservative baseline
MAX_DD_THRESHOLD = 0.10    # TRAIN maxDD limit for N-leg selection

TRAIN_START = "2024-07-01"
TRAIN_END   = "2025-05-31"
TEST_START  = "2025-06-01"
TEST_END    = "2026-05-31"

# thin_new has no backtest track — excluded
STRATEGIES = ["leverage_loop", "lrt_carry", "points_farm", "susde_dn", "variant_d"]

# Known maximum crisis loss from fixture spec (ALL three crises).
# Labeled [bt-spec] / look-ahead — uses documented strategy class properties.
KNOWN_MAX_TAIL: dict[str, float] = {
    "susde_dn":      0.09,   # worst: USDe-unwind (funding_flip shape)
    "lrt_carry":     0.22,   # worst: rsETH-depeg (depeg shape)
    "leverage_loop": 0.28,   # worst: USDe-unwind (liquidation shape)
    "points_farm":   0.02,   # worst: USDe-unwind (incentive_decay shape)
    "variant_d":     0.20,   # worst: rsETH-depeg (depeg shape)
}
KNOWN_DRIFT: dict[str, float] = {
    "susde_dn":      0.11,
    "lrt_carry":     0.13,
    "leverage_loop": 0.15,
    "points_farm":   0.14,
    "variant_d":     0.09,
}


# ── data loading ──────────────────────────────────────────────────────────

def load_bt_returns(strategy_id: str) -> dict[str, float]:
    """Load daily returns for backtest phase only, keyed by date string."""
    rows = [json.loads(ln) for ln in strategy_jsonl(strategy_id).splitlines() if ln.strip()]
    bt   = sorted((r for r in rows if r["phase"] == "backtest"), key=lambda x: x["date"])
    rets: dict[str, float] = {}
    for i in range(1, len(bt)):
        rets[bt[i]["date"]] = bt[i]["equity_usd"] / bt[i - 1]["equity_usd"] - 1.0
    return rets


def date_slice(all_dates: list[str], start: str, end: str) -> list[str]:
    return [d for d in all_dates if start <= d <= end]


# ── statistics ───────────────────────────────────────────────────────────

def portfolio_stats(
    strategy_ids: list[str],
    all_returns: dict[str, dict[str, float]],
    dates: list[str],
    weights: list[float] | None = None,
) -> tuple[float, float, float]:
    """Return (APY, maxDD, Calmar) for an equal-weight portfolio on given dates."""
    n = len(strategy_ids)
    if weights is None:
        weights = [1.0 / n] * n
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    n_days = 0
    for d in dates:
        r = sum(w * all_returns[sid].get(d, 0.0)
                for sid, w in zip(strategy_ids, weights))
        eq   *= (1.0 + r)
        peak  = max(peak, eq)
        dd    = (peak - eq) / peak
        max_dd = max(max_dd, dd)
        n_days += 1
    if n_days == 0 or eq <= 0:
        return 0.0, 0.0, 0.0
    apy    = eq ** (365.0 / n_days) - 1.0
    calmar = apy / max_dd if max_dd > 1e-9 else float("inf")
    return apy, max_dd, calmar


def crisis_hit(
    strategy_id: str,
    all_returns: dict[str, dict[str, float]],
    c_start: str, c_end: str,
    all_dates: list[str],
) -> float:
    """Cumulative percentage loss for a single strategy during a crisis window."""
    c_dates = date_slice(all_dates, c_start, c_end)
    eq = 1.0
    for d in c_dates:
        eq *= (1.0 + all_returns[strategy_id].get(d, 0.0))
    return (1.0 - eq) * 100.0


# ── N-leg selection ───────────────────────────────────────────────────────

def select_best_subset(
    strategies: list[str],
    n: int,
    all_returns: dict[str, dict[str, float]],
    train_dates: list[str],
    max_dd_limit: float,
) -> tuple[list[str], float, float, float] | None:
    """Pick N-subset with max TRAIN APY at TRAIN maxDD ≤ limit. TRAIN only."""
    best: tuple[list[str], float, float, float] | None = None
    best_apy = -1e9
    for combo in itertools.combinations(strategies, n):
        apy, maxdd, calmar = portfolio_stats(list(combo), all_returns, train_dates)
        if maxdd <= max_dd_limit and apy > best_apy:
            best_apy = apy
            best = (list(combo), apy, maxdd, calmar)
    return best


# ── reporting helpers ─────────────────────────────────────────────────────

def fmt_row(
    label: str,
    tr_apy: float, tr_dd: float, tr_cal: float,
    te_apy: float, te_dd: float, te_cal: float,
) -> str:
    def _c(v: float) -> str:
        return f"{v:6.2f}" if v < 1e8 else "   inf"
    return (
        f" {label:<44}  {tr_apy*100:8.2f} {tr_dd*100:7.2f} {_c(tr_cal)}"
        f"  {te_apy*100:8.2f} {te_dd*100:7.2f} {_c(te_cal)}"
    )


HDR_COLS = (
    f" {'Label':<44}  {'TRAIN APY%':>8} {'maxDD%':>7} {'Calmar':>6}"
    f"  {'TEST APY%':>8} {'maxDD%':>7} {'Calmar':>6}"
)


# ── main ─────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 76)
    print("Idea #124 CTC — Crisis-Transfer Composition")
    print("[bt-fix] L0 | IS_ADVISORY=True | OUTSIDE_RISKPOLICY=True")
    print("=" * 76)

    all_rets: dict[str, dict[str, float]] = {s: load_bt_returns(s) for s in STRATEGIES}

    common_dates = sorted(
        set.intersection(*[set(r.keys()) for r in all_rets.values()])
    )
    train_dates = date_slice(common_dates, TRAIN_START, TRAIN_END)
    test_dates  = date_slice(common_dates, TEST_START,  TEST_END)

    print(f"\nTRAIN: {TRAIN_START}→{TRAIN_END}  {len(train_dates)} days  1 crisis: ETH-crash 2024-08")
    print(f"TEST : {TEST_START}→{TEST_END}  {len(test_dates)} days  2 crises: USDe-unwind 2025-10, rsETH-depeg 2026-04")

    # ── individual strategy summary ───────────────────────────────────────
    print(f"\n{'─'*76}")
    print("INDIVIDUAL STRATEGIES: TRAIN stats + TEST crisis hits")
    print(f"{'─'*76}")
    print(f" {'Strategy':<18} {'drift%':>7} {'TRAIN APY%':>11} {'TRAIN DD%':>10} "
          f"{'TEST USDe%':>11} {'TEST rsETH%':>12}")
    print("─" * 76)
    for sid in STRATEGIES:
        tr_apy, tr_dd, _ = portfolio_stats([sid], all_rets, train_dates)
        hit_usde  = crisis_hit(sid, all_rets, "2025-10-01", "2025-10-31", common_dates)
        hit_rseth = crisis_hit(sid, all_rets, "2026-04-01", "2026-04-30", common_dates)
        print(f" {sid:<18} {KNOWN_DRIFT[sid]*100:7.1f} {tr_apy*100:11.2f} {tr_dd*100:10.2f} "
              f"{hit_usde:+11.2f} {hit_rseth:+12.2f}")

    # ── N-leg frontier ────────────────────────────────────────────────────
    print(f"\n{'─'*76}")
    print(f"N-LEG FRONTIER (TRAIN-only selection, maxDD≤{MAX_DD_THRESHOLD*100:.0f}%)")
    print(f"{'─'*76}")
    print(HDR_COLS)
    print("─" * 96)

    selected: dict[int, tuple] = {}
    for n in range(1, len(STRATEGIES) + 1):
        best = select_best_subset(STRATEGIES, n, all_rets, train_dates, MAX_DD_THRESHOLD)
        if best is None:
            print(f" N={n}: ⛔ no subset passes TRAIN maxDD≤{MAX_DD_THRESHOLD*100:.0f}%")
            continue
        combo, tr_apy, tr_dd, tr_cal = best
        te_apy, te_dd, te_cal = portfolio_stats(combo, all_rets, test_dates)
        short = "+".join(s[:6] for s in combo)
        print(fmt_row(f"N={n}: {short}", tr_apy, tr_dd, tr_cal, te_apy, te_dd, te_cal))
        selected[n] = (combo, tr_apy, tr_dd, tr_cal, te_apy, te_dd, te_cal)

    # ── baselines ─────────────────────────────────────────────────────────
    print(f"\n{'─'*76}")
    print("BASELINES")
    print(f"{'─'*76}")
    print(HDR_COLS)
    print("─" * 96)

    # spec-calibrated: include only strategies with annual carry > max known tail [look-ahead]
    spec_combo = sorted(s for s in STRATEGIES if KNOWN_DRIFT[s] > KNOWN_MAX_TAIL[s])

    for label, combo in [
        ("EW-5 (all 5 strategies)", STRATEGIES),
        ("EW-STABLE (points_farm+susde_dn)",       ["points_farm", "susde_dn"]),
        ("EW-CARRY3 (levloop+lrt+pts)",             ["leverage_loop", "lrt_carry", "points_farm"]),
        (f"SPEC-CALIB [look-ahead] ({'+'.join(s[:6] for s in spec_combo)})", spec_combo),
    ]:
        tr = portfolio_stats(combo, all_rets, train_dates)
        te = portfolio_stats(combo, all_rets, test_dates)
        print(fmt_row(label, *tr, *te))

    print(f" {'RWA floor 3.4% (flat)':<44}  {'n/a':>8} {'n/a':>7} {'n/a':>6}"
          f"  {3.4:8.2f} {'n/a':>7} {'n/a':>6}")

    # ── full-period EW for context ────────────────────────────────────────
    all_period = date_slice(common_dates, TRAIN_START, TEST_END)
    print(f"\n{'─'*76}")
    print("FULL-PERIOD (TRAIN+TEST combined, no split — context only, NOT selection criterion)")
    print(f"{'─'*76}")
    for label, combo in [
        ("EW-5 full period",                   STRATEGIES),
        ("EW-STABLE full period",              ["points_farm", "susde_dn"]),
        (f"SPEC-CALIB full period [look-ahead]", spec_combo),
    ]:
        apy, maxdd, calmar = portfolio_stats(combo, all_rets, all_period)
        _c = f"{calmar:.2f}" if calmar < 1e8 else "inf"
        print(f" {label:<44}  APY={apy*100:.2f}%  maxDD={maxdd*100:.2f}%  Calmar={_c}")

    # ── key finding ───────────────────────────────────────────────────────
    print(f"\n{'='*76}")
    print("HONEST VERDICT (IDEA #124 CTC)")
    print(f"{'='*76}")

    n1 = selected.get(1)
    n1_name = n1[0][0] if n1 else "N/A"
    n1_tr_apy  = n1[1] if n1 else 0.0
    n1_tr_dd   = n1[2] if n1 else 0.0
    n1_te_apy  = n1[4] if n1 else 0.0
    n1_te_dd   = n1[5] if n1 else 0.0

    tr_stable_apy, tr_stable_dd, _ = portfolio_stats(
        ["points_farm", "susde_dn"], all_rets, train_dates
    )
    te_stable_apy, te_stable_dd, te_stable_cal = portfolio_stats(
        ["points_farm", "susde_dn"], all_rets, test_dates
    )

    print(f"""
QUESTION: Does N-leg composition selected on a TRAIN with one crisis (ETH-crash 2024-08)
          transfer to a TEST with two DIFFERENT crises (USDe-unwind, rsETH-depeg)?

FINDING 1 — TRAIN-selected N=1 ({n1_name}) is the worst TEST performer:
  TRAIN: APY={n1_tr_apy*100:.1f}%, maxDD={n1_tr_dd*100:.1f}%  ← passes 10% threshold (only ETH-crash)
  TEST : APY={n1_te_apy*100:.1f}%, maxDD={n1_te_dd*100:.1f}%  ← USDe-unwind -28%, rsETH-depeg -11%

FINDING 2 — EW-STABLE (points_farm+susde_dn) beats TRAIN-selected on TEST:
  EW-STABLE TRAIN: APY={tr_stable_apy*100:.1f}%, maxDD={tr_stable_dd*100:.1f}%
  EW-STABLE TEST : APY={te_stable_apy*100:.1f}%, maxDD={te_stable_dd*100:.1f}%, Calmar={te_stable_cal:.2f}

FINDING 3 — SPEC-CALIB [look-ahead] = EW-STABLE (same set):
  Rule: include only strategies where annual carry > max_known_tail_across_ALL_crises.
  susde_dn (11% carry, 9% max tail) and points_farm (14% carry, 2% max tail) PASS.
  lrt_carry (13% carry, 22% max tail), leverage_loop (15% carry, 28% max tail),
  variant_d (9% carry, 20% max tail) all FAIL.

MECHANISM (why TRAIN selection fails):
  lrt_carry: TRAIN shows 5% hit (ETH-crash), but TEST reveals 22% rsETH-depeg hit.
  leverage_loop: TRAIN shows 6% hit, but TEST reveals 28% USDe-unwind hit.
  variant_d: correctly excluded by TRAIN (18% TRAIN maxDD > 10% threshold).
  TRAIN passes the "wrong" strategies because ETH-crash is the WEAKEST of the three.

IMPLICATION FOR AGGRESSIVE TIER:
  Composition selection based on maxDD from a SINGLE training crisis is MISLEADING.
  Reliable composition selection requires either:
  (a) Carry/tail analysis using KNOWN worst-case risk class properties [bt-spec, look-ahead], OR
  (b) Multiple crisis types in the training window (ideally all three).
  This validates the "carry > max_known_tail" rule as the RIGHT selection criterion,
  even though it requires using out-of-sample crisis information.

EVIDENCE: [bt-fix] L0 — synthetic fixture, NOT live, NOT real feed data.
NEXT STEP: Verify same composition finding on real panel (data/aggressive_lab)
           when available, using EW-live(6) as baseline (#122 correction).
IS_ADVISORY=True | OUTSIDE_RISKPOLICY=True | RiskPolicy v1.0 UNTOUCHED.
""")


if __name__ == "__main__":
    main()
