"""
MP-752: FlashLoanRiskDetector
Advisory/read-only analytics module. Pure stdlib. Atomic JSON writes.

Detects protocols with elevated flash loan attack risk by analyzing:
- Oracle dependencies and centralization
- Price manipulation surface (TVL concentration + price impact)
- Historical manipulation patterns
Scores protocols on attack susceptibility 0-100.
"""

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Data directory (relative to repo root, two levels up from this file)
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "flash_loan_risk_log.json")
_RING_CAP = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FlashLoanRiskProfile:
    protocol: str

    # Risk inputs (each 0-100)
    oracle_centralization: float    # 100 = single oracle, 0 = decentralized
    tvl_concentration_pct: float    # % of TVL in single asset
    price_impact_at_1m_usd: float   # % price impact for $1M trade
    has_price_manipulation_history: bool
    uses_twap: bool                 # True = uses TWAP oracles

    # Computed component scores (0-100)
    oracle_risk_score: float
    manipulation_surface_score: float
    history_risk_score: float

    # Composite score
    flash_loan_risk_score: float    # 0-100

    risk_label: str                 # MINIMAL | LOW | MODERATE | HIGH | CRITICAL
    max_safe_exposure_usd: float
    is_safe_for_deployment: bool
    recommendation: str


@dataclass
class FlashLoanRiskResult:
    profiles: List[FlashLoanRiskProfile]
    safest_protocol: str
    riskiest_protocol: str
    safe_for_deployment_count: int
    avg_risk_score: float
    market_risk_label: str          # SAFE_MARKET | CAUTION_MARKET | DANGER_MARKET
    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Core scoring functions
# ---------------------------------------------------------------------------

def compute_oracle_risk(oracle_centralization: float, uses_twap: bool) -> float:
    """oracle_centralization * 0.8 + (0 if uses_twap else 20), clamped 0-100."""
    raw = oracle_centralization * 0.8 + (0.0 if uses_twap else 20.0)
    return max(0.0, min(100.0, raw))


def compute_manipulation_surface(tvl_concentration_pct: float,
                                  price_impact_at_1m_usd: float) -> float:
    """tvl_concentration_pct * 0.5 + price_impact_at_1m_usd * 0.5, clamped 0-100."""
    raw = tvl_concentration_pct * 0.5 + price_impact_at_1m_usd * 0.5
    return max(0.0, min(100.0, raw))


def compute_history_risk(has_history: bool) -> float:
    """100 if has_history else 0."""
    return 100.0 if has_history else 0.0


def compute_flash_loan_risk(oracle_risk: float,
                             manipulation_surface: float,
                             history_risk: float) -> float:
    """0.35*oracle + 0.35*manipulation + 0.30*history, clamped 0-100."""
    raw = 0.35 * oracle_risk + 0.35 * manipulation_surface + 0.30 * history_risk
    return max(0.0, min(100.0, raw))


def risk_label(score: float) -> str:
    """MINIMAL (<20) | LOW (20-40) | MODERATE (40-60) | HIGH (60-80) | CRITICAL (>=80)."""
    if score < 20:
        return "MINIMAL"
    if score < 40:
        return "LOW"
    if score < 60:
        return "MODERATE"
    if score < 80:
        return "HIGH"
    return "CRITICAL"


def max_safe_exposure(risk_score: float) -> float:
    """1_000_000 * (1 - risk_score / 100)."""
    return 1_000_000.0 * (1.0 - risk_score / 100.0)


def _recommendation_text(label: str) -> str:
    if label == "CRITICAL":
        return "CRITICAL: Do not deploy. Extreme flash loan attack risk."
    if label == "HIGH":
        return "HIGH RISK: Flash loan exploit possible. Avoid unless hedged."
    if label == "MODERATE":
        return "Moderate risk. Use TWAP oracles if available."
    return "Acceptable risk. Safe for standard deployment."


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

def profile_protocol(
    protocol: str,
    oracle_centralization: float,
    tvl_concentration_pct: float,
    price_impact_at_1m_usd: float,
    has_history: bool,
    uses_twap: bool,
) -> FlashLoanRiskProfile:
    """Build a FlashLoanRiskProfile for one protocol."""
    o_risk = compute_oracle_risk(oracle_centralization, uses_twap)
    m_surface = compute_manipulation_surface(tvl_concentration_pct, price_impact_at_1m_usd)
    h_risk = compute_history_risk(has_history)
    fl_risk = compute_flash_loan_risk(o_risk, m_surface, h_risk)
    label = risk_label(fl_risk)
    exposure = max_safe_exposure(fl_risk)
    safe = fl_risk < 60.0
    rec = _recommendation_text(label)

    return FlashLoanRiskProfile(
        protocol=protocol,
        oracle_centralization=oracle_centralization,
        tvl_concentration_pct=tvl_concentration_pct,
        price_impact_at_1m_usd=price_impact_at_1m_usd,
        has_price_manipulation_history=has_history,
        uses_twap=uses_twap,
        oracle_risk_score=o_risk,
        manipulation_surface_score=m_surface,
        history_risk_score=h_risk,
        flash_loan_risk_score=fl_risk,
        risk_label=label,
        max_safe_exposure_usd=exposure,
        is_safe_for_deployment=safe,
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Aggregate detector
# ---------------------------------------------------------------------------

def detect_risks(protocols_data: List[Dict[str, Any]]) -> FlashLoanRiskResult:
    """
    Compute flash loan risk profiles for a list of protocols.

    Each entry in protocols_data should have keys:
        protocol, oracle_centralization, tvl_concentration_pct,
        price_impact_at_1m_usd, has_price_manipulation_history, uses_twap
    """
    profiles: List[FlashLoanRiskProfile] = []
    for pd in protocols_data:
        p = profile_protocol(
            protocol=pd["protocol"],
            oracle_centralization=float(pd["oracle_centralization"]),
            tvl_concentration_pct=float(pd["tvl_concentration_pct"]),
            price_impact_at_1m_usd=float(pd["price_impact_at_1m_usd"]),
            has_history=bool(pd["has_price_manipulation_history"]),
            uses_twap=bool(pd["uses_twap"]),
        )
        profiles.append(p)

    if not profiles:
        return FlashLoanRiskResult(
            profiles=[],
            safest_protocol="N/A",
            riskiest_protocol="N/A",
            safe_for_deployment_count=0,
            avg_risk_score=0.0,
            market_risk_label="SAFE_MARKET",
            recommendation_summary="No protocols to evaluate.",
            saved_to="",
        )

    scores = [p.flash_loan_risk_score for p in profiles]
    safest = profiles[scores.index(min(scores))].protocol
    riskiest = profiles[scores.index(max(scores))].protocol
    safe_count = sum(1 for p in profiles if p.is_safe_for_deployment)
    avg_score = sum(scores) / len(scores)

    if avg_score < 30:
        mrl = "SAFE_MARKET"
    elif avg_score < 60:
        mrl = "CAUTION_MARKET"
    else:
        mrl = "DANGER_MARKET"

    summary = (
        f"{safe_count}/{len(profiles)} protocols safe for deployment. "
        f"Avg flash loan risk: {avg_score:.1f}/100 ({mrl}). "
        f"Safest: {safest}, Riskiest: {riskiest}."
    )

    return FlashLoanRiskResult(
        profiles=profiles,
        safest_protocol=safest,
        riskiest_protocol=riskiest,
        safe_for_deployment_count=safe_count,
        avg_risk_score=avg_score,
        market_risk_label=mrl,
        recommendation_summary=summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def load_history() -> List[Dict[str, Any]]:
    """Load flash loan risk log from disk."""
    if not os.path.exists(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, "r") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _result_to_dict(result: FlashLoanRiskResult) -> Dict[str, Any]:
    d = asdict(result)
    d["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return d


def save_results(result: FlashLoanRiskResult) -> str:
    """Append result to ring-buffer log (cap 100). Returns path written."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    history = load_history()
    entry = _result_to_dict(result)
    history.append(entry)
    # Ring-buffer: keep last 100
    if len(history) > _RING_CAP:
        history = history[-_RING_CAP:]
    # Atomic write
    tmp = _LOG_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(history, fh, indent=2)
    os.replace(tmp, _LOG_FILE)
    return _LOG_FILE


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_protocols() -> List[Dict[str, Any]]:
    return [
        {
            "protocol": "Aave V3",
            "oracle_centralization": 20,
            "tvl_concentration_pct": 30,
            "price_impact_at_1m_usd": 5,
            "has_price_manipulation_history": False,
            "uses_twap": True,
        },
        {
            "protocol": "Compound V3",
            "oracle_centralization": 25,
            "tvl_concentration_pct": 35,
            "price_impact_at_1m_usd": 6,
            "has_price_manipulation_history": False,
            "uses_twap": True,
        },
        {
            "protocol": "Morpho Steakhouse",
            "oracle_centralization": 30,
            "tvl_concentration_pct": 40,
            "price_impact_at_1m_usd": 8,
            "has_price_manipulation_history": False,
            "uses_twap": False,
        },
    ]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MP-752 FlashLoanRiskDetector")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute + write to data/")
    args = parser.parse_args()

    protocols = _default_protocols()
    result = detect_risks(protocols)

    print(f"FlashLoanRiskDetector — {len(result.profiles)} protocols")
    print(f"  Market risk: {result.market_risk_label}  (avg {result.avg_risk_score:.1f}/100)")
    print(f"  Safest: {result.safest_protocol}  |  Riskiest: {result.riskiest_protocol}")
    print(f"  Safe for deployment: {result.safe_for_deployment_count}/{len(result.profiles)}")
    for p in result.profiles:
        print(f"  [{p.risk_label:8s}] {p.protocol}: {p.flash_loan_risk_score:.1f}/100 — {p.recommendation}")

    if args.run:
        path = save_results(result)
        print(f"\nSaved → {path}")
    else:
        print("\n(dry-run — use --run to persist)")


if __name__ == "__main__":
    main()
