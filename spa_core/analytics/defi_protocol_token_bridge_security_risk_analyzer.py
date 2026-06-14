"""
MP-1052: DeFiProtocolTokenBridgeSecurityRiskAnalyzer
Assess security risk of DeFi token bridges for capital routing decisions.

Bridge hacks have caused billions in losses (Ronin $625M, Wormhole $320M, Nomad $190M).
This module provides a multi-factor risk score to guide bridge selection.

Advisory / read-only. Pure stdlib. Atomic writes (os.replace).
Ring-buffer log capped at 100 entries in data/bridge_security_risk_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/bridge_security_risk_log.json")
MAX_ENTRIES = 100

# Validation model risk weights (lower score = stronger validation)
VALIDATION_STRENGTH: Dict[str, float] = {
    "zk": 95.0,           # ZK-proof: cryptographically verified
    "zk_proof": 95.0,
    "optimistic": 60.0,   # Optimistic rollup: 7-day challenge window
    "multisig": 45.0,     # Base score; adjusted by validator_count
    "poa": 30.0,          # Proof-of-authority: centralized
    "federated": 25.0,    # Federated signers: small trusted set
}

# Thresholds for overall_label
LABEL_THRESHOLDS = [
    (20.0,  "FORTRESS_BRIDGE"),
    (40.0,  "SECURE_BRIDGE"),
    (60.0,  "MODERATE_RISK"),
    (80.0,  "HIGH_RISK"),
    (100.1, "DO_NOT_USE"),
]

# Audit freshness breakpoints (days → score 0–100)
AUDIT_FRESHNESS_TABLE = [
    (30,   100.0),
    (90,    80.0),
    (180,   60.0),
    (365,   35.0),
    (730,   15.0),
]
AUDIT_STALE_SCORE = 0.0   # never audited / >730 days

# ---------------------------------------------------------------------------
# Pure helper functions (easily unit-tested)
# ---------------------------------------------------------------------------


def compute_validation_strength_score(validation_model: str, validator_count: int) -> float:
    """
    Return validation strength score 0–100 (higher = safer).

    For multisig/federated the score is boosted by validator_count:
      base + min(40, validator_count * 3)  capped at 90.
    """
    model_key = validation_model.lower().strip()
    base = VALIDATION_STRENGTH.get(model_key)
    if base is None:
        # Unknown model — treat as least safe
        base = 20.0

    if model_key in ("multisig", "poa", "federated"):
        boost = min(40.0, validator_count * 3.0)
        score = min(90.0, base + boost)
    else:
        score = base

    return round(max(0.0, min(100.0, score)), 4)


def compute_audit_freshness_score(days_since_last_audit: int) -> float:
    """
    Return audit freshness score 0–100 (higher = more recent/safer).

    Negative days treated as 'just audited' (score 100).
    """
    if days_since_last_audit < 0:
        return 100.0
    for threshold, score in AUDIT_FRESHNESS_TABLE:
        if days_since_last_audit <= threshold:
            return score
    return AUDIT_STALE_SCORE


def compute_hack_exposure_ratio(historical_hacks: List[Dict[str, Any]], tvl_usd: float) -> float:
    """
    Return total hacked USD / current TVL USD, capped at 1.0.

    Returns 0.0 if tvl_usd <= 0 or no hacks.
    """
    if tvl_usd <= 0:
        return 1.0  # zero TVL → treat as maximum exposure
    total_hacked = sum(float(h.get("amount_usd", 0)) for h in historical_hacks)
    return min(1.0, total_hacked / tvl_usd)


def compute_finality_risk_penalty(time_to_finality_minutes: float) -> float:
    """
    Return a 0–25 penalty based on time to finality.

    Faster finality = lower capital-in-transit risk.
    """
    if time_to_finality_minutes <= 1:
        return 0.0
    elif time_to_finality_minutes <= 5:
        return 3.0
    elif time_to_finality_minutes <= 20:
        return 8.0
    elif time_to_finality_minutes <= 60:
        return 15.0
    elif time_to_finality_minutes <= 1440:   # up to 24 h
        return 20.0
    else:
        return 25.0  # > 24 h (e.g. optimistic 7-day exit)


def compute_bridge_risk_score(
    validation_strength_score: float,
    audit_freshness_score: float,
    hack_exposure_ratio: float,
    time_to_finality_minutes: float,
    open_source: bool,
    bug_bounty_usd: float,
    tvl_usd: float,
) -> float:
    """
    Combine sub-scores into a single bridge_risk_score (0–100, higher = riskier).

    Weights:
        validation weakness  35 %
        audit staleness      25 %
        hack exposure        25 %
        finality penalty     15 %   (normalised to 0–15 contribution)
    Adjustments (deductions from final score):
        open_source           −5 pts
        bug_bounty_usd       −3 / −7 / −12 pts (graduated)
        high TVL              −3 pts  (≥ $500M)
    """
    validation_weakness = 100.0 - validation_strength_score
    audit_staleness = 100.0 - audit_freshness_score
    hack_score = hack_exposure_ratio * 100.0
    finality_penalty = compute_finality_risk_penalty(time_to_finality_minutes)
    # Normalise finality penalty into 0–15 contribution (max penalty is 25 → scales to 15)
    finality_contribution = finality_penalty * (15.0 / 25.0)

    raw = (
        validation_weakness * 0.35
        + audit_staleness * 0.25
        + hack_score * 0.25
        + finality_contribution * 0.15
    )

    # Positive reductions
    if open_source:
        raw -= 5.0
    if bug_bounty_usd >= 1_000_000:
        raw -= 12.0
    elif bug_bounty_usd >= 100_000:
        raw -= 7.0
    elif bug_bounty_usd > 0:
        raw -= 3.0

    if tvl_usd >= 500_000_000:
        raw -= 3.0

    return round(max(0.0, min(100.0, raw)), 4)


def compute_overall_label(bridge_risk_score: float) -> str:
    """Map numeric risk score to categorical label."""
    for threshold, label in LABEL_THRESHOLDS:
        if bridge_risk_score < threshold:
            return label
    return "DO_NOT_USE"


# ---------------------------------------------------------------------------
# Main analyser class
# ---------------------------------------------------------------------------


class DeFiProtocolTokenBridgeSecurityRiskAnalyzer:
    """
    Assess DeFi token bridge security risk from structural and historical factors.

    Usage
    -----
    analyzer = DeFiProtocolTokenBridgeSecurityRiskAnalyzer()
    result = analyzer.analyze({
        "bridge_name": "Wormhole",
        "tvl_usd": 800_000_000,
        "validation_model": "multisig",
        "validator_count": 19,
        "days_since_last_audit": 45,
        "historical_hacks": [{"date": "2022-02-02", "amount_usd": 320_000_000}],
        "open_source": True,
        "bug_bounty_usd": 2_500_000,
        "time_to_finality_minutes": 15,
    })
    # result is a dict with keys defined in OUTPUT_KEYS
    """

    OUTPUT_KEYS = (
        "bridge_name",
        "bridge_risk_score",
        "hack_exposure_ratio",
        "audit_freshness_score",
        "validation_strength_score",
        "overall_label",
        "timestamp",
    )

    def __init__(self, data_file: Path | None = None, max_entries: int = MAX_ENTRIES) -> None:
        self._data_file = data_file if data_file is not None else DATA_FILE
        self._max_entries = max_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse bridge security risk and return a result dict.

        Parameters
        ----------
        params : dict with keys:
            bridge_name             str
            tvl_usd                 float  ≥ 0
            validation_model        str    e.g. "zk", "optimistic", "multisig"
            validator_count         int    ≥ 1
            days_since_last_audit   int    ≥ 0
            historical_hacks        list   of {"date": str, "amount_usd": float}
            open_source             bool
            bug_bounty_usd          float  ≥ 0
            time_to_finality_minutes float ≥ 0

        Returns
        -------
        dict with OUTPUT_KEYS
        """
        self._validate(params)

        bridge_name = str(params["bridge_name"])
        tvl_usd = float(params["tvl_usd"])
        validation_model = str(params["validation_model"])
        validator_count = int(params["validator_count"])
        days_since_last_audit = int(params["days_since_last_audit"])
        historical_hacks = list(params.get("historical_hacks", []))
        open_source = bool(params["open_source"])
        bug_bounty_usd = float(params["bug_bounty_usd"])
        time_to_finality_minutes = float(params["time_to_finality_minutes"])

        # Sub-scores
        validation_strength_score = compute_validation_strength_score(
            validation_model, validator_count
        )
        audit_freshness_score = compute_audit_freshness_score(days_since_last_audit)
        hack_exposure_ratio = compute_hack_exposure_ratio(historical_hacks, tvl_usd)

        # Composite risk score
        bridge_risk_score = compute_bridge_risk_score(
            validation_strength_score=validation_strength_score,
            audit_freshness_score=audit_freshness_score,
            hack_exposure_ratio=hack_exposure_ratio,
            time_to_finality_minutes=time_to_finality_minutes,
            open_source=open_source,
            bug_bounty_usd=bug_bounty_usd,
            tvl_usd=tvl_usd,
        )

        overall_label = compute_overall_label(bridge_risk_score)

        result: Dict[str, Any] = {
            "bridge_name": bridge_name,
            "bridge_risk_score": bridge_risk_score,
            "hack_exposure_ratio": round(hack_exposure_ratio, 6),
            "audit_freshness_score": audit_freshness_score,
            "validation_strength_score": validation_strength_score,
            "overall_label": overall_label,
            "timestamp": time.time(),
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(params: Dict[str, Any]) -> None:
        required = {
            "bridge_name", "tvl_usd", "validation_model", "validator_count",
            "days_since_last_audit", "historical_hacks", "open_source",
            "bug_bounty_usd", "time_to_finality_minutes",
        }
        missing = required - set(params.keys())
        if missing:
            raise ValueError(f"Missing required params: {sorted(missing)}")
        if float(params["tvl_usd"]) < 0:
            raise ValueError("tvl_usd must be >= 0")
        if int(params["validator_count"]) < 1:
            raise ValueError("validator_count must be >= 1")
        if int(params["days_since_last_audit"]) < 0:
            raise ValueError("days_since_last_audit must be >= 0")
        if float(params["bug_bounty_usd"]) < 0:
            raise ValueError("bug_bounty_usd must be >= 0")
        if float(params["time_to_finality_minutes"]) < 0:
            raise ValueError("time_to_finality_minutes must be >= 0")

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Append entry to ring-buffer JSON log (max MAX_ENTRIES). Atomic write."""
        self._data_file.parent.mkdir(parents=True, exist_ok=True)

        existing: List[Dict[str, Any]] = []
        if self._data_file.exists():
            try:
                with open(self._data_file, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(entry)
        if len(existing) > self._max_entries:
            existing = existing[-self._max_entries:]

        tmp = self._data_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp, self._data_file)
