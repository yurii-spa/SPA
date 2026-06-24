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


class FetchError(RuntimeError):
    """Network or transport-level failure fetching a URL. Distinct from InvalidDataError
    (which is a *schema* failure on a successfully fetched body)."""


def http_fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """Fetch `url` and return parsed JSON. Raises FetchError on any network/transport/parse
    failure. Pins Accept-Encoding: gzip and decompresses manually (urllib does not auto-decode
    when we set the header), matching the repo's DeFiLlama feed convention."""
    try:
        req = urllib.request.Request(
            url, headers={"Accept-Encoding": "gzip", "User-Agent": _UA}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - re-raised as FetchError; never a silent default
        raise FetchError(f"fetch failed for {url[:80]}: {exc}") from exc
