"""
spa_core/monitoring/base_gas_monitor.py
========================================
Base chain gas price monitor — ADR-025 kill-switch condition.

Kill-switch: Base gas > 10 Gwei for 3+ consecutive days → reduce Base allocation to 0%.

Data sources (no API key required):
  1. BlockNative Gas Estimator (chainid=8453 = Base)
  2. Infura free gas endpoint (networks/8453)
  3. Fallback: conservative constant (Base is typically 0.001–0.1 Gwei)

Data file: data/base_gas_history.json
Format:
{
  "last_updated": "2026-06-12T10:00:00Z",
  "recent_readings": [
    {"date": "2026-06-12", "gwei": 0.08, "above_threshold": false}
  ],
  "consecutive_above": 0,
  "kill_switch_active": false,
  "kill_switch_activated_at": null
}

Rules:
  - STDLIB ONLY — no external dependencies
  - READ-ONLY (adapters domain) — only writes to data/base_gas_history.json
  - FAIL-SAFE — every network call catches exceptions, never crashes
  - ATOMIC writes — tmp + os.replace
  - LLM FORBIDDEN in this module
  - Max 30 readings kept (ring-buffer)
  - One reading per calendar day (deduplication)

CLI:
  python3 -m spa_core.monitoring.base_gas_monitor [--check | --run]
  --check  (default) compute and print, no write
  --run    compute + atomic write to data/base_gas_history.json
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants (ADR-025)
# ---------------------------------------------------------------------------

BASE_GAS_THRESHOLD_GWEI: float = 10.0   # ADR-025 kill-switch threshold
BASE_GAS_KILL_DAYS: int = 3             # consecutive days above threshold → kill-switch
MAX_HISTORY_DAYS: int = 30              # ring-buffer size for recent_readings
HTTP_TIMEOUT_SEC: float = 5.0           # network timeout per request

# Typical Base chain gas is 0.001–0.1 Gwei; 0.1 is a safe conservative fallback
FALLBACK_GWEI: float = 0.1

# Public APIs that do not require an API key
# BlockNative: chain 8453 = Base
# Infura free gas API: https://gas.api.infura.io/networks/8453/suggestedGasFees
GAS_APIS: List[str] = [
    "https://api.blocknative.com/gasprices/blockprices?chainid=8453",
    "https://gas.api.infura.io/networks/8453/suggestedGasFees",
]


# ---------------------------------------------------------------------------
# BaseGasMonitor
# ---------------------------------------------------------------------------

class BaseGasMonitor:
    """
    Monitors Base chain gas prices and enforces the ADR-025 kill-switch.

    Typical usage:
        monitor = BaseGasMonitor(data_dir="data")
        result = monitor.record_reading()
        # result["action"] is one of: OK | WARN | KILL_SWITCH_ACTIVE | KILL_SWITCH_RESET
    """

    DATA_FILENAME = "base_gas_history.json"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self._data_dir = Path(data_dir)
        self._data_file = self._data_dir / self.DATA_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def DATA_FILE(self) -> str:
        """Canonical relative path used in tests and external callers."""
        return f"data/{self.DATA_FILENAME}"

    def get_current_gas_gwei(self) -> float:
        """
        Fetch current Base chain gas price in Gwei.

        Tries GAS_APIS in order; on any error falls through to the next.
        Returns FALLBACK_GWEI if all sources fail.

        The returned value is always >= 0.
        """
        for url in GAS_APIS:
            try:
                result = self._fetch_gas_gwei(url)
                if result is not None and result >= 0:
                    return result
            except Exception:  # noqa: BLE001
                continue
        return FALLBACK_GWEI

    def load_history(self) -> Dict[str, Any]:
        """
        Load gas price history from disk.

        Returns a default empty history structure if the file does not exist
        or is malformed (fail-safe).
        """
        try:
            raw = self._data_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            # Basic validation
            if not isinstance(data, dict):
                raise ValueError("not a dict")
            return data
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, ValueError, OSError):
            pass
        return self._empty_history()

    def save_history(self, data: Dict[str, Any]) -> None:
        """
        Atomically write history to data/base_gas_history.json.

        Uses tmp-file + os.replace pattern (FORBIDDEN to use direct open(..., "w")).
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._data_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(self._data_file))
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def record_reading(
        self,
        gwei: Optional[float] = None,
        *,
        today: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Record a daily gas price reading, update kill-switch state, and persist.

        Args:
            gwei:  Gas price in Gwei. If None, fetches live from network.
            today: Override today's date (for testing).

        Returns dict with keys:
            gwei               float  — recorded gas price
            consecutive_above  int    — days in a row above threshold
            kill_switch_active bool   — whether kill-switch is now triggered
            action             str    — OK | WARN | KILL_SWITCH_ACTIVE | KILL_SWITCH_RESET
            date               str    — ISO date of this reading (YYYY-MM-DD)
            threshold_gwei     float  — ADR-025 threshold
        """
        if gwei is None:
            gwei = self.get_current_gas_gwei()

        if today is None:
            today = date.today()

        today_str = today.isoformat()
        now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        history = self.load_history()
        readings: List[Dict[str, Any]] = history.get("recent_readings", [])

        # Deduplication: remove existing entry for today if present
        readings = [r for r in readings if r.get("date") != today_str]

        above = gwei > BASE_GAS_THRESHOLD_GWEI
        reading = {
            "date": today_str,
            "gwei": round(gwei, 6),
            "above_threshold": above,
        }
        readings.append(reading)

        # Enforce ring-buffer (keep last MAX_HISTORY_DAYS entries, sorted by date)
        readings = sorted(readings, key=lambda r: r.get("date", ""))[-MAX_HISTORY_DAYS:]

        # Recompute consecutive_above from the trailing window of sorted readings
        consecutive_above = self._count_consecutive_above(readings)

        # Determine kill-switch state
        was_active = history.get("kill_switch_active", False)
        kill_switch_active = consecutive_above >= BASE_GAS_KILL_DAYS
        activated_at = history.get("kill_switch_activated_at")

        if kill_switch_active and not was_active:
            # Just activated
            activated_at = now_utc
            action = "KILL_SWITCH_ACTIVE"
        elif kill_switch_active and was_active:
            # Still active
            action = "KILL_SWITCH_ACTIVE"
        elif not kill_switch_active and was_active:
            # Reset
            activated_at = None
            action = "KILL_SWITCH_RESET"
        elif above and consecutive_above > 0:
            # 1 or 2 days above threshold (WARN)
            action = "WARN"
        else:
            action = "OK"

        updated_history: Dict[str, Any] = {
            "last_updated": now_utc,
            "recent_readings": readings,
            "consecutive_above": consecutive_above,
            "kill_switch_active": kill_switch_active,
            "kill_switch_activated_at": activated_at,
        }
        self.save_history(updated_history)

        return {
            "gwei": round(gwei, 6),
            "consecutive_above": consecutive_above,
            "kill_switch_active": kill_switch_active,
            "action": action,
            "date": today_str,
            "threshold_gwei": BASE_GAS_THRESHOLD_GWEI,
        }

    def is_kill_switch_active(self) -> bool:
        """
        Check if the kill-switch is currently active (3+ consecutive days above threshold).

        Reads state from disk without side effects.
        """
        history = self.load_history()
        return bool(history.get("kill_switch_active", False))

    def get_status(self) -> Dict[str, Any]:
        """
        Get current monitoring status for the dashboard.

        Returns dict with keys:
            gwei               float | None
            consecutive_above  int
            kill_switch_active bool
            last_updated       str | None
            threshold_gwei     float
            kill_days          int
        """
        history = self.load_history()
        readings: List[Dict[str, Any]] = history.get("recent_readings", [])
        latest_gwei: Optional[float] = None
        if readings:
            latest_gwei = readings[-1].get("gwei")

        return {
            "gwei": latest_gwei,
            "consecutive_above": history.get("consecutive_above", 0),
            "kill_switch_active": bool(history.get("kill_switch_active", False)),
            "last_updated": history.get("last_updated"),
            "threshold_gwei": BASE_GAS_THRESHOLD_GWEI,
            "kill_days": BASE_GAS_KILL_DAYS,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_gas_gwei(self, url: str) -> Optional[float]:
        """
        Fetch gas price in Gwei from a single URL.

        Returns None if the response cannot be parsed.
        Raises on network errors (caller handles).
        """
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "SPA-Monitor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            raw = resp.read()
            data = json.loads(raw)

        # BlockNative format: {"blockPrices": [{"estimatedPrices": [{"price": <gwei>}]}]}
        if "blockPrices" in data:
            block_prices = data["blockPrices"]
            if block_prices and isinstance(block_prices, list):
                estimated = block_prices[0].get("estimatedPrices", [])
                if estimated and isinstance(estimated, list):
                    price = estimated[0].get("price")
                    if price is not None:
                        return float(price)
            # Fallback: baseFeePerGas field
            base_fee = data["blockPrices"][0].get("baseFeePerGas") if data["blockPrices"] else None
            if base_fee is not None:
                return float(base_fee)

        # Infura format: {"low": {"suggestedMaxFeePerGas": "<gwei>", ...}, "medium": {...}, ...}
        if "medium" in data:
            medium = data["medium"]
            fee = medium.get("suggestedMaxFeePerGas") or medium.get("suggestedMaxPriorityFeePerGas")
            if fee is not None:
                return float(fee)
        if "low" in data:
            low = data["low"]
            fee = low.get("suggestedMaxFeePerGas") or low.get("suggestedMaxPriorityFeePerGas")
            if fee is not None:
                return float(fee)

        # Generic: look for any "gasPrice", "maxFeePerGas", "baseFee" key
        for key in ("gasPrice", "maxFeePerGas", "baseFee", "gas_price", "fast"):
            if key in data and data[key] is not None:
                return float(data[key])

        return None

    @staticmethod
    def _count_consecutive_above(readings: List[Dict[str, Any]]) -> int:
        """
        Count how many trailing consecutive days are above threshold.

        Readings must be sorted ascending by date (oldest first).
        Counts backwards from the most recent entry.
        """
        count = 0
        for r in reversed(readings):
            if r.get("above_threshold", False):
                count += 1
            else:
                break
        return count

    @staticmethod
    def _empty_history() -> Dict[str, Any]:
        return {
            "last_updated": None,
            "recent_readings": [],
            "consecutive_above": 0,
            "kill_switch_active": False,
            "kill_switch_activated_at": None,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Resolve repo root from this file's location."""
    return Path(__file__).resolve().parent.parent.parent  # spa_core/monitoring/… → repo


def main(argv: Optional[List[str]] = None) -> None:
    """
    CLI: record a Base gas reading and print status.

    --check  (default) compute and print, no write to disk
    --run    compute + atomic write to data/base_gas_history.json
    """
    if argv is None:
        argv = sys.argv[1:]

    repo = _repo_root()
    data_dir = repo / "data"
    monitor = BaseGasMonitor(data_dir=data_dir)

    write = "--run" in argv

    if write:
        result = monitor.record_reading()
    else:
        # Check mode: read live gas but do NOT persist
        gwei = monitor.get_current_gas_gwei()
        history = monitor.load_history()
        consecutive = history.get("consecutive_above", 0)
        kill_active = history.get("kill_switch_active", False)
        above = gwei > BASE_GAS_THRESHOLD_GWEI
        if kill_active:
            action = "KILL_SWITCH_ACTIVE"
        elif above and consecutive > 0:
            action = "WARN"
        elif above:
            action = "WARN"
        else:
            action = "OK"
        result = {
            "gwei": round(gwei, 6),
            "consecutive_above": consecutive,
            "kill_switch_active": kill_active,
            "action": action,
            "date": date.today().isoformat(),
            "threshold_gwei": BASE_GAS_THRESHOLD_GWEI,
        }

    print("\n[BaseGasMonitor] ADR-025 Kill-Switch Check")
    print(f"  Date:               {result['date']}")
    print(f"  Gas (Gwei):         {result['gwei']}")
    print(f"  Threshold (Gwei):   {result['threshold_gwei']}")
    print(f"  Consecutive above:  {result['consecutive_above']} / {BASE_GAS_KILL_DAYS} days")
    print(f"  Kill-switch active: {result['kill_switch_active']}")
    print(f"  Action:             {result['action']}")
    if write:
        print(f"  Written to:         {data_dir / BaseGasMonitor.DATA_FILENAME}")
    else:
        print("  (check mode — not written to disk; use --run to persist)")
    print()

    sys.exit(0 if result["action"] != "KILL_SWITCH_ACTIVE" else 2)


if __name__ == "__main__":
    main()
