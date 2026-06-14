"""Aave V3 Polygon USDC.e lending adapter — T1 L2 anchor, read-only/advisory — MP-593.

Конкретный адаптер для Aave V3 USDC.e-рынка на Polygon (PoS Mainnet).
Pool address: 0x794a61358D6845594F94dc1DB02A252b5b4814aD  (Aave V3 Polygon Pool)
USDC address: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174  (USDC.e on Polygon — bridged)

Ключевые характеристики:
- Tier T1 (TVL ~$800M, Risk Score 0.27) — лимит 40% портфеля.
  Aave V3 Polygon — зрелый L2-рынок, один из первых Aave V3 deployment-ов.
  RISK_SCORE = 0.27 (чуть выше Optimism 0.25) из-за bridged-природы USDC.e:
  USDC.e — не native Circle USDC, а bridged через Polygon PoS Bridge, что несёт
  дополнительный bridge-риск (smart contract risk on the bridge).
- APY читается из data/adapter_status.json (поле aave_v3_polygon.apy),
  fallback = DEFAULT_APY_PCT (5.1%) при отсутствии / ошибке чтения.
  Polygon USDC.e supply APY исторически ~4.8–5.5% (base rate + OP incentives).
- Peg-gate: is_peg_healthy() True пока USDC держит привязку к $1.0 —
  отклонение |usdc_price - 1.0| не превышает PEG_TOLERANCE (0.5%).
  Логика default-safe в сторону healthy.
- EXIT_LATENCY_HOURS = 0.0: instant withdraw из Aave V3 Polygon пула
  (same-block, subject to pool utilization).
- L2-преимущество: gas ~90% дешевле mainnet ($0.001 vs $0.10).
  Метод get_gas_savings_vs_mainnet() возвращает {savings_pct: 90.0, chain: "polygon"}.
- USDC.e = bridged USDC: get_bridge_risk_note() возвращает описание bridge risk.
- Модуль строго read-only / advisory: никогда не трогает живой капитал.

Правила:
- Только stdlib Python (без внешних зависимостей)
- Не импортировать из execution / feed_health / risk / monitoring
- Атомарные записи data/-файлов: tmp + os.replace (соблюдается в зависимостях)
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
# Путь к корню репо (два уровня выше spa_core/adapters/)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Константы сети и протокола
# ---------------------------------------------------------------------------
_NETWORK    = "polygon"
_CHAIN_ID   = 137

# Контрактные адреса (только метаданные, реальных вызовов нет)
_POOL_ADDRESS = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"   # Aave V3 Polygon Pool
_USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"   # USDC.e on Polygon (bridged)

# ---------------------------------------------------------------------------
# Газовые параметры L2 vs mainnet
# ---------------------------------------------------------------------------
_GAS_MAINNET_USD    = 0.10    # типичная стоимость газа на Ethereum mainnet
_GAS_L2_USD         = 0.001   # типичная стоимость газа на Polygon (~90% дешевле)
_GAS_SAVINGS_PCT    = 90.0    # экономия gas vs mainnet (%)
_FINALITY_MINUTES   = 2       # мин до finality на Polygon (PoS BFT)
_FINALITY_DAYS_MAINNET = 7    # дней для официального Polygon bridge exit

# ---------------------------------------------------------------------------
# APY и TVL
# ---------------------------------------------------------------------------
_DEFAULT_APY_PCT: float = 5.1           # % (Polygon supply APY; typical range 4.8–5.5%)
_APY_STATUS_KEY   = "aave_v3_polygon"   # ключ в data/adapter_status.json
_TVL_USD          = 800_000_000         # $800M TVL на Polygon

# ---------------------------------------------------------------------------
# Диапазон "здорового" APY
# ---------------------------------------------------------------------------
_APY_HEALTH_MIN: float = 1.0
_APY_HEALTH_MAX: float = 30.0

# ---------------------------------------------------------------------------
# Fallback APY других протоколов для gap-методов
# ---------------------------------------------------------------------------
_MORPHO_APY_FALLBACK: float = 6.5   # Morpho Blue Steakhouse USDC ~6.5%
_AAVE_MAINNET_APY_FALLBACK: float = 4.2  # Aave V3 Ethereum USDC ~4.2%


class AaveV3PolygonAdapter(BaseAdapter):
    """Aave V3 Polygon USDC.e — T1 anchor адаптер на L2 (MP-593).

    Следует паттерну AaveV3OptimismAdapter:
    APY из adapter_status.json (ключ aave_v3_polygon), fallback DEFAULT_APY_PCT=5.1%.
    Peg-gate: USDC hard peg 0.5% (Circle redemption).
    L2-специфичный метод: get_gas_savings_vs_mainnet().
    Polygon-специфичный метод: get_bridge_risk_note() — USDC.e bridge risk.

    USDC.e — bridged USDC через Polygon PoS Bridge (не native Circle USDC).
    RISK_SCORE = 0.27 (выше Optimism 0.25) из-за bridged asset risk.

    Параметры конструктора
    ----------------------
    asset : str
        Торгуемый актив. По умолчанию "USDC".
    data_dir : str | Path | None
        Путь к директории data/. Если None — вычисляется автоматически.

    Атрибуты класса (константы)
    ---------------------------
    PROTOCOL           : "aave_v3_polygon"
    POOL_ADDRESS       : адрес Aave V3 Polygon Pool
    USDC_ADDRESS       : адрес USDC.e на Polygon (bridged)
    CHAIN              : "polygon"
    CHAIN_ID           : 137
    TIER               : "T1"
    T1_CAP             : 0.40  (40% портфеля — стандарт T1)
    RISK_SCORE         : 0.27  (T1 L2; выше 0.25 из-за USDC.e bridge-риска)
    DEFAULT_APY_PCT    : 5.1   (%)
    EXIT_LATENCY_HOURS : 0.0   (мгновенный вывод, same-block)
    TVL_USD            : 800_000_000  (~$800M Polygon USDC.e market)
    PEG_TOLERANCE      : 0.005  (0.5% — USDC hard peg через Circle)
    GAS_SAVINGS_PCT    : 90.0  (% экономии gas vs Ethereum mainnet)
    """

    # ── идентификаторы протокола ─────────────────────────────────────────────
    PROTOCOL      = "aave_v3_polygon"
    PROTOCOL_NAME = "Aave V3 Polygon USDC.e"
    POOL_ADDRESS  = _POOL_ADDRESS
    USDC_ADDRESS  = _USDC_ADDRESS

    # ── сеть ────────────────────────────────────────────────────────────────
    CHAIN    = "polygon"
    CHAIN_ID = 137

    # ── тир и лимиты ────────────────────────────────────────────────────────
    TIER   = "T1"
    T1_CAP = 0.40   # 40% — стандартный лимит T1

    # ── риск-профиль ────────────────────────────────────────────────────────
    RISK_SCORE         = 0.27   # T1 L2; чуть выше Optimism (0.25) из-за USDC.e bridge-риска
    EXIT_LATENCY_HOURS = 0.0    # мгновенный вывод из пула (same-block)

    # ── APY-параметры ────────────────────────────────────────────────────────
    DEFAULT_APY_PCT: float = _DEFAULT_APY_PCT   # fallback 5.1%
    APY_FALLBACK:    float = _DEFAULT_APY_PCT   # backward-compat alias
    MIN_APY_PCT:     float = _APY_HEALTH_MIN    # 1.0%
    MAX_APY_PCT:     float = _APY_HEALTH_MAX    # 30.0%

    # ── TVL ──────────────────────────────────────────────────────────────────
    TVL_USD: float = _TVL_USD   # ~$800M (Polygon USDC.e market)

    # ── peg compliance ───────────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.005   # 0.5% — USDC hard peg (Circle 1:1 redemption)

    # ── L2 газовые параметры ─────────────────────────────────────────────────
    GAS_L2_USD      = _GAS_L2_USD
    GAS_MAINNET_USD = _GAS_MAINNET_USD
    GAS_SAVINGS_PCT = _GAS_SAVINGS_PCT

    # ── стабильный идентификатор для дашбордов ───────────────────────────────
    pool_id = "aave-v3-usdc-e-polygon-t1"

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
        """Читает aave_v3_polygon-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get(_APY_STATUS_KEY, {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("aave_v3_polygon: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из aave_v3_polygon.apy. Возвращает float или None."""
        apy = self._read_status().get("apy")
        if isinstance(apy, (int, float)) and not isinstance(apy, bool):
            return float(apy)
        return None

    def _load_protocol_apy(self, key: str, fallback: float) -> float:
        """Читает APY протокола по ключу из adapter_status.json.

        Используется gap-методами. Возвращает fallback при отсутствии.
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
            logger.debug("aave_v3_polygon: _load_protocol_apy(%s) failed: %s", key, exc)
        return fallback

    # ──────────────────────────────────────────────────────────────────────────
    # Публичный APY API
    # ──────────────────────────────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (5.1, не 0.051).

        Источник: data/adapter_status.json → aave_v3_polygon.apy.
        Fallback: DEFAULT_APY_PCT (5.1%).
        """
        apy = self._read_apy_from_status()
        return apy if apy is not None else self.DEFAULT_APY_PCT

    def get_apy_pct(self) -> float:
        """Синоним get_apy() — APY в процентах (совместимость с BaseAdapter-family)."""
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        YieldInfo.apy — decimal (0.051 для 5.1%); оркестратор умножает на 100.
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

        Читает ``usdc_price`` из aave_v3_polygon-секции status JSON.
        Логика default-safe в сторону healthy:
          - поле отсутствует            → usdc_price = 1.0 → healthy=True
          - поле нечисловое/bool        → usdc_price = 1.0 → healthy=True
          - |usdc_price - 1.0| <= 0.005 → healthy=True  (привязка в норме)
          - |usdc_price - 1.0| >  0.005 → healthy=False (депег обнаружен)

        Примечание: USDC.e на Polygon — bridged USDC. Депег возможен как через
        Circle, так и через риск Polygon PoS Bridge (bridge pause/exploit).
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
    # L2-специфичный метод
    # ──────────────────────────────────────────────────────────────────────────

    def get_gas_savings_vs_mainnet(self) -> dict:
        """Возвращает информацию об экономии газа vs Ethereum mainnet.

        Returns
        -------
        dict
            {savings_pct: 90.0, chain: "polygon", gas_l2_usd: 0.001,
             gas_mainnet_usd: 0.10, finality_minutes: 2,
             mainnet_bridge_exit_days: 7}
        """
        return {
            "savings_pct": self.GAS_SAVINGS_PCT,
            "chain": self.CHAIN,
            "gas_l2_usd": self.GAS_L2_USD,
            "gas_mainnet_usd": self.GAS_MAINNET_USD,
            "finality_minutes": _FINALITY_MINUTES,
            "mainnet_bridge_exit_days": _FINALITY_DAYS_MAINNET,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Polygon-специфичный метод: bridge risk note
    # ──────────────────────────────────────────────────────────────────────────

    def get_bridge_risk_note(self) -> str:
        """Возвращает краткое описание bridge-риска USDC.e на Polygon.

        USDC.e — это bridged USDC (не native Circle USDC). Токен создан через
        Polygon PoS Bridge: Circle's native USDC заблокирован на Ethereum,
        а USDC.e выпущен на Polygon. Это несёт дополнительный bridge-контракт-риск
        и риск паузы bridge (Polygon PoS Bridge может быть приостановлен).

        Note: Polygon планирует миграцию с USDC.e на native USDC (Circle CCTP).
        При миграции позиция в USDC.e потребует ребалансировки.

        Returns
        -------
        str
            Описание USDC.e bridge risk для дашборда / advisory.
        """
        return (
            "USDC.e на Polygon — bridged USDC через Polygon PoS Bridge, не native Circle USDC. "
            "Несёт дополнительный bridge-контракт-риск (Polygon PoS Bridge smart contract) "
            "и риск паузы/эксплойта bridge. RISK_SCORE повышен до 0.27 vs 0.25 для Optimism "
            "(native USDC). Polygon планирует миграцию на native USDC (Circle CCTP): "
            "при миграции USDC.e → native USDC потребуется ребалансировка позиции."
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Paper-trading: simulate_deposit / simulate_withdraw
    # ──────────────────────────────────────────────────────────────────────────

    def simulate_deposit(self, amount_usd: float) -> dict:
        """Симуляция deposit в Aave V3 Polygon USDC.e пул.

        Параметры
        ----------
        amount_usd : float
            Сумма в USD для виртуальной аллокации. Должна быть > 0.

        Возвращает
        ----------
        dict
            Статус операции: status, protocol, amount_usd,
            allocated_total_usd, apy_pct, annual_yield_usd,
            chain, pool_address, ts.

        Исключения
        ----------
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
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "pool_address": self.POOL_ADDRESS,
            "ts": time.time(),
        }

    def simulate_withdraw(self, amount_usd: float) -> dict:
        """Симуляция withdraw из Aave V3 Polygon USDC.e пула.

        Параметры
        ----------
        amount_usd : float
            Сумма в USD. Должна быть > 0.

        Возвращает
        ----------
        dict
            status="ok" при успехе, status="error" + reason если insufficient.

        Исключения
        ----------
        ValueError
            Если amount_usd <= 0.
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
            "chain": self.CHAIN,
            "pool_address": self.POOL_ADDRESS,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "ts": time.time(),
        }

    # ── backward-compat aliases for allocate/withdraw ─────────────────────────

    def allocate(self, capital_usd: float) -> dict:
        """Алиас simulate_deposit для обратной совместимости с orchestrator API."""
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
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "pool_address": self.POOL_ADDRESS,
            "gas_cost_usd": self.GAS_L2_USD,
            "ts": time.time(),
        }

    def withdraw(self, amount_usd: float) -> dict:
        """Виртуальный вывод; raises ValueError при недостатке баланса."""
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
            "chain": self.CHAIN,
            "pool_address": self.POOL_ADDRESS,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "ts": time.time(),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Health
    # ──────────────────────────────────────────────────────────────────────────

    def get_health(self) -> dict:
        """Проверка работоспособности адаптера (без сетевых вызовов).

        Критерий: APY ∈ [MIN_APY_PCT, MAX_APY_PCT] → status "ok", иначе "degraded".
        TVL floor RiskPolicy: ≥ $5M (Polygon $800M — всегда выполнен).

        Возвращает
        ----------
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
            "chain": self.CHAIN,
            "tvl_usd": self.TVL_USD,
            "tvl_floor_ok": self.TVL_USD >= 5_000_000,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "peg_healthy": self.is_peg_healthy(),
            "eligible": self.is_eligible(),
            "allocated_usd": self._allocated,
            "gas_savings_pct": self.GAS_SAVINGS_PCT,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Сериализация
    # ──────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Полное представление адаптера для дашборда и отчётов.

        Возвращает
        ----------
        dict
            Полный снапшот состояния адаптера: сетевые параметры, APY, TVL,
            peg_healthy, eligible, L2-газовые метрики, bridge risk, paper-trading позиция.
        """
        apy_pct = self.get_apy()
        gas_info = self.get_gas_savings_vs_mainnet()
        return {
            "protocol": self.PROTOCOL,
            "protocol_name": self.PROTOCOL_NAME,
            "pool_id": self.pool_id,
            "tier": self.TIER,
            "chain": self.CHAIN,
            "chain_id": self.CHAIN_ID,
            "pool_address": self.POOL_ADDRESS,
            "usdc_address": self.USDC_ADDRESS,
            "asset": self.asset,
            "apy_pct": apy_pct,
            "tvl_usd": self.TVL_USD,
            "risk_score": self.RISK_SCORE,
            "t1_cap": self.T1_CAP,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "peg_tolerance": self.PEG_TOLERANCE,
            "peg_healthy": self.is_peg_healthy(),
            "eligible": self.is_eligible(),
            "l2_advantages": gas_info,
            "bridge_risk_note": self.get_bridge_risk_note(),
            "strategy_note": (
                "Aave V3 Polygon USDC.e supply; instant withdraw (same-block); "
                "T1 anchor; USDC hard-peg gate 0.5%; gas ~90% cheaper vs mainnet; "
                "USDC.e = bridged USDC (bridge risk, RISK_SCORE=0.27)"
            ),
            "allocated_usd": self._allocated,
        }

    # end of class
