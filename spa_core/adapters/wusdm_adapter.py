"""Mountain Protocol Wrapped USDM (wUSDM) ERC-4626 RWA vault adapter (T2) — MP-559.

Конкретный адаптер для Mountain Protocol wUSDM Vault на Ethereum mainnet.
Vault address: 0x57F5E098CaD7A3D1Eed53991D4d66C45C9Af7812

Ключевые характеристики:
- Tier T2 (TVL $200M, Risk Score 0.45) — лимит 20% портфеля
- wUSDM — это ERC-4626 wrapper над USDM, регулируемым (Bermuda) RWA-стейблкоином
  Mountain Protocol, обеспеченным короткими казначейскими векселями США
  (US Treasury T-bills). Доход начисляется ребейзом USDM и аккумулируется в
  цене обмена wUSDM→USDM (share price растёт). APY привязан к доходности
  short-term US Treasury (T-bill yield).
- APY читается из data/adapter_status.json (поле wusdm.apy),
  fallback = 5.0% при отсутствии / ошибке чтения
- RISK_SCORE = 0.45 выше sFRAX (0.40): централизованный RWA-эмитент даёт
  дополнительный контрагентский / регуляторный / redemption-риск (off-chain
  выкуп T-bills, KYC-гейт на первичный mint/redeem, потенциальная заморозка
  эмитентом). Это не алгоритмический, а кастодиальный стейблкоин.
- Peg-gate: is_peg_healthy() True пока USDM держит привязку к $1.0 —
  отклонение |usdm_price - 1.0| не превышает PEG_TOLERANCE (0.5%).
- ERC-4626 unwrap wUSDM→USDM атомарен и мгновенный (EXIT_LATENCY_HOURS = 0.0);
  однако на практике есть swap-friction USDM↔USDC (slippage / ликвидность
  пула на вторичном рынке) — выход в USDC не атомарен, аналогично сценарию
  FRAX↔USDC у sFRAX. Первичный redeem USDM у эмитента требует KYC и не
  мгновенен. Эта friction учитывается отдельно оркестратором; здесь
  декларируется только латентность ERC-4626 unwrap.
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


class WusdmAdapter(BaseAdapter):
    """Read-only advisory адаптер для Mountain Protocol wUSDM ERC-4626 vault (T2).

    APY берётся из ``data/adapter_status.json`` → ``wusdm.apy``
    (значение в процентах, например 5.0). При отсутствии поля или ошибке
    чтения используется ``DEFAULT_APY_PCT = 5.0`` (доход от US T-bills,
    привязан к short-term Treasury yield).

    Peg-gate: ``is_peg_healthy()`` возвращает True пока цена USDM держит
    привязку к $1.0 — отклонение ``|usdm_price - 1.0|`` не превышает
    ``PEG_TOLERANCE`` (0.5%). Логика default-safe в сторону healthy:
    отсутствие поля ``usdm_price`` трактуется как 1.0 (нет данных о депеге !=
    депег), значит healthy=True. Но если поле присутствует и отклонение
    превышает допуск — gate закрывается (False).
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "wusdm"
    PROTOCOL_NAME = "Mountain Protocol Wrapped USDM (wUSDM)"
    VAULT_ADDRESS = "0x57F5E098CaD7A3D1Eed53991D4d66C45C9Af7812"

    # ── тир / риск ───────────────────────────────────────────────────────
    TIER = "T2"
    T2_CAP: float = 0.20          # макс 20% портфеля в этом протоколе (T2 лимит)
    CHAIN = "ethereum"
    CHAIN_ID: int = 1
    RISK_SCORE: float = 0.45      # выше sFRAX (0.40): централизованный RWA-эмитент + регуляторный/redemption риск

    # ERC-4626 unwrap wUSDM→USDM атомарен; swap-friction USDM↔USDC учитывается оркестратором
    EXIT_LATENCY_HOURS: float = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    MIN_APY_PCT: float = 3.0
    MAX_APY_PCT: float = 10.0
    DEFAULT_APY_PCT: float = 5.0   # fallback (доход от US T-bills, привязан к short-term Treasury yield)

    TVL_USD: float = 200_000_000

    # ── peg compliance ───────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.005   # 0.5% — макс отклонение usdm_price от 1.0

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
        """Читает wusdm-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get("wusdm", {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("wusdm: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из wusdm.apy. Возвращает float или None."""
        apy = self._read_status().get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return None

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (5.0, не 0.05).

        Источник: data/adapter_status.json → wusdm.apy.
        Fallback: DEFAULT_APY_PCT (5.0%).
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
        """True если USDM держит привязку к $1.0 в пределах PEG_TOLERANCE.

        Читает ``usdm_price`` из status. Логика default-safe в сторону healthy:
          - поле отсутствует            → usdm_price = 1.0 → healthy=True
            (отсутствие данных != депег; не блокируем по неполноте данных)
          - поле нечисловое/bool        → usdm_price = 1.0 → healthy=True (safe)
          - |usdm_price - 1.0| <= 0.005 → healthy=True  (привязка в норме)
          - |usdm_price - 1.0| >  0.005 → healthy=False (депег обнаружен)
        """
        price = self._read_status().get("usdm_price", 1.0)
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
        """Возвращает morpho_apy - wusdm_apy (отрицательный = wUSDM лучше).

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
