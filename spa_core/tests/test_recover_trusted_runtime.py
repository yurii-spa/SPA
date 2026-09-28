"""
Regression tests for scripts/recover_trusted_runtime.sh — the narrowly-scoped OWNER recovery
utility for a content-correct but inaccessible trusted runtime (the Checkpoint-D 0700 defect).

Architecture Review Board correction pass. These tests cover the fail-closed safety semantics
the Board required WITHOUT root:

  BEHAVIOURAL (no root; STUDIO_TRUSTED_ROOT sandbox + --dry-run):
    - a bare/no-mode invocation mutates nothing
    - --execute as a non-root user is refused
    - a non-hex digest is refused
    - a runtime.json runtime_id mismatch is refused
    - a missing control file is refused
    - --dry-run against a staged broken runtime performs ZERO mutation

  GUARD-PREDICATE (no root; the exact `[ -e X ] || [ -L X ]` test the script uses, run against
  real fixtures — including a dangling symlink that a bare `-e` would MISS):
    - a pre-existing TEMP object is rejected
    - a TEMP dangling symlink is caught by `-e || -L` (and would be missed by `-e` alone)
    - a pre-existing quarantine object is rejected
    - a quarantine dangling symlink is caught by `-e || -L`

  STRUCTURAL LINKAGE (assert the live script carries the exact guards the predicate tests
  reproduce — the root-only --execute path cannot be run here; a non-privileged test must not
  fake root, mirroring test_trusted_runtime.py's stance):
    - TEMP is claimed via atomic `mkdir` (ownership), never `rm -rf "$TEMP"` before creation
    - TEMP and quarantine guards both reject `-e || -L`
    - cleanup preserves the quarantine and NEVER auto-restores the broken runtime
    - publish-failure message preserves artifacts and STOPs
    - the active-workload guard inspects gui/<uid> and resolves the fleet home via dscl, not $HOME
    - post-publish verification is mandatory

Pure stdlib; skips nothing that can run without root.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RECOVER = REPO_ROOT / "scripts" / "recover_trusted_runtime.sh"

# a valid 64-char lowercase-hex digest for the sandbox (content is irrelevant here)
SANDBOX_DIGEST = "abcdef0123456789" * 4
SANDBOX_RID = "python-3.13-" + SANDBOX_DIGEST[:16]


def _read() -> str:
    return RECOVER.read_text(encoding="utf-8")


def _run(args, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(RECOVER), *args],
        capture_output=True, text=True, env=env,
    )


def _stage_sandbox(root: Path):
    """Stage a minimal trusted-root sandbox so --dry-run reaches the 'confirmed broken' branch:
    control files present, a DST directory that fails as-user verify (no valid python)."""
    tc = root / "toolchains"
    dst = tc / SANDBOX_RID
    (dst).mkdir(parents=True)
    (dst / "placeholder").write_text("not a real runtime\n", encoding="utf-8")  # digest != expected
    (root / "runtime.json").write_text(
        '{"runtime_id": "%s", "app_python": "%s/bin/python3"}\n' % (SANDBOX_RID, dst),
        encoding="utf-8")
    (root / "approved_release.json").write_text('{"release_sha": "sandbox"}\n', encoding="utf-8")
    (root / "bin").mkdir()
    (root / "bin" / "release_launcher-x.py").write_text("# launcher\n", encoding="utf-8")
    (root / "releases" / "rel1").mkdir(parents=True)
    return dst


class TestBehaviouralRefusals(unittest.TestCase):
    def test_no_mode_refuses_and_mutates_nothing(self):
        r = _run(["--runtime", "/x", "--runtime-digest", SANDBOX_DIGEST])
        self.assertEqual(r.returncode, 1)
        self.assertIn("specify exactly one of --dry-run | --execute", r.stderr)

    def test_execute_as_nonroot_is_refused(self):
        if os.geteuid() == 0:
            self.skipTest("running as root — this refusal is for the non-root case")
        r = _run(["--execute", "--runtime", "/x", "--runtime-digest", SANDBOX_DIGEST])
        self.assertEqual(r.returncode, 1)
        self.assertIn("--execute needs root", r.stderr)

    def test_nonhex_digest_refused(self):
        r = _run(["--dry-run", "--runtime", "/x", "--runtime-digest", "NOTHEX"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("lowercase hex", r.stderr)

    def test_runtime_json_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "toolchains").mkdir()
            (root / "runtime.json").write_text(
                '{"runtime_id": "python-3.13-DIFFERENT", "app_python": "/nope"}\n', encoding="utf-8")
            r = _run(["--dry-run", "--runtime", "/x", "--runtime-digest", SANDBOX_DIGEST],
                     env_extra={"STUDIO_TRUSTED_ROOT": str(root)})
            self.assertEqual(r.returncode, 1)
            self.assertIn("runtime.json runtime_id", r.stderr)

    def test_missing_control_file_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dst = (root / "toolchains" / SANDBOX_RID)
            dst.mkdir(parents=True)
            (root / "runtime.json").write_text(
                '{"runtime_id": "%s", "app_python": "%s/bin/python3"}\n' % (SANDBOX_RID, dst),
                encoding="utf-8")
            # approved_release.json deliberately absent
            r = _run(["--dry-run", "--runtime", "/x", "--runtime-digest", SANDBOX_DIGEST],
                     env_extra={"STUDIO_TRUSTED_ROOT": str(root)})
            self.assertEqual(r.returncode, 1)
            self.assertIn("control file missing", r.stderr)


class TestDryRunZeroMutation(unittest.TestCase):
    def test_dry_run_reaches_confirmed_broken_and_mutates_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _stage_sandbox(root)
            tc = root / "toolchains"
            before = sorted(p.name for p in tc.iterdir())
            r = _run(["--dry-run", "--runtime", "/x", "--runtime-digest", SANDBOX_DIGEST],
                     env_extra={"STUDIO_TRUSTED_ROOT": str(root)})
            after = sorted(p.name for p in tc.iterdir())
            self.assertEqual(r.returncode, 0, f"dry-run failed:\n{r.stdout}\n{r.stderr}")
            self.assertIn("no mutation performed", r.stdout)
            self.assertIn("confirmed: broken runtime present", r.stdout)
            # ZERO mutation: no lock, no TEMP, no quarantine created
            self.assertEqual(before, after, f"dry-run mutated toolchains: {before} -> {after}")
            self.assertFalse(any(n.startswith(".recover") or n.startswith(".quarantine") for n in after))


class TestGuardPredicate(unittest.TestCase):
    """The exact refusal predicate the script uses: `[ -e X ] || [ -L X ]`."""

    @staticmethod
    def _guard_refuses(path: str) -> bool:
        # returns True when the guard would FAIL-CLOSED (object exists, incl. dangling symlink)
        return subprocess.run(["bash", "-c", '[ -e "$1" ] || [ -L "$1" ]', "_", path]).returncode == 0

    @staticmethod
    def _bare_e(path: str) -> bool:
        return subprocess.run(["bash", "-c", '[ -e "$1" ]', "_", path]).returncode == 0

    def test_preexisting_temp_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".recover-preexisting"
            p.mkdir()
            self.assertTrue(self._guard_refuses(str(p)))

    def test_temp_dangling_symlink_missed_by_bare_e_but_caught_by_e_or_L(self):
        with tempfile.TemporaryDirectory() as td:
            link = Path(td) / ".recover-dangling"
            link.symlink_to(Path(td) / "no-such-target")  # dangling
            self.assertFalse(self._bare_e(str(link)),
                             "a bare -e MISSES a dangling symlink — this is why -L is required")
            self.assertTrue(self._guard_refuses(str(link)),
                            "-e || -L must catch a dangling symlink")

    def test_preexisting_quarantine_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".quarantine-preexisting"
            p.mkdir()
            self.assertTrue(self._guard_refuses(str(p)))

    def test_quarantine_dangling_symlink_caught_by_e_or_L(self):
        with tempfile.TemporaryDirectory() as td:
            link = Path(td) / ".quarantine-dangling"
            link.symlink_to(Path(td) / "no-such-target")
            self.assertFalse(self._bare_e(str(link)))
            self.assertTrue(self._guard_refuses(str(link)))


class TestStructuralGuards(unittest.TestCase):
    def setUp(self):
        self.s = _read()

    def test_bash_syntax_valid(self):
        r = subprocess.run(["bash", "-n", str(RECOVER)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_temp_claimed_via_mkdir_not_rm_rf(self):
        self.assertIn('mkdir "$TEMP"', self.s, "TEMP must be claimed atomically via mkdir")
        # A pre-existing TEMP is REFUSED, not deleted. The only allowed `rm -rf "$TEMP"` is inside
        # cleanup(), gated by TEMP_OWNED=1 (a TEMP THIS invocation created) — never an unguarded delete
        # of an unknown path in the prepare/build path.
        for line in self.s.splitlines():
            if 'rm -rf "$TEMP"' in line:
                self.assertIn("TEMP_OWNED", line,
                              f'unguarded `rm -rf "$TEMP"` — must be gated by TEMP_OWNED:\n{line}')
        # the guard must precede the mkdir claim
        guard_i = self.s.index('[ -e "$TEMP" ] || [ -L "$TEMP" ]')
        mkdir_i = self.s.index('mkdir "$TEMP"')
        self.assertLess(guard_i, mkdir_i, "the pre-existence guard must come before the mkdir claim")

    def test_temp_guard_rejects_e_or_L(self):
        self.assertIn('[ -e "$TEMP" ] || [ -L "$TEMP" ]', self.s)

    def test_quarantine_guard_rejects_e_or_L(self):
        self.assertIn('[ -e "$QUAR" ] || [ -L "$QUAR" ]', self.s)

    def test_cleanup_never_restores_broken_runtime(self):
        # the broken runtime must never be moved back over the destination
        self.assertNotIn('mv "$QUAR" "$DST"', self.s)
        self.assertIn("NOT restored", self.s)

    def test_cleanup_preserves_quarantine_in_quarantined_state(self):
        self.assertIn("QUARANTINED)", self.s)
        self.assertIn("PRESERVED", self.s)
        # the quarantine path is never deleted by the script (cleanup only removes TEMP/LOCK)
        self.assertNotIn('rm -rf "$QUAR"', self.s)

    def test_publish_failure_message_preserves_and_stops(self):
        self.assertIn("Quarantine + TEMP preserved", self.s)
        self.assertIn("STOP and escalate", self.s)

    def test_state_machine_states_declared(self):
        for st in ("INIT", "PREPARE", "TEMP_VERIFIED", "QUARANTINED", "PUBLISHED"):
            self.assertIn(st, self.s, f"missing recovery state {st}")

    def test_launchd_uses_gui_uid_domain_and_dscl_home_not_HOME(self):
        self.assertIn('gui/$FLEET_UID/$lbl', self.s, "user LaunchAgents live in gui/<uid>")
        self.assertIn("system/$lbl", self.s, "LaunchDaemons live in the system domain")
        self.assertIn("NFSHomeDirectory", self.s, "fleet home must be resolved via dscl, not $HOME")
        self.assertNotIn('"$HOME"/Library/LaunchAgents', self.s,
                         "$HOME under sudo is root's home — must not be used to find the fleet user's agents")

    def test_post_publish_verify_mandatory(self):
        self.assertIn("post-publish verify", self.s)


class TestExecuteRootSeamAndFleetUser(unittest.TestCase):
    """ARB item 1 + 2: --execute must forbid the STUDIO_TRUSTED_ROOT test seam and demand a real
    non-root fleet user, all BEFORE any mutation. The production-root guard precedes the euid check,
    so the seam refusal is reachable without root."""

    def test_execute_with_nonproduction_root_refuses_before_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "toolchains").mkdir()
            before = sorted(p.name for p in (root / "toolchains").iterdir())
            r = _run(["--execute", "--runtime", "/x", "--runtime-digest", SANDBOX_DIGEST],
                     env_extra={"STUDIO_TRUSTED_ROOT": str(root)})
            self.assertEqual(r.returncode, 1)
            self.assertIn("non-production trusted root", r.stderr)
            after = sorted(p.name for p in (root / "toolchains").iterdir())
            self.assertEqual(before, after, "must not mutate before the seam refusal")
            self.assertFalse(any(n.startswith(".recover") or n.startswith(".quarantine") for n in after))

    def test_execute_as_nonroot_without_seam_refuses_needs_root(self):
        if os.geteuid() == 0:
            self.skipTest("only meaningful as a non-root caller")
        # default ROOT = production ⇒ item-1 passes; the euid==0 check then refuses (before the lock/mutation)
        r = _run(["--execute", "--runtime", "/x", "--runtime-digest", SANDBOX_DIGEST])
        self.assertEqual(r.returncode, 1)
        self.assertIn("needs root", r.stderr)


class TestExecuteGuardsStructural(unittest.TestCase):
    """The root-gated sub-checks (euid 0 required) cannot be exercised without root; assert the exact
    guard code is present and ordered before any mutation."""

    def setUp(self):
        self.s = _read()

    def test_execute_requires_exact_production_root(self):
        self.assertIn('[ "$ROOT" = "/Library/Application Support/StudioOS" ]', self.s)

    def test_execute_rejects_studio_trusted_root_env(self):
        self.assertIn('${STUDIO_TRUSTED_ROOT:-}', self.s)
        self.assertIn("STUDIO_TRUSTED_ROOT set", self.s)

    def test_execute_requires_sudo_user_present(self):
        self.assertIn("SUDO_USER unset", self.s)

    def test_execute_rejects_sudo_user_root(self):
        self.assertIn('"$SUDO_USER" != root', self.s)

    def test_execute_rejects_fleet_uid_zero(self):
        self.assertIn("fleet uid 0", self.s)
        self.assertIn('id -u "$SUDO_USER"', self.s)

    def test_execute_guards_precede_any_mutation(self):
        guard_i = self.s.index("non-production trusted root")
        lock_i = self.s.index('mkdir "$LOCK"')
        self.assertLess(guard_i, lock_i, "the --execute guards must precede the first mutation (mkdir lock)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
