"""
MP-866 ProtocolSmartContractAgeScorer
Advisory/read-only analytics module.
Scores smart contract battle-testing based on age, TVL exposure, historical incidents,
and code upgrade frequency. Pure stdlib. Atomic writes via tmp + os.replace.
"""
import json
import os
import time
from typing import Any

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "smart_contract_age_log.json")
_LOG_CAP = 100


def _age_score(contract_age_days: int) -> int:
    if contract_age_days >= 1460:
        return 25
    elif contract_age_days >= 730:
        return 20
    elif contract_age_days >= 365:
        return 15
    elif contract_age_days >= 180:
        return 10
    elif contract_age_days >= 90:
        return 5
    else:
        return 0


def _tvl_stress_score(peak_tvl_usd: float) -> int:
    if peak_tvl_usd >= 1_000_000_000:
        return 25
    elif peak_tvl_usd >= 100_000_000:
        return 20
    elif peak_tvl_usd >= 10_000_000:
        return 15
    elif peak_tvl_usd >= 1_000_000:
        return 8
    elif peak_tvl_usd >= 100_000:
        return 3
    else:
        return 0


def _incident_score(exploit_count: int, exploit_loss_ratio: float) -> int:
    if exploit_count == 0:
        raw = 25
    elif exploit_count == 1 and exploit_loss_ratio < 0.01:
        raw = 15
    elif exploit_count == 1:
        raw = 10
    elif exploit_count == 2:
        raw = 5
    else:  # >= 3
        raw = 0

    # Apply exploit_loss_ratio penalty
    if exploit_loss_ratio >= 0.5:
        raw -= 10
    elif exploit_loss_ratio >= 0.25:
        raw -= 5

    return max(0, raw)


def _stability_score(upgrade_count: int, last_upgrade_days_ago: int) -> int:
    if upgrade_count == 0:
        return 25
    elif upgrade_count == 1 and last_upgrade_days_ago >= 365:
        return 20
    elif upgrade_count <= 3 and last_upgrade_days_ago >= 180:
        return 15
    elif upgrade_count <= 5 and last_upgrade_days_ago >= 90:
        return 10
    elif upgrade_count <= 10:
        return 5
    else:
        # upgrade_count > 10 OR last_upgrade_days_ago < 30
        return 0


def _stability_score_full(upgrade_count: int, last_upgrade_days_ago: int) -> int:
    """Handle the OR condition: upgrade_count > 10 OR last_upgrade_days_ago < 30."""
    if upgrade_count == 0:
        return 25
    elif upgrade_count == 1 and last_upgrade_days_ago >= 365:
        return 20
    elif upgrade_count <= 3 and last_upgrade_days_ago >= 180:
        return 15
    elif upgrade_count <= 5 and last_upgrade_days_ago >= 90:
        return 10
    elif upgrade_count > 10 or last_upgrade_days_ago < 30:
        return 0
    else:
        # upgrade_count <= 10 (and last_upgrade_days_ago >= 30, but didn't match earlier brackets)
        return 5


def _safety_grade(score: int) -> str:
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 65:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 30:
        return "D"
    else:
        return "F"


def _battle_test_label(score: int) -> str:
    if score >= 80:
        return "BATTLE_TESTED"
    elif score >= 60:
        return "PROVEN"
    elif score >= 40:
        return "MATURING"
    elif score >= 20:
        return "YOUNG"
    else:
        return "UNPROVEN"


def _complexity_risk(lines_of_code: int) -> str:
    if lines_of_code >= 10000:
        return "HIGH"
    elif lines_of_code >= 3000:
        return "MEDIUM"
    else:
        return "LOW"


def _compute_contract(contract: dict) -> dict:
    protocol = contract.get("protocol", "")
    contract_age_days = int(contract.get("contract_age_days", 0))
    peak_tvl_usd = float(contract.get("peak_tvl_usd", 0.0))
    current_tvl_usd = float(contract.get("current_tvl_usd", 0.0))
    exploit_count = int(contract.get("exploit_count", 0))
    exploit_total_loss_usd = float(contract.get("exploit_total_loss_usd", 0.0))
    upgrade_count = int(contract.get("upgrade_count", 0))
    last_upgrade_days_ago = int(contract.get("last_upgrade_days_ago", 0))
    formal_verification = bool(contract.get("formal_verification", False))
    lines_of_code = int(contract.get("lines_of_code", 0))

    # exploit_loss_ratio
    if peak_tvl_usd > 0:
        exploit_loss_ratio = exploit_total_loss_usd / peak_tvl_usd
    else:
        exploit_loss_ratio = 0.0

    # Scores
    a_score = _age_score(contract_age_days)
    t_score = _tvl_stress_score(peak_tvl_usd)
    i_score = _incident_score(exploit_count, exploit_loss_ratio)
    s_score = _stability_score_full(upgrade_count, last_upgrade_days_ago)

    battle_test_score = min(100, a_score + t_score + i_score + s_score)
    if formal_verification:
        battle_test_score = min(100, battle_test_score + 5)

    grade = _safety_grade(battle_test_score)
    label = _battle_test_label(battle_test_score)
    c_risk = _complexity_risk(lines_of_code)
    is_heavily_audited = formal_verification

    summary = (
        f"{protocol}: {label} ({grade}), {contract_age_days}d old, "
        f"{exploit_count} exploits, {upgrade_count} upgrades"
    )

    return {
        "protocol": protocol,
        "battle_test_score": battle_test_score,
        "safety_grade": grade,
        "age_score": a_score,
        "tvl_stress_score": t_score,
        "incident_score": i_score,
        "stability_score": s_score,
        "exploit_loss_ratio": exploit_loss_ratio,
        "is_heavily_audited": is_heavily_audited,
        "complexity_risk": c_risk,
        "battle_test_label": label,
        "summary": summary,
    }


def analyze(contracts: list, config: dict = None) -> dict:
    """
    Analyze smart contracts for battle-test safety scoring.

    contracts: list of dicts with protocol, contract_age_days, peak_tvl_usd, current_tvl_usd,
               exploit_count, exploit_total_loss_usd, upgrade_count, last_upgrade_days_ago,
               formal_verification, lines_of_code
    config: unused (reserved for future extension)

    Returns dict with per-contract scores and aggregate statistics.
    """
    if not contracts:
        return {
            "contracts": [],
            "safest_protocol": None,
            "riskiest_protocol": None,
            "battle_tested_count": 0,
            "average_score": 0.0,
            "timestamp": time.time(),
        }

    analyzed = [_compute_contract(c) for c in contracts]

    safest = max(analyzed, key=lambda c: c["battle_test_score"])
    riskiest = min(analyzed, key=lambda c: c["battle_test_score"])

    battle_tested_count = sum(
        1 for c in analyzed if c["battle_test_label"] in ("BATTLE_TESTED", "PROVEN")
    )

    average_score = sum(c["battle_test_score"] for c in analyzed) / len(analyzed)

    return {
        "contracts": analyzed,
        "safest_protocol": safest["protocol"],
        "riskiest_protocol": riskiest["protocol"],
        "battle_tested_count": battle_tested_count,
        "average_score": average_score,
        "timestamp": time.time(),
    }


def log_result(result: dict, log_path: str = None) -> None:
    """Append result to ring-buffer JSON log (cap 100). Atomic write."""
    path = log_path or _LOG_PATH
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with open(path, "r") as f:
            log = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, path)


if __name__ == "__main__":
    import sys

    sample_contracts = [
        {
            "protocol": "Aave V3",
            "contract_age_days": 900,
            "peak_tvl_usd": 12_000_000_000,
            "current_tvl_usd": 9_000_000_000,
            "exploit_count": 0,
            "exploit_total_loss_usd": 0.0,
            "upgrade_count": 2,
            "last_upgrade_days_ago": 400,
            "formal_verification": True,
            "lines_of_code": 8500,
        },
        {
            "protocol": "Compound V3",
            "contract_age_days": 500,
            "peak_tvl_usd": 3_500_000_000,
            "current_tvl_usd": 1_800_000_000,
            "exploit_count": 1,
            "exploit_total_loss_usd": 80_000_000,
            "upgrade_count": 5,
            "last_upgrade_days_ago": 200,
            "formal_verification": False,
            "lines_of_code": 5000,
        },
        {
            "protocol": "Morpho",
            "contract_age_days": 400,
            "peak_tvl_usd": 800_000_000,
            "current_tvl_usd": 600_000_000,
            "exploit_count": 0,
            "exploit_total_loss_usd": 0.0,
            "upgrade_count": 1,
            "last_upgrade_days_ago": 380,
            "formal_verification": True,
            "lines_of_code": 2000,
        },
    ]

    result = analyze(sample_contracts)
    print(json.dumps(result, indent=2))

    if "--run" in sys.argv:
        log_result(result)
        print("\nResult logged to", _LOG_PATH)
