"""Gas Cost Tracker (MP-624).

Tracks cumulative gas costs per adapter/chain and computes net APY after
deducting annualised gas drag.  Useful for comparing the true yield of
on-chain positions once execution overhead is taken into account.

Design constraints
------------------
* Pure stdlib + math — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* All writes are atomic: ``tmp-file + os.replace``.
* Ring-buffer capped at :data:`RING_BUFFER` entries (100).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Data File
---------
``data/gas_cost_log.json`` — JSON object::

    {
      "schema_version": "1.0",
      "generated_at": "<ISO-8601 UTC>",
      "entries": [ <GasCostEntry dicts>, ... ]   # ring-buffer ≤ 100
    }

Gas Cost Formula
----------------
``cost_usd = gas_used × gas_price_gwei × 1e-9 × eth_price_usd``

Net APY Formula
---------------
::
    gas_cost_window   = sum of cost_usd for last <days> days
    annualised_gas    = gas_cost_window / days * 365
    gas_drag_pct      = annualised_gas / capital_usd * 100
    net_apy           = gross_apy – gas_drag_pct
    gas_drag_bps      = gas_drag_pct * 100

Grade (gas_drag_bps)
--------------------
* A — drag < 5 bps
* B — drag < 15 bps
* C — drag < 30 bps
* D — drag ≥ 30 bps

Public API
----------
``GasCostTracker(data_dir="data")``

    record_gas(tx_hash, adapter, chain, gas_used, gas_price_gwei, eth_price_usd)
        → GasCostEntry
    get_total_cost_usd(days=30) → float
    get_cost_by_adapter(days=30) → dict[str, float]
    get_cost_by_chain(days=30) → dict[str, float]
    compute_net_apy(gross_apy, capital_usd, days=30) → dict
    generate_report() → dict
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0"
RING_BUFFER: int = 100
_DATA_FILE: str = "gas_cost_log.json"

GWEI_TO_ETH: float = 1e-9

# Grade thresholds (basis points)
_GRADE_A_BPS: float = 5.0
_GRADE_B_BPS: float = 15.0
_GRADE_C_BPS: float = 30.0

ADVISORY: str = "For informational purposes only."


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class GasCostEntry:
    """A single gas-cost record for one on-chain transaction."""

    tx_hash: str
    adapter: str
    chain: str
    gas_used: int
    gas_price_gwei: float
    eth_price_usd: float
    cost_usd: float
    timestamp: str  # ISO-8601 UTC

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GasCostEntry":
        return cls(
            tx_hash=str(d.get("tx_hash", "")),
            adapter=str(d.get("adapter", "")),
            chain=str(d.get("chain", "")),
            gas_used=int(d.get("gas_used", 0)),
            gas_price_gwei=float(d.get("gas_price_gwei", 0.0)),
            eth_price_usd=float(d.get("eth_price_usd", 0.0)),
            cost_usd=float(d.get("cost_usd", 0.0)),
            timestamp=str(d.get("timestamp", "")),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0, min_val: Optional[float] = None) -> float:
    """Coerce *value* to float; return *default* on failure."""
    if value is None:
        result = default
    else:
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = default
    if not math.isfinite(result):
        result = default
    if min_val is not None and result < min_val:
        result = min_val
    return result


def _safe_int(value: Any, default: int = 0, min_val: int = 0) -> int:
    """Coerce *value* to int; return *default* on failure."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(result, min_val)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if not ts:
        return None
    try:
        # Python 3.7+ fromisoformat does not handle trailing 'Z'
        ts_clean = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _entries_within_days(entries: List[GasCostEntry], days: int) -> List[GasCostEntry]:
    """Return entries whose timestamp falls within the last *days* days."""
    if days <= 0:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = []
    for e in entries:
        dt = _parse_timestamp(e.timestamp)
        if dt is not None and dt >= cutoff:
            result.append(e)
    return result


def _compute_gas_cost(gas_used: int, gas_price_gwei: float, eth_price_usd: float) -> float:
    """cost_usd = gas_used × gas_price_gwei × 1e-9 × eth_price_usd"""
    cost = max(gas_used, 0) * max(gas_price_gwei, 0.0) * GWEI_TO_ETH * max(eth_price_usd, 0.0)
    return round(cost, 8)


def _grade_from_drag_bps(drag_bps: float) -> str:
    if drag_bps < _GRADE_A_BPS:
        return "A"
    if drag_bps < _GRADE_B_BPS:
        return "B"
    if drag_bps < _GRADE_C_BPS:
        return "C"
    return "D"


# ---------------------------------------------------------------------------
# GasCostTracker
# ---------------------------------------------------------------------------

class GasCostTracker:
    """Advisory gas-cost tracker for on-chain DeFi operations.

    Parameters
    ----------
    data_dir:
        Directory for ``gas_cost_log.json`` (default: ``"data"``).
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = Path(data_dir)
        self._data_file = self._data_dir / _DATA_FILE

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _load_entries(self) -> List[GasCostEntry]:
        """Load entries from disk; return [] on any error."""
        if not self._data_file.exists():
            return []
        try:
            with open(self._data_file, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            entries_raw = raw.get("entries", [])
            if not isinstance(entries_raw, list):
                return []
            return [GasCostEntry.from_dict(e) for e in entries_raw]
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return []

    def _save_entries(self, entries: List[GasCostEntry]) -> None:
        """Atomically persist *entries* (ring-buffer capped at RING_BUFFER)."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        if len(entries) > RING_BUFFER:
            entries = entries[-RING_BUFFER:]
        doc = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now_iso(),
            "entries": [e.to_dict() for e in entries],
        }
        atomic_save(doc, str(self))
    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_gas(
        self,
        tx_hash: str,
        adapter: str,
        chain: str,
        gas_used: int,
        gas_price_gwei: float,
        eth_price_usd: float,
    ) -> GasCostEntry:
        """Record a gas cost event and persist it.

        Parameters
        ----------
        tx_hash:
            Unique transaction identifier (hex string or synthetic label).
        adapter:
            Adapter/protocol identifier (e.g. ``"aave_v3_ethereum"``).
        chain:
            Chain name (e.g. ``"ethereum"``, ``"arbitrum"``).
        gas_used:
            Gas units consumed (≥ 0).
        gas_price_gwei:
            Gas price in gwei (≥ 0).
        eth_price_usd:
            ETH price in USD at execution time (≥ 0).

        Returns
        -------
        GasCostEntry
            The newly recorded entry.
        """
        gas_used_i = _safe_int(gas_used, 0, 0)
        gas_price = _safe_float(gas_price_gwei, 0.0, 0.0)
        eth_price = _safe_float(eth_price_usd, 0.0, 0.0)
        cost = _compute_gas_cost(gas_used_i, gas_price, eth_price)

        entry = GasCostEntry(
            tx_hash=str(tx_hash) if tx_hash else "",
            adapter=str(adapter) if adapter else "",
            chain=str(chain) if chain else "",
            gas_used=gas_used_i,
            gas_price_gwei=gas_price,
            eth_price_usd=eth_price,
            cost_usd=cost,
            timestamp=_utc_now_iso(),
        )

        entries = self._load_entries()
        entries.append(entry)
        self._save_entries(entries)
        return entry

    def get_total_cost_usd(self, days: int = 30) -> float:
        """Sum of ``cost_usd`` across all entries within the last *days* days.

        Parameters
        ----------
        days:
            Lookback window in calendar days (default 30).

        Returns
        -------
        float
            Total gas cost in USD (≥ 0).
        """
        entries = _entries_within_days(self._load_entries(), days)
        return round(sum(e.cost_usd for e in entries), 8)

    def get_cost_by_adapter(self, days: int = 30) -> Dict[str, float]:
        """Gas costs grouped by adapter within the last *days* days.

        Returns
        -------
        dict[str, float]
            Mapping ``{adapter_id: total_cost_usd}``, sorted descending.
        """
        entries = _entries_within_days(self._load_entries(), days)
        totals: Dict[str, float] = {}
        for e in entries:
            key = e.adapter or "_unknown"
            totals[key] = round(totals.get(key, 0.0) + e.cost_usd, 8)
        return dict(sorted(totals.items(), key=lambda x: -x[1]))

    def get_cost_by_chain(self, days: int = 30) -> Dict[str, float]:
        """Gas costs grouped by chain within the last *days* days.

        Returns
        -------
        dict[str, float]
            Mapping ``{chain: total_cost_usd}``, sorted descending.
        """
        entries = _entries_within_days(self._load_entries(), days)
        totals: Dict[str, float] = {}
        for e in entries:
            key = e.chain or "_unknown"
            totals[key] = round(totals.get(key, 0.0) + e.cost_usd, 8)
        return dict(sorted(totals.items(), key=lambda x: -x[1]))

    def compute_net_apy(
        self,
        gross_apy: float,
        capital_usd: float,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Compute net APY after deducting annualised gas drag.

        Formula::

            cost_window   = total cost_usd in last <days> days
            annual_gas    = cost_window / days * 365
            gas_drag_pct  = annual_gas / capital_usd * 100
            gas_drag_bps  = gas_drag_pct * 100
            net_apy       = gross_apy – gas_drag_pct

        Grade (drag in bps):
            A < 5 bps, B < 15 bps, C < 30 bps, D ≥ 30 bps

        Parameters
        ----------
        gross_apy:
            Gross annual yield in percent (e.g. ``5.0`` for 5%).
        capital_usd:
            Portfolio capital in USD (must be > 0 for meaningful result).
        days:
            Lookback window for gas cost aggregation (default 30).

        Returns
        -------
        dict with keys: ``net_apy``, ``gas_drag_bps``, ``cost_usd``, ``grade``
        """
        gross = _safe_float(gross_apy, 0.0)
        capital = _safe_float(capital_usd, 0.0, 0.0)
        d = max(int(days), 1)

        cost_window = self.get_total_cost_usd(d)

        if capital <= 0.0:
            annual_gas = 0.0
            gas_drag_pct = 0.0
            gas_drag_bps = 0.0
        else:
            annual_gas = cost_window / d * 365
            gas_drag_pct = annual_gas / capital * 100.0
            gas_drag_bps = gas_drag_pct * 100.0

        net_apy = gross - gas_drag_pct
        grade = _grade_from_drag_bps(gas_drag_bps)

        return {
            "net_apy": round(net_apy, 6),
            "gas_drag_bps": round(gas_drag_bps, 6),
            "cost_usd": round(cost_window, 8),
            "grade": grade,
        }

    def generate_report(self, days: int = 30, gross_apy: float = 0.0, capital_usd: float = 0.0) -> Dict[str, Any]:
        """Generate a full advisory gas-cost report.

        Parameters
        ----------
        days:
            Lookback window (default 30).
        gross_apy:
            Gross APY for net-APY calculation (default 0.0).
        capital_usd:
            Capital base for drag calculation (default 0.0 → skipped).

        Returns
        -------
        dict with keys:
            ``schema_version``, ``generated_at``, ``summary``,
            ``by_adapter``, ``by_chain``, ``net_apy_impact``, ``advisory``
        """
        entries = self._load_entries()
        window_entries = _entries_within_days(entries, days)

        total_cost = round(sum(e.cost_usd for e in window_entries), 8)
        tx_count = len(window_entries)

        by_adapter = self.get_cost_by_adapter(days)
        by_chain = self.get_cost_by_chain(days)

        net_apy_impact: Dict[str, Any] = {}
        if gross_apy != 0.0 or capital_usd > 0.0:
            net_apy_impact = self.compute_net_apy(gross_apy, capital_usd, days)

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now_iso(),
            "summary": {
                "window_days": days,
                "total_cost_usd": total_cost,
                "tx_count": tx_count,
                "total_entries_all_time": len(entries),
            },
            "by_adapter": by_adapter,
            "by_chain": by_chain,
            "net_apy_impact": net_apy_impact,
            "advisory": ADVISORY,
        }


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------

def get_tracker(data_dir: str = "data") -> GasCostTracker:
    """Return a :class:`GasCostTracker` bound to *data_dir*."""
    return GasCostTracker(data_dir=data_dir)


__all__ = [
    "GasCostEntry",
    "GasCostTracker",
    "get_tracker",
    "_compute_gas_cost",
    "_grade_from_drag_bps",
    "_entries_within_days",
    "_safe_float",
    "_safe_int",
    "RING_BUFFER",
    "SCHEMA_VERSION",
    "ADVISORY",
    "GWEI_TO_ETH",
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """CLI: python3 -m spa_core.analytics.gas_cost_tracker [--check|--run]"""
    parser = argparse.ArgumentParser(
        description="Gas Cost Tracker (MP-624) — net APY after gas drag"
    )
    parser.add_argument("--check", action="store_true", default=False,
                        help="Compute and print report (no write).")
    parser.add_argument("--run", action="store_true", default=False,
                        help="Record a synthetic entry and save report.")
    parser.add_argument("--data-dir", default="data", metavar="PATH")
    args = parser.parse_args(argv)

    tracker = GasCostTracker(data_dir=args.data_dir)

    if args.run:
        # Record a synthetic example entry
        entry = tracker.record_gas(
            tx_hash="0xSYNTHETIC",
            adapter="aave_v3_ethereum",
            chain="ethereum",
            gas_used=200_000,
            gas_price_gwei=20.0,
            eth_price_usd=3000.0,
        )
        print(f"Recorded: {entry.tx_hash}, cost=${entry.cost_usd:.4f}")

    report = tracker.generate_report(days=30, gross_apy=5.0, capital_usd=100_000.0)
    print("=== Gas Cost Tracker (MP-624) ===")
    print(f"  window_days      : {report['summary']['window_days']}")
    print(f"  total_cost_usd   : ${report['summary']['total_cost_usd']:.4f}")
    print(f"  tx_count         : {report['summary']['tx_count']}")
    if report["net_apy_impact"]:
        ni = report["net_apy_impact"]
        print(f"  net_apy          : {ni['net_apy']:.4f}%")
        print(f"  gas_drag_bps     : {ni['gas_drag_bps']:.2f} bps")
        print(f"  grade            : {ni['grade']}")
    print(f"  advisory         : {report['advisory']}")
    if not args.run:
        print("\n(--check mode: not saved. Use --run to record synthetic entry.)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
