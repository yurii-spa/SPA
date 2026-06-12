"""Compound V3 (Comet) USDC Mainnet адаптер — T1 anchor (MP-365).

Comet USDC на Ethereum mainnet:
  Контракт: 0xc3d688B66703497DAA19211EEdff47f25384cdc3  (cUSDCv3)
  TVL: ~$2.8B, APY supply rate ~4.8% (Ethereum mainnet)
  Вывод: мгновенный (instant withdraw, same-block).

APY-приоритет:
  1. data/adapter_status.json → ключ "compound_v3" → поле "apy"
  2. Fallback: APY_FALLBACK = 4.8%

Gap-методы:
  vs_morpho_gap() → Morpho APY − Compound APY  (positive = Morpho лучше)
  vs_aave_gap()   → Compound APY − Aave APY    (positive = Compound лучше)
  is_better_than_aave() → True если vs_aave_gap() > 50 bps (0.50%)

Health-check:
  "ok"       если APY ∈ [3.0, 8.0]%
  "degraded" иначе (APY вышел за ожидаемый рабочий диапазон)

Этот модуль — строго read-only / advisory (paper-trading симуляция):
allocate() и withdraw() работают с виртуальным капиталом, не трогают
реальные активы. Никогда не импортируется из execution/ или risk/.

FORBIDDEN:
  - Только stdlib Python — без внешних зависимостей
  - LLM запрещён в risk/execution/monitoring компонентах
  - Атомарные записи data/-файлов: tmp + os.replace
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
# Константы протокола
# ---------------------------------------------------------------------------

# Адрес Comet USDC v3 на Ethereum mainnet (только метаданные, реальных вызовов нет)
COMET_ADDRESS = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"

# Ключ верхнего уровня в data/adapter_status.json
_APY_STATUS_KEY = "compound_v3"

# Fallback APY (%) — фактический supply rate Ethereum mainnet на момент релиза
_APY_FALLBACK_PCT = 4.8

# Fallback APY других протоколов для gap-вычислений (если JSON недоступен)
_MORPHO_APY_FALLBACK = 6.5   # Morpho Blue Steakhouse USDC ~6.5%
_AAVE_APY_FALLBACK   = 4.2   # Aave V3 Ethereum USDC ~4.2%

# Диапазон "здорового" APY для health_check
_APY_HEALTH_MIN = 3.0
_APY_HEALTH_MAX = 8.0

# Порог для is_better_than_aave: 50 bps = 0.50%
_BETTER_THAN_AAVE_THRESHOLD_PCT = 0.50


class CompoundV3Adapter(BaseAdapter):
    """Compound V3 Comet USDC Ethereum — T1 anchor адаптер (MP-365).

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
    T1_CAP             : 0.30  (максимум 30% портфеля — чуть ниже Aave 40%)
    RISK_SCORE         : 0.25  (T1, выше Aave 0.20 — Comet имеет меньше истории)
    APY_FALLBACK       : 4.8   (%)
    EXIT_LATENCY_HOURS : 0.0   (мгновенный вывод, same-block)
    TVL_USD            : 2_800_000_000  (~$2.8B Ethereum mainnet USDC market)
    """

    # Идентификаторы протокола
    PROTOCOL      = "compound_v3"
    COMET_ADDRESS = COMET_ADDRESS

    # Tier и лимиты
    TIER   = "T1"
    T1_CAP = 0.30   # 30% — чуть ниже Aave (40%) как второй T1

    # Риск-профиль
    RISK_SCORE         = 0.25   # T1, чуть выше Aave (0.20) — меньше истории
    EXIT_LATENCY_HOURS = 0.0    # мгновенный вывод (same-block)

    # APY-параметры
    APY_FALLBACK    = _APY_FALLBACK_PCT
    _APY_STATUS_KEY = _APY_STATUS_KEY

    # TVL
    TVL_USD = 2_800_000_000   # ~$2.8B (Ethereum mainnet USDC market)

    # Ключи других протоколов в adapter_status.json (для gap-методов)
    _MORPHO_STATUS_KEY = "morpho_blue"
    _AAVE_STATUS_KEY   = "aave_v3"

    # Стабильный идентификатор для дашбордов
    pool_id = "compound-v3-usdc-ethereum-t1"

    # ------------------------------------------------------------------ #
    # Инициализация                                                        #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[str | Path] = None,
    ) -> None:
        super().__init__(asset)
        # Устанавливаем tier T1 (BaseAdapter по умолчанию ставит T2)
        self.tier = self.TIER

        # Определяем путь к data/
        if data_dir is None:
            # spa_core/adapters/compound_v3_adapter.py → repo root / data
            self._data_dir: Path = (
                Path(__file__).resolve().parents[2] / "data"
            )
        else:
            self._data_dir = Path(data_dir)

        # Виртуальная позиция для paper-trading симуляции
        self._allocated_capital: float = 0.0

    # ------------------------------------------------------------------ #
    # APY-чтение (приоритет: JSON → fallback)                              #
    # ------------------------------------------------------------------ #

    def _load_status_json(self) -> dict:
        """Читает data/adapter_status.json целиком.

        Возвращает dict при успехе, пустой dict при любой ошибке.
        Никогда не бросает исключений.
        """
        status_path = self._data_dir / "adapter_status.json"
        try:
            with open(status_path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            logger.debug(
                "compound_v3_adapter: adapter_status.json не найден (%s)", status_path
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "compound_v3_adapter: ошибка чтения adapter_status.json: %s", exc
            )
        return {}

    def _load_apy_from_status(self) -> Optional[float]:
        """Читает APY из adapter_status.json → ключ "compound_v3" → "apy".

        Возвращает float (%) при успехе, None если запись отсутствует или
        невалидна. Никогда не бросает исключений.
        """
        data = self._load_status_json()
        entry = data.get(self._APY_STATUS_KEY)
        if entry and isinstance(entry.get("apy"), (int, float)):
            return float(entry["apy"])
        return None

    def _load_protocol_apy(self, key: str, fallback: float) -> float:
        """Читает APY протокола по ключу из adapter_status.json.

        Используется gap-методами для получения APY Morpho и Aave.
        Возвращает fallback при отсутствии валидной записи.

        Parameters
        ----------
        key : str
            Ключ верхнего уровня в adapter_status.json.
        fallback : float
            Fallback APY в % если запись отсутствует или невалидна.
        """
        data = self._load_status_json()
        entry = data.get(key)
        if entry and isinstance(entry.get("apy"), (int, float)):
            return float(entry["apy"])
        return fallback

    def get_apy(self) -> float:
        """Возвращает APY Compound V3 USDC в процентах (напр. 4.8 = 4.8%).

        Приоритет источника:
          1. data/adapter_status.json → ключ "compound_v3" → поле "apy"
          2. Fallback: APY_FALLBACK = 4.8%
        """
        apy = self._load_apy_from_status()
        if apy is not None:
            return apy
        return self.APY_FALLBACK

    def get_apy_pct(self) -> float:
        """Синоним get_apy() — APY в процентах для явного обозначения единиц.

        Полезен для вызовов, где имя метода должно явно указывать единицы
        измерения (%, а не decimal). Всегда равен get_apy().
        """
        return self.get_apy()

    # ------------------------------------------------------------------ #
    # Gap-методы: сравнение с Morpho и Aave                               #
    # ------------------------------------------------------------------ #

    def vs_morpho_gap(self, morpho_apy: Optional[float] = None) -> float:
        """Разница APY: Morpho − Compound (positive = Morpho лучше).

        Parameters
        ----------
        morpho_apy : float | None
            APY Morpho в % (override для тестов или внешних вызовов).
            Если None — читается из adapter_status.json → ключ "morpho_blue",
            fallback = 6.5%.

        Returns
        -------
        float
            Положительное значение → Morpho предлагает более высокий APY.
            Отрицательное значение → Compound лучше Morpho.
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
            APY Aave в % (override для тестов или внешних вызовов).
            Если None — читается из adapter_status.json → ключ "aave_v3",
            fallback = 4.2%.

        Returns
        -------
        float
            Положительное значение → Compound предлагает более высокий APY.
            Отрицательное значение → Aave лучше Compound.
        """
        if aave_apy is None:
            aave_apy = self._load_protocol_apy(
                self._AAVE_STATUS_KEY, _AAVE_APY_FALLBACK
            )
        return round(self.get_apy() - aave_apy, 6)

    def is_better_than_aave(self, aave_apy: Optional[float] = None) -> bool:
        """True если Compound APY превышает Aave APY более чем на 50 bps.

        Parameters
        ----------
        aave_apy : float | None
            APY Aave в % (override). Если None — читается из JSON / fallback.

        Returns
        -------
        bool
            True если vs_aave_gap(aave_apy) > 0.50% (50 basis points).
        """
        return self.vs_aave_gap(aave_apy) > _BETTER_THAN_AAVE_THRESHOLD_PCT

    # ------------------------------------------------------------------ #
    # Обязательные методы BaseAdapter                                      #
    # ------------------------------------------------------------------ #

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        YieldInfo.apy — decimal (0.048 для 4.8%), tvl_usd в USD.
        """
        apy_pct = self.get_apy()
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            # YieldInfo.apy — decimal (0.048 для 4.8%), оркестратор умножает на 100
            apy=apy_pct / 100.0,
            tvl_usd=float(self.TVL_USD),
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
        )

    # ------------------------------------------------------------------ #
    # Paper-trading: allocate / withdraw                                   #
    # ------------------------------------------------------------------ #

    def allocate(self, capital_usd: float) -> dict:
        """Виртуальное размещение капитала на Compound V3 Comet USDC.

        Симулирует supply в пул cUSDCv3. Никогда не трогает реальные активы.

        Parameters
        ----------
        capital_usd : float
            Сумма в USD для виртуального размещения. Должна быть > 0.

        Returns
        -------
        dict
            Статус операции, APY, ожидаемый годовой доход, метаданные.

        Raises
        ------
        ValueError
            Если capital_usd ≤ 0.
        """
        if capital_usd <= 0:
            raise ValueError(
                f"allocate: capital_usd должен быть > 0, получено {capital_usd}"
            )
        apy_pct = self.get_apy()
        self._allocated_capital += capital_usd
        # Ожидаемый годовой доход в USD
        annual_yield = capital_usd * (apy_pct / 100.0)

        return {
            "status": "allocated",
            "protocol": self.PROTOCOL,
            "capital_usd": capital_usd,
            "total_allocated_usd": self._allocated_capital,
            "apy_pct": apy_pct,
            "annual_yield_usd": round(annual_yield, 4),
            "comet_address": self.COMET_ADDRESS,
            "tier": self.TIER,
            "ts": time.time(),
        }

    def withdraw(self, amount_usd: float) -> dict:
        """Виртуальный вывод капитала с Compound V3 Comet USDC.

        Симулирует withdraw из пула cUSDCv3. Никогда не трогает реальные
        активы. Сумма не может превышать текущую виртуальную позицию.

        Parameters
        ----------
        amount_usd : float
            Сумма в USD для вывода. Должна быть > 0 и ≤ allocated_capital.

        Returns
        -------
        dict
            Статус операции, остаток позиции, метаданные.

        Raises
        ------
        ValueError
            Если amount_usd ≤ 0 или amount_usd > allocated_capital.
        """
        if amount_usd <= 0:
            raise ValueError(
                f"withdraw: amount_usd должен быть > 0, получено {amount_usd}"
            )
        if amount_usd > self._allocated_capital:
            raise ValueError(
                f"withdraw: запрос {amount_usd:.2f} превышает размещённый "
                f"капитал {self._allocated_capital:.2f}"
            )
        self._allocated_capital -= amount_usd

        return {
            "status": "withdrawn",
            "protocol": self.PROTOCOL,
            "amount_usd": amount_usd,
            "remaining_allocated_usd": self._allocated_capital,
            "comet_address": self.COMET_ADDRESS,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "ts": time.time(),
        }

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                               #
    # ------------------------------------------------------------------ #

    def health_check(self) -> dict:
        """Проверка работоспособности адаптера (без сетевых вызовов).

        Критерий: APY ∈ [3.0, 8.0]% → status "ok", иначе "degraded".
        TVL floor RiskPolicy: ≥ $5M (Compound V3 $2.8B — всегда выполнен).

        Returns
        -------
        dict
            Обязательные ключи: "status" ("ok" | "degraded"), "apy_pct",
            "apy_in_range", "tvl_floor_ok" и прочие метрики адаптера.
        """
        apy_pct = self.get_apy()
        apy_from_file = self._load_apy_from_status()
        # Проверяем что APY в ожидаемом рабочем диапазоне
        apy_in_range = _APY_HEALTH_MIN <= apy_pct <= _APY_HEALTH_MAX

        return {
            "protocol": self.PROTOCOL,
            "status": "ok" if apy_in_range else "degraded",
            "apy_pct": apy_pct,
            "apy_in_range": apy_in_range,
            "apy_range": [_APY_HEALTH_MIN, _APY_HEALTH_MAX],
            "apy_source": "adapter_status" if apy_from_file is not None else "fallback",
            "tier": self.TIER,
            "tvl_usd": self.TVL_USD,
            # TVL floor RiskPolicy: ≥ $5M
            "tvl_floor_ok": self.TVL_USD >= 5_000_000,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "allocated_capital_usd": self._allocated_capital,
        }

    def to_dict(self) -> dict:
        """Полное представление адаптера для дашборда и отчётов.

        Включает метаданные контракта, APY, TVL, gap-метрики и
        strategy_note с описанием стратегии по спецификации MP-365.

        Returns
        -------
        dict
            Полный снапшот состояния адаптера.
        """
        apy_pct = self.get_apy()
        return {
            "protocol": self.PROTOCOL,
            "pool_id": self.pool_id,
            "name": "Compound V3 Comet USDC (Ethereum)",
            "tier": self.TIER,
            # Контрактные метаданные
            "comet_address": self.COMET_ADDRESS,
            # Финансовые метрики
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t1_cap": self.T1_CAP,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            # Gap-метрики (без override → JSON / fallback)
            "vs_morpho_gap_pct": self.vs_morpho_gap(),
            "vs_aave_gap_pct": self.vs_aave_gap(),
            "is_better_than_aave": self.is_better_than_aave(),
            # Стратегическое описание (обязательное поле по MP-365)
            "strategy_note": (
                "Compound V3 Comet USDC supply; instant withdraw; T1 anchor"
            ),
            # Paper-trading состояние
            "allocated_capital_usd": self._allocated_capital,
        }

    # end of class
