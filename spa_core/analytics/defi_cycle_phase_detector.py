"""
MP-717: DeFiCyclePhaseDetector
Detects which phase of the DeFi market cycle the ecosystem is in based on
TVL trends, yield levels, and capital flow signals.

Advisory/read-only. Pure stdlib. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap 100 entries.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from spa_core.utils.atomic import atomic_save

# ── Default paths ──────────────────────────────────────────────────────────
_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "cycle_phase_log.json"
)
_RING_CAP = 100


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class MarketSignal:
    signal_type: str    # "TVL" | "YIELD" | "CAPITAL_FLOW" | "VOLATILITY"
    value: float        # current reading
    trend: str          # "RISING" | "FALLING" | "STABLE"
    strength: str       # "STRONG" | "MODERATE" | "WEAK"


@dataclass
class CyclePhaseReport:
    # Inputs
    total_tvl_usd: float
    tvl_30d_change_pct: float
    avg_top_protocol_apy: float
    apy_30d_change_pct: float
    new_capital_inflow_usd: float

    # Analysis
    signals: List[MarketSignal]

    # Phase scores 0–100
    accumulation_score: float
    bull_score: float
    distribution_score: float
    bear_score: float

    # Current phase
    current_phase: str      # "ACCUMULATION"|"BULL"|"DISTRIBUTION"|"BEAR"
    phase_confidence: str   # "HIGH"|"MEDIUM"|"LOW"

    # Recommendations
    strategy_bias: str      # "AGGRESSIVE_DEPLOY"|"DEPLOY_SELECTIVELY"|"REDUCE_EXPOSURE"|"DEFENSIVE"
    risk_multiplier: float  # 1.5 | 1.0 | 0.7 | 0.4

    outlook_days: int       # 30 | 60 | 90 | 120
    warnings: List[str]
    saved_to: str = ""
    timestamp: float = field(default_factory=time.time)


# ── Trend classification ───────────────────────────────────────────────────

def classify_tvl_trend(tvl_30d_change_pct: float) -> Tuple[str, str]:
    """
    Classify TVL 30-day % change into (trend, strength).
    > 20%      → RISING / STRONG
    5–20%      → RISING / MODERATE
    0–5%       → STABLE / WEAK
    -5 to 0%   → STABLE / WEAK
    -20 to -5% → FALLING / MODERATE
    < -20%     → FALLING / STRONG
    """
    pct = tvl_30d_change_pct
    if pct > 20:
        return "RISING", "STRONG"
    elif pct > 5:
        return "RISING", "MODERATE"
    elif pct >= -5:
        return "STABLE", "WEAK"
    elif pct >= -20:
        return "FALLING", "MODERATE"
    else:
        return "FALLING", "STRONG"


def classify_yield_trend(apy_30d_change_pct: float) -> Tuple[str, str]:
    """
    Classify APY 30-day % change into (trend, strength).
    > 20%      → RISING / STRONG
    5–20%      → RISING / MODERATE
    0–5%       → STABLE / WEAK
    -5 to 0%   → STABLE / WEAK
    -20 to -5% → FALLING / MODERATE
    < -20%     → FALLING / STRONG
    """
    pct = apy_30d_change_pct
    if pct > 20:
        return "RISING", "STRONG"
    elif pct > 5:
        return "RISING", "MODERATE"
    elif pct >= -5:
        return "STABLE", "WEAK"
    elif pct >= -20:
        return "FALLING", "MODERATE"
    else:
        return "FALLING", "STRONG"


# ── Phase scoring ──────────────────────────────────────────────────────────

def score_phases(
    tvl_30d_change_pct: float,
    apy_30d_change_pct: float,
    avg_top_protocol_apy: float,
    new_capital_inflow_usd: float,
    total_tvl_usd: float,
) -> Dict[str, float]:
    """
    Score each of the four DeFi cycle phases 0–100.

    ACCUMULATION: TVL stable or slight recovery, yields high, low inflow
      base: -5 < tvl_change < 15 → 40
      if avg_apy > 8 → +20
      if new_capital < total_tvl * 0.02 → +20

    BULL: TVL rising fast, yields falling, high inflow
      base: tvl_change > 15 → 40
      if apy_30d_change_pct < -5 → +20
      if new_capital > total_tvl * 0.05 → +20
      if tvl_change > 30 → +10 extra

    DISTRIBUTION: TVL growth slowing, yields very low, inflow slowing
      base: 0 < tvl_change < 10 → 30
      if avg_apy < 5 → +25
      if new_capital < total_tvl * 0.03 → +20

    BEAR: TVL falling, any yield, outflows
      base: tvl_change < -5 → 40
      if tvl_change < -20 → +20 extra
      if new_capital < 0 → +20
    """
    tvl_ratio = new_capital_inflow_usd / total_tvl_usd if total_tvl_usd > 0 else 0.0

    # ── ACCUMULATION ──
    accum = 0.0
    if -5 < tvl_30d_change_pct < 15:
        accum += 40
    if avg_top_protocol_apy > 8:
        accum += 20
    if new_capital_inflow_usd < total_tvl_usd * 0.02:
        accum += 20
    accum = min(accum, 100.0)

    # ── BULL ──
    bull = 0.0
    if tvl_30d_change_pct > 15:
        bull += 40
    if apy_30d_change_pct < -5:
        bull += 20
    if new_capital_inflow_usd > total_tvl_usd * 0.05:
        bull += 20
    if tvl_30d_change_pct > 30:
        bull += 10
    bull = min(bull, 100.0)

    # ── DISTRIBUTION ──
    dist = 0.0
    if 0 < tvl_30d_change_pct < 10:
        dist += 30
    if avg_top_protocol_apy < 5:
        dist += 25
    if new_capital_inflow_usd < total_tvl_usd * 0.03:
        dist += 20
    dist = min(dist, 100.0)

    # ── BEAR ──
    bear = 0.0
    if tvl_30d_change_pct < -5:
        bear += 40
    if tvl_30d_change_pct < -20:
        bear += 20
    if new_capital_inflow_usd < 0:
        bear += 20
    bear = min(bear, 100.0)

    return {
        "accumulation": accum,
        "bull": bull,
        "distribution": dist,
        "bear": bear,
    }


def detect_phase(scores: Dict[str, float]) -> str:
    """Return the phase key with the highest score."""
    phase_map = {
        "accumulation": "ACCUMULATION",
        "bull": "BULL",
        "distribution": "DISTRIBUTION",
        "bear": "BEAR",
    }
    best_key = max(scores, key=lambda k: scores[k])
    return phase_map[best_key]


def _phase_confidence(winning_score: float) -> str:
    if winning_score > 60:
        return "HIGH"
    elif winning_score >= 40:
        return "MEDIUM"
    return "LOW"


def _strategy_bias(phase: str) -> str:
    return {
        "BULL": "AGGRESSIVE_DEPLOY",
        "ACCUMULATION": "DEPLOY_SELECTIVELY",
        "DISTRIBUTION": "REDUCE_EXPOSURE",
        "BEAR": "DEFENSIVE",
    }[phase]


def _risk_multiplier(phase: str) -> float:
    return {
        "BULL": 1.5,
        "ACCUMULATION": 1.0,
        "DISTRIBUTION": 0.7,
        "BEAR": 0.4,
    }[phase]


def _outlook_days(confidence: str) -> int:
    return {"HIGH": 30, "MEDIUM": 60, "LOW": 90}[confidence]


# ── Signal builder ─────────────────────────────────────────────────────────

def _build_signals(
    tvl_30d_change_pct: float,
    avg_top_protocol_apy: float,
    apy_30d_change_pct: float,
    new_capital_inflow_usd: float,
    total_tvl_usd: float,
) -> List[MarketSignal]:
    tvl_trend, tvl_strength = classify_tvl_trend(tvl_30d_change_pct)
    yield_trend, yield_strength = classify_yield_trend(apy_30d_change_pct)

    # CAPITAL_FLOW: rising if positive inflow > 3% TVL, falling if negative
    if new_capital_inflow_usd > total_tvl_usd * 0.03:
        cf_trend, cf_strength = "RISING", "STRONG"
    elif new_capital_inflow_usd > 0:
        cf_trend, cf_strength = "RISING", "MODERATE"
    elif new_capital_inflow_usd < 0:
        cf_trend, cf_strength = "FALLING", "STRONG"
    else:
        cf_trend, cf_strength = "STABLE", "WEAK"

    # VOLATILITY: based on combined movement magnitude
    vol_mag = abs(tvl_30d_change_pct + apy_30d_change_pct) / 2.0
    if vol_mag > 15:
        vol_strength = "STRONG"
    elif vol_mag > 7:
        vol_strength = "MODERATE"
    else:
        vol_strength = "WEAK"
    # trend: same direction as TVL
    vol_trend = tvl_trend

    return [
        MarketSignal("TVL", tvl_30d_change_pct, tvl_trend, tvl_strength),
        MarketSignal("YIELD", avg_top_protocol_apy, yield_trend, yield_strength),
        MarketSignal("CAPITAL_FLOW", new_capital_inflow_usd, cf_trend, cf_strength),
        MarketSignal("VOLATILITY", vol_mag, vol_trend, vol_strength),
    ]


# ── Main analysis function ─────────────────────────────────────────────────

def analyze(
    total_tvl_usd: float,
    tvl_30d_change_pct: float,
    avg_top_protocol_apy: float,
    apy_30d_change_pct: float,
    new_capital_inflow_usd: float,
    log_path: str = _DEFAULT_LOG,
) -> CyclePhaseReport:
    """
    Analyze DeFi market cycle phase from input signals.
    Returns CyclePhaseReport (advisory, does not persist automatically).
    """
    signals = _build_signals(
        tvl_30d_change_pct,
        avg_top_protocol_apy,
        apy_30d_change_pct,
        new_capital_inflow_usd,
        total_tvl_usd,
    )

    scores = score_phases(
        tvl_30d_change_pct,
        apy_30d_change_pct,
        avg_top_protocol_apy,
        new_capital_inflow_usd,
        total_tvl_usd,
    )

    phase = detect_phase(scores)
    winning_score = scores[phase.lower()]
    confidence = _phase_confidence(winning_score)
    bias = _strategy_bias(phase)
    multiplier = _risk_multiplier(phase)
    outlook = _outlook_days(confidence)

    # Warnings
    warnings: List[str] = []
    if scores["bear"] > 60:
        warnings.append("bear market conditions")
    if avg_top_protocol_apy < 3 and tvl_30d_change_pct < 0:
        warnings.append("yield collapse + TVL drain")
    if new_capital_inflow_usd < 0:
        warnings.append("capital leaving DeFi")

    return CyclePhaseReport(
        total_tvl_usd=total_tvl_usd,
        tvl_30d_change_pct=tvl_30d_change_pct,
        avg_top_protocol_apy=avg_top_protocol_apy,
        apy_30d_change_pct=apy_30d_change_pct,
        new_capital_inflow_usd=new_capital_inflow_usd,
        signals=signals,
        accumulation_score=scores["accumulation"],
        bull_score=scores["bull"],
        distribution_score=scores["distribution"],
        bear_score=scores["bear"],
        current_phase=phase,
        phase_confidence=confidence,
        strategy_bias=bias,
        risk_multiplier=multiplier,
        outlook_days=outlook,
        warnings=warnings,
        saved_to="",
        timestamp=time.time(),
    )


# ── Period comparison ──────────────────────────────────────────────────────

def compare_periods(reports: List[CyclePhaseReport]) -> List[CyclePhaseReport]:
    """Return reports sorted by total_tvl_usd descending."""
    return sorted(reports, key=lambda r: r.total_tvl_usd, reverse=True)


# ── Persistence: ring-buffer 100 ───────────────────────────────────────────

def _signal_to_dict(s: MarketSignal) -> dict:
    return {
        "signal_type": s.signal_type,
        "value": s.value,
        "trend": s.trend,
        "strength": s.strength,
    }


def _report_to_dict(report: CyclePhaseReport) -> dict:
    return {
        "total_tvl_usd": report.total_tvl_usd,
        "tvl_30d_change_pct": report.tvl_30d_change_pct,
        "avg_top_protocol_apy": report.avg_top_protocol_apy,
        "apy_30d_change_pct": report.apy_30d_change_pct,
        "new_capital_inflow_usd": report.new_capital_inflow_usd,
        "signals": [_signal_to_dict(s) for s in report.signals],
        "accumulation_score": report.accumulation_score,
        "bull_score": report.bull_score,
        "distribution_score": report.distribution_score,
        "bear_score": report.bear_score,
        "current_phase": report.current_phase,
        "phase_confidence": report.phase_confidence,
        "strategy_bias": report.strategy_bias,
        "risk_multiplier": report.risk_multiplier,
        "outlook_days": report.outlook_days,
        "warnings": report.warnings,
        "saved_to": report.saved_to,
        "timestamp": report.timestamp,
    }


def save_results(
    report: CyclePhaseReport,
    log_path: str = _DEFAULT_LOG,
) -> CyclePhaseReport:
    """Append report to ring-buffer log (cap 100). Atomic write."""
    log_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    history = load_history(log_path)

    # Build new report with saved_to set
    report = CyclePhaseReport(
        total_tvl_usd=report.total_tvl_usd,
        tvl_30d_change_pct=report.tvl_30d_change_pct,
        avg_top_protocol_apy=report.avg_top_protocol_apy,
        apy_30d_change_pct=report.apy_30d_change_pct,
        new_capital_inflow_usd=report.new_capital_inflow_usd,
        signals=report.signals,
        accumulation_score=report.accumulation_score,
        bull_score=report.bull_score,
        distribution_score=report.distribution_score,
        bear_score=report.bear_score,
        current_phase=report.current_phase,
        phase_confidence=report.phase_confidence,
        strategy_bias=report.strategy_bias,
        risk_multiplier=report.risk_multiplier,
        outlook_days=report.outlook_days,
        warnings=report.warnings,
        saved_to=log_path,
        timestamp=report.timestamp,
    )

    history.append(_report_to_dict(report))
    if len(history) > _RING_CAP:
        history = history[-_RING_CAP:]

    _atomic_write(log_path, history)
    return report


def load_history(log_path: str = _DEFAULT_LOG) -> list:
    """Load ring-buffer history list. Returns [] if file missing/malformed."""
    log_path = os.path.abspath(log_path)
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically via tmp file + os.replace."""
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
# ── CLI entry ──────────────────────────────────────────────────────────────

def _demo() -> None:
    """Quick smoke-test with synthetic data."""
    report = analyze(
        total_tvl_usd=50_000_000_000,
        tvl_30d_change_pct=25.0,
        avg_top_protocol_apy=4.2,
        apy_30d_change_pct=-8.0,
        new_capital_inflow_usd=3_000_000_000,
    )
    print(f"Phase: {report.current_phase} ({report.phase_confidence})")
    print(f"Strategy bias: {report.strategy_bias}")
    print(f"Risk multiplier: {report.risk_multiplier}")
    print(f"Scores: accum={report.accumulation_score:.0f} bull={report.bull_score:.0f} "
          f"dist={report.distribution_score:.0f} bear={report.bear_score:.0f}")
    print(f"Warnings: {report.warnings}")
    saved = save_results(report)
    print(f"Saved to: {saved.saved_to}")


if __name__ == "__main__":
    _demo()
