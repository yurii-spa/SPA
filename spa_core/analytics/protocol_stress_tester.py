"""
MP-806 ProtocolStressTester
============================
Runs stress scenarios (market crash, liquidity crunch, smart contract pause)
against a protocol and estimates impact on portfolio yield and capital safety.

Data file: data/protocol_stress_test_log.json  (ring-buffer, max 100 entries)
Advisory / read-only — never touches allocator, risk, or execution domains.
Pure stdlib only.
"""

from __future__ import annotations

import json
import os
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "protocol_stress_test_log.json"
)
_LOG_CAP = 100

_DEFAULT_SCENARIOS: list[dict] = [
    {
        "name": "Market Correction",
        "tvl_drop_pct": 20,
        "utilization_spike_pct": 10,
        "severity": "LOW",
    },
    {
        "name": "Bear Market",
        "tvl_drop_pct": 50,
        "utilization_spike_pct": 20,
        "severity": "MEDIUM",
    },
    {
        "name": "Market Crash",
        "tvl_drop_pct": 70,
        "utilization_spike_pct": 30,
        "severity": "HIGH",
    },
    {
        "name": "Black Swan",
        "tvl_drop_pct": 90,
        "utilization_spike_pct": 40,
        "severity": "EXTREME",
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_scenario(
    scenario: dict,
    tvl_usd: float,
    utilization_rate: float,
    liquidity_buffer_pct: float,
    protocol_reserves_usd: float,
) -> dict:
    """Compute a single stress scenario result."""
    tvl_drop_pct = float(scenario["tvl_drop_pct"])
    utilization_spike_pct = float(scenario["utilization_spike_pct"])
    severity = scenario["severity"]
    name = scenario["name"]

    post_tvl = tvl_usd * (1.0 - tvl_drop_pct / 100.0)
    post_utilization = min(1.0, utilization_rate + utilization_spike_pct / 100.0)

    available_liquidity = post_tvl * liquidity_buffer_pct / 100.0
    # 30% of available (undeployed) capital tries to exit
    withdrawals_needed = post_tvl * (1.0 - post_utilization) * 0.3

    liquidity_shortfall = max(
        0.0, withdrawals_needed - available_liquidity - protocol_reserves_usd
    )
    reserve_adequate = protocol_reserves_usd >= max(
        0.0, withdrawals_needed - available_liquidity
    )

    # yield_impact: APY change from utilization shift, capped 0-20
    yield_impact = (post_utilization * 2.0) - (utilization_rate * 2.0)
    yield_impact = max(0.0, min(20.0, yield_impact))

    # Outcome determination
    if (
        liquidity_shortfall > 0
        and not reserve_adequate
        and post_utilization >= 0.95
    ):
        outcome = "INSOLVENT"
    elif liquidity_shortfall > 0 or post_utilization >= 0.85:
        outcome = "STRESSED"
    else:
        outcome = "SURVIVES"

    return {
        "name": name,
        "severity": severity,
        "post_tvl_usd": round(post_tvl, 2),
        "post_utilization": round(post_utilization, 6),
        "liquidity_shortfall_usd": round(liquidity_shortfall, 2),
        "reserve_adequate": reserve_adequate,
        "outcome": outcome,
        "yield_impact_pct": round(yield_impact, 6),
    }


def _overall_resilience(scenario_results: list[dict]) -> str:
    """
    CRITICAL if >= 3 INSOLVENT, WEAK if >= 2, MODERATE if >= 1, STRONG if 0.
    """
    insolvent_count = sum(
        1 for s in scenario_results if s["outcome"] == "INSOLVENT"
    )
    if insolvent_count >= 3:
        return "CRITICAL"
    if insolvent_count >= 2:
        return "WEAK"
    if insolvent_count >= 1:
        return "MODERATE"
    return "STRONG"


def _max_survivable_tvl_drop(
    scenarios: list[dict], scenario_results: list[dict]
) -> float:
    """
    Largest tvl_drop_pct where outcome != INSOLVENT.
    Returns 100 if no INSOLVENT scenarios.
    """
    survivable = [
        float(s["tvl_drop_pct"])
        for s, r in zip(scenarios, scenario_results)
        if r["outcome"] != "INSOLVENT"
    ]
    if not survivable:
        return 0.0
    return max(survivable)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    protocol: str,
    protocol_metrics: dict,
    scenarios: list[dict] | None = None,
) -> dict:
    """
    Run stress scenarios against a protocol.

    Parameters
    ----------
    protocol : str
        Protocol name (e.g. "Aave V3").
    protocol_metrics : dict
        {
            "tvl_usd": float,
            "utilization_rate": float,   # 0–1
            "collateral_ratio": float,
            "liquidity_buffer_pct": float,
            "protocol_reserves_usd": float,
            "insurance_coverage_pct": float  # 0–100
        }
    scenarios : list[dict] or None
        Custom scenarios; defaults to the 4 standard ones.

    Returns
    -------
    dict
        Full stress-test result (see module docstring for schema).
    """
    if scenarios is None:
        scenarios = _DEFAULT_SCENARIOS

    tvl_usd = float(protocol_metrics["tvl_usd"])
    utilization_rate = float(protocol_metrics["utilization_rate"])
    liquidity_buffer_pct = float(protocol_metrics["liquidity_buffer_pct"])
    protocol_reserves_usd = float(protocol_metrics["protocol_reserves_usd"])

    baseline = {
        "tvl_usd": round(tvl_usd, 2),
        "utilization_rate": round(utilization_rate, 6),
        "available_liquidity_usd": round(tvl_usd * liquidity_buffer_pct / 100.0, 2),
        "reserve_coverage_pct": round(
            (protocol_reserves_usd / tvl_usd * 100.0) if tvl_usd > 0 else 0.0, 6
        ),
    }

    scenario_results = [
        _compute_scenario(
            sc,
            tvl_usd,
            utilization_rate,
            liquidity_buffer_pct,
            protocol_reserves_usd,
        )
        for sc in scenarios
    ]

    resilience = _overall_resilience(scenario_results)
    max_drop = _max_survivable_tvl_drop(scenarios, scenario_results)

    result = {
        "protocol": protocol,
        "baseline": baseline,
        "scenarios": scenario_results,
        "overall_resilience": resilience,
        "max_survivable_tvl_drop_pct": round(max_drop, 6),
        "timestamp": time.time(),
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _append_log(entry: dict) -> None:
    """Append result to ring-buffer log (max _LOG_CAP entries). Atomic write."""
    log_path = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "protocol_stress_test_log.json"
        )
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log: list = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(entry)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    tmp = log_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)
    os.replace(tmp, log_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:  # pragma: no cover
    metrics = {
        "tvl_usd": 500_000_000,
        "utilization_rate": 0.75,
        "collateral_ratio": 1.5,
        "liquidity_buffer_pct": 15.0,
        "protocol_reserves_usd": 5_000_000,
        "insurance_coverage_pct": 10.0,
    }
    import json as _json
    print(_json.dumps(analyze("Aave V3", metrics), indent=2))


if __name__ == "__main__":  # pragma: no cover
    _demo()
