"""
MP-1086: DeFi Protocol Oracle Price Freshness Analyzer
Analyzes oracle price feed freshness and staleness risk.
Chainlink-style heartbeat + deviation threshold model.

Pure Python stdlib only. No external dependencies.
Atomic writes (tmp + os.replace). Ring-buffer log cap 100.
"""

import json
import os
import time
from typing import Any, Dict, List


class DeFiProtocolOraclePriceFreshnessAnalyzer:
    """
    Analyzes oracle price feed freshness and staleness risk using
    a Chainlink-style heartbeat + deviation threshold model.

    Labels (in priority order):
        MANIPULATED_PRICE  — deviation > 2× threshold (regardless of staleness)
        FRESH_ORACLE       — staleness_ratio < 0.5 AND deviation < threshold
        AGING_ORACLE       — staleness_ratio in [0.5, 1.0)
        STALE_ORACLE       — staleness_ratio in [1.0, 2.0)
        CRITICAL_STALE     — staleness_ratio >= 2.0

    Risk score (0 = safe, 100 = critical):
        staleness_component  0–70:  min(70, staleness_ratio × 35)
        deviation_component  0–30:  min(30, (deviation_pct / threshold) × 15)
        redundancy_penalty   0–10:  10 if num_oracles ≤ 1, 5 if == 2, else 0
    """

    LOG_FILE_NAME: str = "oracle_price_freshness_log.json"
    LOG_CAP: int = 100

    # Public label constants
    FRESH_ORACLE: str = "FRESH_ORACLE"
    AGING_ORACLE: str = "AGING_ORACLE"
    STALE_ORACLE: str = "STALE_ORACLE"
    CRITICAL_STALE: str = "CRITICAL_STALE"
    MANIPULATED_PRICE: str = "MANIPULATED_PRICE"

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.log_file = os.path.join(data_dir, self.LOG_FILE_NAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        last_update_timestamp: float,
        current_timestamp: float,
        heartbeat_seconds: int,
        deviation_threshold_pct: float,
        observed_price_usd: float,
        reference_price_usd: float,
        num_oracles: int,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Analyze oracle price freshness.

        Args:
            last_update_timestamp:  Unix timestamp of last oracle update (seconds).
            current_timestamp:      Current Unix timestamp (seconds).
            heartbeat_seconds:      Oracle heartbeat interval in seconds (e.g. 3600).
            deviation_threshold_pct: Max acceptable % deviation from reference (e.g. 0.5).
            observed_price_usd:     Price reported by the oracle under analysis.
            reference_price_usd:    Price from a secondary/reference oracle.
            num_oracles:            Number of oracle sources aggregated (redundancy).
            protocol_name:          Human-readable protocol identifier.

        Returns:
            dict with keys:
                staleness_seconds   (float)
                staleness_ratio     (float)
                price_deviation_pct (float)
                oracle_risk_score   (int, 0–100)
                oracle_label        (str)
                log_entry           (dict, suitable for ring-buffer logging)
        """
        staleness_seconds: float = float(current_timestamp - last_update_timestamp)
        staleness_ratio: float = (
            staleness_seconds / float(heartbeat_seconds)
            if heartbeat_seconds > 0
            else 0.0
        )

        price_deviation_pct: float = self._compute_deviation_pct(
            observed_price_usd, reference_price_usd
        )

        oracle_label: str = self._compute_label(
            staleness_ratio, price_deviation_pct, deviation_threshold_pct
        )
        oracle_risk_score: int = self._compute_risk_score(
            staleness_ratio, price_deviation_pct, deviation_threshold_pct, num_oracles
        )

        log_entry: Dict[str, Any] = {
            "protocol_name": protocol_name,
            "last_update_timestamp": last_update_timestamp,
            "current_timestamp": current_timestamp,
            "heartbeat_seconds": heartbeat_seconds,
            "deviation_threshold_pct": deviation_threshold_pct,
            "observed_price_usd": observed_price_usd,
            "reference_price_usd": reference_price_usd,
            "num_oracles": num_oracles,
            "staleness_seconds": staleness_seconds,
            "staleness_ratio": staleness_ratio,
            "price_deviation_pct": price_deviation_pct,
            "oracle_risk_score": oracle_risk_score,
            "oracle_label": oracle_label,
            "analyzed_at": time.time(),
        }

        return {
            "staleness_seconds": staleness_seconds,
            "staleness_ratio": staleness_ratio,
            "price_deviation_pct": price_deviation_pct,
            "oracle_risk_score": oracle_risk_score,
            "oracle_label": oracle_label,
            "log_entry": log_entry,
        }

    def log_result(self, log_entry: Dict[str, Any]) -> None:
        """
        Append a log_entry dict to the ring-buffer log file.
        Capped at LOG_CAP entries; oldest entry dropped first.
        Atomic write via tmp + os.replace.
        """
        entries: List[Dict[str, Any]] = self._read_log()
        entries.append(log_entry)
        if len(entries) > self.LOG_CAP:
            entries = entries[-self.LOG_CAP :]
        self._write_log(entries)

    # ------------------------------------------------------------------
    # Static computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_deviation_pct(
        observed_price_usd: float,
        reference_price_usd: float,
    ) -> float:
        """Absolute percentage difference between observed and reference price."""
        if reference_price_usd == 0.0:
            return 0.0
        return (
            abs(observed_price_usd - reference_price_usd)
            / abs(reference_price_usd)
            * 100.0
        )

    @staticmethod
    def _compute_label(
        staleness_ratio: float,
        price_deviation_pct: float,
        deviation_threshold_pct: float,
    ) -> str:
        """
        Determine oracle freshness label.  MANIPULATED_PRICE has highest priority.

        Priority (first match wins):
          1. deviation > 2× threshold            → MANIPULATED_PRICE
          2. ratio < 0.5 AND deviation < threshold → FRESH_ORACLE
          3. ratio < 1.0                           → AGING_ORACLE
          4. ratio < 2.0                           → STALE_ORACLE
          5. ratio >= 2.0                          → CRITICAL_STALE
        """
        if price_deviation_pct > 2.0 * deviation_threshold_pct:
            return "MANIPULATED_PRICE"
        if staleness_ratio < 0.5 and price_deviation_pct < deviation_threshold_pct:
            return "FRESH_ORACLE"
        if staleness_ratio < 1.0:
            return "AGING_ORACLE"
        if staleness_ratio < 2.0:
            return "STALE_ORACLE"
        return "CRITICAL_STALE"

    @staticmethod
    def _compute_risk_score(
        staleness_ratio: float,
        price_deviation_pct: float,
        deviation_threshold_pct: float,
        num_oracles: int,
    ) -> int:
        """
        Compute oracle risk score in range [0, 100].

        Components:
            staleness_component:  min(70, staleness_ratio × 35)       → 0–70
            deviation_component:  min(30, (dev_pct/threshold) × 15)   → 0–30
            redundancy_penalty:   10 if oracles ≤ 1, 5 if == 2, 0 if ≥ 3
        Final value = sum of components, clamped to [0, 100], rounded half-up.
        """
        staleness_component: float = min(70.0, staleness_ratio * 35.0)

        if deviation_threshold_pct > 0.0:
            dev_ratio: float = price_deviation_pct / deviation_threshold_pct
        else:
            dev_ratio = 0.0
        deviation_component: float = min(30.0, dev_ratio * 15.0)

        if num_oracles <= 1:
            redundancy_penalty: int = 10
        elif num_oracles == 2:
            redundancy_penalty = 5
        else:
            redundancy_penalty = 0

        total: float = staleness_component + deviation_component + redundancy_penalty
        # Round half-up, clamp to [0, 100]
        return min(100, max(0, int(total + 0.5)))

    # ------------------------------------------------------------------
    # Log persistence helpers
    # ------------------------------------------------------------------

    def _read_log(self) -> List[Dict[str, Any]]:
        """Read existing log file; return empty list on missing/corrupt file."""
        if not os.path.exists(self.log_file):
            return []
        try:
            with open(self.log_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError, OSError, ValueError):
            return []

    def _write_log(self, entries: List[Dict[str, Any]]) -> None:
        """Atomically write entries list to log file (tmp + os.replace)."""
        os.makedirs(self.data_dir, exist_ok=True)
        tmp_path: str = self.log_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2)
            os.replace(tmp_path, self.log_file)
        except OSError:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
