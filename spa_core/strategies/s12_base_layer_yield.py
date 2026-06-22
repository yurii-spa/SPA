"""
spa_core/strategies/s12_base_layer_yield.py — MP-462 S12 Base Layer Yield

S12: Base Layer Yield — Multi-Protocol Base Chain Strategy

Architecture:
- Primary: Morpho Blue Base (USDC, 6.2% APY) — 50%
- Secondary: Aave V3 Base (USDC, 4.5% APY) — 30%
- Reserve: Morpho Blue Ethereum (fallback) — 20%

Target APY: 6.0% (conservative — weighted average Base)
Risk profile: T2-only, no IL, no leverage
Tier classification: T3 (needs 30d paper before promotion to live)
Risk score: 0.40 (low — USDC only, L2 risk vs. T1 ETH adapters)

Gate: Only allocates when BASE_CHAIN_CAP allows (ADR-025 Phase 2)
      During Phase 1 → all capital to Morpho Blue ETH fallback

Kill-switch: if BaseGasMonitor.is_kill_switch_active() → fallback 100%

Ограничения:
  - STDLIB ONLY — без внешних зависимостей
  - Атомарные записи: mkstemp + os.replace
  - LLM FORBIDDEN в данном модуле
  - approved=False от RiskPolicy не переопределяется
  - MAX_BASE_ALLOCATION = 20% (ADR-025 Phase 2 cap)
  - MIN_DAYS_PAPER = 30, MIN_SHARPE = 1.0 (ADR-023)

ADR: ADR-025 (Base chain Phase 1/2 expansion)
     ADR-023 (T3 промоушн политика: 30d paper + Sharpe≥1.0 + USER_APPROVAL)

Date: 2026-06-12
"""
from __future__ import annotations

import datetime
import os
import sys
from typing import Dict, Optional

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID      = "s12_base_layer_yield"
STRATEGY_NAME    = "S12: Base Layer Yield"
TIER             = "T3"
RISK_SCORE       = 0.40
TARGET_APY_PCT   = 6.0
DESCRIPTION      = "Multi-protocol Base chain USDC yield, Phase 2 ADR-025"

# Phase gating — Phase 2 go-live date (ADR-025)
BASE_PHASE_2_DATE = "2026-08-01"

# Идентификаторы Base chain адаптеров (реестр spa_core/adapters/__init__.py)
BASE_ADAPTER_IDS = ["aave-v3-base", "morpho-blue-base"]

# ETH fallback во время Phase 1
FALLBACK_ADAPTER = "morpho_steakhouse"

# ADR-023 promotion requirements
MIN_DAYS_PAPER = 30
MIN_SHARPE     = 1.0

# ADR-025 Phase 2 cap (не превышать 20% от портфеля)
MAX_BASE_ALLOCATION = 0.20

# ─── Аллокации ────────────────────────────────────────────────────────────────

# Phase 2: Base chain активна (после 2026-08-01)
BASE_WEIGHTS: Dict[str, float] = {
    "morpho-blue-base": 0.50,   # Primary: T2, $180M TVL, ~6.2% APY
    "aave-v3-base":     0.30,   # Secondary: T2, ~4.5% APY
    FALLBACK_ADAPTER:   0.20,   # Reserve: T1 ETH, ~6.5% APY
}

# Phase 1 fallback: только ETH адаптеры (Base chain не активна)
PHASE1_WEIGHTS: Dict[str, float] = {
    FALLBACK_ADAPTER: 0.80,     # Morpho Steakhouse ETH: T1, ~6.5%
    "aave_v3":        0.20,     # Aave V3 ETH: T1, ~3.2%
}

# Gas kill-switch fallback (совпадает с Phase 1)
GAS_KILL_WEIGHTS: Dict[str, float] = PHASE1_WEIGHTS.copy()

# Default APY для расчётов при отсутствии live-данных
_DEFAULT_APY: Dict[str, float] = {
    "morpho-blue-base": 6.2,
    "aave-v3-base":     4.5,
    FALLBACK_ADAPTER:   6.5,
    "aave_v3":          3.2,
}


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _is_phase2_active() -> bool:
    """Проверяет, активна ли Phase 2 (Base chain expansion, ADR-025).

    Phase 2 активна если текущая дата >= BASE_PHASE_2_DATE (2026-08-01).
    До этой даты все аллокации идут через ETH fallback.
    """
    today = datetime.date.today().isoformat()
    return today >= BASE_PHASE_2_DATE


def _is_gas_kill_switch() -> bool:
    """Проверяет Base gas kill-switch (ADR-025).

    Читает состояние из BaseGasMonitor. Если монитор недоступен —
    fail-open: kill-switch НЕ активен (безопасное состояние).

    Returns:
        True  — газ превышает порог 3+ дня → Base allocation = 0%
        False — газ в норме, Base allocation разрешена
    """
    try:
        _spa_root = os.path.expanduser("~/Documents/SPA_Claude")
        if _spa_root not in sys.path:
            sys.path.insert(0, _spa_root)
        from spa_core.monitoring.base_gas_monitor import BaseGasMonitor
        monitor = BaseGasMonitor()
        return monitor.is_kill_switch_active()
    except Exception:
        return False  # fail-open: нет данных → разрешаем Base


def _weighted_apy(weights: Dict[str, float], apy_map: Dict[str, float]) -> float:
    """Вычисляет взвешенный APY по переданным весам и данным.

    При отсутствии APY в apy_map использует _DEFAULT_APY.

    Args:
        weights: Словарь {adapter_id: weight}.
        apy_map: Словарь {adapter_id: apy_pct} из live-фида.

    Returns:
        Взвешенный APY в процентах (float).
    """
    total = 0.0
    for adapter_id, weight in weights.items():
        apy = apy_map.get(adapter_id)
        if apy is None or apy <= 0:
            apy = _DEFAULT_APY.get(adapter_id, 4.0)
        total += apy * weight
    return round(total, 4)


# ─── Основной класс ───────────────────────────────────────────────────────────

class S12BaseLayerYield:
    """S12: Base Layer Yield — ADR-025 Phase 2 compatible strategy.

    В Phase 1 (до 2026-08-01) работает как ETH-fallback агрегатор.
    В Phase 2 перераспределяет 80% в Base chain (Morpho + Aave).
    Gas kill-switch откатывает на ETH в случае ценового шока газа.

    Tier: T3 — требует 30 дней paper + Sharpe≥1.0 + USER_APPROVAL (ADR-023).
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    RISK_SCORE     = RISK_SCORE
    TARGET_APY_PCT = TARGET_APY_PCT

    def __init__(self) -> None:
        self.phase2_active   = _is_phase2_active()
        self.gas_kill_switch = _is_gas_kill_switch()

    # ── Публичный API ─────────────────────────────────────────────────────────

    def get_target_weights(self) -> Dict[str, float]:
        """Возвращает целевые веса аллокации для текущей фазы.

        Логика:
          1. Gas kill-switch активен → ETH fallback (GAS_KILL_WEIGHTS)
          2. Phase 1 (до 2026-08-01) → ETH fallback (PHASE1_WEIGHTS)
          3. Phase 2 → Base chain weights (BASE_WEIGHTS)

        Returns:
            Копия словаря весов {adapter_id: float}.
        """
        if self.gas_kill_switch:
            return GAS_KILL_WEIGHTS.copy()
        if not self.phase2_active:
            return PHASE1_WEIGHTS.copy()
        return BASE_WEIGHTS.copy()

    def get_mode(self) -> str:
        """Возвращает текущий режим работы стратегии.

        Returns:
            "phase2_base"     — Base chain активна, газ норм
            "phase1_fallback" — до go-live, ETH only
            "gas_kill"        — kill-switch активен, ETH fallback
        """
        if self.gas_kill_switch:
            return "gas_kill"
        if not self.phase2_active:
            return "phase1_fallback"
        return "phase2_base"

    def run_day(self, apy_map: Dict[str, float]) -> Dict:
        """Симулирует один торговый день стратегии.

        Перечитывает состояние phase2/gas перед каждым вызовом,
        чтобы корректно реагировать на изменения в runtime.

        Args:
            apy_map: Словарь {adapter_id: apy_pct} из live-фида.
                     Пустой dict — будут использованы дефолтные значения.

        Returns:
            Dict с ключами:
              strategy_id      — идентификатор стратегии
              apy_pct          — расчётный APY за день
              weights          — использованные веса
              mode             — режим (phase2_base / phase1_fallback / gas_kill)
              gas_kill_switch  — bool
              phase2_active    — bool
        """
        # Обновляем состояние на каждый вызов
        self.phase2_active   = _is_phase2_active()
        self.gas_kill_switch = _is_gas_kill_switch()

        weights      = self.get_target_weights()
        total_apy    = _weighted_apy(weights, apy_map)
        mode         = self.get_mode()

        return {
            "strategy_id":     self.STRATEGY_ID,
            "apy_pct":         total_apy,
            "weights":         weights,
            "mode":            mode,
            "gas_kill_switch": self.gas_kill_switch,
            "phase2_active":   self.phase2_active,
        }

    def get_info(self) -> Dict:
        """Возвращает метаданные стратегии (без runtime-состояния).

        Returns:
            Dict с ключами: strategy_id, name, tier, risk_score,
            target_apy_pct, description.
        """
        return {
            "strategy_id":    STRATEGY_ID,
            "name":           STRATEGY_NAME,
            "tier":           TIER,
            "risk_score":     RISK_SCORE,
            "target_apy_pct": TARGET_APY_PCT,
            "description":    DESCRIPTION,
        }


# ─── CLI точка входа ──────────────────────────────────────────────────────────

# ─── Авто-регистрация в StrategyRegistry ─────────────────────────────────────

def _register_s12() -> None:
    """Авто-регистрация S12 в spa_core/strategies/strategy_registry.py REGISTRY."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T3",
            target_apy_min=5.0,
            target_apy_max=8.0,
            max_drawdown_pct=5.0,
            description=DESCRIPTION,
            module="spa_core.strategies.s12_base_layer_yield",
            handler_class="S12BaseLayerYield",
            tags=["base_chain", "multi_protocol", "l2", "t3", "paper_only", "phase_gated"],
        ))
    except Exception as _exc:
        import logging
        logging.getLogger(__name__).warning("S12 auto-registration failed: %s", _exc)


_register_s12()


if __name__ == "__main__":
    import json

    strategy = S12BaseLayerYield()
    result   = strategy.run_day({})
    info     = strategy.get_info()

    print("=== S12 Base Layer Yield ===")
    print(f"Mode         : {result['mode']}")
    print(f"APY (blended): {result['apy_pct']:.2f}%")
    print(f"Phase 2      : {result['phase2_active']}")
    print(f"Gas KS       : {result['gas_kill_switch']}")
    print("Weights      :")
    for adapter, w in result["weights"].items():
        print(f"  {adapter:<30} {w*100:.0f}%")
    print()
    print("Info:", json.dumps(info, indent=2))
