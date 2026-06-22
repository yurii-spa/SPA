"""Moonwell Finance Base USDC Adapter (MP-463).

Moonwell Finance — ведущий lending protocol на Base chain.
DeFiLlama: https://api.llama.fi/pools (project=moonwell-finance, chain=Base, symbol=USDC)

Tier: T2 (TVL ~$500M на Base, устоявшийся протокол)
Risk Score: 0.75 (повышен с 0.36 из-за хака Nov 2025, ADR-026)
Chain: Base (L2)
Phase: ADR-025 Phase 1 (monitoring only, no allocation until 2026-08-01)

⚠️  SECURITY INCIDENT (ADR-026):
    Hack: November 2025 — Chainlink oracle manipulation.
    Impact: ~$1M stolen; $3.7M bad debt (not cleared as of 2026-06-12).
    Status: SUSPENDED — reassess December 2026 after full recovery.

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

Особенности Base chain (Moonwell):
  - Bridge risk: активы поступают через official Coinbase bridge
    (оптимистический период 7 дней для вывода на mainnet)
  - Газ: ~10-30x дешевле Ethereum mainnet ($0.001–0.01 за tx)
  - Finality: ~2 секунды (OP-stack sequencer), затем Ethereum ~12 мин
  - TVL Moonwell на Base: ~$500M (данные 2026-06)
  - Moonwell — форк Compound V2, аудирован, работает на Base с 2023
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
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter, YieldInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы протокола
# ---------------------------------------------------------------------------

ADAPTER_ID = "moonwell-base"
PROTOCOL_ID = "moonwell-base"
ADAPTER_NAME = "Moonwell Finance USDC (Base)"
CHAIN = "base"
TIER = "T2"

# TVL в USD (~$500M на Base, данные 2026-06)
TVL_USD = 500_000_000

# Risk score: повышен с 0.36 до 0.75 из-за хака Nov 2025 (ADR-026)
RISK_SCORE = 0.75  # было 0.36 — повышен из-за хака Nov 2025 (ADR-026)

# === SECURITY INCIDENT ===
# ADR-026: Moonwell Finance hack November 2025
# Mechanism: Chainlink oracle manipulation
# Impact: ~$1M stolen + $3.7M bad debt (not cleared as of 2026-06-12)
# Status: SUSPENDED — reassess December 2026 after full recovery
HACK_DATE = "2025-11"
HACK_IMPACT_USD = 1_000_000
BAD_DEBT_USD = 3_700_000
ADAPTER_STATUS = "suspended"

# APY fallback (%) если DeFiLlama недоступен
APY_FALLBACK = 5.5

# Максимальная доля портфеля для T2 (20%, ADR-025 Base chain cap)
T2_CAP_PCT = 20

# ---------------------------------------------------------------------------
# DeFiLlama API
# ---------------------------------------------------------------------------

_DEFILLAMA_URL = "https://yields.llama.fi/pools"
_REQUEST_TIMEOUT = 10  # секунд

# DeFiLlama project slug для Moonwell
_DEFILLAMA_PROJECTS = ("moonwell-finance", "moonwell")

# Допустимые символы USDC-пулов на Base
_USDC_SYMBOLS = {"USDC", "USDC.E", "USDBC", "USDBC.E"}

# Санитарные границы APY (%)
_APY_MIN = 0.1
_APY_MAX = 50.0

# Минимальный TVL пула чтобы считаться живым ($1M)
_MIN_POOL_TVL = 1_000_000.0

# Конфиг DeFiLlama (публичные константы для тестов)
DEFILLAMA_POOLS_URL = _DEFILLAMA_URL
DEFILLAMA_PROJECT = "moonwell-finance"
DEFILLAMA_CHAIN = "Base"
DEFILLAMA_SYMBOL_HINT = "USDC"
DEFILLAMA_TIMEOUT_S = _REQUEST_TIMEOUT
DEFILLAMA_CACHE_TTL_S = 3600  # 1 час

# ---------------------------------------------------------------------------
# L2 газовые параметры
# ---------------------------------------------------------------------------

GAS_BASE_USD = 0.005       # типичная стоимость tx на Base
GAS_MAINNET_USD = 0.10     # типичная стоимость tx на Ethereum mainnet
GAS_ADVANTAGE_USD = 0.095  # явная константа экономии (без float-арифметики)
FINALITY_SECONDS_BASE = 2  # OP-stack sequencer finality (секунды)

# Module-level cache (для standalone-функции get_apy())
_cache: Dict[str, Any] = {}


class MoonwellBaseAdapter(BaseAdapter):
    """Moonwell Finance USDC адаптер для Base chain (ADR-025 Phase 1 monitoring).

    Read-only — получает живые APY/TVL из DeFiLlama. При недоступности сети
    возвращает APY_FALLBACK. Никогда не бросает исключений публично.

    Параметры конструктора
    ----------------------
    asset : str
        Торгуемый актив. По умолчанию "USDC".
    data_dir : str | Path | None
        Путь к директории data/. Если None — вычисляется автоматически.

    Атрибуты класса (константы)
    ---------------------------
    ADAPTER_ID   : "moonwell-base"
    PROTOCOL_ID  : "moonwell-base"
    ADAPTER_NAME : "Moonwell Finance USDC (Base)"
    CHAIN        : "base"
    TIER         : "T2"
    TVL_USD      : 500_000_000
    RISK_SCORE   : 0.75 (повышен с 0.36 из-за хака Nov 2025, ADR-026)
    APY_FALLBACK : 5.5 (%)
    T2_CAP_PCT   : 20 (% портфеля, ADR-025)
    ADAPTER_STATUS : "suspended" (ADR-026)
    HACK_DATE    : "2025-11"
    """

    # Публичные константы (доступны из тестов и реестра)
    ADAPTER_ID = ADAPTER_ID
    PROTOCOL_ID = PROTOCOL_ID
    ADAPTER_NAME = ADAPTER_NAME
    CHAIN = CHAIN
    TIER = TIER
    TVL_USD = TVL_USD
    RISK_SCORE = RISK_SCORE
    APY_FALLBACK = APY_FALLBACK
    T2_CAP_PCT = T2_CAP_PCT
    # Security incident constants (ADR-026)
    ADAPTER_STATUS = ADAPTER_STATUS
    HACK_DATE = HACK_DATE
    HACK_IMPACT_USD = HACK_IMPACT_USD
    BAD_DEBT_USD = BAD_DEBT_USD

    # Для BaseAdapter
    PROTOCOL = PROTOCOL_ID
    EXIT_LATENCY_HOURS = 0.0  # мгновенный выход (same-block lending)

    # Стабильный идентификатор для дашборда
    pool_id = "moonwell-usdc-base"

    # ------------------------------------------------------------------ #
    # Инициализация                                                        #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[Any] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER

        if data_dir is None:
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
            Список пулов при успехе, None при любой ошибке.
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
                    "moonwell_base: DeFiLlama вернул неожиданный формат"
                )
                return None
            return pools
        except urllib.error.URLError as exc:
            logger.warning("moonwell_base: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("moonwell_base: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_usdc_pool(self, pools: list) -> Optional[dict]:
        """Находит лучший USDC-пул Moonwell на Base.

        Фильтрация:
          - chain == "Base" (case-insensitive)
          - project: один из _DEFILLAMA_PROJECTS (moonwell-finance, moonwell)
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
                    "moonwell_base: пул %s имеет аномальный APY %.2f%% — пропускаем",
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
                "moonwell_base: подходящий USDC-пул Moonwell на Base "
                "не найден в DeFiLlama"
            )
            return None
        apy = float(best.get("apy", 0.0))
        logger.info(
            "moonwell_base: live APY=%.3f%% из пула %s (TVL=%.0f)",
            apy,
            best.get("pool", "?"),
            best.get("tvlUsd", 0),
        )
        return apy

    # ------------------------------------------------------------------ #
    # Публичные методы (BaseAdapter interface)                             #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (например 5.5 == 5.5%).

        Приоритет:
          1. Живые данные DeFiLlama (Base / moonwell-finance / USDC)
          2. APY_FALLBACK = 5.5% при недоступности сети

        Никогда не бросает исключений.
        """
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "moonwell_base: DeFiLlama недоступен, используем fallback APY=%.1f%%",
            self.APY_FALLBACK,
        )
        return float(self.APY_FALLBACK)

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        YieldInfo.apy — decimal (0.055 для 5.5%).
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

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус адаптера совместимый со spec интерфейсом (MP-463).

        Returns
        -------
        dict
            adapter_id, name, tier, chain, apy_pct, tvl_usd,
            risk_score, phase, adr.
        """
        apy = self.get_apy()
        return {
            "adapter_id": ADAPTER_ID,
            "name": ADAPTER_NAME,
            "tier": TIER,
            "chain": CHAIN,
            "apy_pct": apy,
            "tvl_usd": float(TVL_USD),
            "risk_score": RISK_SCORE,
            "phase": "phase1_monitoring",
            "adr": "ADR-025",
            "adapter_status": ADAPTER_STATUS,
            "hack_date": HACK_DATE,
            "hack_impact_usd": HACK_IMPACT_USD,
            "bad_debt_usd": BAD_DEBT_USD,
            "security_note": "SUSPENDED: Chainlink oracle exploit Nov 2025, $3.7M bad debt uncleared",
        }

    def get_apy_with_metadata(self) -> Dict[str, Any]:
        """Возвращает полный статус — псевдоним get_status()."""
        return self.get_status()

    def get_write_state(self) -> dict:
        """Возвращает словарь состояния для adapter_status.json."""
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

    def validate(self):
        """Проверяет корректность данных адаптера.

        Returns
        -------
        tuple (bool, str)
            (False, reason) если адаптер suspended или данные некорректны.
            (True, "ok") если данные корректны.
        """
        if ADAPTER_STATUS == "suspended":
            return False, f"Adapter suspended due to security incident: {HACK_DATE}"
        try:
            apy_pct = self.get_apy()
            if bool(apy_pct > 0 and self.TVL_USD > 0):
                return True, "ok"
            return False, "apy or tvl is zero"
        except Exception:  # noqa: BLE001
            return False, "exception during validation"

    def health_check(self) -> dict:
        """Проверка работоспособности (использует fallback APY, без сети).

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
            "name": ADAPTER_NAME,
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
            "phase": "phase1_monitoring",
            "adr": "ADR-025",
            "l2_note": (
                "Base (Coinbase L2): газ ~20x дешевле Ethereum mainnet "
                "($0.005 vs $0.10 за tx). Finality: 2 сек (OP-stack). "
                "Bridge exit: 7 дней через official Coinbase bridge. "
                "T2 из-за L2 bridge risk (risk_score=0.75, повышен из-за хака Nov 2025, ADR-026). "
                "ADR-025: Base chain expansion. TVL ~$500M. ADAPTER_STATUS=suspended."
            ),
        }


# ---------------------------------------------------------------------------
# Standalone функция get_apy() с кэшем (для обратной совместимости)
# ---------------------------------------------------------------------------

def get_apy() -> float:
    """Возвращает APY для Moonwell USDC на Base. Использует module-level cache."""
    now = time.time()
    if _cache.get("ts", 0) + DEFILLAMA_CACHE_TTL_S > now:
        cached = _cache.get("apy")
        if cached is not None:
            return float(cached)

    adapter = MoonwellBaseAdapter()
    result = adapter._fetch_live_apy()
    if result is not None:
        _cache["apy"] = result
        _cache["ts"] = now
        return result
    return float(APY_FALLBACK)
