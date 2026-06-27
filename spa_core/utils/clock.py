"""Deterministic, deprecation-free UTC clock helper (Task 9, Block D hygiene).

Why this module exists
======================
Python 3.12 deprecates :func:`datetime.datetime.utcnow`. The naive sweep
``datetime.utcnow()`` → ``datetime.now(timezone.utc)`` is **NOT** behavior-
preserving:

* ``datetime.utcnow()`` returns a **NAIVE** datetime (``tzinfo is None``).
* ``datetime.now(timezone.utc)`` returns an **AWARE** datetime (``tzinfo=UTC``).

That difference is load-bearing across this codebase:

* ``.isoformat()`` on a NAIVE value yields ``"2026-06-27T08:00:00.123456"``
  (no offset); on an AWARE value it yields ``"...+00:00"``. Many ``data/*.json``
  state files persist these strings verbatim, and several tests assert on the
  exact shape. Swapping to aware would silently append ``+00:00`` everywhere.
* Naive-vs-aware comparison / subtraction raises ``TypeError``. A mixed sweep
  could turn a working ``utcnow() - parsed_naive_ts`` into a crash.

The least-risk modernization is therefore a helper that returns the **same
value the old ``utcnow()`` did** — a naive UTC datetime — while using the
non-deprecated API underneath:

    datetime.now(timezone.utc).replace(tzinfo=None)

This is byte-identical to the old ``datetime.utcnow()`` (same wall-clock value,
same ``tzinfo is None``, same ``.isoformat()`` output, same arithmetic/compare
semantics) and emits no DeprecationWarning. Stdlib-only, deterministic, no LLM.

Use :func:`utcnow` as a drop-in for ``datetime.utcnow()``. When a caller
genuinely needs a tz-aware value (later tz math), use :func:`utcnow_aware`
explicitly — do not reach for it by default.
"""
from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["utcnow", "utcnow_aware"]


def utcnow() -> datetime:
    """Naive UTC datetime — drop-in for the deprecated ``datetime.utcnow()``.

    Byte-identical to ``datetime.utcnow()``: ``tzinfo is None``, so
    ``.isoformat()`` carries no ``+00:00`` offset and naive comparison /
    arithmetic semantics are preserved. No deprecation warning.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Tz-aware UTC datetime (``tzinfo=timezone.utc``).

    Only for callers that explicitly need awareness (tz-aware arithmetic);
    NOT a drop-in for ``datetime.utcnow()`` — its ``.isoformat()`` appends
    ``+00:00``.
    """
    return datetime.now(timezone.utc)
