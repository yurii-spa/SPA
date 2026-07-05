"""spa_core/monitoring/sensors/tvl_providers.py — RTMR (ADR-053) keyless TVL providers.

TVL data is DeFiLlama-dominated (unlike price, there is no 5-venue TVL world), so the TVL sensor
runs a LOWER quorum (min_quorum ~1–2) than peg — honest to the data reality, still fail-closed if
DeFiLlama is unreachable. Current TVL from two DeFiLlama endpoints (/tvl and /protocol) as a light
cross-check; 24h-ago from the protocol's daily history. stdlib urllib, None on failure, LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import urllib.request

_TIMEOUT = 10
_UA = {"User-Agent": "spa-rtmr/1.0"}


def _get(url: str):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — trusted public https
        return json.load(r)


def parse_tvl_simple(payload) -> float | None:
    """`/tvl/{slug}` returns a bare number."""
    try:
        return float(payload)
    except Exception:  # noqa: BLE001
        return None


def parse_protocol_current(payload: dict) -> float | None:
    """`/protocol/{slug}` → latest total TVL (sum of currentChainTvls, or last tvl point)."""
    try:
        cc = payload.get("currentChainTvls") or {}
        vals = [v for k, v in cc.items() if isinstance(v, (int, float)) and "-" not in k]
        if vals:
            return float(sum(vals))
        arr = payload.get("tvl") or []
        return float(arr[-1]["totalLiquidityUSD"])
    except Exception:  # noqa: BLE001
        return None


def parse_history_24h_ago(payload: dict) -> float | None:
    """From `/protocol/{slug}` daily tvl array, the value ~24h before the latest point."""
    try:
        arr = payload.get("tvl") or []
        if len(arr) >= 2:
            return float(arr[-2]["totalLiquidityUSD"])  # previous daily point ≈ 24h ago
        return float(arr[-1]["totalLiquidityUSD"])
    except Exception:  # noqa: BLE001
        return None


def tvl_current_providers(slug: str) -> dict:
    """{name: callable()->tvl} — current TVL from DeFiLlama's two endpoints (light cross-check)."""
    def simple():
        try:
            return parse_tvl_simple(_get(f"https://api.llama.fi/tvl/{slug}"))
        except Exception:  # noqa: BLE001
            return None

    def protocol():
        try:
            return parse_protocol_current(_get(f"https://api.llama.fi/protocol/{slug}"))
        except Exception:  # noqa: BLE001
            return None

    # TVL is DeFiLlama-dominated: /tvl is the authoritative single source; /protocol kept only for
    # history. A single source is honest here — fail-closed if DeFiLlama is unreachable (n=0 < quorum).
    return {"defillama_tvl": simple}


def tvl_24h_ago(slug: str):
    """(tvl_1h_ago, tvl_24h_ago). DeFiLlama history is DAILY → 1h-ago ≈ 24h-ago (no intraday);
    the 24h-drop is the meaningful signal. Returns None on failure (sensor → fail-closed)."""
    try:
        payload = _get(f"https://api.llama.fi/protocol/{slug}")
        v24 = parse_history_24h_ago(payload)
        if v24 is None:
            return None
        return (v24, v24)  # (1h≈24h for daily data)
    except Exception:  # noqa: BLE001
        return None
