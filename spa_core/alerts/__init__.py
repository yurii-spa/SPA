"""SPA alerts package.

MP-015/MP-016: ``telegram_client`` (credentials from macOS Keychain) and
``alert_manager`` (fail-safe formatted alerts for the daily cycle).
Legacy modules (``telegram_sender``, ``alert_dispatcher``, monitors) date
from the GitHub-Actions runtime and read env vars instead.
"""
# Expose telegram_client as a package attribute so that monkeypatching via
# "spa_core.alerts.telegram_client.send_message" resolves correctly in tests.
from . import telegram_client  # noqa: F401
