"""Q2-1: the defenses-exercised report drives the REAL governance code and every
defense fires at the right threshold. This pins the reproducible proof so a
regression in the kill-switch / de-risk ladder is caught in CI, not on cutover day.
"""
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "defenses_exercised_report", _ROOT / "scripts" / "defenses_exercised_report.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_every_defense_fires():
    res = _mod.run()
    assert res["all_defenses_fired"] is True, [r for r in res["scenarios"] if not r["fired"]]
    assert res["scenarios_fired"] == res["scenarios_total"]


def test_drawdown_ladder_bands():
    res = _mod.run()
    by = {r["scenario"]: r for r in res["scenarios"]}
    assert by["drawdown_2pct"]["actual"] == "NONE"
    assert by["drawdown_6pct"]["actual"] == "SOFT_DERISK"
    assert by["drawdown_8pct"]["actual"] == "SOFT_DERISK"
    assert by["drawdown_12pct"]["actual"] == "HARD_KILL"


def test_soft_derisk_blocks_new_and_increase_but_allows_reduce():
    res = _mod.run()
    by = {r["scenario"]: r for r in res["scenarios"]}
    assert by["soft_derisk_blocks_increase"]["actual"] == "40000.0"  # clamped to held
    assert by["soft_derisk_blocks_new"]["actual"] == "0.0"           # new forced to 0
    assert by["soft_derisk_allows_reduce"]["actual"] == "3000.0"     # reduce left intact


def test_hard_kill_triggers_deep_holds_shallow():
    res = _mod.run()
    by = {r["scenario"]: r for r in res["scenarios"]}
    assert by["hard_kill_at_15pct"]["actual"] == "TRIGGERED"
    assert by["hard_kill_held_at_3pct"]["actual"] == "NOT_TRIGGERED"
