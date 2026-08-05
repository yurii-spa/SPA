"""
spa_core/tests/test_aggressive_lab_series_rewrite.py — the contract of
``data/aggressive_lab/<id>/realized_series.jsonl`` across the two producers, AND the launchd
argument-transmission mechanism that decides which producer runs at night.

HISTORY (deliberate contract change, invariant #16 — recorded in docs/journal/2026-W32.md).
Until 2026-08-05 this file MEASURED the incident: :func:`run_backtest` truncated the whole series
file (853/853 rows of ``susde_dn`` rewritten, forward points destroyed), and the launchd wrapper's
``export MODULE_ARGS=(paper)`` never reached the module (bash arrays do not survive a process
boundary) so mode "both" ran nightly — together: the forward track could never exceed ONE row and
the Balanced/Aggressive packages stayed unprovable. The old tests pinned that destruction as fact
and said, verbatim, that when the behaviour is deliberately fixed "this contract ... must be
updated deliberately". This is that update. The fix is two independent defenses:

  1. TRANSMISSION — ``agent_aggressive_lab.sh`` exports MODULE_ARGS as a plain STRING and
     ``agent_template.sh`` splits a string arriving via the environment into the args array.
  2. PRESERVATION — :func:`run_backtest` still rewrites its own phase="backtest" rows from
     scratch, but phase="forward" rows are PRESERVED across a replay (re-appended, re-chained).

Both directions are held: the positive controls reproducing the original avaria (an exported bash
ARRAY arrives empty → mode "both") stay in this file forever, so the fix can never be silently
reverted without a red test.

stdlib + pytest only; everything injected (no network, no live data touched); deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from spa_core.strategy_lab.aggressive_lab import _io, proof
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds
from spa_core.strategy_lab.aggressive_lab.harness import PaperService, run_backtest, upsert_day

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "scripts" / "agent_template.sh"
WRAPPER = REPO_ROOT / "scripts" / "agent_aggressive_lab.sh"


# ── a small injected history (same shape as test_aggressive_lab_producer's, no network) ──────────
def _feeds(n: int = 6):
    base = datetime.date(2025, 10, 1)
    dates = [(base + datetime.timedelta(days=i)).isoformat() for i in range(n)]
    susde: dict = {}
    pt: dict = {}
    funding: dict = {}
    eth: dict = {}
    rest: dict = {"steth": {}, "eeth": {}}
    ratio: dict = {"eeth": {}}
    for i, d in enumerate(dates):
        susde[d] = 0.11
        pt[d] = 0.12
        funding[d] = 0.0001
        eth[d] = 3000.0
        rest["steth"][d] = 0.03
        rest["eeth"][d] = 0.032
        ratio["eeth"][d] = 1.03
    return AggressiveFeeds(
        susde_apy_series=susde, pt_susde_series=pt, funding_series=funding,
        eth_price_series=eth, restaking_series=rest, lrt_ratio_series=ratio,
    ), dates


def _series(root: Path, sid: str) -> list:
    return _io.read_jsonl(root / sid / "realized_series.jsonl")


def _any_book(root: Path) -> str:
    """The id of some book the backtest actually wrote (roster ids are not this test's subject)."""
    ids = sorted(p.name for p in root.iterdir() if (p / "realized_series.jsonl").is_file())
    assert ids, "the backtest wrote no series at all — fixture is broken, not the code under test"
    return ids[0]


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE GUARD — run_backtest rewrites ITS OWN backtest rows but PRESERVES forward rows.
#    (Until 2026-08-05 it destroyed them; the old tests here pinned the destruction.)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_run_backtest_preserves_forward_points_written_by_the_paper_path(tmp_path):
    """The live symptom, closed: the forward track survives a replay and can therefore accumulate.

    On the live books exactly ONE `phase="forward"` row was ever present, because every nightly
    replay truncated the file before the tick re-appended one row. This is the guard that makes
    that impossible regardless of what mode the agent runs in."""
    feeds, dates = _feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    sid = _any_book(tmp_path)

    for day in ("2026-07-25", "2026-07-26"):
        upsert_day(tmp_path, sid, {"date": day, "as_of": day, "equity_usd": 100.0,
                                   "phase": "forward"})
    forward_before = [p["date"] for p in _series(tmp_path, sid) if p.get("phase") == "forward"]
    assert forward_before == ["2026-07-25", "2026-07-26"], (
        "fixture: two distinct forward days should be present before the replay")

    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)

    after = _series(tmp_path, sid)
    forward_after = [p["date"] for p in after if p.get("phase") == "forward"]
    assert forward_after == ["2026-07-25", "2026-07-26"], (
        "a replay LOST forward points — the 2026-08-05 destruction guard has been reverted; "
        "the forward track is the product and no replay may shorten it")
    # equity of the preserved points is untouched (preservation, not regeneration)
    kept = [p for p in after if p.get("phase") == "forward"]
    assert all(p["equity_usd"] == 100.0 for p in kept), (
        "preserved forward points must carry their ORIGINAL economics, not re-derived ones")


def test_run_backtest_still_rederives_its_own_backtest_rows(tmp_path):
    """The half of the old contract that stays true: backtest rows are replaced on every replay
    (a clean replay of history), so preservation applies to forward rows ONLY — a stale marker
    row of phase="backtest" does NOT survive."""
    feeds, dates = _feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    sid = _any_book(tmp_path)

    upsert_day(tmp_path, sid, {"date": "2020-01-01", "as_of": "2020-01-01",
                               "equity_usd": 12345.0, "phase": "backtest"})
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)

    after = _series(tmp_path, sid)
    assert not any(p["date"] == "2020-01-01" for p in after), (
        "a foreign phase='backtest' row survived the replay — the backtest no longer fully owns "
        "its own rows, and stale backtest data can now shadow a real replay")


def test_run_backtest_keeps_the_proof_chain_valid_across_preserved_forward_rows(tmp_path):
    """Preservation must re-chain, not merely concatenate: the file stays ONE valid hash chain."""
    feeds, dates = _feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    sid = _any_book(tmp_path)
    upsert_day(tmp_path, sid, {"date": "2026-07-25", "as_of": "2026-07-25",
                               "equity_usd": 100.0, "phase": "forward"})
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)

    ok, reason = proof.verify_chain(_series(tmp_path, sid))
    assert ok, f"series chain broken after a preserving replay: {reason}"


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 2. THE PAPER WRITER — append-across-days, replace-same-day (unchanged contract).
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_upsert_day_accumulates_across_days(tmp_path):
    sid = "control_book"
    for day in ("2026-07-25", "2026-07-26", "2026-07-27"):
        upsert_day(tmp_path, sid, {"date": day, "as_of": day, "equity_usd": 100.0,
                                   "phase": "forward"})
    got = [p["date"] for p in _series(tmp_path, sid)]
    assert got == ["2026-07-25", "2026-07-26", "2026-07-27"], (
        "the paper writer must APPEND distinct days — otherwise the forward track cannot grow "
        "no matter what the agent mode is")


def test_upsert_day_still_refreshes_the_same_day_in_place(tmp_path):
    """Positive control for per-(date, phase) idempotency, so these tests cannot be read as
    'upsert_day appends unconditionally'."""
    sid = "control_book"
    upsert_day(tmp_path, sid, {"date": "2026-07-25", "as_of": "2026-07-25",
                               "equity_usd": 100.0, "phase": "forward"})
    upsert_day(tmp_path, sid, {"date": "2026-07-25", "as_of": "2026-07-25",
                               "equity_usd": 999.0, "phase": "forward"})
    rows = _series(tmp_path, sid)
    assert len(rows) == 1 and rows[0]["equity_usd"] == 999.0, (
        "re-writing the same (date, phase) must REPLACE, not double-append")


def test_two_nights_then_a_replay_the_full_scenario(tmp_path):
    """END-TO-END of the fixed nightly life: two paper ticks on different dates through the REAL
    PaperService (dates injected via as_of, feeds injected — no network, no live data), then a
    backtest replay. The book must hold BOTH forward rows after all three runs."""
    feeds, dates = _feeds()
    svc = PaperService(feeds, state_dir=tmp_path, verify_isolation=False)
    s1 = svc.tick("2026-08-04")
    assert not s1.get("gap"), f"night 1 unexpectedly gapped: {s1.get('gap_reason')}"
    svc2 = PaperService(feeds, state_dir=tmp_path, verify_isolation=False)  # fresh process, restored
    s2 = svc2.tick("2026-08-05")
    assert not s2.get("gap"), f"night 2 unexpectedly gapped: {s2.get('gap_reason')}"

    sid = _any_book(tmp_path)
    forward = [p["date"] for p in _series(tmp_path, sid) if p.get("phase") == "forward"]
    assert forward == ["2026-08-04", "2026-08-05"], (
        f"two nights must leave two forward rows, got {forward!r}")

    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    forward_after = [p["date"] for p in _series(tmp_path, sid) if p.get("phase") == "forward"]
    assert forward_after == ["2026-08-04", "2026-08-05"], (
        f"the replay must not touch the two accumulated nights, got {forward_after!r}")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 3. THE CLI — defaults, the explicit modes, fail-closed on garbage, --as-of plumbed through.
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_main_without_argv_runs_the_backtest_not_only_the_paper_tick(monkeypatch):
    """``run.main([])`` → mode "both". Still the fact a caller that passes no argument gets —
    which is exactly why the transmission tests below exist: the argument must ARRIVE."""
    from spa_core.strategy_lab.aggressive_lab import run as run_mod

    called = []
    monkeypatch.setattr(run_mod, "run_real_backtest", lambda: called.append("backtest") or {})
    monkeypatch.setattr(run_mod, "run_daily", lambda *a, **k: called.append("paper") or {})

    assert run_mod.main([]) == 0
    assert called == ["backtest", "paper"], (
        f"expected the no-argv default to run BOTH producers, got {called!r}")


def test_main_with_paper_argument_runs_only_the_forward_tick(monkeypatch):
    """Positive control: the argument the wrapper passes does the harmless thing — so the live
    damage was about the argument never arriving, not about the argument being wrong."""
    from spa_core.strategy_lab.aggressive_lab import run as run_mod

    called = []
    monkeypatch.setattr(run_mod, "run_real_backtest", lambda: called.append("backtest") or {})
    monkeypatch.setattr(run_mod, "run_daily", lambda *a, **k: called.append("paper") or {})

    assert run_mod.main(["paper"]) == 0
    assert called == ["paper"], f"'paper' must not run the replay, got {called!r}"


def test_main_refuses_an_unknown_mode(monkeypatch, capsys):
    """fail-CLOSED: a typo'd mode must not silently run nothing (rc 0 used to make a dead agent
    look alive) and must certainly not fall through to the destructive default."""
    from spa_core.strategy_lab.aggressive_lab import run as run_mod

    called = []
    monkeypatch.setattr(run_mod, "run_real_backtest", lambda: called.append("backtest") or {})
    monkeypatch.setattr(run_mod, "run_daily", lambda *a, **k: called.append("paper") or {})

    assert run_mod.main(["papr"]) == 64
    assert called == [], f"an unknown mode must run NOTHING, got {called!r}"
    assert "unknown mode" in capsys.readouterr().err


def test_main_passes_as_of_to_the_paper_tick(monkeypatch):
    from spa_core.strategy_lab.aggressive_lab import run as run_mod

    seen = []
    monkeypatch.setattr(run_mod, "run_daily", lambda as_of=None: seen.append(as_of) or {})

    assert run_mod.main(["paper", "--as-of", "2026-08-04"]) == 0
    assert seen == ["2026-08-04"], f"--as-of must reach run_daily, got {seen!r}"


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 4. THE TRANSMISSION — measured on the REAL bash and the REAL agent_template.sh.
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_exported_bash_array_does_not_reach_a_child_shell(tmp_path):
    """POSITIVE CONTROL, kept forever: `export MODULE_ARGS=(paper)` succeeds in the parent and
    arrives EMPTY in the child. This is the shell fact behind the incident — the reason the fix
    is 'export a STRING', and the test that proves the old wrapper form can never work."""
    child = tmp_path / "child.sh"
    child.write_text(textwrap.dedent("""\
        #!/bin/bash
        if ! declare -p MODULE_ARGS >/dev/null 2>&1; then MODULE_ARGS=(); fi
        echo "count=${#MODULE_ARGS[@]}"
    """), encoding="utf-8")
    parent = tmp_path / "parent.sh"
    parent.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        export MODULE_ARGS=(paper)
        echo "parent_count=${{#MODULE_ARGS[@]}}"
        /bin/bash {child}
    """), encoding="utf-8")

    out = subprocess.run(["/bin/bash", str(parent)], capture_output=True, text=True, timeout=60)
    assert "parent_count=1" in out.stdout, (
        f"fixture: the parent shell itself should hold one element, got {out.stdout!r}")
    assert "count=0" in out.stdout, (
        "the child saw the array — if bash ever starts exporting arrays, the transmission "
        f"defense becomes redundant (but the preservation guard still stands); got {out.stdout!r}")


def _template_fixture(tmp_path):
    """A sandbox the REAL agent_template.sh accepts: a fake repo root (spa_core/__init__.py must be
    readable — the wake-storm readiness probe does a real 1-byte read) and a stub 'module' that
    records its argv to a file. Uses the documented test-only overrides SPA_AGENT_REPO_ROOT /
    SPA_AGENT_PYTHON; production plists set neither."""
    fake_root = tmp_path / "repo"
    (fake_root / "spa_core").mkdir(parents=True)
    (fake_root / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    argv_out = tmp_path / "argv_seen.json"
    stub = tmp_path / "stub.py"
    stub.write_text(
        "import json, sys, pathlib\n"
        f"pathlib.Path({str(argv_out)!r}).write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8")
    return fake_root, stub, argv_out


def _run_real_template(tmp_path, module_args_line: str):
    """Invoke the REAL scripts/agent_template.sh exactly the way a separate parent wrapper does
    (child /bin/bash + exported env), with MODULE_ARGS set by `module_args_line`."""
    fake_root, stub, argv_out = _template_fixture(tmp_path)
    name = f"pytest_modargs_{os.getpid()}"
    parent = tmp_path / "wrapper.sh"
    parent.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        export AGENT_NAME="{name}"
        export RUN_SCRIPT="{stub}"
        export SPA_AGENT_REPO_ROOT="{fake_root}"
        export SPA_AGENT_PYTHON="{sys.executable}"
        {module_args_line}
        /bin/bash {TEMPLATE}
    """), encoding="utf-8")
    proc = subprocess.run(["/bin/bash", str(parent)], capture_output=True, text=True, timeout=120)
    log = Path(f"/tmp/spa_{name}.log")
    try:
        assert proc.returncode == 0, (
            f"template run failed rc={proc.returncode} stderr={proc.stderr!r} "
            f"log={log.read_text(encoding='utf-8') if log.is_file() else '<missing>'!r}")
        assert argv_out.is_file(), "stub module never ran — the template did not reach python"
        return json.loads(argv_out.read_text(encoding="utf-8"))
    finally:
        if log.is_file():
            log.unlink()


def test_real_template_delivers_a_string_module_args_across_the_process_boundary(tmp_path):
    """THE FIX, end-to-end on the real file: an exported STRING MODULE_ARGS arrives as real args.
    This is the exact invocation shape of the fixed agent_aggressive_lab.sh."""
    got = _run_real_template(tmp_path, 'export MODULE_ARGS="paper"')
    assert got == ["paper"], (
        f"the exported string did not arrive as args — the template no longer splits a "
        f"string MODULE_ARGS and every env-mode wrapper with args is silently argless; got {got!r}")


def test_real_template_splits_a_multi_arg_string(tmp_path):
    got = _run_real_template(tmp_path, 'export MODULE_ARGS="--flag value"')
    assert got == ["--flag", "value"], f"whitespace split broken: {got!r}"


def test_real_template_still_arrives_argless_from_the_old_array_export(tmp_path):
    """POSITIVE CONTROL replaying the avaria against today's template: the OLD wrapper form
    (`export MODULE_ARGS=(paper)`) still arrives as ZERO args — bash, not the template, drops it.
    If this ever starts delivering args, bash semantics changed; re-measure everything."""
    got = _run_real_template(tmp_path, "export MODULE_ARGS=(paper)")
    assert got == [], f"an exported ARRAY arrived across the boundary?! got {got!r}"


def test_the_deployed_wrapper_exports_a_string_not_an_array():
    """Both halves of the fix are present in the tree: the wrapper exports a STRING (the only
    form that can arrive), and the template contains the string-split branch."""
    if not (WRAPPER.is_file() and TEMPLATE.is_file()):
        pytest.skip(f"wrapper/template not present in this checkout: {WRAPPER}, {TEMPLATE}")
    w = WRAPPER.read_text(encoding="utf-8")
    t = TEMPLATE.read_text(encoding="utf-8")
    # judge the wrapper by its EFFECTIVE lines — the incident is documented in its comments,
    # which legitimately quote the broken form
    w_code = "\n".join(l for l in w.splitlines() if not l.lstrip().startswith("#"))
    assert 'export MODULE_ARGS="paper"' in w_code, (
        "agent_aggressive_lab.sh no longer exports the STRING form — mode 'paper' will not reach "
        "the module and the nightly replay returns")
    assert "MODULE_ARGS=(" not in w_code.replace("MODULE_ARGS=()", ""), (
        "an ARRAY MODULE_ARGS export is back in the wrapper — it cannot cross the process "
        "boundary (see test_exported_bash_array_does_not_reach_a_child_shell)")
    assert 'MODULE="spa_core.strategy_lab.aggressive_lab.run"' in w, (
        "the wrapper no longer targets the aggressive-lab run module — re-derive this contract")
    assert "read -r -a MODULE_ARGS" in t, (
        "agent_template.sh no longer splits a string MODULE_ARGS from the environment — half of "
        "the transmission fix is gone")
