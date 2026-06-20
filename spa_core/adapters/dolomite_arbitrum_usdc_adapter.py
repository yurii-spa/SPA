"""Dolomite Arbitrum USDC адаптер — T2 tier (multichain expansion).

Заменяет deprecated GMX GLP Arbitrum (GLP свёрнут в пользу GM/GLV пулов;
стейблкоин-доходности GLP больше нет на DeFiLlama 2026-06-21).

Chain: Arbitrum One (L2)
Tier: T2 — Dolomite — money-market с isolated borrow positions поверх большого
  набора залогов (включая GLP/GM-токены). USDC supply-доходность зависит от
  utilization рынка.
Pool: USDC lending market на Dolomite (Arbitrum)
APY source: DeFiLlama /pools — project=dolomite, chain=Arbitrum, symbol USDC

⚠️ ТЕКУЩИЙ СТАТУС TVL (DeFiLlama, 2026-06-21): USDC-пул Dolomite на Arbitrum —
   APY 3.98%, TVL ~$1.47M, что НИЖЕ RiskPolicy TVL floor ($5M). Поэтому адаптер
   работает как read-only мониторинг-фид: RiskPolicy НЕ выделит капитал, пока TVL
   не вырастет ≥ $5M. APY_FALLBACK=4.0% — ориентир, требует подтверждения on-chain.

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

Особенности Arbitrum chain:
  - Газ ~10x дешевле Ethereum mainnet ($0.01 vs $0.10 за tx)
  - Finality ~15 мин (vs 7 дней для официальных мостов)
  - Dolomite поддерживает экзотические залоги → idiosyncratic risk выше Aave
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

PROTOCOL_ID = "dolomite-arbitrum"
CHAIN = "arbitrum"
CHAIN_ID = 42161
TIER = "T2"

# TVL в USD — ориентир по USDC-рынку Dolomite на Arbitrum (DeFiLlama 2026-06).
# NB: ниже RiskPolicy floor ($5M) → read-only мониторинг, без аллокации.
TVL_USD = 1_470_000

# Risk score: established money-market, но широкий набор экзотических залогов
# и средняя ликвидность USDC → выше Aave-L2 (0.22), чуть ниже Silo тонких рынков.
RISK_SCORE = 0.38

# APY fallback (%) если DeFiLlama недоступен (требует on-chain подтверждения)
APY_FALLBACK = 4.0

# Максимальная доля портфеля для T2 (20%)
T2_CAP_PCT = 20

# ---------------------------------------------------------------------------
# DeFiLlama API
# ---------------------------------------------------------------------------

_DEFILLAMA_URL = "https://yields.llama.fi/pools"
_REQUEST_TIMEOUT = 10  # секунд

# Проекты Dolomite на DeFiLlama
_DEFILLAMA_PROJECTS = ("dolomite",)

# Допустимые символы USDC-пулов на Arbitrum
_USDC_SYMBOLS = {"USDC", "USDC.E", "USDCE"}

# Санитарные границы APY (%)
_APY_MIN = 0.1
_APY_MAX = 50.0

# Минимальный TVL пула чтобы считаться живым ($100K; финальный RiskPolicy floor
# $5M применяется отдельно при аллокации).
_MIN_POOL_TVL = 100_000.0

# ---------------------------------------------------------------------------
# L2 газовые параметры
# ---------------------------------------------------------------------------

GAS_L2_USD = 0.01        # типичная стоимость tx на Arbitrum
GAS_MAINNET_USD = 0.10   # типичная стоимость tx на Ethereum mainnet
GAS_ADVANTAGE_USD = 0.09  # явная константа экономии (без float-арифметики)
FINALITY_MINUTES = 15    # finality на Arbitrum (минуты)


class DolomiteArbitrumUSDCAdapter(BaseAdapter):
    """Read-only адаптер Dolomite USDC на Arbitrum (T2).

    Получает живые APY/TVL из DeFiLlama. При недоступности сети —
    возвращает APY_FALLBACK. Никогда не бросает исключений публично.
    """

    # Публичные константы (доступны из тестов и реестра)
    PROTOCOL_ID = PROTOCOL_ID
    CHAIN = CHAIN
    CHAIN_ID = CHAIN_ID
    TIER = TIER
    TVL_USD = TVL_USD
    RISK_SCORE = RISK_SCORE
    APY_FALLBACK = APY_FALLBACK
    T2_CAP_PCT = T2_CAP_PCT

    # Для BaseAdapter
    PROTOCOL = "dolomite_arbitrum"
    EXIT_LATENCY_HOURS = 0.0  # мгновенный выход (same-block lending)

    # Стабильный идентификатор для дашборда
    pool_id = "dolomite-usdc-arbitrum"

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
    # DeFiLlama fetch (stdlib urllib)                                      #
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
                logger.warning("dolomite_arbitrum: DeFiLlama вернул не-dict payload")
                return None
            if payload.get("status") != "success":
                logger.warning(
                    "dolomite_arbitrum: DeFiLlama status != success: %r",
                    payload.get("status"),
                )
                return None
            data = payload.get("data")
            if not isinstance(data, list):
                logger.warning("dolomite_arbitrum: DeFiLlama data не список")
                return None
            return data
        except urllib.error.URLError as exc:
            logger.warning("dolomite_arbitrum: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("dolomite_arbitrum: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_usdc_pool(self, pools: list[dict]) -> Optional[dict]:
        """Находит лучший USDC-пул Dolomite на Arbitrum (по максимальному TVL)."""
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
            if symbol not in _USDC_SYMBOLS:
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
                logger.warning(
                    "dolomite_arbitrum: пул %s имеет аномальный APY %.2f%% — пропускаем",
                    pool.get("pool", "?"),
                    apy,
                )
                continue
            if tvl > best_tvl:
                best_tvl = tvl
                best = pool
        return best

    def _fetch_live_apy(self) -> Optional[float]:
        """Возвращает живой APY (%) из DeFiLlama или None при ошибке."""
        pools = self._fetch_pools_raw()
        if pools is None:
            return None
        best = self._find_best_usdc_pool(pools)
        if best is None:
            logger.warning(
                "dolomite_arbitrum: подходящий USDC-пул не найден в DeFiLlama"
            )
            return None
        apy = float(best.get("apy", 0.0))
        logger.info(
            "dolomite_arbitrum: live APY=%.3f%% из пула %s (TVL=%.0f)",
            apy,
            best.get("pool", "?"),
            best.get("tvlUsd", 0),
        )
        return apy

    # ------------------------------------------------------------------ #
    # Публичные методы (BaseAdapter interface)                             #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (4.0 == 4.0%). Никогда не бросает исключений."""
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "dolomite_arbitrum: DeFiLlama недоступен, fallback APY=%.1f%%",
            self.APY_FALLBACK,
        )
        return self.APY_FALLBACK

    def get_apy_pct(self) -> float:
        """Синоним get_apy() (совместимость с registry-интерфейсом)."""
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo (apy — decimal)."""
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
        """Состояние адаптера для adapter_status.json (read_only)."""
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
            "last_updated": time.strftime("%Y-%m-%d", time.gmtime()),
        }

    def health_check(self) -> dict:
        """Проверка работоспособности без сетевых вызовов (fallback APY)."""
        return {
            "protocol": self.PROTOCOL_ID,
            "chain": self.CHAIN,
            "tier": self.TIER,
            "apy_fallback_pct": self.APY_FALLBACK,
            "tvl_usd": self.TVL_USD,
            "tvl_floor_ok": self.TVL_USD >= 5_000_000,  # RiskPolicy floor
            "risk_score": self.RISK_SCORE,
            "t2_cap_pct": self.T2_CAP_PCT,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "gas_l2_usd": GAS_L2_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "status": "ok",
        }

    def to_dict(self) -> dict:
        """Полное представление адаптера для дашборда и отчётов."""
        apy_pct = self.get_apy()
        return {
            "protocol": self.PROTOCOL_ID,
            "pool_id": self.pool_id,
            "name": "Dolomite Arbitrum USDC",
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "tier": self.TIER,
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t2_cap_pct": self.T2_CAP_PCT,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "gas_l2_usd": GAS_L2_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "l2_note": (
                "Dolomite (Arbitrum L2): money-market с isolated borrow positions "
                "поверх широкого набора залогов. Газ ~10x дешевле mainnet "
                "($0.01 vs $0.10). Finality ~15 мин. T2 risk_score=0.38. "
                "⚠️ TVL USDC-пула ~$1.47M, APY 3.98% (DeFiLlama 2026-06-21) "
                "< RiskPolicy floor $5M → read-only мониторинг, без аллокации, "
                "пока ликвидность не вырастет. APY_FALLBACK=4.0% требует "
                "on-chain подтверждения."
            ),
        }
