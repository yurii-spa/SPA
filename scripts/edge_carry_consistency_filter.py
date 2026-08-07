#!/usr/bin/env python3
"""Edge R&D — registry idea #42 (CVT): Carry Velocity Trigger.

WHERE THIS COMES FROM
  #40 (XSD) ranks books by the LEVEL of their trailing carry (trailing mean return over L=60
  days). That signal fires when the medium-term carry has deteriorated. But it has two limits:

    1. SPEED: XSD fires when a long window's mean turns negative. For a book with a small per-day
       loss spread over many days, the 60-day mean may stay positive for weeks while the carry is
       visibly declining.

    2. DIRECTION: XSD demotes permanently based on LEVEL (lowest-APY books are always in the
       bottom-k even in calm, so it conflates static allocation with crisis timing).

  CVT (Carry Velocity Trigger) directly measures the RATE OF CHANGE of carry rather than its
  level: does the book's recent carry (fast window) sit below its medium-term carry (slow window)?
  This fires when the TREND is negative, even before the absolute level crosses zero.

  Carries a STRUCTURAL CLARIFICATION (not a criticism of XSD): because the synthetic fixture has
  PIECEWISE-CONSTANT carry (returns = daily_drift ± crisis_loss, constant in each phase), the
  velocity signal reduces to a scaled version of the level signal in calm periods. This means
  CVT is verifiably only marginally different from XSD on the fixture. On real data — where carry
  has genuine intraday and intraweek variance (oracle APY moves, utilisation rates, funding rate
  swings) — CVT would show earlier, more targeted demotion. The fixture documents this LIMIT
  explicitly (see verdict below).

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #42 — CVT: Carry Velocity Trigger
──────────────────────────────────────────────────────────────────────────────────────────────
  velocity(b, t) = mean(r_b[t−L_fast : t−1]) − mean(r_b[t−L_slow : t−1])
                   ← the MACD-like carry deceleration signal (causal, all data through t−1)

  score(b, t) = velocity(b, t)   if velocity(b, t) < −ε      ← carry is actively decelerating
              = None             otherwise                     ← no signal → not rankable

  DEMOTED(b,t): score is among the k LOWEST (most negative deceleration) among rankable books
  RE-ADMIT    : book is NOT in the bottom-k for M consecutive days
  allocator   : freed weight redistributed equally over the eligible books (same as #39/#40)

  Parameters: L_fast=20, L_slow=60, k=2, M=20 — all inherited/comparable; only L_fast is new.
  The None-if-not-decelerating convention is important: in calm periods (all books in trend),
  CVT demotes nobody; XSD always demotes the lowest-APY books. This makes CVT a PURE TIMING
  OVERLAY, not a selection rule.

  SIGNAL TIMING ON THE FIXTURE (calculated):
    Day 2 of a crisis (crisis day 1 now in the window):
      velocity ≈ −hit_fraction × (1/L_fast − 1/L_slow)   for a front-loaded crisis
    This is: (−hit/20 + hit/60) × 0.5 = −hit × 0.0333 (for the front-loaded fraction)
    All books with hits in the current crisis become rankable from day 2 onwards.

  THE STRUCTURAL LIMIT (fixture-specific — stated before the numbers):
  On the synthetic fixture, calm-period carry is IDENTICAL every day (daily_drift is constant).
  In these windows, mean_fast = mean_slow = daily_drift → velocity = 0 → None for all books.
  CVT demotes nobody in calm periods. XSD always keeps 2 books out (the 2 lowest-drift books).
  This means on the fixture, CVT has zero demotion duty in calm periods and only fires during
  and after crises. The XSD vs CVT comparison on the fixture therefore measures: "Does demoting
  only during crisis (CVT) do better than always excluding the 2 worst-carry books (XSD)?"
  On REAL DATA, CVT would additionally fire when carry drifts lower in one window vs another,
  giving a genuine early-warning signal — but that cannot be measured here.

──────────────────────────────────────────────────────────────────────────────────────────────
CONTROLS (same suite as #40/#41 plus one specific to CVT)
──────────────────────────────────────────────────────────────────────────────────────────────
  • XSD k=2 M=20         — the same rule but scoring by LEVEL (trailing mean). On the fixture
                           this is the decisive comparison: CVT (velocity) vs XSD (level).
  • TOP-k SIGN FLIP      — demote best-velocity books (accelerating carry). If as good as worst,
                           the ranking is noise.
  • DUTY-MATCHED ABSOLUTE — #39's absolute rule, L/hurdle/M searched to match CVT's duty.
  • STATIC WEIGHT-MATCHED — time-average of CVT weights. If CVT ≈ static twin, it is not timing.
  • LEAVE-ONE-OUT        — mandatory since #37.
  • BOOK PERMUTATION     — 20 seeds; "0/20 beat real" → p < 0.048.
  • TIME ROTATION        — 28 one-week shifts.
  • TRAIN → TEST         — split at 2025-06-30 (registry standard).

BACKTEST DATA: FIXTURE (synthetic deterministic, from fixtures.py — code-generated, no external
  data files needed). The fixture is materialized in a temp directory and the panel loader
  pointed there. PANEL_DIR is monkeypatched before Panel() is instantiated.
  Evidence level: L0 (backtest on synthetic fixture, NOT live, NOT real feed history).

HONESTY / SCOPE
  • Strictly causal: all signals use data through t−1 only.
  • Read-only. Writes nothing under data/, imports no execution code.
    IS_ADVISORY = True, OUTSIDE_RISKPOLICY = True. Capital does not move.

Usage:
    python3 scripts/edge_carry_consistency_filter.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# All imports must happen BEFORE monkeypatching PANEL_DIR.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spa_core.strategy_lab.aggressive_lab.fixtures import materialize

import edge_calm_fp_tax as cfpt               # audited loader + metrics (#32)
import edge_capital_recycling as ecr          # allocator, cost model, controls (#38/#39)
import edge_drift_gated_overlay as dgo        # Panel, signals (#35–#37)
import edge_cross_sectional_demotion as xsd   # rank_demotion_flags, absolute_flags, controls (#40/#41)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

L_FAST: int = 20          # fast lookback window (days) — new param vs XSD
L_SLOW: int = 60          # slow lookback window (days) — same as XSD's L=60
HURDLE: float = ecr.SDS_HURDLE   # 0.0, used only by absolute reference rows
TRAIN_END: str = ecr.TRAIN_END
RF_ANNUAL: float = ecr.RF_ANNUAL
BP: float = cfpt.BP
DECEL_EPS: float = 1e-7   # minimum deceleration magnitude to treat as "signal"

Scores = Dict[str, List[Optional[float]]]

# ══════════════════════════════ fixture setup ══════════════════════════════

_FIXTURE_TMPDIR: Optional[tempfile.TemporaryDirectory] = None


def _ensure_fixture() -> Path:
    """Materialize the fixture and redirect cfpt.load_clean_panel to read from it.

    Python evaluates default arg values at function-definition time, so assigning
    cfpt.PANEL_DIR after import does NOT change the default in load_clean_panel().
    We therefore replace the function itself with a wrapper that passes the fixture path.
    """
    global _FIXTURE_TMPDIR
    if _FIXTURE_TMPDIR is None:
        _FIXTURE_TMPDIR = tempfile.TemporaryDirectory(prefix="spa_cvt_fixture_")
        panel_dir = materialize(Path(_FIXTURE_TMPDIR.name))
        _real_loader = cfpt.load_clean_panel   # keep original for restore if needed
        cfpt.load_clean_panel = lambda **_kw: _real_loader(panel_dir=panel_dir)
        cfpt.PANEL_DIR = panel_dir             # for any code that reads the constant
    return Path(_FIXTURE_TMPDIR.name)


# ══════════════════════════════ score function ══════════════════════════════

def cvt_scores(rets: Dict[str, Sequence[float]],
               l_fast: int = L_FAST,
               l_slow: int = L_SLOW,
               decel_eps: float = DECEL_EPS) -> Scores:
    """Carry Velocity: fast_mean(t-1) − slow_mean(t-1).  None unless actively decelerating.

    Returns None when:
      • i < l_slow  — warming-up (not enough history for both windows)
      • velocity ≥ −decel_eps — carry is flat or accelerating → no demotion signal

    Only NEGATIVE velocity (carry is slowing) is a demotion candidate. Positive velocity
    (carry speeding up) is set to None — it is not informative for demotion. Books with
    None are not ranked and cannot be demoted on that day.

    This is a THRESHOLD + RANKING hybrid: fires only when carry deceleration exceeds epsilon,
    and then ranks by the magnitude of that deceleration. Distinguishes CVT (timing-only) from
    XSD (always ranks all books, even in calm periods).
    """
    out: Scores = {}
    for b, r in rets.items():
        fast = cfpt.trailing_mean(r, l_fast)
        slow = cfpt.trailing_mean(r, l_slow)
        scores: List[Optional[float]] = []
        for i in range(len(r)):
            if i < l_slow:
                scores.append(None)
            else:
                vel = fast[i] - slow[i]
                scores.append(vel if vel < -decel_eps else None)
        out[b] = scores
    return out


# ══════════════════════════════ diagnostics ══════════════════════════════

def _cvt_stats(panel: "dgo.Panel") -> None:
    """Diagnostic: how many cells have a carry-deceleration signal per book."""
    sc = cvt_scores(panel.rets)
    n_total = sum(len(v) for v in sc.values())
    n_signal = sum(1 for v in sc.values() for x in v if x is not None)
    print()
    print("=" * 80)
    print(f"CVT DIAGNOSTIC — deceleration-signal days (velocity < −{DECEL_EPS:.0e}) per book:")
    print(f"  Total cells: {n_total}   Signal cells: {n_signal} ({n_signal*100/n_total:.1f}%)")
    for b in panel.books:
        n = len(sc[b])
        sig = sum(1 for x in sc[b] if x is not None)
        none_post_warmup = sum(1 for i, x in enumerate(sc[b]) if x is None and i >= L_SLOW)
        print(f"  {b:28s}: {sig:4d}/{n} signal days  "
              f"({none_post_warmup} post-warmup calm/flat days)")

    # Rank overlap with XSD: how often do CVT and XSD agree on which k=2 books to demote?
    sc_drift = xsd.drift_scores(panel.rets, L_SLOW)
    agree, disagree, cvt_idle = 0, 0, 0
    books = panel.books
    for i in range(panel.n):
        cvt_rankable = [b for b in books if sc[b][i] is not None]
        drift_rankable = [b for b in books if sc_drift[b][i] is not None]
        if len(cvt_rankable) < 3:   # need > k=2 to rank
            cvt_idle += 1
            continue
        if len(drift_rankable) < 3:
            continue
        cvt_bottom2 = set(sorted(cvt_rankable, key=lambda b: sc[b][i])[:2])
        drift_bottom2 = set(sorted(drift_rankable, key=lambda b: sc_drift[b][i])[:2])
        if cvt_bottom2 == drift_bottom2:
            agree += 1
        else:
            disagree += 1

    active = agree + disagree
    print()
    print(f"CVT vs XSD ranking agreement: {agree}/{active} days with 2-book rank overlap")
    print(f"  ({cvt_idle} days CVT idle / no signal, {disagree} days CVT active but disagrees)")
    if active > 0:
        print(f"  Agreement rate: {agree*100/active:.1f}%")


# ══════════════════════════════ idea runner ══════════════════════════════

def idea42_cvt(subset: Optional[Sequence[str]] = None, label: str = "fixture 5 books",
               start: Optional[str] = None, end: Optional[str] = None,
               segment: str = "FULL", quiet: bool = False,
               ks: Sequence[int] = (1, 2, 3), ms: Sequence[int] = (1, 20),
               full_controls: bool = True) -> Dict[str, Dict[str, float]]:
    """Idea #42 — does carry VELOCITY (MACD-like) add to carry LEVEL for crisis detection?"""
    panel = dgo.Panel(subset, start, end)
    books, n = panel.books, panel.n

    sc_vel = cvt_scores(panel.rets, L_FAST, L_SLOW)
    sc_drift = xsd.drift_scores(panel.rets, L_SLOW)    # XSD control (carry level)

    rows: List[Tuple[str, Dict[str, List[float]], float]] = []

    # ── baseline: #39 CDR absolute M=20 ──
    abs20 = xsd.absolute_flags(panel, HURDLE, L_SLOW, 20)
    rows.append(("#39 CDR absolute M=20", ecr.alloc_recycle(books, abs20, n), 0.0))

    # ── decisive control: XSD k=2 M=20 (same framework, carry LEVEL score) ──
    xsd_fl = xsd.rank_demotion_flags(sc_drift, 2, 20)
    rows.append(("XSD k=2 M=20 carry-level", ecr.alloc_recycle(books, xsd_fl, n), 0.0))

    # ── CVT configurations (carry velocity as score) ──
    ref_k, ref_m = ks[len(ks) // 2], ms[-1]
    for k in ks:
        for m_days in ms:
            fl = xsd.rank_demotion_flags(sc_vel, k, m_days)
            rows.append((f"CVT k={k} M={m_days}", ecr.alloc_recycle(books, fl, n), 0.0))

    # ── controls ──
    ref_fl = xsd.rank_demotion_flags(sc_vel, ref_k, ref_m)
    ref_duty = xsd.duty(ref_fl)

    rows.append((f"  CTRL top-k flip k={ref_k} M={ref_m}",
                 ecr.alloc_recycle(books,
                                   xsd.rank_demotion_flags(sc_vel, ref_k, ref_m,
                                                           worst_first=False), n), 0.0))
    if full_controls:
        h_only, d_only = xsd.match_duty_hurdle(panel, ref_duty, L_SLOW, ref_m)
        rows.append((f"  CTRL hurdle-only duty {d_only*100:.0f}% vs {ref_duty*100:.0f}%",
                     ecr.alloc_recycle(books,
                                       xsd.absolute_flags(panel, h_only, L_SLOW, ref_m),
                                       n), 0.0))
        lkb_m, h_m, m_m, d_m = xsd.match_duty_absolute(panel, ref_duty)
        rows.append((f"  CTRL duty-matched abs {d_m*100:.0f}% L{lkb_m}/M{m_m}",
                     ecr.alloc_recycle(books,
                                       xsd.absolute_flags(panel, h_m, lkb_m, m_m),
                                       n), 0.0))
    rows.append(("  CTRL static-matched",
                 ecr.alloc_static_matched(ecr.alloc_recycle(books, ref_fl, n)), 0.0))
    rows.append((f"  under {int(ecr.CONC_CAP*100)}% per-name cap k={ref_k} M={ref_m}",
                 ecr.alloc_recycle(books, ref_fl, n, cap=ecr.CONC_CAP), 0.0))

    base = ecr._raw_metrics(panel)
    if not quiet:
        ecr._header(f"IDEA #42 CVT — carry velocity trigger [{segment}] — {label}",
                    panel, base)

    results: Dict[str, Dict[str, float]] = {}
    for name, w, cash_rate in rows:
        m = ecr.portfolio_metrics(panel, w, cash_annual=cash_rate)
        results[name.strip()] = m
        if not quiet:
            ecr._row(name, m, base)

    if not quiet:
        print("-" * 110)
        print(f"CVT parameters: L_fast={L_FAST}, L_slow={L_SLOW}, k={ref_k}, M={ref_m}")
        print(f"CVT duty={ref_duty*100:.1f}%; XSD k={ref_k} M={ref_m} duty="
              f"{xsd.duty(xsd.rank_demotion_flags(sc_drift, ref_k, ref_m))*100:.1f}%")
        print("NOTE: On the synthetic fixture, calm-period carry is piecewise-constant,")
        print("  so CVT velocity = 0 in calm periods → None → nobody demoted.")
        print("  XSD level always ranks someone. CVT is a PURE TIMING overlay on the fixture.")
    return results


# ══════════════════════════════ sweep ══════════════════════════════

def sweep(ks: Sequence[int] = (1, 2, 3, 4),
          ms: Sequence[int] = (1, 2, 3, 5, 10, 20, 45)) -> None:
    """ΔCalmar grid over (k demoted, M re-admission days) — same format as #40."""
    panel = dgo.Panel()
    base = ecr._raw_metrics(panel)
    sc = cvt_scores(panel.rets)
    sc_d = xsd.drift_scores(panel.rets, L_SLOW)

    km_hdr = "k \\ M"
    print()
    print("=" * 110)
    print(f"#42 CVT — SWEEP ΔCalmar vs raw ({base['calmar']:.2f}); "
          f"rows = k demoted, cols = M re-admission days")
    print("=" * 110)
    print(f"{km_hdr:>8s}" + "".join(f"{m:>8d}" for m in ms))
    for k in ks:
        cells = []
        for m_days in ms:
            w = ecr.alloc_recycle(panel.books,
                                  xsd.rank_demotion_flags(sc, k, m_days),
                                  panel.n)
            cells.append(ecr.portfolio_metrics(panel, w)["calmar"] - base["calmar"])
        print(f"{k:>8d}" + "".join(f"{c:>+8.2f}" for c in cells))

    print()
    print("XSD carry-level (same grid — for comparison):")
    print(f"{km_hdr:>8s}" + "".join(f"{m:>8d}" for m in ms))
    for k in ks:
        cells = []
        for m_days in ms:
            w = ecr.alloc_recycle(panel.books,
                                  xsd.rank_demotion_flags(sc_d, k, m_days),
                                  panel.n)
            cells.append(ecr.portfolio_metrics(panel, w)["calmar"] - base["calmar"])
        print(f"{k:>8d}" + "".join(f"{c:>+8.2f}" for c in cells))


# ══════════════════════════════ main ══════════════════════════════

def main(argv: Sequence[str]) -> int:
    print("Idea #42 CVT — Carry Velocity Trigger")
    print("ADVISORY, OUTSIDE_RISKPOLICY, evidence L0 (backtest on SYNTHETIC FIXTURE, NOT live).")
    print("Capital does not move. Live track and RiskPolicy v1.0 untouched.")
    print()
    print("USING FIXTURE DATA: real panel not available in this environment; materialising from")
    print("spa_core/strategy_lab/aggressive_lab/fixtures.py (deterministic, stdlib-only, no LLM).")
    print("5 usable books: leverage_loop, lrt_carry, points_farm, susde_dn, variant_d")
    print("(thin_new excluded: <61 backtest days)")

    _ensure_fixture()

    panel = dgo.Panel()
    print(f"\nPanel: {panel.n} days from {panel.axis[0]}..{panel.axis[-1]}, "
          f"{len(panel.books)} books: {', '.join(panel.books)}")

    _cvt_stats(panel)

    idea42_cvt()
    sweep()

    ecr.train_test(idea42_cvt,
                   ["#39 CDR absolute M=20",
                    "XSD k=2 M=20 carry-level",
                    "CVT k=1 M=20",
                    "CVT k=2 M=20",
                    "CVT k=3 M=20",
                    "CTRL static-matched",
                    "CTRL top-k flip k=2 M=20"])

    ecr.leave_one_out(idea42_cvt, "CVT k=2 M=20")

    fl = xsd.rank_demotion_flags(cvt_scores(panel.rets), 2, 20)
    ecr.information_controls(panel, fl, "CVT k=2 M=20")
    ecr.weight_decomposition(panel, fl, "CVT k=2 M=20 recycled")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
