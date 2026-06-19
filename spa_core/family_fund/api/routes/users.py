"""User profile routes: /users/me (view and update own profile).

Access: any authenticated user.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import invalidate_users_cache
from ..dependencies import get_current_user
from ..models import CurrentUser

logger = logging.getLogger("family_fund.users")
router = APIRouter(prefix="/users", tags=["users"])

_USERS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "users.json"
_write_lock = threading.Lock()


def _users_file() -> Path:
    return _USERS_PATH


def set_users_path(path: Path) -> None:
    global _USERS_PATH
    _USERS_PATH = Path(path)


class UserProfileResponse(BaseModel):
    username: str
    email: str
    role: str
    display_name: str = ""
    telegram_handle: str = ""
    is_active: bool = True
    created_at: Optional[str] = None
    last_login: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=100)
    telegram_handle: Optional[str] = Field(default=None, max_length=100)


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


def _find_user(users: list[dict], user_id: str) -> Optional[dict]:
    for u in users:
        if u.get("username") == user_id or u.get("id") == user_id:
            return u
    return None


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    current_user: CurrentUser = Depends(get_current_user),
) -> UserProfileResponse:
    raw = _read_users_raw()
    user = _find_user(raw.get("users", []), current_user.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserProfileResponse(
        username=user.get("username", ""),
        email=user.get("email", ""),
        role=user.get("role", "readonly"),
        display_name=user.get("display_name", ""),
        telegram_handle=user.get("telegram_handle", ""),
        is_active=user.get("is_active", True),
        created_at=user.get("created_at"),
        last_login=user.get("last_login"),
    )


@router.put("/me", response_model=UserProfileResponse)
async def update_my_profile(
    body: UpdateProfileRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> UserProfileResponse:
    with _write_lock:
        raw = _read_users_raw()
        users = raw.get("users", [])
        user = _find_user(users, current_user.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if body.display_name is not None:
            user["display_name"] = body.display_name
        if body.telegram_handle is not None:
            user["telegram_handle"] = body.telegram_handle

        raw["users"] = users
        _write_users_raw(raw)

    logger.info("Profile updated: %s", current_user.user_id)
    return UserProfileResponse(
        username=user.get("username", ""),
        email=user.get("email", ""),
        role=user.get("role", "readonly"),
        display_name=user.get("display_name", ""),
        telegram_handle=user.get("telegram_handle", ""),
        is_active=user.get("is_active", True),
        created_at=user.get("created_at"),
        last_login=user.get("last_login"),
    )
