"""
spa_core/analytics/stablecoin_yield_optimizer.py

Optimizes stablecoin allocation for RS-001 and RS-002 core slots.
The stablecoin slot is the ONLY clean evidence component in both research strategies.

For RS-001: stablecoin_t1 is 15% weight, target ~3%+ APY
For RS-002: stablecoin_deposit is 16% weight, target ~4%+ APY

Optimization across available T1 protocols:
  - Aave V3 USDC (Arbitrum): ~3-4% APY
  - Morpho Blue USDC: ~4-5% APY
  - Sky sUSDS: ~5-6% APY
  - Compound V3 USDC: ~3-4% APY

Strategy: maximize APY across these 4 while respecting concentration limits.
Concentration limit: max 50% in any single protocol.

CLI:
  python3 -m spa_core.analytics.stablecoin_yield_optimizer --check
  python3 -m spa_core.analytics.stablecoin_yield_optimizer --run
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Protocol catalogue
# ---------------------------------------------------------------------------

T1_PROTOCOLS: Dict[str, dict] = {
    "aave_v3_usdc": {
        "fallback_apy": 3.5,
        "max_allocation_pct": 50.0,
        "tier": "T1",
        "chain": "arbitrum",
    },
    "morpho_blue_usdc": {
        "fallback_apy": 4.5,
        "max_allocation_pct": 50.0,
        "tier": "T1",
        "chain": "ethereum",
    },
    "sky_susds": {
        "fallback_apy": 5.5,
        "max_allocation_pct": 40.0,
        "tier": "T1",
        "chain": "ethereum",
    },
    "compound_v3_usdc": {
        "fallback_apy": 3.2,
        "max_allocation_pct": 30.0,
        "tier": "T1",
        "chain": "ethereum",
    },
}


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

class StablecoinYieldOptimizer(BaseAnalytics):
    """Greedy APY maximiser for T1 stablecoin slots in RS-001 / RS-002."""

    OUTPUT_PATH = "data/research/stablecoin_optimizer.json"

    def __init__(self, capital_fraction: float = 0.15) -> None:
        """
        Parameters
        ----------
        capital_fraction : float
            Fraction of total portfolio capital held in the stablecoin slot.
            RS-001 uses 0.15 (15%); RS-002 uses 0.16 (16%).
        """
        super().__init__()
        if not (0.0 < capital_fraction <= 1.0):
            raise ValueError(
                f"capital_fraction must be in (0, 1], got {capital_fraction}"
            )
        self.capital_fraction = capital_fraction

    # ------------------------------------------------------------------
    # Live APY fetch (with fallback)
    # ------------------------------------------------------------------

    def live_apys(self) -> dict:
        """Fetch live APYs from available adapters; fall back on error.

        Returns a dict mapping protocol_id → APY (percentage float, e.g. 4.5).
        """
        apys: dict = {}

        for protocol_id, spec in T1_PROTOCOLS.items():
            apy = self._fetch_single(protocol_id, spec)
            apys[protocol_id] = apy

        return apys

    def _fetch_single(self, protocol_id: str, spec: dict) -> float:
        """Try to get a live APY for one protocol; return fallback on any error."""
        fallback = spec["fallback_apy"]
        try:
            if protocol_id == "aave_v3_usdc":
                return self._fetch_aave_arb(fallback)
            elif protocol_id == "morpho_blue_usdc":
                return self._fetch_morpho_blue(fallback)
            elif protocol_id == "sky_susds":
                return self._fetch_sky_susds(fallback)
            elif protocol_id == "compound_v3_usdc":
                return self._fetch_compound_v3(fallback)
        except Exception:  # noqa: BLE001
            pass
        return fallback

    def _fetch_aave_arb(self, fallback: float) -> float:
        try:
            from spa_core.adapters.aave_v3_arbitrum import AaveV3ArbitrumAdapter  # type: ignore
            adapter = AaveV3ArbitrumAdapter()
            result = adapter.fetch()
            apy = result.get("apy")
            if apy is not None and apy > 0:
                return float(apy) * 100.0  # decimal → percent
        except Exception:  # noqa: BLE001
            pass
        return fallback

    def _fetch_morpho_blue(self, fallback: float) -> float:
        try:
            from spa_core.adapters.morpho_blue import MorphoBlueAdapter  # type: ignore
            adapter = MorphoBlueAdapter()
            result = adapter.fetch()
            apy = result.get("apy")
            if apy is not None and apy > 0:
                return float(apy) * 100.0
        except Exception:  # noqa: BLE001
            pass
        return fallback

    def _fetch_sky_susds(self, fallback: float) -> float:
        try:
            from spa_core.adapters.spark_susds import SparkSusdsAdapter  # type: ignore
            adapter = SparkSusdsAdapter()
            result = adapter.fetch()
            apy = result.get("apy")
            if apy is not None and apy > 0:
                return float(apy) * 100.0
        except Exception:  # noqa: BLE001
            pass
        return fallback

    def _fetch_compound_v3(self, fallback: float) -> float:
        try:
            from spa_core.adapters.compound_v3 import CompoundV3Adapter  # type: ignore
            adapter = CompoundV3Adapter()
            result = adapter.fetch()
            apy = result.get("apy")
            if apy is not None and apy > 0:
                return float(apy) * 100.0
        except Exception:  # noqa: BLE001
            pass
        return fallback

    # ------------------------------------------------------------------
    # Allocation logic
    # ------------------------------------------------------------------

    def optimal_allocation(self, apys: Optional[dict] = None) -> dict:
        """Return optimal allocation respecting per-protocol concentration limits.

        Algorithm (greedy):
          1. Rank protocols by APY descending.
          2. For each protocol (highest APY first), allocate up to
             min(max_allocation_pct, remaining) of the stablecoin slot.
          3. Stop when 100% is allocated or all protocols are exhausted.

        Returns
        -------
        dict
            Mapping protocol_id → fraction of stablecoin slot [0, 1].
            Sum is always 1.0 (all capital is placed).
        """
        if apys is None:
            apys = self.live_apys()

        # Rank protocols by APY descending
        ranked = sorted(
            T1_PROTOCOLS.keys(),
            key=lambda pid: apys.get(pid, T1_PROTOCOLS[pid]["fallback_apy"]),
            reverse=True,
        )

        allocation: dict = {pid: 0.0 for pid in T1_PROTOCOLS}
        remaining_pct = 100.0  # work in percentage points for precision

        for pid in ranked:
            if remaining_pct <= 0.0:
                break
            cap_pct = T1_PROTOCOLS[pid]["max_allocation_pct"]
            alloc_pct = min(cap_pct, remaining_pct)
            allocation[pid] = round(alloc_pct / 100.0, 10)
            remaining_pct = round(remaining_pct - alloc_pct, 10)

        # Normalise to exactly 1.0 (handles floating-point dust)
        total = sum(allocation.values())
        if total > 0:
            allocation = {k: v / total for k, v in allocation.items()}

        return allocation

    # ------------------------------------------------------------------
    # Blended APY
    # ------------------------------------------------------------------

    def blended_apy(self, allocation: Optional[dict] = None) -> float:
        """Weighted-average APY of the current allocation.

        Parameters
        ----------
        allocation : dict or None
            Mapping protocol_id → fraction. If None, ``optimal_allocation()``
            is called with live APYs.

        Returns
        -------
        float
            Blended APY in percentage points (e.g. 4.8 for 4.8%).
        """
        if allocation is None:
            allocation = self.optimal_allocation()

        apys = self.live_apys()
        total = 0.0
        for pid, fraction in allocation.items():
            apy = apys.get(pid, T1_PROTOCOLS[pid]["fallback_apy"])
            total += fraction * apy
        return total

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def allocation_report(self) -> dict:
        """Return a comprehensive allocation report.

        Schema
        ------
        {
          "capital_fraction": float,
          "protocols": {
            protocol_id: {
              "apy": float,
              "allocation_pct": float,   # 0–100
              "contribution_apy": float  # allocation_pct/100 * apy
            }
          },
          "blended_apy": float,
          "total_allocated_pct": float,
          "optimization_note": str,
          "generated_at": str (ISO-8601),
          "schema_version": str
        }
        """
        apys = self.live_apys()
        allocation = self.optimal_allocation(apys=apys)
        blended = self.blended_apy(allocation=allocation)

        protocols: dict = {}
        for pid in T1_PROTOCOLS:
            apy = apys.get(pid, T1_PROTOCOLS[pid]["fallback_apy"])
            frac = allocation.get(pid, 0.0)
            alloc_pct = round(frac * 100.0, 6)
            protocols[pid] = {
                "apy": round(apy, 4),
                "allocation_pct": alloc_pct,
                "contribution_apy": round(alloc_pct / 100.0 * apy, 6),
                "max_allocation_pct": T1_PROTOCOLS[pid]["max_allocation_pct"],
                "tier": T1_PROTOCOLS[pid]["tier"],
                "chain": T1_PROTOCOLS[pid]["chain"],
            }

        # Determine which protocol is largest
        largest_pid = max(allocation, key=allocation.get)
        note = (
            f"Greedy T1 optimisation: {largest_pid} allocated "
            f"{protocols[largest_pid]['allocation_pct']:.1f}% "
            f"(highest APY {protocols[largest_pid]['apy']:.2f}%); "
            f"blended {blended:.2f}% across {sum(1 for v in allocation.values() if v > 0)} "
            f"active protocol(s)."
        )

        return {
            "capital_fraction": self.capital_fraction,
            "protocols": protocols,
            "blended_apy": round(blended, 4),
            "total_allocated_pct": round(sum(allocation.values()) * 100.0, 6),
            "optimization_note": note,
            "generated_at": _iso_now(),
            "schema_version": "1.0",
        }

    # ------------------------------------------------------------------
    # BaseAnalytics interface
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Returns current allocation report as JSON-serializable dict."""
        return self.allocation_report()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str = "data/research/stablecoin_optimizer.json") -> None:
        """Atomically write the allocation report to *path*.

        Uses a tmp-file + os.replace pattern (atomic on POSIX).
        """
        report = self.allocation_report()
        _atomic_write(path, report)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    """Return current UTC time as ISO-8601 string (no external dependencies)."""
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
        f"T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: dict) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Stablecoin T1 yield optimizer for RS-001/RS-002 slots."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print report without writing to disk (default if no flag).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute and atomically write report to data/research/stablecoin_optimizer.json.",
    )
    parser.add_argument(
        "--capital-fraction",
        type=float,
        default=0.15,
        help="Capital fraction for the stablecoin slot (default 0.15 for RS-001).",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="",
        help="Override output directory (used with --run).",
    )
    args = parser.parse_args()

    optimizer = StablecoinYieldOptimizer(capital_fraction=args.capital_fraction)
    report = optimizer.allocation_report()

    print(json.dumps(report, indent=2))

    if args.run:
        out_path = (
            os.path.join(args.data_dir, "stablecoin_optimizer.json")
            if args.data_dir
            else "data/research/stablecoin_optimizer.json"
        )
        _atomic_write(out_path, report)
        print(f"\n[stablecoin_yield_optimizer] Saved → {out_path}")


if __name__ == "__main__":
    _main()
