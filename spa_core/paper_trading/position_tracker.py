#!/usr/bin/env python3
"""Daily Portfolio Position & Allocation Tracker (SPA / MP-position_tracker) — read-only / advisory.

Records a daily snapshot of the portfolio's allocation weights into
``data/position_history.json`` (ring-buffer of 365 entries), enabling
downstream drift analysis and yield attribution.

Key features
============
- **Idempotent per calendar day** — a second ``record_position`` call for the
  same UTC date is a no-op (returns the existing snapshot unchanged).
- **Atomic writes** — always ``tmp-file + os.replace``; never a direct open-w
  on the state file.
- **Pure stdlib** — no external dependencies; no network calls.
- **Advisory / read-only** — never touches risk, execution, or allocator code.

position_history.json schema (ring-buffer, max 365 entries)::

    [
      {
        "date":         "2026-06-12",
        "equity":       100017.45,
        "allocation":   {"aave_v3": 0.30, "compound_v3": 0.25, "morpho_blue": 0.45},
        "apy_weighted": 3.85,           // only present when apy_map supplied
        "timestamp":    "2026-06-12T10:00:00+00:00",
        "top_adapter":  "morpho_blue",
        "adapter_count": 3
      },
      ...
    ]

CLI::

    python3 -m spa_core.paper_trading.position_tracker --check   # no write
    python3 -m spa_core.paper_trading.position_tracker --run     # + atomic write
    python3 -m spa_core.paper_trading.position_tracker --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

# Ring-buffer cap — never grow beyond this
HISTORY_MAX: int = 365

# File that stores the history list
HISTORY_FILENAME: str = "position_history.json"


class PositionTracker:
    """Records and analyses daily allocation snapshots.

    All public methods accept an optional ``data_dir`` parameter (default
    ``"data"``) so tests can point at a temporary directory without touching
    the real state files.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_position(
        self,
        allocation: Dict[str, float],
        equity: float,
        apy_map: Optional[Dict[str, float]] = None,
        date_str: Optional[str] = None,
        data_dir: str = "data",
    ) -> dict:
        """Append today's position snapshot to ``position_history.json``.

        Parameters
        ----------
        allocation:
            Mapping ``adapter_id → weight`` where weights are fractions
            (sum ≈ 1.0, e.g. ``{"aave_v3": 0.30, "compound_v3": 0.70}``).
        equity:
            Current portfolio value in USD.
        apy_map:
            Optional ``{adapter_id: apy_pct}`` (percentage, not fraction).
            When supplied the snapshot includes ``apy_weighted`` — the
            allocation-weighted average APY.
        date_str:
            Override the snapshot date as ``"YYYY-MM-DD"``.  Defaults to
            today's UTC date.
        data_dir:
            Directory that contains (or will contain) ``position_history.json``.

        Returns
        -------
        dict
            The snapshot that was recorded (or the pre-existing one if today
            was already recorded — idempotent).

        Raises
        ------
        ValueError
            If ``allocation`` is not a dict, or ``equity`` is not a real number.
        """
        if not isinstance(allocation, dict):
            raise ValueError("allocation must be a dict")
        if not isinstance(equity, (int, float)) or equity != equity:  # NaN check
            raise ValueError("equity must be a real number")

        target_date = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._history_path(data_dir)
        history = self._load_history(path)

        # Idempotency: skip if this date is already recorded
        for existing in history:
            if existing.get("date") == target_date:
                logger.debug("position_tracker: date %s already recorded, skipping", target_date)
                return existing

        snapshot = self._build_snapshot(allocation, equity, apy_map, target_date)

        history.append(snapshot)
        # Ring-buffer — keep only the most recent HISTORY_MAX entries
        if len(history) > HISTORY_MAX:
            history = history[-HISTORY_MAX:]

        self._atomic_write(path, history)
        logger.info(
            "position_tracker: recorded %s equity=%.2f adapters=%d",
            target_date,
            equity,
            len(allocation),
        )
        return snapshot

    def get_history(self, data_dir: str = "data") -> List[dict]:
        """Return the full position history list (oldest first).

        Returns ``[]`` when the file is absent or unreadable.
        """
        return self._load_history(self._history_path(data_dir))

    def get_current_weights(self, data_dir: str = "data") -> Dict[str, float]:
        """Return the latest allocation weights dict, or ``{}`` if no history."""
        history = self._load_history(self._history_path(data_dir))
        if not history:
            return {}
        return dict(history[-1].get("allocation", {}))

    def compute_drift(
        self,
        target_weights: Dict[str, float],
        data_dir: str = "data",
    ) -> Dict[str, float]:
        """Compute per-adapter drift from ``target_weights``.

        Drift is defined as ``(current_weight - target_weight) * 100``
        (percentage points).  Adapters present only in target or only in
        current are included with the missing side treated as 0.

        Returns ``{}`` when there is no recorded history yet.
        """
        current = self.get_current_weights(data_dir)
        if not current:
            return {}

        all_keys = set(current) | set(target_weights)
        return {
            k: round((current.get(k, 0.0) - target_weights.get(k, 0.0)) * 100, 6)
            for k in sorted(all_keys)
        }

    def get_concentration_metric(self, data_dir: str = "data") -> dict:
        """Return concentration metrics for the current (latest) allocation.

        Returns
        -------
        dict with keys:

        - ``max_single_pct`` — largest single adapter weight in percent.
        - ``top3_pct``       — combined weight of the top-3 adapters in percent.
        - ``hhi``            — Herfindahl-Hirschman Index (sum of squared weight
          fractions, in ``[0, 1]``).
        - ``adapter_count``  — number of adapters with positive weight.

        Returns all-zero / zero-count dict when there is no history.
        """
        weights = self.get_current_weights(data_dir)
        return self._concentration_from_weights(weights)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _history_path(data_dir: str) -> Path:
        return Path(data_dir) / HISTORY_FILENAME

    def _load_history(self, path: Path) -> List[dict]:
        """Safe load with fallback to ``[]``."""
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            logger.warning("position_tracker: unexpected type in %s, resetting", path)
            return []
        except FileNotFoundError:
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("position_tracker: could not read %s: %s", path, exc)
            return []

    def _atomic_write(self, path: Path, data: List[dict]) -> None:
        """Write ``data`` atomically via tmp + os.replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(data, str(path))
    @staticmethod
    def _build_snapshot(
        allocation: Dict[str, float],
        equity: float,
        apy_map: Optional[Dict[str, float]],
        date_str: str,
    ) -> dict:
        """Construct a single snapshot dict."""
        # Normalise: keep only numeric, non-negative weights
        clean_alloc: Dict[str, float] = {}
        for k, v in allocation.items():
            if isinstance(v, (int, float)) and v == v and v >= 0:  # skip NaN/neg
                clean_alloc[str(k)] = float(v)

        # Top adapter by weight
        top_adapter: Optional[str] = None
        if clean_alloc:
            top_adapter = max(clean_alloc, key=lambda k: clean_alloc[k])

        snapshot: dict = {
            "date": date_str,
            "equity": round(float(equity), 6),
            "allocation": clean_alloc,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "top_adapter": top_adapter,
            "adapter_count": len(clean_alloc),
        }

        # Weighted APY — only when apy_map is supplied
        if apy_map is not None:
            total_w = sum(clean_alloc.values())
            if total_w > 0:
                weighted = sum(
                    clean_alloc.get(k, 0.0) * v
                    for k, v in apy_map.items()
                    if isinstance(v, (int, float)) and v == v
                )
                snapshot["apy_weighted"] = round(weighted / total_w, 6)
            else:
                snapshot["apy_weighted"] = 0.0

        return snapshot

    @staticmethod
    def _concentration_from_weights(weights: Dict[str, float]) -> dict:
        """Compute HHI and friends from a weight dict."""
        if not weights:
            return {
                "max_single_pct": 0.0,
                "top3_pct": 0.0,
                "hhi": 0.0,
                "adapter_count": 0,
            }

        positive = {k: v for k, v in weights.items() if isinstance(v, (int, float)) and v > 0}
        if not positive:
            return {
                "max_single_pct": 0.0,
                "top3_pct": 0.0,
                "hhi": 0.0,
                "adapter_count": 0,
            }

        total = sum(positive.values())
        fracs = [v / total for v in positive.values()]
        fracs_sorted = sorted(fracs, reverse=True)

        hhi = sum(f * f for f in fracs)
        max_single_pct = fracs_sorted[0] * 100.0
        top3_pct = sum(fracs_sorted[:3]) * 100.0

        return {
            "max_single_pct": round(max_single_pct, 6),
            "top3_pct": round(top3_pct, 6),
            "hhi": round(hhi, 8),
            "adapter_count": len(positive),
        }


# ---------------------------------------------------------------------------
# CLI entry-point (offline, exit 0 always, advisory only)
# ---------------------------------------------------------------------------

def _build_report(tracker: PositionTracker, data_dir: str) -> dict:
    history = tracker.get_history(data_dir)
    current = tracker.get_current_weights(data_dir)
    concentration = tracker.get_concentration_metric(data_dir)
    latest = history[-1] if history else {}
    return {
        "entries": len(history),
        "latest_date": latest.get("date"),
        "latest_equity": latest.get("equity"),
        "current_weights": current,
        "concentration": concentration,
    }


def main(argv: Optional[List[str]] = None) -> int:  # noqa: UP006
    parser = argparse.ArgumentParser(
        description="PositionTracker — daily allocation snapshot reader"
    )
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Alias for --check (tracker writes only via cycle_runner)")
    parser.add_argument("--data-dir", default="data", help="Path to data directory")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tracker = PositionTracker()
    try:
        report = _build_report(tracker, args.data_dir)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
