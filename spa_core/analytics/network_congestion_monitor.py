"""Network Congestion Monitor (MP-696).

Monitors blockchain network congestion and estimates optimal transaction
timing for yield strategy executions.

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* All writes are atomic: ``tmp-file + os.replace``.
* Ring-buffer capped at :data:`MAX_ENTRIES` entries (100).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Data File
---------
``data/congestion_monitor_log.json``::

    {
      "schema_version": "1.0",
      "generated_at": "<ISO-8601 UTC>",
      "entries": [ <CongestionReport dicts>, ... ]   # ring-buffer ≤ 100
    }

Public API
----------
``NetworkCongestionMonitor(data_dir="data")``

    analyze(snapshot: NetworkSnapshot) -> CongestionReport
    analyze_batch(snapshots: list[NetworkSnapshot]) -> list[CongestionReport]
    compare_networks(snapshots: list[NetworkSnapshot]) -> str
        Returns the network name with the lowest gas_premium_pct.
    save_results(reports: list[CongestionReport]) -> None
    load_history() -> list[dict]
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/congestion_monitor_log.json")
MAX_ENTRIES = 100
SCHEMA_VERSION = "1.0"

# Network base parameters
NETWORK_PARAMS: Dict[str, Dict] = {
    "ethereum": {
        "base_gas_gwei": 20.0,
        "block_time_seconds": 12,
        "max_gas_per_block": 30_000_000,
    },
    "base": {
        "base_gas_gwei": 0.1,
        "block_time_seconds": 2,
        "max_gas_per_block": 30_000_000,
    },
    "arbitrum": {
        "base_gas_gwei": 0.1,
        "block_time_seconds": 0.25,
        "max_gas_per_block": 32_000_000,
    },
    "optimism": {
        "base_gas_gwei": 0.1,
        "block_time_seconds": 2,
        "max_gas_per_block": 30_000_000,
    },
}

L2_NETWORKS = frozenset({"base", "arbitrum", "optimism"})

# congestion_level → estimated_wait_blocks
_WAIT_BLOCKS: Dict[str, int] = {
    "LOW": 1,
    "MODERATE": 2,
    "HIGH": 5,
    "EXTREME": 20,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class NetworkSnapshot:
    network: str
    current_gas_gwei: float
    pending_tx_count: int          # mempool depth
    avg_block_utilization_pct: float  # 0-100: how full recent blocks are
    timestamp: float


@dataclass
class CongestionReport:
    network: str
    current_gas_gwei: float
    base_gas_gwei: float
    gas_premium_pct: float         # (current - base) / base * 100
    congestion_level: str          # LOW / MODERATE / HIGH / EXTREME
    estimated_wait_blocks: int     # blocks until tx likely confirmed
    estimated_wait_seconds: float
    cost_urgency: str              # OPTIMAL / ELEVATED / EXPENSIVE / PROHIBITIVE
    optimal_window: str            # NOW / WAIT_1H / WAIT_4H / WAIT_NIGHT
    pending_tx_count: int
    recommendations: List[str]


# ---------------------------------------------------------------------------
# Helper functions (pure, no I/O)
# ---------------------------------------------------------------------------


def _base_gas(network: str) -> float:
    return NETWORK_PARAMS.get(network, {}).get("base_gas_gwei", 20.0)


def _block_time(network: str) -> float:
    return NETWORK_PARAMS.get(network, {}).get("block_time_seconds", 12.0)


def _gas_premium_pct(current: float, base: float) -> float:
    if base <= 0:
        return 0.0
    return (current - base) / base * 100.0


def _congestion_level(gas_premium: float) -> str:
    if gas_premium < 20.0:
        return "LOW"
    if gas_premium < 100.0:
        return "MODERATE"
    if gas_premium < 300.0:
        return "HIGH"
    return "EXTREME"


def _cost_urgency(gas_premium: float) -> str:
    if gas_premium < 10.0:
        return "OPTIMAL"
    if gas_premium < 50.0:
        return "ELEVATED"
    if gas_premium < 200.0:
        return "EXPENSIVE"
    return "PROHIBITIVE"


def _optimal_window(cost_urgency: str, congestion_level: str) -> str:
    if cost_urgency in ("OPTIMAL", "ELEVATED"):
        return "NOW"
    if cost_urgency == "EXPENSIVE":
        return "WAIT_1H"
    # PROHIBITIVE
    if congestion_level == "EXTREME":
        return "WAIT_NIGHT"
    return "WAIT_4H"


def _recommendations(
    network: str,
    current_gas_gwei: float,
    cost_urgency: str,
    congestion_level: str,
    block_utilization: float,
) -> List[str]:
    recs: List[str] = []

    if cost_urgency == "PROHIBITIVE":
        recs.append(
            "🚨 Gas extremely high — postpone non-urgent transactions"
        )

    if congestion_level in ("HIGH", "EXTREME"):
        recs.append(
            f"⚠️ Network congested at {current_gas_gwei:.1f} gwei"
            " — execute on L2 instead"
        )

    if network == "ethereum" and current_gas_gwei < 15:
        recs.append("✅ Gas very low — excellent time to execute")

    if block_utilization > 90:
        recs.append(
            "⚠️ Blocks nearly full — transactions may be delayed"
        )

    if network in L2_NETWORKS:
        recs.append("✅ L2 network — fees minimal regardless of congestion")

    return recs


# ---------------------------------------------------------------------------
# Main monitor class
# ---------------------------------------------------------------------------


class NetworkCongestionMonitor:
    """Advisory monitor for blockchain network congestion."""

    def __init__(self, data_dir: str = "data") -> None:
        self._data_file = Path(data_dir) / "congestion_monitor_log.json"

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    def analyze(self, snapshot: NetworkSnapshot) -> CongestionReport:
        """Return a CongestionReport for a single NetworkSnapshot."""
        network = snapshot.network
        current = snapshot.current_gas_gwei
        base = _base_gas(network)
        block_time = _block_time(network)

        premium = _gas_premium_pct(current, base)
        level = _congestion_level(premium)
        urgency = _cost_urgency(premium)
        wait_blocks = _WAIT_BLOCKS[level]
        wait_seconds = wait_blocks * block_time
        window = _optimal_window(urgency, level)
        recs = _recommendations(
            network, current, urgency, level,
            snapshot.avg_block_utilization_pct,
        )

        return CongestionReport(
            network=network,
            current_gas_gwei=current,
            base_gas_gwei=base,
            gas_premium_pct=premium,
            congestion_level=level,
            estimated_wait_blocks=wait_blocks,
            estimated_wait_seconds=wait_seconds,
            cost_urgency=urgency,
            optimal_window=window,
            pending_tx_count=snapshot.pending_tx_count,
            recommendations=recs,
        )

    def analyze_batch(
        self, snapshots: List[NetworkSnapshot]
    ) -> List[CongestionReport]:
        """Return a list of CongestionReports; empty list for empty input."""
        return [self.analyze(s) for s in snapshots]

    def compare_networks(
        self, snapshots: List[NetworkSnapshot]
    ) -> str:
        """Return the network name with the lowest gas_premium_pct.

        If *snapshots* is empty, returns an empty string.
        """
        if not snapshots:
            return ""
        reports = self.analyze_batch(snapshots)
        best = min(reports, key=lambda r: r.gas_premium_pct)
        return best.network

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic)
    # ------------------------------------------------------------------

    def save_results(self, reports: List[CongestionReport]) -> None:
        """Append *reports* to the ring-buffer JSON file atomically."""
        history = self.load_history()
        new_entries = [asdict(r) for r in reports]
        history.extend(new_entries)
        # trim to ring-buffer size
        if len(history) > MAX_ENTRIES:
            history = history[-MAX_ENTRIES:]

        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entries": history,
        }
        _atomic_write(self._data_file, payload)

    def load_history(self) -> List[dict]:
        """Load existing entries from the ring-buffer file.

        Returns an empty list if the file does not exist or is corrupt.
        """
        if not self._data_file.exists():
            return []
        try:
            with open(self._data_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("entries", [])
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, payload: dict) -> None:
    """Write *payload* as JSON to *path* atomically (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MP-696 NetworkCongestionMonitor — advisory CLI"
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Run example analysis and print, without writing (default)",
    )
    p.add_argument(
        "--run",
        action="store_true",
        help="Run example analysis and write to data file",
    )
    p.add_argument(
        "--data-dir",
        default="data",
        help="Directory for data files (default: data)",
    )
    return p


def _example_snapshots() -> List[NetworkSnapshot]:
    now = time.time()
    return [
        NetworkSnapshot("ethereum", 45.0, 12000, 85.0, now),
        NetworkSnapshot("base",     0.05, 200,   30.0, now),
        NetworkSnapshot("arbitrum", 0.08, 300,   20.0, now),
    ]


def main() -> None:
    args = _build_cli().parse_args()
    monitor = NetworkCongestionMonitor(data_dir=args.data_dir)
    snapshots = _example_snapshots()
    reports = monitor.analyze_batch(snapshots)

    for r in reports:
        print(
            f"[{r.network.upper():>10}] gas={r.current_gas_gwei:.2f} gwei "
            f"| premium={r.gas_premium_pct:+.1f}% "
            f"| level={r.congestion_level:<8} "
            f"| urgency={r.cost_urgency:<11} "
            f"| window={r.optimal_window}"
        )
        for rec in r.recommendations:
            print(f"               {rec}")

    best = monitor.compare_networks(snapshots)
    print(f"\n✅ Cheapest network to execute on right now: {best}")

    if args.run:
        monitor.save_results(reports)
        print(f"\n📄 Results saved → {monitor._data_file}")


if __name__ == "__main__":
    main()
