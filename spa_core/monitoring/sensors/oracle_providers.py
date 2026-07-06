"""spa_core/monitoring/sensors/oracle_providers.py — RTMR (ADR-053) keyless Chainlink oracle reader.

Reads Chainlink USD price feeds ON-CHAIN via keyless public RPCs (eth_call latestRoundData()), so the
oracle sensor can check (a) staleness — how long since the feed updated — and (b) deviation — oracle
price vs the CEX/DEX market quorum. Multiple public RPCs give redundancy (fail-closed if all are down).

stdlib only (urllib JSON-RPC + manual hex decode of the ABI words); LLM-forbidden. USD feeds are
8-decimals. latestRoundData() returns 5 words: roundId, answer, startedAt, updatedAt, answeredInRound.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import urllib.request

from spa_core.utils.errors import SourceError

_TIMEOUT = 4  # short: a slow RPC must not block the sense tick
_HDR = {"User-Agent": "spa-rtmr/1.0", "Content-Type": "application/json"}

# keyless public Ethereum RPCs (redundancy)
_RPCS = [
    "https://ethereum.publicnode.com",
    "https://rpc.ankr.com/eth",
    "https://cloudflare-eth.com",
]

_LATEST_ROUND_DATA = "0xfeaf968c"  # keccak('latestRoundData()')[:4]

# Chainlink stablecoin feeds update on a ~24h heartbeat, so re-reading every 45s tick is pointless
# and (on a slow RPC) would block the sense loop. Cache the last good (price, updated_at) per feed.
_READ_CACHE: dict = {}
_READ_TTL = 300  # seconds

# Chainlink mainnet USD aggregators (8 decimals)
_FEEDS = {
    "USDC": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
    "USDT": "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D",
    "DAI": "0xAed0c38402a5d19df6E4c03F4E2DceD6e29c1ee9",  # verified live: returns ~$1.00
}
_DECIMALS = 8


def _eth_call(rpc: str, to: str, data: str) -> str | None:
    payload = json.dumps({"jsonrpc": "2.0", "method": "eth_call",
                          "params": [{"to": to, "data": data}, "latest"], "id": 1}).encode()
    try:
        req = urllib.request.Request(rpc, data=payload, headers=_HDR)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — trusted public https
            return json.load(r).get("result")
    except Exception:  # noqa: BLE001 — RPC unreachable → try the next
        return None


def parse_latest_round_data(result_hex: str, decimals: int = _DECIMALS):
    """Decode latestRoundData() → (price, updated_at_unix). Returns None on malformed data."""
    try:
        h = result_hex[2:] if result_hex.startswith("0x") else result_hex
        words = [h[i:i + 64] for i in range(0, len(h), 64)]
        if len(words) < 5:
            return None
        answer = int(words[1], 16)                 # int256 answer (price × 10^decimals)
        # two's-complement guard (prices are positive, but be correct)
        if answer >= 2 ** 255:
            answer -= 2 ** 256
        updated_at = int(words[3], 16)             # uint updatedAt (unix)
        if answer <= 0 or updated_at <= 0:
            return None
        return (answer / (10 ** decimals), updated_at)
    except Exception:  # noqa: BLE001
        return None


def chainlink_reader(address: str, decimals: int = _DECIMALS):
    """callable() → (price, updated_at). Cached (~5 min) so a slow RPC never blocks the tick; on a
    cache miss, tries the public RPCs (first that answers). Serves the last good value while re-reading
    fails, up to the TTL — after which a persistent failure surfaces as stale (fail-closed)."""
    import time as _t

    def fn():
        now = _t.time()
        cached = _READ_CACHE.get(address)
        if cached and (now - cached[1]) < _READ_TTL:
            return cached[0]
        for rpc in _RPCS:
            res = _eth_call(rpc, address, _LATEST_ROUND_DATA)
            if res and res != "0x":
                parsed = parse_latest_round_data(res, decimals)
                if parsed is not None:
                    _READ_CACHE[address] = (parsed, now)
                    return parsed
        if cached:            # RPCs down but we have a recent value within TTL → serve it
            return cached[0]
        raise SourceError("all RPCs failed for Chainlink feed")  # → sensor treats as stale critical
    return fn


def oracle_feeds(assets: list | None = None) -> dict:
    """{scope: {'oracle': reader, 'market': {src: price_cb}}} for assets that have a Chainlink feed."""
    from spa_core.monitoring.sensors.providers import price_providers_for
    assets = assets or list(_FEEDS.keys())
    out: dict = {}
    for a in assets:
        addr = _FEEDS.get(str(a).upper())
        market = price_providers_for(a)
        if addr and market:
            out[a] = {"oracle": chainlink_reader(addr), "market": market}
    return out
