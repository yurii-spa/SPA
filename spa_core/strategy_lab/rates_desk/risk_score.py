"""
spa_core/strategy_lab/rates_desk/risk_score.py — deterministic per-underlying TAIL-RISK score.

RESEARCH module (Rates-Desk de-risk). Pure stdlib, deterministic, LLM-forbidden, fail-CLOSED.

Produces a 0..1 tail-risk score per underlying per date from data we ALREADY have:
  1. DEPEG drawdown   — how far the SMOOTHED X/ETH ratio has fallen from its trailing peak
                        (the peg reference). Measures the ezETH/rsETH-type peg breakdown.
  2. DOWNSIDE-DRIFT vol — volatility of the NEGATIVE daily moves of the smoothed ratio (the
                        "grinding decay" of a token that slowly loses its peg).
  3. FUNDING-FLIP prob — fraction of recent days with NEGATIVE perp funding. A delta-neutral
                        restaking carry trade pays for its short hedge out of funding; when
                        funding flips negative the hedge BLEEDS — the classic carry-unwind that
                        precedes restaking blowups. (Per-underlying funding is not available;
                        we use the shared ETH-perp funding as the systemic carry-regime signal.)

Higher score = more toxic = more of any quoted excess yield is just tail compensation.

FAIL-CLOSED: a date with no usable smoothed ratio (insufficient history / a gap) scores its
depeg+drift components at MAXIMUM (1.0), never a silent low score. Funding falls back to 0 only
if the funding series is entirely absent (and that absence is surfaced, not hidden).

DEPEG SMOOTHING: the raw DeFiLlama X/ETH ratio carries spurious 1-day spikes (the token and ETH
are logged at different intraday moments). We evaluate every depeg signal on a SHORT TRAILING
MEDIAN of the ratio — the exact remedy in strategies/eth_lst_neutral.py + variant_n.py. The ratio
is NOT assumed ~1.0 (value-accruing wrappers drift above 1.0); depeg = drawdown vs trailing peak.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from spa_core.strategy_lab.rates_desk import config as C


@dataclass
class TailScore:
    """One underlying's tail-risk score on one date, with its components exposed for audit."""
    underlying: str
    date: str
    score: float                       # 0..1 composite (higher = more toxic)
    depeg_dd: float = 0.0              # smoothed-ratio drawdown vs trailing peak (>=0, fraction)
    downside_drift_vol: float = 0.0   # downside daily-drift vol of the smoothed ratio (fraction)
    funding_flip_prob: float = 0.0    # fraction of recent days with negative funding
    depeg_sub: float = 0.0            # normalized 0..1 sub-scores (audit)
    drift_sub: float = 0.0
    funding_sub: float = 0.0
    failed_closed: bool = False       # True if scored at MAX due to missing/insufficient data
    reason: str = ""


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def trailing_median(values: Sequence[float], window: int) -> List[float]:
    """Per-index trailing median over the last `window` values (the false-depeg de-noiser)."""
    out: List[float] = []
    for i in range(len(values)):
        w = values[max(0, i - window + 1): i + 1]
        out.append(statistics.median(w) if w else 0.0)
    return out


def _smoothed_ratio_series(ratios_by_date: Dict[str, float], window: int) -> Dict[str, float]:
    """{date: raw X/ETH ratio} → {date: trailing-median ratio}. Dates ascending."""
    dates = sorted(ratios_by_date)
    raw = [ratios_by_date[d] for d in dates]
    sm = trailing_median(raw, window)
    return {d: sm[i] for i, d in enumerate(dates)}


def _depeg_drawdown(smoothed: List[float], idx: int, peak_window: int) -> float:
    """Drawdown of smoothed[idx] vs the max over the trailing `peak_window`. >=0 (0 = at/above
    peak). This is the peg-breakdown signal that is independent of the token's absolute ratio
    level (value-accruing wrappers sit above 1.0)."""
    lo = max(0, idx - peak_window)
    window = smoothed[lo: idx + 1]
    if not window:
        return 0.0
    peak = max(window)
    if peak <= 0:
        return 0.0
    dd = (peak - smoothed[idx]) / peak
    return dd if dd > 0 else 0.0


def _downside_drift_vol(smoothed: List[float], idx: int, vol_window: int) -> float:
    """RMS of the NEGATIVE daily fractional changes of the smoothed ratio over the trailing
    window. Captures the grinding one-sided decay of a slowly-failing peg (a stable token has a
    tiny number here; a toxic LRT a large one)."""
    lo = max(1, idx - vol_window + 1)
    downs: List[float] = []
    for j in range(lo, idx + 1):
        prev = smoothed[j - 1]
        if prev <= 0:
            continue
        chg = (smoothed[j] - prev) / prev
        if chg < 0:
            downs.append(chg)
    if not downs:
        return 0.0
    return math.sqrt(sum(c * c for c in downs) / len(downs))


def funding_flip_prob(funding_by_date: Dict[str, float], date: str, window: int) -> Optional[float]:
    """Fraction of the trailing `window` days (up to and incl. `date`) with NEGATIVE funding.
    None if no funding history covers the window (caller decides — we surface, not hide)."""
    dates = sorted(d for d in funding_by_date if d <= date)
    if not dates:
        return None
    tail = dates[-window:]
    if not tail:
        return None
    neg = sum(1 for d in tail if funding_by_date[d] < 0)
    return neg / len(tail)


def score_underlying_series(
    underlying: str,
    ratios_by_date: Dict[str, float],
    funding_by_date: Optional[Dict[str, float]] = None,
    cfg=C,
) -> Dict[str, TailScore]:
    """Score one underlying over its whole ratio history → {date: TailScore}.

    Deterministic. A date whose smoothed ratio cannot be formed (no history) is failed-CLOSED at
    score 1.0. Funding is a shared systemic signal (per-underlying funding is unavailable); if
    the funding series is absent the funding sub-score is 0 and that is reflected in `reason`."""
    funding_by_date = funding_by_date or {}
    dates = sorted(ratios_by_date)
    if not dates:
        return {}
    smoothed_map = _smoothed_ratio_series(ratios_by_date, cfg.RATIO_MEDIAN_WINDOW)
    smoothed = [smoothed_map[d] for d in dates]

    out: Dict[str, TailScore] = {}
    for i, d in enumerate(dates):
        if smoothed[i] is None or smoothed[i] <= 0:
            out[d] = TailScore(underlying, d, 1.0, failed_closed=True,
                               reason="no usable smoothed ratio")
            continue
        dd = _depeg_drawdown(smoothed, i, cfg.RATIO_PEAK_WINDOW)
        dvol = _downside_drift_vol(smoothed, i, cfg.DRIFT_VOL_WINDOW)
        fflip = funding_flip_prob(funding_by_date, d, cfg.FUNDING_WINDOW)

        depeg_sub = _clamp01(dd / cfg.DEPEG_DD_FULL) if cfg.DEPEG_DD_FULL > 0 else 0.0
        drift_sub = _clamp01(dvol / cfg.DRIFT_VOL_FULL) if cfg.DRIFT_VOL_FULL > 0 else 0.0
        funding_sub = (_clamp01(fflip / cfg.FUNDING_FLIP_FULL)
                       if (fflip is not None and cfg.FUNDING_FLIP_FULL > 0) else 0.0)

        score = (cfg.W_DEPEG * depeg_sub
                 + cfg.W_DRIFT * drift_sub
                 + cfg.W_FUNDING * funding_sub)
        reason = "" if fflip is not None else "no funding history (funding sub=0)"
        out[d] = TailScore(
            underlying=underlying, date=d, score=round(_clamp01(score), 6),
            depeg_dd=round(dd, 6), downside_drift_vol=round(dvol, 6),
            funding_flip_prob=round(fflip, 6) if fflip is not None else 0.0,
            depeg_sub=round(depeg_sub, 6), drift_sub=round(drift_sub, 6),
            funding_sub=round(funding_sub, 6), reason=reason,
        )
    return out


def score_on_date(
    underlying: str,
    ratios_by_date: Dict[str, float],
    date: str,
    funding_by_date: Optional[Dict[str, float]] = None,
    cfg=C,
) -> TailScore:
    """Tail score for ONE date (uses only data up to `date` — no look-ahead). Fail-CLOSED at 1.0
    if `date` has no usable history."""
    upto = {d: v for d, v in ratios_by_date.items() if d <= date}
    series = score_underlying_series(underlying, upto, funding_by_date, cfg)
    if date in series:
        return series[date]
    return TailScore(underlying, date, 1.0, failed_closed=True, reason="date not in history")
