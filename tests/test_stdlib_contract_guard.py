"""
tests/test_stdlib_contract_guard.py
20 tests for scripts/stdlib_contract_guard.py
"""
import os
import sys
import tempfile
import unittest

# Make scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from stdlib_contract_guard import (
    is_stdlib_contract,
    validate_no_spa_imports,
    scan_for_contracts,
    report,
    STDLIB_CONTRACT_FILES,
)

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
PROOF_OF_TRACK = os.path.join(PROJECT_ROOT, "spa_core", "audit", "proof_of_track.py")


class TestIsStdlibContract(unittest.TestCase):
    def test_proof_of_track_is_contract_by_whitelist(self):
        """proof_of_track.py is in STDLIB_CONTRACT_FILES → is_stdlib_contract returns True."""
        self.assertTrue(is_stdlib_contract(PROOF_OF_TRACK))

    def test_regular_file_not_contract(self):
        """A regular analytics file is NOT a stdlib contract."""
        regular = os.path.join(PROJECT_ROOT, "spa_core", "analytics", "rs001_stress_engine.py")
        if os.path.exists(regular):
            self.assertFalse(is_stdlib_contract(regular))

    def test_file_with_stdlib_only_comment_is_contract(self):
        """File containing '# stdlib only' comment → True."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# stdlib only\nimport os\n")
            fname = f.name
        try:
            self.assertTrue(is_stdlib_contract(fname))
        finally:
            os.unlink(fname)

    def test_file_without_marker_not_contract(self):
        """File with no markers → False."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nimport json\n")
            fname = f.name
        try:
            self.assertFalse(is_stdlib_contract(fname))
        finally:
            os.unlink(fname)

    def test_file_with_test_only_stdlib_imports_is_contract(self):
        """File with def test_only_stdlib_imports → True."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\n\ndef test_only_stdlib_imports():\n    pass\n")
            fname = f.name
        try:
            self.assertTrue(is_stdlib_contract(fname))
        finally:
            os.unlink(fname)

    def test_nonexistent_file_not_contract(self):
        """Non-existent file → False (not a contract)."""
        self.assertFalse(is_stdlib_contract("/nonexistent/path/file.py"))

    def test_whitelist_contains_proof_of_track(self):
        """STDLIB_CONTRACT_FILES must include proof_of_track.py."""
        self.assertTrue(any("proof_of_track" in e for e in STDLIB_CONTRACT_FILES))

    def test_whitelist_is_list(self):
        """STDLIB_CONTRACT_FILES is a list."""
        self.assertIsInstance(STDLIB_CONTRACT_FILES, list)

    def test_partial_path_match_whitelist(self):
        """is_stdlib_contract handles paths with extra leading segments."""
        # The function should match even if path has extra leading components
        # Try full absolute path to proof_of_track
        self.assertTrue(is_stdlib_contract(PROOF_OF_TRACK))

    def test_empty_file_not_contract(self):
        """Empty file with no markers → False."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("")
            fname = f.name
        try:
            self.assertFalse(is_stdlib_contract(fname))
        finally:
            os.unlink(fname)


class TestValidateNoSpaImports(unittest.TestCase):
    def test_file_with_spa_core_import_fails(self):
        """File with 'from spa_core.utils.atomic import atomic_save' → False."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("from spa_core.utils.atomic import atomic_save\nimport os\n")
            fname = f.name
        try:
            self.assertFalse(validate_no_spa_imports(fname))
        finally:
            os.unlink(fname)

    def test_pure_stdlib_file_passes(self):
        """File with only stdlib imports → True."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\nimport json\nimport tempfile\n")
            fname = f.name
        try:
            self.assertTrue(validate_no_spa_imports(fname))
        finally:
            os.unlink(fname)

    def test_spa_core_import_statement_fails(self):
        """'import spa_core.utils' → False."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import spa_core.utils\n")
            fname = f.name
        try:
            self.assertFalse(validate_no_spa_imports(fname))
        finally:
            os.unlink(fname)

    def test_nonexistent_file_returns_true(self):
        """Non-existent file → True (assume clean, can't verify)."""
        self.assertTrue(validate_no_spa_imports("/nonexistent/file.py"))

    def test_proof_of_track_is_clean(self):
        """proof_of_track.py has no spa_core.utils imports → True."""
        if os.path.exists(PROOF_OF_TRACK):
            self.assertTrue(validate_no_spa_imports(PROOF_OF_TRACK))

    def test_inline_import_in_function_fails(self):
        """Even inline 'from spa_core.utils.atomic import ...' inside a function → False."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\n\ndef foo():\n    from spa_core.utils.atomic import atomic_save\n    atomic_save({}, '/tmp/x.json')\n")
            fname = f.name
        try:
            self.assertFalse(validate_no_spa_imports(fname))
        finally:
            os.unlink(fname)


class TestScanForContracts(unittest.TestCase):
    def test_scan_returns_list(self):
        """scan_for_contracts() returns a list."""
        result = scan_for_contracts(PROJECT_ROOT)
        self.assertIsInstance(result, list)

    def test_scan_finds_proof_of_track(self):
        """scan_for_contracts on project root finds proof_of_track.py."""
        result = scan_for_contracts(PROJECT_ROOT)
        self.assertTrue(any("proof_of_track" in r for r in result))

    def test_scan_temp_dir_with_stdlib_marker(self):
        """scan_for_contracts finds files with '# stdlib only' comment."""
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "mymodule.py")
            with open(fpath, "w") as f:
                f.write("# stdlib only\nimport os\n")
            result = scan_for_contracts(d)
            self.assertEqual(len(result), 1)


class TestReport(unittest.TestCase):
    def test_report_returns_string(self):
        """report() returns a string."""
        result = report(PROJECT_ROOT)
        self.assertIsInstance(result, str)

    def test_report_contains_stdlib_contract(self):
        """report() output contains 'stdlib contract' phrase."""
        result = report(PROJECT_ROOT)
        self.assertIn("stdlib contract", result)

    def test_report_contains_protected(self):
        """report() output marks protected files."""
        result = report(PROJECT_ROOT)
        # Should find at least proof_of_track.py
        self.assertIn("PROTECTED", result)


if __name__ == "__main__":
    unittest.main()
