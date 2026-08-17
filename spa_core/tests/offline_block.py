"""The ``tests/`` root's blanket offline block — as a WRAPPER, not an assignment.

Why this module exists (2026-08-17, card
``inbox-storozh-telegram-dverei-vybivaet-storozh``)
------------------------------------------------------------------------------
``tests/conftest.py`` has carried a blanket offline block since SPA-D003, and
it installed it the only way that is guaranteed to destroy everyone else's
work::

    _urllib_req.urlopen = _blocked_urlopen        # plain assignment

Measured on the shipped code, in the order a repo-root run actually loads the
two conftests::

    1. spa_core conftest: network_guard.install()   chain=2  network_guard -> urlopen
    2. spa_core conftest: telegram_guard.install()  chain=3  telegram_guard -> network_guard -> urlopen
    3. tests/conftest.py PLAIN ASSIGNMENT           chain=1  _blocked_urlopen
                                                    ng.is_installed=False  tg.is_installed=False
    4. tests/conftest.py telegram_guard.install()   chain=2  telegram_guard -> _blocked_urlopen
                                                    ng.is_installed=False   <-- network guard GONE
    5. first test, autouse repair                   chain=4  telegram_guard -> network_guard
                                                             -> telegram_guard(retired) -> _blocked_urlopen
       clobbers: [('spa_core/tests/test_doc_drift.py::test_canonical_dr_doc_exists', 'urlopen')]

Step 3 is the defect: one line removes BOTH guards, step 4 puts back only one,
and the network guard returns at step 5 — attributed to whichever test happened
to run first.  Hence the end-of-run banner ``network guard was RE-INSTALLED
mid-run`` naming an innocent file (reproduced verbatim with two files:
``pytest spa_core/tests/test_doc_drift.py tests/test_adapter_registry.py``).

What changed, and what deliberately did NOT
------------------------------------------------------------------------------
The block is now a layer like the other two: it wraps whatever is current,
publishes ``__wrapped__`` so the chain stays walkable, carries a marker so it
is idempotent at any depth, and never replaces anything.

Its *rule* is unchanged in effect but split across the two layers that already
exist, because a layer that refuses everything makes every layer beneath it
unreachable — and an unreachable :mod:`network_guard` is exactly the fail-OPEN
this repo keeps closing (its ledger would stay empty while three tests assert
on it).  So:

* **loopback / unparseable URLs** are refused HERE, with :class:`OfflineError`
  — that is the part the ``tests/`` root has always been stricter about than
  :mod:`network_guard`, which allows local servers on purpose;
* **everything else** is delegated down to :mod:`network_guard`, which refuses
  it with ``LiveNetworkAccessAttempted`` and *records* the refusal.

Both are ``OSError``, which is the documented contract every caller under test
already takes (``_OfflineError`` subclassed ``OSError`` for the same reason).
No call that used to be refused is now allowed: ``tests/conftest.py`` installs
:mod:`network_guard` alongside this block, so the "everything else" branch
always meets a guard — including in a ``pytest tests/`` run, which previously
had no socket-level backstop at all.

The loopback rule is not re-implemented here: it is asked of
:mod:`network_guard` (``is_loopback_url``), so the two layers cannot drift into
disagreeing about which addresses each owns.

Stdlib only.  Import has no side effects; call :func:`install` explicitly.
"""
from __future__ import annotations

import urllib.request
from typing import Any, List


class OfflineError(OSError):
    """Raised instead of a local/unparseable network call in the test suite.

    Kept an ``OSError`` subclass with a ``reason`` attribute, exactly as the
    ``tests/conftest.py::_OfflineError`` it replaces, so callers under test
    take the identical fail-CLOSED path.
    """

    reason = "offline — network disabled in test suite"


#: Marker stamped on this layer's wrapper, so it recognises itself at ANY depth
#: rather than only when it happens to be on top.  The whole point of this
#: module is that install order must not decide the answer.
_MARKER = "_spa_offline_block"

#: How a wrapper points at the callable it delegates to.  All three layers set
#: it; that is what makes the chain walkable instead of guessable.
_WRAPPED_ATTR = "__wrapped__"

#: How deep to follow ``__wrapped__`` before declaring the chain pathological.
_MAX_CHAIN_DEPTH = 32

_real_urlopen = None  # set by install(): the callable this layer delegates to


def urlopen_chain() -> List[Any]:
    """The ``urlopen`` delegation chain, outermost first.  Cycle-safe."""
    chain: List[Any] = []
    current = urllib.request.urlopen
    seen = set()
    for _ in range(_MAX_CHAIN_DEPTH):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, _WRAPPED_ATTR, None)
    return chain


def is_installed() -> bool:
    """``True`` when this layer is SOMEWHERE in the ``urlopen`` chain.

    Walks the chain rather than reading the outermost marker, for the reason
    :func:`telegram_guard.is_installed` had to learn on 2026-08-17: "am I on
    top" is a different question, and answering it as if it were this one makes
    a layer wrap itself a second time whenever a sibling legitimately sits
    above it.
    """
    return any(getattr(link, _MARKER, False) for link in urlopen_chain())


def install(network_guard: Any) -> None:
    """Wrap ``urllib.request.urlopen`` with the offline block.  Idempotent.

    ``network_guard`` is the module object that owns the loopback rule and the
    refusal for every non-loopback address; it is passed in rather than
    imported so both roots keep sharing the ONE module instance that
    ``conftest`` loaded (two copies would mean two ledgers — the failure class
    the guard docstrings describe).
    """
    global _real_urlopen
    if is_installed():
        return
    _real_urlopen = urllib.request.urlopen
    # Bound HERE and read from the closure, never from the module global
    # (cycle #163): install() rebinds that global, so a wrapper reading it would
    # delegate to whatever was installed LAST instead of to what it wraps —
    # which is how the `telegram_guard -> network_guard -> telegram_guard`
    # cycle and its RecursionError were built.
    _base_urlopen = _real_urlopen
    _guard = network_guard

    def _offline_urlopen(req, *args, **kwargs):  # type: ignore[no-untyped-def]
        if _guard.is_loopback_url(req):
            # Local servers are fair game for network_guard but never for this
            # root, which has refused every URL since SPA-D003.
            raise OfflineError("offline — network disabled in test suite")
        # Everything else belongs to network_guard: it refuses it AND records
        # the refusal, which is why this layer must delegate instead of
        # answering for it.
        return _base_urlopen(req, *args, **kwargs)  # type: ignore[misc]

    setattr(_offline_urlopen, _MARKER, True)
    setattr(_offline_urlopen, _WRAPPED_ATTR, _base_urlopen)
    urllib.request.urlopen = _offline_urlopen  # type: ignore[assignment]


def uninstall() -> None:
    """Restore what was current before :func:`install`.  For positive controls."""
    global _real_urlopen
    if _real_urlopen is not None:
        urllib.request.urlopen = _real_urlopen  # type: ignore[assignment]
        _real_urlopen = None
