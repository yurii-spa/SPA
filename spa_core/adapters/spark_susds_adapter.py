"""Spark Protocol sUSDS ERC-4626 vault adapter (T1) — MP-376.

Конкретный адаптер для Spark Protocol sUSDS Vault на Ethereum mainnet.
Vault address: 0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD

Ключевые характеристики:
- Tier T1 (TVL $3B+, Risk Score 0.28) — лимит 30% портфеля
- APY читается из data/adapter_status.json через status_reader (наблюдение —
  поле live_apy в современной схеме). Наблюдения нет ⇒ None, БЕЗ подстановки
  литерала: fake-fallback отменён ADR-063 (fail-CLOSED)
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
# ADR-063 (D1): единый читатель схемы adapter_status.json — адаптер больше не
# знает форму файла и не может прочитать не то место.
from spa_core.adapters.status_reader import read_live_apy_pct, read_status_block

logger = logging.getLogger(__name__)

# Корень репо — два уровня выше пакета adapters
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class SparkSusdsAdapter(BaseAdapter):
    """Read-only advisory адаптер для Spark Protocol sUSDS ERC-4626 vault (T1).

    APY берётся из ``data/adapter_status.json`` через ``status_reader``:
    наблюдением считается ТОЛЬКО ``live_apy`` (современная схема) либо ``apy``
    легаси-блока верхнего уровня. Значение — в процентах (например 5.5).
    Наблюдения нет ⇒ ``None``; подстановки ``DEFAULT_APY_PCT`` больше нет —
    fake-fallback отменён ADR-063.

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
    # ВНИМАНИЕ: это НЕ fallback. После ADR-063 ни один путь адаптера сюда не
    # обращается — ``get_apy()`` при отсутствии наблюдения отказывает (None).
    # Константа сохранена как справочная середина диапазона SSR; вернуть её в
    # ответ ``get_apy()`` значит выдать литерал за наблюдение (тест
    # test_spark_get_apy_pct_is_none_when_live_apy_null покраснеет).
    DEFAULT_APY_PCT: float = 5.5   # справочная середина SSR, НЕ подстановка

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
        """Блок протокола из data/adapter_status.json (ADR-063).

        Форму файла знает ``status_reader``: сперва современная секция
        ``adapters[<protocol>]``, затем легаси-ключи верхнего уровня. Раньше
        метод искал блок ТОЛЬКО на верхнем уровне и всегда возвращал {} — из-за
        чего пустыми были и APY, и смежные поля (gsm_hours, цена пега).
        Никогда не бросает исключений.
        """
        return read_status_block(self.PROTOCOL, self._data_dir)

    def _read_apy_from_status(self) -> Optional[float]:
        """Наблюдённый APY (%) или ``None`` (ADR-063).

        Читается ``live_apy`` — единственное поле, доказывающее наблюдение.
        Соседнее ``apy`` не годится: без живого чтения оно повторяет литерал
        ``fallback_apy``.
        """
        return read_live_apy_pct(self.PROTOCOL, self._data_dir)

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy(self) -> Optional[float]:
        """Возвращает наблюдённый APY в процентах (5.5, не 0.055) либо ``None``.

        Источник: ``data/adapter_status.json`` через ``status_reader``
        (``live_apy`` в современной схеме; ``apy`` — только в легаси-блоке).
        Наблюдения нет ⇒ ``None``. Подстановки ``DEFAULT_APY_PCT`` НЕТ:
        fake-fallback отменён ADR-063 (fail-CLOSED, инвариант «никаких
        fake-fallback'ов» из .claude/rules/adapters.md).
        """
        # ADR-063: нет живых данных → None, а не зашитая константа. Раньше
        # константа уходила потребителям как наблюдение (WS1.1 штамповал её
        # apy_source="live") и ранжировала капитал.
        return self._read_apy_from_status()

    def get_apy_pct(self) -> Optional[float]:
        """Возвращает APY в процентах — то же что get_apy() (совместимость с BaseAdapter)."""
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора."""
        _apy_pct = self.get_apy()
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            # ADR-063: None пробрасывается как None (контракт YieldInfo SPA-V398).
            apy=(_apy_pct / 100.0) if _apy_pct is not None else None,   # YieldInfo ожидает десятичную дробь
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
        if apy is None:
            return False   # ADR-063: нет наблюдения ⇒ не eligible (fail-CLOSED)
        return self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT

    # ── vs Morpho gap ─────────────────────────────────────────────────────

    def vs_morpho_gap(self, morpho_apy: float = 6.5) -> Optional[float]:
        """Возвращает morpho_apy - spark_apy (отрицательный = Spark лучше).

        Args:
            morpho_apy: Morpho APY в процентах. По умолчанию 6.5%.
        """
        _apy = self.get_apy()
        if _apy is None:
            return None   # ADR-063: без наблюдения разрыв не определён
        return round(morpho_apy - _apy, 10)

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
        if apy is None:
            return "degraded"   # ADR-063: нет наблюдения ⇒ не "ok"
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
