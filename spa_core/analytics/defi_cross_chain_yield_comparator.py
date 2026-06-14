"""
MP-861 DeFiCrossChainYieldComparator
=====================================
Advisory-only analytics module. Compares yield opportunities across chains
(Ethereum, Arbitrum, Base, Optimism, etc.) accounting for bridge costs,
gas fees, and holding period economics.

Pure Python stdlib. No external dependencies.
Atomic writes via tmp + os.replace.
"""

import json
import os
import time
import tempfile
from typing import Any

_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "cross_chain_yield_log.json"
)
_LOG_CAP = 100


def _resolve_data_file(data_dir: str | None) -> str:
    if data_dir:
        return os.path.join(data_dir, "cross_chain_yield_log.json")
    return os.path.abspath(_DATA_FILE)


def _atomic_write(path: str, obj: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, record: dict) -> None:
    log = _load_log(path)
    log.append(record)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    _atomic_write(path, log)


# ─────────────────────────────────────────────────────────────────────────────
# Label & recommendation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _efficiency_label(net_apy_pct: float, gross_apy_pct: float) -> str:
    if gross_apy_pct <= 0:
        efficiency = 1.0
    else:
        efficiency = net_apy_pct / gross_apy_pct

    if net_apy_pct <= 0:
        return "UNVIABLE"
    if efficiency >= 0.9:
        return "EXCELLENT"
    if efficiency >= 0.75:
        return "GOOD"
    if efficiency >= 0.5:
        return "FAIR"
    if efficiency >= 0.25:
        return "POOR"
    return "UNVIABLE"


def _recommendation(
    label: str,
    chain: str,
    net_apy_pct: float,
    bridge_cost_usd: float,
    holding_period_days: int,
    break_even_days: float,
    net_yield_usd: float,
) -> str:
    if label == "EXCELLENT":
        return (
            f"Deploy on {chain}. Net APY {net_apy_pct:.2f}% after "
            f"{bridge_cost_usd:.0f} USD bridge cost."
        )
    if label == "GOOD":
        return (
            f"{chain} viable. {net_apy_pct:.2f}% net APY with "
            f"{holding_period_days}d holding."
        )
    if label == "FAIR":
        return f"Marginal on {chain}. Break-even at {break_even_days:.0f} days."
    if label == "POOR":
        return f"High overhead on {chain}. Consider longer holding period."
    # UNVIABLE
    return (
        f"Costs exceed yield on {chain}. Net yield negative "
        f"({net_yield_usd:.0f} USD)."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core analyze function
# ─────────────────────────────────────────────────────────────────────────────

def analyze(
    opportunities: list,
    config: dict | None = None,
    data_dir: str | None = None,
    persist: bool = False,
) -> dict:
    """
    Compares yield opportunities across chains accounting for bridge costs,
    gas fees, and holding period economics.

    Parameters
    ----------
    opportunities : list[dict]
        Each entry must contain:
          protocol, chain, gross_apy_pct, bridge_cost_usd,
          gas_cost_per_interaction_usd, interactions_per_month,
          capital_usd, holding_period_days
    config : dict, optional
        reference_chain (default "ethereum"), annual_overhead_factor (default 1.0)
    data_dir : str, optional
        Override directory for log file.
    persist : bool
        If True, append result to ring-buffer log.

    Returns
    -------
    dict with enriched opportunities list and summary fields.
    """
    cfg = config or {}
    reference_chain: str = str(cfg.get("reference_chain", "ethereum")).lower()

    ts = time.time()

    # ── Empty input ──────────────────────────────────────────────────────────
    if not opportunities:
        result = {
            "opportunities": [],
            "best_net_yield": None,
            "best_net_apy": None,
            "reference_chain_net_apy": None,
            "chain_summary": {},
            "timestamp": ts,
        }
        if persist:
            _append_log(_resolve_data_file(data_dir), result)
        return result

    # ── Per-opportunity calculations ─────────────────────────────────────────
    enriched = []
    for opp in opportunities:
        protocol = str(opp.get("protocol", ""))
        chain = str(opp.get("chain", "")).lower()
        gross_apy_pct = float(opp.get("gross_apy_pct", 0.0))
        bridge_cost_usd = float(opp.get("bridge_cost_usd", 0.0))
        gas_per_interaction = float(opp.get("gas_cost_per_interaction_usd", 0.0))
        interactions_per_month = int(opp.get("interactions_per_month", 0))
        capital_usd = float(opp.get("capital_usd", 0.0))
        holding_period_days = int(opp.get("holding_period_days", 0))

        # gross yield
        if capital_usd > 0 and holding_period_days > 0:
            gross_yield_usd = capital_usd * (gross_apy_pct / 100.0) * (holding_period_days / 365.0)
        else:
            gross_yield_usd = 0.0

        # gas overhead
        if holding_period_days > 0:
            gas_overhead_usd = gas_per_interaction * interactions_per_month * (holding_period_days / 30.0)
        else:
            gas_overhead_usd = 0.0

        # net yield
        net_yield_usd = gross_yield_usd - bridge_cost_usd - gas_overhead_usd

        # net APY
        if capital_usd > 0 and holding_period_days > 0:
            net_apy_pct = (net_yield_usd / capital_usd / holding_period_days) * 365 * 100
        else:
            net_apy_pct = 0.0

        # break-even
        daily_yield = gross_yield_usd / holding_period_days if holding_period_days > 0 else 0.0
        total_fixed_costs = bridge_cost_usd + gas_overhead_usd
        if daily_yield > 0:
            bev = total_fixed_costs / daily_yield
            break_even_days = bev
        else:
            break_even_days = 99999.0

        # label & recommendation
        label = _efficiency_label(net_apy_pct, gross_apy_pct)
        rec = _recommendation(
            label, chain, net_apy_pct, bridge_cost_usd,
            holding_period_days, break_even_days, net_yield_usd,
        )

        enriched.append({
            "protocol": protocol,
            "chain": chain,
            "gross_apy_pct": gross_apy_pct,
            "gross_yield_usd": gross_yield_usd,
            "bridge_cost_usd": bridge_cost_usd,
            "gas_overhead_usd": gas_overhead_usd,
            "net_yield_usd": net_yield_usd,
            "net_apy_pct": net_apy_pct,
            "break_even_days": break_even_days,
            "chain_efficiency_label": label,
            "recommendation": rec,
            # vs_reference filled below
        })

    # ── Reference chain net APY ──────────────────────────────────────────────
    ref_net_apy: float | None = None
    for e in enriched:
        if e["chain"] == reference_chain:
            ref_net_apy = e["net_apy_pct"]
            break

    # ── vs_reference_chain_pct ───────────────────────────────────────────────
    for e in enriched:
        if e["chain"] == reference_chain or ref_net_apy is None:
            e["vs_reference_chain_pct"] = None
        else:
            e["vs_reference_chain_pct"] = e["net_apy_pct"] - ref_net_apy

    # ── Bests ────────────────────────────────────────────────────────────────
    best_yield_entry = max(enriched, key=lambda x: x["net_yield_usd"])
    best_apy_entry = max(enriched, key=lambda x: x["net_apy_pct"])
    best_net_yield = f"{best_yield_entry['protocol']} ({best_yield_entry['chain']})"
    best_net_apy = f"{best_apy_entry['protocol']} ({best_apy_entry['chain']})"

    # ── Chain summary ────────────────────────────────────────────────────────
    chain_groups: dict[str, list] = {}
    for e in enriched:
        chain_groups.setdefault(e["chain"], []).append(e["net_apy_pct"])

    chain_summary: dict[str, dict] = {}
    for ch, apys in chain_groups.items():
        chain_summary[ch] = {
            "count": len(apys),
            "avg_net_apy": sum(apys) / len(apys),
            "best_net_apy": max(apys),
        }

    result = {
        "opportunities": enriched,
        "best_net_yield": best_net_yield,
        "best_net_apy": best_net_apy,
        "reference_chain_net_apy": ref_net_apy,
        "chain_summary": chain_summary,
        "timestamp": ts,
    }

    if persist:
        _append_log(_resolve_data_file(data_dir), result)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _demo() -> None:
    import pprint
    demo_opps = [
        {
            "protocol": "AaveV3",
            "chain": "ethereum",
            "gross_apy_pct": 3.5,
            "bridge_cost_usd": 0.0,
            "gas_cost_per_interaction_usd": 15.0,
            "interactions_per_month": 2,
            "capital_usd": 100_000,
            "holding_period_days": 90,
        },
        {
            "protocol": "AaveV3",
            "chain": "arbitrum",
            "gross_apy_pct": 4.6,
            "bridge_cost_usd": 5.0,
            "gas_cost_per_interaction_usd": 0.5,
            "interactions_per_month": 4,
            "capital_usd": 100_000,
            "holding_period_days": 90,
        },
        {
            "protocol": "CompoundV3",
            "chain": "base",
            "gross_apy_pct": 5.2,
            "bridge_cost_usd": 8.0,
            "gas_cost_per_interaction_usd": 0.3,
            "interactions_per_month": 4,
            "capital_usd": 100_000,
            "holding_period_days": 90,
        },
    ]
    res = analyze(demo_opps)
    pprint.pprint(res)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-861 DeFi Cross-Chain Yield Comparator")
    parser.add_argument("--run", action="store_true", help="Run demo and persist log")
    parser.add_argument("--check", action="store_true", help="Run demo, print, no persist (default)")
    parser.add_argument("--data-dir", dest="data_dir", default=None)
    args = parser.parse_args()

    _demo()
