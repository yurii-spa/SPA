"""Compound V3 (Comet) USDC lending adapter — T1, read-only/advisory — MP-564.

Конкретный адаптер для Compound V3 Comet USDC рынка на Ethereum mainnet.
Comet address: 0xc3d688B66703497DAA19211EEdff47f25384cdc3  (cUSDCv3)

Ключевые характеристики:
- Tier T1 (TVL ~$1.5B, Risk Score 0.28) — лимит 40% портфеля.
  Compound V3 (Comet) — ведущий монолитный lending рынок USDC на Ethereum mainnet.
  Comet market: supply-side позиции в USDC, instant withdraw (same-block).
- APY читается из data/adapter_status.json (поле compound_v3_adapter.apy),
  fallback = DEFAULT_APY_PCT (5.2%) при отсутствии / ошибке чтения.
- RISK_SCORE = 0.28 — T1 anchor; немного выше Aave V3 (0.20) ввиду
  монолитной архитектуры Comet vs multi-market Aave, и меньшей истории
  на уровне Aave V2 (battle-tested), но значительно ниже T2-протоколов.
- Peg-gate: is_peg_healthy() True пока USDC держит привязку к $1.0 —
  отклонение |usdc_price - 1.0| не превышает PEG_TOLERANCE (0.5%).
  USDC имеет жёсткую привязку через Circle redemption 1:1. Логика
  default-safe в сторону healthy: отсутствие поля usdc_price трактуется
  как 1.0 (нет данных о депеге != депег), значит healthy=True.
- EXIT_LATENCY_HOURS = 0.0: instant withdraw из Comet USDC рынка
  (same-block, subject to transient pool utilization).
- Gap-методы: vs_morpho_gap() и vs_aave_gap() для advisory comparisons.
- Модуль строго read-only / advisory: никогда не трогает живой капитал.

Правила:
- Только stdlib Python (без внешних зависимостей)
- Не импортировать из execution / feed_health / risk / monitoring
- Атомарные записи data/-файлов: tmp + os.replace (apply в save-методах)
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Путь к корню репо
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Константы протокола
# ---------------------------------------------------------------------------

#: Адрес Comet USDC v3 на Ethereum mainnet (только метаданные, реальных вызовов нет)
COMET_ADDRESS = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"

#: Ключ верхнего уровня в data/adapter_status.json (MP-564 новая секция)
_APY_STATUS_KEY = "compound_v3_adapter"

#: Fallback APY (%) — типичный supply rate Ethereum mainnet на момент релиза MP-564
_DEFAULT_APY_PCT: float = 5.2

#: Fallback APY других протоколов для gap-вычислений (если JSON недоступен)
_MORPHO_APY_FALLBACK: float = 6.5   # Morpho Blue Steakhouse USDC ~6.5%
_AAVE_APY_FALLBACK: float = 4.2     # Aave V3 Ethereum USDC ~4.2%

#: Диапазон "здорового" APY для health_check / is_eligible
_APY_HEALTH_MIN: float = 1.0
_APY_HEALTH_MAX: float = 30.0

#: Порог для is_better_than_aave: 50 bps = 0.50%
_BETTER_THAN_AAVE_THRESHOLD_PCT: float = 0.50


class CompoundV3Adapter(BaseAdapter):
    """Compound V3 Comet USDC Ethereum — T1 anchor адаптер (MP-564).

    Следует паттерну SdaiAdapter/FraxAdapter: APY из adapter_status.json
    (ключ compound_v3_adapter), fallback DEFAULT_APY_PCT = 5.2%.
    Peg-gate: USDC hard peg 0.5% (Circle redemption).

    Параметры конструктора
    ----------------------
    asset : str
        Торгуемый актив. По умолчанию "USDC".
    data_dir : str | Path | None
        Путь к директории data/. Если None — вычисляется автоматически
        относительно корня репо (два уровня выше spa_core/).

    Атрибуты класса (константы)
    ---------------------------
    PROTOCOL           : "compound_v3"
    COMET_ADDRESS      : адрес контракта cUSDCv3 на Ethereum mainnet
    TIER               : "T1"
    T1_CAP             : 0.40  (максимум 40% портфеля — стандарт T1)
    RISK_SCORE         : 0.28  (T1, выше Aave 0.20 — монолитная архитектура)
    DEFAULT_APY_PCT    : 5.2   (%)
    EXIT_LATENCY_HOURS : 0.0   (мгновенный вывод, same-block)
    TVL_USD            : 1_500_000_000  (~$1.5B Ethereum mainnet USDC market)
    PEG_TOLERANCE      : 0.005  (0.5% — USDC hard peg через Circle)
    """

    # ── идентификаторы протокола ─────────────────────────────────────────────
    PROTOCOL      = "compound_v3"
    COMET_ADDRESS = COMET_ADDRESS

    # ── тир и лимиты ────────────────────────────────────────────────────────
    TIER   = "T1"
    T1_CAP = 0.40   # 40% — стандартный лимит T1

    # ── риск-профиль ────────────────────────────────────────────────────────
    RISK_SCORE         = 0.28   # T1, чуть выше Aave (0.20) — монолитная архитектура
    EXIT_LATENCY_HOURS = 0.0    # мгновенный вывод (same-block)

    # ── APY-параметры ────────────────────────────────────────────────────────
    DEFAULT_APY_PCT: float = _DEFAULT_APY_PCT    # fallback 5.2%
    # backward-compat alias — тесты и старый код могут обращаться через APY_FALLBACK
    APY_FALLBACK: float = _DEFAULT_APY_PCT
    MIN_APY_PCT:  float = _APY_HEALTH_MIN        # 1.0%
    MAX_APY_PCT:  float = _APY_HEALTH_MAX        # 30.0%

    # ── TVL ──────────────────────────────────────────────────────────────────
    TVL_USD: float = 1_500_000_000   # ~$1.5B (Ethereum mainnet USDC market)

    # ── peg compliance ───────────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.005   # 0.5% — USDC hard peg (Circle 1:1 redemption)

    # ── JSON-ключи других протоколов для gap-методов ─────────────────────────
    _MORPHO_STATUS_KEY = "morpho_blue"
    _AAVE_STATUS_KEY   = "aave_v3"

    # ── стабильный идентификатор для дашбордов ──────────────────────────────
    pool_id = "compound-v3-usdc-ethereum-t1"

    # ── chain metadata ───────────────────────────────────────────────────────
    CHAIN    = "ethereum"
    CHAIN_ID = 1

    # ──────────────────────────────────────────────────────────────────────────
    # Инициализация
    # ──────────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[str | Path] = None,
    ) -> None:
        super().__init__(asset)
        # Переопределяем tier (BaseAdapter по умолчанию ставит T2)
        self.tier = self.TIER

        # Определяем путь к data/
        if data_dir is None:
            self._data_dir: Path = _DEFAULT_DATA_DIR
        else:
            self._data_dir = Path(data_dir)

        # Виртуальная позиция для paper-trading симуляции
        self._allocated: float = 0.0

    # ──────────────────────────────────────────────────────────────────────────
    # Внутреннее чтение JSON
    # ──────────────────────────────────────────────────────────────────────────

    def _read_status(self) -> dict:
        """Читает compound_v3_adapter-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get(_APY_STATUS_KEY, {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("compound_v3_adapter: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из compound_v3_adapter.apy. Возвращает float или None."""
        apy = self._read_status().get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return None

    def _load_protocol_apy(self, key: str, fallback: float) -> float:
        """Читает APY протокола по ключу из adapter_status.json.

        Используется gap-методами для получения APY Morpho и Aave.
        Возвращает fallback при отсутствии валидной записи.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            entry = data.get(key, {})
            if isinstance(entry, dict):
                apy = entry.get("apy") or entry.get("apy_pct")
                if isinstance(apy, (int, float)) and not isinstance(apy, bool):
                    return float(apy)
        except Exception as exc:  # noqa: BLE001
            logger.debug("compound_v3_adapter: _load_protocol_apy(%s) failed: %s", key, exc)
        return fallback

    # ──────────────────────────────────────────────────────────────────────────
    # Публичный APY API
    # ──────────────────────────────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (5.2, не 0.052).

        Источник: data/adapter_status.json → compound_v3_adapter.apy.
        Fallback: DEFAULT_APY_PCT (5.2%).
        """
        apy = self._read_apy_from_status()
        return apy if apy is not None else self.DEFAULT_APY_PCT

    def get_apy_pct(self) -> float:
        """Синоним get_apy() — APY в процентах (совместимость с BaseAdapter-family)."""
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        YieldInfo.apy — decimal (0.052 для 5.2%), оркестратор умножает на 100.
        """
        apy_pct = self.get_apy()
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=apy_pct / 100.0,   # YieldInfo ожидает десятичную дробь
            tvl_usd=float(self.TVL_USD),
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Peg compliance
    # ──────────────────────────────────────────────────────────────────────────

    def is_peg_healthy(self) -> bool:
        """True если USDC держит привязку к $1.0 в пределах PEG_TOLERANCE (0.5%).

        Читает ``usdc_price`` из compound_v3_adapter-секции status JSON.
        Логика default-safe в сторону healthy:
          - поле отсутствует            → usdc_price = 1.0 → healthy=True
          - поле нечисловое/bool        → usdc_price = 1.0 → healthy=True
          - |usdc_price - 1.0| <= 0.005 → healthy=True  (привязка в норме)
          - |usdc_price - 1.0| >  0.005 → healthy=False (депег обнаружен)
        """
        price = self._read_status().get("usdc_price", 1.0)
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            return True
        deviation = round(abs(float(price) - 1.0), 10)
        return deviation <= self.PEG_TOLERANCE

    # ──────────────────────────────────────────────────────────────────────────
    # Eligibility
    # ──────────────────────────────────────────────────────────────────────────

    def is_eligible(self) -> bool:
        """True если peg здоров И APY в допустимом диапазоне [MIN_APY_PCT, MAX_APY_PCT]."""
        if not self.is_peg_healthy():
            return False
        apy = self.get_apy()
        return self.MIN_APY_PCT <= apy <= self.MAX_APY_PCT

    # ──────────────────────────────────────────────────────────────────────────
    # Gap-методы: сравнение с Morpho и Aave
    # ──────────────────────────────────────────────────────────────────────────

    def vs_morpho_gap(self, morpho_apy: Optional[float] = None) -> float:
        """Разница APY: Morpho − Compound (positive = Morpho лучше).

        Parameters
        ----------
        morpho_apy : float | None
            APY Morpho в % (override для тестов). Если None — читается из
            adapter_status.json → ключ "morpho_blue", fallback = 6.5%.
        """
        if morpho_apy is None:
            morpho_apy = self._load_protocol_apy(
                self._MORPHO_STATUS_KEY, _MORPHO_APY_FALLBACK
            )
        return round(morpho_apy - self.get_apy(), 6)

    def vs_aave_gap(self, aave_apy: Optional[float] = None) -> float:
        """Разница APY: Compound − Aave (positive = Compound лучше).

        Parameters
        ----------
        aave_apy : float | None
            APY Aave в % (override). Если None — читается из JSON / fallback.
        """
        if aave_apy is None:
            aave_apy = self._load_protocol_apy(
                self._AAVE_STATUS_KEY, _AAVE_APY_FALLBACK
            )
        return round(self.get_apy() - aave_apy, 6)

    def is_better_than_aave(self, aave_apy: Optional[float] = None) -> bool:
        """True если Compound APY превышает Aave APY более чем на 50 bps."""
        return self.vs_aave_gap(aave_apy) > _BETTER_THAN_AAVE_THRESHOLD_PCT

    # ──────────────────────────────────────────────────────────────────────────
    # Paper-trading: allocate / withdraw + симуляционные алиасы
    # ──────────────────────────────────────────────────────────────────────────

    def allocate(self, capital_usd: float) -> dict:
        """Виртуальное размещение капитала на Compound V3 Comet USDC.

        Симулирует supply в пул cUSDCv3. Никогда не трогает реальные активы.

        Parameters
        ----------
        capital_usd : float
            Сумма в USD. Должна быть > 0.

        Returns
        -------
        dict
            Статус операции, APY, ожидаемый годовой доход, метаданные.

        Raises
        ------
        ValueError
            Если capital_usd <= 0.
        """
        if capital_usd <= 0:
            raise ValueError(
                f"allocate: capital_usd должен быть > 0, получено {capital_usd}"
            )
        apy_pct = self.get_apy()
        self._allocated += capital_usd
        annual_yield = capital_usd * (apy_pct / 100.0)

        return {
            "status": "allocated",
            "protocol": self.PROTOCOL,
            "capital_usd": capital_usd,
            "total_allocated_usd": self._allocated,
            "apy_pct": apy_pct,
            "annual_yield_usd": round(annual_yield, 4),
            "comet_address": self.COMET_ADDRESS,
            "tier": self.TIER,
            "ts": time.time(),
        }

    def simulate_deposit(self, amount_usd: float) -> dict:
        """Симуляция deposit (алиас allocate для совместимости с sdai-pattern).

        Parameters
        ----------
        amount_usd : float
            Сумма в USD для виртуальной аллокации. Должна быть > 0.

        Returns
        -------
        dict
            Результат с ключами status, protocol, amount_usd,
            allocated_total_usd, apy_pct, annual_yield_usd, ts.

        Raises
        ------
        ValueError
            Если amount_usd <= 0.
        """
        if amount_usd <= 0:
            raise ValueError(
                f"simulate_deposit: amount_usd должен быть > 0, получено {amount_usd}"
            )
        apy_pct = self.get_apy()
        self._allocated += amount_usd
        annual_yield = amount_usd * (apy_pct / 100.0)

        return {
            "status": "ok",
            "protocol": self.PROTOCOL,
            "amount_usd": amount_usd,
            "allocated_total_usd": self._allocated,
            "apy_pct": apy_pct,
            "annual_yield_usd": round(annual_yield, 4),
            "comet_address": self.COMET_ADDRESS,
            "ts": time.time(),
        }

    def withdraw(self, amount_usd: float) -> dict:
        """Виртуальный вывод капитала с Compound V3 Comet USDC.

        Parameters
        ----------
        amount_usd : float
            Сумма в USD. Должна быть > 0 и <= allocated.

        Returns
        -------
        dict
            Статус операции, остаток позиции, метаданные.

        Raises
        ------
        ValueError
            Если amount_usd <= 0 или amount_usd > _allocated.
        """
        if amount_usd <= 0:
            raise ValueError(
                f"withdraw: amount_usd должен быть > 0, получено {amount_usd}"
            )
        if amount_usd > self._allocated:
            raise ValueError(
                f"withdraw: запрос {amount_usd:.2f} превышает размещённый "
                f"капитал {self._allocated:.2f}"
            )
        self._allocated -= amount_usd

        return {
            "status": "withdrawn",
            "protocol": self.PROTOCOL,
            "amount_usd": amount_usd,
            "remaining_allocated_usd": self._allocated,
            "comet_address": self.COMET_ADDRESS,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "ts": time.time(),
        }

    def simulate_withdraw(self, amount_usd: float) -> dict:
        """Симуляция withdraw (алиас withdraw для совместимости с sdai-pattern).

        Parameters
        ----------
        amount_usd : float
            Сумма в USD. Должна быть > 0.

        Returns
        -------
        dict
            status="ok" при успехе, status="error" + reason если insufficient.
        """
        if amount_usd <= 0:
            raise ValueError(
                f"simulate_withdraw: amount_usd должен быть > 0, получено {amount_usd}"
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
            "amount_usd": amount_usd,
            "allocated_remaining": self._allocated,
            "comet_address": self.COMET_ADDRESS,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "ts": time.time(),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Health
    # ──────────────────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Проверка работоспособности адаптера (без сетевых вызовов).

        Критерий: APY ∈ [MIN_APY_PCT, MAX_APY_PCT] → status "ok", иначе "degraded".
        TVL floor RiskPolicy: ≥ $5M (Compound V3 $1.5B — всегда выполнен).

        Returns
        -------
        dict
            Обязательные ключи: "status" ("ok" | "degraded"), "apy_pct",
            "apy_in_range", "tvl_floor_ok" и прочие метрики адаптера.
        """
        apy_pct = self.get_apy()
        apy_from_file = self._read_apy_from_status()
        apy_in_range = self.MIN_APY_PCT <= apy_pct <= self.MAX_APY_PCT

        return {
            "protocol": self.PROTOCOL,
            "status": "ok" if apy_in_range else "degraded",
            "apy_pct": apy_pct,
            "apy_in_range": apy_in_range,
            "apy_range": [self.MIN_APY_PCT, self.MAX_APY_PCT],
            "apy_source": "adapter_status" if apy_from_file is not None else "fallback",
            "tier": self.TIER,
            "tvl_usd": self.TVL_USD,
            "tvl_floor_ok": self.TVL_USD >= 5_000_000,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "peg_healthy": self.is_peg_healthy(),
            "eligible": self.is_eligible(),
            "allocated_usd": self._allocated,
        }

    def get_health(self) -> dict:
        """Алиас health_check() для совместимости с sdai-паттерном.

        Returns
        -------
        dict
            Тот же результат, что и health_check().
        """
        return self.health_check()

    # ──────────────────────────────────────────────────────────────────────────
    # Сериализация
    # ──────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Полное представление адаптера для дашборда и отчётов.

        Returns
        -------
        dict
            Полный снапшот состояния адаптера, включая peg_healthy, eligible,
            gap-метрики и paper-trading позицию.
        """
        apy_pct = self.get_apy()
        return {
            "protocol": self.PROTOCOL,
            "pool_id": self.pool_id,
            "name": "Compound V3 Comet USDC (Ethereum)",
            "tier": self.TIER,
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "comet_address": self.COMET_ADDRESS,
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t1_cap": self.T1_CAP,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "peg_tolerance": self.PEG_TOLERANCE,
            "peg_healthy": self.is_peg_healthy(),
            "eligible": self.is_eligible(),
            "vs_morpho_gap_pct": self.vs_morpho_gap(),
            "vs_aave_gap_pct": self.vs_aave_gap(),
            "is_better_than_aave": self.is_better_than_aave(),
            "strategy_note": (
                "Compound V3 Comet USDC supply; instant withdraw; T1 anchor; "
                "USDC hard-peg gate 0.5%"
            ),
            "allocated_usd": self._allocated,
        }

    # end of class
