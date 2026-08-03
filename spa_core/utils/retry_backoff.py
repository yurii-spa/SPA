"""Tell a failure that *can* succeed on a retry from one that cannot.

Why this exists (2026-08-03, cycle #103, card
``agent-offline-suite-still-pays-full-retry-backoff``)
------------------------------------------------------------------------------
Every HTTP helper in the transport layer implements the same loop: *call —
failed — sleep — call again*.  The sleep is the whole point when the failure is
**transient** (a rate limit, a dropped connection, a slow venue): waiting is
what makes the next attempt more likely to work.

Since ``spa_core/tests/network_guard.py`` (cycle #93) the suite runs offline,
and there the failure is **deterministic**: the guard raises
:class:`~spa_core.tests.network_guard.LiveNetworkAccessAttempted` on every
single attempt, by construction, for as long as it is installed.  The backoff
then waits for an event that is excluded — measured on ONE test
(``test_breadth_flag_on_widens_universe``, 28.37 s wall):

```
  12.00s  defi_llama_feed.py get_apy  <- _load_pools <- _fetch_with_retry
  12.00s  defi_llama_feed.py get_tvl  <- _load_pools <- _fetch_with_retry
   2.00s  pendle_adapter.py _fetch_eligible <- pendle_pt._http_get_with_retry
  TOTAL slept: 26.00s of 28.37s
```

That is the "plateau at 49 %" two earlier cycles (#54, #90) misread as a
network hang.  It is not a correctness bug — the tests are green and the
fail-CLOSED contract holds — it is pure cost, paid on every local run and in
CI.

The contract
------------
An exception may advertise that retrying it is pointless by carrying a truthy
:data:`DETERMINISTIC_FAILURE_ATTR` attribute (on the instance or the class).
:func:`is_retryable` is the only reader.  A retry loop that consults it skips
the backoff **and** the remaining attempts, and then takes exactly the same
failure path it would have taken after exhausting them — so the caller-visible
outcome is unchanged, only the waiting is gone.

**Production behaviour is provably unchanged.**  The attribute is set in
exactly one place in the repository — the test guard's exception class, which
lives under ``spa_core/tests/`` and is never imported by runtime code — so in
production ``getattr(exc, DETERMINISTIC_FAILURE_ATTR, False)`` is ``False`` for
every exception that can reach these loops, and every backoff still happens.
``spa_core/tests/test_retry_backoff_deterministic.py`` pins that claim with a
repo-wide scan, so a future "just mark this one too" cannot quietly turn a
transient production failure into a no-retry one.

Deliberately NOT an assertion-level change (invariant #16): no test is made
less strict, no adapter starts inventing a value.  Adapters keep returning
``None`` / re-raising on a dead feed, which is what
``.claude/rules/adapters.md`` requires.
"""
from __future__ import annotations

#: Attribute name an exception carries to say "retrying me cannot help".
#: Read via ``getattr(exc, ..., False)`` so anything that does not set it — i.e.
#: every exception in the production path — keeps the full backoff.
DETERMINISTIC_FAILURE_ATTR = "spa_deterministic_failure"

__all__ = ["DETERMINISTIC_FAILURE_ATTR", "is_retryable"]


def is_retryable(exc: BaseException) -> bool:
    """``False`` only when *exc* declares itself a deterministic failure.

    Fail-OPEN towards retrying on purpose: an unknown exception is treated as
    transient and keeps its backoff, so the guarantee this module weakens is
    never the production one.
    """
    return not bool(getattr(exc, DETERMINISTIC_FAILURE_ATTR, False))
