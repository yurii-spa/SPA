"""
tests/test_spaerror_complete.py

MP-1467 (v10.83) — SPAError Final Comprehensive Test Suite

20 tests covering:
  - Full exception hierarchy
  - to_dict() serialization
  - safe_call() behavior
  - require_gate() behavior
  - Zero bare Exception/RuntimeError in spa_core/ (audit integration)

stdlib-only, no external dependencies.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.utils.errors import (
    SPAError,
    GateError,
    SourceError,
    ValidationError,
    KANBANError,
    AdapterError,
    ConfigError,
    AtomicWriteError,
    RegistryError,
    RiskPolicyError,
    AllocationError,
    LiveTradingForbiddenError,
    safe_call,
    require_gate,
)

REPO_ROOT = Path(__file__).parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# 1. SPAError base
# ─────────────────────────────────────────────────────────────────────────────


def test_01_spaerror_is_exception():
    """SPAError must be a subclass of Exception."""
    assert issubclass(SPAError, Exception)


def test_02_spaerror_default_code():
    """SPAError with no code gets SPA_UNKNOWN."""
    err = SPAError("something went wrong")
    assert err.code == "SPA_UNKNOWN"
    assert err.details == {}


def test_03_spaerror_custom_code_and_details():
    """SPAError stores custom code and details."""
    err = SPAError("msg", code="MY_CODE", details={"k": "v"})
    assert err.code == "MY_CODE"
    assert err.details == {"k": "v"}


def test_04_spaerror_to_dict_shape():
    """to_dict() returns expected keys."""
    err = SPAError("msg", code="SOME_CODE", details={"x": 1})
    d = err.to_dict()
    assert d["error"] == "SPAError"
    assert d["code"] == "SOME_CODE"
    assert d["message"] == "msg"
    assert d["details"] == {"x": 1}


def test_05_spaerror_repr():
    """__repr__ contains class name and code."""
    err = SPAError("msg", code="REPR_CODE")
    r = repr(err)
    assert "SPAError" in r
    assert "REPR_CODE" in r


# ─────────────────────────────────────────────────────────────────────────────
# 2. Domain subclasses
# ─────────────────────────────────────────────────────────────────────────────


def test_06_gate_error_code_construction():
    """GateError auto-generates GATE_<GATE>_<STATUS> code."""
    err = GateError("paper_ready", "FAIL")
    assert err.code == "GATE_PAPER_READY_FAIL"
    assert err.gate == "paper_ready"
    assert err.status == "FAIL"
    assert isinstance(err, SPAError)


def test_07_gate_error_custom_message():
    """GateError accepts custom message override."""
    err = GateError("live", "BLOCKED", message="Custom message")
    assert str(err) == "Custom message"


def test_08_source_error():
    """SourceError stores source_id and reason."""
    err = SourceError("aave_v3", "API timeout")
    assert err.source_id == "aave_v3"
    assert err.reason == "API timeout"
    assert err.code == "SOURCE_ERROR"
    assert isinstance(err, SPAError)


def test_09_validation_error():
    """ValidationError stores field, value, reason."""
    err = ValidationError("clean_pct", 1.5, "must be in [0.0, 1.0]")
    assert err.field == "clean_pct"
    assert err.value == 1.5
    assert err.reason == "must be in [0.0, 1.0]"
    assert err.code == "VALIDATION_ERROR"
    assert isinstance(err, SPAError)


def test_10_kanban_error():
    """KANBANError has default code KANBAN_ERROR."""
    err = KANBANError("parse failed")
    assert err.code == "KANBAN_ERROR"
    assert isinstance(err, SPAError)


def test_11_adapter_error():
    """AdapterError stores adapter_id and reason."""
    err = AdapterError("compound_v3", "missing tvlUsd key")
    assert err.adapter_id == "compound_v3"
    assert err.reason == "missing tvlUsd key"
    assert err.code == "ADAPTER_ERROR"
    assert isinstance(err, SPAError)


def test_12_config_error():
    """ConfigError stores key and reason."""
    err = ConfigError("GITHUB_PAT", "not found in Keychain")
    assert err.key == "GITHUB_PAT"
    assert err.reason == "not found in Keychain"
    assert err.code == "CONFIG_ERROR"
    assert isinstance(err, SPAError)


def test_13_atomic_write_error():
    """AtomicWriteError stores path and reason."""
    err = AtomicWriteError("data/trades.json", "Permission denied")
    assert err.path == "data/trades.json"
    assert err.reason == "Permission denied"
    assert err.code == "ATOMIC_WRITE_ERROR"
    assert isinstance(err, SPAError)


def test_14_registry_error():
    """RegistryError default code REGISTRY_ERROR."""
    err = RegistryError("adapter not found")
    assert err.code == "REGISTRY_ERROR"
    assert isinstance(err, SPAError)


def test_15_risk_policy_error():
    """RiskPolicyError default code RISK_POLICY_ERROR."""
    err = RiskPolicyError("drawdown limit exceeded")
    assert err.code == "RISK_POLICY_ERROR"
    assert isinstance(err, SPAError)


def test_16_allocation_error():
    """AllocationError default code ALLOCATION_ERROR."""
    err = AllocationError("T2 total cap exceeded")
    assert err.code == "ALLOCATION_ERROR"
    assert isinstance(err, SPAError)


def test_17_live_trading_forbidden_error():
    """LiveTradingForbiddenError stores gate, code LIVE_TRADING_FORBIDDEN."""
    err = LiveTradingForbiddenError("paper_ready")
    assert err.gate == "paper_ready"
    assert err.code == "LIVE_TRADING_FORBIDDEN"
    assert isinstance(err, SPAError)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Utilities
# ─────────────────────────────────────────────────────────────────────────────


def test_18_safe_call_returns_value_on_success():
    """safe_call returns function result when no exception."""
    result = safe_call(lambda: 42, default=0)
    assert result == 42


def test_18b_safe_call_returns_default_on_exception():
    """safe_call returns default when wrapped function raises."""

    def boom():
        raise SPAError("simulated failure")

    result = safe_call(boom, default="fallback", log_error=False)
    assert result == "fallback"


def test_19_require_gate_passes_on_pass_status():
    """require_gate does not raise when status is PASS."""
    require_gate("PASS", "test_gate")  # must not raise


def test_19b_require_gate_raises_on_non_pass():
    """require_gate raises LiveTradingForbiddenError on non-PASS status."""
    with pytest.raises(LiveTradingForbiddenError) as exc_info:
        require_gate("FAIL", "live_gate")
    assert exc_info.value.gate == "live_gate"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Audit integration — zero bare exceptions in spa_core/
# ─────────────────────────────────────────────────────────────────────────────


def test_20_zero_bare_exceptions_in_spa_core():
    """
    Integration audit: grep spa_core/ for bare Exception/RuntimeError.
    Fails if any non-test, non-stdlib-marker line is found.
    MP-1467 acceptance criterion: 100% SPAError adoption.
    """
    violations: list[str] = []
    for pattern in ["raise Exception", "raise RuntimeError"]:
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "--include=*.py",
                pattern,
                str(REPO_ROOT / "spa_core"),
            ],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "test" in line:
                continue
            if "__pycache__" in line:
                continue
            if "# stdlib-only" in line:
                continue
            violations.append(line)

    assert violations == [], (
        f"Found {len(violations)} bare Exception/RuntimeError in spa_core/ "
        f"(non-test, non-stdlib). Migrate to SPAError:\n"
        + "\n".join(violations[:10])
    )
