"""Usual Protocol USD0++ adapter (T2 tier) — read-only APY/TVL feed.

Usual Finance issues USD0, an RWA-backed stablecoin collateralised by short-dated
US Treasury bills. USD0++ is the staked/bonded form that earns the Treasury yield
(plus protocol rewards). This adapter is **read-only / advisory** — it never
signs, never moves capital and never imports from ``execution/`` or ``risk/``
(FORBIDDEN policy). Pure stdlib only.

Data sourcing (layered, first hit wins):
  1. Usual public rates API (best-effort; endpoints are unstable):
     https://api.usual.money/v1/rates  (fallback: https://app.usual.money/api/rates)
  2. DeFiLlama yields pools (project ``usual-usd0``) — primary live source in
     practice; also yields TVL.
  3. Cached constant ``FALLBACK_APY`` (5.0%) flagged ``stale=True`` /
     ``live_data=False`` when every live source is unreachable.

Note on exit latency: USD0++ is a bond-like position with an early-unbond floor;
liquid exit is via secondary AMM liquidity. A conservative non-zero exit latency
is declared so the allocator never assumes instant redemption.
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


class UsualUSD0PPAdapter(BaseAdapter):
    """Usual Protocol USD0++ RWA-backed yield adapter (T2, read-only)."""

    PROTOCOL = "usual_usd0pp"
    ASSET = "USD0++"
    CHAIN = "ethereum"
    TIER = "T2"
    RISK_SCORE = 0.50  # RWA-backed; counterparty + redemption-floor risk

    # Bond-like; liquid exit only via secondary AMM. Conservative 24h declared.
    EXIT_LATENCY_HOURS = 24.0

    FALLBACK_APY = 0.05             # 5.0% decimal
    FALLBACK_TVL_USD = 350_000_000.0

    MIN_APY = 0.0
    MAX_APY = 0.50

    PRIMARY_URLS = (
        "https://api.usual.money/v1/rates",
        "https://app.usual.money/api/rates",
    )
    DEFILLAMA_PROJECT = "usual-usd0"
    DEFILLAMA_SYMBOL = "USD0"  # matches USD0++, USD0, SUSD0 etc.

    RISKS = {
        "depeg_risk": "MEDIUM",
        "smart_contract_risk": "MEDIUM",
        "centralization_risk": "HIGH",  # RWA issuer / off-chain T-bill custody
    }

    def __init__(
        self,
        asset: str = "USD0++",
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

    def _fetch_primary(self) -> Optional[float]:
        for url in self.PRIMARY_URLS:
            try:
                data = self._get_json(url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("%s: primary %s failed: %s", self.PROTOCOL, url, exc)
                continue
            apy = self._parse_primary(data)
            if apy is not None:
                return apy
        return None

    def _parse_primary(self, data: Any) -> Optional[float]:
        """Best-effort parse of a Usual rates payload for the USD0++ APY."""
        if isinstance(data, dict):
            # Direct fields some rates endpoints expose.
            for key in ("usd0pp_apy", "usd0ppApy", "apy", "rate"):
                cand = self._norm_apy(data.get(key))
                if cand is not None:
                    return cand
            rows = data.get("data") or data.get("rates") or data.get("result")
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    sym = (r.get("symbol") or r.get("token") or r.get("asset") or "").upper()
                    if "USD0" not in sym:
                        continue
                    cand = self._norm_apy(r.get("apy") or r.get("rate") or r.get("apr"))
                    if cand is not None:
                        return cand
        elif isinstance(data, list):
            cands = [self._norm_apy(r.get("apy")) for r in data if isinstance(r, dict)]
            cands = [c for c in cands if c is not None]
            if cands:
                return max(cands)
        return None

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
        record: Dict[str, Any] = {
            "protocol": self.PROTOCOL,
            "asset": self.asset,
            "tier": self.tier,
            "apy": None,
            "tvl": None,
            "utilization": None,  # RWA bond — no borrow utilization
            "source": None,
            "live_data": False,
            "stale": False,
            "status": "ok",
            "error": None,
            "ts": time.time(),
        }

        apy = self._fetch_primary()
        source = "usual_api" if apy is not None else None

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
