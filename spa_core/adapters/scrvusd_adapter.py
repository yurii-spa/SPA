"""Curve Savings crvUSD (scrvUSD) ERC-4626 savings vault adapter (T2) — MP-560.

Конкретный адаптер для Curve Savings crvUSD (scrvUSD) на Ethereum mainnet.
Vault address: 0x0655977FEb2f289A4aB78af67BAB0d17aAb84367

Ключевые характеристики:
- Tier T2 (TVL ~$100M, Risk Score 0.42) — лимит 20% портфеля
- scrvUSD — это ERC-4626 savings-vault над crvUSD (стейблкоин Curve Finance,
  over-collateralized, soft-pegged через LLAMMA). Доход начисляется из части
  процентного дохода рынков заимствования crvUSD (crvUSD borrow interest),
  распределяемого держателям savings-vault. Share price scrvUSD→crvUSD растёт
  (yield-accruing wrapper, не ребейз).
- APY читается из data/adapter_status.json (поле scrvusd.apy),
  fallback = 7.0% при отсутствии / ошибке чтения. crvUSD savings rate
  историчеcки переменчив (≈5–12% в зависимости от utilization рынков crvUSD).
- RISK_SCORE = 0.42 — между sFRAX (0.40, hard-pegged, алгоритмический) и
  wUSDM (0.45, кастодиальный RWA). crvUSD децентрализован и over-collateralized
  (нет off-chain контрагента / KYC-гейта / эмитентской заморозки — риск ниже,
  чем у RWA), НО soft-peg через LLAMMA-механику допускает бо́льший дрейф цены,
  чем у hard-pegged стейблов (риск чуть выше, чем у sFRAX). Итоговый 0.42.
- Peg-gate: is_peg_healthy() True пока crvUSD держит привязку к $1.0 —
  отклонение |crvusd_price - 1.0| не превышает PEG_TOLERANCE (1.0%). Допуск
  шире, чем у hard-pegged sFRAX/wUSDM (0.5%), т.к. soft-peg LLAMMA штатно
  допускает бо́льшие колебания вокруг $1.0.
- ERC-4626 redeem scrvUSD→crvUSD атомарен и мгновенный (EXIT_LATENCY_HOURS = 0.0);
  однако на практике есть swap-friction crvUSD↔USDC (slippage / ликвидность
  пула на вторичном рынке) — выход в USDC не атомарен, аналогично сценарию
  FRAX↔USDC у sFRAX. Эта friction учитывается отдельно оркестратором; здесь
  декларируется только латентность ERC-4626 redeem.
- Модуль строго read-only / advisory: никогда не трогает живой капитал

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
# ADR-063 (D1): единый читатель схемы adapter_status.json — адаптер больше не
# знает форму файла и не может прочитать не то место.
from spa_core.adapters.status_reader import read_live_apy_pct, read_status_block
from spa_core.utils.data_dir import own_data_dir

logger = logging.getLogger(__name__)

# Корень репо — два уровня выше пакета adapters
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class ScrvusdAdapter(BaseAdapter):
    """Read-only advisory адаптер для Curve Savings crvUSD ERC-4626 vault (T2).

    APY берётся из ``data/adapter_status.json`` → ``scrvusd.apy``
    (значение в процентах, например 7.0). При отсутствии поля или ошибке
    чтения используется ``DEFAULT_APY_PCT = 7.0`` (доход из процентов рынков
    заимствования crvUSD).

    Peg-gate: ``is_peg_healthy()`` возвращает True пока цена crvUSD держит
    привязку к $1.0 — отклонение ``|crvusd_price - 1.0|`` не превышает
    ``PEG_TOLERANCE`` (1.0%). Логика default-safe в сторону healthy:
    отсутствие поля ``crvusd_price`` трактуется как 1.0 (нет данных о депеге !=
    депег), значит healthy=True. Но если поле присутствует и отклонение
    превышает допуск — gate закрывается (False).
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "scrvusd"
    PROTOCOL_NAME = "Curve Savings crvUSD (scrvUSD)"
    VAULT_ADDRESS = "0x0655977FEb2f289A4aB78af67BAB0d17aAb84367"

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T2"
    T2_CAP: float = 0.20          # макс 20% портфеля в этом протоколе (T2 лимит)
    CHAIN = "ethereum"
    CHAIN_ID: int = 1
    RISK_SCORE: float = 0.42      # между sFRAX (0.40) и wUSDM (0.45): децентрализованный over-collateralized stable, но soft-peg LLAMMA

    # ERC-4626 redeem scrvUSD→crvUSD атомарен; swap-friction crvUSD↔USDC учитывается оркестратором
    EXIT_LATENCY_HOURS: float = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    MIN_APY_PCT: float = 3.0
    MAX_APY_PCT: float = 15.0
    DEFAULT_APY_PCT: float = 7.0   # fallback (доход из процентов рынков заимствования crvUSD; переменчив)

    TVL_USD: float = 100_000_000

    # ── peg compliance ───────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.01    # 1.0% — макс отклонение crvusd_price от 1.0 (soft-peg LLAMMA, шире hard-pegged 0.5%)

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[Path | str] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER
        self._data_dir = Path(data_dir) if data_dir is not None else own_data_dir(_DEFAULT_DATA_DIR)
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
        """Возвращает APY в процентах (7.0, не 0.07).

        Источник: data/adapter_status.json → scrvusd.apy.
        Fallback: DEFAULT_APY_PCT (7.0%).
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

    # ── peg compliance ───────────────────────────────────────────────────

    def is_peg_healthy(self) -> bool:
        """True если crvUSD держит привязку к $1.0 в пределах PEG_TOLERANCE.

        Читает ``crvusd_price`` из status. Логика default-safe в сторону healthy:
          - поле отсутствует            → crvusd_price = 1.0 → healthy=True
            (отсутствие данных != депег; не блокируем по неполноте данных)
          - поле нечисловое/bool        → crvusd_price = 1.0 → healthy=True (safe)
          - |crvusd_price - 1.0| <= 0.01 → healthy=True  (привязка в норме)
          - |crvusd_price - 1.0| >  0.01 → healthy=False (депег обнаружен)
        """
        price = self._read_status().get("crvusd_price", 1.0)
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
        if apy is None:
            return False   # ADR-063: нет наблюдения ⇒ не eligible (fail-CLOSED)
        return self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT

    # ── vs Morpho gap ─────────────────────────────────────────────────────

    def vs_morpho_gap(self, morpho_apy: float = 6.5) -> Optional[float]:
        """Возвращает morpho_apy - scrvusd_apy (отрицательный = scrvUSD лучше).

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
            dict с ключами: protocol, protocol_name, vault_address, tier, t2_cap,
            chain, chain_id, asset, apy_pct, risk_score, exit_latency_hours,
            tvl_usd, min_apy_pct, max_apy_pct, peg_healthy, eligible, allocated.
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
        }

    # end of class
