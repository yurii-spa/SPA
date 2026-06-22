"""
MP-694: SmartMoneyFlowTracker
Track capital flow patterns to detect "smart money" movements —
large sophisticated investors entering or exiting DeFi protocols.

Advisory / read-only analytics. Pure stdlib. Atomic writes (os.replace).
"""

from dataclasses import dataclass
from typing import List
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/smart_money_flow_log.json")
MAX_ENTRIES = 100


@dataclass
class CapitalFlowEvent:
    event_id: str
    protocol: str
    direction: str          # "INFLOW" or "OUTFLOW"
    amount_usd: float
    timestamp: float        # unix timestamp
    wallet_type: str        # "WHALE", "DAO", "INSTITUTION", "RETAIL"
    is_concentrated: bool   # True if single wallet > 80% of amount


@dataclass
class FlowAnalysis:
    protocol: str
    analysis_window_hours: int
    total_inflow_usd: float
    total_outflow_usd: float
    net_flow_usd: float             # inflow - outflow
    flow_direction: str             # STRONG_INFLOW / INFLOW / NEUTRAL / OUTFLOW / STRONG_OUTFLOW
    smart_money_score: float        # 0.0–1.0: proportion of whale/institution flows
    is_exodus: bool                 # True if net outflow > 20% of total volume
    is_accumulation: bool           # True if net inflow > 20% of total volume AND smart_money > 0.5
    largest_single_flow_usd: float
    event_count: int
    signal: str                     # BULLISH / NEUTRAL / BEARISH
    recommendations: List[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_flow_direction(net_flow_usd: float, total_volume_usd: float) -> str:
    """Classify net flow relative to total volume."""
    if total_volume_usd == 0:
        return "NEUTRAL"
    if net_flow_usd > total_volume_usd * 0.3:
        return "STRONG_INFLOW"
    if net_flow_usd > total_volume_usd * 0.1:
        return "INFLOW"
    if net_flow_usd < -total_volume_usd * 0.3:
        return "STRONG_OUTFLOW"
    if net_flow_usd < -total_volume_usd * 0.1:
        return "OUTFLOW"
    return "NEUTRAL"


def _compute_smart_money_score(events: List[CapitalFlowEvent]) -> float:
    """Proportion of WHALE + INSTITUTION events; 0.0 if no events."""
    if not events:
        return 0.0
    smart = sum(1 for e in events if e.wallet_type in ("WHALE", "INSTITUTION"))
    return smart / len(events)


def _compute_signal(
    flow_direction: str,
    smart_money_score: float,
    is_exodus: bool,
) -> str:
    """Return BULLISH / NEUTRAL / BEARISH."""
    if flow_direction in ("STRONG_INFLOW", "INFLOW") and smart_money_score > 0.4:
        return "BULLISH"
    if is_exodus or flow_direction in ("STRONG_OUTFLOW", "OUTFLOW"):
        return "BEARISH"
    return "NEUTRAL"


def _build_recommendations(
    is_accumulation: bool,
    is_exodus: bool,
    smart_money_score: float,
    signal: str,
) -> List[str]:
    recs: List[str] = []
    if is_accumulation:
        recs.append("🐋 Smart money accumulation detected — follow institutional flow")
    if is_exodus:
        recs.append("🚨 Capital exodus — reduce exposure or exit")
    if smart_money_score > 0.6:
        recs.append("📊 High smart money participation — signal reliability elevated")
    if signal == "BULLISH":
        recs.append("✅ Bullish flow signal — consider increasing allocation")
    if signal == "BEARISH":
        recs.append("⚠️ Bearish flow signal — defensive positioning recommended")
    return recs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    protocol: str,
    events: List[CapitalFlowEvent],
    window_hours: int = 24,
) -> FlowAnalysis:
    """
    Analyse capital flows for *protocol* within the last *window_hours* hours.
    The reference point is the timestamp of the latest event in *events*
    (so that unit tests with fixed timestamps work deterministically).
    """
    if events:
        latest_ts = max(e.timestamp for e in events)
    else:
        latest_ts = time.time()

    cutoff = latest_ts - window_hours * 3600

    filtered = [
        e for e in events
        if e.protocol == protocol and e.timestamp >= cutoff
    ]

    total_inflow = sum(e.amount_usd for e in filtered if e.direction == "INFLOW")
    total_outflow = sum(e.amount_usd for e in filtered if e.direction == "OUTFLOW")
    net_flow = total_inflow - total_outflow
    total_volume = total_inflow + total_outflow

    flow_direction = _compute_flow_direction(net_flow, total_volume)
    smart_money_score = _compute_smart_money_score(filtered)

    is_exodus = net_flow < -total_volume * 0.2 if total_volume > 0 else False
    is_accumulation = (
        net_flow > total_volume * 0.2
        and smart_money_score > 0.5
        if total_volume > 0
        else False
    )

    largest = max((e.amount_usd for e in filtered), default=0.0)

    signal = _compute_signal(flow_direction, smart_money_score, is_exodus)
    recommendations = _build_recommendations(
        is_accumulation, is_exodus, smart_money_score, signal
    )

    return FlowAnalysis(
        protocol=protocol,
        analysis_window_hours=window_hours,
        total_inflow_usd=total_inflow,
        total_outflow_usd=total_outflow,
        net_flow_usd=net_flow,
        flow_direction=flow_direction,
        smart_money_score=smart_money_score,
        is_exodus=is_exodus,
        is_accumulation=is_accumulation,
        largest_single_flow_usd=largest,
        event_count=len(filtered),
        signal=signal,
        recommendations=recommendations,
    )


def analyze_all(
    events: List[CapitalFlowEvent],
    window_hours: int = 24,
) -> List[FlowAnalysis]:
    """Group events by protocol and return a FlowAnalysis for each."""
    protocols = list(dict.fromkeys(e.protocol for e in events))  # preserve order
    return [analyze(p, events, window_hours) for p in protocols]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _flow_analysis_to_dict(fa: FlowAnalysis) -> dict:
    return {
        "protocol": fa.protocol,
        "analysis_window_hours": fa.analysis_window_hours,
        "total_inflow_usd": fa.total_inflow_usd,
        "total_outflow_usd": fa.total_outflow_usd,
        "net_flow_usd": fa.net_flow_usd,
        "flow_direction": fa.flow_direction,
        "smart_money_score": fa.smart_money_score,
        "is_exodus": fa.is_exodus,
        "is_accumulation": fa.is_accumulation,
        "largest_single_flow_usd": fa.largest_single_flow_usd,
        "event_count": fa.event_count,
        "signal": fa.signal,
        "recommendations": fa.recommendations,
        "_saved_at": time.time(),
    }


def save_results(
    analyses: List[FlowAnalysis],
    data_file: Path = DATA_FILE,
    max_entries: int = MAX_ENTRIES,
) -> None:
    """Append analyses to ring-buffer JSON; atomic write via os.replace."""
    data_file = Path(data_file)
    existing = load_history(data_file)

    new_records = [_flow_analysis_to_dict(a) for a in analyses]
    combined = existing + new_records

    # Ring-buffer: keep last max_entries
    if len(combined) > max_entries:
        combined = combined[-max_entries:]

    tmp = data_file.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w") as fh:
        json.dump(combined, fh, indent=2)
    os.replace(tmp, data_file)


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load saved analyses; returns [] if file missing or invalid."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        with open(data_file) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
