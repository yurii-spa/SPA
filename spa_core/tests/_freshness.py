"""Test helpers for anything with a freshness window — make the right thing easy.

Why this file exists. On 2026-08-04 an evidence-age window was introduced, and
three test files broke the same day — not because behaviour changed, but because
their fixtures held literal dates (``"2026-08-02T06:00:00+00:00"``) that had
simply drifted out of the window. A test that fails because the calendar moved
says nothing about the code and trains people to "fix" fixtures instead of bugs.

Two safe patterns, in order of preference:

1. **Inject the clock.** If the code under test accepts ``now=``, pass a fixed
   ``now`` AND fixed timestamps. Both sides are pinned, the test is immune to the
   calendar forever, and it reads as a statement about behaviour.

       ev = _load_evidenced_apy(orch, st, now=at("2026-08-02T12:00:00+00:00"))

2. **Relative timestamps.** When the clock cannot be injected, express fixtures
   as ages: ``ts(hours_ago=6)`` instead of a literal date.

Use a literal date ONLY when the date itself is the subject (parsing, a golden
file, a historical incident). Then mark it ``# FROZEN-DATE-OK: <reason>`` so the
ratchet guard knows it was a decision rather than an oversight.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now_utc() -> datetime:
    """Timezone-aware current time — never use a naive datetime in fixtures."""
    return datetime.now(timezone.utc)


def ts(hours_ago: float = 0.0) -> str:
    """ISO-8601 timestamp ``hours_ago`` in the past (negative = future)."""
    return (now_utc() - timedelta(hours=hours_ago)).isoformat()


def at(iso: str) -> datetime:
    """Parse a literal ISO timestamp for use as an injected ``now``.

    Pair with literal fixture timestamps: pinning both sides is what makes a
    fixed date safe.
    """
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hours_between(later: str, earlier: str) -> float:
    """Age in hours between two ISO timestamps — for asserting on windows."""
    return (at(later) - at(earlier)).total_seconds() / 3600.0
