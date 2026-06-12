"""Spark Protocol sUSDS ERC-4626 vault adapter (T1) — MP-376.

Конкретный адаптер для Spark Protocol sUSDS Vault на Ethereum mainnet.
Vault address: 0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD

Ключевые характеристики:
- Tier T1 (TVL $3B+, Risk Score 0.28) — лимит 30% портфеля
- APY читается из data/adapter_status.json (поле spark_susds.apy),
  fallback = 5.5% при отсутствии / ошибке чтения
- Маршрут: USDC → USDS via PSM 1:1 → sUSDS (SSR 5–6.5%)
- GSM compliance gate: is_eligible() True только если gsm_hours >= 48 (ADR)
- Governance-backed rate, мгновенный выход (no lockup) via PSM
- Модуль строго read-only / advisory: никогда не трогает живой капитал

Правила:
- Только stdlib Python (без внешних зависимостей)
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


class SparkSusdsAdapter(BaseAdapter):
    """Read-only advisory адаптер для Spark Protocol sUSDS ERC-4626 vault (T1).

    APY берётся из ``data/adapter_status.json`` → ``spark_susds.apy``
    (значение в процентах, например 5.5). При отсутствии поля или ошибке
    чтения используется ``DEFAULT_APY_PCT = 5.5``.

    GSM compliance gate: ``is_eligible()`` возвращает True только если
    gsm_hours >= 48 (ADR). Пока gsm_hours = 0 — адаптер не активен.
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "spark_susds"
    PROTOCOL_NAME = "Spark Protocol sUSDS"
    VAULT_ADDRESS = "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T1"
    T1_CAP: float = 0.30          # макс 30% портфеля в этом протоколе
    CHAIN = "ethereum"
    CHAIN_ID: int = 1
    RISK_SCORE: float = 0.28      # ниже Morpho Steakhouse (0.35)

    # мгновенный выход via PSM (USDS → USDC 1:1)
    EXIT_LATENCY_HOURS: float = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    MIN_APY_PCT: float = 4.0
    MAX_APY_PCT: float = 9.0
    DEFAULT_APY_PCT: float = 5.5   # fallback (SSR mid-range)

    TVL_USD: float = 3_000_000_000

    # ── GSM compliance ───────────────────────────────────────────────────
    FORBIDDEN_IF_GSM_BELOW_HOURS: int = 48  # ADR compliance (Sky/sUSDS rule)

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
        """Читает spark_susds-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get("spark_susds", {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("spark_susds: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из spark_susds.apy. Возвращает float или None."""
        apy = self._read_status().get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return None

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (5.5, не 0.055).

        Источник: data/adapter_status.json → spark_susds.apy.
        Fallback: DEFAULT_APY_PCT (5.5%).
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

    # ── GSM compliance ───────────────────────────────────────────────────

    def is_gsm_compliant(self) -> bool:
        """True если gsm_hours >= FORBIDDEN_IF_GSM_BELOW_HOURS (48).

        По умолчанию False (safe): если поле отсутствует или < 48 — не compliant.
        """
        gsm_hours = self._read_status().get("gsm_hours", 0)
        if not isinstance(gsm_hours, (int, float)) or isinstance(gsm_hours, bool):
            return False
        return float(gsm_hours) >= float(self.FORBIDDEN_IF_GSM_BELOW_HOURS)

    # ── eligibility ──────────────────────────────────────────────────────

    def is_eligible(self) -> bool:
        """True если GSM compliant И APY в допустимом диапазоне [MIN, MAX]."""
        if not self.is_gsm_compliant():
            return False
        apy = self.get_apy()
        return self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT

    # ── vs Morpho gap ─────────────────────────────────────────────────────

    def vs_morpho_gap(self, morpho_apy: float = 6.5) -> float:
        """Возвращает morpho_apy - spark_apy (отрицательный = Spark лучше).

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
            dict с ключами: protocol, protocol_name, vault_address, tier, t1_cap,
            chain, chain_id, asset, apy_pct, risk_score, exit_latency_hours,
            tvl_usd, min_apy_pct, max_apy_pct, gsm_compliant, eligible, allocated.
        """
        return {
            "protocol": self.PROTOCOL,
            "protocol_name": self.PROTOCOL_NAME,
            "vault_address": self.VAULT_ADDRESS,
            "tier": self.tier,
            "t1_cap": self.T1_CAP,
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "asset": self.asset,
            "apy_pct": self.get_apy_pct(),
            "risk_score": self.RISK_SCORE,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "tvl_usd": self.TVL_USD,
            "min_apy_pct": self.MIN_APY_PCT,
            "max_apy_pct": self.MAX_APY_PCT,
            "gsm_compliant": self.is_gsm_compliant(),
            "eligible": self.is_eligible(),
            "allocated": self._allocated,
        }

    # end of class
