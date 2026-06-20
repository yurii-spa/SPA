"""
spa_core/analytics/var_calculator.py

Value at Risk (VaR) and Conditional VaR (CVaR/Expected Shortfall) calculator.
Uses historical simulation method on paper trading returns.

MP-1499 (v11.15) — stdlib only, no external dependencies, LLM FORBIDDEN.

Confidence levels supported: 90%, 95%, 99%.
All returns are daily (fractional, e.g. -0.012 = -1.2% day).

CLI:
    python3 -m spa_core.analytics.var_calculator --check
    python3 -m spa_core.analytics.var_calculator --run
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from typing import Optional

from spa_core.base import BaseAnalytics

CONFIDENCE_LEVELS = [0.90, 0.95, 0.99]

__all__ = ["VaRCalculator", "CONFIDENCE_LEVELS"]


class VaRCalculator(BaseAnalytics):
    """
    Calculates VaR and CVaR for SPA portfolio using historical simulation.

    Historical simulation:
      - Sort returns ascending (worst first).
      - VaR at confidence c = -returns[floor(n*(1-c))] (the loss at that quantile).
      - CVaR at confidence c = -mean(returns[0 : floor(n*(1-c))+1])
        (mean of losses in the tail).

    Minimum 10 daily returns required before metrics are produced.
    Results are written to data/var_analytics.json (atomic).
    """

    OUTPUT_PATH = "data/var_analytics.json"

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._data: dict = {
            "var": {},
            "cvar": {},
            "returns": [],
            "capital": 100_000,
            "n_returns": 0,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_returns(self, daily_returns: list) -> None:
        """
        Loads daily returns for VaR calculation.

        Replaces any existing return series, sorts ascending, recalculates
        VaR/CVaR for all confidence levels, then persists atomically.

        Args:
            daily_returns: List of daily fractional returns (e.g. [-0.012, 0.005, ...]).
        """
        self._data["returns"] = sorted(daily_returns)
        self._data["n_returns"] = len(daily_returns)
        self._recalculate()
        self.save()

    def set_capital(self, capital: float) -> None:
        """Updates the capital amount used for USD-denominated VaR queries."""
        self._data["capital"] = capital

    def var_usd(self, capital: float, confidence: float = 0.95) -> float:
        """
        Returns VaR in USD for given capital.

        Args:
            capital:    Portfolio capital in USD.
            confidence: Confidence level (0.90, 0.95, or 0.99).

        Returns:
            Expected maximum daily loss (positive USD amount) at the given
            confidence level.  Returns 0.0 if not enough data.
        """
        cl_key = _cl_key(confidence)
        return capital * self._data["var"].get(cl_key, 0.0)

    def cvar_usd(self, capital: float, confidence: float = 0.95) -> float:
        """
        Returns CVaR (Expected Shortfall) in USD for given capital.

        Args:
            capital:    Portfolio capital in USD.
            confidence: Confidence level (0.90, 0.95, or 0.99).

        Returns:
            Expected loss given that the loss exceeds VaR (positive USD).
            Returns 0.0 if not enough data.
        """
        cl_key = _cl_key(confidence)
        return capital * self._data["cvar"].get(cl_key, 0.0)

    def is_within_limit(
        self, capital: float, max_loss_usd: float = 5_000
    ) -> bool:
        """
        Checks if 95% VaR is within acceptable loss limit.

        Args:
            capital:       Portfolio capital in USD.
            max_loss_usd:  Maximum acceptable daily loss in USD (default $5,000).

        Returns:
            True if VaR(95%) ≤ max_loss_usd, False otherwise.
        """
        return self.var_usd(capital) <= max_loss_usd

    def summary(self) -> dict:
        """Returns a human-readable summary dict of all VaR/CVaR levels."""
        return {
            "n_returns": self._data["n_returns"],
            "var_90pct": self._data["var"].get("90pct", None),
            "var_95pct": self._data["var"].get("95pct", None),
            "var_99pct": self._data["var"].get("99pct", None),
            "cvar_90pct": self._data["cvar"].get("90pct", None),
            "cvar_95pct": self._data["cvar"].get("95pct", None),
            "cvar_99pct": self._data["cvar"].get("99pct", None),
        }

    def to_dict(self) -> dict:
        """Returns current state as JSON-serializable dict."""
        return self._data

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _recalculate(self) -> None:
        """
        Core VaR/CVaR calculation using historical simulation.

        Requires at least 10 observations. Clears metrics otherwise.
        """
        returns = self._data["returns"]
        n = len(returns)

        if n < 10:
            self._data["var"] = {}
            self._data["cvar"] = {}
            return

        for cl in CONFIDENCE_LEVELS:
            idx = int(n * (1 - cl))
            # VaR: the loss at the tail quantile (returns are sorted asc → idx is worst tail)
            var_frac = -returns[idx] if idx < n else 0.0
            var_frac = max(var_frac, 0.0)  # VaR is never negative

            # CVaR: mean of losses in the tail (returns[:idx+1])
            tail = returns[: idx + 1]
            if len(tail) > 0:
                cvar_frac = -statistics.mean(tail)
                cvar_frac = max(cvar_frac, var_frac)  # CVaR ≥ VaR by definition
            else:
                cvar_frac = var_frac

            key = _cl_key(cl)
            self._data["var"][key] = round(var_frac, 8)
            self._data["cvar"][key] = round(cvar_frac, 8)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _cl_key(confidence: float) -> str:
    """Converts 0.95 → '95pct', etc."""
    return f"{int(round(confidence * 100))}pct"


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


def _load_equity_curve(base_dir: str) -> list:
    """Loads daily returns from equity_curve_daily.json if available."""
    path = os.path.join(base_dir, "data", "equity_curve_daily.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data if isinstance(data, list) else data.get("entries", [])
        navs = [e["nav"] for e in entries if isinstance(e, dict) and "nav" in e]
        if len(navs) < 2:
            return []
        returns = [(navs[i] - navs[i - 1]) / navs[i - 1] for i in range(1, len(navs))]
        return returns
    except Exception as exc:
        print(f"[var_calculator] equity_curve load error: {exc}", file=sys.stderr)
        return []


def main(argv: list | None = None) -> None:
    args = argv or sys.argv[1:]
    run_mode = "--run" in args
    base_dir = "."
    for i, a in enumerate(args):
        if a == "--data-dir" and i + 1 < len(args):
            base_dir = args[i + 1]

    calc = VaRCalculator(base_dir=base_dir)
    daily_returns = _load_equity_curve(base_dir)

    if not daily_returns:
        print("[var_calculator] No equity curve data found — using demo returns for check.")
        # Synthetic 30-day returns for offline check
        import math
        daily_returns = [round(math.sin(i * 0.4) * 0.015, 6) for i in range(30)]

    if run_mode:
        calc.add_returns(daily_returns)
        print(f"[var_calculator] Saved → {calc._path(calc.OUTPUT_PATH)}")
    else:
        # --check: compute without saving
        calc._data["returns"] = sorted(daily_returns)
        calc._data["n_returns"] = len(daily_returns)
        calc._recalculate()

    s = calc.summary()
    capital = 100_000.0
    print(f"[var_calculator] n={s['n_returns']} daily returns")
    for cl_label, var_key, cvar_key in [
        ("90%", "var_90pct", "cvar_90pct"),
        ("95%", "var_95pct", "cvar_95pct"),
        ("99%", "var_99pct", "cvar_99pct"),
    ]:
        v = s.get(var_key)
        c = s.get(cvar_key)
        if v is not None:
            print(
                f"  VaR({cl_label})  = {v:.4%}  (${v*capital:,.0f})   "
                f"CVaR = {c:.4%}  (${c*capital:,.0f})"
            )
        else:
            print(f"  VaR({cl_label})  = N/A (need ≥10 returns)")
    print(f"[var_calculator] within_limit(95%, $5k): {calc.is_within_limit(capital)}")


if __name__ == "__main__":
    main()
