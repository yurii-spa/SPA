"""Замок хранилища Problem: запись RCA не теряется в ход agent_health и не стирает его.

Замер 27.10: у `data/problems.json` два писателя «прочитать → изменить → записать» —
ежечасный `run_once` и `record_rca` — и ни одного замка. `atomic_save` защищает файл от
порчи, но не от потерянного обновления: RCA, записанный между load и save хода, исчезал
молча (или ход стирал его). Тесты гоняют НАСТОЯЩИЕ функции модуля на временном каталоге.
"""
import json
import threading
import time

import pytest

from spa_core.monitoring import problem_store as ps

PID = "com.spa.example.stale_log"


def _seed(tmp_path):
    key = ps.problem_key("com.spa.example", "stale_log")
    ps.save_store(tmp_path, {"problems": {key: {
        "problem_id": PID, "agent": "com.spa.example", "cause_code": "stale_log",
        "status": "MITIGATED", "rca": None, "recent_observations": []}}})
    return key


def test_rca_written_during_a_concurrent_tick_survives_the_tick(tmp_path):
    key = _seed(tmp_path)
    tick_loaded = threading.Event()

    def tick():  # то, что делает ход run_once: load → (работа) → save, под замком
        with ps.store_lock(tmp_path):
            store = ps.load_store(tmp_path)
            tick_loaded.set()
            time.sleep(0.4)
            store["problems"][key]["occurrences"] = 7
            ps.save_store(tmp_path, store)

    t = threading.Thread(target=tick)
    t.start()
    assert tick_loaded.wait(5)
    ps.record_rca(tmp_path, problem_id=PID, cause="причина", fix_ref="x", regression_test="y")
    t.join(5)
    p = json.loads((tmp_path / ps.OUTPUT_FILENAME).read_text())["problems"][key]
    assert p["occurrences"] == 7, "ход стёрт"
    assert p["rca"] and p["rca"]["cause"] == "причина", "RCA потерян"


def test_held_lock_refuses_instead_of_writing_blind(tmp_path, monkeypatch):
    key = _seed(tmp_path)
    monkeypatch.setattr(ps, "LOCK_TIMEOUT_S", 0.3)
    before = (tmp_path / ps.OUTPUT_FILENAME).read_bytes()
    holder_in, release = threading.Event(), threading.Event()

    def holder():
        with ps.store_lock(tmp_path):
            holder_in.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    assert holder_in.wait(5)
    try:
        with pytest.raises(ps.StoreLockTimeout):
            ps.record_rca(tmp_path, problem_id=PID, cause="c")
        rep = ps.run_once(tmp_path, create_cards=False)
        assert "StoreLockTimeout" in rep.get("error", ""), rep
        assert rep["written"] is False
    finally:
        release.set()
        t.join(5)
    assert (tmp_path / ps.OUTPUT_FILENAME).read_bytes() == before, "запись мимо замка"
    assert json.loads(before)["problems"][key]["rca"] is None


def test_every_load_modify_save_in_the_module_runs_under_the_lock():
    """Структурный сторож: новый писатель «load … save» без замка краснит здесь."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(ps))
    unlocked = []
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        calls = {c.func.id for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        if {"load_store", "save_store"} <= calls and not fn.name.endswith("_locked"):
            unlocked.append(fn.name)
    assert unlocked == [], unlocked
