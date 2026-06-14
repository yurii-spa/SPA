"""
Tests for Base chain section in daily_paper_report.py — MP-460
"""
import json
import os
import subprocess
import sys
import unittest

# Locate SPA_ROOT relative to this test file (tests/ is one level below root)
SPA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT_PATH = os.path.join(SPA_ROOT, "scripts", "daily_paper_report.py")


class TestBaseChainReport(unittest.TestCase):

    def test_script_exists(self):
        """Скрипт daily_paper_report.py должен существовать."""
        self.assertTrue(os.path.exists(SCRIPT_PATH),
                        f"Script not found: {SCRIPT_PATH}")

    def test_base_section_in_script(self):
        """В скрипте должна быть секция Base chain."""
        with open(SCRIPT_PATH) as f:
            content = f.read()
        self.assertIn("base_chain", content.lower(),
                      "get_base_chain_section should be present in script")

    def test_dry_run_mode(self):
        """--dry-run не должен падать с Traceback и должен вернуть код 0."""
        result = subprocess.run(
            [sys.executable, SCRIPT_PATH, "--dry-run"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertNotIn(
            "Traceback", result.stderr,
            f"Unhandled exception in dry-run:\n{result.stderr}",
        )
        self.assertEqual(result.returncode, 0,
                         f"dry-run exited non-zero:\nstdout={result.stdout}\nstderr={result.stderr}")

    def test_dry_run_contains_base_section(self):
        """Вывод --dry-run должен содержать строку Base Chain."""
        result = subprocess.run(
            [sys.executable, SCRIPT_PATH, "--dry-run"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertIn("Base Chain", result.stdout,
                      "DRY_RUN output must include Base Chain section")

    def test_adapter_status_has_base(self):
        """adapter_status.json должен содержать хотя бы один адаптер с chain=base."""
        status_path = os.path.join(SPA_ROOT, "data", "adapter_status.json")
        self.assertTrue(os.path.exists(status_path),
                        f"adapter_status.json not found: {status_path}")
        with open(status_path) as f:
            data = json.load(f)
        base_items = [
            k for k, v in data.items()
            if isinstance(v, dict) and v.get("chain") == "base"
        ]
        self.assertGreater(
            len(base_items), 0,
            "adapter_status.json should have at least one Base chain adapter",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
