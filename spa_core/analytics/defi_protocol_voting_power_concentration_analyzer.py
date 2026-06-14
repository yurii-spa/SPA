"""
MP-1096 DeFiProtocolVotingPowerConcentrationAnalyzer
-----------------------------------------------------
Analyzes governance token voting power concentration to quantify the risk
that a small number of wallets can control protocol governance outcomes.

High concentration => protocol can be captured by a cartel => governance risk
is elevated and DeFi risk models must discount yield accordingly.

Inputs (via analyze(params)):
    top1_voting_power_pct   float  largest single holder %
    top5_voting_power_pct   float  top-5 holders combined %
    top10_voting_power_pct  float  top-10 holders combined %
    total_token_supply      float  total token supply (units)
    circulating_supply      float  circulating supply (units)
    dao_treasury_pct        float  % held by DAO treasury
    team_vesting_pct        float  % held by team / vesting contracts
    quorum_threshold_pct    float  minimum % of supply to pass a proposal
    protocol_name           str    human-readable protocol name

Outputs (returned dict):
    herfindahl_index         float  HHI approximation (sum of squares of top-10
                                    individual share estimates, 0-10000 scale)
    effective_control_pct    float  top1 + team_vesting (concentration signal, %)
    quorum_achievability_score int  0-100; 100 = quorum trivially reachable
    governance_risk_score    int    0-100; 0 = fully decentralized, 100 = cartel
    governance_label         str    DECENTRALIZED / MODERATELY_CONCENTRATED /
                                    CONCENTRATED / HIGHLY_CONCENTRATED /
                                    GOVERNANCE_CARTEL

Label logic driven by top5_voting_power_pct:
    < 20%   => DECENTRALIZED
    20-35%  => MODERATELY_CONCENTRATED
    35-51%  => CONCENTRATED
    51-70%  => HIGHLY_CONCENTRATED
    > 70%   => GOVERNANCE_CARTEL

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap=100).
Log file: data/voting_power_concentration_log.json
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

_LOG_FILENAME = "voting_power_concentration_log.json"
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", _LOG_FILENAME
)
_LOG_CAP = 100

# Label thresholds on top5_voting_power_pct
_LABEL_THRESHOLDS = [
    (20.0, "DECENTRALIZED"),
    (35.0, "MODERATELY_CONCENTRATED"),
    (51.0, "CONCENTRATED"),
    (70.0, "HIGHLY_CONCENTRATED"),
]
_LABEL_TOP = "GOVERNANCE_CARTEL"

# governance_risk_score weights
_W_TOP5 = 0.55
_W_TOP1 = 0.25
_W_TEAM = 0.20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


def _herfindahl_index(
    top1: float,
    top5: float,
    top10: float,
) -> float:
    """
    HHI approximation from bracket totals.

    We decompose the three bracket totals into 10 individual estimated shares
    (equal-split within each bracket) and compute the classic HHI = Σ sᵢ²
    on the 0–100 percentage scale (so maximum HHI is 10 000).

    Bracket decomposition:
        Holder 1           : top1
        Holders 2-5 (×4)  : (top5 − top1) / 4  each
        Holders 6-10 (×5) : (top10 − top5) / 5  each

    Negative bracket remainders are clamped to 0 so guard-railed inputs
    never produce NaN / negative squares.
    """
    s1 = max(0.0, top1)
    bucket_2_5 = max(0.0, top5 - top1)
    bucket_6_10 = max(0.0, top10 - top5)

    share_2_5 = bucket_2_5 / 4.0  # per-holder share in bucket 2-5
    share_6_10 = bucket_6_10 / 5.0  # per-holder share in bucket 6-10

    hhi = (
        s1 ** 2
        + 4.0 * (share_2_5 ** 2)
        + 5.0 * (share_6_10 ** 2)
    )
    return round(hhi, 4)


def _effective_control_pct(top1: float, team_vesting: float) -> float:
    """
    Effective control concentration signal: largest single holder PLUS team
    vesting contracts.  Capped at 100 %.
    """
    return round(_clamp(top1 + team_vesting), 4)


def _quorum_achievability_score(top10: float, quorum_threshold: float) -> int:
    """
    Integer 0–100 reflecting how easily the quorum threshold can be reached.

    100  = top-10 holders alone can clear quorum (trivially achievable).
    0    = quorum threshold is so high that even top-10 cannot reach it.
    The score scales linearly from 0 to 100 based on the ratio
    top10 / quorum_threshold.  When quorum_threshold == 0 the governance
    system has no quorum requirement → score = 100.
    """
    if quorum_threshold <= 0.0:
        return 100
    ratio = _clamp(top10, 0.0) / quorum_threshold
    return int(min(100, round(ratio * 100)))


def _governance_risk_score(top5: float, top1: float, team_vesting: float) -> int:
    """
    Composite governance risk score 0–100.

    Weights:
        top5_voting_power_pct  : 55 %  (primary breadth of concentration)
        top1_voting_power_pct  : 25 %  (single-actor dominance risk)
        team_vesting_pct       : 20 %  (insider control risk)

    All three inputs are clamped to [0, 100] before weighting.
    """
    t5 = _clamp(top5)
    t1 = _clamp(top1)
    tv = _clamp(team_vesting)
    raw = _W_TOP5 * t5 + _W_TOP1 * t1 + _W_TEAM * tv
    return int(min(100, max(0, round(raw))))


def _governance_label(top5: float) -> str:
    """Map top5_voting_power_pct to a governance label."""
    t5 = top5
    if t5 < 20.0:
        return "DECENTRALIZED"
    if t5 < 35.0:
        return "MODERATELY_CONCENTRATED"
    if t5 < 51.0:
        return "CONCENTRATED"
    if t5 <= 70.0:
        return "HIGHLY_CONCENTRATED"
    return "GOVERNANCE_CARTEL"


def _atomic_log(log_path: str, entry: dict, log_cap: int = _LOG_CAP) -> None:
    """Append *entry* to ring-buffer JSON array (capped at log_cap), atomic write."""
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
    if len(data) > log_cap:
        data = data[-log_cap:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DeFiProtocolVotingPowerConcentrationAnalyzer:
    """
    Analyzes governance token voting power concentration for DeFi protocols.

    Usage
    -----
    analyzer = DeFiProtocolVotingPowerConcentrationAnalyzer()
    result = analyzer.analyze(params)

    Parameters
    ----------
    log_path : str
        Path to the ring-buffer JSON log file (default: data/voting_power_concentration_log.json)
    log_cap : int
        Maximum number of log entries to retain (default: 100)
    """

    def __init__(
        self,
        log_path: str = _LOG_PATH,
        log_cap: int = _LOG_CAP,
    ) -> None:
        self._log_path = log_path
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def analyze(self, params: dict, config: dict | None = None) -> dict[str, Any]:
        """
        Analyze voting power concentration.

        Parameters
        ----------
        params : dict
            top1_voting_power_pct   : float  (largest single holder %)
            top5_voting_power_pct   : float  (top-5 combined %)
            top10_voting_power_pct  : float  (top-10 combined %)
            total_token_supply      : float  (total supply, informational)
            circulating_supply      : float  (circulating supply, informational)
            dao_treasury_pct        : float  (% held by DAO treasury)
            team_vesting_pct        : float  (% held by team / vesting)
            quorum_threshold_pct    : float  (min % to pass a proposal)
            protocol_name           : str

        config : dict, optional
            log_path : str   override log path
            skip_log : bool  skip writing to log (default False)

        Returns
        -------
        dict with keys:
            protocol_name, top1_voting_power_pct, top5_voting_power_pct,
            top10_voting_power_pct, total_token_supply, circulating_supply,
            dao_treasury_pct, team_vesting_pct, quorum_threshold_pct,
            herfindahl_index, effective_control_pct,
            quorum_achievability_score, governance_risk_score,
            governance_label, timestamp
        """
        cfg = config or {}
        log_path = cfg.get("log_path", self._log_path)
        skip_log = bool(cfg.get("skip_log", False))

        # -- Parse and sanitize inputs -----------------------------------
        protocol_name = str(params.get("protocol_name", "UNKNOWN"))
        top1 = float(params.get("top1_voting_power_pct", 0.0))
        top5 = float(params.get("top5_voting_power_pct", 0.0))
        top10 = float(params.get("top10_voting_power_pct", 0.0))
        total_supply = float(params.get("total_token_supply", 0.0))
        circ_supply = float(params.get("circulating_supply", 0.0))
        dao_treasury = float(params.get("dao_treasury_pct", 0.0))
        team_vesting = float(params.get("team_vesting_pct", 0.0))
        quorum_threshold = float(params.get("quorum_threshold_pct", 0.0))

        # Clamp to valid [0, 100] ranges
        top1 = _clamp(top1)
        top5 = _clamp(top5)
        top10 = _clamp(top10)
        dao_treasury = _clamp(dao_treasury)
        team_vesting = _clamp(team_vesting)
        quorum_threshold = _clamp(quorum_threshold)

        # -- Core calculations -------------------------------------------
        hhi = _herfindahl_index(top1, top5, top10)
        eff_ctrl = _effective_control_pct(top1, team_vesting)
        quorum_score = _quorum_achievability_score(top10, quorum_threshold)
        risk_score = _governance_risk_score(top5, top1, team_vesting)
        label = _governance_label(top5)

        result: dict[str, Any] = {
            "protocol_name": protocol_name,
            # raw inputs (sanitized)
            "top1_voting_power_pct": top1,
            "top5_voting_power_pct": top5,
            "top10_voting_power_pct": top10,
            "total_token_supply": total_supply,
            "circulating_supply": circ_supply,
            "dao_treasury_pct": dao_treasury,
            "team_vesting_pct": team_vesting,
            "quorum_threshold_pct": quorum_threshold,
            # computed outputs
            "herfindahl_index": hhi,
            "effective_control_pct": eff_ctrl,
            "quorum_achievability_score": quorum_score,
            "governance_risk_score": risk_score,
            "governance_label": label,
            "timestamp": time.time(),
        }

        if not skip_log:
            try:
                _atomic_log(log_path, result, self._log_cap)
            except Exception:
                pass  # advisory: never crash caller

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(params: dict, config: dict | None = None) -> dict[str, Any]:
    """Module-level shortcut — delegates to DeFiProtocolVotingPowerConcentrationAnalyzer."""
    return DeFiProtocolVotingPowerConcentrationAnalyzer().analyze(params, config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "protocol_name": "Aave",
        "top1_voting_power_pct": 12.0,
        "top5_voting_power_pct": 38.0,
        "top10_voting_power_pct": 55.0,
        "total_token_supply": 16_000_000.0,
        "circulating_supply": 14_500_000.0,
        "dao_treasury_pct": 15.0,
        "team_vesting_pct": 10.0,
        "quorum_threshold_pct": 40.0,
    }

    r = analyze(_demo, config={"skip_log": True})
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)
