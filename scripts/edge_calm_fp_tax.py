#!/usr/bin/env python3
"""
scripts/edge_calm_fp_tax.py — registry idea #32: Calm-Regime False-Positive Tax (CFPT)

THE QUESTION THE REGISTRY KEPT DEFERRING
  Ideas #1, #9, #14, #15, #23, #25, #26, #27, #28 all build a DE-RISK signal and all report
  their headline numbers on the SYNTHETIC stress fixture. Every one of those entries carries
  the same honest caveat, in the same words:

      "fixture σ² ≈ 0 in calm → zero false positives (fixture artifact); in real markets it
       would be different — slope_thresh / δ / vol_mult needs calibration to real σ_noise."

  Nobody ever measured that difference. A de-risk signal has two costs, and the fixture can
  only show one of them:
      TRUE  POSITIVE  — de-risked before a real loss   → loss avoided (the fixture measures it)
      FALSE POSITIVE  — de-risked in calm, nothing came → CARRY FORGONE (the fixture cannot
                        produce it at all, because calm days have no variance to trigger on)
  So the whole registry leaderboard (KODS #15 Calmar 4.55, ALK/CSD 4.58, NRK-AH 5.91) is a
  ranking of TP-side benefit with the FP-side cost structurally set to zero.

  #32 measures the missing half on the REAL 10-book panel, where calm days DO have variance:
      data/aggressive_lab/<book>/realized_series.jsonl   (853 real days, 2024-03 .. 2026-07)
  and reports, per signal family, the number the registry has never had:
      the CALM-REGIME FALSE-POSITIVE TAX, in bp/yr of forgone carry.

DATA-INTEGRITY FINDING THAT COMES FIRST (see load_clean_panel)
  These files GLUE TWO DIFFERENT ACCOUNTING SERIES together: 853 rows of phase="backtest"
  (equity compounding from $100k up to e.g. $147k for susde_dn) plus ONE row of
  phase="forward" — the live forward paper book, which starts over at ~$100k. A loader that
  diffs equity_usd without looking at `phase` (which is what scripts/edge_real_panel_ensemble.py
  does, and therefore what registry ideas #16/#17 were computed on) reads that re-anchor as a
  real one-day return of −31% (susde_dn), −84% (pendle_yt_susde) or +105% (eth_directional).
  It is not a market event; it is a change of accounting series. This loader is fail-CLOSED
  against it: rows are kept only from the single contiguous phase="backtest" block, and any
  residual same-block jump beyond JUMP_REFUSE is refused rather than silently compounded.
  The size of that artifact is printed in the report (section 0) because it materially moves
  numbers already published in the registry — it is NOT silently corrected here.

WHAT IS MEASURED (all signals strictly causal — state through t-1 only)
  Families, each a faithful re-implementation of the registry entry it names:
    dd(θ)          #9  DDO           — de-risk while trailing drawdown ≤ −θ
    vol(m,lkb)     #1  pre-emptive   — de-risk while trailing vol > m × causal expanding median vol
    kods(lkb)      #15 KODS          — de-risk while annualised trailing mean return < r_f
    ecdr(f,s)      #23 ECDR          — de-risk while EMA_f(equity) < SMA_s(equity)
    csd(lkb,sl)    #28 CSD           — de-risk while slope(μ_rolling) < −sl AND μ < r_f × buffer
  For every (book, family, params):
    duty            share of days de-risked
    TP / FP         a de-risk day is a TRUE positive iff the book's RAW forward-H cumulative
                    return from that day is < 0 (something was in fact coming), else FALSE
    precision       TP / (TP + FP)
    tax_bp_yr       carry forgone on FP days, annualised, in bp/yr   ← the missing number
    calm_tax_bp_yr  the same but restricted to CALM days (trailing DD > −CALM_DD), i.e. the
                    part of the tax the fixture sets to zero by construction
    avoided_bp_yr   loss avoided on TP days, annualised, in bp/yr
    net_bp_yr       avoided − tax  (>0 ⇒ the signal paid for itself on this book)
    Calmar/APY/maxDD of the overlaid book vs raw, in-sample and OOS (train ≤ TRAIN_END).

HONEST LIMITS (mirrored into the registry entry)
  (a) SURVIVORSHIP: 10 surviving books; delisted-after-blowup books are absent.
  (b) The panel is a realized backtest over real feed history, not a live forward track.
  (c) De-risk to cash is frictionless here; idea #10 put the causal-overlay break-even at
      ~96 bp per switch — a signal whose net_bp_yr is smaller than 96 bp × switches/yr is
      NEGATIVE in reality even when it looks positive here.
  (d) TP/FP is defined by a forward-H window; H is a choice, so precision is H-conditional.
      Both H=5 and H=10 are reported for exactly that reason.
  (e) Evidence level L0 (backtest on real feed history). NOT live results. IS_ADVISORY.

Read-only. Touches no state: does not write data/, does not import spa_core.execution, does
not touch the live paper track, RiskPolicy v1.0, the site or any agent. stdlib-only,
deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
PANEL_DIR = ROOT / "data" / "aggressive_lab"

TRAIN_END = "2025-06-30"     # OOS split: params inspected on ≤ this date, checked after it
RF_ANNUAL = 0.046            # risk-free hurdle used by KODS #15 / CSD #28
CALM_DD = 0.02               # a day is CALM while trailing drawdown > −2%
JUMP_REFUSE = 0.50           # same-phase one-day move beyond this ⇒ refuse the book (fail-CLOSED)
BP = 10_000.0


# ─────────────────────── clean panel loader (fail-CLOSED on phase glue) ───────────────────────
def read_rows(path: Path) -> List[dict]:
    out: List[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def backtest_block(rows: Sequence[dict]) -> List[dict]:
    """Keep only the phase=="backtest" rows, in date order.

    The forward row is a DIFFERENT accounting series (the live paper book, re-anchored at
    ~$100k) appended to the same file. Diffing across that boundary fabricates a huge
    one-day return, so the boundary is cut, never crossed.
    """
    keep = [r for r in rows if r.get("phase") == "backtest"]
    keep.sort(key=lambda r: r.get("date") or r.get("as_of") or "")
    return keep


def _returns(rows: Sequence[dict], book: str) -> Tuple[List[str], List[float]]:
    dates: List[str] = []
    eq: List[float] = []
    for row in rows:
        d = row.get("date") or row.get("as_of")
        e = row.get("equity_usd")
        if d is None or e is None or float(e) <= 0:
            continue
        dates.append(str(d))
        eq.append(float(e))
    rets: List[float] = []
    for i in range(1, len(eq)):
        ret = eq[i] / eq[i - 1] - 1.0
        if abs(ret) > JUMP_REFUSE:
            raise ValueError(
                f"{book}: {abs(ret) * 100:.1f}% one-day move at {dates[i]} inside a single "
                f"phase block — refusing to treat an accounting discontinuity as a return"
            )
        rets.append(ret)
    return dates[1:], rets


def load_clean_panel(panel_dir: Path = PANEL_DIR) -> Dict[str, Dict[str, float]]:
    """{book: {date: daily_return}} over the phase=="backtest" block only.

    Fail-CLOSED: a book with < 60 usable points is dropped; a book with an unexplained
    same-block jump raises. Never fabricates a point.
    """
    panel: Dict[str, Dict[str, float]] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        book = sub.parent.name
        rows = backtest_block(read_rows(sub))
        if len(rows) < 61:
            continue
        dates, rets = _returns(rows, book)
        panel[book] = {dates[i]: rets[i] for i in range(len(dates))}
    if not panel:
        raise RuntimeError(f"no usable books in {panel_dir} — refusing to fabricate a panel")
    return panel


def load_glued_panel(panel_dir: Path = PANEL_DIR) -> Dict[str, Dict[str, float]]:
    """The naive loader (every row, phase ignored) — kept ONLY to quantify the artifact."""
    panel: Dict[str, Dict[str, float]] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        book = sub.parent.name
        rows = read_rows(sub)
        rows.sort(key=lambda r: r.get("date") or r.get("as_of") or "")
        eq = {str(r.get("date") or r.get("as_of")): float(r["equity_usd"])
              for r in rows if r.get("equity_usd") and float(r["equity_usd"]) > 0}
        ds = sorted(eq)
        if len(ds) < 61:
            continue
        panel[book] = {ds[i]: eq[ds[i]] / eq[ds[i - 1]] - 1.0 for i in range(1, len(ds))}
    return panel


def common_axis(panel: Dict[str, Dict[str, float]]) -> List[str]:
    sets = [set(r) for r in panel.values()]
    return sorted(set.intersection(*sets)) if sets else []


# ─────────────────────────────────── metrics ───────────────────────────────────
def equity_path(returns: Sequence[float]) -> List[float]:
    eq = [1.0]
    for r in returns:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def max_drawdown(eq: Sequence[float]) -> float:
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def perf(returns: Sequence[float]) -> Dict[str, float]:
    n = len(returns)
    if n == 0:
        return {"apy": 0.0, "maxdd": 0.0, "calmar": 0.0}
    eq = equity_path(returns)
    apy = eq[-1] ** (365.0 / n) - 1.0 if eq[-1] > 0 else -1.0
    mdd = max_drawdown(eq)
    return {"apy": apy, "maxdd": mdd, "calmar": (apy / abs(mdd) if mdd < 0 else float("inf"))}


# ─────────────────────── causal state (everything is THROUGH t-1) ───────────────────────
def trailing_drawdown(returns: Sequence[float]) -> List[float]:
    """dd[i] = drawdown of the equity built from returns[:i]. Causal: excludes day i."""
    out: List[float] = []
    eq, peak = 1.0, 1.0
    for i in range(len(returns)):
        out.append(eq / peak - 1.0 if peak > 0 else 0.0)
        eq *= 1.0 + returns[i]
        peak = max(peak, eq)
    return out


def trailing_vol(returns: Sequence[float], lookback: int) -> List[float]:
    out: List[float] = []
    for i in range(len(returns)):
        w = returns[max(0, i - lookback):i]
        if len(w) < 2:
            out.append(0.0)
            continue
        m = sum(w) / len(w)
        out.append(math.sqrt(sum((x - m) ** 2 for x in w) / (len(w) - 1)))
    return out


def trailing_mean(returns: Sequence[float], lookback: int) -> List[float]:
    out: List[float] = []
    for i in range(len(returns)):
        w = returns[max(0, i - lookback):i]
        out.append(sum(w) / len(w) if w else 0.0)
    return out


def expanding_median(values: Sequence[float], warmup: int) -> List[float]:
    """med[i] = median of values[:i] (causal). 0.0 until `warmup` points exist."""
    out: List[float] = []
    seen: List[float] = []
    for i, v in enumerate(values):
        if i < warmup:
            out.append(0.0)
        else:
            s = sorted(seen)
            n = len(s)
            out.append(s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2]))
        seen.append(v)
    return out


def ema(values: Sequence[float], span: int) -> List[float]:
    a = 2.0 / (span + 1.0)
    out: List[float] = []
    cur: Optional[float] = None
    for v in values:
        cur = v if cur is None else a * v + (1 - a) * cur
        out.append(cur)
    return out


def sma(values: Sequence[float], window: int) -> List[float]:
    out: List[float] = []
    for i in range(len(values)):
        w = values[max(0, i - window + 1):i + 1]
        out.append(sum(w) / len(w))
    return out


# ─────────────────────────────── signal families ───────────────────────────────
# Each returns derisk[i] ∈ {True, False}, decided from information available BEFORE day i.
def sig_dd(returns: Sequence[float], theta: float) -> List[bool]:
    dd = trailing_drawdown(returns)
    return [d <= -theta for d in dd]


def sig_vol(returns: Sequence[float], mult: float, lookback: int = 10) -> List[bool]:
    vol = trailing_vol(returns, lookback)
    base = expanding_median(vol, warmup=max(30, lookback * 2))
    return [base[i] > 0 and vol[i] > mult * base[i] for i in range(len(returns))]


def sig_kods(returns: Sequence[float], lookback: int) -> List[bool]:
    mu = trailing_mean(returns, lookback)
    thr = RF_ANNUAL / 365.0
    return [(i >= lookback) and (mu[i] < thr) for i in range(len(returns))]


def sig_ecdr(returns: Sequence[float], fast: int, slow: int) -> List[bool]:
    """EMA_fast(equity) < SMA_slow(equity), both built from equity THROUGH t-1."""
    eq = equity_path(returns)          # eq[i] = wealth after returns[:i] ⇒ eq[i] is causal for day i
    causal = eq[:len(returns)]
    ef, ss = ema(causal, fast), sma(causal, slow)
    return [(i >= slow) and (ef[i] < ss[i]) for i in range(len(returns))]


def sig_csd(returns: Sequence[float], lookback: int, slope_thr: float,
            buffer: float = 1.2) -> List[bool]:
    """#28: slope of μ_rolling negative beyond a threshold AND μ below r_f × buffer."""
    mu = trailing_mean(returns, lookback)
    thr = RF_ANNUAL * buffer / 365.0
    out = [False] * len(returns)
    for i in range(len(returns)):
        if i < lookback + 1:
            continue
        slope = mu[i] - mu[i - 1]
        out[i] = (slope < -slope_thr) and (mu[i] < thr)
    return out


def kelly_weights(returns: Sequence[float], lookback: int, alpha: float,
                  w_max: float = 1.0) -> List[float]:
    """#15 KODS in its ACTUAL form: continuous fractional Kelly, not a binary gate.

        f*(t) = α · (μ_rolling(t) − r_f) / σ²_rolling(t),  clipped to [0, w_max]

    with μ and σ² causal (through t-1). #15's own honest caveat (a) says the fixture makes
    this degenerate — "σ² ≈ 0 in calm → f → ∞ → always capped; alpha does not matter at all;
    in real markets with non-zero calm σ² alpha WOULD give continuous control". This is that
    test: on the real panel σ² in calm is strictly positive, so f is a real number and α is
    a real knob. Exposure 1.0 = the raw book (the baseline), so w < 1 is de-risking.
    """
    mu = trailing_mean(returns, lookback)
    vol = trailing_vol(returns, lookback)
    rf_d = RF_ANNUAL / 365.0
    out: List[float] = []
    for i in range(len(returns)):
        var = vol[i] ** 2
        if i < lookback or var <= 0.0:
            # fail-CLOSED on an unmeasurable variance: hold the baseline, never lever up
            out.append(w_max)
            continue
        f = alpha * (mu[i] - rf_d) / var
        out.append(min(w_max, max(0.0, f)))
    return out


# A signal is a weight path in [0, 1]: 1.0 = full exposure to the book, 0.0 = cash.
# Binary families are the special case {0.0, 1.0}.
SignalSpec = Tuple[str, Callable[[Sequence[float]], List[float]]]


def _binary(flags: Sequence[bool]) -> List[float]:
    return [0.0 if f else 1.0 for f in flags]


def _mk_dd(theta: float) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return _binary(sig_dd(r, theta))
    return f


def _mk_vol(mult: float) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return _binary(sig_vol(r, mult))
    return f


def _mk_kods(lookback: int) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return _binary(sig_kods(r, lookback))
    return f


def _mk_kelly(alpha: float) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return kelly_weights(r, 10, alpha)
    return f


def _mk_ecdr(fast: int, slow: int) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return _binary(sig_ecdr(r, fast, slow))
    return f


def _mk_csd(slope_thr: float) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return _binary(sig_csd(r, 10, slope_thr))
    return f


def signal_catalog() -> List[SignalSpec]:
    """The registry's de-risk families with the parameters their entries actually used."""
    specs: List[SignalSpec] = []
    for th in (0.02, 0.05, 0.10):
        specs.append((f"dd#9(θ={th:.0%})", _mk_dd(th)))
    for m in (1.5, 2.0, 3.0):
        specs.append((f"vol#1(m={m})", _mk_vol(m)))
    for lb in (5, 10, 20):
        specs.append((f"kods#15-gate(lkb={lb})", _mk_kods(lb)))
    for a in (0.1, 1.0):
        specs.append((f"kelly#15-frac(α={a})", _mk_kelly(a)))
    for f_, s_ in ((5, 20), (10, 30)):
        specs.append((f"ecdr#23({f_}/{s_})", _mk_ecdr(f_, s_)))
    for sl in (0.0001, 0.0005):
        specs.append((f"csd#28(sl={sl})", _mk_csd(sl)))
    return specs


# ─────────────────────────── FP / TP accounting ───────────────────────────
def forward_return(returns: Sequence[float], i: int, horizon: int) -> Optional[float]:
    """Cumulative RAW return over days [i, i+horizon). None if the window runs off the end."""
    if i + horizon > len(returns):
        return None
    acc = 1.0
    for k in range(i, i + horizon):
        acc *= 1.0 + returns[k]
    return acc - 1.0


DERISK_EPS = 0.01   # a day counts as "de-risked" once exposure is ≥1pp below the baseline


def evaluate(returns: Sequence[float], weights: Sequence[float], horizon: int) -> Dict[str, float]:
    """Split de-risked days into TP/FP by the RAW forward-H outcome and price both sides.

    A de-risked day is a TRUE positive iff the raw forward-H cumulative return is < 0 (loss
    was in fact coming, so cutting exposure helped). Otherwise it is a FALSE positive and the
    exposure that was cut is carry handed back.

    Continuous weights are handled by pricing the CUT fraction (1 − w) on each day, so a
    fractional-Kelly path and a binary gate are measured on the same scale.

    tax / avoided are arithmetic sums of daily returns, annualised as sum/n × 365 — an
    approximation that is exact to first order and is the same convention on both sides, so
    net_bp_yr is a like-for-like comparison. Overlay APY/maxDD/Calmar (compounded) are
    reported alongside so the arithmetic figure can never be the only evidence.
    """
    n = len(returns)
    dd = trailing_drawdown(returns)
    tp = fp = 0
    tax = avoided = calm_tax = 0.0
    calm_fp = calm_days = 0
    switches = 0
    prev = False
    for i in range(n):
        if dd[i] > -CALM_DD:
            calm_days += 1
        cut = 1.0 - weights[i]
        active = cut >= DERISK_EPS
        if active:
            if not prev:
                switches += 1
            fwd = forward_return(returns, i, horizon)
            if fwd is not None and fwd < 0:
                tp += 1
                avoided += -returns[i] * cut
            else:
                fp += 1
                tax += returns[i] * cut
                if dd[i] > -CALM_DD:
                    calm_fp += 1
                    calm_tax += returns[i] * cut
        prev = active
    ann = 365.0 / n if n else 0.0
    duty = sum(1 for i in range(n) if (1.0 - weights[i]) >= DERISK_EPS) / n if n else 0.0
    overlay = perf([weights[i] * returns[i] for i in range(n)])
    raw = perf(returns)
    return {
        "duty": duty,
        "mean_w": (sum(weights) / n) if n else 1.0,
        "tp": float(tp),
        "fp": float(fp),
        "precision": (tp / (tp + fp)) if (tp + fp) else float("nan"),
        "tax_bp_yr": tax * ann * BP,
        "calm_tax_bp_yr": calm_tax * ann * BP,
        "calm_fp_rate": (calm_fp / calm_days) if calm_days else 0.0,
        "avoided_bp_yr": avoided * ann * BP,
        "net_bp_yr": (avoided - tax) * ann * BP,
        "switches_yr": switches * ann,
        "raw_calmar": raw["calmar"],
        "ov_calmar": overlay["calmar"],
        "d_calmar": overlay["calmar"] - raw["calmar"],
        "raw_apy": raw["apy"],
        "ov_apy": overlay["apy"],
        "raw_maxdd": raw["maxdd"],
        "ov_maxdd": overlay["maxdd"],
    }


# ─────────────────────────────────── report ───────────────────────────────────
def _median(xs: Sequence[float]) -> float:
    s = sorted(x for x in xs if not math.isnan(x))
    if not s:
        return float("nan")
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def section_zero_artifact() -> None:
    print("=" * 100)
    print("0. DATA-INTEGRITY: what the phase glue does to the panel (finding, not a fix)")
    print("=" * 100)
    glued, clean = load_glued_panel(), load_clean_panel()
    print(f"{'book':20s} {'glued APY':>10s} {'glued DD':>9s} | {'clean APY':>10s} {'clean DD':>9s}"
          f" | {'ΔAPY(pp)':>9s} {'ΔDD(pp)':>8s}")
    for book in sorted(clean):
        g = perf([glued[book][d] for d in sorted(glued[book])])
        c = perf([clean[book][d] for d in sorted(clean[book])])
        print(f"{book:20s} {g['apy']*100:9.2f}% {g['maxdd']*100:8.2f}% |"
              f" {c['apy']*100:9.2f}% {c['maxdd']*100:8.2f}% |"
              f" {(c['apy']-g['apy'])*100:8.1f} {(c['maxdd']-g['maxdd'])*100:7.1f}")
    print("\nThe glued column is what a phase-blind equity diff sees — one appended forward row")
    print("re-anchored at ~$100k. Registry ideas #16/#17 were computed with a phase-blind loader.")


def run(horizon: int = 5, start: Optional[str] = None, end: Optional[str] = None,
        label: str = "FULL") -> Dict[str, List[Dict[str, float]]]:
    panel = load_clean_panel()
    axis = common_axis(panel)
    axis = [d for d in axis if (start is None or d >= start) and (end is None or d <= end)]
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}

    print()
    print("=" * 100)
    print(f"{label}: calm-regime false-positive tax, horizon H={horizon}d, "
          f"{len(axis)} days {axis[0]}..{axis[-1]}, {len(books)} books")
    print("=" * 100)
    print(f"{'signal':20s} {'duty':>6s} {'prec':>6s} {'calmFP':>7s} {'tax':>9s} {'calmTax':>9s}"
          f" {'avoided':>9s} {'net':>9s} {'sw/yr':>6s} {'ΔCalmar':>9s} {'books+':>7s}")
    print(f"{'':20s} {'':>6s} {'':>6s} {'':>7s} {'bp/yr':>9s} {'bp/yr':>9s} {'bp/yr':>9s}"
          f" {'bp/yr':>9s} {'':>6s} {'median':>9s} {'net>0':>7s}")
    out: Dict[str, List[Dict[str, float]]] = {}
    for name, fn in signal_catalog():
        per_book = [evaluate(rets[b], fn(rets[b]), horizon) for b in books]
        out[name] = per_book
        pos = sum(1 for m in per_book if m["net_bp_yr"] > 0)
        print(f"{name:20s} {_median([m['duty'] for m in per_book])*100:5.1f}%"
              f" {_median([m['precision'] for m in per_book])*100:5.1f}%"
              f" {_median([m['calm_fp_rate'] for m in per_book])*100:6.1f}%"
              f" {_median([m['tax_bp_yr'] for m in per_book]):9.0f}"
              f" {_median([m['calm_tax_bp_yr'] for m in per_book]):9.0f}"
              f" {_median([m['avoided_bp_yr'] for m in per_book]):9.0f}"
              f" {_median([m['net_bp_yr'] for m in per_book]):9.0f}"
              f" {_median([m['switches_yr'] for m in per_book]):6.1f}"
              f" {_median([m['d_calmar'] for m in per_book]):9.2f}"
              f" {pos:4d}/{len(books):2d}")
    return out


def per_book_detail(horizon: int = 5) -> None:
    panel = load_clean_panel()
    axis = common_axis(panel)
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    print()
    print("=" * 100)
    print(f"PER-BOOK detail for the two registry leaders (H={horizon}d, full sample)")
    print("=" * 100)
    for name, fn in [("kods#15-gate(lkb=10)", lambda r: _binary(sig_kods(r, 10))),
                     ("kelly#15-frac(α=1.0)", lambda r: kelly_weights(r, 10, 1.0)),
                     ("vol#1(m=2.0)", lambda r: _binary(sig_vol(r, 2.0)))]:
        print(f"\n-- {name}")
        print(f"{'book':20s} {'rawAPY':>8s} {'ovAPY':>8s} {'rawDD':>8s} {'ovDD':>8s}"
              f" {'duty':>6s} {'prec':>6s} {'tax':>8s} {'avoid':>8s} {'net':>9s}")
        for b in books:
            m = evaluate(rets[b], fn(rets[b]), horizon)
            print(f"{b:20s} {m['raw_apy']*100:7.1f}% {m['ov_apy']*100:7.1f}%"
                  f" {m['raw_maxdd']*100:7.1f}% {m['ov_maxdd']*100:7.1f}%"
                  f" {m['duty']*100:5.1f}% {m['precision']*100:5.1f}%"
                  f" {m['tax_bp_yr']:8.0f} {m['avoided_bp_yr']:8.0f} {m['net_bp_yr']:9.0f}")


NOISY_VOL_FLOOR = 0.10   # ann. vol above which a book carries real mark-to-market noise


def panel_character() -> List[str]:
    """Print what kind of series each book actually is, and return the NOISY subset.

    This matters for the whole verdict. Several books in this panel are ACCRUAL paths —
    carry booked day by day with almost no mark-to-market noise (susde_dn: 0.9% annualised
    vol against 17.9% APY, i.e. Sharpe ~20, which no traded book achieves). On such a series
    a variance-triggered overlay can hardly fire, so measuring the false-positive tax there
    UNDERSTATES it. The books with real price noise are the honest test-bed, so every
    headline is repeated on that subset alone.
    """
    panel = load_clean_panel()
    axis = common_axis(panel)
    books = sorted(panel)
    print()
    print("=" * 100)
    print("PANEL CHARACTER: which books carry real market noise (and which are accrual paths)")
    print("=" * 100)
    print(f"{'book':20s} {'APY':>9s} {'annVol':>8s} {'Sharpe':>7s} {'lag1 AC':>8s} {'maxDD':>8s} {'class':>8s}")
    noisy: List[str] = []
    for b in books:
        r = [panel[b][d] for d in axis]
        p = perf(r)
        n = len(r)
        m = sum(r) / n
        var = sum((x - m) ** 2 for x in r) / (n - 1)
        vol = math.sqrt(var) * math.sqrt(365)
        sharpe = (m * 365 / vol) if vol > 0 else float("nan")
        num = sum((r[i] - m) * (r[i - 1] - m) for i in range(1, n))
        den = sum((x - m) ** 2 for x in r)
        ac = (num / den) if den > 0 else float("nan")
        cls = "NOISY" if vol >= NOISY_VOL_FLOOR else "accrual"
        if cls == "NOISY":
            noisy.append(b)
        print(f"{b:20s} {p['apy']*100:8.2f}% {vol*100:7.2f}% {sharpe:7.2f} {ac:8.2f}"
              f" {p['maxdd']*100:7.2f}% {cls:>8s}")
    print(f"\nNOISY subset ({len(noisy)}/{len(books)}): {', '.join(noisy)}")
    return noisy


def portfolio_view(horizon: int = 5, subset: Optional[Sequence[str]] = None,
                   label: str = "all 10 real books", cash_daily: float = 0.0) -> None:
    """The registry's entries are portfolio-level claims, so state the portfolio answer too.

    Each signal is applied PER BOOK (each book de-risks on its own state), then the ten
    overlaid books are combined equal-weight and rebalanced daily — the same combination
    rule for every signal and for the raw baseline, so the comparison isolates the overlay.
    """
    panel = load_clean_panel()
    axis = common_axis(panel)
    books = sorted(panel) if subset is None else sorted(subset)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    n = len(axis)
    raw_pf = [sum(rets[b][i] for b in books) / len(books) for i in range(n)]
    base = perf(raw_pf)
    cash_note = ("0% cash (conservative, the registry's own convention)" if cash_daily == 0.0
                 else f"cash earns r_f = {cash_daily * 365 * 100:.1f}%/yr")
    print()
    print("=" * 100)
    print(f"EQUAL-WEIGHT PORTFOLIO — {label}, per-book overlays (H={horizon}d), {cash_note}")
    print("=" * 100)
    print(f"{'signal':22s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔAPY(pp)':>9s}"
          f" {'ΔDD(pp)':>8s} {'ΔCalmar':>8s} {'mean w':>7s}")
    print(f"{'raw (no overlay)':22s} {base['apy']*100:7.2f}% {base['maxdd']*100:7.2f}%"
          f" {base['calmar']:8.2f} {'—':>9s} {'—':>8s} {'—':>8s} {1.0:7.2f}")
    for name, fn in signal_catalog():
        w = {b: fn(rets[b]) for b in books}
        pf = [sum(w[b][i] * rets[b][i] + (1.0 - w[b][i]) * cash_daily for b in books) / len(books)
              for i in range(n)]
        p = perf(pf)
        mw = sum(sum(w[b]) for b in books) / (len(books) * n)
        print(f"{name:22s} {p['apy']*100:7.2f}% {p['maxdd']*100:7.2f}% {p['calmar']:8.2f}"
              f" {(p['apy']-base['apy'])*100:8.2f} {(p['maxdd']-base['maxdd'])*100:7.2f}"
              f" {p['calmar']-base['calmar']:8.2f} {mw:7.2f}")


def mechanism(subset: Optional[Sequence[str]] = None, label: str = "all 10 books") -> None:
    """WHY the overlays lose: reactivity tax + rebound forfeit.

    Two diagnostics, both computed on the same portfolio construction as portfolio_view:
      • reactivity — switches/yr against ΔCalmar across every configuration, with the
        Pearson correlation. If de-risking were an edge, more reactivity would not be
        monotonically worse.
      • rebound forfeit — the mean RAW daily return of the days the signal sits de-risked,
        split into days inside a drawdown (where cash is supposed to help) and calm days.
        A positive mean on drawdown days means the overlay is selling the recovery leg:
        it cuts exposure after the loss has landed and is still out while the book climbs
        back, which lengthens the drawdown instead of shortening it.
    """
    panel = load_clean_panel()
    axis = common_axis(panel)
    books = sorted(panel) if subset is None else sorted(subset)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    n = len(axis)
    base = perf([sum(rets[b][i] for b in books) / len(books) for i in range(n)])
    print()
    print("=" * 100)
    print(f"MECHANISM — {label}: reactivity tax and rebound forfeit")
    print("=" * 100)
    print(f"{'signal':22s} {'sw/yr':>7s} {'ΔCalmar':>8s} | {'mean raw ret on de-risked days':>34s}")
    print(f"{'':22s} {'':>7s} {'':>8s} | {'in drawdown':>14s} {'in calm':>10s} {'all days':>9s}")
    xs: List[float] = []
    ys: List[float] = []
    for name, fn in signal_catalog():
        w = {b: fn(rets[b]) for b in books}
        pf = [sum(w[b][i] * rets[b][i] for b in books) / len(books) for i in range(n)]
        d_cal = perf(pf)["calmar"] - base["calmar"]
        sw = 0
        in_dd: List[float] = []
        in_calm: List[float] = []
        allr: List[float] = []
        for b in books:
            dd = trailing_drawdown(rets[b])
            prev = False
            for i in range(n):
                act = (1.0 - w[b][i]) >= DERISK_EPS
                if act and not prev:
                    sw += 1
                if act:
                    allr.append(rets[b][i])
                    (in_calm if dd[i] > -CALM_DD else in_dd).append(rets[b][i])
                prev = act
        sw_yr = sw / len(books) * 365.0 / n
        mean = lambda v: (sum(v) / len(v) * BP) if v else float("nan")   # noqa: E731 (bp/day)
        xs.append(sw_yr)
        ys.append(d_cal)
        print(f"{name:22s} {sw_yr:7.1f} {d_cal:8.2f} | {mean(in_dd):13.1f}bp"
              f" {mean(in_calm):9.1f}bp {mean(allr):8.1f}bp")
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs)))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    corr = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else float("nan")
    print(f"\ncorr(switches/yr, ΔCalmar) = {corr:+.2f} over {len(xs)} configurations"
          "  — negative ⇒ the more reactive the signal, the more value it destroys")
    print("mean raw return on de-risked days is in bp/DAY; positive ⇒ exposure was cut into")
    print("days that paid, i.e. carry handed back (calm) or recovery forfeited (drawdown).")


def sig_rgvd(returns: Sequence[float], mult: float, lookback: int = 10) -> List[bool]:
    """Idea #33 — Regime-Gated Volatility De-Risk (RGVD), derived from #32's mechanism table.

    #32 measured that a vol trigger is TWO different signals wearing one name:
      • fired in CALM   → the days it skips are strongly negative (informative);
      • fired in DRAWDOWN → the days it skips are strongly POSITIVE (anti-informative — it
        is selling the recovery leg, which is why every reactive overlay deepened maxDD).
    RGVD keeps the first half and deletes the second: de-risk on a vol spike ONLY while the
    book is still in calm; once a drawdown is under way, stay fully invested and let the
    rebound run. Strictly causal — both the vol and the drawdown state are through t-1.
    """
    vol = trailing_vol(returns, lookback)
    base = expanding_median(vol, warmup=max(30, lookback * 2))
    dd = trailing_drawdown(returns)
    return [base[i] > 0 and vol[i] > mult * base[i] and dd[i] > -CALM_DD
            for i in range(len(returns))]


def sig_rgvd_inverse(returns: Sequence[float], mult: float, lookback: int = 10) -> List[bool]:
    """Control for #33: the SAME vol trigger restricted to the drawdown half instead.

    If #32's mechanism reading is right this must be clearly worse than both plain vol#1
    and RGVD — it isolates exactly the anti-informative half.
    """
    vol = trailing_vol(returns, lookback)
    base = expanding_median(vol, warmup=max(30, lookback * 2))
    dd = trailing_drawdown(returns)
    return [base[i] > 0 and vol[i] > mult * base[i] and dd[i] <= -CALM_DD
            for i in range(len(returns))]


def _mk_rgvd(mult: float) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return _binary(sig_rgvd(r, mult))
    return f


def _mk_rgvd_inverse(mult: float) -> Callable[[Sequence[float]], List[float]]:
    def f(r: Sequence[float]) -> List[float]:
        return _binary(sig_rgvd_inverse(r, mult))
    return f


def idea33_rgvd() -> None:
    """Test #33 under an honest protocol: the mechanism is re-derived on TRAIN only, the
    candidate is then scored on the unseen TEST segment."""
    panel = load_clean_panel()
    axis_all = common_axis(panel)
    noisy = [b for b in sorted(panel)
             if _ann_vol([panel[b][d] for d in axis_all]) >= NOISY_VOL_FLOOR]
    segments = [
        ("TRAIN (≤ 2025-06-30)", [d for d in axis_all if d <= TRAIN_END]),
        ("TEST  (> 2025-06-30)", [d for d in axis_all if d > TRAIN_END]),
    ]
    print()
    print("=" * 100)
    print("IDEA #33 — Regime-Gated Volatility De-Risk (RGVD), NOISY subset, equal-weight")
    print("=" * 100)
    for seg_name, axis in segments:
        n = len(axis)
        rets = {b: [panel[b][d] for d in axis] for b in noisy}
        base = perf([sum(rets[b][i] for b in noisy) / len(noisy) for i in range(n)])
        print(f"\n-- {seg_name}: {n} days {axis[0]}..{axis[-1]}")
        print(f"{'variant':28s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s} {'ΔAPY(pp)':>9s}"
              f" {'ΔDD(pp)':>8s} {'ΔCalmar':>8s} {'duty':>6s}")
        print(f"{'raw (no overlay)':28s} {base['apy']*100:7.2f}% {base['maxdd']*100:7.2f}%"
              f" {base['calmar']:8.2f} {'—':>9s} {'—':>8s} {'—':>8s} {'—':>6s}")
        variants: List[Tuple[str, Callable[[Sequence[float]], List[float]]]] = []
        for m in (1.5, 2.0, 3.0):
            variants.append((f"vol#1(m={m}) [baseline]", _mk_vol(m)))
            variants.append((f"RGVD#33(m={m}) calm-only", _mk_rgvd(m)))
            variants.append((f"  control: dd-only(m={m})", _mk_rgvd_inverse(m)))
        for name, fn in variants:
            w = {b: fn(rets[b]) for b in noisy}
            pf = [sum(w[b][i] * rets[b][i] for b in noisy) / len(noisy) for i in range(n)]
            p = perf(pf)
            duty = sum(sum(1 for x in w[b] if x < 1.0) for b in noisy) / (len(noisy) * n)
            print(f"{name:28s} {p['apy']*100:7.2f}% {p['maxdd']*100:7.2f}% {p['calmar']:8.2f}"
                  f" {(p['apy']-base['apy'])*100:8.2f} {(p['maxdd']-base['maxdd'])*100:7.2f}"
                  f" {p['calmar']-base['calmar']:8.2f} {duty*100:5.1f}%")
    print("\nProtocol note: #33 was GENERATED from #32's mechanism table on the full sample, so")
    print("TEST is a partial hold-out, not a virgin sample. It is reported as such.")


def _ann_vol(returns: Sequence[float]) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    m = sum(returns) / n
    return math.sqrt(sum((x - m) ** 2 for x in returns) / (n - 1)) * math.sqrt(365)


def cost_breakeven(horizon: int = 5, cost_bp_per_switch: float = 96.0) -> None:
    """Idea #10 put the causal-overlay break-even at ~96 bp per switch. Apply it."""
    panel = load_clean_panel()
    axis = common_axis(panel)
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    print()
    print("=" * 100)
    print(f"TURNOVER-COST OVERLAY (#10: ~{cost_bp_per_switch:.0f} bp per switch), H={horizon}d")
    print("=" * 100)
    print(f"{'signal':20s} {'median net':>11s} {'median cost':>12s} {'net after cost':>15s}"
          f" {'books net>0':>12s}")
    for name, fn in signal_catalog():
        nets, costs, after = [], [], []
        for b in books:
            m = evaluate(rets[b], fn(rets[b]), horizon)
            c = m["switches_yr"] * cost_bp_per_switch
            nets.append(m["net_bp_yr"])
            costs.append(c)
            after.append(m["net_bp_yr"] - c)
        pos = sum(1 for x in after if x > 0)
        print(f"{name:20s} {_median(nets):10.0f}  {_median(costs):11.0f}  {_median(after):14.0f}"
              f" {pos:9d}/{len(books):2d}")


def main(argv: Sequence[str]) -> int:
    section_zero_artifact()
    for h in (5, 10):
        run(horizon=h, label=f"FULL SAMPLE (H={h})")
    run(horizon=5, end=TRAIN_END, label="IN-SAMPLE (≤ 2025-06-30)")
    run(horizon=5, start=TRAIN_END, label="OUT-OF-SAMPLE (> 2025-06-30)")
    noisy = panel_character()
    portfolio_view(horizon=5)
    portfolio_view(horizon=5, subset=noisy, label=f"NOISY subset only ({len(noisy)} books)")
    portfolio_view(horizon=5, subset=noisy, label=f"NOISY subset only ({len(noisy)} books)",
                   cash_daily=RF_ANNUAL / 365.0)
    mechanism(subset=noisy, label=f"NOISY subset ({len(noisy)} books)")
    idea33_rgvd()
    per_book_detail(horizon=5)
    cost_breakeven(horizon=5)
    print()
    print("Evidence L0 (backtest on real feed history) · IS_ADVISORY · OUTSIDE_RISKPOLICY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
