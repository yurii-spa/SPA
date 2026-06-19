"""
spa_core/utils/keychain.py
macOS Keychain access for secrets.
"""
import subprocess
from typing import Optional


def get_secret(service: str) -> Optional[str]:
    """
    Retrieves secret from macOS Keychain.
    Returns None (not raises) if unavailable.
    """
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        val = result.stdout.strip()
        return val if val else None
    except Exception:
        return None


def get_github_pat() -> Optional[str]:
    return get_secret("GITHUB_PAT_SPA")


def get_telegram_token() -> Optional[str]:
    return get_secret("TELEGRAM_BOT_TOKEN_SPA")


def get_telegram_chat_id() -> Optional[str]:
    return get_secret("TELEGRAM_CHAT_ID_SPA")
