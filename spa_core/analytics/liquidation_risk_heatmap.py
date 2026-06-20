"""
MP-768: LiquidationRiskHeatmap
================================
Advisory / read-only analytics module.

Maps liquidation risk across portfolio positions using price-drop scenarios.
Computes per-position health factor and classifies risk level as
SAFE / WARNING / DANGER / CRITICAL.

Portfolio-level aggregation: portfolio_risk_score (0–100) and count of
positions at risk.

Design constraints
------------------
* Pure stdlib — no external dependencies.
* Advisory only — never modifies risk/, execution/, allocator/, cycle_runner.
* Atomic writes: tmp + os.replace.
* Ring-buffer log capped at 100 entries: data/liquidation_risk_heatmap_log.json
* Deterministic: identical input → identical output.
* NOT imported by risk / execution / monitoring / allocator / cycle_runner.

Risk classification
-------------------
health_factor = (collateral_usd * liquidation_threshold_pct) / debt_usd

    health_factor >= 2.0        → SAFE
    1.25 <= health_factor < 2.0 → WARNING
    1.0  <= health_factor < 1.25 → DANGER
    health_factor  < 1.0        → CRITICAL  (already under water)
    debt_usd == 0               → SAFE (infinite health factor)

liquidation_price_drop_pct = (1 - 1/(health_factor)) * 100  [%]
    i.e. how far collateral price must fall to trigger liquidation.
    For debt_usd == 0: returns 100.0 (no liquidation possible).
    For CRITICAL positions: returns 0.0 (already liquidatable).

portfolio_risk_score = weighted average of per-position risk weights,
    scaled to 0–100:
        SAFE     → 0
        WARNING  → 30
        DANGER   → 70
        CRITICAL → 100
    Weight = collateral_usd for each position.
    Empty portfolio → 0.

CLI
---
python3 -m spa_core.analytics.liquidation_risk_heatmap --check
python3 -m spa_core.analytics.liquidation_risk_heatmap --run
python3 -m spa_core.analytics.liquidation_risk_heatmap --data-dir PATH

MP-768.
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILE = "liquidation_risk_heatmap_log.json"
RING_BUFFER_CAP = 100

RISK_SAFE = "SAFE"
RISK_WARNING = "WARNING"
RISK_DANGER = "DANGER"
RISK_CRITICAL = "CRITICAL"

_RISK_WEIGHTS: Dict[str, float] = {
    RISK_SAFE: 0.0,
    RISK_WARNING: 30.0,
    RISK_DANGER: 70.0,
    RISK_CRITICAL: 100.0,
}

_ADVISORY = (
    "LiquidationRiskHeatmap is advisory only. "
    "Not financial advice. Read-only analytics module."
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def compute_health_factor(
    collateral_usd: float,
    debt_usd: float,
    liquidation_threshold_pct: float,
) -> float:
    """Return health_factor = (collateral * threshold) / debt.

    Returns math.inf when debt_usd == 0 (no leverage, cannot be liquidated).
    Returns 0.0 when collateral_usd == 0 and debt_usd > 0 (fully underwater).
    """
    if debt_usd == 0.0:
        return math.inf
    if collateral_usd <= 0.0:
        return 0.0
    # liquidation_threshold_pct is expressed as a fraction in [0, 1]
    return (collateral_usd * liquidation_threshold_pct) / debt_usd


def classify_risk(health_factor: float) -> str:
    """Map health_factor → risk level string."""
    if math.isinf(health_factor) or health_factor >= 2.0:
        return RISK_SAFE
    if health_factor >= 1.25:
        return RISK_WARNING
    if health_factor >= 1.0:
        return RISK_DANGER
    return RISK_CRITICAL


def compute_liquidation_price_drop_pct(health_factor: float) -> float:
    """Percentage price drop in collateral needed to trigger liquidation.

    Derivation:
        At liquidation: collateral * (1 - drop) * threshold = debt
        health_factor = collateral * threshold / debt
        So: drop = 1 - 1/health_factor

    Returns 100.0 for infinite HF (no liquidation possible).
    Returns 0.0 for HF <= 0 or HF < 1 (already liquidatable).
    """
    if math.isinf(health_factor):
        return 100.0
    if health_factor <= 0.0:
        return 0.0
    if health_factor < 1.0:
        # Already liquidatable → 0% further drop needed
        return 0.0
    return (1.0 - 1.0 / health_factor) * 100.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PositionRisk:
    protocol: str
    collateral_usd: float
    debt_usd: float
    liquidation_threshold_pct: float

    health_factor: float          # math.inf serialised as None in JSON
    liquidation_price_drop_pct: float
    risk_level: str               # SAFE / WARNING / DANGER / CRITICAL

    def to_dict(self) -> dict:
        hf = None if math.isinf(self.health_factor) else round(self.health_factor, 6)
        return {
            "protocol": self.protocol,
            "collateral_usd": round(self.collateral_usd, 4),
            "debt_usd": round(self.debt_usd, 4),
            "liquidation_threshold_pct": round(self.liquidation_threshold_pct, 6),
            "health_factor": hf,
            "liquidation_price_drop_pct": round(self.liquidation_price_drop_pct, 4),
            "risk_level": self.risk_level,
        }


@dataclass
class HeatmapResult:
    positions: List[PositionRisk]
    portfolio_risk_score: float        # 0–100
    positions_at_risk: int             # WARNING + DANGER + CRITICAL count
    critical_count: int
    danger_count: int
    warning_count: int
    safe_count: int
    advisory: str
    computed_at: str                   # ISO-8601 UTC

    def to_dict(self) -> dict:
        return {
            "computed_at": self.computed_at,
            "portfolio_risk_score": round(self.portfolio_risk_score, 4),
            "positions_at_risk": self.positions_at_risk,
            "critical_count": self.critical_count,
            "danger_count": self.danger_count,
            "warning_count": self.warning_count,
            "safe_count": self.safe_count,
            "risk_heatmap": [p.to_dict() for p in self.positions],
            "advisory": self.advisory,
        }


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class LiquidationRiskHeatmap(BaseAnalytics):
    """Computes liquidation risk heatmap for a list of DeFi positions.

    Usage::

        lrh = LiquidationRiskHeatmap(data_dir="/abs/path/to/data")
        positions = [
            {"protocol": "Aave V3", "collateral_usd": 10000,
             "debt_usd": 5000, "liquidation_threshold_pct": 0.825},
        ]
        result = lrh.compute_heatmap(positions)
        score  = lrh.get_portfolio_risk_score()
        at_risk = lrh.get_at_risk_positions()
        lrh.save(result)
    """

    OUTPUT_PATH = "data/liquidation_risk_heatmap_log.json"

    def __init__(self, data_dir: Optional[str] = None) -> None:
        super().__init__()
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._log_path = self._data_dir / _LOG_FILE
        self._last_result: Optional[HeatmapResult] = None

    def to_dict(self) -> dict:
        """Returns last heatmap result as JSON-serializable dict."""
        return self._last_result.to_dict() if self._last_result else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_heatmap(
        self,
        positions: Sequence[dict],
    ) -> HeatmapResult:
        """Compute risk heatmap for *positions*.

        Each position dict must contain:
            protocol               (str)
            collateral_usd         (float)
            debt_usd               (float)
            liquidation_threshold_pct  (float, 0–1 range)
        """
        position_risks: List[PositionRisk] = []

        for pos in positions:
            protocol = str(pos.get("protocol", "unknown"))
            collateral = float(pos.get("collateral_usd", 0.0))
            debt = float(pos.get("debt_usd", 0.0))
            threshold = float(pos.get("liquidation_threshold_pct", 0.8))

            hf = compute_health_factor(collateral, debt, threshold)
            level = classify_risk(hf)
            drop_pct = compute_liquidation_price_drop_pct(hf)

            position_risks.append(
                PositionRisk(
                    protocol=protocol,
                    collateral_usd=collateral,
                    debt_usd=debt,
                    liquidation_threshold_pct=threshold,
                    health_factor=hf,
                    liquidation_price_drop_pct=drop_pct,
                    risk_level=level,
                )
            )

        portfolio_score = self._compute_portfolio_risk_score(position_risks)
        at_risk = sum(
            1 for p in position_risks
            if p.risk_level in (RISK_WARNING, RISK_DANGER, RISK_CRITICAL)
        )
        critical = sum(1 for p in position_risks if p.risk_level == RISK_CRITICAL)
        danger = sum(1 for p in position_risks if p.risk_level == RISK_DANGER)
        warning = sum(1 for p in position_risks if p.risk_level == RISK_WARNING)
        safe = sum(1 for p in position_risks if p.risk_level == RISK_SAFE)

        result = HeatmapResult(
            positions=position_risks,
            portfolio_risk_score=portfolio_score,
            positions_at_risk=at_risk,
            critical_count=critical,
            danger_count=danger,
            warning_count=warning,
            safe_count=safe,
            advisory=_ADVISORY,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._last_result = result
        return result

    def get_portfolio_risk_score(self) -> float:
        """Return portfolio_risk_score from the last compute_heatmap call.

        Returns 0.0 if compute_heatmap has not been called yet.
        """
        if self._last_result is None:
            return 0.0
        return self._last_result.portfolio_risk_score

    def get_at_risk_positions(self) -> List[PositionRisk]:
        """Return positions classified as WARNING, DANGER, or CRITICAL."""
        if self._last_result is None:
            return []
        return [
            p for p in self._last_result.positions
            if p.risk_level in (RISK_WARNING, RISK_DANGER, RISK_CRITICAL)
        ]

    def save(self, result: HeatmapResult) -> str:
        """Append result to ring-buffer log (cap 100). Atomic write.

        Returns the absolute path of the log file.
        """
        log_path = str(self._log_path)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Load existing log
        existing: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        # Append new entry
        existing.append(result.to_dict())

        # Trim to ring buffer cap
        if len(existing) > RING_BUFFER_CAP:
            existing = existing[-RING_BUFFER_CAP:]

        # Atomic write
        atomic_save(existing, str(log_path))
        return log_path

    def load_history(self) -> List[dict]:
        """Load the ring-buffer log from disk. Returns empty list on error."""
        log_path = str(self._log_path)
        if not os.path.exists(log_path):
            return []
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_portfolio_risk_score(
        position_risks: List[PositionRisk],
    ) -> float:
        """Weighted-average risk score across positions (weight = collateral_usd).

        Returns 0.0 for an empty portfolio or zero total collateral.
        """
        if not position_risks:
            return 0.0

        total_weight = sum(p.collateral_usd for p in position_risks)
        if total_weight <= 0.0:
            # Equal-weight fallback
            scores = [_RISK_WEIGHTS[p.risk_level] for p in position_risks]
            return sum(scores) / len(scores)

        weighted_sum = sum(
            _RISK_WEIGHTS[p.risk_level] * p.collateral_usd
            for p in position_risks
        )
        return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# Module-level convenience functions (for tests & external callers)
# ---------------------------------------------------------------------------

def compute_heatmap(
    positions: Sequence[dict],
    data_dir: Optional[str] = None,
) -> HeatmapResult:
    """Convenience wrapper: create engine, compute, return result."""
    engine = LiquidationRiskHeatmap(data_dir=data_dir)
    return engine.compute_heatmap(positions)


def get_portfolio_risk_score(
    positions: Sequence[dict],
    data_dir: Optional[str] = None,
) -> float:
    """Convenience wrapper: compute heatmap, return portfolio risk score."""
    engine = LiquidationRiskHeatmap(data_dir=data_dir)
    engine.compute_heatmap(positions)
    return engine.get_portfolio_risk_score()


def get_at_risk_positions(
    positions: Sequence[dict],
    data_dir: Optional[str] = None,
) -> List[PositionRisk]:
    """Convenience wrapper: compute heatmap, return at-risk positions."""
    engine = LiquidationRiskHeatmap(data_dir=data_dir)
    engine.compute_heatmap(positions)
    return engine.get_at_risk_positions()


def save_results(
    result: HeatmapResult,
    data_dir: Optional[str] = None,
) -> str:
    """Convenience wrapper: save result to ring-buffer log."""
    engine = LiquidationRiskHeatmap(data_dir=data_dir)
    return engine.save(result)


def load_history(data_dir: Optional[str] = None) -> List[dict]:
    """Convenience wrapper: load ring-buffer log."""
    engine = LiquidationRiskHeatmap(data_dir=data_dir)
    return engine.load_history()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_sample_positions() -> List[dict]:
    """Return sample positions for CLI demo mode."""
    return [
        {
            "protocol": "Aave V3 (Ethereum)",
            "collateral_usd": 50_000.0,
            "debt_usd": 20_000.0,
            "liquidation_threshold_pct": 0.825,
        },
        {
            "protocol": "Compound V3",
            "collateral_usd": 30_000.0,
            "debt_usd": 25_000.0,
            "liquidation_threshold_pct": 0.8,
        },
        {
            "protocol": "Morpho Steakhouse",
            "collateral_usd": 15_000.0,
            "debt_usd": 14_000.0,
            "liquidation_threshold_pct": 0.85,
        },
        {
            "protocol": "Euler V2",
            "collateral_usd": 5_000.0,
            "debt_usd": 0.0,
            "liquidation_threshold_pct": 0.8,
        },
    ]


def main(argv: Optional[List[str]] = None) -> int:  # noqa: C901
    argv = argv or sys.argv[1:]

    run_mode = False
    data_dir: Optional[str] = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--run":
            run_mode = True
        elif arg == "--check":
            run_mode = False
        elif arg == "--data-dir" and i + 1 < len(argv):
            i += 1
            data_dir = argv[i]
        i += 1

    positions = _build_sample_positions()
    engine = LiquidationRiskHeatmap(data_dir=data_dir)
    result = engine.compute_heatmap(positions)

    # Print summary
    print("=" * 60)
    print("MP-768: LiquidationRiskHeatmap")
    print("=" * 60)
    print(f"Portfolio Risk Score : {result.portfolio_risk_score:.2f}/100")
    print(f"Positions At Risk    : {result.positions_at_risk}")
    print(f"  CRITICAL           : {result.critical_count}")
    print(f"  DANGER             : {result.danger_count}")
    print(f"  WARNING            : {result.warning_count}")
    print(f"  SAFE               : {result.safe_count}")
    print()
    print(f"{'Protocol':<30} {'HF':>8} {'Drop%':>8} {'Level'}")
    print("-" * 60)
    for pos in result.positions:
        hf_str = (
            "∞" if math.isinf(pos.health_factor)
            else f"{pos.health_factor:.3f}"
        )
        print(
            f"{pos.protocol:<30} {hf_str:>8} "
            f"{pos.liquidation_price_drop_pct:>7.2f}% "
            f"{pos.risk_level}"
        )

    if run_mode:
        path = engine.save(result)
        print(f"\n✅ Saved → {path}")
    else:
        print("\n(dry-run — use --run to write output)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
