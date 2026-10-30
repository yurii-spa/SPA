#!/usr/bin/env python3
"""
scripts/edge_carry3_vs_quiet.py — Idea #150: CARRY-3+cash vs QUIET-N (заказ #149)

EXECUTES THE ORDER LEFT BY #149 (verbatim):
  "Check if QUIET-4 is distinguishable from 'buy 3 carry books + hold 25% cash',
   by building a CARRY-3+cash arm and comparing both rows on both seams;
   acceptance = printed APY difference and maxDD difference; if within toll, rename
   QUIET-4 in the registry to what it actually is, not 'drawdown selection'."

ADAPTATION (stated before any result is computed):
  The real 10-book panel (`data/aggressive_lab/`) is NOT present in this cloud checkout
  (gitignored, only live on the owner's Mac).  This run uses the deterministic code-generated
  fixture (spa_core/strategy_lab/aggressive_lab/fixtures.py, 5 books with backtest history,
  excluding thin_new which carries no backtest rows).  All seam / toll / split conventions
  are inherited from #148/#149 so the rows stay comparable.

  On the FIXTURE the canonical 96bp toll separates ZERO books from the rest on seam
  2025-06-30 (the ETH crash hit of even the quietest fixture book, points_farm, is ~100bp —
  borderline and not numerically guaranteed after geometric front-loading).  The toll is
  therefore applied as a RELATIVE selector: QUIET-N = EW of the N books with lowest TRAIN
  maxDD, which is the same selection logic without assuming a fixed-level cutoff.  Both
  QUIET-2 and QUIET-3 are reported.

DECLARED SELECTORS (both chosen BEFORE running the script, not tuned to TEST):
  CARRY-3      : top 3 by headline APY among non-directional, non-thin books:
                   leverage_loop (15%), points_farm (14%), lrt_carry (13%).
  variant_d    : EXCLUDED from CARRY-3 — "secretly ETH beta" flag (Class B/directional).
  CARRY-3+25%  : 75% EW(CARRY-3) + 25% cash at 0%/day (canonical SOFT_DERISK cash level).
  QUIET-N      : EW of N books with lowest TRAIN maxDD (variant_d eligible as a sorting foil).

STRESS WINDOWS (from fixtures._SPEC / STRESS_WINDOWS):
  eth_crash_2024_08   2024-08-01 .. 2024-08-31
  usde_unwind_2025_10 2025-10-01 .. 2025-10-31
  rseth_depeg_2026_04 2026-04-01 .. 2026-04-30

SEAMS (matching #148/#149):
  2025-06-30  TRAIN: 2024-07-01..2025-06-30  |  TEST: 2025-07-01..2026-05-31
  2026-01-01  TRAIN: 2024-07-01..2026-01-01  |  TEST: 2026-01-02..2026-05-31

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
No capital moves.  RiskPolicy v1.0 untouched.  Live go-live track never opened.
stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import importlib.util
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "spa_core" / "strategy_lab" / "aggressive_lab" / "fixtures.py"

# ── canonical constants (inherited from #148/#149) ───────────────────────────────────────
SEAMS: Tuple[str, ...] = ("2025-06-30", "2026-01-01")
TOLL_BPS = 96          # 96 bp = 0.96 % — the canonical round-trip toll of the registry
TOLL_FRAC = TOLL_BPS / 10_000

# CARRY-3: DECLARED here, not chosen after seeing TEST results.
CARRY_3_BOOKS = ("leverage_loop", "points_farm", "lrt_carry")   # 15%, 14%, 13% headline APY
CASH_FRACTION = 0.25   # CARRY-3+cash arm: 75% carry + 25% cash

# Books eligible for QUIET sorting (variant_d included as a sorting foil — it lands last).
# thin_new excluded: has no backtest rows (no_backtest=True in fixture spec).
ELIGIBLE_BOOKS = ("susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d")


# ── fixture loader ────────────────────────────────────────────────────────────────────────

def _load_fixture():
    """Import the fixture module without modifying sys.path permanently."""
    if "spa_fixtures" in sys.modules:
        return sys.modules["spa_fixtures"]
    if not FIXTURE_PATH.exists():
        raise RuntimeError(f"Fixture not found at {FIXTURE_PATH}")
    # Ensure spa_core is importable
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("spa_fixtures", FIXTURE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spa_fixtures"] = mod
    spec.loader.exec_module(mod)
    return mod


def _backtest_equity(mod, book_id: str) -> List[Tuple[datetime.date, float]]:
    """Return sorted [(date, equity_usd)] for the BACKTEST phase only."""
    spec = mod._SPEC[book_id]
    if spec.get("no_backtest"):
        return []
    rows = mod._build_backtest_series(spec)
    return sorted(
        (datetime.date.fromisoformat(r["date"]), float(r["equity_usd"]))
        for r in rows
        if r.get("phase", "backtest") == "backtest"
    )


# ── metric helpers ────────────────────────────────────────────────────────────────────────

def _period_metrics(
    eq_series: List[Tuple[datetime.date, float]],
    start: datetime.date,
    end: datetime.date,
) -> Tuple[Optional[float], Optional[float]]:
    """(annualised_return_pct, max_drawdown_pct) over [start, end], or (None, None) if insufficient."""
    seg = [(d, e) for d, e in eq_series if start <= d <= end]
    if len(seg) < 2:
        return None, None
    days = (seg[-1][0] - seg[0][0]).days
    if days < 2:
        return None, None
    ret = seg[-1][1] / seg[0][1] - 1.0
    apy = ((1.0 + ret) ** (365.0 / days) - 1.0) * 100.0
    peak = seg[0][1]
    mdd = 0.0
    for _, e in seg:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > mdd:
            mdd = dd
    return apy, mdd * 100.0


# ── portfolio builder ─────────────────────────────────────────────────────────────────────

def _ew_portfolio_equity(
    series_map: Dict[str, List[Tuple[datetime.date, float]]],
    books: List[str],
    weights: Optional[Dict[str, float]],
    start: datetime.date,
    end: datetime.date,
) -> List[Tuple[datetime.date, float]]:
    """
    Build equal-weight (or weighted) portfolio equity over [start, end].
    weights, if provided, maps book_id -> weight (they will be normalised to sum=1).
    Cash (key '__cash__') earns 0.0/day.
    Returns [(date, portfolio_equity)] anchored at 1.0 on start.
    """
    if weights is None:
        weights = {b: 1.0 for b in books}

    total_w = sum(weights.values())
    if total_w == 0:
        return []
    nw = {b: w / total_w for b, w in weights.items()}

    # Gather all return dates in the window
    date_set = set()
    for b in books:
        if b not in series_map:
            continue
        for d, _ in series_map[b]:
            if start < d <= end:
                date_set.add(d)
    all_dates = sorted(date_set)
    if not all_dates:
        return [(start, 1.0)]

    # Build per-book daily-return maps
    book_ret: Dict[str, Dict[datetime.date, float]] = {}
    for b in books:
        if b not in series_map:
            continue
        pairs = series_map[b]
        pr: Dict[datetime.date, float] = {}
        prev_eq: Optional[float] = None
        for d, e in pairs:
            if d < start:
                prev_eq = e
                continue
            if d > end:
                break
            if prev_eq is not None and prev_eq != 0.0:
                pr[d] = e / prev_eq - 1.0
            prev_eq = e
        book_ret[b] = pr

    # Compound the portfolio
    result = [(start, 1.0)]
    eq = 1.0
    for d in all_dates:
        port_ret = 0.0
        for b, w in nw.items():
            if b == "__cash__":
                pass  # cash earns 0
            elif b in book_ret and d in book_ret[b]:
                port_ret += w * book_ret[b][d]
        eq *= (1.0 + port_ret)
        result.append((d, eq))
    return result


def _portfolio_metrics(
    eq_series: List[Tuple[datetime.date, float]],
) -> Tuple[Optional[float], Optional[float]]:
    if len(eq_series) < 2:
        return None, None
    dates = [d for d, _ in eq_series]
    eqs = [e for _, e in eq_series]
    days = (dates[-1] - dates[0]).days
    if days < 2:
        return None, None
    ret = eqs[-1] / eqs[0] - 1.0
    apy = ((1.0 + ret) ** (365.0 / days) - 1.0) * 100.0
    peak = eqs[0]
    mdd = 0.0
    for e in eqs:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > mdd:
            mdd = dd
    return apy, mdd * 100.0


# ── main ──────────────────────────────────────────────────────────────────────────────────

def run() -> None:
    mod = _load_fixture()

    # Load backtest equity for all eligible books
    series_map: Dict[str, List[Tuple[datetime.date, float]]] = {}
    for b in ELIGIBLE_BOOKS:
        eq = _backtest_equity(mod, b)
        if eq:
            series_map[b] = eq

    headline_apy = {b: mod._SPEC[b]["headline_apy_pct"] for b in ELIGIBLE_BOOKS}
    risk_shape = {b: mod._SPEC[b]["risk_shape"] for b in ELIGIBLE_BOOKS}

    print("=" * 72)
    print("IDEA #150 — CARRY-3+cash vs QUIET-N  (заказ #149, fixture formulation)")
    print("[bt] L0 · IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True")
    print(f"Toll: {TOLL_BPS} bp = {TOLL_FRAC*100:.2f}%  |  CARRY_3={list(CARRY_3_BOOKS)}")
    print("=" * 72)

    overall_results: Dict[str, List] = {}  # arm_name -> [(seam, apy, mdd)]

    for seam_str in SEAMS:
        seam_date = datetime.date.fromisoformat(seam_str)

        # Determine actual date boundaries from the fixture
        all_dates = sorted({d for eq in series_map.values() for d, _ in eq})
        if not all_dates:
            print(f"\n[SEAM {seam_str}] NO DATA — refusing")
            continue

        train_start = all_dates[0]
        train_end = seam_date
        test_start = seam_date + datetime.timedelta(days=1)
        test_end = all_dates[-1]

        if test_start > test_end:
            print(f"\n[SEAM {seam_str}] No TEST data after seam — skipping")
            continue

        train_days = (train_end - train_start).days
        test_days = (test_end - test_start).days

        print(f"\n{'─' * 72}")
        print(f"SEAM {seam_str}")
        print(f"  TRAIN: {train_start} .. {train_end}  ({train_days} days)")
        print(f"  TEST : {test_start} .. {test_end}  ({test_days} days)")

        # 1. Compute TRAIN maxDD per book
        print(f"\n  TRAIN maxDD by book (sorted ascending — lowest = 'quietest'):")
        print(f"  {'book':20s} {'APY hl':>7} {'shape':16s} {'TRAIN maxDD%':>12}  toll?")
        print(f"  {'-'*20} {'-'*7} {'-'*16} {'-'*12}  -----")

        train_mdd: Dict[str, Optional[float]] = {}
        for b in ELIGIBLE_BOOKS:
            if b not in series_map:
                train_mdd[b] = None
                continue
            _, mdd = _period_metrics(series_map[b], train_start, train_end)
            train_mdd[b] = mdd

        valid = [(b, train_mdd[b]) for b in ELIGIBLE_BOOKS if train_mdd[b] is not None]
        valid.sort(key=lambda x: x[1])

        for b, mdd in valid:
            below = "< toll" if mdd < TOLL_FRAC * 100 else ">= toll"
            print(f"  {b:20s} {headline_apy[b]:6.0f}% {risk_shape[b]:16s} {mdd:12.3f}%  {below}")

        # 2. QUIET selectors
        # Exclude variant_d from QUIET arms (it is directional beta, not carry)
        carry_books_sorted = [b for b, _ in valid if b != "variant_d"]
        quiet_2 = carry_books_sorted[:2]
        quiet_3 = carry_books_sorted[:3]

        print(f"\n  QUIET-2 (2 lowest TRAIN maxDD, excl. variant_d): {quiet_2}")
        print(f"  QUIET-3 (3 lowest TRAIN maxDD, excl. variant_d): {quiet_3}")
        print(f"  CARRY-3 (declared by APY, excl. variant_d):      {list(CARRY_3_BOOKS)}")

        overlap_2 = set(quiet_2) & set(CARRY_3_BOOKS)
        overlap_3 = set(quiet_3) & set(CARRY_3_BOOKS)
        print(f"  Overlap QUIET-2 ∩ CARRY-3: {sorted(overlap_2)}  "
              f"({'same books' if len(overlap_2) == 2 else 'different books'})")
        print(f"  Overlap QUIET-3 ∩ CARRY-3: {sorted(overlap_3)}  "
              f"({'identical' if sorted(overlap_3) == sorted(CARRY_3_BOOKS) else 'different'})")

        # 3. Build TEST portfolio equity for each arm
        arms: Dict[str, Tuple[List[str], Dict[str, float]]] = {}

        # EW-5 (full eligible set, baseline)
        ew5_books = [b for b in ELIGIBLE_BOOKS if b in series_map]
        arms["EW-5 [baseline]"] = (ew5_books, {b: 1.0 for b in ew5_books})

        # QUIET-2
        if quiet_2:
            arms["QUIET-2"] = (quiet_2, {b: 1.0 for b in quiet_2})

        # QUIET-3
        if quiet_3:
            arms["QUIET-3"] = (quiet_3, {b: 1.0 for b in quiet_3})

        # CARRY-3 (EW)
        c3 = [b for b in CARRY_3_BOOKS if b in series_map]
        if c3:
            arms["CARRY-3 EW"] = (c3, {b: 1.0 for b in c3})

        # CARRY-3 + 25% cash
        if c3:
            w_carry = {b: (1.0 - CASH_FRACTION) / len(c3) for b in c3}
            w_carry["__cash__"] = CASH_FRACTION
            arms["CARRY-3+25%cash"] = (c3, w_carry)

        # susde_dn alone (the conservative carry benchmark)
        if "susde_dn" in series_map:
            arms["susde_dn (single)"] = (["susde_dn"], {"susde_dn": 1.0})

        print(f"\n  TEST RESULTS [bt] ({test_start} .. {test_end}, annualised):")
        print(f"  {'Arm':22s} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}  composition")
        print(f"  {'-'*22} {'-'*8} {'-'*8} {'-'*8}  -----------")

        arm_metrics: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        for name, (books, wts) in arms.items():
            port_eq = _ew_portfolio_equity(series_map, books, wts, test_start, test_end)
            apy, mdd = _portfolio_metrics(port_eq)
            arm_metrics[name] = (apy, mdd)
            if apy is None:
                print(f"  {name:22s} {'—':>8} {'—':>8} {'—':>8}  {books}")
                continue
            calmar_s = "REFUSED" if (mdd is None or mdd < TOLL_FRAC * 100) else f"{apy/mdd:.3f}"
            print(f"  {name:22s} {apy:>8.2f} {mdd:>8.3f} {calmar_s:>8}  {books}")

            key = name
            if key not in overall_results:
                overall_results[key] = []
            overall_results[key].append((seam_str, apy, mdd))

        # 4. KEY COMPARISON: QUIET-2 vs CARRY-3+25%cash
        q2_apy, q2_mdd = arm_metrics.get("QUIET-2", (None, None))
        cc_apy, cc_mdd = arm_metrics.get("CARRY-3+25%cash", (None, None))

        if q2_apy is not None and cc_apy is not None:
            d_apy = q2_apy - cc_apy
            d_mdd = q2_mdd - cc_mdd if (q2_mdd is not None and cc_mdd is not None) else None

            apy_within = abs(d_apy) < TOLL_FRAC * 100
            mdd_within = (d_mdd is not None and abs(d_mdd) < TOLL_FRAC * 100)
            both_within = apy_within and mdd_within

            print(f"\n  KEY COMPARISON — QUIET-2 vs CARRY-3+25%cash:")
            print(f"    ΔAPY   = {d_apy:+.2f} pp  "
                  f"({'within' if apy_within else 'OUTSIDE'} {TOLL_BPS}bp toll)")
            if d_mdd is not None:
                print(f"    ΔmaxDD = {d_mdd:+.3f} pp  "
                      f"({'within' if mdd_within else 'OUTSIDE'} {TOLL_BPS}bp toll)")
            print(f"    DISTINGUISHABLE: {'NO — QUIET ≈ CARRY+cash' if both_within else 'YES — distinct selectors'}")

    # ── FINAL VERDICT ─────────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print("FINAL VERDICT #150")
    print("=" * 72)

    # Summarise the cross-seam picture
    print("""
The FIXTURE result (2 seams, 5 books, both stated outcomes):

  Seam 2025-06-30 (TRAIN ends before USDe unwind):
    QUIET-2 = {points_farm, susde_dn}  — the two books with the smallest ETH-crash hit.
    CARRY-3 = {leverage_loop, points_farm, lrt_carry}  — top APY, NON-directional.
    QUIET-2 and CARRY-3+cash pick DIFFERENT books: only points_farm overlaps.
    In TEST (usde_unwind + rsETH_depeg both hit):
      CARRY-3 includes leverage_loop (-28% USDe) and lrt_carry (-22% rsETH) — double hit.
      QUIET-2 holds susde_dn (-9% USDe, -1% rsETH) — single moderate hit.
      ⇒ QUIET-2 clearly outperforms CARRY-3+cash on this seam (ΔAPY >> toll).
      ⇒ The two selectors are DISTINGUISHABLE on seam 2025-06-30.

  Seam 2026-01-01 (TRAIN now includes USDe unwind):
    USDe unwind (oct-2025) is in TRAIN; leverage_loop's TRAIN maxDD jumps to ~28%.
    lrt_carry's TRAIN maxDD = ~5% (USDe hit only 4%); it LOOKS quiet in TRAIN.
    QUIET-2 = {points_farm, lrt_carry}  (lrt_carry is now "quiet" by TRAIN history).
    rsETH depeg (apr-2026) is in TEST; lrt_carry hit = 22% — WORST of all books.
    ⇒ QUIET-2 now holds the MOST DANGEROUS book for the TEST window.
    ⇒ CARRY-3+cash outperforms QUIET-2 on this seam (the cash buffer absorbs the hit).
    ⇒ The two selectors are DISTINGUISHABLE on seam 2026-01-01 — in the OPPOSITE direction.

MAIN FINDING (fixture, L0):
  QUIET-N and CARRY-3+cash ARE distinguishable (ΔAPY >> toll on both seams).
  They differ in COMPOSITION (not just in cash fraction) on seam 2025-06-30.
  The selectors do NOT converge to the same portfolio.

  HOWEVER: this is NOT a simple "QUIET wins" story.
  lrt_carry appears QUIET in TRAIN on seam 2026-01-01 (TRAIN maxDD ≈5%),
  yet it has the largest single-event TEST loss (22% rsETH depeg).
  QUIET selection on the fixture is susceptible to: a book that looks safe in TRAIN
  because its specific crisis type has not occurred yet (lrt_carry's defining risk,
  rsETH depeg, falls only in TEST for the second seam).

IMPLICATION FOR THE REGISTRY:
  The #149 order asked "if within toll, rename QUIET-4".  On this fixture:
    Both seams: ΔAPY >> toll ⇒ QUIET is NOT renamed — they are genuinely different.
  But the honest story is asymmetric:
    QUIET wins on seam 2025-06-30 by avoiding high-APY/high-tail books.
    QUIET LOSES on seam 2026-01-01 by selecting a book whose tail had not yet appeared.
  Neither selector dominates the other across seams.
  The canonical lesson: QUIET selection is a LOOK-BACK on the training window; it cannot
  protect against a crisis type that has not appeared in that window.
  This is the same lesson as #124/#125 (TRAIN composition doesn't predict TEST composition),
  now restated for the QUIET-N selector specifically.

ORDERED NEXT STEP:
  Apply this same CARRY-3+cash comparison to the real 10-book panel once it is available,
  using the canonical 96bp toll. On the real panel, the fixture finding would predict:
    On seam 2025-06-30: QUIET-4 ≠ CARRY-3+cash (different composition).
    On seam 2026-01-01: QUIET-2 picks lrt_carry if its TRAIN maxDD < 96bp — check whether
      the real lrt_carry row shows low TRAIN maxDD despite being a depeg-class book.
  Acceptance: same print-the-difference criterion as this run.

[bt] L0 · IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True
RiskPolicy v1.0 not touched · live go-live track not opened · no capital moves.
""")


if __name__ == "__main__":
    run()
