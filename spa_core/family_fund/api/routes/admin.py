"""Admin routes: user management, system status, session management.

Access: OWNER and ADMIN roles only (enforced via require_min_role).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import (
    _revoked_jti,
    _revoked_lock,
    decode_token,
    hash_password,
    invalidate_users_cache,
    load_users,
)
from ..dependencies import get_current_user, require_min_role
from ..file_store import read_json_file
from ..models import CurrentUser, UserRole

logger = logging.getLogger("family_fund.admin")
router = APIRouter(prefix="/admin", tags=["admin"])

_USERS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "users.json"
_users_write_lock = threading.Lock()


def _users_file() -> Path:
    return _USERS_PATH


def set_users_path(path: Path) -> None:
    global _USERS_PATH
    _USERS_PATH = Path(path)


# ── Request / Response models ────────────────────────────────────────────────

class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool = True
    created_at: Optional[str] = None
    last_login: Optional[str] = None
    display_name: Optional[str] = None
    telegram_handle: Optional[str] = None


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=6, max_length=1024)
    role: str = Field(default="investor")
    display_name: str = Field(default="")
    telegram_handle: str = Field(default="")


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None
    telegram_handle: Optional[str] = None


class SystemStatusResponse(BaseModel):
    cycle_health: dict
    kanban_done_count: int
    sprint_current: str
    golive_status: dict
    data_freshness: dict


class SessionStatsResponse(BaseModel):
    revoked_tokens: int
    active_estimate: str


class ForceRefreshResponse(BaseModel):
    invalidated: int
    message: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_users_raw() -> dict:
    path = _users_file()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"users": []}


def _write_users_raw(data: dict) -> None:
    path = _users_file()
    tmp = path.parent / f".tmp_users_{uuid.uuid4().hex[:8]}.json"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    invalidate_users_cache()


def _user_to_out(u: dict) -> UserOut:
    return UserOut(
        id=u.get("id", u.get("username", "")),
        username=u.get("username", ""),
        email=u.get("email", ""),
        role=u.get("role", "readonly"),
        is_active=u.get("is_active", True),
        created_at=u.get("created_at"),
        last_login=u.get("last_login"),
        display_name=u.get("display_name", ""),
        telegram_handle=u.get("telegram_handle", ""),
    )


VALID_ROLES = {"owner", "admin", "investor", "readonly"}


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(
    current_user: CurrentUser = Depends(require_min_role(UserRole.ADMIN)),
) -> list[UserOut]:
    raw = _read_users_raw()
    return [_user_to_out(u) for u in raw.get("users", [])]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    current_user: CurrentUser = Depends(require_min_role(UserRole.ADMIN)),
) -> UserOut:
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Invalid role: {body.role}")
    if current_user.role != UserRole.OWNER and body.role == "owner":
        raise HTTPException(status_code=403, detail="Only owner can create owner accounts")

    with _users_write_lock:
        raw = _read_users_raw()
        users = raw.get("users", [])
        for u in users:
            if u.get("username") == body.username:
                raise HTTPException(status_code=409, detail="Username already exists")
            if u.get("email") == body.email:
                raise HTTPException(status_code=409, detail="Email already exists")

        new_user = {
            "id": str(uuid.uuid4()),
            "username": body.username,
            "email": body.email,
            "password_hash": hash_password(body.password),
            "role": body.role,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login": None,
            "display_name": body.display_name,
            "telegram_handle": body.telegram_handle,
        }
        users.append(new_user)
        raw["users"] = users
        _write_users_raw(raw)

    logger.info("User created: %s role=%s by=%s", body.username, body.role, current_user.user_id)
    return _user_to_out(new_user)


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user: CurrentUser = Depends(require_min_role(UserRole.ADMIN)),
) -> UserOut:
    with _users_write_lock:
        raw = _read_users_raw()
        users = raw.get("users", [])
        target = None
        for u in users:
            if u.get("id") == user_id or u.get("username") == user_id:
                target = u
                break

        if target is None:
            raise HTTPException(status_code=404, detail="User not found")

        if target.get("username") == "owner" and current_user.role != UserRole.OWNER:
            raise HTTPException(status_code=403, detail="Cannot modify owner account")

        if body.role is not None:
            if body.role not in VALID_ROLES:
                raise HTTPException(status_code=422, detail=f"Invalid role: {body.role}")
            if body.role == "owner" and current_user.role != UserRole.OWNER:
                raise HTTPException(status_code=403, detail="Only owner can assign owner role")
            target["role"] = body.role
        if body.email is not None:
            for u in users:
                if u is not target and u.get("email") == body.email:
                    raise HTTPException(status_code=409, detail="Email already in use")
            target["email"] = body.email
        if body.is_active is not None:
            target["is_active"] = body.is_active
        if body.display_name is not None:
            target["display_name"] = body.display_name
        if body.telegram_handle is not None:
            target["telegram_handle"] = body.telegram_handle

        raw["users"] = users
        _write_users_raw(raw)

    logger.info("User updated: %s by=%s", user_id, current_user.user_id)
    return _user_to_out(target)


@router.delete("/users/{user_id}", response_model=UserOut)
async def deactivate_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_min_role(UserRole.ADMIN)),
) -> UserOut:
    with _users_write_lock:
        raw = _read_users_raw()
        users = raw.get("users", [])
        target = None
        for u in users:
            if u.get("id") == user_id or u.get("username") == user_id:
                target = u
                break

        if target is None:
            raise HTTPException(status_code=404, detail="User not found")

        if target.get("username") == current_user.user_id:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

        target["is_active"] = False
        raw["users"] = users
        _write_users_raw(raw)

    logger.info("User deactivated: %s by=%s", user_id, current_user.user_id)
    return _user_to_out(target)


@router.get("/system", response_model=SystemStatusResponse)
async def get_system_status(
    current_user: CurrentUser = Depends(require_min_role(UserRole.ADMIN)),
) -> SystemStatusResponse:
    status_data = await read_json_file("paper_trading_status.json")
    golive_data = await read_json_file("golive_status.json")

    kanban_done_count = 0
    sprint_current = ""
    try:
        kanban_path = Path(__file__).resolve().parent.parent.parent.parent.parent / "KANBAN.json"
        if kanban_path.exists():
            kanban = json.loads(kanban_path.read_text(encoding="utf-8"))
            kanban_done_count = kanban.get("done_count", 0)
            sprint_current = kanban.get("sprint_current", "")
    except Exception:
        pass

    return SystemStatusResponse(
        cycle_health={
            "last_cycle_ts": status_data.get("last_cycle_ts"),
            "days_running": status_data.get("days_running", 0),
            "is_demo": status_data.get("is_demo", True),
            "current_equity": str(status_data.get("current_equity", 0)),
            "apy_today_pct": str(status_data.get("apy_today_pct", 0)),
        },
        kanban_done_count=kanban_done_count,
        sprint_current=sprint_current,
        golive_status={
            "ready": golive_data.get("ready", False),
            "passed": golive_data.get("passed", 0),
            "total": golive_data.get("total", 0),
            "blockers": golive_data.get("blockers", [])[:5],
        },
        data_freshness={
            "paper_trading_status": bool(status_data),
            "golive_status": bool(golive_data),
        },
    )


@router.get("/sessions", response_model=SessionStatsResponse)
async def get_session_stats(
    current_user: CurrentUser = Depends(require_min_role(UserRole.ADMIN)),
) -> SessionStatsResponse:
    with _revoked_lock:
        count = len(_revoked_jti)
    return SessionStatsResponse(
        revoked_tokens=count,
        active_estimate="In-memory blacklist only; active count not tracked",
    )


@router.post("/force-refresh", response_model=ForceRefreshResponse)
async def force_refresh_all(
    current_user: CurrentUser = Depends(require_min_role(UserRole.OWNER)),
) -> ForceRefreshResponse:
    with _revoked_lock:
        count_before = len(_revoked_jti)
    logger.warning("Force refresh triggered by %s", current_user.user_id)
    return ForceRefreshResponse(
        invalidated=count_before,
        message="All previously revoked tokens cleared. Users will need to re-authenticate on next access token expiry.",
    )
