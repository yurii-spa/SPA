"""
MP-809 YieldSourceClassifier
Classifies yield into real yield (fees/revenue) vs inflationary yield (token emissions)
vs price appreciation to assess sustainability.

Advisory/read-only module. Pure stdlib. Atomic writes via tmp + os.replace.
Data: data/yield_source_classification_log.json (ring-buffer 100)
"""

import json
import os
import time
import tempfile

_DEFAULT_CONFIG = {
    "real_yield_threshold": 50.0,      # real_yield_pct >= this → SUSTAINABLE
    "emission_danger_threshold": 80.0, # emission_pct >= this → INFLATIONARY
}

_LOG_RING_SIZE = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "yield_source_classification_log.json"
)


def _compute_sustainability_score(real_yield_pct: float, emission_pct: float, total_apy: float) -> int:
    """Compute 0-100 sustainability score."""
    if total_apy <= 0:
        return 0

    score = min(real_yield_pct, 100.0)

    if emission_pct > 80:
        score -= 30
    elif emission_pct > 50:
        score -= 15

    return max(0, min(100, int(round(score))))


def _compute_risk_flags(
    emission_pct: float,
    total_apy: float,
    real_yield_pct: float,
    price_appreciation_apy: float,
    fee_apy: float,
) -> list:
    """Return list of risk flag strings."""
    flags = []

    if emission_pct > 80:
        flags.append("High token emission dependency")
    elif emission_pct > 50:
        flags.append("Majority of yield is inflationary")

    if total_apy > 50 and real_yield_pct < 20:
        flags.append("Unsustainably high APY")

    if price_appreciation_apy < 0:
        flags.append("Negative price appreciation component")

    if total_apy < fee_apy:
        flags.append("APY components inconsistent")

    return flags


def _classify_sustainability(
    total_apy: float,
    real_yield_pct: float,
    emission_pct: float,
    real_yield_threshold: float,
    emission_danger_threshold: float,
) -> str:
    """Return sustainability category."""
    if total_apy <= 0:
        return "NEGATIVE"
    if emission_pct >= emission_danger_threshold:
        return "INFLATIONARY"
    if real_yield_pct >= real_yield_threshold:
        return "SUSTAINABLE"
    return "MIXED"


def _recommendation(sustainability: str) -> str:
    """Map sustainability to human-readable recommendation."""
    return {
        "NEGATIVE": "Avoid — yield is negative",
        "INFLATIONARY": "Caution — yield driven by token emissions, expect decay",
        "SUSTAINABLE": "Favorable — real yield backed by protocol revenue",
        "MIXED": "Moderate — partial real yield, monitor emission schedule",
    }[sustainability]


def analyze(protocol: str, yield_breakdown: dict, config: dict = None) -> dict:
    """
    Classify protocol yield into real vs inflationary vs price-appreciation components.

    Parameters
    ----------
    protocol : str
        Protocol name (e.g. "Aave V3").
    yield_breakdown : dict
        {
            "total_apy": float,
            "fee_apy": float,
            "emission_apy": float,
            "price_appreciation_apy": float
        }
    config : dict, optional
        {
            "real_yield_threshold": float,      # default 50.0
            "emission_danger_threshold": float  # default 80.0
        }

    Returns
    -------
    dict with keys:
        protocol, total_apy, breakdown, real_yield_apy, real_yield_pct,
        emission_pct, sustainability, sustainability_score, risk_flags,
        recommendation, timestamp
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    real_yield_threshold = float(cfg.get("real_yield_threshold", _DEFAULT_CONFIG["real_yield_threshold"]))
    emission_danger_threshold = float(cfg.get("emission_danger_threshold", _DEFAULT_CONFIG["emission_danger_threshold"]))

    total_apy = float(yield_breakdown.get("total_apy", 0.0))
    fee_apy = float(yield_breakdown.get("fee_apy", 0.0))
    emission_apy = float(yield_breakdown.get("emission_apy", 0.0))
    price_appreciation_apy = float(yield_breakdown.get("price_appreciation_apy", 0.0))

    # Percentage breakdown
    if total_apy == 0:
        fee_pct = 0.0
        emission_pct = 0.0
        price_appreciation_pct = 0.0
    else:
        fee_pct = (fee_apy / total_apy) * 100.0
        emission_pct = (emission_apy / total_apy) * 100.0
        price_appreciation_pct = (price_appreciation_apy / total_apy) * 100.0

    real_yield_apy = fee_apy + price_appreciation_apy
    real_yield_pct = (real_yield_apy / total_apy * 100.0) if total_apy != 0 else 0.0

    sustainability = _classify_sustainability(
        total_apy, real_yield_pct, emission_pct,
        real_yield_threshold, emission_danger_threshold
    )

    sustainability_score = _compute_sustainability_score(real_yield_pct, emission_pct, total_apy)

    risk_flags = _compute_risk_flags(
        emission_pct, total_apy, real_yield_pct,
        price_appreciation_apy, fee_apy
    )

    result = {
        "protocol": protocol,
        "total_apy": total_apy,
        "breakdown": {
            "fee_apy": fee_apy,
            "emission_apy": emission_apy,
            "price_appreciation_apy": price_appreciation_apy,
            "fee_pct": fee_pct,
            "emission_pct": emission_pct,
            "price_appreciation_pct": price_appreciation_pct,
        },
        "real_yield_apy": real_yield_apy,
        "real_yield_pct": real_yield_pct,
        "emission_pct": emission_pct,
        "sustainability": sustainability,
        "sustainability_score": sustainability_score,
        "risk_flags": risk_flags,
        "recommendation": _recommendation(sustainability),
        "timestamp": time.time(),
    }

    return result


def log_result(result: dict, log_path: str = None) -> None:
    """Append result to ring-buffer JSON log (max 100 entries). Atomic write."""
    if log_path is None:
        log_path = _DEFAULT_LOG_PATH

    # Load existing log
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []
    else:
        log = []

    log.append(result)

    # Ring-buffer cap
    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    # Atomic write
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=log_dir or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def analyze_and_log(protocol: str, yield_breakdown: dict, config: dict = None, log_path: str = None) -> dict:
    """analyze() + log_result(). Returns the result dict."""
    result = analyze(protocol, yield_breakdown, config)
    log_result(result, log_path)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    _example_breakdown = {
        "total_apy": 8.5,
        "fee_apy": 5.0,
        "emission_apy": 2.5,
        "price_appreciation_apy": 1.0,
    }

    result = analyze("Aave V3", _example_breakdown)
    json.dump(result, sys.stdout, indent=2)
    print()
