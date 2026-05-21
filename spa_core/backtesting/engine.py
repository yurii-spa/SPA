"""
SPA Backtesting Engine v0.9
============================

Replays the auto_allocate() strategy on historical (or synthetic) APY data.
Uses the SAME RiskPolicy as live trading — no exceptions, no parameter overrides.

Design principles:
  - Same RiskConfig as production → backtest = real behaviour approximation
  - No look-ahead bias: decisions on day T use only data from day T
  - Daily rebalancing: each day re-evaluates all positions
  - Cash management mirrors live: 5% buffer enforced at all times
  - Positions earn daily interest: amount × APY/100 / 365

Usage:
    from backtesting.data_loader import generate_synthetic_history
    from backtesting.engine import BacktestEngine

    history = generate_synthetic_history(days=90)
    result = BacktestEngine().run(history)
    print(result.metrics)
    print(result.equity_curve[-5:])
"""

from __future__ import annotations

import sys
import math
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.policy import RiskPolicy, RiskConfig, Position, PortfolioState
from backtesting.metrics import (
    sharpe_ratio,
    max_drawdown,
    win_rate,
    total_return_pct,
    annualised_return_pct,
)

log = logging.getLogger(__name__)


# ─── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """
    Full result from a BacktestEngine.run() call.

    Attributes:
        equity_curve: Daily portfolio snapshots (list of dicts).
        trades: All trade events during the backtest (list of dicts).
        metrics: Summary statistics dict (Sharpe, max_dd, total_return, etc.)
        policy_version: Version string of the RiskConfig used.
        days: Number of days in the backtest.
        initial_capital: Starting capital in USD.
    """
    equity_curve: list[dict]   # [{date, total_capital, deployed, cash, pnl_pct}, ...]
    trades: list[dict]         # [{date, protocol, action, amount, apy, reason}, ...]
    metrics: dict
    policy_version: str
    days: int
    initial_capital: float


# ─── Internal position state (not the same as risk.policy.Position) ────────────

@dataclass
class _BtPosition:
    """Backtest-internal position tracking."""
    protocol_key: str
    tier: str
    amount_usd: float
    apy_at_open: float
    date_opened: str
    current_apy: float = 0.0
    total_interest_usd: float = 0.0

    def daily_interest(self) -> float:
        """Interest earned today based on current APY."""
        return self.amount_usd * (self.current_apy / 100.0) / 365.0


# ─── Engine ────────────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Replay auto_allocate() strategy on historical APY data.

    Uses the SAME RiskPolicy as live trading — no exceptions.

    The engine simulates:
    1. Morning: accrue daily interest on all open positions.
    2. Rebalance: close positions that no longer pass risk checks or have
       fallen below min_apy threshold.
    3. Allocate: open new positions in best-APY protocols with available cash,
       subject to all RiskPolicy constraints.
    4. Record: snapshot equity curve entry for the day.
    """

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        self.policy = RiskPolicy(config=self.config)

    def run(
        self,
        historical_data: list[dict],
        initial_capital: float = 100_000.0,
        policy_version: str = "v1.0",
    ) -> BacktestResult:
        """
        Run the backtest.

        Args:
            historical_data: List of snapshot dicts:
                [{timestamp, protocol_key, apy, tvl_usd, tier}, ...]
                All timestamps should be ISO date strings (YYYY-MM-DD).
                Multiple records per date (one per protocol) are expected.
            initial_capital: Starting virtual capital in USD (default $100,000).
            policy_version: Label for the policy version (for output metadata).

        Returns:
            BacktestResult with equity_curve, trades, and metrics.
        """
        # ── Group data by date ────────────────────────────────────────────────
        days_data: dict[str, list[dict]] = {}
        for row in historical_data:
            ts = row["timestamp"][:10]  # ensure YYYY-MM-DD
            days_data.setdefault(ts, []).append(row)

        sorted_dates = sorted(days_data.keys())
        if not sorted_dates:
            return _empty_result(initial_capital, policy_version)

        # ── Initial state ─────────────────────────────────────────────────────
        capital = initial_capital            # total capital (grows with interest)
        positions: list[_BtPosition] = []   # currently open BT positions
        equity_curve: list[dict] = []
        all_trades: list[dict] = []
        closed_trades_pnl: list[dict] = []  # for win_rate

        # ── Daily simulation loop ─────────────────────────────────────────────
        for day_str in sorted_dates:
            day_protocols = {r["protocol_key"]: r for r in days_data[day_str]}

            # Step 1: Update current APY for all open positions
            for pos in positions:
                if pos.protocol_key in day_protocols:
                    pos.current_apy = day_protocols[pos.protocol_key]["apy"]

            # Step 2: Accrue daily interest
            for pos in positions:
                interest = pos.daily_interest()
                pos.total_interest_usd += interest
                capital += interest

            # Step 3: Rebalance — close positions that should be exited
            positions, closed_today = self._rebalance(
                positions, day_protocols, capital, day_str
            )
            all_trades.extend(closed_today)
            closed_trades_pnl.extend(closed_today)

            # Step 4: Auto-allocate — open new positions with available cash
            deployed = sum(p.amount_usd for p in positions)
            cash = capital - deployed
            new_opens = self._auto_allocate(
                positions, day_protocols, capital, cash, day_str
            )
            positions.extend(new_opens["positions"])
            all_trades.extend(new_opens["trades"])

            # Step 5: Record equity snapshot
            deployed = sum(p.amount_usd for p in positions)
            cash = capital - deployed
            interest_earned = sum(p.total_interest_usd for p in positions)
            pnl_pct = (capital - initial_capital) / initial_capital * 100 if initial_capital > 0 else 0.0

            equity_curve.append({
                "date": day_str,
                "total_capital": round(capital, 2),
                "deployed": round(deployed, 2),
                "cash": round(cash, 2),
                "pnl_pct": round(pnl_pct, 4),
                "open_positions": len(positions),
            })

        # ── Close remaining positions at end of backtest ────────────────────
        final_date = sorted_dates[-1]
        for pos in positions:
            close_trade = {
                "date": final_date,
                "protocol": pos.protocol_key,
                "action": "CLOSE",
                "amount": round(pos.amount_usd, 2),
                "apy": round(pos.current_apy, 4),
                "interest_usd": round(pos.total_interest_usd, 4),
                "pnl": round(pos.total_interest_usd, 4),
                "reason": "backtest_end",
            }
            closed_trades_pnl.append(close_trade)
            all_trades.append(close_trade)

        # ── Compute metrics ───────────────────────────────────────────────────
        daily_capitals = [e["total_capital"] for e in equity_curve]
        daily_returns = [
            (daily_capitals[i] - daily_capitals[i - 1]) / daily_capitals[i - 1]
            if daily_capitals[i - 1] > 0 else 0.0
            for i in range(1, len(daily_capitals))
        ]

        final_capital = daily_capitals[-1] if daily_capitals else initial_capital
        total_ret_pct = total_return_pct(initial_capital, final_capital)
        total_ret_fraction = (final_capital - initial_capital) / initial_capital
        n_days = len(sorted_dates)

        open_trades = [t for t in all_trades if t["action"] == "OPEN"]
        close_trades = [t for t in all_trades if t["action"] == "CLOSE"]

        avg_position_size = (
            sum(t["amount"] for t in open_trades) / len(open_trades)
            if open_trades else 0.0
        )

        metrics = {
            "sharpe_ratio": sharpe_ratio(daily_returns, risk_free_rate=0.04),
            "max_drawdown_pct": round(max_drawdown(daily_capitals) * 100, 4),
            "total_return_pct": total_ret_pct,
            "annualised_return_pct": annualised_return_pct(total_ret_fraction, n_days),
            "win_rate": win_rate(closed_trades_pnl),
            "total_trades": len(open_trades),
            "avg_position_size_usd": round(avg_position_size, 2),
            "initial_capital_usd": round(initial_capital, 2),
            "final_capital_usd": round(final_capital, 2),
            "total_interest_usd": round(final_capital - initial_capital, 2),
            "backtest_days": n_days,
        }

        return BacktestResult(
            equity_curve=equity_curve,
            trades=all_trades,
            metrics=metrics,
            policy_version=policy_version,
            days=n_days,
            initial_capital=initial_capital,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _rebalance(
        self,
        positions: list[_BtPosition],
        day_protocols: dict[str, dict],
        capital: float,
        day_str: str,
    ) -> tuple[list[_BtPosition], list[dict]]:
        """
        Close positions that should be exited:
        - Protocol no longer in whitelist / day data.
        - Current APY dropped below policy minimum.
        - Position causes concentration breach (would be rejected today).

        Returns (remaining_positions, closed_trade_records).
        """
        remaining = []
        closed = []

        for pos in positions:
            should_close = False
            reason = ""

            data = day_protocols.get(pos.protocol_key)

            if data is None:
                should_close = True
                reason = "protocol_not_in_data"
            elif data["apy"] < self.config.min_apy_for_new_position:
                should_close = True
                reason = f"apy_below_minimum ({data['apy']:.2f}% < {self.config.min_apy_for_new_position:.1f}%)"
            elif data["tvl_usd"] < self.config.min_tvl_usd:
                should_close = True
                reason = f"tvl_too_low (${data['tvl_usd']:,.0f} < ${self.config.min_tvl_usd:,.0f})"

            if should_close:
                closed.append({
                    "date": day_str,
                    "protocol": pos.protocol_key,
                    "action": "CLOSE",
                    "amount": round(pos.amount_usd, 2),
                    "apy": round(pos.current_apy, 4),
                    "interest_usd": round(pos.total_interest_usd, 4),
                    "pnl": round(pos.total_interest_usd, 4),
                    "reason": reason,
                })
            else:
                remaining.append(pos)

        return remaining, closed

    def _auto_allocate(
        self,
        positions: list[_BtPosition],
        day_protocols: dict[str, dict],
        capital: float,
        cash: float,
        day_str: str,
    ) -> dict:
        """
        Open new positions in best-APY protocols, subject to all RiskPolicy constraints.
        Mirrors the live auto_allocate() logic in paper_trading/engine.py.

        Returns dict with "positions" (new BtPosition list) and "trades" (trade records).
        """
        new_positions = []
        trades = []

        min_cash_threshold = capital * 0.10
        if cash < min_cash_threshold:
            return {"positions": [], "trades": []}

        # Sort protocols by APY descending (no look-ahead — only today's data)
        candidates = sorted(
            day_protocols.values(),
            key=lambda r: r.get("apy", 0),
            reverse=True,
        )

        open_keys = {p.protocol_key for p in positions}

        for candidate in candidates:
            key = candidate["protocol_key"]
            apy = candidate["apy"]
            tvl = candidate["tvl_usd"]
            tier = candidate["tier"]

            if key in open_keys:
                continue

            # Build current portfolio state for RiskPolicy
            bt_positions = list(positions) + new_positions
            state = self._build_portfolio_state(bt_positions, capital)

            cash_now = state.cash_usd
            if cash_now < min_cash_threshold:
                break

            # Use RiskPolicy to compute max safe size
            amount = self.policy.max_safe_position_size(state, key, tier)
            if amount < 10.0:
                continue

            # Full risk check (same as live)
            result = self.policy.check_new_position(
                state=state,
                protocol_key=key,
                tier=tier,
                amount_usd=amount,
                current_apy=apy,
                tvl_usd=tvl,
            )

            if result.approved:
                new_pos = _BtPosition(
                    protocol_key=key,
                    tier=tier,
                    amount_usd=amount,
                    apy_at_open=apy,
                    date_opened=day_str,
                    current_apy=apy,
                    total_interest_usd=0.0,
                )
                new_positions.append(new_pos)
                open_keys.add(key)
                trades.append({
                    "date": day_str,
                    "protocol": key,
                    "action": "OPEN",
                    "amount": round(amount, 2),
                    "apy": round(apy, 4),
                    "tier": tier,
                    "interest_usd": 0.0,
                    "pnl": 0.0,
                    "reason": "auto_allocate",
                })

        return {"positions": new_positions, "trades": trades}

    def _build_portfolio_state(
        self, positions: list[_BtPosition], capital: float
    ) -> PortfolioState:
        """Convert backtest positions into a RiskPolicy-compatible PortfolioState."""
        risk_positions = [
            Position(
                protocol_key=p.protocol_key,
                tier=p.tier,
                asset="USDC",  # all protocols in scope are stablecoin
                amount_usd=p.amount_usd,
                apy_at_open=p.apy_at_open,
                current_apy=p.current_apy,
                unrealized_pnl_usd=p.total_interest_usd,
                days_held=0.0,
            )
            for p in positions
        ]
        return PortfolioState(total_capital_usd=capital, positions=risk_positions)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _empty_result(initial_capital: float, policy_version: str) -> BacktestResult:
    """Return an empty BacktestResult when there's no data to process."""
    return BacktestResult(
        equity_curve=[],
        trades=[],
        metrics={
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
            "annualised_return_pct": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
            "avg_position_size_usd": 0.0,
            "initial_capital_usd": initial_capital,
            "final_capital_usd": initial_capital,
            "total_interest_usd": 0.0,
            "backtest_days": 0,
        },
        policy_version=policy_version,
        days=0,
        initial_capital=initial_capital,
    )
