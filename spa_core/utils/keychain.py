"""
spa_core/utils/keychain.py — macOS Keychain accessor (stdlib only, LLM FORBIDDEN)

Reads secrets from macOS Keychain using the `security` command-line tool.
No secrets are ever hardcoded; all values are retrieved at runtime via subprocess.

Usage::

    from spa_core.utils.keychain import get_secret
    pat = get_secret("GITHUB_PAT_SPA")   # reads from macOS Keychain

Security model:
  - Uses `security find-generic-password -s <service> -w` via subprocess.
  - Returns None if the secret is not found (never raises).
  - Logs a warning on failure (no secret values in logs).

LLM FORBIDDEN — this module is in the security domain.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Optional

log = logging.getLogger("spa.utils.keychain")

# Known Keychain service names used by SPA
GITHUB_PAT_SPA = "GITHUB_PAT_SPA"
TELEGRAM_BOT_TOKEN = "SPA_TELEGRAM_BOT_TOKEN"


def get_secret(service: str) -> Optional[str]:
    """Read a secret from macOS Keychain by service name.

    Uses ``security find-generic-password -s <service> -w`` via subprocess.
    Returns ``None`` if the secret is missing or retrieval fails.
    Never logs the secret value.

    Args:
        service: Keychain service name (e.g. ``"GITHUB_PAT_SPA"``).

    Returns:
        The secret string, or ``None`` if not found.
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            value = result.stdout.strip()
            if value:
                return value
        log.warning("Keychain: secret '%s' not found (exit %d)", service, result.returncode)
        return None
    except FileNotFoundError:
        log.warning("Keychain: 'security' command not found (non-macOS environment)")
        return None
    except subprocess.TimeoutExpired:
        log.warning("Keychain: timeout reading '%s'", service)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Keychain: unexpected error reading '%s': %s", service, type(exc).__name__)
        return None


def get_github_pat() -> Optional[str]:
    """Convenience wrapper: read GitHub PAT from Keychain.

    Returns the PAT string or ``None`` if not found.
    """
    return get_secret(GITHUB_PAT_SPA)


def require_secret(service: str) -> str:
    """Like ``get_secret`` but raises ``KeyError`` if the secret is absent.

    Args:
        service: Keychain service name.

    Raises:
        KeyError: If the secret cannot be retrieved from Keychain.
    """
    value = get_secret(service)
    if value is None:
        raise KeyError(
            f"Required secret '{service}' not found in macOS Keychain. "
            f"Run: security add-generic-password -s {service} -w <value>"
        )
    return value
