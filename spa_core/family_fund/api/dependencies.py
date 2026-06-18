"""FastAPI dependencies: get_current_user, require_role, require_min_role."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from .auth import decode_token
from .models import ROLE_HIERARCHY, CurrentUser, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=True)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """Извлекает и валидирует access-токен."""
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        role = UserRole(payload["role"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid role claim",
        )

    return CurrentUser(user_id=payload["sub"], role=role)


def require_role(*allowed_roles: UserRole):
    """Dependency-фабрика: разрешает только перечисленные роли (по иерархии ≥)."""
    if not allowed_roles:
        raise ValueError("require_role needs at least one role")
    min_level = min(ROLE_HIERARCHY[r] for r in allowed_roles)

    async def checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        user_level = ROLE_HIERARCHY.get(current_user.role, -1)
        if user_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Access denied. Required role >= "
                    + min(allowed_roles, key=lambda r: ROLE_HIERARCHY[r]).value
                ),
            )
        return current_user

    return checker


def require_min_role(min_role: UserRole):
    """Удобный алиас: роль пользователя должна быть >= min_role."""
    return require_role(min_role)
