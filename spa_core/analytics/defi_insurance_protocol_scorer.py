"""
MP-881 DeFiInsuranceProtocolScorer
Advisory/read-only analytics module.
Scores DeFi insurance/coverage protocols on reliability, coverage quality, and capital efficiency.

Data: data/insurance_protocol_log.json (ring-buffer 100, atomic writes)
Pure stdlib only. LLM FORBIDDEN.
"""

import json
import os
import time
import tempfile
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_MIN_CAPITAL_USD = 1_000_000.0
_LOG_FILE = "data/insurance_protocol_log.json"
_RING_BUFFER_MAX = 100

_GRADE_THRESHOLDS = [
    (90, "S"),
    (80, "A"),
    (70, "B"),
    (60, "C"),
    (50, "D"),
    (0,  "F"),
]

_PREMIUM_BANDS = [
    (0,   50,  "CHEAP"),
    (50,  150, "COMPETITIVE"),
    (150, 300, "EXPENSIVE"),
    (300, None, "VERY_EXPENSIVE"),
]

_MATURITY_BANDS = [
    (730, None, "ESTABLISHED"),
    (365, 730,  "MATURE"),
    (180, 365,  "GROWING"),
    (0,   180,  "NEW"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    """Clamp and convert to int."""
    return int(max(lo, min(hi, value)))


def _coverage_ratio(total_coverage_usd: float, total_capital_usd: float) -> float:
    if total_capital_usd <= 0:
        return 0.0
    return total_coverage_usd / total_capital_usd


def _claims_payment_rate(claims_paid: float, claims_rejected: float) -> float:
    denom = claims_paid + claims_rejected
    if denom <= 0:
        # Benefit of the doubt — no claims ever
        return 100.0
    return claims_paid / denom * 100.0


def _capital_efficiency_score(coverage_ratio: float) -> int:
    return _clamp(coverage_ratio * 10)


def _cover_breadth_score(cover_types: list) -> int:
    return _clamp(len(cover_types) / 4 * 100)


def _maturity_normalized(days_since_launch: int) -> int:
    return _clamp(days_since_launch / 730 * 100)


def _premium_competitiveness(bps: float) -> str:
    for lo, hi, label in _PREMIUM_BANDS:
        if hi is None or bps < hi:
            if bps >= lo:
                return label
    return "VERY_EXPENSIVE"


def _maturity_label(days: int) -> str:
    for lo, hi, label in _MATURITY_BANDS:
        if hi is None or days < hi:
            if days >= lo:
                return label
    return "NEW"


def _grade(score: int) -> str:
    for threshold, letter in _GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"


def _flags(
    total_capital_usd: float,
    claims_paid: float,
    claims_rejected: float,
    capital_utilization_pct: float,
    min_capital_usd: float,
) -> list:
    result = []
    if total_capital_usd < min_capital_usd:
        result.append("UNDERCAPITALIZED")
    denom = claims_paid + claims_rejected
    if denom > 0 and claims_rejected > claims_paid:
        result.append("HIGH_REJECTION_RATE")
    if capital_utilization_pct > 500:
        result.append("OVERLEVERAGED")
    return result


def _recommendation(grade: str, claims_payment_rate_pct: float, cover_breadth_score: int, overall_score: int, flag_list: list) -> str:
    if grade in ("S", "A"):
        return f"Reliable protocol. {claims_payment_rate_pct:.0f}% claims paid, {cover_breadth_score} breadth score."
    if grade == "B":
        return f"Solid option. Monitor claims history. Score: {overall_score}."
    if grade == "C":
        return f"Acceptable but review {len(flag_list)} flags before deploying capital."
    # D or F
    flags_str = ", ".join(flag_list) if flag_list else "low overall score"
    return f"Avoid. High risk flags: {flags_str}."


# ---------------------------------------------------------------------------
# Atomic log write
# ---------------------------------------------------------------------------

def _append_log(entry: dict, log_path: str = _LOG_FILE) -> None:
    """Append entry to ring-buffer JSON log (max 100 entries), atomic write."""
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []
    except Exception:
        data = []

    data.append(entry)
    if len(data) > _RING_BUFFER_MAX:
        data = data[-_RING_BUFFER_MAX:]

    dir_name = os.path.dirname(log_path) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Score a list of DeFi insurance protocols.

    Parameters
    ----------
    protocols : list of dict
        Each dict must contain:
            name, total_coverage_usd, total_capital_usd, claims_paid_usd,
            claims_rejected_usd, active_cover_policies, annual_premium_rate_bps,
            days_since_launch, cover_types, capital_utilization_pct
    config : dict, optional
        min_capital_usd (default 1_000_000)

    Returns
    -------
    dict with keys: protocols, best_protocol, average_claims_payment_rate_pct, timestamp
    """
    if config is None:
        config = {}
    min_capital_usd = float(config.get("min_capital_usd", _DEFAULT_MIN_CAPITAL_USD))

    scored: list[dict] = []

    for p in protocols:
        name = str(p.get("name", ""))
        total_coverage_usd = float(p.get("total_coverage_usd", 0.0))
        total_capital_usd = float(p.get("total_capital_usd", 0.0))
        claims_paid_usd = float(p.get("claims_paid_usd", 0.0))
        claims_rejected_usd = float(p.get("claims_rejected_usd", 0.0))
        annual_premium_rate_bps = float(p.get("annual_premium_rate_bps", 0.0))
        days_since_launch = int(p.get("days_since_launch", 0))
        cover_types = list(p.get("cover_types", []))
        capital_utilization_pct = float(p.get("capital_utilization_pct", 0.0))

        # Derived metrics
        cov_ratio = _coverage_ratio(total_coverage_usd, total_capital_usd)
        claims_rate = _claims_payment_rate(claims_paid_usd, claims_rejected_usd)
        cap_eff = _capital_efficiency_score(cov_ratio)
        breadth = _cover_breadth_score(cover_types)
        maturity_norm = _maturity_normalized(days_since_launch)
        mat_label = _maturity_label(days_since_launch)
        premium_comp = _premium_competitiveness(annual_premium_rate_bps)

        # Overall score (clamped 0-100)
        raw_score = (
            claims_rate * 0.4
            + cap_eff * 0.3
            + breadth * 0.2
            + maturity_norm * 0.1
        )
        overall = _clamp(raw_score)

        grade = _grade(overall)
        flag_list = _flags(
            total_capital_usd,
            claims_paid_usd,
            claims_rejected_usd,
            capital_utilization_pct,
            min_capital_usd,
        )
        rec = _recommendation(grade, claims_rate, breadth, overall, flag_list)

        scored.append({
            "name": name,
            "coverage_ratio": cov_ratio,
            "claims_payment_rate_pct": claims_rate,
            "capital_efficiency_score": cap_eff,
            "premium_competitiveness": premium_comp,
            "cover_breadth_score": breadth,
            "maturity_label": mat_label,
            "overall_score": overall,
            "grade": grade,
            "flags": flag_list,
            "recommendation": rec,
        })

    # Aggregate
    best_protocol: str | None = None
    if scored:
        best_protocol = max(scored, key=lambda x: x["overall_score"])["name"]

    avg_claims_rate = (
        sum(x["claims_payment_rate_pct"] for x in scored) / len(scored)
        if scored else 0.0
    )

    result = {
        "protocols": scored,
        "best_protocol": best_protocol,
        "average_claims_payment_rate_pct": avg_claims_rate,
        "timestamp": time.time(),
    }

    # Log atomically
    try:
        _append_log({
            "timestamp": result["timestamp"],
            "protocol_count": len(scored),
            "best_protocol": best_protocol,
            "average_claims_payment_rate_pct": avg_claims_rate,
        })
    except Exception:
        pass

    return result
