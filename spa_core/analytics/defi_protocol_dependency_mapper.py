"""
MP-875: DeFiProtocolDependencyMapper

Maps and scores dependencies between DeFi protocols (oracle, underlying asset,
bridge) to identify contagion risk if a dependency fails.

Read-only analytics module — stdlib only, atomic writes, ring-buffer 100.

Scoring breakdown (max 100 pts):
  dependency_chain_score  0-30   (depth of dependency stack)
  oracle_risk_score       0-25   (oracle centralization)
  admin_risk_score        0-25   (admin key risk)
  bridge_risk_score       0-20   (bridge dependency)
  contagion_risk_score = min(100, sum)

Levels:
  CRITICAL  >= 70
  HIGH      >= 50
  MODERATE  >= 30
  LOW       <  30
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

_DEFAULT_LOG_PATH = "data/protocol_dependency_log.json"
_MAX_LOG_ENTRIES = 100

# ---------------------------------------------------------------------------
# Sub-scoring helpers
# ---------------------------------------------------------------------------


def _dependency_chain_score(dependency_count: int) -> int:
    """0-30 based on total number of external dependencies."""
    if dependency_count >= 10:
        return 30
    if dependency_count >= 7:
        return 25
    if dependency_count >= 5:
        return 20
    if dependency_count >= 3:
        return 15
    if dependency_count >= 2:
        return 10
    if dependency_count == 1:
        return 5
    return 0


def _oracle_risk_score(oracle_dependency: Optional[str],
                       underlying_protocols: List[str]) -> int:
    """0-25 based on oracle centralization and self-referential dependency."""
    if oracle_dependency is None:
        base = 5
    else:
        od_lower = oracle_dependency.lower()
        if oracle_dependency == "Chainlink":
            base = 8
        elif "twap" in od_lower:
            base = 12
        elif oracle_dependency == "Pyth":
            base = 10
        else:
            base = 20

    # Self-referential: oracle name matches any underlying protocol name
    if oracle_dependency is not None:
        od_lower = oracle_dependency.lower()
        for up in underlying_protocols:
            if up.lower() == od_lower:
                base += 5
                break

    return min(25, base)


def _admin_risk_score(is_upgradeable: bool, multisig_signers: int) -> int:
    """0-25 based on upgradeability and multisig key count."""
    if not is_upgradeable:
        return 5
    # Upgradeable — evaluate multisig depth
    if multisig_signers >= 7:
        return 8
    if multisig_signers >= 5:
        return 12
    if multisig_signers >= 3:
        return 16
    if multisig_signers == 2:
        return 20
    if multisig_signers == 1:
        return 23
    # multisig_signers == 0
    return 25


def _bridge_risk_score(bridge_dependency: Optional[str],
                       tvl_usd: float) -> int:
    """0-20 based on bridge type and TVL."""
    if bridge_dependency is None:
        return 0

    bd_lower = bridge_dependency.lower()
    if "native" in bd_lower:
        base = 5
    elif "official" in bd_lower:
        base = 8
    else:
        base = 15

    # Additional +5 if bridge is the only cross-chain link AND tvl > 10M
    if tvl_usd > 10_000_000:
        base += 5

    return min(20, base)


def _contagion_level(score: int) -> str:
    if score >= 70:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 30:
        return "MODERATE"
    return "LOW"


def _single_points_of_failure(bridge_dependency: Optional[str],
                               bridge_score: int,
                               multisig_signers: int,
                               is_upgradeable: bool,
                               oracle_dependency: Optional[str],
                               oracle_score: int,
                               underlying_protocols: List[str]) -> List[str]:
    spofs: List[str] = []
    if bridge_dependency is not None and bridge_score >= 15:
        spofs.append(f"Bridge: {bridge_dependency}")
    if multisig_signers <= 1 and is_upgradeable:
        spofs.append("Single admin key (upgrade risk)")
    if oracle_dependency is not None and oracle_score >= 18:
        spofs.append(f"Oracle: {oracle_dependency}")
    if len(underlying_protocols) >= 5:
        spofs.append(f"{len(underlying_protocols)} underlying protocol dependencies")
    return spofs


# ---------------------------------------------------------------------------
# Shared dependencies helper
# ---------------------------------------------------------------------------


def _build_shared_dependencies(protocols: List[dict]) -> Dict[str, List[str]]:
    """
    Build a dict {dependency_name: [protocols that use it]}
    Includes oracle names, bridge names, and underlying protocol names.
    Only entries appearing in ≥ 2 protocols are returned.
    """
    dep_map: Dict[str, List[str]] = {}

    for p in protocols:
        name = p.get("name", "")
        seen_deps: set = set()

        oracle = p.get("oracle_dependency")
        if oracle is not None:
            dep_map.setdefault(oracle, [])
            if oracle not in seen_deps:
                dep_map[oracle].append(name)
                seen_deps.add(oracle)

        bridge = p.get("bridge_dependency")
        if bridge is not None:
            dep_map.setdefault(bridge, [])
            if bridge not in seen_deps:
                dep_map[bridge].append(name)
                seen_deps.add(bridge)

        for up in p.get("underlying_protocols", []):
            dep_map.setdefault(up, [])
            if up not in seen_deps:
                dep_map[up].append(name)
                seen_deps.add(up)

    # Only keep entries shared by ≥ 2 protocols
    return {k: v for k, v in dep_map.items() if len(v) >= 2}


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------


def analyze(protocols: List[dict],
            config: Optional[dict] = None,
            log_path: str = _DEFAULT_LOG_PATH) -> dict:
    """
    Analyze contagion risk for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list of protocol dicts (see module docstring).
    config    : reserved for future use (currently ignored).
    log_path  : path to ring-buffer JSON log.

    Returns
    -------
    dict with keys: protocols, highest_contagion_risk, lowest_contagion_risk,
    shared_dependencies, average_contagion_score, timestamp.
    """
    ts = time.time()

    if not protocols:
        result: dict = {
            "protocols": [],
            "highest_contagion_risk": None,
            "lowest_contagion_risk": None,
            "shared_dependencies": {},
            "average_contagion_score": 0.0,
            "timestamp": ts,
        }
        _append_log(result, log_path)
        return result

    scored: List[dict] = []

    for p in protocols:
        name: str = p.get("name", "")
        oracle_dep: Optional[str] = p.get("oracle_dependency")
        underlying: List[str] = p.get("underlying_protocols", [])
        bridge_dep: Optional[str] = p.get("bridge_dependency")
        tvl: float = float(p.get("tvl_usd", 0.0))
        upgradeable: bool = bool(p.get("is_upgradeable", False))
        multisig: int = int(p.get("multisig_signers", 0))
        dep_count: int = int(p.get("dependency_count", 0))

        chain_score = _dependency_chain_score(dep_count)
        oracle_score = _oracle_risk_score(oracle_dep, underlying)
        admin_score = _admin_risk_score(upgradeable, multisig)
        bridge_score = _bridge_risk_score(bridge_dep, tvl)

        contagion_score = min(100, chain_score + oracle_score + admin_score + bridge_score)
        level = _contagion_level(contagion_score)
        spofs = _single_points_of_failure(
            bridge_dep, bridge_score,
            multisig, upgradeable,
            oracle_dep, oracle_score,
            underlying,
        )
        summary = (
            f"{name}: {level} contagion risk (score {contagion_score}), "
            f"{dep_count} deps, {len(spofs)} SPOFs"
        )

        scored.append({
            "name": name,
            "contagion_risk_score": contagion_score,
            "contagion_risk_level": level,
            "dependency_chain_score": chain_score,
            "oracle_risk_score": oracle_score,
            "admin_risk_score": admin_score,
            "bridge_risk_score": bridge_score,
            "total_dependencies": dep_count,
            "single_points_of_failure": spofs,
            "summary": summary,
        })

    # Highest / lowest contagion
    highest = max(scored, key=lambda x: x["contagion_risk_score"])["name"]
    lowest = min(scored, key=lambda x: x["contagion_risk_score"])["name"]

    avg = sum(s["contagion_risk_score"] for s in scored) / len(scored)

    shared_deps = _build_shared_dependencies(protocols)

    result = {
        "protocols": scored,
        "highest_contagion_risk": highest,
        "lowest_contagion_risk": lowest,
        "shared_dependencies": shared_deps,
        "average_contagion_score": avg,
        "timestamp": ts,
    }

    _append_log(result, log_path)
    return result


# ---------------------------------------------------------------------------
# Ring-buffer log helper
# ---------------------------------------------------------------------------


def _append_log(result: dict, log_path: str) -> None:
    """Append a summary entry to the ring-buffer log (capped at 100)."""
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as fh:
                entries: List[dict] = json.load(fh)
        else:
            entries = []
    except Exception:
        entries = []

    entry = {
        "timestamp": result.get("timestamp", time.time()),
        "protocol_count": len(result.get("protocols", [])),
        "highest_contagion_risk": result.get("highest_contagion_risk"),
        "lowest_contagion_risk": result.get("lowest_contagion_risk"),
        "average_contagion_score": result.get("average_contagion_score", 0.0),
    }
    entries.append(entry)
    # Ring-buffer cap
    if len(entries) > _MAX_LOG_ENTRIES:
        entries = entries[-_MAX_LOG_ENTRIES:]

    # Atomic write
    dir_path = os.path.dirname(log_path) or "."
    os.makedirs(dir_path, exist_ok=True)
    tmp = log_path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp, log_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _DEMO = [
        {
            "name": "Aave V3",
            "oracle_dependency": "Chainlink",
            "underlying_protocols": [],
            "bridge_dependency": None,
            "stablecoin_dependency": "USDC",
            "tvl_usd": 8_000_000_000.0,
            "is_upgradeable": True,
            "multisig_signers": 6,
            "dependency_count": 2,
        },
        {
            "name": "CompoundV3",
            "oracle_dependency": "Chainlink",
            "underlying_protocols": [],
            "bridge_dependency": None,
            "stablecoin_dependency": "USDC",
            "tvl_usd": 3_000_000_000.0,
            "is_upgradeable": True,
            "multisig_signers": 4,
            "dependency_count": 2,
        },
        {
            "name": "Morpho Blue",
            "oracle_dependency": "Chainlink",
            "underlying_protocols": ["Aave V3"],
            "bridge_dependency": None,
            "stablecoin_dependency": "USDC",
            "tvl_usd": 500_000_000.0,
            "is_upgradeable": False,
            "multisig_signers": 0,
            "dependency_count": 3,
        },
    ]

    out = analyze(_DEMO)
    print(json.dumps(out, indent=2))
    sys.exit(0)
