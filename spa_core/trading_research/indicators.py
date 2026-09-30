"""Causal indicators: every output at index t depends only on inputs at indices <= t.

None marks «not enough history yet» (warm-up) — never a guessed number. Pinned by
test_trading_research_backtest.py::test_no_indicator_or_signal_looks_ahead.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

Series = List[Optional[float]]


def sma(x: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(x: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(x)
    k = 2.0 / (n + 1)
    e = None
    for i, v in enumerate(x):
        if i == n - 1:
            e = sum(x[:n]) / n
        elif i >= n:
            e = v * k + e * (1 - k)
        out[i] = e
    return out


def rsi(close: Sequence[float], n: int = 14) -> Series:
    """Wilder RSI."""
    out: Series = [None] * len(close)
    gain = loss = 0.0
    for i in range(1, len(close)):
        ch = close[i] - close[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            gain += g; loss += l
            if i == n:
                gain /= n; loss /= n
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + l) / n
        if i >= n:
            out[i] = 100.0 if loss == 0 else 100.0 - 100.0 / (1 + gain / loss)
    return out


def true_range(high, low, close) -> List[float]:
    tr = [high[0] - low[0]]
    for i in range(1, len(close)):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return tr


def atr(high, low, close, n: int = 14) -> Series:
    """Wilder ATR."""
    tr = true_range(high, low, close)
    out: Series = [None] * len(tr)
    a = None
    for i, v in enumerate(tr):
        if i == n - 1:
            a = sum(tr[:n]) / n
        elif i >= n:
            a = (a * (n - 1) + v) / n
        out[i] = a
    return out


def macd(close, fast=12, slow=26, signal=9):
    ef, es = ema(close, fast), ema(close, slow)
    line: Series = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig_part = ema([v for v in line[start:]], signal) if start < len(line) else []
    sig: Series = [None] * start + sig_part
    return line, sig


def rolling_max(x, n: int) -> Series:
    return [None if i < n - 1 else max(x[i - n + 1:i + 1]) for i in range(len(x))]


def rolling_min(x, n: int) -> Series:
    return [None if i < n - 1 else min(x[i - n + 1:i + 1]) for i in range(len(x))]


def rolling_std(x, n: int) -> Series:
    out: Series = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = (sum((v - m) ** 2 for v in w) / n) ** 0.5
    return out


def supertrend(high, low, close, n: int = 10, mult: float = 3.0) -> List[Optional[int]]:
    """Direction +1 (up) / -1 (down), standard final-band SuperTrend."""
    a = atr(high, low, close, n)
    out: List[Optional[int]] = [None] * len(close)
    fu = fl = None
    d = 1
    for i in range(len(close)):
        if a[i] is None:
            continue
        mid = (high[i] + low[i]) / 2
        bu, bl = mid + mult * a[i], mid - mult * a[i]
        if fu is None:
            fu, fl = bu, bl
        else:
            fu = bu if (bu < fu or close[i - 1] > fu) else fu
            fl = bl if (bl > fl or close[i - 1] < fl) else fl
        if d == 1 and close[i] < fl:
            d = -1
        elif d == -1 and close[i] > fu:
            d = 1
        out[i] = d
    return out
