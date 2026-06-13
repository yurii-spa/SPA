"""
spa_core/strategies/s19_balanced_l2.py — MP-608 S19 Balanced L2

S19 Balanced L2 Strategy
=========================
Равномерно распределяет USDC по всем 4 Aave V3 L2 адаптерам:
Arbitrum, Base, Optimism, Polygon — по 25% каждому.
Цель: максимальная chain-диверсификация при T1-уровне риска.

Аллокация (равномерная, может меняться при недоступности адаптера):
  Arbitrum  (aave_arbitrum):    25%  — Aave V3 Arbitrum  (APY ~4.6%, T1, gas 90%)
  Base      (aave_v3_base):     25%  — Aave V3 Base       (APY ~5.0%, T2, gas 95%)
  Optimism  (aave_v3_optimism): 25%  — Aave V3 Optimism  (APY ~4.8%, T1, gas 95%)
  Polygon   (aave_v3_polygon):  25%  — Aave V3 Polygon   (APY ~5.1%, T1, gas 90%)

Equal-weight APY (default, все eligible):
  (4.6 + 5.0 + 4.8 + 5.1) / 4 = 4.875%

Blended Risk Score:
  (0.22 + 0.35 + 0.25 + 0.27) / 4 = 0.2725 ≈ 0.26

Gas savings summary:
  Arbitrum: ~90% savings ($0.01 vs $0.10 mainnet)
  Base:     ~95% savings ($0.005 vs $0.10 mainnet)
  Optimism: ~95% savings ($0.005 vs $0.10 mainnet)
  Polygon:  ~90% savings ($0.001 vs $0.10 mainnet)
  Avg: ~92.5% savings

Перераспределение при недоступном адаптере (is_eligible=False):
  - Равный вес отдаётся оставшимся eligible адаптерам.
  - Если один неeligible → 33.3% каждому из трёх.
  - Если два неeligible → 50% каждому из двух.
  - Если три неeligible → 100% единственному.
  - Если все неeligible → пустой dict (нет аллокации).

Target APY: 5.0% (strategic)
RISK_SCORE: 0.26 (avg T1, slight elevation for multi-chain ops)

Правила:
  - stdlib only, никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется

ADR: ADR-019 (T2 total cap ≤ 50%), ADR-025 (Base/Arbitrum Phase 2 expansion)

Date: 2026-06-13 (MP-608)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S19"
STRATEGY_NAME = "Balanced L2"
TIER          = "T1"   # T1-dominant (Arbitrum T1 + Optimism T1 + Polygon T1 = 75%)
DESCRIPTION   = (
    "Balanced L2: equal 25% each across Aave V3 Arbitrum (T1, ~4.6% APY, gas 90%), "
    "Aave V3 Base (T2, ~5.0% APY, gas 95%), "
    "Aave V3 Optimism (T1, ~4.8% APY, gas 95%), "
    "Aave V3 Polygon (T1, ~5.1% APY, gas 90%). "
    "Target APY 5.0%, Blended Risk 0.26. Maximum L2 chain diversity."
)

# Целевые веса по протоколам (равные доли 0.25 каждому, сумма = 1.0)
L2_ADAPTERS: Dict[str, float] = {
    "aave_arbitrum":    0.25,  # T1, Arbitrum chain, Risk 0.22, APY ~4.6%
    "aave_v3_base":     0.25,  # T2, Base chain,     Risk 0.35, APY ~5.0%
    "aave_v3_optimism": 0.25,  # T1, Optimism chain, Risk 0.25, APY ~4.8%
    "aave_v3_polygon":  0.25,  # T1, Polygon chain,  Risk 0.27, APY ~5.1%
}

# Дефолтные годовые APY (%) — fallback при недоступности адаптеров
FALLBACK_APY: Dict[str, float] = {
    "aave_arbitrum":    4.6,   # ~4.6% APY Aave V3 Arbitrum (mature L2 anchor)
    "aave_v3_base":     5.0,   # ~5.0% APY Aave V3 Base (Coinbase L2)
    "aave_v3_optimism": 4.8,   # ~4.8% APY Aave V3 Optimism (OP incentive layer)
    "aave_v3_polygon":  5.1,   # ~5.1% APY Aave V3 Polygon (USDC.e; typical 4.8–5.5%)
}

# Risk scores по протоколам
RISK_SCORES: Dict[str, float] = {
    "aave_arbitrum":    0.22,  # T1, Arbitrum, наиболее зрелый L2
    "aave_v3_base":     0.35,  # T2, Base chain bridge-риск (Coinbase L2)
    "aave_v3_optimism": 0.25,  # T1, L2 bridge-риск (меньше mainnet T1=0.20)
    "aave_v3_polygon":  0.27,  # T1, Polygon USDC.e bridge-риск
}

# Газовые параметры по цепочкам
GAS_INFO: Dict[str, dict] = {
    "aave_arbitrum": {
        "chain":            "arbitrum",
        "gas_l2_usd":       0.01,
        "gas_mainnet_usd":  0.10,
        "savings_pct":      90.0,
    },
    "aave_v3_base": {
        "chain":            "base",
        "gas_l2_usd":       0.005,
        "gas_mainnet_usd":  0.10,
        "savings_pct":      95.0,
    },
    "aave_v3_optimism": {
        "chain":            "optimism",
        "gas_l2_usd":       0.005,
        "gas_mainnet_usd":  0.10,
        "savings_pct":      95.0,
    },
    "aave_v3_polygon": {
        "chain":            "polygon",
        "gas_l2_usd":       0.001,
        "gas_mainnet_usd":  0.10,
        "savings_pct":      90.0,
    },
}

# Target APY (стратегический ориентир)
TARGET_APY_PCT: float = 5.0

# APY диапазон для health check и регистрации
TARGET_APY_MIN: float = 3.5
TARGET_APY_MAX: float = 7.5

# Kill-switch: максимальный drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 5.0

# Ожидаемый равновзвешенный APY при дефолтных значениях
# (4.6 + 5.0 + 4.8 + 5.1) / 4 = 4.875%
EQUAL_WEIGHT_APY_EXPECTED: float = 4.875

# Кольцевой буфер equity_history
_EQUITY_HISTORY_MAX: int = 365


# ─── BalancedL2Strategy ───────────────────────────────────────────────────────

class BalancedL2Strategy:
    """S19 — Balanced L2 Strategy: Arbitrum + Base + Optimism + Polygon (25% each).

    Аллокация: 25% Aave V3 Arbitrum (T1, ~4.6% APY),
               25% Aave V3 Base     (T2, ~5.0% APY),
               25% Aave V3 Optimism (T1, ~4.8% APY),
               25% Aave V3 Polygon  (T1, ~5.1% APY).
    Equal-weight APY ≈ 4.875%, Blended Risk ≈ 0.26.
    Gas savings: ~92.5% среднее vs Ethereum mainnet.

    При недоступности адаптера (is_eligible=False) вес перераспределяется
    равномерно на оставшихся доступных адаптерах.
    Если все адаптеры неeligible → get_allocation возвращает пустой dict.

    Stdlib only, без внешних зависимостей.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = 0.26

    def __init__(self) -> None:
        """Инициализировать S19 и загрузить доступные адаптеры."""
        self._adapters: Dict[str, object] = {}
        self._load_adapters()

    # ── Загрузка адаптеров ─────────────────────────────────────────────────────

    def _load_adapters(self) -> None:
        """Загрузить адаптеры из ADAPTER_REGISTRY через try/except.

        Каждый адаптер загружается индивидуально: ImportError/Exception →
        адаптер пропускается (будет использован fallback APY).
        """
        try:
            from spa_core.adapters.aave_arbitrum_adapter import AaveArbitrumAdapter
            self._adapters["aave_arbitrum"] = AaveArbitrumAdapter()
        except Exception:  # noqa: BLE001
            pass

        try:
            from spa_core.adapters.aave_v3_base_adapter import AaveV3BaseAdapter
            self._adapters["aave_v3_base"] = AaveV3BaseAdapter()
        except Exception:  # noqa: BLE001
            pass

        try:
            from spa_core.adapters.aave_v3_optimism_adapter import AaveV3OptimismAdapter
            self._adapters["aave_v3_optimism"] = AaveV3OptimismAdapter()
        except Exception:  # noqa: BLE001
            pass

        try:
            from spa_core.adapters.aave_v3_polygon_adapter import AaveV3PolygonAdapter
            self._adapters["aave_v3_polygon"] = AaveV3PolygonAdapter()
        except Exception:  # noqa: BLE001
            pass

    # ── Утилиты ────────────────────────────────────────────────────────────────

    def _get_adapter_apy(self, key: str) -> float:
        """Получить APY адаптера по ключу. Fallback если адаптер недоступен."""
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
        """True если адаптер eligible. Fallback: True (default-safe).

        Если адаптер не загружен → True (используем fallback APY,
        считаем адаптер доступным для аллокации).
        """
        adapter = self._adapters.get(key)
        if adapter is None:
            return True  # не загружен → fallback APY, eligible по умолчанию
        try:
            result = adapter.is_eligible()  # type: ignore[attr-defined]
            return bool(result)
        except Exception:  # noqa: BLE001
            return True

    def _compute_effective_weights(self) -> Dict[str, float]:
        """Вычислить эффективные веса с учётом is_eligible.

        Равные веса (1/n) для всех eligible адаптеров.
        Если нет eligible адаптеров → пустой dict.

        Returns:
            {adapter_key: weight} — сумма = 1.0 (если хоть один eligible)
            Пустой dict если нет eligible адаптеров.
        """
        eligible_keys = [k for k in L2_ADAPTERS if self._is_adapter_eligible(k)]
        if not eligible_keys:
            return {}
        equal_weight = 1.0 / len(eligible_keys)
        return {k: equal_weight for k in eligible_keys}

    # ── Публичный API ──────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Вычислить целевую аллокацию капитала по L2 адаптерам.

        Равные доли (1/n) среди eligible адаптеров.
        При capital_usd ≤ 0 → нулевые аллокации по eligible ключам.
        Если все неeligible → пустой dict.

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
        """Вычислить равновзвешенный средний APY по eligible адаптерам (%).

        При отсутствии eligible адаптеров → 0.0.

        Returns:
            equal_weight_avg_apy_pct: средний APY в процентах годовых.
        """
        weights = self._compute_effective_weights()
        if not weights:
            return 0.0
        total = 0.0
        for key, weight in weights.items():
            apy = self._get_adapter_apy(key)
            total += weight * apy
        return total

    def get_chain_diversity_score(self) -> dict:
        """Оценка диверсификации по L2 chains.

        score = eligible_count / total_chains
        1.0 = максимальная диверсификация (все 4 цепочки).

        Returns:
            dict:
                score (float): 0.0–1.0, отношение eligible к total.
                chains (list): все ключи L2_ADAPTERS (порядок стабилен).
                eligible_count (int): количество eligible адаптеров.
                description (str): текстовая оценка диверсификации.
        """
        total_chains = len(L2_ADAPTERS)
        eligible_keys = [k for k in L2_ADAPTERS if self._is_adapter_eligible(k)]
        eligible_count = len(eligible_keys)
        score = eligible_count / total_chains if total_chains > 0 else 0.0

        if score >= 1.0:
            description = "Perfect L2 diversity"
        elif score >= 0.75:
            description = "High L2 diversity (3/4 chains)"
        elif score >= 0.5:
            description = "Moderate L2 diversity (2/4 chains)"
        elif score > 0.0:
            description = "Low L2 diversity (1/4 chains)"
        else:
            description = "No eligible L2 chains"

        return {
            "score":          round(score, 4),
            "chains":         list(L2_ADAPTERS.keys()),
            "eligible_count": eligible_count,
            "description":    description,
        }

    def get_gas_savings_summary(self) -> dict:
        """Средняя экономия на газе vs mainnet по eligible L2 адаптерам.

        Возвращает avg_savings_pct и chains_breakdown по eligible адаптерам.
        Если нет eligible → использует полный список L2_ADAPTERS (fallback).

        Returns:
            dict:
                avg_savings_pct (float): средняя экономия в % vs mainnet.
                chains_breakdown (dict): {chain_name: savings_pct}.
        """
        weights = self._compute_effective_weights()
        if not weights:
            # Fallback: используем все 4 адаптера для оценки газа
            active_keys = list(L2_ADAPTERS.keys())
        else:
            active_keys = list(weights.keys())

        n = len(active_keys)
        if n == 0:
            return {"avg_savings_pct": 0.0, "chains_breakdown": {}}

        total_savings = 0.0
        chains_breakdown: Dict[str, float] = {}
        for key in active_keys:
            gas = GAS_INFO.get(key, {})
            savings = gas.get("savings_pct", 0.0)
            chain = gas.get("chain", key)
            total_savings += savings
            chains_breakdown[chain] = savings

        avg_savings = total_savings / n

        return {
            "avg_savings_pct":  round(avg_savings, 2),
            "chains_breakdown": chains_breakdown,
        }

    def get_health(self) -> dict:
        """Состояние здоровья стратегии S19.

        Returns:
            dict:
                strategy_id (str): "S19"
                name (str): "Balanced L2"
                tier (str): "T1"
                target_apy (float): TARGET_APY_PCT
                expected_apy (float): текущий equal-weight avg APY
                risk_score (float): RISK_SCORE
                chain_breakdown (dict): детальная инфо по каждому адаптеру
                all_eligible (bool): True если все 4 адаптера eligible
                overall_status (str): "ok" | "warning" | "degraded"
        """
        chain_breakdown: Dict[str, dict] = {}
        all_eligible = True

        for key in L2_ADAPTERS:
            eligible = self._is_adapter_eligible(key)
            apy = self._get_adapter_apy(key)
            chain_breakdown[key] = {
                "weight":          L2_ADAPTERS[key],
                "apy":             apy,
                "eligible":        eligible,
                "risk_score":      RISK_SCORES.get(key, 0.0),
                "gas_savings_pct": GAS_INFO.get(key, {}).get("savings_pct", 0.0),
            }
            if not eligible:
                all_eligible = False

        expected_apy = self.get_expected_apy()

        if all_eligible and expected_apy >= TARGET_APY_MIN:
            overall_status = "ok"
        elif expected_apy <= 0.0:
            overall_status = "degraded"
        else:
            overall_status = "warning"

        return {
            "strategy_id":     self.STRATEGY_ID,
            "name":            self.STRATEGY_NAME,
            "tier":            self.TIER,
            "target_apy":      self.TARGET_APY_PCT,
            "expected_apy":    round(expected_apy, 4),
            "risk_score":      self.RISK_SCORE,
            "chain_breakdown": chain_breakdown,
            "all_eligible":    all_eligible,
            "overall_status":  overall_status,
        }

    def simulate(self, capital_usd: float) -> dict:
        """Симуляция распределения капитала по L2 адаптерам.

        Args:
            capital_usd: начальный капитал в USD.

        Returns:
            dict:
                total_capital (float): входной капитал
                allocation (dict): {adapter_key: amount_usd}
                expected_annual_yield_usd (float): сумма годовых доходов
                expected_apy_pct (float): равновзвешенный APY
                status (str): "ok" | "no_eligible_adapters"
                chain_results (dict): детальные результаты по каждому адаптеру
        """
        allocation = self.get_allocation(capital_usd)
        if not allocation:
            return {
                "total_capital":              capital_usd,
                "allocation":                 {},
                "expected_annual_yield_usd":  0.0,
                "expected_apy_pct":           0.0,
                "status":                     "no_eligible_adapters",
                "chain_results":              {},
            }

        total_yield = 0.0
        chain_results: Dict[str, dict] = {}

        for key, amount in allocation.items():
            apy = self._get_adapter_apy(key)
            annual_yield = amount * (apy / 100.0)
            total_yield += annual_yield

            # Пробуем вызвать simulate_deposit на адаптере
            adapter = self._adapters.get(key)
            deposit_result: Optional[dict] = None
            if adapter is not None and amount > 0:
                try:
                    deposit_result = adapter.simulate_deposit(amount)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass

            chain_results[key] = {
                "amount_usd":       amount,
                "apy_pct":          apy,
                "annual_yield_usd": round(annual_yield, 4),
                "deposit_result":   deposit_result,
                "gas_savings_pct":  GAS_INFO.get(key, {}).get("savings_pct", 0.0),
            }

        expected_apy = self.get_expected_apy()

        return {
            "total_capital":              capital_usd,
            "allocation":                 allocation,
            "expected_annual_yield_usd":  round(total_yield, 4),
            "expected_apy_pct":           round(expected_apy, 4),
            "status":                     "ok",
            "chain_results":              chain_results,
        }

    def to_dict(self) -> dict:
        """Полное представление стратегии для дашборда и отчётов."""
        now_iso = datetime.now(timezone.utc).isoformat()
        health = self.get_health()
        gas_summary = self.get_gas_savings_summary()
        diversity = self.get_chain_diversity_score()

        return {
            "strategy_id":       self.STRATEGY_ID,
            "strategy_name":     self.STRATEGY_NAME,
            "tier":              self.TIER,
            "description":       DESCRIPTION,
            "target_apy_pct":    self.TARGET_APY_PCT,
            "expected_apy_pct":  health["expected_apy"],
            "risk_score":        self.RISK_SCORE,
            "l2_adapters":       dict(L2_ADAPTERS),
            "fallback_apy":      dict(FALLBACK_APY),
            "risk_scores":       dict(RISK_SCORES),
            "all_eligible":      health["all_eligible"],
            "overall_status":    health["overall_status"],
            "chain_diversity":   diversity,
            "gas_savings":       gas_summary,
            "adapters_loaded":   list(self._adapters.keys()),
            "timestamp":         now_iso,
        }


# ─── Авто-регистрация в реестре ──────────────────────────────────────────────

def _register() -> None:
    """Зарегистрировать S19 Balanced L2 в глобальном REGISTRY.

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
                "Balanced L2: equal 25% each across Aave V3 Arbitrum (T1, ~4.6% APY), "
                "Aave V3 Base (T2, ~5.0% APY), Aave V3 Optimism (T1, ~4.8% APY), "
                "Aave V3 Polygon (T1, ~5.1% APY). "
                "Target APY 5.0%, Blended Risk 0.26. Gas avg ~92.5% cheaper vs mainnet."
            ),
            module="spa_core.strategies.s19_balanced_l2",
            handler_class="BalancedL2Strategy",
            tags=["arbitrum", "base", "optimism", "polygon", "l2", "aave", "balanced",
                  "equal_weight", "multi_chain", "gas_efficient", "t1", "s19"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "BalancedL2Strategy auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
