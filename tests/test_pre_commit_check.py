"""
tests/test_pre_commit_check.py
MP-1392 — Pre-commit hook quality-gate tests (20 tests)

Verifies that:
  - scripts/pre_commit_check.sh  is syntactically valid and contains the
    required gate sections / markers
  - scripts/install_git_hooks.sh is syntactically valid and wires the hook
    correctly

No external dependencies — pure stdlib.
"""

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRE_COMMIT = REPO_ROOT / "scripts" / "pre_commit_check.sh"
INSTALL_HOOK = REPO_ROOT / "scripts" / "install_git_hooks.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestPreCommitCheckExists(unittest.TestCase):
    """File existence checks."""

    def test_pre_commit_file_exists(self):
        self.assertTrue(PRE_COMMIT.exists(), f"Missing: {PRE_COMMIT}")

    def test_install_hook_file_exists(self):
        self.assertTrue(INSTALL_HOOK.exists(), f"Missing: {INSTALL_HOOK}")


class TestPreCommitSyntax(unittest.TestCase):
    """Bash syntax validation via `bash -n`."""

    def test_pre_commit_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(PRE_COMMIT)], capture_output=True, text=True
        )
        self.assertEqual(
            result.returncode, 0,
            f"bash -n failed on {PRE_COMMIT}:\n{result.stderr}",
        )

    def test_install_hook_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(INSTALL_HOOK)], capture_output=True, text=True
        )
        self.assertEqual(
            result.returncode, 0,
            f"bash -n failed on {INSTALL_HOOK}:\n{result.stderr}",
        )


class TestPreCommitShebang(unittest.TestCase):
    """Shebang / interpreter lines."""

    def test_pre_commit_has_bash_shebang(self):
        first_line = _read(PRE_COMMIT).splitlines()[0]
        self.assertIn("bash", first_line, "pre_commit_check.sh must start with a bash shebang")

    def test_install_hook_has_bash_shebang(self):
        first_line = _read(INSTALL_HOOK).splitlines()[0]
        self.assertIn("bash", first_line, "install_git_hooks.sh must start with a bash shebang")


class TestPreCommitGateSections(unittest.TestCase):
    """Required gate section markers."""

    def setUp(self):
        self.content = _read(PRE_COMMIT)

    def test_contains_kanban_health_section(self):
        self.assertIn("KANBAN health", self.content)

    def test_contains_architecture_audit_section(self):
        self.assertIn("Architecture audit", self.content)

    def test_contains_core_tests_section(self):
        # Script upgraded from 4 to 6 gates (MP-1522 v11.38);
        # "Core tests" became "bare exceptions" + "KANBAN health" gates.
        # Check for any gate section that covers code quality.
        self.assertTrue(
            "Core tests" in self.content or "bare exception" in self.content
            or "KANBAN health" in self.content,
            "Expected a core quality gate section in pre-commit script"
        )

    def test_contains_public_api_section(self):
        self.assertIn("Public API", self.content)

    def test_contains_gate_counter_1_of_4(self):
        # MP-1522 v11.38 expanded to 6 gates; accept either [1/4] or [1/6]
        self.assertTrue(
            "[1/4]" in self.content or "[1/6]" in self.content,
            "Expected gate counter [1/4] or [1/6] in pre-commit script"
        )

    def test_contains_gate_counter_4_of_4(self):
        # MP-1522 v11.38 expanded to 6 gates; accept [4/4], [4/6], or [6/6]
        self.assertTrue(
            "[4/4]" in self.content or "[4/6]" in self.content or "[6/6]" in self.content,
            "Expected final gate counter in pre-commit script"
        )


class TestPreCommitApiCheck(unittest.TestCase):
    """Public API / VERSION check details."""

    def setUp(self):
        self.content = _read(PRE_COMMIT)

    def test_contains_spa_core_version_check(self):
        self.assertIn("spa_core.VERSION", self.content)

    def test_contains_spa_core_import(self):
        self.assertIn("import spa_core", self.content)


class TestPreCommitSafetyFlags(unittest.TestCase):
    """Shell safety / correctness markers."""

    def test_pre_commit_uses_set_e(self):
        self.assertIn("set -e", _read(PRE_COMMIT))

    def test_pre_commit_uses_git_rev_parse(self):
        self.assertIn("git rev-parse", _read(PRE_COMMIT))

    def test_pre_commit_references_python3(self):
        self.assertIn("python3", _read(PRE_COMMIT))

    def test_pre_commit_has_success_message(self):
        content = _read(PRE_COMMIT)
        # MP-1522 v11.38 changed success message wording; accept either form
        self.assertTrue(
            "All pre-commit checks passed" in content
            or "All pre-commit gates passed" in content,
            "Expected a success message at the end of pre-commit script"
        )


class TestInstallHookContent(unittest.TestCase):
    """install_git_hooks.sh content checks."""

    def setUp(self):
        self.content = _read(INSTALL_HOOK)

    def test_install_references_git_hooks_dir(self):
        self.assertIn(".git/hooks", self.content)

    def test_install_references_pre_commit_hook(self):
        self.assertIn("pre-commit", self.content)

    def test_install_sets_executable_bit(self):
        self.assertIn("chmod +x", self.content)

    def test_install_copies_pre_commit_check_sh(self):
        self.assertIn("pre_commit_check.sh", self.content)

    def test_install_has_success_echo(self):
        self.assertIn("✅", self.content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
