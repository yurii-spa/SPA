"""
spa_core/strategies/s17_polygon_yield.py — MP-599 S17 Polygon Yield

S17 Polygon Yield Strategy
===========================
Специализируется на Polygon L2: низкие gas-комиссии (~$0.001/tx, 90% экономии vs mainnet),
быстрые финализации (~2 мин), mature Aave V3 Polygon USDC.e пул.

Аллокация по ролям:
  Core   (aave_v3_polygon): 60% капитала — T1 anchor, APY ~5.1%, gas 90% cheaper
  Anchor (spark_susds):     25% капитала — T1 stability, APY ~5.5%, L1 diversification
  Boost  (morpho_blue):     15% капитала — T2 yield boost, APY ~7.0%

Weighted APY (дефолт):
  0.60*5.1 + 0.25*5.5 + 0.15*7.0
  = 3.06 + 1.375 + 1.05 = 5.485%

Blended Risk Score:
  0.60*0.27 + 0.25*0.18 + 0.15*0.30
  = 0.162 + 0.045 + 0.045 = 0.252 ≈ 0.25

Gas savings vs mainnet: ~90% (Polygon PoS).
Target APY (стратегический ориентир): 5.8%.

Перераспределение при недоступном адаптере (is_eligible=False):
  - Вес инeligible адаптера перераспределяется пропорционально
    оставшимся eligible адаптерам.
  - Если нет eligible адаптеров — возвращает пустой dict.

Правила:
  - stdlib only, никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется

ADR: ADR-019 (T2 total cap ≤ 50%). T2 в S17 = 15% (morpho_blue) ≤ 50% ✓.
     ADR-002 (go-live transfer rule).

Date: 2026-06-13 (MP-599)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Идентичность стратегии ───────────────────────────────────────────────────

STRATEGY_ID   = "S17"
STRATEGY_NAME = "Polygon Yield"
TIER          = "T1"   # T1-dominant (core 60% T1 + anchor 25% T1 = 85% T1)
DESCRIPTION   = (
    "Polygon Yield: Aave V3 Polygon USDC.e 60% (T1, ~5.1% APY, gas 90% cheaper) + "
    "SparkSUSDS 25% (T1, ~5.5% APY, L1 stability) + "
    "MorphoBlue 15% (T2, ~7.0% APY, yield boost). "
    "Target APY 5.8%, Blended Risk 0.25. Gas ~90% cheaper vs Ethereum mainnet."
)

# ─── Аллокация по ролям ───────────────────────────────────────────────────────
# Ключи соответствуют ADAPTER_REGISTRY в spa_core/adapters/__init__.py.

ALLOCATION: Dict[str, dict] = {
    "core": {
        "adapter": "aave_v3_polygon",   # T1, Polygon L2, USDC.e, APY ~5.1%
        "weight":  0.60,
        "role":    "primary_l2",
        "target_apy": 5.1,
        "tier":    "T1",
    },
    "anchor": {
        "adapter": "spark_susds",        # T1, Ethereum L1, sUSDS, APY ~5.5%
        "weight":  0.25,
        "role":    "stability",
        "target_apy": 5.5,
        "tier":    "T1",
    },
    "boost": {
        "adapter": "morpho_blue",        # T2, Ethereum L1, Morpho Blue, APY ~7.0%
        "weight":  0.15,
        "role":    "yield_boost",
        "target_apy": 7.0,
        "tier":    "T2",
    },
}

# Плоская карта весов (adapter_key → weight) — для cycle_runner и аналитики
ALLOCATION_WEIGHTS: Dict[str, float] = {
    ALLOCATION["core"]["adapter"]:   ALLOCATION["core"]["weight"],
    ALLOCATION["anchor"]["adapter"]: ALLOCATION["anchor"]["weight"],
    ALLOCATION["boost"]["adapter"]:  ALLOCATION["boost"]["weight"],
}

# Дефолтные годовые APY (%) — fallback при недоступности адаптеров
FALLBACK_APY: Dict[str, float] = {
    "aave_v3_polygon": 5.1,   # Aave V3 Polygon USDC.e (~4.8–5.5% исторически)
    "spark_susds":     5.5,   # Spark SparkSUSDS (~5.0–6.0%)
    "morpho_blue":     7.0,   # Morpho Blue curated vaults (~6.0–8.0%)
}

# Risk scores по адаптерам
RISK_SCORES: Dict[str, float] = {
    "aave_v3_polygon": 0.27,  # T1 L2; USDC.e bridge-риск (чуть выше Optimism 0.25)
    "spark_susds":     0.18,  # T1 L1; SparkSUSDS (MakerDAO-backed, very low risk)
    "morpho_blue":     0.30,  # T2 L1; Morpho Blue curated vaults
}

# Ожидаемый взвешенный APY при дефолтных значениях
# 0.60*5.1 + 0.25*5.5 + 0.15*7.0 = 3.06 + 1.375 + 1.05 = 5.485%
WEIGHTED_APY_EXPECTED: float = 5.485

# Взвешенный Risk Score
# 0.60*0.27 + 0.25*0.18 + 0.15*0.30 = 0.162 + 0.045 + 0.045 = 0.252
RISK_BLENDED: float = 0.25

# Целевой APY (стратегический ориентир — с учётом gas savings)
TARGET_APY_PCT: float = 5.8

# Диапазон целевого APY (%)
TARGET_APY_MIN: float = 3.5
TARGET_APY_MAX: float = 9.0

# Kill-switch: максимальный drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 5.0

# Gas savings Polygon vs mainnet
GAS_SAVINGS_PCT: float = 90.0       # % экономии
GAS_L2_USD: float = 0.001           # типичная стоимость tx на Polygon
GAS_MAINNET_USD: float = 0.10       # типичная стоимость tx на Ethereum mainnet
AVG_FINALITY_MINUTES: int = 2       # финализация на Polygon PoS

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX: int = 365


# ─── PolygonYieldStrategy ─────────────────────────────────────────────────────

class PolygonYieldStrategy:
    """S17 — Polygon Yield Strategy: Core 60% (Polygon) + Anchor 25% + Boost 15%.

    Специализируется на Polygon L2 как основном yield-источнике:
    Aave V3 Polygon USDC.e 60% (T1, ~5.1% APY, gas 90% cheaper),
    SparkSUSDS 25% (T1, ~5.5% APY, L1 stability anchor),
    MorphoBlue 15% (T2, ~7.0% APY, yield boost).

    Weighted APY ≈ 5.49%, Target APY 5.8%, Blended Risk ≈ 0.25.

    При недоступности адаптера (is_eligible=False) вес перераспределяется
    пропорционально оставшимся доступным адаптерам.

    Stdlib only, без внешних зависимостей.
    """

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE    = RISK_BLENDED

    def __init__(self) -> None:
        """Инициализировать S17 и загрузить доступные адаптеры."""
        self._adapters: Dict[str, object] = {}
        self._load_adapters()

    # ── Загрузка адаптеров ─────────────────────────────────────────────────────

    def _load_adapters(self) -> None:
        """Загрузить адаптеры из ADAPTER_REGISTRY через try/except.

        Каждый адаптер загружается индивидуально: если ImportError/Exception —
        адаптер пропускается (will use fallback APY/weights).
        """
        try:
            from spa_core.adapters.aave_v3_polygon_adapter import AaveV3PolygonAdapter
            self._adapters["aave_v3_polygon"] = AaveV3PolygonAdapter()
        except Exception:  # noqa: BLE001
            pass

        try:
            from spa_core.adapters.spark_susds_adapter import SparkSusdsAdapter
            self._adapters["spark_susds"] = SparkSusdsAdapter()
        except Exception:  # noqa: BLE001
            pass

        try:
            from spa_core.adapters.morpho_blue import MorphoBlueAdapter
            self._adapters["morpho_blue"] = MorphoBlueAdapter()
        except Exception:  # noqa: BLE001
            pass

    # ── Утилиты ────────────────────────────────────────────────────────────────

    def _get_adapter_apy(self, key: str) -> float:
        """Получить APY адаптера по ключу. Возвращает fallback если адаптер недоступен."""
        adapter = self._adapters.get(key)
        if adapter is None:
            return FALLBACK_APY.get(key, 0.0)
        try:
            apy = adapter.get_apy()  # type: ignore[attr-defined]
            if isinstance(apy, (int, float)) and not isinstance(apy, bool) and apy > 0:
                return float(apy)
        except Exception:  # noqa: BLE001
            pass
        return FALLBACK_APY.get(key, 0.0)

    def _is_adapter_eligible(self, key: str) -> bool:
        """True если адаптер загружен и eligible. Fallback: True (default-safe)."""
        adapter = self._adapters.get(key)
        if adapter is None:
            return True  # не загружен → используем fallback APY, считаем доступным
        try:
            result = adapter.is_eligible()  # type: ignore[attr-defined]
            return bool(result)
        except Exception:  # noqa: BLE001
            return True

    def _compute_effective_weights(self) -> Dict[str, float]:
        """Вычислить эффективные веса с учётом is_eligible адаптеров.

        Если адаптер недоступен (is_eligible=False), его вес перераспределяется
        пропорционально оставшимся eligible адаптерам.

        Returns:
            {adapter_key: effective_weight} — сумма = 1.0 (если хоть один eligible)
            Пустой dict если нет eligible адаптеров.
        """
        eligible = {
            k: w for k, w in ALLOCATION_WEIGHTS.items()
            if self._is_adapter_eligible(k)
        }
        if not eligible:
            return {}
        total_w = sum(eligible.values())
        if total_w <= 0.0:
            return {}
        return {k: w / total_w for k, w in eligible.items()}

    # ── Публичный API ──────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Вычислить целевую аллокацию капитала по ролям.

        При capital_usd ≤ 0 возвращает нулевые аллокации по всем eligible адаптерам.
        Если адаптер is_eligible=False — его вес перераспределяется на остальных.
        Если нет eligible адаптеров — возвращает пустой dict.

        Args:
            capital_usd: сумма в USD для распределения.

        Returns:
            {adapter_key: amount_usd} для eligible адаптеров.
        """
        weights = self._compute_effective_weights()
        if not weights:
            return {}
        if capital_usd <= 0.0:
            return {k: 0.0 for k in weights}
        return {k: w * capital_usd for k, w in weights.items()}

    def get_expected_apy(self) -> float:
        """Вычислить взвешенный средний APY по eligible адаптерам (%).

        При отсутствии eligible адаптеров → 0.0.
        При отсутствии конкретного адаптера → fallback APY из FALLBACK_APY.

        Returns:
            weighted_apy_pct: взвешенный APY в процентах годовых.
        """
        weights = self._compute_effective_weights()
        if not weights:
            return 0.0
        total = 0.0
        for key, weight in weights.items():
            apy = self._get_adapter_apy(key)
            total += weight * apy
        return total

    def get_polygon_advantages(self) -> dict:
        """Polygon L2-преимущества стратегии S17.

        Запрашивает данные у core-адаптера (aave_v3_polygon) если загружен:
        get_gas_savings_vs_mainnet() и get_bridge_risk_note().
        При недоступности адаптера использует константы модуля.

        Returns:
            dict с ключами:
              gas_savings_pct: float — % экономии gas vs mainnet (90.0)
              gas_l2_usd: float — типичная стоимость tx на Polygon ($0.001)
              gas_mainnet_usd: float — типичная стоимость tx на mainnet ($0.10)
              avg_finality_minutes: int — время финализации блока на Polygon
              mainnet_bridge_exit_days: int — дней до official bridge exit
              chain: str — "polygon"
              usdc_note: str — примечание о USDC.e (bridged, не native)
              bridge_risk: str — описание bridge risk от адаптера
        """
        # Дефолтные значения (если адаптер не загружен)
        gas_savings_pct   = GAS_SAVINGS_PCT
        gas_l2_usd        = GAS_L2_USD
        gas_mainnet_usd   = GAS_MAINNET_USD
        finality_minutes  = AVG_FINALITY_MINUTES
        bridge_exit_days  = 7
        chain             = "polygon"
        bridge_risk: str  = (
            "USDC.e на Polygon — bridged USDC через Polygon PoS Bridge. "
            "RISK_SCORE повышен до 0.27 из-за bridge contract risk."
        )

        # Пробуем получить данные у адаптера
        adapter = self._adapters.get("aave_v3_polygon")
        if adapter is not None:
            try:
                gas_info = adapter.get_gas_savings_vs_mainnet()  # type: ignore[attr-defined]
                if isinstance(gas_info, dict):
                    gas_savings_pct  = float(gas_info.get("savings_pct", gas_savings_pct))
                    gas_l2_usd       = float(gas_info.get("gas_l2_usd", gas_l2_usd))
                    gas_mainnet_usd  = float(gas_info.get("gas_mainnet_usd", gas_mainnet_usd))
                    finality_minutes = int(gas_info.get("finality_minutes", finality_minutes))
                    bridge_exit_days = int(gas_info.get("mainnet_bridge_exit_days", bridge_exit_days))
                    chain            = str(gas_info.get("chain", chain))
            except Exception:  # noqa: BLE001
                pass
            try:
                note = adapter.get_bridge_risk_note()  # type: ignore[attr-defined]
                if isinstance(note, str) and note:
                    bridge_risk = note
            except Exception:  # noqa: BLE001
                pass

        usdc_note = (
            "USDC.e — bridged USDC через Polygon PoS Bridge (не native Circle USDC). "
            "Polygon планирует миграцию на native USDC (Circle CCTP)."
        )

        return {
            "gas_savings_pct":        gas_savings_pct,
            "gas_l2_usd":             gas_l2_usd,
            "gas_mainnet_usd":        gas_mainnet_usd,
            "avg_finality_minutes":   finality_minutes,
            "mainnet_bridge_exit_days": bridge_exit_days,
            "chain":                  chain,
            "usdc_note":              usdc_note,
            "bridge_risk":            bridge_risk,
        }

    def get_health(self) -> dict:
        """Состояние здоровья стратегии S17.

        Returns:
            dict с ключами:
              strategy_id, name, target_apy, expected_apy, risk_score,
              chain_breakdown: {adapter_key: {weight, apy, eligible, role, tier}},
              all_eligible: bool, overall_status: "ok" | "degraded" | "warning",
              polygon_core_eligible: bool
        """
        chain_breakdown: Dict[str, dict] = {}
        all_eligible = True
        polygon_core_eligible = True

        for slot, cfg in ALLOCATION.items():
            key = cfg["adapter"]
            eligible = self._is_adapter_eligible(key)
            apy = self._get_adapter_apy(key)
            chain_breakdown[key] = {
                "slot":       slot,
                "role":       cfg["role"],
                "weight":     cfg["weight"],
                "apy":        apy,
                "eligible":   eligible,
                "tier":       cfg["tier"],
                "risk_score": RISK_SCORES.get(key, 0.0),
            }
            if not eligible:
                all_eligible = False
                if key == "aave_v3_polygon":
                    polygon_core_eligible = False

        expected_apy = self.get_expected_apy()

        # overall_status
        if all_eligible and expected_apy >= TARGET_APY_MIN:
            overall_status = "ok"
        elif expected_apy <= 0.0:
            overall_status = "degraded"
        else:
            overall_status = "warning"

        return {
            "strategy_id":            self.STRATEGY_ID,
            "name":                   self.STRATEGY_NAME,
            "tier":                   self.TIER,
            "target_apy":             self.TARGET_APY_PCT,
            "expected_apy":           round(expected_apy, 4),
            "risk_score":             self.RISK_SCORE,
            "chain_breakdown":        chain_breakdown,
            "all_eligible":           all_eligible,
            "polygon_core_eligible":  polygon_core_eligible,
            "overall_status":         overall_status,
            "gas_savings_pct":        GAS_SAVINGS_PCT,
        }

    def simulate(self, capital_usd: float) -> dict:
        """Симуляция распределения капитала по ролям.

        Для каждого eligible адаптера вычисляет yield аналитически
        (simulate_deposit если доступно, иначе APY * amount).

        Args:
            capital_usd: начальный капитал в USD.

        Returns:
            dict с ключами:
              total_capital, allocation, expected_annual_yield_usd,
              expected_apy_pct, status, slot_results
        """
        allocation = self.get_allocation(capital_usd)
        if not allocation:
            return {
                "total_capital": capital_usd,
                "allocation": {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct": 0.0,
                "status": "no_eligible_adapters",
                "slot_results": {},
            }

        total_yield = 0.0
        slot_results: Dict[str, dict] = {}

        for key, amount in allocation.items():
            apy = self._get_adapter_apy(key)
            annual_yield = amount * (apy / 100.0)
            total_yield += annual_yield

            # Пробуем simulate_deposit на адаптере
            adapter = self._adapters.get(key)
            deposit_result: Optional[dict] = None
            if adapter is not None and amount > 0:
                try:
                    deposit_result = adapter.simulate_deposit(amount)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass

            # Ищем role для этого ключа
            role = next(
                (cfg["role"] for cfg in ALLOCATION.values() if cfg["adapter"] == key),
                "unknown"
            )

            slot_results[key] = {
                "role":             role,
                "amount_usd":       amount,
                "apy_pct":          apy,
                "annual_yield_usd": round(annual_yield, 4),
                "deposit_result":   deposit_result,
                "risk_score":       RISK_SCORES.get(key, 0.0),
                "gas_savings_pct":  GAS_SAVINGS_PCT if key == "aave_v3_polygon" else 0.0,
            }

        expected_apy = self.get_expected_apy()
        return {
            "total_capital":             capital_usd,
            "allocation":                allocation,
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          round(expected_apy, 4),
            "status":                    "ok",
            "slot_results":              slot_results,
        }

    def to_dict(self) -> dict:
        """Полное представление стратегии для дашборда и отчётов."""
        now_iso = datetime.now(timezone.utc).isoformat()
        health = self.get_health()
        polygon_adv = self.get_polygon_advantages()

        return {
            "strategy_id":       self.STRATEGY_ID,
            "strategy_name":     self.STRATEGY_NAME,
            "tier":              self.TIER,
            "description":       DESCRIPTION,
            "target_apy_pct":    self.TARGET_APY_PCT,
            "expected_apy_pct":  health["expected_apy"],
            "weighted_apy_expected": WEIGHTED_APY_EXPECTED,
            "risk_score":        self.RISK_SCORE,
            "allocation":        {
                slot: {
                    "adapter":     cfg["adapter"],
                    "weight":      cfg["weight"],
                    "role":        cfg["role"],
                    "target_apy":  cfg["target_apy"],
                    "tier":        cfg["tier"],
                    "fallback_apy": FALLBACK_APY.get(cfg["adapter"], 0.0),
                    "risk_score":  RISK_SCORES.get(cfg["adapter"], 0.0),
                }
                for slot, cfg in ALLOCATION.items()
            },
            "allocation_weights": dict(ALLOCATION_WEIGHTS),
            "fallback_apy":      dict(FALLBACK_APY),
            "risk_scores":       dict(RISK_SCORES),
            "all_eligible":      health["all_eligible"],
            "overall_status":    health["overall_status"],
            "polygon_advantages": polygon_adv,
            "adapters_loaded":   list(self._adapters.keys()),
            "timestamp":         now_iso,
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S17 Polygon Yield в глобальном REGISTRY.

    Вызывается при импорте модуля. Ошибка регистрации не блокирует импорт.
    """
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T1",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "Polygon Yield: Aave V3 Polygon USDC.e 60% (T1, ~5.1% APY, gas 90%), "
                "SparkSUSDS 25% (T1, ~5.5% APY, L1 stability), "
                "MorphoBlue 15% (T2, ~7.0% APY, yield boost). "
                "Target APY 5.8%, Blended Risk 0.25. Gas ~90% cheaper vs mainnet."
            ),
            module="spa_core.strategies.s17_polygon_yield",
            handler_class="PolygonYieldStrategy",
            tags=["polygon", "l2", "aave", "spark", "morpho",
                  "gas_efficient", "t1", "s17", "usdc_e"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "PolygonYieldStrategy auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
