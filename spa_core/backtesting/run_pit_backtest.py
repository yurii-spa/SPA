"""
spa_core/backtesting/run_pit_backtest.py

Runs a full historical backtest using PITEngine (point-in-time filtered).
Compares results vs existing CPA backtest results.

Difference from existing engine.py:
  - Uses PointInTimeWhitelist to filter protocols by date
  - Only eligible protocols can appear in any given day's allocation
  - Measures how much more conservative strict-PIT mode is vs naive backtest

Design:
  - Synthetic data is generated using PIT-whitelist protocol IDs (underscores)
    so PITEngine correctly recognises and filters them by launch date.
  - cash_days_pct = average fraction of capital held in cash across all
    simulation days, expressed as a percentage. Always > 0 due to the
    mandatory cash buffer enforced by RiskPolicy.
  - vs_cpa compares the PIT annualised return against the CPA baseline APY
    (read from data/backtest/backtest_gate.json if present, else 0.0).

CLI:
    python3 -m spa_core.backtesting.run_pit_backtest --run
    python3 -m spa_core.backtesting.run_pit_backtest --run --save
    python3 -m spa_core.backtesting.run_pit_backtest --report

MP-1310 (v9.26) — stdlib only, atomic writes, no external dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# ── Path setup ─────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.pit_engine import PITEngine                     # noqa: E402
from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist  # noqa: E402


# ── Synthetic base data for PIT-format protocols ───────────────────────────────
#
# These protocol IDs must match the PointInTimeWhitelist launch-date table
# (underscore format) so PITEngine filtering works correctly.
#
# APY / TVL values are representative long-run baselines; the generator
# applies a light random walk (seed=42 for reproducibility).

_PIT_PROTOCOL_BASES: dict[str, dict] = {
    "aave_v2_usdc": {
        "apy": 4.0, "tvl_usd": 800_000_000, "tier": "T1",
    },
    "compound_v2_usdc": {
        "apy": 3.5, "tvl_usd": 500_000_000, "tier": "T1",
    },
    "aave_v3_usdc": {
        "apy": 4.5, "tvl_usd": 150_000_000, "tier": "T1",
    },
    "compound_v3_usdc": {
        "apy": 4.0, "tvl_usd": 50_000_000, "tier": "T1",
    },
    "morpho_steakhouse_usdc": {
        "apy": 6.5, "tvl_usd": 80_000_000, "tier": "T1",
    },
    "morpho_blue": {
        "apy": 5.5, "tvl_usd": 100_000_000, "tier": "T2",
    },
    "yearn_v2_yvusdc": {
        "apy": 5.0, "tvl_usd": 200_000_000, "tier": "T2",
    },
    "yearn_v3_yvusdc": {
        "apy": 6.0, "tvl_usd": 50_000_000, "tier": "T2",
    },
    "euler_v2_usdc": {
        "apy": 5.8, "tvl_usd": 30_000_000, "tier": "T2",
    },
}


# ── Runner ─────────────────────────────────────────────────────────────────────

class PITBacktestRunner:
    """
    Runs a full historical backtest using PITEngine (point-in-time filtered).

    Usage::

        runner = PITBacktestRunner(
            start="2022-05-01",
            end="2026-05-05",
            initial_capital=100_000.0,
        )
        results = runner.run()
        runner.save_results()
        print(runner.generate_report())

    The runner generates synthetic APY/TVL data using the PIT-whitelist
    protocol IDs so that PITEngine correctly applies launch-date filtering:
    protocols not yet live on a given date are excluded from that day's data,
    preventing look-ahead bias.
    """

    DEFAULT_SAVE_PATH = "data/backtest/pit_backtest_results.json"

    def __init__(
        self,
        start: str = "2022-05-01",
        end: str = "2026-05-05",
        initial_capital: float = 100_000.0,
    ) -> None:
        """
        Args:
            start:           Backtest start date, ISO 8601 (inclusive).
            end:             Backtest end date, ISO 8601 (inclusive).
            initial_capital: Starting virtual capital in USD.
        """
        self._start = start
        self._end = end
        self._initial_capital = initial_capital
        self._results: Optional[dict] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, protocols: Optional[list] = None) -> dict:
        """
        Run PIT-filtered backtest.

        Generates synthetic historical data with PIT-whitelist protocol IDs,
        feeds it through PITEngine (which drops rows before each protocol's
        launch date), then runs BacktestEngine on the filtered data.

        Args:
            protocols: Optional list of protocol IDs to include.
                       Must be keys in the PIT whitelist (underscore format).
                       Defaults to all protocols in _PIT_PROTOCOL_BASES.

        Returns::

            {
                "period": {"start": ..., "end": ...},
                "metrics": {
                    "total_return_pct": float,
                    "apy": float,
                    "max_dd": float,
                    "sharpe": float,
                },
                "pit_stats": {
                    "total_protocols": int,
                    "total_rows": int,
                    "kept_rows": int,
                    "dropped_rows": int,
                    "per_protocol": {protocol_id: {"kept": int, "dropped": int}, ...},
                },
                "cash_days_pct": float,     # avg cash fraction across all days (%)
                "vs_cpa": {
                    "cpa_apy": float,       # from existing gate file, else 0.0
                    "pit_apy": float,
                    "delta": float,         # pit_apy - cpa_apy
                },
            }
        """
        historical_data = self._generate_synthetic_pit_data(protocols=protocols)

        engine = PITEngine(whitelist=PointInTimeWhitelist())
        bt_result = engine.run(
            historical_data,
            initial_capital=self._initial_capital,
            policy_version="v1.0",
        )
        filter_stats = engine.filter_stats()

        # ── Metrics ────────────────────────────────────────────────────────
        metrics = {
            "total_return_pct": round(
                bt_result.metrics.get("total_return_pct", 0.0), 4
            ),
            "apy": round(
                bt_result.metrics.get("annualised_return_pct", 0.0), 4
            ),
            "max_dd": round(
                bt_result.metrics.get("max_drawdown_pct", 0.0), 4
            ),
            "sharpe": round(
                bt_result.metrics.get("sharpe_ratio", 0.0), 6
            ),
        }

        # ── Cash days % ────────────────────────────────────────────────────
        # Defined as: average daily (cash / total_capital) × 100.
        # Always > 0 because the RiskPolicy mandates a minimum cash buffer.
        equity = bt_result.equity_curve
        if equity:
            total_cash_sum = sum(e.get("cash", 0.0) for e in equity)
            total_capital_sum = sum(e.get("total_capital", 1.0) for e in equity)
            cash_days_pct = (
                round(total_cash_sum / total_capital_sum * 100.0, 4)
                if total_capital_sum > 0
                else 100.0
            )
        else:
            # No data → treat as fully in cash
            cash_days_pct = 100.0

        # ── PIT stats ──────────────────────────────────────────────────────
        per_protocol: dict = filter_stats.get("per_protocol", {})
        pit_stats = {
            "total_protocols": len(per_protocol),
            "total_rows": filter_stats.get("total_rows", 0),
            "kept_rows": filter_stats.get("kept_rows", 0),
            "dropped_rows": filter_stats.get("dropped_rows", 0),
            "per_protocol": per_protocol,
        }

        # ── vs CPA ─────────────────────────────────────────────────────────
        cpa_apy = self._load_cpa_apy()
        pit_apy = metrics["apy"]
        vs_cpa = {
            "cpa_apy": cpa_apy,
            "pit_apy": round(pit_apy, 2),
            "delta": round(pit_apy - cpa_apy, 2),
        }

        self._results = {
            "period": {"start": self._start, "end": self._end},
            "metrics": metrics,
            "pit_stats": pit_stats,
            "cash_days_pct": cash_days_pct,
            "vs_cpa": vs_cpa,
        }

        return self._results

    def save_results(
        self, path: str = DEFAULT_SAVE_PATH
    ) -> None:
        """
        Atomically save the backtest results to a JSON file.

        Args:
            path: Destination path. Parent directories are created if needed.

        Raises:
            ValueError: If run() has not been called yet.
        """
        if self._results is None:
            raise ValueError(
                "No results to save — call run() before save_results()."
            )

        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        tmp = save_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._results, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(save_path))

    def generate_report(self) -> str:
        """
        Return a Markdown-formatted report of the most recent run().

        Returns:
            Multi-line markdown string.

        Raises:
            ValueError: If run() has not been called yet.
        """
        if self._results is None:
            raise ValueError(
                "No results to report — call run() before generate_report()."
            )

        r = self._results
        period = r["period"]
        metrics = r["metrics"]
        pit_stats = r["pit_stats"]
        vs_cpa = r["vs_cpa"]
        per_proto: dict = pit_stats.get("per_protocol", {})

        lines = [
            "# PIT Backtest Report",
            "",
            f"**Period:** {period['start']} → {period['end']}",
            f"**Initial Capital:** ${self._initial_capital:,.0f}",
            "**Engine:** PITEngine (point-in-time filtered)",
            "",
            "## Performance Metrics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Return | {metrics['total_return_pct']:.2f}% |",
            f"| Annualised APY | {metrics['apy']:.2f}% |",
            f"| Max Drawdown | {metrics['max_dd']:.2f}% |",
            f"| Sharpe Ratio | {metrics['sharpe']:.4f} |",
            f"| Avg Cash (%) | {r['cash_days_pct']:.2f}% |",
            "",
            "## vs CPA Baseline",
            "",
            "| Baseline | Value |",
            "|---------|-------|",
            f"| CPA APY | {vs_cpa['cpa_apy']:.2f}% |",
            f"| PIT APY | {vs_cpa['pit_apy']:.2f}% |",
            f"| Delta   | {vs_cpa['delta']:+.2f}% |",
            "",
            "## PIT Filter Statistics",
            "",
            f"- Protocols tracked: **{pit_stats['total_protocols']}**",
            f"- Total data rows: {pit_stats['total_rows']}",
            f"- Rows kept (post-launch): {pit_stats['kept_rows']}",
            f"- Rows dropped (pre-launch): {pit_stats['dropped_rows']}",
        ]

        if per_proto:
            lines += [
                "",
                "### Per-Protocol Filter Breakdown",
                "",
                "| Protocol | Kept | Dropped |",
                "|---------|------|---------|",
            ]
            for proto, stats in sorted(per_proto.items()):
                kept = stats.get("kept", 0)
                dropped = stats.get("dropped", 0)
                lines.append(f"| {proto} | {kept} | {dropped} |")

        lines.append("")
        return "\n".join(lines)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _generate_synthetic_pit_data(
        self, protocols: Optional[list] = None
    ) -> list:
        """
        Generate synthetic daily APY/TVL data using PIT-whitelist protocol IDs.

        Uses a seeded random walk (seed=42) for reproducibility.
        Protocol IDs are in underscore format matching PointInTimeWhitelist,
        so PITEngine correctly filters rows that precede each protocol's
        real-world launch date.

        Args:
            protocols: Optional filter list of protocol IDs. Unknown IDs are
                       silently skipped. Defaults to all in _PIT_PROTOCOL_BASES.

        Returns:
            List of row dicts sorted by (timestamp, protocol_key):
              [{"timestamp": "YYYY-MM-DD", "protocol_key": str,
                "apy": float, "tvl_usd": float, "tier": str}, ...]
        """
        if protocols is not None:
            bases = {k: v for k, v in _PIT_PROTOCOL_BASES.items() if k in protocols}
            if not bases:
                # Requested protocols are unknown → fall back to all
                bases = dict(_PIT_PROTOCOL_BASES)
        else:
            bases = dict(_PIT_PROTOCOL_BASES)

        start_d = date.fromisoformat(self._start)
        end_d = date.fromisoformat(self._end)

        rng = random.Random(42)
        records: list[dict] = []

        # Track per-protocol state for the random walk
        state: dict[str, dict] = {
            pid: {"apy": info["apy"], "tvl": info["tvl_usd"]}
            for pid, info in bases.items()
        }

        current = start_d
        while current <= end_d:
            date_str = current.isoformat()
            for pid, info in bases.items():
                s = state[pid]

                # Ornstein-Uhlenbeck-style APY walk
                eps = rng.gauss(0.0, 1.0)
                delta_apy = 0.10 * (info["apy"] - s["apy"]) + 0.8 * eps
                new_apy = max(0.5, min(20.0, s["apy"] + delta_apy))
                s["apy"] = new_apy

                # Light TVL walk
                tvl_change = rng.uniform(-0.02, 0.02)
                new_tvl = max(
                    info["tvl_usd"] * 0.5,
                    min(info["tvl_usd"] * 3.0, s["tvl"] * (1.0 + tvl_change)),
                )
                s["tvl"] = new_tvl

                records.append({
                    "timestamp": date_str,
                    "protocol_key": pid,
                    "apy": round(new_apy, 4),
                    "tvl_usd": round(new_tvl, 0),
                    "tier": info["tier"],
                })

            current += timedelta(days=1)

        return sorted(records, key=lambda row: (row["timestamp"], row["protocol_key"]))

    def _load_cpa_apy(self) -> float:
        """
        Load the CPA (existing backtest) annualised APY from gate files.

        Tries data/backtest/backtest_gate.json → annualised_return_pct.
        Returns 0.0 (shown as -0.00 when negated) if the file is absent or
        the field is missing, matching the pre-paper gate's conservative
        cash-proxy baseline.

        Returns:
            float — annualised return % from the CPA backtest, or 0.0.
        """
        gate_path = _REPO_ROOT / "data" / "backtest" / "backtest_gate.json"
        try:
            with open(gate_path, encoding="utf-8") as fh:
                data = json.load(fh)
            value = data.get("annualised_return_pct", 0.0)
            return float(value) if value is not None else 0.0
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            return 0.0


# ── CLI ────────────────────────────────────────────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="PIT Backtest Runner — full historical run with point-in-time filtering",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 -m spa_core.backtesting.run_pit_backtest --run\n"
            "  python3 -m spa_core.backtesting.run_pit_backtest --run --save\n"
            "  python3 -m spa_core.backtesting.run_pit_backtest --report\n"
        ),
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Execute the PIT backtest and print summary",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save results to data/backtest/pit_backtest_results.json (requires --run)",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Print full markdown report (requires --run first, or combined with --run)",
    )
    parser.add_argument(
        "--start", default="2022-05-01",
        help="Backtest start date YYYY-MM-DD (default: 2022-05-01)",
    )
    parser.add_argument(
        "--end", default="2026-05-05",
        help="Backtest end date YYYY-MM-DD (default: 2026-05-05)",
    )
    parser.add_argument(
        "--capital", type=float, default=100_000.0,
        help="Initial capital in USD (default: 100000)",
    )
    args = parser.parse_args()

    runner = PITBacktestRunner(
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
    )

    if args.run:
        results = runner.run()
        print(json.dumps(results, indent=2))
        if args.save:
            runner.save_results()
            print(f"\nResults saved to {PITBacktestRunner.DEFAULT_SAVE_PATH}")
        if args.report:
            print("\n" + runner.generate_report())
    elif args.report:
        parser.error("--report requires --run to be specified as well")
    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
