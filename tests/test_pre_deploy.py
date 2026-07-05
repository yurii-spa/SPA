"""
tests/test_pre_deploy.py
Tests for scripts/pre_deploy_check.py — 20 unit tests.
All subprocess calls are mocked; no real build/filesystem needed.
"""
import sys
import os
import json
import types
import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the module under test (without executing main)
import scripts.pre_deploy_check as pdc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed_process(returncode=0, stdout="", stderr=""):
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestLandingBuilds(unittest.TestCase):
    """Check 1: Landing build succeeds."""

    @patch("scripts.pre_deploy_check.subprocess.run")
    @patch("os.path.isdir", return_value=True)
    @patch("scripts.pre_deploy_check.shutil.which", return_value="/usr/bin/npm")
    def test_build_success(self, _which, _isdir, mock_run):
        mock_run.return_value = _make_completed_process(returncode=0)
        result = pdc.landing_builds()
        self.assertEqual(result, "build OK")

    @patch("scripts.pre_deploy_check.subprocess.run")
    @patch("os.path.isdir", return_value=True)
    @patch("scripts.pre_deploy_check.shutil.which", return_value="/usr/bin/npm")
    def test_build_failure_raises(self, _which, _isdir, mock_run):
        mock_run.return_value = _make_completed_process(
            returncode=1, stderr="Error: module not found"
        )
        with self.assertRaises(AssertionError) as ctx:
            pdc.landing_builds()
        self.assertIn("Build failed", str(ctx.exception))

    @patch("os.path.isdir", return_value=False)
    def test_missing_landing_dir(self, _isdir):
        with self.assertRaises(AssertionError) as ctx:
            pdc.landing_builds()
        self.assertIn("landing/ directory not found", str(ctx.exception))


class TestGateLocked(unittest.TestCase):
    """Check 3: LiveTradingGate locked."""

    def test_gate_locked_ok(self):
        gate_mock = MagicMock()
        gate_mock.is_active.return_value = False
        klass_mock = MagicMock(return_value=gate_mock)
        module_mock = types.ModuleType("spa_core.safety.live_trading_gate")
        module_mock.LiveTradingGate = klass_mock
        with patch.dict("sys.modules", {"spa_core.safety.live_trading_gate": module_mock,
                                        "spa_core.safety": MagicMock(),
                                        "spa_core": MagicMock()}):
            result = pdc.gate_locked()
        self.assertEqual(result, "LOCKED")

    def test_gate_unlocked_raises(self):
        gate_mock = MagicMock()
        gate_mock.is_active.return_value = True
        klass_mock = MagicMock(return_value=gate_mock)
        module_mock = types.ModuleType("spa_core.safety.live_trading_gate")
        module_mock.LiveTradingGate = klass_mock
        with patch.dict("sys.modules", {"spa_core.safety.live_trading_gate": module_mock,
                                        "spa_core.safety": MagicMock(),
                                        "spa_core": MagicMock()}):
            with self.assertRaises(AssertionError) as ctx:
                pdc.gate_locked()
        self.assertIn("UNLOCKED", str(ctx.exception))

    def test_gate_module_absent(self):
        # ImportError → treated as LOCKED
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            result = pdc.gate_locked()
        self.assertIn("LOCKED", result)


class TestNoSecrets(unittest.TestCase):
    """Check 4: No hardcoded secrets."""

    @patch("scripts.pre_deploy_check.subprocess.run")
    def test_clean(self, mock_run):
        mock_run.return_value = _make_completed_process(returncode=0, stdout="")
        result = pdc.no_secrets()
        self.assertEqual(result, "clean")

    @patch("scripts.pre_deploy_check.subprocess.run")
    def test_secret_found_raises(self, mock_run):
        mock_run.return_value = _make_completed_process(
            returncode=0, stdout="spa_core/foo.py:10:token = 'ghp_ABCDEF'"
        )
        with self.assertRaises(AssertionError) as ctx:
            pdc.no_secrets()
        self.assertIn("Possible secrets", str(ctx.exception))


class TestDataFilesPresent(unittest.TestCase):
    """Check 6: data/ state files present."""

    def test_all_present(self):
        with patch("os.path.exists", return_value=True):
            result = pdc.data_files_present()
        self.assertIn("files present", result)

    def test_missing_file_raises(self):
        with patch("os.path.exists", side_effect=lambda p: "trades" not in p):
            with self.assertRaises(AssertionError) as ctx:
                pdc.data_files_present()
        self.assertIn("Missing state files", str(ctx.exception))


class TestGoLiveJsonValid(unittest.TestCase):
    """Check 7: golive_status.json parseable."""

    def test_valid_json(self):
        data = {"checks": {"a": True, "b": True, "c": False}}
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=json.dumps(data))):
            result = pdc.golive_json_valid()
        self.assertIn("2/3", result)

    def test_missing_file_raises(self):
        with patch("os.path.exists", return_value=False):
            with self.assertRaises(AssertionError):
                pdc.golive_json_valid()


class TestTradesJsonValid(unittest.TestCase):
    """Check 8: trades.json parseable."""

    def test_valid_list(self):
        data = [{"id": 1}, {"id": 2}]
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=json.dumps(data))):
            result = pdc.trades_json_valid()
        self.assertIn("2 trades", result)

    def test_non_list_raises(self):
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=json.dumps({}))):
            with self.assertRaises(AssertionError) as ctx:
                pdc.trades_json_valid()
        self.assertIn("Expected list", str(ctx.exception))


class TestKanbanValid(unittest.TestCase):
    """Check 11: KANBAN.json parseable."""

    def test_valid_kanban(self):
        data = {"sprint_completed": "v11.54", "done_count": 1197}
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=json.dumps(data))):
            result = pdc.kanban_valid()
        self.assertIn("v11.54", result)

    def test_missing_raises(self):
        with patch("os.path.exists", return_value=False):
            with self.assertRaises(AssertionError):
                pdc.kanban_valid()


class TestRiskPolicyVersion(unittest.TestCase):
    """Check 13: RiskPolicy version is v1.0."""

    def test_version_ok(self):
        content = "version = \"v1.0\"  # FORBIDDEN to change"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=content)):
            result = pdc.risk_policy_version()
        self.assertIn("v1.0", result)

    def test_wrong_version_raises(self):
        content = "version = 'v2.0'"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=content)):
            with self.assertRaises(AssertionError) as ctx:
                pdc.risk_policy_version()
        self.assertIn("FORBIDDEN", str(ctx.exception))


class TestHeadersFile(unittest.TestCase):
    """Check 15: landing/_headers present."""

    def test_headers_present(self):
        content = "/*\n  X-Frame-Options: DENY\n  X-Content-Type-Options: nosniff\n"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=content)):
            result = pdc.headers_file_present()
        self.assertIn("headers OK", result)

    def test_headers_missing_raises(self):
        with patch("os.path.exists", return_value=False):
            with self.assertRaises(AssertionError) as ctx:
                pdc.headers_file_present()
        self.assertIn("missing", str(ctx.exception))

    def test_headers_no_xframe_raises(self):
        content = "/*\n  Cache-Control: no-cache\n"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=content)):
            with self.assertRaises(AssertionError) as ctx:
                pdc.headers_file_present()
        self.assertIn("X-Frame-Options", str(ctx.exception))


class TestAstroConfig(unittest.TestCase):
    """Check 17: astro.config.mjs has site set."""

    def test_site_present(self):
        content = "export default defineConfig({ site: 'https://earn-defi.com' })"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=content)):
            result = pdc.astro_config_site()
        self.assertIn("earn-defi.com", result)

    def test_site_missing_raises(self):
        content = "export default defineConfig({ output: 'static' })"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=content)):
            with self.assertRaises(AssertionError):
                pdc.astro_config_site()


class TestDeployWorkflowPresent(unittest.TestCase):
    """Check 19: deploy-landing workflow present."""

    def test_workflow_present(self):
        with patch("os.path.exists", return_value=True):
            result = pdc.deploy_workflow_present()
        self.assertIn("deploy-landing.yml", result)

    def test_workflow_missing_raises(self):
        with patch("os.path.exists", return_value=False):
            with self.assertRaises(AssertionError):
                pdc.deploy_workflow_present()


class TestRunChecks(unittest.TestCase):
    """Integration tests for the run_checks runner."""

    def test_all_pass_returns_zero_failures(self):
        checks = [
            ("always pass", lambda: "ok", True),
            ("also pass", lambda: "yep", False),
        ]
        failed, results = pdc.run_checks(checks=checks, verbose=False)
        self.assertEqual(failed, 0)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["status"] == "pass" for r in results))

    def test_critical_failure_counted(self):
        def fail():
            raise AssertionError("boom")
        checks = [
            ("critical fail", fail, True),
            ("warn fail", fail, False),
        ]
        failed, results = pdc.run_checks(checks=checks, verbose=False)
        self.assertEqual(failed, 1)
        self.assertEqual(results[0]["status"], "fail")
        self.assertEqual(results[0]["critical"], True)
        self.assertEqual(results[1]["critical"], False)

    def test_result_structure_fields(self):
        checks = [("ok check", lambda: "done", True)]
        _, results = pdc.run_checks(checks=checks, verbose=False)
        r = results[0]
        self.assertIn("name", r)
        self.assertIn("critical", r)
        self.assertIn("status", r)
        self.assertIn("error", r)
        self.assertIsNone(r["error"])


if __name__ == "__main__":
    unittest.main()
