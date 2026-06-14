#!/usr/bin/env python3
"""
MP-309: Tests for scripts/lint_llm_forbidden.py

Run with:
    python3 -m unittest discover -s scripts/tests -p "test_lint_llm_forbidden.py" -v
    # or directly:
    python3 scripts/tests/test_lint_llm_forbidden.py
"""

import os
import sys
import tempfile
import textwrap
import unittest

# Make scripts/ importable regardless of cwd
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import lint_llm_forbidden as linter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_file(directory: str, rel_path: str, content: str) -> str:
    """Write content to directory/rel_path, creating parents as needed."""
    full = os.path.join(directory, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(content))
    return full


class _TempProjectMixin:
    """Mixin: creates a fresh temp dir as project root before each test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.base = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _make(self, rel_path: str, content: str) -> str:
        return _write_file(self.base, rel_path, content)

    def _scan(self, rel_dir: str, patterns=None):
        patterns = patterns or linter.FORBIDDEN_PATTERNS
        full_dir = os.path.join(self.base, rel_dir)
        return linter.scan_directory(full_dir, patterns, self.base)

    def _run_lint(self, strict=False):
        return linter.run_lint(self.base, strict=strict)


# ── 1. scan_file: clean files ─────────────────────────────────────────────────

class TestScanFileClean(_TempProjectMixin, unittest.TestCase):

    def test_empty_file_no_violations(self):
        f = self._make("spa_core/risk/clean.py", "")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(v, [])

    def test_stdlib_imports_no_violations(self):
        f = self._make("spa_core/risk/stdlib.py", """\
            import os
            import sys
            import json
            from pathlib import Path
        """)
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(v, [])

    def test_internal_import_no_violation(self):
        f = self._make("spa_core/risk/internal.py", """\
            from spa_core.adapters import some_adapter
            import spa_core.risk.policy
        """)
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(v, [])


# ── 2. scan_file: import anthropic ───────────────────────────────────────────

class TestScanFileImportAnthropic(_TempProjectMixin, unittest.TestCase):

    def test_bare_import_anthropic(self):
        f = self._make("spa_core/risk/bad.py", "import anthropic\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)
        lineno, text = v[0]
        self.assertEqual(lineno, 1)
        self.assertIn("anthropic", text)

    def test_from_anthropic_import(self):
        f = self._make("spa_core/risk/bad.py", "from anthropic import Anthropic\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_from_anthropic_submodule(self):
        f = self._make("spa_core/risk/bad.py", "from anthropic.types import Message\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_indented_import_anthropic(self):
        f = self._make("spa_core/risk/bad.py", """\
            def foo():
                import anthropic
        """)
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)


# ── 3. scan_file: comment lines must NOT trigger ─────────────────────────────

class TestScanFileComments(_TempProjectMixin, unittest.TestCase):

    def test_commented_import_anthropic_not_flagged(self):
        f = self._make("spa_core/risk/comments.py", "# import anthropic\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(v, [])

    def test_commented_from_anthropic_not_flagged(self):
        f = self._make("spa_core/risk/comments.py", "# from anthropic import Anthropic\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(v, [])

    def test_commented_import_openai_not_flagged(self):
        f = self._make("spa_core/risk/comments.py", "# import openai  # forbidden\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(v, [])

    def test_docstring_mentioning_anthropic_not_flagged(self):
        f = self._make("spa_core/risk/docs.py", '''\
            """
            This module does NOT use anthropic SDK.
            # import anthropic
            """
            import os
        ''')
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(v, [])


# ── 4. scan_file: other forbidden SDKs ───────────────────────────────────────

class TestScanFileOtherSDKs(_TempProjectMixin, unittest.TestCase):

    def test_import_openai(self):
        f = self._make("spa_core/adapters/bad.py", "import openai\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_from_openai(self):
        f = self._make("spa_core/adapters/bad.py", "from openai import ChatCompletion\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_import_langchain(self):
        f = self._make("spa_core/monitoring/bad.py", "import langchain\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_from_langchain(self):
        f = self._make("spa_core/monitoring/bad.py", "from langchain.llms import OpenAI\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_import_google_generativeai(self):
        f = self._make("spa_core/execution/bad.py", "import google.generativeai\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_from_google_generativeai(self):
        f = self._make("spa_core/execution/bad.py", "from google.generativeai import GenerativeModel\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_import_llama(self):
        f = self._make("spa_core/allocator/bad.py", "import llama\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)

    def test_from_llama(self):
        f = self._make("spa_core/allocator/bad.py", "from llama import LLaMA\n")
        v = linter.scan_file(f, linter.FORBIDDEN_PATTERNS)
        self.assertEqual(len(v), 1)


# ── 5. File skipping rules ────────────────────────────────────────────────────

class TestFileSkipping(_TempProjectMixin, unittest.TestCase):

    def test_pycache_dir_skipped(self):
        self._make("spa_core/risk/__pycache__/policy.cpython-311.py", "import anthropic\n")
        n_files, violations = self._scan("spa_core/risk")
        self.assertEqual(violations, [])
        self.assertEqual(n_files, 0)

    def test_pyc_file_skipped(self):
        path = os.path.join(self.base, "spa_core/risk/policy.pyc")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"import anthropic\n")
        n_files, violations = self._scan("spa_core/risk")
        self.assertEqual(violations, [])
        self.assertEqual(n_files, 0)

    def test_test_files_skipped(self):
        self._make("spa_core/risk/test_policy.py", "import anthropic\n")
        n_files, violations = self._scan("spa_core/risk")
        self.assertEqual(violations, [])
        self.assertEqual(n_files, 0)

    def test_nonpy_files_skipped(self):
        path = os.path.join(self.base, "spa_core/risk/README.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("import anthropic\n")
        n_files, violations = self._scan("spa_core/risk")
        self.assertEqual(violations, [])
        self.assertEqual(n_files, 0)

    def test_clean_py_file_counted(self):
        self._make("spa_core/risk/policy.py", "import os\n")
        n_files, violations = self._scan("spa_core/risk")
        self.assertEqual(n_files, 1)
        self.assertEqual(violations, [])


# ── 6. scan_directory edge cases ─────────────────────────────────────────────

class TestScanDirectory(_TempProjectMixin, unittest.TestCase):

    def test_nonexistent_dir_returns_zero(self):
        n_files, violations = self._scan("spa_core/no_such_dir")
        self.assertEqual(n_files, 0)
        self.assertEqual(violations, [])

    def test_multiple_violations_in_one_file(self):
        self._make("spa_core/risk/multi.py", """\
            import anthropic
            import openai
        """)
        n_files, violations = self._scan("spa_core/risk")
        self.assertEqual(n_files, 1)
        self.assertEqual(len(violations), 2)

    def test_violation_rel_path_format(self):
        self._make("spa_core/risk/bad.py", "import anthropic\n")
        _, violations = self._scan("spa_core/risk")
        self.assertEqual(len(violations), 1)
        rel_path, lineno, text = violations[0]
        # rel_path should not be absolute
        self.assertFalse(os.path.isabs(rel_path))
        self.assertIn("bad.py", rel_path)
        self.assertIsInstance(lineno, int)
        self.assertGreater(lineno, 0)


# ── 7. run_lint: exit codes and summary ──────────────────────────────────────

class TestRunLint(_TempProjectMixin, unittest.TestCase):

    def test_clean_project_zero_violations(self):
        # Populate all default scan dirs with clean files
        for rel_dir in linter.SCAN_DIRS_DEFAULT:
            self._make(f"{rel_dir}/module.py", "import os\nimport json\n")
        n_files, violations = self._run_lint(strict=False)
        self.assertEqual(violations, [])
        self.assertGreater(n_files, 0)

    def test_dirty_project_nonzero_violations(self):
        self._make("spa_core/risk/bad.py", "import anthropic\n")
        _, violations = self._run_lint(strict=False)
        self.assertGreater(len(violations), 0)

    def test_strict_includes_spa_agents(self):
        # Only spa_agents has a violation; default scan should miss it
        self._make("spa_agents/agent.py", "import anthropic\n")
        _, v_default = self._run_lint(strict=False)
        _, v_strict = self._run_lint(strict=True)
        self.assertEqual(len(v_default), 0)
        self.assertGreater(len(v_strict), 0)


# ── 8. main() exit codes ─────────────────────────────────────────────────────

class TestMainExitCodes(_TempProjectMixin, unittest.TestCase):

    def _run_main(self, extra_args=None):
        """Run linter.main() with --base-dir pointing at temp project."""
        argv = ["--base-dir", self.base] + (extra_args or [])
        return linter.main(argv)

    def test_exit_0_on_clean(self):
        # No files at all in scan dirs — should be clean
        exit_code = self._run_main()
        self.assertEqual(exit_code, 0)

    def test_exit_1_on_violation(self):
        self._make("spa_core/risk/bad.py", "import anthropic\n")
        exit_code = self._run_main()
        self.assertEqual(exit_code, 1)

    def test_exit_0_strict_no_spa_agents_violation(self):
        exit_code = self._run_main(["--strict"])
        self.assertEqual(exit_code, 0)

    def test_exit_1_strict_with_spa_agents_violation(self):
        self._make("spa_agents/agent.py", "import anthropic\n")
        exit_code = self._run_main(["--strict"])
        self.assertEqual(exit_code, 1)


# ── 9. Output format ─────────────────────────────────────────────────────────

class TestOutputFormat(_TempProjectMixin, unittest.TestCase):

    def test_violation_output_contains_violation_prefix(self, capsys=None):
        """VIOLATION: prefix must appear in stdout for bad files."""
        import io
        from contextlib import redirect_stdout
        self._make("spa_core/risk/bad.py", "import anthropic\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            linter.main(["--base-dir", self.base])
        output = buf.getvalue()
        self.assertIn("VIOLATION:", output)

    def test_summary_line_in_output(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            linter.main(["--base-dir", self.base])
        output = buf.getvalue()
        self.assertIn("Scanned", output)
        self.assertIn("violations", output)

    def test_violation_line_contains_filename(self):
        import io
        from contextlib import redirect_stdout
        self._make("spa_core/risk/badfile.py", "import anthropic\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            linter.main(["--base-dir", self.base])
        output = buf.getvalue()
        self.assertIn("badfile.py", output)

    def test_violation_line_contains_lineno(self):
        import io
        from contextlib import redirect_stdout
        self._make("spa_core/risk/bad.py", "# ok\nimport openai\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            linter.main(["--base-dir", self.base])
        output = buf.getvalue()
        # Line 2 should appear in the violation
        self.assertIn(":2:", output)

    def test_clean_run_zero_violations_summary(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            linter.main(["--base-dir", self.base])
        output = buf.getvalue()
        self.assertIn("found 0 violations", output)


# ── 10. _is_test_file and _should_skip helpers ───────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_is_test_file_true(self):
        self.assertTrue(linter._is_test_file("test_policy.py"))

    def test_is_test_file_false_for_regular(self):
        self.assertFalse(linter._is_test_file("policy.py"))

    def test_should_skip_pycache(self):
        self.assertTrue(linter._should_skip("/some/__pycache__", "module.py"))

    def test_should_skip_pyc(self):
        self.assertTrue(linter._should_skip("/some/path", "module.pyc"))

    def test_should_skip_test_file(self):
        self.assertTrue(linter._should_skip("/some/path", "test_module.py"))

    def test_should_not_skip_regular_py(self):
        self.assertFalse(linter._should_skip("/some/path", "module.py"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
