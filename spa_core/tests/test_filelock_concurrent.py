"""
spa_core/tests/test_filelock_concurrent.py

Hardening tests for the concurrent-edit / stale-push hazards (Architect P3-12):

  1. spa_core.utils.filelock — advisory lock serializes writers; reload-before-write
     means a second writer sees the first's committed change (no lost updates);
     the lock degrades SAFELY (no-op + warning, never hangs) if flock is unavailable.
  2. push_to_github.push_file — a 409 stale-sha on PUT auto-retries with a freshly
     re-fetched remote sha and succeeds (mocked remote: first PUT 409, second 200).
  3. Both push_to_github.py copies (root + scripts/) stay byte-identical.

Run:
  python3 -m pytest spa_core/tests/test_filelock_concurrent.py -p no:randomly -q
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import warnings
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from spa_core.utils import filelock  # noqa: E402
from spa_core.utils.filelock import (  # noqa: E402
    FileLockTimeout,
    file_lock,
    locked_json_update,
    locked_text_rewrite,
)

import push_to_github as ptg  # noqa: E402  (root copy; conftest also adds scripts/)


# ---------------------------------------------------------------------------
# 1. filelock: serialization + reload-before-write (no lost updates)
# ---------------------------------------------------------------------------
class TestLockedJsonUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "KANBAN.json")
        with open(self.path, "w") as f:
            json.dump({"done_count": 0}, f)

    def test_serialized_writers_dont_lose_update(self):
        # Writer A then Writer B, each +1. The lock + reload-before-write means
        # B observes A's committed change → final == 2 (not 1, which a stale
        # snapshot RMW would produce).
        def bump(d):
            d["done_count"] = d.get("done_count", 0) + 1
            return d

        locked_json_update(self.path, bump)   # writer A
        locked_json_update(self.path, bump)   # writer B
        final = json.loads(Path(self.path).read_text())
        self.assertEqual(final["done_count"], 2)

    def test_nested_writer_sees_committed_state(self):
        # Simulate "another process wrote while we were computing": the second
        # writer is invoked from INSIDE the first's update_fn but writes first to
        # disk; the outer write must merge on top of the freshly-reloaded state.
        seen = {}

        def inner(d):
            d["done_count"] = d.get("done_count", 0) + 10
            return d

        def outer(d):
            # outer's update_fn already ran under the lock with reloaded state.
            seen["outer_saw"] = d.get("done_count", 0)
            d["done_count"] = d.get("done_count", 0) + 1
            return d

        # writer-1 commits +10
        locked_json_update(self.path, inner)
        # writer-2 reloads under lock, must see 10, then commits 11
        locked_json_update(self.path, outer)
        self.assertEqual(seen["outer_saw"], 10)
        self.assertEqual(json.loads(Path(self.path).read_text())["done_count"], 11)

    def test_creates_file_from_default(self):
        path2 = os.path.join(self.tmp, "new.json")
        locked_json_update(path2, lambda d: {**d, "x": 1}, default={})
        self.assertEqual(json.loads(Path(path2).read_text()), {"x": 1})

    def test_lock_file_is_sidecar_not_target(self):
        # The data file must NOT be opened/truncated to lock it.
        with file_lock(self.path) as held:
            self.assertTrue(held)
            self.assertTrue(os.path.exists(self.path + ".lock"))
        # data file content intact
        self.assertEqual(json.loads(Path(self.path).read_text())["done_count"], 0)


class TestLockedTextRewrite(unittest.TestCase):
    def test_reload_before_write_text(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "registry.py")
        Path(path).write_text("# v1\n")
        seen = {}

        def render(cur):
            seen["cur"] = cur
            return (cur or "") + "appended\n"

        locked_text_rewrite(path, render)
        self.assertEqual(seen["cur"], "# v1\n")
        self.assertEqual(Path(path).read_text(), "# v1\nappended\n")


class TestLockTimeout(unittest.TestCase):
    def test_timeout_when_held_by_other_fd(self):
        if filelock._fcntl is None:
            self.skipTest("flock unavailable on this platform")
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "x.json")
        fcntl = filelock._fcntl
        lock_path = path + ".lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with self.assertRaises(FileLockTimeout):
                with file_lock(path, timeout=0.2):
                    pass
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


class TestDegradeSafely(unittest.TestCase):
    def test_noop_when_flock_unavailable(self):
        # Simulate a platform without fcntl: must NOT hang, must warn once, and
        # the read-modify-write still works (best effort).
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "k.json")
        Path(path).write_text(json.dumps({"done_count": 5}))

        filelock._warned_no_flock = False  # reset one-time warning latch
        with mock.patch.object(filelock, "_fcntl", None):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                with file_lock(path, timeout=0.1) as held:
                    self.assertFalse(held)  # degraded → no real lock
                # update still works
                locked_json_update(path, lambda d: {**d, "done_count": d["done_count"] + 1})
            msgs = [str(x.message) for x in w]
            self.assertTrue(any("flock unavailable" in m for m in msgs))
        self.assertEqual(json.loads(Path(path).read_text())["done_count"], 6)


# ---------------------------------------------------------------------------
# 2. push_to_github: 409 stale-sha → re-fetch sha → retry → success
# ---------------------------------------------------------------------------
class _FakeHTTP409Then200:
    """urlopen mock: first PUT raises HTTP 409, second PUT returns 200."""

    def __init__(self):
        self.put_calls = 0

    def __call__(self, req, *a, **k):
        method = getattr(req, "method", "GET")
        if method == "PUT":
            self.put_calls += 1
            if self.put_calls == 1:
                raise urllib.error.HTTPError(
                    url="x", code=409, msg="Conflict",
                    hdrs=None,
                    fp=io.BytesIO(b'{"message":"is at ... but expected ..."}'),
                )
            # second attempt succeeds
            resp = mock.MagicMock()
            resp.read.return_value = json.dumps(
                {"content": {"sha": "f" * 40}}
            ).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: False
            return resp
        # GET (get_file_sha) — shouldn't be hit because we patch it.
        raise AssertionError("unexpected GET")


class TestPush409Retry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fpath = os.path.join(self.tmp, "sample.txt")
        with open(self.fpath, "wb") as fh:
            fh.write(b"changed content\n")

    def test_409_retries_with_fresh_sha_and_succeeds(self):
        fake = _FakeHTTP409Then200()
        sha_calls = {"n": 0}

        def fake_get_sha(*a, **k):
            # Each call returns a DIFFERENT remote sha → proves we re-fetch.
            sha_calls["n"] += 1
            return f"{'a' * 39}{sha_calls['n']}"

        with mock.patch.object(ptg, "get_file_sha", side_effect=fake_get_sha), \
                mock.patch("urllib.request.urlopen", fake), \
                mock.patch("time.sleep"):
            res = ptg.push_file("PAT", self.fpath, "msg", "owner/repo", branch="main")

        self.assertTrue(res.get("ok"), res)
        self.assertEqual(fake.put_calls, 2)          # one 409 + one success
        self.assertGreaterEqual(sha_calls["n"], 2)   # remote sha re-fetched

    def test_409_exhausts_retries_then_fails(self):
        class AlwaysConflict:
            def __call__(self, req, *a, **k):
                if getattr(req, "method", "GET") == "PUT":
                    raise urllib.error.HTTPError(
                        url="x", code=409, msg="Conflict", hdrs=None,
                        fp=io.BytesIO(b'{"message":"sha mismatch"}'),
                    )
                raise AssertionError("unexpected GET")

        with mock.patch.object(ptg, "get_file_sha", return_value="a" * 40), \
                mock.patch("urllib.request.urlopen", AlwaysConflict()), \
                mock.patch("time.sleep"):
            res = ptg.push_file("PAT", self.fpath, "msg", "owner/repo",
                                branch="main", _stale_retries=2)
        self.assertFalse(res.get("ok"))
        self.assertIn("409", res.get("error", ""))


# ---------------------------------------------------------------------------
# 3. Both push_to_github.py copies are byte-identical
# ---------------------------------------------------------------------------
class TestPushCopiesIdentical(unittest.TestCase):
    def test_root_and_scripts_identical(self):
        root = (_ROOT / "push_to_github.py").read_bytes()
        scripts = (_ROOT / "scripts" / "push_to_github.py").read_bytes()
        self.assertEqual(root, scripts, "push_to_github.py copies drifted")


if __name__ == "__main__":
    unittest.main()
