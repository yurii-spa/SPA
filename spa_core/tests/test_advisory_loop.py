"""Tests for the Q2-19 non-custodial advisory loop (spa_core/pilot/advisory_loop.py).

Verifies: the advisory draft carries the hard non-custodial stamps (ai_never_signs / unsigned_draft /
requires_human_execution), recommendations + refusal context are sourced from the decision log,
duplicate decisions dedupe by proof_hash, it is fail-CLOSED on an empty log, and the ISOLATION invariant
holds — the module has NO actual spa_core.execution import and loads none. No network.
"""
import importlib
import json
import re

import pytest

al = importlib.import_module("spa_core.pilot.advisory_loop")


def _log(tmp_path, rows):
    p = tmp_path / "decision_log.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def test_non_custodial_stamps_present(tmp_path):
    p = _log(tmp_path, [{"approved": True, "underlying": "susde", "shape": "fixed_carry",
                         "net_edge": "0.11", "proof_hash": "h1", "as_of": "2026-07-11",
                         "approved_size_usd": "7000"}])
    a = al.build_advisory(decisions_path=p)
    for k in ("non_custodial", "ai_never_signs", "unsigned_draft", "requires_human_execution", "no_keys_held"):
        assert a[k] is True
    assert "Safe" in a["execution_venue"]


def test_recommendations_and_refusals(tmp_path):
    rows = [
        {"approved": True, "underlying": "susde", "shape": "fixed_carry", "net_edge": "0.12",
         "proof_hash": "h1", "as_of": "2026-07-11", "approved_size_usd": "7634.69"},
        {"approved": False, "underlying": "ezeth", "shape": "fixed_carry", "net_edge": "0.6",
         "proof_hash": "h2", "as_of": "2026-07-11", "reason": "structural PEG tail"},
    ]
    a = al.build_advisory(decisions_path=_log(tmp_path, rows))
    assert a["n_recommendations"] == 1 and a["n_refusals"] == 1
    rec = a["recommendations"][0]
    assert rec["underlying"] == "susde" and rec["advisory_size_hint_usd"] == 7634.69
    assert rec["proof_hash"] == "h1" and "L4" in rec["evidence"]
    assert a["refusal_context"][0]["refused_reason"] == "structural PEG tail"


def test_dedupe_by_proof_hash(tmp_path):
    rows = [{"approved": True, "underlying": "susde", "shape": "fixed_carry", "net_edge": "0.12",
             "proof_hash": "same", "as_of": "2026-07-11", "approved_size_usd": "7000"}] * 4
    a = al.build_advisory(decisions_path=_log(tmp_path, rows))
    assert a["n_recommendations"] == 1     # 4 identical logged rows → one distinct recommendation


def test_fail_closed_empty_log(tmp_path):
    a = al.build_advisory(decisions_path=tmp_path / "missing.jsonl")
    assert a["recommendations"] == [] and a["refusal_context"] == []
    assert "fail-closed" in a["flag_reason"]
    assert a["ai_never_signs"] is True     # stamps still present on the empty draft


def test_as_of_filter(tmp_path):
    rows = [
        {"approved": True, "underlying": "a", "shape": "s", "net_edge": "0.1", "proof_hash": "p1",
         "as_of": "2026-07-10", "approved_size_usd": "1"},
        {"approved": True, "underlying": "b", "shape": "s", "net_edge": "0.1", "proof_hash": "p2",
         "as_of": "2026-07-11", "approved_size_usd": "1"},
    ]
    a = al.build_advisory(decisions_path=_log(tmp_path, rows), as_of="2026-07-10")
    assert a["as_of"] == "2026-07-10"
    assert [r["underlying"] for r in a["recommendations"]] == ["a"]


def test_isolation_no_execution_import_source():
    """The advisory producer must have NO actual spa_core.execution import statement (the docstring's
    descriptive mention does not count)."""
    src = open(al.__file__).read()
    assert not re.search(r"^\s*(?:from|import)\s+spa_core\.execution", src, re.M)


def test_isolation_clean_room_no_execution_loaded():
    """CLEAN-ROOM: a fresh interpreter that imports ONLY the advisory loop must NOT pull in any
    spa_core.execution module (avoids shared-process test pollution giving a false pass/fail)."""
    import subprocess
    import sys
    from pathlib import Path
    code = ("import sys;"
            "from spa_core.pilot import advisory_loop as al;"
            "al.build_advisory(decisions_path='/nonexistent');"
            "leaked=[m for m in sys.modules if m.startswith('spa_core.execution')];"
            "print('LEAK' if leaked else 'CLEAN')")
    # Run the clean-room interpreter FROM the repo root so `spa_core` is importable via cwd-on-path.
    # Without cwd, CI (where spa_core is not pip-installed, only on the repo path) raises
    # ModuleNotFoundError in the subprocess → empty stdout → a false "leak" failure.
    repo_root = str(Path(__file__).resolve().parents[2])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                       cwd=repo_root)
    assert "CLEAN" in r.stdout, f"execution leaked into the advisory import: {r.stdout} {r.stderr}"
