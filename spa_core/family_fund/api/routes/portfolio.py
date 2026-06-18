"""Portfolio routes: /portfolio, /portfolio/positions, /portfolio/performance.

Доступ: READONLY и выше (все аутентифицированные роли могут смотреть портфель
фонда). Данные — read-only снимки из data/*.json, которые пишет cycle_runner.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends

from ..dependencies import get_current_user
from ..file_store import read_json_file
from ..models import (
    CurrentUser,
    PerformanceResponse,
    PortfolioResponse,
    PositionItem,
    PositionsResponse,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# Тиры протоколов (из CLAUDE.md / ADAPTER_REGISTRY).
_TIER_MAP: dict[str, str] = {
    "aave_v3": "T1",
    "aave_v3_arbitrum": "T1",
    "compound_v3": "T1",
    "morpho_steakhouse": "T1",
    "morpho_blue": "T2",
    "yearn_v3": "T2",
    "euler_v2": "T2",
    "maple": "T2",
    "pendle_pt_rest": "T3-SPEC",
}


def _positions_to_items(positions: dict[str, Any]) -> tuple[list[PositionItem], Decimal]:
    """Превращает {protocol: usd} в список PositionItem + сумму deployed."""
    items: list[PositionItem] = []
    total = Decimal("0")
    parsed: list[tuple[str, Decimal]] = []
    for protocol, usd in positions.items():
        try:
            amount = Decimal(str(usd))
        except Exception:
            continue
        if amount < 0:
            continue
        parsed.append((protocol, amount))
        total += amount

    for protocol, amount in parsed:
        weight = (amount / total * 100) if total > 0 else Decimal("0")
        items.append(
            PositionItem(
                protocol=protocol,
                allocation_usd=amount,
                weight_pct=weight.quantize(Decimal("0.0001")),
                tier=_TIER_MAP.get(protocol),
            )
        )
    items.sort(key=lambda it: it.allocation_usd, reverse=True)
    return items, total


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


@router.get("", response_model=PortfolioResponse)
async def get_portfolio(
    current_user: CurrentUser = Depends(get_current_user),
) -> PortfolioResponse:
    pos_data = await read_json_file("current_positions.json")
    status_data = await read_json_file("paper_trading_status.json")

    positions = pos_data.get("positions") or status_data.get("current_positions") or {}
    items, deployed = _positions_to_items(positions)

    capital = _dec(pos_data.get("capital_usd", status_data.get("current_equity", 0)))
    deployed_usd = _dec(pos_data.get("deployed_usd", deployed))
    cash = _dec(pos_data.get("cash_usd", capital - deployed_usd))
    if cash < 0:
        cash = Decimal("0")
    equity = _dec(status_data.get("current_equity", capital))

    return PortfolioResponse(
        capital_usd=capital,
        deployed_usd=deployed_usd,
        cash_usd=cash,
        current_equity=equity,
        total_return_pct=_dec(status_data.get("total_return_pct", 0)),
        num_positions=len(items),
        positions=items,
        is_demo=bool(pos_data.get("is_demo", status_data.get("is_demo", False))),
    )


@router.get("/positions", response_model=PositionsResponse)
async def get_positions(
    current_user: CurrentUser = Depends(get_current_user),
) -> PositionsResponse:
    pos_data = await read_json_file("current_positions.json")
    positions = pos_data.get("positions") or {}
    items, deployed = _positions_to_items(positions)
    return PositionsResponse(
        positions=items,
        total_positions=len(items),
        deployed_usd=deployed,
    )


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    current_user: CurrentUser = Depends(get_current_user),
) -> PerformanceResponse:
    status_data = await read_json_file("paper_trading_status.json")
    equity_data = await read_json_file("equity_curve_daily.json")
    summary = equity_data.get("summary", {}) if isinstance(equity_data, dict) else {}

    return PerformanceResponse(
        current_equity=_dec(status_data.get("current_equity", 0)),
        total_return_pct=_dec(status_data.get("total_return_pct", 0)),
        daily_return_pct=_dec(status_data.get("daily_return_pct", 0)),
        apy_today_pct=_dec(status_data.get("apy_today_pct", 0)),
        daily_yield_usd=_dec(status_data.get("daily_yield_usd", 0)),
        days_running=int(status_data.get("days_running", 0) or 0),
        max_drawdown_pct=_dec(summary.get("max_drawdown_pct", 0)),
        daily_volatility_pct=_dec(summary.get("daily_volatility_pct", 0)),
        best_day=summary.get("best_day"),
        worst_day=summary.get("worst_day"),
        paper_start_date=status_data.get("paper_start_date"),
        last_cycle_ts=status_data.get("last_cycle_ts"),
    )
