"""
MP-1061: ProtocolDeFiYieldAggregatorStrategyRiskAnalyzer
Evaluates the multi-layer risk of a DeFi yield aggregator strategy, including
protocol dependency risk, concentration, fee drag, and smart-contract complexity.

Pure stdlib, read-only / advisory, atomic ring-buffer log (cap 100).
LLM_FORBIDDEN: no AI calls in this module.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_THIS_DIR, "..", "..")
LOG_FILE = os.path.normpath(
    os.path.join(_REPO_ROOT, "data", "yield_aggregator_strategy_risk_log.json")
)
LOG_CAP = 100

# Aggregator label thresholds (applied to composite_risk — average of three risk scores)
_LABEL_THRESHOLDS = [
    (80.0, "AVOID_COMPLEXITY"),
    (62.0, "HIGH_DEPENDENCY_RISK"),
    (42.0, "MODERATE_COMPLEXITY"),
    (22.0, "SOUND_STRATEGY"),
    (0.0,  "OPTIMAL_AGGREGATION"),
]

# Complexity score points per smart_contract_layers
_LAYERS_PTS: Dict[int, float] = {
    1: 0.0,
    2: 18.0,
    3: 38.0,
    4: 58.0,
    5: 76.0,
}
_LAYERS_PTS_DEFAULT = 92.0   # 6 or more layers


class ProtocolDeFiYieldAggregatorStrategyRiskAnalyzer:
    """
    Analyse the strategy risk of a DeFi yield aggregator.

    Usage
    -----
    analyzer = ProtocolDeFiYieldAggregatorStrategyRiskAnalyzer()
    result   = analyzer.analyze(aggregator_data)

    ``aggregator_data`` keys
    ------------------------
    aggregator_name             str
    underlying_protocols        list of dicts, each:
                                  {"name": str, "allocation_pct": float,
                                   "tvl_usd": float, "audit_count": int}
    total_tvl_usd               float  – aggregator's total value locked
    strategy_apy_pct            float  – gross APY before fees
    performance_fee_pct         float  – % of profits taken as fee
    withdrawal_fee_pct          float  – one-time % fee on withdrawal
    auto_compound               bool   – strategy auto-compounds yield
    days_since_last_rebalance   float  – calendar days since last rebalance
    smart_contract_layers       int    – depth of nested smart-contract calls

    Result keys
    -----------
    aggregator_name                 str
    weighted_protocol_risk_score    float  0–100
    concentration_risk_score        float  0–100
    net_apy_after_fees_pct          float  (can be negative)
    complexity_risk_score           float  0–100
    aggregator_label                str    one of the five label constants
    _breakdown                      dict   intermediate values
    timestamp                       float  unix epoch
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, data: Dict[str, Any], *, write_log: bool = False) -> Dict[str, Any]:
        """
        Compute all scores for a single aggregator snapshot.

        Parameters
        ----------
        data       : aggregator snapshot dict (required keys in class docstring)
        write_log  : if True, append result to ring-buffer log atomically

        Returns
        -------
        dict with all result keys listed in class docstring
        """
        self._validate(data)

        name           = str(data["aggregator_name"])
        protocols: List[Dict[str, Any]] = list(data["underlying_protocols"])
        total_tvl      = float(data["total_tvl_usd"])
        gross_apy      = float(data["strategy_apy_pct"])
        perf_fee       = float(data["performance_fee_pct"])
        withdrawal_fee = float(data["withdrawal_fee_pct"])
        auto_compound  = bool(data["auto_compound"])
        days_rebal     = float(data["days_since_last_rebalance"])
        layers         = int(data["smart_contract_layers"])

        w_proto_risk  = self._weighted_protocol_risk_score(protocols)
        conc_risk     = self._concentration_risk_score(protocols)
        net_apy       = self._net_apy_after_fees(gross_apy, perf_fee, withdrawal_fee, auto_compound)
        complex_risk  = self._complexity_risk_score(layers, days_rebal, len(protocols))

        composite = (w_proto_risk + conc_risk + complex_risk) / 3.0
        composite = _clamp(composite, 0.0, 100.0)
        label = self._label(composite)

        result: Dict[str, Any] = {
            "aggregator_name":              name,
            "weighted_protocol_risk_score": round(w_proto_risk, 2),
            "concentration_risk_score":     round(conc_risk,    2),
            "net_apy_after_fees_pct":       round(net_apy,      4),
            "complexity_risk_score":        round(complex_risk, 2),
            "aggregator_label":             label,
            "_breakdown": {
                "composite_risk":    round(composite, 2),
                "protocol_count":    len(protocols),
                "gross_apy_pct":     round(gross_apy,      4),
                "perf_fee_pct":      round(perf_fee,       4),
                "withdrawal_fee_pct": round(withdrawal_fee, 4),
                "auto_compound":     auto_compound,
                "smart_contract_layers": layers,
                "days_since_last_rebalance": days_rebal,
            },
            "timestamp": time.time(),
        }

        if write_log:
            _append_log(LOG_FILE, result, LOG_CAP)

        return result

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _weighted_protocol_risk_score(self, protocols: List[Dict[str, Any]]) -> float:
        """
        Weighted average of per-protocol risk scores.

        Per-protocol risk factors
        -------------------------
        - Audit count : 0 audits → 100; each audit reduces risk by 20 pts
        - TVL         : low TVL = riskier (< $5M → +30; < $50M → +10)
        """
        if not protocols:
            return 50.0   # unknown risk if no protocols specified

        total_alloc = sum(float(p.get("allocation_pct", 0.0)) for p in protocols)
        if total_alloc <= 0:
            total_alloc = 1.0   # avoid division by zero

        weighted_sum = 0.0
        for p in protocols:
            alloc  = float(p.get("allocation_pct", 0.0))
            audits = int(p.get("audit_count", 0))
            tvl    = float(p.get("tvl_usd", 0.0))

            # Base risk from audit quality
            base = _clamp(100.0 - audits * 20.0, 0.0, 100.0)

            # TVL adjustment (smaller pools = higher risk)
            if tvl < 5_000_000:
                base = _clamp(base + 30.0, 0.0, 100.0)
            elif tvl < 50_000_000:
                base = _clamp(base + 10.0, 0.0, 100.0)

            weighted_sum += (alloc / total_alloc) * base

        return _clamp(weighted_sum, 0.0, 100.0)

    def _concentration_risk_score(self, protocols: List[Dict[str, Any]]) -> float:
        """
        HHI-based concentration risk.

        HHI = sum of (allocation_pct/100)^2.
        Ranges from 1/n (perfectly diversified) to 1 (single protocol).
        Normalise to 0–100.
        """
        if not protocols:
            return 100.0   # no diversification info = maximum uncertainty

        n = len(protocols)
        total_alloc = sum(float(p.get("allocation_pct", 0.0)) for p in protocols)
        if total_alloc <= 0:
            return 100.0

        hhi = sum((float(p.get("allocation_pct", 0.0)) / total_alloc) ** 2 for p in protocols)
        min_hhi = 1.0 / n

        # Normalise: 0 = perfectly diversified, 1 = fully concentrated
        if n == 1:
            normalised = 1.0
        else:
            normalised = _clamp(
                (hhi - min_hhi) / (1.0 - min_hhi + 1e-9), 0.0, 1.0
            )

        score = normalised * 100.0

        # Hard floor if any single protocol dominates (> 60%)
        max_alloc = max(float(p.get("allocation_pct", 0.0)) for p in protocols)
        if max_alloc / max(total_alloc, 1.0) > 0.60:
            score = max(score, 70.0)

        return _clamp(score, 0.0, 100.0)

    def _net_apy_after_fees(
        self,
        gross_apy: float,
        perf_fee: float,
        withdrawal_fee: float,
        auto_compound: bool,
    ) -> float:
        """
        Net APY after fees.

        Performance fee reduces the APY yield (applied to gains).
        Withdrawal fee is treated as an annual drag (assuming 1-year hold).
        Auto-compound adds a modest compounding bonus (~0.5% of gross APY).
        """
        # Performance fee reduces gross yield
        effective_apy = gross_apy * (1.0 - perf_fee / 100.0)

        # Withdrawal fee as one-time annual drag
        effective_apy -= withdrawal_fee

        # Compounding bonus
        if auto_compound:
            effective_apy += gross_apy * 0.005

        return effective_apy

    def _complexity_risk_score(
        self,
        layers: int,
        days_rebal: float,
        n_protocols: int,
    ) -> float:
        """
        Smart-contract complexity and staleness risk.

        Factors
        -------
        - smart_contract_layers : deeper nesting = exponentially more attack surface
        - days_since_last_rebalance : stale positions drift from target
        - n_protocols : more integrations = more dependency surface
        """
        # Base from contract layer depth
        base = _LAYERS_PTS.get(layers, _LAYERS_PTS_DEFAULT)

        # Rebalance staleness
        if days_rebal > 90:
            base = _clamp(base + 20.0, 0.0, 100.0)
        elif days_rebal > 30:
            base = _clamp(base + 10.0, 0.0, 100.0)

        # Integration breadth
        if n_protocols > 5:
            base = _clamp(base + 15.0, 0.0, 100.0)
        elif n_protocols > 3:
            base = _clamp(base + 5.0, 0.0, 100.0)

        return _clamp(base, 0.0, 100.0)

    def _label(self, composite: float) -> str:
        for threshold, label in _LABEL_THRESHOLDS:
            if composite >= threshold:
                return label
        return "OPTIMAL_AGGREGATION"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, data: Dict[str, Any]) -> None:
        required = [
            "aggregator_name", "underlying_protocols", "total_tvl_usd",
            "strategy_apy_pct", "performance_fee_pct", "withdrawal_fee_pct",
            "auto_compound", "days_since_last_rebalance", "smart_contract_layers",
        ]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing required keys: {missing}")

        if not isinstance(data["underlying_protocols"], list):
            raise TypeError("underlying_protocols must be a list")

        for i, p in enumerate(data["underlying_protocols"]):
            if not isinstance(p, dict):
                raise TypeError(f"underlying_protocols[{i}] must be a dict")
            for pk in ("name", "allocation_pct", "tvl_usd", "audit_count"):
                if pk not in p:
                    raise ValueError(
                        f"underlying_protocols[{i}] missing key: {pk!r}"
                    )
            if float(p["allocation_pct"]) < 0:
                raise ValueError(f"underlying_protocols[{i}].allocation_pct must be ≥ 0")
            if float(p["tvl_usd"]) < 0:
                raise ValueError(f"underlying_protocols[{i}].tvl_usd must be ≥ 0")
            if int(p["audit_count"]) < 0:
                raise ValueError(f"underlying_protocols[{i}].audit_count must be ≥ 0")

        if float(data["total_tvl_usd"]) < 0:
            raise ValueError("total_tvl_usd must be non-negative")
        if float(data["performance_fee_pct"]) < 0:
            raise ValueError("performance_fee_pct must be non-negative")
        if float(data["withdrawal_fee_pct"]) < 0:
            raise ValueError("withdrawal_fee_pct must be non-negative")
        if float(data["days_since_last_rebalance"]) < 0:
            raise ValueError("days_since_last_rebalance must be non-negative")
        if int(data["smart_contract_layers"]) < 1:
            raise ValueError("smart_contract_layers must be ≥ 1")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _append_log(path: str, entry: Dict[str, Any], cap: int) -> None:
    """Atomically append entry to ring-buffer JSON log."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            log: list = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]

    dir_ = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(log, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# CLI entry-point (informational only)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sample = {
        "aggregator_name": "YearnV3-USDC",
        "underlying_protocols": [
            {"name": "Aave V3",     "allocation_pct": 40.0, "tvl_usd": 10_000_000_000.0, "audit_count": 8},
            {"name": "Compound V3", "allocation_pct": 35.0, "tvl_usd":  5_000_000_000.0, "audit_count": 6},
            {"name": "Morpho Blue", "allocation_pct": 25.0, "tvl_usd":  1_000_000_000.0, "audit_count": 3},
        ],
        "total_tvl_usd":             250_000_000.0,
        "strategy_apy_pct":          8.5,
        "performance_fee_pct":       10.0,
        "withdrawal_fee_pct":        0.1,
        "auto_compound":             True,
        "days_since_last_rebalance": 14.0,
        "smart_contract_layers":     3,
    }

    analyzer = ProtocolDeFiYieldAggregatorStrategyRiskAnalyzer()
    result = analyzer.analyze(sample)
    print(json.dumps(result, indent=2))
    sys.exit(0)
