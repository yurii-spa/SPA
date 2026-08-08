"""The network guard's ledger belongs to ONE test — pinned, not assumed.

Incident (measured 2026-08-04, cycle #115, cards
``agent-network-guard-attempts-never-reset`` /
``agent-telegram-guard-outermost-fails-only-in-full-run``)
--------------------------------------------------------------------------
``telegram_guard`` has been reset before every test since cycle #55.
``network_guard``, added in #93, never was, so its ``_ATTEMPTS`` list grew for
the whole session.  The only assertion in the repo that reads the LIVE ledger
— ``test_no_live_network_in_tests::test_telegram_guard_stays_outermost``, whose
claim is *"the network guard did not swallow **my** Telegram call"* — was
therefore comparing a session-wide cumulative list against ``[]``::

    isolation:  15 passed in 0.13 s
    full run:   AssertionError: Lists differ: ['urlopen https://yields.llama.fi/pools', …] != []
                First list contains 2745 additional elements.
                ERROR at teardown: LiveTelegramSendAttempted

That one test was the entire reason ``SPA Tests`` and ``SPA CI`` were red on
``main``, and under ``-x`` it stopped the suite at 58 %, leaving the remaining
42 % unrun.

Why the ledger is scoped rather than the assertion relaxed
---------------------------------------------------------
The card put the fork explicitly: either the "ledger is empty" claim is local
to the test (then scope it), or it is global (then 2745 real violations must be
named and fixed).  Measured, on ``origin/main`` d07714d07: 2745 refusals from
**102 named tests**, 2153 of them to ``yields.llama.fi``, the rest to
CoinGecko / Fluid / Binance / Bybit / OKX / KuCoin / Hyperliquid / Pendle /
Ethena / Usual.  Every one is a *refusal* — the guard raised ``OSError`` and no
call went out — so they are not leaks to chase, they are the guard working.
The assertion's claim was local all along; the ledger was not.  Nothing is
hidden by the fix: those refusals used to be read by nobody and are now
attributed per test and printed at the end of the run.

Hermetic: no network (that is the point), no repo state, stdlib + unittest.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: The live guard installed by conftest — the one that protects the real run.
_live_net = sys.modules.get("spa_network_guard")

_LIVE_URL = "https://api.llama.fi/pools"


def _load_guard():
    """Load a FRESH copy of network_guard.py — never the installed one."""
    spec = importlib.util.spec_from_file_location(
        "spa_network_guard_ledger_under_test", _HERE / "network_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)                 # type: ignore[union-attr]
    return mod


def _conftest_module():
    """The conftest object pytest already loaded, found by file identity.

    Looked up rather than re-exec'd: a second copy would re-run the guard
    installs and the collect_ignore scan, and the point here is to inspect the
    module that is actually in force.
    """
    target = os.path.realpath(str(_HERE / "conftest.py"))
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None)
        if path and os.path.realpath(path) == target:
            return mod
    return None


# ---------------------------------------------------------------------------
# The behavioural pin.  These two run in definition order in the same module,
# which is the only way to observe "between tests" from inside a test: the
# first fills the LIVE ledger, the second states what the next test must see.
# Without the autouse fixture the second one fails — that is the regression.
# ---------------------------------------------------------------------------
def test_a_a_refused_call_lands_in_the_live_ledger():
    """Positive control: without this, the pin below would pass vacuously."""
    assert _live_net is not None, "conftest did not install network_guard"
    try:
        urllib.request.urlopen(_LIVE_URL)
    except OSError:
        pass  # the refusal is the point; production code swallows it too
    recorded = _live_net.attempts()
    assert recorded, "the guard recorded nothing — the ledger pin is vacuous"
    assert "api.llama.fi" in recorded[-1]


def test_b_the_next_test_starts_with_an_empty_ledger():
    """The regression itself: this is what test_telegram_guard_stays_outermost
    was really asserting, and what a session-cumulative ledger made impossible.
    """
    assert _live_net.attempts() == [], (
        "the network guard's ledger carried over from the previous test — the "
        "session-cumulative ledger is back, and every assertion about 'my own "
        "refusals' now reads someone else's"
    )


def test_c_the_previous_tests_refusal_was_archived_not_discarded():
    """Scoping the ledger must not lose the refusal — only re-file it.

    This is the half that keeps the fix honest: 'reset between tests' on its own
    would silently drop 2745 measurements, which is the exact failure class
    (#29/#31/#35-#38, #40) this repo keeps closing.
    """
    archived = _live_net.archived()
    mine = [
        (nodeid, items)
        for nodeid, items in archived
        if nodeid.endswith("test_a_a_refused_call_lands_in_the_live_ledger")
    ]
    assert mine, (
        "the refusal made by test_a is in no ledger at all — it was reset away "
        f"instead of archived (archive holds {len(archived)} test(s))"
    )
    assert any("api.llama.fi" in item for _, items in mine for item in items)


class TestArchiveSemantics(unittest.TestCase):
    """Archive behaviour on a FRESH copy — no dependence on the live run."""

    def setUp(self):
        self.guard = _load_guard()

    def test_archive_moves_the_ledger_and_clears_it(self):
        self.guard._ATTEMPTS.extend(["urlopen https://example.invalid/a"])
        moved = self.guard.archive("some/test.py::test_x")
        self.assertEqual(moved, ["urlopen https://example.invalid/a"])
        self.assertEqual(self.guard.attempts(), [], "ledger not cleared")
        self.assertEqual(
            self.guard.archived(), [("some/test.py::test_x", moved)]
        )

    def test_archive_of_a_clean_test_records_nothing(self):
        """Otherwise the end-of-run report would list all ~91k tests."""
        self.assertEqual(self.guard.archive("some/test.py::test_clean"), [])
        self.assertEqual(self.guard.archived(), [])

    def test_archived_returns_copies(self):
        """A caller mutating the report must not corrupt the record."""
        self.guard._ATTEMPTS.append("urlopen https://example.invalid/b")
        self.guard.archive("some/test.py::test_y")
        snapshot = self.guard.archived()
        snapshot.clear()
        snapshot_again = self.guard.archived()
        self.assertEqual(len(snapshot_again), 1)
        snapshot_again[0][1].append("forged")
        self.assertEqual(len(self.guard.archived()[0][1]), 1)

    def test_clear_archive_empties_it(self):
        self.guard._ATTEMPTS.append("urlopen https://example.invalid/c")
        self.guard.archive("some/test.py::test_z")
        self.guard.clear_archive()
        self.assertEqual(self.guard.archived(), [])

    def test_reset_alone_does_not_touch_the_archive(self):
        self.guard._ATTEMPTS.append("urlopen https://example.invalid/d")
        self.guard.archive("some/test.py::test_w")
        self.guard.reset()
        self.assertEqual(len(self.guard.archived()), 1)


class _Reporter:
    """Minimal stand-in for pytest's terminal reporter."""

    def __init__(self):
        self.lines = []

    def write_sep(self, sep, title=""):
        self.lines.append(f"{sep} {title}")

    def write_line(self, line):
        self.lines.append(line)


class TestEndOfRunReport(unittest.TestCase):
    """The refusals must be *reported*, not merely retained.

    A record nobody prints is the same as no record — that is the whole reason
    the 2745 refusals went unnoticed for a day while reddening an unrelated
    test.
    """

    def setUp(self):
        self.conftest = _conftest_module()
        self.assertIsNotNone(self.conftest, "conftest module not found by path")
        self.summary = getattr(self.conftest, "pytest_terminal_summary", None)
        self.assertIsNotNone(
            self.summary, "conftest defines no end-of-run report for refusals"
        )
        self._archive = _live_net._ARCHIVE
        self._saved = list(self._archive)
        # The report has TWO independent inputs since cycle #163 (refusals and
        # guard-clobbers), so a test about one of them must pin the other —
        # otherwise it reads whatever the live run happened to record and the
        # "silent" case below fails for a reason it is not about. Isolation
        # only: not one assertion here is relaxed.
        self._clobbers = _live_net._CLOBBERS
        self._saved_clobbers = list(self._clobbers)

    def tearDown(self):
        self._archive[:] = self._saved
        self._clobbers[:] = self._saved_clobbers

    def _render(self, entries, clobbers=()):
        self._archive[:] = entries
        self._clobbers[:] = list(clobbers)
        reporter = _Reporter()
        self.summary(reporter, 0, None)
        return "\n".join(reporter.lines)

    def test_report_names_the_tests_and_totals_the_refusals(self):
        out = self._render(
            [("a.py::test_one", ["urlopen x", "urlopen y"]), ("b.py::test_two", ["connect z"])]
        )
        self.assertIn("a.py::test_one", out)
        self.assertIn("b.py::test_two", out)
        self.assertIn("3 refusal(s) from 2 test(s)", out)

    def test_report_is_silent_when_nothing_was_refused(self):
        self.assertEqual(self._render([]), "")

    def test_report_names_a_guard_clobber_even_with_no_refusals(self):
        """The clobber must be reported in the state where it actually occurs.

        A knocked-out guard records NOTHING, so an empty refusal ledger is the
        normal companion of a clobber — hanging this report off the refusals
        would hide it exactly when it matters (cycle #163).
        """
        out = self._render([], clobbers=[("x.py::test_x", "urlopen")])
        self.assertIn("RE-INSTALLED", out)
        self.assertIn("x.py::test_x", out)
        self.assertIn("urlopen", out)

    def test_report_says_how_many_tests_it_left_out(self):
        """No silent caps: a truncated list must not read as the whole list."""
        entries = [(f"t{i}.py::test_{i}", ["urlopen x"]) for i in range(25)]
        out = self._render(entries)
        self.assertIn("5 more test(s) not shown", out)
        self.assertIn("5 refusal(s) between them", out)


class TestTheFixtureIsWiredIn(unittest.TestCase):
    """Behaviour is pinned above; this pins the WIRING it depends on.

    The behavioural pin needs two tests in one module in the right order — a
    shape that is easy to break by accident (split the file, reorder, rename).
    Naming the fixture explicitly means a silent removal of the wiring cannot
    look like a harmless refactor.
    """

    def test_conftest_scopes_the_ledger_with_an_autouse_fixture(self):
        src = (_HERE / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("def _scope_network_guard_ledger", src)
        self.assertIn("network_guard.archive(request.node.nodeid)", src)

    def test_the_fixture_is_registered_for_every_test(self):
        conftest = _conftest_module()
        fixture = getattr(conftest, "_scope_network_guard_ledger", None)
        self.assertIsNotNone(fixture, "the scoping fixture is gone")
        # pytest ≥8 exposes the marker as ``_fixture_function_marker``; older
        # releases used ``_pytestfixturefunction``. Accept either, and fail
        # loudly rather than silently passing if a future release renames both.
        marker = getattr(fixture, "_fixture_function_marker", None) or getattr(
            fixture, "_pytestfixturefunction", None
        )
        self.assertIsNotNone(
            marker,
            "not a pytest fixture any more (or pytest renamed the marker "
            "attribute — check before assuming the former)",
        )
        self.assertTrue(marker.autouse, "fixture is no longer autouse")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
