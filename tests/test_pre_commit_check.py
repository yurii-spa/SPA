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
import tempfile
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

    # 2026-09-17: знаменатель больше не перечисляется руками. Тест знал «/4» и «/6», ADR-402
    # добавил седьмой шаг — и main покраснел не от дефекта, а от того, что список допустимых
    # чисел отстал от скрипта. Теперь знаменатель ЧИТАЕТСЯ из скрипта, а проверяется свойство:
    # он один на весь скрипт, шагов не меньше четырёх, и объявлен КАЖДЫЙ шаг от 1 до N. Это
    # строже прежнего: раньше «[4/6]» засчитывался как «последний шаг», а пропуск шага и два
    # разных знаменателя в одном файле не ловились вовсе.
    def _counters(self):
        import re
        return [(int(a), int(b)) for a, b in re.findall(r'echo "\[(\d+)/(\d+)\]', self.content)]

    def test_contains_gate_counter_1_of_4(self):
        counters = self._counters()
        self.assertTrue(counters, "pre-commit script announces no gate counters at all")
        denominators = {n for _, n in counters}
        self.assertEqual(len(denominators), 1, f"gate counters disagree on the total: {sorted(denominators)}")
        self.assertGreaterEqual(denominators.pop(), 4, "the gate may grow, it may not shrink below the original four")
        self.assertIn(1, [i for i, _ in counters], "Expected the first gate counter in pre-commit script")

    def test_contains_gate_counter_4_of_4(self):
        counters = self._counters()
        self.assertTrue(counters, "pre-commit script announces no gate counters at all")
        total = counters[0][1]
        self.assertEqual(sorted(i for i, _ in counters), list(range(1, total + 1)),
                         "Expected every gate from 1 to the final one to be announced exactly once")


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


class TestBareExceptionGateBehavior(unittest.TestCase):
    """Positive control for gate [1/6] (found in the wild 2026-09-02): the gate's
    own display grep lacked --exclude-dir=tests/scripts (already fixed by the
    decision grep having them), and it had no way to tell a genuine bare
    exception from explicitly-marked drill/fault-injection scaffolding
    (spa_core/paper_trading/pre_cutover_gate.py, spa_core/execution/eth_signer.py)
    — the gate failed on EVERY commit regardless of what was actually staged.
    Fix: lines carrying the literal ``# drill:`` marker are excluded from the
    match, by marker text, not by path — a NEW unmarked bare exception must
    still fail this gate."""

    def _gate_would_fail(self, tmp_path: Path) -> bool:
        """Runs the exact grep pipeline gate [1/6] uses against a synthetic tree."""
        result = subprocess.run(
            ["bash", "-c",
             'grep -rn --include="*.py" --exclude-dir=__pycache__ --exclude-dir=tests '
             '--exclude-dir=scripts --exclude-dir=".git" '
             r'-E "raise\s+(Exception|RuntimeError)\s*\(" spa_core/ 2>/dev/null '
             '| grep -v "# drill:" | grep -q .'],
            cwd=tmp_path,
        )
        return result.returncode == 0  # grep -q found something ⇒ gate fails

    def test_real_unmarked_bare_exception_still_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            d = tmp_path / "spa_core" / "risk"
            d.mkdir(parents=True)
            (d / "policy.py").write_text('raise RuntimeError("boom")\n', encoding="utf-8")
            self.assertTrue(self._gate_would_fail(tmp_path))

    def test_drill_marked_fault_injection_does_not_fail_the_gate(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            d = tmp_path / "spa_core" / "paper_trading"
            d.mkdir(parents=True)
            (d / "pre_cutover_gate.py").write_text(
                'raise RuntimeError("signer failure")  # drill: intentional fault injection\n',
                encoding="utf-8")
            self.assertFalse(self._gate_would_fail(tmp_path))

    def test_pre_commit_check_sh_carries_the_drill_marker_exclusion(self):
        content = _read(PRE_COMMIT)
        self.assertIn("# drill:", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
