"""
tests/test_spa_base.py
Unit tests for spa_core/base.py — BaseAnalytics, BaseAdapter, BaseReport.
40 tests covering abstract class enforcement, save/load delegation,
path resolution, adapter fallback, and markdown output.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.base import BaseAdapter, BaseAnalytics, BaseReport


# ---------------------------------------------------------------------------
# Concrete implementations used in tests
# ---------------------------------------------------------------------------

class ConcreteAnalytics(BaseAnalytics):
    OUTPUT_PATH = "data/test_output.json"

    def __init__(self, base_dir=".", state=None):
        super().__init__(base_dir)
        self._state = state or {"value": 42, "name": "test"}

    def to_dict(self) -> dict:
        return self._state


class ConcreteAdapter(BaseAdapter):
    SOURCE_ID = "test_protocol"
    FALLBACK_APY = 3.0

    def __init__(self, apy=None, raise_on_apy=False):
        super().__init__()
        self._apy = apy
        self._raise = raise_on_apy

    def current_apy(self) -> float:
        if self._raise:
            raise RuntimeError("API down")
        return self._apy if self._apy is not None else 7.5

    def source_metadata(self) -> dict:
        return {"source": "test", "protocol": self.SOURCE_ID}


class ConcreteReport(BaseReport):
    OUTPUT_PATH = "data/test_report.json"

    def to_dict(self) -> dict:
        return {"report": "data"}

    def to_markdown(self) -> str:
        return "# Test Report\n\nSome content."


# ===========================================================================
# BaseAnalytics
# ===========================================================================

class TestBaseAnalyticsAbstract(unittest.TestCase):
    # 1
    def test_cannot_instantiate_base_directly(self):
        with self.assertRaises(TypeError):
            BaseAnalytics()

    # 2
    def test_concrete_subclass_instantiates(self):
        obj = ConcreteAnalytics()
        self.assertIsInstance(obj, BaseAnalytics)

    # 3
    def test_default_base_dir_is_dot(self):
        obj = ConcreteAnalytics()
        self.assertEqual(obj.base_dir, ".")

    # 4
    def test_custom_base_dir(self):
        obj = ConcreteAnalytics(base_dir="/tmp/spa")
        self.assertEqual(obj.base_dir, "/tmp/spa")


class TestBaseAnalyticsPath(unittest.TestCase):
    # 5
    def test_path_joins_base_dir_and_relative(self):
        obj = ConcreteAnalytics(base_dir="/mybase")
        result = obj._path("data/out.json")
        self.assertEqual(result, "/mybase/data/out.json")

    # 6
    def test_path_with_dot_base_dir(self):
        obj = ConcreteAnalytics(base_dir=".")
        result = obj._path("sub/file.json")
        self.assertEqual(result, "./sub/file.json")

    # 7
    def test_ensure_dir_creates_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "a", "b", "c.json")
            obj = ConcreteAnalytics()
            obj._ensure_dir(target)
            self.assertTrue(os.path.isdir(os.path.join(tmpdir, "a", "b")))


class TestBaseAnalyticsSave(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.obj = ConcreteAnalytics(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # 8
    def test_save_creates_file_at_output_path(self):
        self.obj.save()
        expected = os.path.join(self.tmpdir, "data", "test_output.json")
        self.assertTrue(os.path.exists(expected))

    # 9
    def test_save_returns_path_string(self):
        result = self.obj.save()
        self.assertIsInstance(result, str)
        self.assertTrue(result.endswith(".json"))

    # 10
    def test_save_explicit_data_overrides_to_dict(self):
        custom = {"override": True}
        path = self.obj.save(data=custom)
        with open(path) as f:
            data = json.load(f)
        self.assertTrue(data["override"])

    # 11
    def test_save_without_args_uses_to_dict(self):
        path = self.obj.save()
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["value"], 42)

    # 12
    def test_save_explicit_path_overrides_output_path(self):
        target = os.path.join(self.tmpdir, "custom_out.json")
        result = self.obj.save(data={"x": 1}, path=target)
        self.assertTrue(os.path.exists(target))
        self.assertEqual(result, target)

    # 13
    def test_save_calls_atomic_save(self):
        with patch("spa_core.base.atomic_save") as mock_as:
            # Need to re-import inside patch context
            from spa_core.base import BaseAnalytics  # noqa
            self.obj.save(data={"y": 2})
        mock_as.assert_called_once()

    # 14
    def test_save_content_is_valid_json(self):
        path = self.obj.save()
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)


class TestBaseAnalyticsLoad(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.obj = ConcreteAnalytics(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # 15
    def test_load_returns_empty_dict_for_missing_file(self):
        result = self.obj.load()
        self.assertEqual(result, {})

    # 16
    def test_load_returns_saved_data(self):
        self.obj.save()
        result = self.obj.load()
        self.assertEqual(result["value"], 42)

    # 17
    def test_load_from_explicit_path(self):
        p = os.path.join(self.tmpdir, "other.json")
        with open(p, "w") as f:
            json.dump({"z": 99}, f)
        result = self.obj.load(path=p)
        self.assertEqual(result["z"], 99)

    # 18
    def test_load_calls_atomic_load(self):
        with patch("spa_core.base.atomic_load", return_value={"mocked": True}) as mock_al:
            result = self.obj.load()
        mock_al.assert_called_once()
        self.assertTrue(result["mocked"])


# ===========================================================================
# BaseAdapter
# ===========================================================================

class TestBaseAdapterAbstract(unittest.TestCase):
    # 19
    def test_cannot_instantiate_base_adapter_directly(self):
        with self.assertRaises(TypeError):
            BaseAdapter()

    # 20
    def test_concrete_adapter_instantiates(self):
        obj = ConcreteAdapter()
        self.assertIsInstance(obj, BaseAdapter)


class TestBaseAdapterInterface(unittest.TestCase):
    def setUp(self):
        self.adapter = ConcreteAdapter(apy=6.0)

    # 21
    def test_current_apy_returns_value(self):
        self.assertEqual(self.adapter.current_apy(), 6.0)

    # 22
    def test_source_metadata_returns_dict(self):
        meta = self.adapter.source_metadata()
        self.assertIsInstance(meta, dict)

    # 23
    def test_is_research_only_true_by_default(self):
        self.assertTrue(self.adapter.is_research_only())

    # 24
    def test_research_only_flag_inherited(self):
        self.assertTrue(ConcreteAdapter.RESEARCH_ONLY)

    # 25
    def test_source_id_set_on_subclass(self):
        self.assertEqual(self.adapter.SOURCE_ID, "test_protocol")

    # 26
    def test_cache_ttl_default(self):
        self.assertEqual(self.adapter.CACHE_TTL, 300)

    # 27
    def test_cache_starts_none(self):
        obj = ConcreteAdapter()
        self.assertIsNone(obj._cache)

    # 28
    def test_cache_time_starts_zero(self):
        obj = ConcreteAdapter()
        self.assertEqual(obj._cache_time, 0.0)


class TestBaseAdapterSafeApy(unittest.TestCase):
    # 29
    def test_safe_apy_returns_current_apy_on_success(self):
        obj = ConcreteAdapter(apy=8.5)
        self.assertEqual(obj.safe_apy(), 8.5)

    # 30
    def test_safe_apy_returns_fallback_on_exception(self):
        obj = ConcreteAdapter(raise_on_apy=True)
        self.assertEqual(obj.safe_apy(), ConcreteAdapter.FALLBACK_APY)

    # 31
    def test_safe_apy_logs_warning_on_exception(self):
        obj = ConcreteAdapter(raise_on_apy=True)
        with self.assertLogs("spa_core.base", level="WARNING") as cm:
            result = obj.safe_apy()
        self.assertEqual(result, 3.0)
        self.assertTrue(any("safe_apy fallback" in line for line in cm.output))

    # 32
    def test_safe_apy_fallback_apy_overridable(self):
        class HighFallback(ConcreteAdapter):
            FALLBACK_APY = 99.0
        obj = HighFallback(raise_on_apy=True)
        self.assertEqual(obj.safe_apy(), 99.0)

    # 33
    def test_cache_expired_when_time_is_zero(self):
        obj = ConcreteAdapter()
        # _cache_time=0 means instantly expired
        self.assertTrue(obj._cache_expired())


# ===========================================================================
# BaseReport
# ===========================================================================

class TestBaseReportAbstract(unittest.TestCase):
    # 34
    def test_cannot_instantiate_base_report_directly(self):
        with self.assertRaises(TypeError):
            BaseReport()

    # 35
    def test_concrete_report_instantiates(self):
        obj = ConcreteReport()
        self.assertIsInstance(obj, BaseReport)
        self.assertIsInstance(obj, BaseAnalytics)


class TestBaseReportMarkdown(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.obj = ConcreteReport(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # 36
    def test_to_markdown_returns_string(self):
        md = self.obj.to_markdown()
        self.assertIsInstance(md, str)

    # 37
    def test_save_markdown_creates_md_file(self):
        path = self.obj.save_markdown()
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".md"))

    # 38
    def test_save_markdown_default_path_replaces_json_with_md(self):
        path = self.obj.save_markdown()
        self.assertIn("test_report.md", path)

    # 39
    def test_save_markdown_content_correct(self):
        path = self.obj.save_markdown()
        with open(path) as f:
            content = f.read()
        self.assertIn("# Test Report", content)

    # 40
    def test_save_markdown_explicit_path(self):
        target = os.path.join(self.tmpdir, "custom.md")
        result = self.obj.save_markdown(path=target)
        self.assertTrue(os.path.exists(target))
        self.assertEqual(result, target)


if __name__ == "__main__":
    unittest.main()
