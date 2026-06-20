"""
YieldSentimentScorer (MP-726)
==============================

Scores DeFi market sentiment using on-chain observable signals:
TVL momentum, yield compression/expansion, capital flow direction.
Guides overall risk posture (advisory only — never touches risk/execution).

Signals (weights sum to 1.0):
  1. TVL_7D           (0.25) — short-term capital flow
  2. TVL_30D          (0.20) — medium-term capital trend
  3. YIELD_EXPANSION  (0.25) — yield opportunity signal
  4. ACTIVITY         (0.15) — new protocol launches (ecosystem health)
  5. STABLECOIN_FLIGHT(0.15) — stablecoin dominance (risk-off indicator)

Score range: -100 (very bearish) … +100 (very bullish)

Output: data/yield_sentiment_log.json (ring-buffer 100 entries)

Design constraints
------------------
* Pure stdlib only — no numpy / pandas / requests.
* Advisory / read-only: never imports execution/, risk/, monitoring/.
* Atomic writes: tmp + os.replace.
* Deterministic: identical input → identical output.
* CLI: --check (default) | --run (+ save) | --data-dir PATH
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILE = "yield_sentiment_log.json"
_RING_BUFFER_MAX = 100

# ---------------------------------------------------------------------------
# Signal weights — MUST sum to 1.0
# ---------------------------------------------------------------------------
_SIGNAL_WEIGHTS: Dict[str, float] = {
    "TVL_7D":            0.25,
    "TVL_30D":           0.20,
    "YIELD_EXPANSION":   0.25,
    "ACTIVITY":          0.15,
    "STABLECOIN_FLIGHT": 0.15,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SentimentSignal:
    signal_name: str
    value: float
    direction: str       # "BULLISH" | "BEARISH" | "NEUTRAL"
    weight: float
    contribution: float  # direction_score (+1/0/-1) * weight  → ×100 for final


@dataclass
class SentimentReport:
    # Raw inputs
    total_tvl_usd: float
    tvl_7d_change_pct: float
    tvl_30d_change_pct: float
    avg_top10_apy: float
    apy_7d_change_pct: float
    new_protocol_launches_30d: int
    stablecoin_dominance_pct: float

    # Computed
    signals: List[SentimentSignal]
    raw_score: float
    normalized_score: float
    sentiment: str        # VERY_BULLISH | BULLISH | NEUTRAL | BEARISH | VERY_BEARISH
    confidence: str       # HIGH | MEDIUM | LOW
    recommended_risk_pct: float
    positioning_label: str
    market_notes: List[str]
    saved_to: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

def _direction_score(direction: str) -> float:
    if direction == "BULLISH":
        return 1.0
    if direction == "BEARISH":
        return -1.0
    return 0.0


def _tvl_7d_direction(value: float) -> str:
    if value > 5:
        return "BULLISH"
    if value < -5:
        return "BEARISH"
    return "NEUTRAL"


def _tvl_30d_direction(value: float) -> str:
    if value > 10:
        return "BULLISH"
    if value < -10:
        return "BEARISH"
    return "NEUTRAL"


def _yield_expansion_direction(value: float) -> str:
    if value > 5:
        return "BULLISH"
    if value < -5:
        return "BEARISH"
    return "NEUTRAL"


def _activity_direction(value: float) -> str:
    if value > 5:
        return "BULLISH"
    if value < 2:
        return "BEARISH"
    return "NEUTRAL"


def _stablecoin_flight_direction(value: float) -> str:
    if value > 60:
        return "BEARISH"
    if value < 30:
        return "BULLISH"
    return "NEUTRAL"


def compute_signals(
    tvl_7d_change_pct: float,
    tvl_30d_change_pct: float,
    apy_7d_change_pct: float,
    new_protocol_launches_30d: int,
    stablecoin_dominance_pct: float,
) -> List[SentimentSignal]:
    """Compute all 5 sentiment signals."""
    specs = [
        ("TVL_7D",            tvl_7d_change_pct,       _tvl_7d_direction),
        ("TVL_30D",           tvl_30d_change_pct,      _tvl_30d_direction),
        ("YIELD_EXPANSION",   apy_7d_change_pct,       _yield_expansion_direction),
        ("ACTIVITY",          float(new_protocol_launches_30d), _activity_direction),
        ("STABLECOIN_FLIGHT", stablecoin_dominance_pct, _stablecoin_flight_direction),
    ]
    signals: List[SentimentSignal] = []
    for name, value, dir_fn in specs:
        direction = dir_fn(value)
        weight = _SIGNAL_WEIGHTS[name]
        contribution = _direction_score(direction) * weight
        signals.append(SentimentSignal(
            signal_name=name,
            value=value,
            direction=direction,
            weight=weight,
            contribution=contribution,
        ))
    return signals


def _compute_raw_score(signals: List[SentimentSignal]) -> float:
    return sum(s.contribution for s in signals) * 100.0


def _classify_sentiment(score: float) -> str:
    if score > 60:
        return "VERY_BULLISH"
    if score > 20:
        return "BULLISH"
    if score > -20:
        return "NEUTRAL"
    if score > -60:
        return "BEARISH"
    return "VERY_BEARISH"


def _classify_confidence(score: float) -> str:
    abs_score = abs(score)
    if abs_score > 60:
        return "HIGH"
    if abs_score > 30:
        return "MEDIUM"
    return "LOW"


_RISK_PCT: Dict[str, float] = {
    "VERY_BULLISH": 90.0,
    "BULLISH":      75.0,
    "NEUTRAL":      55.0,
    "BEARISH":      35.0,
    "VERY_BEARISH": 20.0,
}


def _positioning_label(risk_pct: float) -> str:
    if risk_pct >= 80:
        return "FULLY_DEPLOYED"
    if risk_pct >= 65:
        return "MOSTLY_DEPLOYED"
    if risk_pct >= 45:
        return "BALANCED"
    if risk_pct >= 25:
        return "DEFENSIVE"
    return "VERY_DEFENSIVE"


def _build_market_notes(signals: List[SentimentSignal], sentiment: str) -> List[str]:
    notes: List[str] = []
    # Sort by absolute contribution (most extreme first)
    sorted_sigs = sorted(signals, key=lambda s: abs(s.contribution), reverse=True)
    top = sorted_sigs[:3]

    label_map = {
        "TVL_7D":            "7-day TVL momentum",
        "TVL_30D":           "30-day TVL trend",
        "YIELD_EXPANSION":   "yield expansion",
        "ACTIVITY":          "new protocol activity",
        "STABLECOIN_FLIGHT": "stablecoin dominance",
    }

    for sig in top:
        if sig.direction == "BULLISH":
            notes.append(
                f"{label_map[sig.signal_name]} is signalling bullish "
                f"(value={sig.value:.1f})"
            )
        elif sig.direction == "BEARISH":
            notes.append(
                f"{label_map[sig.signal_name]} is signalling bearish "
                f"(value={sig.value:.1f})"
            )
        else:
            notes.append(
                f"{label_map[sig.signal_name]} is neutral "
                f"(value={sig.value:.1f})"
            )

    # Overall note
    notes.append(f"Overall market sentiment: {sentiment}")
    return notes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_sentiment(
    total_tvl_usd: float,
    tvl_7d_change_pct: float,
    tvl_30d_change_pct: float,
    avg_top10_apy: float,
    apy_7d_change_pct: float,
    new_protocol_launches_30d: int,
    stablecoin_dominance_pct: float,
    data_dir: Optional[Path] = None,
) -> SentimentReport:
    """Compute a full SentimentReport from market inputs."""
    signals = compute_signals(
        tvl_7d_change_pct,
        tvl_30d_change_pct,
        apy_7d_change_pct,
        new_protocol_launches_30d,
        stablecoin_dominance_pct,
    )
    raw_score = _compute_raw_score(signals)
    normalized_score = max(-100.0, min(100.0, raw_score))
    sentiment = _classify_sentiment(normalized_score)
    confidence = _classify_confidence(normalized_score)
    risk_pct = _RISK_PCT[sentiment]
    pos_label = _positioning_label(risk_pct)
    notes = _build_market_notes(signals, sentiment)

    dd = data_dir or _DEFAULT_DATA_DIR
    saved_to = str(dd / _LOG_FILE)

    return SentimentReport(
        total_tvl_usd=total_tvl_usd,
        tvl_7d_change_pct=tvl_7d_change_pct,
        tvl_30d_change_pct=tvl_30d_change_pct,
        avg_top10_apy=avg_top10_apy,
        apy_7d_change_pct=apy_7d_change_pct,
        new_protocol_launches_30d=new_protocol_launches_30d,
        stablecoin_dominance_pct=stablecoin_dominance_pct,
        signals=signals,
        raw_score=raw_score,
        normalized_score=normalized_score,
        sentiment=sentiment,
        confidence=confidence,
        recommended_risk_pct=risk_pct,
        positioning_label=pos_label,
        market_notes=notes,
        saved_to=saved_to,
    )


def trend_comparison(reports: List[SentimentReport]) -> dict:
    """Summarise sentiment change across a list of historical reports."""
    if not reports:
        return {"error": "no_reports"}
    sentiments = [r.sentiment for r in reports]
    scores = [r.normalized_score for r in reports]
    return {
        "count": len(reports),
        "latest_sentiment": sentiments[-1],
        "earliest_sentiment": sentiments[0],
        "latest_score": scores[-1],
        "earliest_score": scores[0],
        "score_delta": scores[-1] - scores[0],
        "sentiment_history": sentiments,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _report_to_dict(report: SentimentReport) -> dict:
    return {
        "timestamp": report.timestamp,
        "total_tvl_usd": report.total_tvl_usd,
        "tvl_7d_change_pct": report.tvl_7d_change_pct,
        "tvl_30d_change_pct": report.tvl_30d_change_pct,
        "avg_top10_apy": report.avg_top10_apy,
        "apy_7d_change_pct": report.apy_7d_change_pct,
        "new_protocol_launches_30d": report.new_protocol_launches_30d,
        "stablecoin_dominance_pct": report.stablecoin_dominance_pct,
        "signals": [
            {
                "signal_name": s.signal_name,
                "value": s.value,
                "direction": s.direction,
                "weight": s.weight,
                "contribution": s.contribution,
            }
            for s in report.signals
        ],
        "raw_score": report.raw_score,
        "normalized_score": report.normalized_score,
        "sentiment": report.sentiment,
        "confidence": report.confidence,
        "recommended_risk_pct": report.recommended_risk_pct,
        "positioning_label": report.positioning_label,
        "market_notes": report.market_notes,
        "saved_to": report.saved_to,
    }


def save_results(report: SentimentReport, data_dir: Optional[Path] = None) -> str:
    """Append report to ring-buffer log (max 100). Returns path written."""
    dd = data_dir or _DEFAULT_DATA_DIR
    dd.mkdir(parents=True, exist_ok=True)
    log_path = dd / _LOG_FILE

    existing: list = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(_report_to_dict(report))
    # Ring-buffer trim
    if len(existing) > _RING_BUFFER_MAX:
        existing = existing[-_RING_BUFFER_MAX:]

    # Atomic write
    atomic_save(existing, str(log_path))
    return str(log_path)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load all saved sentiment reports as raw dicts."""
    dd = data_dir or _DEFAULT_DATA_DIR
    log_path = dd / _LOG_FILE
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Convenience: weights validation
# ---------------------------------------------------------------------------

def weights_sum() -> float:
    return sum(_SIGNAL_WEIGHTS.values())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(report: SentimentReport) -> None:
    print("\n=== YieldSentimentScorer (MP-726) ===")
    print(f"  Timestamp   : {report.timestamp}")
    print(f"  Total TVL   : ${report.total_tvl_usd:,.0f}")
    print(f"  TVL 7d      : {report.tvl_7d_change_pct:+.1f}%")
    print(f"  TVL 30d     : {report.tvl_30d_change_pct:+.1f}%")
    print(f"  APY avg     : {report.avg_top10_apy:.2f}%")
    print(f"  APY 7d Δ    : {report.apy_7d_change_pct:+.1f}%")
    print(f"  New protos  : {report.new_protocol_launches_30d}")
    print(f"  Stable dom  : {report.stablecoin_dominance_pct:.1f}%")
    print()
    print(f"  Raw score   : {report.raw_score:+.1f}")
    print(f"  Norm score  : {report.normalized_score:+.1f}")
    print(f"  Sentiment   : {report.sentiment}")
    print(f"  Confidence  : {report.confidence}")
    print(f"  Risk %      : {report.recommended_risk_pct:.0f}%")
    print(f"  Positioning : {report.positioning_label}")
    print()
    print("  Signals:")
    for sig in report.signals:
        print(f"    {sig.signal_name:<20} {sig.direction:<8} "
              f"contrib={sig.contribution:+.3f}  (w={sig.weight})")
    print()
    print("  Notes:")
    for note in report.market_notes:
        print(f"    • {note}")
    print()


def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv
    data_dir = _DEFAULT_DATA_DIR
    if "--data-dir" in argv:
        idx = argv.index("--data-dir")
        if idx + 1 < len(argv):
            data_dir = Path(argv[idx + 1])

    # Demo inputs (representative of a mild bull market)
    report = score_sentiment(
        total_tvl_usd=45_000_000_000,
        tvl_7d_change_pct=6.5,
        tvl_30d_change_pct=12.0,
        avg_top10_apy=5.8,
        apy_7d_change_pct=6.2,
        new_protocol_launches_30d=7,
        stablecoin_dominance_pct=38.0,
        data_dir=data_dir,
    )
    _print_report(report)

    if run_mode:
        path = save_results(report, data_dir=data_dir)
        print(f"  Saved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
