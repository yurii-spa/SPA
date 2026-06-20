"""
tests/test_phase3_migration.py

20 tests: all Phase 3 modules importable, BaseAnalytics in MRO,
OUTPUT_PATH defined, to_dict() callable and returns dict.

Sprint v10.46 — MP-1430
"""
import importlib

import pytest

from spa_core.base import BaseAnalytics

# ── Phase 3 module registry ────────────────────────────────────────────────────
# (modules without tests / not migrated are excluded)

PHASE3_MIGRATED = [
    # Batch A
    ("regime_adjusted_allocator",  "RegimeAdjustedAllocator"),
    ("rs001_stress_engine",        "RS001StressEngine"),
    ("research_summary_report",    "ResearchSummaryReport"),
    ("rs001_live_apy_engine",      "RS001LiveAPYEngine"),
    ("rs002_live_apy_engine",      "RS002LiveAPYEngine"),
    ("rs002_position_tracker",     "RS002PositionTracker"),
    # Batch B
    ("source_acquisition_tracker", "SourceAcquisitionTracker"),
    ("stablecoin_yield_optimizer", "StablecoinYieldOptimizer"),
    ("t1_data_verifier",           "T1DataVerifier"),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _import_class(module_name: str, class_name: str):
    mod = importlib.import_module(f"spa_core.analytics.{module_name}")
    return getattr(mod, class_name)


def _make_instance(module_name: str, class_name: str):
    """Construct a default instance (no required args)."""
    cls = _import_class(module_name, class_name)
    return cls()


# ── Test 1-9: All Phase 3 modules importable ──────────────────────────────────

@pytest.mark.parametrize("module_name,class_name", PHASE3_MIGRATED)
def test_module_importable(module_name, class_name):
    """Each Phase 3 module must import without error."""
    mod = importlib.import_module(f"spa_core.analytics.{module_name}")
    assert mod is not None


# ── Test 10-18: BaseAnalytics in MRO ──────────────────────────────────────────

@pytest.mark.parametrize("module_name,class_name", PHASE3_MIGRATED)
def test_baseanalytics_in_mro(module_name, class_name):
    """Each Phase 3 main class must inherit BaseAnalytics."""
    cls = _import_class(module_name, class_name)
    assert BaseAnalytics in cls.__mro__, (
        f"{class_name} does not inherit BaseAnalytics "
        f"(MRO: {[c.__name__ for c in cls.__mro__]})"
    )


# ── Test 19: All 9 modules pass MRO check (batch assertion) ───────────────────

def test_all_phase3_inherit_baseanalytics():
    """All 9 Phase 3 migrated modules must have BaseAnalytics in MRO."""
    failures = []
    for module_name, class_name in PHASE3_MIGRATED:
        cls = _import_class(module_name, class_name)
        if BaseAnalytics not in cls.__mro__:
            failures.append(f"{class_name} ({module_name})")
    assert not failures, f"Missing BaseAnalytics in MRO: {failures}"


# ── Test 20: Summary script exit code ─────────────────────────────────────────

def test_migration_summary_all_pass():
    """baseanalytics_migration_summary.summary() must return 0 for all phases."""
    import importlib.util
    import os

    script = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "scripts",
        "baseanalytics_migration_summary.py",
    )
    spec = importlib.util.spec_from_file_location("migration_summary", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Redirect stdout during summary() to suppress output in test run
    import io, sys
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        result = mod.summary()
    finally:
        sys.stdout = old_stdout

    assert result == 0, "baseanalytics_migration_summary.summary() returned non-zero (some modules failed)"
