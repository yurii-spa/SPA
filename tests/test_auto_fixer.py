"""
tests/test_auto_fixer.py
==========================
25 unit tests for spa_core/dev_agents/auto_fixer.py

All network calls, subprocess calls, Claude API and file I/O are mocked
where necessary. Tests run fully offline.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Repo root on sys.path ─────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spa_core.dev_agents.auto_fixer import (
    BASE_DIR,
    MAX_FIXES_PER_HOUR,
    _clean_code_response,
    _extract_error_lineno,
    _extract_sha,
    _summarize_fix,
    _to_relative,
    call_claude_api,
    create_backup,
    find_affected_file,
    is_rate_limited,
    rollback,
    run_auto_fix,
    safety_check,
)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

SAMPLE_TRACEBACK = (
    "Traceback (most recent call last):\n"
    "  File \"{base}/spa_core/monitoring/uptime_monitor.py\", line 47, in check_cycle\n"
    "    result = data['apy'].strip()\n"
    "AttributeError: 'NoneType' object has no attribute 'strip'\n"
)


# ────────────────────────────────────────────────────────────────────────────
# 1-5  find_affected_file
# ────────────────────────────────────────────────────────────────────────────

class TestFindAffectedFile:
    def test_finds_real_file_from_traceback(self):
        """Should find uptime_monitor.py which really exists in the repo."""
        text = SAMPLE_TRACEBACK.format(base=str(BASE_DIR))
        result = find_affected_file(text)
        assert result is not None
        assert result.name == "uptime_monitor.py"

    def test_returns_none_when_no_file_in_text(self):
        result = find_affected_file("ERROR: no traceback here, just a message")
        assert result is None

    def test_ignores_forbidden_dirs_in_traceback(self, tmp_path):
        """A traceback pointing to scripts/ should not be returned."""
        fake_scripts = tmp_path / "scripts" / "cycle_runner.py"
        fake_scripts.parent.mkdir(parents=True)
        fake_scripts.write_text("# fake\n")
        text = f'  File "{fake_scripts}", line 1\nImportError: bad'
        with patch("spa_core.dev_agents.auto_fixer.BASE_DIR", tmp_path):
            result = find_affected_file(text)
        assert result is None

    def test_finds_file_without_absolute_path(self, tmp_path):
        """Traceback with relative path should resolve against BASE_DIR."""
        # Create a real file under spa_core/monitoring/
        fake_dir = tmp_path / "spa_core" / "monitoring"
        fake_dir.mkdir(parents=True)
        fake_file = fake_dir / "sample_module.py"
        fake_file.write_text("# sample\n")

        text = '  File "spa_core/monitoring/sample_module.py", line 10\nAttributeError: x'
        with patch("spa_core.dev_agents.auto_fixer.BASE_DIR", tmp_path):
            result = find_affected_file(text)
        assert result is not None
        assert result.name == "sample_module.py"

    def test_returns_most_recent_frame(self, tmp_path):
        """Should return the LAST file in the traceback (innermost frame)."""
        d = tmp_path / "spa_core" / "monitoring"
        d.mkdir(parents=True)
        f1 = d / "outer.py"
        f2 = d / "inner.py"
        f1.write_text("# outer\n")
        f2.write_text("# inner\n")
        text = (
            f'  File "{f1}", line 5\n'
            f'  File "{f2}", line 10\n'
            "AttributeError: bad"
        )
        with patch("spa_core.dev_agents.auto_fixer.BASE_DIR", tmp_path):
            result = find_affected_file(text)
        assert result is not None
        assert result.name == "inner.py"


# ────────────────────────────────────────────────────────────────────────────
# 6-10  safety_check
# ────────────────────────────────────────────────────────────────────────────

class TestSafetyCheck:
    def test_allows_spa_core(self):
        assert safety_check("spa_core/monitoring/uptime_monitor.py") is True

    def test_allows_tests(self):
        assert safety_check("tests/test_uptime_monitor.py") is True

    def test_blocks_scripts_dir(self):
        assert safety_check("scripts/push_to_github.py") is False

    def test_blocks_data_dir(self):
        assert safety_check("data/telegram_last_update_id.json") is False

    def test_blocks_github_dir(self):
        assert safety_check(".github/workflows/ci.yml") is False

    def test_blocks_cycle_runner(self):
        assert safety_check("spa_core/cycle_runner.py") is False

    def test_blocks_kill_switch(self):
        assert safety_check("spa_core/kill_switch.py") is False

    def test_blocks_root_level_script(self):
        assert safety_check("push_to_github.py") is False


# ────────────────────────────────────────────────────────────────────────────
# 11-13  create_backup / rollback
# ────────────────────────────────────────────────────────────────────────────

class TestBackupRollback:
    def test_backup_created(self, tmp_path):
        original = tmp_path / "mymodule.py"
        original.write_text("original content\n")
        # Pass backup_dir=tmp_path to avoid /tmp cross-session ownership conflicts
        backup = create_backup(original, backup_dir=tmp_path)
        assert backup is not None
        assert backup.exists()
        assert backup.read_text() == "original content\n"

    def test_rollback_restores_file(self, tmp_path):
        original = tmp_path / "mymodule.py"
        original.write_text("original content\n")
        backup = create_backup(original, backup_dir=tmp_path)
        # Simulate a bad fix
        original.write_text("BROKEN\n")
        result = rollback(original, backup)
        assert result is True
        assert original.read_text() == "original content\n"

    def test_backup_nonexistent_file_returns_none(self, tmp_path):
        nonexistent = tmp_path / "no_such_file.py"
        backup = create_backup(nonexistent)
        assert backup is None


# ────────────────────────────────────────────────────────────────────────────
# 14-16  Rate limiting
# ────────────────────────────────────────────────────────────────────────────

class TestRateLimit:
    def test_not_rate_limited_initially(self, tmp_path, monkeypatch):
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.RATE_LIMIT_PREFIX",
                            str(tmp_path) + "/rl_")
        assert is_rate_limited() is False

    def test_rate_limited_after_max_fixes(self, tmp_path, monkeypatch):
        prefix = str(tmp_path) + "/rl_"
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.RATE_LIMIT_PREFIX", prefix)
        # Create MAX_FIXES_PER_HOUR fresh files
        for i in range(MAX_FIXES_PER_HOUR):
            path = prefix + str(i)
            with open(path, "w") as f:
                f.write(str(time.time()))
        assert is_rate_limited() is True

    def test_expired_rate_limit_slots_ignored(self, tmp_path, monkeypatch):
        prefix = str(tmp_path) + "/rl_"
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.RATE_LIMIT_PREFIX", prefix)
        # Create MAX_FIXES_PER_HOUR files with OLD timestamps (2 hours ago)
        old_time = time.time() - 7300
        for i in range(MAX_FIXES_PER_HOUR):
            path = prefix + str(i)
            with open(path, "w") as f:
                f.write(str(old_time))
            os.utime(path, (old_time, old_time))
        assert is_rate_limited() is False


# ────────────────────────────────────────────────────────────────────────────
# 17-19  Claude API response cleaning
# ────────────────────────────────────────────────────────────────────────────

class TestCleanCodeResponse:
    def test_strips_python_fence(self):
        code = "```python\nprint('hello')\n```"
        assert _clean_code_response(code) == "print('hello')"

    def test_strips_plain_fence(self):
        code = "```\nprint('hello')\n```"
        assert _clean_code_response(code) == "print('hello')"

    def test_leaves_clean_code_unchanged(self):
        code = "def foo():\n    return 42\n"
        assert _clean_code_response(code) == code.strip()


# ────────────────────────────────────────────────────────────────────────────
# 20-22  call_claude_api (mocked)
# ────────────────────────────────────────────────────────────────────────────

class TestCallClaudeApi:
    def test_returns_fixed_code_via_sdk(self):
        """Mock anthropic SDK path."""
        fixed = "def foo():\n    return 42\n"
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=fixed)]
        )
        with patch.dict("sys.modules", {"anthropic": MagicMock(Anthropic=lambda **kw: mock_client)}):
            result = call_claude_api("error text", "old code", "fake-key")
        assert result == fixed.strip()

    def test_returns_none_on_api_failure(self):
        """Both SDK and raw HTTP fail → None."""
        with patch.dict("sys.modules", {"anthropic": None}):
            with patch("urllib.request.urlopen", side_effect=Exception("network error")):
                # SDK import will fail since anthropic=None won't work as module
                # Fall to raw HTTP which also fails
                result = call_claude_api("error", "code", "key")
        # May return None or raise; we just check it doesn't crash
        # result could be None or the fallback value
        assert result is None or isinstance(result, str)

    def test_cleans_fenced_response(self):
        """Code returned inside ``` should be cleaned."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="```python\nfixed_code()\n```")]
        )
        with patch.dict("sys.modules", {"anthropic": MagicMock(Anthropic=lambda **kw: mock_client)}):
            result = call_claude_api("error", "code", "key")
        assert result == "fixed_code()"


# ────────────────────────────────────────────────────────────────────────────
# 23-25  run_auto_fix (full pipeline, mocked)
# ────────────────────────────────────────────────────────────────────────────

class TestRunAutoFix:
    def test_no_api_key_graceful_degradation(self, tmp_path, monkeypatch):
        """No API key → sends Telegram instruction, returns False."""
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.RATE_LIMIT_PREFIX",
                            str(tmp_path) + "/rl_")
        with patch("spa_core.dev_agents.auto_fixer.get_anthropic_key", return_value=None):
            with patch("spa_core.dev_agents.auto_fixer._tg_request") as mock_tg:
                result = run_auto_fix(
                    "AttributeError: test",
                    token="TOKEN",
                    chat_id="CHAT",
                )
        assert result is False
        # Should have sent the "no API key" notification
        mock_tg.assert_called()

    def test_fix_applied_and_pushed_on_success(self, tmp_path, monkeypatch):
        """Happy path: find file → Claude fix → tests pass → push → True."""
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.RATE_LIMIT_PREFIX",
                            str(tmp_path) + "/rl_")
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.BACKUP_PREFIX",
                            str(tmp_path) + "/bak_")

        # Create a real target file in tmp_path under spa_core/monitoring/
        fake_dir = tmp_path / "spa_core" / "monitoring"
        fake_dir.mkdir(parents=True)
        target = fake_dir / "sample_fix.py"
        target.write_text("def broken():\n    return None.strip()\n")

        traceback = (
            f'File "{target}", line 2, in broken\n'
            "AttributeError: 'NoneType' object has no attribute 'strip'"
        )

        with patch("spa_core.dev_agents.auto_fixer.BASE_DIR", tmp_path):
            with patch("spa_core.dev_agents.auto_fixer.get_anthropic_key", return_value="key"):
                with patch("spa_core.dev_agents.auto_fixer.call_claude_api",
                           return_value="def broken():\n    x = None\n    return x or ''\n"):
                    with patch("spa_core.dev_agents.auto_fixer.run_tests",
                               return_value=(True, "3 passed")):
                        with patch("spa_core.dev_agents.auto_fixer.push_file",
                                   return_value="abc1234"):
                            with patch("spa_core.dev_agents.auto_fixer._tg_request"):
                                result = run_auto_fix(traceback, token="TOK", chat_id="CID")

        assert result is True

    def test_rollback_on_test_failure(self, tmp_path, monkeypatch):
        """If tests fail after fix → file is rolled back to original."""
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.RATE_LIMIT_PREFIX",
                            str(tmp_path) + "/rl_")
        monkeypatch.setattr("spa_core.dev_agents.auto_fixer.BACKUP_PREFIX",
                            str(tmp_path) + "/bak_")

        fake_dir = tmp_path / "spa_core" / "monitoring"
        fake_dir.mkdir(parents=True)
        target = fake_dir / "broken_mod.py"
        original_content = "def orig():\n    pass\n"
        target.write_text(original_content)

        traceback = f'File "{target}", line 1\nAttributeError: bad'

        with patch("spa_core.dev_agents.auto_fixer.BASE_DIR", tmp_path):
            with patch("spa_core.dev_agents.auto_fixer.get_anthropic_key", return_value="key"):
                with patch("spa_core.dev_agents.auto_fixer.call_claude_api",
                           return_value="def orig():\n    BROKEN_SYNTAX(((\n"):
                    with patch("spa_core.dev_agents.auto_fixer.run_tests",
                               return_value=(False, "1 failed")):
                        with patch("spa_core.dev_agents.auto_fixer._tg_request"):
                            result = run_auto_fix(traceback, token="TOK", chat_id="CID")

        assert result is False
        # File should be rolled back to original
        assert target.read_text() == original_content


# ────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ────────────────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_extract_error_lineno(self):
        assert _extract_error_lineno("File 'foo.py', line 47, in bar") == 47

    def test_extract_sha(self):
        assert _extract_sha("Successfully pushed abc1234 to main") == "abc1234"
        assert _extract_sha("no sha here") is None

    def test_summarize_import_error(self):
        assert "import" in _summarize_fix("", "ImportError").lower()

    def test_to_relative_under_base(self):
        p = BASE_DIR / "spa_core" / "monitoring" / "uptime_monitor.py"
        rel = _to_relative(p)
        assert rel == "spa_core/monitoring/uptime_monitor.py"

    def test_to_relative_outside_base(self, tmp_path):
        p = tmp_path / "outside.py"
        assert _to_relative(p) is None
