"""YieldOptimizationSummary (MP-729).

Master analytics aggregator — combines signals from multiple analytics modules
into a single executive summary with prioritised action items and health scoring.

Design constraints:
- Pure stdlib only — no external dependencies.
- Advisory / read-only (never touches allocator / risk / execution).
- Atomic JSON writes via tmp + os.replace.
- Ring-buffer history capped at 100 entries.

Public API
----------
    create_signal(...) -> AnalyticsSignal
    compute_health_score(summary_metrics) -> float
    build_summary(portfolio_id, signals, summary_metrics, generated_at_iso) -> OptimizationSummary
    merge_summaries(summaries) -> List[AnalyticsSignal]
    top_opportunities(summary, n) -> List[AnalyticsSignal]
    top_risks(summary, n) -> List[AnalyticsSignal]
    save_results(summary, data_dir) -> str
    load_history(data_dir) -> list
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HISTORY_MAX: int = 100
_LOG_FILE: str = "optimization_summary_log.json"
_DEFAULT_DATA_DIR: str = "data"

SIGNAL_TYPES = frozenset({"RISK", "OPPORTUNITY", "ACTION", "INFO"})
HEALTH_LABELS = {
    80.0: "EXCELLENT",
    60.0: "GOOD",
    40.0: "FAIR",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AnalyticsSignal:
    """A single analytics signal from any module."""

    module: str                    # source module
    signal_type: str               # "RISK" | "OPPORTUNITY" | "ACTION" | "INFO"
    priority: int                  # 1 = highest, 5 = lowest
    title: str                     # short description
    detail: str                    # longer description
    recommended_action: str        # what to do
    estimated_impact_pct: float    # estimated APY or risk improvement


@dataclass
class OptimizationSummary:
    """Aggregated executive portfolio summary."""

    portfolio_id: str
    generated_at_iso: str

    # Overall health
    overall_health_score: float = 0.0      # 0–100 composite
    health_label: str = "POOR"             # EXCELLENT | GOOD | FAIR | POOR

    # Input signals (sorted by priority asc)
    signals: List[AnalyticsSignal] = field(default_factory=list)

    # Bucketed by priority
    immediate_actions: List[AnalyticsSignal] = field(default_factory=list)   # priority 1
    short_term_actions: List[AnalyticsSignal] = field(default_factory=list)  # priority 2–3
    monitor_items: List[AnalyticsSignal] = field(default_factory=list)       # priority 4–5

    # Key metrics summary
    summary_metrics: Dict[str, float] = field(default_factory=dict)

    # Narrative
    executive_summary: str = ""

    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def create_signal(
    module: str,
    signal_type: str,
    priority: int,
    title: str,
    detail: str,
    recommended_action: str,
    estimated_impact_pct: float,
) -> AnalyticsSignal:
    """Create an AnalyticsSignal with all fields validated.

    Parameters
    ----------
    module:
        Name of the analytics module generating this signal.
    signal_type:
        One of "RISK", "OPPORTUNITY", "ACTION", "INFO".
    priority:
        1 (highest urgency) to 5 (lowest).
    title:
        Short one-line description.
    detail:
        Full description.
    recommended_action:
        Suggested remediation or follow-up.
    estimated_impact_pct:
        Expected APY or risk improvement (%).

    Returns
    -------
    AnalyticsSignal
    """
    return AnalyticsSignal(
        module=str(module),
        signal_type=str(signal_type),
        priority=int(priority),
        title=str(title),
        detail=str(detail),
        recommended_action=str(recommended_action),
        estimated_impact_pct=float(estimated_impact_pct),
    )


def compute_health_score(summary_metrics: Dict[str, float]) -> float:
    """Compute a composite health score [0–100].

    Formula (requires keys total_apy, total_risk, diversification, sustainability):

        health = (total_apy / 20 * 25)
               + ((100 - total_risk) / 100 * 30)
               + (diversification / 100 * 25)
               + (sustainability / 100 * 20)

    Each component contributes max points when:
        total_apy >= 20, total_risk == 0, diversification == 100, sustainability == 100.

    If any required key is missing the component contributes 0.

    Parameters
    ----------
    summary_metrics:
        Dict with optional keys: total_apy, total_risk, diversification, sustainability.

    Returns
    -------
    float
        Health score capped to [0.0, 100.0].
    """
    total_apy = float(summary_metrics.get("total_apy", 0.0))
    total_risk = float(summary_metrics.get("total_risk", 0.0))
    diversification = float(summary_metrics.get("diversification", 0.0))
    sustainability = float(summary_metrics.get("sustainability", 0.0))

    score = (
        (total_apy / 20.0 * 25.0)
        + ((100.0 - total_risk) / 100.0 * 30.0)
        + (diversification / 100.0 * 25.0)
        + (sustainability / 100.0 * 20.0)
    )
    return max(0.0, min(100.0, score))


def _health_label(score: float) -> str:
    """Map numeric health score to label."""
    if score >= 80.0:
        return "EXCELLENT"
    if score >= 60.0:
        return "GOOD"
    if score >= 40.0:
        return "FAIR"
    return "POOR"


def _build_executive_summary(
    immediate_actions: List[AnalyticsSignal],
    short_term_actions: List[AnalyticsSignal],
    health_label: str,
    health_score: float,
) -> str:
    """Generate a 2–3 sentence executive summary string."""
    n_immediate = len(immediate_actions)
    n_short = len(short_term_actions)
    top = immediate_actions[0].title if immediate_actions else "No immediate actions"
    return (
        f"Portfolio has {n_immediate} immediate action{'s' if n_immediate != 1 else ''}, "
        f"{n_short} short-term item{'s' if n_short != 1 else ''}. "
        f"Overall health: {health_label} ({health_score:.0f}/100). "
        f"Top priority: {top}."
    )


def build_summary(
    portfolio_id: str,
    signals: List[AnalyticsSignal],
    summary_metrics: Dict[str, float],
    generated_at_iso: str,
) -> OptimizationSummary:
    """Assemble an OptimizationSummary from a list of signals.

    Steps
    -----
    1. Sort signals by priority ascending (stable sort, preserving order of
       equal-priority signals).
    2. Bucket into immediate_actions (p=1), short_term_actions (p=2–3),
       monitor_items (p=4–5).
    3. Compute overall_health_score via compute_health_score(summary_metrics).
    4. Derive health_label and generate executive_summary.

    Parameters
    ----------
    portfolio_id:
        Unique portfolio identifier.
    signals:
        Raw list of AnalyticsSignal objects (not modified).
    summary_metrics:
        Dict of metric values for health scoring.
    generated_at_iso:
        ISO-8601 timestamp string.

    Returns
    -------
    OptimizationSummary
    """
    sorted_signals = sorted(signals, key=lambda s: s.priority)

    immediate = [s for s in sorted_signals if s.priority == 1]
    short_term = [s for s in sorted_signals if s.priority in (2, 3)]
    monitor = [s for s in sorted_signals if s.priority in (4, 5)]

    health_score = compute_health_score(summary_metrics)
    label = _health_label(health_score)

    executive = _build_executive_summary(immediate, short_term, label, health_score)

    return OptimizationSummary(
        portfolio_id=portfolio_id,
        generated_at_iso=generated_at_iso,
        overall_health_score=health_score,
        health_label=label,
        signals=sorted_signals,
        immediate_actions=immediate,
        short_term_actions=short_term,
        monitor_items=monitor,
        summary_metrics=dict(summary_metrics),
        executive_summary=executive,
        saved_to="",
    )


def merge_summaries(summaries: List[OptimizationSummary]) -> List[AnalyticsSignal]:
    """Merge signals from multiple summaries, deduplicating by title.

    The first occurrence of each title is kept; subsequent duplicates are
    dropped.  Order is preserved (all signals from summaries[0] first,
    then summaries[1], etc.).

    Parameters
    ----------
    summaries:
        List of OptimizationSummary objects.

    Returns
    -------
    List[AnalyticsSignal]
        Combined, deduplicated signal list.
    """
    seen_titles: set = set()
    combined: List[AnalyticsSignal] = []
    for summary in summaries:
        for sig in summary.signals:
            if sig.title not in seen_titles:
                seen_titles.add(sig.title)
                combined.append(sig)
    return combined


def top_opportunities(
    summary: OptimizationSummary,
    n: int,
) -> List[AnalyticsSignal]:
    """Return the top-n OPPORTUNITY signals sorted by estimated_impact_pct descending.

    Parameters
    ----------
    summary:
        The OptimizationSummary to query.
    n:
        Maximum number of signals to return.

    Returns
    -------
    List[AnalyticsSignal]
    """
    opps = [s for s in summary.signals if s.signal_type == "OPPORTUNITY"]
    opps.sort(key=lambda s: s.estimated_impact_pct, reverse=True)
    return opps[:n]


def top_risks(
    summary: OptimizationSummary,
    n: int,
) -> List[AnalyticsSignal]:
    """Return the top-n RISK signals sorted by priority asc then impact desc.

    Parameters
    ----------
    summary:
        The OptimizationSummary to query.
    n:
        Maximum number of signals to return.

    Returns
    -------
    List[AnalyticsSignal]
    """
    risks = [s for s in summary.signals if s.signal_type == "RISK"]
    risks.sort(key=lambda s: (s.priority, -s.estimated_impact_pct))
    return risks[:n]


# ---------------------------------------------------------------------------
# Persistence (advisory, atomic ring-buffer)
# ---------------------------------------------------------------------------

def _signal_to_dict(s: AnalyticsSignal) -> dict:
    return {
        "module": s.module,
        "signal_type": s.signal_type,
        "priority": s.priority,
        "title": s.title,
        "detail": s.detail,
        "recommended_action": s.recommended_action,
        "estimated_impact_pct": s.estimated_impact_pct,
    }


def _summary_to_dict(s: OptimizationSummary) -> dict:
    return {
        "portfolio_id": s.portfolio_id,
        "generated_at_iso": s.generated_at_iso,
        "overall_health_score": s.overall_health_score,
        "health_label": s.health_label,
        "signals": [_signal_to_dict(sig) for sig in s.signals],
        "immediate_actions": [_signal_to_dict(sig) for sig in s.immediate_actions],
        "short_term_actions": [_signal_to_dict(sig) for sig in s.short_term_actions],
        "monitor_items": [_signal_to_dict(sig) for sig in s.monitor_items],
        "summary_metrics": dict(s.summary_metrics),
        "executive_summary": s.executive_summary,
        "saved_to": s.saved_to,
        "persisted_at": datetime.now(timezone.utc).isoformat(),
    }


def save_results(
    summary: OptimizationSummary,
    data_dir: str = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically append summary to ring-buffer JSON log (max 100 entries).

    Parameters
    ----------
    summary:
        The OptimizationSummary to persist.
    data_dir:
        Directory for the log file (created if absent).

    Returns
    -------
    str
        Absolute path of the written file.
    """
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    log_path = data_path / _LOG_FILE

    history: list = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                history = json.load(fh)
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []

    entry = _summary_to_dict(summary)
    history.append(entry)
    if len(history) > _HISTORY_MAX:
        history = history[-_HISTORY_MAX:]

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(dir=data_path, prefix=".opt_summary_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    summary.saved_to = str(log_path.resolve())
    return summary.saved_to


def load_history(data_dir: str = _DEFAULT_DATA_DIR) -> list:
    """Load the persisted optimization summary history.

    Parameters
    ----------
    data_dir:
        Directory containing the log file.

    Returns
    -------
    list
        List of summary dicts (may be empty).
    """
    log_path = Path(data_dir) / _LOG_FILE
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


__all__ = [
    "AnalyticsSignal",
    "OptimizationSummary",
    "create_signal",
    "compute_health_score",
    "build_summary",
    "merge_summaries",
    "top_opportunities",
    "top_risks",
    "save_results",
    "load_history",
]
