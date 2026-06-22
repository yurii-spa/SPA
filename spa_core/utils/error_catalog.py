"""
spa_core/utils/error_catalog.py — MP-1485 (v11.01)

Machine-readable catalog of all SPA error codes.
Each entry maps a short code to structured metadata about the exception class.

Usage::

    from spa_core.utils.error_catalog import ERROR_CATALOG, lookup, list_codes
    entry = lookup("G001")

All error classes referenced here are importable from spa_core.utils.errors.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Catalog definition
# ---------------------------------------------------------------------------

ERROR_CATALOG: Dict[str, Dict[str, Any]] = {
    "E001": {
        "code": "E001",
        "class": "SPAError",
        "runtime_code": "SPA_BASE_ERROR",
        "module": "spa_core.utils.errors",
        "category": "base",
        "description": "Base SPA exception — all SPA errors inherit from this.",
        "when": "Raised directly only as a last resort; prefer domain subclasses.",
        "remediation": "Inspect the 'details' dict attached to the exception.",
        "example": "raise SPAError('SPA_BASE_ERROR', details={'reason': 'unknown'})",
    },
    "G001": {
        "code": "G001",
        "class": "GateError",
        "runtime_code": "GATE_CHECK_FAILED",
        "module": "spa_core.utils.errors",
        "category": "gate",
        "description": "A safety gate check failed (e.g. backtest gate not PASS).",
        "when": "Raised when a gate status is not PASS and live trading is attempted.",
        "remediation": "Run the required gate check and ensure it returns PASS.",
        "example": "raise GateError('GATE_CHECK_FAILED', details={'gate': 'BacktestGate'})",
    },
    "S001": {
        "code": "S001",
        "class": "SourceError",
        "runtime_code": "SOURCE_UNAVAILABLE",
        "module": "spa_core.utils.errors",
        "category": "data",
        "description": "A data source (DeFiLlama, on-chain) is unavailable or returned invalid data.",
        "when": "Raised when an HTTP fetch fails or the response is malformed.",
        "remediation": "Check network connectivity and the upstream data source.",
        "example": "raise SourceError('SOURCE_UNAVAILABLE', details={'url': url})",
    },
    "V001": {
        "code": "V001",
        "class": "ValidationError",
        "runtime_code": "VALIDATION_FAILED",
        "module": "spa_core.utils.errors",
        "category": "validation",
        "description": "A field-level validation failure.",
        "when": "Raised when input data does not meet schema or value constraints.",
        "remediation": "Fix the input data to meet the documented constraints.",
        "example": "raise ValidationError('VALIDATION_FAILED', details={'field': 'apy', 'value': -1})",
    },
    "K001": {
        "code": "K001",
        "class": "KANBANError",
        "runtime_code": "KANBAN_WRITE_FAILED",
        "module": "spa_core.utils.errors",
        "category": "kanban",
        "description": "A KANBAN.json operation failed (read, write, or lock).",
        "when": "Raised when increment_done() or get_done_count() encounters an I/O error.",
        "remediation": "Check file permissions and that KANBAN.json is valid JSON.",
        "example": "raise KANBANError('KANBAN_WRITE_FAILED', details={'path': str(path)})",
    },
    "A001": {
        "code": "A001",
        "class": "AdapterError",
        "runtime_code": "ADAPTER_FETCH_FAILED",
        "module": "spa_core.utils.errors",
        "category": "adapter",
        "description": "A DeFi protocol adapter failed to fetch APY or position data.",
        "when": "Raised when safe_apy() falls back and the caller needs to know.",
        "remediation": "Check the adapter's fetch_apy() implementation and the protocol endpoint.",
        "example": "raise AdapterError('ADAPTER_FETCH_FAILED', details={'protocol': 'aave-v3'})",
    },
    "C001": {
        "code": "C001",
        "class": "ConfigError",
        "runtime_code": "CONFIG_MISSING",
        "module": "spa_core.utils.errors",
        "category": "config",
        "description": "A required configuration key is missing or has an invalid value.",
        "when": "Raised during startup or first-use when a required config is absent.",
        "remediation": "Set the missing configuration key in the environment or config file.",
        "example": "raise ConfigError('CONFIG_MISSING', details={'key': 'DEFILLAMA_API_KEY'})",
    },
    "W001": {
        "code": "W001",
        "class": "AtomicWriteError",
        "runtime_code": "ATOMIC_WRITE_FAILED",
        "module": "spa_core.utils.errors",
        "category": "io",
        "description": "An atomic file write operation failed.",
        "when": "Raised when atomic_save() cannot complete the write-rename cycle.",
        "remediation": "Check disk space and file system permissions.",
        "example": "raise AtomicWriteError('ATOMIC_WRITE_FAILED', details={'path': str(path)})",
    },
    "R001": {
        "code": "R001",
        "class": "RegistryError",
        "runtime_code": "REGISTRY_NOT_FOUND",
        "module": "spa_core.utils.errors",
        "category": "registry",
        "description": "An adapter or module was not found in a registry.",
        "when": "Raised when looking up a protocol key that has no registered adapter.",
        "remediation": "Register the adapter in ADAPTER_REGISTRY or check the protocol key spelling.",
        "example": "raise RegistryError('REGISTRY_NOT_FOUND', details={'key': 'unknown-protocol'})",
    },
    "P001": {
        "code": "P001",
        "class": "RiskPolicyError",
        "runtime_code": "RISK_POLICY_VIOLATION",
        "module": "spa_core.utils.errors",
        "category": "risk",
        "description": "A risk policy constraint was violated.",
        "when": "Raised by RiskPolicy.check() when an allocation exceeds configured limits.",
        "remediation": "Reduce the allocation to comply with the risk policy limits.",
        "example": "raise RiskPolicyError('RISK_POLICY_VIOLATION', details={'constraint': 'max_single_protocol'})",
    },
    "L001": {
        "code": "L001",
        "class": "LiveTradingForbiddenError",
        "runtime_code": "LIVE_TRADING_FORBIDDEN",
        "module": "spa_core.utils.errors",
        "category": "safety",
        "description": "Live trading was attempted without the required gate PASS.",
        "when": "Raised by require_gate() when live_trading_forbidden() is enforced.",
        "remediation": "Pass all safety gates before enabling live trading mode.",
        "example": "raise LiveTradingForbiddenError('LIVE_TRADING_FORBIDDEN', details={'gate': 'BacktestGate'})",
    },
    "X001": {
        "code": "X001",
        "class": "AllocationError",
        "runtime_code": "ALLOCATION_INVALID",
        "module": "spa_core.utils.errors",
        "category": "allocation",
        "description": "An invalid allocation or constraint violation was detected.",
        "when": "Raised when the allocator produces an allocation that violates hard constraints.",
        "remediation": "Check the allocator inputs and ensure capital totals are consistent.",
        "example": "raise AllocationError('ALLOCATION_INVALID', details={'reason': 'negative allocation'})",
    },
}

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def lookup(code: str, default: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Return the catalog entry for *code*, or *default* if not found.

    >>> lookup("G001")["class"]
    'GateError'
    >>> lookup("UNKNOWN") is None
    True
    """
    return ERROR_CATALOG.get(code, default)


def list_codes() -> List[str]:
    """Return all error codes in sorted order."""
    return sorted(ERROR_CATALOG.keys())


def lookup_by_class(class_name: str) -> List[Dict[str, Any]]:
    """
    Return all catalog entries whose 'class' field matches *class_name*.

    >>> lookup_by_class("GateError")[0]["code"]
    'G001'
    """
    return [e for e in ERROR_CATALOG.values() if e["class"] == class_name]


def lookup_by_category(category: str) -> List[Dict[str, Any]]:
    """
    Return all catalog entries in *category*.

    >>> [e["code"] for e in lookup_by_category("gate")]
    ['G001']
    """
    return [e for e in ERROR_CATALOG.values() if e["category"] == category]


__all__ = [
    "ERROR_CATALOG",
    "lookup",
    "list_codes",
    "lookup_by_class",
    "lookup_by_category",
]
