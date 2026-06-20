"""
SPA — Stablecoin Portfolio Algorithm
Public API v10.0

Quick start::

    from spa_core import VERSION, BaseAnalytics, BaseAdapter, ADAPTER_REGISTRY
    from spa_core import SPAError, GateError, atomic_save, LiveTradingGate

All public names are guaranteed stable across patch versions.
For the full reference see docs/PUBLIC_API.md.
"""

from __future__ import annotations

# ── Version ───────────────────────────────────────────────────────────────────
from spa_core.version import VERSION, __version__  # noqa: F401

# ── Base classes ──────────────────────────────────────────────────────────────
from spa_core.base import BaseAnalytics, BaseAdapter, BaseReport  # noqa: F401

# ── Error hierarchy ───────────────────────────────────────────────────────────
from spa_core.utils.errors import (  # noqa: F401
    SPAError,
    GateError,
    SourceError,
    ConfigError,
    RegistryError,
    AdapterError,
    AllocationError,
    LiveTradingForbiddenError,
)

# ── Atomic I/O ────────────────────────────────────────────────────────────────
from spa_core.utils.atomic import atomic_save, atomic_load  # noqa: F401

# ── KANBAN helpers ────────────────────────────────────────────────────────────
from spa_core.utils.kanban import increment_done  # noqa: F401

# ── Adapter registry ──────────────────────────────────────────────────────────
from spa_core.adapters.registry import ADAPTER_REGISTRY  # noqa: F401

# ── Safety / live-trading gate ────────────────────────────────────────────────
from spa_core.safety.live_trading_gate import LiveTradingGate  # noqa: F401
from spa_core.safety.safeguard import live_trading_forbidden  # noqa: F401

# ── Legacy / convenience re-exports (preserved for backwards compat) ──────────
try:
    from spa_core.backtesting.backtest_gate import BacktestGate  # noqa: F401
except ImportError:
    try:
        from spa_core.backtesting.gate import BacktestGate  # noqa: F401
    except ImportError:
        BacktestGate = None  # type: ignore[assignment,misc]

try:
    from spa_core.backtesting.pit_engine import PITEngine  # noqa: F401
except ImportError:
    PITEngine = None  # type: ignore[assignment,misc]

try:
    from spa_core.analytics.rs001_live_apy_engine import RS001LiveAPYEngine  # noqa: F401
except ImportError:
    RS001LiveAPYEngine = None  # type: ignore[assignment,misc]

try:
    from spa_core.analytics.rs002_live_apy_engine import RS002LiveAPYEngine  # noqa: F401
except ImportError:
    RS002LiveAPYEngine = None  # type: ignore[assignment,misc]

# ── __all__ ───────────────────────────────────────────────────────────────────
__all__ = [
    # version
    "VERSION",
    "__version__",
    # base classes
    "BaseAnalytics",
    "BaseAdapter",
    "BaseReport",
    # error hierarchy
    "SPAError",
    "GateError",
    "SourceError",
    "ConfigError",
    "RegistryError",
    "AdapterError",
    "AllocationError",
    "LiveTradingForbiddenError",
    # atomic I/O
    "atomic_save",
    "atomic_load",
    # KANBAN
    "increment_done",
    # adapter registry
    "ADAPTER_REGISTRY",
    # safety
    "LiveTradingGate",
    "live_trading_forbidden",
    # legacy / optional
    "BacktestGate",
    "PITEngine",
    "RS001LiveAPYEngine",
    "RS002LiveAPYEngine",
]
