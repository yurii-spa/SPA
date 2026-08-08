#!/usr/bin/env python3
"""Сторож Телеграма: ловит поломку, чинит одну, и НЕ чинит там, где сделал бы хуже.

Каждый тест — положительный контроль над конкретной аварией, а не над воображаемой:

* **08.08, главная:** бот трое суток исполнял код от 5 августа. Процесс жив, pid на месте,
  `self_heal` доволен (он оживляет только при pid == 0) — а кнопки мертвы.
* **08.08, вторая:** гейт перед деплоем поднял ВТОРОЙ поллер на том же токене; 409-конфликты,
  нажатия владельца теряются. Перезапуск тут добавил бы ТРЕТИЙ — сторож обязан отказаться.
* **Класс fail-OPEN:** «не смогли измерить» никогда не значит «всё хорошо».
* **Сторож как источник аварии:** крашлуп не должен превратиться в шторм перезапусков.
* **«Перезапустили» ≠ «починили»:** результат проверяется маячком, а не фактом вызова.

Ни один тест не ходит в сеть и не трогает живое состояние: измерители подменяются.
Время — вход, а не окружение: все отметки от одного якоря, литеральных дат нет.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.monitoring import telegram_health as TH
from spa_core.tests._freshness import now_utc

NOW = now_utc()

#: Настоящие реализации, снятые ДО того, как автофикстура подменит их заглушками:
#: тесты самих измерителей обязаны проверять НАСТОЯЩИЙ разбор, а не свою же заглушку.
_REAL_POLLER_PIDS = TH.poller_pids


@pytest.fixture(autouse=True)
def no_real_system(monkeypatch):
    """Ни одного настоящего вызова launchctl/ps/kickstart из тестов.

    Умолчания — «всё здорово»; каждый тест ломает РОВНО одну вещь, чтобы было видно,
    какая проверка сработала.
    """
    monkeypatch.setattr(TH, "launchd_pid", lambda label=TH.LABEL: 4242)
    monkeypatch.setattr(TH, "poller_pids", lambda module=TH.BOT_MODULE: [4242])
    monkeypatch.setattr(TH, "process_age_s", lambda pid: 60.0)
    monkeypatch.setattr(TH, "newest_watched_mtime",
                        lambda root=None, modules=TH.WATCHED_MODULES:
                        (NOW - timedelta(hours=2)).timestamp())
    monkeypatch.setattr(TH, "kickstart",
                        lambda label=TH.LABEL: pytest.fail("kickstart вызван неожиданно"))


def _beacon(tmp_path: Path, *, age_s: int = 10, caps=("alert_actions",)) -> Path:
    p = tmp_path / "beacon.json"
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot", "pid": 4242,
        "updated_at": (NOW - timedelta(seconds=age_s)).isoformat(),
        "capabilities": list(caps),
    }), encoding="utf-8")
    return p


def _status_of(rep, check_name):
    return next(f.status for f in rep.findings if f.check == check_name)


# ── проверка ─────────────────────────────────────────────────────────────────


def test_healthy_bot_reports_ok(tmp_path):
    """Обратная сторона всех остальных тестов: здоровый бот НЕ поднимает тревогу."""
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path))
    assert rep.status == TH.OK, [f.detail for f in rep.findings if f.status != TH.OK]


def test_stale_code_is_caught_even_though_the_process_is_alive(tmp_path, monkeypatch):
    """ГЛАВНАЯ авария 08.08: процесс жив и молод по меркам launchd, но стартовал ДО
    доставки кода. Ни один существующий сторож этого не видит — `self_heal` оживляет
    только при pid == 0, а pid здесь есть."""
    monkeypatch.setattr(TH, "process_age_s", lambda pid: 3 * 86400.0)  # живёт 3 суток
    monkeypatch.setattr(TH, "newest_watched_mtime",
                        lambda root=None, modules=TH.WATCHED_MODULES:
                        (NOW - timedelta(hours=5)).timestamp())  # код правлен 5 часов назад
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path))
    assert _status_of(rep, "свежесть кода") == TH.CRITICAL
    assert rep.status == TH.CRITICAL


def test_a_process_started_after_the_code_is_not_stale(tmp_path, monkeypatch):
    """Контроль в обратную сторону: перезапущенный бот НЕ считается устаревшим."""
    monkeypatch.setattr(TH, "process_age_s", lambda pid: 30.0)
    monkeypatch.setattr(TH, "newest_watched_mtime",
                        lambda root=None, modules=TH.WATCHED_MODULES:
                        (NOW - timedelta(hours=9)).timestamp())
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path))
    assert _status_of(rep, "свежесть кода") == TH.OK


def test_missing_beacon_is_critical(tmp_path):
    """Так выглядела авария 08.08 со стороны отправителя: маячка нет ⇒ кнопки не вешаются."""
    rep = TH.check(now=NOW, beacon_path=tmp_path / "нет.json")
    assert _status_of(rep, "маячок") == TH.CRITICAL


def test_stale_beacon_means_the_loop_is_wedged(tmp_path):
    """Процесс есть, а цикл не крутится: нажатия обрабатывать некому."""
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, age_s=TH.BEACON_MAX_AGE_S + 60))
    assert _status_of(rep, "маячок") == TH.CRITICAL


def test_old_bot_without_the_capability_is_critical(tmp_path):
    """Бот поднялся, но со старым кодом: маячок свежий, а умения обрабатывать нажатия нет."""
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, caps=("что-то_другое",)))
    assert _status_of(rep, "маячок") == TH.CRITICAL


def test_two_pollers_are_critical(tmp_path, monkeypatch):
    """Авария гейта 08.08: два поллера на одном токене — 409, нажатия теряются."""
    monkeypatch.setattr(TH, "poller_pids", lambda module=TH.BOT_MODULE: [111, 222])
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path))
    assert _status_of(rep, "поллеры") == TH.CRITICAL


def test_unmeasurable_system_is_unknown_not_ok(tmp_path, monkeypatch):
    """Наш родовой класс дефектов: «не смогли измерить» ≠ «всё хорошо»."""
    monkeypatch.setattr(TH, "launchd_pid", lambda label=TH.LABEL: None)
    monkeypatch.setattr(TH, "poller_pids", lambda module=TH.BOT_MODULE: None)
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path))
    assert _status_of(rep, "launchd") == TH.UNKNOWN
    assert rep.status != TH.OK


# ── починка ──────────────────────────────────────────────────────────────────


def test_restart_fires_for_a_stale_beacon_and_is_verified(tmp_path, monkeypatch):
    """Починка применяется — и ПОДТВЕРЖДАЕТСЯ вернувшимся маячком, а не фактом вызова."""
    calls = []
    monkeypatch.setattr(TH, "kickstart", lambda label=TH.LABEL: calls.append(label) or True)
    monkeypatch.setattr(TH, "_beacon_came_back", lambda *a, **k: True)
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, age_s=99999))
    rep = TH.heal(rep, now=NOW, state_path=tmp_path / "state.json")
    assert calls == [TH.LABEL]
    assert any("перезапущен" in a for a in rep.actions)
    assert any("подтверждена" in a for a in rep.actions)


def test_restart_that_does_not_bring_the_bot_back_is_reported_as_failure(tmp_path, monkeypatch):
    """«Перезапустили» ≠ «починили». Маячок не вернулся — говорим вслух, а не молчим.

    Без этого сторож рапортовал бы об успехе ровно тогда, когда бот не поднялся.
    """
    monkeypatch.setattr(TH, "kickstart", lambda label=TH.LABEL: True)
    monkeypatch.setattr(TH, "_beacon_came_back", lambda *a, **k: False)
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, age_s=99999))
    rep = TH.heal(rep, now=NOW, state_path=tmp_path / "state.json")
    assert any("НЕ ПОДТВЕРЖДЕНА" in a for a in rep.actions)
    assert rep.status == TH.CRITICAL


def test_duplicate_pollers_block_the_restart(tmp_path, monkeypatch):
    """Ключевой отказ: при двух поллерах перезапуск добавил бы ТРЕТИЙ.

    Сторож, который «чинит» дубль перезапуском, ухудшает ровно ту поломку, что нашёл.
    """
    monkeypatch.setattr(TH, "poller_pids", lambda module=TH.BOT_MODULE: [111, 222])
    # kickstart остаётся фикстурным — его вызов провалит тест сам по себе.
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, age_s=99999))
    rep = TH.heal(rep, now=NOW, state_path=tmp_path / "state.json")
    assert any("ЗАБЛОКИРОВАН" in a for a in rep.actions)


def test_circuit_breaker_stops_a_restart_storm(tmp_path, monkeypatch):
    """Крашлуп не должен превратиться в шторм перезапусков — их лечит человек."""
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "schema_version": 1,
        "restarts": [NOW.timestamp() - 60 * i for i in range(TH.MAX_RESTARTS_PER_WINDOW)],
    }), encoding="utf-8")
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, age_s=99999))
    rep = TH.heal(rep, now=NOW, state_path=state)
    assert any("предохранитель" in a for a in rep.actions)


def test_old_restarts_outside_the_window_do_not_count(tmp_path, monkeypatch):
    """Предохранитель — скользящее окно, а не счётчик навсегда: вчерашние не считаются."""
    monkeypatch.setattr(TH, "kickstart", lambda label=TH.LABEL: True)
    monkeypatch.setattr(TH, "_beacon_came_back", lambda *a, **k: True)
    state = tmp_path / "state.json"
    old = NOW.timestamp() - TH.RESTART_WINDOW_S - 600
    state.write_text(json.dumps({"schema_version": 1, "restarts": [old] * 10}), encoding="utf-8")
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, age_s=99999))
    rep = TH.heal(rep, now=NOW, state_path=state)
    assert any("перезапущен" in a for a in rep.actions)


def test_unknown_state_never_triggers_a_restart(tmp_path, monkeypatch):
    """Fail-CLOSED в сторону БЕЗДЕЙСТВИЯ: не измерили — не дёргаем прод."""
    monkeypatch.setattr(TH, "launchd_pid", lambda label=TH.LABEL: None)
    monkeypatch.setattr(TH, "poller_pids", lambda module=TH.BOT_MODULE: None)
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path))
    rep = TH.heal(rep, now=NOW, state_path=tmp_path / "state.json")
    assert not any("перезапущен" in a for a in rep.actions)


def test_healthy_bot_is_never_restarted(tmp_path):
    """Здоровый бот не трогаем — иначе сторож сам роняет связь владельца."""
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path))
    rep = TH.heal(rep, now=NOW, state_path=tmp_path / "state.json")
    assert rep.actions == []


# ── тревога ──────────────────────────────────────────────────────────────────


def test_alert_names_the_real_problem_in_russian(tmp_path):
    """Владельцу едет то, что ИЗМЕРЕНО, простыми словами — без кодов и без догадок."""
    rep = TH.check(now=NOW, beacon_path=_beacon(tmp_path, age_s=99999))
    text = TH.alert_text(rep)
    assert "Телеграм-бот сломан" in text
    assert "маячок" in text
    assert "OK" not in text  # здоровые проверки в тревогу не попадают


@pytest.mark.parametrize("status", [TH.OK, TH.WARN, TH.UNKNOWN, TH.CRITICAL])
def test_every_status_has_its_own_headline(status):
    """Положительный контроль замеренного дефекта (08.08 13:15): сообщение о ВЫЗДОРОВЛЕНИИ
    ушло владельцу с телом «⚠️ не всё измерено».

    Причина — двоичный выбор заголовка «CRITICAL или всё остальное». Теперь заголовок есть
    у каждого статуса, и забыть один нельзя: параметризация покраснеет.
    """
    text = TH.alert_text(TH.Report(status=status, checked_at=""))
    assert TH._HEAD_BY_STATUS[status].split("<b>")[1] in text
    if status == TH.OK:
        assert "не всё измерено" not in text
        assert "сломан" not in text


def test_notification_goes_through_the_single_push_authority(monkeypatch):
    """Тревога уходит ЧЕРЕЗ `push_policy`, а не прямо в транспорт.

    У непрошеных сообщений Телеграма один авторитет (CI-страж
    `test_telegram_single_authority`), и он же даёт дедуп: сторож просыпается каждые
    5 минут, без дедупа одна поломка стала бы 288 сообщениями в сутки — и владелец
    отключил бы уведомления вместе с настоящими тревогами.
    """
    calls = []

    def fake_push(event_key, severity, title, body="", **kw):
        calls.append((event_key, severity, title, kw))
        return True

    monkeypatch.setattr("spa_core.telegram.push_policy.push_critical", fake_push)
    rep = TH.Report(status=TH.CRITICAL, checked_at="")
    rep.add(TH.Finding("маячок", TH.CRITICAL, "маячка нет"))
    TH.notify(rep)

    assert calls, "тревога обязана уйти через push_policy"
    key, severity, title, kw = calls[0]
    assert key == "telegram_down"
    assert severity == TH.CRITICAL
    assert kw["dedup_key"]  # отпечаток конкретной поломки обязателен


def test_recovery_is_announced_as_resolved(monkeypatch):
    """Выздоровление объявляется отдельно: `resolved=True`.

    Решает про отправку `push_policy` — только она знает предыдущее состояние и потому
    пришлёт «снова работает» ровно один раз, на переходе. Своя проверка «слать ли» здесь
    была бы вторым авторитетом, который разъедется с первым.
    """
    calls = []
    monkeypatch.setattr("spa_core.telegram.push_policy.resolve",
                        lambda *a, **kw: calls.append((a, kw)) or True)
    TH.notify(TH.Report(status=TH.OK, checked_at=""))
    assert calls, "выздоровление обязано объявляться через push_policy.resolve"
    assert calls[0][0][0] == "telegram_down"


def test_a_different_breakage_is_not_swallowed_by_dedup():
    """Отпечаток обязан РАЗЛИЧАТЬ аварии.

    Замерено в проде на `core_agent_down`: без отпечатка вчерашняя поломка оставляла класс
    в состоянии «плохо», и сегодняшняя ДРУГАЯ уходила в тишину как «всё ещё плохо».
    """
    a = TH.Report()
    a.add(TH.Finding("маячок", TH.CRITICAL, "нет"))
    b = TH.Report()
    b.add(TH.Finding("поллеры", TH.CRITICAL, "их два"))
    assert TH.incident_fingerprint(a) != TH.incident_fingerprint(b)
    assert TH.incident_fingerprint(TH.Report()) == "ok"


# ── измерители (чистые разборы) ──────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("01:02", 62.0),
    ("1:01:00", 3660.0),
    ("3-01:00:00", 3 * 86400 + 3600.0),
    ("мусор", None),
])
def test_etime_parsing(text, expected):
    """`ps -o etime` отдаёт три разных формата; ошибка разбора = ложный вердикт."""
    assert TH._parse_etime(text) == expected


def test_poller_count_ignores_the_bash_wrapper(monkeypatch):
    """Обёртка launchd тоже несёт имя модуля в командной строке.

    Посчитав её, сторож вечно видел бы «два поллера» там, где он один, — и НАВСЕГДА
    блокировал бы починку, ради которой его и завели.
    """
    ps_out = (
        " 100 /bin/bash /Users/x/SPA_Claude/scripts/agent_template.sh telegram_bot spa_core.telegram.bot\n"
        " 101 /Users/x/miniconda3/bin/python3 -m spa_core.telegram.bot\n"
        " 102 grep spa_core.telegram.bot\n"
    )

    class R:
        returncode = 0
        stdout = ps_out

    monkeypatch.setattr(TH, "_run", lambda args: R())
    assert _REAL_POLLER_PIDS() == [101]


def test_a_self_healed_incident_is_not_shouted_as_broken():
    """Владелец жаловался на лишнюю ругань. Инцидент, который сторож УЖЕ починил и проверил,
    к моменту чтения не сломан — 🚨 на нём вводит в заблуждение и зовёт чинить починенное.

    Факты не прячутся: что ломалось и что сделано — остаётся в теле дословно.
    """
    rep = TH.Report(status=TH.CRITICAL, checked_at="")
    rep.add(TH.Finding("свежесть кода", TH.CRITICAL, "процесс старше кода"))
    rep.actions += ["перезапущен com.spa.telegram_bot", "починка подтверждена: маячок вернулся"]
    text = TH.alert_text(rep)
    assert "починил сам" in text
    assert "🚨" not in text
    assert "процесс старше кода" in text          # факт на месте
    assert "починка подтверждена" in text


def test_an_unhealed_break_is_still_shouted():
    """Контроль в обратную сторону: не починили — тревога остаётся тревогой."""
    rep = TH.Report(status=TH.CRITICAL, checked_at="")
    rep.add(TH.Finding("поллеры", TH.CRITICAL, "их два"))
    rep.actions += ["перезапуск ЗАБЛОКИРОВАН: сначала руками устранить — их два"]
    text = TH.alert_text(rep)
    assert "🚨" in text and "починил сам" not in text
