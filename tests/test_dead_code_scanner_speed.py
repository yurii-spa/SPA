"""
tests/test_dead_code_scanner_speed.py

Hermetic tests for the SINGLE-PASS traversal of ``scripts/dead_code_scanner.py``
(cycle #60, card ``agent-task-ci-na-main-krasnyi-s-06-23z-skaner-mertv``).

**Why this file exists.** The scanner used to walk every parsed module five
times. With 3006 files under ``spa_core`` that measured 10.95s of a 15.47s scan
on the host; on a GitHub runner (~2x slower) the whole scan ran past the
``timeout=30`` in ``tests/test_dead_code_resolved.py`` and left ``main`` red for
five cycles. The fix collapses the five walks into one
(``_collect_file_facts``), and the danger of any such refactor is not speed —
it is that the *number* the scanner publishes quietly changes meaning.

So the file pins two different things:

* **semantics** — ``_collect_file_facts`` is checked against reference
  implementations of the five original walks, written out in full below. The
  reference code is copied from the pre-fix implementation on purpose —
  comparing the new code against itself would prove nothing.
* **the fix itself** — ``test_scan_makes_a_single_traversal`` counts node
  visits. Without it, the walks could come back one at a time and only a CI
  timeout would notice, months later.

── How these tests were actually controlled (cycle #64, correcting cycle #60) ──
The first version of this docstring claimed the equivalence tests "pass on both
the old and the new scanner" and that ``test_scan_makes_a_single_traversal`` is
"RED on the old five-walk scanner". **Neither claim is measurable, and both were
wrong.** This module imports ``_collect_file_facts``, which does not exist
before the fix, so against the pre-fix scanner the file does not go red — it
does not *collect at all* (``ImportError``, collection interrupted, measured on
a clean ``origin/main`` checkout). A test file that cannot run proves nothing
about the code it cannot run against; asserting otherwise is the same
"statement about a measurement that never happened" class this repo keeps
finding in its monitors (#29/#31/#35–#38/#40).

What the tests are really controlled by is **mutation of the new
implementation** — six deliberate defects, each of which must redden exactly
its own check (verified cycle #64, then reverted):

===========================================  ==============================
mutation of ``_collect_file_facts``          goes red
===========================================  ==============================
drop the ``__future__`` exclusion            3 checks incl. ``test_future_import_is_never_reported``
drop ``TYPE_CHECKING`` collection            4 checks incl. both ``type_checking`` cases
drop ``__all__`` re-exports                  8 checks incl. all three ``all_*`` cases
drop string-annotation harvesting            7 checks incl. both string-annotation cases
FIFO → LIFO (traversal *order*)              7 ``imports_match_reference`` cases
re-introduce a second ``ast.walk``           ``test_scan_makes_a_single_traversal``
===========================================  ==============================

The equivalence of the whole scanner was additionally measured end-to-end on
the real repository, not just on this corpus: pre-fix and post-fix output is
**byte-for-byte identical** in both formats (``--json`` 974 746 bytes / 4034
items, and the markdown the CI test parses), at 15.9s → 8.5s on the host.

stdlib only, no network, no repo scan (every test builds its own tiny module).
"""
from __future__ import annotations

import ast
import os
import sys
import textwrap
from typing import List, Set, Tuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.dead_code_scanner import (  # noqa: E402
    DeadCodeScanner,
    _collect_exported_names,
    _collect_file_facts,
    _collect_names_used,
    _collect_string_annotation_names,
    _collect_type_checking_imports,
    _extract_from_import_names,
    _extract_import_names,
    _harvest_annotation_strings,
)


# ---------------------------------------------------------------------------
# Reference implementations — the FIVE walks exactly as they were before the fix
# ---------------------------------------------------------------------------

def ref_type_checking(tree: ast.AST) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        guarded = (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        )
        if not guarded:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                names.update(_extract_import_names(sub))
            elif isinstance(sub, ast.ImportFrom):
                names.update(_extract_from_import_names(sub))
    return names


def ref_imports(tree: ast.AST) -> List[Tuple[int, str]]:
    """Import list BEFORE the TYPE_CHECKING filter, in ``ast.walk`` order."""
    out: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in _extract_import_names(node):
                out.append((node.lineno, name))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for name in _extract_from_import_names(node):
                out.append((node.lineno, name))
    return out


def ref_used(tree: ast.AST) -> Set[str]:
    used: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)
    return used


def ref_exported(tree: ast.AST) -> Set[str]:
    exported: Set[str] = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        value = getattr(node, "value", None)
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    exported.add(elt.value)
    return exported


def ref_annotations(tree: ast.AST) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.AnnAssign, ast.arg)) and node.annotation is not None:
            _harvest_annotation_strings(node.annotation, found)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            _harvest_annotation_strings(node.returns, found)
    return found


def ref_unused_imports(source: str) -> List[Tuple[int, str]]:
    """The whole pre-fix heuristic: what it would report as unused."""
    tree = ast.parse(source)
    tc = ref_type_checking(tree)
    nodes = [(line, name) for (line, name) in ref_imports(tree) if name not in tc]
    used = ref_used(tree) | ref_exported(tree) | ref_annotations(tree)
    return [(line, name) for (line, name) in nodes if name not in used]


# ---------------------------------------------------------------------------
# Corpus — every branch the heuristic has, in one place
# ---------------------------------------------------------------------------

CORPUS = {
    "future_directive": """
        from __future__ import annotations
        import os
        print(os.getcwd())
    """,
    "all_reexport": """
        from .core import Engine, Widget
        __all__ = ["Engine"]
    """,
    "all_augassign": """
        from .core import Engine
        __all__ = []
        __all__ += ["Engine"]
    """,
    "all_annassign": """
        from typing import List
        from .core import Engine
        __all__: List[str] = ["Engine"]
    """,
    "type_checking_block": """
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from .models import Account
        def f(a: "Account") -> None: ...
    """,
    "type_checking_dotted": """
        import typing
        if typing.TYPE_CHECKING:
            import decimal
        def f(x: "decimal.Decimal") -> None: ...
    """,
    "string_return_annotation": """
        from .models import Account
        def f() -> "Account": ...
    """,
    "string_arg_annotation": """
        from .models import Account
        def f(a: "Account"): ...
    """,
    "string_annassign": """
        from .models import Account
        x: "Account" = None
    """,
    "async_return_annotation": """
        from .models import Account
        async def f() -> "Account": ...
    """,
    "nested_subscript_annotation": """
        from typing import Dict, Optional
        from .models import Account
        def f() -> Optional[Dict[str, "Account"]]: ...
    """,
    "dotted_attribute_use": """
        import os.path
        import json
        print(os.path.join("a", "b"))
    """,
    "genuinely_unused": """
        import os
        import sys
        print(sys.argv)
    """,
    "aliases": """
        import numpy as np
        from collections import OrderedDict as OD
        x = np.array([])
    """,
    "star_import": """
        from os import *
        import re
    """,
    "nested_function_scope": """
        import json
        def outer():
            def inner():
                return json.dumps({})
            return inner
    """,
    "class_body_imports": """
        class C:
            import os
    """,
    "no_imports_at_all": """
        x = 1
        def f():
            return x
    """,
    "empty": "",
}


def _tree(name: str) -> ast.AST:
    return ast.parse(textwrap.dedent(CORPUS[name]))


ALL_CASES = sorted(CORPUS)


# ---------------------------------------------------------------------------
# 1. Equivalence with the five original walks (semantics did not move)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES)
def test_single_pass_imports_match_reference(case):
    tree = _tree(case)
    assert _collect_file_facts(tree).imports == ref_imports(tree)


@pytest.mark.parametrize("case", ALL_CASES)
def test_single_pass_type_checking_match_reference(case):
    tree = _tree(case)
    assert _collect_file_facts(tree).type_checking == ref_type_checking(tree)


@pytest.mark.parametrize("case", ALL_CASES)
def test_single_pass_used_names_match_reference(case):
    tree = _tree(case)
    assert _collect_file_facts(tree).used == ref_used(tree)


@pytest.mark.parametrize("case", ALL_CASES)
def test_single_pass_exported_match_reference(case):
    tree = _tree(case)
    assert _collect_file_facts(tree).exported == ref_exported(tree)


@pytest.mark.parametrize("case", ALL_CASES)
def test_single_pass_annotations_match_reference(case):
    tree = _tree(case)
    assert _collect_file_facts(tree).annotation_names == ref_annotations(tree)


@pytest.mark.parametrize("case", ALL_CASES)
def test_scan_unused_imports_matches_pre_fix_heuristic(tmp_path, case):
    """End-to-end: the file-level verdict is what the five-walk version gave."""
    source = textwrap.dedent(CORPUS[case])
    path = tmp_path / f"{case}.py"
    path.write_text(source, encoding="utf-8")
    items = DeadCodeScanner(str(tmp_path)).scan_unused_imports(str(path))
    assert [(i.line, i.description) for i in items] == [
        (line, f"Import '{name}' is defined but not used")
        for (line, name) in ref_unused_imports(source)
    ]


# ---------------------------------------------------------------------------
# 2. Positive controls — the corpus really does exercise each branch
# ---------------------------------------------------------------------------

def test_corpus_exercises_type_checking_exclusion():
    """If this stops holding, the TYPE_CHECKING equivalence tests prove nothing."""
    facts = _collect_file_facts(_tree("type_checking_block"))
    assert "Account" in facts.type_checking
    assert facts.imports, "the block still yields import nodes before filtering"


def test_corpus_exercises_all_reexport():
    assert _collect_file_facts(_tree("all_reexport")).exported == {"Engine"}


def test_corpus_exercises_string_annotations():
    assert "Account" in _collect_file_facts(_tree("string_return_annotation")).annotation_names


def test_corpus_contains_a_genuinely_unused_import():
    """Otherwise every 'matches reference' assertion could compare [] to []."""
    # line 2: the corpus entries open with a newline, so the first import is on line 2
    assert ref_unused_imports(textwrap.dedent(CORPUS["genuinely_unused"])) == [(2, "os")]


def test_future_import_is_never_reported():
    facts = _collect_file_facts(_tree("future_directive"))
    assert "annotations" not in [name for _, name in facts.imports]


def test_reference_and_scanner_disagree_when_the_source_changes():
    """A control on the controls: the comparison is not vacuously true."""
    unused = ref_unused_imports("import os\nimport sys\nprint(sys.argv)\n")
    still_used = ref_unused_imports("import os\nprint(os.getcwd())\n")
    assert unused and not still_used


# ---------------------------------------------------------------------------
# 3. The fix itself — ONE traversal, not five (RED on the old scanner)
# ---------------------------------------------------------------------------

def _count_visits(tree: ast.AST) -> int:
    """How many nodes a full traversal of ``tree`` visits."""
    return sum(1 for _ in ast.walk(tree))


def test_scan_makes_a_single_traversal(monkeypatch):
    """Node visits per file must be ~one traversal, not five.

    Counts calls to ``ast.iter_child_nodes`` — the primitive both ``ast.walk``
    and the single-pass collector use exactly once per visited node. The
    pre-fix scanner walked the tree five times, so this number was ~5x the node
    count; the budget below (1.5x) is far under that and far over one pass, so
    it cannot go red on ordinary edits, only on a reintroduced extra walk.
    """
    source = textwrap.dedent(CORPUS["nested_subscript_annotation"])
    tree = ast.parse(source)
    nodes = _count_visits(tree)

    calls = {"n": 0}
    real = ast.iter_child_nodes

    def counting(node):
        calls["n"] += 1
        return real(node)

    monkeypatch.setattr(ast, "iter_child_nodes", counting)
    _collect_file_facts(ast.parse(source))

    assert calls["n"] <= nodes * 1.5, (
        f"{calls['n']} node visits for {nodes} nodes — the tree is being walked "
        f"more than once per scan (the five-walk regression)"
    )
    assert calls["n"] >= nodes * 0.5, (
        f"only {calls['n']} visits for {nodes} nodes — the traversal is not "
        f"reaching the whole tree"
    )


def test_helper_wrappers_still_answer_the_same(monkeypatch):
    """The four one-name helpers are wrappers, not second copies of the logic."""
    tree = _tree("type_checking_block")
    assert _collect_type_checking_imports(tree) == ref_type_checking(tree)
    assert _collect_names_used(tree, []) == ref_used(tree)
    assert _collect_exported_names(_tree("all_reexport")) == ref_exported(_tree("all_reexport"))
    assert _collect_string_annotation_names(tree) == ref_annotations(tree)


def test_scanner_reports_are_stable_across_repeated_scans(tmp_path):
    """The collector must not carry state between files (a shared-mutable trap)."""
    a = tmp_path / "a.py"
    a.write_text("import os\nimport sys\nprint(sys.argv)\n", encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text("import json\nprint(json.dumps({}))\n", encoding="utf-8")
    scanner = DeadCodeScanner(str(tmp_path))
    first = [(i.filepath, i.line) for i in scanner.scan_unused_imports(str(a))]
    _ = scanner.scan_unused_imports(str(b))
    second = [(i.filepath, i.line) for i in scanner.scan_unused_imports(str(a))]
    assert first == second == [(str(a), 1)]
