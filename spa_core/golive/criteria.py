"""
SPA-V387 — Go-Live Readiness Criteria registry.

Determines the *catalogue* of go-live criteria the ReadinessChecker evaluates.
This module is PURELY DECLARATIVE — it defines WHAT is checked (id, name,
category, weight, description), never HOW the underlying data is read or graded.
The grading logic lives in ``readiness_checker.py``.

Read-only / analytics surface only. No money-moving code, no execution, no
risk-agent or feed-health coupling — this is a reporting aggregation over data
files those subsystems already emit.

Weight semantics (used by the verdict logic in readiness_checker):
  * ``blocker`` — a FAIL here forces the overall verdict to ``NOT_READY``,
                  regardless of the composite score.
  * ``high`` / ``medium`` / ``low`` — contribute to the weighted score only.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    """A single go-live readiness criterion (declarative descriptor)."""

    id: str           # stable identifier, e.g. "C001"
    name: str         # human-readable headline
    category: str     # "paper_trading" / "adapters" / "risk" / "infrastructure"
    weight: str       # "blocker" / "high" / "medium" / "low"
    description: str  # what PASS means / where the data comes from


# ─── Weight → numeric points (for the weighted score) ───────────────────────────
WEIGHT_POINTS: dict[str, float] = {
    "blocker": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}


# ─── The criteria catalogue ─────────────────────────────────────────────────────
CRITERIA: list[Criterion] = [
    # ── paper_trading ──────────────────────────────────────────────────────────
    Criterion(
        "C001",
        "Paper trading duration ≥ 30 days",
        "paper_trading",
        "blocker",
        "Elapsed paper-trading days since PAPER_START_DATE must be ≥ 30.",
    ),
    Criterion(
        "C002",
        "Win rate ≥ 40%",
        "paper_trading",
        "blocker",
        "win_rate_pct from data/risk_metrics.json must be ≥ 40%.",
    ),
    Criterion(
        "C003",
        "Max drawdown ≤ 5%",
        "paper_trading",
        "blocker",
        "Absolute max_drawdown_pct must be ≤ 5% (risk_metrics / drawdown_analysis).",
    ),
    Criterion(
        "C004",
        "Sharpe ratio computed",
        "paper_trading",
        "medium",
        "sharpe_ratio must exist (any sign); a negative value is a WARN, not a FAIL.",
    ),
    Criterion(
        "C005",
        "Trading days ≥ 20",
        "paper_trading",
        "high",
        "Number of return/trading days (equity_curve_daily / risk_metrics) must be ≥ 20.",
    ),
    # ── adapters ───────────────────────────────────────────────────────────────
    Criterion(
        "C006",
        "≥ 2 adapters return APY > 0",
        "adapters",
        "high",
        "At least 2 adapters in adapter_orchestrator_status.json report apy_pct > 0.",
    ),
    Criterion(
        "C007",
        "Orchestrator ran ≥ 1 time",
        "adapters",
        "medium",
        "data/orchestrator_runs.json exists and contains at least one run.",
    ),
    Criterion(
        "C008",
        "Overall health grade ≠ F",
        "adapters",
        "blocker",
        "overall_health.grade from the adapter orchestrator must not be 'F'.",
    ),
    # ── risk ───────────────────────────────────────────────────────────────────
    Criterion(
        "C009",
        "VaR95 computed",
        "risk",
        "high",
        "data/return_distribution.json exists and exposes a 5th-percentile (VaR95) figure.",
    ),
    Criterion(
        "C010",
        "No current drawdown > 10%",
        "risk",
        "blocker",
        "current_drawdown_pct from drawdown_analysis.json must be within 10%.",
    ),
    # ── infrastructure ─────────────────────────────────────────────────────────
    Criterion(
        "C011",
        "push_to_github.py present",
        "infrastructure",
        "low",
        "Repo sync entrypoint push_to_github.py must exist at project root.",
    ),
    Criterion(
        "C012",
        "auto_push.py present (launchd autopush)",
        "infrastructure",
        "low",
        "auto_push.py must exist (launchd auto-push wiring).",
    ),
    Criterion(
        "C013",
        "sprint_completed ≥ v3.80",
        "infrastructure",
        "medium",
        "KANBAN.json sprint_completed must be ≥ v3.80 (sufficient dev progress).",
    ),
]

# Fast lookup by id.
CRITERIA_BY_ID: dict[str, Criterion] = {c.id: c for c in CRITERIA}


def all_criteria() -> list[Criterion]:
    """Return the full criteria catalogue (stable order)."""
    return list(CRITERIA)


def get_criterion(criterion_id: str) -> Criterion:
    """Return a single criterion by id (raises KeyError if unknown)."""
    return CRITERIA_BY_ID[criterion_id]
