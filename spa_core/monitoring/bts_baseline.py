"""bts_baseline.py — OUR OWN measured yield, the only honest hurdle for a BTS alert.

Why this module exists (ADR-070 п.12, owner decision 2026-08-07)
----------------------------------------------------------------
`spa_core/monitoring/bts_monitor.py` called an opportunity EXCELLENT at >=100 bps net
over a **hardcoded 5% spot baseline**, and priced it in dollars off a **hardcoded
$20,000** of capital that is not allocated to this sleeve at all.  Measured on a copy of
production data 2026-08-01 (funding ETH −2.18% / BTC +10.95% / SOL +5.07% annual): net
262 / 1575 / 987 bps ⇒ all three "EXCELLENT/ENTER", i.e. the label carried no
information, and the owner-facing message read "Annual PnL $3,150" about money that does
not exist.

The owner's instruction was explicit about the ORDER: make the threshold honest FIRST,
arm the Telegram transport only afterwards.  Arming an unvalidated threshold produces a
weekly false red, and a false red teaches everyone to ignore the channel.

The honest threshold is the alternative use of the same capital: **our own portfolio
yield**, measured from the evidenced paper track (`data/paper_evidence.json`), never a
literal.  Anything that cannot be measured comes back as a verbatim ``unchecked`` reason
so the caller refuses instead of guessing (fail-CLOSED, invariant #2).

stdlib only.  No I/O — the caller owns loading.  ``now`` is an argument, never the wall
clock read behind the caller's back, so freshness logic is testable at any calendar date.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

# The paper-track evidencing window: go-live is judged on a 30-day evidenced track, so
# "our yield" is the same 30 days, not a period invented for this comparison.
OUR_YIELD_WINDOW_DAYS = 30
# A full week. Below that a single day sets the hurdle for the whole sleeve, and one
# day's figure is an annualised daily return — the noisiest number the track produces.
OUR_YIELD_MIN_DAYS = 7
# 48h = two daily cycles. One missed cycle is tolerated; two means the track is not
# current and the hurdle would be a claim about the past.
OUR_YIELD_MAX_AGE_S = 172_800

DAYS_KEY = "days"
APY_KEY = "apy_pct"
DATE_KEY = "date"


@dataclass(frozen=True)
class OurYieldRead:
    """Our own portfolio yield, or a verbatim reason it is unknown.

    ``apy_annual`` is a decimal (0.059 = 5.9%); ``bps`` is the same number in basis
    points, which is the unit the basis-trade spread is expressed in.  Both are ``None``
    when ``unchecked`` is set — there is no "default yield".
    """

    apy_annual: Optional[float]
    bps: Optional[float]
    days_used: int
    window_days: int
    newest_day: Optional[str]
    source: Optional[str]
    unchecked: Optional[str]

    @property
    def measured(self) -> bool:
        return self.unchecked is None

    def to_dict(self) -> dict:
        return {
            "measured": self.measured,
            "apy_pct": round(self.apy_annual * 100, 4) if self.apy_annual is not None else None,
            "bps": round(self.bps, 1) if self.bps is not None else None,
            "days_used": self.days_used,
            "window_days": self.window_days,
            "newest_day": self.newest_day,
            "source": self.source,
            "unchecked": self.unchecked,
        }


def _refusal(reason: str, *, window_days: int, days_used: int = 0,
             newest_day: Optional[str] = None) -> OurYieldRead:
    return OurYieldRead(
        apy_annual=None,
        bps=None,
        days_used=days_used,
        window_days=window_days,
        newest_day=newest_day,
        source=None,
        unchecked=reason,
    )


def _parse_day(record: Any) -> Optional[Tuple[datetime, float]]:
    """One evidenced day → (UTC datetime, apy_pct), or None when unusable."""
    if not isinstance(record, dict):
        return None
    raw_date = record.get(DATE_KEY)
    raw_apy = record.get(APY_KEY)
    if not isinstance(raw_date, str) or isinstance(raw_apy, bool) or raw_apy is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed, float(raw_apy)
    except (TypeError, ValueError):
        return None


def read_our_yield(
    evidence_payload: Any,
    *,
    now: Optional[datetime] = None,
    window_days: int = OUR_YIELD_WINDOW_DAYS,
    min_days: int = OUR_YIELD_MIN_DAYS,
    max_age_s: float = OUR_YIELD_MAX_AGE_S,
) -> OurYieldRead:
    """Our own annual yield from the evidenced paper track.  NEVER raises.

    The statistic is the **median** of the evidenced daily APY over the trailing
    ``window_days``: the median cannot be moved by one freak day, and one freak day is
    exactly what would otherwise set (or erase) the hurdle for a whole week.
    """
    try:
        if not isinstance(evidence_payload, dict):
            return _refusal(
                f"evidence payload is {type(evidence_payload).__name__}, not a mapping",
                window_days=window_days,
            )
        raw_days = evidence_payload.get(DAYS_KEY)
        if not isinstance(raw_days, list):
            return _refusal(
                f"evidence payload has no {DAYS_KEY!r} list; top-level keys: "
                f"{sorted(str(k) for k in evidence_payload.keys())!r}",
                window_days=window_days,
            )

        parsed: List[Tuple[datetime, float]] = []
        for record in raw_days:
            day = _parse_day(record)
            if day is not None:
                parsed.append(day)
        if not parsed:
            return _refusal(
                f"no evidenced day carries both {DATE_KEY!r} and a numeric {APY_KEY!r} "
                f"({len(raw_days)} record(s) present)",
                window_days=window_days,
            )

        parsed.sort(key=lambda item: item[0])
        newest_dt, _ = parsed[-1]
        newest_day = newest_dt.strftime("%Y-%m-%d")
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age_s = (reference - newest_dt).total_seconds()
        if age_s > max_age_s:
            return _refusal(
                f"evidenced track is stale: newest day {newest_day} is {age_s:.0f}s old "
                f"(limit {max_age_s:.0f}s)",
                window_days=window_days,
                days_used=0,
                newest_day=newest_day,
            )

        cutoff = reference - timedelta(days=window_days)
        window = [apy for when, apy in parsed if when >= cutoff]
        if len(window) < min_days:
            return _refusal(
                f"only {len(window)} evidenced day(s) in the last {window_days} days, "
                f"need >= {min_days} before our own yield is a usable hurdle",
                window_days=window_days,
                days_used=len(window),
                newest_day=newest_day,
            )

        median_pct = float(statistics.median(window))
        return OurYieldRead(
            apy_annual=median_pct / 100.0,
            bps=median_pct * 100.0,
            days_used=len(window),
            window_days=window_days,
            newest_day=newest_day,
            source=(
                f"median of {len(window)} evidenced {APY_KEY} day(s) in the trailing "
                f"{window_days} days, newest {newest_day}"
            ),
            unchecked=None,
        )
    except Exception as exc:  # pragma: no cover - the contract is "never raises"
        return _refusal(f"our-yield computation failed: {exc}", window_days=window_days)
