"""
spa_core/analytics/strategy_rs002_tracker.py — RS-002 Shadow Tracker

Shadow tracking of RS-002 Cashflow Research Strategy hypothetical performance.

Stores simulated daily snapshots in data/research/rs002_shadow.json.
Ring-buffer cap = 100 entries. Atomic writes (mkstemp + os.replace).

RESEARCH-ONLY module. Never affects allocator, risk, or execution.
Pure stdlib, no external dependencies. LLM FORBIDDEN.

Data schema:
  {
    "schema_version": "1.0",
    "strategy_id": "S21",
    "research_only": true,
    "entries": [
      {
        "date": "YYYY-MM-DD",
        "timestamp": "ISO-8601",
        "capital": float,
        "gross_apy_pct": float,
        "net_apy_pct": float,
        "volatility_regime": str,
        "btc_move_pct": float,
        "il_drag_pct": float,
        "leg_apys": {...},
        "notes": str
      },
      ...
    ],
    "ring_buffer_cap": 100,
    "last_updated": "ISO-8601"
  }
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from spa_core.strategies.s21_cashflow_research import (
    CashflowResearchStrategy,
    STRATEGY_ID,
    GROSS_APY_ASSUMPTIONS,
)

# ─── Constants ────────────────────────────────────────────────────────────────

RING_BUFFER_CAP = 100
SCHEMA_VERSION = "1.0"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "research"
_FILENAME = "rs002_shadow.json"


# ══════════════════════════════════════════════════════════════════════════════
# RS002ShadowTracker
# ══════════════════════════════════════════════════════════════════════════════

class RS002ShadowTracker:
    """
    Shadow tracker for RS-002 Cashflow Research Strategy.

    Records hypothetical daily performance snapshots. Data is stored in
    data/research/rs002_shadow.json with ring-buffer cap of 100 entries.
    Writes are atomic (mkstemp + os.replace).

    This tracker is RESEARCH-ONLY and must never influence live allocation,
    risk policy, or execution decisions.

    Parameters
    ----------
    data_dir : str or Path, optional
        Directory for the shadow JSON file.
        Defaults to <repo-root>/data/research/.
    """

    def __init__(self, data_dir: Optional[str | Path] = None) -> None:
        if data_dir is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            self._data_dir = Path(data_dir)
        self._path = self._data_dir / _FILENAME
        self._strategy = CashflowResearchStrategy()
        self._data: dict = self._load()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def record(
        self,
        date: str,
        capital: float,
        volatility_regime: str = "sideways",
        btc_move_pct: float = 0.0,
        live_apy: Optional[Dict[str, float]] = None,
        notes: str = "",
    ) -> Dict:
        """
        Record a hypothetical daily snapshot for RS-002.

        Parameters
        ----------
        date : str
            Date string in YYYY-MM-DD format.
        capital : float
            Capital at snapshot time (USD).
        volatility_regime : str
            Volatility regime: "sideways", "trending", "crash", "bull".
        btc_move_pct : float
            BTC price move percentage (e.g., 20 for ±20%).
        live_apy : dict, optional
            Live APY overrides for strict-eligible legs.
        notes : str
            Optional annotation.

        Returns
        -------
        dict
            The snapshot entry that was recorded.
        """
        now = datetime.now(timezone.utc).isoformat()
        alloc = self._strategy.allocate(capital, live_apy)

        gross_apy = self._strategy.gross_blended_apy()
        net_apy = self._strategy.net_apy_estimate(volatility_regime)
        il_drag = self._strategy.il_drag_estimate(btc_move_pct)

        leg_apys: Dict[str, float] = {
            leg: info["apy_pct"] for leg, info in alloc["legs"].items()
        }

        entry = {
            "date": date,
            "timestamp": now,
            "capital": capital,
            "gross_apy_pct": gross_apy,
            "net_apy_pct": net_apy,
            "volatility_regime": volatility_regime,
            "btc_move_pct": btc_move_pct,
            "il_drag_pct": il_drag,
            "leg_apys": leg_apys,
            "notes": notes,
        }

        entries: list = self._data.get("entries", [])
        entries.append(entry)

        # Ring-buffer: keep only the last RING_BUFFER_CAP entries
        if len(entries) > RING_BUFFER_CAP:
            entries = entries[-RING_BUFFER_CAP:]

        self._data["entries"] = entries
        self._data["last_updated"] = now
        self._save()
        return entry

    def entries(self) -> list:
        """Return current entries list (copy)."""
        return list(self._data.get("entries", []))

    def entry_count(self) -> int:
        """Return number of stored entries."""
        return len(self._data.get("entries", []))

    def latest(self) -> Optional[Dict]:
        """Return the most recent entry, or None if empty."""
        entries = self._data.get("entries", [])
        return entries[-1] if entries else None

    def clear(self) -> None:
        """Clear all entries and persist."""
        self._data["entries"] = []
        self._data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def summary_stats(self) -> Dict:
        """
        Return aggregate stats over all recorded entries.

        Returns
        -------
        dict
            {
              "count": int,
              "avg_gross_apy": float | None,
              "avg_net_apy": float | None,
              "avg_il_drag": float | None,
              "regime_counts": dict[str, int],
            }
        """
        entries = self._data.get("entries", [])
        if not entries:
            return {
                "count": 0,
                "avg_gross_apy": None,
                "avg_net_apy": None,
                "avg_il_drag": None,
                "regime_counts": {},
            }

        gross_vals = [e["gross_apy_pct"] for e in entries]
        net_vals = [e["net_apy_pct"] for e in entries]
        il_vals = [e["il_drag_pct"] for e in entries]
        regime_counts: Dict[str, int] = {}
        for e in entries:
            r = e.get("volatility_regime", "unknown")
            regime_counts[r] = regime_counts.get(r, 0) + 1

        return {
            "count": len(entries),
            "avg_gross_apy": round(sum(gross_vals) / len(gross_vals), 4),
            "avg_net_apy": round(sum(net_vals) / len(net_vals), 4),
            "avg_il_drag": round(sum(il_vals) / len(il_vals), 4),
            "regime_counts": regime_counts,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence (atomic writes)
    # ──────────────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        """Load existing data from disk, or return a fresh structure."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and "entries" in data:
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return self._fresh_structure()

    def _fresh_structure(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "strategy_id": STRATEGY_ID,
            "research_only": True,
            "entries": [],
            "ring_buffer_cap": RING_BUFFER_CAP,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def _save(self) -> None:
        """Atomically write data to disk (mkstemp + os.replace)."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, indent=2, ensure_ascii=False)
        fd, tmp_path = tempfile.mkstemp(
            dir=self._data_dir, prefix=".rs002_shadow_tmp_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ─── CLI entry-point ──────────────────────────────────────────────────────────

def _cli() -> None:  # pragma: no cover
    import sys
    tracker = RS002ShadowTracker()
    stats = tracker.summary_stats()
    print(json.dumps({
        "strategy_id": STRATEGY_ID,
        "research_only": True,
        "entry_count": tracker.entry_count(),
        "summary_stats": stats,
    }, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _cli()
