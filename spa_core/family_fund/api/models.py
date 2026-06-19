"""Pydantic v2 схемы Family Fund API.

Финансовые суммы — `Decimal` (нет float-погрешностей `0.1 + 0.2 != 0.3`).
`model_config = ConfigDict(...)` вместо deprecated `class Config`.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Roles / RBAC ──────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    INVESTOR = "investor"
    READONLY = "readonly"


# Иерархия доступа: чем выше число — тем больше прав.
ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.READONLY: 0,
    UserRole.INVESTOR: 1,
    UserRole.ADMIN: 2,
    UserRole.OWNER: 3,
}


class CurrentUser(BaseModel):
    model_config = ConfigDict(frozen=True)  # immutable — нельзя случайно подменить

    user_id: str
    role: UserRole
    email: Optional[str] = None


# ── Auth ──────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access-token TTL в секундах")
    role: UserRole


# ── Decimal coercion helper ───────────────────────────────────────────────────
def _to_decimal(v: Any) -> Decimal:
    if v is None:
        raise ValueError("value is required")
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Cannot convert {v!r} to Decimal")


def _to_optional_decimal(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    return _to_decimal(v)


# ── Portfolio ─────────────────────────────────────────────────────────────────
class PositionItem(BaseModel):
    """Одна позиция в виртуальном портфеле фонда."""

    model_config = ConfigDict(populate_by_name=True)

    protocol: str = Field(..., min_length=1, max_length=100)
    allocation_usd: Decimal = Field(..., ge=Decimal("0"), le=Decimal("100000000"))
    weight_pct: Decimal = Field(..., ge=Decimal("0"), le=Decimal("100"))
    tier: Optional[str] = Field(default=None, max_length=16)
    apy_pct: Optional[Decimal] = Field(default=None)

    @field_validator("allocation_usd", "weight_pct", mode="before")
    @classmethod
    def _coerce_required(cls, v: Any) -> Decimal:
        return _to_decimal(v)

    @field_validator("apy_pct", mode="before")
    @classmethod
    def _coerce_apy(cls, v: Any) -> Optional[Decimal]:
        return _to_optional_decimal(v)


class PortfolioResponse(BaseModel):
    capital_usd: Decimal = Field(..., ge=Decimal("0"))
    deployed_usd: Decimal = Field(..., ge=Decimal("0"))
    cash_usd: Decimal = Field(..., ge=Decimal("0"))
    current_equity: Decimal = Field(..., ge=Decimal("0"))
    total_return_pct: Decimal
    num_positions: int = Field(..., ge=0)
    positions: list[PositionItem] = Field(default_factory=list)
    is_demo: bool = False
    as_of: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class PositionsResponse(BaseModel):
    positions: list[PositionItem] = Field(default_factory=list)
    total_positions: int = Field(default=0, ge=0)
    deployed_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class PerformanceResponse(BaseModel):
    current_equity: Decimal = Field(..., ge=Decimal("0"))
    total_return_pct: Decimal
    daily_return_pct: Decimal
    apy_today_pct: Decimal
    daily_yield_usd: Decimal
    days_running: int = Field(..., ge=0)
    max_drawdown_pct: Optional[Decimal] = None
    daily_volatility_pct: Optional[Decimal] = None
    best_day: Optional[str] = None
    worst_day: Optional[str] = None
    paper_start_date: Optional[str] = None
    last_cycle_ts: Optional[str] = None


# ── Yield history ─────────────────────────────────────────────────────────────
class AttributionItem(BaseModel):
    protocol: str
    yield_usd: Decimal
    yield_pct: Decimal
    apy: Decimal
    days_active: int = Field(..., ge=0)


class AttributionResponse(BaseModel):
    items: list[AttributionItem] = Field(default_factory=list)
    period_days: int = Field(..., ge=1)
    total_yield_usd: Decimal = Field(default=Decimal("0"))


class YieldDayItem(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    equity_usd: Decimal = Field(..., ge=Decimal("0"))
    daily_yield_usd: Optional[Decimal] = None
    daily_return_pct: Optional[Decimal] = None
    apy_today_pct: Optional[Decimal] = None

    @field_validator("equity_usd", mode="before")
    @classmethod
    def _coerce_equity(cls, v: Any) -> Decimal:
        return _to_decimal(v)

    @field_validator(
        "daily_yield_usd", "daily_return_pct", "apy_today_pct", mode="before"
    )
    @classmethod
    def _coerce_opt(cls, v: Any) -> Optional[Decimal]:
        return _to_optional_decimal(v)


class YieldHistoryResponse(BaseModel):
    days: list[YieldDayItem] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)
    total_yield_usd: Decimal = Field(default=Decimal("0"))
    start_date: Optional[str] = None
    end_date: Optional[str] = None


# ── Health ────────────────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    service: str = "family_fund_api"
    version: str = "1.0.0"


# ── Errors ────────────────────────────────────────────────────────────────────
class ErrorDetail(BaseModel):
    code: str
    message: str
    field: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: Optional[str] = None
