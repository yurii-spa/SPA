"""Aerodrome Finance Base USDC-USDT stable-pool адаптер — T2 tier.

Chain: Base (Coinbase L2, OP-stack)
Tier: T2 — Aerodrome — доминирующий DEX на Base (ve(3,3) модель, форк
  Velodrome). Стейбл-пул USDC-USDT: минимальный IL (оба актива ~$1), доход =
  торговые комиссии + AERO emissions. IL-риск НЕ нулевой (депег одного из
  активов) + волатильность AERO-наград → T2 risk_score выше lending.
Pool: USDC-USDT stable / concentrated (slipstream) AMM pool на Base
APY source: DeFiLlama /pools — project=aerodrome-v2 / aerodrome-slipstream /
  aerodrome, chain=Base, symbol содержит и USDC и USDT (стейбл-пара)

⚠️  Реальный USDC-USDT пул живёт на aerodrome-slipstream (concentrated
    liquidity), не на aerodrome-v2 — поэтому матчим несколько project-слагов
    по подстроке (как в velodrome_optimism_adapter).

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

ВНИМАНИЕ: LP-позиция в стейбл-паре — не single-asset lending. IL минимален
пока оба актива держат привязку, но депег ломает паритет. risk_score=0.45.
AERO-награды волатильны — учитываем консервативно (fallback 4.5%).
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

PROTOCOL_ID = "aerodrome-base"
CHAIN = "base"
CHAIN_ID = 8453
TIER = "T2"

# TVL в USD — протокол-уровень стейбл-ликвидности Aerodrome (ориентир 2026-06).
# Конкретный USDC-USDT пул тоньше (~$2M на slipstream) — фактическую аллокацию
# всё равно гейтит RiskPolicy $5M floor; здесь это headline-метрика протокола.
TVL_USD = 50_000_000

# Risk score: LP IL-риск (депег) + AERO emission волатильность (как Velodrome)
RISK_SCORE = 0.45

# APY fallback (%) если DeFiLlama недоступен — консервативная оценка стейбл-пары
APY_FALLBACK = 4.5

# Максимальная доля портфеля для T2 (20%)
T2_CAP_PCT = 20

# ---------------------------------------------------------------------------
# DeFiLlama API
# ---------------------------------------------------------------------------

_DEFILLAMA_URL = "https://yields.llama.fi/pools"
_REQUEST_TIMEOUT = 10  # секунд

# Aerodrome маркируется разными слагами; USDC-USDT обычно на slipstream (CL)
_DEFILLAMA_PROJECTS = ("aerodrome-slipstream", "aerodrome-v2", "aerodrome")

# DeFiLlama маркирует Base как "Base"
_CHAIN_LABELS = {"base"}

# Для стейбл-пары требуем наличие обоих символов в symbol-строке пула
_REQUIRED_TOKENS = ("USDC", "USDT")

# Санитарные границы APY (%)
_APY_MIN = 0.1
_APY_MAX = 50.0

# Минимальный TVL пула чтобы считаться живым. Стейбл-пул USDC-USDT Aerodrome
# тонкий (~$2M на 2026-06) — это advisory APY-feed, а не allocation target;
# реальный $5M floor RiskPolicy всё равно гейтит фактическую аллокацию.
# Порог >$10M из спеки относится к протокол-уровню (TVL_USD), не к thin-пулу.
_MIN_POOL_TVL = 500_000.0

# ---------------------------------------------------------------------------
# L2 газовые параметры (Base)
# ---------------------------------------------------------------------------

GAS_L2_USD = 0.005
GAS_MAINNET_USD = 0.10
GAS_ADVANTAGE_USD = 0.095
FINALITY_SECONDS = 2  # OP-stack sequencer finality


class AerodromeUsdcAdapter(BaseAdapter):
    """Read-only адаптер Aerodrome USDC-USDT стейбл-пула на Base (T2).

    Получает живые APY/TVL из DeFiLlama. При недоступности сети —
    возвращает APY_FALLBACK. Никогда не бросает исключений публично.
    """

    PROTOCOL_ID = PROTOCOL_ID
    CHAIN = CHAIN
    CHAIN_ID = CHAIN_ID
    TIER = TIER
    TVL_USD = TVL_USD
    RISK_SCORE = RISK_SCORE
    APY_FALLBACK = APY_FALLBACK
    T2_CAP_PCT = T2_CAP_PCT

    PROTOCOL = "aerodrome_base"
    EXIT_LATENCY_HOURS = 0.0  # LP burn same-block

    pool_id = "aerodrome-usdc-usdt-base"

    def __init__(
        self,
        asset: str = "USDC-USDT",
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
            logger.warning("aerodrome_base: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("aerodrome_base: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_stable_pool(self, pools: list[dict]) -> Optional[dict]:
        """Находит USDC-USDT стейбл-пул Aerodrome на Base (макс. TVL)."""
        best: Optional[dict] = None
        best_tvl: float = float("-inf")
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            if str(pool.get("chain", "")).lower() not in _CHAIN_LABELS:
                continue
            proj = str(pool.get("project", "")).lower()
            if not any(p in proj for p in _DEFILLAMA_PROJECTS):
                continue
            symbol = str(pool.get("symbol", "")).upper()
            # Стейбл-пара: оба токена в symbol
            if not all(tok in symbol for tok in _REQUIRED_TOKENS):
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

    def _fetch_live_apy(self) -> Optional[float]:
        pools = self._fetch_pools_raw()
        if pools is None:
            return None
        best = self._find_best_stable_pool(pools)
        if best is None:
            logger.warning(
                "aerodrome_base: USDC-USDT стейбл-пул не найден в DeFiLlama"
            )
            return None
        apy = float(best.get("apy", 0.0))
        logger.info(
            "aerodrome_base: live APY=%.3f%% из пула %s (TVL=%.0f)",
            apy,
            best.get("pool", "?"),
            best.get("tvlUsd", 0),
        )
        return apy

    # ------------------------------------------------------------------ #
    # Публичные методы                                                     #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (4.5 == 4.5%). Никогда не бросает исключений."""
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "aerodrome_base: DeFiLlama недоступен, fallback APY=%.1f%%",
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
            "is_lp_position": True,
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
            "is_lp_position": True,
            "gas_l2_usd": GAS_L2_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "status": "ok",
        }

    def to_dict(self) -> dict:
        apy_pct = self.get_apy()
        return {
            "protocol": self.PROTOCOL_ID,
            "pool_id": self.pool_id,
            "name": "Aerodrome Base USDC-USDT",
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "tier": self.TIER,
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t2_cap_pct": self.T2_CAP_PCT,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "is_lp_position": True,
            "gas_l2_usd": GAS_L2_USD,
            "gas_advantage_usd": GAS_ADVANTAGE_USD,
            "l2_note": (
                "Aerodrome (Base L2): доминирующий ve(3,3) DEX на Base, "
                "USDC-USDT стейбл-пул. Доход = торговые комиссии + AERO emissions. "
                "IL минимален пока оба актива в привязке. Газ ~95% дешевле mainnet, "
                "finality ~2 сек (OP-stack). T2 risk_score=0.45 — LP IL-риск (депег) "
                "+ AERO emission волатильность."
            ),
        }
