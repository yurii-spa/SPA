"""Чтение секретов для Family Fund API из macOS Keychain.

JWT secret НИКОГДА не хардкодится. В production он читается из Keychain через
stdlib `subprocess`. В dev/test (или если `security` недоступен) допускается
fallback на переменную окружения `FAMILY_FUND_JWT_SECRET`.

Запись секрета (один раз на машине):
    security add-generic-password -s FAMILY_FUND_JWT_SECRET -a family_fund \\
        -w "<очень-длинный-случайный-секрет>"

Ротация:
    security delete-generic-password -s FAMILY_FUND_JWT_SECRET
    security add-generic-password -s FAMILY_FUND_JWT_SECRET -a family_fund -w '<new>'
    # затем перезапуск API
"""
from __future__ import annotations

import functools
import os
import subprocess

KEYCHAIN_SERVICE = "FAMILY_FUND_JWT_SECRET"
ENV_FALLBACK = "FAMILY_FUND_JWT_SECRET"
MIN_SECRET_LEN = 32


def _read_from_keychain(service: str) -> str | None:
    """Возвращает секрет из Keychain или None, если недоступно."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        # `security` нет (не macOS) или таймаут — переходим к fallback
        return None
    if result.returncode != 0:
        return None
    secret = result.stdout.strip()
    return secret or None


@functools.lru_cache(maxsize=1)
def get_jwt_secret() -> str:
    """Кэшированное чтение JWT-секрета.

    Порядок: Keychain → env var `FAMILY_FUND_JWT_SECRET`.
    lru_cache(maxsize=1) гарантирует один subprocess-вызов на lifetime процесса.

    Raises:
        RuntimeError: секрет не найден нигде.
        ValueError: секрет короче MIN_SECRET_LEN символов.
    """
    secret = _read_from_keychain(KEYCHAIN_SERVICE)
    source = "keychain"
    if secret is None:
        secret = os.environ.get(ENV_FALLBACK)
        source = "env"
    if not secret:
        raise RuntimeError(
            "JWT secret not found. Add it to the Keychain:\n"
            f"  security add-generic-password -s {KEYCHAIN_SERVICE} "
            "-a family_fund -w '<secret>'\n"
            f"or set env var {ENV_FALLBACK} (dev/test only)."
        )
    if len(secret) < MIN_SECRET_LEN:
        raise ValueError(
            f"JWT secret (source={source}) must be at least {MIN_SECRET_LEN} characters"
        )
    return secret


def reset_cache() -> None:
    """Сбрасывает кэш секрета (для тестов и после ротации)."""
    get_jwt_secret.cache_clear()
