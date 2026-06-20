"""
tests/test_error_catalog.py — MP-1485 (v11.01)

15 tests covering:
  - ERROR_CATALOG structure and completeness
  - lookup() happy path and unknown-code fallback
  - lookup_by_class() and lookup_by_category()
  - list_codes() ordering and coverage
  - Integration: every catalog entry's class is importable from spa_core.utils.errors
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.utils.error_catalog import (
    ERROR_CATALOG,
    lookup,
    list_codes,
    lookup_by_class,
    lookup_by_category,
)
import spa_core.utils.errors as errors_module


# ── 1. Catalog structure ──────────────────────────────────────────────────────

def test_catalog_is_dict():
    assert isinstance(ERROR_CATALOG, dict)
    assert len(ERROR_CATALOG) >= 12


def test_catalog_entries_have_required_keys():
    required = {"code", "class", "runtime_code", "module", "category",
                "description", "when", "remediation", "example"}
    for code, entry in ERROR_CATALOG.items():
        missing = required - set(entry.keys())
        assert not missing, f"Entry {code!r} missing keys: {missing}"


def test_catalog_codes_match_keys():
    """Each entry's 'code' field must match its dict key."""
    for key, entry in ERROR_CATALOG.items():
        assert entry["code"] == key, f"Key {key!r} has entry code {entry['code']!r}"


def test_catalog_covers_all_expected_codes():
    expected = {"E001", "G001", "S001", "V001", "K001", "A001",
                "C001", "W001", "R001", "P001", "L001", "X001"}
    assert expected.issubset(set(ERROR_CATALOG.keys()))


# ── 2. lookup() ───────────────────────────────────────────────────────────────

def test_lookup_known_code():
    entry = lookup("G001")
    assert entry["class"] == "GateError"
    assert "gate" in entry["category"]


def test_lookup_safety_code():
    entry = lookup("X001")
    assert entry["class"] == "LiveTradingForbiddenError"
    assert entry["category"] == "safety"


def test_lookup_unknown_code_returns_fallback():
    entry = lookup("ZZZ")
    assert entry["class"] == "Unknown"
    assert entry["code"] == "ZZZ"
    assert "ZZZ" in entry["description"]


def test_lookup_returns_dict_for_all_codes():
    for code in list_codes():
        result = lookup(code)
        assert isinstance(result, dict)


# ── 3. list_codes() ───────────────────────────────────────────────────────────

def test_list_codes_returns_list():
    codes = list_codes()
    assert isinstance(codes, list)
    assert len(codes) >= 12


def test_list_codes_includes_all_catalog_keys():
    codes = list_codes()
    for key in ERROR_CATALOG:
        assert key in codes


def test_list_codes_order_matches_catalog():
    """list_codes() must return codes in the same order as ERROR_CATALOG."""
    assert list_codes() == list(ERROR_CATALOG.keys())


# ── 4. lookup_by_class() ─────────────────────────────────────────────────────

def test_lookup_by_class_gate_error():
    entry = lookup_by_class("GateError")
    assert entry is not None
    assert entry["code"] == "G001"


def test_lookup_by_class_unknown_returns_none():
    assert lookup_by_class("NoSuchError") is None


def test_lookup_by_class_live_trading_forbidden():
    entry = lookup_by_class("LiveTradingForbiddenError")
    assert entry is not None
    assert entry["code"] == "X001"


# ── 5. lookup_by_category() ──────────────────────────────────────────────────

def test_lookup_by_category_safety():
    entries = lookup_by_category("safety")
    assert len(entries) >= 1
    classes = [e["class"] for e in entries]
    assert "LiveTradingForbiddenError" in classes


def test_lookup_by_category_unknown_returns_empty():
    assert lookup_by_category("nonexistent_category") == []


# ── 6. Integration: every catalog class is importable ─────────────────────────

def test_all_catalog_classes_importable():
    """Every 'class' in the catalog must exist in spa_core.utils.errors."""
    for code, entry in ERROR_CATALOG.items():
        class_name = entry["class"]
        cls = getattr(errors_module, class_name, None)
        assert cls is not None, (
            f"ERROR_CATALOG[{code!r}] references class {class_name!r} "
            f"which is not in spa_core.utils.errors"
        )
        assert inspect.isclass(cls), f"{class_name} is not a class"
        assert issubclass(cls, Exception), f"{class_name} must inherit Exception"
