"""The ≥25-scenario ACTUALLY INDUCED failure matrix for the ADR-564 (RM-EVIDENCE-01) Package E2
paper ledger (``spa_core.research_factory.failure_matrix_v2``), run through the real code and
asserted here — plus the dependency-missing discipline the task's own instructions require:
``pass=None`` is allowed ONLY while the named module genuinely cannot be imported; once it CAN
be imported, a ``None`` row is itself a failure (the matrix must have been re-run and wired, not
left stale).

No literal date lives in this file — it only calls into failure_matrix_v2.py's own NOW anchor by
reference (``fm2.NOW``), so the frozen-date ratchet does not apply here, matching the same note
in ``test_research_factory_failures.py`` for the v1 matrix.
"""
from __future__ import annotations

import importlib
import json

from spa_core.research_factory import failure_matrix_v2 as fm2


def test_at_least_25_scenarios_declared():
    assert len(fm2.CASES) >= 25
    assert len({c.id for c in fm2.CASES}) == len(fm2.CASES)  # unique ids


def test_every_scenario_names_what_it_induced():
    rows = fm2.run_all()
    for r in rows:
        assert r["induced"], f"{r['id']} names no induced condition"
        assert r["expected"] is not None
        assert "observed" in r


def test_none_rows_are_genuinely_dependency_missing_not_an_unmeasured_shortcut():
    """A ``pass=None`` row's ``observed`` must literally say 'dependency missing: <module>', and
    that module must ACTUALLY fail to import right now. A row that claims a missing dependency
    while the module is importable is the exact "unmeasured masquerading as fine" defect
    ``.claude/rules/deployment.md`` names for pyflakes/pid — caught here, not assumed away."""
    rows = fm2.run_all()
    for r in rows:
        if r["pass"] is not None:
            continue
        observed = r["observed"]
        assert isinstance(observed, str) and observed.startswith("dependency missing: "), (
            f"{r['id']}: pass=None but observed does not name a missing dependency: {observed!r}")
        module_name = observed[len("dependency missing: "):]
        imported = True
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            imported = False
        assert not imported, (
            f"{r['id']}: claims 'dependency missing: {module_name}' but that module DOES import — "
            "this scenario must be re-wired to the real pipeline now that the dependency exists, "
            "not left reporting a stale None (task instruction: re-run after integration).")


def test_every_scenario_passes():
    """The matrix's own bar: every row that is not a genuine dependency-missing ``None`` must be
    ``pass=True``. A failure here is a real, reproducible defect found by running real code —
    see the failing row's ``observed`` field for exactly what broke and why; it is NOT this
    test's job to paper over a cross-package integration gap (CLAUDE.md inv. #16)."""
    rows = fm2.run_all()
    failed = [r for r in rows if r["pass"] is False]
    assert not failed, "\n".join(f"{r['id']} {r['scenario']}: expected {r['expected']!r}, "
                                 f"observed {r['observed']!r}" for r in failed)


def test_cli_writes_json_and_returns_nonzero_on_failure(tmp_path):
    out = tmp_path / "fm2.json"
    rc = fm2.main(["--out", str(out)])
    assert out.exists()
    rows = json.loads(out.read_text())
    assert len(rows) == len(fm2.CASES)
    failed = [r for r in rows if r["pass"] is False]
    assert rc == (1 if failed else 0)


def test_cli_returns_nonzero_when_a_scenario_is_broken(tmp_path, monkeypatch):
    broken_case = fm2.Case("FM2-BROKEN", "a scenario forced to fail", lambda tmp: ("x", "y", "z", False))
    monkeypatch.setattr(fm2, "CASES", fm2.CASES + [broken_case])
    out = tmp_path / "fm2_broken.json"
    rc = fm2.main(["--out", str(out)])
    assert rc == 1


def test_a_none_scenario_does_not_count_as_failed_in_the_cli_exit_code(tmp_path, monkeypatch):
    """pass=None (dependency genuinely missing) must never flip the CLI's exit code — that would
    make "not yet integrated" indistinguishable from "broken", exactly the class CLAUDE.md's
    absent-observation invariant (#17) forbids."""
    none_case = fm2.Case("FM2-NONE", "a scenario whose dependency is missing",
                        lambda tmp: ("x", "y", "dependency missing: no.such.module", None))
    monkeypatch.setattr(fm2, "CASES", [none_case])
    out = tmp_path / "fm2_none.json"
    rc = fm2.main(["--out", str(out)])
    assert rc == 0
    rows = json.loads(out.read_text())
    assert rows[0]["pass"] is None
