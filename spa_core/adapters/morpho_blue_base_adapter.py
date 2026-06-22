"""Morpho Blue Base chain adapter — T2 tier (MP-450).

Chain: Base (Coinbase L2)
Tier: T2 — TVL ~$180M, аудированный код Morpho Blue (тот же что на mainnet),
      но L2 bridge риск = premium к риск-скору
Pool: USDC / cbETH / другие активы на Morpho Blue Base
APY source: DeFiLlama /pools — project=morpho, chain=Base, symbol contains USDC

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

Особенности Base chain (Morpho Blue):
  - Bridge risk: активы поступают через official Coinbase bridge
    (оптимистический период 7 дней для вывода на mainnet)
  - Газ: ~10-30x дешевле Ethereum mainnet ($0.001–0.01 за tx)
  - Finality: ~2 секунды (OP-stack sequencer), затем Ethereum ~12 мин
  - TVL Morpho Blue на Base: ~$180M (данные 2026-06)
  - Тот же аудированный код Morpho Blue что на mainnet, но TVL ниже T1 порога $500M
  - APY premium: +1.5–2.5% к Aave mainnet за счёт меньшей ликвидности
  - ADR-025: Base chain expansion plan — shared Base chain cap
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

PROTOCOL_ID = "morpho-blue-base"
CHAIN = "base"
TIER = "T2"

# TVL в USD (~$180M на Base, данные 2026-06)
TVL_USD = 180_000_000

# Risk score: выше mainnet Morpho (0.30) из-за L2 bridge риска
RISK_SCORE = 0.38

# APY fallback (%) если DeFiLlama недоступен
APY_FALLBACK = 6.2

# Максимальная доля портфеля для T2 (20%, ADR-025 Base chain cap)
T2_CAP_PCT = 20

# ---------------------------------------------------------------------------
# DeFiLlama API
# ---------------------------------------------------------------------------

_DEFILLAMA_URL = "https://yields.llama.fi/pools"
_REQUEST_TIMEOUT = 10  # секунд

# Проекты Morpho на Base (DeFiLlama использует различные slug-и)
_DEFILLAMA_PROJECTS = ("morpho", "morpho-blue")

# Допустимые символы USDC-пулов на Base
_USDC_SYMBOLS = {"USDC", "USDC.E", "USDBC", "USDBC.E"}

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


class MorphoBlueBaseAdapter(BaseAdapter):
    """Read-only адаптер Morpho Blue USDC на Base chain (T2, MP-450).

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
    PROTOCOL_ID   : "morpho-blue-base"
    CHAIN         : "base"
    TIER          : "T2"
    TVL_USD       : 180_000_000
    RISK_SCORE    : 0.38
    APY_FALLBACK  : 6.2 (%)
    T2_CAP_PCT    : 20 (% портфеля, ADR-025)
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
    pool_id = "morpho-blue-usdc-base"

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
            # spa_core/adapters/morpho_blue_base_adapter.py → repo root / data
            self._data_dir: Path = (
                Path(__file__).resolve().parents[2] / "data"
            )
        else:
            self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------ #
    # DeFiLlama fetch                                                      #
    # ------------------------------------------------------------------ #

    def _fetch_pools_raw(self) -> Optional[list]:
        """Загружает список пулов из DeFiLlama /pools.

        Returns
        -------
        list | None
            Список пулов при успехе, None при любой ошибке сети или парсинга.
        """
        try:
            req = urllib.request.Request(
                _DEFILLAMA_URL,
                headers={"Accept-Encoding": "gzip", "User-Agent": "SPA/1.0"},
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                raw = resp.read()

            # gzip decode если нужно
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)

            data = json.loads(raw.decode("utf-8"))
            pools = data.get("data") if isinstance(data, dict) else data
            if not isinstance(pools, list):
                logger.warning(
                    "morpho_blue_base: DeFiLlama вернул неожиданный формат"
                )
                return None
            return pools
        except urllib.error.URLError as exc:
            logger.warning("morpho_blue_base: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("morpho_blue_base: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_usdc_pool(
        self, pools: list[dict]
    ) -> Optional[dict]:
        """Находит лучший USDC-пул Morpho Blue на Base.

        Фильтрация:
          - chain == "Base" (case-insensitive)
          - project: один из _DEFILLAMA_PROJECTS (morpho, morpho-blue)
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
                    "morpho_blue_base: пул %s имеет аномальный APY %.2f%% — пропускаем",
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
                "morpho_blue_base: подходящий USDC-пул Morpho на Base "
                "не найден в DeFiLlama"
            )
            return None
        apy = float(best.get("apy", 0.0))
        logger.info(
            "morpho_blue_base: live APY=%.3f%% из пула %s (TVL=%.0f)",
            apy,
            best.get("pool", "?"),
            best.get("tvlUsd", 0),
        )
        return apy

    # ------------------------------------------------------------------ #
    # Публичные методы (BaseAdapter interface)                             #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (например 6.2 == 6.2%).

        Приоритет:
          1. Живые данные DeFiLlama (Base / morpho / USDC)
          2. APY_FALLBACK = 6.2% при недоступности сети

        Никогда не бросает исключений.
        """
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "morpho_blue_base: DeFiLlama недоступен, используем fallback APY=%.1f%%",
            self.APY_FALLBACK,
        )
        return self.APY_FALLBACK

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        YieldInfo.apy — decimal (0.062 для 6.2%).
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

    def validate(self) -> bool:
        """Проверяет корректность данных адаптера.

        Returns
        -------
        bool
            True если apy_pct > 0 и tvl_usd > 0, иначе False.
        """
        try:
            apy_pct = self.get_apy()
            return bool(apy_pct > 0 and self.TVL_USD > 0)
        except Exception:  # noqa: BLE001
            return False

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
            "name": "Morpho Blue Base USDC",
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
                "T2 из-за L2 bridge risk (risk_score=0.38 vs 0.22 у mainnet Morpho T1). "
                "ADR-025: Base chain expansion. TVL ~$180M (ниже T1 порога $500M)."
            ),
        }
