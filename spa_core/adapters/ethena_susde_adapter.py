"""Ethena sUSDe adapter (T2 tier) — read-only APY/TVL feed.

Ethena Finance issues USDe, a delta-neutral synthetic dollar. Staking USDe into
sUSDe (an ERC-4626 vault) captures the protocol yield (funding-rate carry +
staked-collateral yield), historically ~8–15% APY but variable.

This adapter is **read-only / advisory** — it never signs, never moves capital
and never imports from ``execution/`` or ``risk/`` (FORBIDDEN policy). Pure
stdlib only.

Data sourcing (layered, first hit wins):
  1. Ethena public yield API:
     https://ethena.fi/api/yields/protocol-and-staking-yield  (field ``stakingYield``)
     fallback URL: https://app.ethena.fi/api/yields  (field ``apr``)
  2. DeFiLlama yields pools (project ``ethena-usde``, symbol ``SUSDE``) — used for
     TVL and as an APY fallback.
  3. Cached constant ``FALLBACK_APY`` (8.5%) flagged ``stale=True`` /
     ``live_data=False`` when every live source is unreachable. The staleness
     flag keeps the "no live data" signal honest (SPA-V398) rather than silently
     pretending the cached number is fresh.

Kill-switch hint (advisory): a sudden collapse of the staking yield below
``ANOMALY_APY_FLOOR`` (3%) is flagged via ``is_anomaly()`` / ``anomaly`` so the
RiskPolicy / monitoring layer can react. This adapter only *flags* — the
deterministic RiskPolicy owns any actual de-risking decision.

Risk profile: depeg_risk=HIGH, smart_contract_risk=MEDIUM,
centralization_risk=MEDIUM.
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
    """GET ``url`` and return parsed JSON. Raises on any failure (caller guards).

    Handles gzip-encoded responses. ``opener`` is an injection seam for tests.
    """
    if opener is not None:
        return opener(url, timeout)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only)
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


class EthenaSusdeAdapter(BaseAdapter):
    """Ethena sUSDe staked-USDe yield adapter (T2, read-only)."""

    PROTOCOL = "ethena_susde"
    ASSET = "sUSDe"
    CHAIN = "ethereum"
    TIER = "T2"
    RISK_SCORE = 0.55  # delta-neutral; depeg risk dominates

    # sUSDe withdrawals carry a 7-day unstake cooldown (168h).
    EXIT_LATENCY_HOURS = 168.0

    # Cached fallbacks (decimals / USD) used only when every live source fails.
    FALLBACK_APY = 0.085          # 8.5% decimal
    FALLBACK_TVL_USD = 1_700_000_000.0

    # APY sanity bounds (decimals).
    MIN_APY = 0.0
    MAX_APY = 0.50

    # Advisory kill-switch hint: staking yield below this is treated as anomalous.
    ANOMALY_APY_FLOOR = 0.03  # 3%

    PRIMARY_URLS = (
        "https://ethena.fi/api/yields/protocol-and-staking-yield",
        "https://app.ethena.fi/api/yields",
    )
    DEFILLAMA_PROJECT = "ethena-usde"
    DEFILLAMA_SYMBOL = "SUSDE"
    DEFILLAMA_CHAIN = "Ethereum"

    # Declarative risk attributes (advisory metadata).
    RISKS = {
        "depeg_risk": "HIGH",
        "smart_contract_risk": "MEDIUM",
        "centralization_risk": "MEDIUM",
    }

    def __init__(
        self,
        asset: str = "sUSDe",
        http_get: Optional[Callable[[str, int], Any]] = None,
        timeout: int = _REQUEST_TIMEOUT,
    ):
        super().__init__(asset)
        self.tier = self.TIER
        self.timeout = timeout
        # Injection seam: tests pass an ``http_get(url, timeout)`` callable that
        # returns parsed JSON (or raises to simulate an outage).
        self._http_get = http_get

    # -- internal fetch helpers --------------------------------------------

    def _get_json(self, url: str) -> Any:
        return _http_get_json(url, self.timeout, opener=self._http_get)

    @staticmethod
    def _norm_apy(value: Any) -> Optional[float]:
        """Normalise a raw APY to a decimal. Values > 1.0 are treated as percent."""
        if not isinstance(value, (int, float)):
            return None
        v = float(value)
        if v != v:  # NaN guard
            return None
        return v / 100.0 if v > 1.0 else v

    def _fetch_primary(self) -> Optional[float]:
        """Try the Ethena public APIs. Return APY decimal or None."""
        for url in self.PRIMARY_URLS:
            try:
                data = self._get_json(url)
            except Exception as exc:  # noqa: BLE001 — never propagate to capital path
                logger.debug("%s: primary %s failed: %s", self.PROTOCOL, url, exc)
                continue
            apy = self._parse_primary(data)
            if apy is not None:
                return apy
        return None

    def _parse_primary(self, data: Any) -> Optional[float]:
        if isinstance(data, dict):
            # protocol-and-staking-yield shape
            block = data.get("stakingYield") or data.get("avg30dSusdeYield")
            if isinstance(block, dict):
                return self._norm_apy(block.get("value"))
            # app.ethena.fi/api/yields shape: {"data": [{"apr": ...}, ...]}
            rows = data.get("data")
            if isinstance(rows, list):
                aprs = [self._norm_apy(r.get("apr")) for r in rows if isinstance(r, dict)]
                aprs = [a for a in aprs if a is not None]
                if aprs:
                    return max(aprs)
        return None

    def _fetch_defillama(self) -> Dict[str, Optional[float]]:
        """Best-effort DeFiLlama lookup → {apy, tvl} (decimals/USD), Nones on miss."""
        out: Dict[str, Optional[float]] = {"apy": None, "tvl": None}
        try:
            payload = self._get_json(_DEFILLAMA_POOLS_URL)
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: defillama failed: %s", self.PROTOCOL, exc)
            return out
        rows: List[dict] = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return out
        best = None
        for r in rows:
            if not isinstance(r, dict):
                continue
            if (r.get("project") or "").lower() != self.DEFILLAMA_PROJECT:
                continue
            if self.DEFILLAMA_SYMBOL not in (r.get("symbol") or "").upper():
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
        """Return a flat status dict. Never raises, never silently mocks.

        Keys: apy (decimal|None-free, always set), tvl, utilization, tier,
        source, live_data, stale, anomaly, status, error, ts.
        """
        record: Dict[str, Any] = {
            "protocol": self.PROTOCOL,
            "asset": self.asset,
            "tier": self.tier,
            "apy": None,
            "tvl": None,
            "utilization": None,  # staking vault → no borrow utilization
            "source": None,
            "live_data": False,
            "stale": False,
            "anomaly": False,
            "status": "ok",
            "error": None,
            "ts": time.time(),
        }

        apy = self._fetch_primary()
        source = "ethena_api" if apy is not None else None

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

        apy = self._clamp(apy)
        record["apy"] = apy
        record["source"] = source
        # Advisory anomaly: live yield collapsed below the floor.
        record["anomaly"] = bool(record["live_data"] and apy < self.ANOMALY_APY_FLOOR)
        return record

    def get_apy(self) -> Optional[float]:
        """Current APY as a decimal (cached fallback flagged via ``fetch()``)."""
        return self.fetch()["apy"]

    def get_tvl(self) -> Optional[float]:
        """Current TVL in USD (positive)."""
        return self.fetch()["tvl"]

    def get_utilization(self) -> Optional[float]:
        """Borrow utilization — N/A for a staking vault, always None."""
        return self.fetch()["utilization"]

    def is_anomaly(self) -> bool:
        """Advisory kill-switch hint: True if live APY collapsed below the floor."""
        return self.fetch()["anomaly"]

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
