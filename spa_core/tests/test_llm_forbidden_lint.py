"""Tests for the LLM-forbidden static lint (SPA-V416 / MP-309).

unittest only (pytest is not installed in this repo). All fixtures are built
in temporary directories — the real repo code is never modified. The single
test that touches the real checkout (`test_real_repo_is_clean`) is the actual
constitutional enforcement: if it goes red, somebody imported an LLM SDK into
risk/execution/allocator.

Run::

    python3 -m unittest spa_core.tests.test_llm_forbidden_lint
"""
import json
import os
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

from spa_core.ci.llm_forbidden_lint import (
    FORBIDDEN_DIRS,
    FORBIDDEN_IMPORTS,
    find_forbidden_imports,
    run_lint,
    write_report_atomic,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_repo(tmp: Path, files: dict) -> Path:
    """Create a fake repo layout: {relative_path: source_text}."""
    for rel, src in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
    return tmp


class TestFindForbiddenImports(unittest.TestCase):
    def test_plain_import_anthropic(self):
        v = find_forbidden_imports("import anthropic\n", "x.py")
        self.assertEqual(len(v), 1)
        self.assertEqual((v[0].file, v[0].line, v[0].module), ("x.py", 1, "anthropic"))

    def test_from_anthropic_import(self):
        v = find_forbidden_imports("from anthropic import Anthropic\n", "x.py")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].module, "anthropic")

    def test_dotted_submodule_import(self):
        v = find_forbidden_imports("import anthropic.foo.bar\n", "x.py")
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].module, "anthropic.foo.bar")

    def test_google_generativeai_caught_but_plain_google_ok(self):
        v = find_forbidden_imports(
            "import google.generativeai\n"
            "from google.generativeai import GenerativeModel\n"
            "from google import generativeai\n"
            "import google.cloud\n",  # plain google.* is NOT forbidden
            "x.py",
        )
        self.assertEqual(len(v), 3)
        self.assertTrue(all(m.module.startswith("google.generativeai") for m in v))

    def test_legal_imports_not_flagged(self):
        src = (
            "import json\nimport os\nfrom pathlib import Path\n"
            "from typing import Dict\nimport logging\n"
        )
        self.assertEqual(find_forbidden_imports(src, "x.py"), [])

    def test_comment_and_string_not_flagged(self):
        src = (
            "# import anthropic  <- just a comment\n"
            "s = 'import anthropic'\n"
            'doc = """from anthropic import Anthropic"""\n'
        )
        self.assertEqual(find_forbidden_imports(src, "x.py"), [])

    def test_all_forbidden_sdks_caught(self):
        for mod in ("openai", "langchain", "litellm"):
            with self.subTest(mod=mod):
                v = find_forbidden_imports(f"import {mod}\n", "x.py")
                self.assertEqual([x.module for x in v], [mod])

    def test_line_numbers_correct(self):
        src = "import os\nimport json\n\nimport anthropic\n"
        v = find_forbidden_imports(src, "x.py")
        self.assertEqual(v[0].line, 4)


class TestRunLintOnFixtures(unittest.TestCase):
    def test_clean_directory_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {
                "spa_core/risk/policy.py": "import json\nX = 1\n",
                "spa_core/execution/router.py": "import os\n",
                "spa_core/allocator/allocator.py": "from pathlib import Path\n",
                "spa_core/monitoring/health.py": "import logging\n",
            })
            report = run_lint(tmp)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["violations"], [])
            self.assertEqual(report["files_scanned"], 4)
            self.assertEqual(sorted(report["scanned_dirs"]),
                             sorted(FORBIDDEN_DIRS))

    def test_planted_violation_detected_with_file_line_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {
                "spa_core/risk/policy.py": "import json\n\nimport anthropic\n",
            })
            report = run_lint(tmp)
            self.assertEqual(report["status"], "violations")
            self.assertEqual(report["violations"], [{
                "file": "spa_core/risk/policy.py",
                "line": 3,
                "module": "anthropic",
            }])

    def test_violation_in_nested_subdir_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {
                "spa_core/execution/adapters/deep/mod.py":
                    "from openai import OpenAI\n",
            })
            report = run_lint(tmp)
            self.assertEqual(report["status"], "violations")
            self.assertEqual(report["violations"][0]["file"],
                             "spa_core/execution/adapters/deep/mod.py")
            self.assertEqual(report["violations"][0]["module"], "openai")

    def test_pycache_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {
                "spa_core/risk/ok.py": "import json\n",
                "spa_core/risk/__pycache__/evil.py": "import anthropic\n",
            })
            report = run_lint(tmp)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["files_scanned"], 1)

    def test_syntax_error_goes_to_parse_errors_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {
                "spa_core/risk/broken.py": "def f(:\n    pass\n",
                "spa_core/risk/evil.py": "import litellm\n",
            })
            report = run_lint(tmp)  # must not raise
            self.assertEqual(len(report["parse_errors"]), 1)
            self.assertEqual(report["parse_errors"][0]["file"],
                             "spa_core/risk/broken.py")
            self.assertIn("SyntaxError", report["parse_errors"][0]["error"])
            # the broken file must not mask the violation next door
            self.assertEqual(report["status"], "violations")
            self.assertEqual(report["violations"][0]["module"], "litellm")

    def test_missing_forbidden_dir_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {
                "spa_core/risk/policy.py": "import json\n",
                # no spa_core/execution, no spa_core/allocator
            })
            report = run_lint(tmp)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["scanned_dirs"], ["spa_core/risk"])

    def test_no_dirs_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_lint(tmp)  # empty root: none of FORBIDDEN_DIRS exist
            self.assertEqual(report["status"], "no_dirs")
            self.assertEqual(report["scanned_dirs"], [])
            report2 = run_lint(tmp, forbidden_dirs=[])  # explicit empty list
            self.assertEqual(report2["status"], "no_dirs")

    def test_report_schema_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {"spa_core/risk/a.py": "import os\n"})
            report = run_lint(tmp)
            for key in ("generated_at", "root", "forbidden_imports",
                        "scanned_dirs", "files_scanned", "violations",
                        "parse_errors", "status"):
                self.assertIn(key, report)
            self.assertEqual(report["forbidden_imports"],
                             sorted(FORBIDDEN_IMPORTS))


class TestMonitoringFenced(unittest.TestCase):
    """WS2: spa_core/monitoring must be inside the LLM fence (CLAUDE.md rule#5)."""

    def test_monitoring_in_forbidden_dirs(self):
        self.assertIn("spa_core/monitoring", FORBIDDEN_DIRS,
                      "monitoring must be LLM-forbidden (CLAUDE.md rule#5)")

    def test_monitoring_violation_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {
                "spa_core/monitoring/evil.py": "import anthropic\n",
            })
            report = run_lint(tmp)
            self.assertEqual(report["status"], "violations")
            self.assertEqual(report["violations"][0]["file"],
                             "spa_core/monitoring/evil.py")
            self.assertEqual(report["violations"][0]["module"], "anthropic")

    def test_real_monitoring_dir_is_scanned_and_clean(self):
        report = run_lint(_REPO_ROOT)
        self.assertIn("spa_core/monitoring", report["scanned_dirs"],
                      "monitoring dir must actually be scanned")
        self.assertEqual(report["status"], "ok", report["violations"])


class TestAtomicWrite(unittest.TestCase):
    def test_write_report_atomic_no_tmp_leftovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data" / "llm_forbidden_lint.json"
            report = {"status": "ok", "violations": []}
            write_report_atomic(report, out)
            self.assertTrue(out.exists())
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), report)
            leftovers = list(Path(tmp).rglob("*.tmp"))
            self.assertEqual(leftovers, [], f"tmp leftovers: {leftovers}")


class TestRealRepoEnforcement(unittest.TestCase):
    """The actual constitutional check: the live checkout must be clean."""

    def test_real_repo_is_clean(self):
        report = run_lint(_REPO_ROOT)
        self.assertEqual(
            report["status"], "ok",
            "CONSTITUTION VIOLATION: LLM SDK import found in a deterministic "
            f"domain — {report['violations']} (parse_errors: {report['parse_errors']})",
        )
        # all three deterministic domains exist and were actually scanned
        self.assertEqual(sorted(report["scanned_dirs"]), sorted(FORBIDDEN_DIRS))
        self.assertGreater(report["files_scanned"], 0)
        self.assertEqual(report["parse_errors"], [])


class TestCLI(unittest.TestCase):
    def _run_cli(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "spa_core.ci.llm_forbidden_lint", *args],
            capture_output=True, text=True, cwd=cwd or str(_REPO_ROOT),
        )

    def test_cli_exit_0_on_clean_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {"spa_core/risk/a.py": "import json\n"})
            proc = self._run_cli("--root", tmp, "--no-write")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("status=ok", proc.stdout)

    def test_cli_exit_1_on_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {"spa_core/risk/a.py": "import anthropic\n"})
            proc = self._run_cli("--root", tmp, "--no-write")
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("VIOLATION", proc.stdout)

    def test_cli_exit_2_on_no_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run_cli("--root", tmp, "--no-write")
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertIn("status=no_dirs", proc.stdout)

    def test_cli_writes_report_via_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {"spa_core/risk/a.py": "import json\n"})
            out = Path(tmp) / "report" / "lint.json"
            proc = self._run_cli("--root", tmp, "--out", str(out))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(doc["status"], "ok")
            self.assertEqual(list(Path(tmp).rglob("*.tmp")), [])

    def test_cli_no_write_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(Path(tmp), {"spa_core/risk/a.py": "import json\n"})
            out = Path(tmp) / "lint.json"
            proc = self._run_cli("--root", tmp, "--out", str(out), "--no-write")
            self.assertEqual(proc.returncode, 0)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
