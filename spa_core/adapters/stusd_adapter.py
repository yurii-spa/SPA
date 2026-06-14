"""Angle Staked USDA (stUSD) ERC-4626 savings vault adapter (T2) — MP-561.

Конкретный адаптер для Angle Staked USDA (stUSD) на Ethereum mainnet.
Vault address: 0x0022228a2cc5E7eF0274A2C3D1E5e306d3eF0a17
Underlying USDA: 0x0000206329b97DB379d5E1Bf586BbDB969C63274 (Angle Protocol)

Ключевые характеристики:
- Tier T2 (TVL ~$50M, Risk Score 0.43) — лимит 20% портфеля
- stUSD — это ERC-4626 savings-vault над USDA (стейблкоин Angle Protocol,
  over-collateralized, hard-pegged через transmuter-механику; резервы частично
  RWA / T-bill-backed). Доход начисляется savings rate-механизмом Angle:
  share price stUSD→USDA растёт (yield-accruing wrapper, не ребейз).
- APY читается из data/adapter_status.json (поле stusd.apy),
  fallback = 6.0% при отсутствии / ошибке чтения. Savings rate Angle
  историчеcки переменчив (≈3–12% в зависимости от доходности резервов).
- RISK_SCORE = 0.43 — между sFRAX (0.40, hard-pegged, алгоритмический) и
  wUSDM (0.45, кастодиальный RWA). USDA over-collateralized и hard-pegged
  через transmuter (peg удерживается жёстче, чем у soft-peg LLAMMA scrvUSD),
  эмитент децентрализован (нет KYC-гейта / эмитентской заморозки уровня
  кастодиального RWA), НО частично RWA / T-bill-backed резервы дают умеренный
  контрагентский риск, чуть выше чем у чисто-алгоритмического sFRAX. Итоговый 0.43.
- Peg-gate: is_peg_healthy() True пока USDA держит привязку к $1.0 —
  отклонение |usda_price - 1.0| не превышает PEG_TOLERANCE (0.5%). Допуск
  как у hard-pegged wUSDM/sFRAX (0.5%), т.к. USDA hard-pegged через transmuter
  (жёсткая привязка, не штатные soft-peg колебания scrvUSD).
- ERC-4626 redeem stUSD→USDA атомарен и мгновенный (EXIT_LATENCY_HOURS = 0.0);
  однако на практике есть swap-friction USDA↔USDC (slippage / ликвидность
  пула на вторичном рынке) — выход в USDC не атомарен, аналогично сценарию
  crvUSD↔USDC у scrvUSD. Эта friction учитывается отдельно оркестратором; здесь
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

logger = logging.getLogger(__name__)

# Корень репо — два уровня выше пакета adapters
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class StusdAdapter(BaseAdapter):
    """Read-only advisory адаптер для Angle Staked USDA ERC-4626 vault (T2).

    APY берётся из ``data/adapter_status.json`` → ``stusd.apy``
    (значение в процентах, например 6.0). При отсутствии поля или ошибке
    чтения используется ``DEFAULT_APY_PCT = 6.0`` (savings rate Angle Protocol).

    Peg-gate: ``is_peg_healthy()`` возвращает True пока цена USDA держит
    привязку к $1.0 — отклонение ``|usda_price - 1.0|`` не превышает
    ``PEG_TOLERANCE`` (0.5%). Логика default-safe в сторону healthy:
    отсутствие поля ``usda_price`` трактуется как 1.0 (нет данных о депеге !=
    депег), значит healthy=True. Но если поле присутствует и отклонение
    превышает допуск — gate закрывается (False).
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "stusd"
    PROTOCOL_NAME = "Angle Staked USDA (stUSD)"
    VAULT_ADDRESS = "0x0022228a2cc5E7eF0274A2C3D1E5e306d3eF0a17"
    UNDERLYING_ADDRESS = "0x0000206329b97DB379d5E1Bf586BbDB969C63274"  # USDA

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T2"
    T2_CAP: float = 0.20          # макс 20% портфеля в этом протоколе (T2 лимит)
    CHAIN = "ethereum"
    CHAIN_ID: int = 1
    RISK_SCORE: float = 0.43      # между sFRAX (0.40) и wUSDM (0.45): over-collateralized hard-peg, но частично RWA/T-bill резервы

    # ERC-4626 redeem stUSD→USDA атомарен; swap-friction USDA↔USDC учитывается оркестратором
    EXIT_LATENCY_HOURS: float = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    MIN_APY_PCT: float = 3.0
    MAX_APY_PCT: float = 12.0
    DEFAULT_APY_PCT: float = 6.0   # fallback (savings rate Angle Protocol; переменчив)

    TVL_USD: float = 50_000_000

    # ── peg compliance ───────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.005   # 0.5% — макс отклонение usda_price от 1.0 (hard-peg через transmuter)

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
        """Читает stusd-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get("stusd", {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("stusd: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из stusd.apy. Возвращает float или None."""
        apy = self._read_status().get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return None

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (6.0, не 0.06).

        Источник: data/adapter_status.json → stusd.apy.
        Fallback: DEFAULT_APY_PCT (6.0%).
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
        """True если USDA держит привязку к $1.0 в пределах PEG_TOLERANCE.

        Читает ``usda_price`` из status. Логика default-safe в сторону healthy:
          - поле отсутствует             → usda_price = 1.0 → healthy=True
            (отсутствие данных != депег; не блокируем по неполноте данных)
          - поле нечисловое/bool         → usda_price = 1.0 → healthy=True (safe)
          - |usda_price - 1.0| <= 0.005  → healthy=True  (привязка в норме)
          - |usda_price - 1.0| >  0.005  → healthy=False (депег обнаружен)
        """
        price = self._read_status().get("usda_price", 1.0)
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            # Нечисловое значение — считаем привязку здоровой (нет валидных данных о депеге)
            return True
        # round до 10 знаков снимает float-артефакты на самой границе допуска
        # (напр. abs(0.995 - 1.0) = 0.00500000...44), чтобы граница вела себя
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
        """Возвращает morpho_apy - stusd_apy (отрицательный = stUSD лучше).

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
