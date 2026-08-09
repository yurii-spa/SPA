# LLM_FORBIDDEN
"""spa_core/tests/test_deploy_gate_long_lived.py — the gate must not start a never-exiting agent.

INCIDENT REPLAYED HERE (2026-08-08, card `inbox-geit-pered-deploem-podnimaet-vtorogo-tel`).
`scripts/check_agent_before_deploy.sh` proved an agent works by RUNNING IT ONCE. For
`telegram_bot` — a KeepAlive poller that never exits — that started a SECOND bot (pid 90696)
on the SAME Telegram token beside the live one. Two pollers on one token means 409-conflicts
on getUpdates: the owner's taps and commands go to whichever poller wins, and part of them are
lost. The second instance lived for the gate's whole RUN_TIMEOUT (~3 min) while the gate printed
nothing at all. The check was more dangerous than the failure it guards against.

Every test below is a POSITIVE CONTROL — it fails on the un-fixed gate:
  * the long-lived agent's wrapper is EXECUTED (marker file appears) instead of probed;
  * the gate burns the full RUN_TIMEOUT instead of finishing in seconds;
  * `<key>KeepAlive</key><false/>` was read as "KeepAlive" (the key was grepped, not the value),
    so a genuine hang in a scheduled agent was accepted as "server started OK".

Controls in BOTH directions, so the assertions cannot pass vacuously:
  * the SAME wrapper + SAME marker under a scheduled (run-once) plist MUST still be executed;
  * the static path must still REFUSE a broken import, a non-executable entrypoint, a wrapper
    that does not parse, an unresolvable python target and an unwritable launchd log dir.

The gate hardcodes REPO_ROOT so its hash guard can never be aimed at a decoy tree. These tests
use `SPA_GATE_REPO_ROOT`, which the gate accepts ONLY together with CHECK_ONLY=1 (never loads
anything) — that refusal is itself pinned below.
"""
from __future__ import annotations

import os
import subprocess
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "scripts" / "check_agent_before_deploy.sh"
_PROBE = _REPO / "scripts" / "agent_static_probe.sh"

_LONG_LIVED_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.{name}</string>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>{wrapper}</string>
  </array>
  <key>StandardOutPath</key><string>{out}</string>
  <key>StandardErrorPath</key><string>{err}</string>
</dict></plist>
"""

# KeepAlive FALSE + a schedule: an ordinary run-once agent. It must keep the run-once
# validation — that is what makes the "no execution" assertions above non-vacuous.
_SCHEDULED_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.{name}</string>
  <key>KeepAlive</key><false/>
  <key>StartInterval</key><integer>3600</integer>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>{wrapper}</string>
  </array>
  <key>StandardOutPath</key><string>{out}</string>
  <key>StandardErrorPath</key><string>{err}</string>
</dict></plist>
"""


class _Fixture:
    """A throw-away repo root with one agent in it (never the canonical tree)."""

    def __init__(self, tmp: Path, name: str):
        self.root = tmp
        self.name = name
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        self.marker = self.root / "EXECUTED_MARKER"
        self.wrapper = self.root / "scripts" / f"agent_{name}.sh"
        self.plist = self.root / "scripts" / f"com.spa.{name}.plist"
        self.out = self.root / "logs" / f"{name}.out"
        self.err = self.root / "logs" / f"{name}.err"

    def write_wrapper(self, body: str, mode: int = 0o755) -> None:
        self.wrapper.write_text(body, encoding="utf-8")
        self.wrapper.chmod(mode)

    def write_plist(self, template: str = _LONG_LIVED_PLIST, **over) -> None:
        text = template.format(
            name=self.name, wrapper=str(self.wrapper),
            out=over.get("out", str(self.out)), err=over.get("err", str(self.err)),
        )
        self.plist.write_text(text, encoding="utf-8")

    def run_gate(self, timeout: int = 120, **env_over) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update({
            "CHECK_ONLY": "1",
            "SPA_GATE_REPO_ROOT": str(self.root),
            "SPA_PROBE_PYTHON": os.sys.executable,
            "RUN_TIMEOUT": "8",          # keep the un-fixed (run-once) path short
            "KICKSTART_TIMEOUT": "5",
        })
        env.update(env_over)
        return subprocess.run(
            ["/bin/bash", str(_GATE), self.name],
            capture_output=True, text=True, env=env, timeout=timeout, cwd=str(self.root),
        )


def _wrapper_marks_then_exits(marker: Path, module: str = "json") -> str:
    """A wrapper that RECORDS it was executed and exits 0 (the detector for 'was it run?')."""
    return (
        "#!/bin/bash\n"
        f'MODULE="{module}"\n'
        f'echo "RAN $(date -u)" >> "{marker}"\n'
        "exit 0\n"
    )


def _wrapper_marks_then_never_exits(marker: Path, module: str = "json") -> str:
    """The telegram_bot shape: it records that it started and then never returns."""
    return (
        "#!/bin/bash\n"
        f'MODULE="{module}"\n'
        f'echo "RAN $(date -u)" >> "{marker}"\n'
        "exec /bin/sleep 600\n"
    )


class TestGateNeverStartsALongLivedAgent(unittest.TestCase):
    """The incident itself."""

    def setUp(self):
        self._tmpdirs = []
        self._labels = []

    def tearDown(self):
        import shutil
        # Safety net, measured the hard way while mutation-testing this file: with the
        # CHECK_ONLY interlock removed the gate ran to completion and actually LOADED the
        # fixture agent into the host launchd (KeepAlive → it respawns forever). Under the
        # correct code that path is refused, so this loop is a no-op — but a test that can
        # ever install a launchd job must be the thing that removes it.
        for label in self._labels:
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                           capture_output=True, text=True)
            plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
            if plist.exists():
                plist.unlink()
        for d in self._tmpdirs:
            shutil.rmtree(d, ignore_errors=True)

    def _fixture(self, name: str) -> _Fixture:
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="spa_gate_fx_"))
        self._tmpdirs.append(tmp)
        self._labels.append(f"com.spa.{name}")
        return _Fixture(tmp, name)

    def test_long_lived_agent_is_NOT_executed_by_the_gate(self):
        """THE incident: validating telegram_bot must not put a second poller on the token."""
        fx = self._fixture("gatefx_longlived")
        fx.write_wrapper(_wrapper_marks_then_never_exits(fx.marker))
        fx.write_plist()

        started = time.monotonic()
        res = fx.run_gate()
        elapsed = time.monotonic() - started

        self.assertEqual(res.returncode, 0, f"gate refused a healthy agent:\n{res.stdout}\n{res.stderr}")
        self.assertFalse(
            fx.marker.exists(),
            "the gate EXECUTED the long-lived agent's entrypoint — that is exactly the 2026-08-08 "
            "incident: a second live instance beside production",
        )
        self.assertIn("static probe", res.stdout.lower())
        # RUN_TIMEOUT is 8s here; the un-fixed gate waits it out and calls that success.
        self.assertLess(elapsed, 6.0, f"gate took {elapsed:.1f}s — it still ran (and waited out) the agent")

    def test_the_marker_really_detects_execution_scheduled_agent_IS_run(self):
        """Control in the other direction: same wrapper, same marker, run-once plist → executed.

        Without this, 'marker absent' could pass for a wrapper that simply never writes it.
        """
        fx = self._fixture("gatefx_scheduled")
        fx.write_wrapper(_wrapper_marks_then_exits(fx.marker))
        fx.write_plist(_SCHEDULED_PLIST)
        # the run-once path needs a log written by the run; the conventional wrapper log is
        # /tmp/spa_<name>.log, so let the wrapper write it exactly as agent_template.sh does.
        fx.write_wrapper(
            "#!/bin/bash\n"
            f'echo "RAN" >> "{fx.marker}"\n'
            f'echo "log line" >> "/tmp/spa_{fx.name}.log"\n'
            "exit 0\n"
        )
        res = fx.run_gate()
        self.assertTrue(
            fx.marker.exists(),
            f"the run-once path must still RUN an ordinary scheduled agent:\n{res.stdout}\n{res.stderr}",
        )

    def test_keepalive_FALSE_is_not_read_as_keepalive(self):
        """The value, not the key. `<key>KeepAlive</key><false/>` used to count as KeepAlive."""
        fx = self._fixture("gatefx_kafalse")
        fx.write_wrapper(_wrapper_marks_then_exits(fx.marker))
        fx.write_plist(_SCHEDULED_PLIST)

        val = subprocess.run(
            ["/bin/bash", str(_PROBE), "--plist-bool", "KeepAlive", str(fx.plist)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(val.stdout.strip(), "false")

        longlived = subprocess.run(
            ["/bin/bash", str(_PROBE), "--is-long-lived", str(fx.plist)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(longlived.returncode, 1, "a KeepAlive=false scheduled agent is not long-lived")

    def test_keepalive_dict_counts_as_long_lived(self):
        """A KeepAlive DICT is still a restart-forever policy — it must take the safe path."""
        fx = self._fixture("gatefx_kadict")
        fx.write_wrapper(_wrapper_marks_then_exits(fx.marker))
        fx.plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>\n'
            f"  <key>Label</key><string>com.spa.{fx.name}</string>\n"
            "  <key>KeepAlive</key>\n  <dict><key>SuccessfulExit</key><false/></dict>\n"
            "  <key>ProgramArguments</key><array>\n"
            f"    <string>/bin/bash</string><string>{fx.wrapper}</string>\n"
            "  </array>\n</dict></plist>\n",
            encoding="utf-8",
        )
        res = subprocess.run(
            ["/bin/bash", str(_PROBE), "--is-long-lived", str(fx.plist)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(res.returncode, 0)

    # ── the static path must still catch REAL breakage ──────────────────────

    def test_static_path_still_catches_a_non_executable_entrypoint(self):
        """2026-08-04: mode 100644 on a launchd entrypoint = exit 126 for the whole fleet."""
        fx = self._fixture("gatefx_noexec")
        fx.write_wrapper(_wrapper_marks_then_never_exits(fx.marker), mode=0o644)
        fx.write_plist()
        res = fx.run_gate()
        self.assertNotEqual(res.returncode, 0, "a non-executable entrypoint must fail the gate")
        self.assertIn("executable", (res.stdout + res.stderr).lower())
        self.assertFalse(fx.marker.exists())

    def test_static_path_still_catches_a_broken_import(self):
        fx = self._fixture("gatefx_badimport")
        fx.write_wrapper(_wrapper_marks_then_never_exits(fx.marker, module="spa_no_such_module_zzz"))
        fx.write_plist()
        res = fx.run_gate()
        self.assertNotEqual(res.returncode, 0, "a module that does not import must fail the gate")
        self.assertIn("spa_no_such_module_zzz", res.stdout + res.stderr)
        self.assertFalse(fx.marker.exists())

    def test_static_path_still_catches_a_wrapper_that_does_not_parse(self):
        fx = self._fixture("gatefx_syntax")
        fx.write_wrapper('#!/bin/bash\nMODULE="json"\nif [ 1 -eq 1 ; then echo x\n')
        fx.write_plist()
        res = fx.run_gate()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("syntax", (res.stdout + res.stderr).lower())

    def test_python_agent_without_a_resolvable_target_is_REFUSED(self):
        """Fail-CLOSED: 'this is python but we could not tell what it imports' is not a pass."""
        fx = self._fixture("gatefx_notarget")
        fx.write_wrapper('#!/bin/bash\nexec /usr/bin/env python3 "$SOMETHING_DYNAMIC"\n')
        fx.write_plist()
        res = fx.run_gate()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("import target", (res.stdout + res.stderr).lower())

    def test_non_python_long_lived_agent_is_NAMED_not_silently_passed(self):
        """cloudflared / cc-kanban have no import target by construction — say so out loud."""
        fx = self._fixture("gatefx_nonpython")
        fx.write_wrapper("#!/bin/bash\nexec /bin/sleep 600\n")
        fx.write_plist()
        res = fx.run_gate()
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        self.assertIn("no python", res.stdout.lower())
        self.assertFalse(fx.marker.exists())

    def test_static_path_catches_an_unwritable_launchd_log_dir(self):
        fx = self._fixture("gatefx_badlog")
        fx.write_wrapper(_wrapper_marks_then_never_exits(fx.marker))
        fx.write_plist(out="/no/such/dir/agent.out", err="/no/such/dir/agent.err")
        res = fx.run_gate()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("StandardOutPath", res.stdout + res.stderr)

    def test_gate_works_when_the_probe_arrives_without_an_exec_bit(self):
        """Delivery-realistic: a synced/checked-out copy may land as 100644.

        The gate invokes the probe as `bash <path>`, so the bit is irrelevant — and it must
        NOT be turned into a refusal that blocks every deploy for a non-reason.
        """
        import shutil
        fx = self._fixture("gatefx_nobit")
        fx.write_wrapper(_wrapper_marks_then_never_exits(fx.marker))
        fx.write_plist()
        # a copy of the toolchain where the probe has no x-bit; the gate finds the probe
        # beside ITSELF, so both files move together.
        toolbox = fx.root / "toolbox"
        toolbox.mkdir()
        gate_copy = toolbox / _GATE.name
        probe_copy = toolbox / _PROBE.name
        shutil.copy2(_GATE, gate_copy)
        shutil.copy2(_PROBE, probe_copy)
        gate_copy.chmod(0o755)
        probe_copy.chmod(0o644)

        env = dict(os.environ)
        env.update({
            "CHECK_ONLY": "1", "SPA_GATE_REPO_ROOT": str(fx.root),
            "SPA_PROBE_PYTHON": os.sys.executable, "RUN_TIMEOUT": "8",
        })
        res = subprocess.run(["/bin/bash", str(gate_copy), fx.name],
                             capture_output=True, text=True, env=env, timeout=120, cwd=str(fx.root))
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        self.assertFalse(fx.marker.exists())

    # ── the override that makes all of the above testable must stay harmless ─

    def test_root_override_is_REFUSED_without_check_only(self):
        """The override may decide what is VALIDATED, never what is LOADED."""
        fx = self._fixture("gatefx_override")
        fx.write_wrapper(_wrapper_marks_then_never_exits(fx.marker))
        fx.write_plist()
        env = dict(os.environ)
        env.update({"SPA_GATE_REPO_ROOT": str(fx.root), "SPA_PROBE_PYTHON": os.sys.executable})
        env.pop("CHECK_ONLY", None)
        res = subprocess.run(
            ["/bin/bash", str(_GATE), fx.name],
            capture_output=True, text=True, env=env, timeout=60, cwd=str(fx.root),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("CHECK_ONLY", res.stdout + res.stderr)
        self.assertFalse(fx.marker.exists())


class TestLivePlistsTakeTheSafePath(unittest.TestCase):
    """The agents this was written for, read from the real plists in this checkout."""

    def _plists(self):
        for d in ("launchd", "scripts"):
            for p in sorted((_REPO / d).glob("com.spa.*.plist")):
                yield p

    def test_telegram_bot_is_classified_long_lived(self):
        found = [p for p in self._plists() if p.name == "com.spa.telegram_bot.plist"]
        self.assertTrue(found, "com.spa.telegram_bot.plist is missing from this checkout")
        for p in found:
            res = subprocess.run(
                ["/bin/bash", str(_PROBE), "--is-long-lived", str(p)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(res.returncode, 0, f"{p} must take the static path, not a second poller")

    def test_telegram_bot_target_module_resolves(self):
        p = next(p for p in self._plists() if p.name == "com.spa.telegram_bot.plist")
        res = subprocess.run(
            ["/bin/bash", str(_PROBE), "--targets", str(p), str(_REPO)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("module: spa_core.telegram.bot", res.stdout)

    def test_every_long_lived_plist_resolves_a_target_or_is_openly_non_python(self):
        """No live long-lived agent may land in the fail-CLOSED 'python, target unknown' hole.

        Left unchecked this would turn the fix into a deploy blocker the first time someone
        needed to redeploy apiserver / familyfund / rtmr_sense.
        """
        unresolved = []
        for p in self._plists():
            ll = subprocess.run(
                ["/bin/bash", str(_PROBE), "--is-long-lived", str(p)],
                capture_output=True, text=True, timeout=30,
            )
            if ll.returncode != 0:
                continue
            res = subprocess.run(
                ["/bin/bash", str(_PROBE), "--targets", str(p), str(_REPO)],
                capture_output=True, text=True, timeout=30,
            )
            has_target = ("module: " in res.stdout) or ("script: " in res.stdout)
            is_python = "python_agent: 1" in res.stdout
            if is_python and not has_target:
                unresolved.append(p.name)
        self.assertEqual(unresolved, [], f"long-lived python agents with no resolvable target: {unresolved}")


if __name__ == "__main__":
    unittest.main()
