"""
MP-1114 — DeFiProtocolYieldSourceDiversificationScorer
======================================================
Scores a portfolio's yield-source diversification across protocol, chain, and
yield-type dimensions. Concentrated yield = systemic risk; good diversification
= resilience.

Pure Python stdlib only. Atomic JSON log writes (tmp + os.replace).
Log file: data/yield_source_diversification_log.json (ring-buffer, cap 100).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH_DEFAULT = "data/yield_source_diversification_log.json"
LOG_CAP = 100

VALID_YIELD_TYPES = {"lending", "amm", "staking", "farming", "cdp", "restaking"}

# HHI thresholds (0–10 000 scale)
_LABEL_THRESHOLDS = [
    (1000, "WELL_DIVERSIFIED"),
    (2000, "GOOD_DIVERSIFICATION"),
    (4000, "MODERATE_CONCENTRATION"),
    (7000, "CONCENTRATED"),
    (float("inf"), "SINGLE_POINT_OF_FAILURE"),
]


# ---------------------------------------------------------------------------
# Public scorer
# ---------------------------------------------------------------------------
class DeFiProtocolYieldSourceDiversificationScorer:
    """
    Score a portfolio's yield-source diversification.

    Parameters
    ----------
    log_path : str
        Path to the JSON ring-buffer log file.
    """

    def __init__(self, log_path: str = LOG_PATH_DEFAULT) -> None:
        self.log_path = log_path

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------
    def score(
        self,
        positions: List[dict],
        protocol_name: Optional[str] = None,
        *,
        write_log: bool = True,
    ) -> dict:
        """
        Compute diversification metrics for *positions*.

        Each position dict must contain:
            protocol   : str
            chain      : str
            yield_type : str  (one of VALID_YIELD_TYPES)
            value_usd  : float
            apy_pct    : float

        Returns a result dict with all required output fields.
        """
        if not positions:
            return self._empty_result(protocol_name)

        positions = [self._validate_position(p) for p in positions]

        total_value = sum(p["value_usd"] for p in positions)
        if total_value <= 0:
            return self._empty_result(protocol_name)

        protocol_hhi = self._hhi_by(positions, total_value, "protocol")
        chain_hhi = self._hhi_by(positions, total_value, "chain")
        yield_type_hhi = self._hhi_by(positions, total_value, "yield_type")
        weighted_avg_apy = self._weighted_avg_apy(positions, total_value)
        largest_pct = self._largest_single_exposure_pct(positions, total_value)
        div_score = self._diversification_score(
            protocol_hhi, chain_hhi, yield_type_hhi
        )
        div_label = self._diversification_label(protocol_hhi)

        result = {
            "module": "MP-1114",
            "protocol_name": protocol_name or "",
            "total_value_usd": round(total_value, 6),
            "protocol_hhi": round(protocol_hhi, 4),
            "chain_hhi": round(chain_hhi, 4),
            "yield_type_hhi": round(yield_type_hhi, 4),
            "weighted_avg_apy_pct": round(weighted_avg_apy, 6),
            "diversification_score": div_score,
            "largest_single_exposure_pct": round(largest_pct, 6),
            "diversification_label": div_label,
            "position_count": len(positions),
            "timestamp": time.time(),
        }

        if write_log:
            self._append_log(result)

        return result

    # ------------------------------------------------------------------
    # HHI helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _hhi_by(positions: List[dict], total: float, field: str) -> float:
        """HHI for a given grouping field (0–10 000 scale)."""
        buckets: dict = {}
        for p in positions:
            key = p[field]
            buckets[key] = buckets.get(key, 0.0) + p["value_usd"]
        hhi = sum((v / total * 100) ** 2 for v in buckets.values())
        return hhi

    # ------------------------------------------------------------------
    # Weighted APY
    # ------------------------------------------------------------------
    @staticmethod
    def _weighted_avg_apy(positions: List[dict], total: float) -> float:
        if total == 0:
            return 0.0
        return sum(p["value_usd"] * p["apy_pct"] for p in positions) / total

    # ------------------------------------------------------------------
    # Largest single exposure
    # ------------------------------------------------------------------
    @staticmethod
    def _largest_single_exposure_pct(
        positions: List[dict], total: float
    ) -> float:
        if total == 0:
            return 0.0
        return max(p["value_usd"] / total * 100 for p in positions)

    # ------------------------------------------------------------------
    # Composite diversification score (0–100)
    # ------------------------------------------------------------------
    @staticmethod
    def _diversification_score(
        protocol_hhi: float, chain_hhi: float, yield_type_hhi: float
    ) -> int:
        """
        Maps the average of the three HHIs to a 0-100 score.
        HHI = 10 000 (monopoly) → score 0; HHI = 0 → score 100.
        """
        avg_hhi = (protocol_hhi + chain_hhi + yield_type_hhi) / 3.0
        score = max(0, min(100, round(100 - avg_hhi / 100)))
        return int(score)

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------
    @staticmethod
    def _diversification_label(protocol_hhi: float) -> str:
        for threshold, label in _LABEL_THRESHOLDS:
            if protocol_hhi < threshold:
                return label
        return "SINGLE_POINT_OF_FAILURE"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_position(p: dict) -> dict:
        required = {"protocol", "chain", "yield_type", "value_usd", "apy_pct"}
        missing = required - p.keys()
        if missing:
            raise ValueError(f"Position missing fields: {missing}")
        yt = str(p["yield_type"]).lower()
        if yt not in VALID_YIELD_TYPES:
            raise ValueError(
                f"Invalid yield_type '{yt}'. Must be one of {VALID_YIELD_TYPES}"
            )
        value = float(p["value_usd"])
        if value < 0:
            raise ValueError(f"value_usd must be >= 0, got {value}")
        return {
            "protocol": str(p["protocol"]),
            "chain": str(p["chain"]),
            "yield_type": yt,
            "value_usd": value,
            "apy_pct": float(p["apy_pct"]),
        }

    # ------------------------------------------------------------------
    # Empty result (no positions / zero value)
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_result(protocol_name: Optional[str]) -> dict:
        return {
            "module": "MP-1114",
            "protocol_name": protocol_name or "",
            "total_value_usd": 0.0,
            "protocol_hhi": 0.0,
            "chain_hhi": 0.0,
            "yield_type_hhi": 0.0,
            "weighted_avg_apy_pct": 0.0,
            "diversification_score": 100,
            "largest_single_exposure_pct": 0.0,
            "diversification_label": "WELL_DIVERSIFIED",
            "position_count": 0,
            "timestamp": time.time(),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (cap 100, atomic)
    # ------------------------------------------------------------------
    def _append_log(self, entry: dict) -> None:
        entry_with_id = {**entry, "log_id": str(uuid.uuid4())}
        try:
            os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                if not isinstance(records, list):
                    records = []
            except (FileNotFoundError, json.JSONDecodeError):
                records = []

            records.append(entry_with_id)
            records = records[-LOG_CAP:]  # ring-buffer

            tmp_path = self.log_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
            os.replace(tmp_path, self.log_path)
        except Exception:
            pass  # never raise from logging


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------
def score_diversification(
    positions: List[dict],
    protocol_name: Optional[str] = None,
    log_path: str = LOG_PATH_DEFAULT,
    write_log: bool = False,
) -> dict:
    """Module-level convenience wrapper."""
    return DeFiProtocolYieldSourceDiversificationScorer(
        log_path=log_path
    ).score(positions, protocol_name, write_log=write_log)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    sample = [
        {"protocol": "Aave", "chain": "Ethereum", "yield_type": "lending", "value_usd": 40000, "apy_pct": 3.5},
        {"protocol": "Compound", "chain": "Ethereum", "yield_type": "lending", "value_usd": 30000, "apy_pct": 4.8},
        {"protocol": "Curve", "chain": "Ethereum", "yield_type": "amm", "value_usd": 20000, "apy_pct": 6.0},
        {"protocol": "Lido", "chain": "Ethereum", "yield_type": "staking", "value_usd": 10000, "apy_pct": 4.0},
    ]

    scorer = DeFiProtocolYieldSourceDiversificationScorer()
    result = scorer.score(sample, "SPA Portfolio", write_log=False)
    print(json.dumps(result, indent=2))
