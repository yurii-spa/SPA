"""DeFi Insurance Calculator (MP-705) — advisory / read-only.

Calculates whether DeFi insurance coverage is worth purchasing for a position,
based on risk-adjusted expected loss vs premium cost.  Uses a compound
probability model to quantify five independent risk factors
(smart-contract exploit, oracle manipulation, admin-key misuse, economic
attack, bridge hack) and compares the expected payout from a set of
reference insurance quotes against their annual premium.

Design constraints
------------------
* Pure stdlib only (json, os, math, time, dataclasses, pathlib, typing).
  No requests / numpy / pandas / web3 / LLM SDK.
* Advisory only — never touches allocator / risk / execution.
* Atomic JSON writes: ``tmp-file + os.replace``.
* Ring-buffer cap ``RING_BUFFER_CAP`` (100) per ``data/insurance_calc_log.json``.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_FILE = _REPO_ROOT / "data" / "insurance_calc_log.json"

#: Maximum number of entries kept in the ring-buffer log.
RING_BUFFER_CAP: int = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RiskFactor:
    """One independent risk vector for a DeFi protocol position."""

    factor_type: str
    """Category: ``SMART_CONTRACT`` | ``ORACLE`` | ``ADMIN_KEY`` |
    ``ECONOMIC`` | ``BRIDGE``."""

    probability: float
    """Annual probability of the loss event occurring (0.0–1.0)."""

    severity: float
    """Fraction of position lost if the event occurs (0.0–1.0)."""

    expected_loss_pct: float
    """``probability × severity × 100``."""


@dataclass
class InsuranceQuote:
    """One insurance provider's quote for a given position."""

    provider: str
    """Provider name: ``nexus_mutual`` | ``insurace`` | ``unslashed`` |
    ``ribbon_protect``."""

    annual_premium_pct: float
    """Annual premium as % of the covered amount."""

    coverage_pct: float
    """Fraction of the loss covered (e.g. 0.80 = 80%)."""

    max_coverage_usd: float
    """Maximum USD payout from this provider."""

    deductible_pct: float
    """Fraction of any loss the insured absorbs first (before the payout)."""


@dataclass
class InsuranceAnalysis:
    """Complete insurance cost-benefit analysis for one protocol position."""

    protocol: str
    position_usd: float

    annual_premium_usd: float
    """position_usd × cheapest_premium_pct / 100."""

    # Risk quantification
    risk_factors: List[RiskFactor]
    total_expected_loss_pct: float
    """1 − ∏(1 − pᵢ × sᵢ), expressed as a percentage (0–100)."""

    total_expected_loss_usd: float
    """position_usd × total_expected_loss_pct / 100."""

    # Coverage analysis
    best_quote: InsuranceQuote
    net_payout_if_loss: float
    """position_usd × coverage_pct − annual_premium_usd."""

    break_even_probability: float
    """annual_premium_usd / (position_usd × coverage_pct)."""

    # Decision
    insurance_roi: float
    """(expected_payout − annual_premium_usd) / annual_premium_usd.
    0 when annual_premium_usd = 0."""

    worth_insuring: bool
    """``insurance_roi > 0``."""

    recommendation: str
    """``BUY_INSURANCE`` | ``PARTIAL_COVERAGE`` | ``SKIP`` | ``SELF_INSURE``."""

    reasoning: List[str]
    """Human-readable explanation bullets for the recommendation."""

    saved_to: str = ""
    """Populated after ``save_results`` with the absolute path written."""


# ---------------------------------------------------------------------------
# Risk factor calculation
# ---------------------------------------------------------------------------

# Default severity per factor type
_SEVERITY_DEFAULTS: Dict[str, float] = {
    "SMART_CONTRACT": 0.8,
    "ORACLE": 0.3,
    "ADMIN_KEY": 0.5,
    "ECONOMIC": 0.3,
    "BRIDGE": 0.6,
}


def calculate_risk_factors(
    protocol_type: str,
    audits_count: int,
    tvl_usd: float,
    age_months: float,
    has_admin_key: bool,
    has_bridge: bool,
) -> List[RiskFactor]:
    """Compute the list of applicable risk factors for a protocol position.

    Parameters
    ----------
    protocol_type:
        Protocol category (e.g. ``"lending"``, ``"dex"``).  Currently used
        only as documentation; future versions may adjust defaults by type.
    audits_count:
        Number of independent security audits completed.
    tvl_usd:
        Total Value Locked in the protocol (USD).
    age_months:
        Protocol age in months since first deployment.
    has_admin_key:
        Whether the protocol has an upgradeable admin / owner key.
    has_bridge:
        Whether the position depends on a cross-chain bridge.
    """
    factors: List[RiskFactor] = []

    # ── SMART_CONTRACT ───────────────────────────────────────────────────
    sc_prob = 0.05 - 0.01 * audits_count
    sc_prob = max(sc_prob, 0.01)
    if age_months < 6:
        sc_prob += 0.02
    sc_sev = _SEVERITY_DEFAULTS["SMART_CONTRACT"]
    factors.append(RiskFactor(
        factor_type="SMART_CONTRACT",
        probability=sc_prob,
        severity=sc_sev,
        expected_loss_pct=sc_prob * sc_sev * 100,
    ))

    # ── ORACLE ───────────────────────────────────────────────────────────
    oracle_prob = 0.02
    if tvl_usd > 100_000_000:
        oracle_prob += 0.01
    oracle_sev = _SEVERITY_DEFAULTS["ORACLE"]
    factors.append(RiskFactor(
        factor_type="ORACLE",
        probability=oracle_prob,
        severity=oracle_sev,
        expected_loss_pct=oracle_prob * oracle_sev * 100,
    ))

    # ── ADMIN_KEY ────────────────────────────────────────────────────────
    if has_admin_key:
        ak_prob = 0.03
        ak_sev = _SEVERITY_DEFAULTS["ADMIN_KEY"]
        factors.append(RiskFactor(
            factor_type="ADMIN_KEY",
            probability=ak_prob,
            severity=ak_sev,
            expected_loss_pct=ak_prob * ak_sev * 100,
        ))

    # ── ECONOMIC ─────────────────────────────────────────────────────────
    eco_prob = 0.02
    if tvl_usd > 500_000_000:
        eco_prob += 0.01
    eco_sev = _SEVERITY_DEFAULTS["ECONOMIC"]
    factors.append(RiskFactor(
        factor_type="ECONOMIC",
        probability=eco_prob,
        severity=eco_sev,
        expected_loss_pct=eco_prob * eco_sev * 100,
    ))

    # ── BRIDGE ───────────────────────────────────────────────────────────
    if has_bridge:
        br_prob = 0.08
        br_sev = _SEVERITY_DEFAULTS["BRIDGE"]
        factors.append(RiskFactor(
            factor_type="BRIDGE",
            probability=br_prob,
            severity=br_sev,
            expected_loss_pct=br_prob * br_sev * 100,
        ))

    return factors


# ---------------------------------------------------------------------------
# Expected-loss compound formula
# ---------------------------------------------------------------------------


def total_expected_loss_pct(factors: List[RiskFactor]) -> float:
    """Compound probability of at least one loss event, expressed as %.

    Formula: ``(1 − ∏(1 − pᵢ × sᵢ)) × 100``

    Parameters
    ----------
    factors:
        List of :class:`RiskFactor` objects (empty list → returns ``0.0``).
    """
    if not factors:
        return 0.0
    survival = 1.0
    for f in factors:
        survival *= 1.0 - f.probability * f.severity
    return (1.0 - survival) * 100.0


# ---------------------------------------------------------------------------
# Insurance quotes
# ---------------------------------------------------------------------------


def get_quotes(position_usd: float) -> List[InsuranceQuote]:  # noqa: ARG001
    """Return the fixed reference set of four insurance quotes.

    Premiums are fixed market approximations and do not vary with
    ``position_usd`` (which is accepted for API symmetry only).
    """
    return [
        InsuranceQuote(
            provider="nexus_mutual",
            annual_premium_pct=2.6,
            coverage_pct=0.80,
            max_coverage_usd=1_000_000.0,
            deductible_pct=0.0,
        ),
        InsuranceQuote(
            provider="insurace",
            annual_premium_pct=1.8,
            coverage_pct=0.85,
            max_coverage_usd=500_000.0,
            deductible_pct=0.10,
        ),
        InsuranceQuote(
            provider="unslashed",
            annual_premium_pct=3.1,
            coverage_pct=0.90,
            max_coverage_usd=200_000.0,
            deductible_pct=0.05,
        ),
        InsuranceQuote(
            provider="ribbon_protect",
            annual_premium_pct=1.5,
            coverage_pct=0.75,
            max_coverage_usd=250_000.0,
            deductible_pct=0.15,
        ),
    ]


# ---------------------------------------------------------------------------
# Recommendation logic (exposed as a pure helper so tests can call it directly)
# ---------------------------------------------------------------------------


def get_recommendation(
    worth_insuring: bool,
    total_loss_pct: float,
) -> str:
    """Derive a recommendation string from worth-insuring flag and loss magnitude.

    Priority rules (in order)
    -------------------------
    1. ``worth_insuring and total_loss_pct > 5`` → ``"BUY_INSURANCE"``
    2. ``worth_insuring``                          → ``"PARTIAL_COVERAGE"``
    3. ``total_loss_pct < 1``                      → ``"SELF_INSURE"``
    4. otherwise                                    → ``"SKIP"``
    """
    if worth_insuring and total_loss_pct > 5.0:
        return "BUY_INSURANCE"
    if worth_insuring:
        return "PARTIAL_COVERAGE"
    if total_loss_pct < 1.0:
        return "SELF_INSURE"
    return "SKIP"


def _build_reasoning(
    protocol: str,
    total_loss_pct: float,
    insurance_roi: float,
    worth_insuring: bool,
    recommendation: str,
    best_quote: InsuranceQuote,
    annual_premium_usd: float,
    break_even_probability: float,
) -> List[str]:
    """Construct human-readable reasoning bullets."""
    lines: List[str] = []
    lines.append(
        f"Protocol '{protocol}': total expected annual loss "
        f"{total_loss_pct:.2f}%."
    )
    lines.append(
        f"Best quote: {best_quote.provider} at "
        f"{best_quote.annual_premium_pct:.1f}% annual premium "
        f"(${annual_premium_usd:,.0f}/year), "
        f"{best_quote.coverage_pct:.0%} coverage."
    )
    lines.append(
        f"Break-even probability: {break_even_probability:.2%} "
        "(loss must exceed this rate annually for insurance to pay off)."
    )
    lines.append(
        f"Insurance ROI: {insurance_roi:+.2f} "
        f"({'positive — insurance pays off' if worth_insuring else 'negative — insurance costs more than expected payout'})."
    )
    lines.append(f"Recommendation: {recommendation}.")
    return lines


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyze(
    protocol: str,
    protocol_type: str,
    position_usd: float,
    audits_count: int,
    tvl_usd: float,
    age_months: float,
    has_admin_key: bool,
    has_bridge: bool,
) -> InsuranceAnalysis:
    """Run a full insurance cost-benefit analysis for a protocol position.

    Parameters
    ----------
    protocol:
        Human-readable protocol name (e.g. ``"aave_v3"``).
    protocol_type:
        Category passed through to :func:`calculate_risk_factors`.
    position_usd:
        Size of the position in USD.
    audits_count:
        Number of independent audits completed.
    tvl_usd:
        Protocol TVL in USD.
    age_months:
        Protocol age in months.
    has_admin_key:
        Whether an upgradeable admin key exists.
    has_bridge:
        Whether the position relies on a cross-chain bridge.
    """
    factors = calculate_risk_factors(
        protocol_type=protocol_type,
        audits_count=audits_count,
        tvl_usd=tvl_usd,
        age_months=age_months,
        has_admin_key=has_admin_key,
        has_bridge=has_bridge,
    )

    loss_pct = total_expected_loss_pct(factors)
    loss_usd = position_usd * loss_pct / 100.0

    quotes = get_quotes(position_usd)
    best_quote = min(quotes, key=lambda q: q.annual_premium_pct)

    annual_premium_usd = position_usd * best_quote.annual_premium_pct / 100.0
    net_payout_if_loss = position_usd * best_quote.coverage_pct - annual_premium_usd

    denominator = position_usd * best_quote.coverage_pct
    break_even_probability = (
        annual_premium_usd / denominator if denominator > 0 else 0.0
    )

    expected_payout = loss_usd * best_quote.coverage_pct
    insurance_roi = (
        (expected_payout - annual_premium_usd) / annual_premium_usd
        if annual_premium_usd > 0
        else 0.0
    )

    worth = insurance_roi > 0
    rec = get_recommendation(worth, loss_pct)
    reasoning = _build_reasoning(
        protocol, loss_pct, insurance_roi, worth, rec,
        best_quote, annual_premium_usd, break_even_probability,
    )

    return InsuranceAnalysis(
        protocol=protocol,
        position_usd=position_usd,
        annual_premium_usd=annual_premium_usd,
        risk_factors=factors,
        total_expected_loss_pct=loss_pct,
        total_expected_loss_usd=loss_usd,
        best_quote=best_quote,
        net_payout_if_loss=net_payout_if_loss,
        break_even_probability=break_even_probability,
        insurance_roi=insurance_roi,
        worth_insuring=worth,
        recommendation=rec,
        reasoning=reasoning,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Quote comparison
# ---------------------------------------------------------------------------


def compare_quotes(
    quotes: List[InsuranceQuote],
    position_usd: float,
    expected_loss_pct: float,
) -> List[InsuranceQuote]:
    """Rank quotes by net value delivered to the insured (best first).

    Net value = expected_payout − annual_premium_usd, where
    ``expected_payout = (position_usd × expected_loss_pct / 100) × coverage_pct``.

    Higher net value → quote ranked earlier.
    """
    expected_loss_usd = position_usd * expected_loss_pct / 100.0

    def net_value(q: InsuranceQuote) -> float:
        payout = expected_loss_usd * q.coverage_pct
        premium = position_usd * q.annual_premium_pct / 100.0
        return payout - premium

    return sorted(quotes, key=net_value, reverse=True)


# ---------------------------------------------------------------------------
# Persistence — ring-buffer JSON (cap 100, atomic writes)
# ---------------------------------------------------------------------------


def _analysis_to_dict(analysis: InsuranceAnalysis) -> dict:
    """Serialise an InsuranceAnalysis to a plain JSON-compatible dict."""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "protocol": analysis.protocol,
        "position_usd": analysis.position_usd,
        "annual_premium_usd": analysis.annual_premium_usd,
        "risk_factors": [
            {
                "factor_type": f.factor_type,
                "probability": f.probability,
                "severity": f.severity,
                "expected_loss_pct": f.expected_loss_pct,
            }
            for f in analysis.risk_factors
        ],
        "total_expected_loss_pct": analysis.total_expected_loss_pct,
        "total_expected_loss_usd": analysis.total_expected_loss_usd,
        "best_quote": {
            "provider": analysis.best_quote.provider,
            "annual_premium_pct": analysis.best_quote.annual_premium_pct,
            "coverage_pct": analysis.best_quote.coverage_pct,
            "max_coverage_usd": analysis.best_quote.max_coverage_usd,
            "deductible_pct": analysis.best_quote.deductible_pct,
        },
        "net_payout_if_loss": analysis.net_payout_if_loss,
        "break_even_probability": analysis.break_even_probability,
        "insurance_roi": analysis.insurance_roi,
        "worth_insuring": analysis.worth_insuring,
        "recommendation": analysis.recommendation,
        "reasoning": list(analysis.reasoning),
        "saved_to": analysis.saved_to,
    }


def save_results(
    analysis: InsuranceAnalysis,
    data_file: Path = _DEFAULT_DATA_FILE,
) -> str:
    """Append *analysis* to the ring-buffer JSON log.

    The write is atomic (tmp-file + ``os.replace``). The ``analysis.saved_to``
    field is updated in-place with the absolute path of the log file.

    Returns
    -------
    str
        Absolute path of the log file that was written.
    """
    data_file = Path(data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)

    existing: List[dict] = []
    if data_file.exists():
        try:
            with open(data_file, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (json.JSONDecodeError, OSError):
            existing = []

    entry = _analysis_to_dict(analysis)
    combined = (existing + [entry])[-RING_BUFFER_CAP:]

    tmp = data_file.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=2)
    os.replace(tmp, data_file)

    analysis.saved_to = str(data_file)
    return str(data_file)


def load_history(
    data_file: Path = _DEFAULT_DATA_FILE,
) -> List[dict]:
    """Load all entries from the ring-buffer log.

    Returns ``[]`` if the file is missing or corrupt.
    """
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        with open(data_file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
