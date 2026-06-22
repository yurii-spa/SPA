"""
MP-1054: DeFiProtocolRestakingRiskAnalyzer
------------------------------------------
Analyzes the risk profile of a single DeFi restaking protocol position.
Read-only / advisory — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer JSON log (cap 100).

Input dict keys:
  protocol_name              : str
  restaked_asset             : str   ("ETH" / "stETH" / etc.)
  avs_count                  : int   (number of Actively Validated Services)
  slashing_conditions        : list[str]
  operator_concentration_pct : float  (top-3 operators' share, 0-100)
  tvl_usd                    : float
  base_staking_apy_pct       : float
  restaking_bonus_apy_pct    : float
  smart_contract_audits      : int
  days_since_launch          : float

Output dict keys:
  protocol_name              : str   (echo)
  restaked_asset             : str   (echo)
  total_apy_pct              : float
  slashing_risk_score        : float (0-100)
  concentration_risk_score   : float (0-100)
  restaking_composite_risk   : float (0-100)
  label                      : str   one of:
                                     CONSERVATIVE_RESTAKING / BALANCED_RESTAKING /
                                     ELEVATED_RISK / HIGH_RISK / AVOID_RESTAKING
  analyzed_at                : str   (ISO-8601 UTC)
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "restaking_risk_log.json"
)
_LOG_CAP = 100

# Slashing risk weights
_AVS_MAX_SCORE = 40.0          # max points from avs_count
_AVS_SATURATION = 20           # avs_count at which we hit max
_CONDITIONS_MAX_SCORE = 30.0   # max points from slashing_conditions length
_CONDITIONS_SATURATION = 6     # len(conditions) at which we hit max
_AUDIT_MAX_REDUCTION = 20.0    # max reduction from smart_contract_audits
_AUDIT_SATURATION = 4          # audits count at which we hit max reduction
_AGE_MAX_SCORE = 10.0          # max points for brand-new protocols
_AGE_SATURATION_DAYS = 365.0   # fully mature at 1 year

# Concentration risk
_CONCENTRATION_MULTIPLIER = 1.2   # concentration_pct * multiplier → base score

# Composite weights (must sum to 1.0)
_W_SLASHING = 0.55
_W_CONCENTRATION = 0.45

# Label bands [upper_bound_exclusive, label]
_LABEL_BANDS = [
    (20.0,  "CONSERVATIVE_RESTAKING"),
    (40.0,  "BALANCED_RESTAKING"),
    (60.0,  "ELEVATED_RISK"),
    (80.0,  "HIGH_RISK"),
    (101.0, "AVOID_RESTAKING"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def _saturation_score(value: float, saturation: float, max_score: float) -> float:
    """Linear ramp from 0 to max_score as value rises from 0 to saturation."""
    if saturation <= 0:
        return max_score if value > 0 else 0.0
    return _clamp(value / saturation, 0.0, 1.0) * max_score


def _compute_slashing_risk_score(
    avs_count: int,
    slashing_conditions: list,
    smart_contract_audits: int,
    days_since_launch: float,
) -> float:
    """
    Slashing risk score 0-100.

    Components:
      avs_component        = min(avs_count / 20, 1) * 40
      conditions_component = min(len(conditions) / 6, 1) * 30
      age_component        = max(0, 1 - days_since_launch / 365) * 10
      audit_reduction      = min(audits / 4, 1) * 20
    raw = avs + conditions + age - audit_reduction
    """
    avs_component = _saturation_score(float(avs_count), _AVS_SATURATION, _AVS_MAX_SCORE)
    conditions_component = _saturation_score(
        float(len(slashing_conditions)), _CONDITIONS_SATURATION, _CONDITIONS_MAX_SCORE
    )
    age_fraction = max(0.0, 1.0 - days_since_launch / _AGE_SATURATION_DAYS)
    age_component = age_fraction * _AGE_MAX_SCORE
    audit_reduction = _saturation_score(
        float(smart_contract_audits), _AUDIT_SATURATION, _AUDIT_MAX_REDUCTION
    )
    raw = avs_component + conditions_component + age_component - audit_reduction
    return round(_clamp(raw, 0.0, 100.0), 4)


def _compute_concentration_risk_score(
    operator_concentration_pct: float,
    tvl_usd: float,
) -> float:
    """
    Concentration risk score 0-100.

    Base:    concentration_pct * 1.2 (clipped at 100)
    TVL adj: small TVL (< $10M) adds up to 5 pts; large TVL (> $500M) subtracts up to 5 pts.
    """
    base = _clamp(operator_concentration_pct * _CONCENTRATION_MULTIPLIER, 0.0, 100.0)
    # TVL adjustment: log-linear mapping
    # tvl_usd = $10M → adj = +5; tvl_usd = $500M → adj = -5
    if tvl_usd > 0:
        log_tvl = math.log10(max(tvl_usd, 1.0))
        # log10($10M)=7, log10($500M)≈8.7; centre at 8.0 (~$100M)
        tvl_adj = (8.0 - log_tvl) * 5.0 / 1.0   # ±5 per log unit around 8
        tvl_adj = _clamp(tvl_adj, -5.0, 5.0)
    else:
        tvl_adj = 5.0  # no TVL → worst case

    raw = base + tvl_adj
    return round(_clamp(raw, 0.0, 100.0), 4)


def _compute_composite_risk(
    slashing_risk_score: float,
    concentration_risk_score: float,
) -> float:
    """Weighted composite risk 0-100."""
    raw = _W_SLASHING * slashing_risk_score + _W_CONCENTRATION * concentration_risk_score
    return round(_clamp(raw, 0.0, 100.0), 4)


def _compute_label(composite_risk: float) -> str:
    """Map composite risk to label."""
    for upper, label in _LABEL_BANDS:
        if composite_risk < upper:
            return label
    return "AVOID_RESTAKING"


def _atomic_append_log(log_path: str, entry: dict, cap: int = _LOG_CAP) -> None:
    """Append *entry* to ring-buffer JSON array; atomic write via tmp+replace."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > cap:
        data = data[-cap:]

    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DeFiProtocolRestakingRiskAnalyzer:
    """
    Analyze a single DeFi restaking protocol position.

    Usage:
        analyzer = DeFiProtocolRestakingRiskAnalyzer()
        result = analyzer.analyze({
            "protocol_name": "EigenLayer",
            "restaked_asset": "stETH",
            "avs_count": 8,
            "slashing_conditions": ["double-signing", "liveness"],
            "operator_concentration_pct": 45.0,
            "tvl_usd": 8_000_000_000,
            "base_staking_apy_pct": 3.8,
            "restaking_bonus_apy_pct": 2.1,
            "smart_contract_audits": 3,
            "days_since_launch": 400,
        })
    """

    def __init__(self, log_path: str | None = None) -> None:
        self._log_path = log_path or _LOG_PATH_DEFAULT

    # ------------------------------------------------------------------
    # Core scoring helpers (exposed for unit testing)
    # ------------------------------------------------------------------

    @staticmethod
    def slashing_risk_score(
        avs_count: int,
        slashing_conditions: list,
        smart_contract_audits: int,
        days_since_launch: float,
    ) -> float:
        """Compute slashing risk score (0-100)."""
        return _compute_slashing_risk_score(
            avs_count, slashing_conditions, smart_contract_audits, days_since_launch
        )

    @staticmethod
    def concentration_risk_score(
        operator_concentration_pct: float,
        tvl_usd: float,
    ) -> float:
        """Compute concentration risk score (0-100)."""
        return _compute_concentration_risk_score(operator_concentration_pct, tvl_usd)

    @staticmethod
    def composite_risk(
        slashing_risk: float,
        concentration_risk: float,
    ) -> float:
        """Compute restaking_composite_risk (0-100)."""
        return _compute_composite_risk(slashing_risk, concentration_risk)

    @staticmethod
    def label_for(composite_risk: float) -> str:
        """Return the label for a given composite risk score."""
        return _compute_label(composite_risk)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(self, data: dict[str, Any], *, write_log: bool = True) -> dict[str, Any]:
        """
        Analyze a restaking protocol position.

        Parameters
        ----------
        data : dict
            Input dictionary with the keys documented at module level.
        write_log : bool
            If True (default) append result to the ring-buffer log file.

        Returns
        -------
        dict
            Output dictionary with scoring results.
        """
        protocol_name = str(data.get("protocol_name", "unknown"))
        restaked_asset = str(data.get("restaked_asset", "unknown"))
        avs_count = int(data.get("avs_count", 0))
        slashing_conditions = list(data.get("slashing_conditions", []))
        operator_concentration_pct = float(data.get("operator_concentration_pct", 0.0))
        tvl_usd = float(data.get("tvl_usd", 0.0))
        base_staking_apy_pct = float(data.get("base_staking_apy_pct", 0.0))
        restaking_bonus_apy_pct = float(data.get("restaking_bonus_apy_pct", 0.0))
        smart_contract_audits = int(data.get("smart_contract_audits", 0))
        days_since_launch = float(data.get("days_since_launch", 0.0))

        total_apy_pct = round(base_staking_apy_pct + restaking_bonus_apy_pct, 4)

        sr_score = _compute_slashing_risk_score(
            avs_count, slashing_conditions, smart_contract_audits, days_since_launch
        )
        cr_score = _compute_concentration_risk_score(
            operator_concentration_pct, tvl_usd
        )
        composite = _compute_composite_risk(sr_score, cr_score)
        label = _compute_label(composite)

        result: dict[str, Any] = {
            "protocol_name": protocol_name,
            "restaked_asset": restaked_asset,
            "total_apy_pct": total_apy_pct,
            "slashing_risk_score": sr_score,
            "concentration_risk_score": cr_score,
            "restaking_composite_risk": composite,
            "label": label,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        if write_log:
            _atomic_append_log(self._log_path, result)

        return result
