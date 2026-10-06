"""spa_core/tests/test_company_truth_import_ratchet.py — RM-TRUTH-01 / ADR-580 Director OS v2
design §1 rule 3: "No consumer except the server." Only ``mission_control.py`` (the one caller)
and WP1's own named test files (this module, the ``test_mission_*`` files, and the five unit-test
files for company_truth's pure helpers) may import ``spa_core.studio_os.company_truth``.

Positive control: a planted importer in a disposable tree turns the check red and names the
file — proving the AST scan actually looks, not just that nothing happens to import it today.
The baseline is empty and can only shrink (same ratchet discipline as every other baseline file
in this repo — ``.claude/rules/*.md``: dописывать запрещено).
"""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ALLOWED_IMPORTERS = {
    REPO / "spa_core" / "studio_os" / "mission_control.py",
}
ALLOWED_PREFIXES = (
    "test_company_truth",
    "test_mission_",
)
#: WP1's own unit-test files for the pure helpers inside company_truth.py (typed_fleet,
#: claude_work, decisions_triage, readiness-scope re-projection, the three backup facts).
#: Named explicitly (not a broad prefix) — the whole point of this ratchet is a NARROW list.
ALLOWED_TEST_FILENAMES = {
    "test_scoped_readiness_never_collapsed.py",
    "test_typed_fleet_counts.py",
    "test_claude_work_derivation.py",
    "test_backups_three_facts.py",
    "test_decisions_triage.py",
}


def _imports_company_truth(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "company_truth" in node.module:
                return True
            if any("company_truth" in a.name for a in node.names):
                return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "company_truth" in alias.name:
                    return True
    return False


def _scan(roots: list[Path]) -> list[Path]:
    hits = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if p in ALLOWED_IMPORTERS:
                continue
            if p.parent.name == "tests" and (p.name.startswith(ALLOWED_PREFIXES) or p.name in ALLOWED_TEST_FILENAMES):
                continue
            if p.name == "company_truth.py":
                continue
            if _imports_company_truth(p):
                hits.append(p)
    return hits


def test_no_module_outside_mission_control_imports_company_truth():
    hits = _scan([REPO / "spa_core", REPO / "scripts", REPO / "studio_shell"])
    assert hits == [], [str(h.relative_to(REPO)) for h in hits]


def test_positive_control_a_planted_importer_is_caught_and_named(tmp_path):
    """The scan itself is not a decoration: plant a real importer in a disposable tree and
    confirm it turns red and is NAMED, not merely "something failed somewhere"."""
    pkg = tmp_path / "spa_core" / "studio_os"
    pkg.mkdir(parents=True)
    bad = pkg / "unauthorized_reader.py"
    bad.write_text("from spa_core.studio_os import company_truth\n\nx = company_truth.SCHEMA\n", encoding="utf-8")
    good = pkg / "unrelated.py"
    good.write_text("x = 1\n", encoding="utf-8")
    hits = _scan([tmp_path / "spa_core"])
    assert hits == [bad], [str(h) for h in hits]


def test_baseline_is_empty_and_the_allow_list_is_narrow():
    """The ratchet baseline for this class is EMPTY (unlike site_numbers_baseline.json etc. —
    there is nothing grandfathered here because the module is brand new). Growing the allow-list
    beyond the one caller + its own tests is the same defect the ratchet exists to catch."""
    assert ALLOWED_IMPORTERS == {REPO / "spa_core" / "studio_os" / "mission_control.py"}
    assert len(ALLOWED_TEST_FILENAMES) == 5, "grew without a deliberate edit to this test too"
