#!/usr/bin/env python3
"""Shared read-only helpers for the enhanced attribution/reporting suite (MP-1236).

Pure stdlib, offline, STRICTLY READ-ONLY (SPA-BL-011): consumes ``data/*.json``,
never touches execution / risk policy / wallets. Three reporting modules build on
this helper:

* :mod:`spa_core.reporting.performance_attributor` → ``data/performance_attribution.json``
* :mod:`spa_core.reporting.tear_sheet_hf`           → ``data/tear_sheet.json``
* :mod:`spa_core.reporting.benchmark_comparator`    → ``data/benchmark_comparison.json``

Conventions deliberately match the existing track tooling
(``risk_metrics.py`` / ``tear_sheet.py``):

* ``equity_curve_daily.json`` daily bars carry returns in **percent units**
  (``daily_return_pct`` of ``0.0108`` means 0.0108 %, NOT 1.08 %).
* The seed bar (first bar of a track, ``daily_return_pct == 0.0``) is excluded
  from return statistics, exactly like ``risk_metrics._daily_returns``.
* Annualisation uses 365 days (``risk_metrics.ANNUALIZATION_DAYS``).

The "honest" track is the post-warm-up segment (bars with ``is_warmup`` falsy),
which is the real paper track that began 2026-06-10. We rebuild
``daily_return_pct`` / ``cumulative_return_pct`` / ``drawdown_pct`` from
``close_equity`` inside the chosen segment so the warm-up→real capital reset does
not leak a spurious drawdown into the real-track metrics.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional

# Reuse existing primitives by import (no duplication of these well-tested fns).
from spa_core.paper_trading.risk_metrics import (  # noqa: F401
    ANNUALIZATION_DAYS,
    compute_risk_metrics,
)
from spa_core.reporting.tear_sheet import content_fingerprint  # noqa: F401
from spa_core.utils.atomic import atomic_save

DEFAULT_DATA_DIR = "data"

# Annual benchmark APYs (percent) used across the suite — single source of truth.
TBILL_APY_PCT = 5.0          # US T-Bills, risk-free baseline
STETH_APY_PCT = 3.5          # ETH staking (stETH)
AAVE_CONSERVATIVE_APY_PCT = 3.8  # single-protocol Aave-only conservative
RISK_FREE_ANNUAL_PCT = 4.5   # risk-free for Sharpe/Sortino (hedge-fund convention)

DISCLAIMER = (
    "Advisory / read-only. Paper-trading track ($100k virtual USDC); not "
    "investment advice. Past simulated performance does not guarantee future "
    "results. Attribution uses capital-weighted decomposition over available "
    "daily bars — see per-field notes for approximations."
)


def now_iso() -> str:
    """Current UTC timestamp, ISO-8601. Isolated so it is trivial to monkeypatch."""
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path | str, default: Any = None) -> Any:
    """Read JSON defensively. Missing / corrupt → ``default`` (never raises)."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def atomic_write_json(path: Path | str, obj: Any) -> None:
    """Atomic JSON write via the centralised helper (tmp + os.replace)."""
    atomic_save(obj, str(path))


def load_equity_curve(data_dir: str | Path = DEFAULT_DATA_DIR) -> List[dict]:
    """Return the ``daily`` bar list from ``equity_curve_daily.json`` (or [])."""
    doc = read_json(Path(data_dir) / "equity_curve_daily.json", default={})
    if not isinstance(doc, dict):
        return []
    daily = doc.get("daily")
    return [b for b in daily if isinstance(b, dict)] if isinstance(daily, list) else []


def real_track_bars(daily: Iterable[dict]) -> List[dict]:
    """Post-warm-up bars (the honest track). Falls back to all bars if none."""
    real = [b for b in daily if not b.get("is_warmup")]
    return real if real else list(daily)


def _close(bar: dict) -> Optional[float]:
    for key in ("close_equity", "equity", "nav"):
        v = bar.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def rebuild_curve(bars: List[dict]) -> List[dict]:
    """Re-derive a clean metrics curve from ``close_equity`` within ``bars``.

    Produces bars with the schema ``risk_metrics.compute_risk_metrics`` expects:
    ``date`` / ``daily_return_pct`` / ``cumulative_return_pct`` / ``drawdown_pct``
    / ``close_equity``. The first bar is a 0.0-return seed; drawdown is computed
    against the running peak *within this segment only* (no warm-up leakage).
    Returns ``[]`` when fewer than one usable close exists.
    """
    closes: List[tuple[str, float]] = []
    for b in bars:
        c = _close(b)
        if c is not None:
            closes.append((str(b.get("date", "")), c))
    if not closes:
        return []

    # Anchor the seed on the first bar's OPEN if available, so day-1 yield counts.
    first_open = bars[0].get("open_equity") if bars else None
    base = float(first_open) if isinstance(first_open, (int, float)) else closes[0][1]

    curve: List[dict] = []
    peak = base
    prev = base
    start = base
    for i, (date, close) in enumerate(closes):
        ret = 0.0 if (i == 0 and base == closes[0][1]) else (close / prev - 1.0) * 100.0
        peak = max(peak, close)
        dd = (close / peak - 1.0) * 100.0 if peak > 0 else 0.0
        cum = (close / start - 1.0) * 100.0 if start > 0 else 0.0
        curve.append({
            "date": date,
            "close_equity": round(close, 6),
            "daily_return_pct": round(ret, 6),
            "cumulative_return_pct": round(cum, 6),
            "drawdown_pct": round(dd, 6),
        })
        prev = close
    return curve


def daily_returns_pct(curve: List[dict]) -> List[float]:
    """Realised daily returns (%) excluding the seed bar — risk_metrics convention."""
    return [float(b["daily_return_pct"]) for b in curve[1:]]


def annualize_return_pct(returns_pct: List[float]) -> Optional[float]:
    """Geometric annualised return (%) from a list of daily returns in percent."""
    n = len(returns_pct)
    if n == 0:
        return None
    growth = 1.0
    for r in returns_pct:
        growth *= (1.0 + r / 100.0)
    if growth <= 0:
        return -100.0
    return (growth ** (ANNUALIZATION_DAYS / n) - 1.0) * 100.0


def compound_return_pct(returns_pct: List[float]) -> float:
    """Compounded total return (%) over the supplied daily returns."""
    growth = 1.0
    for r in returns_pct:
        growth *= (1.0 + r / 100.0)
    return (growth - 1.0) * 100.0


def rnd(x: Optional[float], places: int = 4) -> Optional[float]:
    """Round, propagating ``None``."""
    return None if x is None else round(float(x), places)
