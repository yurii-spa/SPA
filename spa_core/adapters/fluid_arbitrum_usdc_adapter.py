"""Fluid Protocol USDC lending on **Arbitrum** (T2 tier) — read-only APY/TVL feed.

Sibling of :mod:`spa_core.adapters.fluid_usdc_adapter` (mainnet). Fluid (formerly
Instadapp) runs the same lending market on Arbitrum, where the USDC supply pool
carries a notably higher blended yield than mainnet Compound/Aave at a healthy
TVL well above the RiskPolicy $5M floor:

  * DeFiLlama 2026-06: project ``fluid-lending``, chain ``Arbitrum``, symbol
    ``USDC`` → pool ``4c45cc9e-e1a4-43c9-8a3d-687d96abb07c``,
    TVL ≈ $36.6M, APY ≈ 4.96% — better than mainnet Compound (~3.3%) / Aave
    (~3.1%) and most mainnet T2s, comfortably over the $5M TVL floor.

This adapter is **read-only / advisory** — it never signs, never moves capital,
never imports from ``execution/`` or ``risk/`` (FORBIDDEN policy). Pure stdlib.

Data sourcing (layered, first hit wins):
  1. Fluid public lending API for Arbitrum (chain id 42161; endpoints unstable):
     https://api.fluid.instadapp.io/v2/42161/lending  (fallback: .../v2/lending)
  2. DeFiLlama yields pools — matched first by the exact ``POOL_ID``, then by
     (project ``fluid-lending``, chain ``Arbitrum``, symbol ``USDC``). Primary
     live source in practice; also yields TVL and utilization when available.
  3. Cached constant ``FALLBACK_APY`` (4.5% — conservative vs the 4.96% live)
     flagged ``stale=True`` / ``live_data=False`` when every source is down.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .base_adapter import BaseAdapter, YieldInfo

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10  # seconds
_USER_AGENT = "SPA-adapter/1.0 (read-only)"
_DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"


def _http_get_json(
    url: str,
    timeout: int = _REQUEST_TIMEOUT,
    opener: Optional[Callable[[str, int], Any]] = None,
) -> Any:
    """GET ``url`` and return parsed JSON. Raises on failure (caller guards)."""
    if opener is not None:
        return opener(url, timeout)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


class FluidArbitrumUsdcAdapter(BaseAdapter):
    """Fluid Protocol USDC lending yield adapter on Arbitrum (T2, read-only)."""

    PROTOCOL = "fluid_arbitrum"
    ASSET = "USDC"
    CHAIN = "Arbitrum"
    TIER = "T2"
    # Slightly higher than mainnet Fluid (0.35) to reflect Arbitrum-specific
    # L2 risk (sequencer liveness, bridge dependency) on top of the same
    # protocol smart-contract surface.
    RISK_SCORE = 0.38

    # Liquid lending position — withdrawals settle same-block subject to vault
    # utilization, so the declared exit latency is 0h.
    EXIT_LATENCY_HOURS = 0.0

    # Conservative cached fallback: 4.5% vs the ~4.96% DeFiLlama-live rate.
    FALLBACK_APY = 0.045           # 4.5% decimal
    FALLBACK_TVL_USD = 36_600_000.0

    MIN_APY = 0.0
    MAX_APY = 0.50

    PRIMARY_URLS = (
        "https://api.fluid.instadapp.io/v2/42161/lending",
        "https://api.fluid.instadapp.io/v2/lending",
    )
    DEFILLAMA_PROJECT = "fluid-lending"
    DEFILLAMA_SYMBOL = "USDC"
    DEFILLAMA_CHAIN = "Arbitrum"
    # Exact DeFiLlama pool id for fluid-lending USDC on Arbitrum (2026-06).
    # Matched first; project/chain/symbol is the resilient fallback.
    POOL_ID = "4c45cc9e-e1a4-43c9-8a3d-687d96abb07c"

    RISKS = {
        "depeg_risk": "LOW",
        "smart_contract_risk": "MEDIUM",
        "centralization_risk": "MEDIUM",
        "l2_sequencer_risk": "MEDIUM",
    }

    def __init__(
        self,
        asset: str = "USDC",
        http_get: Optional[Callable[[str, int], Any]] = None,
        timeout: int = _REQUEST_TIMEOUT,
    ):
        super().__init__(asset)
        self.tier = self.TIER
        self.timeout = timeout
        self._http_get = http_get

    # -- internal helpers --------------------------------------------------

    def _get_json(self, url: str) -> Any:
        return _http_get_json(url, self.timeout, opener=self._http_get)

    @staticmethod
    def _norm_apy(value: Any) -> Optional[float]:
        if not isinstance(value, (int, float)):
            return None
        v = float(value)
        if v != v:
            return None
        return v / 100.0 if v > 1.0 else v

    def _fetch_primary(self) -> Dict[str, Optional[float]]:
        """Try Fluid's own API. Return {apy, utilization}; Nones on miss."""
        out: Dict[str, Optional[float]] = {"apy": None, "utilization": None}
        for url in self.PRIMARY_URLS:
            try:
                data = self._get_json(url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("%s: primary %s failed: %s", self.PROTOCOL, url, exc)
                continue
            apy, util = self._parse_primary(data)
            if apy is not None:
                out["apy"] = apy
                out["utilization"] = util
                return out
        return out

    def _parse_primary(self, data: Any) -> tuple:
        """Best-effort parse of the Fluid lending payload for a USDC supply rate."""
        rows: List[dict] = []
        if isinstance(data, dict):
            for key in ("data", "tokens", "lending", "result"):
                v = data.get(key)
                if isinstance(v, list):
                    rows = v
                    break
        elif isinstance(data, list):
            rows = data
        for r in rows:
            if not isinstance(r, dict):
                continue
            sym = (r.get("symbol") or r.get("token") or r.get("asset") or "").upper()
            if "USDC" not in sym:
                continue
            apy = self._norm_apy(
                r.get("supplyRate")
                or r.get("supplyApy")
                or r.get("lendingRate")
                or r.get("apy")
            )
            util = r.get("utilization") or r.get("utilizationRate")
            util = float(util) / 100.0 if isinstance(util, (int, float)) and util > 1.0 else (
                float(util) if isinstance(util, (int, float)) else None
            )
            if apy is not None:
                return apy, util
        return None, None

    def _fetch_defillama(self) -> Dict[str, Optional[float]]:
        out: Dict[str, Optional[float]] = {"apy": None, "tvl": None}
        try:
            payload = self._get_json(_DEFILLAMA_POOLS_URL)
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: defillama failed: %s", self.PROTOCOL, exc)
            return out
        rows = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return out
        best = None
        for r in rows:
            if not isinstance(r, dict):
                continue
            # Prefer the exact pool id; short-circuit if found.
            if r.get("pool") == self.POOL_ID:
                best = r
                break
            if (r.get("project") or "").lower() != self.DEFILLAMA_PROJECT:
                continue
            if (r.get("chain") or "") != self.DEFILLAMA_CHAIN:
                continue
            if (r.get("symbol") or "").upper() != self.DEFILLAMA_SYMBOL:
                continue
            tvl = r.get("tvlUsd")
            if best is None or (isinstance(tvl, (int, float)) and tvl > (best.get("tvlUsd") or 0)):
                best = r
        if best is not None:
            out["apy"] = self._norm_apy(best.get("apy"))
            tvl = best.get("tvlUsd")
            out["tvl"] = float(tvl) if isinstance(tvl, (int, float)) else None
        return out

    @classmethod
    def _clamp(cls, apy: float) -> float:
        return max(cls.MIN_APY, min(cls.MAX_APY, apy))

    # -- public API --------------------------------------------------------

    def fetch(self) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "protocol": self.PROTOCOL,
            "asset": self.asset,
            "chain": self.CHAIN,
            "tier": self.tier,
            "apy": None,
            "tvl": None,
            "utilization": None,
            "source": None,
            "live_data": False,
            "stale": False,
            "status": "ok",
            "error": None,
            "ts": time.time(),
        }

        primary = self._fetch_primary()
        apy = primary["apy"]
        source = "fluid_api" if apy is not None else None
        record["utilization"] = primary["utilization"]

        dl = self._fetch_defillama()
        if apy is None and dl["apy"] is not None:
            apy = dl["apy"]
            source = "defillama"
        record["tvl"] = dl["tvl"]

        if apy is None:
            apy = self.FALLBACK_APY
            source = "cached"
            record["stale"] = True
            record["error"] = "live_feed_unavailable"
        else:
            record["live_data"] = True

        if record["tvl"] is None:
            record["tvl"] = self.FALLBACK_TVL_USD

        record["apy"] = self._clamp(apy)
        record["source"] = source
        return record

    def get_apy(self) -> Optional[float]:
        return self.fetch()["apy"]

    def get_tvl(self) -> Optional[float]:
        return self.fetch()["tvl"]

    def get_utilization(self) -> Optional[float]:
        return self.fetch()["utilization"]

    def get_yield_info(self) -> YieldInfo:
        data = self.fetch()
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=data["apy"],
            tvl_usd=data["tvl"],
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )
