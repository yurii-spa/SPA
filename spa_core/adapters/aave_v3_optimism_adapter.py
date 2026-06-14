"""Aave V3 Optimism USDC lending adapter — T1 L2 anchor, read-only/advisory — MP-565.

Конкретный адаптер для Aave V3 USDC-рынка на Optimism (OP Mainnet).
Pool address: 0x794a61358D6845594F94dc1DB02A252b5b4814aD  (Aave V3 Optimism Pool)
USDC address: 0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85  (native USDC на Optimism)

Ключевые характеристики:
- Tier T1 (TVL ~$600M, Risk Score 0.25) — лимит 40% портфеля.
  Aave V3 Optimism — зрелый L2-рынок с batch audits Aave V3 core + OP-specific
  parameters. Ниже риска чем Arbitrum (0.22) нет, но 0.25 отражает бо́льшую
  концентрацию OP-нативного TVL (vs USDC.e на Arbitrum) и меньший абсолютный TVL.
- APY читается из data/adapter_status.json (поле aave_v3_optimism.apy),
  fallback = DEFAULT_APY_PCT (4.8%) при отсутствии / ошибке чтения.
  Optimism USDC supply APY исторически ~4.5–5.0% (OP incentive layer + base rate).
- RISK_SCORE = 0.25 — T1 L2: Aave V3 battle-tested, OP zkEVM-like finality,
  bridge latency 7 дней (через официальный OP bridge, но быстрые выходы через
  Hop/Across/Stargate); ниже mainnet T1 (0.20) из-за bridge-риска.
- Peg-gate: is_peg_healthy() True пока USDC держит привязку к $1.0 —
  отклонение |usdc_price - 1.0| не превышает PEG_TOLERANCE (0.5%).
  Логика default-safe в сторону healthy.
- EXIT_LATENCY_HOURS = 0.0: instant withdraw из Aave V3 Optimism пула
  (same-block, subject to pool utilization).
- L2-преимущество: gas ~95% дешевле mainnet ($0.005 vs $0.10).
  Метод get_gas_savings_vs_mainnet() возвращает {savings_pct: 95.0, chain: "optimism"}.
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
_NETWORK    = "optimism"
_CHAIN_ID   = 10

# Контрактные адреса (только метаданные, реальных вызовов нет)
_POOL_ADDRESS = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"   # Aave V3 Optimism Pool
_USDC_ADDRESS = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"   # Native USDC на Optimism

# ---------------------------------------------------------------------------
# Газовые параметры L2 vs mainnet
# ---------------------------------------------------------------------------
_GAS_MAINNET_USD    = 0.10    # типичная стоимость газа на Ethereum mainnet
_GAS_L2_USD         = 0.005   # типичная стоимость газа на Optimism
_GAS_SAVINGS_PCT    = 95.0    # экономия gas vs mainnet (%)
_FINALITY_MINUTES   = 10      # мин до finality на Optimism (OP sequencer)
_FINALITY_DAYS_MAINNET = 7    # дней для official OP bridge exit

# ---------------------------------------------------------------------------
# APY и TVL
# ---------------------------------------------------------------------------
_DEFAULT_APY_PCT: float = 4.8           # % (Optimism supply APY; +0.6% vs mainnet Aave)
_APY_STATUS_KEY   = "aave_v3_optimism"  # ключ в data/adapter_status.json
_TVL_USD          = 600_000_000         # $600M TVL на Optimism

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


class AaveV3OptimismAdapter(BaseAdapter):
    """Aave V3 Optimism USDC — T1 anchor адаптер на L2 (MP-565).

    Следует паттерну CompoundV3Adapter / AaveArbitrumAdapter:
    APY из adapter_status.json (ключ aave_v3_optimism), fallback DEFAULT_APY_PCT=4.8%.
    Peg-gate: USDC hard peg 0.5% (Circle redemption).
    L2-специфичный метод: get_gas_savings_vs_mainnet().

    Параметры конструктора
    ----------------------
    asset : str
        Торгуемый актив. По умолчанию "USDC".
    data_dir : str | Path | None
        Путь к директории data/. Если None — вычисляется автоматически.

    Атрибуты класса (константы)
    ---------------------------
    PROTOCOL           : "aave_v3_optimism"
    POOL_ADDRESS       : адрес Aave V3 Optimism Pool
    USDC_ADDRESS       : адрес native USDC на Optimism
    CHAIN              : "optimism"
    CHAIN_ID           : 10
    TIER               : "T1"
    T1_CAP             : 0.40  (40% портфеля — стандарт T1)
    RISK_SCORE         : 0.25  (T1 L2; ниже mainnet 0.20 из-за bridge-риска)
    DEFAULT_APY_PCT    : 4.8   (%)
    EXIT_LATENCY_HOURS : 0.0   (мгновенный вывод, same-block)
    TVL_USD            : 600_000_000  (~$600M Optimism USDC market)
    PEG_TOLERANCE      : 0.005  (0.5% — USDC hard peg через Circle)
    GAS_SAVINGS_PCT    : 95.0  (% экономии gas vs Ethereum mainnet)
    """

    # ── идентификаторы протокола ─────────────────────────────────────────────
    PROTOCOL      = "aave_v3_optimism"
    PROTOCOL_NAME = "Aave V3 Optimism USDC"
    POOL_ADDRESS  = _POOL_ADDRESS
    USDC_ADDRESS  = _USDC_ADDRESS

    # ── сеть ────────────────────────────────────────────────────────────────
    CHAIN    = "optimism"
    CHAIN_ID = 10

    # ── тир и лимиты ────────────────────────────────────────────────────────
    TIER   = "T1"
    T1_CAP = 0.40   # 40% — стандартный лимит T1

    # ── риск-профиль ────────────────────────────────────────────────────────
    RISK_SCORE         = 0.25   # T1 L2; чуть выше mainnet (0.20) из-за bridge-риска
    EXIT_LATENCY_HOURS = 0.0    # мгновенный вывод из пула (same-block)

    # ── APY-параметры ────────────────────────────────────────────────────────
    DEFAULT_APY_PCT: float = _DEFAULT_APY_PCT   # fallback 4.8%
    APY_FALLBACK:    float = _DEFAULT_APY_PCT   # backward-compat alias
    MIN_APY_PCT:     float = _APY_HEALTH_MIN    # 1.0%
    MAX_APY_PCT:     float = _APY_HEALTH_MAX    # 30.0%

    # ── TVL ──────────────────────────────────────────────────────────────────
    TVL_USD: float = _TVL_USD   # ~$600M (Optimism USDC market)

    # ── peg compliance ───────────────────────────────────────────────────────
    PEG_TOLERANCE: float = 0.005   # 0.5% — USDC hard peg (Circle 1:1 redemption)

    # ── L2 газовые параметры ─────────────────────────────────────────────────
    GAS_L2_USD      = _GAS_L2_USD
    GAS_MAINNET_USD = _GAS_MAINNET_USD
    GAS_SAVINGS_PCT = _GAS_SAVINGS_PCT

    # ── стабильный идентификатор для дашбордов ───────────────────────────────
    pool_id = "aave-v3-usdc-optimism-t1"

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
        """Читает aave_v3_optimism-секцию из data/adapter_status.json.

        Возвращает dict или {} при любой ошибке. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            result = data.get(_APY_STATUS_KEY, {})
            return result if isinstance(result, dict) else {}
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("aave_v3_optimism: не удалось прочитать status JSON: %s", exc)
        return {}

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из aave_v3_optimism.apy. Возвращает float или None."""
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
            logger.debug("aave_v3_optimism: _load_protocol_apy(%s) failed: %s", key, exc)
        return fallback

    # ──────────────────────────────────────────────────────────────────────────
    # Публичный APY API
    # ──────────────────────────────────────────────────────────────────────────

    def get_apy(self) -> float:
        """Возвращает APY в процентах (4.8, не 0.048).

        Источник: data/adapter_status.json → aave_v3_optimism.apy.
        Fallback: DEFAULT_APY_PCT (4.8%).
        """
        apy = self._read_apy_from_status()
        return apy if apy is not None else self.DEFAULT_APY_PCT

    def get_apy_pct(self) -> float:
        """Синоним get_apy() — APY в процентах (совместимость с BaseAdapter-family)."""
        return self.get_apy()

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        YieldInfo.apy — decimal (0.048 для 4.8%); оркестратор умножает на 100.
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

        Читает ``usdc_price`` из aave_v3_optimism-секции status JSON.
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
    # L2-специфичный метод
    # ──────────────────────────────────────────────────────────────────────────

    def get_gas_savings_vs_mainnet(self) -> dict:
        """Возвращает информацию об экономии газа vs Ethereum mainnet.

        Returns
        -------
        dict
            {savings_pct: 95.0, chain: "optimism", gas_l2_usd: 0.005,
             gas_mainnet_usd: 0.10, finality_minutes: 10,
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
    # Paper-trading: simulate_deposit / simulate_withdraw
    # ──────────────────────────────────────────────────────────────────────────

    def simulate_deposit(self, amount_usd: float) -> dict:
        """Симуляция deposit в Aave V3 Optimism USDC пул.

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
        """Симуляция withdraw из Aave V3 Optimism USDC пула.

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
        TVL floor RiskPolicy: ≥ $5M (Optimism $600M — всегда выполнен).

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
            peg_healthy, eligible, L2-газовые метрики, paper-trading позиция.
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
            "strategy_note": (
                "Aave V3 Optimism USDC supply; instant withdraw (same-block); "
                "T1 anchor; USDC hard-peg gate 0.5%; gas ~95% cheaper vs mainnet"
            ),
            "allocated_usd": self._allocated,
        }

    # end of class
