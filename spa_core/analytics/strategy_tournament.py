"""Strategy Tournament Leaderboard (MP-628).

Ranks strategies S0–S19 by paper trading performance.  Reads
``data/strategy_shadow_comparison.json`` (primary source), falls back to
``data/pnl_history.json``, and finally to deterministic defaults if neither
file is usable.

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory / read-only — never modifies allocator / risk / execution.
* All writes are atomic: ``tmp-file + os.replace``.
* Output ring-buffer capped at 100 entries (report list).
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

StrategyScore fields
--------------------
strategy_id : str   — e.g. "S0"
name        : str   — human label (e.g. "Conservative Yield")
paper_apy   : float — annualised % return in paper trading
sharpe      : float — Sharpe ratio computed from daily returns; 0.0 if
                      stdev == 0 or < 2 data points
max_drawdown: float — maximum peak-to-trough drawdown as positive fraction
                      (0.05 = 5%)
days_active : int   — number of paper-trading days recorded
rank        : int   — 1 = best (assigned by rank_strategies)
medal       : str   — "🥇" / "🥈" / "🥉" / ""

Public API
----------
``StrategyTournament(data_dir="data/")``

    _load_scores()                         -> list[StrategyScore]
    rank_strategies(metric="paper_apy")    -> list[StrategyScore]
    compute_sharpe(returns, rf_rate=0.045) -> float
    get_top_n(n=3)                         -> list[StrategyScore]
    generate_leaderboard_report()          -> dict
    save_report(report)                    -> str  (path written)
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0"
ADVISORY: str = "For informational purposes only."
OUTPUT_FILE: str = "strategy_tournament.json"
RING_BUFFER_MAX: int = 100

MEDALS: tuple[str, ...] = ("🥇", "🥈", "🥉")

# Deterministic strategy names for S0–S19
_DEFAULT_NAMES: Dict[str, str] = {
    "S0":  "Conservative Yield",
    "S1":  "Balanced Diversified",
    "S2":  "Yield Maximiser",
    "S3":  "TVL-Weighted Alpha",
    "S4":  "Tier-1 Only Safe",
    "S5":  "Momentum Rotator",
    "S6":  "Risk-Parity Blend",
    "S7":  "Low-Drawdown Guard",
    "S8":  "Delta-Neutral sUSDe",
    "S9":  "E-Mode Looping",
    "S10": "Pendle YT Speculative",
    "S11": "Multi-Chain Spread",
    "S12": "Yield Curve Arbitrage",
    "S13": "Protocol Concentration",
    "S14": "Adaptive Kelly",
    "S15": "Covariance Minimiser",
    "S16": "Tail-Risk Hedge",
    "S17": "Cash-Buffer Optimiser",
    "S18": "Compounding Compounder",
    "S19": "Experimental Basket",
}

# Deterministic seed APY values for S0–S19 (used only when no data available)
_SEED_APY: Dict[str, float] = {
    "S0":  3.50, "S1":  4.20, "S2":  5.80, "S3":  6.10, "S4":  3.30,
    "S5":  7.20, "S6":  5.50, "S7":  2.90, "S8": 12.40, "S9":  5.84,
    "S10":18.50, "S11": 4.80, "S12": 6.60, "S13": 8.10, "S14": 7.40,
    "S15": 4.00, "S16": 2.50, "S17": 3.80, "S18": 9.20, "S19":11.00,
}

_SEED_SHARPE: Dict[str, float] = {
    "S0":  0.85, "S1":  1.10, "S2":  1.30, "S3":  1.20, "S4":  0.70,
    "S5":  1.50, "S6":  1.15, "S7":  0.60, "S8":  1.80, "S9":  1.25,
    "S10": 2.10, "S11": 1.05, "S12": 1.40, "S13": 1.60, "S14": 1.55,
    "S15": 0.90, "S16": 0.55, "S17": 0.80, "S18": 1.75, "S19": 1.90,
}

_SEED_MDD: Dict[str, float] = {
    "S0":  0.00, "S1":  0.00, "S2":  0.01, "S3":  0.01, "S4":  0.00,
    "S5":  0.02, "S6":  0.01, "S7":  0.00, "S8":  0.03, "S9":  0.01,
    "S10": 0.04, "S11": 0.01, "S12": 0.02, "S13": 0.02, "S14": 0.02,
    "S15": 0.00, "S16": 0.00, "S17": 0.00, "S18": 0.03, "S19": 0.03,
}

_SEED_DAYS: Dict[str, int] = {
    "S0": 3,  "S1": 3,  "S2": 3,  "S3": 3,  "S4": 3,
    "S5": 3,  "S6": 3,  "S7": 3,  "S8": 3,  "S9": 3,
    "S10": 3, "S11": 1, "S12": 1, "S13": 1, "S14": 1,
    "S15": 1, "S16": 1, "S17": 1, "S18": 1, "S19": 1,
}

# Allowed ranking metrics
VALID_METRICS: tuple[str, ...] = (
    "paper_apy", "sharpe", "max_drawdown", "days_active",
)

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class StrategyScore:
    """Snapshot of one strategy's paper-trading performance."""

    strategy_id:  str
    name:         str
    paper_apy:    float  # annualised %
    sharpe:       float  # 0.0 when not enough data
    max_drawdown: float  # fraction, 0.03 = 3%; lower is better
    days_active:  int
    rank:         int    = 0   # 1 = best; assigned by rank_strategies()
    medal:        str    = ""  # 🥇/🥈/🥉/""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce *val* to float, returning *default* on failure."""
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Coerce *val* to int, returning *default* on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stdev(values: List[float]) -> float:
    """Population standard deviation (ddof=1 when len>1, else 0)."""
    n = len(values)
    if n < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance) if variance > 0 else 0.0


def _pnl_pct_to_apy(pnl_pct: float, days: int) -> float:
    """Convert total PnL % over *days* to annualised APY %.

    Uses simple annualisation: ``(pnl_pct / days) * 365``.
    Returns 0.0 if *days* <= 0.
    """
    if days <= 0:
        return 0.0
    return (pnl_pct / max(days, 1)) * 365.0


def _max_drawdown_from_equity(equity_series: List[float]) -> float:
    """Compute max peak-to-trough drawdown as a positive fraction."""
    if len(equity_series) < 2:
        return 0.0
    peak = equity_series[0]
    mdd = 0.0
    for v in equity_series[1:]:
        if v > peak:
            peak = v
        elif peak > 0:
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd
    return mdd


# ---------------------------------------------------------------------------
# StrategyTournament
# ---------------------------------------------------------------------------


class StrategyTournament:
    """Loads strategy performance data and produces a ranked leaderboard.

    Parameters
    ----------
    data_dir:
        Directory containing ``strategy_shadow_comparison.json``,
        ``pnl_history.json``, etc.  Defaults to ``"data/"``.
    """

    def __init__(self, data_dir: str = "data/") -> None:
        self.data_dir = Path(data_dir)
        self._output_path = self.data_dir / OUTPUT_FILE

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def compute_sharpe(
        self,
        returns: List[float],
        rf_rate: float = 0.045,
    ) -> float:
        """Compute annualised Sharpe ratio.

        Parameters
        ----------
        returns:
            List of daily return fractions (e.g. 0.001 = 0.1% per day).
        rf_rate:
            Annual risk-free rate as a fraction (default 0.045 = 4.5%).

        Returns
        -------
        float
            Annualised Sharpe; 0.0 when stdev == 0 or len < 2.
        """
        if not returns or len(returns) < 2:
            return 0.0
        safe_returns = [_safe_float(r) for r in returns]
        daily_rf = rf_rate / 365.0
        excess = [r - daily_rf for r in safe_returns]
        sd = _stdev(excess)
        if sd == 0.0:
            return 0.0
        return (_mean(excess) / sd) * math.sqrt(365.0)

    # ------------------------------------------------------------------
    # Internal data loading
    # ------------------------------------------------------------------

    def _load_shadow_comparison(self) -> Optional[List[StrategyScore]]:
        """Load from strategy_shadow_comparison.json (preferred source)."""
        path = self.data_dir / "strategy_shadow_comparison.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Cannot read %s: %s", path, exc)
            return None

        strategies = data.get("strategies") if isinstance(data, dict) else None
        if not strategies or not isinstance(strategies, list):
            return None

        scores: List[StrategyScore] = []
        for item in strategies:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("name", item.get("label", ""))).strip()
            if not sid:
                continue
            pnl_pct = _safe_float(item.get("pnl_pct", 0.0))
            days = _safe_int(item.get("days_running", 1))
            apy = _pnl_pct_to_apy(pnl_pct, days)

            # Prefer explicit sharpe when present (may be None)
            sharpe_raw = item.get("sharpe")
            sharpe = _safe_float(sharpe_raw) if sharpe_raw is not None else 0.0

            mdd = _safe_float(item.get("max_drawdown", 0.0))

            scores.append(
                StrategyScore(
                    strategy_id=sid,
                    name=_DEFAULT_NAMES.get(sid, sid),
                    paper_apy=round(apy, 4),
                    sharpe=round(sharpe, 4),
                    max_drawdown=round(mdd, 6),
                    days_active=max(days, 0),
                )
            )

        return scores if scores else None

    def _load_pnl_history(self) -> Optional[List[StrategyScore]]:
        """Derive single aggregate score from pnl_history.json."""
        path = self.data_dir / "pnl_history.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Cannot read %s: %s", path, exc)
            return None

        if not isinstance(data, list) or not data:
            return None

        # Build equity series from total_capital_usd
        equity = [
            _safe_float(e.get("total_capital_usd", 100_000.0))
            for e in data
            if isinstance(e, dict)
        ]
        if len(equity) < 2:
            return None

        days = len(equity)
        pnl_pct = ((equity[-1] - equity[0]) / equity[0]) * 100.0 if equity[0] else 0.0
        apy = _pnl_pct_to_apy(pnl_pct, days)
        mdd = _max_drawdown_from_equity(equity)

        daily_returns = [
            (equity[i] - equity[i - 1]) / equity[i - 1]
            for i in range(1, len(equity))
            if equity[i - 1] != 0
        ]
        sharpe = self.compute_sharpe(daily_returns)

        # Return a single composite score representing the live portfolio
        return [
            StrategyScore(
                strategy_id="S0",
                name=_DEFAULT_NAMES["S0"],
                paper_apy=round(apy, 4),
                sharpe=round(sharpe, 4),
                max_drawdown=round(mdd, 6),
                days_active=days,
            )
        ]

    def _generate_defaults(self) -> List[StrategyScore]:
        """Return deterministic placeholder scores for S0–S19."""
        return [
            StrategyScore(
                strategy_id=sid,
                name=_DEFAULT_NAMES[sid],
                paper_apy=_SEED_APY[sid],
                sharpe=_SEED_SHARPE[sid],
                max_drawdown=_SEED_MDD[sid],
                days_active=_SEED_DAYS[sid],
            )
            for sid in _DEFAULT_NAMES
        ]

    def _load_scores(self) -> List[StrategyScore]:
        """Load strategy scores from disk, with graceful fallback chain.

        Priority:
          1. strategy_shadow_comparison.json  (real per-strategy data)
          2. pnl_history.json                 (portfolio-level data → S0)
          3. Deterministic defaults (S0–S19)  (no data files available)
        """
        scores = self._load_shadow_comparison()
        if scores:
            return scores

        scores = self._load_pnl_history()
        if scores:
            return scores

        logger.info(
            "No data files found — using deterministic seed defaults."
        )
        return self._generate_defaults()

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def rank_strategies(
        self,
        metric: str = "paper_apy",
        scores: Optional[List[StrategyScore]] = None,
    ) -> List[StrategyScore]:
        """Sort strategies by *metric* (descending) and assign rank + medal.

        Parameters
        ----------
        metric:
            One of ``"paper_apy"`` (default), ``"sharpe"``,
            ``"max_drawdown"``, or ``"days_active"``.
            For ``"max_drawdown"`` the sort is ascending (lower = better).
        scores:
            Optional pre-loaded list; if None, ``_load_scores()`` is called.

        Returns
        -------
        list[StrategyScore]
            Sorted list with *rank* and *medal* populated.
        """
        if metric not in VALID_METRICS:
            raise ValueError(
                f"metric must be one of {VALID_METRICS}, got {metric!r}"
            )

        if scores is None:
            scores = self._load_scores()

        ascending = metric == "max_drawdown"
        sorted_scores = sorted(
            scores,
            key=lambda s: getattr(s, metric),
            reverse=not ascending,
        )

        for i, s in enumerate(sorted_scores):
            s.rank = i + 1
            s.medal = MEDALS[i] if i < len(MEDALS) else ""

        return sorted_scores

    # ------------------------------------------------------------------
    # Top-N helper
    # ------------------------------------------------------------------

    def get_top_n(
        self,
        n: int = 3,
        metric: str = "paper_apy",
        scores: Optional[List[StrategyScore]] = None,
    ) -> List[StrategyScore]:
        """Return the top *n* strategies after ranking.

        Parameters
        ----------
        n:
            Number of strategies to return (clamped to len(ranked)).
        metric:
            Ranking metric forwarded to ``rank_strategies``.
        scores:
            Optional pre-loaded list.
        """
        ranked = self.rank_strategies(metric=metric, scores=scores)
        return ranked[:max(0, n)]

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def generate_leaderboard_report(
        self,
        metric: str = "paper_apy",
    ) -> Dict[str, Any]:
        """Build the full leaderboard report dict.

        Returns
        -------
        dict with keys:
            schema_version, generated_at, metric, total_strategies,
            ranked_strategies, top_3, winner, advisory
        """
        ranked = self.rank_strategies(metric=metric)
        top3 = ranked[:3]
        winner = ranked[0].to_dict() if ranked else None

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metric": metric,
            "total_strategies": len(ranked),
            "ranked_strategies": [s.to_dict() for s in ranked],
            "top_3": [s.to_dict() for s in top3],
            "winner": winner,
            "advisory": ADVISORY,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: Optional[Dict[str, Any]] = None) -> str:
        """Atomically write *report* to ``data/strategy_tournament.json``.

        Parameters
        ----------
        report:
            Dict from ``generate_leaderboard_report()``.  If None, the
            report is generated automatically.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if report is None:
            report = self.generate_leaderboard_report()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._output_path

        # Ring-buffer: keep at most RING_BUFFER_MAX ranked_strategies entries
        ranked = report.get("ranked_strategies", [])
        if len(ranked) > RING_BUFFER_MAX:
            report = dict(report)
            report["ranked_strategies"] = ranked[:RING_BUFFER_MAX]


        atomic_save(report, str(out_path))
        logger.info("Saved leaderboard report → %s", out_path)
        return str(out_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Strategy Tournament Leaderboard (MP-628)"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute leaderboard and write data/strategy_tournament.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print without writing (default if neither flag given)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/",
        help="Path to data directory (default: data/)",
    )
    parser.add_argument(
        "--metric",
        default="paper_apy",
        choices=list(VALID_METRICS),
        help="Ranking metric (default: paper_apy)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    tournament = StrategyTournament(data_dir=args.data_dir)
    report = tournament.generate_leaderboard_report(metric=args.metric)

    if args.run:
        path = tournament.save_report(report)
        print(f"[MP-628] Written → {path}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
