"""
MP-823: DeFiInsuranceCostAnalyzer
Analyzes whether buying DeFi insurance (e.g. Nexus Mutual) for a position
is cost-effective based on the protocol's risk profile and position size.

Advisory / read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer log capped at 100 entries (data/insurance_cost_log.json).
"""

import json
import os
import time
from pathlib import Path

_DATA_FILE = Path("data/insurance_cost_log.json")
_MAX_ENTRIES = 100
_DEFAULT_HACK_PROBABILITY_BASE = 0.05  # 5 % annual base probability


# ---------------------------------------------------------------------------
# Ring-buffer helpers
# ---------------------------------------------------------------------------

def _load_log(data_file: Path) -> list:
    """Load ring-buffer log; return [] on any read / parse error."""
    try:
        return json.loads(data_file.read_text())
    except Exception:
        return []


def _save_log(entry: dict, data_file: Path) -> None:
    """Append *entry* to the ring-buffer log (max _MAX_ENTRIES). Atomic write."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_log(data_file)
    existing.append(entry)
    if len(existing) > _MAX_ENTRIES:
        existing = existing[-_MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    os.replace(tmp, data_file)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    position: dict,
    insurance_options: list,
    config: dict = None,
    *,
    data_file: Path = None,
    save: bool = True,
) -> dict:
    """
    Analyze cost-effectiveness of DeFi insurance for a position.

    Parameters
    ----------
    position : dict
        {
            "protocol": str,
            "value_usd": float,
            "protocol_risk_score": int,   # 0-100 (0=safe, 100=very risky)
            "holding_period_days": int
        }
    insurance_options : list[dict]
        Each element:
        {
            "provider": str,
            "annual_premium_pct": float,   # % of covered amount per year
            "coverage_pct": float,         # % of loss covered (0-100)
            "max_coverage_usd": float | None,  # None = unlimited
            "deductible_pct": float        # % of loss not covered (0-100)
        }
    config : dict | None
        {"hack_probability_base": float}  # default 0.05
    data_file : Path | None
        Override default log path (useful in tests).
    save : bool
        Whether to append the result to the ring-buffer log.

    Returns
    -------
    dict
        {
            "position": {protocol, value_usd, protocol_risk_score, holding_period_days},
            "expected_loss_usd": float,
            "adjusted_hack_probability": float,
            "options": list[...],
            "best_option": str | None,
            "insurance_worthwhile": bool,
            "timestamp": float,
        }
    """
    if data_file is None:
        data_file = _DATA_FILE

    cfg = config or {}
    hack_prob_base = float(cfg.get("hack_probability_base", _DEFAULT_HACK_PROBABILITY_BASE))

    # --- parse position ---
    protocol = str(position.get("protocol", ""))
    value_usd = float(position.get("value_usd", 0.0))
    risk_score = int(position.get("protocol_risk_score", 0))
    holding_days = int(position.get("holding_period_days", 0))

    # clamp risk score to [0, 100]
    risk_score = max(0, min(100, risk_score))

    # --- hack probability (annual, adjusted for protocol risk) ---
    adjusted_hack_prob = min(1.0, hack_prob_base * (1.0 + risk_score / 100.0))

    # --- period fraction (holding period / year) ---
    period_fraction = holding_days / 365.0 if holding_days > 0 else 0.0

    # --- top-level expected loss over holding period ---
    # avg_coverage_factor = period_fraction (how much of the annual probability
    # materialises during the holding window)
    expected_loss_usd = value_usd * adjusted_hack_prob * period_fraction

    # --- per-option analysis ---
    options_out: list = []
    for opt in (insurance_options or []):
        provider = str(opt.get("provider", ""))
        annual_premium_pct = float(opt.get("annual_premium_pct", 0.0))
        coverage_pct = float(opt.get("coverage_pct", 0.0))
        max_cov = opt.get("max_coverage_usd", None)
        deductible_pct = float(opt.get("deductible_pct", 0.0))

        # premium for the holding period
        premium_for_period = value_usd * (annual_premium_pct / 100.0) * period_fraction

        # effective coverage:
        #   min(value * coverage_pct/100, max_coverage or inf)
        #   For JSON safety, cap "inf" at value_usd
        if max_cov is not None:
            coverage_cap = float(max_cov)
        else:
            coverage_cap = value_usd  # cap inf at position value

        raw_coverage = min(value_usd * (coverage_pct / 100.0), coverage_cap)
        effective_coverage = raw_coverage * (1.0 - deductible_pct / 100.0)

        # expected payout over the holding period
        expected_payout = effective_coverage * adjusted_hack_prob * period_fraction

        # net value of buying this insurance for the period
        net_value = expected_payout - premium_for_period

        # cost-benefit ratio (infinity → 999.0 for JSON safety when premium == 0)
        if premium_for_period > 0:
            cbr = expected_payout / premium_for_period
        else:
            cbr = 999.0

        # recommendation
        if net_value > 0 and cbr > 1.5:
            recommendation = "BUY"
        elif net_value > 0 or cbr > 1.0:
            recommendation = "CONSIDER"
        else:
            recommendation = "SKIP"

        options_out.append(
            {
                "provider": provider,
                "annual_premium_pct": annual_premium_pct,
                "premium_for_period_usd": premium_for_period,
                "effective_coverage_usd": effective_coverage,
                "expected_payout_usd": expected_payout,
                "net_value_usd": net_value,
                "cost_benefit_ratio": cbr,
                "recommendation": recommendation,
            }
        )

    # --- aggregate results ---
    best_option: "str | None" = None
    if options_out:
        best = max(options_out, key=lambda o: o["net_value_usd"])
        best_option = best["provider"]

    insurance_worthwhile = any(o["net_value_usd"] > 0 for o in options_out)

    result = {
        "position": {
            "protocol": protocol,
            "value_usd": value_usd,
            "protocol_risk_score": risk_score,
            "holding_period_days": holding_days,
        },
        "expected_loss_usd": expected_loss_usd,
        "adjusted_hack_probability": adjusted_hack_prob,
        "options": options_out,
        "best_option": best_option,
        "insurance_worthwhile": insurance_worthwhile,
        "timestamp": time.time(),
    }

    if save:
        _save_log(result, data_file)

    return result


# ---------------------------------------------------------------------------
# CLI entry point (advisory — prints result, exit 0 always)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_position = {
        "protocol": "Aave V3",
        "value_usd": 50_000.0,
        "protocol_risk_score": 30,
        "holding_period_days": 90,
    }
    _demo_options = [
        {
            "provider": "Nexus Mutual",
            "annual_premium_pct": 2.6,
            "coverage_pct": 100.0,
            "max_coverage_usd": None,
            "deductible_pct": 0.0,
        },
        {
            "provider": "InsureAce",
            "annual_premium_pct": 1.8,
            "coverage_pct": 80.0,
            "max_coverage_usd": 40_000.0,
            "deductible_pct": 5.0,
        },
    ]

    res = analyze(_demo_position, _demo_options, save=False)
    print(json.dumps(res, indent=2))
    sys.exit(0)
