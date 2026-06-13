"""
spa_core/strategies/s15_multichain_l2.py — MP-591 S15 MultiChain L2 Yield

S15 MultiChain L2 Yield Strategy
=================================
Оптимально распределяет USDC по L2 chains (Base, Optimism, Arbitrum),
выбирая лучшие T1/T2 адаптеры с учётом APY и gas savings.
Target APY: 5.5% (скорректирован под реальные L2 условия).

Аллокация по chains (может меняться в зависимости от APY):
  Base (aave_v3_base):      40%  — Aave V3 Base (APY ~5.0%, T2)
  Optimism (aave_v3_opt):   35%  — Aave V3 Optimism (APY ~4.8%, T1)
  Arbitrum (aave_arb):      25%  — Aave V3 Arbitrum (APY ~4.6%, T1)

Weighted APY (дефолт):
  0.40*5.0 + 0.35*4.8 + 0.25*4.6
  = 2.00 + 1.68 + 1.15 = 4.83%

Blended Risk Score:
  0.40*0.35 + 0.35*0.25 + 0.25*0.22
  = 0.140 + 0.0875 + 0.055 = 0.2825 ≈ 0.28

Gas savings summary:
  Base: ~95% savings ($0.005 vs $0.10 mainnet)
  Optimism: ~95% savings ($0.005 vs $0.10 mainnet)
  Arbitrum: ~90% savings ($0.01 vs $0.10 mainnet)
  Avg: ~93.3% savings

Перераспределение при недоступном адаптере (is_eligible=False):
  - Весь вес отдаётся оставшимся eligible адаптерам пропорционально их весам.

Правила:
  - stdlib only, никаких внешних зависимостей
  - Атомарные записи: tmp + os.replace (соблюдается в зависимостях)
  - read-only / advisory — не вызывает execution/ или risk-агентов
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется

ADR: ADR-019 (T2 total cap ≤ 50%), ADR-025 (Base/Arbitrum Phase 2 expansion)

Date: 2026-06-13 (MP-591)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S15"
STRATEGY_NAME = "MultiChain L2 Yield"
TIER          = "T1"   # T1-dominant (Optimism T1 + Arbitrum T1 = 60%), Base T2 = 40%
DESCRIPTION   = (
    "MultiChain L2 Yield: Aave V3 Base 40% (T2, ~5.0% APY, gas 95% cheaper) + "
    "Aave V3 Optimism 35% (T1, ~4.8% APY, gas 95% cheaper) + "
    "Aave V3 Arbitrum 25% (T1, ~4.6% APY, gas 90% cheaper). "
    "Target APY 5.5%, Blended Risk 0.28."
)

# Целевые веса по протоколам (доли 0..1). Сумма = 1.0.
CHAIN_WEIGHTS: Dict[str, float] = {
    "aave_v3_base":    0.40,   # T2, Base chain,     Risk 0.35, APY ~5.0%
    "aave_v3_optimism": 0.35,  # T1, Optimism chain, Risk 0.25, APY ~4.8%
    "aave_arbitrum":   0.25,   # T1, Arbitrum chain, Risk 0.22, APY ~4.6%
}

# Дефолтные годовые APY (%) — fallback при недоступности адаптеров
FALLBACK_APY: Dict[str, float] = {
    "aave_v3_base":     5.0,   # ~5.0% APY Aave V3 Base (Base premium, T2)
    "aave_v3_optimism": 4.8,   # ~4.8% APY Aave V3 Optimism (OP incentive layer + base rate)
    "aave_arbitrum":    4.6,   # ~4.6% APY Aave V3 Arbitrum (Arbitrum premium)
}

# Risk scores по протоколам
RISK_SCORES: Dict[str, float] = {
    "aave_v3_base":     0.35,  # T2, Base chain bridge-риск
    "aave_v3_optimism": 0.25,  # T1, L2 bridge-риск (меньше mainnet T1=0.20)
    "aave_arbitrum":    0.22,  # T1, Arbitrum, наиболее зрелый L2
}

# Информация о газе по цепочкам
GAS_INFO: Dict[str, dict] = {
    "aave_v3_base": {
        "chain":          "base",
        "gas_l2_usd":     0.005,
        "gas_mainnet_usd": 0.10,
        "savings_pct":    95.0,
    },
    "aave_v3_optimism": {
        "chain":          "optimism",
        "gas_l2_usd":     0.005,
        "gas_mainnet_usd": 0.10,
        "savings_pct":    95.0,
    },
    "aave_arbitrum": {
        "chain":          "arbitrum",
        "gas_l2_usd":     0.01,
        "gas_mainnet_usd": 0.10,
        "savings_pct":    90.0,
    },
}

# Ожидаемый взвешенный APY при дефолтных значениях
# 0.40*5.0 + 0.35*4.8 + 0.25*4.6 = 2.00 + 1.68 + 1.15 = 4.83%
WEIGHTED_APY_EXPECTED: float = 4.83

# Взвешенный Risk Score
# 0.40*0.35 + 0.35*0.25 + 0.25*0.22 = 0.14 + 0.0875 + 0.055 = 0.2825
RISK_BLENDED: float = 0.28

# Целевой APY (стратегический ориентир)
TARGET_APY_PCT: float = 5.5

# Диапазон целевого APY (%)
TARGET_APY_MIN: float = 4.0
TARGET_APY_MAX: float = 7.0

# Kill-switch: максимальный drawdown портфеля (%)
MAX_DRAWDOWN_PCT: float = 5.0

# Максимальный размер кольцевого буфера equity_history
_EQUITY_HISTORY_MAX: int = 365


# ─── MultiChainL2Strategy ─────────────────────────────────────────────────────

class MultiChainL2Strategy:
    """S15 — MultiChain L2 Yield Strategy: Base + Optimism + Arbitrum.

    Аллокация: 40% Aave V3 Base (T2, ~5.0% APY),
               35% Aave V3 Optimism (T1, ~4.8% APY),
               25% Aave V3 Arbitrum (T1, ~4.6% APY).
    Weighted APY ≈ 4.83%, Blended Risk ≈ 0.28.
    Gas savings: ~93% среднее vs Ethereum mainnet.

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
        """Инициализировать S15 и загрузить доступные адаптеры."""
        self._adapters: Dict[str, object] = {}
        self._load_adapters()

    # ── Загрузка адаптеров ─────────────────────────────────────────────────────

    def _load_adapters(self) -> None:
        """Загрузить адаптеры из ADAPTER_REGISTRY через try/except.

        Каждый адаптер загружается индивидуально: если ImportError/Exception —
        адаптер пропускается (will use fallback APY/weights).
        """
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
            from spa_core.adapters.aave_arbitrum_adapter import AaveArbitrumAdapter
            self._adapters["aave_arbitrum"] = AaveArbitrumAdapter()
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
            k: w for k, w in CHAIN_WEIGHTS.items()
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
        """Вычислить целевую аллокацию капитала по L2 адаптерам.

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

    def get_health(self) -> dict:
        """Состояние здоровья стратегии S15.

        Returns:
            dict с ключами:
              strategy_id, name, target_apy, expected_apy, risk_score,
              chain_breakdown: {chain_key: {weight, apy, eligible}},
              all_eligible: bool, overall_status: "ok" | "degraded" | "warning"
        """
        chain_breakdown: Dict[str, dict] = {}
        all_eligible = True

        for key in CHAIN_WEIGHTS:
            eligible = self._is_adapter_eligible(key)
            apy = self._get_adapter_apy(key)
            chain_breakdown[key] = {
                "weight": CHAIN_WEIGHTS[key],
                "apy": apy,
                "eligible": eligible,
                "risk_score": RISK_SCORES.get(key, 0.0),
                "gas_savings_pct": GAS_INFO.get(key, {}).get("savings_pct", 0.0),
            }
            if not eligible:
                all_eligible = False

        expected_apy = self.get_expected_apy()

        # Определяем overall_status
        if all_eligible and expected_apy >= TARGET_APY_MIN:
            overall_status = "ok"
        elif expected_apy <= 0.0:
            overall_status = "degraded"
        else:
            overall_status = "warning"

        return {
            "strategy_id":    self.STRATEGY_ID,
            "name":           self.STRATEGY_NAME,
            "tier":           self.TIER,
            "target_apy":     self.TARGET_APY_PCT,
            "expected_apy":   round(expected_apy, 4),
            "risk_score":     self.RISK_SCORE,
            "chain_breakdown": chain_breakdown,
            "all_eligible":   all_eligible,
            "overall_status": overall_status,
        }

    def get_gas_savings_summary(self) -> dict:
        """Средняя экономия на газе vs mainnet для всех L2 адаптеров в стратегии.

        Рассчитывается как средневзвешенная экономия по eligible адаптерам.

        Returns:
            dict с ключами:
              avg_savings_pct, total_estimated_gas_usd_per_tx,
              chains: {chain_key: {savings_pct, gas_l2_usd, chain}}
        """
        weights = self._compute_effective_weights()
        if not weights:
            # Если нет eligible — считаем по всем дефолтным весам
            weights = dict(CHAIN_WEIGHTS)

        total_savings_pct = 0.0
        total_gas_l2_usd = 0.0
        total_w = sum(weights.values())

        chains_detail: Dict[str, dict] = {}
        for key, weight in weights.items():
            gas = GAS_INFO.get(key, {})
            savings = gas.get("savings_pct", 0.0)
            gas_l2 = gas.get("gas_l2_usd", 0.0)
            fraction = weight / total_w if total_w > 0 else 0.0
            total_savings_pct += fraction * savings
            total_gas_l2_usd += fraction * gas_l2
            chains_detail[key] = {
                "savings_pct": savings,
                "gas_l2_usd": gas_l2,
                "chain": gas.get("chain", key),
            }

        return {
            "avg_savings_pct": round(total_savings_pct, 2),
            "total_estimated_gas_usd_per_tx": round(total_gas_l2_usd, 4),
            "chains": chains_detail,
        }

    def simulate(self, capital_usd: float) -> dict:
        """Симуляция распределения капитала по L2 адаптерам.

        Для каждого eligible адаптера вызывает simulate_deposit (если доступно)
        или вычисляет yield аналитически.

        Args:
            capital_usd: начальный капитал в USD.

        Returns:
            dict с ключами:
              total_capital, allocation, expected_annual_yield_usd,
              expected_apy_pct, status, chain_results
        """
        allocation = self.get_allocation(capital_usd)
        if not allocation:
            return {
                "total_capital": capital_usd,
                "allocation": {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct": 0.0,
                "status": "no_eligible_adapters",
                "chain_results": {},
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
                "amount_usd": amount,
                "apy_pct": apy,
                "annual_yield_usd": round(annual_yield, 4),
                "deposit_result": deposit_result,
                "gas_savings_pct": GAS_INFO.get(key, {}).get("savings_pct", 0.0),
            }

        expected_apy = self.get_expected_apy()
        status = "ok" if allocation else "no_eligible_adapters"

        return {
            "total_capital": capital_usd,
            "allocation": allocation,
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct": round(expected_apy, 4),
            "status": status,
            "chain_results": chain_results,
        }

    def to_dict(self) -> dict:
        """Полное представление стратегии для дашборда и отчётов."""
        now_iso = datetime.now(timezone.utc).isoformat()
        health = self.get_health()
        gas_summary = self.get_gas_savings_summary()

        return {
            "strategy_id":     self.STRATEGY_ID,
            "strategy_name":   self.STRATEGY_NAME,
            "tier":            self.TIER,
            "description":     DESCRIPTION,
            "target_apy_pct":  self.TARGET_APY_PCT,
            "expected_apy_pct": health["expected_apy"],
            "risk_score":      self.RISK_SCORE,
            "chain_weights":   dict(CHAIN_WEIGHTS),
            "fallback_apy":    dict(FALLBACK_APY),
            "risk_scores":     dict(RISK_SCORES),
            "all_eligible":    health["all_eligible"],
            "overall_status":  health["overall_status"],
            "gas_savings":     gas_summary,
            "adapters_loaded": list(self._adapters.keys()),
            "timestamp":       now_iso,
        }


# ─── Авто-регистрация в реестре spa_core/strategies/ ─────────────────────────

def _register() -> None:
    """Зарегистрировать S15 MultiChain L2 Yield в глобальном REGISTRY.

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
                "MultiChain L2 Yield: Aave V3 Base 40% (T2, ~5.0% APY, gas 95%), "
                "Aave V3 Optimism 35% (T1, ~4.8% APY, gas 95%), "
                "Aave V3 Arbitrum 25% (T1, ~4.6% APY, gas 90%). "
                "Target APY 5.5%, Blended Risk 0.28. Gas avg ~93% cheaper vs mainnet."
            ),
            module="spa_core.strategies.s15_multichain_l2",
            handler_class="MultiChainL2Strategy",
            tags=["base", "optimism", "arbitrum", "l2", "aave", "multi_chain",
                  "gas_efficient", "t1", "s15"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "MultiChainL2Strategy auto-registration failed: %s", exc
        )


# Регистрация срабатывает при первом импорте модуля
_register()
