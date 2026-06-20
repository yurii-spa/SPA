"""
spa_core/safety/safeguard.py

Decorators for guarding functions that could cause live trading.

Usage::

    from spa_core.safety.safeguard import live_trading_forbidden, require_gate, research_only

    @live_trading_forbidden
    def execute_swap(amount, token_in, token_out):
        # This function can NEVER be called without an explicit gate activation.
        # The decorator raises LiveTradingForbiddenError unconditionally.
        ...

    @require_gate
    def place_order(size, price):
        # Checks LiveTradingGate before execution.
        # Raises LiveTradingForbiddenError if gate is not active.
        ...

    @research_only("MyAdapter")
    def get_allocation_recommendation():
        # RESEARCH_ONLY — function executes normally, wrapper sets metadata attrs.
        ...

LLM_FORBIDDEN: no LLM calls inside this module.

MP-1402 (v10.18) — stdlib only, no external dependencies.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from spa_core.utils.errors import LiveTradingForbiddenError

__all__ = [
    "live_trading_forbidden",
    "require_gate",
    "research_only",
    "is_research_only",
]

logger = logging.getLogger("spa.safety.safeguard")


# ─────────────────────────────────────────────────────────────────────────────
# @live_trading_forbidden
# ─────────────────────────────────────────────────────────────────────────────


def live_trading_forbidden(func: Callable) -> Callable:
    """
    Decorator that raises LiveTradingForbiddenError *unconditionally*.

    Use on any function that could execute a real trade.  The wrapper
    never delegates to the original function body — the decorated function
    becomes permanently forbidden until the decorator is removed.

    The function name and docstring are preserved via ``functools.wraps``.

    Example::

        @live_trading_forbidden
        def execute_swap(amount, token_in, token_out):
            ...  # body is unreachable

    Raises:
        LiveTradingForbiddenError: always.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        raise LiveTradingForbiddenError(func.__name__)

    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# @require_gate
# ─────────────────────────────────────────────────────────────────────────────


def require_gate(func: Callable) -> Callable:
    """
    Decorator that checks LiveTradingGate before execution.

    The gate must be explicitly activated (all prerequisites met + manual
    activation call) before the wrapped function is allowed to run.

    Example::

        @require_gate
        def place_order(size, price):
            ...

    Raises:
        LiveTradingForbiddenError: if the gate is LOCKED.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from spa_core.safety.live_trading_gate import require_live_gate
        require_live_gate()
        return func(*args, **kwargs)

    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# @research_only
# ─────────────────────────────────────────────────────────────────────────────


def research_only(adapter_name: str = "") -> Callable:
    """
    Decorator factory that marks a function as RESEARCH_ONLY.

    The wrapped function executes normally.  The decorator attaches two
    metadata attributes to the wrapper for introspection::

        func._research_only  → True
        func._adapter_name   → adapter_name (str, empty string by default)

    No blocking occurs — use ``@live_trading_forbidden`` for hard blocks.

    Example::

        @research_only("GMXAdapter")
        def get_gmx_apy() -> float:
            ...

    Args:
        adapter_name: Optional name of the adapter / component (for logging).
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if adapter_name:
                logger.debug(
                    "research_only call: %s.%s", adapter_name, func.__name__
                )
            else:
                logger.debug("research_only call: %s", func.__name__)
            return func(*args, **kwargs)

        wrapper._research_only = True  # type: ignore[attr-defined]
        wrapper._adapter_name = adapter_name  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# Introspection helper
# ─────────────────────────────────────────────────────────────────────────────


def is_research_only(func: Callable) -> bool:
    """
    Return True if *func* has been decorated with ``@research_only``.

    Example::

        @research_only("Aave")
        def fetch_apy(): ...

        assert is_research_only(fetch_apy)  # True
        assert not is_research_only(lambda: None)  # False

    Args:
        func: Any callable.

    Returns:
        True if ``func._research_only is True``, False otherwise.
    """
    return getattr(func, "_research_only", False) is True
