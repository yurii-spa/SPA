"""
The two pytest-summary readers must answer about the RUN, not about the log's
wording (ADR-828, order G828 п. 1).

Every scene here is produced by a REAL pytest subprocess and fed to the REAL
reader functions. Hand-built "sample output" strings are deliberately avoided:
the readers' previous tests were written that way, and they stayed green while
all four defects below were live, because the hand-built strings happened to
omit the one line (`test session starts`) and the one marker (`SUBFAILED`) that
made the parsers wrong.

Measured on live pytest 9.0.3, 2026-10-27, before the fix:
  · a test whose SUBTESTS failed was counted as `passed` and `failed` read 0;
  · a single errored test made `errors` read 3 (" ERROR" appears 3× per run);
  · `summary` read "test session starts" on EVERY run, pass or fail;
  · a failure outside a path starting with "tests/" was never named;
  · a timeout (no summary bar) reported 0/0/0 — indistinguishable from clean.
"""

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from spa_core.agents.tester_agent import TesterAgent
from spa_core.dev_agents.tester import SpaTester


# ── scenes: produced by a real pytest run, not by hand ────────────────────────

_SCENES = {
    # A test whose subtests fail. pytest prints "PASSED" for the carrier on its
    # verbose line and "SUBFAILED(i=N)" in the short summary.
    "subtests": '''
        import unittest

        class TestSub(unittest.TestCase):
            def test_subtest_only_failure(self):
                for i in (1, 2, 3):
                    with self.subTest(i=i):
                        self.assertEqual(i, 1)

            def test_plain_pass(self):
                self.assertTrue(True)

        class TestSkips(unittest.TestCase):
            def test_skipped_a(self):
                self.skipTest("scene: reason A")

            def test_skipped_b(self):
                self.skipTest("scene: reason B")
    ''',
    # Exactly ONE error — a broken fixture at setup.
    "one_error": '''
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("fixture blew up")

        def test_uses_broken(broken):
            assert True
    ''',
    # A run whose DURATION crosses one minute. pytest then appends a
    # human-readable duration in brackets to its summary bar — see
    # _SCENE_CONFTEST below for why the clock is shifted instead of slept.
    "long_run": '''
        def test_green():
            assert True

        def test_red():
            assert False, "scene: deliberately red"

        def test_skipped():
            import pytest; pytest.skip("scene: deliberately skipped")
    ''',
    "all_pass": '''
        def test_a():
            assert True

        def test_b():
            assert True
    ''',
}


# Some scenes need pytest itself to take a different code path. Here: the
# summary bar of a run longer than a minute.
#
# A test that really sleeps 61 s was used for the measurement (cycle #954,
# live pytest 9.0.3) and produced exactly:
#   "====== 1 failed, 1 passed, 1 skipped in 61.12s (0:01:01) ======"
# Keeping a 61-second sleep in the suite would tax every run forever, so the
# scene shifts pytest's own session start instead. The bracketed form is still
# produced by pytest's own `format_session_duration` — the string is never
# written by this file. `test_the_long_run_scene_matches_the_measured_form`
# below asserts the scene's bar has the shape that was measured for real; a
# hand-written bar would be exactly the defect this module exists to catch.
_SCENE_CONFTEST = {
    "long_run": '''
        def pytest_collection_finish(session):
            """Make pytest's own formatter print the long (bracketed) duration.

            This reaches into pytest internals, and the attribute has already
            been renamed once (`_sessionstarttime` → `_session_start` in
            pytest 9). So it must stay SILENT when it cannot shift the clock:
            the scene then prints a short bar, `_long_bar()` fails loudly with
            "premise NOT established", and nobody mistakes "not measured" for
            "measured and fine". Raising here would abort the whole scene
            module with an INTERNALERROR instead.
            """
            extra_seconds = 3600.0
            tr = session.config.pluginmanager.get_plugin("terminalreporter")
            if tr is None:
                return

            instant = getattr(tr, "_session_start", None)
            if instant is not None and hasattr(instant, "elapsed"):
                class _Duration:
                    def __init__(self, seconds):
                        self.seconds = seconds

                class _ShiftedInstant:
                    def elapsed(self):
                        return _Duration(
                            instant.elapsed().seconds + extra_seconds
                        )

                tr._session_start = _ShiftedInstant()
                return

            if isinstance(getattr(tr, "_sessionstarttime", None), (int, float)):
                tr._sessionstarttime -= extra_seconds
    ''',
}


def _run_scene(tmp_path: Path, name: str, extra_args: tuple[str, ...]) -> tuple[str, int]:
    """Run a real pytest on a scene file; return (combined output, exit code)."""
    scene_dir = tmp_path / name
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / f"test_{name}.py").write_text(textwrap.dedent(_SCENES[name]))
    if name in _SCENE_CONFTEST:
        (scene_dir / "conftest.py").write_text(
            textwrap.dedent(_SCENE_CONFTEST[name])
        )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", f"test_{name}.py",
         "-p", "no:cacheprovider", *extra_args],
        cwd=str(scene_dir), capture_output=True, text=True, timeout=300,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    # A scene that did not run is not evidence about the readers — fail loudly
    # rather than judging an empty log (third outcome, invariant #17).
    if "no tests ran" in out or proc.returncode >= 4:
        pytest.fail(
            f"scene {name!r} did not run (exit={proc.returncode}); "
            f"premise NOT established, nothing measured:\n{out[-2000:]}"
        )
    return out, proc.returncode


@pytest.fixture(scope="module")
def scenes(tmp_path_factory) -> dict:
    """Real pytest output for every scene, in both readers' own invocations."""
    base = tmp_path_factory.mktemp("summary_reader_scenes")
    r1 = ("-v", "--tb=short", "--no-header")   # spa_core/dev_agents/tester.py
    r2 = ("-v",)                                # spa_core/agents/tester_agent.py
    return {
        name: {
            "reader1": _run_scene(base / "r1", name, r1),
            "reader2": _run_scene(base / "r2", name, r2),
        }
        for name in _SCENES
    }


# ── reader 1: spa_core/dev_agents/tester.py ──────────────────────────────────

def test_reader1_counts_a_failed_subtest_as_a_failure(scenes):
    """The defect: carrier printed PASSED, so `failed` was 0 on a red run."""
    out, rc = scenes["subtests"]["reader1"]
    r = SpaTester()._parse_output(out, returncode=rc, duration=1.0)

    assert r["counts_measured"] is True
    assert r["failed"] >= 1, (
        "a run whose subtests failed must not report zero failures; "
        f"bar was {r['summary']!r}"
    )
    assert r["status"] == "FAIL"


def test_reader1_names_the_test_whose_subtest_failed(scenes):
    """A red verdict with an empty name list is the report that cost ADR-828."""
    out, rc = scenes["subtests"]["reader1"]
    r = SpaTester()._parse_output(out, returncode=rc, duration=1.0)

    assert r["failed_tests"], "no name reported for a failed subtest"
    assert any("test_subtest_only_failure" in n for n in r["failed_tests"])
    # Deduplicated: two failed subtests of one test are one test id.
    assert len(r["failed_tests"]) == len(set(r["failed_tests"]))


def test_reader1_names_failures_outside_a_tests_slash_path(scenes):
    """
    The old name regex was anchored to "FAILED (tests/...)", so any failure
    under spa_core/tests/ — the suite's biggest directory — went unnamed.
    These scenes live in a tmp dir, i.e. no "tests/" prefix at all.
    """
    out, rc = scenes["subtests"]["reader1"]
    r = SpaTester()._parse_output(out, returncode=rc, duration=1.0)

    assert r["failed_tests"]
    assert not any(n.startswith("tests/") for n in r["failed_tests"]), (
        "scene paths carry no 'tests/' prefix — if they did, this test would "
        "not be measuring the anchor at all"
    )


def test_reader1_counts_one_error_once(scenes):
    """The defect: " ERROR" appears 3× per errored run, so `errors` read 3."""
    out, rc = scenes["one_error"]["reader1"]
    r = SpaTester()._parse_output(out, returncode=rc, duration=1.0)

    assert out.count(" ERROR") >= 2, (
        "premise: verbose output must repeat ' ERROR' — otherwise this test "
        "is not measuring the over-count"
    )
    assert r["errors"] == 1, f"one error must count once, got {r['errors']}"


def test_reader1_summary_is_the_result_bar_not_the_session_banner(scenes):
    """The defect: `summary` read "test session starts" on every single run."""
    for name in ("all_pass", "subtests", "one_error"):
        out, rc = scenes[name]["reader1"]
        r = SpaTester()._parse_output(out, returncode=rc, duration=1.0)
        assert r["summary"] is not None, name
        assert "test session starts" not in r["summary"], (
            f"scene {name}: summary carries the session banner, not the result"
        )
        assert " in " in r["summary"] and "=" in r["summary"], (
            f"scene {name}: summary is not pytest's result bar: {r['summary']!r}"
        )


def test_reader1_reports_the_owner_a_reason_for_every_red_verdict(scenes):
    """A ❌ message must carry either a failure count or an explicit reason."""
    t = SpaTester()
    out, rc = scenes["subtests"]["reader1"]
    msg = t.format_telegram(t._parse_output(out, returncode=rc, duration=1.0))

    assert msg.startswith("❌")
    assert "failed" in msg
    assert "test_subtest_only_failure" in msg
    assert "test session starts" not in msg


def test_reader1_absent_summary_bar_is_a_named_third_outcome():
    """
    Timeout / crash: no bar was printed. Zeros here read as a clean run — the
    class invariant #17 exists for. Must be None + a named reason, not 0.
    """
    r = SpaTester()._parse_output(
        "TIMEOUT: tests exceeded 120 seconds", returncode=1, duration=120.0
    )

    assert r["counts_measured"] is False
    assert r["passed"] is None and r["failed"] is None and r["errors"] is None
    assert r["total"] is None
    assert r["unmeasured_reason"]
    msg = SpaTester().format_telegram(r)
    assert "НЕ ИЗМЕРЕН" in msg, "the owner must be told nothing was counted"


def test_reader1_measured_zero_is_not_the_third_outcome(scenes):
    """The other side of the same door: a real clean run IS measured."""
    out, rc = scenes["all_pass"]["reader1"]
    r = SpaTester()._parse_output(out, returncode=rc, duration=1.0)

    assert r["counts_measured"] is True
    assert r["failed"] == 0 and r["errors"] == 0
    assert r["unmeasured_reason"] is None
    assert r["status"] == "PASS"


# ── reader 2: spa_core/agents/tester_agent.py ────────────────────────────────

def test_reader2_names_the_failed_subtest_with_its_parameters(scenes):
    """
    Reader 2's COUNTS were already right (it parses the bar). Its name list was
    blind: "SUBFAILED(i=2) …" never matched "^(FAILED|ERROR)".
    """
    out, _rc = scenes["subtests"]["reader2"]
    parsed = TesterAgent.parse_pytest_output(TesterAgent, out)

    assert "SUBFAILED" in out, "premise: pytest must print SUBFAILED lines"
    subfails = [f for f in parsed["failures"] if f["kind"] == "SUBFAILED"]
    assert subfails, "a failed subtest was not named at all"
    assert any("test_subtest_only_failure" in f["name"] for f in subfails)
    # The parameters distinguish the two failing subtests of one test.
    assert {f["params"] for f in subfails} >= {"i=2", "i=3"}


def test_reader2_counts_are_unchanged_by_the_name_door(scenes):
    """Guard against a regression in the half that was already correct."""
    out, _rc = scenes["subtests"]["reader2"]
    parsed = TesterAgent.parse_pytest_output(TesterAgent, out)

    assert parsed["totals"]["failed"] >= 1
    assert parsed["totals"]["skipped"] == 2
    assert parsed["summary_line"] is not None
    assert "test session starts" not in parsed["summary_line"]


def test_reader2_plain_failures_keep_their_kind(scenes):
    """SUBFAILED support must not relabel ordinary errors."""
    out, _rc = scenes["one_error"]["reader2"]
    parsed = TesterAgent.parse_pytest_output(TesterAgent, out)

    kinds = {f["kind"] for f in parsed["failures"]}
    assert "SUBFAILED" not in kinds
    assert kinds <= {"FAILED", "ERROR"}
    assert parsed["totals"]["errors"] == 1


# ── both readers: the bar of a run longer than a minute (cycle #954) ─────────
#
# ADR-828 (cycle #953) introduced the summary bar as the ONE door to the
# numbers and called reader 2's counts "already correct". Both claims were
# measured on scenes that finish in 0.01 s. pytest formats the duration
# differently once a run passes one minute, and neither bar regex allowed for
# it, so on a real run:
#   · reader 1 answered "счёт НЕ ИЗМЕРЕН: pytest printed no summary bar"
#     while pytest HAD printed it — a false third outcome;
#   · reader 2 reported 0 passed / 0 failed for "1 failed, 1 passed" and
#     `summary_line = None`, while `collected` said 3 — a silent fail-OPEN.
# dev_agents/tester.py runs with a 120 s timeout, so 60–120 s is its ordinary
# case, not an edge one.

_LONG_BAR_SHAPE = re.compile(
    r"^=+\s*.*?\s+in\s+\d+\.\d+s\s+\(\d+:\d{2}:\d{2}\)\s*=+\s*$"
)


def _long_bar(output: str) -> str:
    bars = [
        line.strip() for line in output.splitlines()
        if _LONG_BAR_SHAPE.match(line.rstrip())
    ]
    if not bars:
        pytest.fail(
            "premise NOT established: the scene produced no bracketed-duration "
            "summary bar, so nothing is measured about the 60-second boundary "
            f"(invariant #17). Output tail:\n{output[-2000:]}"
        )
    return bars[-1]


def test_the_long_run_scene_matches_the_measured_form(scenes):
    """
    Positive control on the SCENE itself: the shifted clock must make pytest
    print the same shape a real 61-second run printed
    ("… in 61.12s (0:01:01) …"). Without this, a scene that silently stopped
    producing the long form would make the two tests below vacuous.
    """
    for reader in ("reader1", "reader2"):
        out, _rc = scenes["long_run"][reader]
        bar = _long_bar(out)
        assert " in " in bar and "(" in bar
        assert "test session starts" not in bar


def test_reader1_counts_a_run_longer_than_a_minute(scenes):
    """The bar exists; "not measured" here is a false third outcome."""
    out, rc = scenes["long_run"]["reader1"]
    bar = _long_bar(out)
    r = SpaTester()._parse_output(out, returncode=rc, duration=3601.0)

    assert r["counts_measured"] is True, (
        f"pytest printed the bar {bar!r} and the reader said it did not"
    )
    assert r["unmeasured_reason"] is None
    assert r["passed"] == 1 and r["failed"] == 1 and r["skipped"] == 1
    assert r["summary"] == bar
    msg = SpaTester().format_telegram(r)
    assert "НЕ ИЗМЕРЕН" not in msg


def test_reader2_counts_a_run_longer_than_a_minute(scenes):
    """Same boundary, the other reader: zeros that looked like a clean run."""
    out, _rc = scenes["long_run"]["reader2"]
    bar = _long_bar(out)
    parsed = TesterAgent.parse_pytest_output(TesterAgent, out)

    assert parsed["summary_line"] == bar, (
        f"pytest printed the bar {bar!r}; the reader found "
        f"{parsed['summary_line']!r}"
    )
    assert parsed["totals"]["failed"] == 1
    assert parsed["totals"]["passed"] == 1
    assert parsed["totals"]["skipped"] == 1
    assert parsed["duration_s"] is not None


# ── reader 2: the third outcome it did not have (ADR-829, cycle #955) ────────
#
# Order G829 п. 4 named the remaining half of the class: reader 2 has no third
# outcome at all. When no summary bar is there (timeout, crash, truncated log)
# `parse_pytest_output` returned a full set of ZEROS and `summary_line = None`,
# so "measured and equal to zero" and "never measured" were the same value
# (invariant #17). Measured 27.10 on the 61.12 s run: 0 passed / 0 failed for
# a run pytest had reported as "1 failed", with `collected = 3` lying beside it.
#
# The class has THREE doors, not one, and only one of them goes through the
# parser (measured 27.10, cycle #955): `run_tests` also built all-zero totals
# when no test directory was found (`exit_code = -1`) and when the pytest
# subprocess never finished (`exit_code = -2`). Fixing the parser alone would
# have left two doors answering zeros.


_SUMMARY_BAR_SHAPE = re.compile(r"^=+\s*.*?\s+in\s+\d+(?:\.\d+)?s(?:\s+\([^)]*\))?\s*=+\s*$")


def _without_bar(output: str) -> str:
    """A REAL run's log, truncated before its summary bar.

    This is the shape of a timed-out or killed run: everything up to the bar
    is there, the bar is not. Using a real log rather than a hand-made string
    is the whole method of this module.
    """
    kept = [
        line for line in output.splitlines()
        if not _SUMMARY_BAR_SHAPE.match(line.rstrip())
    ]
    if len(kept) == len(output.splitlines()):
        pytest.fail(
            "premise NOT established: no summary bar found to remove, so this "
            "scene measures nothing about the missing-bar outcome"
        )
    return "\n".join(kept) + "\n"


def test_reader2_absent_summary_bar_is_a_named_third_outcome(scenes):
    """Zeros for an unmeasured run are what made a timeout read as clean."""
    out, _rc = scenes["subtests"]["reader2"]
    truncated = _without_bar(out)
    parsed = TesterAgent.parse_pytest_output(TesterAgent, truncated)

    assert parsed["counts_measured"] is False
    assert parsed["unmeasured_reason"], "a third outcome without a reason is silence"
    for key in ("passed", "failed", "errors", "skipped"):
        assert parsed["totals"][key] is None, (
            f"{key} must be None when nothing was counted, not 0"
        )
    assert parsed["summary_line"] is None


def test_reader2_collected_keeps_its_own_door_when_the_bar_is_gone(scenes):
    """
    `collected` comes from a different line of output than the tally. It can
    be measured when the bar is not — folding it into the bar's verdict would
    hide one measurement behind another's absence.
    """
    out, _rc = scenes["subtests"]["reader2"]
    truncated = _without_bar(out)
    parsed = TesterAgent.parse_pytest_output(TesterAgent, truncated)

    assert "collected" in truncated, "premise: the collection line must survive"
    assert parsed["collected_measured"] is True
    assert parsed["totals"]["collected"] >= 1
    # …and the tally is still honestly absent.
    assert parsed["counts_measured"] is False


def test_reader2_measured_zero_is_not_the_third_outcome(scenes):
    """The other side of the door: a real clean run IS measured."""
    out, _rc = scenes["all_pass"]["reader2"]
    parsed = TesterAgent.parse_pytest_output(TesterAgent, out)

    assert parsed["counts_measured"] is True
    assert parsed["unmeasured_reason"] is None
    assert parsed["totals"]["failed"] == 0 and parsed["totals"]["errors"] == 0


def test_reader2_totals_have_one_shape_on_every_path(scenes):
    """
    The keys of `totals` must not depend on which branch produced the dict.
    Until this cycle the empty-stdout path alone carried an extra "error" key,
    because the singular→plural fold ran after an early return.
    """
    measured_out, _rc = scenes["all_pass"]["reader2"]
    shapes = {
        "measured": TesterAgent.parse_pytest_output(TesterAgent, measured_out),
        "no_bar": TesterAgent.parse_pytest_output(
            TesterAgent, _without_bar(scenes["subtests"]["reader2"][0])
        ),
        "empty": TesterAgent.parse_pytest_output(TesterAgent, ""),
    }
    keysets = {name: set(r["totals"]) for name, r in shapes.items()}
    assert len(set(map(frozenset, keysets.values()))) == 1, keysets
    for name, r in shapes.items():
        assert "error" not in r["totals"], f"{name}: singular 'error' key leaked"
        assert {"counts_measured", "unmeasured_reason", "collected_measured"} <= set(r)


def test_reader2_a_run_that_never_started_is_not_a_clean_run(tmp_path):
    """
    Door two of the class: `run_tests` with no test directory never reaches
    the parser, and it used to answer all zeros for a pytest that never ran.
    """
    from spa_core.message_bus.bus import MessageBus

    agent = TesterAgent(MessageBus(), repo_root=tmp_path)
    result = agent.run_tests()

    assert result["exit_code"] == -1, (
        "premise: this tmp repo must contain no test directory at all"
    )
    assert result["counts_measured"] is False
    assert result["unmeasured_reason"]
    assert result["totals"]["passed"] is None and result["totals"]["failed"] is None


def test_reader2_a_subprocess_that_never_finished_is_not_a_clean_run(
    tmp_path, monkeypatch
):
    """Door three: the pytest subprocess timed out or could not be launched."""
    import subprocess as _sp

    from spa_core.message_bus.bus import MessageBus

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text("def test_x():\n    assert True\n")
    agent = TesterAgent(MessageBus(), repo_root=tmp_path)

    def _boom(*_a, **_kw):
        raise _sp.TimeoutExpired(cmd="pytest", timeout=600)

    monkeypatch.setattr("spa_core.agents.tester_agent.subprocess.run", _boom)
    result = agent.run_tests()

    assert result["exit_code"] == -2
    assert result["counts_measured"] is False
    assert "NOT measured" in result["unmeasured_reason"]
    assert result["totals"]["failed"] is None


def test_the_collected_clue_is_not_a_watchdog_and_the_measurement_says_why(scenes):
    """
    Order G829 п. 5 asked for a guard comparing `collected` against the sum of
    outcomes, on the grounds that "collected = 3 beside a sum of 0" was a
    direct sign of an unparsed bar. The sign is real, but the guard is not:
    MEASURED 27.10 on live pytest 9.0.3, the two numbers legitimately disagree
    on ordinary runs, because they count different things —

      · this scene: 4 tests collected, 6 outcomes in the bar (a failed subtest
        is tallied in `failed`, while `collected` counts TESTS);
      · `-x` / `--exitfirst`: 3 collected, 2 outcomes — the run stopped early.

    Two of four live scenes differed with nothing whatsoever wrong, so a guard
    on inequality would be a false-alarm generator, and its baseline would
    teach the next cycle to suppress it. The silent form п. 5 was actually
    aimed at — "a sum of zero presented as a measurement" — is closed by
    `counts_measured` above, at the door, and not by arithmetic beside it.

    This test exists to keep that measurement from being re-derived as an
    opinion: it will go red if the two numbers ever start agreeing here, which
    is the only thing that would reopen the question.
    """
    out, _rc = scenes["subtests"]["reader2"]
    parsed = TesterAgent.parse_pytest_output(TesterAgent, out)
    totals = parsed["totals"]

    assert parsed["counts_measured"] is True
    outcomes = sum(
        totals[k] for k in ("passed", "failed", "errors", "skipped",
                            "xfailed", "xpassed")
    )
    assert totals["collected"] is not None
    assert outcomes != totals["collected"], (
        "the two numbers agreed on this scene; the premise of the declined "
        f"guard changed (outcomes={outcomes}, collected={totals['collected']})"
    )


def test_reader2_the_line_a_human_reads_never_fakes_a_tally(
    scenes, tmp_path, monkeypatch, caplog
):
    """
    The census in ADR-828 found NO reader of `data/tester_report.json` or of
    the `tester.report` bus topic: the only live door of this agent is a human
    reading its output. So the dict carrying `counts_measured` is not the whole
    fix — the sentence printed beside it is the product.

    Mutation 9 of docs/mutations/ADR-829.json survived the first run for
    exactly this reason: removing the branch changed what a human reads and
    nothing went red.
    """
    import logging
    from unittest.mock import MagicMock

    from spa_core.agents.tester_agent import TesterAgent as _TA

    # ── unmeasured: a real run_tests door (no test directory at all) ─────────
    agent = _TA(bus=MagicMock(), repo_root=tmp_path)
    with caplog.at_level(logging.DEBUG, logger="spa.agent.tester_agent"):
        agent.run()
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "NOT MEASURED" in said, (
        f"an unmeasured run must say so to whoever reads the log; said: {said!r}"
    )
    assert "0 passed" not in said and "None passed" not in said, (
        "a tally was presented for a run that produced none"
    )

    # ── measured: the SAME code path, replaying a real pytest log ───────────
    real_out, real_rc = scenes["all_pass"]["reader2"]
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_placeholder.py").write_text(
        "def test_placeholder():\n    assert True\n"
    )

    def _replay(*_a, **_kw):
        from types import SimpleNamespace
        return SimpleNamespace(stdout=real_out, stderr="", returncode=real_rc)

    monkeypatch.setattr("spa_core.agents.tester_agent.subprocess.run", _replay)
    agent2 = _TA(bus=MagicMock(), repo_root=tmp_path)
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="spa.agent.tester_agent"):
        agent2.run()
    said2 = " ".join(r.getMessage() for r in caplog.records)
    assert "NOT MEASURED" not in said2, (
        f"a measured run must not be reported as unmeasured; said: {said2!r}"
    )
    assert "2 passed" in said2, said2
