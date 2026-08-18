"""Positive controls for the live-feed GATE (card ``agent-tests-reach-live-feed-222``).

The gate's whole claim is one sentence: **a test that reaches for a live feed
goes red, a test that injects a fake feed goes green.** Everything here exists to
make that claim falsifiable rather than asserted:

* the decision table is pinned in BOTH directions on the pure function, so a
  mutation that makes the gate permissive and a mutation that makes it
  trigger-happy each turn a test red (``TestTheDecisionTable``,
  ``TestMutatingTheGateBreaksTheseTests``);
* the end-to-end control actually runs pytest on two generated tests — one that
  calls ``urlopen`` on a real feed URL, one that injects a fake — through the
  real ``conftest``, and asserts the first ERRORs with the gate's message while
  the second passes (``TestEndToEnd``). Without it "the gate is wired up" would
  be a claim about a file, not about a run — the exact shape
  ``.claude/rules/deployment.md`` calls "проверка, никогда не видевшая настоящей
  поломки".

The baseline is checked for the properties that make it a ratchet rather than a
wish list: every capped nodeid names a file that exists, every measured file
exists, and the cutoff is a real commit time.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_feed_gate as gate  # noqa: E402  (path pinned above)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: A baseline that owes nothing to the real one — the decision table must be a
#: property of the code, not of whatever is on disk today.
FAKE_BASELINE = {
    "cutoff_epoch": 1_000_000,
    "measured_files": ["spa_core/tests/test_measured.py"],
    "caps": {"spa_core/tests/test_measured.py::test_known_offender": 21},
}


class TestTheDecisionTable:
    """Every row of the table in live_feed_gate.__doc__, pinned both ways."""

    def test_a_capped_test_at_its_cap_is_allowed(self):
        assert gate.verdict(
            "spa_core/tests/test_measured.py::test_known_offender",
            21, marked=False, baseline=FAKE_BASELINE, is_new=False,
        ) is None

    def test_a_capped_test_over_its_cap_is_refused(self):
        msg = gate.verdict(
            "spa_core/tests/test_measured.py::test_known_offender",
            22, marked=False, baseline=FAKE_BASELINE, is_new=False,
        )
        assert msg is not None and "allows 21" in msg

    def test_a_new_test_in_a_measured_file_is_refused(self):
        msg = gate.verdict(
            "spa_core/tests/test_measured.py::test_added_later",
            1, marked=False, baseline=FAKE_BASELINE, is_new=False,
        )
        assert msg is not None and "measured clean" in msg

    def test_a_test_in_a_NEW_file_is_refused(self):
        msg = gate.verdict(
            "spa_core/tests/test_brand_new.py::test_anything",
            1, marked=False, baseline=FAKE_BASELINE, is_new=True,
        )
        assert msg is not None and "is NEW" in msg

    def test_an_old_unmeasured_file_is_NOT_gated(self):
        """The honest gap, pinned so nobody 'fixes' it into a mass-red gate.

        Kept deliberately: 89 % of the suite has never been measured, and a gate
        that reddens for being unmeasured gets switched off (the frozen-date
        ratchet lesson). It is reported by the banner and written into
        ``coverage_note``, not hidden.
        """
        assert gate.verdict(
            "spa_core/tests/test_old_unmeasured.py::test_anything",
            99, marked=False, baseline=FAKE_BASELINE, is_new=False,
        ) is None

    def test_zero_refusals_is_never_a_violation(self):
        assert gate.verdict(
            "spa_core/tests/test_brand_new.py::test_anything",
            0, marked=False, baseline=FAKE_BASELINE, is_new=True,
        ) is None

    def test_the_transport_marker_opts_a_test_out(self):
        assert gate.verdict(
            "spa_core/tests/test_brand_new.py::test_transport_itself",
            5, marked=True, baseline=FAKE_BASELINE, is_new=True,
        ) is None


class TestMutatingTheGateBreaksTheseTests:
    """The controls above must disagree with BOTH degenerate gates.

    A test suite that would still pass against ``lambda *a, **k: None`` (gate
    off) or against ``lambda *a, **k: "boom"`` (gate always firing) is not
    testing a gate. This states that in one place instead of trusting it.
    """

    CASES = [
        # (nodeid, count, marked, is_new, expect_violation)
        ("spa_core/tests/test_measured.py::test_known_offender", 21, False, False, False),
        ("spa_core/tests/test_measured.py::test_known_offender", 22, False, False, True),
        ("spa_core/tests/test_brand_new.py::test_anything", 1, False, True, True),
        ("spa_core/tests/test_brand_new.py::test_anything", 0, False, True, False),
        ("spa_core/tests/test_brand_new.py::test_transport", 5, True, True, False),
    ]

    def test_the_real_gate_matches_the_table(self):
        for nodeid, count, marked, is_new, expected in self.CASES:
            got = gate.verdict(nodeid, count, marked, FAKE_BASELINE, is_new) is not None
            assert got is expected, nodeid

    def test_a_permissive_mutant_fails_the_table(self):
        mutant = lambda *a, **k: None  # noqa: E731 — "the gate never fires"
        assert any(
            (mutant() is not None) is not expected
            for *_unused, expected in self.CASES
        )

    def test_a_trigger_happy_mutant_fails_the_table(self):
        mutant = lambda *a, **k: "always"  # noqa: E731
        assert any(
            (mutant() is not None) is not expected
            for *_unused, expected in self.CASES
        )


class TestTheTimeBudget:
    """The other half of the card: one slow zone eating the cycle.

    Pinned both ways, for the same reason as the network table — a budget that
    banned everything slow would be routed around, and a budget that never fires
    is decoration.
    """

    BASE = dict(
        FAKE_BASELINE,
        slow_test_seconds=30.0,
        duration_caps={"spa_core/tests/test_measured.py::test_long": 60.0},
    )

    def test_a_quick_test_is_never_gated(self):
        assert gate.duration_verdict(
            "spa_core/tests/test_brand_new.py::t", 0.5, False, self.BASE, is_new=True
        ) is None

    def test_an_undeclared_long_runner_is_refused(self):
        msg = gate.duration_verdict(
            "spa_core/tests/test_brand_new.py::t", 31.0, False, self.BASE, is_new=True
        )
        assert msg is not None and "30s budget" in msg

    def test_the_slow_marker_declares_it_and_opts_out(self):
        assert gate.duration_verdict(
            "spa_core/tests/test_brand_new.py::t", 300.0, True, self.BASE, is_new=True
        ) is None

    def test_a_measured_long_runner_keeps_its_recorded_cap(self):
        assert gate.duration_verdict(
            "spa_core/tests/test_measured.py::test_long", 65.0, False, self.BASE,
            is_new=False,
        ) is None

    def test_a_measured_long_runner_that_BLOWS_UP_is_refused(self):
        msg = gate.duration_verdict(
            "spa_core/tests/test_measured.py::test_long", 200.0, False, self.BASE,
            is_new=False,
        )
        assert msg is not None and "recorded cap" in msg

    def test_a_recorded_cap_may_only_RAISE_the_limit_never_lower_it(self):
        """max(), not min() — measured: a 28.6 s test took 34.1 s the next run.

        With a cap below the budget, ``cap x tolerance`` could sit under 30 s and
        machine load would start reddening tests for reasons the code does not
        own. That gate would be ignored within a week.
        """
        base = dict(self.BASE, duration_caps={"spa_core/tests/test_measured.py::t": 2.0})
        assert gate.duration_verdict(
            "spa_core/tests/test_measured.py::t", 20.0, False, base, is_new=False
        ) is None

    def test_an_old_unmeasured_file_is_NOT_time_gated(self):
        assert gate.duration_verdict(
            "spa_core/tests/test_old.py::t", 900.0, False, self.BASE, is_new=False
        ) is None

    def test_the_tolerance_is_wide_enough_to_survive_a_loaded_machine(self):
        # A tight time gate on a shared runner is a flaky gate, and a flaky gate
        # gets switched off. Pinned so nobody tightens it without deciding to.
        assert gate.DURATION_TOLERANCE >= 2.0

    def test_the_real_baseline_carries_the_measured_profile(self):
        b = gate.load_baseline()
        assert b["slow_test_seconds"] > 0
        assert b["duration_caps"], "the --durations profile was not recorded"
        stray = [n for n in b["duration_caps"]
                 if gate.file_of(n) not in set(b["measured_files"])]
        assert stray == [], stray


class TestTheBaselineIsARatchetNotAWishList:
    def test_every_measured_file_exists(self):
        b = gate.load_baseline()
        missing = [f for f in b["measured_files"] if not (REPO_ROOT / f).exists()]
        assert missing == [], f"baseline names files that are gone: {missing[:5]}"

    def test_every_capped_nodeid_names_a_measured_file(self):
        b = gate.load_baseline()
        measured = set(b["measured_files"])
        stray = [n for n in b["caps"] if gate.file_of(n) not in measured]
        assert stray == [], f"cap without a measured file: {stray[:5]}"

    def test_caps_are_positive_integers(self):
        b = gate.load_baseline()
        bad = {n: c for n, c in b["caps"].items() if not isinstance(c, int) or c <= 0}
        assert bad == {}, bad

    def test_the_cutoff_is_a_real_commit_time(self):
        b = gate.load_baseline()
        assert isinstance(b["cutoff_epoch"], int)
        # A cutoff in the future would gate NOTHING as new; a cutoff at zero
        # would gate EVERY file as new. Both are the same class of silent break.
        assert 1_600_000_000 < b["cutoff_epoch"] <= time.time() + 86_400

    def test_the_coverage_line_states_the_gap(self):
        line = gate.coverage()
        assert "measured" in line and "NEW test file gated at zero" in line


# ---------------------------------------------------------------------------
# End-to-end: the gate against a real pytest run.
# ---------------------------------------------------------------------------

_PROBE_NET = '''
import urllib.request


def test_reaches_a_live_feed():
    """Exactly the shape the card is about: production code swallows the
    transport error, so the body passes while the check means nothing."""
    try:
        urllib.request.urlopen("https://yields.llama.fi/pools", timeout=5)
    except Exception:
        pass
    assert True
'''

_PROBE_FAKE = '''
class FakeFeed:
    def get_pools(self):
        return [{"pool": "p", "apy": 4.2, "tvlUsd": 10_000_000}]


def test_uses_an_injected_feed():
    assert FakeFeed().get_pools()[0]["apy"] == 4.2
'''


def _run_probe(tmp_path: Path, name: str, body: str):
    """Run ONE generated test through the real conftest, in a subprocess.

    The conftest is loaded with ``-p spa_core.tests.conftest`` rather than by
    putting the probe inside the repo: a generated file under ``spa_core/tests``
    would be collected by every other run and could survive a crash, and
    ``git status`` staying clean is itself a guard here (card
    ``agent-test-run-dirties-tracked-fixtures``).
    """
    probe = tmp_path / name
    probe.write_text(body, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         "-p", "spa_core.tests.conftest", str(probe), "-q"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=600,
    )


@pytest.mark.slow
class TestEndToEnd:
    """The claim, run rather than argued."""

    def test_a_test_that_reaches_the_network_is_CAUGHT(self, tmp_path):
        res = _run_probe(tmp_path, "test_probe_net.py", _PROBE_NET)
        out = res.stdout + res.stderr
        assert res.returncode != 0, f"gate let a network-reaching test pass:\n{out}"
        assert "live-feed GATE" in out, out[-3000:]
        # And it names the reason, not just "something failed".
        assert "is NEW" in out, out[-3000:]

    def test_a_test_with_an_injected_fake_feed_PASSES(self, tmp_path):
        res = _run_probe(tmp_path, "test_probe_fake.py", _PROBE_FAKE)
        out = res.stdout + res.stderr
        assert res.returncode == 0, f"gate reddened a hermetic test:\n{out[-3000:]}"
        assert "live-feed GATE" not in out

    def test_the_marker_lets_a_transport_test_through(self, tmp_path):
        marked = _PROBE_NET.replace(
            "def test_reaches_a_live_feed():",
            "def test_reaches_a_live_feed():",
        )
        marked = "import pytest\npytestmark = pytest.mark.live_feed_transport\n" + marked
        res = _run_probe(tmp_path, "test_probe_marked.py", marked)
        out = res.stdout + res.stderr
        assert res.returncode == 0, f"marked transport test was gated:\n{out[-3000:]}"
        # The call is still refused — the mark allows the attempt, not the traffic.
        assert "live-network refusals" in out, out[-3000:]
