"""
MP-890: ProtocolTVLConcentrationAnalyzer
Analyzes TVL concentration across protocols, chains, and asset types
for systemic risk assessment using HHI and concentration labels.

Advisory / read-only. Pure stdlib. Atomic JSON writes.
"""

import json
import os
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "tvl_concentration_log.json"
)
_LOG_CAP = 100

_DEFAULT_CONCENTRATION_WARNING_PCT = 20.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tvl_pct(tvl_usd: float, total: float) -> float:
    """Compute TVL percentage; returns 0.0 when total <= 0."""
    if total <= 0:
        return 0.0
    return tvl_usd / total * 100.0


def _concentration_label(pct: float) -> str:
    """Map TVL % to concentration label."""
    if pct > 20:
        return "DOMINANT"
    if pct > 10:
        return "SIGNIFICANT"
    if pct > 5:
        return "MODERATE"
    return "MINOR"


def _hhi(protocol_pcts: list) -> float:
    """Herfindahl-Hirschman Index on a list of tvl_pct values.

    HHI = sum((pct/100)^2 * 10000) for each protocol.
    Range: 0–10000.
    """
    return sum((p / 100.0) ** 2 * 10_000 for p in protocol_pcts)


def _concentration_risk(hhi_value: float) -> str:
    """Map HHI to concentration risk label."""
    if hhi_value < 1000:
        return "LOW"
    if hhi_value < 2500:
        return "MODERATE"
    if hhi_value < 5000:
        return "HIGH"
    return "CRITICAL"


def _build_by_chain(protocols: list, total: float) -> dict:
    """Group protocols by chain, summing TVL and counting protocols."""
    chains: dict = {}
    for p in protocols:
        chain = p.get("chain", "")
        tvl = p.get("tvl_usd", 0.0)
        if chain not in chains:
            chains[chain] = {"tvl_usd": 0.0, "tvl_pct": 0.0, "protocol_count": 0}
        chains[chain]["tvl_usd"] += tvl
        chains[chain]["protocol_count"] += 1
    for chain in chains:
        chains[chain]["tvl_pct"] = _tvl_pct(chains[chain]["tvl_usd"], total)
    return chains


def _build_by_asset_type(protocols: list, total: float) -> dict:
    """Group protocols by asset_type, summing TVL."""
    types: dict = {}
    for p in protocols:
        at = p.get("asset_type", "OTHER")
        tvl = p.get("tvl_usd", 0.0)
        if at not in types:
            types[at] = {"tvl_usd": 0.0, "tvl_pct": 0.0}
        types[at]["tvl_usd"] += tvl
    for at in types:
        types[at]["tvl_pct"] = _tvl_pct(types[at]["tvl_usd"], total)
    return types


def _top_by_tvl(mapping: dict, key: str = "tvl_usd") -> Optional[str]:
    """Return the name/key with the highest tvl_usd; None if empty."""
    if not mapping:
        return None
    return max(mapping, key=lambda k: mapping[k][key])


def _build_flags(by_protocol_list: list, by_chain: dict,
                 by_asset_type: dict,
                 concentration_warning_pct: float) -> list:
    """Build the flags list."""
    flags = []
    # SINGLE_PROTOCOL_DOMINANT: any protocol tvl_pct > concentration_warning_pct
    if any(p["tvl_pct"] > concentration_warning_pct for p in by_protocol_list):
        flags.append("SINGLE_PROTOCOL_DOMINANT")
    # SINGLE_CHAIN_DOMINANT: any chain tvl_pct > 50
    if any(by_chain[c]["tvl_pct"] > 50 for c in by_chain):
        flags.append("SINGLE_CHAIN_DOMINANT")
    # STABLECOIN_HEAVY: STABLECOIN asset type tvl_pct > 60
    sc_pct = by_asset_type.get("STABLECOIN", {}).get("tvl_pct", 0.0)
    if sc_pct > 60:
        flags.append("STABLECOIN_HEAVY")
    return flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(ecosystem: dict, config: dict = None) -> dict:
    """Analyze TVL concentration across protocols, chains, and asset types.

    Parameters
    ----------
    ecosystem : dict with keys "protocols" and "total_ecosystem_tvl_usd"
    config : optional dict with "concentration_warning_pct" (default 20)

    Returns
    -------
    dict with by_protocol, by_chain, by_asset_type, hhi, concentration_risk,
    top_protocol, top_chain, dominant_asset_type, flags, systemic_risk_score,
    timestamp.
    """
    cfg = config or {}
    concentration_warning_pct = float(
        cfg.get("concentration_warning_pct", _DEFAULT_CONCENTRATION_WARNING_PCT)
    )

    protocols = ecosystem.get("protocols", []) or []
    total = float(ecosystem.get("total_ecosystem_tvl_usd", 0.0))

    if not protocols:
        return {
            "by_protocol": [],
            "by_chain": {},
            "by_asset_type": {},
            "hhi": 0.0,
            "concentration_risk": "LOW",
            "top_protocol": None,
            "top_chain": None,
            "dominant_asset_type": None,
            "flags": [],
            "systemic_risk_score": 0,
            "timestamp": time.time(),
        }

    # Build by_protocol list
    by_protocol_list = []
    for p in protocols:
        pct = _tvl_pct(p.get("tvl_usd", 0.0), total)
        by_protocol_list.append({
            "name": p.get("name", ""),
            "tvl_usd": p.get("tvl_usd", 0.0),
            "tvl_pct": pct,
            "chain": p.get("chain", ""),
            "asset_type": p.get("asset_type", "OTHER"),
            "concentration_label": _concentration_label(pct),
        })

    by_chain = _build_by_chain(protocols, total)
    by_asset_type = _build_by_asset_type(protocols, total)

    pcts = [p["tvl_pct"] for p in by_protocol_list]
    hhi_value = _hhi(pcts)
    risk = _concentration_risk(hhi_value)

    # top_protocol: name with max tvl_usd
    top_protocol: Optional[str] = None
    if by_protocol_list:
        top_protocol = max(by_protocol_list, key=lambda x: x["tvl_usd"])["name"]

    # top_chain: chain name with max tvl_usd
    top_chain = _top_by_tvl(by_chain)

    # dominant_asset_type: asset_type with max tvl_usd
    dominant_asset_type = _top_by_tvl(by_asset_type)

    flags = _build_flags(
        by_protocol_list, by_chain, by_asset_type, concentration_warning_pct
    )

    systemic_risk_score = min(100, int(hhi_value / 100))

    return {
        "by_protocol": by_protocol_list,
        "by_chain": by_chain,
        "by_asset_type": by_asset_type,
        "hhi": hhi_value,
        "concentration_risk": risk,
        "top_protocol": top_protocol,
        "top_chain": top_chain,
        "dominant_asset_type": dominant_asset_type,
        "flags": flags,
        "systemic_risk_score": systemic_risk_score,
        "timestamp": time.time(),
    }


def run_and_log(ecosystem: dict, config: dict = None,
                data_file: str = _DATA_FILE) -> dict:
    """Run analyze() and append result to ring-buffer JSON log.

    Atomic write via tmp+os.replace. Ring-buffer capped at _LOG_CAP entries.
    """
    result = analyze(ecosystem, config)

    data_dir = os.path.dirname(data_file)
    os.makedirs(data_dir, exist_ok=True)

    try:
        with open(data_file) as f:
            log: list = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    tmp = data_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, data_file)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    mode = "--check"
    data_dir = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a in ("--check", "--run"):
            mode = a
        if a == "--data-dir" and i + 1 < len(args):
            data_dir = args[i + 1]

    demo_ecosystem = {
        "protocols": [
            {"name": "Aave V3", "tvl_usd": 8_000_000_000, "chain": "Ethereum",
             "asset_type": "STABLECOIN"},
            {"name": "Compound V3", "tvl_usd": 3_000_000_000, "chain": "Ethereum",
             "asset_type": "STABLECOIN"},
            {"name": "Morpho", "tvl_usd": 2_000_000_000, "chain": "Ethereum",
             "asset_type": "ETH_LST"},
            {"name": "Yearn V3", "tvl_usd": 1_000_000_000, "chain": "Ethereum",
             "asset_type": "STABLECOIN"},
            {"name": "GMX", "tvl_usd": 500_000_000, "chain": "Arbitrum",
             "asset_type": "OTHER"},
        ],
        "total_ecosystem_tvl_usd": 14_500_000_000,
    }

    if mode == "--run":
        df = os.path.join(data_dir or "data", "tvl_concentration_log.json")
        r = run_and_log(demo_ecosystem, data_file=df)
    else:
        r = analyze(demo_ecosystem)

    print(json.dumps(r, indent=2))
