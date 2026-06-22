"""
MP-878: ProtocolRegulatoryRiskAssessor
Assesses regulatory risk exposure of DeFi protocols — KYC requirements,
jurisdiction risk, token classification risk, and potential for enforcement actions.

Advisory / read-only. Pure stdlib. Atomic writes (tmp + os.replace).
"""

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/regulatory_risk_log.json")
MAX_ENTRIES = 100

# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------

_JURISDICTION_SCORES = {
    "US": 20,
    "EU": 15,
    "CAYMAN": 8,
    "OFFSHORE": 12,
    "DECENTRALIZED": 5,
}
_JURISDICTION_DEFAULT = 10

_TOKEN_RISK_SCORES = {
    "SECURITY_LIKE": 25,
    "STABLECOIN": 18,
    "GOVERNANCE": 12,
    "UTILITY": 8,
    "NFT": 5,
}
_TOKEN_RISK_DEFAULT = 8


def _jurisdiction_score(jurisdiction: str) -> int:
    """0-25 score based on jurisdiction."""
    return _JURISDICTION_SCORES.get(str(jurisdiction).upper(), _JURISDICTION_DEFAULT)


def _enforcement_exposure_score(protocol: dict) -> int:
    """0-35 score based on enforcement exposure factors."""
    score = 0
    if protocol.get("has_received_sec_subpoena", False):
        score += 20
    if protocol.get("team_is_doxxed", False):
        score += 8
    # US users + no KYC = risk
    if not protocol.get("has_us_user_restriction", False) and not protocol.get("has_kyc", False):
        score += 7
    return min(35, score)


def _token_risk_score(token_type: str) -> int:
    """0-25 score based on token type."""
    return _TOKEN_RISK_SCORES.get(str(token_type).upper(), _TOKEN_RISK_DEFAULT)


def _structural_risk_score(protocol: dict) -> int:
    """0-15 score based on structural characteristics."""
    centralized = int(protocol.get("centralized_components", 0))
    score = 0
    if centralized >= 5:
        score += 10
    elif centralized >= 3:
        score += 7
    elif centralized >= 1:
        score += 4
    # else 0

    if not protocol.get("has_legal_wrapper", False):
        score += 5

    return min(15, score)


def _regulatory_risk_score(j_score: int, e_score: int,
                            t_score: int, s_score: int) -> int:
    """Total regulatory risk score, capped at 100."""
    return min(100, j_score + e_score + t_score + s_score)


def _risk_level(score: int) -> str:
    """Risk level label from score."""
    if score >= 75:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 35:
        return "ELEVATED"
    if score >= 20:
        return "MODERATE"
    return "LOW"


def _regulatory_flags(protocol: dict) -> list:
    """Build list of regulatory flag strings."""
    flags = []
    name = protocol.get("name", "")
    jurisdiction = str(protocol.get("jurisdiction", "")).upper()
    token_type = str(protocol.get("token_type", "UTILITY")).upper()
    centralized = int(protocol.get("centralized_components", 0))
    tvl = float(protocol.get("tvl_usd", 0.0))

    if protocol.get("has_received_sec_subpoena", False):
        flags.append("Active SEC investigation/subpoena")

    if token_type == "SECURITY_LIKE":
        flags.append("Token may be classified as security")

    if jurisdiction == "US" and not protocol.get("has_kyc", False):
        flags.append("US-based without KYC — high enforcement risk")

    if not protocol.get("has_us_user_restriction", False) and token_type in (
        "SECURITY_LIKE", "GOVERNANCE"
    ):
        flags.append("Accessible to US users without restriction")

    if centralized >= 3:
        flags.append(f"{centralized} centralized components — regulatory attack surface")

    if not protocol.get("has_legal_wrapper", False) and tvl >= 10_000_000:
        flags.append("Large TVL protocol without legal wrapper")

    if not flags:
        flags.append("No significant regulatory flags")

    return flags


def _recommendation(name: str, risk_lv: str, jurisdiction: str,
                    centralized: int) -> str:
    """Human-readable recommendation based on risk level."""
    if risk_lv == "CRITICAL":
        return f"CRITICAL: {name} faces high enforcement risk. Reduce exposure."
    if risk_lv == "HIGH":
        return f"Regulatory risk elevated. Monitor {name} for enforcement actions."
    if risk_lv == "ELEVATED":
        return f"Moderate regulatory exposure. {jurisdiction} jurisdiction watchlist."
    if risk_lv == "MODERATE":
        return (
            f"Some regulatory risk. {name} has "
            f"{centralized} centralized components."
        )
    return f"{name} has manageable regulatory profile."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Assess regulatory risk of DeFi protocols.

    protocols: list of protocol dicts (see module docstring)
    config: currently unused; reserved for future filtering

    Returns analysis dict.
    """
    if not protocols:
        return {
            "protocols": [],
            "highest_regulatory_risk": None,
            "lowest_regulatory_risk": None,
            "high_risk_count": 0,
            "average_risk_score": 0.0,
            "timestamp": time.time(),
        }

    results = []

    for p in protocols:
        name = p.get("name", "")
        jurisdiction = str(p.get("jurisdiction", "OTHER")).upper()
        token_type = str(p.get("token_type", "UTILITY")).upper()
        centralized = int(p.get("centralized_components", 0))

        j_score = _jurisdiction_score(jurisdiction)
        e_score = _enforcement_exposure_score(p)
        t_score = _token_risk_score(token_type)
        s_score = _structural_risk_score(p)

        total = _regulatory_risk_score(j_score, e_score, t_score, s_score)
        risk_lv = _risk_level(total)
        flags = _regulatory_flags(p)
        rec = _recommendation(name, risk_lv, jurisdiction, centralized)

        results.append({
            "name": name,
            "regulatory_risk_score": total,
            "risk_level": risk_lv,
            "jurisdiction_score": j_score,
            "enforcement_exposure_score": e_score,
            "token_risk_score": t_score,
            "structural_risk_score": s_score,
            "regulatory_flags": flags,
            "recommendation": rec,
        })

    # Aggregates
    highest = max(results, key=lambda x: x["regulatory_risk_score"])["name"]
    lowest = min(results, key=lambda x: x["regulatory_risk_score"])["name"]
    high_risk_count = sum(
        1 for r in results if r["risk_level"] in ("HIGH", "CRITICAL")
    )
    avg_score = sum(r["regulatory_risk_score"] for r in results) / len(results)

    output = {
        "protocols": results,
        "highest_regulatory_risk": highest,
        "lowest_regulatory_risk": lowest,
        "high_risk_count": high_risk_count,
        "average_risk_score": round(avg_score, 4),
        "timestamp": time.time(),
    }

    _log_result(output)
    return output


# ---------------------------------------------------------------------------
# Ring-buffer log
# ---------------------------------------------------------------------------

def _log_result(result: dict) -> None:
    """Append result to ring-buffer JSON log (max MAX_ENTRIES). Atomic write."""
    data_path = Path(DATA_FILE)
    data_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    if data_path.exists():
        try:
            with open(data_path) as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = []
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(result)
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]

    tmp = str(data_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, str(data_path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _init_data_file() -> None:
    """Ensure data file exists as empty list."""
    p = Path(DATA_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        tmp = str(p) + ".tmp"
        with open(tmp, "w") as f:
            json.dump([], f)
        os.replace(tmp, str(p))


if __name__ == "__main__":
    import argparse
    import sys

    _init_data_file()

    parser = argparse.ArgumentParser(
        description="MP-878 ProtocolRegulatoryRiskAssessor"
    )
    parser.add_argument("--check", action="store_true",
                        help="Run demo analysis and print")
    parser.add_argument("--run", action="store_true",
                        help="Run demo analysis and log")
    args = parser.parse_args()

    demo_protocols = [
        {
            "name": "Aave V3",
            "jurisdiction": "CAYMAN",
            "has_kyc": False,
            "token_type": "GOVERNANCE",
            "has_us_user_restriction": False,
            "team_is_doxxed": True,
            "has_received_sec_subpoena": False,
            "tvl_usd": 8_000_000_000,
            "centralized_components": 2,
            "has_legal_wrapper": True,
        },
        {
            "name": "Tornado Cash",
            "jurisdiction": "DECENTRALIZED",
            "has_kyc": False,
            "token_type": "GOVERNANCE",
            "has_us_user_restriction": False,
            "team_is_doxxed": True,
            "has_received_sec_subpoena": True,
            "tvl_usd": 300_000_000,
            "centralized_components": 0,
            "has_legal_wrapper": False,
        },
        {
            "name": "CoinBase Base Earn",
            "jurisdiction": "US",
            "has_kyc": True,
            "token_type": "STABLECOIN",
            "has_us_user_restriction": False,
            "team_is_doxxed": True,
            "has_received_sec_subpoena": False,
            "tvl_usd": 500_000_000,
            "centralized_components": 4,
            "has_legal_wrapper": True,
        },
    ]

    result = analyze(demo_protocols)
    print(json.dumps(result, indent=2))
    sys.exit(0)
