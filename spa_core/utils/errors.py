"""
spa_core/utils/errors.py

SPA error catalog.
All custom exceptions and error handling utilities.

Usage:
    from spa_core.utils.errors import SPAError, GateError, SourceError
    from spa_core.utils.errors import safe_call, require_gate

Design principle: fail-fast in tests, fail-safe in production.

Error hierarchy:
    SPAError                     — base for all SPA exceptions
    ├── GateError                — gate check failed
    ├── SourceError              — data source unavailable or invalid
    ├── ValidationError          — field-level validation failure
    ├── KANBANError              — KANBAN.json operation failed
    ├── AdapterError             — DeFi adapter failed to fetch data
    ├── ConfigError              — missing or invalid configuration
    ├── AtomicWriteError         — atomic file write failed
    ├── RegistryError            — adapter/module not found in a registry
    ├── RiskPolicyError          — RiskPolicy violation detected
    ├── AllocationError          — invalid allocation or constraint violation
    └── LiveTradingForbiddenError — live trading attempted without gate PASS

Utilities:
    safe_call(func, *args, default, log_error)  — exception-safe wrapper
    require_gate(gate_status, gate_name)        — hard stop for live trading

MP-1382 (v9.98) — stdlib only, no external dependencies, LLM FORBIDDEN.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

__all__ = [
    # Base
    "SPAError",
    # Domain exceptions
    "GateError",
    "SourceError",
    "ValidationError",
    "KANBANError",
    "AdapterError",
    "ConfigError",
    "AtomicWriteError",
    "RegistryError",
    "RiskPolicyError",
    "AllocationError",
    "LiveTradingForbiddenError",
    # Utilities
    "safe_call",
    "require_gate",
]


# ─────────────────────────────────────────────────────────────────────────────
# Base exception
# ─────────────────────────────────────────────────────────────────────────────


class SPAError(Exception):
    """
    Base class for all SPA exceptions.

    Every SPA-specific exception carries:
      - ``code``    — machine-readable string (e.g. "GATE_BACKTEST_FAIL")
      - ``details`` — free-form dict with contextual information

    Usage::

        try:
            gate_check()
        except SPAError as e:
            logging.error("%s", e.to_dict())
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.code: str = code or "SPA_UNKNOWN"
        self.details: dict = details or {}

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (for logging and API responses)."""
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={str(self)!r})"


# ─────────────────────────────────────────────────────────────────────────────
# Gate exceptions
# ─────────────────────────────────────────────────────────────────────────────


class GateError(SPAError):
    """
    Raised when a gate check fails or returns a non-PASS status.

    Use for all 4-state gate failures: BACKTEST, PRE_PAPER, PAPER, LIVE.

    Args:
        gate:    Gate identifier (e.g. "backtest", "paper_ready", "live").
        status:  Observed status (e.g. "FAIL", "NOT_READY", "UNKNOWN", "BLOCKED").
        message: Optional human-readable override.

    The error code is auto-generated as ``GATE_<GATE>_<STATUS>``.

    Examples:
        - BacktestGate not in PASS state
        - Missing required gate JSON file
        - Corrupt gate data
    """

    def __init__(
        self,
        gate: str,
        status: str,
        message: Optional[str] = None,
    ) -> None:
        gate_up = gate.upper().replace("-", "_")
        status_up = status.upper().replace("-", "_")
        code = f"GATE_{gate_up}_{status_up}"
        super().__init__(
            message or f"Gate '{gate}' is {status}",
            code=code,
            details={"gate": gate, "status": status},
        )
        self.gate = gate
        self.status = status


# ─────────────────────────────────────────────────────────────────────────────
# Data source exceptions
# ─────────────────────────────────────────────────────────────────────────────


class SourceError(SPAError):
    """
    Raised when a data source is unavailable, stale, or returns invalid data.

    Args:
        source_id: Canonical source identifier (e.g. "sky_susds", "aave_v3_usdc").
        reason:    Human-readable description of the failure.

    Examples:
        - DeFiLlama API timeout
        - Adapter fetch returns unexpected schema
        - TVL below required floor
    """

    def __init__(self, source_id: str, reason: str) -> None:
        super().__init__(
            f"Source '{source_id}': {reason}",
            code="SOURCE_ERROR",
            details={"source_id": source_id, "reason": reason},
        )
        self.source_id = source_id
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Validation exceptions
# ─────────────────────────────────────────────────────────────────────────────


class ValidationError(SPAError, ValueError):
    """
    Field-level validation failed.

    Also a :class:`ValueError` — a failed field validation is conceptually an
    invalid value, so ``except ValueError`` callers catch it too (existing
    ``except ValidationError`` / ``except SPAError`` handlers are unaffected).

    Args:
        field:  Name of the field that failed validation.
        value:  The invalid value (coerced to str for the message).
        reason: Explanation of why the value is invalid.

    Example::

        raise ValidationError("clean_pct", 1.5, "must be in [0.0, 1.0]")
    """

    def __init__(self, field: str, value: Any, reason: str) -> None:
        super().__init__(
            f"Validation failed: {field}={value!r} — {reason}",
            code="VALIDATION_ERROR",
            details={"field": field, "value": str(value), "reason": reason},
        )
        self.field = field
        self.value = value
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# KANBAN exceptions
# ─────────────────────────────────────────────────────────────────────────────


class KANBANError(SPAError):
    """
    KANBAN.json operation failed.

    Used when reading, writing, or updating KANBAN state fails.
    Concurrent write conflicts should also raise this.

    Example::

        raise KANBANError("Failed to parse KANBAN.json", code="KANBAN_PARSE_ERROR")
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(
            message,
            code=code or "KANBAN_ERROR",
            details=details or {},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Adapter exceptions
# ─────────────────────────────────────────────────────────────────────────────


class AdapterError(SPAError):
    """
    A DeFi protocol adapter failed to fetch or parse data.

    Args:
        adapter_id: Adapter identifier (e.g. "aave_v3", "morpho_steakhouse").
        reason:     Description of the failure.

    Example::

        raise AdapterError("compound_v3", "TVL response missing 'tvlUsd' key")
    """

    def __init__(self, adapter_id: str, reason: str) -> None:
        super().__init__(
            f"Adapter '{adapter_id}': {reason}",
            code="ADAPTER_ERROR",
            details={"adapter_id": adapter_id, "reason": reason},
        )
        self.adapter_id = adapter_id
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Configuration exceptions
# ─────────────────────────────────────────────────────────────────────────────


class ConfigError(SPAError):
    """
    Missing or invalid configuration value.

    Used for environment variable issues, missing Keychain entries,
    or invalid config file contents.

    Example::

        raise ConfigError("GITHUB_PAT_SPA", "not found in Keychain")
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(
            f"Config error: {key!r} — {reason}",
            code="CONFIG_ERROR",
            details={"key": key, "reason": reason},
        )
        self.key = key
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Atomic write exceptions
# ─────────────────────────────────────────────────────────────────────────────


class AtomicWriteError(SPAError):
    """
    Atomic file write (mkstemp + os.replace) failed.

    Critical — signals that a state file may be corrupted or partially written.
    Always log at ERROR level when catching this.

    Example::

        raise AtomicWriteError("data/trades.json", "os.replace: Permission denied")
    """

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(
            f"Atomic write failed for '{path}': {reason}",
            code="ATOMIC_WRITE_ERROR",
            details={"path": path, "reason": reason},
        )
        self.path = path
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# Registry / Risk / Allocation exceptions (preserved from original catalog)
# ─────────────────────────────────────────────────────────────────────────────


class RegistryError(SPAError):
    """Raised when an adapter or module is not found in a registry."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message, code=code or "REGISTRY_ERROR", details=details or {})


class RiskPolicyError(SPAError):
    """Raised when a RiskPolicy violation is detected."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message, code=code or "RISK_POLICY_ERROR", details=details or {})


class AllocationError(SPAError):
    """Raised when an allocation is invalid or violates constraints."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message, code=code or "ALLOCATION_ERROR", details=details or {})


# ─────────────────────────────────────────────────────────────────────────────
# Live trading guard
# ─────────────────────────────────────────────────────────────────────────────


class LiveTradingForbiddenError(SPAError):
    """
    Live (real-money) trading was attempted before all gates passed.

    This exception is the *hard stop* for the live trading activation path.
    It must never be swallowed silently.

    Args:
        gate: The gate that blocked live activation (e.g. "paper_ready").

    Example::

        raise LiveTradingForbiddenError("paper_ready")
    """

    def __init__(self, gate: str) -> None:
        super().__init__(
            f"Live trading forbidden: gate '{gate}' has not passed",
            code="LIVE_TRADING_FORBIDDEN",
            details={"gate": gate},
        )
        self.gate = gate


# ─────────────────────────────────────────────────────────────────────────────
# Utility: safe_call
# ─────────────────────────────────────────────────────────────────────────────


def safe_call(
    func: Callable,
    *args: Any,
    default: Any = None,
    log_error: bool = True,
    logger_name: str = "spa.safe_call",
    **kwargs: Any,
) -> Any:
    """
    Call ``func(*args, **kwargs)`` without propagating exceptions.

    Returns ``default`` on any exception.
    Logs a WARNING if ``log_error=True`` (default).

    Use in background tasks (daily cycle, launchd jobs) where a crash
    in one section must never prevent the rest from running.

    Do NOT use in:
    - live trading paths (use ``require_gate`` and let exceptions propagate)
    - test assertions (tests should see real exceptions)

    Args:
        func:        The callable to invoke.
        *args:       Positional arguments forwarded to ``func``.
        default:     Value returned on exception (default: ``None``).
        log_error:   If True, log the exception at WARNING level.
        logger_name: Logger name (default: ``"spa.safe_call"``).
        **kwargs:    Keyword arguments forwarded to ``func``.

    Returns:
        The return value of ``func(*args, **kwargs)``, or ``default``.

    Example::

        result = safe_call(risky_adapter.fetch, default={"apy": 0.0})
        # Never raises; returns {"apy": 0.0} if fetch() fails.
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        if log_error:
            _logger = logging.getLogger(logger_name)
            _logger.warning(
                "%s(*%r, **%r) → %s: %s",
                getattr(func, "__name__", repr(func)),
                args,
                kwargs,
                type(exc).__name__,
                exc,
            )
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Utility: require_gate
# ─────────────────────────────────────────────────────────────────────────────


def require_gate(gate_status: str, gate_name: str) -> None:
    """
    Assert that a gate has PASS status; raise ``LiveTradingForbiddenError`` otherwise.

    Use at the entry point of any live-trading function to enforce the gate
    check before any real-money operations.

    Args:
        gate_status: The current status string of the gate.
        gate_name:   Human-readable gate name (used in the error message).

    Raises:
        LiveTradingForbiddenError: If ``gate_status`` is not ``"PASS"``.

    Example::

        status = gate.four_state_status()
        require_gate(status["live"], "live")   # raises if not "PASS"
        activate_live_trading()                # only reached if gate PASS
    """
    if gate_status != "PASS":
        raise LiveTradingForbiddenError(gate_name)
