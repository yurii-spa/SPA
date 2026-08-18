"""Положительный контроль: РЕАЛЬНАЯ авария 2026-08-04T07:00Z воспроизводится здесь.

Каждый тест — факт из замера карточки `agent-wake-storm-fail-open-monitors`:
хост проспал 01:45–07:00 UTC, на пробуждении 27 `.launchd.err` получили
`Interrupted system call` / `getcwd: cannot access parent directories`, 40 логов —
`ModuleNotFoundError: No module named 'spa_core'`, **39 агентов отметились
одновременно в 07:00:14-15Z**, дневной цикл 06:00Z умер. Флот при этом
самовосстановился за 15 минут — и ни один сторож не сказал ни слова.

Красноту на СТАРОМ коде даёт не отсутствие модуля, а сам факт: тест
`test_recovered_fleet_is_invisible_to_the_neighbour` показывает, что
`agent_health_monitor.detect_wake_storm` — единственный существовавший ответ —
на восстановившемся флоте возвращает `None`. Вопрос «падал ли флот разом»
оставался без сторожа.

Обратная сторона (иначе сторожа выключат люди): обычный перезапуск одного агента
и разнесённые во времени одиночные сдачи тревоги НЕ поднимают.

Время — ВХОД: `now` инъектируется, метки улик заданы явно (`.claude/rules/deployment.md`,
предпочтение №1).
FROZEN-DATE-OK: injected-clock — часы передаются параметром `now`, обе стороны
закреплены; литеральные даты здесь ещё и предмет теста (исторический инцидент).
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest

from spa_core.monitoring import wake_storm_forensics as wsf
from spa_core.tests._freshness import at

# Момент шторма и момент вопроса — оба закреплены.
STORM_AT = "2026-08-04T07:00:14Z"
STORM_DT = at("2026-08-04T07:00:14+00:00")
ASKED_AT = at("2026-08-04T07:20:00+00:00")   # флот уже восстановился

FLEET_39 = [f"agent{i:02d}" for i in range(39)]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _giveup_line(agent: str, ts: str = STORM_AT) -> str:
    return (f"[{ts}] {wsf.GIVEUP_TOKEN} agent={agent} attempts=3 "
            f"last_fail=getcwd repo=/Users/x/Documents/SPA_Claude\n")


def _write(log_dir, name: str, text: str, mtime=None):
    p = log_dir / name
    p.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime.timestamp(), mtime.timestamp()))
    return p


def _storm_logs(log_dir, agents=FLEET_39, ts: str = STORM_AT):
    """Как это выглядит сегодня: обёртка сдалась с маркером, потом агент ожил."""
    for a in agents:
        _write(log_dir, f"spa_{a}.log",
               "[2026-08-04T06:59:00Z] normal work\n"
               + _giveup_line(a, ts)
               + "[2026-08-04T07:12:00Z] recovered, working again\n")


# ===========================================================================
# ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — авария целиком
# ===========================================================================
def test_39_agents_falling_in_one_minute_is_a_storm(tmp_path):
    _storm_logs(tmp_path)
    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)

    assert doc["status"] == wsf.CRITICAL, doc["reason"]
    assert doc["storm"]["count"] == 39
    assert doc["storm"]["time_sources"] == ["marker"]
    assert "РАЗОМ" in doc["reason"]


def test_storm_is_still_named_after_the_fleet_recovered(tmp_path):
    """Флот ожил за 15 минут — событие обязано остаться видимым задним числом."""
    _storm_logs(tmp_path)
    later = STORM_DT + timedelta(hours=6)
    doc = wsf.check_wake_storm(now=later, log_dir=tmp_path)
    assert doc["status"] == wsf.CRITICAL
    assert doc["storm"]["count"] == 39


def test_recovered_fleet_is_invisible_to_the_neighbour():
    """ЗАМЕР существующего ответа: сосед на этот вопрос не отвечает и не может.

    `detect_wake_storm` смотрит на ТЕКУЩИЙ `last_exit`. Через 15 минут после
    шторма launchd показывает `exit 0` у всех — и единственный существовавший
    детектор шторма молчит про 39 упавших агентов.
    """
    ahm = pytest.importorskip("spa_core.monitoring.agent_health_monitor")
    recovered = [
        ahm.AgentHealth(label=f"com.spa.{a}", status=ahm.OK, last_exit=0,
                        log_age_min=20.0)
        for a in FLEET_39
    ]
    assert ahm.detect_wake_storm(recovered) is None


def test_pre_fix_form_of_the_same_storm_is_detected(tmp_path):
    """04.08 обёртка ещё не умела сдаваться с меткой — улики без своего времени.

    27 `.launchd.err` с EINTR + 40 логов с ModuleNotFoundError, все с mtime
    момента шторма. Время события — ОЦЕНКА, и отчёт обязан это сказать.
    """
    for a in FLEET_39[:27]:
        _write(tmp_path, f"spa_{a}.launchd.err",
               "/bin/bash: agent_x.sh: Interrupted system call\n"
               "shell-init: error retrieving current directory: getcwd: "
               "cannot access parent directories\n",
               mtime=STORM_DT)
    for a in FLEET_39:
        _write(tmp_path, f"spa_{a}.log",
               "ModuleNotFoundError: No module named 'spa_core'\n", mtime=STORM_DT)

    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)
    assert doc["status"] == wsf.CRITICAL
    # РАЗНЫЕ агенты, а не файлы: 39 агентов, 66 файлов.
    assert doc["storm"]["count"] == 39
    assert doc["storm"]["time_sources"] == ["mtime"]
    assert any("ОЦЕНКА" in line for line in doc["issues"])


def test_same_agent_in_two_files_counts_once(tmp_path):
    """Маркер и в `.log`, и в `.launchd.err` — это один упавший агент."""
    for a in FLEET_39[:4]:
        _write(tmp_path, f"spa_{a}.log", _giveup_line(a))
        _write(tmp_path, f"spa_{a}.launchd.err", _giveup_line(a))
    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)
    # 4 агента, 8 файлов — порог 5 не взят.
    assert doc["status"] == wsf.OK, doc["reason"]
    assert doc["agents_seen"] == sorted(FLEET_39[:4])


# ===========================================================================
# ОБРАТНАЯ СТОРОНА — тишина обязана быть бесплатной
# ===========================================================================
def test_normal_restart_of_one_agent_is_silent(tmp_path):
    _write(tmp_path, "spa_self_heal.log",
           "[2026-08-04T07:00:00Z] starting\n[2026-08-04T07:00:02Z] done, exit 0\n")
    _write(tmp_path, "spa_self_heal.launchd.err", "")
    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)
    assert doc["status"] == wsf.OK
    assert doc["storm"] is None
    assert doc["measured"] is True
    assert doc["issues"] == []


def test_whole_quiet_fleet_is_silent(tmp_path):
    for a in FLEET_39:
        _write(tmp_path, f"spa_{a}.log", "[2026-08-04T07:00:00Z] ok\n")
    assert wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)["status"] == wsf.OK


def test_single_genuine_giveup_is_not_a_storm(tmp_path):
    """«Упал один агент» — вопрос agent_health. Здесь только называем факт."""
    _write(tmp_path, "spa_self_heal.log", _giveup_line("self_heal"))
    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)
    assert doc["status"] == wsf.OK
    assert doc["agents_seen"] == ["self_heal"]
    assert any("одиночные сдачи" in line for line in doc["issues"])


def test_failures_spread_across_the_day_are_not_a_storm(tmp_path):
    """Восемь независимых сдач с шагом 20 минут — не событие уровня флота."""
    base = at("2026-08-04T01:00:00+00:00")
    for i, a in enumerate(FLEET_39[:8]):
        stamp = (base + timedelta(minutes=20 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write(tmp_path, f"spa_{a}.log", _giveup_line(a, stamp))
    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)
    assert doc["status"] == wsf.OK, doc["reason"]
    assert doc["storm"] is None


def test_old_storm_ages_out_and_stops_ringing(tmp_path):
    """Иначе сторож звенит вечно об одном событии — и его выключат."""
    _storm_logs(tmp_path)
    much_later = STORM_DT + timedelta(hours=wsf.LOOKBACK_H + 1)
    doc = wsf.check_wake_storm(now=much_later, log_dir=tmp_path)
    assert doc["status"] == wsf.OK
    assert doc["storm"] is None


# ===========================================================================
# FAIL-CLOSED — «не измерено» ≠ «шторма не было»
# ===========================================================================
def test_missing_log_dir_is_unchecked_not_ok(tmp_path):
    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path / "нет-такого")
    assert doc["status"] == wsf.WARNING
    assert doc["measured"] is False
    assert doc["unchecked"]


def test_unreadable_log_is_unchecked_not_ok(tmp_path, monkeypatch):
    _write(tmp_path, "spa_self_heal.log", "ok\n")

    def boom(path, tail_bytes=wsf.TAIL_BYTES):
        raise PermissionError("нет доступа")

    monkeypatch.setattr(wsf, "_read_tail", boom)
    doc = wsf.check_wake_storm(now=ASKED_AT, log_dir=tmp_path)
    assert doc["status"] == wsf.WARNING
    assert doc["measured"] is False


def test_unwritable_verdict_is_not_swallowed(tmp_path):
    """Незаписанный вердикт не имеет права остаться зелёным (класс `_save`)."""
    _write(tmp_path, "spa_self_heal.log", "[2026-08-04T07:00:00Z] ok\n")
    # Каталог отчётов — на самом деле файл: запись невозможна по-настоящему.
    blocked = _write(tmp_path, "занято.txt", "не каталог\n")
    doc, path = wsf.run(now=ASKED_AT, log_dir=tmp_path, data_dir=blocked)
    assert path is None
    assert doc["published"] is False
    assert doc["status"] != wsf.OK


def test_run_writes_report_when_asked(tmp_path):
    out = tmp_path / "data"
    out.mkdir()
    _write(tmp_path, "spa_self_heal.log", "[2026-08-04T07:00:00Z] ok\n")
    doc, path = wsf.run(now=ASKED_AT, log_dir=tmp_path, data_dir=out)
    assert path is not None and path.exists()
    assert doc["published"] is True


def test_run_without_data_dir_writes_nothing(tmp_path):
    doc, path = wsf.run(now=ASKED_AT, log_dir=tmp_path)
    assert path is None
    assert list(tmp_path.iterdir()) == []
    assert doc["status"] == wsf.OK


# ===========================================================================
# Коды выхода — launchd обязан увидеть шторм как ненулевой
# ===========================================================================
def test_exit_codes(tmp_path):
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    _write(quiet, "spa_self_heal.log", "[2026-08-04T07:00:00Z] ok\n")
    assert wsf.main(["--log-dir", str(quiet)]) == 0

    stormy = tmp_path / "stormy"
    stormy.mkdir()
    _storm_logs(stormy, ts=(wsf._utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert wsf.main(["--log-dir", str(stormy)]) == 2

    assert wsf.main(["--log-dir", str(tmp_path / "нет")]) == 1


# ===========================================================================
# Доставка вердикта: сторож обязан быть кем-то прочитан, иначе он украшение
# ===========================================================================
def _check_system(tmp_path, wake_storm):
    ahm = pytest.importorskip("spa_core.monitoring.agent_health_monitor")
    return ahm, ahm.check_system(tmp_path, ASKED_AT, wake_storm=wake_storm)


def test_storm_reaches_the_report_as_critical(tmp_path):
    def storm():
        return {"status": "CRITICAL", "storm": {"count": 39},
                "issues": ["ФЛОТ УПАЛ РАЗОМ: 39 агентов"], "unchecked": []}

    ahm, (checks, status, issues) = _check_system(tmp_path, storm)
    assert status == ahm.CRITICAL
    assert checks["wake_storm_agents"] == 39
    assert checks["critical_flags"] >= 1
    assert any("РАЗОМ" in line for line in issues)


def test_quiet_storm_check_does_not_colour_the_report(tmp_path):
    def quiet():
        return {"status": "OK", "storm": None, "issues": [], "unchecked": []}

    ahm, (checks, status, issues) = _check_system(tmp_path, quiet)
    assert checks["wake_storm_agents"] == 0
    assert not any("РАЗОМ" in line for line in issues)


def test_broken_storm_check_is_unchecked_not_ok(tmp_path):
    def boom():
        raise RuntimeError("каталог логов пропал")

    ahm, (checks, status, issues) = _check_system(tmp_path, boom)
    assert checks["wake_storm_agents"] is None
    assert status != ahm.OK
    assert any("wake_storm_forensics UNCHECKED" in line for line in issues)


def test_sandbox_data_dir_does_not_measure_the_host(tmp_path):
    """Не спросили про хост — поле остаётся НЕ ИЗМЕРЕНО (None), а не нулём."""
    ahm = pytest.importorskip("spa_core.monitoring.agent_health_monitor")
    checks, _status, _issues = ahm.check_system(tmp_path, ASKED_AT)
    assert checks["wake_storm_agents"] is None


def test_label_from_log_name():
    assert wsf.label_from_log_name("spa_self_heal.launchd.err") == "self_heal"
    assert wsf.label_from_log_name("spa_watchdog.log") == "watchdog"
    assert wsf.label_from_log_name("spa_api.launchd.out") == "api"
