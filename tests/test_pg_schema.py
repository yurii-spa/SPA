"""
Tests for scripts/validate_pg_schema.py — Sprint v10.95 (MP-1479).
25 unit tests using unittest only (stdlib).
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.validate_pg_schema import (
    parse_tables,
    parse_indexes,
    check_primary_keys,
    check_jsonb_usage,
    check_timestamptz,
    check_fk_indexes,
    validate_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ddl(body: str) -> str:
    """Wrap a table body in a minimal CREATE TABLE statement."""
    return f"CREATE TABLE IF NOT EXISTS test_table (\n{body}\n);"


# ---------------------------------------------------------------------------
# 1. TestParseTables  (5 tests)
# ---------------------------------------------------------------------------

class TestParseTables(unittest.TestCase):

    def test_finds_single_table(self):
        """parse_tables finds a table by name."""
        ddl = _make_ddl("    id SERIAL PRIMARY KEY,\n    name TEXT NOT NULL")
        tables = parse_tables(ddl)
        self.assertIn("test_table", tables)

    def test_finds_columns(self):
        """parse_tables extracts column names and types."""
        ddl = _make_ddl("    id SERIAL PRIMARY KEY,\n    amount DOUBLE PRECISION NOT NULL")
        tables = parse_tables(ddl)
        cols = {c["name"]: c["type"] for c in tables["test_table"]["columns"]}
        self.assertIn("id", cols)
        self.assertIn("amount", cols)

    def test_finds_foreign_key(self):
        """parse_tables extracts FOREIGN KEY constraints."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS orders (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    protocol_key TEXT NOT NULL,\n"
            "    FOREIGN KEY (protocol_key) REFERENCES protocols(key)\n"
            ");"
        )
        tables = parse_tables(ddl)
        fks = tables["orders"]["foreign_keys"]
        self.assertEqual(len(fks), 1)
        self.assertEqual(fks[0]["column"], "protocol_key")
        self.assertEqual(fks[0]["ref_table"], "protocols")

    def test_handles_empty_ddl(self):
        """parse_tables returns empty dict for empty string."""
        tables = parse_tables("")
        self.assertEqual(tables, {})

    def test_handles_multiple_tables(self):
        """parse_tables finds all tables when multiple are present."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS alpha (\n    id SERIAL PRIMARY KEY\n);\n"
            "CREATE TABLE IF NOT EXISTS beta (\n    id SERIAL PRIMARY KEY\n);\n"
            "CREATE TABLE IF NOT EXISTS gamma (\n    id SERIAL PRIMARY KEY\n);\n"
        )
        tables = parse_tables(ddl)
        self.assertIn("alpha", tables)
        self.assertIn("beta", tables)
        self.assertIn("gamma", tables)
        self.assertEqual(len(tables), 3)


# ---------------------------------------------------------------------------
# 2. TestParseIndexes  (3 tests)
# ---------------------------------------------------------------------------

class TestParseIndexes(unittest.TestCase):

    def test_finds_index(self):
        """parse_indexes finds a CREATE INDEX statement."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS foo (\n    id SERIAL PRIMARY KEY\n);\n"
            "CREATE INDEX IF NOT EXISTS idx_foo_id ON foo (id);\n"
        )
        indexes = parse_indexes(ddl)
        self.assertEqual(len(indexes), 1)
        self.assertEqual(indexes[0]["name"], "idx_foo_id")

    def test_extracts_table_and_columns(self):
        """parse_indexes captures the table name and column list."""
        ddl = (
            "CREATE INDEX IF NOT EXISTS idx_orders_proto\n"
            "    ON orders (protocol_key, created_at DESC);\n"
        )
        indexes = parse_indexes(ddl)
        self.assertEqual(len(indexes), 1)
        idx = indexes[0]
        self.assertEqual(idx["table"], "orders")
        self.assertIn("protocol_key", idx["columns"])
        self.assertIn("created_at", idx["columns"])

    def test_handles_no_indexes(self):
        """parse_indexes returns empty list when no indexes exist."""
        ddl = _make_ddl("    id SERIAL PRIMARY KEY,\n    name TEXT")
        indexes = parse_indexes(ddl)
        self.assertEqual(indexes, [])


# ---------------------------------------------------------------------------
# 3. TestCheckPrimaryKeys  (4 tests)
# ---------------------------------------------------------------------------

class TestCheckPrimaryKeys(unittest.TestCase):

    def test_passes_with_pk(self):
        """check_primary_keys returns no issues when id SERIAL PRIMARY KEY exists."""
        ddl = _make_ddl("    id SERIAL PRIMARY KEY,\n    name TEXT")
        tables = parse_tables(ddl)
        issues = check_primary_keys(tables)
        self.assertEqual(issues, [])

    def test_fails_without_pk(self):
        """check_primary_keys flags a table with no PRIMARY KEY."""
        ddl = "CREATE TABLE IF NOT EXISTS no_pk (\n    name TEXT NOT NULL\n);"
        tables = parse_tables(ddl)
        issues = check_primary_keys(tables)
        self.assertTrue(any("no_pk" in i for i in issues))

    def test_multiple_tables_all_with_pk(self):
        """check_primary_keys passes when all tables have PKs."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS t1 (\n    id SERIAL PRIMARY KEY\n);\n"
            "CREATE TABLE IF NOT EXISTS t2 (\n    id SERIAL PRIMARY KEY\n);\n"
        )
        tables = parse_tables(ddl)
        issues = check_primary_keys(tables)
        self.assertEqual(issues, [])

    def test_detects_missing_pk_in_one_of_many(self):
        """check_primary_keys finds the single table missing a PK."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS good (\n    id SERIAL PRIMARY KEY\n);\n"
            "CREATE TABLE IF NOT EXISTS bad (\n    name TEXT NOT NULL\n);\n"
        )
        tables = parse_tables(ddl)
        issues = check_primary_keys(tables)
        self.assertEqual(len(issues), 1)
        self.assertIn("bad", issues[0])


# ---------------------------------------------------------------------------
# 4. TestCheckJsonb  (4 tests)
# ---------------------------------------------------------------------------

class TestCheckJsonb(unittest.TestCase):

    def test_passes_with_jsonb_col(self):
        """check_jsonb_usage returns no issues when JSON column uses JSONB."""
        ddl = "CREATE TABLE IF NOT EXISTS t (\n    id SERIAL PRIMARY KEY,\n    payload_json JSONB\n);"
        tables = parse_tables(ddl)
        issues = check_jsonb_usage(tables)
        self.assertEqual(issues, [])

    def test_fails_with_text_json_col(self):
        """check_jsonb_usage flags a payload_json TEXT column."""
        ddl = "CREATE TABLE IF NOT EXISTS t (\n    id SERIAL PRIMARY KEY,\n    payload_json TEXT\n);"
        tables = parse_tables(ddl)
        issues = check_jsonb_usage(tables)
        self.assertTrue(any("payload_json" in i for i in issues))

    def test_passes_non_json_text_col(self):
        """check_jsonb_usage ignores TEXT columns that are not JSON columns."""
        ddl = "CREATE TABLE IF NOT EXISTS t (\n    id SERIAL PRIMARY KEY,\n    description TEXT,\n    notes TEXT\n);"
        tables = parse_tables(ddl)
        issues = check_jsonb_usage(tables)
        self.assertEqual(issues, [])

    def test_detects_raw_json_text(self):
        """check_jsonb_usage flags raw_json TEXT specifically."""
        ddl = "CREATE TABLE IF NOT EXISTS snap (\n    id SERIAL PRIMARY KEY,\n    raw_json TEXT\n);"
        tables = parse_tables(ddl)
        issues = check_jsonb_usage(tables)
        self.assertTrue(any("raw_json" in i for i in issues))


# ---------------------------------------------------------------------------
# 5. TestCheckTimestamptz  (4 tests)
# ---------------------------------------------------------------------------

class TestCheckTimestamptz(unittest.TestCase):

    def test_passes_timestamptz_col(self):
        """check_timestamptz returns no issues for TIMESTAMPTZ column."""
        ddl = "CREATE TABLE IF NOT EXISTS t (\n    id SERIAL PRIMARY KEY,\n    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()\n);"
        tables = parse_tables(ddl)
        issues = check_timestamptz(tables)
        self.assertEqual(issues, [])

    def test_fails_text_timestamp_col(self):
        """check_timestamptz flags a timestamp TEXT column."""
        ddl = "CREATE TABLE IF NOT EXISTS t (\n    id SERIAL PRIMARY KEY,\n    timestamp TEXT NOT NULL\n);"
        tables = parse_tables(ddl)
        issues = check_timestamptz(tables)
        self.assertTrue(any("timestamp" in i for i in issues))

    def test_fails_plain_timestamp_col(self):
        """check_timestamptz flags TIMESTAMP (without TZ) columns."""
        ddl = "CREATE TABLE IF NOT EXISTS t (\n    id SERIAL PRIMARY KEY,\n    resolved_at TIMESTAMP\n);"
        tables = parse_tables(ddl)
        issues = check_timestamptz(tables)
        self.assertTrue(any("resolved_at" in i for i in issues))

    def test_passes_non_timestamp_text_col(self):
        """check_timestamptz ignores TEXT columns not named as timestamps."""
        ddl = "CREATE TABLE IF NOT EXISTS t (\n    id SERIAL PRIMARY KEY,\n    description TEXT,\n    status TEXT\n);"
        tables = parse_tables(ddl)
        issues = check_timestamptz(tables)
        self.assertEqual(issues, [])


# ---------------------------------------------------------------------------
# 6. TestCheckFkIndexes  (3 tests)
# ---------------------------------------------------------------------------

class TestCheckFkIndexes(unittest.TestCase):

    def test_passes_indexed_fk(self):
        """check_fk_indexes returns no issues when FK column has an index."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS protocols (\n    id SERIAL PRIMARY KEY,\n    key TEXT NOT NULL UNIQUE\n);\n"
            "CREATE TABLE IF NOT EXISTS orders (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    protocol_key TEXT NOT NULL,\n"
            "    FOREIGN KEY (protocol_key) REFERENCES protocols(key)\n"
            ");\n"
            "CREATE INDEX IF NOT EXISTS idx_orders_proto ON orders (protocol_key);\n"
        )
        tables = parse_tables(ddl)
        indexes = parse_indexes(ddl)
        issues = check_fk_indexes(tables, indexes)
        self.assertEqual(issues, [])

    def test_fails_unindexed_fk(self):
        """check_fk_indexes flags FK column with no supporting index."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS protocols (\n    id SERIAL PRIMARY KEY,\n    key TEXT NOT NULL UNIQUE\n);\n"
            "CREATE TABLE IF NOT EXISTS orders (\n"
            "    id SERIAL PRIMARY KEY,\n"
            "    protocol_key TEXT NOT NULL,\n"
            "    FOREIGN KEY (protocol_key) REFERENCES protocols(key)\n"
            ");\n"
            # No index on orders.protocol_key
        )
        tables = parse_tables(ddl)
        indexes = parse_indexes(ddl)
        issues = check_fk_indexes(tables, indexes)
        self.assertTrue(any("protocol_key" in i for i in issues))

    def test_handles_no_fks(self):
        """check_fk_indexes returns no issues when no FKs exist."""
        ddl = (
            "CREATE TABLE IF NOT EXISTS standalone (\n    id SERIAL PRIMARY KEY,\n    name TEXT\n);\n"
        )
        tables = parse_tables(ddl)
        indexes = parse_indexes(ddl)
        issues = check_fk_indexes(tables, indexes)
        self.assertEqual(issues, [])


# ---------------------------------------------------------------------------
# 7. TestValidateSchema  (2 tests)
# ---------------------------------------------------------------------------

class TestValidateSchema(unittest.TestCase):

    def test_returns_dict_with_required_keys_on_real_file(self):
        """validate_schema returns a dict with all required keys for the real DDL."""
        result = validate_schema()
        required_keys = {"status", "issues", "tables_checked", "indexes_found", "counts"}
        self.assertEqual(required_keys, required_keys & set(result.keys()))
        self.assertIn(result["status"], {"PASS", "FAIL", "ERROR"})
        self.assertIsInstance(result["issues"], list)
        self.assertIsInstance(result["tables_checked"], list)
        self.assertIsInstance(result["indexes_found"], int)
        self.assertIsInstance(result["counts"], dict)
        # Real schema has 7 tables
        self.assertEqual(len(result["tables_checked"]), 7)

    def test_handles_file_not_found(self):
        """validate_schema returns ERROR status for a missing file."""
        result = validate_schema("/nonexistent/path/schema.sql")
        self.assertEqual(result["status"], "ERROR")
        self.assertTrue(len(result["issues"]) > 0)
        self.assertIn("not found", result["issues"][0].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
