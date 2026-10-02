#!/usr/bin/env python3
"""
scripts/edge_real_panel_ensemble.py — Ideas #16 + #17 on the REAL aggressive-lab panel

WHY THIS IS DIFFERENT FROM EVERY PRIOR REGISTRY IDEA (#1–#15)
  Every prior idea in docs/DYNAMIC_LEVERAGE_GUARDIAN.md was backtested on the SYNTHETIC
  stress fixture (spa_core/strategy_lab/aggressive_lab/fixtures.py) or on synthetic-smooth
  rates/RWA legs. The #15 KODS entry itself documents the fixture's core limitation:
  "σ² ≈ 0 in calm periods (pure deterministic drift without noise) → Kelly degenerates to a
  binary switch." So the whole registry's causal-control conclusions have never been checked
  on data that carries REAL calm-period variance.

  This harness uses the REAL 854-day panel instead:
    data/aggressive_lab/<book>/realized_series.jsonl  (mtm_source="realized_backtest_series")
  built by spa_core/strategy_lab/aggressive_lab/harness.py from the REAL deep-history feeds
  (load_real_susde_history → real Pendle PT 2024–2026 implied yields + real deep funding
  history; fail-CLOSED, refuses to fabricate). It has REAL calm-period noise, REAL crisis
  days (2024-08 ETH crash, 2025-10 USDe unwind, 2025-04, 2026-02), and 10 REAL books sharing
  one date axis (2024-03-05 .. 2026-07-16) — exactly the "real book-return series on a real
  date axis" the registry flagged as DATA-BLOCKED at the end of idea #14.

IDEA #16 — Cross-Book Ensemble Breadth as a causal ONSET signal
  Idea #13 proved ~97% of the live crisis-control gap is ONSET detection (knowing the START).
  Idea #14 tested the obvious leading signal — a book's OWN realized vol — and it FAILED:
  fixture crises are front-loaded, so own-vol spikes SIMULTANEOUSLY with own-drawdown (no
  lead). #14's honest recommendation: the right onset signal is EXOGENOUS to the book.

  #16 tests the cheapest exogenous signal we already have on the real panel: CROSS-BOOK
  BREADTH. When a systemic event hits, many books turn down together, and FAST books
  (directional / levered) draw down on day 1 while a SLOW book (funding-flip susde_dn)
  bleeds over several days. So "how many OTHER books are already in drawdown" may LEAD the
  target book's own drawdown where its own vol cannot.

  Signals compared on a target book (all strictly causal, computed THROUGH day t-1):
    raw            — no overlay (baseline)
    own-DD (#9)    — de-risk when target's own trailing drawdown ≤ −θ
    own-vol (#14)  — de-risk when target's own trailing realized vol > vol_thr
    breadth (#16)  — de-risk when ≥ k of the OTHER 9 books are each in drawdown ≥ θ_book
  De-risk = move the target book to CASH (0%/day — conservative; a yield-bearing floor would
  only help) until the signal clears. Metric: Calmar / maxDD / APY of the overlaid equity,
  plus a LEAD-LAG cross-correlation of the breadth signal vs the target's own drawdown to
  measure whether breadth genuinely leads.

IDEA #17 — Cross-Sectional Risk-Parity across the REAL 10-book panel
  Idea #2 tested naive diversification on the fixture (failed: two survivors correlated 0.87).
  Idea #3 tested a cross-desk blend on synthetic-smooth rates/RWA legs. NEITHER tested the
  REAL 10-book panel. #17 asks the plain question: does real cross-sectional diversification
  of these 10 real books deliver "risk lower" vs the best single book?
    equal-weight        — 1/N across all 10
    inverse-vol (RP)    — causal trailing-vol risk-parity weights
    inverse-vol + floor — RP but the de-risked sleeve (breadth signal) parks in cash
  Reported against best-single-book (hindsight) and the real cross-book correlation matrix.

HONEST CAVEATS (printed in the verdict, mirrored into the registry)
  (a) SURVIVORSHIP: these 10 books are the surviving roster; a real forward universe would
      include books that were delisted after blowing up → cross-sectional results are an
      upper bound on real diversification.
  (b) The panel is a REALIZED BACKTEST over the real feed history, not a live forward track.
      The file also carries phase="forward" rows (the live paper book, RE-ANCHORED at ~$100k);
      they are a DIFFERENT accounting series and are excluded by load_panel — see the phase
      note above the loader. Until 2026-08-02 they were not, and the numbers #16/#17 were
      first published with (2026-07-16) carry that artifact; section 0 of the report prints
      its size per book.
  (f) The books are REGENERATED nightly (card agent-aggressive-lab-books-are-regenerated
      measured 853/853 rows changing between backups, shifts up to −9.7%), so any number here
      is reproducible only against the panel snapshot of the run date, which the report stamps.
  (c) De-risk to cash is frictionless here (no gas/slippage); idea #10 showed the causal
      overlay break-even is ~96 bps/switch — real costs bite only past that.
  (d) Params (θ, vol_thr, k, lookback) are swept on the full run AND re-checked OOS
      (train 2024-03..2025-06 / test 2025-06..2026-07). Calm OOS windows under-test crisis
      protection (same calm-OOS caveat as #1/#4/#8/#9/#14/#15).
  (e) Evidence level: L0 (backtest on real feed history). NOT a live/forward result.

Does NOT touch spa_core/execution, the live paper track (data/equity_curve_daily.json),
RiskPolicy v1.0, the site, or any agent. Read-only over data/aggressive_lab/. Advisory /
paper / OUTSIDE_RISKPOLICY. stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import itertools
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
PANEL_DIR = ROOT / "data" / "aggressive_lab"

# OOS split boundary: params fit on [start, TRAIN_END], validated on (TRAIN_END, end].
TRAIN_END = "2025-06-30"

# Real named crisis windows on THIS panel (from the real feed history; used only for
# per-crisis attribution reporting — NOT for any signal, which stays strictly causal).
CRISIS_WINDOWS = [
    ("eth_crash_2024_08", "2024-08-01", "2024-08-20"),
    ("usde_unwind_2025_10", "2025-10-05", "2025-10-25"),
    ("rseth_depeg_2026_04", "2026-04-01", "2026-04-20"),
]

# A one-day move beyond this INSIDE a single phase block is an accounting discontinuity, not
# a return. Refuse the book rather than compound it (fail-CLOSED). Same constant/semantics as
# scripts/edge_calm_fp_tax.py::JUMP_REFUSE — the reference implementation named by the card.
JUMP_REFUSE = 0.50


# ─────────────────────────── real-panel loader ───────────────────────────
# PHASE DISCIPLINE (fixed 2026-08-02, card agent-idea16-17-phase-glue-contamination).
# realized_series.jsonl glues TWO different accounting series into one file: the
# phase="backtest" block (equity compounding from $100k) and the phase="forward" rows of the
# live paper book, which RE-ANCHOR at ~$100k. Diffing equity_usd across that boundary turns a
# change of accounting series into a fabricated one-day return of −31% (susde_dn), −84%
# (pendle_yt_susde) or +105% (eth_directional). The original loader here did exactly that, and
# the published numbers of registry ideas #16/#17 were computed on it. The boundary is now cut,
# never crossed. Canonical semantics follow the producer's own reader
# (spa_core/strategy_lab/aggressive_lab/loader.py: a missing/unknown `phase` means "forward"),
# so a row without an explicit phase="backtest" is NOT silently treated as backtest.
def _read_rows(path: Path) -> List[dict]:
    out: List[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def backtest_block(rows: Sequence[dict]) -> List[dict]:
    """Keep only the phase=="backtest" rows, in date order (the block that is one series)."""
    keep = [r for r in rows if r.get("phase") == "backtest"]
    keep.sort(key=lambda r: str(r.get("date") or r.get("as_of") or ""))
    return keep


def _equity_points(rows: Sequence[dict]) -> Tuple[List[str], List[float]]:
    dates: List[str] = []
    eq: List[float] = []
    for row in rows:
        d = row.get("date") or row.get("as_of")
        e = row.get("equity_usd")
        if d is None or e is None or float(e) <= 0:
            continue
        dates.append(str(d))
        eq.append(float(e))
    return dates, eq


def load_panel(panel_dir: Path = PANEL_DIR) -> Dict[str, Dict[str, float]]:
    """{book: {date: daily_return}} over the phase=="backtest" block of each book.

    Daily return is derived from equity_usd (the authoritative marked equity), NOT from
    mtm_today_pct, so a book with an odd first-day mark cannot distort the compounding.
    Fail-CLOSED on three counts, none of which fabricates a point:
      • rows outside the phase="backtest" block are never diffed against it (see above);
      • a book with < 60 usable points is dropped;
      • a residual same-block move beyond JUMP_REFUSE raises instead of compounding.
    """
    panel: Dict[str, Dict[str, float]] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        book = sub.parent.name
        dates, eq = _equity_points(backtest_block(_read_rows(sub)))
        if len(dates) < 60:
            continue
        rets: Dict[str, float] = {}
        for i in range(1, len(dates)):
            ret = eq[i] / eq[i - 1] - 1.0
            if abs(ret) > JUMP_REFUSE:
                raise ValueError(
                    f"{book}: {abs(ret) * 100:.1f}% one-day move at {dates[i]} inside a single "
                    f"phase block — refusing to treat an accounting discontinuity as a return"
                )
            rets[dates[i]] = ret
        panel[book] = rets
    if not panel:
        raise RuntimeError(f"no usable books in {panel_dir} — refusing to fabricate a panel")
    return panel


def load_glued_panel(panel_dir: Path = PANEL_DIR) -> Dict[str, Dict[str, float]]:
    """The OLD phase-blind loader — kept ONLY to quantify the artifact it produced.

    Never used by run_idea16 / run_idea17. main() prints the difference between this and
    load_panel() so the size of the correction is visible instead of asserted.
    """
    panel: Dict[str, Dict[str, float]] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        book = sub.parent.name
        eq: Dict[str, float] = {}
        for row in _read_rows(sub):
            d = row.get("date") or row.get("as_of")
            e = row.get("equity_usd")
            if d and e is not None and float(e) > 0:
                eq[d] = float(e)
        dates = sorted(eq)
        if len(dates) < 60:
            continue
        panel[book] = {dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0 for i in range(1, len(dates))}
    return panel


def glue_artifact(panel_dir: Path = PANEL_DIR) -> Dict[str, Dict[str, float]]:
    """Per book: the seam move the phase-blind loader read as a return, and the metric delta.

    {book: {"seam_ret", "apy_glued", "apy_clean", "maxdd_glued", "maxdd_clean"}}.
    Books present in only one of the two panels are omitted (nothing is invented).
    """
    clean, glued = load_panel(panel_dir), load_glued_panel(panel_dir)
    out: Dict[str, Dict[str, float]] = {}
    for book in sorted(set(clean) & set(glued)):
        c_dates, g_dates = sorted(clean[book]), sorted(glued[book])
        extra = [d for d in g_dates if d not in clean[book]]
        seam = max((glued[book][d] for d in extra), key=abs, default=0.0)
        pc, pg = perf([clean[book][d] for d in c_dates]), perf([glued[book][d] for d in g_dates])
        out[book] = {
            "seam_ret": seam,
            "apy_glued": pg["apy"], "apy_clean": pc["apy"],
            "maxdd_glued": pg["maxdd"], "maxdd_clean": pc["maxdd"],
        }
    return out


def common_axis(panel: Dict[str, Dict[str, float]]) -> List[str]:
    """Sorted dates present in EVERY book (fail-closed intersection)."""
    sets = [set(r) for r in panel.values()]
    inter = set.intersection(*sets) if sets else set()
    return sorted(inter)


def slice_axis(axis: Sequence[str], start: Optional[str], end: Optional[str]) -> List[str]:
    return [d for d in axis if (start is None or d >= start) and (end is None or d <= end)]


# ─────────────────────────── metrics ───────────────────────────
def _equity(returns: Sequence[float]) -> List[float]:
    eq = [1.0]
    for r in returns:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _max_drawdown(eq: Sequence[float]) -> float:
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd  # ≤ 0


def perf(returns: Sequence[float]) -> Dict[str, float]:
    n = len(returns)
    if n == 0:
        return {"apy": 0.0, "maxdd": 0.0, "calmar": 0.0, "vol": 0.0, "sharpe": 0.0}
    eq = _equity(returns)
    cagr = eq[-1] ** (365.0 / n) - 1.0
    mdd = _max_drawdown(eq)
    mean = sum(returns) / n
    var = sum((x - mean) ** 2 for x in returns) / (n - 1) if n > 1 else 0.0
    vol_ann = math.sqrt(var) * math.sqrt(365)
    calmar = cagr / abs(mdd) if mdd < 0 else float("inf")
    sharpe = (mean * 365) / vol_ann if vol_ann > 0 else 0.0
    return {"apy": cagr, "maxdd": mdd, "calmar": calmar, "vol": vol_ann, "sharpe": sharpe}


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / math.sqrt(va * vb)


# ─────────────────────────── causal signal builders ───────────────────────────
def _trailing_drawdown(returns: Sequence[float]) -> List[float]:
    """dd[i] = drawdown of the equity built from returns[:i] (THROUGH t-1, causal).
    dd[i] ≤ 0. Uses only info available before acting on day i."""
    dd: List[float] = []
    eq = 1.0
    peak = 1.0
    for i in range(len(returns)):
        # state reflects returns[0..i-1]
        dd.append(eq / peak - 1.0 if peak > 0 else 0.0)
        eq *= 1.0 + returns[i]
        peak = max(peak, eq)
    return dd


def _trailing_vol(returns: Sequence[float], lookback: int) -> List[float]:
    """vol[i] = std of returns[max(0,i-lookback):i] (THROUGH t-1, causal)."""
    out: List[float] = []
    for i in range(len(returns)):
        w = returns[max(0, i - lookback):i]
        if len(w) < 2:
            out.append(0.0)
            continue
        m = sum(w) / len(w)
        out.append(math.sqrt(sum((x - m) ** 2 for x in w) / (len(w) - 1)))
    return out


def breadth_signal(
    panel_rets: Dict[str, List[float]], target: str, theta_book: float
) -> List[float]:
    """breadth[i] = fraction of the OTHER books whose OWN trailing drawdown (through t-1)
    is ≤ −theta_book on day i. Strictly causal per book. Range [0, 1]."""
    others = [b for b in panel_rets if b != target]
    dds = {b: _trailing_drawdown(panel_rets[b]) for b in others}
    n = len(panel_rets[target])
    out: List[float] = []
    for i in range(n):
        hit = sum(1 for b in others if dds[b][i] <= -theta_book)
        out.append(hit / len(others) if others else 0.0)
    return out


def dispersion_signal(panel_rets: Dict[str, List[float]], lookback: int) -> List[float]:
    """disp[i] = cross-sectional stdev of each book's OWN trailing vol (through t-1) — a
    causal proxy for "how stressed is the ensemble right now"."""
    vols = {b: _trailing_vol(r, lookback) for b, r in panel_rets.items()}
    books = list(panel_rets)
    n = len(next(iter(panel_rets.values())))
    out: List[float] = []
    for i in range(n):
        vs = [vols[b][i] for b in books]
        m = sum(vs) / len(vs)
        out.append(math.sqrt(sum((x - m) ** 2 for x in vs) / (len(vs) - 1)) if len(vs) > 1 else 0.0)
    return out


# ─────────────────────────── de-risk overlay ───────────────────────────
def apply_overlay(returns: Sequence[float], derisk: Sequence[bool], safe_daily: float = 0.0) -> List[float]:
    """When derisk[i] is True, the book is in CASH that day (safe_daily), else it earns its
    own return. derisk is computed causally (from state through t-1), so acting on day i is
    admissible. safe_daily default 0.0 = flat cash (conservative)."""
    return [safe_daily if derisk[i] else returns[i] for i in range(len(returns))]


def _lead_lag(signal: Sequence[float], own_dd_severity: Sequence[float], max_lag: int = 10) -> Tuple[int, float]:
    """Find the lag L (0..max_lag) maximizing corr(signal[t-L], own_dd_severity[t]).
    own_dd_severity[t] = max(0, -dd[t]) so bigger = deeper. A positive best-lag L>0 means the
    signal LEADS own drawdown by L days. Returns (best_lag, best_corr)."""
    best_lag, best_corr = 0, -2.0
    for lag in range(0, max_lag + 1):
        s = signal[: len(signal) - lag] if lag else signal
        d = own_dd_severity[lag:] if lag else own_dd_severity
        c = _pearson(s, d)
        if c > best_corr:
            best_lag, best_corr = lag, c
    return best_lag, best_corr


# ─────────────────────────── idea #16 ───────────────────────────
def run_idea16(panel: Dict[str, Dict[str, float]], axis: List[str], target: str,
               verbose: bool = True) -> Dict:
    rets_by_book = {b: [panel[b][d] for d in axis] for b in panel}
    tgt = rets_by_book[target]

    # candidate overlays (param grids)
    dd_thetas = [0.005, 0.01, 0.02, 0.03, 0.05]
    vol_lkbs, vol_thrs = [10, 20], [0.004, 0.008, 0.015]
    breadth_thetas, breadth_ks = [0.02, 0.05, 0.10], [0.25, 0.40, 0.55]

    raw = perf(tgt)

    # DUTY_CAP: an overlay that de-risks (sits in cash) on almost every day trivially wins
    # Calmar by simply "not running the strategy" — a degenerate, non-actionable optimum. A
    # PROTECTIVE overlay must keep the book live most of the time (duty = cash-fraction ≤ cap)
    # and only step aside around stress. We select the best-Calmar overlay subject to that,
    # and separately expose the unconstrained (degenerate) optimum to keep the story honest.
    DUTY_CAP = 0.50

    def best_over(grid_fn, grids):
        best_capped = None
        best_uncapped = None
        for params in grids:
            derisk = grid_fn(*params)
            p = perf(apply_overlay(tgt, derisk))
            row = {"params": params, **p, "duty": sum(derisk) / len(derisk)}
            if best_uncapped is None or row["calmar"] > best_uncapped["calmar"]:
                best_uncapped = row
            if row["duty"] <= DUTY_CAP and (best_capped is None or row["calmar"] > best_capped["calmar"]):
                best_capped = row
        # if nothing satisfies the duty cap, fall back to the least-duty overlay (most live)
        if best_capped is None:
            best_capped = best_uncapped
        best_capped = dict(best_capped)
        best_capped["degenerate_uncapped"] = {
            "calmar": best_uncapped["calmar"], "duty": best_uncapped["duty"], "params": best_uncapped["params"],
        }
        return best_capped

    own_dd = _trailing_drawdown(tgt)
    best_dd = best_over(
        lambda th: [own_dd[i] <= -th for i in range(len(tgt))],
        [(th,) for th in dd_thetas],
    )

    def vol_derisk(lkb, thr):
        v = _trailing_vol(tgt, lkb)
        return [v[i] > thr for i in range(len(tgt))]

    best_vol = best_over(vol_derisk, [(lkb, thr) for lkb in vol_lkbs for thr in vol_thrs])

    def breadth_derisk(th, k):
        b = breadth_signal(rets_by_book, target, th)
        return [b[i] >= k for i in range(len(tgt))]

    best_breadth = best_over(breadth_derisk, [(th, k) for th in breadth_thetas for k in breadth_ks])

    # lead-lag: does breadth (at its best theta) lead the target's own drawdown?
    own_sev = [max(0.0, -x) for x in own_dd]
    br = breadth_signal(rets_by_book, target, best_breadth["params"][0])
    br_lag, br_corr = _lead_lag(br, own_sev)
    vol_series = _trailing_vol(tgt, best_vol["params"][0])
    vol_lag, vol_corr = _lead_lag(vol_series, own_sev)

    # cross-book lead-lag: for EVERY book, does breadth-of-OTHERS lead its own drawdown?
    # This makes the "breadth as onset signal" verdict robust (not cherry-picked on target).
    cross_leadlag: Dict[str, Tuple[int, float]] = {}
    for b in rets_by_book:
        b_dd = _trailing_drawdown(rets_by_book[b])
        b_sev = [max(0.0, -x) for x in b_dd]
        b_breadth = breadth_signal(rets_by_book, b, 0.05)
        cross_leadlag[b] = _lead_lag(b_breadth, b_sev)

    # OOS: refit each family on train, apply the winning params to test
    train_axis = slice_axis(axis, None, TRAIN_END)
    test_axis = slice_axis(axis, TRAIN_END, None)
    ti0 = len(train_axis)

    def oos_for(best_row, derisk_full):
        test_ret = tgt[ti0:]
        test_de = derisk_full[ti0:]
        return perf(apply_overlay(test_ret, test_de))

    # rebuild derisk arrays for the winning params over the FULL axis, then slice test
    de_raw = [False] * len(tgt)
    de_dd = [own_dd[i] <= -best_dd["params"][0] for i in range(len(tgt))]
    bv = _trailing_vol(tgt, best_vol["params"][0])
    de_vol = [bv[i] > best_vol["params"][1] for i in range(len(tgt))]
    bb = breadth_signal(rets_by_book, target, best_breadth["params"][0])
    de_br = [bb[i] >= best_breadth["params"][1] for i in range(len(tgt))]

    oos = {
        "raw": perf(tgt[ti0:]),
        "own_dd": oos_for(best_dd, de_dd),
        "own_vol": oos_for(best_vol, de_vol),
        "breadth": oos_for(best_breadth, de_br),
    }

    # per-crisis maxDD (full run)
    def crisis_dd(derisk):
        overlaid = apply_overlay(tgt, derisk)
        out = {}
        for name, s, e in CRISIS_WINDOWS:
            idx = [i for i, d in enumerate(axis) if s <= d <= e]
            if not idx:
                continue
            seg = [overlaid[i] for i in idx]
            out[name] = _max_drawdown(_equity(seg))
        return out

    result = {
        "target": target,
        "n_days": len(axis),
        "raw": raw,
        "own_dd": best_dd,
        "own_vol": best_vol,
        "breadth": best_breadth,
        "leadlag": {"breadth": (br_lag, br_corr), "own_vol": (vol_lag, vol_corr)},
        "cross_leadlag": cross_leadlag,
        "oos": oos,
        "crisis": {
            "raw": crisis_dd(de_raw),
            "own_dd": crisis_dd(de_dd),
            "breadth": crisis_dd(de_br),
        },
    }

    if verbose:
        print(f"\n{'='*74}\nIDEA #16 — Cross-Book Ensemble Breadth as ONSET signal (target={target})")
        print(f"REAL panel: {len(axis)} shared days {axis[0]}..{axis[-1]} · {len(panel)} books\n")
        print(f"  {'overlay':<24}{'APY':>9}{'maxDD':>9}{'Calmar':>9}{'duty%':>8}")
        print(f"  {'raw (no overlay)':<24}{raw['apy']*100:>8.2f}%{raw['maxdd']*100:>8.2f}%{raw['calmar']:>9.2f}{0:>8}")
        for name, row in (("own-DD (#9)", best_dd), ("own-vol (#14)", best_vol), ("breadth (#16)", best_breadth)):
            print(f"  {name:<24}{row['apy']*100:>8.2f}%{row['maxdd']*100:>8.2f}%{row['calmar']:>9.2f}{row['duty']*100:>7.1f}  params={row['params']}  (protective, duty≤{int(DUTY_CAP*100)}%)")
            deg = row["degenerate_uncapped"]
            print(f"    └─ unconstrained max-Calmar = {deg['calmar']:.1f} but duty={deg['duty']*100:.1f}% → degenerate 'stay-in-cash' optimum (NOT an edge)")
        print(f"\n  LEAD-LAG vs own drawdown severity (lag>0 ⇒ signal LEADS by N days):")
        print(f"    breadth : best_lag={br_lag}d corr={br_corr:.3f}")
        print(f"    own-vol : best_lag={vol_lag}d corr={vol_corr:.3f}")
        print(f"\n  CROSS-BOOK breadth lead-lag (breadth-of-OTHERS vs each book's own drawdown):")
        n_lead = sum(1 for lag, c in cross_leadlag.values() if lag > 0 and c > 0.2)
        for b, (lag, c) in sorted(cross_leadlag.items(), key=lambda kv: -kv[1][1]):
            flag = "  ← LEADS" if (lag > 0 and c > 0.2) else ""
            print(f"    {b:<20} best_lag={lag}d corr={c:6.3f}{flag}")
        print(f"    → {n_lead}/{len(cross_leadlag)} books where breadth genuinely leads (lag>0 & corr>0.2)")
        print(f"\n  OOS (fit family on train ≤{TRAIN_END}, apply to unseen test):")
        for name in ("raw", "own_dd", "own_vol", "breadth"):
            p = oos[name]
            print(f"    {name:<10} APY={p['apy']*100:6.2f}% maxDD={p['maxdd']*100:6.2f}% Calmar={p['calmar']:6.2f}")
        print(f"\n  per-crisis maxDD (raw vs own-DD vs breadth):")
        for name, _, _ in CRISIS_WINDOWS:
            r = result["crisis"]["raw"].get(name)
            d = result["crisis"]["own_dd"].get(name)
            b = result["crisis"]["breadth"].get(name)
            if r is not None:
                print(f"    {name:<22} raw={r*100:6.2f}%  own-DD={d*100:6.2f}%  breadth={b*100:6.2f}%")
    return result


# ─────────────────────────── idea #17 ───────────────────────────
def run_idea17(panel: Dict[str, Dict[str, float]], axis: List[str], verbose: bool = True) -> Dict:
    books = list(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    n = len(axis)

    # per-book performance
    per_book = {b: perf(rets[b]) for b in books}
    best_single = max(books, key=lambda b: per_book[b]["calmar"])

    # correlation matrix (daily returns)
    corr = {}
    for i, a in enumerate(books):
        for b in books[i + 1:]:
            corr[(a, b)] = _pearson(rets[a], rets[b])
    avg_corr = sum(corr.values()) / len(corr) if corr else 0.0

    # equal weight
    ew = [sum(rets[b][t] for b in books) / len(books) for t in range(n)]

    # inverse-vol risk parity (causal trailing vol, lookback 30d)
    LKB = 30
    vols = {b: _trailing_vol(rets[b], LKB) for b in books}
    rp: List[float] = []
    for t in range(n):
        inv = {b: (1.0 / vols[b][t] if vols[b][t] > 1e-9 else 0.0) for b in books}
        s = sum(inv.values())
        if s <= 0:
            rp.append(sum(rets[b][t] for b in books) / len(books))
            continue
        w = {b: inv[b] / s for b in books}
        rp.append(sum(w[b] * rets[b][t] for b in books))

    # inverse-vol + breadth floor: de-risk the whole sleeve when ensemble breadth is high
    breadth = breadth_signal(rets, target=books[0], theta_book=0.05)  # any book's "others"
    # recompute a symmetric ensemble breadth = fraction of ALL books in drawdown
    dds_all = {b: _trailing_drawdown(rets[b]) for b in books}
    ens_breadth = [sum(1 for b in books if dds_all[b][t] <= -0.05) / len(books) for t in range(n)]
    rp_floor = [0.0 if ens_breadth[t] >= 0.5 else rp[t] for t in range(n)]

    p_ew, p_rp, p_floor = perf(ew), perf(rp), perf(rp_floor)
    p_best = per_book[best_single]

    # OOS
    ti0 = len(slice_axis(axis, None, TRAIN_END))
    oos = {
        "equal_weight": perf(ew[ti0:]),
        "inverse_vol": perf(rp[ti0:]),
        "inverse_vol_floor": perf(rp_floor[ti0:]),
        "best_single": perf(rets[best_single][ti0:]),
    }

    result = {
        "books": books,
        "per_book": per_book,
        "best_single": best_single,
        "avg_corr": avg_corr,
        "equal_weight": p_ew,
        "inverse_vol": p_rp,
        "inverse_vol_floor": p_floor,
        "best_single_perf": p_best,
        "oos": oos,
    }

    if verbose:
        print(f"\n{'='*74}\nIDEA #17 — Cross-Sectional Risk-Parity on the REAL 10-book panel")
        print(f"  avg pairwise daily-return corr across {len(books)} books = {avg_corr:.3f}")
        print(f"  best single book by Calmar = {best_single} (Calmar {p_best['calmar']:.2f}, maxDD {p_best['maxdd']*100:.2f}%)\n")
        print(f"  {'portfolio':<24}{'APY':>9}{'maxDD':>9}{'Calmar':>9}{'annVol':>9}")
        for name, p in (("equal-weight", p_ew), ("inverse-vol (RP)", p_rp),
                        ("inverse-vol + floor", p_floor), (f"best-single ({best_single})", p_best)):
            print(f"  {name:<24}{p['apy']*100:>8.2f}%{p['maxdd']*100:>8.2f}%{p['calmar']:>9.2f}{p['vol']*100:>8.2f}%")
        print(f"\n  OOS (unseen test > {TRAIN_END}):")
        for name in ("equal_weight", "inverse_vol", "inverse_vol_floor", "best_single"):
            p = oos[name]
            print(f"    {name:<20} APY={p['apy']*100:6.2f}% maxDD={p['maxdd']*100:6.2f}% Calmar={p['calmar']:6.2f}")
    return result



# ===========================================================================================
# #122 PLB — Panel Live Breadth · #123 NLF — N-Leg Frontier          (added 2026-10-02)
# ===========================================================================================
# These two live HERE, beside the loader, on purpose: what they measure is a property of this
# panel that every consumer of `load_panel` has been reading wrongly, including this file's own
# `run_idea17`. Putting the correction in a separate script would have put the instrument one
# import away from the defect it describes.
#
#   PLB  — how many of the "ten books" are still MOVING on the days being judged, what that does
#          to EW-10 as a zero, and where an inverse-risk sizer actually sends the money.
#   NLF  — the result curve by NUMBER of live legs, each size's membership chosen on TRAIN only.
#
# Advisory / paper / OUTSIDE_RISKPOLICY, like the rest of this file. stdlib-only, deterministic.

#: registry-canonical TRAIN/TEST boundary. TRAIN_END above is the same date; named again here
#: so a reader of this section does not have to scroll to learn which split it means.
PLB_SPLIT = TRAIN_END
#: canonical round-trip toll, #10/#49. A STATIC subset pays it once, on day one.
PLB_ROUNDTRIP = 0.0096
#: per-name policy ceiling used across the project; equal weight over N names gives 1/N each.
POLICY_CAP = 0.20
#: a book counts as live over a slice if its return is non-zero on at least this many of its days
LIVE_MIN_MOVES = 1


def book_census(panel_dir: Path = PANEL_DIR) -> Dict[str, dict]:
    """Per-book liveness census read from the RAW series, not from the aligned panel.

    Per book: rows, the first date with ``killed: true`` (or None), the last date on which
    equity_usd changed, and how many days it changed at all. Reading the raw rows matters: in
    the aligned panel a frozen book is a run of 0.0 returns, indistinguishable by eye from a
    book nobody measured. The raw row carries `killed` and a frozen `equity_usd`, so the two
    cases ARE distinguishable here (inv. #17) and the census says which one it found. A book
    with no backtest block gets ``moving_days = None`` — never 0.
    """
    out: Dict[str, dict] = {}
    for sub in sorted(p for p in panel_dir.iterdir() if p.is_dir()):
        series = sub / "realized_series.jsonl"
        if not series.exists():
            continue
        bt = backtest_block(_read_rows(series))
        if not bt:
            out[sub.name] = {"rows": 0, "killed_on": None, "last_move": None,
                             "moving_days": None, "unmeasured": "no backtest block"}
            continue
        killed_on = next((r["date"] for r in bt if r.get("killed")), None)
        last_move: Optional[str] = None
        moving = 0
        prev: Optional[float] = None
        for r in bt:
            eq = r.get("equity_usd")
            if eq is None:
                continue
            if prev is not None and abs(eq - prev) > 1e-9:
                moving += 1
                last_move = r["date"]
            prev = eq
        out[sub.name] = {"rows": len(bt), "killed_on": killed_on, "last_move": last_move,
                         "moving_days": moving, "unmeasured": None}
    if not out:
        raise RuntimeError(f"no books found under {panel_dir} — refusing to report a clean census")
    return out


def live_breadth(axis: Sequence[str], rets: Dict[str, Sequence[float]],
                 books: Sequence[str], *, lo: int = 0, hi: Optional[int] = None,
                 min_moves: int = LIVE_MIN_MOVES) -> Tuple[List[str], List[str]]:
    """Split `books` into (live, frozen) over the slice [lo, hi) of the axis.

    The slice is an ARGUMENT on purpose. Asked over the full axis this panel answers "10 of 10
    live", and it is not lying: each frozen book did move once, early in 2024. Liveness is a
    property of the days being judged, so a caller that wants a useful denominator has to say
    WHICH days.
    """
    hi = len(axis) if hi is None else hi
    live, frozen = [], []
    for b in books:
        moves = sum(1 for i in range(lo, hi) if abs(rets[b][i]) > 1e-12)
        (live if moves >= min_moves else frozen).append(b)
    return live, frozen


def post_kill_era(axis: Sequence[str], census: Dict[str, dict]) -> Tuple[int, Optional[str]]:
    """Index on `axis` of the day after the LAST kill, and that kill's date.

    The era that matters is the one after the last book died: on it the breadth is constant and
    it covers most of the axis. The date is MEASURED from the census, never written down as a
    constant. No kills at all ⇒ (0, None) — no fabricated era date.
    """
    kills = [c["killed_on"] for c in census.values() if c.get("killed_on")]
    if not kills:
        return 0, None
    last = max(kills)
    return sum(1 for d in axis if d <= last), last


def subset_perf(sub: Sequence[str], rets: Dict[str, Sequence[float]],
                lo: int, hi: int, *, roundtrip: float = 0.0) -> Dict[str, float]:
    """Equal-weight the subset over [lo, hi). `roundtrip` is charged ONCE, on day one.

    maxDD is returned as a POSITIVE magnitude here, unlike `perf`, which returns it negative.
    That sign is why this wrapper exists: with the negative convention a `maxdd <= cap` filter
    admits everything and a drawdown cap silently never binds — four different caps printed
    byte-identical frontiers before this was caught.
    """
    if not sub:
        raise ValueError("empty subset — refusing to report a portfolio of nothing")
    k = list(sub)
    series = [sum(rets[b][i] for b in k) / len(k) for i in range(lo, hi)]
    if roundtrip:
        series = list(series)
        series[0] -= roundtrip
    p = dict(perf(series))
    p["maxdd"] = abs(p["maxdd"])
    p["n_days"] = float(hi - lo)
    return p


def plb_load(panel_dir: Path = PANEL_DIR) -> Tuple[List[str], Dict[str, List[float]], List[str]]:
    panel = load_panel(panel_dir)
    axis = common_axis(panel)
    if len(axis) < 200:
        raise RuntimeError(f"common axis is {len(axis)} days — refusing to judge anything on it")
    books = sorted(panel)
    return axis, {b: [panel[b][d] for d in axis] for b in books}, books


def inverse_risk_weights(rets: Dict[str, Sequence[float]], books: Sequence[str],
                         *, end: int, lookback: int = 30, kind: str = "sigma",
                         floor: float = 1e-5) -> Dict[str, float]:
    """Causal inverse-risk weights at day `end` (window strictly before `end`).

    kind='sigma'    — `run_idea17`'s inverse trailing volatility.
    kind='downside' — inverse worst single day in the window (the sigma_down family, #108/#109).
    `floor` is the only free number, and on a panel with frozen books it is what decides their
    weight. It is therefore a parameter, not a constant: the caller can watch it move the answer.
    """
    lo = max(0, end - lookback)
    win = list(range(lo, end))
    if len(win) < 5:
        raise ValueError("window shorter than 5 days — refusing to call that a risk estimate")
    raw: Dict[str, float] = {}
    for b in books:
        vals = [rets[b][i] for i in win]
        if kind == "sigma":
            risk = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        elif kind == "downside":
            risk = -min(list(vals) + [0.0])
        else:
            raise ValueError(f"unknown kind {kind!r}")
        raw[b] = 1.0 / max(risk, floor)
    total = sum(raw.values())
    return {b: raw[b] / total for b in books}


def degenerate_calmar_subsets(universe: Sequence[str], rets: Dict[str, Sequence[float]],
                              *, lo: int, hi: int) -> Tuple[int, int]:
    """(subsets whose maxDD is exactly 0 over the slice, total subsets).

    A zero-drawdown subset has an undefined Calmar; `perf` reports inf. Any selection that
    maximises Calmar therefore picks one of these, and what it picks earns nothing. This count
    is the reason `nleg_frontier` selects on APY under a drawdown cap instead.
    """
    zero = 0
    total = 0
    for n in range(1, len(universe) + 1):
        for sub in itertools.combinations(universe, n):
            total += 1
            if subset_perf(sub, rets, lo, hi)["maxdd"] <= 1e-12:
                zero += 1
    return zero, total


def rank_spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 3:
        raise ValueError("spearman needs two equal series of at least 3 points")
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        raise ValueError("a constant series has no rank correlation — refusing to return 0.0")

    def rank(v: Sequence[float]) -> List[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        for pos, i in enumerate(order):
            out[i] = float(pos)
        return out

    a, b = rank(xs), rank(ys)
    ma, mb = statistics.mean(a), statistics.mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    sa = sum((x - ma) ** 2 for x in a) ** 0.5
    sb = sum((y - mb) ** 2 for y in b) ** 0.5
    return cov / (sa * sb)


def choice_transfer(universe: Sequence[str], rets: Dict[str, Sequence[float]],
                    *, train_hi: int, test_hi: int) -> Dict[str, float]:
    """Does the TRAIN ranking of subsets survive into TEST? Rank correlation over ALL subsets.

    This is the only thing standing between «the TRAIN-best subset won on TEST» and «one of N
    subsets won on TEST». A high value says the choice is transferable; it does NOT say the
    mechanism is alpha — on this panel the book LEVELS are nearly fixed across the two halves,
    and ranking nearly-fixed levels is easy.
    """
    subs = [s for n in range(1, len(universe) + 1) for s in itertools.combinations(universe, n)]
    tr = [subset_perf(s, rets, 0, train_hi) for s in subs]
    te = [subset_perf(s, rets, train_hi, test_hi) for s in subs]
    return {
        "n_subsets": float(len(subs)),
        "apy_spearman": rank_spearman([p["apy"] for p in tr], [p["apy"] for p in te]),
        "maxdd_spearman": rank_spearman([p["maxdd"] for p in tr], [p["maxdd"] for p in te]),
    }


def nleg_frontier(universe: Sequence[str], rets: Dict[str, Sequence[float]],
                  *, train_hi: int, test_hi: int, cap: float,
                  roundtrip: float = 0.0) -> List[dict]:
    """For each N: the TRAIN-best subset under the drawdown cap, with its TEST result.

    Selection is «max TRAIN APY subject to |TRAIN maxDD| <= cap», and it reads the TRAIN slice
    only. A cap that admits no subset of size N yields a row with `admitted = 0`, every number
    None and a named reason — the third outcome, never a zero and never a dropped line (inv. #17).
    """
    rows: List[dict] = []
    for n in range(1, len(universe) + 1):
        cand = []
        for sub in itertools.combinations(universe, n):
            tr = subset_perf(sub, rets, 0, train_hi, roundtrip=roundtrip)
            if tr["maxdd"] <= cap:
                cand.append((sub, tr))
        if not cand:
            rows.append({"n": n, "admitted": 0, "subset": None, "train": None, "test": None,
                         "test_rank": None, "admissible_by_policy": (1.0 / n) <= POLICY_CAP,
                         "reason": f"no subset of size {n} has |TRAIN maxDD| <= {cap:.4f}"})
            continue
        best_sub, best_tr = max(cand, key=lambda kv: kv[1]["apy"])
        tests = {sub: subset_perf(sub, rets, train_hi, test_hi, roundtrip=roundtrip)
                 for sub, _ in cand}
        ordered = sorted((t["apy"] for t in tests.values()), reverse=True)
        rows.append({"n": n, "admitted": len(cand), "subset": list(best_sub),
                     "train": best_tr, "test": tests[best_sub],
                     "test_rank": ordered.index(tests[best_sub]["apy"]) + 1,
                     "test_median_apy": statistics.median(ordered),
                     "test_best_apy": ordered[0],
                     "admissible_by_policy": (1.0 / n) <= POLICY_CAP,
                     "reason": None})
    return rows


def run_plb_nlf(panel_dir: Path = PANEL_DIR, *, caps: Sequence[float] = (0.02, 0.05, 0.10),
                verbose: bool = True) -> dict:
    """#122 PLB + #123 NLF, printed in the order they must be read."""
    axis, rets, books = plb_load(panel_dir)
    n = len(axis)
    ti = sum(1 for d in axis if d <= PLB_SPLIT)
    census = book_census(panel_dir)
    era_i, era_date = post_kill_era(axis, census)
    live_full, _ = live_breadth(axis, rets, books)
    live_era, frozen_era = live_breadth(axis, rets, books, lo=era_i)
    live_test, frozen_test = live_breadth(axis, rets, books, lo=ti)

    if verbose:
        print(f"\n{'='*86}\n#122 PLB — Panel Live Breadth · #123 NLF — N-Leg Frontier  (advisory, [bt])")
        print(f"  panel {panel_dir}  books {len(books)}  axis {n} days {axis[0]}..{axis[-1]}"
              f"  TRAIN {ti} (<= {PLB_SPLIT})  TEST {n-ti}")
        print("\n0. CENSUS — who is still moving (`killed` + frozen equity is MEASURED zero, not absent)")
        print(f"  {'book':<20}{'rows':>6}{'killed on':>13}{'last move':>13}{'moving days':>13}")
        for b in books:
            c = census.get(b, {})
            if c.get("unmeasured"):
                print(f"  {b:<20}{'—':>6}{'НЕ ИЗМЕРЕНО':>13}  {c['unmeasured']}")
                continue
            print(f"  {b:<20}{c['rows']:>6}{str(c['killed_on'] or '—'):>13}"
                  f"{str(c['last_move'] or '—'):>13}{c['moving_days']:>13}")
        print(f"\n  full axis: live {len(live_full)}/{len(books)} — every book moved SOMETIME, so that")
        print("    count answers nothing. Liveness is a property of the slice being judged:")
        if era_date is None:
            print("  post-kill era: НЕ ИЗМЕРЕНО — no book in this panel was killed")
        else:
            print(f"  post-kill era (after the last kill {era_date}: {n-era_i}/{n} days = "
                  f"{(n-era_i)/n*100:.0f}% of the axis): live {len(live_era)}/{len(books)}, "
                  f"frozen {sorted(frozen_era)}")
        print(f"  TEST half ({n-ti} days): live {len(live_test)}/{len(books)}, frozen {sorted(frozen_test)}")

        print("\n1. CONSEQUENCE FOR THE ZERO — EW over all books is a partly UNINVESTED portfolio")
    arms = [("EW-all (registry zero)", list(books)), (f"EW-live ({len(live_era)})", sorted(live_era))]
    if frozen_era:
        arms.append((f"EW-frozen ({len(frozen_era)})", sorted(frozen_era)))
    zero: Dict[str, dict] = {}
    for label, sub in arms:
        zero[label] = {"full": subset_perf(sub, rets, 0, n),
                       "train": subset_perf(sub, rets, 0, ti),
                       "test": subset_perf(sub, rets, ti, n)}
        if verbose:
            z = zero[label]
            print(f"  {label:<26} FULL {z['full']['apy']*100:7.2f}%/{z['full']['maxdd']*100:5.2f}%"
                  f"   TRAIN {z['train']['apy']*100:7.2f}%/{z['train']['maxdd']*100:5.2f}%"
                  f"   TEST {z['test']['apy']*100:7.2f}%/{z['test']['maxdd']*100:5.2f}%")
    if verbose and frozen_era:
        print(f"  => {len(frozen_era)/len(books)*100:.0f}% of EW-all capital sits in books that cannot"
              " move. Not a tail hedge: a hole.")
        print("\n2. CONSEQUENCE FOR EVERY INVERSE-RISK SIZER — where does 1/risk send the money?")
    leak: Dict[str, float] = {}
    for kind in ("sigma", "downside"):
        w = inverse_risk_weights(rets, books, end=n, kind=kind)
        leak[kind] = sum(w[b] for b in frozen_era)
        if verbose:
            top = ", ".join(f"{b}={w[b]*100:.1f}%" for b in sorted(books, key=lambda x: -w[x])[:4])
            print(f"  1/{kind:<9} share to FROZEN books = {leak[kind]*100:5.1f}%   top: {top}")
    if verbose:
        print("  (run_idea17's inverse-vol row on this panel is therefore largely cash wearing a book's name.)")

    zero_cal, total_cal = degenerate_calmar_subsets(live_era, rets, lo=0, hi=ti)
    transfer = choice_transfer(live_era, rets, train_hi=ti, test_hi=n)
    if verbose:
        print(f"\n3. WHY CALMAR IS NOT THE SELECTION CRITERION: {zero_cal} of {total_cal} live-sleeve"
              " subsets have TRAIN maxDD == 0 exactly ⇒ Calmar = inf.")
        print(f"\n4. DOES THE CHOICE TRANSFER? over {int(transfer['n_subsets'])} live-sleeve subsets:"
              f" spearman(TRAIN APY, TEST APY) = {transfer['apy_spearman']:+.3f},"
              f" spearman(TRAIN maxDD, TEST maxDD) = {transfer['maxdd_spearman']:+.3f}")
    fronts: Dict[float, List[dict]] = {}
    for cap in caps:
        rows = nleg_frontier(live_era, rets, train_hi=ti, test_hi=n, cap=cap)
        fronts[cap] = rows
        if not verbose:
            continue
        print(f"\n5. NLF — live sleeve, max TRAIN APY s.t. |TRAIN maxDD| <= {cap*100:.0f}%"
              "  (TEST printed as it falls)")
        print(f"   {'N':>2} {'TRAIN-chosen subset':<54}{'TRapy':>8}{'TRdd':>7}{'TEapy':>8}"
              f"{'TEdd':>7}{'TESTrank':>10}  policy")
        for r in rows:
            pol = "ok" if r["admissible_by_policy"] else f">{POLICY_CAP*100:.0f}%/name"
            if r["admitted"] == 0:
                print(f"   {r['n']:>2} {'НЕ ИЗМЕРЕНО: ' + r['reason']:<54}"
                      f"{'—':>8}{'—':>7}{'—':>8}{'—':>7}{'—':>10}  {pol}")
                continue
            print(f"   {r['n']:>2} {','.join(b[:8] for b in r['subset']):<54}"
                  f"{r['train']['apy']*100:7.2f}%{r['train']['maxdd']*100:6.2f}%"
                  f"{r['test']['apy']*100:7.2f}%{r['test']['maxdd']*100:6.2f}%"
                  f"{r['test_rank']:6d}/{r['admitted']:<3}  {pol}")
    if verbose:
        print("\n  HONEST LIMITS: [bt] [L0/L1] — the books are backtests, not fills; the LEVELS are not")
        print("  promises (#91 measured gas alone at 1607 bp at the $100k pilot size). The findings are")
        print("  the live count, the corrected zero, the sizer leak and the ORDERING.")
    return {"axis_days": n, "train_days": ti, "era_start": era_date,
            "census": census, "live_era": sorted(live_era), "frozen_era": sorted(frozen_era),
            "live_test": sorted(live_test), "zero": zero, "sizer_leak": leak,
            "degenerate_calmar": {"zero_dd_subsets": zero_cal, "total": total_cal},
            "transfer": transfer, "frontier": {str(c): rows for c, rows in fronts.items()}}


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    target = "susde_dn"
    for a in argv:
        if a.startswith("--target="):
            target = a.split("=", 1)[1]
    if "--plb" in argv:
        # #122 PLB / #123 NLF — the panel's own liveness, and the frontier by number of live legs
        run_plb_nlf()
        return 0
    panel = load_panel()
    axis = common_axis(panel)
    if target not in panel:
        target = "susde_dn" if "susde_dn" in panel else sorted(panel)[0]

    # Section 0 — the size of the phase-glue artifact the old loader compounded. Printed, not
    # asserted: the correction to already-published #16/#17 numbers must be visible.
    art = glue_artifact()
    if art:
        print(f"\n{'='*74}\n0. PHASE-GLUE ARTIFACT (old phase-blind loader vs this one)")
        print(f"  {'book':<20}{'seam read as':>14}{'APY glued':>12}{'APY clean':>12}"
              f"{'maxDD glued':>14}{'maxDD clean':>14}")
        for book, row in art.items():
            print(f"  {book:<20}{row['seam_ret']*100:>13.2f}%{row['apy_glued']*100:>11.2f}%"
                  f"{row['apy_clean']*100:>11.2f}%{row['maxdd_glued']*100:>13.2f}%"
                  f"{row['maxdd_clean']*100:>13.2f}%")
        print("  → the seam is a change of accounting series (forward book re-anchors at ~$100k),"
              " not a market move.")

    run_idea16(panel, axis, target=target)
    run_idea17(panel, axis)
    print(f"\n{'='*74}\nEvidence: L0 (real feed-history backtest, NOT live). "
          f"Advisory / paper / OUTSIDE_RISKPOLICY. Survivorship + frictionless-switch caveats apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
