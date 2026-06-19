"""
spa_core — SPA (Stablecoin Preservation Algorithm) Core Library

Version: see spa_core.version.VERSION

Quick start::

    from spa_core import BacktestGate, PITEngine, RS001LiveAPYEngine

Public API
----------
Gates
    BacktestGate
Engines
    PITEngine, RS001LiveAPYEngine, RS002LiveAPYEngine
Utils
    atomic_save, atomic_load
Errors
    SPAError, GateError, SourceError
Registry
    ADAPTER_REGISTRY (see spa_core.adapters.registry)
Version
    VERSION, VERSION_TUPLE
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Version — always available, never suppressed
# ---------------------------------------------------------------------------
from spa_core.version import VERSION, VERSION_TUPLE  # noqa: F401

# ---------------------------------------------------------------------------
# Core gates
# ---------------------------------------------------------------------------
try:
    from spa_core.backtesting.backtest_gate import BacktestGate  # noqa: F401
except ImportError:
    try:
        # actual file location as of v9.99
        from spa_core.backtesting.gate import BacktestGate  # noqa: F401
    except ImportError:
        BacktestGate = None  # type: ignore[assignment,misc]

try:
    from spa_core.backtesting.pit_engine import PITEngine  # noqa: F401
except ImportError:
    PITEngine = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# APY Engines (research strategies)
# ---------------------------------------------------------------------------
try:
    from spa_core.analytics.rs001_live_apy_engine import RS001LiveAPYEngine  # noqa: F401
except ImportError:
    RS001LiveAPYEngine = None  # type: ignore[assignment,misc]

try:
    from spa_core.analytics.rs002_live_apy_engine import RS002LiveAPYEngine  # noqa: F401
except ImportError:
    RS002LiveAPYEngine = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
try:
    from spa_core.utils.atomic import atomic_save, atomic_load  # noqa: F401
except ImportError:
    atomic_save = None  # type: ignore[assignment]
    atomic_load = None  # type: ignore[assignment]

try:
    from spa_core.utils.errors import SPAError, GateError, SourceError  # noqa: F401
except ImportError:
    SPAError = None  # type: ignore[assignment,misc]
    GateError = None  # type: ignore[assignment,misc]
    SourceError = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------
try:
    from spa_core.adapters.registry import ADAPTER_REGISTRY  # noqa: F401
except ImportError:
    ADAPTER_REGISTRY = {}  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
__version__: str = VERSION

__all__ = [
    # version
    "VERSION",
    "VERSION_TUPLE",
    "__version__",
    # gates / engines
    "BacktestGate",
    "PITEngine",
    # research engines
    "RS001LiveAPYEngine",
    "RS002LiveAPYEngine",
    # utils
    "atomic_save",
    "atomic_load",
    # errors
    "SPAError",
    "GateError",
    "SourceError",
    # registry
    "ADAPTER_REGISTRY",
]
