"""Ethena Staked USDe (sUSDe) ERC-4626 staking vault adapter (T3) — MP-460.

Конкретный адаптер для Ethena sUSDe staking vault на Ethereum mainnet.
Vault address: 0x9D39A5DE30e57443BfF2A8307A4256c8797A3497

Ключевые характеристики:
- Tier T3 (TVL ~$2.5B, Risk Score 0.62) — лимит 10% портфеля (T3_CAP).
  Доход формируется из funding-rate перпетуалов (delta-neutral позиция) +
  staking rewards; исторически 8–25% APY, высокая волатильность доходности.
- APY читается из data/adapter_status.json (поле susde.apy), fallback =
  12.0% при отсутствии / ошибке чтения.
- RISK_SCORE = 0.62 — выше FRAX (0.40): synthetic dollar (USDe) +
  funding-rate риск (доход может уйти в отрицательную зону при инверсии
  funding), плюс зависимость от CeFi-кастодиев для хеджа.
- EXIT_LATENCY_HOURS = 168.0 — это КЛЮЧЕВОЕ отличие от sFRAX. Анстейкинг
  sUSDe требует 7-дневного cooldown (168 часов): пользователь инициирует
  unstake, ждёт окно cooldown, и только затем забирает USDe. Выход НЕ
  атомарен и НЕ мгновенен (в отличие от ERC-4626 redeem у sFRAX). Это
  жёсткое ограничение ликвидности учитывается оркестратором при
  планировании выхода из позиции.
- Peg-gate: is_peg_healthy() True пока |usde_price - 1.0| <= PEG_TOLERANCE
  (1% — допуск шире чем у FRAX, т.к. USDe synthetic dollar с более широким
  торговым коридором).
- Модуль строго read-only / advisory: никогда не трогает живой капитал.

Правила:
- Только stdlib Python (без внешних зависимостей)
- Не импортировать из execution / feed_health / risk / monitoring
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


class SusdeAdapter(BaseAdapter):
    """Read-only advisory адаптер для Ethena sUSDe ERC-4626 staking vault (T3).

    APY берётся из ``data/adapter_status.json`` → ``susde.apy`` (значение в
    процентах, например 12.0). При отсутствии поля или ошибке чтения
    используется ``DEFAULT_APY_PCT = 12.0``.

    Peg-gate: ``is_peg_healthy()`` возвращает True пока цена USDe держит
    привязку — отклонение ``|usde_price - 1.0|`` не превышает
    ``PEG_TOLERANCE`` (1%). Логика default-safe в сторону healthy:
    отсутствие поля ``usde_price`` трактуется как 1.0 (нет данных о депеге !=
    депег), значит healthy=True. Но если поле присутствует и отклонение
    превышает допуск — gate закрывается (False).

    Ликвидность: выход из позиции НЕ атомарен — анстейкинг требует
    7-дневного cooldown (``EXIT_LATENCY_HOURS = 168.0``, см. ``cooldown_hours()``).
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "susde"
    PROTOCOL_NAME = "Ethena Staked USDe (sUSDe)"
    VAULT_ADDRESS = "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T3"
    # Read-only advisory (per this adapter's own docstring): Ethena sUSDe carries
    # funding/depeg tail-risk and is NOT a live-allocatable holding. IS_ADVISORY makes the
    # allocator exclude it from the money path (it had been leaking into the live book).
    IS_ADVISORY = True
    T3_CAP: float = 0.10          # макс 10% портфеля в этом протоколе (T3 лимит)
    CHAIN = "ethereum"
    CHAIN_ID: int = 1
    RISK_SCORE: float = 0.62      # выше FRAX (0.40): synthetic dollar + funding-rate риск

    # 7-дневный unstake cooldown — выход НЕ атомарен (ключевое отличие от sFRAX)
    EXIT_LATENCY_HOURS: float = 168.0

    # ── APY параметры ────────────────────────────────────────────────────
    MIN_APY_PCT: float = 4.0
    MAX_APY_PCT: float = 30.0
    DEFAULT_APY_PCT: float = 12.0  # fallback (funding + staking rewards)

    TVL_USD: float = 2_500_000_000

    # ── peg compliance ───────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.01    # 1% — макс отклонение usde_price от 1.0 (synthetic, шире чем FRAX)

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

    def _read_status(self) -> dict:
        """Читает susde-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get("susde", {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("susde: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из susde.apy. Возвращает float или None."""
        apy = self._read_status().get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return None

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (12.0, не 0.12).

        Источник: data/adapter_status.json → susde.apy.
        Fallback: DEFAULT_APY_PCT (12.0%).
        """
        apy = self._read_apy_from_status()
        return apy if apy is not None else self.DEFAULT_APY_PCT

    def get_apy_pct(self) -> float:
        """Возвращает APY в процентах — то же что get_apy() (совместимость с BaseAdapter)."""
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора."""
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.get_apy() / 100.0,   # YieldInfo ожидает десятичную дробь
            tvl_usd=self.TVL_USD,
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ── peg compliance ───────────────────────────────────────────────────

    def is_peg_healthy(self) -> bool:
        """True если USDe держит привязку к $1.0 в пределах PEG_TOLERANCE.

        Читает ``usde_price`` из status. Логика default-safe в сторону healthy:
          - поле отсутствует           → usde_price = 1.0 → healthy=True
            (отсутствие данных != депег; не блокируем по неполноте данных)
          - поле нечисловое/bool       → usde_price = 1.0 → healthy=True (safe)
          - |usde_price - 1.0| <= 0.01 → healthy=True  (привязка в норме)
          - |usde_price - 1.0| >  0.01 → healthy=False (депег обнаружен)
        """
        price = self._read_status().get("usde_price", 1.0)
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            # Нечисловое значение — считаем привязку здоровой (нет валидных данных о депеге)
            return True
        # round до 10 знаков снимает float-артефакты на самой границе допуска
        # (напр. abs(0.99 - 1.0) = 0.01000000...88), чтобы граница вела себя
        # предсказуемо: ровно PEG_TOLERANCE считается здоровой (<=).
        deviation = round(abs(float(price) - 1.0), 10)
        return deviation <= self.PEG_TOLERANCE

    # ── eligibility ──────────────────────────────────────────────────────

    def is_eligible(self) -> bool:
        """True если peg здоров И APY в допустимом диапазоне [MIN, MAX]."""
        if not self.is_peg_healthy():
            return False
        apy = self.get_apy()
        return self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT

    # ── vs Morpho gap ─────────────────────────────────────────────────────

    def vs_morpho_gap(self, morpho_apy: float = 6.5) -> float:
        """Возвращает morpho_apy - susde_apy (отрицательный = sUSDe лучше).

        Args:
            morpho_apy: Morpho APY в процентах. По умолчанию 6.5%.
        """
        return round(morpho_apy - self.get_apy(), 10)

    # ── виртуальный paper trading API ────────────────────────────────────

    def allocate(self, capital_usd: float) -> dict:
        """Виртуальная аллокация капитала (только для paper trading).

        Args:
            capital_usd: Сумма в USD для аллокации. Должна быть > 0.

        Raises:
            ValueError: если capital_usd <= 0.

        Returns:
            dict со статусом операции.
        """
        if capital_usd <= 0:
            raise ValueError(
                f"capital_usd must be positive, got {capital_usd}"
            )
        self._allocated += capital_usd
        return {
            "status": "ok",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "amount": capital_usd,
            "allocated_total": self._allocated,
            "apy_pct": self.get_apy_pct(),
            "ts": time.time(),
        }

    def withdraw(self, amount_usd: float) -> dict:
        """Виртуальный вывод средств из vault (только для paper trading).

        Внимание: вывод НЕ атомарен — реальный анстейкинг sUSDe требует
        7-дневного cooldown (см. ``cooldown_hours()``). Здесь учитывается
        только paper-баланс; латентность выхода декларируется отдельно.

        Args:
            amount_usd: Сумма в USD для вывода. Должна быть > 0.

        Raises:
            ValueError: если amount_usd <= 0.

        Returns:
            dict со статусом операции.
        """
        if amount_usd <= 0:
            raise ValueError(
                f"amount_usd must be positive, got {amount_usd}"
            )
        if amount_usd > self._allocated:
            return {
                "status": "error",
                "reason": "insufficient_balance",
                "requested": amount_usd,
                "available": self._allocated,
                "protocol": self.PROTOCOL,
            }
        self._allocated -= amount_usd
        return {
            "status": "ok",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "amount": amount_usd,
            "allocated_remaining": self._allocated,
            "ts": time.time(),
        }

    # ── cooldown (специфичный для sUSDe) ─────────────────────────────────

    def cooldown_hours(self) -> float:
        """Возвращает длительность unstake cooldown в часах (EXIT_LATENCY_HOURS).

        Специфичный для этого адаптера метод. Анстейкинг sUSDe не атомарен:
        требуется 7-дневное (168h) окно cooldown между инициацией unstake и
        фактическим получением USDe. Это значение используется оркестратором
        для планирования выхода из позиции — нельзя считать выход мгновенным.

        Returns:
            float: 168.0 (7 дней в часах).
        """
        return self.EXIT_LATENCY_HOURS

    # ── health check ─────────────────────────────────────────────────────

    def health_check(self) -> str:
        """Проверяет работоспособность адаптера.

        Returns:
            "ok" если APY в диапазоне [MIN_APY_PCT, MAX_APY_PCT], "degraded" иначе.
        """
        apy = self.get_apy()
        if self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT:
            return "ok"
        return "degraded"

    # ── сериализация ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Полное представление адаптера (для дашборда / логов / тестов).

        Returns:
            dict с ключами: protocol, protocol_name, vault_address, tier, t3_cap,
            chain, chain_id, asset, apy_pct, risk_score, exit_latency_hours,
            tvl_usd, min_apy_pct, max_apy_pct, peg_healthy, cooldown_hours,
            eligible, allocated.
        """
        return {
            "protocol": self.PROTOCOL,
            "protocol_name": self.PROTOCOL_NAME,
            "vault_address": self.VAULT_ADDRESS,
            "tier": self.tier,
            "t3_cap": self.T3_CAP,
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "asset": self.asset,
            "apy_pct": self.get_apy_pct(),
            "risk_score": self.RISK_SCORE,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "tvl_usd": self.TVL_USD,
            "min_apy_pct": self.MIN_APY_PCT,
            "max_apy_pct": self.MAX_APY_PCT,
            "peg_healthy": self.is_peg_healthy(),
            "cooldown_hours": self.cooldown_hours(),
            "eligible": self.is_eligible(),
            "allocated": self._allocated,
        }

    # end of class
