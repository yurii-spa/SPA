"""
Adapter: Uniswap V3 LP — read-only.
Engine C (LP/Liquidity/RS-004).

LLM_FORBIDDEN: этот модуль не вызывает и не использует LLM.
Запрещено: sign(), send(), write() — все три метода явно поднимают
NotImplementedError (барьер неслучайного вызова).

Источники данных (production):
  - Uniswap V3 Subgraph (The Graph)
  - DeFiLlama yields API (cross-check TVL/APY)
Сейчас: структурно корректные mock-данные с правильным форматом.

Домен: read-only (Engine C adapters/, отдельно от spa_core/adapters/).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ADAPTERS_CACHE_DIR = _PROJECT_ROOT / "data" / "adapters"


class UniswapV3LPAdapter:
    """
    Read-only adapter для Uniswap V3 CLMM LP positions.

    Поддерживаемые пулы:
      USDC_USDT_001       — USDC/USDT 0.01% Ethereum (стейбл/стейбл, минимальный IL)
      USDC_USDT_BASE_001  — USDC/USDT 0.01% Base chain

    Гарантии:
      - read_state() никогда не пишет ни в какой файл.
      - sign() / send() / write() → NotImplementedError без исключений.
      - Если кэш отсутствует или повреждён — возвращает структурированный mock.
      - validated=True только если данные прошли DataTrust проверку.

    LLM_FORBIDDEN.
    """

    SUPPORTED_POOLS: Dict[str, Dict] = {
        "USDC_USDT_001": {
            "description": "USDC/USDT 0.01% fee tier (Ethereum)",
            "chain": "ethereum",
            "fee_tier": 100,           # basis points
            "min_tvl_usd": 50_000_000,
            "il_risk": "minimal",      # стейбл/стейбл
            "audit_count": 4,          # Uniswap: Trail of Bits, ABDK, Peckshield, Certik
        },
        "USDC_USDT_BASE_001": {
            "description": "USDC/USDT 0.01% fee tier (Base)",
            "chain": "base",
            "fee_tier": 100,
            "min_tvl_usd": 50_000_000,
            "il_risk": "minimal",
            "audit_count": 3,
        },
    }

    def __init__(self, pool_id: str = "USDC_USDT_001") -> None:
        if pool_id not in self.SUPPORTED_POOLS:
            raise ValueError(
                f"Unsupported pool: {pool_id!r}."
                f" Supported: {list(self.SUPPORTED_POOLS)}"
            )
        self.pool_id = pool_id
        self.pool_info = self.SUPPORTED_POOLS[pool_id]

    # ─── Public API ──────────────────────────────────────────────────────────

    def read_state(self) -> Dict:
        """
        Читает текущее состояние LP пула (read-only).

        Returns dict с полями:
          fee_apy_24h          — APY от trading fees (24h EMA)
          fee_apy_7d           — APY от trading fees (7d EMA)
          pool_tvl_usd         — TVL пула в USD
          il_current_pct       — текущий IL как доля (0..1)
          range_lower          — нижняя граница диапазона CLMM
          range_upper          — верхняя граница диапазона CLMM
          range_width_pct      — ширина диапазона (upper-lower)/current_price
          fee_volatility_7d    — коэффициент вариации fees за 7д
          liquidity_depth_usd  — глубина ликвидности в диапазоне (USD)
          is_delta_neutral     — True если диапазон симметричный
          audit_count          — кол-во независимых аудитов протокола
          current_price        — текущая цена пары
          entry_price          — цена на момент открытия позиции
          validated            — прошли ли данные DataTrust-проверку
          adapter              — "UniswapV3LPAdapter"
          pool_id              — идентификатор пула
          pool_info            — мета-информация пула
          read_at              — UTC timestamp чтения
          data_source          — "cache" | "mock" | "live"

        LLM_FORBIDDEN. Запрещено: sign(), send(), write().
        """
        # LLM_FORBIDDEN
        state = self._fetch_from_cache_or_mock()
        validated = self._validate(state)

        return {
            **state,
            "validated": validated,
            "adapter": "UniswapV3LPAdapter",
            "pool_id": self.pool_id,
            "pool_info": self.pool_info,
            "read_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── Internal ────────────────────────────────────────────────────────────

    def _fetch_from_cache_or_mock(self) -> Dict:
        """
        Читает из кэша data/adapters/<pool_id>_state.json.
        При отсутствии/ошибке — структурированный mock.
        Файл никогда не записывается этим методом.
        """
        cache_path = _ADAPTERS_CACHE_DIR / f"{self.pool_id.lower()}_state.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                cached["data_source"] = "cache"
                return cached
            except Exception:
                pass  # повреждённый кэш → fallback на mock

        return self._mock_state()

    def _mock_state(self) -> Dict:
        """
        Структурно корректные mock-данные для USDC/USDT пула.
        Заменяется реальным Subgraph-фидом в production.
        """
        # USDC/USDT ~$1 пара — стейбл-пул с tight диапазоном
        return {
            "pool_id": self.pool_id,
            "fee_apy_24h": 0.062,            # ~6.2% APY от fees (24h EMA)
            "fee_apy_7d": 0.058,             # ~5.8% APY от fees (7d EMA)
            "pool_tvl_usd": 180_000_000.0,   # $180M TVL
            "il_current_pct": 0.0002,        # 0.02% IL (стейбл/стейбл)
            "range_lower": 0.9990,
            "range_upper": 1.0010,
            "range_width_pct": 0.001,        # 0.1% диапазон (tight для стейблов)
            "fee_volatility_7d": 0.12,       # 12% CV fees
            "liquidity_depth_usd": 8_000_000.0,  # $8M depth
            "is_delta_neutral": True,        # симметричный диапазон
            "audit_count": self.pool_info["audit_count"],
            "current_price": 1.0001,
            "entry_price": 1.0000,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "staleness_ok": True,
            "data_source": "mock",
        }

    def _validate(self, state: Dict) -> bool:
        """
        DataTrust-валидация структуры и диапазонов.
        True только если все ключевые поля в разумных пределах.
        """
        # fee_apy в разумных пределах [0, 100%]
        if not (0.0 <= state.get("fee_apy_24h", -1.0) <= 1.0):
            return False
        # TVL > 0
        if state.get("pool_tvl_usd", 0.0) <= 0.0:
            return False
        # IL в разумных пределах [0, 50%]
        if state.get("il_current_pct", 1.0) > 0.50:
            return False
        # range_lower < range_upper
        if state.get("range_lower", 0.0) >= state.get("range_upper", 0.0):
            return False
        return True

    # ─── Explicit read-only barriers ─────────────────────────────────────────

    def sign(self, *args, **kwargs):
        """READ-ONLY adapter. sign() is FORBIDDEN."""
        raise NotImplementedError(
            "UniswapV3LPAdapter is READ-ONLY. sign() is FORBIDDEN. "
            "Use execution domain for signing."
        )

    def send(self, *args, **kwargs):
        """READ-ONLY adapter. send() is FORBIDDEN."""
        raise NotImplementedError(
            "UniswapV3LPAdapter is READ-ONLY. send() is FORBIDDEN. "
            "Use execution domain for broadcasting."
        )

    def write(self, *args, **kwargs):
        """READ-ONLY adapter. write() is FORBIDDEN."""
        raise NotImplementedError(
            "UniswapV3LPAdapter is READ-ONLY. write() is FORBIDDEN. "
            "State files belong to the execution domain."
        )
