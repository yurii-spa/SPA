"""JWT HS256 на stdlib + хеширование паролей + хранилище пользователей.

JWT реализован без PyJWT/python-jose — только hmac, hashlib, base64, json.
Сессии (revoked JTI) — in-memory dict под threading.Lock. Один экземпляр
процесса (Mac Mini), поэтому БД не нужна; blacklist сбрасывается при рестарте.

Пароли: bcrypt (через пакет `bcrypt`), с fallback на hashlib.pbkdf2_hmac если
bcrypt недоступен. Хеши лежат в users.json (хеш — не секрет, пароль — да).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from .keychain import get_jwt_secret
from .models import UserRole

# ── TTL ───────────────────────────────────────────────────────────────────────
ACCESS_TOKEN_TTL = 15 * 60          # 15 минут
REFRESH_TOKEN_TTL = 7 * 24 * 3600   # 7 дней

# ── In-memory revoked JTI blacklist ───────────────────────────────────────────
_revoked_lock = threading.Lock()
_revoked_jti: dict[str, float] = {}  # jti → exp (unix ts)


def _cleanup_expired_revoked() -> None:
    """Чистит просроченные JTI. Вызывается под _revoked_lock."""
    now = time.time()
    for jti in [j for j, exp in _revoked_jti.items() if exp < now]:
        del _revoked_jti[jti]


def clear_revoked() -> None:
    """Полностью очищает blacklist (для тестов)."""
    with _revoked_lock:
        _revoked_jti.clear()


# ── base64url helpers ─────────────────────────────────────────────────────────
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


def _sign(header_b64: str, payload_b64: str, secret: str) -> str:
    msg = f"{header_b64}.{payload_b64}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
    return _b64url_encode(sig)


_HEADER_B64 = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())


def _encode(payload: dict) -> str:
    secret = get_jwt_secret()
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = _sign(_HEADER_B64, payload_b64, secret)
    return f"{_HEADER_B64}.{payload_b64}.{sig}"


# ── Token creation ────────────────────────────────────────────────────────────
def create_access_token(user_id: str, role: UserRole) -> str:
    """Access-token (HS256, 15 мин)."""
    now = int(time.time())
    return _encode({
        "sub": user_id,
        "role": role.value if isinstance(role, UserRole) else str(role),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "type": "access",
    })


def create_refresh_token(user_id: str) -> str:
    """Refresh-token (HS256, 7 дней). Роль не включается."""
    now = int(time.time())
    return _encode({
        "sub": user_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + REFRESH_TOKEN_TTL,
        "type": "refresh",
    })


def decode_token(token: str) -> dict:
    """Декодирует и проверяет JWT.

    Raises:
        ValueError: при любой ошибке (формат, подпись, истечение, revoked).
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed token")

    header_b64, payload_b64, sig_b64 = parts
    secret = get_jwt_secret()

    expected_sig = _sign(header_b64, payload_b64, secret)
    if not hmac.compare_digest(expected_sig, sig_b64):
        raise ValueError("Invalid signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        raise ValueError("Malformed payload")
    if not isinstance(payload, dict):
        raise ValueError("Malformed payload")

    if float(payload.get("exp", 0)) < time.time():
        raise ValueError("Token expired")

    jti = payload.get("jti", "")
    with _revoked_lock:
        if jti in _revoked_jti:
            raise ValueError("Token revoked")

    return payload


def revoke_token(token: str) -> None:
    """Добавляет JTI токена в blacklist (logout). Невалидный токен игнорируется."""
    try:
        payload = decode_token(token)
    except ValueError:
        return
    jti = payload.get("jti", "")
    exp = float(payload.get("exp", 0.0))
    with _revoked_lock:
        _revoked_jti[jti] = exp
        _cleanup_expired_revoked()


# ── Password hashing (bcrypt с pbkdf2 fallback) ───────────────────────────────
try:  # pragma: no cover - зависит от окружения
    import bcrypt as _bcrypt

    _HAS_BCRYPT = True
except ImportError:  # pragma: no cover
    _bcrypt = None
    _HAS_BCRYPT = False

_PBKDF2_ROUNDS = 260_000
_PBKDF2_PREFIX = "pbkdf2_sha256$"


def hash_password(password: str) -> str:
    """Хеширует пароль. bcrypt если доступен, иначе pbkdf2_hmac (с префиксом)."""
    if _HAS_BCRYPT:
        return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    salt = base64.b16encode(uuid.uuid4().bytes).decode()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS
    ).hex()
    return f"{_PBKDF2_PREFIX}{_PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Проверяет пароль против хеша. Поддерживает оба формата."""
    if not stored_hash:
        return False
    if stored_hash.startswith(_PBKDF2_PREFIX):
        try:
            _, rounds_s, salt, digest = stored_hash.split("$", 3)
            rounds = int(rounds_s)
        except (ValueError, TypeError):
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), rounds
        ).hex()
        return hmac.compare_digest(candidate, digest)
    # bcrypt-хеш
    if not _HAS_BCRYPT:
        return False
    try:
        return _bcrypt.checkpw(password.encode(), stored_hash.encode())
    except (ValueError, TypeError):
        return False


# ── User store (users.json) ───────────────────────────────────────────────────
# Путь по умолчанию: spa_core/family_fund/users.json
_USERS_PATH = Path(__file__).resolve().parent.parent / "users.json"
_users_lock = threading.Lock()
_users_cache: Optional[dict[str, dict]] = None


def _users_file() -> Path:
    return _USERS_PATH


def load_users(force: bool = False) -> dict[str, dict]:
    """Загружает реестр пользователей из users.json (с кэшем).

    Структура файла:
        {"users": [{"username", "email", "role", "password_hash"}, ...]}

    Возвращает dict, индексированный по username И по email (для гибкого логина).
    """
    global _users_cache
    with _users_lock:
        if _users_cache is not None and not force:
            return _users_cache
        path = _users_file()
        index: dict[str, dict] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _users_cache = index
            return index
        for entry in raw.get("users", []):
            username = entry.get("username", "")
            email = entry.get("email", "")
            record = {
                "username": username,
                "email": email,
                "role": entry.get("role", UserRole.READONLY.value),
                "password_hash": entry.get("password_hash", ""),
            }
            if username:
                index[username] = record
            if email:
                index[email] = record
        _users_cache = index
        return index


def invalidate_users_cache() -> None:
    """Сбрасывает кэш пользователей (тесты / после правки users.json)."""
    global _users_cache
    with _users_lock:
        _users_cache = None


def set_users_path(path: Path) -> None:
    """Переопределяет путь к users.json (используется в тестах)."""
    global _USERS_PATH
    _USERS_PATH = Path(path)
    invalidate_users_cache()


def get_user(identifier: str) -> Optional[dict]:
    """Возвращает запись пользователя по username или email, либо None."""
    return load_users().get(identifier)


def authenticate(identifier: str, password: str) -> Optional[dict]:
    """Проверяет креды. Возвращает запись пользователя или None.

    Время verify тратится даже для несуществующего пользователя (защита от
    user-enumeration по таймингу).
    """
    user = get_user(identifier)
    if user is None:
        # выполняем фиктивную проверку, чтобы выровнять тайминг
        verify_password(password, hash_password("dummy-timing-guard"))
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user
