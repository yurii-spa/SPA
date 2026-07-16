"""GMX GLP Arbitrum адаптер — T2 tier (multichain expansion).

Chain: Arbitrum One (L2)
Tier: T2 — GLP — индексный токен ликвидности GMX V1 (basket BTC/ETH/stables),
  зарабатывает на торговых комиссиях перпетуалов. НЕ чистый стейблкоин:
  имеет USDC-компонент, но цена GLP колеблется вместе с корзиной активов.
  Доходность из торговых комиссий волатильна (5–12% ист.) → повышенный risk_score.
Pool: GLP vault на Arbitrum
APY source: DeFiLlama /pools — project=gmx*, chain=Arbitrum, symbol содержит GLP

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

ВНИМАНИЕ: GLP — НЕ delta-neutral стейблкоин-позиция. Включён как T2 advisory
feed для диверсификации доходности (trading fees), но allocator/RiskPolicy
обязаны учитывать market-exposure корзины. risk_score=0.55 это отражает.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы протокола
# ---------------------------------------------------------------------------

PROTOCOL_ID = "gmx-glp-arbitrum"
CHAIN = "arbitrum"
CHAIN_ID = 42161
TIER = "T2"

# TVL в USD (~$400M GLP на Arbitrum, ориентир 2026-06)
TVL_USD = 400_000_000

# Risk score: выше lending-T2 — рыночная экспозиция корзины + волатильность
# торговых комиссий. Не чистый стейблкоин.
RISK_SCORE = 0.55

# APY fallback (%) если внешние источники недоступны (середина диапазона 5–12%)
APY_FALLBACK = 8.0

# Максимальная доля портфеля для T2 (20%)
T2_CAP_PCT = 20

# ---------------------------------------------------------------------------
# Источники APY (порядок приоритета)
# ---------------------------------------------------------------------------

# 1. DeFiLlama yields (project=gmx*, chain=Arbitrum, symbol GLP)
_DEFILLAMA_URL = "https://yields.llama.fi/pools"
# 2. GMX публичный stats API (без ключа) — fallback на DeFiLlama
_GMX_API_URL = "https://api.gmx.io/glp/apr"
_REQUEST_TIMEOUT = 10  # секунд

# Проекты GMX на DeFiLlama
_DEFILLAMA_PROJECTS = ("gmx-v1", "gmx")

# GLP-символы
_GLP_SYMBOLS = {"GLP", "FSGLP", "SGLP"}

# Санитарные границы APY (%) — GLP может давать выше lending
_APY_MIN = 0.1
_APY_MAX = 60.0

# Минимальный TVL пула чтобы считаться живым ($5M)
_MIN_POOL_TVL = 5_000_000.0

# ---------------------------------------------------------------------------
# L2 газовые параметры
# ---------------------------------------------------------------------------

GAS_L2_USD = 0.01
GAS_MAINNET_USD = 0.10
GAS_ADVANTAGE_USD = 0.09
FINALITY_MINUTES = 15


class GmxGlpArbitrumAdapter(BaseAdapter):
    """Read-only адаптер GMX GLP на Arbitrum (T2).

    Источник APY (приоритет):
      1. DeFiLlama /pools (gmx*, Arbitrum, GLP)
      2. GMX stats API (api.gmx.io)
      3. APY_FALLBACK = 8.0%

    Никогда не бросает исключений публично.
    """

    PROTOCOL_ID = PROTOCOL_ID
    CHAIN = CHAIN
    CHAIN_ID = CHAIN_ID
    TIER = TIER
    TVL_USD = TVL_USD
    RISK_SCORE = RISK_SCORE
    APY_FALLBACK = APY_FALLBACK
    T2_CAP_PCT = T2_CAP_PCT

    PROTOCOL = "gmx_glp_arbitrum"
    EXIT_LATENCY_HOURS = 0.25  # GLP redeem ~15 мин cooldown (приблизительно)

    pool_id = "gmx-glp-arbitrum"

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[str | Path] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER
        if data_dir is None:
            self._data_dir: Path = Path(__file__).resolve().parents[2] / "data"
        else:
            self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------ #
    # DeFiLlama fetch                                                      #
    # ------------------------------------------------------------------ #

    def _fetch_pools_raw(self) -> Optional[list[dict]]:
        """Загружает /pools из DeFiLlama. Возвращает список пулов или None."""
        try:
            req = urllib.request.Request(
                _DEFILLAMA_URL,
                headers={"Accept-Encoding": "gzip", "User-Agent": "SPA/1.0"},
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                raw = resp.read()
                try:
                    payload = json.loads(gzip.decompress(raw))
                except (gzip.BadGzipFile, OSError):
                    payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            if payload.get("status") != "success":
                return None
            data = payload.get("data")
            if not isinstance(data, list):
                return None
            return data
        except urllib.error.URLError as exc:
            logger.warning("gmx_glp_arbitrum: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("gmx_glp_arbitrum: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_glp_pool(self, pools: list[dict]) -> Optional[dict]:
        """Находит GLP-пул GMX на Arbitrum (по максимальному TVL)."""
        best: Optional[dict] = None
        best_tvl: float = float("-inf")
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            if str(pool.get("chain", "")).lower() != "arbitrum":
                continue
            proj = str(pool.get("project", "")).lower()
            if not any(p in proj for p in _DEFILLAMA_PROJECTS):
                continue
            symbol = str(pool.get("symbol", "")).upper().strip()
            if symbol not in _GLP_SYMBOLS:
                continue
            tvl = pool.get("tvlUsd")
            if not isinstance(tvl, (int, float)):
                continue
            tvl = float(tvl)
            if tvl < _MIN_POOL_TVL:
                continue
            apy = pool.get("apy")
            if not isinstance(apy, (int, float)):
                continue
            apy = float(apy)
            if apy < _APY_MIN or apy > _APY_MAX:
                continue
            if tvl > best_tvl:
                best_tvl = tvl
                best = pool
        return best

    def _fetch_apy_from_defillama(self) -> Optional[float]:
        pools = self._fetch_pools_raw()
        if pools is None:
            return None
        best = self._find_best_glp_pool(pools)
        if best is None:
            return None
        apy = float(best.get("apy", 0.0))
        logger.info("gmx_glp_arbitrum: live APY=%.3f%% (DeFiLlama)", apy)
        return apy

    def _fetch_apy_from_gmx_api(self) -> Optional[float]:
        """Резервный источник: GMX публичный API (без ключа).

        Формат ответа GMX варьируется; ищем поле с агрегированным APR GLP
        для Arbitrum. Любая ошибка → None (graceful fallback на cached APY).
        """
        try:
            req = urllib.request.Request(
                _GMX_API_URL,
                headers={"Accept": "application/json", "User-Agent": "SPA/1.0"},
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read())
            # Возможные формы: {"arbitrum": {"glp": <apr>}} или {"glpApr": <apr>}
            for key in ("arbitrum", "Arbitrum"):
                entry = data.get(key) if isinstance(data, dict) else None
                if isinstance(entry, dict):
                    for k in ("glp", "glpApr", "apr", "total"):
                        v = entry.get(k)
                        if isinstance(v, (int, float)):
                            return float(v)
            if isinstance(data, dict):
                for k in ("glpApr", "apr", "glp", "total"):
                    v = data.get(k)
                    if isinstance(v, (int, float)):
                        return float(v)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.debug("gmx_glp_arbitrum: GMX API недоступен: %s", exc)
            return None

    def _fetch_live_apy(self) -> Optional[float]:
        apy = self._fetch_apy_from_defillama()
        if apy is not None and _APY_MIN <= apy <= _APY_MAX:
            return apy
        apy = self._fetch_apy_from_gmx_api()
        if apy is not None and _APY_MIN <= apy <= _APY_MAX:
            return apy
        return None

    # ------------------------------------------------------------------ #
    # Публичные методы                                                     #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (8.0 == 8.0%). Никогда не бросает исключений."""
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "gmx_glp_arbitrum: внешние источники недоступны, fallback APY=%.1f%%",
            self.APY_FALLBACK,
        )
        return self.APY_FALLBACK

    def get_apy_pct(self) -> float:
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        apy_pct = self.get_apy()
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=apy_pct / 100.0,
            tvl_usd=float(self.TVL_USD),
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ------------------------------------------------------------------ #
    # Статус и метаданные                                                  #
    # ------------------------------------------------------------------ #

    def get_write_state(self) -> dict:
        apy_pct = self.get_apy()
        return {
            "protocol_id": self.PROTOCOL_ID,
            "chain": self.CHAIN,
            "tier": self.TIER,
            "apy_pct": apy_pct,
            "tvl_usd": float(self.TVL_USD),
            "risk_score": self.RISK_SCORE,
            "t2_cap_pct": self.T2_CAP_PCT,
            "write_state": "read_only",
            "pool_id": self.pool_id,
            "is_pure_stablecoin": False,
            "last_updated": time.strftime("%Y-%m-%d", time.gmtime()),
        }

    def health_check(self) -> dict:
        return {
            "protocol": self.PROTOCOL_ID,
            "chain": self.CHAIN,
            "tier": self.TIER,
            "apy_fallback_pct": self.APY_FALLBACK,
            "tvl_usd": self.TVL_USD,
            "tvl_floor_ok": self.TVL_USD >= 5_000_000,
            "risk_score": self.RISK_SCORE,
            "t2_cap_pct": self.T2_CAP_PCT,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "is_pure_stablecoin": False,
            "gas_l2_usd": GAS_L2_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "status": "ok",
        }

    def to_dict(self) -> dict:
        apy_pct = self.get_apy()
        return {
            "protocol": self.PROTOCOL_ID,
            "pool_id": self.pool_id,
            "name": "GMX GLP Arbitrum",
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "tier": self.TIER,
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t2_cap_pct": self.T2_CAP_PCT,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "is_pure_stablecoin": False,
            "gas_l2_usd": GAS_L2_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "l2_note": (
                "GMX GLP (Arbitrum L2): индекс ликвидности перпетуалов "
                "(корзина BTC/ETH/stables), доход из торговых комиссий (5–12%). "
                "НЕ чистый стейблкоин — есть рыночная экспозиция корзины. "
                "T2 risk_score=0.55; allocator обязан учитывать market exposure."
            ),
        }
