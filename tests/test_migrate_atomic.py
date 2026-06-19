"""
tests/test_migrate_atomic.py

25 тестов для scripts/migrate_atomic_writes.py
Sprint v10.5 — MP-1389 AUDIT-001
"""
import os
import sys
import json
import shutil
import tempfile
import textwrap
import unittest

# Убеждаемся, что корень проекта в sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.migrate_atomic_writes import (
    scan_file,
    scan_all,
    generate_migration,
    apply_migration,
    migration_report,
    PATTERNS,
    IMPORT_LINE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_py(content: str) -> str:
    """Creates a temp .py file with given content. Caller removes it."""
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(content))
    return path


def _tmp_dir_with_files(files: dict) -> str:
    """Creates a temp directory with given {filename: content} dict. Returns dir path."""
    d = tempfile.mkdtemp()
    for name, content in files.items():
        fpath = os.path.join(d, name)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(content))
    return d


# ---------------------------------------------------------------------------
# 1–6: scan_file — паттерн присутствует
# ---------------------------------------------------------------------------

class TestScanFileHasPattern(unittest.TestCase):

    def test_01_tmp_pattern_detected(self):
        """scan_file на tmp=path+'.tmp' → has_pattern=True"""
        path = _tmp_py("""
            import os, json, tempfile
            def save(data, fpath):
                tmp = fpath + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f)
                os.replace(tmp, fpath)
        """)
        try:
            result = scan_file(path)
            self.assertTrue(result["has_pattern"], "Expected has_pattern=True for tmp+.tmp pattern")
        finally:
            os.unlink(path)

    def test_02_local_def_write_json_detected(self):
        """scan_file с def _write_json → has_pattern=True"""
        path = _tmp_py("""
            import os, json, tempfile
            def _write_json(data, fpath):
                tmp = fpath + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f)
                os.replace(tmp, fpath)
        """)
        try:
            result = scan_file(path)
            self.assertTrue(result["has_pattern"])
        finally:
            os.unlink(path)

    def test_03_local_def_atomic_save_detected(self):
        """scan_file с def _atomic_save → has_pattern=True"""
        path = _tmp_py("""
            def _atomic_save(data, path):
                import os, json, tempfile
                tmp = path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f)
                os.replace(tmp, path)
        """)
        try:
            result = scan_file(path)
            self.assertTrue(result["has_pattern"])
        finally:
            os.unlink(path)

    def test_04_os_replace_detected(self):
        """scan_file с os.replace(tmp, path) → has_pattern=True"""
        path = _tmp_py("""
            import os
            tmp = "/tmp/data.json.tmp"
            os.replace(tmp, "/tmp/data.json")
        """)
        try:
            result = scan_file(path)
            self.assertTrue(result["has_pattern"])
        finally:
            os.unlink(path)

    def test_05_tempfile_mkstemp_detected(self):
        """scan_file с tempfile.mkstemp → has_pattern=True"""
        path = _tmp_py("""
            import os, tempfile
            fd, tmp = tempfile.mkstemp(dir="/tmp", suffix=".tmp")
            os.close(fd)
            os.replace(tmp, "/data/out.json")
        """)
        try:
            result = scan_file(path)
            self.assertTrue(result["has_pattern"])
        finally:
            os.unlink(path)

    def test_06_patterns_found_is_nonempty_list(self):
        """scan_file → patterns_found список непустой при наличии паттерна"""
        path = _tmp_py("""
            def _atomic_write(p, d):
                tmp = p + ".tmp"
                import os; os.replace(tmp, p)
        """)
        try:
            result = scan_file(path)
            self.assertIsInstance(result["patterns_found"], list)
            self.assertGreater(len(result["patterns_found"]), 0)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 7–10: scan_file — паттерн отсутствует / уже мигрирован
# ---------------------------------------------------------------------------

class TestScanFileNoPattern(unittest.TestCase):

    def test_07_clean_file_no_pattern(self):
        """scan_file на чистом файле → has_pattern=False"""
        path = _tmp_py("""
            from spa_core.utils.atomic import atomic_save, atomic_load

            def save(data, fpath):
                atomic_save(data, fpath)
        """)
        try:
            result = scan_file(path)
            self.assertFalse(result["has_pattern"])
        finally:
            os.unlink(path)

    def test_08_already_migrated_flag_set(self):
        """scan_file на уже мигрированном файле → already_migrated=True"""
        path = _tmp_py("""
            from spa_core.utils.atomic import atomic_save
            import os, tempfile

            def save(data, p):
                atomic_save(data, p)
        """)
        try:
            result = scan_file(path)
            self.assertTrue(result["already_migrated"])
        finally:
            os.unlink(path)

    def test_09_empty_file_no_pattern(self):
        """scan_file на пустом файле → has_pattern=False"""
        path = _tmp_py("")
        try:
            result = scan_file(path)
            self.assertFalse(result["has_pattern"])
            self.assertEqual(result["patterns_found"], [])
        finally:
            os.unlink(path)

    def test_10_nonexistent_file_returns_dict(self):
        """scan_file на несуществующем файле возвращает словарь без исключений"""
        result = scan_file("/nonexistent/path/to/file.py")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["has_pattern"])


# ---------------------------------------------------------------------------
# 11–14: scan_file — lines и local_defs
# ---------------------------------------------------------------------------

class TestScanFileDetails(unittest.TestCase):

    def test_11_lines_returned(self):
        """scan_file возвращает список строк с паттернами"""
        path = _tmp_py("""
            import os
            def _write_json(data, p):
                tmp = p + ".tmp"
                os.replace(tmp, p)
        """)
        try:
            result = scan_file(path)
            self.assertIsInstance(result["lines"], list)
            self.assertGreater(len(result["lines"]), 0)
        finally:
            os.unlink(path)

    def test_12_local_defs_populated(self):
        """scan_file заполняет local_defs при наличии локальных функций"""
        path = _tmp_py("""
            def _write_json(data, path):
                pass
            def _atomic_save(data, path):
                pass
        """)
        try:
            result = scan_file(path)
            self.assertIn("_write_json", result["local_defs"])
            self.assertIn("_atomic_save", result["local_defs"])
        finally:
            os.unlink(path)

    def test_13_filepath_in_result(self):
        """scan_file содержит filepath в результате"""
        path = _tmp_py("x = 1\n")
        try:
            result = scan_file(path)
            self.assertEqual(result["filepath"], path)
        finally:
            os.unlink(path)

    def test_14_result_keys_present(self):
        """scan_file возвращает dict с нужными ключами"""
        path = _tmp_py("pass\n")
        try:
            result = scan_file(path)
            for key in ("filepath", "has_pattern", "already_migrated",
                        "patterns_found", "local_defs", "lines"):
                self.assertIn(key, result, f"Missing key: {key}")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 15–17: scan_all
# ---------------------------------------------------------------------------

class TestScanAll(unittest.TestCase):

    def test_15_scan_all_returns_list(self):
        """scan_all() возвращает список"""
        d = _tmp_dir_with_files({
            "a.py": "def _write_json(d, p): pass\n",
            "b.py": "x = 1\n",
        })
        try:
            result = scan_all(d)
            self.assertIsInstance(result, list)
        finally:
            shutil.rmtree(d)

    def test_16_scan_all_finds_affected_files(self):
        """scan_all находит файлы с паттернами"""
        d = _tmp_dir_with_files({
            "module_a.py": "def _atomic_save(data, path): pass\n",
            "module_b.py": "from spa_core.utils.atomic import atomic_save\n",
            "module_c.py": "x = 42\n",
        })
        try:
            result = scan_all(d)
            basenames = [os.path.basename(f) for f in result]
            self.assertIn("module_a.py", basenames)
            self.assertNotIn("module_b.py", basenames)  # already migrated
            self.assertNotIn("module_c.py", basenames)  # no pattern
        finally:
            shutil.rmtree(d)

    def test_17_scan_all_empty_dir(self):
        """scan_all на пустой директории возвращает пустой список"""
        d = tempfile.mkdtemp()
        try:
            result = scan_all(d)
            self.assertEqual(result, [])
        finally:
            shutil.rmtree(d)


# ---------------------------------------------------------------------------
# 18–20: generate_migration
# ---------------------------------------------------------------------------

class TestGenerateMigration(unittest.TestCase):

    def test_18_generate_migration_contains_import(self):
        """generate_migration() возвращает строку с 'from spa_core.utils.atomic'"""
        path = _tmp_py("""
            def _write_json(data, p):
                tmp = p + ".tmp"
                import os; os.replace(tmp, p)
        """)
        try:
            result = generate_migration(path)
            self.assertIn("from spa_core.utils.atomic", result)
        finally:
            os.unlink(path)

    def test_19_generate_migration_nonempty_for_pattern_file(self):
        """generate_migration() возвращает непустую строку для файла с паттерном"""
        path = _tmp_py("""
            def _atomic_save(data, path):
                pass
        """)
        try:
            result = generate_migration(path)
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 50)
        finally:
            os.unlink(path)

    def test_20_generate_migration_empty_for_clean_file(self):
        """generate_migration() возвращает '' для файла без паттернов"""
        path = _tmp_py("""
            from spa_core.utils.atomic import atomic_save
            def save(data, p): atomic_save(data, p)
        """)
        try:
            result = generate_migration(path)
            self.assertEqual(result, "")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 21–23: apply_migration
# ---------------------------------------------------------------------------

class TestApplyMigration(unittest.TestCase):

    def test_21_dry_run_does_not_modify_file(self):
        """apply_migration(dry_run=True) не изменяет файл"""
        path = _tmp_py("""
            import os
            def _write_json(data, p):
                tmp = p + ".tmp"
                os.replace(tmp, p)
        """)
        original_content = open(path).read()
        try:
            apply_migration(path, dry_run=True)
            current_content = open(path).read()
            self.assertEqual(original_content, current_content,
                             "dry_run=True должен оставить файл неизменным")
        finally:
            os.unlink(path)

    def test_22_apply_returns_bool(self):
        """apply_migration возвращает булево значение"""
        path = _tmp_py("""
            def _write_json(data, p):
                tmp = p + ".tmp"
                import os; os.replace(tmp, p)
        """)
        try:
            result = apply_migration(path, dry_run=True)
            self.assertIsInstance(result, bool)
        finally:
            os.unlink(path)

    def test_23_apply_false_for_no_pattern(self):
        """apply_migration возвращает False для файла без паттернов"""
        path = _tmp_py("""
            x = 1
            y = 2
        """)
        try:
            result = apply_migration(path, dry_run=True)
            self.assertFalse(result)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 24–25: migration_report
# ---------------------------------------------------------------------------

class TestMigrationReport(unittest.TestCase):

    def test_24_report_contains_total_files(self):
        """migration_report() содержит ключ total_files"""
        paths = []
        try:
            for src in [
                "def _write_json(d, p): pass\n",
                "from spa_core.utils.atomic import atomic_save\nx=1\n",
                "x = 1\n",
            ]:
                p = _tmp_py(src)
                paths.append(p)
            report = migration_report(paths)
            self.assertIn("total_files", report)
            self.assertEqual(report["total_files"], 3)
        finally:
            for p in paths:
                os.unlink(p)

    def test_25_report_counts_already_using(self):
        """migration_report() правильно считает already_using_utils и needs_migration"""
        paths = []
        try:
            # 1 уже мигрирован, 1 нужна миграция, 1 чистый
            for src in [
                "from spa_core.utils.atomic import atomic_save\ndef s(d,p): atomic_save(d,p)\n",
                "def _atomic_save(data, path): pass\n",
                "import math\nx = math.pi\n",
            ]:
                p = _tmp_py(src)
                paths.append(p)
            report = migration_report(paths)
            self.assertEqual(report["already_using_utils"], 1)
            self.assertEqual(report["needs_migration"], 1)
            self.assertIn("local_defs_found", report)
            self.assertIn("patterns_summary", report)
        finally:
            for p in paths:
                os.unlink(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
