"""Frax Finance FraxLend USDC savings adapter (T2) — MP-563.

Конкретный адаптер для Frax Finance FraxLend USDC lending market на Ethereum mainnet.
Охватывает экосистему Frax Finance: FraxLend USDC-пары + FRAX savings layer
(sfrxETH-коллатерал, FRAX PSM hard-peg).

Pair address (FraxLend v2 USDC/FRAX): 0x3835a58CA93Cdb5f912519ad366826aC9a752510

Ключевые характеристики:
- Tier T2 (TVL ~$800M, Risk Score 0.45) — лимит 20% портфеля.
  Выше sDAI/sFRAX по риску: FraxLend — isolated lending market (no shared liquidity),
  ставка переменная (utilisation-based), исторический depeg-риск FRAX (2022),
  smart-contract риск многоуровневой архитектуры (FraxLend + AMO + PSM).
- APY читается из data/adapter_status.json (поле frax.apy),
  fallback = 7.5% при отсутствии / ошибке чтения. FraxLend USDC APY исторически
  7–12% в зависимости от utilisation rate рынка FRAX/USDC.
- RISK_SCORE = 0.45 — умеренный среди T2: выше sDAI (0.38) и sFRAX (0.40).
  Факторы риска: isolated market mechanics, utilisation-rate volatility,
  FRAX multi-collateral complexity, partial depeg history (2022 UST contagion).
- PEG_TOLERANCE = 0.005 (0.5%, FRAX PSM hard-peg): FRAX удерживается через
  PSM (Peg Stability Module), позволяющий swap USDC↔FRAX 1:1 с fee ≤0.1%.
  Исторически FRAX дольше держался деколляции в стрессовых условиях (2022),
  поэтому tolerance как у sFRAX (0.5%), не мягче.
  Логика default-safe: отсутствие frax_price = нет данных о депеге = healthy.
- EXIT_LATENCY_HOURS = 0.0: withdrawal из FraxLend мгновенный при достаточной
  ликвидности (utilisation < 95%). При high-utilisation может быть задержка;
  здесь декларируем только номинальную латентность в нормальных условиях.
  Swap-friction FRAX↔USDC учитывается отдельно оркестратором.
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


class FraxAdapter(BaseAdapter):
    """Read-only advisory адаптер для Frax Finance FraxLend USDC (T2).

    APY берётся из ``data/adapter_status.json`` → ``frax.apy``
    (значение в процентах, например 7.5). При отсутствии поля или ошибке
    чтения используется ``DEFAULT_APY_PCT = 7.5`` (типичный FraxLend USDC rate).

    Peg-gate: ``is_peg_healthy()`` возвращает True пока FRAX держит привязку к $1.0 —
    отклонение ``|frax_price - 1.0|`` не превышает ``PEG_TOLERANCE`` (0.5%).
    Логика default-safe в сторону healthy: отсутствие поля ``frax_price``
    трактуется как 1.0 (нет данных о депеге != депег), значит healthy=True.
    Но если поле присутствует и отклонение превышает допуск — gate закрывается (False).
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "frax"
    PROTOCOL_NAME = "Frax Finance FraxLend USDC"
    VAULT_ADDRESS = "0x3835a58CA93Cdb5f912519ad366826aC9a752510"

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T2"
    T2_CAP: float = 0.20          # макс 20% портфеля в этом протоколе (T2 лимит)
    CHAIN = "ethereum"
    CHAIN_ID: int = 1
    # RISK_SCORE выше sFRAX (0.40): isolated market mechanics + utilisation volatility
    # + partial depeg history (2022 UST contagion). Ниже sUSDe (0.62).
    RISK_SCORE: float = 0.45

    # FraxLend withdrawal мгновенный при < 95% utilisation; swap-friction учитывается оркестратором
    EXIT_LATENCY_HOURS: float = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    MIN_APY_PCT: float = 3.0
    MAX_APY_PCT: float = 15.0
    DEFAULT_APY_PCT: float = 7.5   # fallback (FraxLend USDC utilisation-based rate)

    TVL_USD: float = 800_000_000   # ~$800M общий TVL экосистемы Frax Finance

    # ── peg compliance ───────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.005   # 0.5% — жёсткий peg через PSM (как sFRAX/sDAI/stUSD)

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
        """Читает frax-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get("frax", {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("frax: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из frax.apy. Возвращает float или None."""
        apy = self._read_status().get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return None

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (7.5, не 0.075).

        Источник: data/adapter_status.json → frax.apy.
        Fallback: DEFAULT_APY_PCT (7.5%).
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
        """True если FRAX держит привязку к $1.0 в пределах PEG_TOLERANCE.

        Читает ``frax_price`` из status. Логика default-safe в сторону healthy:
          - поле отсутствует            → frax_price = 1.0 → healthy=True
            (отсутствие данных != депег; не блокируем по неполноте данных)
          - поле нечисловое/bool        → frax_price = 1.0 → healthy=True (safe)
          - |frax_price - 1.0| <= 0.005 → healthy=True  (привязка в норме)
          - |frax_price - 1.0| >  0.005 → healthy=False (депег обнаружен)
        """
        price = self._read_status().get("frax_price", 1.0)
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            # Нечисловое значение — считаем привязку здоровой (нет валидных данных о депеге)
            return True
        # round до 10 знаков снимает float-артефакты на самой границе допуска
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
        """Возвращает morpho_apy - frax_apy (отрицательный = Frax лучше).

        Args:
            morpho_apy: Morpho APY в процентах. По умолчанию 6.5%.
        """
        return round(morpho_apy - self.get_apy(), 10)

    # ── simulate deposit/withdraw (paper trading) ─────────────────────────

    def simulate_deposit(self, capital_usd: float) -> dict:
        """Виртуальный депозит в FraxLend USDC (только для paper trading).

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

    def simulate_withdraw(self, amount_usd: float) -> dict:
        """Виртуальный вывод средств из FraxLend USDC (только для paper trading).

        Args:
            amount_usd: Сумма в USD для вывода. Должна быть > 0.

        Raises:
            ValueError: если amount_usd <= 0.

        Returns:
            dict со статусом операции (status="ok" или status="error").
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

    # ── aliases для совместимости с SdaiAdapter / SfraxAdapter паттерном ──

    def allocate(self, capital_usd: float) -> dict:
        """Алиас simulate_deposit для совместимости с оркестратором."""
        return self.simulate_deposit(capital_usd)

    def withdraw(self, amount_usd: float) -> dict:
        """Алиас simulate_withdraw для совместимости с оркестратором."""
        return self.simulate_withdraw(amount_usd)

    # ── health check ─────────────────────────────────────────────────────

    def get_health(self) -> str:
        """Проверяет работоспособность адаптера.

        Returns:
            "ok" если APY в диапазоне [MIN_APY_PCT, MAX_APY_PCT], "degraded" иначе.
        """
        apy = self.get_apy()
        if self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT:
            return "ok"
        return "degraded"

    def health_check(self) -> str:
        """Алиас get_health() для совместимости с SdaiAdapter / SfraxAdapter паттерном."""
        return self.get_health()

    # ── сериализация ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Полное представление адаптера (для дашборда / логов / тестов).

        Returns:
            dict с ключами: protocol, protocol_name, vault_address, tier, t2_cap,
            chain, chain_id, asset, apy_pct, risk_score, exit_latency_hours,
            tvl_usd, min_apy_pct, max_apy_pct, peg_healthy, eligible, allocated,
            health.
        """
        return {
            "protocol": self.PROTOCOL,
            "protocol_name": self.PROTOCOL_NAME,
            "vault_address": self.VAULT_ADDRESS,
            "tier": self.tier,
            "t2_cap": self.T2_CAP,
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
            "eligible": self.is_eligible(),
            "allocated": self._allocated,
            "health": self.get_health(),
        }

    # end of class
