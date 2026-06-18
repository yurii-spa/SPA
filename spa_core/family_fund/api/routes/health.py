"""Health endpoint (публичный — без auth)."""
from __future__ import annotations

import datetime

from fastapi import APIRouter

from ..models import HealthResponse

router = APIRouter(tags=["health"])


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", timestamp=_now_iso())
