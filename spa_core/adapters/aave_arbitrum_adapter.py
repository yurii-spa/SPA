"""Aave V3 Arbitrum USDC адаптер — T1 anchor на L2 (MP-356).

Первый T1-классифицированный L2-адаптер SPA. Отслеживает рынок USDC.e
на Aave V3 Arbitrum (TVL > $1.2B, Arbitrum network).

Ключевые L2-преимущества:
  - Газ ~10x дешевле ($0.01 vs $0.10 на Ethereum mainnet)
  - Финальность ~15 минут (vs 7 дней для мостов)
  - Экономия $0.09 за транзакцию

APY-приоритет:
  1. data/adapter_status.json → ключ "aave_arbitrum" → поле "apy"
  2. Fallback: 4.1% (базовый Arbitrum premium ~+0.9% к mainnet 3.2%)

Этот модуль — строго read-only / advisory (paper-trading симуляция):
allocate() и withdraw() работают с виртуальным капиталом, не трогают
реальные активы. Никогда не импортируется из execution/ или risk/.

Ограничения FORBIDDEN:
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (не используются напрямую, но
    соблюдается во всех зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы сети и протокола
# ---------------------------------------------------------------------------

# Идентификаторы сети Arbitrum One
_NETWORK = "arbitrum"
_CHAIN_ID = 42161

# Контрактные адреса (read-only — только для метаданных, реальных вызовов нет)
_POOL_ADDRESS = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"   # Aave V3 Arbitrum Pool
_USDC_ADDRESS = "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"   # USDC.e на Arbitrum

# ---------------------------------------------------------------------------
# Газовые параметры L2 vs mainnet
# ---------------------------------------------------------------------------
_GAS_MAINNET_USD   = 0.10   # типичная стоимость газа на Ethereum mainnet
_GAS_L2_USD        = 0.01   # типичная стоимость газа на Arbitrum
_GAS_ADVANTAGE_USD = 0.09   # экономия за транзакцию (явная константа, без float-арифметики)
_FINALITY_MINUTES_L2    = 15   # мин до finality на Arbitrum
_FINALITY_DAYS_MAINNET  = 7    # дней для bridge finality на Ethereum

# ---------------------------------------------------------------------------
# APY и TVL
# ---------------------------------------------------------------------------
_APY_FALLBACK_PCT = 4.1          # % (Arbitrum premium ~+0.9% к mainnet 3.2%)
_APY_STATUS_KEY   = "aave_arbitrum"   # ключ в data/adapter_status.json
_TVL_USD          = 1_200_000_000    # $1.2B TVL на Arbitrum


class AaveArbitrumAdapter(BaseAdapter):
    """Aave V3 Arbitrum USDC — T1 anchor адаптер на L2 (MP-356).

    Параметры конструктора
    ----------------------
    asset : str
        Торгуемый актив. По умолчанию "USDC".
    data_dir : str | Path | None
        Путь к директории data/. Если None — вычисляется автоматически
        относительно корня репо (два уровня выше spa_core/).

    Атрибуты класса (константы)
    ---------------------------
    NETWORK        : "arbitrum"
    CHAIN_ID       : 42161
    POOL_ADDRESS   : адрес контракта Aave V3 Pool на Arbitrum
    USDC_ADDRESS   : адрес USDC.e на Arbitrum
    TIER           : "T1"
    T1_CAP         : 0.40 (максимум 40% портфеля)
    RISK_SCORE     : 0.22 (T1 L2 — ниже риска чем T2)
    APY_FALLBACK   : 4.1 (%)
    """

    # Сетевые константы — публичные для доступа из тестов
    NETWORK        = _NETWORK
    CHAIN_ID       = _CHAIN_ID
    POOL_ADDRESS   = _POOL_ADDRESS
    USDC_ADDRESS   = _USDC_ADDRESS

    # Tier и лимиты
    TIER      = "T1"
    T1_CAP    = 0.40
    PROTOCOL  = "aave_arbitrum"

    # Риск-профиль
    RISK_SCORE          = 0.22   # T1 L2: чуть выше mainnet T1 (0.20) из-за bridge-риска
    EXIT_LATENCY_HOURS  = 0.0    # мгновенный выход (same-block на L2)

    # APY
    APY_FALLBACK    = _APY_FALLBACK_PCT
    _APY_STATUS_KEY = _APY_STATUS_KEY

    # TVL
    TVL_USD = _TVL_USD

    # Газовые метрики
    GAS_L2_USD        = _GAS_L2_USD
    GAS_MAINNET_USD   = _GAS_MAINNET_USD
    GAS_ADVANTAGE_USD = _GAS_ADVANTAGE_USD

    # Стабильный идентификатор для дашбордов
    pool_id = "aave-v3-usdc-arbitrum-t1"

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

        # Определяем путь к data/
        if data_dir is None:
            # spa_core/adapters/aave_arbitrum_adapter.py → repo root / data
            self._data_dir: Path = (
                Path(__file__).resolve().parents[2] / "data"
            )
        else:
            self._data_dir = Path(data_dir)

        # Виртуальная позиция для paper-trading симуляции
        self._allocated_capital: float = 0.0

    # ------------------------------------------------------------------ #
    # APY-чтение (приоритет: JSON → fallback)                              #
    # ------------------------------------------------------------------ #

    def _load_apy_from_status(self) -> Optional[float]:
        """Читает APY из data/adapter_status.json, ключ aave_arbitrum.

        Возвращает float (%) если запись существует и валидна, иначе None.
        Никогда не бросает исключений — ошибки логируются предупреждением.
        """
        status_path = self._data_dir / "adapter_status.json"
        try:
            with open(status_path, encoding="utf-8") as fh:
                data = json.load(fh)
            entry = data.get(self._APY_STATUS_KEY)
            if entry and isinstance(entry.get("apy"), (int, float)):
                return float(entry["apy"])
        except FileNotFoundError:
            logger.debug(
                "aave_arbitrum: adapter_status.json не найден, используем fallback APY"
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "aave_arbitrum: ошибка чтения adapter_status.json: %s", exc
            )
        return None

    def get_apy(self) -> float:
        """Возвращает APY в процентах (напр. 4.1 означает 4.1%).

        Приоритет источника:
          1. data/adapter_status.json → ключ "aave_arbitrum" → поле "apy"
          2. Fallback: APY_FALLBACK = 4.1%
        """
        apy = self._load_apy_from_status()
        if apy is not None:
            return apy
        return self.APY_FALLBACK

    # ------------------------------------------------------------------ #
    # Обязательные методы BaseAdapter                                      #
    # ------------------------------------------------------------------ #

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора."""
        apy_pct = self.get_apy()
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            # YieldInfo.apy — decimal (0.041 для 4.1%)
            apy=apy_pct / 100.0,
            tvl_usd=float(self.TVL_USD),
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ------------------------------------------------------------------ #
    # Paper-trading: allocate / withdraw                                   #
    # ------------------------------------------------------------------ #

    def allocate(self, capital: float) -> dict:
        """Виртуальное размещение капитала на Aave V3 Arbitrum.

        Симулирует supply в пул USDC.e. Никогда не трогает реальные активы.

        Parameters
        ----------
        capital : float
            Сумма в USD для виртуального размещения. Должна быть > 0.

        Returns
        -------
        dict
            Статус операции, APY, ожидаемый годовой доход, сетевые метаданные.

        Raises
        ------
        ValueError
            Если capital ≤ 0.
        """
        if capital <= 0:
            raise ValueError(
                f"allocate: capital должен быть > 0, получено {capital}"
            )
        apy_pct = self.get_apy()
        self._allocated_capital += capital
        annual_yield = capital * (apy_pct / 100.0)

        return {
            "status": "allocated",
            "capital_usd": capital,
            "total_allocated_usd": self._allocated_capital,
            "apy_pct": apy_pct,
            "annual_yield_usd": round(annual_yield, 4),
            "network": self.NETWORK,
            "chain_id": self.CHAIN_ID,
            "pool_address": self.POOL_ADDRESS,
            "usdc_address": self.USDC_ADDRESS,
            "gas_cost_usd": self.GAS_L2_USD,
            "ts": time.time(),
        }

    def withdraw(self, amount: float) -> dict:
        """Виртуальный вывод капитала с Aave V3 Arbitrum.

        Симулирует withdraw из пула USDC.e. Никогда не трогает реальные
        активы. Сумма не может превышать текущую виртуальную позицию.

        Parameters
        ----------
        amount : float
            Сумма в USD для вывода. Должна быть > 0 и ≤ allocated_capital.

        Returns
        -------
        dict
            Статус операции, остаток позиции, сетевые метаданные.

        Raises
        ------
        ValueError
            Если amount ≤ 0 или amount > allocated_capital.
        """
        if amount <= 0:
            raise ValueError(
                f"withdraw: amount должен быть > 0, получено {amount}"
            )
        if amount > self._allocated_capital:
            raise ValueError(
                f"withdraw: запрос {amount:.2f} превышает размещённый "
                f"капитал {self._allocated_capital:.2f}"
            )
        self._allocated_capital -= amount

        return {
            "status": "withdrawn",
            "amount_usd": amount,
            "remaining_allocated_usd": self._allocated_capital,
            "network": self.NETWORK,
            "chain_id": self.CHAIN_ID,
            "pool_address": self.POOL_ADDRESS,
            "gas_cost_usd": self.GAS_L2_USD,
            "ts": time.time(),
        }

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                               #
    # ------------------------------------------------------------------ #

    def get_gas_estimate(self) -> dict:
        """Оценка газовых расходов — Arbitrum L2 vs Ethereum mainnet.

        Returns
        -------
        dict
            Детальная разбивка газовых метрик с преимуществами L2.
        """
        return {
            "network": self.NETWORK,
            "chain_id": self.CHAIN_ID,
            "gas_cost_usd": self.GAS_L2_USD,
            "mainnet_gas_cost_usd": self.GAS_MAINNET_USD,
            "gas_advantage_usd": self.GAS_ADVANTAGE_USD,
            "gas_multiplier": round(self.GAS_MAINNET_USD / self.GAS_L2_USD),
            "finality_minutes": _FINALITY_MINUTES_L2,
            "mainnet_finality_days": _FINALITY_DAYS_MAINNET,
        }

    def health_check(self) -> dict:
        """Проверка работоспособности адаптера (без сетевых вызовов).

        Проверяет корректность конфигурации, TVL floor из RiskPolicy (≥$5M),
        источник APY (JSON или fallback).

        Returns
        -------
        dict
            Статус "ok", метрики адаптера, флаг tvl_floor_ok.
        """
        apy_pct = self.get_apy()
        apy_from_file = self._load_apy_from_status()

        return {
            "protocol": self.PROTOCOL,
            "network": self.NETWORK,
            "chain_id": self.CHAIN_ID,
            "tier": self.TIER,
            "pool_address": self.POOL_ADDRESS,
            "usdc_address": self.USDC_ADDRESS,
            "apy_pct": apy_pct,
            "apy_source": "adapter_status" if apy_from_file is not None else "fallback",
            "tvl_usd": self.TVL_USD,
            # TVL floor RiskPolicy: ≥ $5M
            "tvl_floor_ok": self.TVL_USD >= 5_000_000,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "gas_advantage_usd": self.GAS_ADVANTAGE_USD,
            "allocated_capital_usd": self._allocated_capital,
            "status": "ok",
        }

    def to_dict(self) -> dict:
        """Полное представление адаптера для дашборда и отчётов.

        Включает сетевые метаданные, APY, TVL, газовые преимущества L2
        и arbitrage_note с описанием выгод Arbitrum vs mainnet.

        Returns
        -------
        dict
            Полный снапшот состояния адаптера.
        """
        apy_pct = self.get_apy()
        return {
            "protocol": self.PROTOCOL,
            "pool_id": self.pool_id,
            "name": "Aave V3 Arbitrum USDC",
            "tier": self.TIER,
            # Сетевые данные
            "network": self.NETWORK,
            "chain_id": self.CHAIN_ID,
            "pool_address": self.POOL_ADDRESS,
            "usdc_address": self.USDC_ADDRESS,
            # Финансовые метрики
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t1_cap": self.T1_CAP,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            # L2 преимущества (ключевые поля по спецификации MP-356)
            "gas_advantage_usd": self.GAS_ADVANTAGE_USD,
            "arbitrage_note": (
                "Arbitrum L2: газ ~10x дешевле ($0.01 vs $0.10 на Ethereum mainnet), "
                "финальность ~15 мин vs 7 дней для мостов. "
                "APY Arbitrum premium +0.9% к mainnet (3.2% → 4.1%)."
            ),
            # Детализация L2 преимуществ
            "l2_advantages": {
                "gas_cost_usd": self.GAS_L2_USD,
                "mainnet_gas_cost_usd": self.GAS_MAINNET_USD,
                "gas_savings_per_tx_usd": self.GAS_ADVANTAGE_USD,
                "gas_multiplier": round(self.GAS_MAINNET_USD / self.GAS_L2_USD),
                "finality_minutes": _FINALITY_MINUTES_L2,
                "mainnet_finality_days": _FINALITY_DAYS_MAINNET,
            },
            # Paper-trading состояние
            "allocated_capital_usd": self._allocated_capital,
        }
