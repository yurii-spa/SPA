# LLM_FORBIDDEN
"""ARB 27.10, OPEN `com.spa.resource_guard.exit_nonzero_1` (259 наблюдений): код 1 у resource_guard — ИЗМЕРЕННОЕ
предупреждение о ресурсах по его договору (0 OK · 1 WARN · 2 CRITICAL/не измерено), а не сбой агента.

Предупреждение НЕ глушится (статус WARNING), но называется своими словами; код 2 и чужие метки — как прежде.
"""
from __future__ import annotations

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring import problem_store as ps
from spa_core.tests.test_cycle_exit_taxonomy import NOW, _fresh_log, _lc

LABEL = ahm.RESOURCE_GUARD_LABEL


def _plist(tmp_path):
    return {"StartInterval": 300, "StandardOutPath": str(_fresh_log(tmp_path, "rg.log"))}


def test_exit_one_is_a_measured_warning_not_a_crash_and_stays_visible(tmp_path):
    h = ahm.check_agent(LABEL, _plist(tmp_path), True, _lc(LABEL, pid=0, exit_code=1), NOW)
    assert h.status == ahm.WARNING                          # предупреждение о памяти не скрыто
    assert "измерено WARN" in h.issue and "не сбой агента" in h.issue
    assert "last_exit=1" not in h.issue
    assert ps.cause_from_agent_issue(h.issue) != "exit_nonzero:1"


def test_exit_two_critical_or_unmeasured_stays_a_failure(tmp_path):
    h = ahm.check_agent(LABEL, _plist(tmp_path), True, _lc(LABEL, pid=0, exit_code=2), NOW)
    assert h.status == ahm.WARNING and "last_exit=2" in h.issue
    assert ps.cause_from_agent_issue(h.issue) == "exit_nonzero:2"


def test_exit_zero_is_ok(tmp_path):
    h = ahm.check_agent(LABEL, _plist(tmp_path), True, _lc(LABEL, pid=0, exit_code=0), NOW)
    assert h.status == ahm.OK and h.issue == ""


def test_the_meaning_applies_only_to_resource_guard(tmp_path):
    other = "com.spa.some_other_agent"
    h = ahm.check_agent(other, _plist(tmp_path), True, _lc(other, pid=0, exit_code=1), NOW)
    assert h.status == ahm.WARNING and "last_exit=1" in h.issue
    assert ps.cause_from_agent_issue(h.issue) == "exit_nonzero:1"


def test_the_literal_label_in_the_consumer_equals_the_constant():
    import inspect
    assert 'label == "com.spa.resource_guard"' in inspect.getsource(ahm.check_agent)
    assert ahm.RESOURCE_GUARD_LABEL == "com.spa.resource_guard"
