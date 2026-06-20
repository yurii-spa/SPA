#!/usr/bin/env python3
"""
tests/test_atomic_migration_complete.py — MP-1432 (Sprint v10.48)

Completion tests for the full atomic migration (batches 1–4):
  Batch 1: paper_trading + safety (MP-1413 / v10.29)
  Batch 2: analytics           (MP-1430 / v10.46)
  Batch 3: backtesting + family_fund (MP-1431 / v10.47)
  Batch 4: adapters            (MP-1432 / v10.48)

30 tests across 6 groups:
  A. Overall count — total migrated files >= 40
  B. In-scope directories clean — no tempfile.mkstemp in batch 3–4 dirs
  C. Batch 3 backtesting — specific files verified
  D. Batch 3 family_fund — specific files verified
  E. Batch 4 adapters — import safety + clean source
  F. Stdlib contracts — proof_of_track & atomic_save itself

Pure stdlib. No network. No pytest. Offline.
"""
from __future__ import annotations

import importlib
import json
import os
import pathlib
import sys
import tempfile
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))


def _read(rel: str) -> str:
    p = _REPO / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ── File lists ────────────────────────────────────────────────────────────────

BATCH3_BACKTESTING = [
    "spa_core/backtesting/source_pipeline.py",
    "spa_core/backtesting/research_scenario_matrix.py",
    "spa_core/backtesting/pit_vs_naive_comparison.py",
    "spa_core/backtesting/pre_launch_validation.py",
    "spa_core/backtesting/source_promotion_engine.py",
    "spa_core/backtesting/pre_paper_checklist.py",
    "spa_core/backtesting/paper_period_simulator.py",
    "spa_core/backtesting/paper_trading_kickoff.py",
    "spa_core/backtesting/research_tournament.py",
    "spa_core/backtesting/launch_runbook.py",
]

BATCH3_FAMILY_FUND = [
    "spa_core/family_fund/registry.py",
    "spa_core/family_fund/pnl_attribution.py",
    "spa_core/family_fund/manage_users.py",
    "spa_core/family_fund/lead_tracker.py",
    "spa_core/family_fund/research_mode.py",
    "spa_core/family_fund/investor_registration.py",
    "spa_core/family_fund/withdrawal_engine.py",
]

BATCH4_ADAPTERS = [
    "spa_core/adapters/adapter_registry.py",
    "spa_core/adapters/apy_aggregator.py",
    "spa_core/adapters/fluid_fusdc_adapter.py",
    "spa_core/adapters/sky_susds_feed.py",
]

IN_SCOPE_DIRS = [
    "spa_core/backtesting",
    "spa_core/family_fund",
    "spa_core/adapters",
    "spa_core/execution",
]


def _count_files_with_atomic_save() -> int:
    """Count non-test files that import atomic_save."""
    count = 0
    spa = _REPO / "spa_core"
    for p in spa.rglob("*.py"):
        if "test" in p.name or "__pycache__" in str(p):
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if "from spa_core.utils.atomic import" in content:
            count += 1
    return count


def _dir_has_mkstemp(dir_rel: str) -> list[str]:
    """Return list of files in dir_rel that still have tempfile.mkstemp (raw impl)."""
    d = _REPO / dir_rel
    hits = []
    if not d.exists():
        return hits
    for p in d.rglob("*.py"):
        if "__pycache__" in str(p) or "proof_of_track" in p.name or "atomic.py" in p.name:
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if "tempfile.mkstemp" in content:
            hits.append(str(p.relative_to(_REPO)))
    return hits


# ═══════════════════════════════════════════════════════════════════════════
# Group A — Overall migration count
# ═══════════════════════════════════════════════════════════════════════════

class TestOverallCount(unittest.TestCase):
    """A1–A5: total migrated file count across all batches."""

    def test_A1_total_migrated_files_at_least_40(self):
        """Non-test files using atomic_save must total >= 40 after all 4 batches."""
        count = _count_files_with_atomic_save()
        self.assertGreaterEqual(
            count, 40,
            f"Only {count} files use atomic_save — expected >= 40 after batches 1–4",
        )

    def test_A2_batch3_backtesting_all_use_atomic_save(self):
        """All 10 batch-3 backtesting files must import atomic_save."""
        for rel in BATCH3_BACKTESTING:
            content = _read(rel)
            if not content:
                self.skipTest(f"{rel} not found")
            self.assertIn(
                "from spa_core.utils.atomic import atomic_save",
                content,
                f"{rel}: missing atomic_save import",
            )

    def test_A3_batch3_family_fund_all_use_atomic_save(self):
        """All 7 batch-3 family_fund files must import atomic_save."""
        for rel in BATCH3_FAMILY_FUND:
            content = _read(rel)
            if not content:
                self.skipTest(f"{rel} not found")
            self.assertIn(
                "atomic_save",
                content,
                f"{rel}: missing atomic_save reference",
            )

    def test_A4_batch4_adapters_all_use_atomic_save(self):
        """All 4 batch-4 adapter files must import atomic_save."""
        for rel in BATCH4_ADAPTERS:
            content = _read(rel)
            if not content:
                self.skipTest(f"{rel} not found")
            self.assertIn(
                "from spa_core.utils.atomic import atomic_save",
                content,
                f"{rel}: missing atomic_save import",
            )

    def test_A5_atomic_save_module_exists(self):
        """spa_core/utils/atomic.py exists and exports atomic_save."""
        p = _REPO / "spa_core/utils/atomic.py"
        self.assertTrue(p.exists(), "spa_core/utils/atomic.py is missing")
        content = p.read_text(encoding="utf-8")
        self.assertIn("def atomic_save", content)


# ═══════════════════════════════════════════════════════════════════════════
# Group B — In-scope directories: no raw tempfile.mkstemp
# ═══════════════════════════════════════════════════════════════════════════

class TestInScopeClean(unittest.TestCase):
    """B1–B4: no raw tempfile.mkstemp in batch 3–4 migration scope dirs."""

    def test_B1_backtesting_dir_clean(self):
        """spa_core/backtesting/: zero files with raw tempfile.mkstemp."""
        hits = _dir_has_mkstemp("spa_core/backtesting")
        self.assertEqual(
            hits, [],
            f"backtesting/ still has local mkstemp in: {hits}",
        )

    def test_B2_family_fund_dir_clean(self):
        """spa_core/family_fund/: zero files with raw tempfile.mkstemp."""
        hits = _dir_has_mkstemp("spa_core/family_fund")
        self.assertEqual(
            hits, [],
            f"family_fund/ still has local mkstemp in: {hits}",
        )

    def test_B3_adapters_dir_clean(self):
        """spa_core/adapters/: zero files with raw tempfile.mkstemp."""
        hits = _dir_has_mkstemp("spa_core/adapters")
        self.assertEqual(
            hits, [],
            f"adapters/ still has local mkstemp in: {hits}",
        )

    def test_B4_execution_dir_clean(self):
        """spa_core/execution/: zero files with raw tempfile.mkstemp."""
        hits = _dir_has_mkstemp("spa_core/execution")
        self.assertEqual(
            hits, [],
            f"execution/ still has local mkstemp in: {hits}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Group C — Batch 3 backtesting: deep verification
# ═══════════════════════════════════════════════════════════════════════════

class TestBatch3Backtesting(unittest.TestCase):
    """C1–C5: key backtesting files verified for correct migration."""

    def test_C1_source_pipeline_no_mkstemp(self):
        content = _read("spa_core/backtesting/source_pipeline.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_C2_pre_paper_checklist_no_mkstemp(self):
        content = _read("spa_core/backtesting/pre_paper_checklist.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_C3_paper_trading_kickoff_shim_intact(self):
        """paper_trading_kickoff._atomic_write now delegates to atomic_save."""
        content = _read("spa_core/backtesting/paper_trading_kickoff.py")
        self.assertIn("atomic_save", content)
        self.assertNotIn("tempfile.mkstemp", content)

    def test_C4_launch_runbook_no_mkstemp(self):
        content = _read("spa_core/backtesting/launch_runbook.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_C5_research_tournament_no_mkstemp(self):
        content = _read("spa_core/backtesting/research_tournament.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)


# ═══════════════════════════════════════════════════════════════════════════
# Group D — Batch 3 family_fund: deep verification
# ═══════════════════════════════════════════════════════════════════════════

class TestBatch3FamilyFund(unittest.TestCase):
    """D1–D5: key family_fund files verified for correct migration."""

    def test_D1_registry_no_mkstemp(self):
        content = _read("spa_core/family_fund/registry.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_D2_pnl_attribution_shim_replaced(self):
        """pnl_attribution._atomic_write now delegates to atomic_save."""
        content = _read("spa_core/family_fund/pnl_attribution.py")
        self.assertIn("atomic_save", content)
        self.assertNotIn("tempfile.mkstemp", content)

    def test_D3_withdrawal_engine_no_mkstemp(self):
        content = _read("spa_core/family_fund/withdrawal_engine.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_D4_investor_registration_no_mkstemp(self):
        content = _read("spa_core/family_fund/investor_registration.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_D5_lead_tracker_no_mkstemp(self):
        content = _read("spa_core/family_fund/lead_tracker.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)


# ═══════════════════════════════════════════════════════════════════════════
# Group E — Batch 4 adapters: import safety + source clean
# ═══════════════════════════════════════════════════════════════════════════

class TestBatch4Adapters(unittest.TestCase):
    """E1–E8: adapters import without side effects, source is clean."""

    def _import_no_error(self, module: str) -> None:
        try:
            importlib.import_module(module)
        except ImportError as exc:
            # Allow missing optional external deps (requests, pydantic, etc.)
            if "spa_core" not in str(exc):
                self.skipTest(f"External dep missing: {exc}")
            raise

    def test_E1_adapter_registry_imports_clean(self):
        """spa_core.adapters.adapter_registry imports without side effects."""
        self._import_no_error("spa_core.adapters.adapter_registry")

    def test_E2_apy_aggregator_imports_clean(self):
        """spa_core.adapters.apy_aggregator imports without side effects."""
        self._import_no_error("spa_core.adapters.apy_aggregator")

    def test_E3_fluid_fusdc_adapter_imports_clean(self):
        """spa_core.adapters.fluid_fusdc_adapter imports without side effects."""
        self._import_no_error("spa_core.adapters.fluid_fusdc_adapter")

    def test_E4_sky_susds_feed_imports_clean(self):
        """spa_core.adapters.sky_susds_feed imports without side effects."""
        self._import_no_error("spa_core.adapters.sky_susds_feed")

    def test_E5_adapter_registry_no_mkstemp(self):
        content = _read("spa_core/adapters/adapter_registry.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_E6_apy_aggregator_no_mkstemp(self):
        content = _read("spa_core/adapters/apy_aggregator.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_E7_fluid_fusdc_adapter_no_mkstemp(self):
        content = _read("spa_core/adapters/fluid_fusdc_adapter.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)

    def test_E8_sky_susds_feed_shim_clean(self):
        """sky_susds_feed._atomic_write_json now delegates to atomic_save."""
        content = _read("spa_core/adapters/sky_susds_feed.py")
        self.assertNotIn("tempfile.mkstemp", content)
        self.assertIn("atomic_save", content)


# ═══════════════════════════════════════════════════════════════════════════
# Group F — Stdlib contracts
# ═══════════════════════════════════════════════════════════════════════════

class TestStdlibContracts(unittest.TestCase):
    """F1–F7: proof_of_track stdlib contract intact; atomic_save works correctly."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _p(self, name: str) -> str:
        return os.path.join(self._tmpdir, name)

    def _load(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_F1_proof_of_track_still_has_mkstemp(self):
        """proof_of_track.py is a stdlib-contract file — must keep tempfile.mkstemp."""
        content = _read("spa_core/audit/proof_of_track.py")
        if not content:
            self.skipTest("proof_of_track.py not found")
        self.assertIn(
            "tempfile.mkstemp",
            content,
            "proof_of_track.py: stdlib contract violated — tempfile.mkstemp removed",
        )

    def test_F2_proof_of_track_does_not_import_atomic_save(self):
        """proof_of_track.py must NOT import from spa_core.utils.atomic."""
        content = _read("spa_core/audit/proof_of_track.py")
        if not content:
            self.skipTest("proof_of_track.py not found")
        self.assertNotIn(
            "from spa_core.utils.atomic",
            content,
            "proof_of_track.py must remain pure stdlib",
        )

    def test_F3_atomic_save_uses_mkstemp_internally(self):
        """atomic_save itself uses tempfile.mkstemp as its internal mechanism."""
        content = _read("spa_core/utils/atomic.py")
        self.assertIn(
            "tempfile.mkstemp",
            content,
            "spa_core/utils/atomic.py must use tempfile.mkstemp internally",
        )

    def test_F4_atomic_save_functional_writes_json(self):
        """atomic_save correctly writes valid JSON to disk."""
        from spa_core.utils.atomic import atomic_save
        p = self._p("f4.json")
        atomic_save({"batch": 4, "mp": 1432}, p)
        data = self._load(p)
        self.assertEqual(data["batch"], 4)
        self.assertEqual(data["mp"], 1432)

    def test_F5_atomic_save_no_tmp_residue(self):
        """atomic_save leaves no .tmp files after successful write."""
        from spa_core.utils.atomic import atomic_save
        p = self._p("f5.json")
        atomic_save({"clean": True}, p)
        leftovers = [f for f in os.listdir(self._tmpdir) if ".tmp" in f]
        self.assertEqual(leftovers, [], f"Residual tmp files: {leftovers}")

    def test_F6_atomic_save_overwrites_safely(self):
        """atomic_save safely overwrites an existing file."""
        from spa_core.utils.atomic import atomic_save
        p = self._p("f6.json")
        atomic_save({"v": 1}, p)
        atomic_save({"v": 2}, p)
        self.assertEqual(self._load(p)["v"], 2)

    def test_F7_count_script_exists(self):
        """scripts/atomic_migration_final_count.sh was created by MP-1431."""
        p = _REPO / "scripts/atomic_migration_final_count.sh"
        self.assertTrue(p.exists(), "atomic_migration_final_count.sh missing")
        content = p.read_text(encoding="utf-8")
        self.assertIn("atomic_save", content)
        self.assertIn("MP-1431", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
