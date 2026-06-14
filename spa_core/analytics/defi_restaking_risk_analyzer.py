"""
MP-922 DeFiRestakingRiskAnalyzer
---------------------------------
Analyzes DeFi restaking position risks (EigenLayer and similar protocols).

Inputs per position:
  protocol, base_token, restaking_protocol, slashing_conditions (list[str]),
  operator_count, operator_concentration_hhi (0-10000), base_apy_pct,
  restaking_apy_pct, slashing_history_count, tvl_usd,
  withdrawal_delay_days, avs_count

Outputs per position:
  total_apy_pct, slashing_risk_score (0-100), concentration_risk_score (0-100),
  withdrawal_liquidity_risk (0-100), composite_risk (0-100),
  risk_label (MINIMAL/LOW/MODERATE/HIGH/CRITICAL), flags

Aggregates:
  safest_position, riskiest_position, total_restaked_usd,
  average_total_apy, critical_count

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "restaking_risk_log.json"
)
_LOG_CAP = 100

# Flag thresholds
_HHI_HIGH_CONCENTRATION_THRESHOLD = 5000   # operator HHI > 5000 → HIGH_CONCENTRATION
_FEW_OPERATORS_THRESHOLD = 10              # operator_count < 10 → FEW_OPERATORS
_HIGH_AVS_THRESHOLD = 10                   # avs_count > 10 → HIGH_AVS_EXPOSURE
_LONG_WITHDRAWAL_DAYS = 14.0               # withdrawal_delay_days > 14 → LONG_WITHDRAWAL

# Risk label bands [upper_bound_exclusive, label]
_RISK_BANDS = [
    (20.0,  "MINIMAL"),
    (40.0,  "LOW"),
    (60.0,  "MODERATE"),
    (80.0,  "HIGH"),
    (101.0, "CRITICAL"),
]

# Composite weight config (must sum to 1.0)
_W_SLASHING     = 0.45
_W_CONCENTRATION = 0.35
_W_WITHDRAWAL   = 0.20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_append_log(log_path: str, entry: dict, cap: int = _LOG_CAP) -> None:
    """Append *entry* to ring-buffer JSON array; atomic write via tmp+replace."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > cap:
        data = data[-cap:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _risk_label(composite: float) -> str:
    """Convert composite score (0-100) to risk label string."""
    for upper, label in _RISK_BANDS:
        if composite < upper:
            return label
    return "CRITICAL"


# ---------------------------------------------------------------------------
# Analyzer class
# ---------------------------------------------------------------------------

class DeFiRestakingRiskAnalyzer:
    """
    Analyzes DeFi restaking position risks.

    Usage::

        analyzer = DeFiRestakingRiskAnalyzer()
        result = analyzer.analyze(positions, config)
    """

    def __init__(
        self,
        log_path: str | None = None,
        log_cap: int = _LOG_CAP,
    ) -> None:
        self._log_path = log_path or _LOG_PATH_DEFAULT
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    # Risk scoring components (static, testable individually)
    # ------------------------------------------------------------------

    @staticmethod
    def slashing_risk_score(position: dict) -> float:
        """
        Compute slashing risk component (0-100).

        Factors:
        - slashing_history_count  → prior incidents (highest weight)
        - slashing_conditions     → number of slashing clauses defined
        - avs_count               → each AVS is an additional slashing surface
        """
        history = max(0, int(position.get("slashing_history_count", 0)))
        conditions = max(0, len(position.get("slashing_conditions", [])))
        avs = max(0, int(position.get("avs_count", 0)))

        # History: logarithmic curve (0→0, 1→~21, 2→~33, 5→~52, 10→~65)
        history_component = min(80.0, 30.0 * math.log1p(history) / math.log(2)) \
            if history > 0 else 0.0

        # Conditions: each slashing clause adds risk exposure
        conditions_component = min(40.0, conditions * 8.0)

        # AVS: more AVS = more services that can slash the operator
        avs_component = min(40.0, avs * 3.5)

        raw = (
            history_component   * 0.50
            + conditions_component * 0.30
            + avs_component        * 0.20
        )
        return min(100.0, max(0.0, raw))

    @staticmethod
    def concentration_risk_score(position: dict) -> float:
        """
        Compute operator concentration risk component (0-100).

        Factors:
        - operator_concentration_hhi (0-10000): market concentration index
        - operator_count: absolute number of operators
        """
        hhi = float(position.get("operator_concentration_hhi", 0))
        hhi = max(0.0, min(10000.0, hhi))
        op_count = max(0, int(position.get("operator_count", 0)))

        # HHI maps directly to 0-100 score
        hhi_score = hhi / 100.0  # 10000 → 100.0

        # Low operator count penalty
        if op_count == 0:
            op_score = 100.0
        elif op_count < 3:
            op_score = 90.0
        elif op_count < 5:
            op_score = 75.0
        elif op_count < 10:
            op_score = 40.0
        elif op_count < 25:
            op_score = 20.0
        elif op_count < 50:
            op_score = 10.0
        else:
            op_score = 5.0

        return min(100.0, max(0.0, hhi_score * 0.70 + op_score * 0.30))

    @staticmethod
    def withdrawal_liquidity_risk(position: dict) -> float:
        """
        Compute withdrawal / liquidity lock risk (0-100).

        Longer withdrawal delay → higher illiquidity risk.
        """
        days = max(0.0, float(position.get("withdrawal_delay_days", 0)))

        if days == 0:
            return 0.0
        elif days <= 1:
            return 5.0
        elif days <= 3:
            return 15.0
        elif days <= 7:
            return 30.0
        elif days <= 14:
            return 50.0
        elif days <= 21:
            return 65.0
        elif days <= 30:
            return 75.0
        elif days <= 90:
            return 88.0
        else:
            return 95.0

    @staticmethod
    def compute_flags(position: dict) -> list:
        """Compute warning flags for a restaking position."""
        flags: list[str] = []

        hhi = float(position.get("operator_concentration_hhi", 0))
        if hhi > _HHI_HIGH_CONCENTRATION_THRESHOLD:
            flags.append("HIGH_CONCENTRATION")

        if int(position.get("slashing_history_count", 0)) > 0:
            flags.append("SLASHING_HISTORY")

        if float(position.get("withdrawal_delay_days", 0)) > _LONG_WITHDRAWAL_DAYS:
            flags.append("LONG_WITHDRAWAL")

        if int(position.get("operator_count", 0)) < _FEW_OPERATORS_THRESHOLD:
            flags.append("FEW_OPERATORS")

        if int(position.get("avs_count", 0)) > _HIGH_AVS_THRESHOLD:
            flags.append("HIGH_AVS_EXPOSURE")

        return flags

    def _composite_risk(
        self,
        slashing: float,
        concentration: float,
        withdrawal: float,
    ) -> float:
        """Weighted composite risk (0-100)."""
        raw = (
            slashing     * _W_SLASHING
            + concentration * _W_CONCENTRATION
            + withdrawal    * _W_WITHDRAWAL
        )
        return min(100.0, max(0.0, raw))

    # ------------------------------------------------------------------
    # Per-position analysis
    # ------------------------------------------------------------------

    def _analyze_position(self, pos: dict) -> dict:
        """Analyze one position and return enriched dict."""
        slashing   = self.slashing_risk_score(pos)
        conc       = self.concentration_risk_score(pos)
        withdrawal = self.withdrawal_liquidity_risk(pos)
        composite  = self._composite_risk(slashing, conc, withdrawal)
        label      = _risk_label(composite)
        flags      = self.compute_flags(pos)

        base_apy      = max(0.0, float(pos.get("base_apy_pct", 0.0)))
        restaking_apy = max(0.0, float(pos.get("restaking_apy_pct", 0.0)))
        total_apy     = base_apy + restaking_apy

        return {
            "protocol":             pos.get("protocol", ""),
            "base_token":           pos.get("base_token", ""),
            "restaking_protocol":   pos.get("restaking_protocol", ""),
            "tvl_usd":              float(pos.get("tvl_usd", 0.0)),
            "total_apy_pct":        round(total_apy, 4),
            "slashing_risk_score":  round(slashing, 4),
            "concentration_risk_score": round(conc, 4),
            "withdrawal_liquidity_risk": round(withdrawal, 4),
            "composite_risk":       round(composite, 4),
            "risk_label":           label,
            "flags":                flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, positions: list, config: dict) -> dict:
        """
        Analyze restaking positions and return risk assessment.

        Parameters
        ----------
        positions : list[dict]
            List of restaking position dicts.
        config : dict
            Optional config:
              - log_enabled (bool, default True): write to ring-buffer log
              - log_path (str): override default log path

        Returns
        -------
        dict with keys:
          - positions: list of per-position analysis results
          - aggregates: safest_position, riskiest_position,
                        total_restaked_usd, average_total_apy, critical_count
          - timestamp: ISO-8601 UTC string
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if not positions:
            result = {
                "positions": [],
                "aggregates": {
                    "safest_position":   None,
                    "riskiest_position": None,
                    "total_restaked_usd": 0.0,
                    "average_total_apy":  0.0,
                    "critical_count":     0,
                },
                "timestamp": timestamp,
            }
            if config.get("log_enabled", True):
                self._try_log(result, config)
            return result

        analyzed = [self._analyze_position(p) for p in positions]

        total_tvl    = sum(p["tvl_usd"]        for p in analyzed)
        avg_apy      = sum(p["total_apy_pct"]  for p in analyzed) / len(analyzed)
        critical_cnt = sum(1 for p in analyzed if p["risk_label"] == "CRITICAL")

        safest   = min(analyzed, key=lambda p: p["composite_risk"])
        riskiest = max(analyzed, key=lambda p: p["composite_risk"])

        result = {
            "positions": analyzed,
            "aggregates": {
                "safest_position":    safest["protocol"],
                "riskiest_position":  riskiest["protocol"],
                "total_restaked_usd": round(total_tvl, 2),
                "average_total_apy":  round(avg_apy, 4),
                "critical_count":     critical_cnt,
            },
            "timestamp": timestamp,
        }

        if config.get("log_enabled", True):
            self._try_log(result, config)

        return result

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _try_log(self, result: dict, config: dict) -> None:
        """Attempt ring-buffer log write; silently swallow errors."""
        log_path = config.get("log_path", self._log_path)
        try:
            _atomic_append_log(log_path, result, self._log_cap)
        except Exception:
            pass  # logging is advisory — never propagate


# ---------------------------------------------------------------------------
# CLI entry point (read-only, advisory)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sample_positions = [
        {
            "protocol": "EigenLayer-ETH",
            "base_token": "stETH",
            "restaking_protocol": "EigenLayer",
            "slashing_conditions": ["operator-fault", "double-sign"],
            "operator_count": 50,
            "operator_concentration_hhi": 3200,
            "base_apy_pct": 4.5,
            "restaking_apy_pct": 3.8,
            "slashing_history_count": 0,
            "tvl_usd": 500_000_000,
            "withdrawal_delay_days": 7,
            "avs_count": 5,
        },
        {
            "protocol": "Symbiotic-wstETH",
            "base_token": "wstETH",
            "restaking_protocol": "Symbiotic",
            "slashing_conditions": ["liveness", "safety", "double-sign"],
            "operator_count": 8,
            "operator_concentration_hhi": 6200,
            "base_apy_pct": 3.8,
            "restaking_apy_pct": 5.2,
            "slashing_history_count": 1,
            "tvl_usd": 120_000_000,
            "withdrawal_delay_days": 21,
            "avs_count": 14,
        },
    ]

    analyzer = DeFiRestakingRiskAnalyzer()
    result = analyzer.analyze(sample_positions, {"log_enabled": False})
    print(json.dumps(result, indent=2))
    sys.exit(0)
