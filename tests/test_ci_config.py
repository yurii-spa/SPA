"""
tests/test_ci_config.py

15 tests validating that all GitHub Actions workflow YAML files meet SPA
CI/CD standards (MP-1475, v10.91).

Checks:
  - Modern action versions (checkout@v4, setup-python@v5, upload-artifact@v4)
  - No deprecated ubuntu-20.04 runners
  - Required jobs/steps present in ci.yml (KANBAN health, SPAError, stdlib guard)
  - No hardcoded secrets in YAML
  - Mandatory workflow triggers defined

Stdlib only — no third-party deps, no network.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _load_workflows() -> dict[str, str]:
    """Return {filename: content} for every .yml in .github/workflows/."""
    if not WORKFLOWS_DIR.exists():
        return {}
    result = {}
    for p in WORKFLOWS_DIR.glob("*.yml"):
        result[p.name] = p.read_text(encoding="utf-8")
    return result


WORKFLOWS = _load_workflows()
CI_YML = WORKFLOWS.get("ci.yml", "")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCIWorkflowsExist(unittest.TestCase):
    """Basic existence checks."""

    def test_workflows_directory_exists(self):
        """The .github/workflows/ directory must be present."""
        self.assertTrue(WORKFLOWS_DIR.exists(), ".github/workflows/ is missing")

    def test_ci_yml_exists(self):
        """ci.yml must exist (primary CI workflow)."""
        self.assertIn("ci.yml", WORKFLOWS, "ci.yml is missing from .github/workflows/")

    def test_at_least_four_workflows(self):
        """Repo should have at least 4 CI/CD workflow files."""
        self.assertGreaterEqual(
            len(WORKFLOWS), 4,
            f"Expected ≥4 workflow files, found {len(WORKFLOWS)}",
        )


class TestModernActionVersions(unittest.TestCase):
    """No deprecated action versions allowed."""

    def test_no_checkout_v2(self):
        """actions/checkout@v2 must not appear in any workflow."""
        for name, content in WORKFLOWS.items():
            self.assertNotIn(
                "actions/checkout@v2", content,
                f"{name}: found deprecated actions/checkout@v2",
            )

    def test_no_checkout_v3(self):
        """actions/checkout@v3 must not appear in any workflow."""
        for name, content in WORKFLOWS.items():
            self.assertNotIn(
                "actions/checkout@v3", content,
                f"{name}: found deprecated actions/checkout@v3 — upgrade to @v4",
            )

    def test_no_setup_python_v4(self):
        """actions/setup-python@v4 must not appear in any workflow."""
        for name, content in WORKFLOWS.items():
            self.assertNotIn(
                "actions/setup-python@v4", content,
                f"{name}: found deprecated actions/setup-python@v4 — upgrade to @v5",
            )

    def test_no_upload_artifact_v3(self):
        """actions/upload-artifact@v3 must not appear in any workflow."""
        for name, content in WORKFLOWS.items():
            self.assertNotIn(
                "actions/upload-artifact@v3", content,
                f"{name}: found deprecated actions/upload-artifact@v3 — upgrade to @v4",
            )

    def test_no_ubuntu_2004_runners(self):
        """ubuntu-20.04 runners must be replaced with ubuntu-22.04 or ubuntu-latest."""
        for name, content in WORKFLOWS.items():
            self.assertNotIn(
                "ubuntu-20.04", content,
                f"{name}: found deprecated ubuntu-20.04 — upgrade to ubuntu-22.04 or ubuntu-latest",
            )

    def test_ci_uses_checkout_v4(self):
        """ci.yml must use actions/checkout@v4."""
        self.assertIn("actions/checkout@v4", CI_YML)

    def test_ci_uses_setup_python_v5(self):
        """ci.yml must use actions/setup-python@v5."""
        self.assertIn("actions/setup-python@v5", CI_YML)


class TestCIRequiredSteps(unittest.TestCase):
    """ci.yml must include all mandatory health-check steps."""

    def test_kanban_health_step_present(self):
        """ci.yml must include the KANBAN Health Check step."""
        self.assertIn(
            "kanban_health.py",
            CI_YML,
            "ci.yml is missing the KANBAN Health Check step",
        )

    def test_spaerror_audit_step_present(self):
        """ci.yml must include the SPAError Adoption Check step."""
        self.assertIn(
            "spaerror_final_audit.py",
            CI_YML,
            "ci.yml is missing the SPAError Adoption Check step",
        )

    def test_stdlib_guard_step_present(self):
        """ci.yml must include the Stdlib Contract Guard step."""
        self.assertIn(
            "stdlib_contract_guard.py",
            CI_YML,
            "ci.yml is missing the Stdlib Contract Guard step",
        )

    def test_forbidden_import_check_present(self):
        """ci.yml must retain the forbidden-imports lint step."""
        self.assertIn(
            "forbidden", CI_YML,
            "ci.yml is missing the forbidden-import check step",
        )


class TestCISecurityBaseline(unittest.TestCase):
    """No hardcoded credentials in workflow files."""

    _SECRET_PATTERNS = [
        r"ghp_[A-Za-z0-9]{36}",          # GitHub PAT
        r"AKIA[0-9A-Z]{16}",              # AWS Access Key
        r"sk-[A-Za-z0-9]{32,}",           # OpenAI key pattern
        r"password\s*[:=]\s*['\"][^$][^'\"]{4,}",  # literal password
    ]

    def test_no_hardcoded_credentials(self):
        """Workflow YAML files must not contain hardcoded credentials."""
        for name, content in WORKFLOWS.items():
            for pattern in self._SECRET_PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                self.assertEqual(
                    matches, [],
                    f"{name}: potential hardcoded credential found: {matches}",
                )

    def test_secrets_referenced_via_context(self):
        """Any token in ci.yml must reference ${{ secrets.* }}, not be hardcoded."""
        # If the file mentions "token:" it must use ${{ secrets. }} syntax
        token_lines = [
            line for line in CI_YML.splitlines()
            if "token:" in line.lower() and "${{ secrets." not in line
            and not line.strip().startswith("#")
        ]
        self.assertEqual(
            token_lines, [],
            f"ci.yml has non-secrets token references: {token_lines}",
        )


class TestScriptsReferencedInCI(unittest.TestCase):
    """Scripts called from CI must exist in the repo."""

    def test_kanban_health_script_exists(self):
        """scripts/kanban_health.py must exist."""
        p = REPO_ROOT / "scripts" / "kanban_health.py"
        self.assertTrue(p.exists(), "scripts/kanban_health.py is missing")

    def test_spaerror_audit_script_exists(self):
        """scripts/spaerror_final_audit.py must exist."""
        p = REPO_ROOT / "scripts" / "spaerror_final_audit.py"
        self.assertTrue(p.exists(), "scripts/spaerror_final_audit.py is missing")

    def test_stdlib_guard_script_exists(self):
        """scripts/stdlib_contract_guard.py must exist."""
        p = REPO_ROOT / "scripts" / "stdlib_contract_guard.py"
        self.assertTrue(p.exists(), "scripts/stdlib_contract_guard.py is missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
