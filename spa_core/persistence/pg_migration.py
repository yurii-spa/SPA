"""
SPA-V331 — PostgreSQL migration prep (SQLite → PostgreSQL).

This module migrates the current SQLite backend to PostgreSQL. The planning
path introspects a live SQLite database, derives the equivalent PostgreSQL DDL
(type mapping, defaults, indexes), and builds an ordered, FK-safe copy plan.

`execute_migration()` (SPA-V341) implements a **gated** execution path: it
refuses to do anything unless the operator both sets
`SPA_PG_MIGRATION_EXECUTE=1` AND passes `i_understand_this_writes_data=True`,
and even then defaults to `dry_run=True` (reports the ordered DDL + copy plan
without writing). Only an explicit `dry_run=False` opens a write transaction.
This mirrors the layered BLOCKED safety pattern used by the live execution
adapters. The PostgreSQL driver is dependency-injected so the path is fully
unit-testable offline without psycopg2.

Design goals
------------
* Pure stdlib for the planning path (`sqlite3`, `json`, `dataclasses`). No
  hard dependency on `psycopg2` — that is only touched if a caller explicitly
  opts into execution (out of scope for V331).
* Reuse the same backend seam concepts as `spa_core.database` (db_url /
  connection) without importing Alembic, so the planner has zero migration-
  framework dependency.
* The generated DDL is byte-for-byte compatible in spirit with the canonical
  PostgreSQL schema in `alembic/versions/0001_initial_schema.py` for the SPA
  v1.6 tables, but is derived generically so future tables migrate for free.

Typical usage
-------------
    python -m spa_core.persistence.pg_migration --plan
    python -m spa_core.persistence.pg_migration --plan --sqlite /path/to/spa.db --ddl-only

Phase scope (V341): schema + plan + gated execution (dry-run default) + tests.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MigrationPlanError(RuntimeError):
    """Raised when a SQLite database cannot be introspected into a plan."""


class MigrationExecutionBlocked(RuntimeError):
    """
    Raised when `execute_migration()` is called without the explicit opt-in.

    V331 is plan-only; actually moving data is out of scope and must be a
    deliberate, separately-reviewed operation.
    """


# ---------------------------------------------------------------------------
# Type mapping: SQLite (dynamic typing / affinity) → PostgreSQL (static).
#
# SQLite stores a declared type string per column but applies only *affinity*
# rules. We map by the affinity the declared type resolves to, which mirrors
# the rules in https://www.sqlite.org/datatype3.html §3.1.
# ---------------------------------------------------------------------------

# Ordered affinity probes — first substring hit wins (SQLite's own algorithm).
_AFFINITY_RULES: Tuple[Tuple[str, str], ...] = (
    ("INT", "INTEGER"),     # INT, INTEGER, BIGINT, TINYINT, ...  -> INTEGER affinity
    ("CHAR", "TEXT"),       # CHARACTER, VARCHAR, NCHAR, ...       -> TEXT affinity
    ("CLOB", "TEXT"),
    ("TEXT", "TEXT"),
    ("BLOB", "BLOB"),       # also the "no datatype" case
    ("REAL", "REAL"),
    ("FLOA", "REAL"),       # FLOAT
    ("DOUB", "REAL"),       # DOUBLE
    ("NUM", "NUMERIC"),     # NUMERIC, DECIMAL, BOOLEAN, DATE, DATETIME -> NUMERIC affinity
)

# Affinity → PostgreSQL base type.
_AFFINITY_TO_PG: dict = {
    "INTEGER": "INTEGER",
    "TEXT": "TEXT",
    "REAL": "DOUBLE PRECISION",
    "BLOB": "BYTEA",
    "NUMERIC": "NUMERIC",
}

# Declared types we want to preserve verbatim rather than collapse to affinity.
# SPA uses TIMESTAMPTZ on the Postgres side for a handful of columns; if the
# SQLite column was declared TIMESTAMP/TIMESTAMPTZ/DATETIME we honour that.
_TIMESTAMP_HINTS = ("TIMESTAMPTZ", "TIMESTAMP", "DATETIME")


def sqlite_affinity(declared_type: str) -> str:
    """
    Return the SQLite type affinity for a declared column type.

    Implements the five-rule algorithm from the SQLite docs. An empty / unknown
    declared type yields BLOB affinity (rule 5), matching SQLite.
    """
    t = (declared_type or "").upper()
    for needle, affinity in _AFFINITY_RULES:
        if needle in t:
            return affinity
    return "BLOB"


def map_sqlite_type(declared_type: str, *, is_serial_pk: bool = False) -> str:
    """
    Map a SQLite declared type to a PostgreSQL column type.

    Parameters
    ----------
    declared_type:
        The `type` string from `PRAGMA table_info`.
    is_serial_pk:
        When True the column is an `INTEGER PRIMARY KEY AUTOINCREMENT` rowid
        alias and should become `SERIAL` (auto-increment) on Postgres.
    """
    if is_serial_pk:
        return "SERIAL"

    t = (declared_type or "").upper().strip()
    # Honour explicit timestamp declarations (SPA maps these to TIMESTAMPTZ).
    for hint in _TIMESTAMP_HINTS:
        if hint in t:
            return "TIMESTAMPTZ"

    affinity = sqlite_affinity(t)
    return _AFFINITY_TO_PG[affinity]


# ---------------------------------------------------------------------------
# Default-value translation.
#
# SQLite column defaults frequently use SQLite-only functions. We translate the
# ones SPA actually relies on and flag anything we cannot safely port so the
# operator reviews it instead of silently shipping broken DDL.
# ---------------------------------------------------------------------------

_DEFAULT_TRANSLATIONS: Tuple[Tuple[str, str], ...] = (
    # (regex on the raw SQLite default, postgres replacement)
    (r"datetime\(\s*'now'\s*,\s*'utc'\s*\)", "NOW()"),
    (r"datetime\(\s*'now'\s*\)", "NOW()"),
    (r"CURRENT_TIMESTAMP", "NOW()"),
)


def translate_default(raw_default: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Translate a SQLite default expression to PostgreSQL.

    Returns
    -------
    (pg_default, warning):
        `pg_default` is the SQL fragment to place after DEFAULT (or None if the
        column has no default). `warning` is a human-readable note when the
        default could not be ported cleanly (e.g. `strftime(...)` snapshot ids),
        else None.
    """
    if raw_default is None:
        return None, None

    d = raw_default.strip()

    # Numeric / boolean / quoted-string literals port verbatim.
    if re.fullmatch(r"-?\d+(\.\d+)?", d) or d.upper() in ("TRUE", "FALSE", "NULL"):
        return d, None
    if (d.startswith("'") and d.endswith("'")) or (d.startswith('"') and d.endswith('"')):
        return d, None

    # strftime(...) ids (e.g. snapshot_id / trade_id seeds) have no clean
    # Postgres equivalent — Postgres should rely on application-supplied values
    # or a trigger/sequence. Checked BEFORE the datetime() rules because a
    # strftime default often *wraps* a datetime('now') call we must not match.
    if "strftime" in d.lower():
        return None, (
            f"default {d!r} uses strftime(); dropped on Postgres "
            "(application supplies value, or add a trigger/sequence)"
        )

    for pattern, replacement in _DEFAULT_TRANSLATIONS:
        if re.search(pattern, d, flags=re.IGNORECASE):
            return replacement, None

    # Unknown expression default — keep it but warn the operator to verify.
    return d, f"default {d!r} passed through unverified — review for Postgres compatibility"


# ---------------------------------------------------------------------------
# Introspection data model.
# ---------------------------------------------------------------------------


@dataclass
class ColumnSpec:
    name: str
    sqlite_type: str
    not_null: bool
    default: Optional[str]
    pk_index: int  # 0 = not part of PK, else 1-based position in PK
    is_serial_pk: bool = False

    @property
    def pg_type(self) -> str:
        return map_sqlite_type(self.sqlite_type, is_serial_pk=self.is_serial_pk)


@dataclass
class ForeignKeySpec:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class IndexSpec:
    name: str
    unique: bool
    columns: List[str]


@dataclass
class TableSpec:
    name: str
    columns: List[ColumnSpec]
    foreign_keys: List[ForeignKeySpec] = field(default_factory=list)
    indexes: List[IndexSpec] = field(default_factory=list)
    unique_columns: List[str] = field(default_factory=list)

    @property
    def pk_columns(self) -> List[str]:
        cols = [c for c in self.columns if c.pk_index]
        cols.sort(key=lambda c: c.pk_index)
        return [c.name for c in cols]


@dataclass
class MigrationPlan:
    """The full plan: ordered tables, generated DDL, and per-table row counts."""
    tables: List[TableSpec]
    copy_order: List[str]
    ddl: str
    row_counts: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "copy_order": self.copy_order,
            "tables": [t.name for t in self.tables],
            "row_counts": self.row_counts,
            "warnings": self.warnings,
            "ddl_sha_len": len(self.ddl),
        }


# Internal SQLite bookkeeping tables we never migrate.
_SKIP_TABLES = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4", "alembic_version"}


# ---------------------------------------------------------------------------
# Introspection.
# ---------------------------------------------------------------------------


def _is_serial_pk(table_sql: Optional[str], column: ColumnSpec) -> bool:
    """
    Decide whether an INTEGER PRIMARY KEY column is an AUTOINCREMENT rowid alias.

    SQLite only treats a single-column `INTEGER PRIMARY KEY` as a rowid alias.
    We additionally require INTEGER affinity. AUTOINCREMENT is detected from the
    original CREATE TABLE SQL (PRAGMA does not expose it directly).
    """
    if column.pk_index != 1:
        return False
    if sqlite_affinity(column.sqlite_type) != "INTEGER":
        return False
    if not table_sql:
        # No DDL available — be conservative and treat a lone INTEGER PK as serial.
        return True
    sql = table_sql.upper()
    # Match "<col> INTEGER PRIMARY KEY [AUTOINCREMENT]"
    pat = re.compile(
        rf"\b{re.escape(column.name.upper())}\b\s+INTEGER\s+PRIMARY\s+KEY",
    )
    return bool(pat.search(sql))


def introspect_sqlite(source: Union[str, Path, sqlite3.Connection]) -> List[TableSpec]:
    """
    Introspect every user table in a SQLite database into `TableSpec`s.

    `source` may be a path, a `sqlite:///...` URL, or an open connection.
    """
    own_conn = False
    if isinstance(source, sqlite3.Connection):
        conn = source
    else:
        path = _resolve_sqlite_path(source)
        if path != ":memory:" and not Path(path).exists():
            raise MigrationPlanError(f"SQLite database not found: {path}")
        conn = sqlite3.connect(path)
        own_conn = True

    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_rows = [(r["name"], r["sql"]) for r in cur.fetchall()]

        tables: List[TableSpec] = []
        for tname, tsql in table_rows:
            if tname in _SKIP_TABLES:
                continue
            cols: List[ColumnSpec] = []
            for r in conn.execute(f"PRAGMA table_info('{tname}')").fetchall():
                col = ColumnSpec(
                    name=r["name"],
                    sqlite_type=r["type"] or "",
                    not_null=bool(r["notnull"]),
                    default=r["dflt_value"],
                    pk_index=int(r["pk"]),
                )
                cols.append(col)
            # Mark serial PKs.
            for col in cols:
                if col.pk_index and _is_serial_pk(tsql, col):
                    col.is_serial_pk = True

            fks = [
                ForeignKeySpec(column=r["from"], ref_table=r["table"], ref_column=r["to"])
                for r in conn.execute(f"PRAGMA foreign_key_list('{tname}')").fetchall()
            ]

            indexes: List[IndexSpec] = []
            unique_cols: List[str] = []
            for ir in conn.execute(f"PRAGMA index_list('{tname}')").fetchall():
                iname = ir["name"]
                # Skip auto-indexes SQLite creates for UNIQUE/PK constraints; we
                # re-express UNIQUE inline in the column DDL instead.
                is_auto = (ir["origin"] != "c")  # 'c' = created by CREATE INDEX
                icols = [
                    c["name"]
                    for c in conn.execute(f"PRAGMA index_info('{iname}')").fetchall()
                ]
                if is_auto:
                    if bool(ir["unique"]) and len(icols) == 1:
                        unique_cols.append(icols[0])
                    continue
                indexes.append(
                    IndexSpec(name=iname, unique=bool(ir["unique"]), columns=icols)
                )

            tables.append(
                TableSpec(
                    name=tname,
                    columns=cols,
                    foreign_keys=fks,
                    indexes=indexes,
                    unique_columns=unique_cols,
                )
            )
        return tables
    finally:
        if own_conn:
            conn.close()


# ---------------------------------------------------------------------------
# FK-safe topological ordering for the data copy.
# ---------------------------------------------------------------------------


def topo_sort_tables(tables: Sequence[TableSpec]) -> List[str]:
    """
    Order tables so a referenced (parent) table is created/copied before any
    table that references it. Falls back to declaration order on cycles.
    """
    names = [t.name for t in tables]
    deps: dict = {t.name: {fk.ref_table for fk in t.foreign_keys if fk.ref_table in names and fk.ref_table != t.name} for t in tables}

    ordered: List[str] = []
    remaining = list(names)
    # Kahn-ish: repeatedly take any table whose deps are all already placed.
    progressed = True
    while remaining and progressed:
        progressed = False
        for name in list(remaining):
            if deps[name] <= set(ordered):
                ordered.append(name)
                remaining.remove(name)
                progressed = True
    # Cycle / unresolved — append the rest in declaration order.
    ordered.extend(remaining)
    return ordered


# ---------------------------------------------------------------------------
# DDL generation.
# ---------------------------------------------------------------------------


def _column_ddl(col: ColumnSpec, table: TableSpec) -> Tuple[str, List[str]]:
    """Return (column DDL fragment, warnings)."""
    warnings: List[str] = []
    parts = [f"    {col.name:<20} {col.pg_type}"]

    if col.is_serial_pk:
        parts.append("PRIMARY KEY")
        return " ".join(parts), warnings

    if col.not_null:
        parts.append("NOT NULL")

    pg_default, warn = translate_default(col.default)
    if warn:
        warnings.append(f"{table.name}.{col.name}: {warn}")
    if pg_default is not None:
        parts.append(f"DEFAULT {pg_default}")

    if col.name in table.unique_columns:
        parts.append("UNIQUE")

    return " ".join(parts), warnings


def generate_table_ddl(table: TableSpec) -> Tuple[str, List[str]]:
    """Generate `CREATE TABLE IF NOT EXISTS` Postgres DDL for one table."""
    warnings: List[str] = []
    col_lines: List[str] = []
    for col in table.columns:
        line, warns = _column_ddl(col, table)
        col_lines.append(line)
        warnings.extend(warns)

    # Composite PK (when not a single SERIAL rowid alias).
    serial_pk = any(c.is_serial_pk for c in table.columns)
    if not serial_pk and table.pk_columns:
        col_lines.append(f"    PRIMARY KEY ({', '.join(table.pk_columns)})")

    # Foreign keys.
    for fk in table.foreign_keys:
        col_lines.append(
            f"    FOREIGN KEY ({fk.column}) "
            f"REFERENCES {fk.ref_table}({fk.ref_column})"
        )

    body = ",\n".join(col_lines)
    ddl = f"CREATE TABLE IF NOT EXISTS {table.name} (\n{body}\n);"
    return ddl, warnings


def generate_index_ddl(table: TableSpec) -> List[str]:
    """Generate `CREATE [UNIQUE] INDEX IF NOT EXISTS` statements for a table."""
    stmts: List[str] = []
    for idx in table.indexes:
        unique = "UNIQUE " if idx.unique else ""
        cols = ", ".join(idx.columns)
        stmts.append(
            f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} "
            f"ON {table.name} ({cols});"
        )
    return stmts


def generate_postgres_ddl(tables: Sequence[TableSpec]) -> Tuple[str, List[str]]:
    """
    Generate the complete PostgreSQL schema DDL (tables then indexes), ordered
    FK-safe. Returns (ddl_text, warnings).
    """
    order = topo_sort_tables(tables)
    by_name = {t.name: t for t in tables}
    warnings: List[str] = []

    blocks: List[str] = [
        "-- ============================================================",
        "-- SPA SQLite -> PostgreSQL migration DDL (generated, plan-only)",
        "-- Generated by spa_core.persistence.pg_migration",
        "-- ============================================================",
        "",
    ]
    for name in order:
        table = by_name[name]
        ddl, warns = generate_table_ddl(table)
        warnings.extend(warns)
        blocks.append(ddl)
        blocks.append("")

    blocks.append("-- Indexes")
    for name in order:
        for stmt in generate_index_ddl(by_name[name]):
            blocks.append(stmt)

    return "\n".join(blocks) + "\n", warnings


# ---------------------------------------------------------------------------
# Plan assembly.
# ---------------------------------------------------------------------------


def _resolve_sqlite_path(source: Union[str, Path]) -> str:
    """Accept a path or a sqlite:/// URL and return a connectable target."""
    s = str(source)
    if s.startswith("sqlite:///"):
        s = s[len("sqlite:///"):]
    elif s.startswith("sqlite://"):
        s = s[len("sqlite://"):]
    if s == ":memory:" or s == "":
        return ":memory:"
    return s


def _default_sqlite_path() -> str:
    """Resolve the SQLite path from SPA_DATABASE_URL, falling back to spa.db."""
    env = os.environ.get("SPA_DATABASE_URL", "").strip()
    if env and env.startswith("sqlite"):
        return _resolve_sqlite_path(env)
    # Canonical on-disk location used by spa_core.database.db_url.
    return str(Path(__file__).resolve().parents[1] / "database" / "spa.db")


def build_migration_plan(
    source: Optional[Union[str, Path, sqlite3.Connection]] = None,
    *,
    count_rows: bool = True,
) -> MigrationPlan:
    """
    Introspect `source` SQLite DB and assemble a full `MigrationPlan`.

    If `source` is None the SQLite path is resolved from `SPA_DATABASE_URL`
    (or the default `spa_core/database/spa.db`).
    """
    if source is None:
        source = _default_sqlite_path()

    tables = introspect_sqlite(source)
    if not tables:
        raise MigrationPlanError("No user tables found in SQLite source.")

    order = topo_sort_tables(tables)
    ddl, warnings = generate_postgres_ddl(tables)

    row_counts: dict = {}
    if count_rows:
        row_counts = _count_rows(source, [t.name for t in tables])

    return MigrationPlan(
        tables=tables,
        copy_order=order,
        ddl=ddl,
        row_counts=row_counts,
        warnings=warnings,
    )


def _count_rows(
    source: Union[str, Path, sqlite3.Connection], table_names: Iterable[str]
) -> dict:
    own = not isinstance(source, sqlite3.Connection)
    conn = sqlite3.connect(_resolve_sqlite_path(source)) if own else source
    counts: dict = {}
    try:
        for name in table_names:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM '{name}'")
                counts[name] = int(cur.fetchone()[0])
            except sqlite3.Error:
                counts[name] = None
        return counts
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# SQL statement splitting (for execution / dry-run reporting).
# ---------------------------------------------------------------------------


def split_sql_statements(ddl: str) -> List[str]:
    """
    Split a generated DDL blob into individual executable statements.

    Comment-only lines (``-- ...``) and blank fragments are dropped. Splitting
    is on the statement-terminating semicolon; SPA's generated DDL never embeds
    a semicolon inside a literal, so a simple split is safe here (the planner is
    the only producer of this text).
    """
    statements: List[str] = []
    for chunk in ddl.split(";"):
        # Strip whole-line SQL comments, keep the actual statement body.
        lines = [
            ln for ln in chunk.splitlines()
            if ln.strip() and not ln.strip().startswith("--")
        ]
        stmt = "\n".join(lines).strip()
        if stmt:
            statements.append(stmt + ";")
    return statements


# ---------------------------------------------------------------------------
# Migration execution (SPA-V341).
#
# V331 shipped this as plan-only. V341 implements a *gated* execution path:
# the function still refuses to do anything unless the operator both sets
# SPA_PG_MIGRATION_EXECUTE=1 AND passes i_understand_this_writes_data=True.
# Even past that gate the default is `dry_run=True`, so the default behaviour
# is to REPORT the ordered DDL + per-table copy plan without opening a single
# write transaction. Actually mutating a live Postgres requires the explicit
# dry_run=False. The PostgreSQL driver is dependency-injected (connection_
# factory) so the whole path is unit-testable offline with a fake DB-API
# connection and never hard-depends on psycopg2.
# ---------------------------------------------------------------------------


def _default_pg_connection_factory(pg_url: str):  # pragma: no cover - needs a live DB
    """Lazily import psycopg2 and open a connection. Only used for real runs."""
    try:
        import psycopg2  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise MigrationExecutionBlocked(
            "psycopg2 is required for a real (dry_run=False) migration run but "
            "is not installed. Install psycopg2-binary or pass connection_factory."
        ) from exc
    return psycopg2.connect(pg_url)


def execute_migration(
    plan: MigrationPlan,
    pg_url: str,
    *,
    i_understand_this_writes_data: bool = False,
    sqlite_source: Optional[Union[str, Path, sqlite3.Connection]] = None,
    connection_factory=None,
    dry_run: bool = True,
    batch_size: int = 500,
) -> dict:
    """
    Apply `plan` to a PostgreSQL instance (SPA-V341 gated execution path).

    Safety gates (all must hold to do anything beyond raising):
      1. ``SPA_PG_MIGRATION_EXECUTE=1`` in the environment, AND
      2. ``i_understand_this_writes_data=True``.
    Failing either raises :class:`MigrationExecutionBlocked`, exactly as V331.

    Even past the gate the default ``dry_run=True`` performs NO writes — it
    returns the ordered list of DDL statements and the per-table copy plan
    (with row counts when a `sqlite_source` is available). Pass
    ``dry_run=False`` to actually open a transaction, apply the DDL and copy
    rows table-by-table in FK-safe order.

    Parameters
    ----------
    plan:
        A :class:`MigrationPlan` from :func:`build_migration_plan`.
    pg_url:
        PostgreSQL DSN/URL (passed to the connection factory on a real run).
    sqlite_source:
        Source SQLite DB (path, ``sqlite:///`` URL, or open connection) to read
        rows from during the data copy. Required when ``dry_run=False``.
    connection_factory:
        Callable ``(pg_url) -> DBAPI connection``. Injected for tests; defaults
        to a lazily-imported ``psycopg2.connect``.
    dry_run:
        When True (default) nothing is written — a plan dict is returned.
    batch_size:
        Rows per ``executemany`` batch during the copy.

    Returns
    -------
    dict
        Summary: ``{dry_run, ddl_statements, copy_order, rows_copied,
        rows_planned, committed}``.
    """
    env_ok = os.environ.get("SPA_PG_MIGRATION_EXECUTE", "") == "1"
    if not (i_understand_this_writes_data and env_ok):
        raise MigrationExecutionBlocked(
            "Migration execution is disabled. To enable a reviewed run set "
            "SPA_PG_MIGRATION_EXECUTE=1 and pass i_understand_this_writes_data=True. "
            f"(env_set={env_ok}, opt_in={i_understand_this_writes_data})"
        )

    statements = split_sql_statements(plan.ddl)
    by_name = {t.name: t for t in plan.tables}
    # Honour the plan's FK-safe order, but only for tables we actually have.
    copy_order = [n for n in plan.copy_order if n in by_name]

    result: dict = {
        "dry_run": bool(dry_run),
        "ddl_statements": statements,
        "copy_order": copy_order,
        "rows_planned": dict(plan.row_counts),
        "rows_copied": {},
        "committed": False,
    }

    # ---- Dry run: report only, never connect, never write. ----------------
    if dry_run:
        return result

    # ---- Real run: a SQLite source is mandatory to copy rows. -------------
    if sqlite_source is None:
        raise MigrationPlanError(
            "dry_run=False requires sqlite_source to copy data from."
        )

    factory = connection_factory or _default_pg_connection_factory
    pg_conn = factory(pg_url)

    # SQLite read connection (do NOT close a caller-supplied connection).
    own_sqlite = not isinstance(sqlite_source, sqlite3.Connection)
    sconn = (
        sqlite3.connect(_resolve_sqlite_path(sqlite_source))
        if own_sqlite
        else sqlite_source
    )
    sconn.row_factory = sqlite3.Row

    try:
        cur = pg_conn.cursor()
        # 1) Apply schema DDL (idempotent: CREATE TABLE/INDEX IF NOT EXISTS).
        for stmt in statements:
            cur.execute(stmt)

        # 2) Copy data table-by-table in FK-safe order.
        for table in copy_order:
            spec = by_name[table]
            col_names = [c.name for c in spec.columns]
            quoted_cols = ", ".join(col_names)
            placeholders = ", ".join(["%s"] * len(col_names))
            insert_sql = (
                f"INSERT INTO {table} ({quoted_cols}) VALUES ({placeholders})"
            )

            copied = 0
            batch: List[tuple] = []
            select_sql = f"SELECT {quoted_cols} FROM '{table}'"
            for row in sconn.execute(select_sql):
                batch.append(tuple(row[c] for c in col_names))
                if len(batch) >= batch_size:
                    cur.executemany(insert_sql, batch)
                    copied += len(batch)
                    batch = []
            if batch:
                cur.executemany(insert_sql, batch)
                copied += len(batch)
            result["rows_copied"][table] = copied

        pg_conn.commit()
        result["committed"] = True
        return result
    except Exception:
        # Best-effort rollback; never mask the original error.
        try:
            pg_conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            pg_conn.close()
        except Exception:
            pass
        if own_sqlite:
            try:
                sconn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m spa_core.persistence.pg_migration",
        description="Prepare (plan-only) a SQLite -> PostgreSQL migration.",
    )
    p.add_argument("--plan", action="store_true", help="Print the migration plan.")
    p.add_argument("--ddl-only", action="store_true", help="Print only the generated DDL.")
    p.add_argument("--json", action="store_true", help="Print the plan summary as JSON.")
    p.add_argument("--sqlite", default=None, help="Path or sqlite:/// URL of the source DB.")
    p.add_argument("--no-counts", action="store_true", help="Skip row counting.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        plan = build_migration_plan(args.sqlite, count_rows=not args.no_counts)
    except MigrationPlanError as e:
        print(f"ERROR: {e}")
        return 2

    if args.ddl_only:
        print(plan.ddl)
        return 0

    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
        return 0

    # Default / --plan: human-readable summary.
    print("SPA SQLite -> PostgreSQL migration plan (PLAN ONLY — nothing executed)")
    print("=" * 70)
    print(f"Tables ({len(plan.tables)}), copy order (FK-safe):")
    for name in plan.copy_order:
        rc = plan.row_counts.get(name)
        rc_s = "?" if rc is None else str(rc)
        print(f"  - {name:<24} rows={rc_s}")
    if plan.warnings:
        print("\nWarnings:")
        for w in plan.warnings:
            print(f"  ! {w}")
    print("\n--- Generated DDL ---")
    print(plan.ddl)
    print("Note: run with --ddl-only to capture just the SQL. Execution is blocked.")
    return 0


__all__ = [
    "MigrationPlanError",
    "MigrationExecutionBlocked",
    "ColumnSpec",
    "ForeignKeySpec",
    "IndexSpec",
    "TableSpec",
    "MigrationPlan",
    "sqlite_affinity",
    "map_sqlite_type",
    "translate_default",
    "introspect_sqlite",
    "topo_sort_tables",
    "generate_table_ddl",
    "generate_index_ddl",
    "generate_postgres_ddl",
    "build_migration_plan",
    "split_sql_statements",
    "execute_migration",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
