#!/usr/bin/env python3
"""APY Anomaly Detector (SPA-V622 / MP-771) — read-only / advisory.

Detects abnormal APY spikes and drops across DeFi protocol adapters using the
z-score method. For each protocol, the z-score of the current APY relative to
the historical series is computed; readings beyond a configurable threshold are
flagged with a label (SPIKE / DROP / NORMAL) and a severity band (LOW / MEDIUM /
HIGH). Results are stored in a ring-buffer log capped at 100 entries.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer history capped at 100 entries in data/apy_anomaly_log.json.
* Never raises on the happy path; degenerate inputs (std_dev=0, empty history,
  single data point) degrade gracefully with explicit notes.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Z-score anomaly detection
-------------------------
  mean      = average of historical APY series
  std_dev   = population standard deviation of historical series
  z_score   = (current_apy - mean) / std_dev

  Label:
    SPIKE   z_score >  +threshold          (default threshold = 2.0)
    DROP    z_score <  -threshold
    NORMAL  |z_score| <= threshold

  Severity (applies only when label != NORMAL):
    LOW     2 <= |z_score| < 3
    MEDIUM  3 <= |z_score| < 4
    HIGH    |z_score| >= 4

  Edge cases:
    * std_dev == 0 and current_apy == mean  →  z_score = 0.0, NORMAL
    * std_dev == 0 and current_apy != mean  →  z_score = None, label = NORMAL
      (indeterminate — noted in warnings)
    * len(history) == 0                     →  z_score = None, label = NORMAL
    * len(history) == 1                     →  std_dev = 0 → as above

CLI
---
  python3 -m spa_core.analytics.apy_anomaly_detector --check   (compute + print, no write)
  python3 -m spa_core.analytics.apy_anomaly_detector --run     (+ atomic save)
  python3 -m spa_core.analytics.apy_anomaly_detector --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save
from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "apy_anomaly_log.json"
RING_BUFFER_CAP = 100
DEFAULT_THRESHOLD: float = 2.0

SCHEMA_VERSION = 1
SOURCE_NAME = "apy_anomaly_detector"
MP_TAG = "MP-771"

# Severity band boundaries
SEV_LOW_LO: float = 2.0
SEV_MEDIUM_LO: float = 3.0
SEV_HIGH_LO: float = 4.0

# Minimum sigma to treat as "non-zero" (guards constant-series float noise)
_SIGMA_EPS: float = 1e-12

log = logging.getLogger("spa.analytics.apy_anomaly_detector")

# ---------------------------------------------------------------------------
# Statistical helpers (stdlib-only)
# ---------------------------------------------------------------------------


def _mean(series: List[float]) -> Optional[float]:
    """Return arithmetic mean or None for empty series."""
    if not series:
        return None
    return sum(series) / len(series)


def _population_std(series: List[float]) -> Optional[float]:
    """Return population std-dev or None for empty series."""
    if not series:
        return None
    mu = sum(series) / len(series)
    variance = sum((x - mu) ** 2 for x in series) / len(series)
    return math.sqrt(variance)


def _compute_z_score(
    current: float,
    history: List[float],
) -> Tuple[Optional[float], Optional[float], Optional[float], List[str]]:
    """Compute z-score statistics.

    Returns
    -------
    (z_score, mean, std_dev, warnings)

    ``z_score`` is ``None`` when indeterminate (std_dev=0 and current!=mean,
    or empty history).
    """
    notes: List[str] = []

    if not history:
        notes.append("Empty history — z-score indeterminate")
        return None, None, None, notes

    mu = _mean(history)
    sigma = _population_std(history)

    if sigma is None or sigma < _SIGMA_EPS:
        if mu is not None and math.isclose(current, mu, rel_tol=1e-9, abs_tol=1e-12):
            notes.append("std_dev=0 and current==mean — z-score set to 0.0 (NORMAL)")
            return 0.0, mu, 0.0, notes
        else:
            notes.append(
                f"std_dev=0 and current ({current}) != mean ({mu}) — z-score indeterminate"
            )
            return None, mu, 0.0, notes

    z = (current - mu) / sigma
    return z, mu, sigma, notes


# ---------------------------------------------------------------------------
# Label & severity helpers
# ---------------------------------------------------------------------------


def _label(z_score: Optional[float], threshold: float) -> str:
    """Classify anomaly as SPIKE / DROP / NORMAL."""
    if z_score is None:
        return "NORMAL"
    if z_score > threshold:
        return "SPIKE"
    if z_score < -threshold:
        return "DROP"
    return "NORMAL"


def _severity(z_score: Optional[float]) -> Optional[str]:
    """Return severity band for anomalous readings, or None for NORMAL."""
    if z_score is None:
        return None
    abs_z = abs(z_score)
    if abs_z >= SEV_HIGH_LO:
        return "HIGH"
    if abs_z >= SEV_MEDIUM_LO:
        return "MEDIUM"
    if abs_z >= SEV_LOW_LO:
        return "LOW"
    return None


# ---------------------------------------------------------------------------
# Per-protocol detection
# ---------------------------------------------------------------------------


def _detect_single(
    protocol: str,
    history: List[float],
    current_apy: float,
    threshold: float = DEFAULT_THRESHOLD,
) -> Dict[str, Any]:
    """Detect anomaly for one protocol. Always returns a result dict."""
    z_score, mu, sigma, warnings = _compute_z_score(current_apy, history)
    anomaly_label = _label(z_score, threshold)
    sev = _severity(z_score) if anomaly_label != "NORMAL" else None
    is_anomaly = anomaly_label != "NORMAL"

    return {
        "protocol": str(protocol),
        "current_apy": round(float(current_apy), 8),
        "history_len": len(history),
        "mean_apy": round(float(mu), 8) if mu is not None else None,
        "std_dev_apy": round(float(sigma), 8) if sigma is not None else None,
        "z_score": round(float(z_score), 6) if z_score is not None else None,
        "threshold": round(float(threshold), 4),
        "label": anomaly_label,
        "is_anomaly": is_anomaly,
        "severity": sev,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Anomaly record for scan_all_adapters API
# ---------------------------------------------------------------------------


@dataclass
class _AnomalyRecord:
    """Lightweight anomaly result returned by scan_all_adapters()."""
    adapter_id: str
    reported_apy: float
    anomaly_type: str   # "OUTLIER" | "NEGATIVE" | "SPIKE" | "DROP"
    severity: str       # "CRITICAL" | "WARNING" | "INFO"
    message: str


# ---------------------------------------------------------------------------
# APYAnomalyDetector class
# ---------------------------------------------------------------------------


class APYAnomalyDetector(BaseAnalytics):
    OUTPUT_PATH = "data/apy_anomaly_detector.json"
    """Stateful detector that accumulates runs into a ring-buffer log.

    Usage
    -----
    ::

        detector = APYAnomalyDetector(data_dir="/path/to/data")
        result   = detector.detect(protocol_apys, current_apys, threshold=2.0)
        anomalies = detector.get_anomalies()
        summary   = detector.get_severity_summary()
    """

    def __init__(
        self,
        data_dir: Optional[Path | str] = None,
        ring_cap: int = RING_BUFFER_CAP,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._ring_cap = ring_cap
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        protocol_apys: Dict[str, List[float]],
        current_apys: Dict[str, float],
        threshold: float = DEFAULT_THRESHOLD,
    ) -> Dict[str, Any]:
        """Run anomaly detection for all protocols present in *current_apys*.

        Parameters
        ----------
        protocol_apys:
            Mapping of protocol → historical APY list (as decimals, e.g. 0.05).
            Missing protocols default to an empty history.
        current_apys:
            Mapping of protocol → current APY to evaluate.
        threshold:
            Z-score threshold for SPIKE / DROP classification (default 2.0).

        Returns
        -------
        Full result dict with per-protocol details, anomaly list, and summary.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        per_protocol: List[Dict[str, Any]] = []

        for protocol, current_apy in current_apys.items():
            history = list(protocol_apys.get(protocol, []))
            try:
                record = _detect_single(
                    protocol=protocol,
                    history=history,
                    current_apy=float(current_apy),
                    threshold=float(threshold),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Error detecting anomaly for %r: %s", protocol, exc)
                record = {
                    "protocol": protocol,
                    "current_apy": current_apy,
                    "error": str(exc),
                    "label": "NORMAL",
                    "is_anomaly": False,
                    "severity": None,
                    "warnings": [],
                }
            per_protocol.append(record)

        anomaly_list = [p for p in per_protocol if p.get("is_anomaly")]
        summary = self._build_summary(per_protocol, threshold)

        result: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "mp_tag": MP_TAG,
            "timestamp": timestamp,
            "threshold": round(float(threshold), 4),
            "protocol_count": len(per_protocol),
            "anomaly_count": len(anomaly_list),
            "per_protocol": per_protocol,
            "anomalies": anomaly_list,
            "summary": summary,
        }
        self._last_result = result
        return result

    def get_anomalies(self) -> List[Dict[str, Any]]:
        """Return anomalous protocol records from the last :meth:`detect` call.

        Returns an empty list if :meth:`detect` has not been called yet.
        """
        if self._last_result is None:
            return []
        return list(self._last_result.get("anomalies", []))

    def get_severity_summary(self) -> Dict[str, Any]:
        """Return severity counts from the last :meth:`detect` call.

        Returns
        -------
        Dict with keys: ``total``, ``SPIKE``, ``DROP``, ``NORMAL``,
        ``LOW``, ``MEDIUM``, ``HIGH``, ``by_protocol``.
        """
        if self._last_result is None:
            return {
                "total": 0,
                "SPIKE": 0,
                "DROP": 0,
                "NORMAL": 0,
                "LOW": 0,
                "MEDIUM": 0,
                "HIGH": 0,
                "by_protocol": {},
            }
        return dict(self._last_result.get("summary", {}))

    # ------------------------------------------------------------------
    # High-level convenience API (scan_all_adapters / generate_report)
    # ------------------------------------------------------------------

    # Absolute bounds for anomaly classification (no history needed).
    _MAX_APY: float = 0.50   # APY fraction > 50% → OUTLIER (CRITICAL)
    _MIN_APY: float = -0.01  # APY fraction < -1% → NEGATIVE (CRITICAL)

    def scan_all_adapters(
        self, apy_map: Dict[str, float]
    ) -> List["_AnomalyRecord"]:
        """Scan a snapshot of current APYs and return anomaly records.

        Uses absolute bounds (no historical data required):
        * APY > _MAX_APY (50%) → OUTLIER / CRITICAL
        * APY < _MIN_APY (-1%) → NEGATIVE / CRITICAL

        Parameters
        ----------
        apy_map:
            Mapping of adapter_id → current APY as a fraction (e.g. 0.05 = 5%).

        Returns
        -------
        List of :class:`_AnomalyRecord` for anomalous adapters only.
        """
        records: List[_AnomalyRecord] = []
        for adapter_id, apy in apy_map.items():
            try:
                current = float(apy)
            except (TypeError, ValueError):
                continue
            if current > self._MAX_APY:
                records.append(_AnomalyRecord(
                    adapter_id=adapter_id,
                    reported_apy=current,
                    anomaly_type="OUTLIER",
                    severity="CRITICAL",
                    message=(
                        f"APY {current:.2%} exceeds ceiling {self._MAX_APY:.0%}"
                    ),
                ))
            elif current < self._MIN_APY:
                records.append(_AnomalyRecord(
                    adapter_id=adapter_id,
                    reported_apy=current,
                    anomaly_type="NEGATIVE",
                    severity="CRITICAL",
                    message=(
                        f"APY {current:.2%} below floor {self._MIN_APY:.0%}"
                    ),
                ))
        return records

    def generate_report(self, apy_map: Dict[str, float]) -> Dict[str, Any]:
        """Generate a structured anomaly report for the given APY snapshot.

        Returns
        -------
        Dict with keys: generated_at, anomalies, critical_count,
        warning_count, info_count, clean_adapters, advisory.
        """
        from datetime import datetime, timezone
        anomalies = self.scan_all_adapters(apy_map)
        critical = [a for a in anomalies if a.severity == "CRITICAL"]
        warnings_list = [a for a in anomalies if a.severity == "WARNING"]
        info_list = [a for a in anomalies if a.severity == "INFO"]
        anomalous_ids = {a.adapter_id for a in anomalies}
        clean = [aid for aid in apy_map if aid not in anomalous_ids]

        if critical:
            advisory = (
                f"CRITICAL: {len(critical)} adapter(s) with critical APY anomaly. "
                "Manual review required before rebalancing."
            )
        elif warnings_list:
            advisory = (
                f"WARNING: {len(warnings_list)} adapter(s) with elevated APY anomaly."
            )
        else:
            advisory = "All adapters within normal APY bounds."

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "anomalies": [
                {
                    "adapter_id": a.adapter_id,
                    "reported_apy": a.reported_apy,
                    "anomaly_type": a.anomaly_type,
                    "severity": a.severity,
                    "message": a.message,
                }
                for a in anomalies
            ],
            "critical_count": len(critical),
            "warning_count": len(warnings_list),
            "info_count": len(info_list),
            "clean_adapters": clean,
            "advisory": advisory,
        }

    def save(self) -> bool:
        """Atomically append last result to the ring-buffer log file.

        Returns ``True`` on success, ``False`` on any error (never raises).
        """
        if self._last_result is None:
            log.warning("save() called before detect() — nothing to write")
            return False
        try:
            log_path = self._data_dir / LOG_FILENAME
            existing: List[Dict[str, Any]] = _load_json_list(log_path)
            existing.append(self._last_result)
            if len(existing) > self._ring_cap:
                existing = existing[-self._ring_cap:]
            _atomic_write(log_path, existing)
            log.info("apy_anomaly_log written (%d entries)", len(existing))
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("save() failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(
        per_protocol: List[Dict[str, Any]],
        threshold: float,
    ) -> Dict[str, Any]:
        """Build aggregate severity summary from per-protocol records."""
        counts: Dict[str, int] = {
            "total": len(per_protocol),
            "SPIKE": 0,
            "DROP": 0,
            "NORMAL": 0,
            "LOW": 0,
            "MEDIUM": 0,
            "HIGH": 0,
        }
        by_protocol: Dict[str, Dict[str, Any]] = {}

        for p in per_protocol:
            label = p.get("label", "NORMAL")
            counts[label] = counts.get(label, 0) + 1

            sev = p.get("severity")
            if sev in ("LOW", "MEDIUM", "HIGH"):
                counts[sev] = counts.get(sev, 0) + 1

            by_protocol[p.get("protocol", "unknown")] = {
                "label": label,
                "severity": sev,
                "z_score": p.get("z_score"),
                "is_anomaly": p.get("is_anomaly", False),
            }

        return {**counts, "by_protocol": by_protocol}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------



    def to_dict(self) -> dict:
        """Return internal state as a plain dict. LLM FORBIDDEN."""
        return getattr(self, '_data', {})

def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# Module-level functional API
# ---------------------------------------------------------------------------


def detect_anomalies(
    protocol_apys: Dict[str, List[float]],
    current_apys: Dict[str, float],
    threshold: float = DEFAULT_THRESHOLD,
) -> Dict[str, Any]:
    """Functional entry-point: detect anomalies and return result dict."""
    detector = APYAnomalyDetector()
    return detector.detect(protocol_apys, current_apys, threshold=threshold)


def write_status(
    protocol_apys: Dict[str, List[float]],
    current_apys: Dict[str, float],
    threshold: float = DEFAULT_THRESHOLD,
    data_dir: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Detect and atomically write results to the ring-buffer log."""
    detector = APYAnomalyDetector(data_dir=data_dir)
    result = detector.detect(protocol_apys, current_apys, threshold=threshold)
    detector.save()
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apy_anomaly_detector",
        description="MP-771 APY Anomaly Detector — z-score spike/drop detection",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print; do NOT write to disk (default)",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute, print, and atomically write to data/apy_anomaly_log.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override default data/ directory path",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Z-score threshold for SPIKE/DROP (default {DEFAULT_THRESHOLD})",
    )
    return parser


def _load_apy_data_from_dir(
    data_dir: Path,
) -> Tuple[Dict[str, List[float]], Dict[str, float]]:
    """Try to load historical and current APY data from data/."""
    history: Dict[str, List[float]] = {}
    current: Dict[str, float] = {}

    hist_path = data_dir / "apy_history.json"
    try:
        with open(hist_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            for proto, series in raw.get("protocol_history", raw).items():
                if isinstance(series, list):
                    history[proto] = [float(v) for v in series if v is not None]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    status_path = data_dir / "adapter_status.json"
    try:
        with open(status_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            for proto, info in raw.items():
                if isinstance(info, dict) and "apy" in info:
                    current[proto] = float(info["apy"])
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    return history, current


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry-point — exit 0 always (pure advisory)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    write_mode: bool = args.run
    threshold: float = args.threshold

    protocol_apys, current_apys = _load_apy_data_from_dir(data_dir)

    if not current_apys:
        print("[apy_anomaly_detector] No current APYs found — using demo data", file=sys.stderr)
        protocol_apys = {
            "aave_v3":     [0.030, 0.032, 0.033, 0.031, 0.034, 0.033, 0.035],
            "compound_v3": [0.045, 0.047, 0.046, 0.048, 0.047, 0.049, 0.048],
            "morpho":      [0.060, 0.062, 0.061, 0.063, 0.062, 0.061, 0.060],
        }
        current_apys = {
            "aave_v3":     0.120,   # spike
            "compound_v3": 0.048,   # normal
            "morpho":      0.005,   # drop
        }

    detector = APYAnomalyDetector(data_dir=data_dir)
    result = detector.detect(protocol_apys, current_apys, threshold=threshold)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if write_mode:
        ok = detector.save()
        if not ok:
            print("[apy_anomaly_detector] WARNING: save() failed", file=sys.stderr)
        else:
            print(
                f"[apy_anomaly_detector] Written to {data_dir / LOG_FILENAME}",
                file=sys.stderr,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
