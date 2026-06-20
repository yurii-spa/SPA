"""Simple historical-APY database interface (MP-1238).

Read-only query layer over the per-protocol JSON files produced by
``historical_apy_fetcher`` (``data/historical_apy/<protocol>.json``). Pure
stdlib, no external dependencies. Each file is a daily series
``[{"date": "2025-06-21", "apy": 4.82}, ...]`` with APY as a percentage.

Files are lazily loaded and cached in-process; APY series are sorted by date on
load so range/period queries are well-defined regardless of on-disk order.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

# Default location of the historical APY store (repo ``data/historical_apy``).
DEFAULT_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "historical_apy")
)


def _parse_date(value: str) -> date:
    """Parse an ISO ``YYYY-MM-DD`` string to a ``date``."""
    return datetime.strptime(value, "%Y-%m-%d").date()


class APYDatabase:
    """In-process query layer over the historical APY JSON files."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = os.path.abspath(data_dir) if data_dir else DEFAULT_DATA_DIR
        self._cache: dict[str, list[dict]] = {}

    # --- loading ------------------------------------------------------------

    def _path(self, protocol: str) -> str:
        return os.path.join(self.data_dir, f"{protocol}.json")

    def _load(self, protocol: str) -> list[dict]:
        """Return the cached, date-sorted series for ``protocol`` (or ``[]``)."""
        if protocol in self._cache:
            return self._cache[protocol]
        path = self._path(protocol)
        if not os.path.exists(path):
            self._cache[protocol] = []
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            self._cache[protocol] = []
            return []
        clean = [
            {"date": r["date"], "apy": float(r["apy"])}
            for r in rows
            if isinstance(r, dict) and "date" in r and "apy" in r
        ]
        clean.sort(key=lambda r: r["date"])
        self._cache[protocol] = clean
        return clean

    # --- public API ---------------------------------------------------------

    def list_available_protocols(self) -> list[str]:
        """Return sorted protocol names with a non-empty series on disk."""
        if not os.path.isdir(self.data_dir):
            return []
        out: list[str] = []
        for fn in os.listdir(self.data_dir):
            if fn.endswith(".json"):
                proto = fn[: -len(".json")]
                if self._load(proto):
                    out.append(proto)
        return sorted(out)

    def get_apy_history(
        self,
        protocol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[dict]:
        """Return ``[{date, apy}]`` for ``protocol`` within the inclusive range.

        ``start_date``/``end_date`` are ISO ``YYYY-MM-DD`` strings; either may be
        omitted to leave that bound open. Unknown protocol → ``[]``.
        """
        series = self._load(protocol)
        if start_date is None and end_date is None:
            return list(series)
        lo = _parse_date(start_date) if start_date else None
        hi = _parse_date(end_date) if end_date else None
        out = []
        for row in series:
            d = _parse_date(row["date"])
            if lo is not None and d < lo:
                continue
            if hi is not None and d > hi:
                continue
            out.append(row)
        return out

    def _tail(self, protocol: str, period_days: int) -> list[float]:
        """Return the trailing ``period_days`` APY values for ``protocol``."""
        series = self._load(protocol)
        if period_days > 0:
            series = series[-period_days:]
        return [r["apy"] for r in series]

    def get_average_apy(self, protocol: str, period_days: int = 365) -> float:
        """Mean daily APY (%) over the trailing ``period_days``.

        Returns ``0.0`` when no data is available.
        """
        vals = self._tail(protocol, period_days)
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def get_apy_volatility(self, protocol: str, period_days: int = 365) -> float:
        """Sample standard deviation of daily APY (%) over ``period_days``.

        Uses the n-1 (sample) denominator. Returns ``0.0`` for fewer than two
        observations.
        """
        vals = self._tail(protocol, period_days)
        n = len(vals)
        if n < 2:
            return 0.0
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
        return variance ** 0.5


# Module-level convenience singleton over the default data dir.
_default_db: Optional[APYDatabase] = None


def _db() -> APYDatabase:
    global _default_db
    if _default_db is None:
        _default_db = APYDatabase()
    return _default_db


def get_apy_history(
    protocol: str, start_date: Optional[str] = None, end_date: Optional[str] = None
) -> list[dict]:
    return _db().get_apy_history(protocol, start_date, end_date)


def get_average_apy(protocol: str, period_days: int = 365) -> float:
    return _db().get_average_apy(protocol, period_days)


def get_apy_volatility(protocol: str, period_days: int = 365) -> float:
    return _db().get_apy_volatility(protocol, period_days)


def list_available_protocols() -> list[str]:
    return _db().list_available_protocols()
