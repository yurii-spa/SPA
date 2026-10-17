"""Контроль памяти «один замер живого дерева на сессию» (`_live_census_memo`).

Память выдаёт ответ настоящего прибора, данный в этой же сессии, — значит она
обязана (1) промахиваться, как только изменился хоть один файл под корнем;
(2) отдавать независимые копии; (3) не брать ответ, зависящий от часов
(``now=None``); (4) не отдавать ответ одной функции другой — в том числе
подменённой на время теста. Каждое свойство — отдельный тест, и каждый
краснеет, если свойство снять.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.tests import _live_census_memo as memo

# FROZEN-DATE-OK: injected-clock — дата подаётся в `measure_once(..., now=)` как ключ, часы не читаются
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)


class _Counting:
    """Прибор-сцена: считает вызовы и отдаёт изменяемый документ о дереве."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, root, *, now=None):
        self.calls += 1
        files = sorted(p.name for p in Path(root).rglob("*") if p.is_file())
        return {"files": files, "nested": {"calls": self.calls},
                "now": None if now is None else now.isoformat()}


class LiveCensusMemo(unittest.TestCase):

    def setUp(self) -> None:
        memo.clear()
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_live_memo_")
        self.root = Path(self._tmp.name)
        (self.root / "a.py").write_text("A = 1\n", encoding="utf-8")
        self.fn = _Counting()

    def tearDown(self) -> None:
        memo.clear()
        self._tmp.cleanup()

    def test_same_tree_is_measured_once(self):
        first = memo.measure_once(self.fn, self.root, now=_NOW)
        second = memo.measure_once(self.fn, self.root, now=_NOW)
        self.assertEqual(self.fn.calls, 1)
        self.assertEqual(first, second)

    def test_a_changed_file_is_a_miss(self):
        memo.measure_once(self.fn, self.root, now=_NOW)
        path = self.root / "a.py"
        path.write_text("A = 22\n", encoding="utf-8")     # другой размер
        memo.measure_once(self.fn, self.root, now=_NOW)
        self.assertEqual(self.fn.calls, 2)
        # Тот же размер, другое время изменения — тоже промах.
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        memo.measure_once(self.fn, self.root, now=_NOW)
        self.assertEqual(self.fn.calls, 3)

    def test_a_new_file_is_a_miss_and_is_seen(self):
        memo.measure_once(self.fn, self.root, now=_NOW)
        (self.root / "b.py").write_text("B = 1\n", encoding="utf-8")
        doc = memo.measure_once(self.fn, self.root, now=_NOW)
        self.assertEqual(self.fn.calls, 2)
        self.assertIn("b.py", doc["files"])

    def test_bytecode_cache_is_not_an_input(self):
        memo.measure_once(self.fn, self.root, now=_NOW)
        cache = self.root / "__pycache__"
        cache.mkdir()
        (cache / "a.cpython-313.pyc").write_bytes(b"\0")
        memo.measure_once(self.fn, self.root, now=_NOW)
        self.assertEqual(self.fn.calls, 1)

    def test_copies_are_independent(self):
        first = memo.measure_once(self.fn, self.root, now=_NOW)
        first["files"].append("INJECTED")
        first["nested"]["calls"] = 999
        second = memo.measure_once(self.fn, self.root, now=_NOW)
        self.assertNotIn("INJECTED", second["files"])
        self.assertEqual(second["nested"]["calls"], 1)

    def test_no_clock_no_memo(self):
        memo.measure_once(self.fn, self.root)
        memo.measure_once(self.fn, self.root)
        self.assertEqual(self.fn.calls, 2)

    def test_a_different_moment_is_a_different_question(self):
        memo.measure_once(self.fn, self.root, now=_NOW)
        memo.measure_once(self.fn, self.root, now=_NOW + dt.timedelta(days=1))
        self.assertEqual(self.fn.calls, 2)

    def test_a_substituted_function_does_not_get_the_real_answer(self):
        memo.measure_once(self.fn, self.root, now=_NOW)
        other = _Counting()
        memo.measure_once(other, self.root, now=_NOW)
        self.assertEqual((self.fn.calls, other.calls), (1, 1))

    def test_fingerprint_names_every_file_under_the_root(self):
        (self.root / "sub").mkdir()
        (self.root / "sub" / "c.json").write_text("{}", encoding="utf-8")
        paths = {Path(p).name for p, _m, _s in memo.tree_fingerprint(self.root)}
        self.assertEqual(paths, {"a.py", "c.json"})

    def test_fingerprint_sees_the_live_tree(self):
        """На живом дереве отпечаток непуст — иначе любой замер был бы «тем же»."""
        root = Path(__file__).resolve().parents[2]
        prints = memo.tree_fingerprint(root)
        self.assertGreater(len(prints), 1000)
        self.assertFalse(any("/.git/" in p for p, _m, _s in prints))

if __name__ == "__main__":
    unittest.main()
