"""
tests/test_public_api.py — MP-1484 (v11.00)

20 tests verifying that `from spa_core import X` works for every symbol
listed in spa_core.__all__ and that each export has the correct type/value.
"""
from __future__ import annotations

import pytest
import inspect


# ── 1. Package importable ─────────────────────────────────────────────────────

def test_spa_core_importable():
    import spa_core  # noqa: F401
    assert spa_core is not None


# ── 2. Version exports ────────────────────────────────────────────────────────

def test_version_is_string():
    from spa_core import VERSION
    assert isinstance(VERSION, str)
    assert len(VERSION) > 0


def test_dunder_version_equals_version():
    from spa_core import VERSION, __version__
    assert __version__ == VERSION


def test_version_semver_format():
    from spa_core import VERSION
    parts = VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


# ── 3. Base classes ───────────────────────────────────────────────────────────

def test_base_analytics_importable():
    from spa_core import BaseAnalytics
    assert inspect.isclass(BaseAnalytics)


def test_base_adapter_importable():
    from spa_core import BaseAdapter
    assert inspect.isclass(BaseAdapter)


def test_base_report_importable():
    from spa_core import BaseReport
    assert inspect.isclass(BaseReport)


def test_base_adapter_has_safe_apy():
    from spa_core import BaseAdapter
    assert hasattr(BaseAdapter, "safe_apy")


def test_base_report_has_to_markdown():
    from spa_core import BaseReport
    assert hasattr(BaseReport, "to_markdown")


# ── 4. Error hierarchy ────────────────────────────────────────────────────────

def test_spa_error_importable():
    from spa_core import SPAError
    assert issubclass(SPAError, Exception)


def test_all_errors_inherit_spa_error():
    from spa_core import (
        SPAError, GateError, SourceError, ConfigError,
        RegistryError, AdapterError, AllocationError,
        LiveTradingForbiddenError,
    )
    for cls in [GateError, SourceError, ConfigError, RegistryError,
                AdapterError, AllocationError, LiveTradingForbiddenError]:
        assert issubclass(cls, SPAError), f"{cls.__name__} must inherit SPAError"


def test_gate_error_raisable():
    from spa_core import GateError
    with pytest.raises(GateError):
        raise GateError("test gate failure")


def test_live_trading_forbidden_error_raisable():
    from spa_core import LiveTradingForbiddenError
    with pytest.raises(LiveTradingForbiddenError):
        raise LiveTradingForbiddenError("paper period active")


# ── 5. Atomic I/O ─────────────────────────────────────────────────────────────

def test_atomic_save_callable():
    from spa_core import atomic_save
    assert callable(atomic_save)


def test_atomic_load_callable():
    from spa_core import atomic_load
    assert callable(atomic_load)


def test_atomic_round_trip(tmp_path):
    from spa_core import atomic_save, atomic_load
    path = str(tmp_path / "test_state.json")
    data = {"key": "value", "count": 42}
    atomic_save(data, path)
    loaded = atomic_load(path)
    assert loaded == data


# ── 6. Adapter registry ───────────────────────────────────────────────────────

def test_adapter_registry_is_dict():
    from spa_core import ADAPTER_REGISTRY
    assert isinstance(ADAPTER_REGISTRY, dict)
    assert len(ADAPTER_REGISTRY) > 0


def test_adapter_registry_values_are_classes():
    from spa_core import ADAPTER_REGISTRY
    for name, cls in list(ADAPTER_REGISTRY.items())[:5]:
        assert inspect.isclass(cls), f"{name} value should be a class"


# ── 7. Safety exports ─────────────────────────────────────────────────────────

def test_live_trading_gate_importable():
    from spa_core import LiveTradingGate
    assert inspect.isclass(LiveTradingGate)


def test_live_trading_forbidden_callable():
    from spa_core import live_trading_forbidden
    assert callable(live_trading_forbidden)


# ── 8. __all__ completeness ───────────────────────────────────────────────────

def test_all_contains_required_symbols():
    import spa_core
    required = [
        "VERSION", "__version__",
        "BaseAnalytics", "BaseAdapter", "BaseReport",
        "SPAError", "GateError", "SourceError", "ConfigError",
        "RegistryError", "AdapterError", "AllocationError",
        "LiveTradingForbiddenError",
        "atomic_save", "atomic_load",
        "increment_done",
        "ADAPTER_REGISTRY",
        "LiveTradingGate",
        "live_trading_forbidden",
    ]
    for sym in required:
        assert sym in spa_core.__all__, f"'{sym}' missing from __all__"


def test_all_symbols_actually_importable():
    import spa_core
    for sym in spa_core.__all__:
        obj = getattr(spa_core, sym, None)
        # None is allowed for optional legacy exports (BacktestGate, PITEngine, etc.)
        # but core symbols must be non-None
        core_required = [
            "VERSION", "__version__", "BaseAnalytics", "BaseAdapter", "BaseReport",
            "SPAError", "GateError", "SourceError", "ConfigError", "RegistryError",
            "AdapterError", "AllocationError", "LiveTradingForbiddenError",
            "atomic_save", "atomic_load", "ADAPTER_REGISTRY",
            "LiveTradingGate", "live_trading_forbidden",
        ]
        if sym in core_required:
            assert obj is not None, f"spa_core.{sym} must not be None"
