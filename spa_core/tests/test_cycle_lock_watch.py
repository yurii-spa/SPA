"""Сторож застрявшего замка дневного цикла — каждый тест воспроизводит РЕАЛЬНУЮ аварию.

FROZEN-DATE-OK: injected-clock — часы инъектируются (`now=` передаётся в каждую
проверку) ВМЕСТЕ с фиксированными отметками замка и лога, обе стороны закреплены;
сверх того сами даты здесь — предмет: это дословный слепок инцидентов 2026-08-08
(03:34:29Z pid 99899 и 10:04:57Z pid 98535), ради которых сторож и написан.

Порядок `.claude/rules/deployment.md`: у каждой новой проверки обязан быть
положительный контроль — тест, краснеющий на неисправленном коде. Здесь их два вида:
воспроизведение аварии (мёртвый держатель ⇒ CRITICAL) и контроль в обратную сторону
(живой держатель ⇒ тишина), плюс контроль-различитель: если живость перестанут
спрашивать вовсе, два состояния сольются и тест покраснеет.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring.cycle_lock_watch import (
    CYCLE_LOCK_FILE,
    CYCLE_LOCK_STALE_SECONDS,
    STATE_HELD_ALIVE,
    STATE_HELD_DEAD,
    STATE_HELD_EXPIRED,
    STATE_NO_LOCK,
    STATE_UNCHECKED,
    _pid_alive,
    check_cycle_lock,
    count_refusals,
)

# ── Слепок инцидента 2026-08-08 (второй за сутки) ───────────────────────────
INCIDENT_PID = 98535
INCIDENT_TS = "2026-08-08T10:04:57.941163+00:00"
INCIDENT_NOW = datetime(2026, 8, 8, 11, 13, 54, tzinfo=timezone.utc)   # замер живьём

# Дословные строки обёртки `run_daily_paper_cycle.sh` из /tmp/spa_daily_cycle.launchd.out.
WRAPPER_LOG = """\
[2026-08-08T09:52:07Z] cycle_runner exit=0
[2026-08-08T09:58:27Z] cycle_runner exit=0
[2026-08-08T10:05:38Z] cycle_runner exit=2
[2026-08-08T10:05:53Z] cycle_runner exit=2
[2026-08-08T10:16:04Z] cycle_runner exit=2
[2026-08-08T10:39:15Z] cycle_runner exit=2
[2026-08-08T11:00:00Z] cycle_runner exit=2
"""

DEAD = lambda pid: False          # noqa: E731 — держатель мёртв
ALIVE = lambda pid: True          # noqa: E731 — держатель жив
UNMEASURABLE = lambda pid: None   # noqa: E731 — живость измерить не удалось


def _write_lock(tmp_path: Path, payload, *, mtime_age_s: float = 60.0,
                now: datetime = INCIDENT_NOW) -> Path:
    """Положить замок и выставить mtime ровно на нужный возраст относительно ``now``."""
    p = tmp_path / CYCLE_LOCK_FILE
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    stamp = now.timestamp() - mtime_age_s
    os.utime(p, (stamp, stamp))
    return p


def _log(tmp_path: Path, text: str = WRAPPER_LOG) -> Path:
    p = tmp_path / "wrapper.log"
    p.write_text(text)
    return p


# ── 1. Авария: замок держит труп ────────────────────────────────────────────

def test_dead_holder_is_critical_and_names_the_corpse(tmp_path):
    """08.08 10:04:57Z — держатель pid 98535 мёртв, цикл отказывает каждому вызову.

    Положительный контроль: до этой проверки система показывала ровно то же самое,
    что при исправной работе, — жёлтое `last_exit=2`.
    """
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS},
                mtime_age_s=(INCIDENT_NOW - datetime(2026, 8, 8, 10, 4, 57,
                                                     tzinfo=timezone.utc)).total_seconds())
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path))

    assert v.state == STATE_HELD_DEAD
    assert v.severity == "CRITICAL"
    assert v.pid == INCIDENT_PID
    assert v.issue and str(INCIDENT_PID) in v.issue
    assert "МЁРТВ" in v.issue


def test_dead_holder_reports_how_long_the_cycle_stays_blocked(tmp_path):
    """Ценность сигнала — не «плохо», а «сколько ещё будет плохо»."""
    age = 69 * 60.0
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS}, mtime_age_s=age)
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path))
    assert v.clears_in_seconds == pytest.approx(CYCLE_LOCK_STALE_SECONDS - age, abs=1)
    assert "51 мин" in v.detail          # 120 − 69


def test_refusals_are_counted_from_the_moment_the_lock_was_taken(tmp_path):
    """5 отказов ПОСЛЕ взятия замка; два успешных прогона ДО него не считаются."""
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path))
    assert v.refusals_since_lock == 5
    assert "5" in v.issue


def test_refusals_before_the_lock_belong_to_a_different_incident(tmp_path):
    """Отказы ПРЕДЫДУЩЕГО инцидента (03:34Z) не приписываются текущему замку."""
    text = ("[2026-08-08T04:10:00Z] cycle_runner exit=2\n"
            "[2026-08-08T04:20:00Z] cycle_runner exit=2\n") + WRAPPER_LOG
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path, text))
    assert v.refusals_since_lock == 5


def test_unreadable_wrapper_log_is_not_measured_never_zero(tmp_path):
    """«Лога нет» ≠ «отказов не было». Ноль читался бы как «вреда нет»."""
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=tmp_path / "нет-такого-файла.log")
    assert v.refusals_since_lock is None
    assert "НЕ ИЗМЕРЕНО" in v.issue
    assert v.severity == "CRITICAL"      # труп остаётся трупом и без лога


def test_wrapper_log_read_with_no_refusals_is_an_honest_zero(tmp_path):
    """А вот прочитанный лог без отказов — честный 0, а не «не измерено»."""
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path, "[2026-08-08T10:30:00Z] cycle_runner exit=0\n"))
    assert v.refusals_since_lock == 0


# ── 2. Обратная сторона: защита сработала по делу ───────────────────────────

def test_live_holder_is_silent_refusals_are_legitimate(tmp_path):
    """Контроль в обратную сторону: живой держатель — это РАБОТАЮЩАЯ защита.

    Сторож, который кричит и здесь, за неделю научит всех себя игнорировать.
    """
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=ALIVE,
                         refusal_log=_log(tmp_path))
    assert v.state == STATE_HELD_ALIVE
    assert v.severity == "OK"
    assert v.issue is None


def test_liveness_is_actually_consulted(tmp_path):
    """Контроль-различитель: снимите вопрос о живости — и два случая сольются.

    Именно это и есть дефект, который сторож закрывает: сегодня замок судит
    ТОЛЬКО по возрасту файла, поэтому труп и работающий цикл для него одно и то же.
    """
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    dead = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                            refusal_log=_log(tmp_path))
    alive = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=ALIVE,
                             refusal_log=_log(tmp_path))
    assert dead.state != alive.state
    assert dead.severity != alive.severity


def test_no_lock_is_ok(tmp_path):
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD)
    assert v.state == STATE_NO_LOCK
    assert v.severity == "OK"
    assert v.issue is None


# ── 3. Fail-CLOSED: «не измерено» никогда не хранится как «в порядке» ───────

@pytest.mark.parametrize("payload,why", [
    ("не json вовсе", "мусор вместо json"),
    ('["pid", 1]', "json, но не объект"),
    ('{"ts": "2026-08-08T10:04:57+00:00"}', "объект без номера процесса"),
])
def test_unparseable_or_pidless_lock_is_unchecked_not_ok(tmp_path, payload, why):
    _write_lock(tmp_path, payload)
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path))
    assert v.state == STATE_UNCHECKED, why
    assert v.severity == "WARNING"
    assert v.issue and "UNCHECKED" in v.issue


def test_unmeasurable_liveness_is_unchecked_not_dead_and_not_fine(tmp_path):
    """«Измерить не удалось» — третий ответ, а не округление к одному из двух."""
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=UNMEASURABLE,
                         refusal_log=_log(tmp_path))
    assert v.state == STATE_UNCHECKED
    assert v.severity == "WARNING"
    assert v.state != STATE_HELD_DEAD


# ── 4. Протухший замок: снимется сам, но день уже стоил отказов ─────────────

def test_expired_lock_is_warning_not_critical(tmp_path):
    """Возраст судится РАНЬШЕ живости: следующий вызов снимет замок сам.

    Кричать CRITICAL о том, что починится ближайшим вызовом, — тот же cry-wolf.
    """
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS},
                mtime_age_s=CYCLE_LOCK_STALE_SECONDS + 600)
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path))
    assert v.state == STATE_HELD_EXPIRED
    assert v.severity == "WARNING"
    assert v.clears_in_seconds == 0.0
    assert v.issue and "протух" in v.issue


def test_just_inside_the_window_is_still_critical(tmp_path):
    """Граница: секунда до протухания — ещё CRITICAL (иначе окно молчания)."""
    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS},
                mtime_age_s=CYCLE_LOCK_STALE_SECONDS - 1)
    v = check_cycle_lock(tmp_path, INCIDENT_NOW, pid_alive=DEAD,
                         refusal_log=_log(tmp_path))
    assert v.state == STATE_HELD_DEAD
    assert v.severity == "CRITICAL"


# ── 5. Пороги и живость — не вторая копия правды ────────────────────────────

def test_thresholds_match_cycle_runner():
    """Копия порога в мониторе не свободна: расхождение с циклом краснит ЗДЕСЬ.

    Импортировать цикл из монитора нельзя (money-path в read-only слой, инв. #6),
    поэтому копия оправдана — но только вместе с этим тестом.
    """
    from spa_core.paper_trading import cycle_runner

    assert CYCLE_LOCK_FILE == cycle_runner.CYCLE_LOCK_FILE
    assert CYCLE_LOCK_STALE_SECONDS == cycle_runner.CYCLE_LOCK_STALE_SECONDS


def test_pid_alive_measures_a_real_process():
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_reports_a_missing_process_as_dead():
    # Заведомо свободный номер: берём большой и убеждаемся, что его нет.
    ghost = 4_194_303
    try:
        os.kill(ghost, 0)
        pytest.skip("номер занят на этой машине — проверка неинформативна")
    except ProcessLookupError:
        pass
    except OSError:
        pytest.skip("живость этого номера измерить нельзя")
    assert _pid_alive(ghost) is False


@pytest.mark.parametrize("bad", [0, -1, None])
def test_pid_alive_refuses_to_guess_on_a_nonsense_pid(bad):
    assert _pid_alive(bad) is None


def test_count_refusals_without_a_start_moment_is_not_measured(tmp_path):
    assert count_refusals(_log(tmp_path), None, INCIDENT_NOW) is None


def test_count_refusals_ignores_the_future(tmp_path):
    """Строки позже `now` — не наши: лог могли дописать после снятия среза."""
    text = WRAPPER_LOG + "[2026-08-08T23:59:59Z] cycle_runner exit=2\n"
    since = datetime(2026, 8, 8, 10, 4, 57, tzinfo=timezone.utc)
    assert count_refusals(_log(tmp_path, text), since, INCIDENT_NOW) == 5


# ── 6. Проводка: сторож должен быть СЛЫШЕН, а не лежать в модуле ────────────

def test_agent_health_surfaces_the_stuck_lock(tmp_path):
    """Мутация «убрать вызов из check_system» красит именно этот тест.

    Урок цикла #144: снятие ОДНОГО места вызова оставило 22 собственных теста
    зелёными, пока фича была мертва в проде. Проверяем эффект, а не наличие кода.
    """
    from spa_core.monitoring import agent_health_monitor as ahm

    _write_lock(tmp_path, {"pid": INCIDENT_PID, "ts": INCIDENT_TS})
    checks, status, issues = ahm.check_system(tmp_path, INCIDENT_NOW)

    assert checks.get("cycle_lock_state") == STATE_HELD_DEAD
    assert status == "CRITICAL"
    assert any(str(INCIDENT_PID) in i for i in issues)


def test_agent_health_stays_quiet_when_the_holder_is_alive(tmp_path):
    """Контроль в обратную сторону на уровне проводки: идущий цикл не краснит."""
    from spa_core.monitoring import agent_health_monitor as ahm

    _write_lock(tmp_path, {"pid": os.getpid(), "ts": INCIDENT_TS})
    checks, status, issues = ahm.check_system(tmp_path, INCIDENT_NOW)

    assert checks.get("cycle_lock_state") == STATE_HELD_ALIVE
    assert not any("cycle lock" in i for i in issues)


def test_agent_health_without_a_lock_says_nothing(tmp_path):
    from spa_core.monitoring import agent_health_monitor as ahm

    checks, _status, issues = ahm.check_system(tmp_path, INCIDENT_NOW)
    assert checks.get("cycle_lock_state") == STATE_NO_LOCK
    assert not any("cycle lock" in i for i in issues)
