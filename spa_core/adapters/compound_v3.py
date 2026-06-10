"""Compound V3 (Comet) adapter — T2, read-only / advisory.

Fetches the live APY/TVL of the Compound V3 USDC market (the *Comet*
``0xc3d688B66703497DAA19211EEdff47f25384cdc3`` contract on Ethereum mainnet)
from the DeFiLlama yields API.

This adapter is deliberately self-contained and uses **only the Python
standard library** (``urllib`` / ``json``) so it carries no third-party
dependency. It is read-only and advisory: it never touches capital and is not
imported by ``execution/``, ``feed_health/`` or the deterministic risk agents.

``fetch()`` returns a flat status dict (never raises); ``apy`` is the raw
DeFiLlama percentage value (e.g. ``5.12`` == 5.12%) and ``tvl`` is in USD.
Both are ``None`` when the live value is unavailable.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# DeFiLlama yields endpoint (same source the other adapters use).
DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"

# The on-chain Comet USDC market this adapter tracks (reference only).
COMET_USDC_CONTRACT = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"


class CompoundV3Adapter:
    """Read-only DeFiLlama feed for the Compound V3 Comet USDC market."""

    pool_id = "compound_v3"
    name = "Compound V3 (Comet USDC)"
    tier = "T2"

    # DeFiLlama selectors (case-insensitive match in ``_select_pool``).
    DEFILLAMA_PROJECT = "compound-v3"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Ethereum"
    COMET_CONTRACT = COMET_USDC_CONTRACT

    def __init__(
        self,
        api_url: str = DEFILLAMA_POOLS_URL,
        timeout: float = 5.0,
    ):
        self.api_url = api_url
        self.timeout = timeout

    # --- internal -----------------------------------------------------------

    def _http_get_json(self) -> Optional[dict]:
        """GET the pools endpoint and parse JSON. Returns ``None`` on any error."""
        try:
            req = urllib.request.Request(
                self.api_url,
                headers={"User-Agent": "SPA-CompoundV3Adapter/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - log and fall back gracefully
            logger.warning("compound_v3: DeFiLlama fetch failed: %s", exc)
            return None

    def _select_pool(self, payload: object) -> Optional[dict]:
        """Pick the matching pool with the highest TVL, or ``None`` on miss.

        Matches ``project == compound-v3`` AND ``symbol == USDC`` AND
        ``chain == Ethereum`` (all case-insensitive). When several pools match,
        the one with the largest ``tvlUsd`` wins.
        """
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, list):
            return None

        project_l = self.DEFILLAMA_PROJECT.lower()
        symbol_l = self.DEFILLAMA_SYMBOL.lower()
        chain_l = self.DEFILLAMA_CHAIN.lower()

        best: Optional[dict] = None
        best_tvl = float("-inf")
        for pool in data:
            if not isinstance(pool, dict):
                continue
            if str(pool.get("project", "")).lower() != project_l:
                continue
            if str(pool.get("symbol", "")).lower() != symbol_l:
                continue
            if str(pool.get("chain", "")).lower() != chain_l:
                continue
            tvl = pool.get("tvlUsd")
            tvl = float(tvl) if isinstance(tvl, (int, float)) else 0.0
            if tvl > best_tvl:
                best_tvl = tvl
                best = pool
        return best

    # --- public -------------------------------------------------------------

    def fetch(self) -> dict:
        """Return a flat status dict for the Comet USDC pool. Never raises.

        On any failure (network error, empty/garbage response, no matching
        pool) ``status`` is ``"error"`` and ``apy``/``tvl`` are ``None``.
        """
        result = {
            "pool_id": self.pool_id,
            "apy": None,
            "tvl": None,
            "protocol": "compound_v3",
            "tier": self.tier,
            "ts": time.time(),
            "status": "error",
            "source": "defillama",
        }

        payload = self._http_get_json()
        if payload is None:
            return result

        pool = self._select_pool(payload)
        if pool is None:
            return result

        apy = pool.get("apy")
        tvl = pool.get("tvlUsd")
        result["apy"] = float(apy) if isinstance(apy, (int, float)) else None
        result["tvl"] = float(tvl) if isinstance(tvl, (int, float)) else None
        result["status"] = "ok"
        return result

    def get_apy(self) -> Optional[float]:
        """Return the live APY (DeFiLlama percentage), or ``None`` on miss/error."""
        return self.fetch().get("apy")

    def get_tvl(self) -> Optional[float]:
        """Return the live TVL in USD, or ``None`` on miss/error."""
        return self.fetch().get("tvl")

    # end of class
