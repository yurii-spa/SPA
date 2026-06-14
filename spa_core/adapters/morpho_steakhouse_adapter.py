"""Morpho Blue Steakhouse USDC vault adapter (T1) — MP-355.

Конкретный адаптер для хранилища Steakhouse USDC на Morpho Blue Mainnet.
Vault address: 0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB.

Ключевые характеристики:
- Tier T1 (TVL > $500M) — лимит 40% портфеля
- APY читается из data/adapter_status.json (поле morpho_steakhouse.apy),
  fallback = 6.5% при отсутствии / ошибке чтения
- Quick Win #1: +200 bps vs Aave mainnet (3.2%) → рекомендует switch при
  превышении порога 50 bps над Aave
- Модуль строго read-only / advisory: никогда не трогает живой капитал

Правила:
- Только stdlib Python (без внешних зависимостей)
- Атомарные записи не нужны: адаптер не пишет state-файлы
- Не импортировать из execution / feed_health / risk
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo

logger = logging.getLogger(__name__)

# Корень репо — два уровня выше пакета adapters
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class MorphoSteakhouseAdapter(BaseAdapter):
    """Read-only advisory адаптер для Morpho Blue Steakhouse USDC vault (T1).

    APY берётся из ``data/adapter_status.json`` → ``morpho_steakhouse.apy``
    (значение в процентах, например 6.5). При отсутствии поля или ошибке
    чтения используется ``FALLBACK_APY_PCT = 6.5``.

    Метод ``switch_recommended()`` возвращает True, если
    ``morpho_apy_pct > aave_apy_pct + SWITCH_THRESHOLD_BPS / 100``.
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "morpho_steakhouse"
    VAULT_ADDRESS = "0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB"
    VAULT_NAME = "Steakhouse USDC"

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T1"
    T1_CAP = 0.40          # макс 40% портфеля в этом протоколе
    RISK_SCORE = 0.22      # чуть выше Aave T1 (0.20) — vault-слой добавляет
                           # незначительный смарт-контрактный риск

    # SPA-V412: instant exit — позиция ликвидна на уровне Morpho Blue lending
    EXIT_LATENCY_HOURS = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    FALLBACK_APY_PCT: float = 6.5        # % (используется при отсутствии данных в JSON)
    AAVE_MAINNET_APY_PCT: float = 3.2   # % (benchmark для switch-рекомендации)
    SWITCH_THRESHOLD_BPS: int = 50      # минимальный отрыв (bps) для рекомендации switch

    # ── quick win метаданные ─────────────────────────────────────────────
    QUICK_WIN: bool = True
    BPS_GAIN: int = 200    # vs Aave mainnet 3.2%

    STRATEGY_NOTE: str = (
        "Quick Win #1: switch $50K from Aave mainnet (3.2%) to Morpho Steakhouse (6.5%)"
        " = +$1,650/yr on $50K"
    )

    # ── DeFiLlama пул (для будущей live интеграции) ──────────────────────
    DEFILLAMA_PROJECT = "morpho-blue"
    DEFILLAMA_POOL_ID = "BEEF01735c132Ada46AA9aA4c54623cAA92A64CB"

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[Path | str] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER
        self._data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        # Виртуальная аллокация (только для paper trading учёта)
        self._allocated: float = 0.0

    # ── внутреннее чтение JSON ───────────────────────────────────────────

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из data/adapter_status.json → morpho_steakhouse.apy.

        Возвращает float в процентах (например 6.5) или None при любой ошибке
        / отсутствии поля. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            ms = data.get("morpho_steakhouse", {})
            apy = ms.get("apy")
            if isinstance(apy, (int, float)) and not isinstance(apy, bool):
                return float(apy)
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("morpho_steakhouse: не удалось прочитать APY из JSON: %s", exc)
        return None

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy_pct(self) -> float:
        """Возвращает APY в процентах (6.5, а не 0.065).

        Источник: data/adapter_status.json → morpho_steakhouse.apy.
        Fallback: FALLBACK_APY_PCT (6.5%).
        """
        apy = self._read_apy_from_status()
        return apy if apy is not None else self.FALLBACK_APY_PCT

    def get_apy(self) -> float:
        """Возвращает APY как десятичную дробь (0.065 = 6.5%).

        Реализует контракт BaseAdapter.get_apy().
        """
        return self.get_apy_pct() / 100.0

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора."""
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.get_apy(),
            tvl_usd=None,      # TVL не читаем из статик-файла; None = «нет данных»
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ── switch-рекомендация ──────────────────────────────────────────────

    def switch_recommended(self, aave_apy_pct: Optional[float] = None) -> bool:
        """True если Morpho APY > Aave APY + SWITCH_THRESHOLD_BPS / 100.

        Args:
            aave_apy_pct: Текущий Aave APY в процентах. Если None — используется
                          AAVE_MAINNET_APY_PCT (3.2%).
        """
        aave = aave_apy_pct if aave_apy_pct is not None else self.AAVE_MAINNET_APY_PCT
        threshold = aave + self.SWITCH_THRESHOLD_BPS / 100.0
        return self.get_apy_pct() > threshold

    def switch_gain_pct(self, aave_apy_pct: Optional[float] = None) -> float:
        """Разница APY в процентах (Morpho - Aave).

        Args:
            aave_apy_pct: Текущий Aave APY в процентах. Если None — используется
                          AAVE_MAINNET_APY_PCT (3.2%).
        """
        aave = aave_apy_pct if aave_apy_pct is not None else self.AAVE_MAINNET_APY_PCT
        return round(self.get_apy_pct() - aave, 10)

    # ── виртуальный paper trading API ────────────────────────────────────

    def allocate(self, capital: float) -> dict:
        """Виртуальная аллокация капитала (только для paper trading).

        Returns:
            dict со статусом операции.
        """
        if capital <= 0:
            return {
                "status": "error",
                "reason": "capital must be positive",
                "requested": capital,
                "allocated": self._allocated,
                "protocol": self.PROTOCOL,
            }
        self._allocated += capital
        return {
            "status": "ok",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "amount": capital,
            "allocated_total": self._allocated,
            "apy_pct": self.get_apy_pct(),
            "ts": time.time(),
        }

    def withdraw(self, amount: float) -> dict:
        """Виртуальный вывод средств из vault (только для paper trading).

        Returns:
            dict со статусом операции.
        """
        if amount <= 0:
            return {
                "status": "error",
                "reason": "amount must be positive",
                "requested": amount,
                "allocated": self._allocated,
                "protocol": self.PROTOCOL,
            }
        if amount > self._allocated:
            return {
                "status": "error",
                "reason": "insufficient_balance",
                "requested": amount,
                "available": self._allocated,
                "protocol": self.PROTOCOL,
            }
        self._allocated -= amount
        return {
            "status": "ok",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "amount": amount,
            "allocated_remaining": self._allocated,
            "ts": time.time(),
        }

    # ── health check ─────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Проверяет работоспособность адаптера.

        Статус «ok» если APY — числовое значение в разумном диапазоне (0–50%).
        Статус «degraded» если APY за пределами диапазона или не числовое.

        Returns:
            dict с полями status, protocol, vault, tier, apy_pct и рекомендацией.
        """
        apy_pct = self.get_apy_pct()
        healthy = isinstance(apy_pct, float) and 0 < apy_pct < 50
        return {
            "status": "ok" if healthy else "degraded",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "tier": self.tier,
            "apy_pct": apy_pct,
            "fallback_used": self._read_apy_from_status() is None,
            "quick_win": self.QUICK_WIN,
            "switch_recommended": self.switch_recommended(),
            "ts": time.time(),
        }

    # ── сериализация ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Полное представление адаптера (для дашборда / логов / тестов).

        Returns:
            dict с ключами:
            protocol, vault_address, vault_name, tier, t1_cap, asset,
            apy_pct, apy_decimal, risk_score, exit_latency_hours,
            quick_win, bps_gain, switch_recommended, switch_gain_pct,
            aave_benchmark_apy_pct, strategy_note, allocated.
        """
        return {
            "protocol": self.PROTOCOL,
            "vault_address": self.VAULT_ADDRESS,
            "vault_name": self.VAULT_NAME,
            "tier": self.tier,
            "t1_cap": self.T1_CAP,
            "asset": self.asset,
            "apy_pct": self.get_apy_pct(),
            "apy_decimal": self.get_apy(),
            "risk_score": self.RISK_SCORE,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "quick_win": self.QUICK_WIN,
            "bps_gain": self.BPS_GAIN,
            "switch_recommended": self.switch_recommended(),
            "switch_gain_pct": self.switch_gain_pct(),
            "aave_benchmark_apy_pct": self.AAVE_MAINNET_APY_PCT,
            "strategy_note": self.STRATEGY_NOTE,
            "allocated": self._allocated,
        }

    # end of class
