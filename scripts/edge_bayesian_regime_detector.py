#!/usr/bin/env python3
"""
scripts/edge_bayesian_regime_detector.py — registry idea #171 BRD (Bayesian Regime Detector)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

──────────────────────────────────────────────────────────────────────────────────────────────
WHAT IS NEW (#1–#170 READ IN FULL)
──────────────────────────────────────────────────────────────────────────────────────────────
Every prior entry (#1–#170) detects risk via a DETERMINISTIC THRESHOLD RULE:
  "if portfolio_drawdown > θ → cut exposure to x%"
  "if breadth_signal ≥ k → suspend book"
  "if duration_T ≤ τ → reduce by factor"

None uses a PROBABILISTIC POSTERIOR that is updated via Bayes' rule.

BRD maintains a hidden-Markov-model (HMM) posterior
    P_t  =  P(S_t = CRISIS | r_1, …, r_t)
updated at every timestep by the online Bayesian forward filter:

  Predict:  P̃_t  = P_{t-1}·(1 − p_NC) + (1 − P_{t-1})·p_CN
  Update:   P_t   = P̃_t · f_C(r_t) / [P̃_t · f_C(r_t) + (1 − P̃_t) · f_N(r_t)]

where f_N ~ N(μ_N, σ_N), f_C ~ N(μ_C, σ_C) are Gaussian emission densities and
p_CN, p_NC are transition probabilities — all estimated on TRAIN only.

EXPOSURE RULE:
    w_t = max(MIN_FLOOR, 1 − P_{t-1})     ← uses YESTERDAY's posterior (causal, no look-ahead)

This is fundamentally different from threshold rules:
  • Soft / continuous: exposure degrades gradually rather than jumping binary
  • Integrates the FULL history via the posterior (not just the last N days)
  • Adapts to regime structure inferred from TRAIN

WHAT THIS MEASURES:
  Does continuous Bayesian regime detection improve risk-adjusted return over:
    (a) no overlay (EW base)
    (b) a threshold rule with the same de-risk ratio ("simple-threshold" arm)?
  The right answer (positive OR negative) is a valid result for the registry.

FIXTURE (DATA SOURCE)
  Real panel blocked in cloud checkout.  Uses the deterministic L0 synthetic stress fixture:
    spa_core.strategy_lab.aggressive_lab.fixtures.materialize(tmpdir)
  712 backtest-phase rows, 2024-07-01 … 2026-05-31; 6 books.
  Three named stress windows embedded in fixture:
    eth_crash_2024_08    (TRAIN)
    usde_unwind_2025_10  (TEST)
    rseth_depeg_2026_04  (TEST)

  Fixture caveat (#162 PERM): on this fixture any selection rule's crisis-window performance
  is an artifact of generator constants, not a measured property of real markets.  Numbers
  below are [bt] [L0]; the HMM structure is verifiable, the numerical estimates are illustrative.

TRAIN/TEST SPLIT  50 / 50 by row count (first vs last half of the backtest-phase series).

HONEST CAVEATS
  (a) [bt] [L0] synthetic fixture — not live/forward, not real-panel.
  (b) Fixture σ_calm ≈ 0 outside stress windows (#162): HMM crisis-day parameters dominated by
      fixture crisis constants rather than from real distributions.
  (c) Parameters estimated on TRAIN, applied unchanged to TEST.  β ≡ 1 assumption (all books
      equal-weight, no dynamic reweighting per book).
  (d) Transition matrix fixed at TRAIN estimates; adaptive EM would be a separate idea.
  (e) MIN_FLOOR = 0.30 (never fully de-risk; floor chosen to bound carry cost; sweep in §4).
  (f) Cost model: 96 bp round-trip per book, amortised over holding period — same canonical
      convention as #163/#164/#165/#167/#168.
  (g) IS_ADVISORY · OUTSIDE_RISKPOLICY · RiskPolicy v1.0 not touched · live track not opened.

Does NOT touch spa_core/execution, the live paper track, RiskPolicy v1.0, the site, or any agent.
stdlib-only, deterministic (PYTHONHASHSEED=0 not needed — no random calls), LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── path so we can import the fixture ─────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from spa_core.strategy_lab.aggressive_lab.fixtures import (  # noqa: E402
    STRESS_WINDOWS,
    materialize,
)

# ── constants ─────────────────────────────────────────────────────────────────────────────────
TRAIN_FRAC        = 0.50          # first 50% of backtest rows → TRAIN
CRISIS_DAY_THR    = -0.005        # portfolio daily return < −0.5% → "crisis day" for TRAIN param est
MIN_FLOOR         = 0.30          # minimum portfolio exposure (never fully cash)
PRIOR_CRISIS      = 0.05          # prior P(crisis) at t=0 (5%)
ROUND_TRIP_BPS    = 96            # canonical cost convention
DAYS_PER_YEAR     = 365.25
CALMAR_REFUSED_THR = 0.0096       # maxDD < 0.96% → Calmar REFUSED (degenerate)

# "simple threshold" arm: if EW portfolio 1-day return < THRESH, reduce to THRESHOLD_EXP for
# COOLDOWN days (benchmark for BRD to beat or match)
THRESHOLD_SIGNAL  = -0.005        # −0.5%/d triggers
THRESHOLD_EXP     = 0.50          # reduce to 50% exposure
THRESHOLD_COOLDOWN = 10           # stay reduced for 10 days

SWEEP_FLOORS = [0.00, 0.10, 0.20, 0.30, 0.50]  # §4 floor sweep


# ── utility: Gaussian PDF ─────────────────────────────────────────────────────────────────────
def _gaussian_pdf(x: float, mu: float, sigma: float) -> float:
    """Standard Gaussian probability density.  Returns 1e-300 when sigma ≤ 0."""
    if sigma <= 0.0:
        return 1e-300
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * math.sqrt(2.0 * math.pi))


# ── fixture loading ───────────────────────────────────────────────────────────────────────────
def _load_fixture() -> Tuple[List[str], Dict[str, List[float]]]:
    """
    Returns (sorted_dates, {book: [return_on_date, ...]}) over the phase=="backtest" block.
    Daily return computed from equity_usd differences (same logic as edge_real_panel_ensemble).
    Books with < 60 valid points are excluded.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        materialize(tmpdir)
        raw: Dict[str, Dict[str, float]] = {}
        for sub in sorted(Path(tmpdir).glob("*/realized_series.jsonl")):
            book = sub.parent.name
            rows = [json.loads(line) for line in sub.read_text().splitlines() if line.strip()]
            bt = [r for r in rows if r.get("phase") == "backtest"]
            bt.sort(key=lambda r: str(r.get("date", "")))
            # derive returns from equity_usd
            dates_eq: List[Tuple[str, float]] = []
            for r in bt:
                d = r.get("date")
                e = r.get("equity_usd")
                if d and e and float(e) > 0:
                    dates_eq.append((str(d), float(e)))
            if len(dates_eq) < 60:
                continue
            ret_by_date: Dict[str, float] = {}
            for i in range(1, len(dates_eq)):
                d_prev, e_prev = dates_eq[i - 1]
                d_curr, e_curr = dates_eq[i]
                ret_by_date[d_curr] = e_curr / e_prev - 1.0
            raw[book] = ret_by_date

    if not raw:
        raise RuntimeError("no usable fixture books — refusing to continue")

    # common dates (intersection across all books, sorted)
    all_date_sets = [set(v.keys()) for v in raw.values()]
    common = sorted(all_date_sets[0].intersection(*all_date_sets[1:]))
    if len(common) < 60:
        raise RuntimeError("fewer than 60 common dates across fixture books")

    book_series: Dict[str, List[float]] = {
        book: [raw[book][d] for d in common] for book in raw
    }
    return common, book_series


def _ew_returns(book_series: Dict[str, List[float]]) -> List[float]:
    """Equal-weight portfolio daily returns."""
    n = len(book_series)
    n_days = len(next(iter(book_series.values())))
    return [
        sum(book_series[b][i] for b in book_series) / n
        for i in range(n_days)
    ]


# ── HMM parameter estimation on TRAIN ────────────────────────────────────────────────────────
def estimate_hmm_params(
    ew_rets: List[float], n_train: int, crisis_threshold: float = CRISIS_DAY_THR
) -> Tuple[float, float, float, float, float, float]:
    """
    Estimate two-state HMM parameters from TRAIN days.
    Returns: (mu_N, sigma_N, mu_C, sigma_C, p_CN, p_NC)
    where N=Normal, C=Crisis; p_XY = P(transition X→Y per day).

    Crisis days on TRAIN: EW return < crisis_threshold.
    If < 2 crisis days or < 2 normal days, raises with named reason.
    """
    train = ew_rets[:n_train]
    is_crisis = [r < crisis_threshold for r in train]
    normal_days = [r for r, c in zip(train, is_crisis) if not c]
    crisis_days = [r for r, c in zip(train, is_crisis) if c]

    if len(crisis_days) < 2:
        raise RuntimeError(
            f"only {len(crisis_days)} crisis days on TRAIN (threshold {crisis_threshold:.3f})"
            " — cannot estimate crisis emission; refusing to fabricate parameters"
        )
    if len(normal_days) < 2:
        raise RuntimeError(
            f"only {len(normal_days)} normal days on TRAIN — cannot estimate normal emission"
        )

    # emission parameters
    mu_N = sum(normal_days) / len(normal_days)
    var_N = sum((x - mu_N) ** 2 for x in normal_days) / max(len(normal_days) - 1, 1)
    sigma_N = math.sqrt(max(var_N, 1e-10))

    mu_C = sum(crisis_days) / len(crisis_days)
    var_C = sum((x - mu_C) ** 2 for x in crisis_days) / max(len(crisis_days) - 1, 1)
    sigma_C = math.sqrt(max(var_C, 1e-10))

    # transition probabilities from run-length analysis of is_crisis sequence
    n_to_c = 0  # normal → crisis transitions
    n_to_c_opp = 0  # normal → normal (stays)
    c_to_n = 0  # crisis → normal transitions
    c_to_c = 0  # crisis → crisis (stays)
    for i in range(1, n_train):
        prev, curr = is_crisis[i - 1], is_crisis[i]
        if not prev and curr:
            n_to_c += 1
        elif not prev and not curr:
            n_to_c_opp += 1
        elif prev and not curr:
            c_to_n += 1
        elif prev and curr:
            c_to_c += 1

    # MLE transition probabilities (Laplace smoothed with 0.5 pseudocount to avoid zero)
    p_CN = (n_to_c + 0.5) / (n_to_c + n_to_c_opp + 1.0)
    p_NC = (c_to_n + 0.5) / (c_to_n + c_to_c + 1.0)

    return mu_N, sigma_N, mu_C, sigma_C, p_CN, p_NC


# ── Bayesian forward filter ───────────────────────────────────────────────────────────────────
def hmm_forward_filter(
    ew_rets: List[float],
    mu_N: float, sigma_N: float,
    mu_C: float, sigma_C: float,
    p_CN: float, p_NC: float,
    prior_crisis: float = PRIOR_CRISIS,
) -> List[float]:
    """
    Online Bayesian HMM forward filter.
    Returns P_crisis[t] = P(S_t = CRISIS | r_1,...,r_t) for every day.

    Predict:  P̃_t = P_{t-1}·(1−p_NC) + (1−P_{t-1})·p_CN
    Update:   P_t  = P̃_t·f_C(r_t) / [P̃_t·f_C(r_t) + (1−P̃_t)·f_N(r_t)]
    """
    alpha = prior_crisis
    posteriors: List[float] = []
    for r in ew_rets:
        # predict step
        alpha_pred = alpha * (1.0 - p_NC) + (1.0 - alpha) * p_CN
        # update step
        l_c = _gaussian_pdf(r, mu_C, sigma_C)
        l_n = _gaussian_pdf(r, mu_N, sigma_N)
        denom = alpha_pred * l_c + (1.0 - alpha_pred) * l_n
        if denom > 1e-300:
            alpha = alpha_pred * l_c / denom
        else:
            alpha = alpha_pred  # degenerate: keep predict
        alpha = min(1.0, max(0.0, alpha))  # clamp for numerical safety
        posteriors.append(alpha)
    return posteriors


# ── backtest engines ──────────────────────────────────────────────────────────────────────────
def _annualise(total_return: float, n_days: int) -> float:
    """Annualise a compound total return over n_days calendar days."""
    if n_days <= 0:
        return 0.0
    return (1.0 + total_return) ** (DAYS_PER_YEAR / n_days) - 1.0


def _metrics(
    rets: List[float], dates: List[str]
) -> Tuple[float, float, Optional[float]]:
    """
    Returns (APY, max_drawdown, calmar).
    max_drawdown = worst peak-to-trough over the period (negative number).
    calmar = APY / abs(max_drawdown); REFUSED (None) if abs(max_drawdown) < CALMAR_REFUSED_THR.
    """
    if not rets:
        return 0.0, 0.0, None
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        eq *= 1.0 + r
        if eq > peak:
            peak = eq
        dd = eq / peak - 1.0
        if dd < max_dd:
            max_dd = dd
    n_days = len(dates)
    apy = _annualise(eq - 1.0, n_days)
    if abs(max_dd) < CALMAR_REFUSED_THR:
        calmar = None  # degenerate: denominator below toll
    else:
        calmar = apy / abs(max_dd)
    return apy, max_dd, calmar


def run_brd(
    ew_rets: List[float],
    posteriors: List[float],
    min_floor: float = MIN_FLOOR,
    switch_cost_bps: float = ROUND_TRIP_BPS,
) -> Tuple[List[float], int]:
    """
    Bayesian-scaled portfolio returns.
    Exposure for day t = max(min_floor, 1 − P_{t-1})   ← CAUSAL: yesterday's posterior
    Returns: (scaled_daily_returns, n_switches)
    A "switch" is any day where the integral exposure changes by > 0.5 pp (96bps cost event).
    """
    scaled: List[float] = []
    n_switches = 0
    prev_w = 1.0  # start fully invested
    for i, r in enumerate(ew_rets):
        # exposure based on PREVIOUS posterior (causal); day 0 uses PRIOR
        p_prev = posteriors[i - 1] if i > 0 else PRIOR_CRISIS
        w = max(min_floor, 1.0 - p_prev)
        # cost only on SUBSTANTIAL moves (> 0.5 pp) so tiny Bayesian noise is free
        if abs(w - prev_w) > 0.005:
            cost = switch_cost_bps / 10000.0 * abs(w - prev_w)
            n_switches += 1
        else:
            cost = 0.0
        scaled.append(w * r - cost)
        prev_w = w
    return scaled, n_switches


def run_threshold(
    ew_rets: List[float],
    signal_thr: float = THRESHOLD_SIGNAL,
    de_risk_to: float = THRESHOLD_EXP,
    cooldown: int = THRESHOLD_COOLDOWN,
    switch_cost_bps: float = ROUND_TRIP_BPS,
) -> Tuple[List[float], int]:
    """
    Simple threshold-rule arm: if EW return < signal_thr → reduce to de_risk_to for cooldown days.
    Returns: (scaled_daily_returns, n_switches)
    """
    scaled: List[float] = []
    n_switches = 0
    cooldown_left = 0
    prev_w = 1.0
    for r in ew_rets:
        if r < signal_thr:
            cooldown_left = cooldown
        w = de_risk_to if cooldown_left > 0 else 1.0
        cooldown_left = max(0, cooldown_left - 1)
        if abs(w - prev_w) > 0.005:
            cost = switch_cost_bps / 10000.0 * abs(w - prev_w)
            n_switches += 1
        else:
            cost = 0.0
        scaled.append(w * r - cost)
        prev_w = w
    return scaled, n_switches


# ── crisis window performance ─────────────────────────────────────────────────────────────────
def _window_dd(rets: List[float], dates: List[str], date_from: str, date_to: str) -> float:
    """Max drawdown within a named stress window (open interval [date_from, date_to])."""
    eq = 1.0
    peak = 1.0
    max_dd = 0.0
    in_window = False
    for d, r in zip(dates, rets):
        if d >= date_from:
            in_window = True
        if d > date_to:
            break
        if in_window:
            eq *= 1.0 + r
            if eq > peak:
                peak = eq
            dd = eq / peak - 1.0
            if dd < max_dd:
                max_dd = dd
    return max_dd


# ── main ──────────────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 78)
    print("#171 BRD — Bayesian Regime Detector")
    print("[bt] [L0] synthetic fixture (real panel DATA-BLOCKED in cloud checkout)")
    print("=" * 78)

    # §0 load fixture
    dates, book_series = _load_fixture()
    ew_rets = _ew_returns(book_series)
    n_total = len(dates)
    n_train = int(n_total * TRAIN_FRAC)
    n_test = n_total - n_train
    train_dates = dates[:n_train]
    test_dates = dates[n_train:]
    print(f"\n§0 ДАННЫЕ")
    print(f"  всего дней: {n_total}  ({dates[0]} … {dates[-1]})")
    print(f"  TRAIN: {n_train} дней  ({dates[0]} … {train_dates[-1]})")
    print(f"  TEST:  {n_test} дней  ({test_dates[0]} … {dates[-1]})")
    print(f"  книги: {sorted(book_series)}")

    # §1 HMM parameter estimation on TRAIN
    mu_N, sigma_N, mu_C, sigma_C, p_CN, p_NC = estimate_hmm_params(
        ew_rets, n_train, CRISIS_DAY_THR
    )
    n_crisis_train = sum(1 for r in ew_rets[:n_train] if r < CRISIS_DAY_THR)
    print(f"\n§1 HMM ПАРАМЕТРЫ (TRAIN, порог кризис-дня={CRISIS_DAY_THR:.3f})")
    print(f"  кризис-дней в TRAIN: {n_crisis_train} / {n_train}")
    print(f"  μ_N = {mu_N*100:.4f}%/d   σ_N = {sigma_N*100:.4f}%/d")
    print(f"  μ_C = {mu_C*100:.4f}%/d   σ_C = {sigma_C*100:.4f}%/d")
    print(f"  p_CN (N→C) = {p_CN:.4f}/d  ({p_CN*100:.2f}%/d)")
    print(f"  p_NC (C→N) = {p_NC:.4f}/d  ({p_NC*100:.2f}%/d)")
    print(f"  стационарное P(crisis) = {p_CN/(p_CN+p_NC):.3f}")

    # §2 Bayesian forward filter (applied to FULL series using TRAIN parameters)
    posteriors = hmm_forward_filter(
        ew_rets, mu_N, sigma_N, mu_C, sigma_C, p_CN, p_NC, PRIOR_CRISIS
    )
    p_crisis_test = posteriors[n_train:]

    # summary of posterior in TEST
    p_mean_test = sum(p_crisis_test) / len(p_crisis_test)
    p_max_test = max(p_crisis_test)
    days_above_50 = sum(1 for p in p_crisis_test if p > 0.5)
    print(f"\n§2 POSTERIOR P(CRISIS) В TEST")
    print(f"  среднее: {p_mean_test:.3f}  максимум: {p_max_test:.3f}")
    print(f"  дней с P>50%: {days_above_50} / {n_test}")

    # §3 backtest: BASE vs BRD vs THRESHOLD
    # run on FULL series first (to get Calmar across full)
    brd_full, n_sw_brd = run_brd(ew_rets, posteriors, MIN_FLOOR)
    thr_full, n_sw_thr = run_threshold(ew_rets)

    # then split TRAIN / TEST
    brd_train = brd_full[:n_train]
    brd_test  = brd_full[n_train:]
    thr_train = thr_full[:n_train]
    thr_test  = thr_full[n_train:]
    base_train = ew_rets[:n_train]
    base_test  = ew_rets[n_train:]

    apy_base_tr, dd_base_tr, cal_base_tr = _metrics(base_train, train_dates)
    apy_base_te, dd_base_te, cal_base_te = _metrics(base_test, test_dates)
    apy_brd_tr,  dd_brd_tr,  cal_brd_tr  = _metrics(brd_train, train_dates)
    apy_brd_te,  dd_brd_te,  cal_brd_te  = _metrics(brd_test,  test_dates)
    apy_thr_tr,  dd_thr_tr,  cal_thr_tr  = _metrics(thr_train, train_dates)
    apy_thr_te,  dd_thr_te,  cal_thr_te  = _metrics(thr_test,  test_dates)

    def fmt_calmar(c: Optional[float]) -> str:
        return f"{c:.3f}" if c is not None else "REFUSED(dd<toll)"

    print(f"\n§3 BACKTЕСТ  (cost={ROUND_TRIP_BPS} bp, min_floor={MIN_FLOOR:.0%})")
    print(f"{'арм':<18} {'APY TRAIN':>10} {'DD TRAIN':>10} {'Cal TRAIN':>12}"
          f" {'APY TEST':>10} {'DD TEST':>10} {'Cal TEST':>12} {'свичей':>8}")
    print("-" * 100)
    print(f"{'base EW':18} {apy_base_tr*100:>10.2f}% {dd_base_tr*100:>10.2f}%"
          f" {fmt_calmar(cal_base_tr):>12}"
          f" {apy_base_te*100:>10.2f}% {dd_base_te*100:>10.2f}%"
          f" {fmt_calmar(cal_base_te):>12} {'—':>8}")
    print(f"{'BRD (Bayes)':18} {apy_brd_tr*100:>10.2f}% {dd_brd_tr*100:>10.2f}%"
          f" {fmt_calmar(cal_brd_tr):>12}"
          f" {apy_brd_te*100:>10.2f}% {dd_brd_te*100:>10.2f}%"
          f" {fmt_calmar(cal_brd_te):>12} {n_sw_brd:>8}")
    print(f"{'threshold':18} {apy_thr_tr*100:>10.2f}% {dd_thr_tr*100:>10.2f}%"
          f" {fmt_calmar(cal_thr_tr):>12}"
          f" {apy_thr_te*100:>10.2f}% {dd_thr_te*100:>10.2f}%"
          f" {fmt_calmar(cal_thr_te):>12} {n_sw_thr:>8}")

    # §4 floor sweep on TEST
    print(f"\n§4 SWEEP MIN_FLOOR (TEST, Calmar тест BRD)")
    print(f"{'floor':>8} {'APY TEST':>10} {'DD TEST':>10} {'Calmar TEST':>14} {'свичей':>8}")
    for fl in SWEEP_FLOORS:
        brd_fl, sw_fl = run_brd(ew_rets, posteriors, fl)
        a, d, c = _metrics(brd_fl[n_train:], test_dates)
        print(f"{fl:>8.0%} {a*100:>10.2f}% {d*100:>10.2f}% {fmt_calmar(c):>14} {sw_fl:>8}")

    # §5 per-window performance
    print(f"\n§5 PER-WINDOW DRAWDOWN (внутри окна, арм: base vs BRD vs threshold)")
    print(f"{'окно':<30} {'base':>10} {'BRD':>10} {'threshold':>10}")
    for sw in STRESS_WINDOWS:
        dd_b = _window_dd(ew_rets,  dates, sw["date_from"], sw["date_to"])
        dd_r = _window_dd(brd_full, dates, sw["date_from"], sw["date_to"])
        dd_t = _window_dd(thr_full, dates, sw["date_from"], sw["date_to"])
        marker = "▶ TEST" if sw["date_from"] >= test_dates[0] else "TRAIN"
        print(f"  {sw['key'][:28]:<28} [{marker}]"
              f" {dd_b*100:>8.2f}% {dd_r*100:>10.2f}% {dd_t*100:>10.2f}%")

    # §6 verdict
    print("\n§6 ВЕРДИКТ")

    # determine verdict
    brd_wins_dd = dd_brd_te < dd_base_te  # negative numbers, < is worse
    brd_wins_calmar = (cal_brd_te is not None and cal_base_te is not None
                       and cal_brd_te > cal_base_te)
    brd_better_than_thr_calmar = (cal_brd_te is not None and cal_thr_te is not None
                                  and cal_brd_te > cal_thr_te)
    apy_cost = apy_base_te - apy_brd_te  # positive = BRD gave up APY

    print(f"  BRD улучшает maxDD vs base: {brd_wins_dd} "
          f"({dd_base_te*100:.2f}% → {dd_brd_te*100:.2f}%)")
    print(f"  BRD улучшает Calmar vs base: {brd_wins_calmar} "
          f"({fmt_calmar(cal_base_te)} → {fmt_calmar(cal_brd_te)})")
    print(f"  BRD лучше threshold по Calmar: {brd_better_than_thr_calmar} "
          f"({fmt_calmar(cal_thr_te)} → {fmt_calmar(cal_brd_te)})")
    print(f"  Стоимость BRD в APY: {apy_cost*100:.2f} pp")
    print(f"  Переходов BRD vs threshold: {n_sw_brd} vs {n_sw_thr}")

    if brd_wins_dd and brd_wins_calmar and brd_better_than_thr_calmar:
        verdict = "CONDITIONALLY_POSITIVE"
        summary = "BRD улучшает и DD и Calmar vs base, и превосходит threshold-arm — forwarding-paper кандидат НА РЕАЛЬНОЙ ПАНЕЛИ"
    elif brd_wins_dd and brd_wins_calmar:
        verdict = "MARGINAL_POSITIVE"
        summary = "BRD улучшает DD и Calmar vs base, но не лучше threshold-arm — Bayesian смягчение работает, но не добавляет к простому правилу"
    elif brd_wins_dd:
        verdict = "STRUCTURAL_FINDING"
        summary = "BRD улучшает только DD (не Calmar): APY потеря > DD выгода — carry cost превышает защиту"
    else:
        verdict = "NEGATIVE"
        summary = "BRD не улучшает ни DD ни Calmar: Bayesian posterior не компенсирует стоимость частичного de-risking"

    print(f"\n  ВЕРДИКТ: {verdict}")
    print(f"  {summary}")

    print(f"\n  Оговорка фикстуры (#162 PERM): данные синтетические, σ_calm ≈ 0 вне кризис-окон —")
    print(f"  HMM параметры доминируются генератором. Числа [bt][L0], не реальные.")
    print("=" * 78)

    return verdict


if __name__ == "__main__":
    main()
