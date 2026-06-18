"""Yield routes: /yield/history, /yield/daily.

История строится из equity_curve_daily.json (массив daily[]), а самый свежий
день дополняется/подтверждается из data/daily_report_<date>.json.
Доступ: READONLY и выше.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_current_user
from ..file_store import list_data_files, read_json_file
from ..models import CurrentUser, YieldDayItem, YieldHistoryResponse

router = APIRouter(prefix="/yield", tags=["yield"])


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _day_from_equity(entry: dict) -> YieldDayItem | None:
    date = entry.get("date")
    if not date:
        return None
    equity = entry.get("close_equity", entry.get("equity"))
    if equity is None:
        return None
    return YieldDayItem(
        date=date,
        equity_usd=equity,
        daily_yield_usd=entry.get("daily_yield_usd"),
        daily_return_pct=entry.get("daily_return_pct"),
        apy_today_pct=entry.get("apy_today"),
    )


@router.get("/history", response_model=YieldHistoryResponse)
async def get_yield_history(
    days: int = Query(default=30, ge=1, le=365),
    current_user: CurrentUser = Depends(get_current_user),
) -> YieldHistoryResponse:
    equity_data = await read_json_file("equity_curve_daily.json")
    daily = equity_data.get("daily", []) if isinstance(equity_data, dict) else []

    items: list[YieldDayItem] = []
    for entry in daily:
        if not isinstance(entry, dict):
            continue
        item = _day_from_equity(entry)
        if item is not None:
            items.append(item)

    items.sort(key=lambda it: it.date)
    items = items[-days:]

    total_yield = Decimal("0")
    for it in items:
        if it.daily_yield_usd is not None:
            total_yield += it.daily_yield_usd

    return YieldHistoryResponse(
        days=items,
        count=len(items),
        total_yield_usd=total_yield,
        start_date=items[0].date if items else None,
        end_date=items[-1].date if items else None,
    )


@router.get("/daily", response_model=YieldDayItem)
async def get_yield_daily(
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    current_user: CurrentUser = Depends(get_current_user),
) -> YieldDayItem:
    """Дневной yield за конкретную дату (по умолчанию — последний день).

    Читает data/daily_report_<date>.json; если файла нет — fallback на запись
    из equity_curve_daily.json.
    """
    reports = list_data_files("daily_report_*.json")
    target_file: str | None = None
    if date:
        candidate = f"daily_report_{date}.json"
        if candidate in reports:
            target_file = candidate
    elif reports:
        target_file = reports[-1]  # отсортированы по имени → последняя дата

    if target_file is not None:
        report = await read_json_file(target_file)
        if isinstance(report, dict) and report.get("date"):
            return YieldDayItem(
                date=report["date"],
                equity_usd=report.get("equity_usd", 0),
                daily_yield_usd=report.get("daily_pnl_usd"),
                daily_return_pct=report.get("daily_pnl_pct"),
                apy_today_pct=report.get("apy_today_pct"),
            )

    # Fallback: equity curve
    equity_data = await read_json_file("equity_curve_daily.json")
    daily = equity_data.get("daily", []) if isinstance(equity_data, dict) else []
    chosen = None
    for entry in daily:
        if not isinstance(entry, dict):
            continue
        if date is None or entry.get("date") == date:
            chosen = entry
            if date is not None:
                break
    if chosen is not None:
        item = _day_from_equity(chosen)
        if item is not None:
            return item

    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="No yield data for requested date")
