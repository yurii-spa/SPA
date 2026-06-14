"""
alert_config.py — SPA-V390 Email Alert System configuration.

Holds SMTP / recipient configuration sourced from environment variables.
Designed for GitHub Actions SMTP delivery, with a graceful dry-run fallback
when SMTP credentials are not present (e.g. local dev, CI without secrets).

stdlib only. No secrets are ever hardcoded — everything comes from env vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

# Severity levels, ordered low → high.
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"

SEVERITY_LEVELS: tuple = (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL)

# Numeric rank for comparison / sorting.
SEVERITY_RANK = {
    SEVERITY_INFO: 1,
    SEVERITY_WARNING: 2,
    SEVERITY_CRITICAL: 3,
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class AlertConfig:
    """
    SMTP + recipient configuration for the email alert system.

    Defaults are pulled from environment variables. If any required SMTP
    variable is missing, ``dry_run`` is forced to True so the dispatcher logs
    to disk instead of attempting a (doomed) network send.
    """

    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    email_to: List[str] = field(default_factory=list)
    severity_levels: tuple = SEVERITY_LEVELS
    # Minimum severity that triggers an actual email (INFO logged, not mailed).
    min_email_severity: str = SEVERITY_WARNING
    dry_run: bool = True

    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls) -> "AlertConfig":
        """
        Build config from env vars:
          SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO

        ALERT_EMAIL_TO may be a comma- or semicolon-separated list.
        If host/user/pass/recipients are incomplete → dry_run=True.
        """
        host = _env("SMTP_HOST")
        user = _env("SMTP_USER")
        password = _env("SMTP_PASS")
        to_raw = _env("ALERT_EMAIL_TO")

        port_raw = _env("SMTP_PORT", "465")
        try:
            port = int(port_raw) if port_raw else 465
        except ValueError:
            port = 465

        recipients = [
            addr.strip()
            for addr in to_raw.replace(";", ",").split(",")
            if addr.strip()
        ]

        smtp_ready = bool(host and user and password and recipients)

        return cls(
            smtp_host=host,
            smtp_port=port,
            smtp_user=user,
            smtp_pass=password,
            email_to=recipients,
            dry_run=not smtp_ready,
        )

    # ------------------------------------------------------------------ #
    @property
    def smtp_configured(self) -> bool:
        """True when all SMTP fields + at least one recipient are present."""
        return bool(
            self.smtp_host
            and self.smtp_user
            and self.smtp_pass
            and self.email_to
        )

    def should_email(self, severity: str) -> bool:
        """Whether a given severity warrants an actual email send."""
        return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(
            self.min_email_severity, 2
        )

    def redacted(self) -> dict:
        """Config summary safe for logging (password masked)."""
        return {
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_user": self.smtp_user,
            "smtp_pass": "***" if self.smtp_pass else "",
            "email_to": list(self.email_to),
            "dry_run": self.dry_run,
            "min_email_severity": self.min_email_severity,
        }
