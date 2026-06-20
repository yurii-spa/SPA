"""
spa_core/utils/logging.py
Structured JSON logging for SPA components.
All log entries are JSON for easy parsing and alerting.
"""
import json
import datetime
import logging
import sys
from typing import Any


class SPALogger:
    """Structured JSON logger for SPA components."""

    def __init__(self, component: str, log_file: str = None):
        self.component = component
        self.log_file = log_file
        self._logger = logging.getLogger(f"spa.{component}")

        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            if log_file:
                file_handler = logging.FileHandler(log_file)
                file_handler.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(file_handler)
            self._logger.setLevel(logging.DEBUG)

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "level": level,
            "component": self.component,
            "message": message,
            **{k: v for k, v in kwargs.items() if v is not None},
        }
        self._logger.log(
            getattr(logging, level),
            json.dumps(entry),
        )

    def info(self, message: str, **kwargs: Any) -> None:
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._log("CRITICAL", message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log("DEBUG", message, **kwargs)

    def audit(self, action: str, actor: str = "system", **kwargs: Any) -> None:
        """Audit log — for compliance-relevant actions."""
        self._log("INFO", f"AUDIT: {action}", actor=actor, audit=True, **kwargs)


def get_logger(component: str, log_file: str = None) -> "SPALogger":
    """Returns a SPALogger for the given component."""
    return SPALogger(component, log_file=log_file)
