"""Флот: код причины Problem следует за КЛАССОМ расхождения, а не за словом «DRIFT».

27.10: строка agent_health «fleet parity DRIFT (…)» несёт разные классы. Всё складывалось
под `retired_but_loaded`, и после починки ложного «выведенного» (карантин, f4e21f1c)
Problem продолжала бы звать живых агентов вне установщика «выведенными, но загруженными».
"""
from spa_core.monitoring import problem_store as ps


def _codes(system_issues, agents=()):
    doc = {"agents": list(agents), "system_issues": list(system_issues)}
    return {c["cause_code"]: c for c in ps._conditions_from_agent_health(doc)
            if c["agent"] == "fleet"}


def test_orphans_only_are_fleet_parity_drift_not_retired():
    c = _codes(["fleet parity DRIFT (8 orphan-plist)"])
    assert set(c) == {"fleet_parity_drift"}


def test_retired_only_keeps_its_code():
    c = _codes(["fleet parity DRIFT (5 retired-still-installed)"])
    assert set(c) == {"retired_but_loaded"}


def test_both_classes_in_one_line_open_both():
    c = _codes(["fleet parity DRIFT (5 retired-still-installed, 8 orphan-plist)"])
    assert set(c) == {"retired_but_loaded", "fleet_parity_drift"}


def test_per_agent_retired_loaded_still_folds_into_one_fleet_problem():
    agents = [{"label": "com.spa.x", "status": "WARNING",
               "issue": "retired_but_loaded — label is in RETIRED_LABELS but launchctl still has it"}]
    c = _codes([], agents)
    assert set(c) == {"retired_but_loaded"} and "com.spa.x" in c["retired_but_loaded"]["detail"]


def test_clean_fleet_opens_nothing():
    assert _codes([]) == {}
