"""
MP-743: StrategyDrawdownGuard
Advisory/read-only analytics module.
Tracks peak portfolio value, current drawdown depth, drawdown duration, and
triggers de-risk alerts when drawdown exceeds configurable thresholds.
Pure stdlib only. Atomic JSON writes via tmp+os.replace.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DrawdownSnapshot:
    strategy_name: str
    portfolio_value_usd: float
    timestamp_iso: str


@dataclass
class DrawdownState:
    strategy_name: str
    current_value_usd: float
    peak_value_usd: float

    # Current drawdown
    drawdown_usd: float = 0.0
    drawdown_pct: float = 0.0

    # Duration (consecutive periods below peak from the end)
    drawdown_duration_periods: int = 0

    # Thresholds
    warning_threshold_pct: float = 10.0
    halt_threshold_pct: float = 20.0

    # Status
    alert_level: str = "NORMAL"
    is_in_drawdown: bool = False
    recovery_needed_pct: float = 0.0

    # Historical max drawdown (across all snapshots)
    max_drawdown_pct: float = 0.0

    recommendation: str = ""


@dataclass
class DrawdownGuardResult:
    strategies: List[DrawdownState] = field(default_factory=list)

    strategies_in_warning: List[str] = field(default_factory=list)
    strategies_in_halt: List[str] = field(default_factory=list)

    overall_alert_level: str = "NORMAL"
    recommendation_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def compute_drawdown(current: float, peak: float) -> float:
    """Drawdown percentage from peak. Returns 0 if peak <= 0."""
    if peak <= 0:
        return 0.0
    if current >= peak:
        return 0.0
    return (peak - current) / peak * 100


def compute_recovery_needed(current: float, peak: float) -> float:
    """Percentage gain needed to recover from current value to peak."""
    if current <= 0:
        return 0.0
    if current >= peak:
        return 0.0
    return (peak / current - 1) * 100


def alert_level(
    drawdown_pct: float,
    warning_threshold: float,
    halt_threshold: float,
) -> str:
    """Return HALT, WARNING, or NORMAL based on drawdown magnitude."""
    if drawdown_pct >= halt_threshold:
        return "HALT"
    if drawdown_pct >= warning_threshold:
        return "WARNING"
    return "NORMAL"


def compute_max_drawdown(snapshots: List[DrawdownSnapshot]) -> float:
    """
    Compute the maximum drawdown percentage observed across the snapshot series.
    Uses a rolling-peak approach. Returns 0 if ≤ 1 snapshot.
    """
    if len(snapshots) <= 1:
        return 0.0
    rolling_peak = snapshots[0].portfolio_value_usd
    max_dd = 0.0
    for snap in snapshots[1:]:
        if snap.portfolio_value_usd > rolling_peak:
            rolling_peak = snap.portfolio_value_usd
        dd = compute_drawdown(snap.portfolio_value_usd, rolling_peak)
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _drawdown_duration(snapshots: List[DrawdownSnapshot], peak: float) -> int:
    """Count consecutive snapshots (from the end) where value < peak."""
    if not snapshots:
        return 0
    count = 0
    for snap in reversed(snapshots):
        if snap.portfolio_value_usd < peak:
            count += 1
        else:
            break
    return count


def _recommendation(dd_pct: float, level: str) -> str:
    if level == "HALT":
        return f"HALT: Drawdown {dd_pct:.1f}% exceeds halt threshold. De-risk immediately."
    if level == "WARNING":
        return f"WARNING: Drawdown {dd_pct:.1f}%. Monitor closely."
    return "Strategy within normal parameters."


# ---------------------------------------------------------------------------
# Strategy analysis
# ---------------------------------------------------------------------------

def analyze_strategy(
    strategy_name: str,
    snapshots: List[DrawdownSnapshot],
    warning_threshold_pct: float = 10.0,
    halt_threshold_pct: float = 20.0,
) -> DrawdownState:
    """
    Analyse a single strategy's snapshot history.
    snapshots: List[DrawdownSnapshot] — sorted ascending by timestamp.
    """
    if not snapshots:
        return DrawdownState(
            strategy_name=strategy_name,
            current_value_usd=0.0,
            peak_value_usd=0.0,
            warning_threshold_pct=warning_threshold_pct,
            halt_threshold_pct=halt_threshold_pct,
            recommendation="No snapshot data available.",
        )

    # rolling peak = max seen so far (full history)
    peak = max(s.portfolio_value_usd for s in snapshots)
    current = snapshots[-1].portfolio_value_usd

    dd_usd = max(0.0, peak - current)
    dd_pct = compute_drawdown(current, peak)
    recovery = compute_recovery_needed(current, peak)
    lvl = alert_level(dd_pct, warning_threshold_pct, halt_threshold_pct)
    duration = _drawdown_duration(snapshots, peak)
    max_dd = compute_max_drawdown(snapshots)
    rec = _recommendation(dd_pct, lvl)

    return DrawdownState(
        strategy_name=strategy_name,
        current_value_usd=current,
        peak_value_usd=peak,
        drawdown_usd=dd_usd,
        drawdown_pct=dd_pct,
        drawdown_duration_periods=duration,
        warning_threshold_pct=warning_threshold_pct,
        halt_threshold_pct=halt_threshold_pct,
        alert_level=lvl,
        is_in_drawdown=(dd_pct > 0.0),
        recovery_needed_pct=recovery,
        max_drawdown_pct=max_dd,
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Portfolio guard
# ---------------------------------------------------------------------------

def _parse_snapshots(raw: List[Dict[str, Any]], strategy_name: str) -> List[DrawdownSnapshot]:
    snaps = []
    for item in raw:
        snaps.append(
            DrawdownSnapshot(
                strategy_name=strategy_name,
                portfolio_value_usd=float(item["portfolio_value_usd"]),
                timestamp_iso=item["timestamp_iso"],
            )
        )
    # Sort ascending by timestamp string (ISO 8601 lexicographic)
    snaps.sort(key=lambda s: s.timestamp_iso)
    return snaps


def _overall_level(states: List[DrawdownState]) -> str:
    levels = {s.alert_level for s in states}
    if "HALT" in levels:
        return "HALT"
    if "WARNING" in levels:
        return "WARNING"
    return "NORMAL"


def guard_portfolio(strategies_data: List[Dict[str, Any]]) -> DrawdownGuardResult:
    """
    strategies_data: List[dict] each with:
        strategy_name, snapshots (list of {portfolio_value_usd, timestamp_iso}),
        warning_threshold_pct (optional, default 10),
        halt_threshold_pct (optional, default 20)
    """
    states: List[DrawdownState] = []
    for item in strategies_data:
        name = item["strategy_name"]
        raw_snaps = item.get("snapshots", [])
        warn = float(item.get("warning_threshold_pct", 10.0))
        halt = float(item.get("halt_threshold_pct", 20.0))
        snaps = _parse_snapshots(raw_snaps, name)
        state = analyze_strategy(name, snaps, warn, halt)
        states.append(state)

    in_warning = [s.strategy_name for s in states if s.alert_level == "WARNING"]
    in_halt = [s.strategy_name for s in states if s.alert_level == "HALT"]
    overall = _overall_level(states)

    n_warn = len(in_warning)
    n_halt = len(in_halt)
    if overall == "HALT":
        rec_summary = (
            f"HALT: {n_halt} strategy/strategies require immediate de-risking. "
            f"{n_warn} in WARNING."
        )
    elif overall == "WARNING":
        rec_summary = (
            f"WARNING: {n_warn} strategy/strategies monitoring required. "
            f"No halts active."
        )
    else:
        rec_summary = (
            f"All {len(states)} strategies within normal drawdown parameters."
        )

    return DrawdownGuardResult(
        strategies=states,
        strategies_in_warning=in_warning,
        strategies_in_halt=in_halt,
        overall_alert_level=overall,
        recommendation_summary=rec_summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "drawdown_guard_log.json"
)
_DEFAULT_LOG = os.path.normpath(_DEFAULT_LOG)
_RING_SIZE = 100


def save_results(result: DrawdownGuardResult, path: str = _DEFAULT_LOG) -> str:
    """Append result to ring-buffer JSON log (max 100). Returns path."""
    history = load_history(path)
    entry = asdict(result)
    entry["_saved_at"] = datetime.now(timezone.utc).isoformat()
    history.append(entry)
    if len(history) > _RING_SIZE:
        history = history[-_RING_SIZE:]
    _atomic_write(path, history)
    result.saved_to = path
    return path


def load_history(path: str = _DEFAULT_LOG) -> list:
    """Load log list, returning [] if missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_save(data, str(path))
    import sys

    sample_data = [
        {
            "strategy_name": "S8_Delta_Neutral",
            "warning_threshold_pct": 10.0,
            "halt_threshold_pct": 20.0,
            "snapshots": [
                {"portfolio_value_usd": 100_000, "timestamp_iso": "2026-06-01T00:00:00Z"},
                {"portfolio_value_usd": 105_000, "timestamp_iso": "2026-06-02T00:00:00Z"},
                {"portfolio_value_usd": 102_000, "timestamp_iso": "2026-06-03T00:00:00Z"},
            ],
        },
        {
            "strategy_name": "S9_EMode",
            "warning_threshold_pct": 10.0,
            "halt_threshold_pct": 20.0,
            "snapshots": [
                {"portfolio_value_usd": 50_000, "timestamp_iso": "2026-06-01T00:00:00Z"},
                {"portfolio_value_usd": 50_500, "timestamp_iso": "2026-06-02T00:00:00Z"},
                {"portfolio_value_usd": 38_000, "timestamp_iso": "2026-06-03T00:00:00Z"},
            ],
        },
    ]

    result = guard_portfolio(sample_data)
    mode = "--check"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    print(f"Overall alert : {result.overall_alert_level}")
    print(f"In HALT       : {result.strategies_in_halt}")
    print(f"In WARNING    : {result.strategies_in_warning}")
    print(f"Summary       : {result.recommendation_summary}")
    for s in result.strategies:
        print(f"  {s.strategy_name}: dd={s.drawdown_pct:.2f}% | {s.alert_level}")

    if mode == "--run":
        saved = save_results(result)
        print(f"Saved to: {saved}")
