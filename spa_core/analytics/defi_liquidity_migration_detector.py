"""
MP-901 DeFiLiquidityMigrationDetector
--------------------------------------
Advisory / read-only analytics module.
Detects and quantifies liquidity migration between DeFi protocols —
identifies when TVL is fleeing one protocol for another, signalling
risk or opportunity.

CLI:
    python3 -m spa_core.analytics.defi_liquidity_migration_detector --check
    python3 -m spa_core.analytics.defi_liquidity_migration_detector --run
    python3 -m spa_core.analytics.defi_liquidity_migration_detector --run --data-dir <dir>
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_SIGNIFICANT_CHANGE_PCT = 10.0
_LOG_CAP = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "liquidity_migration_log.json",
)


# ---------------------------------------------------------------------------
# Core analysis logic
# ---------------------------------------------------------------------------

def _tvl_change(protocol: dict) -> tuple[float, float]:
    """Return (tvl_change_usd, tvl_change_pct)."""
    current = float(protocol.get("tvl_current_usd", 0.0))
    prev = float(protocol.get("tvl_7d_ago_usd", 0.0))
    change_usd = current - prev
    change_pct = (change_usd / prev * 100.0) if prev > 0 else 0.0
    return change_usd, change_pct


def _migration_signal(tvl_change_pct: float) -> str:
    if tvl_change_pct > 20:
        return "STRONG_INFLOW"
    if tvl_change_pct > 10:
        return "INFLOW"
    if tvl_change_pct >= -10:
        return "STABLE"
    if tvl_change_pct >= -20:
        return "OUTFLOW"
    return "STRONG_OUTFLOW"


def _ecosystem_impact_score(tvl_change_pct: float, inflow_cnt: int, outflow_cnt: int) -> int:
    raw = abs(tvl_change_pct) * 2 + inflow_cnt * 5 + outflow_cnt * 5
    return min(100, int(raw))


def _risk_signal(migration_sig: str, tvl_change_reason: str) -> str:
    if migration_sig in ("STRONG_OUTFLOW", "OUTFLOW") and tvl_change_reason == "MIGRATION":
        return "FLEE_RISK"
    if migration_sig == "STRONG_INFLOW":
        return "OPPORTUNITY"
    if migration_sig == "INFLOW":
        return "GROWING"
    if migration_sig in ("OUTFLOW", "STRONG_OUTFLOW"):
        return "MONITOR"
    return "STABLE"


def _flags(tvl_change_pct: float, tvl_change_reason: str, significant_pct: float) -> list[str]:
    out: list[str] = []
    if tvl_change_pct < -significant_pct:
        out.append("SIGNIFICANT_OUTFLOW")
    if tvl_change_pct > significant_pct * 2:
        out.append("RAPID_GROWTH")
    if tvl_change_reason == "MIGRATION":
        out.append("MIGRATION_DRIVEN")
    if tvl_change_reason == "UNKNOWN":
        out.append("UNKNOWN_CAUSE")
    return out


def _recommendation(
    risk_sig: str,
    tvl_change_pct: float,
    inflow_sources: list[str],
    outflow_destinations: list[str],
) -> str:
    if risk_sig in ("OPPORTUNITY", "GROWING"):
        source_str = (
            "Migration inflow from: " + ", ".join(inflow_sources[:2])
            if inflow_sources
            else "Organic growth"
        )
        return f"TVL growing {tvl_change_pct:.1f}%. {source_str}."
    if risk_sig == "STABLE":
        return f"Stable TVL. Change: {tvl_change_pct:.1f}%."
    if risk_sig == "MONITOR":
        return f"TVL declining {tvl_change_pct:.1f}%. Monitor for continued outflows."
    # FLEE_RISK
    dest_str = (
        ", ".join(outflow_destinations[:2]) if outflow_destinations else "unknown destinations"
    )
    return (
        f"Migration-driven outflow ({tvl_change_pct:.1f}%). "
        f"Users moving to: {dest_str}."
    )


def _build_migration_pairs(protocols: list[dict], protocol_names: set[str]) -> list[dict]:
    pairs: list[dict] = []
    for p in protocols:
        dests = p.get("outflow_destinations") or []
        for dest in dests:
            flow_type = "CONFIRMED" if dest in protocol_names else "REPORTED"
            pairs.append(
                {
                    "source": p["name"],
                    "destination": dest,
                    "implied_flow_type": flow_type,
                }
            )
    return pairs


def analyze(snapshot: dict, config: dict | None = None) -> dict:
    """
    Analyse a TVL snapshot for liquidity migration signals.

    Parameters
    ----------
    snapshot : dict
        Must contain key ``"protocols"`` → list of protocol dicts.
    config : dict, optional
        ``significant_change_pct`` (default 10.0).

    Returns
    -------
    dict with keys: protocols, migration_pairs, net_ecosystem_flow,
                    biggest_gainer, biggest_loser, timestamp.
    """
    if config is None:
        config = {}
    significant_pct = float(config.get("significant_change_pct", _DEFAULT_SIGNIFICANT_CHANGE_PCT))

    raw_protocols: list[dict] = snapshot.get("protocols") or []
    protocol_names: set[str] = {p["name"] for p in raw_protocols if "name" in p}

    result_protocols: list[dict] = []
    net_flow = 0.0

    for p in raw_protocols:
        name = p.get("name", "")
        inflow_sources: list[str] = list(p.get("inflow_sources") or [])
        outflow_destinations: list[str] = list(p.get("outflow_destinations") or [])
        tvl_change_reason: str = p.get("tvl_change_reason", "UNKNOWN")

        change_usd, change_pct = _tvl_change(p)
        net_flow += change_usd

        sig = _migration_signal(change_pct)
        impact = _ecosystem_impact_score(change_pct, len(inflow_sources), len(outflow_destinations))
        risk_sig = _risk_signal(sig, tvl_change_reason)
        flag_list = _flags(change_pct, tvl_change_reason, significant_pct)
        rec = _recommendation(risk_sig, change_pct, inflow_sources, outflow_destinations)

        result_protocols.append(
            {
                "name": name,
                "tvl_change_usd": change_usd,
                "tvl_change_pct": change_pct,
                "migration_signal": sig,
                "inflow_source_count": len(inflow_sources),
                "outflow_destination_count": len(outflow_destinations),
                "migration_type": tvl_change_reason,
                "ecosystem_impact_score": impact,
                "risk_signal": risk_sig,
                "flags": flag_list,
                "recommendation": rec,
            }
        )

    # Summary fields
    pairs = _build_migration_pairs(raw_protocols, protocol_names)

    biggest_gainer: str | None = None
    biggest_loser: str | None = None
    if result_protocols:
        by_pct = [(rp["tvl_change_pct"], rp["name"]) for rp in result_protocols]
        biggest_gainer = max(by_pct, key=lambda x: x[0])[1]
        biggest_loser = min(by_pct, key=lambda x: x[0])[1]

    return {
        "protocols": result_protocols,
        "migration_pairs": pairs,
        "net_ecosystem_flow": net_flow,
        "biggest_gainer": biggest_gainer,
        "biggest_loser": biggest_loser,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_save(data, str(path))
def _read_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, entry: dict) -> None:
    """Append one entry to ring-buffer log (cap _LOG_CAP)."""
    log = _read_log(path)
    log.append(entry)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_snapshot() -> dict:
    """Return a small example snapshot for --check mode."""
    return {
        "protocols": [
            {
                "name": "Aave V3",
                "tvl_7d_ago_usd": 10_000_000,
                "tvl_current_usd": 8_000_000,
                "inflow_sources": [],
                "outflow_destinations": ["Morpho Blue", "Compound V3"],
                "tvl_change_reason": "MIGRATION",
            },
            {
                "name": "Morpho Blue",
                "tvl_7d_ago_usd": 3_000_000,
                "tvl_current_usd": 4_500_000,
                "inflow_sources": ["Aave V3"],
                "outflow_destinations": [],
                "tvl_change_reason": "MIGRATION",
            },
            {
                "name": "Compound V3",
                "tvl_7d_ago_usd": 5_000_000,
                "tvl_current_usd": 5_200_000,
                "inflow_sources": ["Aave V3"],
                "outflow_destinations": [],
                "tvl_change_reason": "ORGANIC",
            },
        ]
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-901 DeFiLiquidityMigrationDetector — advisory analytics"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run analysis on sample data, print results, do NOT write to disk (default mode).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run analysis on sample data and append result to data/liquidity_migration_log.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override directory for log file.",
    )
    args = parser.parse_args(argv)

    snapshot = _sample_snapshot()
    result = analyze(snapshot)

    # Pretty print
    print(json.dumps(result, indent=2))
    print(f"\n[MP-901] net_ecosystem_flow = {result['net_ecosystem_flow']:+,.0f} USD")
    print(f"[MP-901] biggest_gainer = {result['biggest_gainer']}")
    print(f"[MP-901] biggest_loser  = {result['biggest_loser']}")

    if args.run:
        if args.data_dir:
            log_path = os.path.join(args.data_dir, "liquidity_migration_log.json")
        else:
            log_path = _DEFAULT_LOG_PATH
        _append_log(log_path, result)
        print(f"[MP-901] Appended to {log_path}")


if __name__ == "__main__":
    main()
