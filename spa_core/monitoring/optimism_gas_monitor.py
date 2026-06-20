"""
spa_core/monitoring/optimism_gas_monitor.py
===========================================
Optimism (OP Mainnet) gas price monitor (multichain expansion).

Kill-switch: Optimism gas > OPTIMISM_GAS_THRESHOLD_GWEI for 3+ consecutive days
→ advisory signal to reduce Optimism allocation. OP L2 fees are typically
0.001–0.05 Gwei; a sustained spike implies sequencer/L1 congestion.

Data sources (no API key required):
  1. BlockNative Gas Estimator (chainid=10 = Optimism)
  2. Infura free gas endpoint (networks/10)
  3. Fallback: conservative constant (Optimism is typically 0.001–0.05 Gwei)

Data file: data/optimism_gas_history.json

Rules:
  - STDLIB ONLY — no external dependencies
  - READ-ONLY (monitoring/advisory) — only writes to data/optimism_gas_history.json
  - FAIL-SAFE — every network call catches exceptions, never crashes
  - ATOMIC writes — tmp + os.replace
  - LLM FORBIDDEN in this module
  - Max 30 readings kept (ring-buffer); one reading per calendar day

CLI:
  python3 -m spa_core.monitoring.optimism_gas_monitor [--check | --run]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPTIMISM_CHAIN_ID: int = 10
OPTIMISM_GAS_THRESHOLD_GWEI: float = 1.0   # advisory kill-switch threshold (L2)
OPTIMISM_GAS_KILL_DAYS: int = 3            # consecutive days above threshold
MAX_HISTORY_DAYS: int = 30
HTTP_TIMEOUT_SEC: float = 5.0

# Typical Optimism gas is 0.001–0.05 Gwei; 0.05 is a safe conservative fallback
FALLBACK_GWEI: float = 0.05

GAS_APIS: List[str] = [
    "https://api.blocknative.com/gasprices/blockprices?chainid=10",
    "https://gas.api.infura.io/networks/10/suggestedGasFees",
]


class OptimismGasMonitor:
    """Monitors Optimism gas prices and emits an advisory kill-switch."""

    DATA_FILENAME = "optimism_gas_history.json"
    CHAIN = "optimism"

    def __init__(self, data_dir: str | Path = "data") -> None:
        self._data_dir = Path(data_dir)
        self._data_file = self._data_dir / self.DATA_FILENAME

    # ------------------------------------------------------------------
    @property
    def DATA_FILE(self) -> str:
        return f"data/{self.DATA_FILENAME}"

    def get_current_gas_gwei(self) -> float:
        for url in GAS_APIS:
            try:
                result = self._fetch_gas_gwei(url)
                if result is not None and result >= 0:
                    return result
            except Exception:  # noqa: BLE001
                continue
        return FALLBACK_GWEI

    def load_history(self) -> Dict[str, Any]:
        try:
            raw = self._data_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("not a dict")
            return data
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, ValueError, OSError):
            pass
        return self._empty_history()

    def save_history(self, data: Dict[str, Any]) -> None:
        """Atomic write (tmp + os.replace)."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._data_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
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
        if gwei is None:
            gwei = self.get_current_gas_gwei()
        if today is None:
            today = date.today()

        today_str = today.isoformat()
        now_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        history = self.load_history()
        readings: List[Dict[str, Any]] = history.get("recent_readings", [])
        readings = [r for r in readings if r.get("date") != today_str]

        above = gwei > OPTIMISM_GAS_THRESHOLD_GWEI
        readings.append(
            {"date": today_str, "gwei": round(gwei, 6), "above_threshold": above}
        )
        readings = sorted(readings, key=lambda r: r.get("date", ""))[-MAX_HISTORY_DAYS:]

        consecutive_above = self._count_consecutive_above(readings)
        was_active = history.get("kill_switch_active", False)
        kill_switch_active = consecutive_above >= OPTIMISM_GAS_KILL_DAYS
        activated_at = history.get("kill_switch_activated_at")

        if kill_switch_active and not was_active:
            activated_at = now_utc
            action = "KILL_SWITCH_ACTIVE"
        elif kill_switch_active and was_active:
            action = "KILL_SWITCH_ACTIVE"
        elif not kill_switch_active and was_active:
            activated_at = None
            action = "KILL_SWITCH_RESET"
        elif above and consecutive_above > 0:
            action = "WARN"
        else:
            action = "OK"

        updated_history: Dict[str, Any] = {
            "chain": self.CHAIN,
            "last_updated": now_utc,
            "recent_readings": readings,
            "consecutive_above": consecutive_above,
            "kill_switch_active": kill_switch_active,
            "kill_switch_activated_at": activated_at,
        }
        self.save_history(updated_history)

        return {
            "chain": self.CHAIN,
            "gwei": round(gwei, 6),
            "consecutive_above": consecutive_above,
            "kill_switch_active": kill_switch_active,
            "action": action,
            "date": today_str,
            "threshold_gwei": OPTIMISM_GAS_THRESHOLD_GWEI,
        }

    def is_kill_switch_active(self) -> bool:
        return bool(self.load_history().get("kill_switch_active", False))

    def get_status(self) -> Dict[str, Any]:
        history = self.load_history()
        readings: List[Dict[str, Any]] = history.get("recent_readings", [])
        latest_gwei: Optional[float] = readings[-1].get("gwei") if readings else None
        return {
            "chain": self.CHAIN,
            "gwei": latest_gwei,
            "consecutive_above": history.get("consecutive_above", 0),
            "kill_switch_active": bool(history.get("kill_switch_active", False)),
            "last_updated": history.get("last_updated"),
            "threshold_gwei": OPTIMISM_GAS_THRESHOLD_GWEI,
            "kill_days": OPTIMISM_GAS_KILL_DAYS,
        }

    # ------------------------------------------------------------------
    def _fetch_gas_gwei(self, url: str) -> Optional[float]:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "SPA-Monitor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read())

        if "blockPrices" in data:
            block_prices = data["blockPrices"]
            if block_prices and isinstance(block_prices, list):
                estimated = block_prices[0].get("estimatedPrices", [])
                if estimated and isinstance(estimated, list):
                    price = estimated[0].get("price")
                    if price is not None:
                        return float(price)
            base_fee = (
                data["blockPrices"][0].get("baseFeePerGas")
                if data["blockPrices"]
                else None
            )
            if base_fee is not None:
                return float(base_fee)

        for level in ("medium", "low"):
            if level in data:
                node = data[level]
                fee = node.get("suggestedMaxFeePerGas") or node.get(
                    "suggestedMaxPriorityFeePerGas"
                )
                if fee is not None:
                    return float(fee)

        for key in ("gasPrice", "maxFeePerGas", "baseFee", "gas_price", "fast"):
            if key in data and data[key] is not None:
                return float(data[key])
        return None

    @staticmethod
    def _count_consecutive_above(readings: List[Dict[str, Any]]) -> int:
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
            "chain": "optimism",
            "last_updated": None,
            "recent_readings": [],
            "consecutive_above": 0,
            "kill_switch_active": False,
            "kill_switch_activated_at": None,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    monitor = OptimismGasMonitor(data_dir=_repo_root() / "data")
    write = "--run" in argv

    if write:
        result = monitor.record_reading()
    else:
        gwei = monitor.get_current_gas_gwei()
        history = monitor.load_history()
        consecutive = history.get("consecutive_above", 0)
        kill_active = history.get("kill_switch_active", False)
        above = gwei > OPTIMISM_GAS_THRESHOLD_GWEI
        if kill_active:
            action = "KILL_SWITCH_ACTIVE"
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
            "threshold_gwei": OPTIMISM_GAS_THRESHOLD_GWEI,
        }

    print("\n[OptimismGasMonitor] Gas Check (chainid=10)")
    print(f"  Date:               {result['date']}")
    print(f"  Gas (Gwei):         {result['gwei']}")
    print(f"  Threshold (Gwei):   {result['threshold_gwei']}")
    print(f"  Consecutive above:  {result['consecutive_above']} / {OPTIMISM_GAS_KILL_DAYS} days")
    print(f"  Kill-switch active: {result['kill_switch_active']}")
    print(f"  Action:             {result['action']}")
    if write:
        print(f"  Written to:         {monitor._data_file}")
    else:
        print("  (check mode — not written; use --run to persist)")
    print()
    sys.exit(0 if result["action"] != "KILL_SWITCH_ACTIVE" else 2)


if __name__ == "__main__":
    main()
