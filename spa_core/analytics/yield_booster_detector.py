"""
MP-820 YieldBoosterDetector
============================
Advisory/read-only module.
Detects temporary yield boost opportunities (liquidity mining programs,
incentive campaigns, lock bonuses) and evaluates their sustainability and value.

CLI:
    python3 -m spa_core.analytics.yield_booster_detector --check
    python3 -m spa_core.analytics.yield_booster_detector --run
    python3 -m spa_core.analytics.yield_booster_detector --run --data-dir <dir>

Pure stdlib only. Atomic ring-buffer log (cap 100) written to
data/yield_booster_log.json.
"""

from __future__ import annotations

import json
import os
import time
import argparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_INFLATION_RISK_THRESHOLD_USD: float = 10_000_000.0
_MEDIUM_CAP_THRESHOLD_USD: float = 100_000_000.0
_LOG_CAP: int = 100
_DEFAULT_LOG_FILE: str = "data/yield_booster_log.json"

_SUSTAINABILITY_WEIGHTS = {
    "SUSTAINABLE": 1.0,
    "TEMPORARY":   0.5,
    "RISKY":       0.2,
}

_VALID_TYPES = {
    "liquidity_mining",
    "lock_bonus",
    "referral",
    "campaign",
    "ve_boost",
}


# ---------------------------------------------------------------------------
# Token-risk classification
# ---------------------------------------------------------------------------
def _token_risk(market_cap: float, threshold: float) -> str:
    """
    HIGH  : market_cap < threshold (default 10M) or market_cap == 0
    MEDIUM: market_cap < 100M
    LOW   : market_cap >= 100M
    """
    if market_cap <= 0 or market_cap < threshold:
        return "HIGH"
    if market_cap < _MEDIUM_CAP_THRESHOLD_USD:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Sustainability classification
# ---------------------------------------------------------------------------
def _sustainability(is_temporary: bool, tok_risk: str) -> str:
    """
    RISKY      : token_risk == HIGH
    TEMPORARY  : is_temporary and token_risk != HIGH
    SUSTAINABLE: not is_temporary and token_risk in (LOW, MEDIUM)
    """
    if tok_risk == "HIGH":
        return "RISKY"
    if is_temporary:
        return "TEMPORARY"
    return "SUSTAINABLE"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------
def analyze(
    protocol: str,
    boosters: list[dict],
    base_apy: float,
    config: dict | None = None,
) -> dict:
    """
    Detect and evaluate yield booster opportunities.

    Parameters
    ----------
    protocol : str
        Name of the yield protocol.
    boosters : list[dict]
        Each element:
            name                : str
            type                : str  (see _VALID_TYPES)
            additional_apy      : float
            duration_days       : int | None   (None = permanent/ongoing)
            token               : str
            token_price_usd     : float
            token_market_cap_usd: float  (0 = unknown)
            requires_lock       : bool
    base_apy : float
        Base protocol APY (without any boosters), percent.
    config : dict | None
        Optional:
            inflation_risk_threshold_usd: float  (default 10_000_000)

    Returns
    -------
    dict
        Full analysis (see module docstring for schema).
    """
    cfg = config or {}
    inflation_threshold: float = float(
        cfg.get("inflation_risk_threshold_usd", _DEFAULT_INFLATION_RISK_THRESHOLD_USD)
    )
    ts = time.time()

    base_apy = float(base_apy)

    # ------------------------------------------------------------------
    # Per-booster enrichment
    # ------------------------------------------------------------------
    total_additional_apy: float = sum(
        float(b.get("additional_apy", 0.0)) for b in boosters
    )
    total_boosted_apy: float = base_apy + total_additional_apy

    # Guard: multiplier when base == 0
    boost_multiplier: float = (
        total_boosted_apy / base_apy if base_apy != 0 else 1.0
    )

    enriched: list[dict] = []
    for b in boosters:
        duration = b.get("duration_days", None)
        is_temporary = duration is not None
        market_cap = float(b.get("token_market_cap_usd", 0.0))
        tok_risk = _token_risk(market_cap, inflation_threshold)
        sust = _sustainability(is_temporary, tok_risk)
        add_apy = float(b.get("additional_apy", 0.0))

        # value_score
        apy_contribution_pct = add_apy / max(total_boosted_apy, 0.01) * 100.0
        weight = _SUSTAINABILITY_WEIGHTS[sust]
        value_score = int(min(apy_contribution_pct * weight, 100))

        enriched.append(
            {
                "name": str(b.get("name", "")),
                "type": str(b.get("type", "")),
                "additional_apy": add_apy,
                "duration_days": duration,
                "is_temporary": is_temporary,
                "token_risk": tok_risk,
                "sustainability": sust,
                "value_score": value_score,
            }
        )

    # ------------------------------------------------------------------
    # Summary metrics
    # ------------------------------------------------------------------
    permanent_boost_apy: float = sum(
        e["additional_apy"] for e in enriched if not e["is_temporary"]
    )
    temporary_boost_apy: float = sum(
        e["additional_apy"] for e in enriched if e["is_temporary"]
    )
    # sustainable_apy: base + permanent boosts with LOW/MEDIUM risk
    sustainable_boost = sum(
        e["additional_apy"]
        for e in enriched
        if not e["is_temporary"] and e["token_risk"] in ("LOW", "MEDIUM")
    )
    sustainable_apy: float = base_apy + sustainable_boost

    locked_required_apy: float = sum(
        float(b.get("additional_apy", 0.0))
        for b in boosters
        if b.get("requires_lock", False)
    )

    # highest_value_booster: name of enriched entry with max value_score
    if enriched:
        best = max(enriched, key=lambda e: e["value_score"])
        highest_value_booster: str = best["name"]
    else:
        highest_value_booster = ""

    # ------------------------------------------------------------------
    # overall_sustainability
    # ------------------------------------------------------------------
    total_boost = total_additional_apy  # sum of all booster APYs
    risky_boost = sum(
        e["additional_apy"] for e in enriched if e["sustainability"] == "RISKY"
    )

    # HIGH: permanent_boost_apy > 50% of total_boost AND all tokens LOW/MEDIUM
    has_high_risk_token = any(e["token_risk"] == "HIGH" for e in enriched)
    if total_boost > 0:
        perm_ratio = permanent_boost_apy / total_boost
    else:
        perm_ratio = 0.0

    if not enriched:
        # No boosters → default to HIGH (only base APY, no risk)
        overall_sustainability = "HIGH"
    elif total_boost == 0:
        overall_sustainability = "HIGH"
    elif perm_ratio > 0.5 and not has_high_risk_token:
        overall_sustainability = "HIGH"
    elif total_boost > 0 and risky_boost / total_boost > 0.5:
        overall_sustainability = "LOW"
    else:
        overall_sustainability = "MEDIUM"

    # ------------------------------------------------------------------
    # recommendation
    # ------------------------------------------------------------------
    if not enriched:
        recommendation = "BASE_ONLY"
    elif overall_sustainability == "HIGH":
        recommendation = "TAKE_ALL"
    elif all(e["sustainability"] == "RISKY" for e in enriched):
        recommendation = "BASE_ONLY"
    else:
        recommendation = "SELECTIVE"

    # ------------------------------------------------------------------
    # Build result
    # ------------------------------------------------------------------
    result: dict = {
        "protocol": protocol,
        "base_apy": round(base_apy, 4),
        "total_boosted_apy": round(total_boosted_apy, 4),
        "boost_multiplier": round(boost_multiplier, 4),
        "boosters": enriched,
        "summary": {
            "permanent_boost_apy": round(permanent_boost_apy, 4),
            "temporary_boost_apy": round(temporary_boost_apy, 4),
            "sustainable_apy": round(sustainable_apy, 4),
            "locked_required_apy": round(locked_required_apy, 4),
            "highest_value_booster": highest_value_booster,
        },
        "overall_sustainability": overall_sustainability,
        "recommendation": recommendation,
        "timestamp": ts,
    }
    return result


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer, cap 100, atomic write)
# ---------------------------------------------------------------------------
def _append_log(result: dict, data_dir: str = "data") -> None:
    """Atomically append *result* to the ring-buffer log (cap 100 entries)."""
    log_path = os.path.join(data_dir, "yield_booster_log.json")
    tmp_path = log_path + ".tmp"

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log: list = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def _sample_boosters() -> list[dict]:
    """Synthetic sample for demo/check mode."""
    return [
        {
            "name": "COMP Liquidity Mining",
            "type": "liquidity_mining",
            "additional_apy": 3.5,
            "duration_days": 90,
            "token": "COMP",
            "token_price_usd": 45.0,
            "token_market_cap_usd": 350_000_000.0,
            "requires_lock": False,
        },
        {
            "name": "veToken Boost",
            "type": "ve_boost",
            "additional_apy": 2.0,
            "duration_days": None,
            "token": "CRV",
            "token_price_usd": 0.40,
            "token_market_cap_usd": 400_000_000.0,
            "requires_lock": True,
        },
        {
            "name": "New Protocol Incentive",
            "type": "campaign",
            "additional_apy": 8.0,
            "duration_days": 30,
            "token": "NEWTKN",
            "token_price_usd": 0.05,
            "token_market_cap_usd": 2_000_000.0,
            "requires_lock": False,
        },
    ]


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="MP-820 YieldBoosterDetector")
    parser.add_argument("--check", action="store_true", help="Run analysis, no write")
    parser.add_argument("--run", action="store_true", help="Run analysis + write log")
    parser.add_argument("--data-dir", default="data", help="Directory for JSON logs")
    args = parser.parse_args()

    result = analyze("SampleProtocol", _sample_boosters(), base_apy=4.8)

    print(json.dumps(result, indent=2))
    print(
        f"\nRecommendation: {result['recommendation']}  "
        f"Sustainability: {result['overall_sustainability']}"
    )

    if args.run:
        os.makedirs(args.data_dir, exist_ok=True)
        _append_log(result, data_dir=args.data_dir)
        print(f"[MP-820] Log written to {args.data_dir}/yield_booster_log.json")


if __name__ == "__main__":  # pragma: no cover
    main()
