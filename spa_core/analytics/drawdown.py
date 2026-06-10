"""Max-drawdown analysis over an equity curve (MP-104).

Stdlib only. Pure function — no IO.
"""
from __future__ import annotations


def calculate_max_drawdown(
    equity_curve: list[float], dates: list[str] | None = None
) -> dict:
    """Deepest peak-to-trough drawdown of an equity series.

    Drawdowns are reported as POSITIVE percentages (10.0 == a 10% drop;
    0.0 == no drawdown). ``dates`` aligns 1:1 with ``equity_curve``; when
    omitted, stringified indices are used.

    Returns::

        {"max_drawdown_pct": float, "peak_date": str | None,
         "trough_date": str | None, "current_drawdown_pct": float}
    """
    n = len(equity_curve)
    if n == 0:
        return {
            "max_drawdown_pct": 0.0,
            "peak_date": None,
            "trough_date": None,
            "current_drawdown_pct": 0.0,
        }
    if dates is None or len(dates) != n:
        dates = [str(i) for i in range(n)]

    peak = float(equity_curve[0])
    peak_idx = 0
    max_dd = 0.0
    max_dd_peak_idx = 0
    max_dd_trough_idx = 0
    for i, raw in enumerate(equity_curve):
        v = float(raw)
        if v > peak:
            peak = v
            peak_idx = i
        dd = (peak - v) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_peak_idx = peak_idx
            max_dd_trough_idx = i

    last = float(equity_curve[-1])
    current_dd = (peak - last) / peak * 100.0 if peak > 0 else 0.0

    return {
        "max_drawdown_pct": round(max_dd, 6),
        "peak_date": dates[max_dd_peak_idx],
        "trough_date": dates[max_dd_trough_idx],
        "current_drawdown_pct": round(current_dd, 6),
    }
