"""
spa_core/academy/auth/passwords.py

argon2id password hashing — wraps argon2-cffi with project-standard params.

This is the ONLY runtime dependency in the Academy contour that is not stdlib
(argon2-cffi is a deliberate, pinned exception, mirroring the bcrypt exception
in the Family Fund cabinet). The import is LAZY: if argon2-cffi is not
installed, the failure surfaces as a clear RuntimeError with an install hint at
call time, rather than an ImportError at module-import time (so the rest of the
package still imports cleanly in environments that never hash a password).

Project-standard argon2id parameters (OWASP-aligned, 2024):
  time_cost=3, memory_cost=65536 (64 MiB), parallelism=2, hash_len=32,
  salt_len=16.  Changing these later is safe: verify_password reads the
  parameters embedded in the stored PHC string, and needs_rehash() reports
  when a stored hash predates a parameter bump.

LLM FORBIDDEN in this module (auth/security-adjacent).
Academy stage 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from spa_core.utils.errors import SPAError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from argon2 import PasswordHasher


# ── Project-standard argon2id parameters ───────────────────────────────────
TIME_COST = 3
MEMORY_COST = 65536  # 64 MiB
PARALLELISM = 2
HASH_LEN = 32
SALT_LEN = 16

_INSTALL_HINT = (
    "argon2-cffi is required for Academy password hashing but is not "
    'installed. Install it with: pip install "argon2-cffi>=23.1,<25"'
)

# Module-level singleton PasswordHasher, built lazily on first use.
_HASHER = None


def _get_hasher() -> "PasswordHasher":
    """Return a cached argon2 PasswordHasher, importing argon2-cffi lazily.

    Raises:
        RuntimeError: If argon2-cffi is not installed (with an install hint).
    """
    global _HASHER
    if _HASHER is not None:
        return _HASHER
    try:
        from argon2 import PasswordHasher
    except ImportError as exc:  # pragma: no cover - exercised only w/o dep
        raise SPAError(_INSTALL_HINT) from exc
    _HASHER = PasswordHasher(
        time_cost=TIME_COST,
        memory_cost=MEMORY_COST,
        parallelism=PARALLELISM,
        hash_len=HASH_LEN,
        salt_len=SALT_LEN,
    )
    return _HASHER


def hash_password(plain: str) -> str:
    """Hash *plain* with argon2id, returning a self-describing PHC string.

    The returned string embeds the algorithm, parameters, salt and hash, so it
    is fully self-verifying — no separate salt column is needed.
    """
    if not plain:
        raise ValueError("password must not be empty")
    return _get_hasher().hash(plain)


def verify_password(plain: str, hash: str) -> bool:
    """Return True iff *plain* matches the argon2id PHC string *hash*.

    Never raises on a mismatch or a malformed/foreign hash — returns False.
    Uses argon2-cffi's constant-time verification internally.
    """
    if not hash:
        return False
    try:
        from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
    except ImportError as exc:  # pragma: no cover - exercised only w/o dep
        raise SPAError(_INSTALL_HINT) from exc
    hasher = _get_hasher()
    try:
        return hasher.verify(hash, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hash: str) -> bool:
    """Return True if *hash* was produced with older/weaker parameters.

    A True result means the stored hash should be transparently re-hashed with
    the current parameters on the next successful login.
    """
    if not hash:
        return True
    try:
        return _get_hasher().check_needs_rehash(hash)
    except Exception:
        # A hash we cannot even parse is, by definition, one we should replace.
        return True
