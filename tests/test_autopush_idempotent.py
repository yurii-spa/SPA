"""
tests/test_autopush_idempotent.py

Guard tests for the autopush idempotency fix (Architect task T3).

ROOT CAUSE these tests pin down: each push_v*.sh called push_to_github.py with a
list of files; push_to_github.py PUT each file via the GitHub Contents API with
the SAME commit message. The Contents API creates ONE commit per PUT — and it
creates a commit EVEN when the uploaded content is byte-identical to what is
already on remote (a no-op / empty-diff commit). Result: a single push of N
files produced N near-identical commits, and re-running an unchanged push
produced empty no-op commits → 40x / 20x duplicate-message spam in git history.

FIX under test: before PUTting, compare the LOCAL git-blob-SHA of the file
against the remote file's `sha` (the Contents API `sha` IS the git blob SHA-1).
If they match → skip the PUT entirely (zero commits). Fail-CLOSED: any
uncertainty (remote sha unavailable / new file) → push as normal so real
changes are never dropped.

The remote (GitHub Contents API) is fully MOCKED — no network, no real pushes.

Run: python3 -m unittest tests/test_autopush_idempotent.py -v
"""

import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# conftest adds root + scripts to sys.path; import the root copy explicitly.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import push_to_github as ptg  # root copy


class TestGitBlobSha(unittest.TestCase):
    """git_blob_sha must equal git's own hash-object (== Contents API `sha`)."""

    def test_matches_git_hash_object(self):
        content = b"hello world\n"
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
            fh.write(content)
            path = fh.name
        try:
            expected = subprocess.run(
                ["git", "hash-object", path],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        finally:
            os.unlink(path)
        self.assertEqual(ptg.git_blob_sha(content), expected)

    def test_empty_file(self):
        # git hash-object of empty content is a well-known constant.
        self.assertEqual(
            ptg.git_blob_sha(b""),
            "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
        )

    def test_deterministic(self):
        c = b"some deterministic payload \x00\xff"
        self.assertEqual(ptg.git_blob_sha(c), ptg.git_blob_sha(c))


class TestPushFileIdempotency(unittest.TestCase):
    """push_file must skip unchanged files (no PUT) and push changed ones."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fpath = os.path.join(self.tmpdir, "sample.txt")
        with open(self.fpath, "wb") as fh:
            fh.write(b"current content\n")
        self.local_sha = ptg.git_blob_sha(b"current content\n")

    def _patch_remote(self, remote_sha):
        """Patch get_file_sha to return a fixed remote sha (mocked remote)."""
        return mock.patch.object(ptg, "get_file_sha", return_value=remote_sha)

    def _spy_put(self):
        """Patch urllib.request.urlopen so any PUT would be detected/fail loudly."""
        return mock.patch("urllib.request.urlopen")

    def test_skip_when_remote_identical(self):
        # Remote already has the exact same content → SKIP, no PUT, no commit.
        with self._patch_remote(self.local_sha), self._spy_put() as urlopen:
            r = ptg.push_file(
                pat="fake", local_path=self.fpath, message="msg",
                repo="owner/repo", dry_run=False, branch="main",
            )
        self.assertTrue(r["ok"])
        self.assertTrue(r.get("skipped"))
        # The critical assertion: urlopen (the PUT) was NEVER called.
        urlopen.assert_not_called()

    def test_push_when_remote_differs(self):
        # Remote has a different sha → must PUT (one real commit).
        fake_put_response = mock.MagicMock()
        fake_put_response.read.return_value = (
            b'{"content": {"sha": "abcdef1234567890"}}'
        )
        fake_put_response.__enter__ = lambda s: s
        fake_put_response.__exit__ = lambda *a: False
        with self._patch_remote("deadbeef" * 5), \
                mock.patch("urllib.request.urlopen", return_value=fake_put_response) as urlopen:
            r = ptg.push_file(
                pat="fake", local_path=self.fpath, message="msg",
                repo="owner/repo", dry_run=False, branch="main",
            )
        self.assertTrue(r["ok"])
        self.assertFalse(r.get("skipped"))
        urlopen.assert_called_once()  # exactly one PUT → one commit

    def test_fail_closed_when_remote_sha_unknown(self):
        # New file / network hiccup → get_file_sha returns None → MUST push,
        # never silently skip (fail-CLOSED preserves real changes).
        fake_put_response = mock.MagicMock()
        fake_put_response.read.return_value = (
            b'{"content": {"sha": "1111111111111111"}}'
        )
        fake_put_response.__enter__ = lambda s: s
        fake_put_response.__exit__ = lambda *a: False
        with self._patch_remote(None), \
                mock.patch("urllib.request.urlopen", return_value=fake_put_response) as urlopen:
            r = ptg.push_file(
                pat="fake", local_path=self.fpath, message="msg",
                repo="owner/repo", dry_run=False, branch="main",
            )
        self.assertTrue(r["ok"])
        self.assertFalse(r.get("skipped"))
        urlopen.assert_called_once()

    def test_dry_run_reports_skip_when_identical(self):
        with self._patch_remote(self.local_sha):
            r = ptg.push_file(
                pat="fake", local_path=self.fpath, message="msg",
                repo="owner/repo", dry_run=True, branch="main",
            )
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "skip")

    def test_dry_run_reports_update_when_differs(self):
        with self._patch_remote("ffffffff" * 5):
            r = ptg.push_file(
                pat="fake", local_path=self.fpath, message="msg",
                repo="owner/repo", dry_run=True, branch="main",
            )
        self.assertTrue(r["ok"])
        self.assertEqual(r["action"], "update")


class TestCopiesInSync(unittest.TestCase):
    """Both push_to_github.py copies (root + scripts/) must stay byte-identical."""

    def test_root_and_scripts_identical(self):
        root = (_ROOT / "push_to_github.py").read_bytes()
        scripts = (_ROOT / "scripts" / "push_to_github.py").read_bytes()
        self.assertEqual(
            root, scripts,
            "push_to_github.py root and scripts/ copies have drifted — "
            "the idempotency fix must live in BOTH.",
        )

    def test_both_have_git_blob_sha(self):
        for rel in ("push_to_github.py", "scripts/push_to_github.py"):
            txt = (_ROOT / rel).read_text()
            self.assertIn("def git_blob_sha", txt, f"{rel} missing git_blob_sha")
            self.assertIn("git_blob_sha(local_bytes)", txt,
                          f"{rel} missing idempotency skip guard")


if __name__ == "__main__":
    unittest.main(verbosity=2)
