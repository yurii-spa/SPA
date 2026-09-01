"""Usual Protocol USD0++ adapter (T2 tier) — read-only APY/TVL feed.

Usual Finance issues USD0, an RWA-backed stablecoin collateralised by short-dated
US Treasury bills. USD0++ is the staked/bonded form that earns the Treasury yield
(plus protocol rewards). This adapter is **read-only / advisory** — it never
signs, never moves capital and never imports from ``execution/`` or ``risk/``
(FORBIDDEN policy). Pure stdlib only.

Data sourcing (layered, first hit wins) — **тождество актива закрепляется, а не
угадывается** (замер 29.08, карточка ``inbox-usual-usd0pp-otdaet-chislo-chuzhogo-akti``):
  1. Usual public rates API (best-effort; endpoints are unstable):
     https://api.usual.money/v1/rates  (fallback: https://app.usual.money/api/rates).
     Принимаются только поля, названные ПО НАШЕМУ активу (``usd0pp_apy`` …) либо
     строки с ТОЧНЫМ символом из ``ACCEPTED_SYMBOLS``. Безымянный ``apy`` верхнего
     уровня и «максимум по всем строкам» отброшены: в оба попадал чужой актив.
  2. DeFiLlama yields pools — сначала ТОЧНЫЙ ``DEFILLAMA_POOL_ID``, иначе точная
     тройка (project, chain, symbol). Подстроки нет: ``"USD0" in symbol``
     приземлялся на ``BUSD0`` ($505.7 млн, 3.41 %) и отдавал ЕГО число как наше.
  3. Наблюдения нет ⇒ ``apy=None`` и ``tvl=None``, ``stale=True`` /
     ``live_data=False``. Литеральной подстановки нет НИ для доходности
     (снята 2026-08-08, «делать все 15»), НИ для TVL (снята 2026-09-01: тот же
     литерал под ярлыком ``live_data=True`` проходил бы порог TVL RiskPolicy
     числом, которого никто не наблюдал — ADR-053/ADR-126).

Кредитного пула USD0++ в фиде на 29.08 нет вовсе (актив встречается только как
LP-пара ``USD0++-USD0``, другой класс риска), поэтому ``DEFILLAMA_POOL_ID`` пока
``None``: адаптер отказывает, а не подбирает похожее. Это осознанный fail-CLOSED —
взять его в опрос можно будет, когда появится пул с доказанным тождеством.

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

    MIN_APY = 0.0
    MAX_APY = 0.50

    PRIMARY_URLS = (
        "https://api.usual.money/v1/rates",
        "https://app.usual.money/api/rates",
    )
    DEFILLAMA_PROJECT = "usual-usd0"
    DEFILLAMA_CHAIN = "Ethereum"
    # Точный символ, НЕ подстрока. `BUSD0` / `USD0A` / `SUSD0` / `USD0++-USD0`
    # содержат "USD0" и содержат его законно — это другие активы.
    DEFILLAMA_SYMBOL = "USD0++"
    # Тождество пула — адрес, а не имя (как в `fluid_arbitrum_usdc`). Кредитного
    # пула USD0++ в фиде нет ⇒ id не объявлен, и отбор остаётся точным по тройке.
    DEFILLAMA_POOL_ID: Optional[str] = None
    # Имена, под которыми НАШ актив приходит из rates-API Usual.
    ACCEPTED_SYMBOLS = ("USD0++", "USD0PP")
    # Ключи rates-API, названные по НАШЕМУ активу. Безымянные `apy`/`rate`
    # сюда не входят: у эмитента их несколько активов.
    PRIMARY_APY_KEYS = ("usd0pp_apy", "usd0ppApy", "usd0PpApy")

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

    @classmethod
    def _is_ours(cls, row: Any) -> bool:
        """Строка rates-API описывает ИМЕННО наш актив?

        Сравнение точное. Подстрока ``"USD0" in symbol`` (как было до 01.09)
        принимала ``BUSD0``, ``USD0A``, ``SUSD0`` — чужие активы, чьё число
        уезжало под именем USD0++.
        """
        if not isinstance(row, dict):
            return False
        for field in ("symbol", "token", "asset"):
            if (row.get(field) or "").strip().upper() in cls.ACCEPTED_SYMBOLS:
                return True
        return False

    def _parse_primary(self, data: Any) -> Optional[float]:
        """Доходность USD0++ из payload rates-API — только при доказанном тождестве.

        Отказ (``None``) здесь честнее числа: у эмитента несколько активов, и
        безымянное поле ``apy`` верхнего уровня не говорит, чьё оно.
        """
        rows: Any = None
        if isinstance(data, dict):
            # Поля, названные по НАШЕМУ активу, — тождество в самом имени ключа.
            for key in self.PRIMARY_APY_KEYS:
                cand = self._norm_apy(data.get(key))
                if cand is not None:
                    return cand
            rows = data.get("data") or data.get("rates") or data.get("result")
        elif isinstance(data, list):
            rows = data
        if isinstance(rows, list):
            for r in rows:
                if not self._is_ours(r):
                    continue
                for field in ("apy", "rate", "apr"):
                    cand = self._norm_apy(r.get(field))
                    if cand is not None:
                        return cand
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
            # Адрес пула бьёт любое имя — если он объявлен, ничем ошибиться нельзя.
            if self.DEFILLAMA_POOL_ID and r.get("pool") == self.DEFILLAMA_POOL_ID:
                best = r
                break
            if (r.get("project") or "").lower() != self.DEFILLAMA_PROJECT:
                continue
            if (r.get("chain") or "").strip() != self.DEFILLAMA_CHAIN:
                continue
            # ТОЧНОЕ равенство. Подстрока брала крупнейшего из подходящих под
            # "USD0" — 29.08 это был `BUSD0` ($505.7 млн, 3.41 %), а LP-пара
            # `USD0++-USD0` — вообще другой класс риска.
            if (r.get("symbol") or "").strip().upper() != self.DEFILLAMA_SYMBOL:
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
    def _clamp(cls, apy):
        """Границы применяются к НАБЛЮДЕНИЮ; ``None`` проходит насквозь.

        Зажать отсутствие наблюдения в MIN_APY значило бы вернуть подстановку
        под другим именем (2026-08-08, «делать все 15»).
        """
        if apy is None:
            return None
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
            # 2026-08-08, решение владельца «делать все 15» (карточка
            # `agent-fake-fallback-v-15-adapterah`): подстановка удалена.
            # Наблюдения нет ⇒ apy остаётся None; запись честно помечается
            # stale + live_feed_unavailable. Раньше здесь появлялся литерал под
            # ярлыком source="cached" — «кэш», которого никто не наблюдал.
            source = "none"
            record["stale"] = True
            record["error"] = "live_feed_unavailable"
        else:
            record["live_data"] = True

        # 2026-09-01: здесь стоял литерал `FALLBACK_TVL_USD = 350_000_000`.
        # Решение владельца 2026-08-08 («делать все 15») сняло подстановку
        # доходности, но подстановка TVL осталась в ТОЙ ЖЕ записи — и уезжала
        # с `live_data=True`, когда доходность пришла, а глубина нет. Порог TVL
        # RiskPolicy ($5 млн) такое число проходит, ничего не наблюдав
        # (ADR-053: «never stamp `live` on a constant»; ADR-126 — тот же класс).
        # Не наблюдали ⇒ None; отсутствие называется отсутствием.

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
