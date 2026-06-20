"""
MP-992: DeFiProtocolRegulatoryRiskScorer
Evaluates regulatory risks for DeFi protocols.
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ── Risk labels ────────────────────────────────────────────────────────────
LABEL_COMPLIANT      = "COMPLIANT"
LABEL_LOW_RISK       = "LOW_RISK"
LABEL_MODERATE_RISK  = "MODERATE_RISK"
LABEL_HIGH_RISK      = "HIGH_RISK"
LABEL_CRITICAL_RISK  = "CRITICAL_RISK"

# ── Flags ─────────────────────────────────────────────────────────────────
FLAG_SECURITIES_RISK          = "SECURITIES_RISK"
FLAG_NO_AML_KYC               = "NO_AML_KYC"
FLAG_ANONYMOUS_TEAM           = "ANONYMOUS_TEAM"
FLAG_US_NEXUS_RISK            = "US_NEXUS_RISK"
FLAG_REGULATOR_ACTION_HISTORY = "REGULATOR_ACTION_HISTORY"
FLAG_STABLECOIN_SYSTEMIC      = "STABLECOIN_SYSTEMIC"

# ── Constants ──────────────────────────────────────────────────────────────
_LOG_CAP          = 100
_LOG_PATH_DEFAULT = "data/regulatory_risk_log.json"

# High-risk jurisdictions for regulatory exposure
_HIGH_RISK_JURISDICTIONS = {"US", "USA", "United States"}
_MEDIUM_RISK_JURISDICTIONS = {"EU", "European Union", "UK", "United Kingdom", "SEC"}

# DeFi categories with elevated securities risk
_SECURITIES_CATEGORY_RISK = {"derivatives": 20, "yield": 5, "lending": 5}


# ── Helpers ────────────────────────────────────────────────────────────────

def _atomic_write(path: str, obj: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ── Sub-scorers ────────────────────────────────────────────────────────────

def _kyc_aml_score(protocol: dict) -> float:
    """Score based on KYC/AML/sanctions absence. Higher = worse."""
    has_kyc            = bool(protocol.get("has_kyc", False))
    has_aml            = bool(protocol.get("has_aml", False))
    sanctions_screening = bool(protocol.get("sanctions_screening", False))

    score = 0.0
    if not has_kyc:
        score += 35.0
    if not has_aml:
        score += 35.0
    if not sanctions_screening:
        score += 15.0
    # Bonus reduction for full compliance
    if has_kyc and has_aml and sanctions_screening:
        score = 0.0
    return _clamp(score)


def _jurisdiction_risk_score(protocol: dict) -> float:
    """Score based on jurisdiction exposure. Higher = worse."""
    jurisdictions  = protocol.get("jurisdiction", [])
    has_kyc        = bool(protocol.get("has_kyc", False))
    has_aml        = bool(protocol.get("has_aml", False))
    geo_blocks     = protocol.get("front_end_geo_restrictions", [])

    score = 0.0

    # Check for high-risk jurisdictions
    has_us_nexus = any(j in _HIGH_RISK_JURISDICTIONS for j in jurisdictions)
    has_eu_nexus = any(j in _MEDIUM_RISK_JURISDICTIONS for j in jurisdictions)

    if has_us_nexus:
        if not (has_kyc and has_aml):
            score += 40.0
        else:
            score += 10.0  # US with compliance is still a factor

    if has_eu_nexus:
        if not has_aml:
            score += 20.0
        else:
            score += 5.0

    # Other jurisdictions baseline
    other_count = len([j for j in jurisdictions
                       if j not in _HIGH_RISK_JURISDICTIONS
                       and j not in _MEDIUM_RISK_JURISDICTIONS])
    score += min(other_count * 2.0, 10.0)

    # Geo restrictions partially mitigate risk
    if has_us_nexus and "US" in geo_blocks:
        score = max(0.0, score - 20.0)
    if has_eu_nexus and "EU" in geo_blocks:
        score = max(0.0, score - 10.0)

    return _clamp(score)


def _securities_risk_score(protocol: dict) -> float:
    """Score based on securities classification risk. Higher = worse."""
    token_classified = bool(protocol.get("token_classified_security", False))
    defi_category    = protocol.get("defi_category", "other")
    has_kyc          = bool(protocol.get("has_kyc", False))

    score = 0.0

    if token_classified:
        score += 40.0
        if not has_kyc:
            score += 15.0  # Extra penalty: securities without KYC

    # Category-based risk
    score += _SECURITIES_CATEGORY_RISK.get(defi_category, 0.0)

    return _clamp(score)


def _operational_opacity_score(protocol: dict) -> float:
    """Score based on team/legal opacity. Higher = worse."""
    team_public       = bool(protocol.get("team_public", False))
    entity_incorporated = bool(protocol.get("entity_incorporated", False))
    dao_governance    = bool(protocol.get("dao_governance", False))

    score = 0.0

    if not team_public:
        score += 30.0
    if not entity_incorporated:
        score += 30.0

    # DAO without public team compounds opacity
    if dao_governance and not team_public and not entity_incorporated:
        score += 15.0

    # Full transparency bonus
    if team_public and entity_incorporated:
        score = max(0.0, score - 5.0)

    return _clamp(score)


# ── Flags ─────────────────────────────────────────────────────────────────

def _compute_flags(protocol: dict) -> list:
    flags = []

    has_kyc         = bool(protocol.get("has_kyc", False))
    has_aml         = bool(protocol.get("has_aml", False))
    team_public     = bool(protocol.get("team_public", False))
    entity_incorp   = bool(protocol.get("entity_incorporated", False))
    jurisdictions   = protocol.get("jurisdiction", [])
    token_classified = bool(protocol.get("token_classified_security", False))
    reg_action      = bool(protocol.get("regulator_action_history", False))
    stablecoin_pct  = float(protocol.get("stablecoin_exposure_pct", 0.0))

    if token_classified:
        flags.append(FLAG_SECURITIES_RISK)

    if not has_kyc and not has_aml:
        flags.append(FLAG_NO_AML_KYC)

    if not team_public and not entity_incorp:
        flags.append(FLAG_ANONYMOUS_TEAM)

    has_us_nexus = any(j in _HIGH_RISK_JURISDICTIONS for j in jurisdictions)
    if has_us_nexus and not (has_kyc and has_aml):
        flags.append(FLAG_US_NEXUS_RISK)

    if reg_action:
        flags.append(FLAG_REGULATOR_ACTION_HISTORY)

    if stablecoin_pct > 70.0:
        flags.append(FLAG_STABLECOIN_SYSTEMIC)

    return flags


# ── Composite score + label ────────────────────────────────────────────────

_WEIGHTS = {
    "kyc_aml":    0.35,
    "jurisdiction": 0.25,
    "securities": 0.25,
    "opacity":    0.15,
}


def _composite_score(kyc_aml: float, jurisdiction: float,
                     securities: float, opacity: float) -> float:
    score = (
        kyc_aml    * _WEIGHTS["kyc_aml"]
        + jurisdiction * _WEIGHTS["jurisdiction"]
        + securities   * _WEIGHTS["securities"]
        + opacity      * _WEIGHTS["opacity"]
    )
    return _clamp(round(score, 2))


def _risk_label(composite: float, protocol: dict) -> str:
    has_kyc      = bool(protocol.get("has_kyc", False))
    has_aml      = bool(protocol.get("has_aml", False))
    reg_action   = bool(protocol.get("regulator_action_history", False))
    token_class  = bool(protocol.get("token_classified_security", False))

    # CRITICAL_RISK check first
    if composite >= 75.0 or reg_action or (token_class and not has_kyc):
        return LABEL_CRITICAL_RISK

    if composite >= 55.0:
        return LABEL_HIGH_RISK

    if composite >= 35.0:
        return LABEL_MODERATE_RISK

    if composite >= 20.0:
        return LABEL_LOW_RISK

    # COMPLIANT: score < 20 AND has_kyc AND has_aml
    if has_kyc and has_aml:
        return LABEL_COMPLIANT

    return LABEL_LOW_RISK


# ── Per-protocol scorer ────────────────────────────────────────────────────

def _score_protocol(protocol: dict) -> dict:
    name = protocol.get("name", "unknown")

    kyc_aml    = _kyc_aml_score(protocol)
    jur        = _jurisdiction_risk_score(protocol)
    securities = _securities_risk_score(protocol)
    opacity    = _operational_opacity_score(protocol)
    composite  = _composite_score(kyc_aml, jur, securities, opacity)
    label      = _risk_label(composite, protocol)
    flags      = _compute_flags(protocol)

    return {
        "name":                    name,
        "kyc_aml_score":           kyc_aml,
        "jurisdiction_risk_score": jur,
        "securities_risk_score":   securities,
        "operational_opacity_score": opacity,
        "composite_regulatory_score": composite,
        "risk_label":              label,
        "flags":                   flags,
        "defi_category":           protocol.get("defi_category", "other"),
        "settlement_layer":        protocol.get("settlement_layer", "other"),
    }


# ── Main class ─────────────────────────────────────────────────────────────

class DeFiProtocolRegulatoryRiskScorer:
    """
    Scores regulatory risk for a batch of DeFi protocols.

    score(protocols, config) -> dict with per-protocol results + aggregates.
    Optionally writes a ring-buffer log entry to data/regulatory_risk_log.json.
    """

    def score(self, protocols: list, config: dict = None) -> dict:
        if config is None:
            config = {}

        log_path  = config.get("log_path", _LOG_PATH_DEFAULT)
        write_log = config.get("write_log", True)

        if not protocols:
            result = {
                "protocols":            [],
                "highest_risk":         None,
                "lowest_risk":          None,
                "avg_regulatory_score": 0.0,
                "critical_count":       0,
                "compliant_count":      0,
                "timestamp":            time.time(),
            }
            if write_log:
                self._append_log(result, log_path)
            return result

        scored = [_score_protocol(p) for p in protocols]

        scores    = [s["composite_regulatory_score"] for s in scored]
        avg_score = round(sum(scores) / len(scores), 4)

        highest   = max(scored, key=lambda x: x["composite_regulatory_score"])
        lowest    = min(scored, key=lambda x: x["composite_regulatory_score"])

        critical_count  = sum(1 for s in scored if s["risk_label"] == LABEL_CRITICAL_RISK)
        compliant_count = sum(1 for s in scored if s["risk_label"] == LABEL_COMPLIANT)

        result = {
            "protocols":            scored,
            "highest_risk":         highest["name"],
            "lowest_risk":          lowest["name"],
            "avg_regulatory_score": avg_score,
            "critical_count":       critical_count,
            "compliant_count":      compliant_count,
            "timestamp":            time.time(),
        }

        if write_log:
            self._append_log(result, log_path)

        return result

    # ── Log helpers ────────────────────────────────────────────────────────

    def _append_log(self, result: dict, path: str) -> None:
        """Append to ring-buffer log (cap _LOG_CAP), atomic write."""
        log = _load_log(path)
        log.append(result)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        _atomic_write(path, log)

    def load_log(self, path: str = _LOG_PATH_DEFAULT) -> list:
        """Public method to read the log."""
        return _load_log(path)


# ── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    _DEMO_PROTOCOLS = [
        {
            "name": "AaveV3",
            "jurisdiction": ["EU", "Cayman Islands"],
            "has_kyc": False,
            "has_aml": True,
            "token_classified_security": False,
            "sanctions_screening": True,
            "front_end_geo_restrictions": ["US", "OFAC"],
            "team_public": True,
            "entity_incorporated": True,
            "dao_governance": True,
            "stablecoin_exposure_pct": 45.0,
            "defi_category": "lending",
            "regulator_action_history": False,
            "settlement_layer": "ethereum",
        },
        {
            "name": "RiskyDex",
            "jurisdiction": ["US", "Singapore"],
            "has_kyc": False,
            "has_aml": False,
            "token_classified_security": True,
            "sanctions_screening": False,
            "front_end_geo_restrictions": [],
            "team_public": False,
            "entity_incorporated": False,
            "dao_governance": True,
            "stablecoin_exposure_pct": 80.0,
            "defi_category": "derivatives",
            "regulator_action_history": True,
            "settlement_layer": "solana",
        },
    ]

    scorer = DeFiProtocolRegulatoryRiskScorer()
    mode   = sys.argv[1] if len(sys.argv) > 1 else "--check"

    if mode == "--run":
        result = scorer.score(_DEMO_PROTOCOLS, {"write_log": True})
    else:
        result = scorer.score(_DEMO_PROTOCOLS, {"write_log": False})

    for p in result["protocols"]:
        print(f"  {p['name']:20s}  score={p['composite_regulatory_score']:5.1f}"
              f"  {p['risk_label']:<15}  flags={p['flags']}")

    print(f"\nHighest risk : {result['highest_risk']}")
    print(f"Lowest risk  : {result['lowest_risk']}")
    print(f"Avg score    : {result['avg_regulatory_score']}")
    print(f"Critical     : {result['critical_count']}")
    print(f"Compliant    : {result['compliant_count']}")
