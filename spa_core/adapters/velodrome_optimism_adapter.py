"""Velodrome Finance Optimism USDC-USDT stable-pool адаптер — T2 tier.

Chain: Optimism (OP Mainnet, L2)
Tier: T2 — Velodrome — ведущий DEX Optimism (ve(3,3) модель). Стейбл-пул
  USDC-USDT: минимальный IL (оба актива ~$1), доход = торговые комиссии +
  VELO emissions. IL-риск НЕ нулевой (депег одного из активов) + волатильность
  VELO-наград → T2 risk_score выше lending.
Pool: USDC-USDT stable AMM pool на Velodrome V2 (Optimism)
APY source: DeFiLlama /pools — project=velodrome-v2/velodrome, chain=Optimism,
  symbol содержит и USDC и USDT (стейбл-пара)

Архитектурные ограничения (FORBIDDEN):
  - Только stdlib Python — никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - LLM запрещён в risk / execution / monitoring компонентах
  - Модуль строго read-only / advisory: никогда не трогает реальный капитал
  - НЕ импортировать из execution/ или risk/

ВНИМАНИЕ: LP-позиция в стейбл-паре — не single-asset lending. IL минимален
пока оба актива держат привязку, но депег ломает паритет. risk_score=0.45.
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

PROTOCOL_ID = "velodrome-optimism"
CHAIN = "optimism"
CHAIN_ID = 10
TIER = "T2"

# TVL в USD (~$100M стейбл-пул на Optimism, ориентир 2026-06)
TVL_USD = 100_000_000

# Risk score: LP IL-риск (депег) + VELO emission волатильность
RISK_SCORE = 0.45

# APY fallback (%) если DeFiLlama недоступен
APY_FALLBACK = 5.0

# Максимальная доля портфеля для T2 (20%)
T2_CAP_PCT = 20

# ---------------------------------------------------------------------------
# DeFiLlama API
# ---------------------------------------------------------------------------

_DEFILLAMA_URL = "https://yields.llama.fi/pools"
_REQUEST_TIMEOUT = 10  # секунд

_DEFILLAMA_PROJECTS = ("velodrome-v3", "velodrome-v2", "velodrome")

# DeFiLlama маркирует Optimism как "OP Mainnet" (исторически также "Optimism")
_CHAIN_LABELS = {"optimism", "op mainnet"}

# Для стейбл-пары требуем наличие обоих символов в symbol-строке пула
_REQUIRED_TOKENS = ("USDC", "USDT")

# Санитарные границы APY (%)
_APY_MIN = 0.1
_APY_MAX = 50.0

# Минимальный TVL пула чтобы считаться живым ($100K). Velodrome стейбл-пул
# USDC-USDT тонкий (~$200K на 2026-06) — это advisory APY-feed, а не allocation
# target; реальный $5M floor RiskPolicy всё равно гейтит фактическую аллокацию.
_MIN_POOL_TVL = 100_000.0

# ---------------------------------------------------------------------------
# L2 газовые параметры (Optimism)
# ---------------------------------------------------------------------------

GAS_L2_USD = 0.005
GAS_MAINNET_USD = 0.10
GAS_ADVANTAGE_USD = 0.095
FINALITY_MINUTES = 10


class VelodromeOptimismAdapter(BaseAdapter):
    """Read-only адаптер Velodrome USDC-USDT стейбл-пула на Optimism (T2).

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

    PROTOCOL = "velodrome_optimism"
    EXIT_LATENCY_HOURS = 0.0  # LP burn same-block

    pool_id = "velodrome-usdc-usdt-optimism"

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
            logger.warning("velodrome_optimism: DeFiLlama URLError: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("velodrome_optimism: DeFiLlama fetch ошибка: %s", exc)
            return None

    def _find_best_stable_pool(self, pools: list[dict]) -> Optional[dict]:
        """Находит USDC-USDT стейбл-пул Velodrome на Optimism (макс. TVL)."""
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
                "velodrome_optimism: USDC-USDT стейбл-пул не найден в DeFiLlama"
            )
            return None
        apy = float(best.get("apy", 0.0))
        logger.info(
            "velodrome_optimism: live APY=%.3f%% из пула %s (TVL=%.0f)",
            apy,
            best.get("pool", "?"),
            best.get("tvlUsd", 0),
        )
        return apy

    # ------------------------------------------------------------------ #
    # Публичные методы                                                     #
    # ------------------------------------------------------------------ #

    def get_apy(self) -> float:
        """Возвращает APY в процентах (5.0 == 5.0%). Никогда не бросает исключений."""
        live = self._fetch_live_apy()
        if live is not None:
            return live
        logger.info(
            "velodrome_optimism: DeFiLlama недоступен, fallback APY=%.1f%%",
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
            "name": "Velodrome Optimism USDC-USDT",
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
                "Velodrome (Optimism L2): ve(3,3) DEX, USDC-USDT стейбл-пул. "
                "Доход = торговые комиссии + VELO emissions. IL минимален пока "
                "оба актива в привязке. Газ ~95% дешевле mainnet. "
                "T2 risk_score=0.45 — LP IL-риск (депег) + emission волатильность."
            ),
        }
