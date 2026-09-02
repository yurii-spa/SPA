"""Якорь сессии обязан УМИРАТЬ вместе с сессией — будильник этого не умеет.

Живая авария (цикл #393, 2026-08-27)
------------------------------------------------------------------------------
Шаг 0a напечатал строку::

    деревьев пропущено как ЖИВЫЕ (сессия подтверждённо активна, расхождение там норма): 2
        — /tmp/spa_c390, /tmp/spa_c391

Обе сессии были МЕРТВЫ: ни одного процесса `claude` в системе, кроме текущего цикла.
Живым был их ЯКОРЬ — фоновый ``sleep 36000``, запущенный ночью как «долгоживущий процесс
сессии». Работа обеих осталась только в `/tmp`-деревьях и на `origin/main` не попала:
у #390 — `ADR-148` и `spa_core/monitoring/entrypoint_import_probe.py` (четвёртая проверка
приёмки деплоя), у #391 — `spa_core/tests/data_dir_guard.py`. Сторож, чья ЕДИНСТВЕННАЯ
работа — замечать недоставленное, молчал о них персонально и назвал это подтверждением.

Почему так вышло. Якорь придуман против настоящего дефекта: `session` по умолчанию — pid
ОДНОКРАТНОЙ CLI-команды, умирающий вместе с ней, поэтому `ps` по нему бессодержателен
(карточка `agent-durable-session-id`). Лекарство сформулировали как «процесс, который
живёт дольше команды» — но «дольше команды» и «ровно столько, сколько живёт сессия» суть
РАЗНЫЕ свойства, и второе никто не проверял. `sleep 36000` удовлетворяет первому и
переживает сессию на часы: он выходит по таймеру, а не вместе с работником.

Довод против якоря-будильника уже был написан — в докстринге самого писателя
(`log_session_change.durable_process`), где отвергнут `os.getppid()`: «shell outlives the
work by days ⇒ ACTIVE навсегда ⇒ шаг 0a замолчит о недоставленной работе, а это fail-OPEN».
Будильник — тот же fail-OPEN в другой одежде: правило применили к родителю и не применили
к таймеру.

Почему по имени команды, а не по родству
------------------------------------------------------------------------------
Первая версия починки собиралась судить по `ppid`: осиротевший якорь должен был
перецепиться к launchd. ЗАМЕР это опроверг — фоновый `sleep`, запущенный ЖИВОЙ сессией
(проверено на процессе самого цикла #393), имеет `ppid=1` С ПЕРВОЙ СЕКУНДЫ, потому что
оболочка, его запустившая, выходит сразу. По родителю живой якорь неотличим от
осиротевшего, и проверка `ppid` дала бы поток ложных находок. Имя команды разделяет их
честно: `sleep` не является сессией НИКОГДА — ни живой, ни мёртвой.

Направление отказа
------------------------------------------------------------------------------
Вердикт понижается до **UNKNOWN («не измерено»), а не до NOT_CONFIRMED («сессия мертва»)**.
Будильник не доказывает ни жизни, ни смерти; объявить смерть по нему значило бы завести
второй сорт лжи вместо первого. UNKNOWN при этом ДОСТАТОЧЕН: отчёт молчит о дереве только
по ACTIVE («не измерено активностью не считается»), поэтому осиротевшая работа снова
становится видимой, а решение о подъёме принимает человек — как и предписывает протокол.

`UNMEASURED` (спросить команду нечем) НАМЕРЕННО не понижает вердикт: «нечем спросить» —
это не «поймали». Тесты держат обе стороны.
"""
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Часы ИНЪЕКТИРОВАНЫ, литеральных дат в фикстурах нет: файл про свежесть объявлений,
#: и литерал начал бы падать от одного лишь сдвига календаря (`.claude/rules/deployment.md`).
NOW = now_utc()
TS = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
#: Формат `ps -o lstart=` — локальный; сессия стартовала ДО объявления.
STARTED = (NOW - timedelta(hours=2)).astimezone().strftime("%a %b %d %H:%M:%S %Y")

#: Дословно то, что видел цикл #393 в `ps -p 42391 -o command=`.
TIMER_CMD = "sleep 36000"
#: Дословно то, чем якорь быть ОБЯЗАН — процесс самой сессии.
SESSION_CMD = "/Users/yuriikulieshov/.local/bin/claude -p Ты — оркестратор SPA"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_anchor_step0a", "scripts/check_undelivered_work.py")


@pytest.fixture(scope="module")
def writer():
    return _load("_test_anchor_writer", "scripts/log_session_change.py")


def _ps(pid):
    """`ps -o lstart=` — процесс есть и стартовал до объявления (живой якорь)."""
    return 0, STARTED


def _cmd(command):
    """Подменённый `ps -o command=`."""
    return lambda pid: (0, command)


def _gone(pid):
    return 1, ""


ENTRY = {"ts": TS, "session": "cycle-390", "session_pid": 42391,
         "session_pid_start": STARTED, "files": ["spa_core/monitoring/entrypoint_import_probe.py"]}


# ── Само измерение якоря ─────────────────────────────────────────────────────

def test_timer_anchor_is_named_as_proving_nothing(guard):
    """`sleep 36000` — не сессия. Положительный контроль: команда взята из живого `ps`."""
    kind, cmd = guard.anchor_kind(42391, cmd_probe=_cmd(TIMER_CMD))
    assert kind == guard.ANCHOR_TIMER
    assert cmd == TIMER_CMD


def test_session_process_is_capable_of_being_the_anchor(guard):
    """Обратный контроль: настоящий процесс сессии якорем быть МОЖЕТ."""
    kind, _ = guard.anchor_kind(29988, cmd_probe=_cmd(SESSION_CMD))
    assert kind == guard.ANCHOR_SESSION_CAPABLE


def test_absolute_path_to_sleep_is_recognised(guard):
    """`/bin/sleep 36000` — тот же будильник: сравнение по имени файла, не по строке."""
    kind, _ = guard.anchor_kind(42391, cmd_probe=_cmd("/bin/sleep 36000"))
    assert kind == guard.ANCHOR_TIMER


def test_unmeasurable_command_is_not_an_accusation(guard):
    """Спросить нечем ⇒ `UNMEASURED`, а НЕ «поймали будильник»."""
    kind, cmd = guard.anchor_kind(42391, cmd_probe=_gone)
    assert kind == guard.ANCHOR_UNMEASURED
    assert cmd == ""


# ── Вердикт о сессии ─────────────────────────────────────────────────────────

def test_live_timer_anchor_no_longer_reads_as_an_active_session(guard):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии 27.08: живой `sleep` + мёртвая сессия.

    До починки эта же запись давала `ACTIVE` («долгоживущий процесс сессии pid42391 жив —
    тот же процесс»), и дерево `/tmp/spa_c390` целиком исчезало из отчёта.
    """
    state, why = guard._durable_state(ENTRY, guard._parse_ts(TS), _ps,
                                      cmd_probe=_cmd(TIMER_CMD))
    assert state == guard.UNKNOWN, why
    assert "sleep 36000" in why
    assert "НЕ ИЗМЕРЕНА" in why


def test_a_real_session_anchor_still_reads_as_active(guard):
    """Контроль в ОБЕ стороны: правка не глушит живые сессии.

    Без этого теста починку можно было бы «пройти», понизив вердикт всем подряд, — и
    отчёт наполнился бы находками о работающих прямо сейчас сессиях.
    """
    state, why = guard._durable_state(ENTRY, guard._parse_ts(TS), _ps,
                                      cmd_probe=_cmd(SESSION_CMD))
    assert state == guard.ACTIVE, why


def test_unmeasured_command_leaves_the_verdict_untouched(guard):
    """«Нечем спросить» не меняет вердикт: обвинение без измерения — тот же класс лжи."""
    state, _ = guard._durable_state(ENTRY, guard._parse_ts(TS), _ps, cmd_probe=_gone)
    assert state == guard.ACTIVE


def test_timer_anchor_is_not_read_as_the_session_being_dead(guard):
    """UNKNOWN ≠ NOT_CONFIRMED: будильник не доказывает и смерти.

    `durable_process_gone` снимает окно ожидания и включает разбор записи немедленно.
    Позволить будильнику ЭТО значило бы объявить чужую живую сессию мёртвой и разобрать
    её незаконченную работу как осиротевшую.
    """
    assert guard.durable_process_gone(ENTRY, ps=_ps, cmd_probe=_cmd(TIMER_CMD)) is False
    assert guard.durable_process_gone(ENTRY, ps=_gone, cmd_probe=_cmd(TIMER_CMD)) is True


def test_label_pid_anchor_is_measured_the_same_way(guard):
    """Запасной критерий (pid из ярлыка `pid95974`) идёт через ту же дверь.

    Иначе сессия, объявившая якорь ярлыком, а не полем, обходила бы проверку — а именно
    так объявлял цикл #391.
    """
    entry = {"ts": TS, "session": "pid95974", "files": ["spa_core/tests/data_dir_guard.py"]}
    state, why = guard._measured_session_state(entry, "pid95974", ps=_ps,
                                               cmd_probe=_cmd(TIMER_CMD))
    assert state == guard.UNKNOWN, why
    assert "sleep 36000" in why


# ── Сквозной эффект: дерево больше не пропускается как «живое» ───────────────

def test_the_tree_of_a_timer_anchored_session_is_no_longer_skipped(guard, tmp_path):
    """Сквозной контроль ровно того ущерба, который случился 27.08.

    Проверяется не текст измерения, а ПОСЛЕДСТВИЕ: попадает ли сессия в множество
    подтверждённо активных (из него `unannounced_divergence_scan` берёт деревья, о которых
    отчёту РАЗРЕШЕНО молчать). Тест на формулировку остался бы зелёным, если бы проводку
    вырезали и вердикт никуда не шёл — ровно этот класс описан в памяти как «one deleted
    call site left 1364 GREEN».

    Репозиторий — свой, пустой и одноразовый: судить об этом обязан вердикт якоря, а не
    состояние хост-дерева (`base_ref` без git даёт «не измерено» на ОБЕИХ ветках, и
    обратный контроль молча зеленел бы вхолостую — проверено).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (("init", "-q", "."),
                ("config", "user.email", "t@example.invalid"),
                ("config", "user.name", "anchor-test"),
                ("commit", "-q", "--allow-empty", "-m", "base"),
                ("branch", "-q", "origin/main")):
        rc, _, err = guard._git(str(repo), *cmd)
        assert rc == 0, err

    report = guard.build_report(entries=[ENTRY], root=repo, base_ref="origin/main",
                                self_session="cycle-393", ps=_ps, now=NOW,
                                cmd_probe=_cmd(TIMER_CMD))
    assert report["sessions_active"] == 0

    live = guard.build_report(entries=[ENTRY], root=repo, base_ref="origin/main",
                              self_session="cycle-393", ps=_ps, now=NOW,
                              cmd_probe=_cmd(SESSION_CMD))
    assert live["sessions_active"] == 1


# ── Писатель: класс перестаёт создаваться ────────────────────────────────────

def test_announce_refuses_to_record_a_timer_as_the_anchor(writer):
    """Отказ у ИСТОЧНИКА: якорь-будильник не записывается вовсе.

    Контракт прежний (`({}, причина)`, как у неподтверждённого процесса) — запись просто
    уходит без якоря вместо якоря, который лжёт. Причина обязана НАЗЫВАТЬ, что делать.

    **Обе пробы инъектированы (#453).** Раньше здесь подавалась только `ps` (старт), а
    КОМАНДУ процесса писатель спрашивал у живой машины — и вердикт решал не код, а то, кто
    сегодня занял номер 42391. Тест был КРАСНЫМ на чистом `origin/main` 61d203a4f ровно
    поэтому: номер свободен, `anchor_kind` отвечал «спросить нечем», будильник не опознавался.
    """
    fields, why = writer.durable_process(env={"SPA_SESSION_PID": "42391"},
                                         ps=lambda pid: (0, STARTED),
                                         cmd_probe=_cmd(TIMER_CMD))
    assert fields == {}
    assert "sleep 36000" in why or "ПО ТАЙМЕРУ" in why
    assert "SPA_SESSION_PID" in why


def test_announce_still_records_a_real_session_anchor(writer):
    """Обратный контроль писателя: настоящий процесс сессии записывается как прежде.

    Раньше обратный контроль добывал ту же инъекцию окольно — подменял ЦЕЛИКОМ
    `_load_resolver`, чтобы подсунуть модулю свой `_ps_command`. Обход работал, но означал,
    что параметра нет: соседний (прямой) тест такого обхода не делал и потому судил о хосте.
    """
    fields, why = writer.durable_process(env={"SPA_SESSION_PID": "29988"},
                                         ps=lambda pid: (0, STARTED),
                                         cmd_probe=_cmd(SESSION_CMD))
    assert why == ""
    assert fields["session_pid"] == 29988


def test_the_command_probe_actually_reaches_the_anchor_check(writer):
    """Положительный контроль ПРОВОДКИ: уроните проброс — тест покраснеет на ЛЮБОМ хосте.

    Якорем объявлен `os.getpid()` — процесс, живой по построению на любой машине, и его
    настоящая команда (`python3 -m pytest …`) будильником НЕ является. Поэтому:

    * проброс есть  ⇒ судит поданная проба (`sleep 36000`) ⇒ отказ;
    * проброс снят  ⇒ судит настоящая ОС (`pytest`) ⇒ якорь записан ⇒ КРАСНЫЙ.

    Обе стороны не зависят от того, какие номера заняты на машине: это и есть разница
    между «повезло» и «измерено» (`.claude/rules/deployment.md`, «ЛИЧНОСТЬ ПРОЦЕССА»).
    """
    import os as _os

    fields, why = writer.durable_process(env={"SPA_SESSION_PID": str(_os.getpid())},
                                         ps=lambda pid: (0, STARTED),
                                         cmd_probe=_cmd(TIMER_CMD))
    assert fields == {}, "поданная проба команды не доехала до проверки якоря"
    assert "ПО ТАЙМЕРУ" in why

    ok, why_ok = writer.durable_process(env={"SPA_SESSION_PID": str(_os.getpid())},
                                        ps=lambda pid: (0, STARTED),
                                        cmd_probe=_cmd(SESSION_CMD))
    assert why_ok == "" and ok["session_pid"] == _os.getpid(), (
        "обратная сторона: с пробой «это сессия» якорь обязан записаться")
