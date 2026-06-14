"""
alert_rules.py — SPA-V390 deterministic alert rules.

Reads existing data/*.json artefacts and emits a list of Alert objects.
Pure stdlib, read-only — never imports execution/, feed_health/ or risk agents.

Rules (deterministic, no LLM):
  * CRITICAL : any blocker-weight criterion is FAIL in golive_readiness.json
  * WARNING  : overall health grade < B in adapter_orchestrator_status.json
  * WARNING  : Sharpe < -3.0 (parsed from golive_readiness.json criteria)
  * WARNING  : portfolio drift_score > 0.15 in portfolio_state.json (if present)
  * INFO     : all blocker criteria PASS (go-live approaching)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .alert_config import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING

# Health grades worse than this rank trigger a WARNING.
_GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
_MIN_HEALTHY_GRADE = "B"

SHARPE_WARN_THRESHOLD = -3.0
DRIFT_WARN_THRESHOLD = 0.15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path) -> Optional[object]:
    """Load JSON from path; return None on any failure (missing/corrupt)."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@dataclass
class Alert:
    severity: str
    title: str
    body: str
    timestamp: str = field(default_factory=_now_iso)
    source: str = "alert_rules"

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "title": self.title,
            "body": self.body,
            "timestamp": self.timestamp,
            "source": self.source,
        }


# ---------------------------------------------------------------------------- #
# Individual rule helpers
# ---------------------------------------------------------------------------- #
def _grade_rank(grade: Optional[str]) -> Optional[int]:
    if not grade:
        return None
    return _GRADE_RANK.get(str(grade).strip().upper())


def _extract_grade(orchestrator: dict) -> Optional[str]:
    """Pull overall health grade from either summary or overall_health block."""
    if not isinstance(orchestrator, dict):
        return None
    oh = orchestrator.get("overall_health")
    if isinstance(oh, dict) and oh.get("grade"):
        return oh["grade"]
    summary = orchestrator.get("summary")
    if isinstance(summary, dict) and summary.get("grade"):
        return summary["grade"]
    return orchestrator.get("grade")


_SHARPE_RE = re.compile(r"Sharpe\s*[=:]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def _extract_sharpe(golive: dict) -> Optional[float]:
    """
    Find a Sharpe value. Prefer a numeric ``sharpe``/``sharpe_ratio`` field on
    any criterion; otherwise parse it from a criterion's ``detail`` string.
    """
    if not isinstance(golive, dict):
        return None
    criteria = golive.get("criteria") or []
    for crit in criteria:
        if not isinstance(crit, dict):
            continue
        for key in ("sharpe", "sharpe_ratio", "score"):
            val = crit.get(key)
            if isinstance(val, (int, float)) and "sharpe" in str(
                crit.get("name", "")
            ).lower():
                return float(val)
    # Fallback: parse from detail / name text.
    for crit in criteria:
        if not isinstance(crit, dict):
            continue
        text = f"{crit.get('detail', '')} {crit.get('name', '')}"
        m = _SHARPE_RE.search(text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def _extract_drift(portfolio: dict) -> Optional[float]:
    """
    Extract a portfolio drift score. Prefer an explicit field; otherwise derive
    the max per-position |actual_weight - target_weight| from positions.
    """
    if not isinstance(portfolio, dict):
        return None
    for key in ("drift_score", "portfolio_drift_score", "total_drift"):
        val = portfolio.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    positions = portfolio.get("positions")
    if isinstance(positions, list) and positions:
        drifts = []
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            aw = pos.get("actual_weight")
            tw = pos.get("target_weight")
            if isinstance(aw, (int, float)) and isinstance(tw, (int, float)):
                drifts.append(abs(aw - tw))
        if drifts:
            return max(drifts)
    return None


def _blocker_criteria(golive: dict) -> List[dict]:
    if not isinstance(golive, dict):
        return []
    out = []
    for crit in golive.get("criteria") or []:
        if isinstance(crit, dict) and str(crit.get("weight", "")).lower() == "blocker":
            out.append(crit)
    return out


# ---------------------------------------------------------------------------- #
# Public entry point
# ---------------------------------------------------------------------------- #
def check_alert_conditions(
    golive_path,
    orchestrator_path,
    portfolio_path,
) -> List[Alert]:
    """
    Evaluate all deterministic rules against the three data files and return a
    severity-ordered (CRITICAL → WARNING → INFO) list of Alert objects.
    """
    golive = _load_json(golive_path) or {}
    orchestrator = _load_json(orchestrator_path) or {}
    portfolio = _load_json(portfolio_path)  # may be None if file absent

    alerts: List[Alert] = []

    # --- CRITICAL: blocker criterion FAIL ---------------------------------- #
    blockers = _blocker_criteria(golive)
    failed_blockers = [
        c for c in blockers if str(c.get("status", "")).upper() == "FAIL"
    ]
    for crit in failed_blockers:
        alerts.append(
            Alert(
                severity=SEVERITY_CRITICAL,
                title=f"Go-live blocker FAIL: {crit.get('id', '?')} "
                f"{crit.get('name', '')}".strip(),
                body=(
                    f"Blocker criterion {crit.get('id', '?')} "
                    f"({crit.get('name', '?')}) is FAIL. "
                    f"Detail: {crit.get('detail', 'n/a')}. "
                    "Go-live is blocked until this clears."
                ),
            )
        )

    # --- WARNING: health grade < B ----------------------------------------- #
    grade = _extract_grade(orchestrator)
    rank = _grade_rank(grade)
    if rank is not None and rank < _GRADE_RANK[_MIN_HEALTHY_GRADE]:
        alerts.append(
            Alert(
                severity=SEVERITY_WARNING,
                title=f"Adapter health grade degraded: {grade}",
                body=(
                    f"Overall adapter orchestrator health grade is "
                    f"'{grade}' (below '{_MIN_HEALTHY_GRADE}'). "
                    "Investigate adapter status before relying on APY feeds."
                ),
            )
        )

    # --- WARNING: Sharpe < -3.0 -------------------------------------------- #
    sharpe = _extract_sharpe(golive)
    if sharpe is not None and sharpe < SHARPE_WARN_THRESHOLD:
        alerts.append(
            Alert(
                severity=SEVERITY_WARNING,
                title=f"Strategy Sharpe very negative: {sharpe:.2f}",
                body=(
                    f"Backtest/paper Sharpe ratio is {sharpe:.2f} "
                    f"(< {SHARPE_WARN_THRESHOLD}). Strategy risk-adjusted "
                    "performance needs review."
                ),
            )
        )

    # --- WARNING: portfolio drift > 0.15 (only if file present) ------------ #
    if portfolio is not None:
        drift = _extract_drift(portfolio)
        if drift is not None and drift > DRIFT_WARN_THRESHOLD:
            alerts.append(
                Alert(
                    severity=SEVERITY_WARNING,
                    title=f"Portfolio drift high: {drift:.3f}",
                    body=(
                        f"Portfolio drift_score {drift:.3f} exceeds "
                        f"{DRIFT_WARN_THRESHOLD}. Rebalancing toward target "
                        "weights is advised."
                    ),
                )
            )

    # --- INFO: all blockers PASS ------------------------------------------- #
    if blockers and not failed_blockers:
        alerts.append(
            Alert(
                severity=SEVERITY_INFO,
                title="All go-live blockers PASS",
                body=(
                    f"All {len(blockers)} blocker criteria are PASS. "
                    "Go-live is approaching — review remaining warnings."
                ),
            )
        )

    # Severity-ordered: CRITICAL first.
    from .alert_config import SEVERITY_RANK

    alerts.sort(key=lambda a: SEVERITY_RANK.get(a.severity, 0), reverse=True)
    return alerts
