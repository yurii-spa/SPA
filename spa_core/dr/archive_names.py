"""
spa_core/dr/archive_names.py — one place that knows how a backup archive is NAMED.

WHY THIS EXISTS (production incident 2026-08-05)
------------------------------------------------
`data/backups/` is written by TWO producers with TWO naming schemes:

    spa_state_20260805T084335Z.tar.gz   ← dr_backup.py      (%Y%m%dT%H%M%SZ)
    spa_state_2026-08-05.tar.gz         ← scripts/daily_backup.py (%Y-%m-%d)

Every consumer ordered them with a plain lexical sort and documented it as
"newest first (the embedded date/ts is sortable)". That is true WITHIN one scheme
and false ACROSS the two: `'-' (0x2D) < '0' (0x30)`, so **every** dashed name sorts
below **every** timestamped name no matter what date it carries. Consequences, both
observed in the production log, not theorised:

  * `dr_backup.prune(keep=14)` kept "the newest 14" and deleted the tail — the tail was
    permanently the entire daily series. 2026-08-04 it swept 15 daily archives in one
    run (`spa_state_2026-07-21` … `spa_state_2026-08-04`); 2026-08-05 it deleted that
    morning's snapshot hours after it was written. The broad 499-file snapshot of all
    of `data/` was being created daily and destroyed daily.
  * `offsite_copy.newest_archive()` could never select a daily archive, so the offsite
    mirror only ever carried the narrow critical-set archive.

Two rules follow, and they live here so no third consumer re-derives them wrongly:

1. **Order by the instant the name encodes, not by the bytes of the name.** Unparseable
   names fall back to mtime — never to lexical position.
2. **A ring buffer deletes only what it owns.** Retention is scoped to a series; an
   archive from another producer (or one whose name we do not recognise) is never
   deleted by someone else's retention.

stdlib-only · no I/O beyond `stat()` for the mtime fallback.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import os
from typing import Iterable, List, Optional, Sequence, Tuple

ARCHIVE_PREFIX = "spa_state_"
ARCHIVE_SUFFIX = ".tar.gz"

#: Timestamped series produced by ``spa_core/backtesting/tier1/dr_backup.py``.
SERIES_DR = "dr"
#: Date-stamped series produced by ``scripts/daily_backup.py``.
SERIES_DAILY = "daily"
#: Anything under the spa_state_*.tar.gz glob we do not recognise. Never auto-deleted.
SERIES_UNKNOWN = "unknown"

_DR_FORMAT = "%Y%m%dT%H%M%SZ"
_DAILY_FORMAT = "%Y-%m-%d"

_UTC = datetime.timezone.utc


def parse_archive_name(name: str) -> Tuple[str, Optional[datetime.datetime]]:
    """``("dr"|"daily"|"unknown", instant-or-None)`` for one archive file NAME.

    The instant is timezone-aware UTC. A daily archive carries no time-of-day, so it is
    anchored at 00:00Z of its date — the honest reading of what the name states.
    """
    base = os.path.basename(name)
    if not base.startswith(ARCHIVE_PREFIX) or not base.endswith(ARCHIVE_SUFFIX):
        return SERIES_UNKNOWN, None
    stem = base[len(ARCHIVE_PREFIX):-len(ARCHIVE_SUFFIX)]
    for series, fmt in ((SERIES_DR, _DR_FORMAT), (SERIES_DAILY, _DAILY_FORMAT)):
        try:
            return series, datetime.datetime.strptime(stem, fmt).replace(tzinfo=_UTC)
        except ValueError:
            continue
    return SERIES_UNKNOWN, None


def archive_series(name: str) -> str:
    """Series of one archive name (see :data:`SERIES_DR` / :data:`SERIES_DAILY`)."""
    return parse_archive_name(name)[0]


def _mtime_instant(path: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path), tz=_UTC)
    except OSError:
        return None


def sort_key(path: str) -> Tuple[datetime.datetime, str]:
    """Ordering key: the instant the NAME encodes, else the file's mtime, else epoch.

    The name is the tie-breaker so ordering stays deterministic for two archives that
    land on the same instant (two daily archives cannot, but a hand-copied file can).
    """
    _series, instant = parse_archive_name(path)
    if instant is None:
        instant = _mtime_instant(path)
    if instant is None:
        instant = datetime.datetime.fromtimestamp(0, tz=_UTC)
    return instant, os.path.basename(path)


def newest_first(paths: Iterable) -> List:
    """The given archive paths, newest first, by :func:`sort_key`. Types are preserved."""
    return sorted(paths, key=lambda p: sort_key(str(p)), reverse=True)


def select_for_retention(paths: Sequence, *, series: str, keep: int) -> Tuple[List, List]:
    """Split *paths* into ``(kept, doomed)`` for a ring buffer that owns ONE *series*.

    Only archives of *series* are candidates for deletion; the newest *keep* of them are
    kept and the rest are doomed. Everything belonging to another producer — or whose name
    we cannot parse — is returned in ``kept`` untouched. This is the fail-CLOSED direction:
    a retention pass that does not recognise a file must leave it alone, never assume the
    file is old because its name sorts low.
    """
    if keep < 0:
        keep = 0
    mine, foreign = [], []
    for p in paths:
        (mine if archive_series(str(p)) == series else foreign).append(p)
    mine = newest_first(mine)
    return newest_first(mine[:keep] + foreign), list(mine[keep:])
