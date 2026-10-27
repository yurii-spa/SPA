"""Прошлый сбой долгожителя стареет: ≥ 24 ч работы после перезапуска — пометка, не тревога.

27.10: `telegram_bot` упал ОДИН раз 18.10 (~16:02Z), KeepAlive поднял его, и до чистого
перезапуска 25.10 agent_health каждый час повторял `last_exit=1 (prior crash; restarted)` —
problem_store насчитал 147 «повторов» одного сбоя. Решение 05.08 («сбой не прятать») цело:
первые 24 ч — WARNING; время работы НЕ ИЗМЕРЕНО — WARNING (fail-CLOSED).
"""
from datetime import datetime, timezone

from spa_core.monitoring import agent_health_monitor as m

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — check_agent(..., NOW)
LABEL = "com.spa.telegram_bot"
PLIST = {"Label": LABEL, "KeepAlive": True, "ProgramArguments": ["/bin/bash", "x.sh"]}


def _check(uptime):
    lc = {LABEL: {"pid": 4242, "exit": 1}}
    return m.check_agent(LABEL, PLIST, True, lc, NOW,
                         proc_uptime_s=(None if uptime == "absent" else (lambda pid: uptime)))


def test_long_uptime_after_one_crash_is_a_note_not_a_warning():
    h = _check(7 * 86400.0)
    assert h.status == m.OK, (h.status, h.issue)
    assert "прошлый сбой" in (h.note or "") and "168 ч" in h.note


def test_fresh_restart_after_a_crash_still_warns():
    h = _check(3600.0)
    assert h.status == m.WARNING and "prior crash" in h.issue


def test_unmeasured_uptime_keeps_the_warning():
    for up in ("absent", None):
        h = _check(up)
        assert h.status == m.WARNING, up


def test_etime_parser_forms():
    assert m.parse_etime("05:07") == 307.0
    assert m.parse_etime("02:05:07") == 7507.0
    assert m.parse_etime("3-02:05:07") == 3 * 86400 + 7507.0
    for bad in ("", "abc", "1-2-3", "1:2:3:4", None):
        assert m.parse_etime(bad) is None


def test_hermetic_scene_never_measures_the_host():
    """Подставленный launchctl ⇒ проводка НЕ спрашивает ps о чужом pid (pid мог быть занят)."""
    import inspect
    assert "proc_uptime_s=(None if self._launchctl_output is not None" in inspect.getsource(m)
