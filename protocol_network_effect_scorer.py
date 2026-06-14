"""
MP-854: ProtocolNetworkEffectScorer

Scores how strong a protocol's network effects are — including user growth
compounding, composability (DeFi Lego integrations), capital efficiency,
and cross-protocol dependency.

Advisory / read-only. Pure stdlib. Atomic JSON writes (tmp + os.replace).
Ring-buffer log capped at 100 entries in data/network_effect_log.json.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RING_BUFFER_CAP = 100
LOG_FILE = "network_effect_log.json"
DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data"
)

# network_strength thresholds
STRENGTH_DOMINANT = 80
STRENGTH_STRONG = 60
STRENGTH_ESTABLISHED = 40
STRENGTH_GROWING = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _data_dir(data_dir: Optional[str]) -> str:
    return os.path.abspath(data_dir or DEFAULT_DATA_DIR)


def _log_path(data_dir: Optional[str]) -> str:
    return os.path.join(_data_dir(data_dir), LOG_FILE)


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_log(data_dir: Optional[str]) -> List[dict]:
    path = _log_path(data_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError, TypeError):
        return []


def _save_log(entry: dict, data_dir: Optional[str]) -> None:
    """Append entry to ring-buffer log (cap at RING_BUFFER_CAP)."""
    history = _load_log(data_dir)
    history.append(entry)
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]
    _atomic_write(_log_path(data_dir), history)


# ---------------------------------------------------------------------------
# Score sub-components
# ---------------------------------------------------------------------------


def _user_flywheel_score(
    monthly_active_users: int, user_growth_30d_pct: float
) -> int:
    """0–25: user growth momentum."""
    # Growth tier
    if user_growth_30d_pct >= 30:
        growth_pts = 15
    elif user_growth_30d_pct >= 15:
        growth_pts = 12
    elif user_growth_30d_pct >= 5:
        growth_pts = 8
    elif user_growth_30d_pct >= 0:
        growth_pts = 4
    else:
        growth_pts = 0

    # User scale tier
    if monthly_active_users >= 100_000:
        scale_pts = 10
    elif monthly_active_users >= 10_000:
        scale_pts = 7
    elif monthly_active_users >= 1_000:
        scale_pts = 4
    else:
        scale_pts = 0

    return min(25, growth_pts + scale_pts)


def _composability_score(
    integrations_count: int, dependent_tvl_usd: float
) -> int:
    """0–25: how many things build on this protocol."""
    # Integration tier
    if integrations_count >= 50:
        int_pts = 15
    elif integrations_count >= 20:
        int_pts = 12
    elif integrations_count >= 10:
        int_pts = 8
    elif integrations_count >= 5:
        int_pts = 4
    else:
        int_pts = 0

    # Dependent TVL tier
    if dependent_tvl_usd >= 1_000_000_000:
        tvl_pts = 10
    elif dependent_tvl_usd >= 100_000_000:
        tvl_pts = 7
    elif dependent_tvl_usd >= 10_000_000:
        tvl_pts = 4
    elif dependent_tvl_usd >= 1_000_000:
        tvl_pts = 2
    else:
        tvl_pts = 0

    return min(25, int_pts + tvl_pts)


def _capital_efficiency_score(
    dependent_tvl_usd: float, own_tvl_usd: float
) -> int:
    """0–25: TVL utilization (dependent / own)."""
    if own_tvl_usd <= 0:
        return 0
    utilization = dependent_tvl_usd / own_tvl_usd
    if utilization >= 5.0:
        return 25
    elif utilization >= 2.0:
        return 20
    elif utilization >= 1.0:
        return 15
    elif utilization >= 0.5:
        return 8
    elif utilization >= 0.1:
        return 4
    else:
        return 0


def _reach_score(
    tx_count_30d: int,
    unique_token_holders: int,
    cross_chain_deployments: int,
) -> int:
    """0–25: holders, chains, txs."""
    # Transaction tier
    if tx_count_30d >= 1_000_000:
        tx_pts = 8
    elif tx_count_30d >= 100_000:
        tx_pts = 6
    elif tx_count_30d >= 10_000:
        tx_pts = 4
    elif tx_count_30d >= 1_000:
        tx_pts = 2
    else:
        tx_pts = 0

    # Holder tier
    if unique_token_holders >= 1_000_000:
        holder_pts = 10
    elif unique_token_holders >= 100_000:
        holder_pts = 7
    elif unique_token_holders >= 10_000:
        holder_pts = 4
    else:
        holder_pts = 1

    # Cross-chain tier
    if cross_chain_deployments >= 5:
        chain_pts = 7
    elif cross_chain_deployments >= 3:
        chain_pts = 5
    elif cross_chain_deployments >= 2:
        chain_pts = 3
    elif cross_chain_deployments == 1:
        chain_pts = 1
    else:
        chain_pts = 0

    return min(25, tx_pts + holder_pts + chain_pts)


def _network_strength(score: int) -> str:
    """Map score 0–100 to strength label."""
    if score >= STRENGTH_DOMINANT:
        return "DOMINANT"
    if score >= STRENGTH_STRONG:
        return "STRONG"
    if score >= STRENGTH_ESTABLISHED:
        return "ESTABLISHED"
    if score >= STRENGTH_GROWING:
        return "GROWING"
    return "NICHE"


def _moat_assessment(network_score: int, integrations_count: int) -> str:
    if network_score >= 80:
        return "Deep moat — high switching costs and composability lock-in"
    if network_score >= 60:
        return f"Strong network with {integrations_count} integrations building on it"
    if network_score >= 40:
        return "Established presence — continue growing integration ecosystem"
    if network_score >= 20:
        return "Early network effects emerging — critical to maintain user growth"
    return "Limited network effects — protocol is easily substitutable"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def analyze(
    protocols: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    data_dir: Optional[str] = None,
    save: bool = False,
) -> Dict[str, Any]:
    """
    Score network effects for each protocol.

    Parameters
    ----------
    protocols : list of dict
        Each dict must contain:
          - name (str)
          - monthly_active_users (int)
          - user_growth_30d_pct (float)
          - integrations_count (int)
          - dependent_tvl_usd (float)
          - own_tvl_usd (float)
          - tx_count_30d (int)
          - unique_token_holders (int)
          - cross_chain_deployments (int)
    config : dict, optional — currently unused; reserved for future parameters.

    Returns
    -------
    dict with keys: protocols, dominant_protocol, fastest_growing,
                    most_composable, average_network_score, timestamp
    """
    scored_protocols: List[Dict[str, Any]] = []

    for proto in protocols:
        name: str = str(proto.get("name", ""))
        mau: int = int(proto.get("monthly_active_users", 0))
        growth: float = float(proto.get("user_growth_30d_pct", 0.0))
        integrations: int = int(proto.get("integrations_count", 0))
        dep_tvl: float = float(proto.get("dependent_tvl_usd", 0.0))
        own_tvl: float = float(proto.get("own_tvl_usd", 0.0))
        tx30d: int = int(proto.get("tx_count_30d", 0))
        holders: int = int(proto.get("unique_token_holders", 0))
        chains: int = int(proto.get("cross_chain_deployments", 0))

        uf = _user_flywheel_score(mau, growth)
        cs = _composability_score(integrations, dep_tvl)
        ce = _capital_efficiency_score(dep_tvl, own_tvl)
        rs = _reach_score(tx30d, holders, chains)

        network_score = min(100, uf + cs + ce + rs)
        strength = _network_strength(network_score)
        moat = _moat_assessment(network_score, integrations)

        scored_protocols.append(
            {
                "name": name,
                "network_score": network_score,
                "network_strength": strength,
                "user_flywheel_score": uf,
                "composability_score": cs,
                "capital_efficiency_score": ce,
                "reach_score": rs,
                "moat_assessment": moat,
            }
        )

    # -----------------------------------------------------------------------
    # Portfolio-level derived fields
    # -----------------------------------------------------------------------
    dominant_protocol: Optional[str] = None
    fastest_growing: Optional[str] = None
    most_composable: Optional[str] = None
    average_network_score: float = 0.0

    if scored_protocols:
        # dominant: highest network_score
        dominant_protocol = max(scored_protocols, key=lambda p: p["network_score"])["name"]

        # fastest_growing: highest user_growth_30d_pct (from original input)
        fastest_growing = max(protocols, key=lambda p: float(p.get("user_growth_30d_pct", 0.0)))[
            "name"
        ]

        # most_composable: highest integrations_count (from original input)
        most_composable = max(protocols, key=lambda p: int(p.get("integrations_count", 0)))[
            "name"
        ]

        average_network_score = sum(
            p["network_score"] for p in scored_protocols
        ) / len(scored_protocols)

    ts = time.time()
    result: Dict[str, Any] = {
        "protocols": scored_protocols,
        "dominant_protocol": dominant_protocol,
        "fastest_growing": fastest_growing,
        "most_composable": most_composable,
        "average_network_score": average_network_score,
        "timestamp": ts,
    }

    if save:
        _save_log(result, data_dir)

    return result


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------


def load_history(data_dir: Optional[str] = None) -> List[dict]:
    """Load the network effect log. Returns [] if missing/corrupt."""
    return _load_log(data_dir)


def init_log(data_dir: Optional[str] = None) -> None:
    """Initialise an empty log file if it doesn't exist yet."""
    path = _log_path(data_dir)
    if not os.path.exists(path):
        _atomic_write(path, [])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _demo_run() -> None:
    protocols = [
        {
            "name": "Aave V3",
            "monthly_active_users": 150_000,
            "user_growth_30d_pct": 8.0,
            "integrations_count": 85,
            "dependent_tvl_usd": 2_000_000_000.0,
            "own_tvl_usd": 8_000_000_000.0,
            "tx_count_30d": 2_000_000,
            "unique_token_holders": 750_000,
            "cross_chain_deployments": 8,
        },
        {
            "name": "Compound V3",
            "monthly_active_users": 45_000,
            "user_growth_30d_pct": 3.0,
            "integrations_count": 30,
            "dependent_tvl_usd": 300_000_000.0,
            "own_tvl_usd": 2_000_000_000.0,
            "tx_count_30d": 500_000,
            "unique_token_holders": 180_000,
            "cross_chain_deployments": 3,
        },
    ]
    result = analyze(protocols)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import sys

    if "--run" in sys.argv:
        data_dir_arg = None
        if "--data-dir" in sys.argv:
            idx = sys.argv.index("--data-dir")
            data_dir_arg = sys.argv[idx + 1]
        result = analyze([], data_dir=data_dir_arg, save=True)
        print("Saved network effect log.")
    else:
        _demo_run()
