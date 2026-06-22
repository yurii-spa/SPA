# LLM_FORBIDDEN
"""
SPA Tournament Engine v1.0
spa_core/tournament/tournament_engine.py

Daily entry point for the strategy tournament lifecycle:
  1. Update paper-tracking for top-N shadow strategies
  2. Check promotion criteria (paper → live advisory)
  3. Re-rank strategies if new backtest data appears
  4. Write updated data/strategy_tournament.json
  5. Send Telegram alerts on rank changes / promotions

IS_ADVISORY = True: all promotions are advisory until manual go-live confirmation.

LLM_FORBIDDEN: no AI calls. Pure deterministic logic.
Constraints
-----------
* stdlib only
* Atomic writes (tmp + shutil.move)
* Never imports execution/, feed_health/, or risk agents
* Keychain access via subprocess; graceful skip if unavailable
"""
# LLM_FORBIDDEN

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"

IS_ADVISORY = True  # promotions are advisory; never touches execution domain

VERSION = "1.0"

# ─────────────────────────────────────────────────────────────────────────────
# Promotion criteria
# ─────────────────────────────────────────────────────────────────────────────

PROMOTION_CRITERIA: Dict[str, Any] = {
    "min_sharpe":       1.5,    # Sharpe ≥ 1.5
    "min_days_paper":   7,      # at least 7 paper days
    "max_drawdown":     -0.15,  # drawdown not worse than -15%
    "min_apy_pct":      3.0,    # at least 3% APY in paper phase
}

PHASES = ["backtest", "paper_30d", "live"]

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


def _keychain_secret(service: str) -> str:
    """
    Read a secret from macOS Keychain via security(1).
    Returns empty string and logs a debug message on any failure.
    """
    try:
        value = subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
        return value
    except Exception as exc:
        _log.debug("Keychain lookup failed for %s: %s", service, exc)
        return ""


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# TournamentEngine
# ─────────────────────────────────────────────────────────────────────────────


class TournamentEngine:
    """
    Daily tournament lifecycle manager.

    Phases
    ------
    backtest   → historical simulation (mass_tournament_results.json)
    paper_30d  → live shadow paper trading (shadow_paper_trading.json)
    live       → advisory promotion flag (IS_ADVISORY = True; never auto-executes)

    Usage
    -----
    engine = TournamentEngine()
    summary = engine.run_daily()
    """

    PHASES = PHASES
    PROMOTION_CRITERIA = PROMOTION_CRITERIA

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self._tournament_path = self._data_dir / "strategy_tournament.json"
        self._shadow_path = self._data_dir / "shadow_paper_trading.json"
        self._engine_state_path = self._data_dir / "tournament_engine_state.json"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run_daily(self) -> Dict[str, Any]:
        """
        Main daily entry point — called by launchd agent every day at 09:00 UTC.

        Steps
        -----
        1. Load current tournament + shadow paper trading state
        2. Run one shadow day simulation (uses cached APY if live feed unavailable)
        3. Check promotion criteria for all paper-phase strategies
        4. Detect rank changes in top-3
        5. Write updated state files atomically
        6. Send Telegram alerts for promotions and rank changes
        7. Return summary dict

        Returns
        -------
        dict with keys: date, strategies_updated, promotions, rank_changes,
        telegram_sent, errors
        """
        _log.info("TournamentEngine.run_daily() starting — %s", _today_utc())
        date_str = _today_utc()
        errors: List[str] = []
        promotions: List[Dict[str, Any]] = []
        rank_changes: List[Dict[str, Any]] = []
        telegram_sent = False

        # 1. Load state
        tournament = _read_json(self._tournament_path, {})
        shadow = _read_json(self._shadow_path, {})

        if not tournament:
            msg = "strategy_tournament.json missing — run StrategyTournamentRunner first"
            _log.warning(msg)
            errors.append(msg)

        # 2. Run shadow day (best-effort; errors are logged, not fatal)
        shadow_result: Dict[str, Any] = {}
        try:
            shadow_result = self.update_shadow_day(date_str)
        except Exception as exc:
            _log.error("update_shadow_day failed: %s", exc)
            errors.append(f"update_shadow_day: {exc}")

        # 3. Check promotions
        try:
            promotions = self.check_promotions()
        except Exception as exc:
            _log.error("check_promotions failed: %s", exc)
            errors.append(f"check_promotions: {exc}")

        # 4. Detect rank changes in top-3
        try:
            rank_changes = self._detect_rank_changes(tournament)
        except Exception as exc:
            _log.error("_detect_rank_changes failed: %s", exc)
            errors.append(f"rank_changes: {exc}")

        # 5. Persist engine state
        try:
            self._save_engine_state(date_str, promotions, rank_changes, shadow_result)
        except Exception as exc:
            _log.error("_save_engine_state failed: %s", exc)
            errors.append(f"save_state: {exc}")

        # 6. Telegram alerts
        try:
            telegram_sent = self._send_alerts(date_str, promotions, rank_changes, tournament)
        except Exception as exc:
            _log.error("_send_alerts failed: %s", exc)
            errors.append(f"telegram: {exc}")

        # Reload shadow after update_shadow_day wrote it
        shadow_after = _read_json(self._shadow_path, {})
        strategies_updated = len(shadow_after.get("active_strategies", []))

        summary: Dict[str, Any] = {
            "date":               date_str,
            "strategies_updated": strategies_updated,
            "promotions":         promotions,
            "rank_changes":       rank_changes,
            "telegram_sent":      telegram_sent,
            "shadow_best":        shadow_result.get("best_strategy"),
            "shadow_best_apy":    shadow_result.get("best_apy_pct", 0.0),
            "errors":             errors,
            "is_advisory":        IS_ADVISORY,
        }

        _log.info(
            "run_daily done: %d promotions, %d rank_changes, errors=%d",
            len(promotions), len(rank_changes), len(errors),
        )
        return summary

    def check_promotions(self) -> List[Dict[str, Any]]:
        """
        Examine all paper-phase shadow strategies and return those that meet
        the PROMOTION_CRITERIA (paper → live advisory).

        Returns
        -------
        List of dicts describing each strategy ready for promotion:
          {strategy_id, rank, sharpe, paper_apy_pct, max_drawdown_pct,
           days_paper, criteria_met, is_advisory}
        """
        shadow = _read_json(self._shadow_path, {})
        tournament = _read_json(self._tournament_path, {})

        daily_results: List[Dict] = shadow.get("daily_results", [])
        active: List[Dict] = shadow.get("active_strategies", [])
        ranked: List[Dict] = tournament.get("shadow_active_strategies", [])

        criteria = PROMOTION_CRITERIA
        promotions: List[Dict[str, Any]] = []

        for strategy in active:
            sid = strategy.get("id", "unknown")
            rank = strategy.get("rank", 999)

            # Find matching ranked entry for Sharpe
            ranked_entry = next(
                (r for r in ranked if r.get("strategy_key") == sid or r.get("id") == sid),
                {}
            )
            sharpe = ranked_entry.get("sharpe", strategy.get("sharpe", 0.0))

            # Collect paper days for this strategy
            strategy_days = [
                dr for dr in daily_results
                if any(
                    s.get("strategy_id") == sid
                    for s in dr.get("strategies", [])
                )
            ]
            days_paper = len(strategy_days)

            # Compute paper APY from daily yields
            paper_apy_pct = self._compute_paper_apy(sid, daily_results)

            # Compute max drawdown from daily yields
            max_dd = self._compute_max_drawdown(sid, daily_results)

            # Check each criterion
            sharpe_ok  = sharpe >= criteria["min_sharpe"]
            days_ok    = days_paper >= criteria["min_days_paper"]
            apy_ok     = paper_apy_pct >= criteria["min_apy_pct"]
            dd_ok      = max_dd >= criteria["max_drawdown"]  # max_drawdown is negative e.g. -0.15

            all_ok = sharpe_ok and days_ok and apy_ok and dd_ok

            if all_ok:
                promotions.append({
                    "strategy_id":      sid,
                    "rank":             rank,
                    "sharpe":           sharpe,
                    "paper_apy_pct":    paper_apy_pct,
                    "max_drawdown_pct": max_dd,
                    "days_paper":       days_paper,
                    "criteria_met": {
                        "min_sharpe":     sharpe_ok,
                        "min_days_paper": days_ok,
                        "min_apy_pct":    apy_ok,
                        "max_drawdown":   dd_ok,
                    },
                    "phase_from": "paper_30d",
                    "phase_to":   "live",
                    "is_advisory": IS_ADVISORY,
                })

        if promotions:
            _log.info(
                "check_promotions: %d strategies ready for advisory promotion",
                len(promotions),
            )
        return promotions

    def update_shadow_day(
        self,
        date: Optional[str] = None,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Run one day of shadow simulation for all paper-phase strategies.

        If *apy_map* is not provided, the engine loads a cached APY snapshot
        from data/paper_trading_status.json (populated by cycle_runner).

        Parameters
        ----------
        date:
            ISO date string (default: today UTC).
        apy_map:
            Live APY data ``{protocol_key: apy_pct}``.

        Returns
        -------
        Day entry dict with keys:
          date, strategies (list), best_strategy, best_yield_usd, best_apy_pct
        """
        date_str = date or _today_utc()

        if apy_map is None:
            apy_map = self._load_cached_apy()

        tournament = _read_json(self._tournament_path, {})
        active: List[Dict] = tournament.get("shadow_active_strategies", [])
        shadow = _read_json(self._shadow_path, {})

        capital = 100_000.0
        day_results: List[Dict[str, Any]] = []

        for s in active:
            allocation: Dict[str, float] = s.get("allocation", {})
            if not allocation:
                continue

            strategy_id = s.get("strategy_key") or s.get("id", "unknown")
            daily_yield_usd = 0.0
            expected_apy_pct = 0.0
            weight_deployed = 0.0

            for proto, weight in allocation.items():
                apy_pct = apy_map.get(proto, 0.0)
                daily_yield_usd += capital * weight * (apy_pct / 100.0) / 365.0
                expected_apy_pct += weight * apy_pct
                weight_deployed += weight

            day_results.append({
                "strategy_id":        strategy_id,
                "rank":               s.get("rank", 0),
                "daily_yield_usd":    round(daily_yield_usd, 4),
                "annualised_apy_pct": round(expected_apy_pct, 4),
                "weight_deployed":    round(weight_deployed, 4),
                "capital_usd":        capital,
            })

        best = (
            max(day_results, key=lambda x: x["daily_yield_usd"])
            if day_results else None
        )

        day_entry: Dict[str, Any] = {
            "date":           date_str,
            "strategies":     day_results,
            "best_strategy":  best["strategy_id"] if best else None,
            "best_yield_usd": best["daily_yield_usd"] if best else 0.0,
            "best_apy_pct":   best["annualised_apy_pct"] if best else 0.0,
            "apy_map_keys":   sorted(apy_map.keys()),
        }

        # Append to shadow_paper_trading.json (ring-buffer 365)
        daily_records: List[Dict] = shadow.get("daily_results", [])
        daily_records = [r for r in daily_records if r.get("date") != date_str]
        daily_records.append(day_entry)
        if len(daily_records) > 365:
            daily_records = daily_records[-365:]

        shadow["daily_results"] = daily_records
        shadow["last_updated"] = _now_iso()
        shadow["total_days"] = len(daily_records)

        # Increment days_active in tournament file
        self._increment_days_active(date_str)

        _atomic_write_json(self._shadow_path, shadow)
        _log.info(
            "update_shadow_day %s: %d strategies, best=%s",
            date_str, len(day_results), day_entry.get("best_strategy"),
        )
        return day_entry

    def get_tournament_status(self) -> Dict[str, Any]:
        """
        Return a unified status dict for API / dashboard consumption.

        Schema
        ------
        {
          schema_version,
          engine_version,
          generated_at,
          is_advisory,
          phases,
          promotion_criteria,
          top_5,
          promotions_pending,
          shadow_days_tracked,
          last_shadow_date,
          engine_state
        }
        """
        tournament = _read_json(self._tournament_path, {})
        shadow = _read_json(self._shadow_path, {})
        engine_state = _read_json(self._engine_state_path, {})

        top_5: List[Dict] = tournament.get("shadow_active_strategies", [])[:5]
        daily_results: List[Dict] = shadow.get("daily_results", [])
        last_shadow_date = (
            daily_results[-1]["date"] if daily_results else None
        )

        promotions_pending: List[Dict] = []
        try:
            promotions_pending = self.check_promotions()
        except Exception as exc:
            _log.warning("get_tournament_status: check_promotions error: %s", exc)

        return {
            "schema_version":      "1.0",
            "engine_version":      VERSION,
            "generated_at":        _now_iso(),
            "is_advisory":         IS_ADVISORY,
            "phases":              PHASES,
            "promotion_criteria":  PROMOTION_CRITERIA,
            "top_5":               top_5,
            "promotions_pending":  promotions_pending,
            "shadow_days_tracked": len(daily_results),
            "last_shadow_date":    last_shadow_date,
            "total_strategies":    tournament.get("total_strategies", 0),
            "engine_state":        engine_state,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _load_cached_apy(self) -> Dict[str, float]:
        """
        Load the most recent APY snapshot from paper_trading_status.json or
        current_positions.json. Returns empty dict if unavailable.
        """
        # Try paper_trading_status first
        status = _read_json(self._data_dir / "paper_trading_status.json", {})
        apy_map: Dict[str, float] = {}

        # Extract APY from current_positions
        positions_path = self._data_dir / "current_positions.json"
        positions_data = _read_json(positions_path, {})
        positions: List[Dict] = (
            positions_data.get("positions", [])
            if isinstance(positions_data, dict)
            else (positions_data if isinstance(positions_data, list) else [])
        )
        for pos in positions:
            proto = pos.get("protocol_key") or pos.get("protocol", "")
            apy = pos.get("current_apy") or pos.get("apy_pct", 0.0)
            if proto and apy:
                apy_map[proto] = float(apy)

        if not apy_map:
            _log.debug("_load_cached_apy: no APY data found, using empty map")

        return apy_map

    def _compute_paper_apy(
        self,
        strategy_id: str,
        daily_results: List[Dict],
    ) -> float:
        """
        Compute annualised APY from shadow daily results for a given strategy.
        Returns 0.0 if no data.
        """
        apy_values: List[float] = []
        for dr in daily_results:
            for s in dr.get("strategies", []):
                if s.get("strategy_id") == strategy_id:
                    apy = s.get("annualised_apy_pct", 0.0)
                    if apy:
                        apy_values.append(apy)
        if not apy_values:
            return 0.0
        return round(sum(apy_values) / len(apy_values), 4)

    def _compute_max_drawdown(
        self,
        strategy_id: str,
        daily_results: List[Dict],
    ) -> float:
        """
        Compute peak-to-trough drawdown fraction from cumulative daily yields.
        Returns 0.0 if insufficient data.
        """
        capital = 100_000.0
        equity = capital
        peak = capital
        max_dd = 0.0

        for dr in daily_results:
            for s in dr.get("strategies", []):
                if s.get("strategy_id") == strategy_id:
                    daily_usd = s.get("daily_yield_usd", 0.0)
                    equity += daily_usd
                    if equity > peak:
                        peak = equity
                    if peak > 0:
                        dd = (equity - peak) / peak
                        if dd < max_dd:
                            max_dd = dd

        return round(max_dd, 6)

    def _detect_rank_changes(
        self,
        tournament: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Compare current top-3 ranks against the last saved engine state.
        Returns list of rank-change events.
        """
        engine_state = _read_json(self._engine_state_path, {})
        prev_top3: List[Dict] = engine_state.get("last_top3", [])

        current_ranked: List[Dict] = tournament.get("shadow_active_strategies", [])
        current_top3 = [
            {"rank": s.get("rank"), "strategy_id": s.get("strategy_key") or s.get("id")}
            for s in current_ranked[:3]
        ]

        changes: List[Dict[str, Any]] = []
        prev_map = {e["strategy_id"]: e["rank"] for e in prev_top3}

        for entry in current_top3:
            sid = entry["strategy_id"]
            new_rank = entry["rank"]
            old_rank = prev_map.get(sid)
            if old_rank is not None and old_rank != new_rank:
                changes.append({
                    "strategy_id": sid,
                    "old_rank":    old_rank,
                    "new_rank":    new_rank,
                })
            elif old_rank is None and new_rank <= 3:
                # Entered top-3
                changes.append({
                    "strategy_id": sid,
                    "old_rank":    None,
                    "new_rank":    new_rank,
                    "event":       "entered_top3",
                })

        return changes

    def _save_engine_state(
        self,
        date_str: str,
        promotions: List[Dict],
        rank_changes: List[Dict],
        shadow_result: Dict,
    ) -> None:
        """Persist engine run state for next-day comparison."""
        tournament = _read_json(self._tournament_path, {})
        current_ranked: List[Dict] = tournament.get("shadow_active_strategies", [])
        top3 = [
            {"rank": s.get("rank"), "strategy_id": s.get("strategy_key") or s.get("id")}
            for s in current_ranked[:3]
        ]

        existing = _read_json(self._engine_state_path, {})
        run_history: List[Dict] = existing.get("run_history", [])
        run_history.append({
            "date":        date_str,
            "promotions":  len(promotions),
            "rank_changes": len(rank_changes),
            "best_strategy": shadow_result.get("best_strategy"),
        })
        # Ring-buffer: last 365 runs
        if len(run_history) > 365:
            run_history = run_history[-365:]

        state: Dict[str, Any] = {
            "schema_version": "1.0",
            "last_run":       date_str,
            "last_top3":      top3,
            "run_history":    run_history,
            "total_promotions": existing.get("total_promotions", 0) + len(promotions),
            "updated_at":     _now_iso(),
        }
        _atomic_write_json(self._engine_state_path, state)

    def _increment_days_active(self, date_str: str) -> None:
        """
        Increment days_active counter for each strategy in strategy_tournament.json.
        Skips if the date was already counted (idempotent).
        """
        tournament = _read_json(self._tournament_path)
        if not tournament:
            return

        # Track which dates we've already incremented
        counted_dates: List[str] = tournament.get("_days_counted", [])
        if date_str in counted_dates:
            _log.debug("_increment_days_active: date %s already counted", date_str)
            return

        for section in ("shadow_active_strategies", "ranked_strategies"):
            for s in tournament.get(section, []):
                s["days_active"] = s.get("days_active", 0) + 1

        counted_dates.append(date_str)
        # Keep only last 400 dates to prevent unbounded growth
        if len(counted_dates) > 400:
            counted_dates = counted_dates[-400:]
        tournament["_days_counted"] = counted_dates
        tournament["last_engine_update"] = _now_iso()

        _atomic_write_json(self._tournament_path, tournament)

    def _send_alerts(
        self,
        date_str: str,
        promotions: List[Dict],
        rank_changes: List[Dict],
        tournament: Dict,
    ) -> bool:
        """
        Send Telegram alerts. Returns True if at least one message was sent.
        Graceful degradation: returns False (not raises) if Telegram unavailable.
        """
        try:
            from spa_core.tournament.tournament_telegram import TournamentTelegram
        except ImportError as exc:
            _log.warning("TournamentTelegram import failed: %s", exc)
            return False

        tg = TournamentTelegram()
        sent = False

        # Daily standings (always send)
        top5 = tournament.get("shadow_active_strategies", [])[:5]
        if top5:
            shadow = _read_json(self._shadow_path, {})
            sent = tg.send_daily_standings(top5, shadow, date_str) or sent

        # Promotion alerts
        for promo in promotions:
            ok = tg.send_promotion_alert(
                promo["strategy_id"],
                promo["phase_from"],
                promo["phase_to"],
            )
            sent = sent or ok

        # Rank-change alerts
        for change in rank_changes:
            old = change.get("old_rank")
            new = change.get("new_rank")
            if old is not None:
                ok = tg.send_position_change(
                    change["strategy_id"],
                    old,
                    new,
                )
                sent = sent or ok

        return sent


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    """Run TournamentEngine daily cycle from command line / launchd."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="SPA Tournament Engine — daily cycle runner"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Print tournament status and exit (no side effects)"
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Override data directory"
    )
    args = parser.parse_args()

    engine = TournamentEngine(
        data_dir=Path(args.data_dir) if args.data_dir else None
    )

    if args.status:
        status = engine.get_tournament_status()
        print(json.dumps(status, indent=2, default=str))
        return

    summary = engine.run_daily()

    print("\n=== Tournament Engine Daily Summary ===")
    print(f"Date:                {summary['date']}")
    print(f"Strategies updated:  {summary['strategies_updated']}")
    print(f"Promotions:          {len(summary['promotions'])}")
    print(f"Rank changes:        {len(summary['rank_changes'])}")
    print(f"Best shadow:         {summary.get('shadow_best')} "
          f"({summary.get('shadow_best_apy', 0):.2f}% APY)")
    print(f"Telegram sent:       {summary['telegram_sent']}")
    if summary["errors"]:
        print(f"Errors ({len(summary['errors'])}):")
        for e in summary["errors"]:
            print(f"  - {e}")
    sys.exit(0)


if __name__ == "__main__":
    main()
