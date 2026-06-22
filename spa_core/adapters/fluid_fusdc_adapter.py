"""Fluid Protocol fUSDC ERC-4626 vault adapter (T2) — MP-377.

Адаптер для Fluid Protocol (Instadapp) fUSDC vault на Ethereum mainnet.
Vault address: 0x9Fb7b4477576Fe5B32be4C1843aFB1e55F251B33

Ключевые характеристики:
- Tier T2 (TVL ~$2B) — лимит 20% одиночного адаптера (ADR-019: T2 total cap 50%)
- APY читается из data/adapter_status.json → fluid_fusdc.apy, fallback=6.5%
- Spike protection: если raw APY > 15% — нормализовать до 9% (исторические спайки
  при DEX activity могут давать аномалии до 22%)
- GSM compliance gate: gsm_hours >= 48 обязателен перед активацией
- is_eligible() = gsm_compliant AND apy in [MIN_APY, MAX_APY]
- Сравнительные методы: vs_morpho_gap, vs_spark_gap
- Только stdlib Python (json, os, math, pathlib, time)
- Атомарные записи (mkstemp + os.replace) для adapter_status.json
- Advisory/paper trading только — никогда не трогает живой капитал
- Не импортировать из execution / feed_health / risk

ADR-019: T2 total cap 50%, single adapter cap 20%.
GSM gate аналогичен Spark sUSDS — protects against governance exploits.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

# Корень репо — два уровня выше пакета adapters
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class FluidFUSDCAdapter(BaseAdapter):
    """Read-only advisory адаптер для Fluid Protocol fUSDC vault (T2).

    APY читается из ``data/adapter_status.json`` → ``fluid_fusdc.apy``
    (значение в процентах, например 6.5). При отсутствии поля или ошибке
    чтения используется ``DEFAULT_APY_PCT = 6.5``.

    Spike protection: raw APY > SPIKE_THRESHOLD_PCT (15.0) → нормализовать
    до SPIKE_NORM_PCT (9.0), чтобы портфель не перекашивался на аномалиях
    DEX trading activity.

    GSM gate: is_gsm_compliant() → gsm_hours >= 48 (аналог Spark sUSDS).
    Только when gsm_compliant AND apy in range → is_eligible() = True.
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "fluid_fusdc"
    PROTOCOL_NAME = "Fluid Protocol fUSDC"
    VAULT_ADDRESS = "0x9Fb7b4477576Fe5B32be4C1843aFB1e55F251B33"
    CHAIN = "ethereum"
    CHAIN_ID = 1

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T2"
    T2_CAP_TOTAL = 0.50    # ADR-019: T2 total cap 50% portfolio
    T2_CAP_SINGLE = 0.20   # max single T2 adapter cap 20%
    RISK_SCORE = 0.38      # moderate: DEX/lending hybrid, newer protocol

    # SPA-V412: instant withdrawal from ERC-4626 vault (no lock)
    EXIT_LATENCY_HOURS = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    MIN_APY_PCT: float = 3.0           # ниже — слишком низкий, не eligible
    MAX_APY_PCT: float = 10.0          # выше 10% в normal режиме — подозрительно
    DEFAULT_APY_PCT: float = 6.5       # fallback при отсутствии данных в JSON

    SPIKE_THRESHOLD_PCT: float = 15.0  # выше — аномальный spike (DEX активность)
    SPIKE_NORM_PCT: float = 9.0        # нормализованный APY при spike

    # ── TVL ──────────────────────────────────────────────────────────────
    TVL_USD: int = 2_000_000_000       # ~$2B TVL

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

    def _read_status_block(self) -> dict:
        """Читает блок fluid_fusdc из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает
        исключений — graceful fallback в любом случае.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            block = data.get("fluid_fusdc", {})
            return block if isinstance(block, dict) else {}
        except Exception as exc:  # noqa: BLE001
            logger.debug("fluid_fusdc: не удалось прочитать adapter_status.json: %s", exc)
            return {}

    # ── APY API ──────────────────────────────────────────────────────────

    def get_raw_apy(self) -> float:
        """Читает сырой APY из adapter_status.json → fluid_fusdc.apy.

        Возвращает float в процентах (6.5, а не 0.065).
        Fallback: DEFAULT_APY_PCT (6.5%) при отсутствии или ошибке.
        """
        block = self._read_status_block()
        apy = block.get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return self.DEFAULT_APY_PCT

    def get_apy(self) -> float:
        """APY с spike protection в процентах.

        Если raw APY > SPIKE_THRESHOLD_PCT (15.0) → возвращает SPIKE_NORM_PCT (9.0).
        Иначе возвращает raw APY. Никогда не возвращает None (fallback=6.5).

        Реализует контракт BaseAdapter.get_apy() (здесь в процентах,
        а не как decimal — специфика SPA T2 адаптеров с pct-интерфейсом).
        """
        raw = self.get_raw_apy()
        if raw > self.SPIKE_THRESHOLD_PCT:
            return self.SPIKE_NORM_PCT
        return raw

    def get_apy_pct(self) -> float:
        """Возвращает APY в процентах (алиас get_apy для совместимости с BaseAdapter).

        Используется оркестратором и StrategyAllocator в единицах %.
        """
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора."""
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=self.get_apy() / 100.0,   # BaseAdapter convention: decimal (0.065)
            tvl_usd=float(self.TVL_USD),
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ── spike detection ──────────────────────────────────────────────────

    def is_spike(self, apy: Optional[float] = None) -> bool:
        """True если APY превышает SPIKE_THRESHOLD_PCT (15.0).

        Args:
            apy: APY в процентах для проверки. Если None — читает get_raw_apy().

        Граничное значение: 15.0 exact → NOT spike (строгое >).
        15.001+ → spike.
        """
        raw = apy if apy is not None else self.get_raw_apy()
        return raw > self.SPIKE_THRESHOLD_PCT

    # ── GSM compliance ───────────────────────────────────────────────────

    def is_gsm_compliant(self) -> bool:
        """True если Fluid Protocol прошёл GSM gate (gsm_hours >= 48).

        Читает adapter_status.json → fluid_fusdc.gsm_hours.
        При отсутствии поля считает gsm_hours = 0 → False.

        GSM (Governance Security Module) gate защищает от governance exploits —
        аналогичен правилу для Spark sUSDS в SPA.
        """
        block = self._read_status_block()
        gsm_hours = block.get("gsm_hours", 0)
        if isinstance(gsm_hours, (int, float)) and not isinstance(gsm_hours, bool):
            return float(gsm_hours) >= 48.0
        return False

    # ── eligibility ──────────────────────────────────────────────────────

    def is_eligible(self) -> bool:
        """True если адаптер готов к аллокации.

        Conditions (обе должны выполняться):
        1. is_gsm_compliant() — GSM gate пройден
        2. MIN_APY_PCT <= get_apy() <= MAX_APY_PCT — APY в допустимом диапазоне
        """
        if not self.is_gsm_compliant():
            return False
        apy = self.get_apy()
        return self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT

    # ── сравнительный анализ ─────────────────────────────────────────────

    def vs_morpho_gap(self, morpho_apy: float = 6.5) -> float:
        """Разница APY: morpho - fluid (отрицательный = Fluid лучше Morpho).

        Args:
            morpho_apy: APY Morpho Steakhouse в процентах (default: 6.5%).

        Returns:
            float: morpho_apy - fluid_apy. Если отрицательный — Fluid выгоднее.
        """
        return round(morpho_apy - self.get_apy(), 10)

    def vs_spark_gap(self, spark_apy: float = 5.5) -> float:
        """Разница APY: spark - fluid (отрицательный = Fluid лучше Spark).

        Args:
            spark_apy: APY Spark sUSDS в процентах (default: 5.5%).

        Returns:
            float: spark_apy - fluid_apy. Если отрицательный — Fluid выгоднее.
        """
        return round(spark_apy - self.get_apy(), 10)

    # ── виртуальный paper trading API ────────────────────────────────────

    def allocate(self, capital_usd: float) -> dict:
        """Виртуальная аллокация капитала в fUSDC vault (paper trading).

        Args:
            capital_usd: Сумма в USD для аллокации. Должна быть > 0.

        Returns:
            dict со статусом операции.

        Raises:
            ValueError: если capital_usd < 0.
        """
        if capital_usd < 0:
            raise ValueError(f"capital_usd must be non-negative, got {capital_usd}")
        if capital_usd == 0:
            return {
                "status": "noop",
                "reason": "zero amount",
                "requested": 0,
                "allocated": self._allocated,
                "protocol": self.PROTOCOL,
            }
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
        """Виртуальный вывод средств из fUSDC vault (paper trading).

        Args:
            amount_usd: Сумма в USD для вывода.

        Returns:
            dict со статусом операции.
        """
        if amount_usd <= 0:
            return {
                "status": "error",
                "reason": "amount must be positive",
                "requested": amount_usd,
                "allocated": self._allocated,
                "protocol": self.PROTOCOL,
            }
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
        """Возвращает статус адаптера как строку.

        Returns:
            "spike"    — raw APY > SPIKE_THRESHOLD_PCT (аномальный режим)
            "ok"       — APY в нормальном диапазоне [MIN_APY, MAX_APY]
            "degraded" — APY за пределами нормального диапазона (< MIN или > MAX)
                         но не spike (≤ SPIKE_THRESHOLD)
        """
        raw = self.get_raw_apy()
        if raw > self.SPIKE_THRESHOLD_PCT:
            return "spike"
        if self.MIN_APY_PCT <= raw <= self.MAX_APY_PCT:
            return "ok"
        return "degraded"

    # ── atomic write ─────────────────────────────────────────────────────

    def _update_status_json(self, updates: dict) -> None:
        """Атомарно обновляет блок fluid_fusdc в adapter_status.json.

        Использует mkstemp + os.replace для атомарности.
        Никогда не бросает исключений — graceful log при ошибке.

        Args:
            updates: dict с полями для обновления в блоке fluid_fusdc.
        """
        path = self._data_dir / "adapter_status.json"
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fluid_fusdc: не удалось прочитать %s: %s", path, exc)
            data = {}

        block = data.get("fluid_fusdc", {})
        if not isinstance(block, dict):
            block = {}
        block.update(updates)
        data["fluid_fusdc"] = block

        try:
            atomic_save(data, str(path))
        except Exception as exc:  # noqa: BLE001
            logger.error("fluid_fusdc: ошибка атомарной записи %s: %s", path, exc)

    # ── сериализация ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Полное представление адаптера (для дашборда / логов / тестов).

        Returns:
            dict с ключами:
            protocol, protocol_name, vault_address, chain, chain_id,
            tier, t2_cap_total, t2_cap_single, asset, risk_score,
            exit_latency_hours, tvl_usd, raw_apy_pct, apy_pct, apy_decimal,
            spike_detected, spike_threshold_pct, spike_norm_pct,
            gsm_compliant, eligible, min_apy_pct, max_apy_pct,
            vs_morpho_gap, vs_spark_gap, health, allocated.
        """
        raw = self.get_raw_apy()
        apy = self.get_apy()
        return {
            "protocol": self.PROTOCOL,
            "protocol_name": self.PROTOCOL_NAME,
            "vault_address": self.VAULT_ADDRESS,
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "tier": self.tier,
            "t2_cap_total": self.T2_CAP_TOTAL,
            "t2_cap_single": self.T2_CAP_SINGLE,
            "asset": self.asset,
            "risk_score": self.RISK_SCORE,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "tvl_usd": self.TVL_USD,
            "raw_apy_pct": raw,
            "apy_pct": apy,
            "apy_decimal": apy / 100.0,
            "spike_detected": self.is_spike(),
            "spike_threshold_pct": self.SPIKE_THRESHOLD_PCT,
            "spike_norm_pct": self.SPIKE_NORM_PCT,
            "gsm_compliant": self.is_gsm_compliant(),
            "eligible": self.is_eligible(),
            "min_apy_pct": self.MIN_APY_PCT,
            "max_apy_pct": self.MAX_APY_PCT,
            "vs_morpho_gap": self.vs_morpho_gap(),
            "vs_spark_gap": self.vs_spark_gap(),
            "health": self.health_check(),
            "allocated": self._allocated,
        }

    # end of class
