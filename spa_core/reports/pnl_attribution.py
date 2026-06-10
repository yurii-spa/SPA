"""
Read-only PnL attribution by protocol (SPA-V393).

Investor-grade reporting layer that answers "where is the capital, and which
protocol drives the portfolio APY". It sits *on top of* the read-only
portfolio-state / P&L-history snapshots — it never touches the execution path,
risk policy, wallets, or any money-moving code, and it is NOT a feed-health
monitor (the SPA-BL-011 frozen domain is untouched).

Sources (each read defensively; a missing/broken file degrades to empty, never
raises):
  * ``data/portfolio_state.json`` — current positions
        ``{protocol, actual_usd, target_usd, actual_weight, target_weight, apy?}``
        plus portfolio roll-up (``total_actual_usd``, ``num_positions``).
  * ``data/pnl_history.json`` — time series of
        ``{timestamp, total_capital_usd, total_pnl_usd, total_pnl_pct,
           current_apy}`` (list of records).
  * ``data/equity_curve_daily.json`` — optional daily equity curve (used only
        for the reporting ``period`` when pnl_history lacks timestamps).

Design notes / safety:
  * Pure stdlib (json, logging, datetime, pathlib) — no web3 / numpy / pandas.
  * STRICTLY READ-ONLY. Computes a derived dict; the caller decides whether to
    persist it.
  * Per-protocol APY contribution to the portfolio is ``weight * protocol_apy``
    **only when** an explicit per-protocol APY is present in the position
    record. If no per-protocol APY is available we DO NOT invent one — the
    ``apy_contribution`` field is ``None`` so investors are never shown a
    fabricated attribution.

Schema (stable) returned by :func:`compute_pnl_attribution`::

    {
      "protocols": [
        {"protocol", "actual_usd", "target_usd",
         "actual_weight", "target_weight",
         "capital_share", "protocol_apy", "apy_contribution"},
        ...
      ],
      "roll_up": {
        "total_capital_usd", "total_pnl_usd", "total_pnl_pct",
        "current_apy", "num_positions",
        "period": {"first": <iso|None>, "last": <iso|None>, "days": int},
        "total_actual_usd", "total_target_usd",
      },
    }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.reports.pnl_attribution")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"

DEFAULT_PORTFOLIO_PATH = _DATA_DIR / "portfolio_state.json"
DEFAULT_PNL_HISTORY_PATH = _DATA_DIR / "pnl_history.json"
DEFAULT_EQUITY_CURVE_PATH = _DATA_DIR / "equity_curve_daily.json"

# Keys we probe for a per-protocol APY inside a position record. The first one
# present with a finite numeric value wins. If none are present the contribution
# stays None (we never fabricate an APY).
_APY_POSITION_KEYS = ("apy", "current_apy", "net_apy", "protocol_apy", "live_apy")


# ─── Defensive IO ──────────────────────────────────────────────────────────────

def _load_json(path: str | Path) -> Any:
    """Load JSON, returning ``None`` on any error (missing / invalid / OSError)."""
    try:
        p = Path(path)
        if not p.exists():
            log.info("source missing: %s", p)
            return None
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None


def _as_float(value: Any) -> float | None:
    """Coerce to a finite float, else None (no NaN/inf leaks into the report)."""
    try:
        if value is None or isinstance(value, bool):
            return None
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ─── Positions / portfolio extraction ──────────────────────────────────────────

def _extract_positions(portfolio: Any) -> list[dict]:
    """Pull the positions list from a portfolio_state payload, tolerating shapes.

    Accepts either ``{"positions": [...]}`` or a bare list. Non-dict entries are
    skipped. Never raises.
    """
    if portfolio is None:
        return []
    raw: Any
    if isinstance(portfolio, dict):
        raw = portfolio.get("positions")
    elif isinstance(portfolio, list):
        raw = portfolio
    else:
        return []
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def _position_apy(pos: dict) -> float | None:
    """Return the first explicit per-protocol APY found, else None."""
    for key in _APY_POSITION_KEYS:
        if key in pos:
            apy = _as_float(pos.get(key))
            if apy is not None:
                return apy
    return None


# ─── Time-series roll-up ────────────────────────────────────────────────────────

def _history_records(history: Any) -> list[dict]:
    """Normalise a pnl_history payload to a list of dict records."""
    if history is None:
        return []
    if isinstance(history, dict):
        for key in ("history", "records", "pnl_history", "data"):
            seq = history.get(key)
            if isinstance(seq, list):
                return [r for r in seq if isinstance(r, dict)]
        return []
    if isinstance(history, list):
        return [r for r in history if isinstance(r, dict)]
    return []


def _equity_dates(equity: Any) -> list[str]:
    """Pull the ordered list of dates from an equity_curve_daily payload."""
    bars: Any = None
    if isinstance(equity, dict):
        bars = equity.get("daily") or equity.get("curve") or equity.get("bars")
    elif isinstance(equity, list):
        bars = equity
    if not isinstance(bars, list):
        return []
    out = []
    for bar in bars:
        if isinstance(bar, dict):
            d = bar.get("date") or bar.get("timestamp")
            if d:
                out.append(str(d))
    return out


def _period_days(first: str | None, last: str | None) -> int:
    """Inclusive day-span between two ISO timestamps; 0 if unparseable."""
    if not first or not last:
        return 0
    try:
        a = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        return abs((b - a).days)
    except (ValueError, TypeError):
        return 0


def _roll_up(
    positions: list[dict],
    history: list[dict],
    equity_dates: list[str],
    portfolio: Any,
) -> dict:
    """Build the portfolio-level summary from history + portfolio_state."""
    # Latest P&L snapshot drives capital / pnl / apy headline numbers.
    last_rec = history[-1] if history else {}
    first_rec = history[0] if history else {}

    first_ts = first_rec.get("timestamp") if first_rec else None
    last_ts = last_rec.get("timestamp") if last_rec else None
    # Fall back to the equity curve for the reporting window if history lacks ts.
    if not first_ts and equity_dates:
        first_ts = equity_dates[0]
    if not last_ts and equity_dates:
        last_ts = equity_dates[-1]

    total_actual = None
    total_target = None
    num_positions = len(positions)
    if isinstance(portfolio, dict):
        total_actual = _as_float(portfolio.get("total_actual_usd"))
        total_target = _as_float(portfolio.get("total_target_usd"))
        np_field = portfolio.get("num_positions")
        if isinstance(np_field, int) and not positions:
            num_positions = np_field
    if total_actual is None and positions:
        total_actual = sum(_as_float(p.get("actual_usd")) or 0.0 for p in positions)
    if total_target is None and positions:
        total_target = sum(_as_float(p.get("target_usd")) or 0.0 for p in positions)

    return {
        "total_capital_usd": _as_float(last_rec.get("total_capital_usd")),
        "total_pnl_usd":     _as_float(last_rec.get("total_pnl_usd")),
        "total_pnl_pct":     _as_float(last_rec.get("total_pnl_pct")),
        "current_apy":       _as_float(last_rec.get("current_apy")),
        "num_positions":     num_positions,
        "period": {
            "first": first_ts,
            "last":  last_ts,
            "days":  _period_days(first_ts, last_ts),
        },
        "total_actual_usd": total_actual,
        "total_target_usd": total_target,
        "history_points":   len(history),
    }


# ─── Public API ────────────────────────────────────────────────────────────────

def compute_pnl_attribution(
    portfolio_path: str | Path = DEFAULT_PORTFOLIO_PATH,
    pnl_history_path: str | Path = DEFAULT_PNL_HISTORY_PATH,
    equity_curve_path: str | Path = DEFAULT_EQUITY_CURVE_PATH,
) -> dict:
    """Compute read-only per-protocol PnL attribution + portfolio roll-up.

    Every source is read defensively; a missing/broken file degrades to an empty
    section, and the function never raises. The returned schema is always stable.

    Args:
        portfolio_path: path to portfolio_state.json.
        pnl_history_path: path to pnl_history.json.
        equity_curve_path: path to equity_curve_daily.json (optional window).

    Returns:
        ``{"protocols": [...], "roll_up": {...}}`` (see module docstring).
    """
    try:
        portfolio = _load_json(portfolio_path)
        history_raw = _load_json(pnl_history_path)
        equity_raw = _load_json(equity_curve_path)

        positions = _extract_positions(portfolio)
        history = _history_records(history_raw)
        equity_dates = _equity_dates(equity_raw)

        # Capital base for the capital_share fraction (sum of actual allocations).
        total_actual = sum(_as_float(p.get("actual_usd")) or 0.0 for p in positions)

        protocols: list[dict] = []
        for pos in positions:
            actual_usd = _as_float(pos.get("actual_usd"))
            target_usd = _as_float(pos.get("target_usd"))
            actual_weight = _as_float(pos.get("actual_weight"))
            target_weight = _as_float(pos.get("target_weight"))

            # capital_share — recomputed from actual_usd so it sums to ~1.0 even
            # when the stored weights are stale or absent.
            if total_actual > 0 and actual_usd is not None:
                capital_share = round(actual_usd / total_actual, 6)
            else:
                capital_share = None

            protocol_apy = _position_apy(pos)
            # Contribution to portfolio APY = effective weight * protocol APY,
            # ONLY when an explicit per-protocol APY exists. Never fabricated.
            weight_for_apy = actual_weight if actual_weight is not None else capital_share
            if protocol_apy is not None and weight_for_apy is not None:
                apy_contribution = round(weight_for_apy * protocol_apy, 6)
            else:
                apy_contribution = None

            protocols.append({
                "protocol":         str(pos.get("protocol", "")) or None,
                "actual_usd":       actual_usd,
                "target_usd":       target_usd,
                "actual_weight":    actual_weight,
                "target_weight":    target_weight,
                "capital_share":    capital_share,
                "protocol_apy":     protocol_apy,
                "apy_contribution": apy_contribution,
            })

        roll_up = _roll_up(positions, history, equity_dates, portfolio)
        return {"protocols": protocols, "roll_up": roll_up}

    except Exception as exc:  # noqa: BLE001 — never let attribution crash callers
        log.error("compute_pnl_attribution failed unexpectedly: %s", exc, exc_info=True)
        return _empty_attribution()


def _empty_attribution() -> dict:
    """Stable empty attribution payload (used on catastrophic failure)."""
    return {
        "protocols": [],
        "roll_up": {
            "total_capital_usd": None,
            "total_pnl_usd":     None,
            "total_pnl_pct":     None,
            "current_apy":       None,
            "num_positions":     0,
            "period": {"first": None, "last": None, "days": 0},
            "total_actual_usd":  None,
            "total_target_usd":  None,
            "history_points":    0,
        },
    }
