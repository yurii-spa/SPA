"""
MP-874: ProtocolPonziRiskScreener
===================================
Advisory-only analytics module.
Screens DeFi protocols for Ponzi-like risk characteristics — unsustainably high
yields paid primarily by new user deposits rather than real economic activity.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/ponzi_risk_log.json.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
import tempfile
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "ponzi_risk_log.json",
)
LOG_MAX_ENTRIES = 100

# Risk classification thresholds
_CLASS_EXIT_SCAM = 80
_CLASS_PONZI = 60
_CLASS_INFLATED = 40
_CLASS_WATCH = 20


# ---------------------------------------------------------------------------
# Score sub-components
# ---------------------------------------------------------------------------

def _yield_coverage_ratio(fee_revenue_30d: float, yield_paid_30d: float) -> float:
    """fee_revenue / yield_paid; 0.0 if yield_paid == 0."""
    if yield_paid_30d <= 0:
        return 0.0
    return fee_revenue_30d / yield_paid_30d


def _emission_dependency_pct(
    token_emission_apy: float, advertised_apy: float
) -> float:
    """token_emission_apy / advertised_apy * 100; 0.0 if advertised == 0."""
    if advertised_apy <= 0:
        return 0.0
    return token_emission_apy / advertised_apy * 100.0


def _new_deposit_reliance(
    new_deposits_30d: float, yield_paid_30d: float
) -> float:
    """new_deposits_30d / (yield_paid_30d * 12); 0.0 if yield_paid == 0."""
    if yield_paid_30d <= 0:
        return 0.0
    return new_deposits_30d / (yield_paid_30d * 12.0)


def _sustainability_score(
    yield_coverage_ratio: float, yield_paid_30d: float
) -> int:
    """
    0-40 — higher = SAFER (real revenue covers more of yield).

    If yield_paid_30d == 0: 40 (no yield = not a Ponzi).
    """
    if yield_paid_30d <= 0:
        return 40

    ratio = yield_coverage_ratio
    if ratio >= 1.5:
        return 40
    if ratio >= 1.0:
        return 30
    if ratio >= 0.75:
        return 20
    if ratio >= 0.5:
        return 10
    if ratio >= 0.25:
        return 5
    return 0


def _emission_risk_score(emission_dependency_pct: float) -> int:
    """
    0-30 — higher = MORE RISKY (direct risk contribution).
    emission_dependency_pct: % of yield from token emissions.
    """
    dep = emission_dependency_pct
    if dep >= 80:
        return 30
    if dep >= 60:
        return 24
    if dep >= 40:
        return 16
    if dep >= 20:
        return 8
    return 0


def _structural_risk_score(
    team_allocation_pct: float,
    tvl_change_30d_pct: float,
    new_deposit_reliance: float,
) -> int:
    """
    0-30 — higher = MORE RISKY (structural warning signs).
    Capped at 30.
    """
    score = 0

    # Team allocation component
    if team_allocation_pct >= 30:
        score += 15
    elif team_allocation_pct >= 20:
        score += 10
    elif team_allocation_pct >= 10:
        score += 5

    # TVL fleeing
    if tvl_change_30d_pct < -20:
        score += 10

    # New deposit reliance (Ponzi structure)
    if new_deposit_reliance >= 2.0:
        score += 5

    return min(score, 30)


def _ponzi_risk_score(
    emission_risk: int,
    structural_risk: int,
    sustainability: int,
) -> int:
    """
    Combined score 0-100. Higher = more Ponzi-like.
    ponzi_risk = emission_risk + structural_risk + (40 - sustainability)
    (Lower sustainability → higher risk contribution.)
    """
    return min(100, emission_risk + structural_risk + (40 - sustainability))


def _classify(score: int) -> str:
    if score >= _CLASS_EXIT_SCAM:
        return "EXIT_SCAM_RISK"
    if score >= _CLASS_PONZI:
        return "PONZI_RISK"
    if score >= _CLASS_INFLATED:
        return "YIELD_INFLATED"
    if score >= _CLASS_WATCH:
        return "WATCH"
    return "LEGITIMATE"


def _warning_signals(
    emission_dep_pct: float,
    yield_coverage: float,
    yield_paid_30d: float,
    team_allocation_pct: float,
    tvl_change_30d_pct: float,
    new_deposit_reliance_pct: float,
    advertised_apy_pct: float,
) -> list:
    signals = []

    if emission_dep_pct >= 80:
        signals.append("Yield >80% from token emissions")

    if yield_coverage < 0.3 and yield_paid_30d > 0:
        signals.append("Fee revenue covers <30% of yield payouts")

    if team_allocation_pct >= 25:
        signals.append(
            f"Team takes {team_allocation_pct:.0f}% of revenue/tokens"
        )

    if tvl_change_30d_pct <= -25:
        signals.append("TVL declining >25% in 30d — capital fleeing")

    if new_deposit_reliance_pct >= 1.5:
        signals.append("Yield primarily funded by new deposits (Ponzi structure)")

    if advertised_apy_pct >= 50:
        signals.append(
            f"Unsustainable headline APY of {advertised_apy_pct:.0f}%"
        )

    if not signals:
        signals = ["No Ponzi risk signals detected"]

    return signals


def _recommendation(
    classification: str,
    name: str,
    emission_dep_pct: float,
    verified_fee_apy: float,
    yield_coverage: float,
) -> str:
    if classification == "EXIT_SCAM_RISK":
        return (
            f"IMMEDIATE EXIT. {name} shows multiple exit scam signals. Withdraw now."
        )
    if classification == "PONZI_RISK":
        return (
            f"HIGH RISK. {name} appears Ponzi-like. "
            f"{emission_dep_pct:.0f}% yield from emissions."
        )
    if classification == "YIELD_INFLATED":
        return (
            f"Yield inflated by token emissions. Real yield ~{verified_fee_apy:.1f}%."
        )
    if classification == "WATCH":
        return f"Monitor {name}. Some unsustainable yield characteristics."
    # LEGITIMATE
    return f"{name} appears sustainable. {yield_coverage:.2f}x fee revenue coverage."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Screen DeFi protocols for Ponzi-like risk characteristics.

    Parameters
    ----------
    protocols : list[dict]
        Each element:
            name                    : str
            advertised_apy_pct      : float
            verified_fee_revenue_apy_pct : float
            token_emission_apy_pct  : float
            new_deposits_30d_usd    : float
            total_tvl_usd           : float
            yield_paid_30d_usd      : float
            fee_revenue_30d_usd     : float
            team_allocation_pct     : float
            tvl_change_30d_pct      : float

    config : dict | None  (unused; reserved for future thresholds)

    Returns
    -------
    dict  (see module docstring for full schema)
    """
    if not protocols:
        result = {
            "protocols": [],
            "highest_risk": None,
            "safest": None,
            "ponzi_risk_protocols": [],
            "average_ponzi_score": 0.0,
            "timestamp": time.time(),
        }
        _append_log(result)
        return result

    processed = []
    for p in protocols:
        name = p.get("name", "")
        advertised_apy = float(p.get("advertised_apy_pct", 0.0))
        verified_fee_apy = float(p.get("verified_fee_revenue_apy_pct", 0.0))
        emission_apy = float(p.get("token_emission_apy_pct", 0.0))
        new_deposits = float(p.get("new_deposits_30d_usd", 0.0))
        yield_paid = float(p.get("yield_paid_30d_usd", 0.0))
        fee_revenue = float(p.get("fee_revenue_30d_usd", 0.0))
        team_alloc = float(p.get("team_allocation_pct", 0.0))
        tvl_change = float(p.get("tvl_change_30d_pct", 0.0))

        # Derived metrics
        ycr = _yield_coverage_ratio(fee_revenue, yield_paid)
        edp = _emission_dependency_pct(emission_apy, advertised_apy)
        ndr = _new_deposit_reliance(new_deposits, yield_paid)

        # Scores
        sus_score = _sustainability_score(ycr, yield_paid)
        em_score = _emission_risk_score(edp)
        str_score = _structural_risk_score(team_alloc, tvl_change, ndr)
        risk_score = _ponzi_risk_score(em_score, str_score, sus_score)

        # Classification
        classification = _classify(risk_score)

        # Signals & recommendation
        signals = _warning_signals(
            edp, ycr, yield_paid, team_alloc, tvl_change, ndr, advertised_apy
        )
        rec = _recommendation(classification, name, edp, verified_fee_apy, ycr)

        processed.append(
            {
                "name": name,
                "ponzi_risk_score": risk_score,
                "risk_classification": classification,
                "yield_coverage_ratio": round(ycr, 6),
                "emission_dependency_pct": round(edp, 6),
                "new_deposit_reliance_pct": round(ndr, 6),
                "sustainability_score": sus_score,
                "emission_risk_score": em_score,
                "structural_risk_score": str_score,
                "warning_signals": signals,
                "recommendation": rec,
            }
        )

    # Summary
    highest = max(processed, key=lambda x: x["ponzi_risk_score"])["name"]
    safest = min(processed, key=lambda x: x["ponzi_risk_score"])["name"]

    ponzi_protocols = [
        p["name"]
        for p in processed
        if p["risk_classification"] in ("PONZI_RISK", "EXIT_SCAM_RISK")
    ]

    scores = [p["ponzi_risk_score"] for p in processed]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    result = {
        "protocols": processed,
        "highest_risk": highest,
        "safest": safest,
        "ponzi_risk_protocols": ponzi_protocols,
        "average_ponzi_score": round(avg_score, 6),
        "timestamp": time.time(),
    }
    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Log management
# ---------------------------------------------------------------------------

def _append_log(entry: dict) -> None:
    """Atomically append result entry to ring-buffer log (max 100)."""
    log_dir = os.path.dirname(LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)

    existing = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    existing = existing[-LOG_MAX_ENTRIES:]

    tmp_fd, tmp_path = tempfile.mkstemp(dir=log_dir, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp_path, LOG_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def init_log() -> None:
    """Initialize the log file as an empty list if it doesn't exist."""
    log_dir = os.path.dirname(LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)
    if not os.path.exists(LOG_PATH):
        tmp_fd, tmp_path = tempfile.mkstemp(dir=log_dir, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                json.dump([], fh)
            os.replace(tmp_path, LOG_PATH)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    init_log()

    sample = [
        {
            "name": "LegitProtocol",
            "advertised_apy_pct": 8.0,
            "verified_fee_revenue_apy_pct": 7.5,
            "token_emission_apy_pct": 0.5,
            "new_deposits_30d_usd": 1_000_000,
            "total_tvl_usd": 50_000_000,
            "yield_paid_30d_usd": 333_000,
            "fee_revenue_30d_usd": 350_000,
            "team_allocation_pct": 5.0,
            "tvl_change_30d_pct": 2.0,
        },
        {
            "name": "SuspectProtocol",
            "advertised_apy_pct": 300.0,
            "verified_fee_revenue_apy_pct": 0.5,
            "token_emission_apy_pct": 299.5,
            "new_deposits_30d_usd": 10_000_000,
            "total_tvl_usd": 5_000_000,
            "yield_paid_30d_usd": 1_000_000,
            "fee_revenue_30d_usd": 5_000,
            "team_allocation_pct": 40.0,
            "tvl_change_30d_pct": -30.0,
        },
    ]

    result = analyze(sample)
    print(json.dumps(result, indent=2))
    sys.exit(0)
