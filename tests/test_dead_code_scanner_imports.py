"""
tests/test_dead_code_scanner_imports.py

Hermetic tests for the unused-import heuristic of ``scripts/dead_code_scanner.py``
(cycle #52, 2026-07-31 — card ``agent-unused-import-ceiling-at-its-limit``).

WHY THIS FILE EXISTS
--------------------
``tests/test_dead_code_resolved.py::TestScannerImprovement::
test_16_unused_imports_decreased`` is a ceiling over the scanner's unused-import
count. On 2026-07-31 the observed count was 4049 against a ceiling of ``< 4050``
— a margin of exactly ONE. Cycle #51 added a single new test module and CI went
red; the "unused import" that tipped it over was ``from __future__ import
annotations``, a compiler directive that by construction can never appear as a
referenced name. So the guardrail fired at a file containing no dead code at all,
and would have fired at *any* next module.

Measured composition of those 4049 (cycle #52, deterministic, whole repo):

  * 1753 (43%) — ``from __future__ import ...``
  *  137       — names re-exported through ``__all__``
  *    4       — names referenced from STRING (forward-ref) annotations
  *    1       — an import inside ``if TYPE_CHECKING:``

None of those four is dead code. After excluding them the count is 2154, and
**not one item was added** by the change — the fix can only ever remove a false
positive, never invent a finding.

These tests pin BOTH directions: the four classes stay uncounted, and genuinely
unused imports (including a mass injection — the guardrail's actual purpose)
stay counted. Every exclusion below has a positive control right next to it.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.dead_code_scanner import DeadCodeScanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan(source: str):
    """Run scan_unused_imports over `source` in a throwaway dir. Returns names."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mod.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
        items = DeadCodeScanner(base_dir=tmp).scan_unused_imports(path)
    for item in items:
        assert item.category == "unused_import"
        assert item.severity == "LOW"
    return sorted(
        i.description.split("'")[1] for i in items
    )


# ---------------------------------------------------------------------------
# 1. `from __future__ import ...` — a compiler directive, never a name
# ---------------------------------------------------------------------------

def test_future_annotations_is_not_an_unused_import():
    assert _scan("from __future__ import annotations\n\nx = 1\n") == []


def test_future_import_of_any_feature_is_not_counted():
    assert _scan("from __future__ import annotations, division\n\nx = 1\n") == []


def test_future_import_does_not_hide_a_real_dead_import_in_the_same_file():
    """POSITIVE CONTROL: the `__future__` skip must not spill onto its neighbours."""
    src = "from __future__ import annotations\nimport os\n\nx = 1\n"
    assert _scan(src) == ["os"]


def test_plain_import_of_the_future_module_is_still_counted():
    """`import __future__` binds a real, unused name — only the FROM form is a directive."""
    assert _scan("import __future__\n\nx = 1\n") == ["__future__"]


def test_reproduces_the_cycle_51_trap_a_clean_new_module_adds_nothing():
    """The exact file shape that turned CI red in cycle #51 must contribute zero."""
    src = (
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def f(x: int) -> int:\n"
        "    return x + 1\n"
    )
    assert _scan(src) == []


# ---------------------------------------------------------------------------
# 2. `__all__` re-exports — publishing a name IS using it (pyflakes convention)
# ---------------------------------------------------------------------------

def test_name_listed_in_all_is_not_an_unused_import():
    src = 'from os.path import join\n\n__all__ = ["join"]\n'
    assert _scan(src) == []


def test_all_as_a_tuple_is_honoured():
    src = 'from os.path import join\n\n__all__ = ("join",)\n'
    assert _scan(src) == []


def test_annotated_all_is_honoured():
    src = (
        "from typing import List\n"
        "from os.path import join\n"
        '\n__all__: List[str] = ["join"]\n'
    )
    assert _scan(src) == []


def test_import_absent_from_all_is_still_counted():
    """POSITIVE CONTROL: `__all__` excuses only what it actually lists."""
    src = 'from os.path import join, dirname\n\n__all__ = ["join"]\n'
    assert _scan(src) == ["dirname"]


# ---------------------------------------------------------------------------
# 3. String (forward-ref) annotations — the AST holds them as str constants
# ---------------------------------------------------------------------------

def test_forward_ref_in_return_annotation_counts_as_use():
    src = 'from decimal import Decimal\n\n\ndef f() -> "Decimal":\n    ...\n'
    assert _scan(src) == []


def test_forward_ref_in_argument_annotation_counts_as_use():
    src = 'from decimal import Decimal\n\n\ndef f(x: "Decimal") -> int:\n    return 1\n'
    assert _scan(src) == []


def test_forward_ref_nested_in_a_subscript_counts_as_use():
    src = (
        "from typing import List\n"
        "from decimal import Decimal\n"
        '\n\ndef f() -> List["Decimal"]:\n    ...\n'
    )
    assert _scan(src) == []


def test_a_name_mentioned_only_in_prose_is_still_counted():
    """POSITIVE CONTROL: docstrings are NOT annotations — no blanket string excuse.

    This is the line between the narrow fix and a lazy one: excluding every name
    that appears in any string literal would have silenced 292 items instead of 4.
    """
    src = 'from decimal import Decimal\n\n\ndef f():\n    """Returns a Decimal, honest."""\n'
    assert _scan(src) == ["Decimal"]


# ---------------------------------------------------------------------------
# 4. `if TYPE_CHECKING:` imports — the docstring always promised this
# ---------------------------------------------------------------------------

def test_type_checking_import_is_not_counted():
    src = (
        "from typing import TYPE_CHECKING\n"
        "\nif TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "\nTYPE_CHECKING\n"
    )
    assert _scan(src) == []


def test_type_checking_import_via_typing_attribute_is_not_counted():
    src = (
        "import typing\n"
        "\nif typing.TYPE_CHECKING:\n"
        "    from decimal import Decimal\n"
        "\nx = typing.Any\n"
    )
    assert _scan(src) == []


def test_the_same_import_outside_the_block_is_still_counted():
    """POSITIVE CONTROL: only the guarded block is excused."""
    src = "from decimal import Decimal\n\nx = 1\n"
    assert _scan(src) == ["Decimal"]


# ---------------------------------------------------------------------------
# 5. The guardrail still does its job — genuinely dead imports stay counted
# ---------------------------------------------------------------------------

def test_ordinary_unused_import_is_still_counted():
    assert _scan("import os\n\nx = 1\n") == ["os"]


def test_used_import_is_not_counted():
    assert _scan("import os\n\nx = os.getcwd()\n") == []


def test_mass_import_injection_is_still_caught():
    """POSITIVE CONTROL for the ceiling's stated purpose (accidental mass import).

    Fifty dead imports in one module must produce fifty findings — the exclusions
    above must not have blunted the thing the guardrail exists to catch.
    """
    src = "from __future__ import annotations\n"
    src += "".join(f"import mod_{i}\n" for i in range(50))
    src += "\nx = 1\n"
    assert len(_scan(src)) == 50


def test_line_numbers_are_preserved_for_the_findings_that_remain():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mod.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("from __future__ import annotations\nimport os\n\nx = 1\n")
        items = DeadCodeScanner(base_dir=tmp).scan_unused_imports(path)
    assert len(items) == 1
    assert items[0].line == 2  # `import os`, not the `__future__` line above it


def test_file_with_only_a_future_import_yields_no_findings():
    assert _scan("from __future__ import annotations\n") == []


def test_syntax_error_still_returns_empty():
    assert _scan("class Foo(\n    # broken\n") == []
