# LLM_FORBIDDEN
"""
SPA Strategy Tournament Runner v1.0
spa_core/backtesting/strategy_tournament_runner.py

Loads the mass tournament backtest results, selects the top-N strategies by
Sharpe ratio, and emits a well-structured data/strategy_tournament.json that
replaces the previous hand-crafted / empty file.

Also initialises data/shadow_paper_trading.json if it does not yet exist.

LLM_FORBIDDEN: no LLM calls. Pure deterministic logic.

Constraints
-----------
* stdlib only
* Atomic writes (tmp + shutil.move)
* Advisory / read-only — never imports execution/, feed_health/, or risk agents
"""
# LLM_FORBIDDEN

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"

VERSION = "v1.0"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, data: Any) -> None:
    """Atomically write *data* as JSON to *path* (tmp + shutil.move)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    shutil.move(tmp, str(path))


def _read_json(path: Path, default: Any = None) -> Any:
    """Read JSON file, returning *default* on any error."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


# ─────────────────────────────────────────────────────────────────────────────
# StrategyTournamentRunner
# ─────────────────────────────────────────────────────────────────────────────


class StrategyTournamentRunner:
    """
    Loads mass_tournament_results.json, picks top-N strategies, and writes
    data/strategy_tournament.json with a proper schema.

    Usage
    -----
    runner = StrategyTournamentRunner()
    result = runner.run(top_n=5)
    # → saves data/strategy_tournament.json
    # → ensures data/shadow_paper_trading.json exists
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DATA_DIR

    # ── Loaders ───────────────────────────────────────────────────────────────

    def _load_mass_results(self) -> Optional[Dict[str, Any]]:
        path = self._data_dir / "mass_tournament_results.json"
        data = _read_json(path)
        if not data or "leaderboard" not in data:
            _log.error("mass_tournament_results.json not found or malformed at %s", path)
            return None
        return data

    # ── Shadow paper trading init ─────────────────────────────────────────────

    def _ensure_shadow_trading_file(self, top_strategies: List[Dict]) -> Path:
        """Create data/shadow_paper_trading.json if it doesn't exist.

        Returns the path.
        """
        path = self._data_dir / "shadow_paper_trading.json"
        if path.exists():
            # File already exists; don't overwrite historical records
            return path

        initial: Dict[str, Any] = {
            "schema_version": "1.0",
            "description": (
                "Shadow paper trading results for top-N tournament strategies. "
                "Each day the cycle runner simulates what each top strategy "
                "would have earned using today's live APY data (advisory only, "
                "never modifies trades.json or equity_curve_daily.json)."
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active_strategies": [
                {
                    "rank":       s["rank"],
                    "id":         s["id"],
                    "sharpe":     s["sharpe"],
                    "annual_return_pct": s["annual_return_pct"],
                    "max_dd_pct": s["max_dd_pct"],
                    "allocation": s["allocation"],
                }
                for s in top_strategies
            ],
            "daily_results": [],  # appended by shadow_cycle hook in cycle_runner
        }
        _atomic_write_json(path, initial)
        _log.info("Initialised shadow_paper_trading.json at %s", path)
        return path

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self, top_n: int = 5) -> Dict[str, Any]:
        """
        Load mass tournament results, select top-N, emit strategy_tournament.json.

        Parameters
        ----------
        top_n:
            Number of top strategies to activate as shadow traders (default 5).

        Returns
        -------
        The emitted strategy_tournament dict.
        """
        mass = self._load_mass_results()
        if mass is None:
            raise RuntimeError(
                "Cannot run StrategyTournamentRunner: "
                "mass_tournament_results.json missing or invalid. "
                "Run MassTournament.run() first."
            )

        leaderboard: List[Dict] = mass.get("leaderboard", [])
        top_strategies = leaderboard[:top_n]

        # ── Build ranked_strategies list ──────────────────────────────────────
        ranked_strategies: List[Dict[str, Any]] = []
        for s in leaderboard:
            ranked_strategies.append({
                "rank":              s["rank"],
                "strategy_id":       s["id"].upper().replace("_", "-")[:8],
                "strategy_key":      s["id"],
                "name":              s.get("class", s["id"]),
                "sharpe":            round(s["sharpe"], 4),
                # OWNER DECISION 2026-06-27: Sharpe is a secondary/displayed metric.
                # Carry through the degenerate flag + display string from the mass
                # leaderboard so the ranking page shows "n/a (locked-vol)" instead of
                # a meaningless 451M Sharpe artifact. Ranking is by net return.
                "sharpe_degenerate": s.get("sharpe_degenerate"),
                "sharpe_display":    s.get("sharpe_display"),
                "rank_unknown":      s.get("rank_unknown", False),
                "net_annual_return_pct": s.get("net_annual_return_pct", s["annual_return_pct"]),
                "paper_apy":         round(s["annual_return_pct"], 4),
                "annual_return_pct": round(s["annual_return_pct"], 4),
                "max_drawdown":      round(s["max_dd_pct"] / 100.0, 6),
                "max_dd_pct":        round(s["max_dd_pct"], 4),
                "sortino":           round(s.get("sortino", 0.0), 4),
                "calmar":            round(s.get("calmar", 0.0), 4),
                "win_rate_pct":      round(s.get("win_rate_pct", 0.0), 4),
                "allocation":        s.get("allocation", {}),
                "is_shadow_active":  s["rank"] <= top_n,
                "days_active":       0,
                "method_used":       s.get("method_used", "unknown"),
            })

        # Top-N shadow strategies
        shadow_active = [s for s in ranked_strategies if s["is_shadow_active"]]

        tournament: Dict[str, Any] = {
            "schema_version":    "2.0",
            "generated_at":      datetime.now(timezone.utc).isoformat(),
            "version":           VERSION,
            "source":            "mass_tournament_results.json",
            # OWNER DECISION 2026-06-27: ranked by net-of-cost annual return,
            # Sharpe demoted to a secondary/displayed-and-flagged metric.
            "metric":            "net_annual_return_pct",
            "secondary_metric":  "sharpe_ratio",
            "simulation_period": mass.get("simulation_period", "2022-01-01 to 2025-12-31"),
            "initial_capital_usd": mass.get("initial_capital_usd", 100_000.0),
            "total_strategies":  mass.get("strategies_tested", len(leaderboard)),
            "strategies_skipped": mass.get("strategies_skipped", 0),
            "shadow_top_n":      top_n,
            "shadow_active_strategies": shadow_active,
            "ranked_strategies": ranked_strategies,
            "top_5": [
                {
                    "rank":              s["rank"],
                    "id":                s["id"],
                    "sharpe":            s["sharpe"],
                    "annual_return_pct": s["annual_return_pct"],
                    "max_dd_pct":        s["max_dd_pct"],
                    "allocation":        s["allocation"],
                }
                for s in leaderboard[:5]
            ],
            "bottom_5": [
                {
                    "rank":              s["rank"],
                    "id":                s["id"],
                    "sharpe":            s["sharpe"],
                    "annual_return_pct": s["annual_return_pct"],
                    "max_dd_pct":        s["max_dd_pct"],
                    "allocation":        s["allocation"],
                }
                for s in leaderboard[-5:]
            ],
            "llm_forbidden": True,
        }

        # Write strategy_tournament.json
        out_path = self._data_dir / "strategy_tournament.json"
        _atomic_write_json(out_path, tournament)
        _log.info(
            "strategy_tournament.json written: %d strategies, top-%d shadow active",
            len(ranked_strategies), top_n,
        )

        # Ensure shadow_paper_trading.json exists
        self._ensure_shadow_trading_file(top_strategies)

        return tournament


# ─────────────────────────────────────────────────────────────────────────────
# Shadow day simulation (used by cycle_runner hook)
# ─────────────────────────────────────────────────────────────────────────────


def run_shadow_day(
    apy_map: Dict[str, float],
    data_dir: Optional[Path] = None,
    date_str: Optional[str] = None,
    capital: float = 100_000.0,
) -> Dict[str, Any]:
    """
    Simulate today's performance for each top-N shadow strategy.

    Called from the cycle_runner after the main daily cycle completes.
    Uses the live ``apy_map`` produced by the adapter orchestrator.

    Returns
    -------
    Dict with today's shadow simulation results.
    Also appends the result to data/shadow_paper_trading.json (ring-buffer 365).

    Parameters
    ----------
    apy_map:
        Live APY data ``{protocol: apy_pct}`` as produced by ``_live_apy_map``.
        Values in percent (4.2 = 4.2 % annual).
    data_dir:
        Override for the data directory.
    date_str:
        ISO date string for the entry (default: today UTC).
    capital:
        Virtual capital per strategy (default: $100k).
    """
    ddir = Path(data_dir) if data_dir else _DATA_DIR
    shadow_path = ddir / "shadow_paper_trading.json"
    tournament_path = ddir / "strategy_tournament.json"

    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load active strategies from tournament file
    tournament = _read_json(tournament_path, {})
    active = tournament.get("shadow_active_strategies", [])
    if not active:
        _log.debug("run_shadow_day: no shadow-active strategies in tournament file")
        return {"date": date_str, "strategies": [], "best_strategy": None}

    # Simulate each strategy for one day
    day_results: List[Dict[str, Any]] = []
    for s in active:
        allocation = s.get("allocation", {})
        if not allocation:
            continue
        # Daily yield = sum(weight * apy_pct / 365)
        daily_yield_usd = 0.0
        expected_daily_apy_pct = 0.0
        weight_deployed = 0.0
        for proto, weight in allocation.items():
            apy_pct = apy_map.get(proto, 0.0)
            daily_yield_usd += capital * weight * (apy_pct / 100.0) / 365.0
            expected_daily_apy_pct += weight * apy_pct
            weight_deployed += weight

        annualised_pct = expected_daily_apy_pct  # already weighted

        day_results.append({
            "strategy_id":          s.get("id", "unknown"),
            "rank":                 s.get("rank", 0),
            "daily_yield_usd":      round(daily_yield_usd, 4),
            "annualised_apy_pct":   round(annualised_pct, 4),
            "weight_deployed":      round(weight_deployed, 4),
            "capital_usd":          capital,
        })

    # Determine best for today
    best = max(day_results, key=lambda x: x["daily_yield_usd"]) if day_results else None

    day_entry: Dict[str, Any] = {
        "date":           date_str,
        "strategies":     day_results,
        "best_strategy":  best["strategy_id"] if best else None,
        "best_yield_usd": best["daily_yield_usd"] if best else 0.0,
        "best_apy_pct":   best["annualised_apy_pct"] if best else 0.0,
        "apy_map_keys":   sorted(apy_map.keys()),
    }

    # Append to shadow_paper_trading.json (ring-buffer 365)
    shadow = _read_json(shadow_path, {})
    daily_records: List[Dict] = shadow.get("daily_results", [])
    # Avoid duplicate date entries
    daily_records = [r for r in daily_records if r.get("date") != date_str]
    daily_records.append(day_entry)
    # Ring-buffer: keep last 365
    if len(daily_records) > 365:
        daily_records = daily_records[-365:]
    shadow["daily_results"] = daily_records
    shadow["last_updated"] = datetime.now(timezone.utc).isoformat()
    shadow["total_days"] = len(daily_records)
    _atomic_write_json(shadow_path, shadow)

    _log.info(
        "shadow_day %s: %d strategies simulated, best=%s yield=%.4f USD",
        date_str,
        len(day_results),
        day_entry.get("best_strategy"),
        day_entry.get("best_yield_usd", 0.0),
    )
    return day_entry


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    """Run strategy tournament runner from command line."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="SPA Strategy Tournament Runner — builds strategy_tournament.json"
    )
    parser.add_argument(
        "--top-n", type=int, default=5,
        help="Number of top strategies to shadow-trade (default: 5)"
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Override data directory"
    )
    args = parser.parse_args()

    runner = StrategyTournamentRunner(
        data_dir=Path(args.data_dir) if args.data_dir else None
    )
    result = runner.run(top_n=args.top_n)

    print(f"\nStrategy Tournament written to data/strategy_tournament.json")
    print(f"Total strategies ranked: {result['total_strategies']}")
    print(f"Shadow-active (top {args.top_n}):")
    for s in result["shadow_active_strategies"]:
        print(
            f"  #{s['rank']:2d}  {s['strategy_key']:<40s}  "
            f"Sharpe={s['sharpe']:7.4f}  APY={s['annual_return_pct']:5.2f}%"
        )


if __name__ == "__main__":
    main()
