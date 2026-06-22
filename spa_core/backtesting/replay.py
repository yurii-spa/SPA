"""
SPA Backtesting — Historical Replay Engine (v0.9)
=================================================

Replays historical positions from pnl_history.json at any speed,
animating the equity curve day-by-day with full metric calculation.

Design:
  - Primary source: data/pnl_history.json (real paper-trading history)
  - Synthetic fallback: 90-day Ornstein-Uhlenbeck simulation via data_loader
  - Each replay step returns a complete portfolio snapshot for that day
  - Summary metrics: Sharpe, MaxDD, WinRate, annualised return, best/worst day

Usage:
    from backtesting.replay import ReplayEngine

    engine = ReplayEngine()
    frame = engine.replay_step(0)      # day 0 snapshot
    all_frames = engine.full_replay()  # all days
    summary = engine.replay_summary()  # aggregate metrics
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# Ensure spa_core is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.metrics import (
    sharpe_ratio,
    max_drawdown,
    total_return_pct,
    annualised_return_pct,
)

# ── Constants ─────────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_PNL_HISTORY_PATH = _DATA_DIR / "pnl_history.json"

_INITIAL_CAPITAL = 100_000.0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_pnl_history(data_dir: Optional[Path] = None) -> list[dict]:
    """
    Load pnl_history.json from the data directory.

    Each record has keys:
        timestamp, total_capital_usd, deployed_capital_usd,
        cash_usd, total_pnl_usd, total_pnl_pct, current_apy, trade_count

    Returns the list sorted by timestamp ascending.
    Raises FileNotFoundError / ValueError if file is missing or empty.
    """
    path = (data_dir or _DATA_DIR) / "pnl_history.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) == 0:
        raise ValueError("pnl_history.json is empty or malformed")
    return sorted(raw, key=lambda r: r.get("timestamp", ""))


def _synthetic_equity_curve(days: int = 90, seed: int = 42) -> list[dict]:
    """
    Build a synthetic equity curve using the OU BacktestEngine.

    Returns a list of records matching the pnl_history.json schema
    so ReplayEngine can treat both sources identically.
    """
    from backtesting.data_loader import generate_synthetic_history
    from backtesting.engine import BacktestEngine

    history = generate_synthetic_history(days=days, seed=seed)
    engine = BacktestEngine()
    result = engine.run(history, initial_capital=_INITIAL_CAPITAL)

    records = []
    for snap in result.equity_curve:
        capital = snap["total_capital"]
        initial = result.initial_capital
        pnl_usd = capital - initial
        pnl_pct = pnl_usd / initial * 100 if initial > 0 else 0.0
        records.append({
            "timestamp": snap["date"],
            "total_capital_usd": capital,
            "deployed_capital_usd": snap.get("deployed", 0.0),
            "cash_usd": snap.get("cash", 0.0),
            "total_pnl_usd": round(pnl_usd, 2),
            "total_pnl_pct": round(pnl_pct, 4),
            "current_apy": None,
            "trade_count": snap.get("open_positions", 0),
        })
    return records


def _positions_snapshot(record: dict, day: int) -> list[dict]:
    """
    Reconstruct a synthetic positions snapshot from an aggregate record.

    Since pnl_history.json stores only portfolio-level data (no per-position
    breakdown), we synthesise a plausible position list that sums to the
    deployed_capital value.  The snapshot is labelled as 'estimated'.
    """
    deployed = record.get("deployed_capital_usd", 0.0) or 0.0
    capital = record.get("total_capital_usd", _INITIAL_CAPITAL) or _INITIAL_CAPITAL

    if deployed <= 0:
        return []

    # Divide deployed capital across 2–3 synthetic positions
    n = min(3, max(1, int(deployed // 25_000) + 1))
    chunk = deployed / n
    apy = record.get("current_apy") or 5.0

    positions = []
    protocols = [
        ("aave-v3-usdc-ethereum", "T1"),
        ("morpho-usdc-ethereum", "T1"),
        ("yearn-v3-usdc-ethereum", "T2"),
    ]
    for i in range(n):
        proto_key, tier = protocols[i % len(protocols)]
        positions.append({
            "protocol_key": proto_key,
            "tier": tier,
            "amount_usd": round(chunk, 2),
            "current_apy": round(apy * (0.9 + 0.1 * i), 4),
            "pct_of_portfolio": round(chunk / capital * 100, 2) if capital > 0 else 0.0,
            "estimated": True,
        })
    return positions


# ── ReplayEngine ──────────────────────────────────────────────────────────────

class ReplayEngine:
    """
    Replay historical portfolio performance day-by-day.

    Data sources (in priority order):
      1. data/pnl_history.json — real paper-trading history
      2. Synthetic 90-day OU simulation (fallback)

    Methods:
        replay_step(day)  → portfolio snapshot for that day
        full_replay()     → all days as a list
        replay_summary()  → aggregate metrics dict
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        synthetic_days: int = 90,
        synthetic_seed: int = 42,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self._synthetic_days = synthetic_days
        self._synthetic_seed = synthetic_seed
        self._records: list[dict] = []
        self._source: str = "unknown"
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load pnl_history.json; fall back to synthetic if unavailable."""
        try:
            self._records = _load_pnl_history(self._data_dir)
            self._source = "pnl_history"
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            self._records = _synthetic_equity_curve(
                days=self._synthetic_days,
                seed=self._synthetic_seed,
            )
            self._source = "synthetic"

    @property
    def source(self) -> str:
        """Return the data source: 'pnl_history' or 'synthetic'."""
        return self._source

    @property
    def total_days(self) -> int:
        """Total number of days in the replay."""
        return len(self._records)

    # ── Core API ──────────────────────────────────────────────────────────────

    def replay_step(self, day: int) -> dict:
        """
        Return the portfolio state at a specific day index.

        Args:
            day: Zero-based day index (0 = first recorded day).

        Returns:
            Dict with keys:
                day, date, portfolio_value, daily_pnl, cumulative_pnl_pct,
                positions_snapshot, deployed_usd, cash_usd, apy, trade_count

        Raises:
            IndexError: if day is out of range.
        """
        if not self._records:
            raise IndexError("No replay data available")
        if day < 0 or day >= len(self._records):
            raise IndexError(
                f"Day {day} out of range [0, {len(self._records) - 1}]"
            )

        rec = self._records[day]
        capital = rec.get("total_capital_usd", _INITIAL_CAPITAL) or _INITIAL_CAPITAL
        initial = self._records[0].get("total_capital_usd", _INITIAL_CAPITAL) or _INITIAL_CAPITAL

        # Daily PnL vs prior day
        if day > 0:
            prior_capital = (
                self._records[day - 1].get("total_capital_usd", initial) or initial
            )
            daily_pnl = capital - prior_capital
        else:
            daily_pnl = 0.0

        # Cumulative PnL %
        cum_pnl_pct = (capital - initial) / initial * 100 if initial > 0 else 0.0

        # Timestamp — normalise to YYYY-MM-DD
        raw_ts = rec.get("timestamp", "")
        date_str = str(raw_ts)[:10] if raw_ts else f"day-{day}"

        return {
            "day": day,
            "date": date_str,
            "portfolio_value": round(capital, 2),
            "daily_pnl": round(daily_pnl, 2),
            "cumulative_pnl_pct": round(cum_pnl_pct, 4),
            "positions_snapshot": _positions_snapshot(rec, day),
            "deployed_usd": round(rec.get("deployed_capital_usd", 0.0) or 0.0, 2),
            "cash_usd": round(rec.get("cash_usd", capital) or capital, 2),
            "apy": rec.get("current_apy"),
            "trade_count": rec.get("trade_count", 0) or 0,
            "data_source": self._source,
        }

    def full_replay(self) -> list[dict]:
        """
        Return all days as a list of replay step dicts.

        Returns:
            List of dicts (one per day), in chronological order.
            Each dict has the same schema as replay_step().
        """
        return [self.replay_step(i) for i in range(len(self._records))]

    def replay_summary(self) -> dict:
        """
        Return aggregate performance metrics across the full replay window.

        Returns:
            Dict with keys:
                total_days, total_return_pct, annualized_return,
                sharpe_ratio, max_drawdown, win_rate,
                best_day, worst_day, data_source, initial_capital, final_capital
        """
        if not self._records:
            return _empty_summary()

        capitals = [
            r.get("total_capital_usd", _INITIAL_CAPITAL) or _INITIAL_CAPITAL
            for r in self._records
        ]
        initial = capitals[0]
        final = capitals[-1]
        n_days = len(capitals)

        # Daily returns
        daily_returns = []
        daily_pnls = []
        for i in range(1, n_days):
            prev = capitals[i - 1]
            curr = capitals[i]
            ret = (curr - prev) / prev if prev > 0 else 0.0
            daily_returns.append(ret)
            daily_pnls.append(curr - prev)

        # Core metrics
        total_ret = total_return_pct(initial, final)
        total_ret_fraction = (final - initial) / initial if initial > 0 else 0.0
        ann_ret = annualised_return_pct(total_ret_fraction, n_days)
        sharpe = sharpe_ratio(daily_returns, risk_free_rate=0.04)
        max_dd = round(max_drawdown(capitals) * 100, 4)

        # Win rate: fraction of days with positive daily PnL
        win_days = sum(1 for p in daily_pnls if p > 0)
        wrate = round(win_days / len(daily_pnls), 4) if daily_pnls else 0.0

        # Best / worst day
        if daily_pnls:
            best_idx = max(range(len(daily_pnls)), key=lambda i: daily_pnls[i])
            worst_idx = min(range(len(daily_pnls)), key=lambda i: daily_pnls[i])
            best_day = {
                "day": best_idx + 1,
                "date": str(self._records[best_idx + 1].get("timestamp", ""))[:10],
                "pnl": round(daily_pnls[best_idx], 2),
                "pnl_pct": round(daily_returns[best_idx] * 100, 4),
            }
            worst_day = {
                "day": worst_idx + 1,
                "date": str(self._records[worst_idx + 1].get("timestamp", ""))[:10],
                "pnl": round(daily_pnls[worst_idx], 2),
                "pnl_pct": round(daily_returns[worst_idx] * 100, 4),
            }
        else:
            best_day = worst_day = {}

        return {
            "total_days": n_days,
            "total_return_pct": total_ret,
            "annualized_return": ann_ret,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": wrate,
            "best_day": best_day,
            "worst_day": worst_day,
            "data_source": self._source,
            "initial_capital": round(initial, 2),
            "final_capital": round(final, 2),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_summary() -> dict:
    return {
        "total_days": 0,
        "total_return_pct": 0.0,
        "annualized_return": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "best_day": {},
        "worst_day": {},
        "data_source": "none",
        "initial_capital": _INITIAL_CAPITAL,
        "final_capital": _INITIAL_CAPITAL,
    }
