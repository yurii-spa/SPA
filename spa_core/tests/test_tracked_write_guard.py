"""Сторож записи в git-tracked состояние: судья храповика и разбор базы.

Поведение сторожа на живом прогоне видно в его отчёте; здесь — контроль ЛОГИКИ, по
которой отчёт превращается в отказ, в обе стороны (инв. #16, ADR-333 п. 3).
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "spa_tracked_write_guard_ut", Path(__file__).resolve().parent / "tracked_write_guard.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def test_module_outside_baseline_is_a_violation():
    assert g.judge({"tests/test_new.py": {"data/x.json"}}, {}) == [("tests/test_new.py", ["data/x.json"])]


def test_new_file_for_a_baselined_module_is_a_violation():
    base = {"tests/test_old.py": {"data/a.json"}}
    assert g.judge({"tests/test_old.py": {"data/a.json", "data/b.json"}}, base) == [
        ("tests/test_old.py", ["data/b.json"])]


def test_within_baseline_is_not_a_violation():
    base = {"tests/test_old.py": {"data/a.json"}}
    assert g.judge({"tests/test_old.py": {"data/a.json"}}, base) == []


def test_live_baseline_parses_and_every_entry_names_files():
    base = g.load_baseline()
    assert base and all(files for files in base.values())


def test_fixed_module_is_not_in_the_baseline():
    """Модуль, починенный при введении, в базу не попадает (иначе починка не держится)."""
    assert ("spa_core/tests/test_defi_protocol_fixed_vs_floating_yield_decision_analyzer.py"
            not in g.load_baseline())
