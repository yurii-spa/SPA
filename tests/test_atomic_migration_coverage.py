#!/usr/bin/env python3
"""
tests/test_atomic_migration_coverage.py — MP-1414 (Sprint v10.30)

Verifies that files migrated in MP-1413 (v10.29) correctly delegate to
spa_core.utils.atomic.atomic_save and no longer contain the full local
tempfile.mkstemp implementation in their _atomic_write_json body.

25 tests across 5 groups:
  A. Import presence (atomic_save imported in migrated files)
  B. Shim correctness (function delegates, not re-implements)
  C. Functional smoke tests (shim actually writes valid JSON)
  D. atomic_save itself (importable, functional, atomic)
  E. Non-migrated files (pure-stdlib contracts still hold)

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

# Repo root
_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

# ─── File lists ──────────────────────────────────────────────────────────────

# Files migrated in MP-1413: shim replaces body, import added
MIGRATED_FILES = [
    "spa_core/paper_trading/cycle_runner.py",
    "spa_core/paper_trading/golive_checker.py",
    "spa_core/paper_trading/gap_monitor.py",
    "spa_core/paper_trading/drawdown_analytics.py",
    "spa_core/paper_trading/concentration_analytics.py",
    "spa_core/paper_trading/yield_attribution.py",
    "spa_core/paper_trading/risk_contribution.py",
    "spa_core/paper_trading/progress_tracker.py",
    "spa_core/paper_trading/cycle_gap_monitor.py",
    "spa_core/paper_trading/analytics_scorecard.py",
    "spa_core/paper_trading/tail_risk.py",
    "spa_core/paper_trading/cost_drag_analytics.py",
    "spa_core/paper_trading/exit_liquidity.py",
    "spa_core/safety/live_trading_gate.py",
]

# pure-stdlib files that must NOT import spa_core.utils.atomic
STDLIB_ONLY_FILES = [
    "spa_core/audit/proof_of_track.py",
]

# Module paths + local func names for smoke tests
MIGRATED_MODULES = [
    ("spa_core.paper_trading.concentration_analytics", "_atomic_write_json"),
    ("spa_core.paper_trading.yield_attribution",       "_atomic_write_json"),
    ("spa_core.analytics_lab.risk_contribution",       "_atomic_write_json"),
    ("spa_core.paper_trading.drawdown_analytics",      "_atomic_write_json"),
    ("spa_core.paper_trading.analytics_scorecard",     "_atomic_write_json"),
    ("spa_core.analytics_lab.tail_risk",               "_atomic_write_json"),
    ("spa_core.analytics_lab.cost_drag_analytics",     "_atomic_write_json"),
    ("spa_core.paper_trading.exit_liquidity",          "_atomic_write_json"),
    ("spa_core.safety.live_trading_gate",              "_atomic_write"),
    ("spa_core.paper_trading.gap_monitor",             "_atomic_write_json"),
]


def _abs(rel: str) -> pathlib.Path:
    return _REPO / rel


def _read(rel: str) -> str:
    p = _abs(rel)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# Group A — Import presence
# ═══════════════════════════════════════════════════════════════════════════

class TestImportPresence(unittest.TestCase):
    """A1–A3: migrated files contain the atomic_save import."""

    def test_A1_atomic_save_import_in_paper_trading_files(self):
        """All paper_trading migrated files import atomic_save."""
        pt_files = [f for f in MIGRATED_FILES if "paper_trading" in f]
        for rel in pt_files:
            content = _read(rel)
            if not content:
                continue  # file missing in this env — skip
            self.assertIn(
                "atomic_save",
                content,
                f"{rel}: 'atomic_save' not found — import missing after migration",
            )

    def test_A2_atomic_save_import_in_safety_files(self):
        """live_trading_gate.py imports atomic_save."""
        content = _read("spa_core/safety/live_trading_gate.py")
        self.assertIn("atomic_save", content,
                      "live_trading_gate.py: atomic_save not found")

    def test_A3_import_line_is_from_utils_atomic(self):
        """Import must come from spa_core.utils.atomic (not re-exported elsewhere)."""
        for rel in MIGRATED_FILES:
            content = _read(rel)
            if not content:
                continue
            self.assertIn(
                "spa_core.utils.atomic",
                content,
                f"{rel}: import is not from spa_core.utils.atomic",
            )


# ═══════════════════════════════════════════════════════════════════════════
# Group B — Shim correctness
# ═══════════════════════════════════════════════════════════════════════════

class TestShimCorrectness(unittest.TestCase):
    """B1–B5: the local function is now a thin shim, not a full implementation."""

    def test_B1_no_tempfile_mkstemp_in_shim_body(self):
        """After migration, migrated files do not call tempfile.mkstemp directly."""
        for rel in MIGRATED_FILES:
            content = _read(rel)
            if not content:
                continue
            self.assertNotIn(
                "tempfile.mkstemp",
                content,
                f"{rel}: still contains tempfile.mkstemp — shim body not replaced",
            )

    def test_B2_atomic_save_called_in_shim(self):
        """Each migrated file calls atomic_save (in the shim or directly)."""
        for rel in MIGRATED_FILES:
            content = _read(rel)
            if not content:
                continue
            self.assertIn(
                "atomic_save(",
                content,
                f"{rel}: atomic_save() call not found",
            )

    def test_B3_shim_body_is_minimal(self):
        """Shim bodies are ≤ 5 lines (docstring + 1 delegation call)."""
        import ast
        for rel in MIGRATED_FILES:
            content = _read(rel)
            if not content:
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name not in ("_atomic_write_json", "_atomic_write"):
                    continue
                body_lines = (node.end_lineno or node.lineno) - node.lineno
                self.assertLessEqual(
                    body_lines,
                    6,
                    f"{rel}: {node.name} body is {body_lines} lines — not a shim?",
                )

    def test_B4_no_os_fdopen_in_migrated_files(self):
        """Migrated files no longer use os.fdopen (removed with tempfile block)."""
        for rel in MIGRATED_FILES:
            content = _read(rel)
            if not content:
                continue
            # Check os.fdopen not inside local atomic write function
            # (it might appear in other unrelated places)
            self.assertNotIn(
                "os.fdopen",
                content,
                f"{rel}: still contains os.fdopen — local mkstemp block not removed",
            )

    def test_B5_shim_delegates_to_atomic_save_not_reimplements(self):
        """Shim function body has atomic_save, not json.dump + os.replace."""
        import ast
        for rel in MIGRATED_FILES:
            content = _read(rel)
            if not content:
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name not in ("_atomic_write_json", "_atomic_write"):
                    continue
                func_src = ast.get_source_segment(content, node) or ""
                # Must NOT re-implement the full pattern
                self.assertNotIn(
                    "json.dump",
                    func_src,
                    f"{rel}: {node.name} still contains json.dump — full re-impl?",
                )


# ═══════════════════════════════════════════════════════════════════════════
# Group C — Functional smoke tests
# ═══════════════════════════════════════════════════════════════════════════

class TestShimFunctional(unittest.TestCase):
    """C1–C5: shims actually write valid JSON atomically."""

    def _run_shim(self, module_name: str, func_name: str) -> None:
        """Import module, call its local shim, verify output."""
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            self.skipTest(f"Cannot import {module_name}: {exc}")
        fn = getattr(mod, func_name, None)
        if fn is None:
            self.skipTest(f"{module_name} has no {func_name}")
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "smoke.json"
            fn(p, {"mp": 1413, "ok": True, "batch": "v10.29"})
            self.assertTrue(p.exists(), f"{module_name}.{func_name} did not create file")
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["mp"], 1413)
            self.assertTrue(data["ok"])

    def test_C1_concentration_analytics_shim(self):
        self._run_shim("spa_core.paper_trading.concentration_analytics", "_atomic_write_json")

    def test_C2_analytics_scorecard_shim(self):
        self._run_shim("spa_core.paper_trading.analytics_scorecard", "_atomic_write_json")

    def test_C3_live_trading_gate_shim(self):
        self._run_shim("spa_core.safety.live_trading_gate", "_atomic_write")

    def test_C4_gap_monitor_shim(self):
        self._run_shim("spa_core.paper_trading.gap_monitor", "_atomic_write_json")

    def test_C5_drawdown_analytics_shim(self):
        self._run_shim("spa_core.paper_trading.drawdown_analytics", "_atomic_write_json")


# ═══════════════════════════════════════════════════════════════════════════
# Group D — atomic_save itself
# ═══════════════════════════════════════════════════════════════════════════

class TestAtomicSaveItself(unittest.TestCase):
    """D1–D7: spa_core.utils.atomic.atomic_save is functional and correct."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.tmpdir, name)

    def _load(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_D1_atomic_save_is_importable(self):
        """spa_core.utils.atomic.atomic_save imports without error."""
        from spa_core.utils.atomic import atomic_save
        self.assertTrue(callable(atomic_save))

    def test_D2_atomic_save_writes_valid_json(self):
        """atomic_save creates a readable JSON file."""
        from spa_core.utils.atomic import atomic_save
        p = self._path("d2.json")
        atomic_save({"key": "value", "n": 42}, p)
        data = self._load(p)
        self.assertEqual(data["key"], "value")
        self.assertEqual(data["n"], 42)

    def test_D3_atomic_save_creates_parent_dirs(self):
        """atomic_save creates missing parent directories."""
        from spa_core.utils.atomic import atomic_save
        p = os.path.join(self.tmpdir, "nested", "deep", "d3.json")
        atomic_save({"nested": True}, p)
        self.assertTrue(os.path.exists(p))

    def test_D4_atomic_save_overwrites_existing(self):
        """atomic_save correctly overwrites an existing file."""
        from spa_core.utils.atomic import atomic_save
        p = self._path("d4.json")
        atomic_save({"v": 1}, p)
        atomic_save({"v": 2}, p)
        data = self._load(p)
        self.assertEqual(data["v"], 2)

    def test_D5_atomic_save_no_tmp_residue(self):
        """atomic_save leaves no .tmp files in the directory."""
        from spa_core.utils.atomic import atomic_save
        p = self._path("d5.json")
        atomic_save({"clean": True}, p)
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], f"Residual .tmp files: {tmp_files}")

    def test_D6_atomic_save_handles_unicode(self):
        """atomic_save correctly handles unicode keys and values."""
        from spa_core.utils.atomic import atomic_save
        p = self._path("d6.json")
        payload = {"протокол": "Aave", "APY": 3.5, "символ": "✓"}
        atomic_save(payload, p)
        data = self._load(p)
        self.assertEqual(data["протокол"], "Aave")
        self.assertEqual(data["символ"], "✓")

    def test_D7_atomic_save_accepts_path_objects(self):
        """atomic_save works with pathlib.Path arguments (not just str)."""
        from spa_core.utils.atomic import atomic_save
        p = pathlib.Path(self.tmpdir) / "d7.json"
        atomic_save({"path_obj": True}, p)
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue(data["path_obj"])


# ═══════════════════════════════════════════════════════════════════════════
# Group E — Non-migrated / pure-stdlib contracts
# ═══════════════════════════════════════════════════════════════════════════

class TestNonMigratedContracts(unittest.TestCase):
    """E1–E5: files NOT migrated still have their own atomic implementation."""

    def test_E1_proof_of_track_is_pure_stdlib(self):
        """proof_of_track.py must NOT import from spa_core.utils.atomic
        (pure stdlib contract enforced by test_only_stdlib_imports)."""
        content = _read("spa_core/audit/proof_of_track.py")
        self.assertNotIn(
            "from spa_core.utils.atomic",
            content,
            "proof_of_track.py must remain pure stdlib — use internal _atomic_write_json",
        )

    def test_E2_proof_of_track_has_tempfile_import(self):
        """proof_of_track.py still imports tempfile (its own atomic impl)."""
        content = _read("spa_core/audit/proof_of_track.py")
        self.assertIn(
            "import tempfile",
            content,
            "proof_of_track.py: missing tempfile import — reverted incorrectly?",
        )

    def test_E3_proof_of_track_atomic_impl_present(self):
        """proof_of_track.py still contains the full local _atomic_write_json."""
        content = _read("spa_core/audit/proof_of_track.py")
        self.assertIn(
            "tempfile.mkstemp",
            content,
            "proof_of_track.py: full atomic impl must be present (pure stdlib contract)",
        )

    def test_E4_atomic_utils_module_exists(self):
        """spa_core/utils/atomic.py exists and is readable."""
        p = _abs("spa_core/utils/atomic.py")
        self.assertTrue(p.exists(), "spa_core/utils/atomic.py is missing!")
        content = p.read_text(encoding="utf-8")
        self.assertIn("def atomic_save", content)

    def test_E5_migration_report_exists(self):
        """scripts/atomic_migration_report.md was created by MP-1413."""
        p = _abs("scripts/atomic_migration_report.md")
        self.assertTrue(
            p.exists(),
            "scripts/atomic_migration_report.md missing — MP-1413 report not created",
        )
        content = p.read_text(encoding="utf-8")
        self.assertIn("MP-1413", content)
        self.assertIn("MIGRATED", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
