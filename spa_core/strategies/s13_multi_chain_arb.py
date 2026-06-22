"""
spa_core/strategies/s13_multi_chain_arb.py — S13 Multi-Chain Yield Arbitrage

S13: Multi-Chain Yield Arbitrage — Cross-chain APY spread capture strategy.

Architecture:
- Phase 1 (до 2026-08-01, ADR-025): 100% ETH T1 (aave_v3 40% / compound_v3 30% / morpho_blue 30%)
- Phase 2 (после go-live): если Base APY > ETH APY + SPREAD_THRESHOLD_PCT →
    30% Base chain (aave_v3_base / morpho_blue_base), 70% ETH T1
  иначе: 100% ETH T1

Target APY: 8.5% (Phase 2 cross-chain арбитраж)
Risk profile: T2, no IL, no leverage, ETH+Arbitrum+Base USDC-only
Tier classification: T2

Аллокации по цепям:
  ETH adapters:       aave_v3 (T1), compound_v3 (T1), morpho_blue (T1) — avg ~5–6%
  Arbitrum adapters:  aave_v3_arbitrum (T1)                              — avg ~5.2%
  Base adapters:      aave_v3_base (T2), morpho_blue_base (T2)          — avg ~6–8%

Phase 1 restriction (ADR-025):
  Base allocation всегда 0%; весь капитал — ETH T1 по PHASE1_WEIGHTS.

Spread logic (Phase 2):
  chain_eth_apy  = weighted avg ETH adapters
  chain_base_apy = weighted avg Base adapters
  if chain_base_apy > chain_eth_apy + SPREAD_THRESHOLD_PCT:
      30% Base, 70% ETH
  else:
      100% ETH (fallback)

Ограничения:
  - STDLIB ONLY — без внешних зависимостей
  - Атомарные записи: mkstemp + os.replace
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется
  - BASE_MAX_ALLOCATION = 30% (ADR-025 Phase 2 cap)

ADR: ADR-025 (Base chain Phase 1/2 expansion)

Date: 2026-06-12
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID      = "s13_multi_chain_arb"
STRATEGY_NAME    = "S13 Multi-Chain Yield Arbitrage"
TIER             = "T2"
RISK_SCORE       = 0.45
TARGET_APY_PCT   = 8.5
DESCRIPTION      = "Cross-chain APY spread arbitrage: ETH / Arbitrum / Base USDC"

# Phase gating (ADR-025): Phase 2 = go-live date
PHASE2_DATE      = "2026-08-01"

# Порог спреда Base vs ETH (в процентных пунктах) для активации Base allocation
SPREAD_THRESHOLD_PCT = 1.5

# Максимальная доля Base в Phase 2
BASE_MAX_ALLOCATION = 0.30

# ─── Phase 1 — ETH T1 fallback (100% ETH, Base = 0%) ─────────────────────────

PHASE1_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.40,   # Aave V3 ETH: T1, ~3.5% APY
    "compound_v3": 0.30,   # Compound V3: T1, ~4.8% APY
    "morpho_blue": 0.30,   # Morpho Blue ETH: T1, ~6.5% APY
}

# ─── Phase 2 — ETH portion (при отсутствии спреда или как base) ──────────────

ETH_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.40,
    "compound_v3": 0.30,
    "morpho_blue": 0.30,
}

# ─── Phase 2 — Base chain адаптеры (активны только при достаточном спреде) ───

BASE_WEIGHTS: Dict[str, float] = {
    "aave_v3_base":     0.50,   # Aave V3 Base: T2, ~4.5%
    "morpho_blue_base": 0.50,   # Morpho Blue Base: T2, ~6.2%
}

# ─── Дефолтные APY (используются при отсутствии live-данных) ─────────────────

_DEFAULT_APY: Dict[str, float] = {
    "aave_v3":           3.5,
    "compound_v3":       4.8,
    "morpho_blue":       6.5,
    "aave_v3_arbitrum":  5.2,
    "aave_v3_base":      4.5,
    "morpho_blue_base":  6.2,
}


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _weighted_apy(weights: Dict[str, float], apy_map: Dict[str, float]) -> float:
    """Взвешенный APY по переданным весам и live-данным.

    При отсутствии APY в apy_map использует _DEFAULT_APY.

    Args:
        weights:  Словарь {adapter_id: weight}.
        apy_map:  Словарь {adapter_id: apy_pct} из live-фида.

    Returns:
        Взвешенный APY в процентах (float), округлённый до 4 знаков.
    """
    total = 0.0
    for adapter_id, weight in weights.items():
        apy = apy_map.get(adapter_id)
        if apy is None or apy <= 0:
            apy = _DEFAULT_APY.get(adapter_id, 4.0)
        total += apy * weight
    return round(total, 4)


# ─── Основной класс ───────────────────────────────────────────────────────────

class MultiChainArbStrategy:
    """S13 Multi-Chain Yield Arbitrage — ADR-025 Phase 1/2 compatible.

    В Phase 1 (до 2026-08-01) работает как ETH-T1 агрегатор (100% ETH).
    В Phase 2 сравнивает APY по цепям и при спреде > SPREAD_THRESHOLD_PCT
    аллоцирует до 30% на Base chain.

    Tier: T2 — USDC-only, без IL, без кредитного плеча.
    """

    STRATEGY_ID      = STRATEGY_ID
    STRATEGY_NAME    = STRATEGY_NAME
    TIER             = TIER
    RISK_SCORE       = RISK_SCORE
    TARGET_APY_PCT   = TARGET_APY_PCT

    # ── Публичный API ─────────────────────────────────────────────────────────

    def get_phase(self, date: Optional[str] = None) -> str:
        """Определяет текущую фазу стратегии.

        Args:
            date: ISO-дата 'YYYY-MM-DD'. Если None — используется сегодня.

        Returns:
            "phase1" если date < PHASE2_DATE, иначе "phase2".
        """
        if date is None:
            date = datetime.date.today().isoformat()
        return "phase2" if date >= PHASE2_DATE else "phase1"

    def compute_chain_yields(self, apy_map: Dict[str, float]) -> Dict[str, float]:
        """Вычисляет средневзвешенный APY по каждой цепи.

        Args:
            apy_map: Словарь {adapter_id: apy_pct} из live-фида.

        Returns:
            Словарь {"eth": float, "arb": float, "base": float}
            с взвешенными APY по каждой цепи.
        """
        eth_apy = _weighted_apy(ETH_WEIGHTS, apy_map)

        # Arbitrum: один адаптер, вес = 1.0
        arb_apy = apy_map.get("aave_v3_arbitrum")
        if arb_apy is None or arb_apy <= 0:
            arb_apy = _DEFAULT_APY.get("aave_v3_arbitrum", 5.2)
        arb_apy = round(arb_apy, 4)

        base_apy = _weighted_apy(BASE_WEIGHTS, apy_map)

        return {
            "eth":  eth_apy,
            "arb":  arb_apy,
            "base": base_apy,
        }

    def select_allocation(
        self,
        chain_yields: Dict[str, float],
        phase: str,
    ) -> Dict[str, float]:
        """Выбирает итоговые веса аллокации по результатам chain_yields.

        Phase 1: всегда PHASE1_WEIGHTS (100% ETH T1, Base = 0%).
        Phase 2:
          - Если Base APY > ETH APY + SPREAD_THRESHOLD_PCT →
              Base 30% (BASE_WEIGHTS), ETH 70% (ETH_WEIGHTS)
          - Иначе → 100% ETH (PHASE1_WEIGHTS как fallback)

        Args:
            chain_yields: Результат compute_chain_yields().
            phase:        "phase1" | "phase2"

        Returns:
            Словарь {adapter_id: weight} с суммой весов = 1.0.
        """
        if phase == "phase1":
            return PHASE1_WEIGHTS.copy()

        eth_apy  = chain_yields.get("eth", 0.0)
        base_apy = chain_yields.get("base", 0.0)

        if base_apy > eth_apy + SPREAD_THRESHOLD_PCT:
            # Активируем cross-chain: 30% Base, 70% ETH
            weights: Dict[str, float] = {}
            for adapter, w in BASE_WEIGHTS.items():
                weights[adapter] = round(w * BASE_MAX_ALLOCATION, 6)
            eth_share = 1.0 - BASE_MAX_ALLOCATION
            for adapter, w in ETH_WEIGHTS.items():
                weights[adapter] = round(w * eth_share, 6)
            return weights

        # Спреда нет — 100% ETH T1
        return PHASE1_WEIGHTS.copy()

    def run_day(
        self,
        date: str,
        apy_map: Dict[str, float],
        capital: float,
    ) -> Dict:
        """Симулирует один торговый день стратегии.

        Args:
            date:    ISO-дата 'YYYY-MM-DD' для текущего цикла.
            apy_map: Словарь {adapter_id: apy_pct} из live-фида.
            capital: Виртуальный капитал в USDC (для информации).

        Returns:
            Dict с ключами:
              strategy_id    — идентификатор стратегии
              date           — переданная дата
              phase          — "phase1" | "phase2"
              apy_pct        — взвешенный APY за день
              allocation_pct — аллокация (веса {adapter_id: float})
              chain_spreads  — {"eth": float, "arb": float, "base": float}
              best_chain     — цепь с наивысшим APY ("eth" | "arb" | "base")
              capital        — переданный капитал
        """
        phase         = self.get_phase(date)
        chain_yields  = self.compute_chain_yields(apy_map)
        allocation    = self.select_allocation(chain_yields, phase)
        apy_pct       = _weighted_apy(allocation, apy_map)
        best_chain    = max(chain_yields, key=lambda k: chain_yields[k])

        return {
            "strategy_id":    self.STRATEGY_ID,
            "date":           date,
            "phase":          phase,
            "apy_pct":        apy_pct,
            "allocation_pct": allocation,
            "chain_spreads":  chain_yields,
            "best_chain":     best_chain,
            "capital":        capital,
        }

    def to_dict(self) -> Dict:
        """Возвращает метаданные стратегии.

        Returns:
            Dict с ключами: strategy_id, name, tier, risk_score,
            target_apy_pct, description, phase2_date, spread_threshold_pct,
            base_max_allocation.
        """
        return {
            "strategy_id":          STRATEGY_ID,
            "name":                 STRATEGY_NAME,
            "tier":                 TIER,
            "risk_score":           RISK_SCORE,
            "target_apy_pct":       TARGET_APY_PCT,
            "description":          DESCRIPTION,
            "phase2_date":          PHASE2_DATE,
            "spread_threshold_pct": SPREAD_THRESHOLD_PCT,
            "base_max_allocation":  BASE_MAX_ALLOCATION,
        }


# ─── Авто-регистрация в StrategyRegistry ─────────────────────────────────────

def _register_s13() -> None:
    """Авто-регистрация S13 в spa_core/strategies/strategy_registry.py REGISTRY."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",
            target_apy_min=6.0,
            target_apy_max=11.0,
            max_drawdown_pct=5.0,
            description=DESCRIPTION,
            module="spa_core.strategies.s13_multi_chain_arb",
            handler_class="MultiChainArbStrategy",
            tags=["multi_chain", "arb", "base_chain", "yield_arb", "t2", "phase_gated"],
        ))
    except Exception as _exc:
        import logging
        logging.getLogger(__name__).warning("S13 auto-registration failed: %s", _exc)


_register_s13()


# ─── CLI точка входа ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    strategy = MultiChainArbStrategy()
    today    = datetime.date.today().isoformat()
    result   = strategy.run_day(today, {}, capital=100_000.0)
    info     = strategy.to_dict()

    print("=== S13 Multi-Chain Yield Arbitrage ===")
    print(f"Date         : {result['date']}")
    print(f"Phase        : {result['phase']}")
    print(f"APY (blended): {result['apy_pct']:.2f}%")
    print(f"Best chain   : {result['best_chain']}")
    print(f"Chain yields : {result['chain_spreads']}")
    print("Allocation   :")
    for adapter, w in result["allocation_pct"].items():
        print(f"  {adapter:<30} {w*100:.1f}%")
    print()
    print("Info:", json.dumps(info, indent=2))
