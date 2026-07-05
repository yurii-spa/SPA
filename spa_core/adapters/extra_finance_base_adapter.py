"""Extra Finance XLend Base USDC Adapter (MP-510).

MP-510: Extra Finance XLend — изолированный lending vault на Base chain.
ADR-026: Base chain expansion Phase 1 — read-only monitoring (no capital).

Аудиты: BlockSec + PeckShield + Sherlock (Dec 2024)
Bug Bounty: Immunefi
USDC APY: 7-12% (fallback = 8.0%)
TVL USDC lending pool: >$5M (флор RiskPolicy)
Tier: T3 (growtech, не T2 из-за возраста протокола)

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

ADR-026 Phase gates:
  Phase 1 (до 2026-08-01): monitoring only, no capital allocation
  Phase 2 (после go-live): max T3_CAP_PCT (5%) allocation

DeFiLlama: project="extra-finance", chain="Base", symbol="USDC"
"""
from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base_adapter import BaseAdapter, YieldInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы протокола
# ---------------------------------------------------------------------------

ADAPTER_ID = "extra_finance_base"
PROTOCOL_ID = "extra-finance-base"
PROTOCOL_NAME = "Extra Finance XLend"
ADAPTER_NAME = "Extra Finance XLend Base USDC"
CHAIN = "base"
TIER = "T3"

# Risk score: T3, 3 аудита (BlockSec + PeckShield + Sherlock), Immunefi,
# но молодой протокол → выше среднего для T3
RISK_SCORE = 0.55

# APY fallback (%) если DeFiLlama недоступен — середина диапазона 7-12%
APY_FALLBACK = 8.0

# TVL (USD)
TVL_USD = 135_000_000        # ~$135M total protocol TVL
TVL_USDC_LENDING = 15_000_000  # USDC lending pool estimate (>$5M — RiskPolicy floor ok)

# Максимальная доля портфеля для T3 (5%, ADR-026)
T3_CAP_PCT = 5

# ADR-026: Phase 2 date
PHASE2_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# DeFiLlama API
# ---------------------------------------------------------------------------

DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"
DEFILLAMA_PROJECT = "extra-finance"
DEFILLAMA_CHAIN = "Base"
DEFILLAMA_SYMBOL = "USDC"
DEFILLAMA_TIMEOUT_S = 10   # секунд
DEFILLAMA_CACHE_TTL_S = 3600  # 1 час

_REQUEST_TIMEOUT = DEFILLAMA_TIMEOUT_S

# Допустимые символы USDC-пулов на Base
_USDC_SYMBOLS = {"USDC", "USDC.E", "USDBC", "USDBC.E"}

# Санитарные границы APY (%)
_APY_MIN = 0.1
_APY_MAX = 100.0

# Минимальный TVL пула чтобы считаться живым ($1M)
_MIN_POOL_TVL = 1_000_000.0

# Module-level cache (для standalone-функции get_apy())
_cache: Dict[str, Any] = {}


class ExtraFinanceBaseAdapter(BaseAdapter):
    """Extra Finance XLend USDC адаптер для Base chain (ADR-026 Phase 1 monitoring).

    Изолированный lending vault на Base. Read-only — получает живые APY/TVL
    из DeFiLlama. При недоступности сети возвращает APY_FALLBACK.
    Никогда не бросает исключений публично.

    Параметры конструктора
    ----------------------
    asset : str
        Торгуемый актив. По умолчанию "USDC".
    data_dir : str | Path | None
        Путь к директории data/. Если None — вычисляется автоматически.

    Атрибуты класса (константы)
    ---------------------------
    ADAPTER_ID   : "extra_finance_base"
    PROTOCOL_ID  : "extra-finance-base"
    ADAPTER_NAME : "Extra Finance XLend Base USDC"
    CHAIN        : "base"
    TIER         : "T3"
    TVL_USD      : 135_000_000
    TVL_USDC_LENDING : 15_000_000
    RISK_SCORE   : 0.55
    APY_FALLBACK : 8.0 (%)
    T3_CAP_PCT   : 5 (% портфеля, ADR-026)
    """

    # Публичные константы (доступны из тестов и реестра)
    ADAPTER_ID = ADAPTER_ID
    PROTOCOL_ID = PROTOCOL_ID
    PROTOCOL_NAME = PROTOCOL_NAME
    ADAPTER_NAME = ADAPTER_NAME
    CHAIN = CHAIN
    TIER = TIER
    # ADR-026 Phase-1 MONITORING (not graduated to live): isolated Base lending vault kept
    # for advisory tracking only. IS_ADVISORY keeps it out of the live allocatable universe.
    IS_ADVISORY = True
    TVL_USD = TVL_USD
    TVL_USDC_LENDING = TVL_USDC_LENDING
    RISK_SCORE = RISK_SCORE
    APY_FALLBACK = APY_FALLBACK
    T3_CAP_PCT = T3_CAP_PCT
    PHASE2_DATE = PHASE2_DATE

    # Для BaseAdapter
    PROTOCOL = PROTOCOL_ID
    EXIT_LATENCY_HOURS = 0.0  # мгновенный выход (same-block lending)

    # Стабильный идентификатор для дашборда
    pool_id = "extra-finance-xlend-usdc-base"

    # Аудиты протокола
    AUDITS = ["BlockSec", "PeckShield", "Sherlock"]
    BUG_BOUNTY = "Immunefi"

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
                DEFILLAMA_POOLS_URL,
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
                    "extra_finance_base: DeFiLlama вернул неожиданный формат"
                )
                return None
            return pools
        except urllib.error.URLError as exc:
            logger.warning("extra_finance_base: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("extra_finance_base: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_usdc_pool(self, pools: list) -> Optional[dict]:
        """Находит лучший USDC-пул Extra Finance на Base.

        Фильтрация:
          - chain == "Base" (case-insensitive)
          - project: содержит "extra-finance" или "extra_finance" или "extrafinance"
          - symbol: один из _USDC_SYMBOLS (case-insensitive, после strip)
          - tvlUsd >= _MIN_POOL_TVL
          - apy в диапазоне [_APY_MIN, _APY_MAX]

        Среди кандидатов выбирается пул с максимальным TVL.
        """
        _EXTRA_FINANCE_SLUGS = ("extra-finance", "extra_finance", "extrafinance")

        best: Optional[dict] = None
        best_tvl: float = float("-inf")

        for pool in pools:
            if not isinstance(pool, dict):
                continue

            # Проверяем chain
            if str(pool.get("chain", "")).lower() != "base":
                continue

            # Проверяем project
            proj = str(pool.get("project", "")).lower().replace(" ", "-")
            if not any(slug in proj for slug in _EXTRA_FINANCE_SLUGS):
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
                    "extra_finance_base: пул %s имеет аномальный APY %.2f%% — пропускаем",
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
                "extra_finance_base: подходящий USDC-пул Extra Finance на Base "
                "не найден в DeFiLlama"
            )
            return None
        apy = float(best.get("apy", 0.0))
        logger.info(
            "extra_finance_base: live APY=%.3f%% из пула %s (TVL=%.0f)",
            apy,
            best.get("pool", "?"),
            best.get("tvlUsd", 0),
        )
        return apy

    # ------------------------------------------------------------------ #
    # Публичные методы (BaseAdapter interface)                             #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (например 8.0 == 8.0%).

        Приоритет:
          1. Живые данные DeFiLlama (Base / extra-finance / USDC)
          2. APY_FALLBACK = 8.0% при недоступности сети

        Никогда не бросает исключений.
        """
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "extra_finance_base: DeFiLlama недоступен, "
            "используем fallback APY=%.1f%%",
            self.APY_FALLBACK,
        )
        return float(self.APY_FALLBACK)

    def get_yield_info(self) -> dict:
        """Возвращает полную информацию о доходности.

        Returns
        -------
        dict
            apy_pct, tvl_usd, tvl_usdc_lending, protocol_name, tier,
            risk_score, chain, audits, bug_bounty.
        """
        apy_pct = self.get_apy()
        return {
            "adapter_id": ADAPTER_ID,
            "protocol_name": PROTOCOL_NAME,
            "apy_pct": apy_pct,
            "tvl_usd": float(TVL_USD),
            "tvl_usdc_lending": float(TVL_USDC_LENDING),
            "tier": TIER,
            "risk_score": RISK_SCORE,
            "chain": CHAIN,
            "asset": self.asset,
            "audits": self.AUDITS,
            "bug_bounty": self.BUG_BOUNTY,
            "phase": "phase1_monitoring",
            "adr": "ADR-026",
        }

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус адаптера совместимый со spec интерфейсом (MP-510).

        Returns
        -------
        dict
            adapter_id, tier, chain, risk_score, phase, adr, apy_pct,
            tvl_usd, tvl_usdc_lending, protocol_name.
        """
        apy = self.get_apy()
        return {
            "adapter_id": ADAPTER_ID,
            "protocol_name": PROTOCOL_NAME,
            "tier": TIER,
            "chain": CHAIN,
            "apy_pct": apy,
            "tvl_usd": float(TVL_USD),
            "tvl_usdc_lending": float(TVL_USDC_LENDING),
            "risk_score": RISK_SCORE,
            "phase": "phase1_monitoring",
            "adr": "ADR-026",
            "audits": self.AUDITS,
            "bug_bounty": self.BUG_BOUNTY,
        }

    def get_apy_with_metadata(self) -> Dict[str, Any]:
        """Возвращает полный статус — псевдоним get_status()."""
        return self.get_status()

    def validate(self) -> Tuple[bool, str]:
        """Проверяет корректность данных адаптера.

        Returns
        -------
        Tuple[bool, str]
            (True, "ok") если TVL_USDC_LENDING >= 5_000_000 (RiskPolicy floor),
            (False, reason) иначе.
        """
        try:
            if self.TVL_USDC_LENDING < 5_000_000:
                return (
                    False,
                    f"TVL_USDC_LENDING={self.TVL_USDC_LENDING} < 5_000_000 (RiskPolicy floor)",
                )
            return (True, "ok")
        except Exception as exc:  # noqa: BLE001
            return (False, f"validate error: {exc}")

    def health_check(self) -> bool:
        """Проверка работоспособности (без сети).

        Returns
        -------
        bool
            True если адаптер инициализирован корректно.
        """
        try:
            valid, _ = self.validate()
            return valid and self.APY_FALLBACK > 0
        except Exception:  # noqa: BLE001
            return False

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
            "tvl_usdc_lending": self.TVL_USDC_LENDING,
            "risk_score": self.RISK_SCORE,
            "t3_cap_pct": self.T3_CAP_PCT,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "phase": "phase1_monitoring",
            "phase2_date": self.PHASE2_DATE,
            "adr": "ADR-026",
            "audits": self.AUDITS,
            "bug_bounty": self.BUG_BOUNTY,
            "l2_note": (
                "Base (Coinbase L2): газ ~20x дешевле Ethereum mainnet. "
                "Extra Finance XLend: изолированный lending vault. "
                "3 аудита (BlockSec + PeckShield + Sherlock Dec 2024). "
                "T3 из-за возраста протокола. ADR-026 Phase 1: monitoring only. "
                f"USDC lending TVL ~${self.TVL_USDC_LENDING:,.0f}."
            ),
        }


# ---------------------------------------------------------------------------
# Standalone функция get_apy() с кэшем (для обратной совместимости)
# ---------------------------------------------------------------------------

def get_apy(fallback: float = APY_FALLBACK) -> float:
    """Возвращает APY для Extra Finance XLend USDC на Base.

    Использует module-level cache (TTL 1 час).
    При недоступности сети возвращает fallback.
    """
    now = time.time()
    if _cache.get("ts", 0) + DEFILLAMA_CACHE_TTL_S > now:
        cached = _cache.get("apy")
        if cached is not None:
            return float(cached)

    adapter = ExtraFinanceBaseAdapter()
    result = adapter._fetch_live_apy()
    if result is not None:
        _cache["apy"] = result
        _cache["ts"] = now
        return result
    return float(fallback)
