"""Отказ замка (код 2) судится ФАКТОМ, а не цифрой (цикл #290).

Карточка `inbox-otkaz-zamka-tsikla-neotlichim-ot-avarii`, замер 2026-08-08
(цикл #161): за сутки дневной цикл звали **20 раз, 18 из них — отказ замка**,
ни одной аварии. Владелец всё это время видел на пульте жёлтое
`com.spa.daily_cycle — last_exit=2`, то есть предупреждение, на 18/18
порождённое УСПЕШНОЙ работой защиты. Тот же самый жёлтый цвет означал бы и
противоположное: цикл отказывает раз за разом, а трека за день нет.

Цикл #219 развёл КОДЫ (`cycle_exit`), но двойку не тронул намеренно — по ней
считает отказы `cycle_lock_watch`. Здесь закрывается второй, главный пункт
карточки: **отказ показывать как ИНФОРМАЦИЮ, а не WARN** — но только тогда,
когда есть доказательство, что цикл в своём окне всё-таки отработал.

Проверка идёт в ОБЕ стороны:

* отказ + доказанный свежий цикл → агент не краснеет, исход назван вслух;
* отказ без свежего цикла → краснеет, и дыра названа словами;
* отказ, про который НЕЛЬЗЯ измерить, отработал ли цикл → краснеет (fail-CLOSED);
* авария (код 1) краснеет даже при свежайшем цикле — иначе мы починили тишину;
* труп в замке остаётся CRITICAL, даже когда агент зелёный: это ДРУГОЙ вопрос
  и другой сторож (`cycle_lock_watch`, цикл #164).

Время входит через `NOW` и относительные отметки (`.claude/rules/deployment.md`):
литеральных дат, от которых тест испортится со сдвигом календаря, здесь нет.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.paper_trading import cycle_exit as ce

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
_NONE_LOG = "/nonexistent/autopush.log"

# Замер 2026-08-08: 18 отказов подряд при отработавшем в тот же день цикле.
PROD_REFUSALS = 18


def _lc(label: str, pid: int = 0, exit_code: int | None = None) -> dict:
    return {label: {"pid": pid, "exit": exit_code}}


def _daily_plist(log_path) -> dict:
    """Плист дневного цикла в той же форме, что живой com.spa.daily_cycle."""
    return {"StartCalendarInterval": {"Hour": 8, "Minute": 0},
            "StandardOutPath": str(log_path)}


def _fresh_log(tmp_path, name: str = "cycle.log"):
    p = tmp_path / name
    p.write_text("x")
    ts = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(p, (ts, ts))
    return p


def _cycle_artifact(data_dir, hours_ago: float, key: str = "last_run",
                    name: str = "cycle_status.json"):
    """Артефакт отработавшего цикла возрастом `hours_ago` часов."""
    ts = (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (data_dir / name).write_text(json.dumps({key: ts}), encoding="utf-8")
    return ts


def _judge(tmp_path, data_dir, exit_code=ce.EXIT_LOCK_REFUSED,
           label=ce.CYCLE_AGENT_LABEL, log_name="cycle.log"):
    plist = _daily_plist(_fresh_log(tmp_path, log_name))
    return ahm.check_agent(label, plist, True,
                           _lc(label, pid=0, exit_code=exit_code), NOW,
                           data_dir=data_dir)


# ── Вердикт сам по себе ─────────────────────────────────────────────────────
def test_fresh_cycle_makes_the_refusal_protection(tmp_path):
    _cycle_artifact(tmp_path, 2.5)
    v = ahm.judge_lock_refusal(tmp_path, NOW)
    assert v.state == ahm.REFUSAL_PROTECTED
    assert v.cycle_age_h == pytest.approx(2.5, abs=0.01)
    assert "защитил трек" in v.words


def test_no_fresh_cycle_makes_the_refusal_a_hole(tmp_path):
    _cycle_artifact(tmp_path, ahm.CYCLE_STALE_H + 5)
    v = ahm.judge_lock_refusal(tmp_path, NOW)
    assert v.state == ahm.REFUSAL_TRACK_HOLE
    assert "не защитил трек" in v.words


def test_the_threshold_is_a_boundary_not_a_mood(tmp_path):
    """Мутация «поменять <= на <» обязана краснеть ровно здесь."""
    _cycle_artifact(tmp_path, ahm.CYCLE_STALE_H)
    assert ahm.judge_lock_refusal(tmp_path, NOW).state == ahm.REFUSAL_PROTECTED
    _cycle_artifact(tmp_path, ahm.CYCLE_STALE_H + 0.1)
    assert ahm.judge_lock_refusal(tmp_path, NOW).state == ahm.REFUSAL_TRACK_HOLE


def test_no_data_dir_is_unmeasured_not_fine(tmp_path):
    v = ahm.judge_lock_refusal(None, NOW)
    assert v.state == ahm.REFUSAL_UNCHECKED
    assert "НЕ ИЗМЕРЕНО" in v.words


@pytest.mark.parametrize("payload", [None, "{не json", '["список"]', '{"last_run": null}',
                                     '{"checks": ["не объект"]}'])
def test_unreadable_artifact_is_unmeasured_not_fine(tmp_path, payload):
    """Пустой/чужой формы артефакт ⇒ «не измерено», а не «свежего цикла нет».

    Разница существенная: «нет» — это находка о треке, «не измерено» — находка
    о нашей слепоте, и лечатся они по-разному.
    """
    if payload is not None:
        (tmp_path / "cycle_status.json").write_text(payload, encoding="utf-8")
    v = ahm.judge_lock_refusal(tmp_path, NOW)
    assert v.state == ahm.REFUSAL_UNCHECKED
    assert "НЕ ИЗМЕРЕНО" in v.words


def test_a_timestamp_from_the_future_is_not_evidence(tmp_path):
    """Испорченные часы не должны гасить сигнал."""
    _cycle_artifact(tmp_path, -6.0)
    v = ahm.judge_lock_refusal(tmp_path, NOW)
    assert v.state == ahm.REFUSAL_UNCHECKED
    assert "БУДУЩЕМ" in v.words


# ── Читатель: здоровье агента ───────────────────────────────────────────────
def test_refusal_over_a_working_cycle_no_longer_reddens_the_agent(tmp_path):
    """ЗАМЕР 08.08: 18 из 18 предупреждений породила сработавшая защита."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _cycle_artifact(data_dir, 2.1)
    h = _judge(tmp_path, data_dir)
    assert h.status == ahm.OK
    assert h.issue == ""
    # И НЕ молчит: исход назван вслух отдельным полем, вместе с доказательством.
    assert f"last_exit={ce.EXIT_LOCK_REFUSED}" in h.note
    assert "замка" in h.note
    assert "цикл отработал" in h.note


def test_refusal_without_a_cycle_still_reddens_and_names_the_hole(tmp_path):
    """Обратная сторона: отказ, за которым нет трека, обязан быть виден."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _cycle_artifact(data_dir, ahm.CYCLE_STALE_H + 12)
    h = _judge(tmp_path, data_dir)
    assert h.status == ahm.WARNING
    assert f"last_exit={ce.EXIT_LOCK_REFUSED}" in h.issue
    assert "не защитил трек" in h.issue
    assert h.note == ""


def test_refusal_stays_red_while_the_cycle_is_unmeasured(tmp_path):
    """Fail-CLOSED: без доказательства отказ красит ровно как раньше."""
    h = _judge(tmp_path, None)
    assert h.status == ahm.WARNING
    assert f"last_exit={ce.EXIT_LOCK_REFUSED}" in h.issue
    assert "НЕ ИЗМЕРЕНО" in h.issue


def test_a_real_crash_reddens_even_next_to_the_freshest_cycle(tmp_path):
    """Починили ли мы тишину? Нет: авария краснит при любом артефакте."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _cycle_artifact(data_dir, 0.2)
    h = _judge(tmp_path, data_dir, exit_code=ce.EXIT_ERROR, log_name="crash.log")
    assert h.status == ahm.WARNING
    assert "АВАРИЯ" in h.issue


@pytest.mark.parametrize("code", [ce.EXIT_NO_LIVE_DATA, ce.EXIT_SAFETY_UNMEASURED,
                                  ce.EXIT_PROTECTION_TRIGGERED])
def test_other_outcomes_are_not_quietened_by_a_fresh_cycle(tmp_path, code):
    """Послабление касается ОДНОГО кода. Дыра в треке и неотработавшая
    проверка безопасности остаются видимыми при любом свежем артефакте."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _cycle_artifact(data_dir, 0.2)
    h = _judge(tmp_path, data_dir, exit_code=code, log_name=f"c{code}.log")
    assert h.status == ahm.WARNING
    assert f"last_exit={code}" in h.issue


def test_the_carve_out_does_not_leak_to_other_agents(tmp_path):
    """У чужого агента двойка означает что угодно — молчать о ней нельзя."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _cycle_artifact(data_dir, 0.2)
    plist = {"StartInterval": 300, "StandardOutPath": str(_fresh_log(tmp_path, "o.log"))}
    h = ahm.check_agent("com.spa.some_other_agent", plist, True,
                        _lc("com.spa.some_other_agent", pid=0,
                            exit_code=ce.EXIT_LOCK_REFUSED),
                        NOW, data_dir=data_dir)
    assert h.status == ahm.WARNING
    assert f"last_exit={ce.EXIT_LOCK_REFUSED}" in h.issue
    assert "защитил трек" not in h.issue


def test_policy_refusal_verdict_is_untouched(tmp_path):
    """Соседний исход (цикл #219) не задет: его вердикт не зависит от артефакта."""
    h = _judge(tmp_path, None, exit_code=ce.EXIT_POLICY_REFUSED, log_name="p.log")
    assert h.status == ahm.OK
    assert "штатный отказ политики" in h.note


# ── Проводка: монитор ОБЯЗАН передавать своё дерево ─────────────────────────
def test_the_monitor_hands_its_own_data_dir_to_the_judge(tmp_path, monkeypatch):
    """Один удалённый вызов оставил бы всё выше зелёным, а прод — прежним.

    Поэтому проверяется не функция, а ПРОВОДКА: полный `collect()` над
    поддельным `launchctl` обязан дать зелёного `com.spa.daily_cycle` при
    коде 2 и свежем цикле — то есть монитор действительно донёс свой `data_dir`.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _cycle_artifact(data_dir, 1.0)
    agents_dir = tmp_path / "LaunchAgents"
    agents_dir.mkdir()
    import plistlib
    with open(agents_dir / f"{ce.CYCLE_AGENT_LABEL}.plist", "wb") as f:
        plistlib.dump(_daily_plist(_fresh_log(tmp_path, "wired.log")), f)

    monitor = ahm.AgentHealthMonitor(
        data_dir=data_dir, launch_agents_dir=agents_dir,
        launchctl_output=f"-\t{ce.EXIT_LOCK_REFUSED}\t{ce.CYCLE_AGENT_LABEL}\n",
        autopush_log=_NONE_LOG, now=NOW,
    )
    report = monitor.collect()
    entry = [a for a in report["agents"] if a["label"] == ce.CYCLE_AGENT_LABEL]
    assert entry, "агент дневного цикла не попал в отчёт — проводка сломана"
    assert entry[0]["last_exit"] == ce.EXIT_LOCK_REFUSED
    assert entry[0]["status"] == ahm.OK
    assert "цикл отработал" in entry[0]["note"]


# ── Соседний сторож на месте: труп в замке по-прежнему CRITICAL ─────────────
def test_the_corpse_in_the_doorway_is_still_critical(tmp_path):
    """08.08: цикл отработал в 09:52 и ТУТ ЖЕ встал на 68 минут отказов.

    Зелёный агент здесь не означает «с замком всё хорошо» — на этот вопрос
    отвечает другой сторож, и его CRITICAL обязан остаться на месте.
    """
    # ЖИВОСТЬ ГОВОРИТСЯ ЯВНО (цикл #343). До этого номер брался «заведомо
    # свободный» (4_194_303), а если он вдруг занят — тест СКИПАЛСЯ двумя
    # разными ветками. Скип здесь хуже, чем кажется: сторож, чей CRITICAL
    # проверяют, молча переставал проверяться, и «не измерено» было
    # неотличимо от «прошло». Изменение НАМЕРЕННОЕ и УСИЛЯЕТ проверку
    # (инв. #16): номер теперь ЖИВОЙ по построению (`os.getpid()`), смерть
    # держателя — вход, обе ветки скипа исчезли, тест исполняется ВСЕГДА и на
    # любой машине. Соседний класс — та же авария 22.08 с pid 98535.
    holder_pid = os.getpid()   # жив ПО ПОСТРОЕНИЮ; «мёртв» скажет вход, а не имя

    from spa_core.monitoring.cycle_lock_watch import CYCLE_LOCK_FILE

    _cycle_artifact(tmp_path, 2.1)
    held_dt = NOW - timedelta(minutes=68)
    held = held_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    lock = tmp_path / CYCLE_LOCK_FILE
    lock.write_text(json.dumps({"pid": holder_pid, "ts": held}), encoding="utf-8")
    # Возраст замка сторож меряет по mtime — иначе он объявит замок протухшим
    # по разнице реальных часов и `NOW`, и мы проверим не тот исход.
    os.utime(lock, (held_dt.timestamp(), held_dt.timestamp()))

    # агент зелёный…
    assert _judge(tmp_path, tmp_path).status == ahm.OK
    # …и ровно в тот же момент система кричит о трупе в замке.
    _checks, status, issues = ahm.check_system(tmp_path, NOW, autopush_log=_NONE_LOG,
                                               pid_alive=lambda _pid: False)
    assert status == ahm.CRITICAL
    assert any("замок" in i or "lock" in i for i in issues)


# ── Одно определение отметки цикла на двух читателей ────────────────────────
@pytest.mark.parametrize("key, name", [
    ("last_run", "cycle_status.json"),
    ("last_cycle_ts", "cycle_health.json"),
])
def test_both_readers_share_one_definition_of_the_last_cycle(tmp_path, key, name):
    """Два выражения об одном факте разошлись бы молча — здесь оно одно."""
    _cycle_artifact(tmp_path, 3.0, key=key, name=name)
    checks, _status, _issues = ahm.check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    verdict = ahm.judge_lock_refusal(tmp_path, NOW)
    assert checks["cycle_freshness_h"] == pytest.approx(3.0, abs=0.01)
    assert verdict.cycle_age_h == pytest.approx(checks["cycle_freshness_h"], abs=0.01)


def test_the_gap_shaped_artifact_is_understood_by_both(tmp_path):
    """Третья форма артефакта (`checks.cycle_gap.last_cycle_at`) — та же отметка."""
    ts = (NOW - timedelta(hours=4.0)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "cycle_status.json").write_text(
        json.dumps({"checks": {"cycle_gap": {"last_cycle_at": ts}}}), encoding="utf-8")
    checks, _s, _i = ahm.check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert checks["cycle_freshness_h"] == pytest.approx(4.0, abs=0.01)
    assert ahm.judge_lock_refusal(tmp_path, NOW).state == ahm.REFUSAL_PROTECTED


def test_a_malformed_checks_block_does_not_crash_the_system_report(tmp_path):
    """`checks` не объект — вердикт «не измерено», а не падение всего отчёта."""
    (tmp_path / "cycle_status.json").write_text(
        json.dumps({"checks": "мусор"}), encoding="utf-8")
    checks, _s, _i = ahm.check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert checks["cycle_freshness_h"] is None
    assert ahm.judge_lock_refusal(tmp_path, NOW).state == ahm.REFUSAL_UNCHECKED
