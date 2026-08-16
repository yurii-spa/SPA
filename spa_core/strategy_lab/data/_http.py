"""
spa_core/strategy_lab/data/_http.py — the one stdlib HTTP JSON fetcher used by every feed.

A `Fetcher` is just a callable `url -> parsed_json`. The real one (`http_fetch`) uses urllib
+ gzip; tests inject a FakeFetcher with the same signature so they never touch the network.
Network/parse failures raise (fail-CLOSED — callers must not swallow into a silent default).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import gzip
import json
import urllib.request
from typing import Any

DEFAULT_TIMEOUT = 15
_UA = "spa-strategy-lab/1.0 (+stdlib)"

#: Close this door without opening a socket.  ``False`` in production — nothing in
#: the runtime ever sets it, and `test_live_feed_doors.py` pins that default.
#:
#: Why the switch exists (2026-08-16, card ``agent-tests-reach-live-feed-222``)
#: ---------------------------------------------------------------------------
#: This function is the ONE entrance every rates-desk / DFB feed uses, and the
#: test suite walks through it constantly: measured on the fixed door slice,
#: ``spa_core/tests/test_dfb_alerts.py`` alone attempts 5 perp venues per test
#: (Binance, Bybit, OKX, KuCoin, Hyperliquid) — 75 refusals from 13 tests.  Those
#: attempts were already refused by ``spa_core/tests/network_guard.py``, so the
#: suite was never online; what they cost is time and, worse, honesty — a run
#: whose green depends on a refusal is green for a reason the code does not own.
#:
#: This is NOT a second refusal path.  With the guard installed the attempt ends
#: in ``LiveNetworkAccessAttempted`` (an ``OSError``), which the ``except`` below
#: re-raises as ``FetchError``.  Refusing here raises the SAME ``FetchError`` at
#: the same call sites, so every caller takes the identical documented branch —
#: what changes is that no socket is opened and no wrapper has to unwind.
#:
#: Loopback stays open on purpose: a local test server is not the live network
#: (the same line ``network_guard`` draws), so ``TestClient``-style fixtures and
#: the fund-API port checks keep working with the door shut.
OFFLINE = False

#: Addresses that are not "the live network" — mirrors ``network_guard``.
_LOOPBACK_HOSTS = frozenset(("127.0.0.1", "::1", "localhost", "0.0.0.0", ""))


class FetchError(RuntimeError):
    """Network or transport-level failure fetching a URL. Distinct from InvalidDataError
    (which is a *schema* failure on a successfully fetched body)."""


def _is_live_host(url: str) -> bool:
    """``True`` when ``url`` points somewhere other than loopback."""
    try:
        from urllib.parse import urlsplit

        host = (urlsplit(url.split("#", 1)[0]).hostname or "").lower()
    except Exception:  # noqa: BLE001 — an unparseable URL is treated as live (fail-CLOSED)
        return True
    if host in _LOOPBACK_HOSTS or host.startswith("127."):
        return False
    return True


def http_fetch(url: str, timeout: int = DEFAULT_TIMEOUT, post_json: Any = None) -> Any:
    """Fetch `url` and return parsed JSON. Raises FetchError on any network/transport/parse
    failure. Pins Accept-Encoding: gzip and decompresses manually (urllib does not auto-decode
    when we set the header), matching the repo's DeFiLlama feed convention.

    If `post_json` is given, issues a POST with a JSON body (Content-Type: application/json) —
    used by venues whose query is a request body (e.g. Hyperliquid's /info endpoint). The
    fragment part of `url` (after '#') is stripped before the request — it only carries routing
    hints for the test FakeFetcher and is not part of the real network address."""
    if OFFLINE and _is_live_host(url):
        # Same exception, same call sites, no socket — see OFFLINE above.
        raise FetchError(
            f"fetch refused for {url[:80]}: this door is closed for the test "
            f"suite. Inject a fetcher/feed instead of calling out "
            f"(.claude/rules/adapters.md); mark the test "
            f"`live_feed_transport` if the transport itself is its subject."
        )
    try:
        net_url = url.split("#", 1)[0]
        headers = {"Accept-Encoding": "gzip", "User-Agent": _UA}
        data = None
        if post_json is not None:
            data = json.dumps(post_json).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(net_url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - re-raised as FetchError; never a silent default
        raise FetchError(f"fetch failed for {url[:80]}: {exc}") from exc
