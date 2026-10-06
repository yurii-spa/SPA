"""F14 (integration review, 2026-10-05): ``_origin_shelf_json``'s ``fetch`` is
best-effort BY DESIGN (``make_fresh_checkout`` does the same) — but "best-effort"
must not mean "a failed fetch is silently invisible". Before this fix, when
``fetch`` failed (network/auth), ``git show origin/main:<rel>`` could still
succeed against whatever the LOCAL ``origin/main`` ref already pointed to (the
last successful fetch, possibly long stale) — and that success was reported as
``"measured"``. The prod tree's local ref lags origin by design (CLAUDE.md §1),
so this is exactly the scene where the gap is quietest: a confident "measured"
built on a ref this run never actually confirmed.

Real git throughout (no stand-in git), only the ``fetch`` subprocess call is
forced to fail — the same ``mock.patch.object(self.mod.subprocess, "run", ...)``
pattern as ``test_site_custodian_fresh_checkout.py``, so the positive control is
real: strip the fix and this test goes red because the stale `git show` succeeds
and gets labelled "measured".
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

# FROZEN-DATE-OK: opaque-payload — "measured_at": "2026-10-01T00:00:00Z" below is
# JSON content that `_origin_shelf_json` passes through untouched (it reports
# whether `git fetch`/`git show` succeeded, not whether the shelf is stale); the
# only assertion on it is byte-for-byte dict equality (`doc == self.SHELF_DOC`).
# No function on this test's call path (`_origin_shelf_json`) reads this field to
# compare it against now/wall-clock — that comparison lives elsewhere in
# site_freshness_monitor.py, in code this file never calls.
_REPO = Path(__file__).resolve().parents[2]
SHELF_REL = "landing/src/data/site_numbers.json"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(_REPO / rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True)


class _OriginShelfFixture(unittest.TestCase):
    """A real origin + a real local clone whose ``origin/main`` already has the
    shelf file from a PRIOR successful fetch — the stale-ref scene."""

    SHELF_DOC = {"measured_at": "2026-10-01T00:00:00Z", "headline": {}}

    def setUp(self):
        self.mod = _load("site_freshness_monitor_f14", "scripts/site_freshness_monitor.py")
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        origin = root / "origin.git"
        _git(root, "init", "--bare", "-b", "main", str(origin))

        self.local = root / "local"
        _git(root, "clone", str(origin), str(self.local))
        _git(self.local, "config", "user.email", "t@example.com")
        _git(self.local, "config", "user.name", "t")

        shelf = self.local / SHELF_REL
        shelf.parent.mkdir(parents=True)
        shelf.write_text(json.dumps(self.SHELF_DOC), encoding="utf-8")
        _git(self.local, "add", "-A")
        _git(self.local, "commit", "-m", "shelf")
        _git(self.local, "push", "origin", "main")
        # The local clone's own `origin/main` remote ref now has the shelf — the
        # SAME mechanism that leaves a prod tree's ref pointing at an old commit
        # even when nothing has fetched in a while.
        _git(self.local, "fetch", "origin", "main")

    def _call_with_fetch_failing(self):
        """``_origin_shelf_json`` with ONLY its ``fetch`` subprocess call forced
        to fail — ``git show`` still runs for REAL against the local ref."""
        real_run = subprocess.run

        def _run(cmd, *a, **k):
            if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "fetch":
                return mock.Mock(returncode=128, stdout="",
                                  stderr="fatal: unable to access origin (simulated)")
            return real_run(cmd, *a, **k)

        with mock.patch.object(self.mod.subprocess, "run", _run):
            return self.mod._origin_shelf_json(self.local, Path(SHELF_REL))


class TestFetchFailureIsNamedNotMeasured(_OriginShelfFixture):
    """Положительный контроль: снимите фикс — тест покраснеет, потому что
    `git show` против старого локального ref молча назовётся «measured»."""

    def test_a_failed_fetch_never_reports_measured(self):
        doc, leg = self._call_with_fetch_failing()
        self.assertIsNone(doc)
        self.assertNotEqual(leg, "measured")
        self.assertTrue(leg.startswith("unmeasured:fetch_failed"), leg)

    def test_a_successful_fetch_still_reports_measured(self):
        """Positive control for the control above: the SAME local ref, with a
        fetch that actually succeeds, must still report "measured" — the fix
        names the failure, it does not make every read unmeasured."""
        doc, leg = self.mod._origin_shelf_json(self.local, Path(SHELF_REL))
        self.assertEqual(leg, "measured")
        self.assertEqual(doc, self.SHELF_DOC)
