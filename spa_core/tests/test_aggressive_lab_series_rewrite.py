"""
spa_core/tests/test_aggressive_lab_series_rewrite.py — what ACTUALLY happens to
``data/aggressive_lab/<id>/realized_series.jsonl``, pinned against the docstring that said
otherwise.

WHY THIS FILE EXISTS (card ``agent-aggressive-lab-books-are-regenerated``). ``harness.py`` opened
by describing the file as "proof-chained, **append-only**". It is not: :func:`run_backtest` rewrites
the whole file from scratch on every run, and cycle #66/#69 measured the consequence on the live
books — 853 of 853 rows of ``susde_dn`` changed against the 2026-07-25 repository backup (max
−9.70% on 2026-07-05), while the single ``phase="forward"`` row did not accumulate but was
REPLACED. Nothing in the tree pinned either behaviour, so "append-only" could stay written next to
code that truncates.

These tests do NOT change behaviour — they MEASURE it, so the contract is a fact in the suite
instead of a sentence in a docstring:

  1. :func:`run_backtest` rewrites the series file — pre-existing points (INCLUDING forward ones a
     paper tick appended) do not survive it.
  2. Contrast control: the paper path (:func:`upsert_day`) really IS append-across-days, so the
     loss in (1) is attributable to ``run_backtest`` and not to the writer they share.
  3. :func:`run.main` with NO argv resolves to mode ``"both"`` — i.e. a caller that passes no
     argument runs the destructive backtest, not just the forward tick.
  4. The mechanism behind the live incident, measured on real bash: a shell ARRAY does not survive
     ``export`` across a process boundary, so ``export MODULE_ARGS=(paper)`` in a launchd wrapper
     reaches the child template as NOTHING — which, with (3), is why the production agent has been
     running ``both`` nightly. (The wrapper itself is the owner's domain — card
     ``owner-decision-*``; this test pins the shell fact the card rests on.)

stdlib + pytest only; everything injected (no network, no live data touched); deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import subprocess
import textwrap
from pathlib import Path

import pytest

from spa_core.strategy_lab.aggressive_lab import _io
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds
from spa_core.strategy_lab.aggressive_lab.harness import run_backtest, upsert_day


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
# 1. run_backtest REWRITES — the file is not append-only, and forward points do not survive it.
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_run_backtest_rewrites_the_series_and_drops_pre_existing_points(tmp_path):
    """A point already in the file before the replay is GONE after it.

    This is the behaviour the live books show (853/853 rows re-written) and the exact opposite of
    "append-only". Pinned so the contract cannot drift back into the docstring unmeasured."""
    feeds, dates = _feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)
    sid = _any_book(tmp_path)

    # a pre-existing point from an EARLIER era, of the kind a paper tick leaves behind
    upsert_day(tmp_path, sid, {"date": "2020-01-01", "as_of": "2020-01-01",
                               "equity_usd": 12345.0, "phase": "forward"})
    before = _series(tmp_path, sid)
    assert any(p["date"] == "2020-01-01" for p in before), "fixture: the marker point was not stored"

    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=False)

    after = _series(tmp_path, sid)
    assert not any(p["date"] == "2020-01-01" for p in after), (
        "run_backtest kept a pre-existing point — if that is now true, the series really did become "
        "append-only and this contract (plus the harness docstring) must be updated deliberately"
    )
    assert all(p.get("phase") == "backtest" for p in after), (
        "after a replay the file holds backtest points ONLY — a surviving forward point would mean "
        "the two producers no longer own the file exclusively"
    )


def test_run_backtest_destroys_a_forward_point_written_by_the_paper_path(tmp_path):
    """The live symptom, reproduced: the forward track cannot accumulate across a replay.

    On the real books exactly ONE `phase="forward"` row is ever present, and between 2026-07-25 and
    2026-08-01 it did not grow to two — it was replaced. That is this, not a paper-tick bug."""
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

    forward_after = [p["date"] for p in _series(tmp_path, sid) if p.get("phase") == "forward"]
    assert forward_after == [], (
        "a replay left forward points behind — the accumulated forward track would then survive, "
        "which is NOT what the live books show")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 2. CONTRAST CONTROL — the paper writer itself is append-across-days.
#    Without this, test 1 would not tell you WHICH producer loses the history.
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_upsert_day_accumulates_across_days_so_the_loss_is_run_backtests(tmp_path):
    sid = "control_book"
    for day in ("2026-07-25", "2026-07-26", "2026-07-27"):
        upsert_day(tmp_path, sid, {"date": day, "as_of": day, "equity_usd": 100.0,
                                   "phase": "forward"})
    got = [p["date"] for p in _series(tmp_path, sid)]
    assert got == ["2026-07-25", "2026-07-26", "2026-07-27"], (
        "the paper writer must APPEND distinct days — if it does not, the forward track is lost "
        "twice over and test 1 attributes the loss to the wrong producer")


def test_upsert_day_still_refreshes_the_same_day_in_place(tmp_path):
    """Positive control for the idempotency the docstring DOES describe correctly (per date+phase),
    so these tests cannot be read as 'upsert_day appends unconditionally'."""
    sid = "control_book"
    upsert_day(tmp_path, sid, {"date": "2026-07-25", "as_of": "2026-07-25",
                               "equity_usd": 100.0, "phase": "forward"})
    upsert_day(tmp_path, sid, {"date": "2026-07-25", "as_of": "2026-07-25",
                               "equity_usd": 999.0, "phase": "forward"})
    rows = _series(tmp_path, sid)
    assert len(rows) == 1 and rows[0]["equity_usd"] == 999.0, (
        "re-writing the same (date, phase) must REPLACE, not double-append")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 3. THE DEFAULT — no argv means "both", i.e. the destructive replay runs.
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_main_without_argv_runs_the_backtest_not_only_the_paper_tick(monkeypatch):
    """``run.main([])`` → mode "both". Nothing here is a wish about what the default SHOULD be —
    it is the fact a caller that passes no argument gets, and the live agent is such a caller."""
    from spa_core.strategy_lab.aggressive_lab import run as run_mod

    called = []
    monkeypatch.setattr(run_mod, "run_real_backtest", lambda: called.append("backtest") or {})
    monkeypatch.setattr(run_mod, "run_daily", lambda *a, **k: called.append("paper") or {})

    assert run_mod.main([]) == 0
    assert called == ["backtest", "paper"], (
        f"expected the no-argv default to run BOTH producers, got {called!r}")


def test_main_with_paper_argument_runs_only_the_forward_tick(monkeypatch):
    """Positive control: the argument the wrapper INTENDS to pass does the harmless thing — so the
    live damage is about the argument never arriving, not about the argument being wrong."""
    from spa_core.strategy_lab.aggressive_lab import run as run_mod

    called = []
    monkeypatch.setattr(run_mod, "run_real_backtest", lambda: called.append("backtest") or {})
    monkeypatch.setattr(run_mod, "run_daily", lambda *a, **k: called.append("paper") or {})

    assert run_mod.main(["paper"]) == 0
    assert called == ["paper"], f"'paper' must not run the replay, got {called!r}"


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 4. THE MECHANISM — a bash ARRAY does not cross a process boundary via `export`.
#    Measured on the real shell, not asserted from memory.
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_exported_bash_array_does_not_reach_a_child_shell(tmp_path):
    """`export MODULE_ARGS=(paper)` succeeds in the parent and arrives EMPTY in the child.

    This is why ``scripts/agent_aggressive_lab.sh`` — which sets exactly that and then execs
    ``scripts/agent_template.sh`` as a separate ``/bin/bash`` — has been running the module with no
    argument every night (verbatim in /tmp/spa_aggressive_lab.log: `... .run ` with nothing after
    it), i.e. mode "both" per test 3. Fixing the wrapper is the owner's domain (a live launchd
    agent); pinning the shell fact is not."""
    child = tmp_path / "child.sh"
    child.write_text(textwrap.dedent("""\
        #!/bin/bash
        # the guard agent_template.sh uses at line 50
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
        "the child saw the array — if bash ever starts exporting arrays, the wrapper's intent "
        f"would arrive and this whole finding changes; got {out.stdout!r}")


def test_the_wrapper_and_template_still_carry_the_two_halves_of_the_mechanism():
    """Both halves still exist in the tree, quoted from the real files.

    Deliberately NOT a guard that fails until the wrapper is fixed: the fix is owner-gated and a
    red test on main is forbidden (invariant #16 is about not weakening tests, not about shipping
    known-red ones). If the owner fixes the wrapper, this test is the one to update — and it says
    so out loud, which a silent absence of coverage never did."""
    root = Path(__file__).resolve().parents[2]
    wrapper = root / "scripts" / "agent_aggressive_lab.sh"
    template = root / "scripts" / "agent_template.sh"
    if not (wrapper.is_file() and template.is_file()):
        pytest.skip(f"wrapper/template not present in this checkout: {wrapper}, {template}")

    w = wrapper.read_text(encoding="utf-8")
    t = template.read_text(encoding="utf-8")
    assert "MODULE=\"spa_core.strategy_lab.aggressive_lab.run\"" in w, (
        "the wrapper no longer targets the aggressive-lab run module — re-derive this finding")
    assert "declare -p MODULE_ARGS" in t, (
        "agent_template.sh no longer falls back to an EMPTY MODULE_ARGS — the second half of the "
        "mechanism changed and the owner card must be re-measured")
