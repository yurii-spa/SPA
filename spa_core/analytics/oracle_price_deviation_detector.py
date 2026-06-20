"""
MP-774: OraclePriceDeviationDetector
=====================================
Detects when on-chain oracle prices deviate significantly from reference prices.

Inputs: [{protocol, oracle_price, reference_price, max_deviation_pct}]

Computes:
  deviation_pct = abs(oracle - reference) / reference * 100

Status thresholds (relative to max_deviation_pct):
  NORMAL      < 1.5x max
  WARNING     >= 1.5x max
  CRITICAL    >= 2.0x max
  MANIPULATED >= 3.0x max

manipulation_risk_score (0-100):
  0   = normal, well within bounds
  100 = clear manipulation

Ring buffer log: data/oracle_deviation_log.json (max 100 entries, atomic write).

Pure stdlib, read-only/advisory domain, exit-0 always.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
STATUS_NORMAL: str = "NORMAL"
STATUS_WARNING: str = "WARNING"
STATUS_CRITICAL: str = "CRITICAL"
STATUS_MANIPULATED: str = "MANIPULATED"

# Multipliers that trigger each level (relative to max_deviation_pct)
_WARN_MUL: float = 1.5
_CRIT_MUL: float = 2.0
_MANIP_MUL: float = 3.0

# Ring-buffer cap
LOG_MAX_ENTRIES: int = 100

# Default log path: <project_root>/data/oracle_deviation_log.json
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_LOG_PATH: str = os.path.join(_PROJECT_ROOT, "data", "oracle_deviation_log.json")


# ---------------------------------------------------------------------------
# Pure helper functions (importable for tests)
# ---------------------------------------------------------------------------

def compute_deviation_pct(oracle_price: float, reference_price: float) -> float:
    """Return abs deviation as a percentage of reference_price.

    Returns 0.0 when reference_price == 0 to avoid ZeroDivisionError.
    """
    if reference_price == 0:
        return 0.0
    return abs(oracle_price - reference_price) / reference_price * 100.0


def compute_status(deviation_pct: float, max_deviation_pct: float) -> str:
    """Classify deviation relative to the protocol's configured maximum.

    Thresholds (checked from worst to best):
      MANIPULATED : deviation_pct >= max * 3
      CRITICAL    : deviation_pct >= max * 2
      WARNING     : deviation_pct >= max * 1.5
      NORMAL      : otherwise
    """
    if deviation_pct >= max_deviation_pct * _MANIP_MUL:
        return STATUS_MANIPULATED
    if deviation_pct >= max_deviation_pct * _CRIT_MUL:
        return STATUS_CRITICAL
    if deviation_pct >= max_deviation_pct * _WARN_MUL:
        return STATUS_WARNING
    return STATUS_NORMAL


def compute_manipulation_risk_score(deviation_pct: float, max_deviation_pct: float) -> int:
    """Return an integer risk score in [0, 100].

    Scoring bands (ratio = deviation_pct / max_deviation_pct):
      [0, 1)    NORMAL   → score in [0, 33]
      [1, 1.5)  WARNING  → score in [33, 49]
      [1.5, 2)  CRITICAL → score in [49, 74]
      [2, 3)    MANIP    → score in [74, 99]
      [3, ∞)             → 100
    """
    if max_deviation_pct <= 0:
        return 0
    ratio = deviation_pct / max_deviation_pct
    if ratio <= 0.0:
        score = 0
    elif ratio < 1.0:
        score = int(ratio * 33)
    elif ratio < 1.5:
        score = 33 + int((ratio - 1.0) / 0.5 * 16)
    elif ratio < 2.0:
        score = 49 + int((ratio - 1.5) / 0.5 * 25)
    elif ratio < 3.0:
        score = 74 + int((ratio - 2.0) / 1.0 * 25)
    else:
        score = 100
    return min(100, max(0, score))


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via tmp + os.replace."""
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    atomic_save(data, str(path))
def _load_log(path: str) -> List[Dict]:
    """Load ring-buffer list from *path*; return [] on missing/corrupt file."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class OraclePriceDeviationDetector:
    """MP-774 — detects oracle price deviation / manipulation risk.

    Usage::

        detector = OraclePriceDeviationDetector()
        results = detector.detect([
            {"protocol": "aave",     "oracle_price": 1.002, "reference_price": 1.0, "max_deviation_pct": 1.0},
            {"protocol": "compound", "oracle_price": 1.035, "reference_price": 1.0, "max_deviation_pct": 1.0},
        ])
        print(detector.get_manipulated_protocols())
        print(detector.get_portfolio_oracle_risk())
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self.log_path: str = log_path or DEFAULT_LOG_PATH
        self._results: List[Dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, oracle_data: List[Dict]) -> List[Dict]:
        """Analyse *oracle_data* and return per-protocol result list.

        Each input entry must contain:
          protocol          (str)
          oracle_price      (float)
          reference_price   (float)
          max_deviation_pct (float)

        Each result contains:
          timestamp, protocol, oracle_price, reference_price,
          max_deviation_pct, deviation_pct, status, manipulation_risk_score
        """
        ts = datetime.now(timezone.utc).isoformat()
        results: List[Dict] = []

        for entry in oracle_data:
            protocol = str(entry.get("protocol", "unknown"))
            oracle_price = float(entry.get("oracle_price", 0))
            reference_price = float(entry.get("reference_price", 0))
            max_deviation_pct = float(entry.get("max_deviation_pct", 1.0))

            deviation_pct = compute_deviation_pct(oracle_price, reference_price)
            status = compute_status(deviation_pct, max_deviation_pct)
            risk_score = compute_manipulation_risk_score(deviation_pct, max_deviation_pct)

            results.append({
                "timestamp": ts,
                "protocol": protocol,
                "oracle_price": oracle_price,
                "reference_price": reference_price,
                "max_deviation_pct": max_deviation_pct,
                "deviation_pct": round(deviation_pct, 6),
                "status": status,
                "manipulation_risk_score": risk_score,
            })

        self._results = results
        if results:
            self._append_to_log(results)
        return results

    def get_manipulated_protocols(self) -> List[str]:
        """Return protocol names whose status is MANIPULATED after last detect()."""
        return [
            r["protocol"]
            for r in self._results
            if r.get("status") == STATUS_MANIPULATED
        ]

    def get_portfolio_oracle_risk(self) -> Dict:
        """Aggregate risk across all protocols from the last detect() call.

        Returns a dict with:
          max_risk_score    (int)
          avg_risk_score    (float)
          critical_count    (int)
          manipulated_count (int)
          overall_status    (str)  — worst-case across all protocols
          protocols_at_risk (list) — WARNING, CRITICAL, or MANIPULATED
        """
        if not self._results:
            return {
                "max_risk_score": 0,
                "avg_risk_score": 0.0,
                "critical_count": 0,
                "manipulated_count": 0,
                "overall_status": STATUS_NORMAL,
                "protocols_at_risk": [],
            }

        scores = [r["manipulation_risk_score"] for r in self._results]
        statuses = [r["status"] for r in self._results]

        manipulated_count = statuses.count(STATUS_MANIPULATED)
        critical_count = statuses.count(STATUS_CRITICAL)
        warning_count = statuses.count(STATUS_WARNING)

        if manipulated_count > 0:
            overall_status = STATUS_MANIPULATED
        elif critical_count > 0:
            overall_status = STATUS_CRITICAL
        elif warning_count > 0:
            overall_status = STATUS_WARNING
        else:
            overall_status = STATUS_NORMAL

        protocols_at_risk = [
            r["protocol"]
            for r in self._results
            if r["status"] in (STATUS_WARNING, STATUS_CRITICAL, STATUS_MANIPULATED)
        ]

        return {
            "max_risk_score": max(scores),
            "avg_risk_score": round(sum(scores) / len(scores), 2),
            "critical_count": critical_count,
            "manipulated_count": manipulated_count,
            "overall_status": overall_status,
            "protocols_at_risk": protocols_at_risk,
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _append_to_log(self, results: List[Dict]) -> None:
        """Append *results* to ring-buffer log, cap at LOG_MAX_ENTRIES."""
        log = _load_log(self.log_path)
        log.extend(results)
        if len(log) > LOG_MAX_ENTRIES:
            log = log[-LOG_MAX_ENTRIES:]
        _atomic_write(self.log_path, log)
