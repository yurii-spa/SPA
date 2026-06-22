"""
Adapter: Pendle PT (Principal Token) — Engine B, read-only.

Pendle PT — «безопасная» нога Pendle: покупается с дисконтом к par,
возвращает 1:1 к underlying на дату экспирации. Фиксирует APY на срок.

LLM_FORBIDDEN: этот модуль не вызывает и не использует LLM.
Запрещено: подписывать, отправлять транзакции, писать state-файлы.
sign() / send() / write() → NotImplementedError (явный барьер).

Источники данных (production):
  - Pendle Finance API v2 (публичный)
  - DeFiLlama yields API (cross-check)
Сейчас: структурированные mock-данные с правильным форматом.

Домен: read-only (spa_core/adapters/ — Engine A).
       Engine B adapters/ — этот файл.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CACHE_PATH = _PROJECT_ROOT / "data" / "adapters" / "pendle_pt_state.json"

# Максимальный возраст кэша до повторного запроса (секунды)
_CACHE_MAX_AGE_SEC = 4 * 3600  # 4 часа


class PendlePTAdapter:
    """
    Read-only adapter для Pendle Principal Token (Engine B).

    Поддерживаемые рынки:
      - PT-sUSDe-MAR2025: Pendle PT sUSDe (Ethena staked USDe)
      - PT-USDe-SEP2025:  Pendle PT USDe

    Типичный APY: ~8–12% фиксированный yield-to-maturity.
    TVL требование: ≥$100M (RiskPolicy-HY).
    Аудиты: ≥2 (RiskPolicy-HY).

    LLM_FORBIDDEN: никаких AI вызовов.
    READ-ONLY: sign(), send(), write() → NotImplementedError.
    """

    SUPPORTED_MARKETS: Dict[str, Dict] = {
        "PT-sUSDe-MAR2025": {
            "description": "Pendle PT sUSDe (Ethena staked USDe) — March 2025",
            "underlying": "sUSDe",
            "chain": "ethereum",
            "min_tvl_usd": 100_000_000,
            "defillama_project": "pendle",
        },
        "PT-USDe-SEP2025": {
            "description": "Pendle PT USDe (Ethena USDe) — September 2025",
            "underlying": "USDe",
            "chain": "ethereum",
            "min_tvl_usd": 100_000_000,
            "defillama_project": "pendle",
        },
    }

    def __init__(self, market_id: str = "PT-sUSDe-MAR2025") -> None:
        """
        Args:
            market_id: Идентификатор рынка из SUPPORTED_MARKETS.

        Raises:
            ValueError: если market_id не поддерживается.
        """
        if market_id not in self.SUPPORTED_MARKETS:
            raise ValueError(
                f"Unsupported market: {market_id!r}. "
                f"Supported: {list(self.SUPPORTED_MARKETS)}"
            )
        self.market_id = market_id
        self.market_info = self.SUPPORTED_MARKETS[market_id]

    # ------------------------------------------------------------------
    # Public read-only interface
    # ------------------------------------------------------------------

    def read_state(self) -> Dict:
        """
        Читает текущее состояние PT позиции (read-only).

        Не подписывает, не отправляет, не пишет state-файлы.
        Использует кэш (data/adapters/pendle_pt_state.json) если свежий,
        иначе возвращает структурированные mock-данные.

        Returns:
            dict: {
                yield_apy: float,           # Фиксированный APY (0–50%)
                price: float,               # Цена PT (дисконт к par, 0.5–1.0)
                term_to_maturity_days: int, # Дней до экспирации
                tvl_usd: float,             # TVL в USD
                depeg_pct: float,           # Депег underlying (0–1)
                funding_rate: float,        # Аннуализированный funding rate
                liquidity_usd: float,       # Глубина рынка (USD)
                audit_count: int,           # Количество аудитов
                validated: bool,            # Прошёл внутреннюю валидацию
                adapter: str,               # Имя адаптера
                market_id: str,             # ID рынка
                read_at: str,               # ISO 8601 UTC timestamp
                data_source: str,           # "mock" / "cache" / "pendle_api+defillama"
            }
        """
        # LLM_FORBIDDEN
        # READ-ONLY — запрещено вызывать self.sign(), self.send(), self.write()
        raw = self._fetch_from_cache_or_mock()
        validated = self._validate(raw)

        return {
            **raw,
            "validated": validated,
            "adapter": "PendlePTAdapter",
            "market_id": self.market_id,
            "read_at": datetime.now(tz=timezone.utc).isoformat(),
            # data_source уже в raw ("mock" или "cache")
        }

    # ------------------------------------------------------------------
    # Internal helpers (read-only)
    # ------------------------------------------------------------------

    def _fetch_from_cache_or_mock(self) -> Dict:
        """
        Читает из кэша если свежий (< 4ч), иначе возвращает mock-данные.

        В production здесь будет запрос к Pendle API + DeFiLlama cross-check.
        """
        if _CACHE_PATH.exists():
            try:
                cached = json.loads(_CACHE_PATH.read_text())
                # Проверяем свежесть
                fetched_at = cached.get("fetched_at", "")
                if fetched_at:
                    fetched_dt = datetime.fromisoformat(fetched_at.rstrip("Z"))
                    age_sec = (
                        datetime.utcnow() - fetched_dt
                    ).total_seconds()
                    if age_sec < _CACHE_MAX_AGE_SEC:
                        cached["data_source"] = "cache"
                        return cached
            except Exception:
                pass  # Повреждённый кэш → используем mock

        return self._mock_state()

    def _mock_state(self) -> Dict:
        """
        Структурированные mock-данные с корректным форматом.
        Используются до интеграции production API.
        Значения соответствуют реалистичным рыночным условиям 2026-06.
        """
        return {
            "market_id": self.market_id,
            "underlying": self.market_info["underlying"],
            "yield_apy": 0.115,           # ~11.5% фиксированный PT yield
            "price": 0.9680,              # PT торгуется с дисконтом к par
            "term_to_maturity_days": 90,  # 90 дней до экспирации
            "tvl_usd": 850_000_000.0,     # $850M TVL (выше RiskPolicy $100M)
            "depeg_pct": 0.0015,          # 0.15% депег sUSDe/USDe
            "funding_rate": 0.085,        # 8.5% аннуализированный фандинг
            "liquidity_usd": 5_000_000.0, # $5M глубина рынка
            "audit_count": 3,             # 3 аудита (выше min 2)
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "staleness_ok": True,
            "data_source": "mock",        # → "pendle_api+defillama" в production
        }

    def _validate(self, state: Dict) -> bool:
        """
        DataTrust валидация: диапазоны, разумность значений.

        Проверяет только структурную корректность данных,
        не бизнес-логику (это делает RiskPolicy-HY).
        """
        # yield_apy в разумных пределах 0–50%
        if not (0.0 <= state.get("yield_apy", -1) <= 0.50):
            return False

        # Цена PT в диапазоне 0.5–1.01 (дисконтированный PT)
        if not (0.50 <= state.get("price", -1) <= 1.01):
            return False

        # TVL > 0
        if state.get("tvl_usd", 0) <= 0:
            return False

        # Депег в разумных пределах (0–50%)
        if state.get("depeg_pct", 1.0) > 0.50:
            return False

        # Funding rate разумный (-100% … +200%)
        fr = state.get("funding_rate", None)
        if fr is not None and not (-1.0 <= fr <= 2.0):
            return False

        return True

    # ------------------------------------------------------------------
    # Запрещённые методы — явный барьер
    # Определены чтобы вызвать информативную ошибку вместо AttributeError
    # ------------------------------------------------------------------

    def sign(self, *args, **kwargs):
        """READ-ONLY adapter. sign() is FORBIDDEN."""
        raise NotImplementedError(
            "PendlePTAdapter is READ-ONLY. "
            "sign() is FORBIDDEN. Use execution domain for signing."
        )

    def send(self, *args, **kwargs):
        """READ-ONLY adapter. send() is FORBIDDEN."""
        raise NotImplementedError(
            "PendlePTAdapter is READ-ONLY. "
            "send() is FORBIDDEN. Use execution domain for on-chain sends."
        )

    def write(self, *args, **kwargs):
        """READ-ONLY adapter. write() is FORBIDDEN."""
        raise NotImplementedError(
            "PendlePTAdapter is READ-ONLY. "
            "write() is FORBIDDEN. State writes belong to execution domain."
        )
