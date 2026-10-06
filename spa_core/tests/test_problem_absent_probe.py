"""`problem_absent` — проба C6 (ADR-580 §C6, `.claude/rules/acceptance.md` п.3).

Контроль в обе стороны (acceptance.md п.3): зелена на закрытой Problem, красна на
открытой, и не проходит подстрокой (ADR-333).
"""
from __future__ import annotations

from pathlib import Path

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import problem_store as ps


def _store(data_dir: Path, problems: dict) -> None:
    ps.save_store(data_dir, {"problems": problems})


def test_problem_absent_is_registered():
    assert "problem_absent" in ca.PROBES
    assert ca.validate_spec("problem_absent:com.spa.x.exit_nonzero_1") is None


def test_green_on_a_closed_problem(tmp_path):
    pid = "com.spa.x.exit_nonzero_1"
    _store(tmp_path, {"k": {"problem_id": pid, "status": ps.STATUS_CLOSED,
                           "consecutive_absences": 3}})
    verdict, detail = ca.run_probe(f"problem_absent:{pid}", data_dir=str(tmp_path))
    assert verdict == ca.SATISFIED, detail


def test_red_on_an_open_problem(tmp_path):
    pid = "com.spa.x.exit_nonzero_1"
    _store(tmp_path, {"k": {"problem_id": pid, "status": ps.STATUS_OPEN}})
    verdict, detail = ca.run_probe(f"problem_absent:{pid}", data_dir=str(tmp_path))
    assert verdict == ca.NOT_SATISFIED, detail


def test_red_on_a_mitigated_problem_no_rca_yet(tmp_path):
    pid = "com.spa.x.exit_nonzero_1"
    _store(tmp_path, {"k": {"problem_id": pid, "status": ps.STATUS_MITIGATED}})
    verdict, _ = ca.run_probe(f"problem_absent:{pid}", data_dir=str(tmp_path))
    assert verdict == ca.NOT_SATISFIED


def test_unmeasured_when_problems_json_absent(tmp_path):
    verdict, detail = ca.run_probe("problem_absent:whatever", data_dir=str(tmp_path))
    assert verdict == ca.UNMEASURED, detail


def test_unmeasured_when_id_not_found(tmp_path):
    _store(tmp_path, {"k": {"problem_id": "com.spa.other.cause", "status": ps.STATUS_CLOSED}})
    verdict, detail = ca.run_probe("problem_absent:com.spa.x.cause", data_dir=str(tmp_path))
    assert verdict == ca.UNMEASURED, detail


def test_unmeasured_when_arg_is_empty():
    verdict, _ = ca.run_probe("problem_absent", data_dir="/nonexistent")
    assert verdict == ca.UNMEASURED


def test_exact_match_not_substring_adr_333(tmp_path):
    """Контроль наоборот: id-подстрока закрытой Problem не должна зеленить чужую пробу."""
    _store(tmp_path, {"k": {"problem_id": "com.spa.x.exit_nonzero_1_extra",
                           "status": ps.STATUS_CLOSED}})
    verdict, detail = ca.run_probe("problem_absent:com.spa.x.exit_nonzero_1", data_dir=str(tmp_path))
    assert verdict == ca.UNMEASURED, detail


def test_probe_tree_inputs_declares_data_dir():
    assert "data_dir" in ca.probe_tree_inputs("problem_absent")
