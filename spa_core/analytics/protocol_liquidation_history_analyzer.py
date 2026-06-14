#!/usr/bin/env python3
"""Protocol Liquidation History Analyzer (SPA-V672 / MP-867) — read-only / advisory.

Analyzes historical liquidation events at lending protocols to assess systemic risk,
cascade potential, and protocol health during stress events.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer history capped at 100 entries in data/liquidation_history_log.json.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Cascade Risk Score (0–100, higher = more risky)
-------------------------------------------------
  Sub-components (additive):
    liquidation_rate_component  0–30  based on liquidation_rate_pct (30d liq / TVL * 100)
    bad_debt_component          0–30  based on bad_debt_ratio_pct (bad_debt / TVL * 100)
    peak_component              0–20  based on peak_to_tvl_pct (peak_single_day / TVL * 100)
    health_component            0–20  based on avg_health_factor_collateral

  cascade_risk_score = min(100, sum of components)

Systemic Risk Labels
--------------------
  CRITICAL:  score >= 80
  HIGH:      score >= 60
  ELEVATED:  score >= 40
  MODERATE:  score >= 20
  LOW:       score < 20

CLI
---
  python3 -m spa_core.analytics.protocol_liquidation_history_analyzer --check
  python3 -m spa_core.analytics.protocol_liquidation_history_analyzer --run
  python3 -m spa_core.analytics.protocol_liquidation_history_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_LOG_FILE = "data/liquidation_history_log.json"
_RING_BUFFER_CAP = 100
_DEFAULT_LARGE_LIQUIDATION_THRESHOLD_PCT = 1.0


# ---------------------------------------------------------------------------
# Core scoring helpers
# ---------------------------------------------------------------------------

def _liquidation_rate_component(liquidation_rate_pct: float) -> int:
    """Return liquidation_rate sub-score (0–30)."""
    if liquidation_rate_pct >= 10.0:
        return 30
    elif liquidation_rate_pct >= 5.0:
        return 25
    elif liquidation_rate_pct >= 2.0:
        return 18
    elif liquidation_rate_pct >= 1.0:
        return 10
    elif liquidation_rate_pct >= 0.5:
        return 5
    else:
        return 0


def _bad_debt_component(bad_debt_ratio_pct: float, bad_debt_usd: float) -> int:
    """Return bad_debt sub-score (0–30)."""
    if bad_debt_ratio_pct >= 1.0:
        return 30
    elif bad_debt_ratio_pct >= 0.5:
        return 25
    elif bad_debt_ratio_pct >= 0.2:
        return 15
    elif bad_debt_ratio_pct >= 0.1:
        return 8
    elif bad_debt_ratio_pct >= 0.01:
        return 3
    else:
        # < 0.01 and bad_debt_usd == 0
        if bad_debt_usd == 0:
            return 0
        return 0


def _peak_component(peak_to_tvl_pct: float) -> int:
    """Return peak sub-score (0–20)."""
    if peak_to_tvl_pct >= 5.0:
        return 20
    elif peak_to_tvl_pct >= 2.0:
        return 15
    elif peak_to_tvl_pct >= 1.0:
        return 10
    elif peak_to_tvl_pct >= 0.5:
        return 5
    else:
        return 0


def _health_component(avg_health_factor: float) -> int:
    """Return health_factor sub-score (0–20)."""
    if avg_health_factor < 1.05:
        return 20
    elif avg_health_factor < 1.1:
        return 15
    elif avg_health_factor < 1.25:
        return 8
    elif avg_health_factor < 1.5:
        return 3
    else:
        return 0


def _cascade_risk_score(
    liquidation_rate_pct: float,
    bad_debt_ratio_pct: float,
    bad_debt_usd: float,
    peak_to_tvl_pct: float,
    avg_health_factor: float,
) -> int:
    """Compute total cascade risk score (0–100)."""
    total = (
        _liquidation_rate_component(liquidation_rate_pct)
        + _bad_debt_component(bad_debt_ratio_pct, bad_debt_usd)
        + _peak_component(peak_to_tvl_pct)
        + _health_component(avg_health_factor)
    )
    return min(100, total)


def _systemic_risk_label(score: int) -> str:
    """Map cascade_risk_score to systemic risk label."""
    if score >= 80:
        return "CRITICAL"
    elif score >= 60:
        return "HIGH"
    elif score >= 40:
        return "ELEVATED"
    elif score >= 20:
        return "MODERATE"
    else:
        return "LOW"


def _liquidator_incentive_adequacy(liquidation_penalty_pct: float) -> str:
    """Assess liquidator incentive based on penalty percentage."""
    if liquidation_penalty_pct >= 15.0:
        return "EXCESSIVE"
    elif liquidation_penalty_pct >= 5.0:
        return "ADEQUATE"
    elif liquidation_penalty_pct >= 3.0:
        return "LOW"
    else:
        return "INSUFFICIENT"


def _health_factor_label(avg_health_factor: float) -> str:
    """Map avg health factor to label."""
    if avg_health_factor < 1.05:
        return "CRITICAL"
    elif avg_health_factor < 1.15:
        return "STRESSED"
    elif avg_health_factor < 1.3:
        return "WATCH"
    else:
        return "HEALTHY"


def _recommendation(
    systemic_label: str,
    bad_debt_ratio_pct: float,
    liquidation_rate_pct: float,
    peak_to_tvl_pct: float,
    avg_health_factor: float,
) -> str:
    """Build recommendation string based on systemic risk label."""
    if systemic_label == "CRITICAL":
        return (
            f"CRITICAL cascade risk. Bad debt {bad_debt_ratio_pct:.2f}% of TVL. "
            f"Reduce exposure immediately."
        )
    elif systemic_label == "HIGH":
        return (
            f"High liquidation activity ({liquidation_rate_pct:.1f}% of TVL in 30d). "
            f"Consider reducing positions."
        )
    elif systemic_label == "ELEVATED":
        return (
            f"Monitor closely. Peak single-day liquidation was {peak_to_tvl_pct:.1f}% of TVL."
        )
    elif systemic_label == "MODERATE":
        return (
            f"Moderate liquidation history. Avg health factor {avg_health_factor:.2f}."
        )
    else:  # LOW
        return (
            f"Protocol shows healthy collateral ratios. Avg HF {avg_health_factor:.2f}, "
            f"low liquidations."
        )


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(
    protocols: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyze historical liquidation data across lending protocols.

    Parameters
    ----------
    protocols:
        List of protocol dicts with liquidation metrics.
    config:
        Optional config dict. Supports:
          "large_liquidation_threshold_pct": float  (default 1.0)

    Returns
    -------
    dict with per-protocol scores, aggregate risk metrics, and timestamp.
    """
    cfg = config or {}
    # large_liquidation_threshold_pct is available for future use / config doc
    _large_liq_threshold = float(
        cfg.get("large_liquidation_threshold_pct", _DEFAULT_LARGE_LIQUIDATION_THRESHOLD_PCT)
    )

    if not protocols:
        return {
            "protocols": [],
            "highest_cascade_risk": None,
            "safest_protocol": None,
            "protocols_with_bad_debt": [],
            "average_cascade_risk": 0.0,
            "timestamp": time.time(),
        }

    results = []
    protocols_with_bad_debt: List[str] = []

    for p in protocols:
        name = str(p.get("name", "unknown"))
        total_liq_30d = float(p.get("total_liquidations_30d_usd", 0.0))
        liq_count_30d = int(p.get("liquidations_count_30d", 0))
        peak_single_day = float(p.get("peak_single_day_usd", 0.0))
        tvl = float(p.get("total_tvl_usd", 0.0))
        bad_debt = float(p.get("bad_debt_usd", 0.0))
        penalty_pct = float(p.get("liquidation_penalty_pct", 0.0))
        avg_hf = float(p.get("avg_health_factor_collateral", 1.5))

        # Derived rates
        liquidation_rate_pct = (total_liq_30d / tvl * 100.0) if tvl > 0 else 0.0
        bad_debt_ratio_pct = (bad_debt / tvl * 100.0) if tvl > 0 else 0.0
        avg_liq_size = (total_liq_30d / liq_count_30d) if liq_count_30d > 0 else 0.0
        peak_to_tvl_pct = (peak_single_day / tvl * 100.0) if tvl > 0 else 0.0

        # Scores / labels
        score = _cascade_risk_score(
            liquidation_rate_pct, bad_debt_ratio_pct, bad_debt, peak_to_tvl_pct, avg_hf
        )
        risk_label = _systemic_risk_label(score)
        incentive = _liquidator_incentive_adequacy(penalty_pct)
        hf_label = _health_factor_label(avg_hf)
        rec = _recommendation(
            risk_label, bad_debt_ratio_pct, liquidation_rate_pct, peak_to_tvl_pct, avg_hf
        )

        if bad_debt > 0:
            protocols_with_bad_debt.append(name)

        results.append(
            {
                "name": name,
                "liquidation_rate_pct": round(liquidation_rate_pct, 6),
                "bad_debt_ratio_pct": round(bad_debt_ratio_pct, 6),
                "cascade_risk_score": score,
                "systemic_risk_label": risk_label,
                "avg_liquidation_size_usd": round(avg_liq_size, 2),
                "peak_to_tvl_pct": round(peak_to_tvl_pct, 6),
                "liquidator_incentive_adequacy": incentive,
                "health_factor_label": hf_label,
                "recommendation": rec,
            }
        )

    # Aggregate
    scores = [r["cascade_risk_score"] for r in results]
    avg_cascade = sum(scores) / len(scores) if scores else 0.0

    highest_risk_result = max(results, key=lambda r: r["cascade_risk_score"])
    safest_result = min(results, key=lambda r: r["cascade_risk_score"])

    return {
        "protocols": results,
        "highest_cascade_risk": highest_risk_result["name"],
        "safest_protocol": safest_result["name"],
        "protocols_with_bad_debt": protocols_with_bad_debt,
        "average_cascade_risk": round(avg_cascade, 4),
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer)
# ---------------------------------------------------------------------------

def _load_log(log_path: Path) -> List[Dict[str, Any]]:
    """Load existing ring-buffer log or return empty list."""
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_log(log_path: Path, entries: List[Dict[str, Any]]) -> None:
    """Atomically save ring-buffer log (capped at _RING_BUFFER_CAP)."""
    entries = entries[-_RING_BUFFER_CAP:]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(log_path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp, str(log_path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run(
    protocols: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze and persist result to ring-buffer log."""
    result = analyze(protocols, config)
    base = Path(data_dir) if data_dir else Path(".")
    log_path = base / _DEFAULT_LOG_FILE
    entries = _load_log(log_path)
    entries.append(result)
    _save_log(log_path, entries)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_sample_protocols() -> List[Dict[str, Any]]:
    """Return sample protocol data for CLI demonstration."""
    return [
        {
            "name": "AaveV3",
            "total_liquidations_30d_usd": 5_000_000,
            "liquidations_count_30d": 120,
            "peak_single_day_usd": 800_000,
            "total_tvl_usd": 800_000_000,
            "bad_debt_usd": 0,
            "liquidation_penalty_pct": 5.0,
            "avg_health_factor_collateral": 1.45,
            "days_since_last_large_liquidation": 45,
        },
        {
            "name": "CompoundV3",
            "total_liquidations_30d_usd": 1_200_000,
            "liquidations_count_30d": 30,
            "peak_single_day_usd": 400_000,
            "total_tvl_usd": 300_000_000,
            "bad_debt_usd": 25_000,
            "liquidation_penalty_pct": 8.0,
            "avg_health_factor_collateral": 1.55,
            "days_since_last_large_liquidation": 90,
        },
    ]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Protocol Liquidation History Analyzer (MP-867)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print result without saving to disk (default)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save result to data/liquidation_history_log.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override base directory for data files",
    )
    args = parser.parse_args(argv)

    protocols = _build_sample_protocols()

    if args.run:
        result = run(protocols, data_dir=args.data_dir)
        print(json.dumps(result, indent=2))
    else:
        result = analyze(protocols)
        print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
