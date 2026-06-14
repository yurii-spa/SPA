"""
MP-898 ProtocolEconomicAttackSimulator
Advisory/read-only analytics module.
Simulates economic attack vectors (flash loans, oracle manipulation,
governance attacks) to assess protocol vulnerability.

Usage:
    from spa_core.analytics.protocol_economic_attack_simulator import analyze
    result = analyze(protocols, config)

Pure stdlib. No external dependencies. Advisory only — no on-chain writes.
"""

import json
import os
import time
import tempfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "attack_simulation_log.json"
)
_LOG_CAP = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _governance_attack_cost(
    majority_threshold_pct: float,
    circulating_supply: float,
    governance_token_price_usd: float,
) -> float:
    """Cost (USD) to acquire enough tokens for majority governance control."""
    return (majority_threshold_pct / 100.0) * circulating_supply * governance_token_price_usd


def _flash_loan_feasibility(governance_attack_cost_usd: float) -> str:
    if governance_attack_cost_usd < 100_000:
        return "TRIVIAL"
    if governance_attack_cost_usd < 1_000_000:
        return "FEASIBLE"
    if governance_attack_cost_usd < 10_000_000:
        return "EXPENSIVE"
    return "IMPRACTICAL"


def _oracle_vulnerability(oracle_attack_cost_10pct: float) -> str:
    if oracle_attack_cost_10pct < 100_000:
        return "CRITICAL"
    if oracle_attack_cost_10pct < 1_000_000:
        return "HIGH"
    if oracle_attack_cost_10pct < 10_000_000:
        return "MODERATE"
    return "LOW"


def _timelock_protection(time_lock_hours: int) -> str:
    if time_lock_hours == 0:
        return "NONE"
    if time_lock_hours < 24:
        return "WEAK"
    if time_lock_hours < 72:
        return "MODERATE"
    if time_lock_hours < 168:
        return "STRONG"
    return "VERY_STRONG"


def _economic_security_score(
    flash_loan_feasibility: str,
    oracle_vuln: str,
    timelock: str,
    has_flash_loan_guard: bool,
    avg_block_governance_votes: int,
) -> int:
    """Compute 0-100 economic security score; higher = more secure."""
    gov_scores = {
        "IMPRACTICAL": 40,
        "EXPENSIVE": 30,
        "FEASIBLE": 15,
        "TRIVIAL": 0,
    }
    oracle_scores = {
        "LOW": 25,
        "MODERATE": 18,
        "HIGH": 8,
        "CRITICAL": 0,
    }
    timelock_scores = {
        "VERY_STRONG": 20,
        "STRONG": 15,
        "MODERATE": 10,
        "WEAK": 5,
        "NONE": 0,
    }

    governance_score = gov_scores.get(flash_loan_feasibility, 0)
    oracle_score = oracle_scores.get(oracle_vuln, 0)
    timelock_score = timelock_scores.get(timelock, 0)
    flash_guard_score = 10 if has_flash_loan_guard else 0
    block_vote_score = min(5, int(avg_block_governance_votes / 100))

    total = governance_score + oracle_score + timelock_score + flash_guard_score + block_vote_score
    return max(0, min(100, total))


def _attack_surface_label(score: int) -> str:
    if score >= 80:
        return "MINIMAL"
    if score >= 65:
        return "LOW"
    if score >= 50:
        return "MODERATE"
    if score >= 35:
        return "HIGH"
    return "CRITICAL"


def _build_recommendation(
    surface: str,
    governance_cost: float,
    flags: list,
) -> str:
    if surface in ("MINIMAL", "LOW"):
        return (
            f"Well-secured protocol. Attack cost: "
            f"${governance_cost:,.0f} for governance."
        )
    if surface == "MODERATE":
        flag_str = ", ".join(flags[:2]) if flags else "review config"
        return f"Moderate security. Address: {flag_str}."
    if surface == "HIGH":
        return f"High attack surface. {len(flags)} vulnerabilities. Limit exposure."
    # CRITICAL
    flag_str = ", ".join(flags) if flags else "very low scores"
    return f"Critical security risk. {flag_str}. Avoid."


def _atomic_log(entry: dict, log_path: str = _LOG_PATH) -> None:
    """Append entry to ring-buffer JSON log (capped at _LOG_CAP). Atomic write."""
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            if not isinstance(records, list):
                records = []
        else:
            records = []
        records.append(entry)
        records = records[-_LOG_CAP:]
        dir_name = os.path.dirname(log_path)
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, encoding="utf-8", suffix=".tmp"
        ) as tf:
            json.dump(records, tf, indent=2)
            tmp_path = tf.name
        os.replace(tmp_path, log_path)
    except Exception:
        # Advisory module — never raise on log failure
        pass


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Advisory simulation of economic attack vectors on DeFi protocols.

    Parameters
    ----------
    protocols : list of dict
        Each dict must contain:
            name, tvl_usd, governance_token_price_usd, circulating_supply,
            majority_threshold_pct, flash_loan_fee_pct,
            oracle_manipulation_cost_usd, time_lock_hours,
            has_flash_loan_guard, avg_block_governance_votes
    config : dict, optional
        (reserved for future extension)

    Returns
    -------
    dict with keys:
        protocols, most_secure, most_vulnerable,
        average_security_score, critical_count, timestamp
    """
    assessed = []

    for p in protocols:
        name = p.get("name", "")
        governance_price = float(p.get("governance_token_price_usd", 0.0))
        circ_supply = float(p.get("circulating_supply", 0.0))
        majority_pct = float(p.get("majority_threshold_pct", 50.0))
        oracle_cost_1pct = float(p.get("oracle_manipulation_cost_usd", 0.0))
        time_lock = int(p.get("time_lock_hours", 0))
        has_guard = bool(p.get("has_flash_loan_guard", False))
        avg_votes = int(p.get("avg_block_governance_votes", 0))

        # ── Derived metrics ──────────────────────────────────────────────
        gov_cost = _governance_attack_cost(majority_pct, circ_supply, governance_price)
        feasibility = _flash_loan_feasibility(gov_cost)
        oracle_cost_10pct = oracle_cost_1pct * 10.0
        oracle_vuln = _oracle_vulnerability(oracle_cost_10pct)
        timelock = _timelock_protection(time_lock)

        sec_score = _economic_security_score(
            feasibility, oracle_vuln, timelock, has_guard, avg_votes
        )
        surface = _attack_surface_label(sec_score)

        # ── Flags ────────────────────────────────────────────────────────
        flags: list = []
        if not has_guard:
            flags.append("FLASH_LOAN_VULNERABLE")
        if feasibility in ("TRIVIAL", "FEASIBLE"):
            flags.append("CHEAP_GOVERNANCE_ATTACK")
        if oracle_vuln in ("CRITICAL", "HIGH"):
            flags.append("ORACLE_VULNERABLE")
        if time_lock == 0:
            flags.append("NO_TIMELOCK")

        recommendation = _build_recommendation(surface, gov_cost, flags)

        assessed.append({
            "name": name,
            "governance_attack_cost_usd": round(gov_cost, 2),
            "flash_loan_attack_feasibility": feasibility,
            "flash_loan_blocked": has_guard,
            "oracle_attack_cost_10pct_usd": round(oracle_cost_10pct, 2),
            "oracle_vulnerability": oracle_vuln,
            "timelock_protection": timelock,
            "economic_security_score": sec_score,
            "attack_surface_label": surface,
            "flags": flags,
            "recommendation": recommendation,
        })

    # ── Summary ──────────────────────────────────────────────────────────
    most_secure = None
    most_vulnerable = None
    avg_score = 0.0
    critical_count = 0

    if assessed:
        most_secure = max(assessed, key=lambda x: x["economic_security_score"])["name"]
        most_vulnerable = min(assessed, key=lambda x: x["economic_security_score"])["name"]
        avg_score = sum(x["economic_security_score"] for x in assessed) / len(assessed)
        critical_count = sum(1 for x in assessed if x["attack_surface_label"] == "CRITICAL")

    result = {
        "protocols": assessed,
        "most_secure": most_secure,
        "most_vulnerable": most_vulnerable,
        "average_security_score": round(avg_score, 6),
        "critical_count": critical_count,
        "timestamp": time.time(),
    }

    _atomic_log({
        "timestamp": result["timestamp"],
        "protocol_count": len(assessed),
        "most_secure": most_secure,
        "most_vulnerable": most_vulnerable,
        "average_security_score": result["average_security_score"],
        "critical_count": critical_count,
    })

    return result
