"""spa_core/monitoring/sensors/providers.py — RTMR (ADR-053) keyless price providers.

Owner §13.1: 5–10 FREE, keyless sources in parallel. These are the concrete callables the peg
sensor's multi-source quorum consumes — each returns a USD price for an asset, or None on ANY
failure (so `_multisource.collect` drops it and the quorum stays fail-closed). stdlib-only
(urllib), short timeout, no API keys. Parse functions are split from the network fetch so they
are unit-testable without live calls.

Deterministic wrappers over live feeds; LLM-forbidden. Add TVL/oracle providers here later.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import urllib.request

_TIMEOUT = 8
_UA = {"User-Agent": "spa-rtmr/1.0"}

# canonical asset → per-source identifiers. USD-pegged stables price ≈ 1.0.
_ASSETS: dict[str, dict] = {
    "USDC": {"coingecko": "usd-coin", "binance": "USDCUSDT", "coinbase": "USDC-USD", "kraken": "USDCUSD"},
    "USDT": {"coingecko": "tether", "coinbase": "USDT-USD", "kraken": "USDTZUSD"},
    "DAI": {"coingecko": "dai", "binance": "DAIUSDT", "coinbase": "DAI-USD", "kraken": "DAIUSD"},
    "USDE": {"coingecko": "ethena-usde", "binance": "USDEUSDT"},
    "SUSDE": {"coingecko": "ethena-staked-usde"},
}


def _get_json(url: str):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — trusted public https
        return json.load(r)


# ── parse functions (pure, unit-testable) ───────────────────────────────────────────
def parse_coingecko(payload: dict, cg_id: str) -> float | None:
    try:
        return float(payload[cg_id]["usd"])
    except Exception:  # noqa: BLE001
        return None


def parse_coinbase(payload: dict) -> float | None:
    try:
        return float(payload["data"]["amount"])
    except Exception:  # noqa: BLE001
        return None


def parse_binance(payload: dict) -> float | None:
    # symbol is vs USDT (≈USD for a stable's USD peg proxy)
    try:
        return float(payload["price"])
    except Exception:  # noqa: BLE001
        return None


def parse_kraken(payload: dict) -> float | None:
    try:
        result = payload["result"]
        pair = next(iter(result))
        return float(result[pair]["c"][0])  # last-trade close
    except Exception:  # noqa: BLE001
        return None


def parse_llama(payload: dict, cg_id: str) -> float | None:
    try:
        return float(payload["coins"][f"coingecko:{cg_id}"]["price"])
    except Exception:  # noqa: BLE001
        return None


# ── live provider factories (each returns a zero-arg callable -> price|None) ──────────
def _coingecko(cg_id):
    def fn():
        try:
            return parse_coingecko(_get_json(
                f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"), cg_id)
        except Exception:  # noqa: BLE001 — unavailable source => None (dropped, not zeroed)
            return None
    return fn


def _coinbase(pair):
    def fn():
        try:
            return parse_coinbase(_get_json(f"https://api.coinbase.com/v2/prices/{pair}/spot"))
        except Exception:  # noqa: BLE001
            return None
    return fn


def _binance(symbol):
    def fn():
        try:
            return parse_binance(_get_json(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"))
        except Exception:  # noqa: BLE001
            return None
    return fn


def _kraken(pair):
    def fn():
        try:
            return parse_kraken(_get_json(f"https://api.kraken.com/0/public/Ticker?pair={pair}"))
        except Exception:  # noqa: BLE001
            return None
    return fn


def _llama(cg_id):
    def fn():
        try:
            return parse_llama(_get_json(f"https://coins.llama.fi/prices/current/coingecko:{cg_id}"), cg_id)
        except Exception:  # noqa: BLE001
            return None
    return fn


def price_providers_for(asset: str) -> dict:
    """{source_name: callable()->price|None} for ``asset`` (e.g. 'USDC') across all keyless sources it has."""
    ids = _ASSETS.get(str(asset).upper())
    if not ids:
        return {}
    out: dict = {}
    if "coingecko" in ids:
        out["coingecko"] = _coingecko(ids["coingecko"])
        out["defillama"] = _llama(ids["coingecko"])
    if "coinbase" in ids:
        out["coinbase"] = _coinbase(ids["coinbase"])
    if "binance" in ids:
        out["binance"] = _binance(ids["binance"])
    if "kraken" in ids:
        out["kraken"] = _kraken(ids["kraken"])
    return out


def supported_assets() -> list:
    return sorted(_ASSETS.keys())
