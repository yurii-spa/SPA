"""APY series accumulator — the missing producer for the time-series lane (A1, 2026-08-05).

The `data/historical_apy/*` generator has been dead since 2026-06-30, so 31 of 36
whitelisted protocols hold exactly ONE live point and every series-hungry analytics
module honestly returns None for them. This module closes the loop the cheapest
honest way: once per daily cycle it appends TODAY's live APY point per protocol from
`data/adapter_status.json` into `data/apy_series_daily.json` (one row per protocol
per date, atomic write, idempotent for the same date — re-runs overwrite today's
point, never history).

Rules honored: stdlib-only; atomic_save; live points only (records with a live
source marker or a finite apy) — no fallbacks, no interpolation, missing feed for a
protocol on a day = simply no row (the gap stays visible); read by
`spa_core/analytics/_apy_series.py` as a first-class source.
"""
from __future__ import annotations

import datetime
import json
import logging
import math
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_FILE = "apy_series_daily.json"
_MAX_DAYS = 800  # ring: keep ~2.2 years per protocol, plenty for 30/90/180-day windows


def _is_finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def accumulate(data_dir=None, today: Optional[str] = None) -> dict:
    """Append today's live APY points. Returns a small summary dict (for the cycle log)."""
    ddir = Path(data_dir) if data_dir else Path(__file__).resolve().parents[2] / "data"
    today = today or datetime.date.today().isoformat()

    try:
        adapters = (json.loads((ddir / "adapter_status.json").read_text()) or {}).get("adapters") or {}
    except Exception as exc:  # noqa: BLE001 — no feed file → nothing to accumulate, loudly
        log.warning("apy_series_accumulator: adapter_status.json unreadable (%s) — no points today", exc)
        return {"date": today, "appended": 0, "skipped": 0, "error": "adapter_status unreadable"}

    path = ddir / _FILE
    try:
        book = json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        # A corrupt accumulator must not kill the cycle; refuse to overwrite it blindly.
        log.warning("apy_series_accumulator: %s corrupt — leaving it untouched, no append", _FILE)
        return {"date": today, "appended": 0, "skipped": 0, "error": f"{_FILE} corrupt"}

    series = book.get("series") or {}
    appended = skipped = 0
    for name, info in adapters.items():
        if not isinstance(info, dict):
            continue
        apy = info.get("live_apy", info.get("apy"))
        # Live-only discipline: a static/fallback record without a finite apy adds nothing.
        if not _is_finite(apy):
            skipped += 1
            continue
        rows = series.get(name) or []
        rows = [r for r in rows if not (isinstance(r, list) and r and r[0] == today)]
        rows.append([today, round(float(apy), 6)])
        series[name] = rows[-_MAX_DAYS:]
        appended += 1

    book = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "apy_series_accumulator (daily cycle hook)",
        "note": "date-keyed live APY percent points; gaps = feed was down that day (never interpolated)",
        "series": series,
    }
    from spa_core.utils.atomic import atomic_save
    atomic_save(book, str(path))
    return {"date": today, "appended": appended, "skipped": skipped}
