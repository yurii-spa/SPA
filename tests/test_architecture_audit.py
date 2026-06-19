"""
tests/test_architecture_audit.py

35 unit tests for spa_core/analytics/architecture_audit.py

MP-1374 (v9.90) — stdlib only, unittest.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on path for importing spa_core
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.architecture_audit import (
    ArchitectureAudit,
    AuditViolation,
    AUDIT_RULES,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_py(directory: str, filename: str, content: str) -> str:
    """Write a Python file to a directory and return its path."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _make_mini_spa(tmp: str) -> str:
    """Create a minimal spa_core-like directory tree and return its path."""
    spa = os.path.join(tmp, "spa_core")
    adapters = os.path.join(spa, "adapters")
    tests_dir = os.path.join(tmp, "tests")
    os.makedirs(adapters, exist_ok=True)
    os.makedirs(tests_dir, exist_ok=True)
    _write_py(spa, "__init__.py", "")
    _write_py(adapters, "__init__.py", "")
    _write_py(adapters, "aave_v3.py", "from .base_adapter import BaseAdapter\n")
    _write_py(tests_dir, "test_sample.py", "import unittest\n\nclass T(unittest.TestCase): pass\n")
    return spa


# ── ArchitectureAudit construction ───────────────────────────────────────────

class TestArchitectureAuditConstruction(unittest.TestCase):

    def test_created_with_default_base_dir(self):
        """ArchitectureAudit can be instantiated with default base_dir."""
        audit = ArchitectureAudit()
        self.assertIsInstance(audit, ArchitectureAudit)

    def test_created_with_explicit_base_dir(self):
        """ArchitectureAudit accepts an explicit base_dir string."""
        with tempfile.TemporaryDirectory() as tmp:
            spa = _make_mini_spa(tmp)
            audit = ArchitectureAudit(base_dir=spa)
            self.assertIsInstance(audit, ArchitectureAudit)

    def test_audit_rules_constant_is_list(self):
        """AUDIT_RULES is a non-empty list of strings."""
        self.assertIsInstance(AUDIT_RULES, list)
        self.assertGreater(len(AUDIT_RULES), 0)
        for rule in AUDIT_RULES:
            self.assertIsInstance(rule, str)

    def test_audit_violation_dataclass(self):
        """AuditViolation dataclass can be instantiated."""
        v = AuditViolation(
            rule="no_third_party_imports",
            file="spa_core/adapters/foo.py",
            line=42,
            message="Import of 'requests' found",
            severity="ERROR",
        )
        self.assertEqual(v.rule, "no_third_party_imports")
        self.assertEqual(v.severity, "ERROR")

    def test_audit_violation_to_dict(self):
        """AuditViolation.to_dict() returns a plain dict."""
        v = AuditViolation(rule="r", file="f", line=1, message="m", severity="WARNING")
        d = v.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("rule", d)
        self.assertIn("severity", d)


# ── check_no_third_party() ───────────────────────────────────────────────────

class TestCheckNoThirdParty(unittest.TestCase):

    def test_returns_list(self):
        """check_no_third_party() always returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_no_third_party()
        self.assertIsInstance(result, list)

    def test_clean_file_produces_no_violation(self):
        """File with only stdlib imports is clean."""
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "clean.py", "import os\nimport json\n")
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_no_third_party()
        self.assertEqual(violations, [])

    def test_known_third_party_import_flagged(self):
        """File in a runtime subdir importing 'requests' is flagged as ERROR."""
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            # Must be in a _STDLIB_ONLY_SUBDIRS directory (e.g. risk/)
            risk_dir = os.path.join(spa, "risk")
            _write_py(risk_dir, "bad.py", "import requests\n")
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_no_third_party()
        self.assertTrue(len(violations) > 0)
        self.assertTrue(all(v.severity == "ERROR" for v in violations))

    def test_spa_core_internal_import_not_flagged(self):
        """Internal spa_core imports are allowed."""
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "internal.py",
                       "from spa_core.adapters.aave_v3 import AaveV3Adapter\n")
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_no_third_party()
        self.assertEqual(violations, [])

    def test_real_spa_core_returns_list(self):
        """check_no_third_party on real codebase returns list (may be empty)."""
        audit = ArchitectureAudit()
        result = audit.check_no_third_party()
        self.assertIsInstance(result, list)


# ── check_atomic_writes() ────────────────────────────────────────────────────

class TestCheckAtomicWrites(unittest.TestCase):

    def test_returns_list(self):
        """check_atomic_writes() always returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_atomic_writes()
        self.assertIsInstance(result, list)

    def test_safe_atomic_write_not_flagged(self):
        """open(..., 'w') in a tmp+os.replace context is not flagged."""
        src = (
            "import os, tempfile\n"
            "fd, tmp = tempfile.mkstemp()\n"
            "with open(tmp, 'w') as f:\n"
            "    f.write('data')\n"
            "os.replace(tmp, 'target.json')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "atomic.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_atomic_writes()
        self.assertEqual(violations, [])

    def test_unsafe_write_flagged(self):
        """Direct open(path, 'w') without tmp is flagged."""
        src = (
            "with open('output.json', 'w') as f:\n"
            "    f.write('data')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "unsafe.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_atomic_writes()
        self.assertTrue(len(violations) > 0)

    def test_violations_have_warning_severity(self):
        """Atomic write violations are WARNING (not ERROR)."""
        src = "with open('out.json', 'w') as f: f.write('{}')\n"
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "uw.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_atomic_writes()
        if violations:
            self.assertTrue(all(v.severity == "WARNING" for v in violations))

    def test_real_spa_core_returns_list(self):
        """check_atomic_writes on real codebase returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_atomic_writes()
        self.assertIsInstance(result, list)


# ── check_no_hardcoded_secrets() ─────────────────────────────────────────────

class TestCheckNoHardcodedSecrets(unittest.TestCase):

    def test_returns_list(self):
        """check_no_hardcoded_secrets() always returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_no_hardcoded_secrets()
        self.assertIsInstance(result, list)

    def test_clean_file_produces_no_violation(self):
        """File with no secret assignments is clean."""
        src = "import os\nTOKEN = os.getenv('GITHUB_PAT')\n"
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "clean.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_no_hardcoded_secrets()
        self.assertEqual(violations, [])

    def test_github_pat_variable_name_not_flagged(self):
        """Variable named GITHUB_PAT is not flagged (it's a variable, not a value)."""
        src = (
            "import subprocess\n"
            "GITHUB_PAT = subprocess.check_output(\n"
            "    ['security', 'find-generic-password', '-s', 'GITHUB_PAT_SPA', '-w']\n"
            ").strip().decode()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "pat_reader.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_no_hardcoded_secrets()
        self.assertEqual(violations, [])

    def test_fake_token_in_test_not_flagged(self):
        """Fake tokens in test files are not flagged."""
        src = 'token="fake-token-123"\n'
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            _write_py(spa, "test_my_module.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_no_hardcoded_secrets()
        self.assertEqual(violations, [])

    def test_hardcoded_password_flagged(self):
        """A hardcoded password value IS flagged when found in a scanned dir."""
        src = 'db_password = "superSecret99!!"\n'
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            # Create a subdirectory that IS in _STDLIB_ONLY_SUBDIRS (e.g. risk/)
            risk_dir = os.path.join(spa, "risk")
            _write_py(risk_dir, "db_config.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_no_hardcoded_secrets()
        self.assertTrue(len(violations) > 0)
        self.assertTrue(all(v.severity == "ERROR" for v in violations))

    def test_real_spa_core_returns_list(self):
        """check_no_hardcoded_secrets on real codebase returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_no_hardcoded_secrets()
        self.assertIsInstance(result, list)


# ── check_adapters_research_flag() ───────────────────────────────────────────

class TestCheckAdaptersResearchFlag(unittest.TestCase):

    def test_returns_list(self):
        """check_adapters_research_flag() always returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_adapters_research_flag()
        self.assertIsInstance(result, list)

    def test_research_adapter_with_flag_is_clean(self):
        """Research adapter declaring RESEARCH_ONLY = True produces no violation."""
        src = (
            '"""Research adapter."""\n'
            "RESEARCH_ONLY: bool = True\n\n"
            "class FooResearch: pass\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            adapters = os.path.join(spa, "adapters")
            os.makedirs(adapters)
            _write_py(adapters, "foo_research.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_adapters_research_flag()
        self.assertEqual(violations, [])

    def test_research_adapter_without_flag_flagged(self):
        """Research adapter missing RESEARCH_ONLY is flagged as ERROR."""
        src = '"""Research adapter without flag."""\n\nclass BarResearch: pass\n'
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            adapters = os.path.join(spa, "adapters")
            os.makedirs(adapters)
            _write_py(adapters, "bar_research.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_adapters_research_flag()
        self.assertTrue(len(violations) > 0)
        self.assertTrue(all(v.severity == "ERROR" for v in violations))

    def test_non_research_adapter_not_checked(self):
        """Non-research adapters are not checked for the flag."""
        src = "class AaveV3Adapter: pass\n"
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            adapters = os.path.join(spa, "adapters")
            os.makedirs(adapters)
            _write_py(adapters, "aave_v3.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.check_adapters_research_flag()
        self.assertEqual(violations, [])

    def test_real_spa_core_adapters(self):
        """check_adapters_research_flag on real codebase returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_adapters_research_flag()
        self.assertIsInstance(result, list)


# ── check_tests_use_unittest() ───────────────────────────────────────────────

class TestCheckTestsUseUnittest(unittest.TestCase):

    def test_returns_list(self):
        """check_tests_use_unittest() always returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_tests_use_unittest()
        self.assertIsInstance(result, list)

    def test_proper_unittest_file_is_clean(self):
        """Test file importing unittest produces no violation."""
        src = (
            "import unittest\n\n"
            "class MyTest(unittest.TestCase):\n"
            "    def test_foo(self): pass\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            tests_dir = os.path.join(tmp, "tests")
            os.makedirs(spa)
            os.makedirs(tests_dir)
            _write_py(tests_dir, "test_foo.py", src)
            # Monkey-patch repo root to use our tmp dir
            audit = ArchitectureAudit(base_dir=spa)
            audit._repo_root = Path(tmp)
            violations = audit.check_tests_use_unittest()
        self.assertEqual(violations, [])

    def test_test_without_any_test_structure_flagged(self):
        """Test file with no unittest/pytest/def test_/class Test is flagged."""
        # This file has content but no recognizable test structure
        src = "\n".join([
            "import os",
            "import json",
            "# This is a test file but has no test structure",
            "SOME_CONSTANT = 42",
            "def helper(): return True",
            "def another_helper(): pass",
            "def not_a_test(): pass",
            "# end of file",
        ]) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            spa = os.path.join(tmp, "spa_core")
            tests_dir = os.path.join(tmp, "tests")
            os.makedirs(spa)
            os.makedirs(tests_dir)
            _write_py(tests_dir, "test_bare.py", src)
            audit = ArchitectureAudit(base_dir=spa)
            audit._repo_root = Path(tmp)
            violations = audit.check_tests_use_unittest()
        self.assertTrue(len(violations) > 0)

    def test_real_spa_core_tests_dir(self):
        """check_tests_use_unittest on real tests/ returns a list."""
        audit = ArchitectureAudit()
        result = audit.check_tests_use_unittest()
        self.assertIsInstance(result, list)

    def test_real_tests_have_no_violations(self):
        """check_tests_use_unittest on the real codebase returns a list (stub files skipped)."""
        audit = ArchitectureAudit()
        violations = audit.check_tests_use_unittest()
        # All meaningful test files use unittest, pytest, or define test functions.
        # Empty/stub files (MOVED placeholders) are skipped.
        self.assertIsInstance(violations, list)
        self.assertEqual(violations, [],
                         msg=f"Unexpected test files with no framework: {[v.file for v in violations]}")


# ── run_all() ────────────────────────────────────────────────────────────────

class TestRunAll(unittest.TestCase):

    def test_returns_list(self):
        """run_all() returns a list."""
        with tempfile.TemporaryDirectory() as tmp:
            spa = _make_mini_spa(tmp)
            audit = ArchitectureAudit(base_dir=spa)
            result = audit.run_all()
        self.assertIsInstance(result, list)

    def test_elements_are_audit_violations(self):
        """Each element returned by run_all() is an AuditViolation."""
        audit = ArchitectureAudit()
        violations = audit.run_all()
        for v in violations:
            self.assertIsInstance(v, AuditViolation)

    def test_real_codebase_violation_count_low(self):
        """violation_count() on the real codebase is <= 5 (healthy codebase)."""
        audit = ArchitectureAudit()
        audit.run_all()
        count = audit.violation_count()
        self.assertLessEqual(
            count, 5,
            msg=f"Expected <= 5 violations, got {count}. "
                f"Violations: {[(v.rule, v.file, v.line) for v in audit._violations]}"
        )

    def test_run_all_populates_violations_cache(self):
        """After run_all(), violation_count() reflects the cached results."""
        with tempfile.TemporaryDirectory() as tmp:
            spa = _make_mini_spa(tmp)
            audit = ArchitectureAudit(base_dir=spa)
            violations = audit.run_all()
            self.assertEqual(audit.violation_count(), len(violations))


# ── violation_count() ────────────────────────────────────────────────────────

class TestViolationCount(unittest.TestCase):

    def _audit_with_violations(self) -> ArchitectureAudit:
        audit = ArchitectureAudit()
        audit._violations = [
            AuditViolation("rule_a", "f.py", 1, "msg", "ERROR"),
            AuditViolation("rule_b", "g.py", 2, "msg", "WARNING"),
            AuditViolation("rule_a", "h.py", 3, "msg", "ERROR"),
        ]
        return audit

    def test_count_all_violations(self):
        """violation_count() with no args returns all violations."""
        audit = self._audit_with_violations()
        self.assertEqual(audit.violation_count(), 3)

    def test_count_by_error_severity(self):
        """violation_count('ERROR') returns only ERROR count."""
        audit = self._audit_with_violations()
        self.assertEqual(audit.violation_count("ERROR"), 2)

    def test_count_by_warning_severity(self):
        """violation_count('WARNING') returns only WARNING count."""
        audit = self._audit_with_violations()
        self.assertEqual(audit.violation_count("WARNING"), 1)

    def test_empty_cache_returns_zero(self):
        """When no run_all() has been called, violation_count() is 0."""
        with tempfile.TemporaryDirectory() as tmp:
            spa = _make_mini_spa(tmp)
            audit = ArchitectureAudit(base_dir=spa)
            self.assertEqual(audit.violation_count(), 0)


# ── save() ───────────────────────────────────────────────────────────────────

class TestSave(unittest.TestCase):

    def test_creates_file(self):
        """save() creates the output JSON file."""
        violations = [
            AuditViolation("rule_a", "f.py", 1, "msg", "ERROR")
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "audit.json")
            audit = ArchitectureAudit()
            result = audit.save(violations, out_path)
            self.assertTrue(os.path.exists(result))

    def test_creates_parent_dirs(self):
        """save() creates parent directories as needed."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "data", "audit", "report.json")
            audit = ArchitectureAudit()
            audit.save([], out_path)
            self.assertTrue(os.path.exists(out_path))

    def test_valid_json_output(self):
        """Output file is valid JSON with expected structure."""
        violations = [
            AuditViolation("no_hardcoded_secrets", "foo.py", 5, "Bad!", "ERROR")
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "audit.json")
            audit = ArchitectureAudit()
            audit.save(violations, out_path)
            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("total_violations", data)
            self.assertEqual(data["total_violations"], 1)
            self.assertEqual(len(data["violations"]), 1)

    def test_returns_string_path(self):
        """save() returns a string path."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "audit.json")
            audit = ArchitectureAudit()
            result = audit.save([], out_path)
            self.assertIsInstance(result, str)


# ── to_markdown() ─────────────────────────────────────────────────────────────

class TestToMarkdown(unittest.TestCase):

    def test_returns_string(self):
        """to_markdown() returns a string."""
        audit = ArchitectureAudit()
        result = audit.to_markdown([])
        self.assertIsInstance(result, str)

    def test_no_violations_produces_clean_message(self):
        """Empty violations list produces a 'No violations' message."""
        audit = ArchitectureAudit()
        result = audit.to_markdown([])
        self.assertIn("No violations", result)

    def test_errors_appear_in_output(self):
        """ERROR violations appear in the markdown output."""
        violations = [
            AuditViolation("rule_x", "bad.py", 10, "Bad import", "ERROR")
        ]
        audit = ArchitectureAudit()
        result = audit.to_markdown(violations)
        self.assertIn("ERROR", result)

    def test_warnings_appear_in_output(self):
        """WARNING violations appear in the markdown output."""
        violations = [
            AuditViolation("atomic_writes", "module.py", 42, "Direct write", "WARNING")
        ]
        audit = ArchitectureAudit()
        result = audit.to_markdown(violations)
        self.assertIn("WARNING", result)

    def test_output_is_markdown_table(self):
        """Output contains pipe characters (table format)."""
        violations = [
            AuditViolation("rule_y", "f.py", 1, "msg", "ERROR")
        ]
        audit = ArchitectureAudit()
        result = audit.to_markdown(violations)
        self.assertIn("|", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
