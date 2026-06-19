"""
SPA Backtesting — Point-in-Time Engine
=======================================
MP-1300 (v9.16)

Wraps BacktestEngine with PointInTimeWhitelist pre-filtering.
Eliminates look-ahead bias by dropping any data row whose date
precedes the protocol's real-world launch date.

Design principle: filter first, then delegate — 100% API compatibility
with BacktestEngine.run() so existing callers can drop-in replace.

stdlib only. No external dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure spa_core package root is importable regardless of cwd
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.engine import BacktestEngine, BacktestResult  # noqa: E402
from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist  # noqa: E402
from spa_core.risk.policy import RiskConfig  # noqa: E402


class PITEngine:
    """
    Point-in-Time BacktestEngine.

    Applies PointInTimeWhitelist filtering before delegating to
    BacktestEngine, ensuring no protocol data is used before that
    protocol actually existed on-chain.

    Usage::

        from spa_core.backtesting.pit_engine import PITEngine

        engine = PITEngine()
        result = engine.run(historical_data)
        print(result.metrics)
        print(engine.filter_stats())

    To use custom protocol IDs (matching the historical_data format)::

        from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist

        wl = PointInTimeWhitelist(launch_dates={
            "aave-v3-usdc-ethereum": "2022-03-16",
            "compound-v3-usdc-ethereum": "2022-08-26",
        })
        engine = PITEngine(whitelist=wl)
        result = engine.run(historical_data)
    """

    def __init__(
        self,
        config: RiskConfig | None = None,
        whitelist: PointInTimeWhitelist | None = None,
    ) -> None:
        """
        Args:
            config:    RiskConfig passed to the underlying BacktestEngine.
                       None → production defaults.
            whitelist: PointInTimeWhitelist to apply during filtering.
                       None → built-in default launch-date table.
        """
        self._engine = BacktestEngine(config=config)
        self._whitelist = (
            whitelist if whitelist is not None else PointInTimeWhitelist()
        )
        self._last_filter_stats: dict = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(
        self,
        historical_data: list[dict],
        initial_capital: float = 100_000.0,
        policy_version: str = "v1.0",
    ) -> BacktestResult:
        """
        Run the backtest with point-in-time filtering applied.

        Pre-launch data rows are silently excluded before the engine sees them.
        Inspect filter_stats() after the run to see per-protocol drop counts.

        Args:
            historical_data: List of snapshot dicts:
                [{timestamp, protocol_key, apy, tvl_usd, tier}, ...]
                Timestamps should be ISO date strings (YYYY-MM-DD).
                Rows with unknown protocol_key are also dropped.
            initial_capital: Starting virtual capital in USD (default $100,000).
            policy_version:  Label for the policy version (output metadata).

        Returns:
            BacktestResult — identical structure to BacktestEngine.run().
        """
        filtered, stats = self._apply_filter(historical_data)
        self._last_filter_stats = stats
        return self._engine.run(filtered, initial_capital, policy_version)

    def filter_stats(self) -> dict:
        """
        Returns row-filtering statistics from the most recent run() call.

        Returns empty dict if run() has not been called yet.

        Returns::

            {
                "total_rows": 1800,
                "kept_rows": 1200,
                "dropped_rows": 600,
                "per_protocol": {
                    "aave_v2_usdc": {"kept": 200, "dropped": 0},
                    "morpho_blue":  {"kept": 90,  "dropped": 110},
                }
            }
        """
        return dict(self._last_filter_stats)

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def config(self) -> RiskConfig:
        """The RiskConfig used by the underlying BacktestEngine."""
        return self._engine.config

    @property
    def whitelist(self) -> PointInTimeWhitelist:
        """The PointInTimeWhitelist used for pre-filtering."""
        return self._whitelist

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _apply_filter(
        self, historical_data: list[dict]
    ) -> tuple[list[dict], dict]:
        """
        Separate eligible rows from ineligible rows.

        Returns:
            (filtered_rows, stats_dict)
        """
        kept: list[dict] = []
        per_protocol: dict[str, dict] = {}

        for row in historical_data:
            key = row.get("protocol_key", "")
            # Accept both "timestamp" and "date" field names for flexibility
            ts_raw = row.get("timestamp") or row.get("date") or ""
            ts = ts_raw[:10]  # normalise to YYYY-MM-DD

            eligible = self._whitelist.is_eligible(key, ts)

            if key not in per_protocol:
                per_protocol[key] = {"kept": 0, "dropped": 0}

            if eligible:
                kept.append(row)
                per_protocol[key]["kept"] += 1
            else:
                per_protocol[key]["dropped"] += 1

        total = len(historical_data)
        kept_count = len(kept)

        stats: dict = {
            "total_rows": total,
            "kept_rows": kept_count,
            "dropped_rows": total - kept_count,
            "per_protocol": per_protocol,
        }
        return kept, stats
