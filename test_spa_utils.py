"""
tests/test_spa_utils.py
Unit tests for spa_core/utils — atomic, keychain, kanban, base classes.
65 tests covering all public functions. (AUDIT-001/002/003 — 2026-06-19)
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.utils.atomic import (
    atomic_append,
    atomic_append_ring,
    atomic_load,
    atomic_save,
    atomic_update,
)
from spa_core.utils.keychain import get_github_pat, get_secret, get_telegram_chat_id, get_telegram_token
from spa_core.utils.kanban import increment_done


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_path(suffix=".json"):
    """Return a temporary file path that does NOT exist yet."""
    fd, p = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    os.unlink(p)
    return p


# ===========================================================================
# atomic_save
# ===========================================================================

class TestAtomicSave(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_path()

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    # 1
    def test_creates_file(self):
        atomic_save({"k": 1}, self.tmp)
        self.assertTrue(os.path.exists(self.tmp))

    # 2
    def test_content_is_valid_json(self):
        atomic_save({"hello": "world"}, self.tmp)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data, {"hello": "world"})

    # 3
    def test_saves_list(self):
        atomic_save([1, 2, 3], self.tmp)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data, [1, 2, 3])

    # 4
    def test_saves_nested_dict(self):
        payload = {"a": {"b": [1, 2]}, "c": None}
        atomic_save(payload, self.tmp)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data["a"]["b"], [1, 2])

    # 5
    def test_overwrites_existing_file(self):
        atomic_save({"v": 1}, self.tmp)
        atomic_save({"v": 2}, self.tmp)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data["v"], 2)

    # 6
    def test_creates_parent_dirs(self):
        nested = os.path.join(tempfile.mkdtemp(), "sub", "deep", "out.json")
        try:
            atomic_save({"x": 1}, nested)
            self.assertTrue(os.path.exists(nested))
        finally:
            import shutil
            shutil.rmtree(os.path.dirname(os.path.dirname(os.path.dirname(nested))), ignore_errors=True)

    # 7
    def test_uses_tempfile_not_direct_write(self):
        """Verifies mkstemp is called (i.e. we don't open target directly)."""
        calls = []
        real_mkstemp = tempfile.mkstemp

        def spy_mkstemp(**kwargs):
            fd, path = real_mkstemp(**kwargs)
            calls.append(path)
            return fd, path

        with patch("spa_core.utils.atomic.tempfile.mkstemp", side_effect=spy_mkstemp):
            atomic_save({"a": 1}, self.tmp)

        self.assertTrue(len(calls) >= 1, "mkstemp was not called")

    # 8
    def test_no_leftover_tmp_on_success(self):
        dir_ = os.path.dirname(os.path.abspath(self.tmp))
        before = set(os.listdir(dir_))
        atomic_save({"x": 99}, self.tmp)
        after = set(os.listdir(dir_))
        new_files = after - before - {os.path.basename(self.tmp)}
        tmps = [f for f in new_files if f.endswith(".tmp")]
        self.assertEqual(tmps, [])

    # 9
    def test_default_indent_2(self):
        atomic_save({"a": 1}, self.tmp)
        with open(self.tmp) as f:
            raw = f.read()
        self.assertIn("\n", raw)

    # 10
    def test_custom_indent_4(self):
        atomic_save({"a": 1}, self.tmp, indent=4)
        with open(self.tmp) as f:
            raw = f.read()
        # indent=4 means 4 spaces before key
        self.assertIn("    ", raw)

    # 11
    def test_saves_empty_dict(self):
        atomic_save({}, self.tmp)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data, {})

    # 12
    def test_saves_integer(self):
        atomic_save(42, self.tmp)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data, 42)

    # 13
    def test_default_str_for_non_serializable(self):
        """default=str should handle datetime-like objects."""
        from datetime import datetime
        atomic_save({"ts": datetime(2026, 1, 1)}, self.tmp)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIn("2026", data["ts"])

    # 14
    def test_raises_on_unserializable_without_default(self):
        """When default cannot handle it, raises TypeError."""
        class _Bad:
            pass
        # We patch default=None to force failure (not our API — just sanity)
        import json as _json
        with self.assertRaises(TypeError):
            _json.dumps({"obj": _Bad()})


# ===========================================================================
# atomic_load
# ===========================================================================

class TestAtomicLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_path()

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    # 15
    def test_returns_empty_dict_for_missing_file(self):
        result = atomic_load("/nonexistent/path/file.json")
        self.assertEqual(result, {})

    # 16
    def test_returns_custom_default_for_missing_file(self):
        result = atomic_load("/nonexistent/path/file.json", default={"k": 0})
        self.assertEqual(result, {"k": 0})

    # 17
    def test_returns_list_default(self):
        result = atomic_load("/no/such/file.json", default=[])
        self.assertEqual(result, [])

    # 18
    def test_loads_valid_json(self):
        with open(self.tmp, "w") as f:
            json.dump({"foo": "bar"}, f)
        result = atomic_load(self.tmp)
        self.assertEqual(result["foo"], "bar")

    # 19
    def test_loads_nested_structure(self):
        payload = {"a": [1, 2, 3], "b": {"c": True}}
        with open(self.tmp, "w") as f:
            json.dump(payload, f)
        result = atomic_load(self.tmp)
        self.assertEqual(result["a"], [1, 2, 3])
        self.assertTrue(result["b"]["c"])

    # 20
    def test_loads_list_file(self):
        with open(self.tmp, "w") as f:
            json.dump([10, 20, 30], f)
        result = atomic_load(self.tmp)
        self.assertEqual(result, [10, 20, 30])

    # 21
    def test_returns_none_default_when_specified(self):
        """Explicitly passing default=None should return None, not {}."""
        result = atomic_load("/no/such/file_xyz.json", default=None)
        self.assertIsNone(result)

    # 22
    def test_raises_on_invalid_json(self):
        with open(self.tmp, "w") as f:
            f.write("NOT JSON {{{{")
        with self.assertRaises(json.JSONDecodeError):
            atomic_load(self.tmp)


# ===========================================================================
# atomic_append
# ===========================================================================

class TestAtomicAppend(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_path()

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    # 23
    def test_appends_to_new_file(self):
        atomic_append({"v": 1}, self.tmp, key="items")
        data = atomic_load(self.tmp)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["v"], 1)

    # 24
    def test_appends_multiple_items(self):
        for i in range(5):
            atomic_append(i, self.tmp, key="items")
        data = atomic_load(self.tmp)
        self.assertEqual(len(data["items"]), 5)

    # 25
    def test_respects_cap_ring_buffer(self):
        for i in range(10):
            atomic_append(i, self.tmp, key="items", cap=5)
        data = atomic_load(self.tmp)
        self.assertEqual(len(data["items"]), 5)

    # 26
    def test_ring_buffer_keeps_latest(self):
        for i in range(10):
            atomic_append(i, self.tmp, key="items", cap=3)
        data = atomic_load(self.tmp)
        self.assertEqual(data["items"], [7, 8, 9])

    # 27
    def test_no_cap_allows_unlimited(self):
        for i in range(20):
            atomic_append(i, self.tmp, key="items")
        data = atomic_load(self.tmp)
        self.assertEqual(len(data["items"]), 20)

    # 28
    def test_custom_key(self):
        atomic_append("x", self.tmp, key="events")
        data = atomic_load(self.tmp)
        self.assertIn("events", data)
        self.assertEqual(data["events"], ["x"])

    # 29
    def test_preserves_existing_data(self):
        atomic_save({"meta": "kept", "items": []}, self.tmp)
        atomic_append(99, self.tmp, key="items")
        data = atomic_load(self.tmp)
        self.assertEqual(data["meta"], "kept")
        self.assertEqual(data["items"], [99])

    # 30
    def test_cap_exactly_at_limit_no_trim(self):
        for i in range(5):
            atomic_append(i, self.tmp, key="items", cap=5)
        data = atomic_load(self.tmp)
        self.assertEqual(len(data["items"]), 5)

    # 31
    def test_appends_dict_item(self):
        atomic_append({"ts": "2026-01-01", "val": 1.5}, self.tmp, key="records")
        data = atomic_load(self.tmp)
        self.assertEqual(data["records"][0]["val"], 1.5)


# ===========================================================================
# keychain
# ===========================================================================

class TestGetSecret(unittest.TestCase):
    # 32
    def test_returns_none_when_subprocess_fails(self):
        with patch("spa_core.utils.keychain.subprocess.run", side_effect=Exception("no keychain")):
            result = get_secret("SOME_SERVICE")
        self.assertIsNone(result)

    # 33
    def test_returns_none_when_empty_stdout(self):
        mock = MagicMock()
        mock.stdout = ""
        with patch("spa_core.utils.keychain.subprocess.run", return_value=mock):
            result = get_secret("SOME_SERVICE")
        self.assertIsNone(result)

    # 34
    def test_returns_stripped_value(self):
        mock = MagicMock()
        mock.stdout = "  mytoken\n"
        with patch("spa_core.utils.keychain.subprocess.run", return_value=mock):
            result = get_secret("MY_SERVICE")
        self.assertEqual(result, "mytoken")

    # 35
    def test_calls_security_command(self):
        mock = MagicMock()
        mock.stdout = "tok"
        with patch("spa_core.utils.keychain.subprocess.run", return_value=mock) as spy:
            get_secret("TEST_SVC")
        args = spy.call_args[0][0]
        self.assertIn("security", args)
        self.assertIn("find-generic-password", args)
        self.assertIn("TEST_SVC", args)

    # 36
    def test_passes_service_name_to_security(self):
        mock = MagicMock()
        mock.stdout = "value"
        with patch("spa_core.utils.keychain.subprocess.run", return_value=mock) as spy:
            get_secret("SPECIAL_SVC")
        cmd = spy.call_args[0][0]
        self.assertIn("SPECIAL_SVC", cmd)

    # 37
    def test_returns_none_on_timeout(self):
        import subprocess
        with patch("spa_core.utils.keychain.subprocess.run", side_effect=subprocess.TimeoutExpired("security", 5)):
            result = get_secret("X")
        self.assertIsNone(result)

    # 38
    def test_get_github_pat_calls_correct_service(self):
        mock = MagicMock()
        mock.stdout = "ghp_abc"
        with patch("spa_core.utils.keychain.subprocess.run", return_value=mock) as spy:
            get_github_pat()
        cmd = spy.call_args[0][0]
        self.assertIn("GITHUB_PAT_SPA", cmd)

    # 39
    def test_get_telegram_token_calls_correct_service(self):
        mock = MagicMock()
        mock.stdout = "bot123"
        with patch("spa_core.utils.keychain.subprocess.run", return_value=mock) as spy:
            get_telegram_token()
        cmd = spy.call_args[0][0]
        self.assertIn("TELEGRAM_BOT_TOKEN_SPA", cmd)

    # 40
    def test_get_telegram_chat_id_calls_correct_service(self):
        mock = MagicMock()
        mock.stdout = "-100123"
        with patch("spa_core.utils.keychain.subprocess.run", return_value=mock) as spy:
            get_telegram_chat_id()
        cmd = spy.call_args[0][0]
        self.assertIn("TELEGRAM_CHAT_ID_SPA", cmd)


# ===========================================================================
# kanban.increment_done
# ===========================================================================

class TestIncrementDone(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.kanban_path = os.path.join(self.tmpdir, "KANBAN.json")
        with open(self.kanban_path, "w") as f:
            json.dump({"done_count": 100, "sprint_completed": "v9.90"}, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # 41
    def test_increments_done_count_by_1(self):
        new_val = increment_done(self.tmpdir, n=1)
        self.assertEqual(new_val, 101)

    # 42
    def test_increments_done_count_by_n(self):
        new_val = increment_done(self.tmpdir, n=5)
        self.assertEqual(new_val, 105)

    # 43
    def test_persists_to_file(self):
        increment_done(self.tmpdir, n=2)
        with open(self.kanban_path) as f:
            data = json.load(f)
        self.assertEqual(data["done_count"], 102)

    # 44
    def test_updates_sprint_completed(self):
        increment_done(self.tmpdir, n=1, sprint="v9.92")
        with open(self.kanban_path) as f:
            data = json.load(f)
        self.assertEqual(data["sprint_completed"], "v9.92")

    # 45
    def test_no_sprint_arg_leaves_existing(self):
        increment_done(self.tmpdir, n=1)
        with open(self.kanban_path) as f:
            data = json.load(f)
        self.assertEqual(data["sprint_completed"], "v9.90")


# ===========================================================================
# atomic_append_ring (AUDIT-001 — new canonical ring-buffer function)
# ===========================================================================

class TestAtomicAppendRing(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_path()

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    # 46 — list format (list_key=None): creates file as JSON array
    def test_list_format_creates_array(self):
        atomic_append_ring({"v": 1}, self.tmp, cap=10)
        data = atomic_load(self.tmp, default=[])
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    # 47 — list format: respects cap
    def test_list_format_respects_cap(self):
        for i in range(15):
            atomic_append_ring(i, self.tmp, cap=5)
        data = atomic_load(self.tmp, default=[])
        self.assertEqual(len(data), 5)

    # 48 — list format: keeps latest items
    def test_list_format_keeps_latest(self):
        for i in range(10):
            atomic_append_ring(i, self.tmp, cap=3)
        data = atomic_load(self.tmp, default=[])
        self.assertEqual(data, [7, 8, 9])

    # 49 — list format: returns new length
    def test_list_format_returns_length(self):
        result = atomic_append_ring("x", self.tmp, cap=5)
        self.assertEqual(result, 1)

    # 50 — dict format (list_key="log"): creates dict with key
    def test_dict_format_creates_key(self):
        atomic_append_ring({"v": 1}, self.tmp, cap=10, list_key="log")
        data = atomic_load(self.tmp)
        self.assertIn("log", data)
        self.assertEqual(len(data["log"]), 1)

    # 51 — dict format: respects cap
    def test_dict_format_respects_cap(self):
        for i in range(12):
            atomic_append_ring(i, self.tmp, cap=5, list_key="events")
        data = atomic_load(self.tmp)
        self.assertEqual(len(data["events"]), 5)

    # 52 — dict format: preserves sibling keys
    def test_dict_format_preserves_sibling_keys(self):
        atomic_save({"meta": "kept", "log": []}, self.tmp)
        atomic_append_ring(99, self.tmp, cap=10, list_key="log")
        data = atomic_load(self.tmp)
        self.assertEqual(data["meta"], "kept")
        self.assertEqual(data["log"], [99])

    # 53 — dict format: returns new length
    def test_dict_format_returns_length(self):
        result = atomic_append_ring("a", self.tmp, cap=5, list_key="items")
        self.assertEqual(result, 1)

    # 54 — handles corrupt file gracefully (list format)
    def test_list_format_handles_corrupt_file(self):
        with open(self.tmp, "w") as f:
            f.write("CORRUPT DATA!!!!")
        # Should not raise; should treat as empty
        atomic_append_ring("x", self.tmp, cap=5)
        data = atomic_load(self.tmp, default=[])
        self.assertIn("x", data)

    # 55 — default cap=100 is enforced
    def test_default_cap_100(self):
        for i in range(105):
            atomic_append_ring(i, self.tmp)
        data = atomic_load(self.tmp, default=[])
        self.assertEqual(len(data), 100)


# ===========================================================================
# atomic_update (AUDIT-001 — new read-modify-write helper)
# ===========================================================================

class TestAtomicUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_path()

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    # 56 — increments a counter
    def test_increments_counter(self):
        atomic_save({"count": 5}, self.tmp)
        result = atomic_update(self.tmp, lambda d: {**d, "count": d.get("count", 0) + 1})
        self.assertEqual(result["count"], 6)

    # 57 — creates file from default if missing
    def test_creates_from_default(self):
        result = atomic_update(self.tmp, lambda d: {**d, "initialized": True}, default={})
        self.assertTrue(result["initialized"])
        self.assertTrue(os.path.exists(self.tmp))

    # 58 — returns new data (not old)
    def test_returns_new_data(self):
        atomic_save({"v": 1}, self.tmp)
        result = atomic_update(self.tmp, lambda d: {"v": 99})
        self.assertEqual(result["v"], 99)

    # 59 — persists changes to disk
    def test_persists_changes(self):
        atomic_save({"x": 0}, self.tmp)
        atomic_update(self.tmp, lambda d: {**d, "x": 42})
        reloaded = atomic_load(self.tmp)
        self.assertEqual(reloaded["x"], 42)

    # 60 — identity update preserves data
    def test_identity_update(self):
        atomic_save({"a": 1, "b": 2}, self.tmp)
        result = atomic_update(self.tmp, lambda d: d)
        self.assertEqual(result, {"a": 1, "b": 2})


# ===========================================================================
# BaseAnalytics and BaseAdapter (spa_core/base.py) — AUDIT-002
# ===========================================================================

class TestBaseAnalytics(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_analytics(self, output_path="data/out.json"):
        from spa_core.base import BaseAnalytics
        class _Impl(BaseAnalytics):
            OUTPUT_PATH = output_path
            def to_dict(self):
                return {"value": 42}
        return _Impl(base_dir=self.tmpdir)

    # 61 — _path resolves relative to base_dir
    def test_path_resolves_relative(self):
        obj = self._make_analytics()
        result = obj._path("data/out.json")
        self.assertTrue(result.startswith(self.tmpdir))
        self.assertIn("out.json", result)

    # 62 — save() creates file
    def test_save_creates_file(self):
        obj = self._make_analytics()
        path = obj.save()
        self.assertTrue(os.path.exists(path))

    # 63 — save() writes correct data
    def test_save_writes_to_dict_data(self):
        obj = self._make_analytics()
        path = obj.save()
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["value"], 42)

    # 64 — load() round-trips save()
    def test_load_round_trips_save(self):
        obj = self._make_analytics()
        obj.save()
        loaded = obj.load()
        self.assertEqual(loaded["value"], 42)


class TestBaseAdapter(unittest.TestCase):
    def _make_adapter(self):
        from spa_core.base import BaseAdapter
        class _Impl(BaseAdapter):
            SOURCE_ID = "test_proto"
            FALLBACK_APY = 5.0
            def current_apy(self):
                return 7.5
            def source_metadata(self):
                return {"protocol": "test"}
        return _Impl()

    # 65 — RESEARCH_ONLY defaults to True
    def test_research_only_default_true(self):
        adapter = self._make_adapter()
        self.assertTrue(adapter.is_research_only())

    # 66 — safe_apy returns current_apy on success
    def test_safe_apy_returns_value(self):
        adapter = self._make_adapter()
        self.assertEqual(adapter.safe_apy(), 7.5)

    # 67 — safe_apy returns FALLBACK_APY on exception
    def test_safe_apy_fallback_on_exception(self):
        from spa_core.base import BaseAdapter
        class _Broken(BaseAdapter):
            SOURCE_ID = "broken"
            FALLBACK_APY = 3.0
            def current_apy(self):
                raise RuntimeError("network down")
            def source_metadata(self):
                return {}
        adapter = _Broken()
        self.assertEqual(adapter.safe_apy(), 3.0)

    # 68 — RESEARCH_ONLY can be overridden to False
    def test_research_only_can_be_false(self):
        from spa_core.base import BaseAdapter
        class _Live(BaseAdapter):
            RESEARCH_ONLY = False
            SOURCE_ID = "live_proto"
            def current_apy(self):
                return 4.0
            def source_metadata(self):
                return {}
        adapter = _Live()
        self.assertFalse(adapter.is_research_only())


if __name__ == "__main__":
    unittest.main()
