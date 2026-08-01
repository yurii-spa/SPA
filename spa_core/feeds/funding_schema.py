"""funding_schema.py — the ONE place that knows how to read what the perp-funding
feed actually writes.

Why this module exists (cycle #78). `spa_core/feeds/perp_funding_feed.py` writes:

    {"timestamp": "<ISO>", "fetched_at": <epoch float>, "stale": <bool>,
     "assets": {"ETH": {"funding_rate_annual": ..., ...}, ...}}

Both consumers — `spa_core/monitoring/bts_monitor.py` and
`spa_core/analytics/bts_exit_monitor.py` — asked for ``rates`` and ``generated_at``,
keys the producer has never written (``git log -S'"rates"'`` on the feed: zero commits).
So every 15 minutes both published "ok / 0 opportunities / clear" about a file they
had not read. Putting the reader here — next to the producer — is deliberate: cycles
#37 and #47 each fixed one copy of a defect and left its twin alive, and these two
consumers are exact twins.

Contract of this module: it NEVER guesses. Anything it could not read comes back as a
verbatim ``unchecked`` reason, so the caller can say "not measured" instead of "fine"
(fail-CLOSED, invariant #2). stdlib only; no I/O — callers own loading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

# What the live producer writes, and the legacy shape the pre-existing test fixtures
# (tests/test_bts_monitor.py, tests/test_bts_exit_monitor.py) build. Both are accepted:
# the live one so the monitors finally measure something, the legacy one so not a single
# existing assertion has to change (invariant #16).
CANONICAL_RATES_KEY = "assets"
LEGACY_RATES_KEY = "rates"

# Age sources, most authoritative first. `fetched_at` is an epoch float; the other two
# are ISO-8601 strings. `generated_at` is the key the monitors used to ask for and is
# kept so legacy payloads keep parsing.
EPOCH_AGE_KEY = "fetched_at"
ISO_AGE_KEYS = ("timestamp", "generated_at")


@dataclass(frozen=True)
class RatesRead:
    """Per-asset funding map, plus WHY it is empty when it is."""

    rates: Dict[str, Any]
    source_key: Optional[str]
    unchecked: Optional[str]

    @property
    def measured(self) -> bool:
        """True when a per-asset map was actually found (it may legitimately be empty)."""
        return self.unchecked is None


@dataclass(frozen=True)
class AgeRead:
    """Feed age in seconds, plus WHY it could not be computed when it could not."""

    age_seconds: Optional[float]
    source_key: Optional[str]
    unchecked: Optional[str]

    @property
    def measured(self) -> bool:
        return self.unchecked is None


def _keys_verbatim(data: Any) -> str:
    if isinstance(data, dict):
        return repr(sorted(str(k) for k in data.keys()))
    return f"payload is {type(data).__name__}, not a mapping"


def read_rates(funding_data: Any) -> RatesRead:
    """Extract the per-asset funding map from a loaded funding payload.

    A key that is PRESENT but empty is a measurement (the feed reported no assets) —
    only a payload carrying neither key, or carrying a non-mapping under one, is
    "not measured".
    """
    if not isinstance(funding_data, dict):
        return RatesRead(
            {},
            None,
            f"funding payload is not a mapping ({type(funding_data).__name__})",
        )

    for key in (CANONICAL_RATES_KEY, LEGACY_RATES_KEY):
        if key not in funding_data:
            continue
        value = funding_data[key]
        if isinstance(value, dict):
            return RatesRead(value, key, None)
        return RatesRead(
            {},
            None,
            f"funding payload key {key!r} is {type(value).__name__}, not a mapping",
        )

    return RatesRead(
        {},
        None,
        (
            f"funding payload has neither {CANONICAL_RATES_KEY!r} (what the live feed "
            f"writes) nor {LEGACY_RATES_KEY!r}; top-level keys: {_keys_verbatim(funding_data)}"
        ),
    )


def feed_age_seconds(funding_data: Any, now: Optional[datetime] = None) -> AgeRead:
    """Age of the funding payload in seconds, or a verbatim reason it is unknown."""
    if not isinstance(funding_data, dict):
        return AgeRead(
            None,
            None,
            f"funding payload is not a mapping ({type(funding_data).__name__})",
        )

    reference = now or datetime.now(timezone.utc)

    raw_epoch = funding_data.get(EPOCH_AGE_KEY)
    if raw_epoch is not None and not isinstance(raw_epoch, bool):
        try:
            return AgeRead(
                reference.timestamp() - float(raw_epoch), EPOCH_AGE_KEY, None
            )
        except (TypeError, ValueError):
            pass  # fall through to the ISO keys; the reason is reported below if all fail

    for key in ISO_AGE_KEYS:
        raw_iso = funding_data.get(key)
        if not isinstance(raw_iso, str) or not raw_iso:
            continue
        try:
            parsed = datetime.fromisoformat(raw_iso.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return AgeRead((reference - parsed).total_seconds(), key, None)

    return AgeRead(
        None,
        None,
        (
            f"no readable age: {EPOCH_AGE_KEY!r}/{'/'.join(repr(k) for k in ISO_AGE_KEYS)} "
            f"absent or unparseable; top-level keys: {_keys_verbatim(funding_data)}"
        ),
    )


def read_feed(
    funding_data: Any, now: Optional[datetime] = None
) -> Tuple[RatesRead, AgeRead]:
    """Both reads at once — the shape every consumer needs."""
    return read_rates(funding_data), feed_age_seconds(funding_data, now=now)
