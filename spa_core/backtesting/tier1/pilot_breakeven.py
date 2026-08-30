"""Точка безубыточности по капиталу и минимальный размер позиции (ADR-181).

# LLM_FORBIDDEN

Отвечает на два вопроса первого пилота на реальных деньгах:

1. При каком капитале годовой заработок книги покрывает издержки перекладок?
   Издержки распадаются на ФИКСИРОВАННУЮ часть (газ — доллары за ногу, не
   зависят от размера) и ПРОПОРЦИОНАЛЬНУЮ (слиппедж/мост — бп от оборота,
   растут вместе с капиталом). Поэтому безубыточность по капиталу существует
   только против газа; пропорциональная часть задаёт ПОТОЛОК достижимого
   покрытия: издержки никогда не станут меньше, чем slippage-доля заработка,
   сколько бы капитала ни было.

2. Ниже какой позиции ход не окупается за max_payback_days? Газ фиксирован,
   выгода пропорциональна позиции — существует минимальный размер.

Числа газа/слиппеджа/моста — из `cost_model.py`; их происхождение (и что из
них НЕ измерено) — `docs/cost_model_provenance.md`. Доходность книги и
недельный профиль ходов — входы, не константы: они меряются, а не зашиваются.

Чистые функции · stdlib · детерминировано · advisory (money-path не трогает).
"""
from __future__ import annotations

from typing import Optional

from spa_core.backtesting.tier1.cost_model import (
    BRIDGE_BPS,
    GAS_USD_PER_POSITION_CHANGE,
    SLIPPAGE_BPS_STABLE,
)

#: Допущение о газ-лимите одной ноги (депозит/выход lending-протокола).
#: Источник: таблица GAS_LIMITS unified_gas_monitor (aave_deposit 300k,
#: compound 250k, morpho 200k) — само допущение, не замер.
DEFAULT_GAS_LIMIT_PER_LEG: int = 250_000

WEEKS_PER_YEAR: float = 52.0


def leg_gas_usd(gas_price_gwei: float, eth_usd: float,
                gas_limit: int = DEFAULT_GAS_LIMIT_PER_LEG) -> float:
    """USD-стоимость газа одной ноги при данной цене газа и цене ETH."""
    return float(gas_limit) * float(gas_price_gwei) * 1e-9 * float(eth_usd)


def proportional_rate_annual(turnover_frac_week: float,
                             cross_chain: bool = False) -> float:
    """Годовая пропорциональная ставка издержек (доля капитала).

    Слиппедж (и мост при кросс-чейн ходах) берётся от оборота; при недельном
    обороте `turnover_frac_week` капитала это годовая ставка, которая НЕ
    убывает с ростом капитала.
    """
    bps = SLIPPAGE_BPS_STABLE + (BRIDGE_BPS if cross_chain else 0.0)
    return WEEKS_PER_YEAR * float(turnover_frac_week) * bps / 1e4


def breakeven_capital_usd(
    yield_annual_frac: float,
    gas_leg_usd: float,
    legs_per_week: float,
    turnover_frac_week: float,
    coverage: float = 1.0,
    cross_chain: bool = False,
) -> Optional[float]:
    """Капитал, при котором годовой заработок ≥ coverage × годовые издержки.

    None ⇔ недостижимо ни при каком капитале: пропорциональная часть издержек
    с требуемым покрытием съедает всю доходность (coverage × prop ≥ yield).
    Это не сбой расчёта, а честный ответ — таким и возвращается.
    """
    prop = proportional_rate_annual(turnover_frac_week, cross_chain)
    denom = float(yield_annual_frac) - float(coverage) * prop
    if denom <= 0.0:
        return None
    gas_year = WEEKS_PER_YEAR * float(legs_per_week) * float(gas_leg_usd)
    return float(coverage) * gas_year / denom


def min_position_usd(
    gas_leg_usd: float,
    gain_pp: float,
    max_payback_days: float,
    legs: int = 2,
    cross_chain: bool = False,
) -> Optional[float]:
    """Ниже какой позиции ход не окупается за `max_payback_days`.

    Выгода хода — `gain_pp` (пп годовых) на размер позиции; стоимость — газ
    за `legs` ног + пропорциональные бп. None ⇔ ход не окупается НИКОГДА,
    любого размера: пропорциональные бп сами по себе больше, чем выгода
    приносит за отведённые дни (важный случай: мост 5бп + слиппедж 8бп
    против 1пп × 45/365 ≈ 12.3бп — кросс-чейн ход при выгоде 1пп мёртв).
    """
    prop = (SLIPPAGE_BPS_STABLE + (BRIDGE_BPS if cross_chain else 0.0)) / 1e4
    denom = float(gain_pp) / 100.0 * float(max_payback_days) / 365.0 - prop
    if denom <= 0.0:
        return None
    return float(legs) * float(gas_leg_usd) / denom


def model_gas_leg_usd(chain: str) -> float:
    """Газ за ногу по константам модели (происхождение — cost_model_provenance)."""
    table = GAS_USD_PER_POSITION_CHANGE
    return float(table.get(str(chain).lower(), table.get("blended", 1.5)))
