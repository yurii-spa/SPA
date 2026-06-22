"""
Performance Regression Detector (MP-635).
==========================================

Detects when performance metrics regress (worsen) over time across adapters
and strategies. Covers APY drops, Sharpe deterioration, drawdown increases,
and allocation drift from target weights.

Data output: data/regression_alerts.json  (ring-buffer 50 entries)

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic, fail-safe cleanup).
* Never raises on the happy path; missing / malformed data degrades gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Regression types
----------------
  APY_DROP           — relative APY drop exceeds WARNING or CRITICAL threshold
  SHARPE_DROP        — absolute Sharpe ratio drop exceeds threshold
  DRAWDOWN_INCREASE  — relative drawdown increase (positive = worsening)
  ALLOCATION_DRIFT   — actual allocation drifted from target by more than threshold

Severity
--------
  CRITICAL — severe regression, immediate attention required
  WARNING  — notable regression, monitor closely
  INFO     — informational (reserved for future use)

CLI
---
  python3 -m spa_core.analytics.performance_regression_detector --check
  python3 -m spa_core.analytics.performance_regression_detector --run
  python3 -m spa_core.analytics.performance_regression_detector --run --data-dir PATH
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_ALERTS_FILE = "regression_alerts.json"
_RING_BUFFER_MAX = 50

# RegressionType literals
RT_APY_DROP           = "APY_DROP"
RT_SHARPE_DROP        = "SHARPE_DROP"
RT_DRAWDOWN_INCREASE  = "DRAWDOWN_INCREASE"
RT_ALLOCATION_DRIFT   = "ALLOCATION_DRIFT"

VALID_REGRESSION_TYPES = {
    RT_APY_DROP,
    RT_SHARPE_DROP,
    RT_DRAWDOWN_INCREASE,
    RT_ALLOCATION_DRIFT,
}

# Severity literals
SEV_CRITICAL = "CRITICAL"
SEV_WARNING  = "WARNING"
SEV_INFO     = "INFO"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class RegressionAlert:
    """A single regression event detected by the detector."""
    timestamp: str               # ISO-8601 UTC
    regression_type: str         # one of VALID_REGRESSION_TYPES
    adapter_or_strategy: str     # identifier of the affected component
    previous_value: float        # baseline metric value
    current_value: float         # current (regressed) metric value
    change_pct: float            # relative or absolute change (signed)
    severity: str                # "INFO" | "WARNING" | "CRITICAL"
    details: str                 # human-readable description

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "RegressionAlert":
        return RegressionAlert(
            timestamp=d["timestamp"],
            regression_type=d["regression_type"],
            adapter_or_strategy=d["adapter_or_strategy"],
            previous_value=float(d["previous_value"]),
            current_value=float(d["current_value"]),
            change_pct=float(d["change_pct"]),
            severity=d["severity"],
            details=d["details"],
        )


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class PerformanceRegressionDetector:
    """
    Detects performance regressions in DeFi adapters and strategies.

    All detection methods return None / empty list when no regression is
    found, and a RegressionAlert (or list) when a regression crosses a
    defined threshold.
    """

    THRESHOLDS: Dict[str, float] = {
        "apy_drop_warning_pct":   15.0,   # 15% relative drop → WARNING
        "apy_drop_critical_pct":  30.0,   # 30% relative drop → CRITICAL
        "sharpe_drop_warning":     0.2,   # absolute Sharpe drop → WARNING
        "sharpe_drop_critical":    0.5,   # absolute Sharpe drop → CRITICAL
        "drawdown_increase_pct":  50.0,   # 50% relative increase → WARNING
        "drawdown_increase_critical_pct": 100.0,  # 100% relative → CRITICAL
        "allocation_drift_pct":   20.0,   # 20% relative drift → WARNING
    }

    def __init__(self, data_dir: str = "data/") -> None:
        self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_float(v, default: float = 0.0) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------
    # Detection methods
    # ------------------------------------------------------------------

    def detect_apy_regression(
        self,
        adapter_id: str,
        previous_apy: float,
        current_apy: float,
    ) -> Optional[RegressionAlert]:
        """
        Detect a relative APY drop.

        change_pct = (current_apy - previous_apy) / abs(previous_apy) * 100

        Returns a CRITICAL alert if change_pct <= -apy_drop_critical_pct,
        WARNING if change_pct <= -apy_drop_warning_pct, else None.

        Skips detection (returns None) when previous_apy == 0 to avoid
        division by zero.
        """
        prev = self._safe_float(previous_apy)
        curr = self._safe_float(current_apy)

        if abs(prev) < 1e-9:
            return None  # cannot compute relative change from zero

        change_pct = (curr - prev) / abs(prev) * 100.0

        critical_thr = -abs(self.THRESHOLDS["apy_drop_critical_pct"])
        warning_thr  = -abs(self.THRESHOLDS["apy_drop_warning_pct"])

        if change_pct <= critical_thr:
            severity = SEV_CRITICAL
        elif change_pct <= warning_thr:
            severity = SEV_WARNING
        else:
            return None

        details = (
            f"APY dropped {abs(change_pct):.1f}% relative "
            f"(from {prev:.4f}% to {curr:.4f}%) for adapter '{adapter_id}'."
        )
        return RegressionAlert(
            timestamp=self._now_iso(),
            regression_type=RT_APY_DROP,
            adapter_or_strategy=adapter_id,
            previous_value=prev,
            current_value=curr,
            change_pct=round(change_pct, 4),
            severity=severity,
            details=details,
        )

    def detect_sharpe_regression(
        self,
        strategy_id: str,
        previous_sharpe: float,
        current_sharpe: float,
    ) -> Optional[RegressionAlert]:
        """
        Detect an absolute Sharpe ratio drop.

        change = current_sharpe - previous_sharpe  (negative = worse)

        Returns CRITICAL if drop >= sharpe_drop_critical,
        WARNING if drop >= sharpe_drop_warning, else None.
        """
        prev = self._safe_float(previous_sharpe)
        curr = self._safe_float(current_sharpe)

        drop = prev - curr  # positive value means Sharpe worsened

        critical_thr = self.THRESHOLDS["sharpe_drop_critical"]
        warning_thr  = self.THRESHOLDS["sharpe_drop_warning"]

        if drop >= critical_thr:
            severity = SEV_CRITICAL
        elif drop >= warning_thr:
            severity = SEV_WARNING
        else:
            return None

        change_pct = (curr - prev) / max(abs(prev), 1e-9) * 100.0
        details = (
            f"Sharpe ratio dropped by {drop:.4f} (absolute) "
            f"(from {prev:.4f} to {curr:.4f}) for strategy '{strategy_id}'."
        )
        return RegressionAlert(
            timestamp=self._now_iso(),
            regression_type=RT_SHARPE_DROP,
            adapter_or_strategy=strategy_id,
            previous_value=prev,
            current_value=curr,
            change_pct=round(change_pct, 4),
            severity=severity,
            details=details,
        )

    def detect_drawdown_regression(
        self,
        strategy_id: str,
        previous_dd: float,
        current_dd: float,
    ) -> Optional[RegressionAlert]:
        """
        Detect a relative increase in maximum drawdown (positive values = worse).

        relative_increase = (current_dd - previous_dd) / max(previous_dd, 0.001) * 100

        Returns CRITICAL if relative_increase >= drawdown_increase_critical_pct,
        WARNING if relative_increase >= drawdown_increase_pct, else None.

        If both values are zero/negligible, returns None.
        """
        prev = self._safe_float(previous_dd)
        curr = self._safe_float(current_dd)

        denom = max(prev, 0.001)
        relative_increase = (curr - prev) / denom * 100.0

        critical_thr = self.THRESHOLDS["drawdown_increase_critical_pct"]
        warning_thr  = self.THRESHOLDS["drawdown_increase_pct"]

        if relative_increase >= critical_thr:
            severity = SEV_CRITICAL
        elif relative_increase >= warning_thr:
            severity = SEV_WARNING
        else:
            return None

        details = (
            f"Max drawdown increased {relative_increase:.1f}% relative "
            f"(from {prev:.4f} to {curr:.4f}) for strategy '{strategy_id}'."
        )
        return RegressionAlert(
            timestamp=self._now_iso(),
            regression_type=RT_DRAWDOWN_INCREASE,
            adapter_or_strategy=strategy_id,
            previous_value=prev,
            current_value=curr,
            change_pct=round(relative_increase, 4),
            severity=severity,
            details=details,
        )

    def detect_allocation_drift(
        self,
        target_weights: Dict[str, float],
        actual_weights: Dict[str, float],
    ) -> List[RegressionAlert]:
        """
        Detect allocation drift for each adapter present in target_weights.

        drift_pct = abs(actual - target) / max(target, 0.001) * 100

        Returns a WARNING alert for each adapter whose drift exceeds threshold.
        """
        alerts: List[RegressionAlert] = []
        thr = self.THRESHOLDS["allocation_drift_pct"]

        for adapter_id, target in target_weights.items():
            t = self._safe_float(target)
            a = self._safe_float(actual_weights.get(adapter_id, 0.0))
            denom = max(abs(t), 0.001)
            drift_pct = abs(a - t) / denom * 100.0

            if drift_pct >= thr:
                change_pct = (a - t) / denom * 100.0  # signed
                details = (
                    f"Allocation drift of {drift_pct:.1f}% for '{adapter_id}': "
                    f"target={t:.4f}, actual={a:.4f}."
                )
                alerts.append(RegressionAlert(
                    timestamp=self._now_iso(),
                    regression_type=RT_ALLOCATION_DRIFT,
                    adapter_or_strategy=adapter_id,
                    previous_value=t,
                    current_value=a,
                    change_pct=round(change_pct, 4),
                    severity=SEV_WARNING,
                    details=details,
                ))

        return alerts

    # ------------------------------------------------------------------
    # Scan-all orchestrator
    # ------------------------------------------------------------------

    def scan_all(
        self,
        previous_snapshot: Dict[str, dict],
        current_snapshot: Dict[str, dict],
    ) -> List[RegressionAlert]:
        """
        Run all detectors against a pair of snapshots.

        Each snapshot maps adapter_id → {apy, drawdown, weight, sharpe?}.
        Returns the combined list of all regression alerts found.

        Graceful: unknown / missing keys are skipped without raising.
        """
        alerts: List[RegressionAlert] = []

        # --- Collect target and actual weights for drift check ---
        target_weights: Dict[str, float] = {}
        actual_weights: Dict[str, float] = {}

        all_ids = set(previous_snapshot) | set(current_snapshot)

        for adapter_id in all_ids:
            prev_data = previous_snapshot.get(adapter_id) or {}
            curr_data = current_snapshot.get(adapter_id) or {}

            if not isinstance(prev_data, dict):
                prev_data = {}
            if not isinstance(curr_data, dict):
                curr_data = {}

            # APY regression
            if "apy" in prev_data and "apy" in curr_data:
                alert = self.detect_apy_regression(
                    adapter_id,
                    self._safe_float(prev_data["apy"]),
                    self._safe_float(curr_data["apy"]),
                )
                if alert:
                    alerts.append(alert)

            # Drawdown regression
            if "drawdown" in prev_data and "drawdown" in curr_data:
                alert = self.detect_drawdown_regression(
                    adapter_id,
                    self._safe_float(prev_data["drawdown"]),
                    self._safe_float(curr_data["drawdown"]),
                )
                if alert:
                    alerts.append(alert)

            # Sharpe regression
            if "sharpe" in prev_data and "sharpe" in curr_data:
                alert = self.detect_sharpe_regression(
                    adapter_id,
                    self._safe_float(prev_data["sharpe"]),
                    self._safe_float(curr_data["sharpe"]),
                )
                if alert:
                    alerts.append(alert)

            # Collect weights for drift check
            if "weight" in prev_data:
                target_weights[adapter_id] = self._safe_float(prev_data["weight"])
            if "weight" in curr_data:
                actual_weights[adapter_id] = self._safe_float(curr_data["weight"])

        # Allocation drift (only when target weights exist)
        if target_weights:
            drift_alerts = self.detect_allocation_drift(target_weights, actual_weights)
            alerts.extend(drift_alerts)

        return alerts

    # ------------------------------------------------------------------
    # Persistence (ring-buffer)
    # ------------------------------------------------------------------

    def _load_existing_alerts(self) -> List[dict]:
        """Load existing alerts from disk; return [] on any error."""
        path = self._data_dir / _ALERTS_FILE
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, OSError):
            return []

    def log_alerts(self, alerts: List[RegressionAlert]) -> None:
        """
        Append alerts to the ring-buffer on disk (max 50 entries).

        Uses atomic write (tmp + os.replace) to avoid corruption.
        No-op when alerts list is empty.
        """
        if not alerts:
            return

        existing = self._load_existing_alerts()
        new_dicts = [a.to_dict() for a in alerts]
        combined = existing + new_dicts

        # Enforce ring-buffer limit
        if len(combined) > _RING_BUFFER_MAX:
            combined = combined[-_RING_BUFFER_MAX:]

        self._data_dir.mkdir(parents=True, exist_ok=True)
        target = self._data_dir / _ALERTS_FILE
        atomic_save(combined, str(target))

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        previous_snapshot: Dict[str, dict],
        current_snapshot: Dict[str, dict],
    ) -> dict:
        """
        Run scan_all and produce a structured summary report.

        Returns a dict with:
          alerts         — list of alert dicts (serialisable)
          critical_count — number of CRITICAL alerts
          warning_count  — number of WARNING alerts
          info_count     — number of INFO alerts
          clean_count    — number of adapters/strategies with no regression
          advisory       — human-readable summary string
        """
        alerts = self.scan_all(previous_snapshot, current_snapshot)

        critical = [a for a in alerts if a.severity == SEV_CRITICAL]
        warnings  = [a for a in alerts if a.severity == SEV_WARNING]
        infos     = [a for a in alerts if a.severity == SEV_INFO]

        all_ids = set(previous_snapshot) | set(current_snapshot)
        alerted_ids = {a.adapter_or_strategy for a in alerts}
        clean_count = len(all_ids - alerted_ids)

        if critical:
            advisory = (
                f"CRITICAL: {len(critical)} critical regression(s) detected — "
                f"immediate review required. "
                f"{len(warnings)} warning(s), {clean_count} component(s) clean."
            )
        elif warnings:
            advisory = (
                f"WARNING: {len(warnings)} regression warning(s) detected. "
                f"{clean_count} component(s) performing within thresholds."
            )
        else:
            advisory = (
                f"OK: No regressions detected. "
                f"{len(all_ids)} component(s) performing within thresholds."
            )

        return {
            "generated_at": self._now_iso(),
            "alerts": [a.to_dict() for a in alerts],
            "critical_count": len(critical),
            "warning_count": len(warnings),
            "info_count": len(infos),
            "clean_count": clean_count,
            "advisory": advisory,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_sample_snapshots() -> tuple:
    """
    Build sample previous/current snapshots from live data files for
    the CLI --run mode.  Falls back to empty dicts on any error.
    """
    root = Path(__file__).resolve().parents[2]
    data_dir = root / "data"

    def _load(filename: str) -> dict:
        p = data_dir / filename
        if not p.exists():
            return {}
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}

    status = _load("paper_trading_status.json")
    positions = _load("current_positions.json")

    # Build a minimal snapshot from current_positions
    current: Dict[str, dict] = {}
    if isinstance(positions, list):
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            pid = pos.get("protocol") or pos.get("adapter_id") or pos.get("id")
            if not pid:
                continue
            current[pid] = {
                "apy": pos.get("apy", 0.0),
                "weight": pos.get("weight", pos.get("allocation_pct", 0.0)),
                "drawdown": pos.get("drawdown", 0.0),
            }
    elif isinstance(positions, dict):
        for pid, pdata in positions.items():
            if isinstance(pdata, dict):
                current[pid] = {
                    "apy": pdata.get("apy", 0.0),
                    "weight": pdata.get("weight", pdata.get("allocation_pct", 0.0)),
                    "drawdown": pdata.get("drawdown", 0.0),
                }

    # We don't have a "previous" snapshot at CLI time, so return empty previous
    return {}, current


def main(argv: Optional[list] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Performance Regression Detector (MP-635)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run detection and print report; do not write to disk.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run detection, print report, and save alerts to disk.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override path to data/ directory.",
    )
    args = parser.parse_args(argv)

    data_dir_str = args.data_dir or str(_DEFAULT_DATA_DIR)
    detector = PerformanceRegressionDetector(data_dir=data_dir_str)

    previous, current = _build_sample_snapshots()
    report = detector.generate_report(previous, current)

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.run:
        alert_objs = [RegressionAlert.from_dict(a) for a in report["alerts"]]
        detector.log_alerts(alert_objs)
        print(
            f"\n[regression_detector] Saved {len(alert_objs)} alert(s) to "
            f"{data_dir_str}/{_ALERTS_FILE}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
