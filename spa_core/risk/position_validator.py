"""
spa_core/risk/position_validator.py — Position Validator (LaunchAgent-compatible)

Читает current_positions.json, проверяет все правила политики,
пишет data/policy_violations.json, отправляет Telegram алерт при нарушениях.
Exit code 1 если есть нарушения, 0 если всё ОК.

LLM_FORBIDDEN: только детерминированные проверки.

Использование:
    python3 -m spa_core.risk.position_validator          # проверить + записать
    python3 -m spa_core.risk.position_validator --check  # проверить без записи
    python3 -m spa_core.risk.position_validator --quiet  # без вывода на stdout
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.risk.position_validator")

_REPO = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO / "data"
_POSITIONS_PATH = _DATA_DIR / "current_positions.json"
_ADAPTER_STATUS_PATH = _DATA_DIR / "adapter_status.json"
_VIOLATIONS_PATH = _DATA_DIR / "policy_violations.json"

# Ring-buffer cap for violations history
_VIOLATIONS_CAP = 200
_HTTP_TIMEOUT = 10


# ── Keychain helpers (stdlib only, same pattern as bot.py) ─────────────────

def _read_keychain(service: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            return val if val else None
    except Exception:
        pass
    return None


def _get_telegram_creds() -> tuple:
    """Returns (token, chat_id) from Keychain or env vars."""
    token = _read_keychain("TELEGRAM_BOT_TOKEN_SPA") or os.environ.get(
        "TELEGRAM_BOT_TOKEN_SPA"
    ) or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = _read_keychain("TELEGRAM_CHAT_ID_SPA") or os.environ.get(
        "TELEGRAM_CHAT_ID_SPA"
    ) or os.environ.get("TELEGRAM_CHAT_ID")
    return token, chat_id


def _send_telegram(message: str) -> bool:
    """RETIRED as a Telegram push (Phase-1 Telegram rebuild).

    Position-validation findings are advisory (the RiskPolicy gate is the
    enforcement); routed to the digest queue, never pushed. Always returns
    False. Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy.enqueue_digest(
            "position_validator", "Position validation", message,
            severity="WARNING", reason="position_validator_retired_push",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("position_validator: digest route failed: %s", e)
    return False


def _atomic_write_json(path: Path, data: object) -> None:
    """Atomic write, delegated to the canonical ``atomic_save`` (P3-9).

    Byte-identical: both use ``json.dump(..., indent=2, default=str)``.
    """
    atomic_save(data, str(path))


def _load_violations_history() -> list:
    """Load existing violations ring-buffer."""
    try:
        with open(_VIOLATIONS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def run_validation_check(
    write: bool = True,
    quiet: bool = False,
    send_alert: bool = True,
) -> int:
    """Run full policy validation on current_positions.json.

    Args:
        write:      If True, write results to data/policy_violations.json.
        quiet:      If True, suppress stdout output.
        send_alert: If True, send Telegram alert on violations.

    Returns:
        0 if portfolio is valid, 1 if violations found.
    """
    from spa_core.risk.policy_enforcer import (
        validate_positions_from_file,
        format_violations_text,
    )

    ts = datetime.now(timezone.utc).isoformat()

    result = validate_positions_from_file(
        str(_POSITIONS_PATH),
        str(_ADAPTER_STATUS_PATH),
    )

    text = format_violations_text(result)
    if not quiet:
        print(text)

    if write:
        # Build violation record
        record = {
            "checked_at": ts,
            "passed": result.passed,
            "violation_count": len(result.violations),
            "warning_count": len(result.warnings),
            "violations": [v.to_dict() for v in result.violations],
            "warnings": [v.to_dict() for v in result.warnings],
            "portfolio_summary": result.portfolio_summary,
        }

        # Append to ring-buffer
        history = _load_violations_history()
        history.append(record)
        if len(history) > _VIOLATIONS_CAP:
            history = history[-_VIOLATIONS_CAP:]

        try:
            _atomic_write_json(_VIOLATIONS_PATH, history)
            log.info("Wrote policy_violations.json (%d records)", len(history))
        except Exception as e:
            log.error("Failed to write policy_violations.json: %s", e)

    # Send Telegram alert on violations
    if send_alert and not result.passed:
        alert_lines = [
            "🚨 <b>SPA POLICY VIOLATION</b>",
            "Время: {}".format(ts[:19].replace("T", " ")),
            "",
            text,
        ]
        _send_telegram("\n".join(alert_lines))

    return 0 if result.passed else 1


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    write = "--check" not in sys.argv
    quiet = "--quiet" in sys.argv
    send_alert = "--no-alert" not in sys.argv

    exit_code = run_validation_check(write=write, quiet=quiet, send_alert=send_alert)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
