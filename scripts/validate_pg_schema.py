"""
Validates the PostgreSQL migration plan (DDL-only, no connection needed).
Checks: primary keys, JSONB usage, TIMESTAMPTZ, index coverage for FKs.
"""
import re
import sys
import json
from pathlib import Path
from typing import Dict, List

DEFAULT_SCHEMA = str(
    Path(__file__).resolve().parents[1] / "spa_core" / "database" / "schema_postgres.sql"
)


def parse_tables(ddl: str) -> Dict[str, Dict]:
    """
    Parse CREATE TABLE statements from DDL text.

    Returns a dict keyed by table name. Each value is a dict with:
      - 'columns': list of dicts with 'name' and 'type' keys
      - 'foreign_keys': list of dicts with 'column' and 'ref_table' keys
    """
    tables: Dict[str, Dict] = {}

    pattern = re.compile(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\);",
        re.DOTALL | re.IGNORECASE,
    )

    for match in pattern.finditer(ddl):
        table_name = match.group(1)
        body = match.group(2)

        columns: List[Dict] = []
        foreign_keys: List[Dict] = []

        for raw_line in body.split("\n"):
            line = raw_line.strip().rstrip(",").strip()
            if not line or line.startswith("--"):
                continue

            # Detect FOREIGN KEY constraint
            fk_match = re.match(
                r"FOREIGN\s+KEY\s*\((\w+)\)\s+REFERENCES\s+(\w+)",
                line,
                re.IGNORECASE,
            )
            if fk_match:
                foreign_keys.append(
                    {
                        "column": fk_match.group(1),
                        "ref_table": fk_match.group(2),
                    }
                )
                continue

            # Skip other constraint lines (PRIMARY KEY, UNIQUE, CHECK, etc.)
            if re.match(
                r"(PRIMARY\s+KEY|UNIQUE|CHECK|CONSTRAINT)\s*[\(\(]",
                line,
                re.IGNORECASE,
            ):
                continue

            # Parse column definition: name type [rest]
            col_match = re.match(r"(\w+)\s+(\S+(?:\s+\S+)*)", line)
            if col_match:
                col_name = col_match.group(1)
                # Grab just the type token(s) before keywords like NOT/DEFAULT/UNIQUE
                remainder = col_match.group(2)
                type_tokens = []
                for token in remainder.split():
                    if token.upper() in (
                        "NOT",
                        "NULL",
                        "DEFAULT",
                        "UNIQUE",
                        "PRIMARY",
                        "KEY",
                        "REFERENCES",
                        "CHECK",
                        "CONSTRAINT",
                    ):
                        break
                    type_tokens.append(token)
                col_type = " ".join(type_tokens)
                columns.append({"name": col_name, "type": col_type})

        tables[table_name] = {"columns": columns, "foreign_keys": foreign_keys}

    return tables


def parse_indexes(ddl: str) -> List[Dict]:
    """
    Parse CREATE INDEX statements from DDL text.

    Returns a list of dicts with:
      - 'name': index name
      - 'table': table the index is on
      - 'columns': list of column names the index covers
    """
    indexes: List[Dict] = []

    pattern = re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+"
        r"ON\s+(\w+)\s*\(([^)]+)\)",
        re.IGNORECASE,
    )

    for match in pattern.finditer(ddl):
        index_name = match.group(1)
        table_name = match.group(2)
        cols_raw = match.group(3)

        # Strip modifiers like DESC/ASC and extra whitespace
        cols = [
            re.split(r"\s+", c.strip())[0]
            for c in cols_raw.split(",")
            if c.strip()
        ]

        indexes.append(
            {
                "name": index_name,
                "table": table_name,
                "columns": cols,
            }
        )

    return indexes


def check_primary_keys(tables: Dict) -> List[str]:
    """
    Return a list of issues for tables that lack a PRIMARY KEY column.

    Detects inline 'SERIAL PRIMARY KEY' style columns.
    """
    issues: List[str] = []

    for table_name, table_info in tables.items():
        has_pk = False
        for col in table_info.get("columns", []):
            t = col["type"].upper()
            if "SERIAL" in t and col["name"].lower() == "id":
                has_pk = True
                break
            if "PRIMARY" in t:
                has_pk = True
                break

        if not has_pk:
            issues.append(f"Table '{table_name}' missing PRIMARY KEY")

    return issues


def check_jsonb_usage(tables: Dict) -> List[str]:
    """
    Return issues for columns that store JSON data but use TEXT/VARCHAR
    instead of JSONB.

    A column is considered a 'JSON column' when its name matches:
      json | payload | details | snapshot | state_json | raw_json
    """
    issues: List[str] = []

    # Match columns whose name ends with 'json' or 'snapshot', or begins
    # with 'payload' / 'details'. This intentionally excludes 'snapshot_id'
    # (a string key) while catching raw_json, payload_json, data_snapshot, etc.
    json_name_pattern = re.compile(
        r"json$|snapshot$|^payload|^details",
        re.IGNORECASE,
    )
    text_types = {"TEXT", "VARCHAR", "CHARACTER VARYING"}

    for table_name, table_info in tables.items():
        for col in table_info.get("columns", []):
            if json_name_pattern.search(col["name"]):
                col_type_base = col["type"].upper().split("(")[0].strip()
                if col_type_base in text_types:
                    issues.append(
                        f"Table '{table_name}', column '{col['name']}': "
                        f"should be JSONB, found {col['type']}"
                    )

    return issues


def check_timestamptz(tables: Dict) -> List[str]:
    """
    Return issues for timestamp-like columns that use TEXT or plain TIMESTAMP
    instead of TIMESTAMPTZ.

    A column is considered timestamp-like when its name matches:
      starts with 'timestamp' OR ends with '_at' OR ends with '_time'
    """
    issues: List[str] = []

    ts_name_pattern = re.compile(
        r"^timestamp|_at$|_time$",
        re.IGNORECASE,
    )
    bad_types = {"TEXT", "TIMESTAMP", "CHARACTER VARYING", "VARCHAR"}

    for table_name, table_info in tables.items():
        for col in table_info.get("columns", []):
            if ts_name_pattern.search(col["name"]):
                col_type_base = col["type"].upper().split("(")[0].strip()
                if col_type_base in bad_types:
                    issues.append(
                        f"Table '{table_name}', column '{col['name']}': "
                        f"should be TIMESTAMPTZ, found {col['type']}"
                    )

    return issues


def check_fk_indexes(tables: Dict, indexes: List[Dict]) -> List[str]:
    """
    Return issues for foreign-key columns that are not covered by any index.

    An FK column is considered 'covered' if there is an index on the same
    table where that column appears among the indexed columns.
    """
    issues: List[str] = []

    # Build a lookup: table -> set of indexed column names
    indexed: Dict[str, set] = {}
    for idx in indexes:
        tbl = idx["table"]
        if tbl not in indexed:
            indexed[tbl] = set()
        for col in idx["columns"]:
            indexed[tbl].add(col)

    for table_name, table_info in tables.items():
        for fk in table_info.get("foreign_keys", []):
            fk_col = fk["column"]
            covered_cols = indexed.get(table_name, set())
            if fk_col not in covered_cols:
                issues.append(
                    f"Table '{table_name}', FK column '{fk_col}' "
                    f"has no supporting index"
                )

    return issues


def validate_schema(ddl_file: str = DEFAULT_SCHEMA) -> dict:
    """
    Run all checks against a DDL file. Returns a result dict.

    Keys:
      status          - "PASS", "FAIL", or "ERROR"
      issues          - list of issue strings
      tables_checked  - list of table names found
      indexes_found   - count of indexes parsed
      counts          - dict of per-check issue counts
    """
    try:
        ddl = Path(ddl_file).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "status": "ERROR",
            "issues": [f"File not found: {ddl_file}"],
            "tables_checked": [],
            "indexes_found": 0,
            "counts": {},
        }

    tables = parse_tables(ddl)
    indexes = parse_indexes(ddl)

    pk_issues = check_primary_keys(tables)
    jsonb_issues = check_jsonb_usage(tables)
    ts_issues = check_timestamptz(tables)
    fk_issues = check_fk_indexes(tables, indexes)

    all_issues = pk_issues + jsonb_issues + ts_issues + fk_issues

    return {
        "status": "PASS" if not all_issues else "FAIL",
        "issues": all_issues,
        "tables_checked": list(tables.keys()),
        "indexes_found": len(indexes),
        "counts": {
            "primary_key_issues": len(pk_issues),
            "jsonb_issues": len(jsonb_issues),
            "timestamptz_issues": len(ts_issues),
            "fk_index_issues": len(fk_issues),
        },
    }


if __name__ == "__main__":
    ddl_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SCHEMA
    result = validate_schema(ddl_file)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)
