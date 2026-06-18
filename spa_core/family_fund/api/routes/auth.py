"""Auth routes: /auth/login, /auth/refresh, /auth/logout."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from ..auth import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    authenticate,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_user,
    revoke_token,
)
from ..dependencies import oauth2_scheme
from ..models import TokenResponse, UserRole

logger = logging.getLogger("family_fund.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_TTL,
        path="/auth",
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> TokenResponse:
    """OAuth2 password flow. username = username или email."""
    user = authenticate(form_data.username, form_data.password)
    if user is None:
        logger.warning("Auth failed: user=%s", form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role = UserRole(user["role"])
    user_id = user["username"]
    access_token = create_access_token(user_id, role)
    refresh_token = create_refresh_token(user_id)
    _set_refresh_cookie(response, refresh_token)
    logger.info("Login ok: user=%s role=%s", user_id, role.value)
    return TokenResponse(
        access_token=access_token, expires_in=ACCESS_TOKEN_TTL, role=role
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> TokenResponse:
    """Выдаёт новый access-token по refresh-cookie. Ротация refresh-токена."""
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )
    try:
        payload = decode_token(refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong token type",
        )

    user_id = payload["sub"]
    user = get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user",
        )

    role = UserRole(user["role"])
    # ротация: гасим старый refresh, выдаём новую пару
    revoke_token(refresh_token)
    new_access = create_access_token(user_id, role)
    new_refresh = create_refresh_token(user_id)
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=new_access, expires_in=ACCESS_TOKEN_TTL, role=role
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    token: str = Depends(oauth2_scheme),
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> Response:
    """Гасит access- и refresh-токены, удаляет cookie."""
    revoke_token(token)
    if refresh_token:
        revoke_token(refresh_token)
    response.delete_cookie(_REFRESH_COOKIE, path="/auth")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
