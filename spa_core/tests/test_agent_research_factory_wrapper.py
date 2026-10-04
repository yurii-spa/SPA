"""REWORK H0 (post-implementation review of ADR-560 WP-S08's runtime wiring).

Package A's ``research_factory.run --live-rpc`` now builds a real ``capital_shadow.rpc.RpcClient``
(binding #5: realised-return consistency needs an independent on-chain series). The pre-deploy gate
(``scripts/check_agent_before_deploy.sh``) runs every agent ONCE in a SANDBOX before it is ever
loaded: it exports ``SPA_DATA_DIR=<temp sandbox>``, unsets ``SPA_ALLOW_LIVE_WRITE``, and relies on
the module's OWN default ``--data-dir`` resolution honouring that env var (see its own comment at
"Per-check sandbox data dir"). This module verifies, end-to-end through the REAL
``scripts/agent_template.sh`` (not a stub), that:

* ``scripts/agent_research_factory.sh``'s exact invocation shape (``MODULE_ARGS="--live-rpc"`` +
  positional ``research_factory spa_core.research_factory.run``, mirroring
  ``agent_capital_shadow.sh``'s own shape) reaches python with ``--live-rpc`` intact;
* under that invocation, ``SPA_DATA_DIR`` is honoured: the sandbox gets written to, the live tree's
  ``data/research_factory/`` is never touched;
* the run completes well inside the gate's own timeout and never needs network (an empty sandbox
  has zero PAPER_ACTIVE/EVIDENCE_ACCUMULATING candidates, so ``RpcClient`` is constructed — which
  does no I/O by itself, see ``capital_shadow/rpc.py``'s own docstring — but ``.request()`` is
  never called).

Uses the documented test-only overrides ``SPA_AGENT_REPO_ROOT``/``SPA_AGENT_PYTHON`` (same
mechanism ``test_aggressive_lab_series_rewrite.py`` already relies on) so this never touches the
production tree.

REWORK N4 (second review): the first draft of this file called ``agent_template.sh`` without
``SPA_AGENT_SKIP_SYNC=1``. ``maybe_sync_code()`` in that script runs
``scripts/code_sync_from_origin.sh`` whenever its stamp (default ``/tmp/spa_code_sync.stamp``,
shared across every agent on the host) is more than ``SPA_AGENT_SYNC_MAX_AGE`` (default 600s) old
— and that sync script's OWN default target is ``REPO="${SPA_SYNC_REPO:-$HOME/Documents/SPA_Claude}"``,
the PRODUCTION tree, regardless of ``SPA_AGENT_REPO_ROOT`` (which only tells the TEMPLATE where to
find the sync script and the python module — it is not read by the sync script itself). A test
process must never run ``git fetch``/checkout against production. Fixed here with THREE
independent layers, any one of which alone would already prevent it:
  1. ``SPA_AGENT_SKIP_SYNC=1`` — ``maybe_sync_code()``'s very first line returns before even
     looking at the stamp or the sync script;
  2. ``SPA_CODE_SYNC_STAMP=<tmp>/...`` — a private, per-test stamp path, never the shared
     ``/tmp/spa_code_sync.stamp`` another agent (or a previous test run) may have just touched;
  3. ``SPA_SYNC_REPO=<tmp>/...`` — if a future edit ever dropped layer 1, the sync script (were it
     somehow still invoked) would still default away from ``$HOME/Documents/SPA_Claude``.
``test_env_always_carries_the_skip_sync_flag_and_a_private_stamp`` asserts, statically, that every
constructed environment in this file carries all three.

The same review also found this file deleting the PRODUCTION agent's own log,
``/tmp/spa_research_factory.log`` (shared with the real launchd-run agent, were one ever running
on this host). Fixed by running under a test-private ``AGENT_NAME`` (``research_factory_pytest``,
not ``research_factory``) — ``agent_template.sh`` derives its log path ONLY from ``AGENT_NAME``
(``LOG="/tmp/spa_${AGENT_NAME}.log"``) and offers no separate log-path override, so a distinct name
is the least invasive way to get a test-private log without touching the template; this file now
never reads or deletes ``/tmp/spa_research_factory.log``.
"""
# FROZEN-DATE-OK: fixed-subprocess-anchor — the ISO literals are CLI text handed to a CHILD
# process's own `--now` parsing (spa_core.research_factory.run, invoked via subprocess/bash -c);
# this file's own Python never reads the wall clock or compares against it, so the literal is not
# an injected-clock claim in the AST sense (test_injected_clock_claim.py correctly rejects that
# label here — nothing in this file passes the anchor as a Python call argument). The run is
# deterministic by construction regardless of which date is picked; it is fixed only so repeated
# runs are directly comparable, not because today's date matters.
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "scripts" / "agent_template.sh"
WRAPPER = REPO_ROOT / "scripts" / "agent_research_factory.sh"
PLIST = REPO_ROOT / "launchd" / "com.spa.research_factory.plist"
# A test-private AGENT_NAME: agent_template.sh derives LOG="/tmp/spa_${AGENT_NAME}.log" from this
# alone, with no separate override — using a name distinct from the real agent's ("research_factory")
# is the least invasive way to get a private log without ever touching the production agent's own
# /tmp/spa_research_factory.log (REWORK N4).
TEST_AGENT_NAME = "research_factory_pytest"
TEST_LOG = Path(f"/tmp/spa_{TEST_AGENT_NAME}.log")


def test_wrapper_file_matches_the_capital_shadow_shape_exactly():
    """Static shape check: MODULE_ARGS is a STRING (never a bash array — the exact class of bug
    `test_aggressive_lab_series_rewrite.py` holds), the module target is the real one, and the
    invocation mirrors agent_capital_shadow.sh's own (same AGENT_NAME positional style, same
    template path, same bash -c construction)."""
    src = WRAPPER.read_text(encoding="utf-8")
    assert WRAPPER.stat().st_mode & 0o111, "wrapper must be executable"
    assert re.search(r'export MODULE_ARGS="--live-rpc"\s*$', src, re.M), \
        "MODULE_ARGS must be exported as a plain STRING (array does not survive export — #1 cause)"
    assert "declare -a" not in src and "MODULE_ARGS=(" not in src
    assert "/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh" in src
    assert "research_factory spa_core.research_factory.run" in src


def test_plist_points_at_the_wrapper_and_runs_daily_before_investment_cio_and_capital_shadow():
    plist_src = PLIST.read_text(encoding="utf-8")
    assert "com.spa.research_factory" in plist_src
    assert "agent_research_factory.sh" in plist_src
    assert "<false/>" in plist_src.split("RunAtLoad")[1][:30]
    m = re.search(r"<key>Hour</key>\s*<integer>(\d+)</integer>\s*<key>Minute</key>\s*<integer>(\d+)</integer>",
                  plist_src)
    assert m and (int(m.group(1)), int(m.group(2))) == (9, 5), \
        "must run at 09:05 — before investment_cio (09:30) and capital_shadow (09:45)"


def _env_lines(tmp_path: Path, sandbox_dir: Path, *, module_args: str) -> list:
    """The exact env this file ever exports before invoking the real agent_template.sh — ONE
    place, so the skip-sync/private-stamp/private-log properties can be asserted statically
    (below) and are structurally guaranteed to match what every dynamic test actually runs."""
    return [
        f'export SPA_AGENT_REPO_ROOT="{REPO_ROOT}"',
        f'export SPA_AGENT_PYTHON="{sys.executable}"',
        f'export SPA_DATA_DIR="{sandbox_dir}"',
        'unset SPA_ALLOW_LIVE_WRITE',                              # the gate's own hardening (fix #1)
        # REWORK N4, layer 1 (sufficient on its own): maybe_sync_code()'s first line returns
        # immediately, before the stamp or the sync script are even looked at.
        'export SPA_AGENT_SKIP_SYNC=1',
        # REWORK N4, layer 2: never the real, HOST-SHARED /tmp/spa_code_sync.stamp.
        f'export SPA_CODE_SYNC_STAMP="{tmp_path}/private_code_sync.stamp"',
        # REWORK N4, layer 3: if SKIP_SYNC were ever dropped, code_sync_from_origin.sh's OWN
        # default (`${SPA_SYNC_REPO:-$HOME/Documents/SPA_Claude}`) still can't reach production.
        f'export SPA_SYNC_REPO="{tmp_path}/not_a_real_repo_never_synced_into"',
        f'export MODULE_ARGS="{module_args}"',
    ]


def _invocation(tmp_path: Path, sandbox_dir: Path, *, module_args: str, extra_positional: str = "") -> str:
    lines = _env_lines(tmp_path, sandbox_dir, module_args=module_args)
    cmd = f'/bin/bash "{TEMPLATE}" {TEST_AGENT_NAME} spa_core.research_factory.run{extra_positional}'
    return "\n".join(lines) + "\n" + cmd + "\n"


def test_env_always_carries_the_skip_sync_flag_and_a_private_stamp(tmp_path):
    """REWORK N4's own static proof: whatever this file runs, the constructed environment ALWAYS
    carries SPA_AGENT_SKIP_SYNC=1, a private SPA_CODE_SYNC_STAMP, and a private SPA_SYNC_REPO — no
    subprocess needed to check this, so it can never be masked by a run that happens not to hit the
    sync path anyway."""
    lines = _env_lines(tmp_path, tmp_path / "sandbox", module_args="--live-rpc")
    joined = "\n".join(lines)
    assert "export SPA_AGENT_SKIP_SYNC=1" in joined
    assert f'export SPA_CODE_SYNC_STAMP="{tmp_path}/private_code_sync.stamp"' in joined
    assert "/tmp/spa_code_sync.stamp" not in joined       # never the real, host-shared stamp
    assert f'export SPA_SYNC_REPO="{tmp_path}' in joined
    assert "Documents/SPA_Claude" not in joined           # never defaults toward production


UNREACHABLE_NETWORK_ENV = "".join(f"export {k}=http://127.0.0.1:9\n" for k in
                                  ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")) + \
    "unset NO_PROXY no_proxy\n"


def _run_wrapper_equivalent(sandbox_dir: Path, tmp_path: Path, *, timeout_s: int = 45,
                            extra_positional: str = "") -> subprocess.CompletedProcess:
    """Exactly scripts/agent_research_factory.sh's invocation shape — a SINGLE exported
    MODULE_ARGS string, and (normally) only the two positional args (name, module) after it —
    pointed at THIS tree via the test-only overrides instead of the hardcoded production path, and
    hermetic against code-sync (REWORK N4) and against the production log (test-private
    AGENT_NAME).

    Deliberately leaves ``extra_positional`` empty by default: agent_template.sh's generic mode B
    OVERWRITES MODULE_ARGS from any remaining CLI args (``if [ "$#" -ge 1 ]; then
    MODULE_ARGS=("$@"); fi``) — found the hard way, writing this very test, when an added ``--now``
    positional silently dropped ``--live-rpc`` entirely and the assertion then in place only caught
    it once a stale log file stopped masking the regression. ``--now`` (when needed) is appended
    INSIDE the one exported MODULE_ARGS string instead, exactly how the real wrapper would."""
    script = _invocation(tmp_path, sandbox_dir, module_args="--live-rpc --now 2026-10-04T12:00:00Z",
                         extra_positional=extra_positional)
    # ADR-564 §8: under --live-rpc Sherlock's evidence collectors fetch BY DESIGN before any
    # scanner runs (funding-pair candidates are built from those rows), so "an empty sandbox
    # makes no call" stopped being true. The network is made deliberately UNREACHABLE instead
    # (urllib honours *_proxy; port 9 refuses at once): the run stays hermetic and fast, and the
    # refusal itself becomes the thing asserted — fail-CLOSED and named, never a hang.
    script = UNREACHABLE_NETWORK_ENV + script
    return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=timeout_s)


def test_sandboxed_run_through_the_real_template_honours_spa_data_dir(tmp_path):
    """The actual H0 proof: run the REAL module through the REAL template, in the SAME sandboxed
    shape the pre-deploy gate uses, and verify the sandbox (not the live tree) receives the
    write — with --live-rpc intact and no hang (no network needed: empty sandbox, zero
    candidates, RpcClient never calls .request()) — and WITHOUT touching code-sync or the
    production agent's log (REWORK N4)."""
    sandbox = tmp_path / "sandbox_data"
    live_research_factory_dir = REPO_ROOT / "data" / "research_factory"
    live_existed_before = live_research_factory_dir.exists()
    TEST_LOG.unlink(missing_ok=True)   # this file's OWN private log only — never the production one

    try:
        proc = _run_wrapper_equivalent(sandbox, tmp_path)
        detail = f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert proc.returncode == 0, detail

        # the sandbox — not the live tree — received the write
        assert (sandbox / "research_factory" / "ledger.jsonl").is_file(), detail
        assert (sandbox / "research_factory" / "status.json").is_file(), detail

        # the live tree was never touched by this sandboxed run (REWORK H0's whole point)
        assert live_research_factory_dir.exists() == live_existed_before, (
            "the sandboxed run touched the LIVE data/research_factory/ — SPA_DATA_DIR was not honoured")

        # --live-rpc actually reached python — asserted UNCONDITIONALLY against THIS test's own
        # private log: a missing log is a failure to investigate, never a silent pass (the exact
        # class of bug that let this test's own first draft hide a dropped --live-rpc).
        assert TEST_LOG.is_file(), "the wrapper's own log was never written — the run never truly happened"
        log_text = TEST_LOG.read_text(encoding="utf-8")
        assert "--live-rpc" in log_text
        # REWORK N4: no code-sync attempt is even logged (maybe_sync_code returned before
        # writing anything) — a CODE_SYNC line here would mean a layer silently failed.
        assert "CODE_SYNC" not in log_text
    finally:
        TEST_LOG.unlink(missing_ok=True)


def test_sandboxed_run_completes_fast_with_no_candidates_to_avoid_network(tmp_path):
    """With the network unreachable, the run must complete well within a few seconds — not the
    gate's multi-minute RUN_TIMEOUT a hung network call would consume — and every evidence fetch
    it attempted must be recorded fail-CLOSED with a named reason (ADR-564 §8 changed this test's
    premise: collectors fetch under --live-rpc by design; journalled W41)."""
    import time
    TEST_LOG.unlink(missing_ok=True)
    try:
        sandbox = tmp_path / "sandbox_data"
        t0 = time.monotonic()
        proc = _run_wrapper_equivalent(sandbox, tmp_path, timeout_s=20)
        elapsed = time.monotonic() - t0
        assert proc.returncode == 0, proc.stderr
        assert elapsed < 15, f"took {elapsed:.1f}s — suspiciously slow with the network unreachable"
        # every evidence fetch the collectors attempted failed CLOSED and NAMED: no value, a reason
        import json as _json
        rows = [_json.loads(line) for line in
                (sandbox / "research_factory" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        observations = [r["payload"] for r in rows if r["kind"] == "evidence_observation"]
        assert observations, "the collectors attempted nothing — --live-rpc did not reach them"
        assert all(o.get("value") is None and o.get("reason") for o in observations), \
            [o for o in observations if o.get("value") is not None or not o.get("reason")][:3]
    finally:
        TEST_LOG.unlink(missing_ok=True)


def test_a_third_positional_arg_would_silently_drop_live_rpc_so_this_test_never_adds_one(tmp_path):
    """Documents, with a positive control, the exact trap this module's own first draft fell into:
    agent_template.sh's generic mode B treats ANY CLI args left over after <name> <module> as a
    REPLACEMENT for MODULE_ARGS, discarding the environment-exported string entirely. The real
    scripts/agent_research_factory.sh never does this (it is `[/bin/bash, wrapper.sh]` with no
    extra args in the plist's ProgramArguments; --live-rpc lives inside the wrapper's own export),
    but a careless test — or a careless future wrapper edit — could reintroduce exactly this."""
    sandbox = tmp_path / "sandbox_data"
    TEST_LOG.unlink(missing_ok=True)
    script = _invocation(tmp_path, sandbox, module_args="--live-rpc",
                         # the trap: one extra positional arg after the module name
                         extra_positional=" --now 2026-10-04T12:00:00Z")
    try:
        proc = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, timeout=45)
        assert proc.returncode == 0, proc.stderr
        assert TEST_LOG.is_file()
        # this IS the trap, named explicitly rather than silently relied upon: the exported
        # MODULE_ARGS string is gone, replaced by the trailing positional args alone.
        assert "--live-rpc" not in TEST_LOG.read_text(encoding="utf-8")
    finally:
        TEST_LOG.unlink(missing_ok=True)
