"""
MP-849 DeFiPortfolioStressTester
Runs a DeFi portfolio through predefined historical crisis scenarios to estimate
worst-case drawdowns and identify the most vulnerable positions.

Pure stdlib, read-only/advisory, atomic ring-buffer log (100 entries).
"""

import json
import os
import time
import tempfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "portfolio_stress_log.json"
)
RING_BUFFER_MAX = 100

# Built-in historical crisis scenarios
# Each entry: {
#   "name": str,
#   "description": str,
#   "collateral_shocks": {collateral_type -> loss_pct (positive = loss)},
#   "category_shocks": {category -> extra_loss_pct (positive = more loss)},
# }
BUILTIN_SCENARIOS = [
    {
        "name": "March 2020 Crash",
        "description": (
            "COVID-19 crypto market crash: ETH -50%, BTC -40%, "
            "stablecoins safe, AMMs suffer impermanent loss."
        ),
        "collateral_shocks": {
            "ETH": 50.0,
            "BTC": 40.0,
            "ALTCOIN": 60.0,
            "STABLECOIN": 0.0,
        },
        "category_shocks": {
            "DEX": 10.0,          # AMM impermanent loss
            "lending": 5.0,
            "stablecoin": 0.0,
            "staking": 5.0,
            "liquid_staking": 30.0,  # depeg risk in crash
        },
    },
    {
        "name": "Terra/Luna Collapse",
        "description": (
            "Algorithmic stablecoin death spiral: UST/LUNA to zero, "
            "contagion hits stablecoins and lending protocols."
        ),
        "collateral_shocks": {
            "STABLECOIN": 30.0,
            "ETH": 20.0,
            "BTC": 15.0,
            "ALTCOIN": 40.0,
        },
        "category_shocks": {
            "stablecoin": 50.0,  # depeg contagion
            "lending": 15.0,     # bad debt accumulation
            "DEX": 0.0,
            "staking": 0.0,
            "liquid_staking": 0.0,
        },
    },
    {
        "name": "FTX Contagion",
        "description": (
            "FTX exchange collapse and credit crunch: ETH -30%, "
            "BTC -25%, ALTCOIN -55%, DEX gains relative to CeFi."
        ),
        "collateral_shocks": {
            "STABLECOIN": 5.0,
            "ETH": 30.0,
            "BTC": 25.0,
            "ALTCOIN": 55.0,
        },
        "category_shocks": {
            "lending": 10.0,
            "DEX": -5.0,     # flight to DEX (negative = less loss)
            "staking": 10.0,
            "stablecoin": 0.0,
            "liquid_staking": 0.0,
        },
    },
    {
        "name": "ETH Merge Uncertainty",
        "description": (
            "Pre-Merge fear of validator slashing and chain split: "
            "staking protocols hit hardest, liquid staking depegs."
        ),
        "collateral_shocks": {
            "STABLECOIN": 0.0,
            "ETH": 20.0,
            "BTC": 10.0,
            "ALTCOIN": 25.0,
        },
        "category_shocks": {
            "staking": 20.0,        # validator uncertainty
            "liquid_staking": 25.0,
            "DEX": 0.0,
            "lending": 0.0,
            "stablecoin": 0.0,
        },
    },
    {
        "name": "DeFi Summer Reversal",
        "description": (
            "Yield farming collapse: token emissions end, ALTCOIN -70%, "
            "DEX TVL drains, staking rewards drop."
        ),
        "collateral_shocks": {
            "STABLECOIN": 2.0,
            "ETH": 15.0,
            "BTC": 10.0,
            "ALTCOIN": 70.0,
        },
        "category_shocks": {
            "DEX": 20.0,
            "staking": 30.0,
            "lending": 5.0,
            "stablecoin": 0.0,
            "liquid_staking": 0.0,
        },
    },
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_data_path(data_dir: str | None = None) -> str:
    if data_dir is not None:
        return os.path.join(data_dir, "portfolio_stress_log.json")
    return DATA_FILE


def _load_log(path: str) -> list:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _save_log(path: str, entries: list) -> None:
    """Atomically write ring-buffer log capped at RING_BUFFER_MAX."""
    capped = entries[-RING_BUFFER_MAX:]
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_path or ".", prefix=".stress_tmp_")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(capped, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _compute_position_loss(
    position: dict,
    collateral_shocks: dict,
    category_shocks: dict,
) -> float:
    """
    Returns loss percentage for a single position (0–100).

    base_loss  = collateral_shock (abs value, positive = loss)
    cat_shock  = category modifier (negative = less loss, positive = more loss)
    total_loss = base_loss + cat_shock, clamped to [0, 100]

    Both shocks are looked up case-insensitively (collateral upper, category lower).
    """
    collateral = position.get("collateral_type", "").upper()
    category = position.get("category", "").lower()

    # Normalize shock dict keys for case-insensitive lookup
    col_shocks_norm = {k.upper(): v for k, v in collateral_shocks.items()}
    cat_shocks_norm = {k.lower(): v for k, v in category_shocks.items()}

    base_loss = abs(col_shocks_norm.get(collateral, 0.0))
    cat_shock = cat_shocks_norm.get(category, 0.0)

    # Negative category shock means the category fares *better* than raw
    # collateral shock — treat it as a reduction (still floor at 0).
    total_loss = base_loss + cat_shock  # cat_shock can be negative
    return min(100.0, max(0.0, total_loss))


def _severity(loss_pct: float) -> str:
    if loss_pct >= 50.0:
        return "CATASTROPHIC"
    if loss_pct >= 30.0:
        return "SEVERE"
    if loss_pct >= 15.0:
        return "MODERATE"
    return "MILD"


def _run_scenario(
    portfolio: list[dict],
    scenario_name: str,
    scenario_description: str,
    collateral_shocks: dict,
    category_shocks: dict,
) -> dict:
    """Execute a single scenario and return the scenario result dict."""
    if not portfolio:
        return {
            "scenario_name": scenario_name,
            "description": scenario_description,
            "portfolio_loss_pct": 0.0,
            "portfolio_loss_usd": 0.0,
            "worst_position": None,
            "surviving_positions": [],
            "severity": _severity(0.0),
        }

    total_value = sum(p.get("position_value_usd", 0.0) for p in portfolio)

    position_losses: list[dict] = []
    for pos in portfolio:
        alloc = pos.get("allocation_pct", 0.0)
        value = pos.get("position_value_usd", 0.0)
        loss_pct = _compute_position_loss(pos, collateral_shocks, category_shocks)
        position_losses.append(
            {
                "protocol": pos.get("protocol", "unknown"),
                "loss_pct": loss_pct,
                "alloc": alloc,
                "loss_usd": value * loss_pct / 100.0,
            }
        )

    # Weighted portfolio loss
    portfolio_loss_pct = sum(
        pl["loss_pct"] * pl["alloc"] / 100.0 for pl in position_losses
    )

    # Absolute dollar loss (based on actual position values)
    portfolio_loss_usd = sum(pl["loss_usd"] for pl in position_losses)

    # Worst and surviving
    worst = max(position_losses, key=lambda x: x["loss_pct"])
    surviving = [pl["protocol"] for pl in position_losses if pl["loss_pct"] < 20.0]

    return {
        "scenario_name": scenario_name,
        "description": scenario_description,
        "portfolio_loss_pct": round(portfolio_loss_pct, 4),
        "portfolio_loss_usd": round(portfolio_loss_usd, 2),
        "worst_position": worst["protocol"],
        "surviving_positions": surviving,
        "severity": _severity(portfolio_loss_pct),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(
    portfolio: list[dict],
    config: dict | None = None,
    _data_dir: str | None = None,
) -> dict:
    """
    Run DeFi portfolio through historical crisis scenarios.

    Parameters
    ----------
    portfolio : list[dict]
        Each item: {
          "protocol": str,
          "category": str,          # stablecoin|lending|DEX|staking|liquid_staking
          "allocation_pct": float,
          "position_value_usd": float,
          "collateral_type": str,   # STABLECOIN|ETH|BTC|ALTCOIN
        }
    config : dict | None
        Optional: {"custom_scenarios": list[dict] | None}

    Returns
    -------
    dict with keys: scenarios, worst_scenario, best_scenario,
                    average_loss_pct, portfolio_resilience_score,
                    most_vulnerable_position, timestamp
    """
    if config is None:
        config = {}

    # Build scenario list
    scenarios_spec: list[dict] = list(BUILTIN_SCENARIOS)

    custom = config.get("custom_scenarios") or []
    for cs in custom:
        shocks = cs.get("shocks", {})
        scenarios_spec.append(
            {
                "name": cs.get("name", "Custom"),
                "description": cs.get("description", ""),
                "collateral_shocks": shocks.get("by_collateral", {}),
                "category_shocks": shocks.get("by_category", {}),
            }
        )

    # Run all scenarios
    scenario_results: list[dict] = []
    for spec in scenarios_spec:
        result = _run_scenario(
            portfolio,
            spec["name"],
            spec["description"],
            spec.get("collateral_shocks", {}),
            spec.get("category_shocks", {}),
        )
        scenario_results.append(result)

    # Aggregate metrics
    if scenario_results:
        loss_values = [s["portfolio_loss_pct"] for s in scenario_results]
        worst_scenario = scenario_results[
            loss_values.index(max(loss_values))
        ]["scenario_name"]
        best_scenario = scenario_results[
            loss_values.index(min(loss_values))
        ]["scenario_name"]
        average_loss_pct = round(sum(loss_values) / len(loss_values), 4)
    else:
        worst_scenario = None
        best_scenario = None
        average_loss_pct = 0.0

    resilience_score = max(0, min(100, int(100 - average_loss_pct)))

    # Most vulnerable position (highest mean loss across all scenarios)
    most_vulnerable = _find_most_vulnerable(portfolio, scenarios_spec)

    ts = time.time()
    result = {
        "scenarios": scenario_results,
        "worst_scenario": worst_scenario,
        "best_scenario": best_scenario,
        "average_loss_pct": average_loss_pct,
        "portfolio_resilience_score": resilience_score,
        "most_vulnerable_position": most_vulnerable,
        "timestamp": ts,
    }

    # Persist to ring-buffer log
    log_path = _get_data_path(_data_dir)
    try:
        entries = _load_log(log_path)
        entries.append(result)
        _save_log(log_path, entries)
    except Exception:
        pass  # advisory — never crash caller

    return result


def _find_most_vulnerable(
    portfolio: list[dict], scenarios_spec: list[dict]
) -> str | None:
    """Return protocol name with highest average loss across all scenarios."""
    if not portfolio or not scenarios_spec:
        return None

    protocol_totals: dict[str, float] = {}
    for pos in portfolio:
        protocol = pos.get("protocol", "unknown")
        losses = []
        for spec in scenarios_spec:
            loss = _compute_position_loss(
                pos,
                spec.get("collateral_shocks", {}),
                spec.get("category_shocks", {}),
            )
            losses.append(loss)
        protocol_totals[protocol] = sum(losses) / len(losses) if losses else 0.0

    if not protocol_totals:
        return None
    return max(protocol_totals, key=lambda k: protocol_totals[k])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MP-849 DeFiPortfolioStressTester")
    parser.add_argument("--check", action="store_true", help="Run on sample portfolio")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    sample = [
        {
            "protocol": "Aave V3",
            "category": "lending",
            "allocation_pct": 40.0,
            "position_value_usd": 40_000.0,
            "collateral_type": "STABLECOIN",
        },
        {
            "protocol": "Uniswap V3",
            "category": "DEX",
            "allocation_pct": 30.0,
            "position_value_usd": 30_000.0,
            "collateral_type": "ETH",
        },
        {
            "protocol": "Lido",
            "category": "liquid_staking",
            "allocation_pct": 30.0,
            "position_value_usd": 30_000.0,
            "collateral_type": "ETH",
        },
    ]

    out = analyze(sample, _data_dir=args.data_dir)
    print(json.dumps(out, indent=2))
    sys.exit(0)
