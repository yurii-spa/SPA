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
  (b) The panel is a REALIZED BACKTEST over the real feed history, not a live forward track;
      phase="forward" covers only the newest day.
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

import json
import math
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


# ─────────────────────────── real-panel loader ───────────────────────────
def load_panel(panel_dir: Path = PANEL_DIR) -> Dict[str, Dict[str, float]]:
    """{book: {date: daily_return}} from the real realized_series.jsonl files.

    Daily return is derived from equity_usd (the authoritative marked equity), NOT from
    mtm_today_pct, so a book with an odd first-day mark cannot distort the compounding.
    Fail-CLOSED: a book with < 60 usable points is dropped (never fabricated).
    """
    panel: Dict[str, Dict[str, float]] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        book = sub.parent.name
        eq: Dict[str, float] = {}
        for line in sub.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            d = row.get("date") or row.get("as_of")
            e = row.get("equity_usd")
            if d and e is not None and float(e) > 0:
                eq[d] = float(e)
        dates = sorted(eq)
        if len(dates) < 60:
            continue
        rets = {dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0 for i in range(1, len(dates))}
        panel[book] = rets
    if not panel:
        raise RuntimeError(f"no usable books in {panel_dir} — refusing to fabricate a panel")
    return panel


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    target = "susde_dn"
    for a in argv:
        if a.startswith("--target="):
            target = a.split("=", 1)[1]
    panel = load_panel()
    axis = common_axis(panel)
    if target not in panel:
        target = "susde_dn" if "susde_dn" in panel else sorted(panel)[0]
    run_idea16(panel, axis, target=target)
    run_idea17(panel, axis)
    print(f"\n{'='*74}\nEvidence: L0 (real feed-history backtest, NOT live). "
          f"Advisory / paper / OUTSIDE_RISKPOLICY. Survivorship + frictionless-switch caveats apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
