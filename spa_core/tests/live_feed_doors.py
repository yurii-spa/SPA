"""The shared live-feed DOORS the test suite walks through, and how to shut them.

Why this exists (2026-08-16, card ``agent-tests-reach-live-feed-222``)
----------------------------------------------------------------------
``network_guard`` answers "did anything reach the live network?" and the answer
has been **no** since cycle #93 — every attempt gets a fail-CLOSED ``OSError``.
That is not the same question as "did any test *try*", and the ledger says a lot
of them do: the refusals are production code under test reaching for a feed and
being turned back at the transport.

The cost is not bandwidth (nothing goes out). It is that **a suite whose green
depends on a refusal is green for a reason the code does not own**: the same
test passes when the thing it means to check is broken, because both the working
path and the broken path end in the same ``None``. That is the class this repo
keeps closing, and it has already cost real diagnosis time — two days in a row
(2026-08-06/07) a diagnosis was built on suite behaviour that turned out to
depend on the environment rather than on the code.

Why doors and not 222 test edits
--------------------------------
The card is explicit that mechanically rewriting 222 tests would turn "222
honest 'I check the wrong thing'" into "222 silent 'I check nothing'".  So the
work is done where the tests share an entrance:

===========================  ==================================================
door                         seam used to shut it
===========================  ==================================================
DeFiLlama yields/TVL feed    ``spa_core.adapters.config.DEFILLAMA_ENABLED`` —
                             an EXISTING switch.  ``DeFiLlamaFeed._fetch_pools``
                             returns ``None`` for a disabled feed on the very
                             line the network-failure branch returns ``None``,
                             so what a test observes is unchanged.
perp funding / price venues  ``spa_core.strategy_lab.data._http.OFFLINE`` —
(Binance, Bybit, OKX,        raises the SAME ``FetchError`` the refused fetch
KuCoin, Hyperliquid) and     already raised, without opening a socket.
every other rates-desk feed
DeFiLlama pools + CoinGecko  ``spa_core.feeds.defi_llama_feed.ENABLED`` — the
markets, via the SECOND      module's own documented "disabled" branch, read at
DeFiLlama client             CALL time so the process-wide ``_SINGLETON`` cannot
                             freeze one test's answer for the whole run.
===========================  ==================================================

There are **two** DeFiLlama clients (``adapters/defillama_feed.py`` and
``feeds/defi_llama_feed.py``) and shutting one is not shutting "DeFiLlama":
measured, closing only the first left 616 of 823 residual refusals going out
through the second.  A door is not closed until it is closed by measurement.

Both are **identities, not relaxations** (invariant #16): the observable result
at every call site is the one the refusal already produced.  What disappears is
the attempt — and with it the false impression that the suite exercised a feed.

Opting a test back out
----------------------
A test whose SUBJECT is the transport (the guard's own end-to-end pins, the feed
clients' gzip/retry/parse tests) needs the door open, and says so explicitly
with ``@pytest.mark.live_feed_transport`` (module-level ``pytestmark`` works for
``unittest.TestCase`` too).  The mark is registered in ``pytest.ini``.  Such a
test still cannot reach the network — ``network_guard`` is untouched and refuses
it exactly as before.  The mark only says "the attempt is the point here".
"""
from __future__ import annotations

from typing import Any, Dict

#: Name of the marker that re-opens the doors for one test.
MARKER = "live_feed_transport"


def _adapters_config():
    import spa_core.adapters.config as cfg

    return cfg


def _strategy_lab_http():
    from spa_core.strategy_lab.data import _http

    return _http


def _feeds_defillama():
    import spa_core.feeds.defi_llama_feed as feed

    return feed


def close() -> Dict[str, Any]:
    """Shut every shared door; return the previous state for :func:`restore`.

    Imports are done here rather than at module import so that loading this
    file never drags the adapter/strategy-lab packages into a conftest.
    """
    cfg = _adapters_config()
    http = _strategy_lab_http()
    feed = _feeds_defillama()
    previous = {
        "DEFILLAMA_ENABLED": cfg.DEFILLAMA_ENABLED,
        "OFFLINE": http.OFFLINE,
        "FEEDS_ENABLED": feed.ENABLED,
    }
    cfg.DEFILLAMA_ENABLED = False
    http.OFFLINE = True
    feed.ENABLED = False
    return previous


def restore(previous: Dict[str, Any]) -> None:
    """Put the doors back exactly as they were before :func:`close`."""
    _adapters_config().DEFILLAMA_ENABLED = previous["DEFILLAMA_ENABLED"]
    _strategy_lab_http().OFFLINE = previous["OFFLINE"]
    _feeds_defillama().ENABLED = previous["FEEDS_ENABLED"]


def are_closed() -> bool:
    """``True`` when every door is currently shut. Read by this module's tests."""
    return (
        _adapters_config().DEFILLAMA_ENABLED is False
        and _strategy_lab_http().OFFLINE is True
        and _feeds_defillama().ENABLED is False
    )
