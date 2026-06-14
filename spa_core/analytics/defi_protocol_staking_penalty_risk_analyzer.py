"""
MP-1128: DeFiProtocolStakingPenaltyRiskAnalyzer
-------------------------------------------------
Analyzes slashing and penalty risk for staking-based yield strategies.
Validators/stakers can lose principal through slashing events.
Calculates expected annual loss from slashing probability.

Read-only / advisory — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer JSON log (cap 100).

Input dict keys:
  staking_type                : str  (eth_solo_validator / eth_liquid_staking /
                                      cosmos_delegation / polkadot_nomination / other)
  slash_probability_annual_pct: float (historical slash rate per year %, e.g. 0.01)
  slash_penalty_pct           : float (% of stake lost per slash event, e.g. 1.0)
  staking_apy_pct             : float (gross staking yield %)
  position_size_usd           : float
  protocol_audited            : bool
  client_diversity_score      : int   (0-10, 10=max diversity, relevant for ETH)
  protocol_name               : str

Output dict keys:
  protocol_name               : str   (echo)
  staking_type                : str   (echo)
  expected_annual_loss_pct    : float (slash_probability_annual_pct * slash_penalty_pct / 100)
  expected_annual_loss_usd    : float (position_size_usd * expected_annual_loss_pct / 100)
  net_staking_apy_pct         : float (staking_apy_pct - expected_annual_loss_pct)
  slash_risk_score            : int   (0-100)
  risk_label                  : str   one of:
                                      NEGLIGIBLE_SLASH_RISK / LOW_SLASH_RISK /
                                      MODERATE_SLASH_RISK / HIGH_SLASH_RISK /
                                      UNACCEPTABLE_SLASH_RISK
  analyzed_at                 : str   (ISO-8601 UTC)
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "staking_penalty_risk_log.json"
)
_LOG_CAP = 100

# Probability component: saturation at 5% annual slash rate → 50 pts
_PROB_SATURATION_PCT = 5.0
_PROB_MAX_SCORE = 50.0

# Penalty component: saturation at 50% slash penalty → 30 pts
_PENALTY_SATURATION_PCT = 50.0
_PENALTY_MAX_SCORE = 30.0

# Audit reduction applied when protocol_audited=True
_AUDIT_REDUCTION = 10.0

# Client diversity reduction: score 0-10 maps to 0-10 pts reduction
_DIVERSITY_MAX_REDUCTION = 10.0

# Staking type modifier (additive, positive = riskier)
_STAKING_TYPE_MODIFIERS = {
    "eth_solo_validator": 5.0,
    "eth_liquid_staking": 0.0,
    "cosmos_delegation": 3.0,
    "polkadot_nomination": 3.0,
    "other": 0.0,
}

# Label bands: (inclusive_upper_bound, label)
_LABEL_BANDS = [
    (10,  "NEGLIGIBLE_SLASH_RISK"),
    (25,  "LOW_SLASH_RISK"),
    (50,  "MODERATE_SLASH_RISK"),
    (75,  "HIGH_SLASH_RISK"),
    (100, "UNACCEPTABLE_SLASH_RISK"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


def _compute_expected_annual_loss_pct(
    slash_probability_annual_pct: float,
    slash_penalty_pct: float,
) -> float:
    """
    Expected annual loss as % of stake.

    Formula:
        expected_loss_pct = (slash_probability_annual_pct / 100) * slash_penalty_pct

    Both inputs are percentages; dividing probability by 100 converts it to a
    fraction, which is then multiplied by the penalty percentage.
    """
    return round((slash_probability_annual_pct / 100.0) * slash_penalty_pct, 6)


def _compute_expected_annual_loss_usd(
    position_size_usd: float,
    expected_annual_loss_pct: float,
) -> float:
    """Expected annual loss in USD = position_size * loss_pct / 100."""
    return round(position_size_usd * expected_annual_loss_pct / 100.0, 4)


def _compute_net_staking_apy_pct(
    staking_apy_pct: float,
    expected_annual_loss_pct: float,
) -> float:
    """Net APY after expected slashing loss = gross_apy - expected_loss."""
    return round(staking_apy_pct - expected_annual_loss_pct, 6)


def _compute_probability_component(slash_probability_annual_pct: float) -> float:
    """
    Probability score component (0–50 pts).

    Linear ramp: 0 pts at 0% → 50 pts at 5% (saturates above 5%).
    """
    frac = _clamp(slash_probability_annual_pct / _PROB_SATURATION_PCT, 0.0, 1.0)
    return frac * _PROB_MAX_SCORE


def _compute_penalty_component(slash_penalty_pct: float) -> float:
    """
    Penalty score component (0–30 pts).

    Linear ramp: 0 pts at 0% → 30 pts at 50% (saturates above 50%).
    """
    frac = _clamp(slash_penalty_pct / _PENALTY_SATURATION_PCT, 0.0, 1.0)
    return frac * _PENALTY_MAX_SCORE


def _compute_audit_reduction(protocol_audited: bool) -> float:
    """Audit reduction: 10 pts if audited, 0 otherwise."""
    return _AUDIT_REDUCTION if protocol_audited else 0.0


def _compute_diversity_reduction(client_diversity_score: int) -> float:
    """
    Client diversity risk reduction (0–10 pts).

    Higher diversity → lower slash risk (better split across clients means
    one bug won't trigger mass slashing).
    diversity_score 10 → full 10 pt reduction; 0 → no reduction.
    """
    clamped = _clamp(float(client_diversity_score), 0.0, 10.0)
    return (clamped / 10.0) * _DIVERSITY_MAX_REDUCTION


def _compute_staking_type_modifier(staking_type: str) -> float:
    """Return additive modifier for staking type (positive = riskier)."""
    return _STAKING_TYPE_MODIFIERS.get(staking_type, 0.0)


def _compute_slash_risk_score(
    slash_probability_annual_pct: float,
    slash_penalty_pct: float,
    protocol_audited: bool,
    client_diversity_score: int,
    staking_type: str,
) -> int:
    """
    Composite slash risk score (int 0–100).

    Components:
      probability_component  = min(slash_prob_pct / 5.0, 1) * 50     [0–50]
      penalty_component      = min(slash_penalty_pct / 50.0, 1) * 30 [0–30]
      staking_type_modifier  = per-type constant                      [0–5]
      audit_reduction        = 10 if audited else 0                   [0–10]
      diversity_reduction    = (diversity_score / 10) * 10            [0–10]

    raw_score = prob + penalty + type_mod - audit_red - diversity_red
    final     = clamp(round(raw_score), 0, 100)
    """
    prob = _compute_probability_component(slash_probability_annual_pct)
    penalty = _compute_penalty_component(slash_penalty_pct)
    type_mod = _compute_staking_type_modifier(staking_type)
    audit_red = _compute_audit_reduction(protocol_audited)
    diversity_red = _compute_diversity_reduction(client_diversity_score)
    raw = prob + penalty + type_mod - audit_red - diversity_red
    return int(round(_clamp(raw, 0.0, 100.0)))


def _compute_risk_label(slash_risk_score: int) -> str:
    """Map slash_risk_score to a risk label."""
    for upper, label in _LABEL_BANDS:
        if slash_risk_score <= upper:
            return label
    return "UNACCEPTABLE_SLASH_RISK"


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

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(abs_path), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class DeFiProtocolStakingPenaltyRiskAnalyzer:
    """
    Analyzes slashing and penalty risk for staking-based yield strategies.

    Usage::

        analyzer = DeFiProtocolStakingPenaltyRiskAnalyzer()
        result = analyzer.analyze({
            "protocol_name": "Lido",
            "staking_type": "eth_liquid_staking",
            "slash_probability_annual_pct": 0.01,
            "slash_penalty_pct": 1.0,
            "staking_apy_pct": 3.8,
            "position_size_usd": 100_000.0,
            "protocol_audited": True,
            "client_diversity_score": 7,
        })
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = log_path or _LOG_PATH_DEFAULT

    # ------------------------------------------------------------------
    # Static helpers exposed for unit testing
    # ------------------------------------------------------------------

    @staticmethod
    def expected_annual_loss_pct(
        slash_probability_annual_pct: float,
        slash_penalty_pct: float,
    ) -> float:
        """Compute expected annual loss percentage."""
        return _compute_expected_annual_loss_pct(
            slash_probability_annual_pct, slash_penalty_pct
        )

    @staticmethod
    def expected_annual_loss_usd(
        position_size_usd: float,
        expected_annual_loss_pct: float,
    ) -> float:
        """Compute expected annual loss in USD."""
        return _compute_expected_annual_loss_usd(
            position_size_usd, expected_annual_loss_pct
        )

    @staticmethod
    def net_staking_apy(
        staking_apy_pct: float,
        expected_annual_loss_pct: float,
    ) -> float:
        """Compute net staking APY after expected slashing loss."""
        return _compute_net_staking_apy_pct(staking_apy_pct, expected_annual_loss_pct)

    @staticmethod
    def slash_risk_score(
        slash_probability_annual_pct: float,
        slash_penalty_pct: float,
        protocol_audited: bool,
        client_diversity_score: int,
        staking_type: str,
    ) -> int:
        """Compute composite slash risk score (0–100)."""
        return _compute_slash_risk_score(
            slash_probability_annual_pct,
            slash_penalty_pct,
            protocol_audited,
            client_diversity_score,
            staking_type,
        )

    @staticmethod
    def risk_label(slash_risk_score: int) -> str:
        """Map risk score to label string."""
        return _compute_risk_label(slash_risk_score)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(
        self, data: dict[str, Any], *, write_log: bool = True
    ) -> dict[str, Any]:
        """
        Analyze staking penalty risk for a protocol position.

        Parameters
        ----------
        data : dict
            Input dictionary with keys documented at module level.
        write_log : bool
            If True (default) append result to the ring-buffer log file.

        Returns
        -------
        dict
            Output dictionary with all scoring results.
        """
        protocol_name = str(data.get("protocol_name", "unknown"))
        staking_type = str(data.get("staking_type", "other"))
        slash_probability_annual_pct = float(
            data.get("slash_probability_annual_pct", 0.0)
        )
        slash_penalty_pct = float(data.get("slash_penalty_pct", 0.0))
        staking_apy_pct = float(data.get("staking_apy_pct", 0.0))
        position_size_usd = float(data.get("position_size_usd", 0.0))
        protocol_audited = bool(data.get("protocol_audited", False))
        client_diversity_score = int(data.get("client_diversity_score", 0))

        exp_loss_pct = _compute_expected_annual_loss_pct(
            slash_probability_annual_pct, slash_penalty_pct
        )
        exp_loss_usd = _compute_expected_annual_loss_usd(
            position_size_usd, exp_loss_pct
        )
        net_apy = _compute_net_staking_apy_pct(staking_apy_pct, exp_loss_pct)
        score = _compute_slash_risk_score(
            slash_probability_annual_pct,
            slash_penalty_pct,
            protocol_audited,
            client_diversity_score,
            staking_type,
        )
        label = _compute_risk_label(score)

        result: dict[str, Any] = {
            "protocol_name": protocol_name,
            "staking_type": staking_type,
            "expected_annual_loss_pct": exp_loss_pct,
            "expected_annual_loss_usd": exp_loss_usd,
            "net_staking_apy_pct": net_apy,
            "slash_risk_score": score,
            "risk_label": label,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        if write_log:
            _atomic_append_log(self._log_path, result)

        return result
