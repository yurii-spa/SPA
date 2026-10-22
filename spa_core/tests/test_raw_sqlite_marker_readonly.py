"""The ``allow-raw-sqlite-connect`` marker is an exemption from the BL-008 Phase-2 scan
(`spa_core.database.migrate_callsites`). It must not become a way to hide a WRITING raw
connection: a marked ``sqlite3.connect(...)`` is accepted only when it opens the file
read-only (``file:...?mode=ro`` URI + ``uri=True``), or when it is one of the named,
reviewed exceptions below (each with its reason).

Why the marker and not ``get_connection()``: ``get_connection`` serves the MAIN database
(``DATABASE_URL``), has no read-only mode, and ``mkdir``s + creates a missing file — routing a
read-only probe of a foreign store through it would turn "store absent ⇒ named refusal" into
"silently created an empty store".
"""
from __future__ import annotations

import ast
from pathlib import Path

from spa_core.database import migrate_callsites as mc

REPO_ROOT = Path(__file__).resolve().parents[2]
SPA_CORE = REPO_ROOT / "spa_core"

#: Reviewed read-write marked opens: relative path -> reason.
RW_EXCEPTIONS = {
    "spa_core/paper_trading/cycle_runner.py":
        "sqlite-native PRAGMA integrity_check on the local mirror (pre-existing, reviewed in place)",
}


def _is_readonly_call(node: ast.Call) -> bool:
    uri_true = any(k.arg == "uri" and isinstance(k.value, ast.Constant) and k.value.value is True
                   for k in node.keywords)
    if not uri_true or not node.args:
        return False
    first = node.args[0]
    parts = []
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        parts = [first.value]
    elif isinstance(first, ast.JoinedStr):
        parts = [v.value for v in first.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    joined = "".join(parts)
    return joined.startswith("file:") and "mode=ro" in joined


def marked_connects(source: str):
    """Yield ``(lineno, readonly)`` for every marked ``sqlite3.connect`` call in *source*."""
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr == "connect" and isinstance(f.value, ast.Name)
                and f.value.id == "sqlite3" and mc._ALLOW_MARKER in lines[node.lineno - 1]):
            yield node.lineno, _is_readonly_call(node)


def _violations(root: Path):
    out, seen = [], 0
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("spa_core/tests/"):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if mc._ALLOW_MARKER not in src:
            continue
        for lineno, ro in marked_connects(src):
            seen += 1
            if not ro and rel not in RW_EXCEPTIONS:
                out.append(f"{rel}:{lineno}")
    return out, seen


def test_every_marked_raw_connect_is_readonly_or_a_named_exception():
    violations, seen = _violations(SPA_CORE)
    assert seen > 0, "no marked sqlite3.connect found at all — scan NOT MEASURED (wrong root?)"
    assert violations == [], (
        "allow-raw-sqlite-connect on a NON-read-only connect (writes must go through review, "
        "not the marker):\n" + "\n".join(violations))


def test_named_exceptions_still_exist_and_are_marked():
    """A stale exception would silently widen the allowance — each must still be a real marked call."""
    for rel in RW_EXCEPTIONS:
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert any(not ro for _, ro in marked_connects(src)), rel


def test_positive_control_marked_readwrite_connect_is_flagged():
    src = 'import sqlite3\ncon = sqlite3.connect("x.db")  # allow-raw-sqlite-connect\n'
    assert list(marked_connects(src)) == [(2, False)]


def test_positive_control_ro_uri_without_uri_flag_is_not_readonly():
    # without uri=True Python does not pass SQLITE_OPEN_URI: "file:...?mode=ro" may be taken as a plain filename, opened READ-WRITE
    src = 'import sqlite3\ncon = sqlite3.connect(f"file:{p}?mode=ro")  # allow-raw-sqlite-connect\n'
    assert list(marked_connects(src)) == [(2, False)]


def test_negative_control_marked_ro_uri_is_accepted():
    src = 'import sqlite3\ncon = sqlite3.connect(f"file:{p}?mode=ro", uri=True)  # allow-raw-sqlite-connect\n'
    assert list(marked_connects(src)) == [(2, True)]


def test_unmarked_connect_is_not_this_tests_business():
    src = 'import sqlite3\ncon = sqlite3.connect("x.db")\n'
    assert list(marked_connects(src)) == []
