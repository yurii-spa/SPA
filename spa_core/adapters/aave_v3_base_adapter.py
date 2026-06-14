"""Aave V3 Base chain adapter — T2 tier (MP-448).

Chain: Base (Coinbase L2)
Tier: T2 — высокий TVL (~$400M USDC), но повышенный риск L2-bridge
Pool: USDC / USDC.e / USDbC на Aave V3 Base
APY source: DeFiLlama /pools — project=aave-v3, chain=Base, symbol contains USDC

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

Особенности Base chain:
  - Bridge risk: активы поступают через official Coinbase bridge
    (оптимистический период 7 дней для вывода на mainnet)
  - Газ: ~10-30x дешевле Ethereum mainnet ($0.001–0.01 за tx)
  - Finality: ~2 секунды (OP-stack sequencer), затем Ethereum ~12 мин
  - TVL Base Aave V3: ~$400M USDC (данные 2026-06)
  - APY premium: +0.5–1.5% к mainnet Aave за счёт меньшей конкуренции
"""
from __future__ import annotations

import gzip
import json
import logging
import os
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

PROTOCOL_ID = "aave-v3-base"
CHAIN = "base"
TIER = "T2"

# TVL в USD (~$400M на Base, данные 2026-06)
TVL_USD = 400_000_000

# Risk score: чуть выше mainnet T1 (0.20) из-за L2 bridge риска
RISK_SCORE = 0.35

# APY fallback (%) если DeFiLlama недоступен
APY_FALLBACK = 4.5

# Максимальная доля портфеля для T2 (20%)
T2_CAP_PCT = 20

# ---------------------------------------------------------------------------
# DeFiLlama API
# ---------------------------------------------------------------------------

_DEFILLAMA_URL = "https://yields.llama.fi/pools"
_REQUEST_TIMEOUT = 10  # секунд

# Проекты Aave V3 на Base (DeFiLlama использует разные slug-и)
_DEFILLAMA_PROJECTS = ("aave-v3", "aave")

# Допустимые символы USDC-пулов на Base
_USDC_SYMBOLS = {"USDC", "USDC.E", "USDBC"}

# Санитарные границы APY (%)
_APY_MIN = 0.1
_APY_MAX = 50.0

# Минимальный TVL пула чтобы считаться живым ($1M)
_MIN_POOL_TVL = 1_000_000.0

# ---------------------------------------------------------------------------
# L2 газовые параметры
# ---------------------------------------------------------------------------

GAS_BASE_USD = 0.005       # типичная стоимость tx на Base
GAS_MAINNET_USD = 0.10     # типичная стоимость tx на Ethereum mainnet
GAS_ADVANTAGE_USD = 0.095  # явная константа экономии (без float-арифметики)
FINALITY_SECONDS_BASE = 2  # OP-stack sequencer finality (секунды)


class AaveV3BaseAdapter(BaseAdapter):
    """Read-only адаптер Aave V3 USDC на Base chain (T2, MP-448).

    Получает живые APY/TVL из DeFiLlama. При недоступности сети —
    возвращает APY_FALLBACK. Никогда не бросает исключений публично.

    Параметры конструктора
    ----------------------
    asset : str
        Торгуемый актив. По умолчанию "USDC".
    data_dir : str | Path | None
        Путь к директории data/. Если None — вычисляется автоматически
        относительно корня репо.

    Атрибуты класса (константы)
    ---------------------------
    PROTOCOL_ID   : "aave-v3-base"
    CHAIN         : "base"
    TIER          : "T2"
    TVL_USD       : 400_000_000
    RISK_SCORE    : 0.35
    APY_FALLBACK  : 4.5 (%)
    T2_CAP_PCT    : 20 (% портфеля)
    """

    # Публичные константы (доступны из тестов и реестра)
    PROTOCOL_ID = PROTOCOL_ID
    CHAIN = CHAIN
    TIER = TIER
    TVL_USD = TVL_USD
    RISK_SCORE = RISK_SCORE
    APY_FALLBACK = APY_FALLBACK
    T2_CAP_PCT = T2_CAP_PCT

    # Для BaseAdapter
    PROTOCOL = PROTOCOL_ID
    EXIT_LATENCY_HOURS = 0.0  # мгновенный выход (same-block lending)

    # Стабильный идентификатор для дашборда
    pool_id = "aave-v3-usdc-base"

    # ------------------------------------------------------------------ #
    # Инициализация                                                        #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[str | Path] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER

        if data_dir is None:
            # spa_core/adapters/aave_v3_base_adapter.py → repo root / data
            self._data_dir: Path = (
                Path(__file__).resolve().parents[2] / "data"
            )
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
                # Пробуем распаковать gzip (DeFiLlama возвращает сжатый ответ)
                try:
                    payload = json.loads(gzip.decompress(raw))
                except (gzip.BadGzipFile, OSError):
                    payload = json.loads(raw)

            if not isinstance(payload, dict):
                logger.warning("aave_v3_base: DeFiLlama вернул не-dict payload")
                return None
            if payload.get("status") != "success":
                logger.warning(
                    "aave_v3_base: DeFiLlama status != success: %r",
                    payload.get("status"),
                )
                return None
            data = payload.get("data")
            if not isinstance(data, list):
                logger.warning("aave_v3_base: DeFiLlama data не список")
                return None
            return data

        except urllib.error.URLError as exc:
            logger.warning("aave_v3_base: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("aave_v3_base: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_usdc_pool(
        self, pools: list[dict]
    ) -> Optional[dict]:
        """Находит лучший USDC-пул Aave V3 на Base.

        Фильтрация:
          - chain == "Base" (case-insensitive)
          - project: один из _DEFILLAMA_PROJECTS
          - symbol: один из _USDC_SYMBOLS (case-insensitive, после strip)
          - tvlUsd >= _MIN_POOL_TVL
          - apy в диапазоне [_APY_MIN, _APY_MAX]

        Среди кандидатов выбирается пул с максимальным TVL.
        """
        best: Optional[dict] = None
        best_tvl: float = float("-inf")

        for pool in pools:
            if not isinstance(pool, dict):
                continue

            # Проверяем chain
            if str(pool.get("chain", "")).lower() != "base":
                continue

            # Проверяем project
            proj = str(pool.get("project", "")).lower()
            if not any(p in proj for p in _DEFILLAMA_PROJECTS):
                continue

            # Проверяем symbol
            symbol = str(pool.get("symbol", "")).upper().strip()
            if symbol not in _USDC_SYMBOLS:
                continue

            # Проверяем TVL
            tvl = pool.get("tvlUsd")
            if not isinstance(tvl, (int, float)):
                continue
            tvl = float(tvl)
            if tvl < _MIN_POOL_TVL:
                continue

            # Проверяем APY
            apy = pool.get("apy")
            if not isinstance(apy, (int, float)):
                continue
            apy = float(apy)
            if apy < _APY_MIN or apy > _APY_MAX:
                logger.warning(
                    "aave_v3_base: пул %s имеет аномальный APY %.2f%% — пропускаем",
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
                "aave_v3_base: подходящий USDC-пул на Base не найден в DeFiLlama"
            )
            return None
        apy = float(best.get("apy", 0.0))
        logger.info(
            "aave_v3_base: live APY=%.3f%% из пула %s (TVL=%.0f)",
            apy,
            best.get("pool", "?"),
            best.get("tvlUsd", 0),
        )
        return apy

    # ------------------------------------------------------------------ #
    # Публичные методы (BaseAdapter interface)                             #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (например 4.5 == 4.5%).

        Приоритет:
          1. Живые данные DeFiLlama (Base / aave-v3 / USDC)
          2. APY_FALLBACK = 4.5% при недоступности сети

        Никогда не бросает исключений.
        """
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "aave_v3_base: DeFiLlama недоступен, используем fallback APY=%.1f%%",
            self.APY_FALLBACK,
        )
        return self.APY_FALLBACK

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        YieldInfo.apy — decimal (0.045 для 4.5%).
        """
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
        """Возвращает словарь состояния адаптера для adapter_status.json.

        Returns
        -------
        dict
            protocol_id, chain, tier, apy_pct, tvl_usd, risk_score,
            t2_cap_pct, write_state, last_updated, pool_id.
        """
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
        """Проверка работоспособности без сетевых вызовов (использует fallback APY).

        Returns
        -------
        dict
            Статус "ok", метрики адаптера, флаг tvl_floor_ok.
        """
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
            "gas_base_usd": GAS_BASE_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "status": "ok",
        }

    def to_dict(self) -> dict:
        """Полное представление адаптера для дашборда и отчётов."""
        apy_pct = self.get_apy()
        return {
            "protocol": self.PROTOCOL_ID,
            "pool_id": self.pool_id,
            "name": "Aave V3 Base USDC",
            "chain": self.CHAIN,
            "tier": self.TIER,
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t2_cap_pct": self.T2_CAP_PCT,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "gas_base_usd": GAS_BASE_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "l2_note": (
                "Base (Coinbase L2): газ ~20x дешевле Ethereum mainnet "
                "($0.005 vs $0.10 за tx). Finality: 2 сек (OP-stack). "
                "Bridge exit: 7 дней через official Coinbase bridge. "
                "T2 из-за L2 bridge risk (risk_score=0.35 vs 0.20 у mainnet T1)."
            ),
        }
