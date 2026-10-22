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
        """``_origin_shelf_json`` with every git call that TALKS TO THE SERVER forced
        to fail — ``git show`` still runs for REAL against the local ref.

        Изменение сцены 22.10 (инв. #16 — названо, утверждения НЕ тронуты): с
        закреплением sha (ADR-361/362) вопрос к серверу задаёт ``ls-remote`` (через
        ``git -C <repo> …``), а не только ``fetch``. Прежняя подмена роняла лишь
        ``cmd[1] == "fetch"`` и при новой двери изображала бы НЕ «сеть отрезана», а
        «сервер ответил, добор не нужен» — то есть другую сцену. Отказ теперь
        ставится на ОБЕ двери к серверу, где бы ни стояла подкоманда после ``-C``.
        """
        real_run = subprocess.run

        def _sub(cmd):
            rest = list(cmd[1:])
            while rest and rest[0] in ("-C", "-c"):
                rest = rest[2:]
            return rest[0] if rest else None

        def _run(cmd, *a, **k):
            if len(cmd) >= 2 and cmd[0] == "git" and _sub(cmd) in ("fetch", "ls-remote"):
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


class TestOneServerValuePerRun(_OriginShelfFixture):
    """Сервер ушёл вперёд, кэш стоит на прошлом: читается ЗАКРЕПЛЁННОЕ значение, и обе
    витрины прогона судятся ОДНИМ sha, даже если сервер сдвинулся между ними."""

    def _advance(self, doc):
        other = Path(self._tmp.name) / "other"
        if not other.exists():
            _git(Path(self._tmp.name), "clone", str(Path(self._tmp.name) / "origin.git"), str(other))
            _git(other, "config", "user.email", "t@example.com")
            _git(other, "config", "user.name", "t")
        else:
            _git(other, "pull", "-q", "origin", "main")
        (other / SHELF_REL).write_text(json.dumps(doc), encoding="utf-8")
        _git(other, "commit", "-qam", "advance")
        _git(other, "push", "-q", "origin", "main")

    def test_a_stale_cache_is_not_read_the_server_value_is(self):
        newer = {"measured_at": "2026-10-02T00:00:00Z", "headline": {"v": 2}}
        self._advance(newer)
        # предпосылка: кэш стоит на прошлом и сам по себе ответил бы старым
        cached = _git(self.local, "show", f"origin/main:{SHELF_REL}").stdout
        self.assertEqual(json.loads(cached), self.SHELF_DOC)
        doc, leg = self.mod._origin_shelf_json(self.local, Path(SHELF_REL))
        self.assertEqual(leg, "measured")
        self.assertEqual(doc, newer)

    def test_both_shelves_of_one_run_are_read_by_one_sha(self):
        pin, note = self.mod.pin_origin_main(self.local)
        self.assertTrue(pin is not None and pin.ok, note)
        self._advance({"measured_at": "2026-10-03T00:00:00Z", "headline": {"v": 3}})
        doc, leg = self.mod._origin_shelf_json(self.local, Path(SHELF_REL), pinned=pin)
        self.assertEqual((leg, doc), ("measured", self.SHELF_DOC),
                         "сервер сдвинулся посреди прогона — читается названный sha")

    def test_an_unpinned_value_is_unmeasured_even_with_a_cache_on_disk(self):
        _git(self.local, "remote", "set-url", "origin", str(Path(self._tmp.name) / "gone.git"))
        self.assertEqual(json.loads(_git(self.local, "show", f"origin/main:{SHELF_REL}").stdout),
                         self.SHELF_DOC, "предпосылка: кэш лежит и читается")
        doc, leg = self.mod._origin_shelf_json(self.local, Path(SHELF_REL))
        self.assertIsNone(doc)
        self.assertTrue(leg.startswith("unmeasured:fetch_failed"), leg)


class TestThePinnedShaIsReadNotTheRefName(TestOneServerValuePerRun):
    """Кэш сдвинут ПОСЛЕ закрепления (чужой процесс, ADR-361): читается закреплённый sha,
    а не то, на что сейчас указывает имя `origin/main`."""

    def test_a_cache_moved_after_the_pin_is_not_read(self):
        old = _git(self.local, "rev-parse", "refs/remotes/origin/main").stdout.strip()
        newer = {"measured_at": "2026-10-04T00:00:00Z", "headline": {"v": 4}}
        self._advance(newer)
        pin, note = self.mod.pin_origin_main(self.local)
        self.assertTrue(pin is not None and pin.ok, note)
        _git(self.local, "update-ref", "refs/remotes/origin/main", old)
        doc, leg = self.mod._origin_shelf_json(self.local, Path(SHELF_REL), pinned=pin)
        self.assertEqual((leg, doc), ("measured", newer))
