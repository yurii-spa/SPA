"""
MP-830: DeFiPositionSizeRecommender
Recommends optimal position sizes for DeFi protocols using risk-adjusted
fractional Kelly criterion, protocol-specific risk factors, and portfolio
concentration limits.

Pure stdlib, read-only analytics, atomic write, ring-buffer log (cap 100).
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

RING_BUFFER_CAP = 100

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "position_size_log.json"
)

# ── defaults ───────────────────────────────────────────────────────────────
_DEFAULT_KELLY_FRACTION = 0.25
_DEFAULT_MAX_POSITION_PCT = 35.0
_DEFAULT_MIN_POSITION_USD = 200.0


def _compute_kelly(
    expected_apy: float,
    risk_score: int,
    max_loss_scenario_pct: float,
    win_probability: float,
    kelly_fraction: float,
    max_position_pct: float,
    min_position_usd: float,
    portfolio_usd: float,
) -> Dict[str, Any]:
    """
    Compute Kelly-based position sizing for a single opportunity.

    Kelly formula (simplified):
      kelly_pct = ((win_prob * expected_apy/100) - ((1-win_prob) * max_loss/100))
                  / (max_loss/100) * 100

    When max_loss_scenario_pct == 0, kelly is unbounded → cap at max_position_pct.
    """
    loss_probability = 1.0 - win_probability

    if max_loss_scenario_pct == 0:
        # Unbounded Kelly → hard-cap
        kelly_pct = float("inf")
    else:
        loss_frac = max_loss_scenario_pct / 100.0
        win_return = expected_apy / 100.0
        # kelly_pct = ((win * win_return) - (loss_prob * loss_frac)) / loss_frac * 100
        kelly_pct = ((win_probability * win_return) - (loss_probability * loss_frac)) / loss_frac * 100.0

    # adjusted_kelly_pct
    if kelly_pct == float("inf"):
        adjusted_kelly_pct = max_position_pct
    else:
        adjusted_kelly_pct = max(0.0, kelly_pct * kelly_fraction)

    # risk_penalty_pct: risk_score/100 * 10
    risk_penalty_pct = (risk_score / 100.0) * 10.0

    # final_pct: clamp [0, max_position_pct]
    final_pct = max(0.0, min(adjusted_kelly_pct - risk_penalty_pct, max_position_pct))

    # recommended_usd
    recommended_usd = (final_pct / 100.0) * portfolio_usd

    # viable
    viable = recommended_usd >= min_position_usd

    # rationale
    if kelly_pct != float("inf") and kelly_pct <= 0:
        rationale = "Negative Kelly — unfavorable risk/reward"
    elif final_pct >= max_position_pct and final_pct > 0:
        rationale = f"Kelly capped at {max_position_pct}% limit"
    elif adjusted_kelly_pct > 0 and risk_penalty_pct > adjusted_kelly_pct / 2.0:
        rationale = "High risk reduces allocation significantly"
    else:
        rationale = f"{final_pct:.1f}% Kelly allocation (adjusted {kelly_fraction * 100:.0f}% fractional)"

    return {
        "kelly_pct": round(kelly_pct if kelly_pct != float("inf") else max_position_pct * 4, 4),
        "adjusted_kelly_pct": round(adjusted_kelly_pct, 4),
        "risk_penalty_pct": round(risk_penalty_pct, 4),
        "final_pct": round(final_pct, 4),
        "recommended_usd": round(recommended_usd, 4),
        "viable": viable,
        "rationale": rationale,
    }


def analyze(
    portfolio_usd: float,
    opportunities: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Recommend optimal position sizes for DeFi protocols.

    opportunities: list of {
        "protocol": str,
        "expected_apy": float,       # annual %
        "risk_score": int,           # 0-100
        "max_loss_scenario_pct": float,  # worst-case loss % (e.g. 80)
        "win_probability": float     # 0-1
    }
    config: {
        "kelly_fraction": float,     # default 0.25
        "max_position_pct": float,   # default 35.0
        "min_position_usd": float    # default 200.0
    }

    Returns dict with per-protocol recommendations + portfolio summary.
    Appends result to ring-buffer log at data/position_size_log.json.
    """
    cfg = config or {}
    kelly_fraction: float = float(cfg.get("kelly_fraction", _DEFAULT_KELLY_FRACTION))
    max_position_pct: float = float(cfg.get("max_position_pct", _DEFAULT_MAX_POSITION_PCT))
    min_position_usd: float = float(cfg.get("min_position_usd", _DEFAULT_MIN_POSITION_USD))
    log_path: str = cfg.get("log_path", _DEFAULT_LOG)

    portfolio: float = float(portfolio_usd)

    recommendations: List[Dict[str, Any]] = []

    for opp in opportunities:
        protocol: str = str(opp["protocol"])
        expected_apy: float = float(opp["expected_apy"])
        risk_score: int = int(opp["risk_score"])
        max_loss: float = float(opp["max_loss_scenario_pct"])
        win_prob: float = float(opp["win_probability"])

        metrics = _compute_kelly(
            expected_apy=expected_apy,
            risk_score=risk_score,
            max_loss_scenario_pct=max_loss,
            win_probability=win_prob,
            kelly_fraction=kelly_fraction,
            max_position_pct=max_position_pct,
            min_position_usd=min_position_usd,
            portfolio_usd=portfolio,
        )

        rec = {"protocol": protocol}
        rec.update(metrics)
        recommendations.append(rec)

    # ── portfolio-level summary ────────────────────────────────────────────
    viable_count = sum(1 for r in recommendations if r["viable"])
    total_allocated_usd = sum(r["recommended_usd"] for r in recommendations)
    unallocated_usd = max(0.0, portfolio - total_allocated_usd)
    allocation_pct = (total_allocated_usd / portfolio * 100.0) if portfolio > 0 else 0.0

    result: Dict[str, Any] = {
        "portfolio_usd": portfolio,
        "recommendations": recommendations,
        "viable_count": viable_count,
        "total_allocated_usd": round(total_allocated_usd, 4),
        "unallocated_usd": round(unallocated_usd, 4),
        "allocation_pct": round(allocation_pct, 4),
        "timestamp": time.time(),
    }

    _append_log(result, log_path)
    return result


# ── ring-buffer log (atomic write) ────────────────────────────────────────

def _append_log(result: Dict[str, Any], log_path: str) -> None:
    """Append result entry to ring-buffer JSON log (cap 100). Atomic write."""
    log_path = os.path.normpath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entries.append(result)
    if len(entries) > RING_BUFFER_CAP:
        entries = entries[-RING_BUFFER_CAP:]

    tmp_path = log_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(tmp_path, log_path)


# ── CLI convenience ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    _DEMO_OPPORTUNITIES = [
        {
            "protocol": "Aave V3",
            "expected_apy": 4.5,
            "risk_score": 20,
            "max_loss_scenario_pct": 30.0,
            "win_probability": 0.9,
        },
        {
            "protocol": "Risky Protocol",
            "expected_apy": 40.0,
            "risk_score": 80,
            "max_loss_scenario_pct": 90.0,
            "win_probability": 0.5,
        },
    ]
    res = analyze(100_000.0, _DEMO_OPPORTUNITIES)
    print(json.dumps(res, indent=2))
    sys.exit(0)
