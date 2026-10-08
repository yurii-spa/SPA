"""Owner presentation policy — ONE place for how a percentage and a time are SHOWN.

Owner decision 2026-10-08 (ADR-660, supersedes ADR-563's presentation-only round-down):

* **Percentages** — exactly two digits after the decimal separator, ``ROUND_HALF_UP`` at
  the third digit, locale-aware: RU ``4,89 %`` · EN ``4.89%``. Rounding happens on the
  DECIMAL string of the value, never on its binary float (``2.675`` is stored as
  ``2.67499999…`` and ``round(2.675, 2)`` gives ``2.67``; the policy says ``2.68``).
* **Owner time** — Europe/Madrid, automatic CET/CEST. Machine timestamps stay UTC; this
  module only converts what is SHOWN.

What this module never does (the policy's own prohibitions):

* it does not round source data or intermediate calculations — callers keep the raw
  number and format only at the edge;
* absence is not zero (inv. #17): ``None`` / non-numeric ⇒ the caller's ``unknown`` text
  (default ``None``), never ``0,00 %``;
* a NONZERO value that rounds to ``0.00`` is not printed as an exact zero — it carries a
  qualifier (``<0,01 %`` / ``>-0,01 %``).

Stdlib only (inv. #4). LLM_FORBIDDEN.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

_CENT = Decimal("0.01")
_NBSP = " "

OWNER_TZ_NAME = "Europe/Madrid"


# ── percentages ─────────────────────────────────────────────────────────────


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Exact decimal of what the value SAYS; None for anything that is not a finite number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            return None
        # repr(float) is the SHORTEST string that round-trips: 2.675 → "2.675", the number
        # the producer meant. Decimal(2.675) would instead be 2.67499999999999982236431605997495353221893310546875.
        d = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            d = Decimal(value.strip())
        except InvalidOperation:
            return None
    else:
        return None
    return d if d.is_finite() else None


def pct_half_up(value: Any, *, input: str = "percent") -> Optional[Decimal]:
    """The value in percent, quantized to 0.01 with ROUND_HALF_UP; None when absent.

    ``input="fraction"`` multiplies by 100 first (exactly, in Decimal)."""
    if input not in ("percent", "fraction"):
        raise ValueError(f"input must be 'percent' or 'fraction', got {input!r}")
    d = _to_decimal(value)
    if d is None:
        return None
    if input == "fraction":
        d = d * 100
    return d.quantize(_CENT, rounding=ROUND_HALF_UP)


def fmt_pct(value: Any, lang: str = "ru", *, input: str = "percent", signed: bool = False,
            unknown: Optional[str] = None) -> Optional[str]:
    """``4.8943`` → RU ``4,89 %`` / EN ``4.89%``. Absent ⇒ ``unknown`` (default None)."""
    d = _to_decimal(value)
    if d is None:
        return unknown
    if input == "fraction":
        d = d * 100
    elif input != "percent":
        raise ValueError(f"input must be 'percent' or 'fraction', got {input!r}")
    q = d.quantize(_CENT, rounding=ROUND_HALF_UP)
    ru = lang == "ru"
    suffix = (_NBSP + "%") if ru else "%"

    def _num(x: Decimal) -> str:
        s = f"{x:.2f}"
        return s.replace(".", ",") if ru else s

    if q == 0:
        if d == 0:
            return _num(Decimal("0.00")) + suffix          # a measured zero is a real zero
        # nonzero but below half a hundredth: never an exact-looking zero
        return ("<" + _num(_CENT) + suffix) if d > 0 else (">-" + _num(_CENT) + suffix)
    sign = "-" if q < 0 else ("+" if signed else "")
    return sign + _num(abs(q)) + suffix


# ── owner time (Europe/Madrid) ──────────────────────────────────────────────


def _last_sunday(year: int, month: int) -> date:
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 6) % 7)


def _eu_summer(utc_dt: datetime) -> bool:
    """EU rule (Directive 2000/84/EC): summer time from 01:00 UTC on the last Sunday of March
    to 01:00 UTC on the last Sunday of October."""
    y = utc_dt.year
    start = datetime.combine(_last_sunday(y, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(y, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    return start <= utc_dt < end


def _fallback_zone(utc_dt: datetime) -> tzinfo:
    if _eu_summer(utc_dt):
        return timezone(timedelta(hours=2), "CEST")
    return timezone(timedelta(hours=1), "CET")


def _zoneinfo() -> Optional[tzinfo]:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(OWNER_TZ_NAME)
    except Exception:  # no tz database on the host — the explicit EU rule takes over
        return None


def _parse_utc(ts: Any) -> Optional[datetime]:
    """Aware UTC datetime from a datetime / ISO string / epoch seconds. Naive = UTC (machine stamps)."""
    if isinstance(ts, bool) or ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        if not math.isfinite(ts):
            return None
        dt = datetime.fromtimestamp(ts, timezone.utc)
    elif isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_owner_time(ts: Any, *, use_tzdb: bool = True) -> Optional[datetime]:
    """The instant ``ts`` in Europe/Madrid; None when unreadable. ``use_tzdb=False`` forces
    the explicit EU rule (also used automatically when the host has no tz database)."""
    utc = _parse_utc(ts)
    if utc is None:
        return None
    zone = _zoneinfo() if use_tzdb else None
    return utc.astimezone(zone if zone is not None else _fallback_zone(utc))


def fmt_owner_time(ts: Any, lang: str = "ru", *, with_date: bool = True, label: bool = True,
                   unknown: Optional[str] = None, use_tzdb: bool = True) -> Optional[str]:
    """``2026-10-08T07:30Z`` → ``2026-10-08 09:30 Мадрид (CEST)`` / ``… Madrid (CEST)``."""
    local = to_owner_time(ts, use_tzdb=use_tzdb)
    if local is None:
        return unknown
    body = local.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")
    if not label:
        return body
    city = "Мадрид" if lang == "ru" else "Madrid"
    return f"{body} {city} ({local.tzname()})"
