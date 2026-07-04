"""
tests/test_ci_workflows.py
15 tests validating GitHub Actions workflow YAML structure.
No network calls; reads files from .github/workflows/.
"""
import os
import sys
import unittest

# Try to import yaml; fall back to manual parsing if absent.
try:
    import yaml  # type: ignore
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS_DIR = os.path.join(REPO_ROOT, ".github", "workflows")
DEPLOY_LANDING = os.path.join(WORKFLOWS_DIR, "deploy-landing.yml")
TEST_WORKFLOW = os.path.join(WORKFLOWS_DIR, "test.yml")


def _load_yaml(path):
    """Load a YAML file; returns None if yaml is unavailable."""
    if not HAS_YAML:
        return None
    with open(path) as fh:
        return yaml.safe_load(fh)


def _read_text(path):
    with open(path) as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# deploy-landing.yml tests
# ---------------------------------------------------------------------------

class TestDeployLandingWorkflow(unittest.TestCase):
    """Tests for .github/workflows/deploy-landing.yml"""

    def setUp(self):
        self.assertTrue(
            os.path.exists(DEPLOY_LANDING),
            f"deploy-landing.yml not found at {DEPLOY_LANDING}"
        )
        self.content = _read_text(DEPLOY_LANDING)

    def test_file_exists(self):
        """deploy-landing.yml must exist in .github/workflows/."""
        self.assertTrue(os.path.isfile(DEPLOY_LANDING))

    def test_is_manual_mirror_not_push_triggered(self):
        """deploy-landing.yml is a NON-CANONICAL MIRROR (ADR-YL-011): workflow_dispatch-only,
        must NOT auto-trigger on push (canonical deploy = Cloudflare Pages git-integration)."""
        self.assertIn("workflow_dispatch", self.content)
        self.assertNotIn("branches: [main]", self.content)

    def test_mirror_self_documented(self):
        """The workflow name must mark it a MIRROR so its purpose is unambiguous."""
        self.assertIn("MIRROR", self.content)

    def test_permissions_pages_write(self):
        """pages: write permission required for Pages deployment."""
        self.assertIn("pages: write", self.content)

    def test_permissions_id_token_write(self):
        """id-token: write required for OIDC-based Pages deployment."""
        self.assertIn("id-token: write", self.content)

    def test_node_version_20(self):
        """Node.js 20 must be specified for the build job."""
        self.assertIn("node-version: '20'", self.content)

    def test_npm_ci_used(self):
        """npm ci is preferred over npm install for reproducible builds."""
        self.assertIn("npm ci", self.content)

    def test_npm_run_build(self):
        """Build must invoke npm run build."""
        self.assertIn("npm run build", self.content)

    def test_upload_pages_artifact(self):
        """Artifact upload action must be present."""
        self.assertIn("upload-pages-artifact", self.content)

    def test_artifact_path_landing_dist(self):
        """Artifact path must point to landing/dist."""
        self.assertIn("landing/dist", self.content)

    def test_deploy_pages_action(self):
        """Deploy action must use actions/deploy-pages."""
        self.assertIn("deploy-pages", self.content)

    def test_concurrency_group_pages(self):
        """Concurrency group must be 'pages' to prevent duplicate deploys."""
        self.assertIn('group: "pages"', self.content)

    def test_workflow_dispatch_trigger(self):
        """Manual workflow_dispatch trigger must be present."""
        self.assertIn("workflow_dispatch", self.content)


# ---------------------------------------------------------------------------
# test.yml tests
# ---------------------------------------------------------------------------

class TestTestWorkflow(unittest.TestCase):
    """Tests for .github/workflows/test.yml"""

    def setUp(self):
        self.assertTrue(
            os.path.exists(TEST_WORKFLOW),
            f"test.yml not found at {TEST_WORKFLOW}"
        )
        self.content = _read_text(TEST_WORKFLOW)

    def test_file_exists(self):
        """test.yml must exist in .github/workflows/."""
        self.assertTrue(os.path.isfile(TEST_WORKFLOW))

    def test_runs_pytest(self):
        """Workflow must invoke pytest."""
        self.assertIn("pytest", self.content)

    def test_triggers_on_push_main(self):
        """Workflow must trigger on push to main."""
        self.assertIn("branches: [main]", self.content)


# ---------------------------------------------------------------------------
# General workflows directory test
# ---------------------------------------------------------------------------

class TestWorkflowsDirectory(unittest.TestCase):
    """General checks for the .github/workflows directory."""

    def test_workflows_dir_exists(self):
        """The .github/workflows directory must exist."""
        self.assertTrue(os.path.isdir(WORKFLOWS_DIR))

    def test_at_least_two_workflows(self):
        """At least 2 workflow YAML files should exist after MP-1536."""
        ymls = [f for f in os.listdir(WORKFLOWS_DIR) if f.endswith(".yml")]
        self.assertGreaterEqual(len(ymls), 2, f"Only found: {ymls}")

    def test_no_hardcoded_secrets_in_workflows(self):
        """Workflow files must not contain raw PAT tokens or API keys."""
        for fname in os.listdir(WORKFLOWS_DIR):
            if not fname.endswith(".yml"):
                continue
            content = _read_text(os.path.join(WORKFLOWS_DIR, fname))
            # Check for common secret patterns (raw GitHub PAT prefixes)
            for pattern in ("ghp_", "github_pat_"):
                self.assertNotIn(
                    pattern, content,
                    f"Possible hardcoded PAT in {fname}"
                )


if __name__ == "__main__":
    unittest.main()
