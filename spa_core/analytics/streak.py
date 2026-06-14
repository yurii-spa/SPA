"""Win/loss streaks over a daily-PnL series (MP-104).

Stdlib only. Pure function — no IO.
"""
from __future__ import annotations


def calculate_streaks(daily_pnl: list[float]) -> dict:
    """Current and maximum win/loss streaks.

    A win is pnl > 0, a loss is pnl < 0; a zero day breaks both streaks.
    "Current" streaks are counted from the end of the series.
    """
    max_win = max_loss = 0
    win = loss = 0
    for pnl in daily_pnl:
        v = float(pnl)
        if v > 0:
            win += 1
            loss = 0
        elif v < 0:
            loss += 1
            win = 0
        else:
            win = loss = 0
        max_win = max(max_win, win)
        max_loss = max(max_loss, loss)
    return {
        "current_win_streak": win,
        "max_win_streak": max_win,
        "current_loss_streak": loss,
        "max_loss_streak": max_loss,
    }
