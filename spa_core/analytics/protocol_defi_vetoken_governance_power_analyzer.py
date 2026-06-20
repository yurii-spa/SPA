"""
MP-1013: ProtocolDeFiVetokenGovernancePowerAnalyzer
====================================================
Advisory-only analytics module.
Analyzes ve-token (vote-escrow) systems and governance power distribution
(Curve-style: CRV/veCRV, BAL/veBAL, etc.).

Computes: lock_participation_ratio, vetoken_yield_pct, bribe_to_emission_ratio,
governance_centralization_score, fee_to_bribe_ratio.

Governance labels: HEALTHY_DEMOCRACY / FUNCTIONAL / PLUTOCRATIC_RISK /
BRIBERY_DOMINATED / GOVERNANCE_CAPTURED / CLIFF_RISK

Flags: HIGH_PARTICIPATION, BRIBERY_ECONOMY, GOVERNANCE_ATTACK_HISTORY,
CLIFF_EXPIRY_RISK, STRONG_FEE_BACKING, PLUTOCRATIC

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/vetoken_governance_log.json
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
import math
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "vetoken_governance_log.json",
)
LOG_MAX_ENTRIES = 100

# Label thresholds
HEALTHY_LOCK_PCT = 50.0
HEALTHY_CENTRALIZATION_MAX = 30.0
PLUTOCRATIC_TOP10 = 60.0
PLUTOCRATIC_TOP1 = 20.0
BRIBERY_DOMINATED_RATIO = 1.0   # bribes >= emissions
GOVERNANCE_CAPTURED_CENTRALIZATION = 70.0
CLIFF_EXPIRY_THRESHOLD = 30.0

# Flag thresholds
HIGH_PARTICIPATION_LOCK = 60.0
BRIBERY_ECONOMY_THRESHOLD = 1.0    # bribes > fees
CLIFF_EXPIRY_FLAG_THRESHOLD = 25.0
STRONG_FEE_RATIO = 0.5             # fee >= 50% of emissions
PLUTOCRATIC_FLAG_TOP1 = 15.0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_system(system: dict, idx: int) -> None:
    """Validate required fields in a ve-token system dict."""
    required = {
        "name",
        "protocol",
        "total_token_supply",
        "tokens_locked_pct",
        "avg_lock_duration_years",
        "max_lock_duration_years",
        "token_price_usd",
        "weekly_emissions_usd",
        "fee_revenue_weekly_usd",
        "bribe_revenue_weekly_usd",
        "top_voter_share_pct",
        "top10_voter_share_pct",
        "governance_attacks_history",
        "lock_expiry_cliff_pct",
    }
    missing = required - set(system.keys())
    if missing:
        raise ValueError(
            f"System {idx} ('{system.get('name', '?')}') missing fields: {missing}"
        )
    if float(system["max_lock_duration_years"]) <= 0:
        raise ValueError(f"System {idx}: max_lock_duration_years must be > 0")
    if float(system["total_token_supply"]) <= 0:
        raise ValueError(f"System {idx}: total_token_supply must be > 0")


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _lock_participation_ratio(tokens_locked_pct: float) -> float:
    """tokens_locked_pct / 100 → 0..1"""
    return round(tokens_locked_pct / 100.0, 4)


def _vetoken_yield_pct(fee_revenue_weekly_usd: float,
                       bribe_revenue_weekly_usd: float,
                       tokens_locked_pct: float,
                       total_token_supply: float,
                       token_price_usd: float) -> float:
    """
    Annual veToken yield %.
    yield = (fee + bribe) * 52 / (locked_tokens_usd)
    locked_tokens_usd = tokens_locked_pct/100 * total_supply * price
    """
    locked_usd = (tokens_locked_pct / 100.0) * total_token_supply * token_price_usd
    if locked_usd <= 0:
        return 0.0
    annual = (fee_revenue_weekly_usd + bribe_revenue_weekly_usd) * 52.0
    return round((annual / locked_usd) * 100.0, 4)


def _bribe_to_emission_ratio(bribe_revenue_weekly_usd: float,
                              weekly_emissions_usd: float) -> float:
    """Bribe / Emissions weekly. >0.5 = bribery dominant."""
    if weekly_emissions_usd <= 0:
        return 0.0
    return round(bribe_revenue_weekly_usd / weekly_emissions_usd, 4)


def _governance_centralization_score(top10_voter_share_pct: float,
                                      governance_attacks_history: bool,
                                      lock_expiry_cliff_pct: float) -> float:
    """
    Centralization score 0-100.
    top10*0.6 + attack_history*30 + cliff_risk*0.1
    """
    score = (
        top10_voter_share_pct * 0.6
        + (30.0 if governance_attacks_history else 0.0)
        + lock_expiry_cliff_pct * 0.1
    )
    return round(min(100.0, max(0.0, score)), 2)


def _fee_to_bribe_ratio(fee_revenue_weekly_usd: float,
                         bribe_revenue_weekly_usd: float) -> float:
    """fee / bribe. Higher = more organic fee revenue vs bribery."""
    if bribe_revenue_weekly_usd <= 0:
        return float("inf") if fee_revenue_weekly_usd > 0 else 0.0
    return round(fee_revenue_weekly_usd / bribe_revenue_weekly_usd, 4)


# ---------------------------------------------------------------------------
# Governance label
# ---------------------------------------------------------------------------

def _governance_label(tokens_locked_pct: float,
                       centralization_score: float,
                       governance_attacks_history: bool,
                       top10_voter_share_pct: float,
                       top1_voter_share_pct: float,
                       bribe_to_emission: float,
                       lock_expiry_cliff_pct: float) -> str:
    """Classify governance health label."""
    # GOVERNANCE_CAPTURED: attacks AND highly centralized
    if governance_attacks_history and top10_voter_share_pct > GOVERNANCE_CAPTURED_CENTRALIZATION:
        return "GOVERNANCE_CAPTURED"
    # CLIFF_RISK: significant upcoming unlock concentration
    if lock_expiry_cliff_pct > CLIFF_EXPIRY_THRESHOLD:
        return "CLIFF_RISK"
    # BRIBERY_DOMINATED: bribes exceed emissions
    if bribe_to_emission >= BRIBERY_DOMINATED_RATIO:
        return "BRIBERY_DOMINATED"
    # PLUTOCRATIC_RISK
    if top10_voter_share_pct > PLUTOCRATIC_TOP10 or top1_voter_share_pct > PLUTOCRATIC_TOP1:
        return "PLUTOCRATIC_RISK"
    # HEALTHY_DEMOCRACY: good participation, low centralization, no attacks
    if (tokens_locked_pct >= HEALTHY_LOCK_PCT
            and centralization_score < HEALTHY_CENTRALIZATION_MAX
            and not governance_attacks_history):
        return "HEALTHY_DEMOCRACY"
    return "FUNCTIONAL"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def _compute_flags(tokens_locked_pct: float,
                   bribe_revenue_weekly_usd: float,
                   fee_revenue_weekly_usd: float,
                   governance_attacks_history: bool,
                   lock_expiry_cliff_pct: float,
                   weekly_emissions_usd: float,
                   top1_voter_share_pct: float) -> list:
    """Compute advisory flags for a ve-token system."""
    flags = []
    if tokens_locked_pct > HIGH_PARTICIPATION_LOCK:
        flags.append("HIGH_PARTICIPATION")
    if bribe_revenue_weekly_usd > fee_revenue_weekly_usd:
        flags.append("BRIBERY_ECONOMY")
    if governance_attacks_history:
        flags.append("GOVERNANCE_ATTACK_HISTORY")
    if lock_expiry_cliff_pct > CLIFF_EXPIRY_FLAG_THRESHOLD:
        flags.append("CLIFF_EXPIRY_RISK")
    if weekly_emissions_usd > 0 and fee_revenue_weekly_usd >= weekly_emissions_usd * STRONG_FEE_RATIO:
        flags.append("STRONG_FEE_BACKING")
    if top1_voter_share_pct > PLUTOCRATIC_FLAG_TOP1:
        flags.append("PLUTOCRATIC")
    return flags


# ---------------------------------------------------------------------------
# Per-system analysis
# ---------------------------------------------------------------------------

def _analyze_one(system: dict) -> dict:
    """Analyze a single ve-token system."""
    name = system["name"]
    protocol = system["protocol"]
    total_supply = float(system["total_token_supply"])
    tokens_locked_pct = float(system["tokens_locked_pct"])
    avg_lock_years = float(system["avg_lock_duration_years"])
    max_lock_years = float(system["max_lock_duration_years"])
    token_price = float(system["token_price_usd"])
    weekly_emissions = float(system["weekly_emissions_usd"])
    fee_weekly = float(system["fee_revenue_weekly_usd"])
    bribe_weekly = float(system["bribe_revenue_weekly_usd"])
    top1 = float(system["top_voter_share_pct"])
    top10 = float(system["top10_voter_share_pct"])
    attacks = bool(system["governance_attacks_history"])
    cliff_pct = float(system["lock_expiry_cliff_pct"])

    lock_ratio = _lock_participation_ratio(tokens_locked_pct)
    vetoken_yield = _vetoken_yield_pct(fee_weekly, bribe_weekly, tokens_locked_pct,
                                        total_supply, token_price)
    bribe_emission = _bribe_to_emission_ratio(bribe_weekly, weekly_emissions)
    centralization = _governance_centralization_score(top10, attacks, cliff_pct)
    fee_bribe = _fee_to_bribe_ratio(fee_weekly, bribe_weekly)
    label = _governance_label(
        tokens_locked_pct, centralization, attacks,
        top10, top1, bribe_emission, cliff_pct
    )
    flags = _compute_flags(
        tokens_locked_pct, bribe_weekly, fee_weekly,
        attacks, cliff_pct, weekly_emissions, top1
    )

    # Lock efficiency: avg / max (0..1)
    lock_efficiency = round(
        min(1.0, avg_lock_years / max_lock_years) if max_lock_years > 0 else 0.0,
        4
    )

    return {
        "name": name,
        "protocol": protocol,
        "lock_participation_ratio": lock_ratio,
        "vetoken_yield_pct": vetoken_yield,
        "bribe_to_emission_ratio": bribe_emission,
        "governance_centralization_score": centralization,
        "fee_to_bribe_ratio": fee_bribe,
        "lock_efficiency": lock_efficiency,
        "governance_label": label,
        "flags": flags,
        "tokens_locked_pct": tokens_locked_pct,
        "top_voter_share_pct": top1,
        "top10_voter_share_pct": top10,
        "lock_expiry_cliff_pct": cliff_pct,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class ProtocolDeFiVetokenGovernancePowerAnalyzer:
    """
    Analyzes ve-token governance power distribution across DeFi protocols.
    Advisory/read-only. No execution side-effects.
    """

    def analyze(self, vetoken_systems: list, config: Optional[dict] = None) -> dict:
        """
        Analyze governance power for a list of ve-token systems.

        Parameters
        ----------
        vetoken_systems : list[dict]
            Each dict must contain:
                name, protocol, total_token_supply, tokens_locked_pct,
                avg_lock_duration_years, max_lock_duration_years, token_price_usd,
                weekly_emissions_usd, fee_revenue_weekly_usd, bribe_revenue_weekly_usd,
                top_voter_share_pct, top10_voter_share_pct,
                governance_attacks_history (bool), lock_expiry_cliff_pct
        config : dict, optional
            Optional overrides (future use).

        Returns
        -------
        dict with keys:
            systems                  list[dict]  per-system results
            healthiest               str | None  name of healthiest system
            most_captured            str | None  name of most governance-captured
            avg_vetoken_yield        float
            healthy_democracy_count  int
            governance_captured_count int
            analyzed_at              str  ISO timestamp
        """
        if config is None:
            config = {}
        if not isinstance(vetoken_systems, list) or len(vetoken_systems) == 0:
            raise ValueError("vetoken_systems must be a non-empty list")

        for idx, s in enumerate(vetoken_systems):
            _validate_system(s, idx)

        results = []
        for s in vetoken_systems:
            results.append(_analyze_one(s))

        # Aggregates
        avg_yield = round(
            sum(r["vetoken_yield_pct"] for r in results) / len(results), 4
        )
        healthy_count = sum(
            1 for r in results if r["governance_label"] == "HEALTHY_DEMOCRACY"
        )
        captured_count = sum(
            1 for r in results if r["governance_label"] == "GOVERNANCE_CAPTURED"
        )

        # Healthiest: lowest centralization + highest participation
        sorted_healthy = sorted(
            results,
            key=lambda r: (r["governance_centralization_score"],
                           -r["lock_participation_ratio"])
        )
        healthiest = sorted_healthy[0]["name"] if sorted_healthy else None

        # Most captured: highest centralization score
        sorted_captured = sorted(
            results,
            key=lambda r: -r["governance_centralization_score"]
        )
        most_captured = sorted_captured[0]["name"] if sorted_captured else None

        output = {
            "systems": results,
            "healthiest": healthiest,
            "most_captured": most_captured,
            "avg_vetoken_yield": avg_yield,
            "healthy_democracy_count": healthy_count,
            "governance_captured_count": captured_count,
            "analyzed_at": _iso_now(),
        }

        _append_log(output)
        return output


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
def _init_log(path: str) -> list:
    """Load existing log or return empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict, log_path: str = LOG_PATH) -> None:
    """Append result snapshot to ring-buffer log (capped at LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    snapshot = {
        "ts": result.get("analyzed_at", _iso_now()),
        "system_count": len(result.get("systems", [])),
        "avg_vetoken_yield": result.get("avg_vetoken_yield"),
        "healthy_democracy_count": result.get("healthy_democracy_count"),
        "governance_captured_count": result.get("governance_captured_count"),
        "healthiest": result.get("healthiest"),
        "most_captured": result.get("most_captured"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(vetoken_systems: list, config: Optional[dict] = None) -> dict:
    """Module-level shorthand — delegates to ProtocolDeFiVetokenGovernancePowerAnalyzer."""
    return ProtocolDeFiVetokenGovernancePowerAnalyzer().analyze(vetoken_systems, config)
