"""
MP-751: ProtocolRiskScorecard
Composite 0-100 risk score across 7 dimensions for DeFi protocols.
Advisory/read-only. Pure stdlib. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap 100 entries.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

# ---------------------------------------------------------------------------
# Default data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_risk_scorecard_log.json"
)
_DEFAULT_DATA_FILE = os.path.normpath(_DEFAULT_DATA_FILE)

_RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Dimension weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHTS = {
    "smart_contract": 0.25,
    "liquidity":      0.20,
    "governance":     0.15,
    "oracle":         0.15,
    "counterparty":   0.10,
    "market":         0.10,
    "regulatory":     0.05,
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RiskDimension:
    name: str
    score: float          # 0-100
    weight: float
    weighted_score: float  # score * weight


@dataclass
class ProtocolRiskScore:
    protocol: str
    chain: str

    # Individual dimensions (0-100)
    smart_contract_risk: float
    liquidity_risk: float
    governance_risk: float
    oracle_risk: float
    counterparty_risk: float
    market_risk: float
    regulatory_risk: float

    dimensions: List[RiskDimension] = field(default_factory=list)

    composite_risk_score: float = 0.0
    risk_label: str = "LOW_RISK"
    top_risk_factors: List[str] = field(default_factory=list)
    is_investment_grade: bool = True
    recommendation: str = ""


@dataclass
class ScorecardResult:
    protocols: List[ProtocolRiskScore] = field(default_factory=list)

    safest_protocol: str = ""
    riskiest_protocol: str = ""

    investment_grade_count: int = 0
    avg_risk_score: float = 0.0

    # Distribution
    low_risk_count: int = 0
    moderate_risk_count: int = 0
    high_risk_count: int = 0
    critical_risk_count: int = 0

    portfolio_risk_label: str = "BALANCED"
    recommendation_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------

def compute_composite(scores_dict: dict) -> float:
    """Weighted sum of risk dimension scores. Returns 0-100."""
    total = 0.0
    for dim, weight in WEIGHTS.items():
        total += scores_dict.get(dim, 0.0) * weight
    return total


def risk_label(score: float) -> str:
    """Map composite score to label. Boundary: <25 LOW, <=50 MODERATE, <75 HIGH, >=75 CRITICAL."""
    if score < 25:
        return "LOW_RISK"
    if score <= 50:
        return "MODERATE_RISK"
    if score < 75:
        return "HIGH_RISK"
    return "CRITICAL_RISK"


def top_risk_factors(scores_dict: dict, n: int = 2) -> List[str]:
    """Return names of top n dimensions by score (deterministic: sort by (-score, name))."""
    sorted_dims = sorted(scores_dict.items(), key=lambda x: (-x[1], x[0]))
    return [dim for dim, _ in sorted_dims[:n]]


def _recommendation(label: str) -> str:
    if label == "CRITICAL_RISK":
        return "Do not deploy capital. Critical risk level."
    if label == "HIGH_RISK":
        return "High risk. Limit exposure and monitor closely."
    if label == "MODERATE_RISK":
        return "Acceptable risk for yield-seeking strategies."
    return "Low risk. Suitable for conservative allocation."


def _portfolio_risk_label(avg_score: float) -> str:
    if avg_score < 25:
        return "CONSERVATIVE"
    if avg_score < 50:
        return "BALANCED"
    if avg_score < 75:
        return "AGGRESSIVE"
    return "SPECULATIVE"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_protocol(
    protocol: str,
    chain: str,
    smart_contract: float,
    liquidity: float,
    governance: float,
    oracle: float,
    counterparty: float,
    market: float,
    regulatory: float,
) -> ProtocolRiskScore:
    """Compute a full ProtocolRiskScore."""
    scores = {
        "smart_contract": smart_contract,
        "liquidity":      liquidity,
        "governance":     governance,
        "oracle":         oracle,
        "counterparty":   counterparty,
        "market":         market,
        "regulatory":     regulatory,
    }

    dimensions = [
        RiskDimension(
            name=dim,
            score=score,
            weight=WEIGHTS[dim],
            weighted_score=score * WEIGHTS[dim],
        )
        for dim, score in scores.items()
    ]

    composite = compute_composite(scores)
    label = risk_label(composite)
    top_factors = top_risk_factors(scores, n=2)
    investment_grade = composite <= 50
    rec = _recommendation(label)

    return ProtocolRiskScore(
        protocol=protocol,
        chain=chain,
        smart_contract_risk=smart_contract,
        liquidity_risk=liquidity,
        governance_risk=governance,
        oracle_risk=oracle,
        counterparty_risk=counterparty,
        market_risk=market,
        regulatory_risk=regulatory,
        dimensions=dimensions,
        composite_risk_score=composite,
        risk_label=label,
        top_risk_factors=top_factors,
        is_investment_grade=investment_grade,
        recommendation=rec,
    )


def score_portfolio(protocols_data: List[dict]) -> ScorecardResult:
    """
    Compute ProtocolRiskScore for each protocol dict and aggregate into ScorecardResult.
    Each dict: {protocol, chain, smart_contract, liquidity, governance, oracle,
                counterparty, market, regulatory}
    """
    scored = []
    for p in protocols_data:
        ps = score_protocol(
            protocol=p["protocol"],
            chain=p["chain"],
            smart_contract=p["smart_contract"],
            liquidity=p["liquidity"],
            governance=p["governance"],
            oracle=p["oracle"],
            counterparty=p["counterparty"],
            market=p["market"],
            regulatory=p["regulatory"],
        )
        scored.append(ps)

    if not scored:
        return ScorecardResult(
            protocols=[],
            safest_protocol="",
            riskiest_protocol="",
            investment_grade_count=0,
            avg_risk_score=0.0,
            portfolio_risk_label="BALANCED",
            recommendation_summary="No protocols provided.",
            saved_to="",
        )

    safest = min(scored, key=lambda p: p.composite_risk_score)
    riskiest = max(scored, key=lambda p: p.composite_risk_score)

    investment_grade_count = sum(1 for p in scored if p.is_investment_grade)
    avg_score = sum(p.composite_risk_score for p in scored) / len(scored)

    low_risk_count = sum(1 for p in scored if p.risk_label == "LOW_RISK")
    moderate_risk_count = sum(1 for p in scored if p.risk_label == "MODERATE_RISK")
    high_risk_count = sum(1 for p in scored if p.risk_label == "HIGH_RISK")
    critical_risk_count = sum(1 for p in scored if p.risk_label == "CRITICAL_RISK")

    port_label = _portfolio_risk_label(avg_score)

    if critical_risk_count > 0:
        summary = (f"{critical_risk_count} protocol(s) at CRITICAL risk. "
                   "Remove from portfolio immediately.")
    elif high_risk_count > 0:
        summary = (f"{high_risk_count} protocol(s) at HIGH risk. "
                   "Limit exposure and monitor closely.")
    elif investment_grade_count == len(scored):
        summary = "All protocols are investment grade. Portfolio risk is acceptable."
    else:
        summary = f"{investment_grade_count}/{len(scored)} protocols are investment grade."

    return ScorecardResult(
        protocols=scored,
        safest_protocol=safest.protocol,
        riskiest_protocol=riskiest.protocol,
        investment_grade_count=investment_grade_count,
        avg_risk_score=avg_score,
        low_risk_count=low_risk_count,
        moderate_risk_count=moderate_risk_count,
        high_risk_count=high_risk_count,
        critical_risk_count=critical_risk_count,
        portfolio_risk_label=port_label,
        recommendation_summary=summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def _serialize_dimension(d: RiskDimension) -> dict:
    return asdict(d)


def _serialize_protocol_score(ps: ProtocolRiskScore) -> dict:
    return {
        "protocol": ps.protocol,
        "chain": ps.chain,
        "smart_contract_risk": ps.smart_contract_risk,
        "liquidity_risk": ps.liquidity_risk,
        "governance_risk": ps.governance_risk,
        "oracle_risk": ps.oracle_risk,
        "counterparty_risk": ps.counterparty_risk,
        "market_risk": ps.market_risk,
        "regulatory_risk": ps.regulatory_risk,
        "dimensions": [_serialize_dimension(d) for d in ps.dimensions],
        "composite_risk_score": ps.composite_risk_score,
        "risk_label": ps.risk_label,
        "top_risk_factors": ps.top_risk_factors,
        "is_investment_grade": ps.is_investment_grade,
        "recommendation": ps.recommendation,
    }


def _serialize_result(result: ScorecardResult) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "protocols": [_serialize_protocol_score(p) for p in result.protocols],
        "safest_protocol": result.safest_protocol,
        "riskiest_protocol": result.riskiest_protocol,
        "investment_grade_count": result.investment_grade_count,
        "avg_risk_score": result.avg_risk_score,
        "low_risk_count": result.low_risk_count,
        "moderate_risk_count": result.moderate_risk_count,
        "high_risk_count": result.high_risk_count,
        "critical_risk_count": result.critical_risk_count,
        "portfolio_risk_label": result.portfolio_risk_label,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def load_history(data_file: Optional[str] = None) -> list:
    path = data_file or _DEFAULT_DATA_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []


def save_results(result: ScorecardResult, data_file: Optional[str] = None) -> str:
    """Append result to ring-buffer log (cap 100). Returns file path."""
    path = data_file or _DEFAULT_DATA_FILE
    history = load_history(path)

    entry = _serialize_result(result)
    history.append(entry)

    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(path), exist_ok=True)

    dir_name = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_name, delete=False, suffix=".tmp"
    ) as tf:
        json.dump(history, tf, indent=2)
        tmp_path = tf.name

    os.replace(tmp_path, path)
    return path


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _demo() -> None:
    protocols = [
        {
            "protocol": "Aave V3", "chain": "Ethereum",
            "smart_contract": 15, "liquidity": 10, "governance": 20,
            "oracle": 15, "counterparty": 5, "market": 10, "regulatory": 20,
        },
        {
            "protocol": "NewProtocol", "chain": "BSC",
            "smart_contract": 80, "liquidity": 70, "governance": 85,
            "oracle": 75, "counterparty": 60, "market": 65, "regulatory": 90,
        },
    ]
    result = score_portfolio(protocols)
    saved = save_results(result)
    result.saved_to = saved
    print("=== ProtocolRiskScorecard Demo ===")
    for p in result.protocols:
        print(f"  {p.protocol}: {p.risk_label}  score={p.composite_risk_score:.1f}  "
              f"top_risks={p.top_risk_factors}")
    print(f"Safest: {result.safest_protocol}  Riskiest: {result.riskiest_protocol}")
    print(f"Saved to: {saved}")


if __name__ == "__main__":
    _demo()
