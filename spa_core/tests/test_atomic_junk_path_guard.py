"""
spa_core/tests/test_atomic_junk_path_guard.py — regression guard for the 'junk file in repo root'
bug (memory: analyzer-object-path-junk-files).

Several analytics modules build their output path as ``str(self._data_file)`` where
``self._data_file`` came from a constructor positional. If that positional is accidentally a
NON-STRING (a list-of-dicts, an object, ``self``), ``str(...)`` produces a Python repr like
``"[{'i': 0}]"`` or ``"<...object at 0x...>"`` — a bare filename with no directory — and the
write lands a junk file in the CWD (the repo root). This has polluted the tree with hundreds of
junk files before.

These tests assert the write path is now fail-CLOSED: constructing/writing with a bad arg RAISES
rather than creating a junk file. stdlib-only, deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import unittest

from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_save, atomic_save_text


class _JunkBefore:
    """Snapshot the CWD listing so a test can assert NO junk file was created."""

    def __init__(self) -> None:
        self.before = set(os.listdir("."))

    def new_files(self) -> set:
        return set(os.listdir(".")) - self.before


class TestAtomicSaveRejectsJunkPath(unittest.TestCase):
    def test_list_of_dicts_repr_path_raises(self) -> None:
        """The exact observed junk: str([{'i': 0}]) → '[{...}]' must be refused."""
        snap = _JunkBefore()
        bad = str([{"i": 0}, {"i": 1}])  # "[{'i': 0}, {'i': 1}]"
        with self.assertRaises(ValueError):
            atomic_save({"x": 1}, bad)
        self.assertEqual(snap.new_files(), set(), "a junk file was created in the repo root")

    def test_object_repr_path_raises(self) -> None:
        snap = _JunkBefore()
        bad = f"<spa_core.analytics.Foo object at 0x{id(self):x}>"
        with self.assertRaises(ValueError):
            atomic_save({"x": 1}, bad)
        self.assertEqual(snap.new_files(), set())

    def test_non_string_path_raises(self) -> None:
        snap = _JunkBefore()
        with self.assertRaises(ValueError):
            atomic_save({"x": 1}, [{"i": 0}])  # a real non-string passed straight through
        self.assertEqual(snap.new_files(), set())

    def test_atomic_save_text_rejects_junk(self) -> None:
        snap = _JunkBefore()
        with self.assertRaises(ValueError):
            atomic_save_text("hi", "[{'i': 0}]")
        self.assertEqual(snap.new_files(), set())

    def test_good_path_still_writes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "ok.json")
            atomic_save({"x": 1}, good)
            self.assertTrue(os.path.exists(good))


class TestBaseAnalyticsRejectsNonStringDir(unittest.TestCase):
    def test_non_string_data_dir_raises(self) -> None:
        snap = _JunkBefore()
        with self.assertRaises(TypeError):
            BaseAnalytics([{"i": 0}, {"i": 1}])  # type: ignore[arg-type]
        self.assertEqual(snap.new_files(), set())

    def test_object_data_dir_raises(self) -> None:
        snap = _JunkBefore()

        class _Obj:
            pass

        with self.assertRaises(TypeError):
            BaseAnalytics(_Obj())  # type: ignore[arg-type]
        self.assertEqual(snap.new_files(), set())

    def test_good_string_dir_ok(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            inst = BaseAnalytics(d)
            self.assertTrue(os.path.isdir(d))
            self.assertEqual(inst.save({"a": 1}, filename="t.json"), True)


if __name__ == "__main__":
    unittest.main()
