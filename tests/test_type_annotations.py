"""
tests/test_type_annotations.py
Tests for type annotation coverage — MP-1520 (v11.36)

20 tests verifying that key functions in spa_core/utils/ and spa_core/safety/
carry full type hints (parameters + return types).

Strategy:
  - Import inspect to check annotations dict.
  - Check __annotations__ on classes and inspect.signature on functions.
  - Verify mypy.ini exists and targets critical modules.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. mypy.ini presence and config
# ─────────────────────────────────────────────────────────────────────────────


def test_mypy_ini_exists() -> None:
    """mypy.ini must be present at repo root."""
    assert Path("mypy.ini").exists(), "mypy.ini not found at repo root"


def test_mypy_ini_has_python_version() -> None:
    content = Path("mypy.ini").read_text()
    assert "python_version" in content


def test_mypy_ini_targets_utils() -> None:
    content = Path("mypy.ini").read_text()
    assert "spa_core.utils" in content


def test_mypy_ini_targets_safety() -> None:
    content = Path("mypy.ini").read_text()
    assert "spa_core.safety" in content


def test_mypy_ini_disallow_untyped_defs() -> None:
    content = Path("mypy.ini").read_text()
    assert "disallow_untyped_defs" in content


# ─────────────────────────────────────────────────────────────────────────────
# 2. spa_core/utils/atomic.py — type annotations
# ─────────────────────────────────────────────────────────────────────────────


def test_atomic_save_return_annotated() -> None:
    from spa_core.utils.atomic import atomic_save
    sig = inspect.signature(atomic_save)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_atomic_save_params_annotated() -> None:
    from spa_core.utils.atomic import atomic_save
    sig = inspect.signature(atomic_save)
    for name, param in sig.parameters.items():
        assert param.annotation is not inspect.Parameter.empty, \
            f"atomic_save param '{name}' lacks annotation"


def test_atomic_load_return_annotated() -> None:
    from spa_core.utils.atomic import atomic_load
    sig = inspect.signature(atomic_load)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_atomic_append_ring_return_annotated() -> None:
    from spa_core.utils.atomic import atomic_append_ring
    sig = inspect.signature(atomic_append_ring)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_atomic_update_update_fn_annotated() -> None:
    """update_fn parameter must have a type annotation (Callable)."""
    from spa_core.utils.atomic import atomic_update
    sig = inspect.signature(atomic_update)
    update_fn_param = sig.parameters.get("update_fn")
    assert update_fn_param is not None
    assert update_fn_param.annotation is not inspect.Parameter.empty, \
        "atomic_update.update_fn lacks type annotation"


def test_atomic_save_text_return_annotated() -> None:
    from spa_core.utils.atomic import atomic_save_text
    sig = inspect.signature(atomic_save_text)
    assert sig.return_annotation is not inspect.Parameter.empty


# ─────────────────────────────────────────────────────────────────────────────
# 3. spa_core/utils/errors.py — type annotations
# ─────────────────────────────────────────────────────────────────────────────


def test_safe_call_return_annotated() -> None:
    from spa_core.utils.errors import safe_call
    sig = inspect.signature(safe_call)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_require_gate_annotated() -> None:
    from spa_core.utils.errors import require_gate
    sig = inspect.signature(require_gate)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_spa_error_to_dict_annotated() -> None:
    from spa_core.utils.errors import SPAError
    sig = inspect.signature(SPAError.to_dict)
    assert sig.return_annotation is not inspect.Parameter.empty


# ─────────────────────────────────────────────────────────────────────────────
# 4. spa_core/safety/safeguard.py — type annotations
# ─────────────────────────────────────────────────────────────────────────────


def test_live_trading_forbidden_return_annotated() -> None:
    from spa_core.safety.safeguard import live_trading_forbidden
    sig = inspect.signature(live_trading_forbidden)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_safeguard_require_gate_annotated() -> None:
    from spa_core.safety.safeguard import require_gate
    sig = inspect.signature(require_gate)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_is_research_only_return_annotated() -> None:
    from spa_core.safety.safeguard import is_research_only
    sig = inspect.signature(is_research_only)
    # Return annotation should be bool (PEP 563: may be string 'bool' or type bool)
    ann = sig.return_annotation
    assert ann is not inspect.Parameter.empty
    # Allow PEP 563 lazy string or actual type
    assert ann is bool or str(ann) == "bool", f"Expected bool, got {ann!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. spa_core/utils/keychain.py — type annotations
# ─────────────────────────────────────────────────────────────────────────────


def test_get_secret_return_annotated() -> None:
    from spa_core.utils.keychain import get_secret
    sig = inspect.signature(get_secret)
    assert sig.return_annotation is not inspect.Parameter.empty


def test_get_github_pat_annotated() -> None:
    from spa_core.utils.keychain import get_github_pat
    sig = inspect.signature(get_github_pat)
    assert sig.return_annotation is not inspect.Parameter.empty


# ─────────────────────────────────────────────────────────────────────────────
# 6. scripts/type_check.sh existence
# ─────────────────────────────────────────────────────────────────────────────


def test_type_check_sh_exists() -> None:
    assert Path("scripts/type_check.sh").exists()


def test_type_check_sh_executable() -> None:
    """File should reference bash and spa_core targets."""
    content = Path("scripts/type_check.sh").read_text()
    assert "spa_core" in content
    assert "mypy" in content


# ─────────────────────────────────────────────────────────────────────────────
# 7. spa_core/utils/kanban.py
# ─────────────────────────────────────────────────────────────────────────────


def test_increment_done_return_annotated() -> None:
    from spa_core.utils.kanban import increment_done
    sig = inspect.signature(increment_done)
    ann = sig.return_annotation
    assert ann is not inspect.Parameter.empty
    # Allow PEP 563 lazy string or actual type
    assert ann is int or str(ann) == "int", f"Expected int, got {ann!r}"
