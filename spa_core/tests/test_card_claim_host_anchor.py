"""Живой якорь — не бессрочный замок: якорь-ХОСТ переживает сессию и запирал карточку навсегда.

**Авария, которую проигрывает каждый положительный тест здесь** (28.08.2026, цикл #412, живой
замер). Карточка `own-pererazdavat-li-srezannoe-zaschitami` несла ОТВЕТ ВЛАДЕЛЬЦА — вариант 2,
`owner_answered_at: 2026-08-28T06:47:16Z`, след уехал на `origin/main` коммитом `eb66fcb9d`.
Работу по ней делали два цикла подряд, и оба умерли, не доставив:

- #409 (`cycle-93730`, якорь pid93758) — объявился в 07:41:56Z, `verified: "pending: тесты будут
  прогнаны до пуша"`; процесс измеримо мёртв ⇒ шаг 0b честно назвал захват `stale`;
- #410 (`cycle-33355`) — поднял работу #409 в 09:01:21Z и объявил якорем **pid10980**.

pid10980 — это `/Applications/Claude.app/Contents/Helpers/disclaimer -- …/claude …`, ppid=1533
(сам Claude.app): процесс-ХОСТ десктопного приложения, внутри которого идут одна за другой
сессии. Цикл #410 умер (его собственный прогон приёмки остался сиротой, ppid=1, и молотил
2 ч 39 мин, пока его не сняли), а `ps -p 10980` отвечал «жив» — и ответил бы так же завтра.

Вердикт шага 0b: `⛔ ЗАНЯТА — НЕ бери эту карточку`. **Навсегда.** Не «пока свежо»: в
`_classify` условие блокировки читалось `state == ACTIVE or (fresh and …)` — подтверждённая
жизнь якоря стояла ПЕРЕД окном свежести и окну не подчинялась. Значит любая карточка, взятая
десктопной сессией, запиралась до перезапуска приложения, а ответ владельца лежал бы
недоставленным ровно столько же.

**Почему это не лечится опознанием якоря.** Проверка `anchor_kind` (#393) отвергает якоря,
выходящие ПО ТАЙМЕРУ, по имени команды — так закрыт `sleep`. Здесь имя не помогает: `claude`
ИНОГДА и есть процесс сессии (headless `-p` из `agent_orchestrator.sh` умирает вместе с
циклом), а иногда — её хост. Отвергать по имени значило бы обвинить верный якорь.

**Что изменено (цикл #412).** Жизнь якоря перестала быть БЕССРОЧНЫМ доводом. Живой якорь плюс
голос сессии в окне ⇒ `claimed`, как и раньше. Живой якорь плюс молчание дольше окна ⇒ `stale`
— «кандидат на ручной подъём». Это НЕ ослабление: `stale` даёт тот же код возврата 1, карточку
молча взять по-прежнему нельзя, авто-захвата нет — нужен явный `claim --takeover "<чем
сверил>"` после ручной сверки по шагу 0a. Меняется ровно один исход: **вечная блокировка
становится разбираемой находкой.**

Голос меряется по ВСЕМУ журналу (`last_voice_by_session`), а не по захвату этой карточки:
сессия, которая долго копает одну карточку, но объявляет по дороге владение файлами, остаётся
свежей. Иначе честно работающая сессия теряла бы карточку за то, что не перезахватывала её
каждые три часа.

Тесты герметичны: свой журнал и свой каталог карточек в ``tmp_path``, `ps` подменяется, время
подаётся ВХОДОМ (`now=NOW`). Все отметки журнала и времена старта процессов отсчитываются от
той же точки — обе стороны каждого сравнения закреплены, поэтому файл не привязан к календарю
(правило `.claude/rules/deployment.md`, порядок предпочтения 1).
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# FROZEN-DATE-OK: время здесь — ВХОД, а не окружение (правило `.claude/rules/deployment.md`,
# порядок предпочтения 1). `now` подаётся сторожу явно, все отметки отсчитываются от этой же
# точки ⇒ смена календаря тест не двигает. Часы на уровне модуля читать нельзя (сторож
# `test_no_import_time_clock_in_tests`), поэтому точка — литерал.
NOW = datetime(2026, 8, 28, 12, 30, 0, tzinfo=timezone.utc)

#: Карточка живого замера — та самая, с ответом владельца.
CARD = "own-pererazdavat-li-srezannoe-zaschitami"

#: Ярлык и якорь цикла #410 из живого замера. Хост стартовал ЗАДОЛГО до записи — так и было
#: (10:09:13+02:00 против объявления в 09:01:21Z), и так сужение `borrow_durable` не мешает.
HOST_STARTED = NOW - timedelta(hours=4)
HOST_PID = 10980
DESKTOP_LABEL = "cycle-33355"


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_host_anchor_card_claim", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lstart(dt):
    """Время старта процесса в формате `ps -o lstart=` (локальная зона, как отдаёт сам `ps`)."""
    return dt.astimezone().strftime("%a %b %d %H:%M:%S %Y")


ANCHOR = {"session_pid": HOST_PID, "session_pid_start": _lstart(HOST_STARTED)}


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


@pytest.fixture()
def log(tmp_path):
    p = tmp_path / "session_changes.jsonl"
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture()
def ps_host_alive():
    """`ps` отвечает «жив» — процесс-хост десктопного приложения переживает сессию."""
    return lambda pid: (0, _lstart(HOST_STARTED) + "\n")


def write_card(tracker, cid, *, status="needs-owner"):
    p = tracker / f"{cid}.md"
    p.write_text("---\ntrackerStatus:\n  type: owner-decision\ntitle: Карточка\n"
                 f"status: {status}\nowner_choice: 2\n---\n\nтело\n", encoding="utf-8")
    return p


def entry(session, ts, *, anchor=None, card=None, card_state="claim", files=(),
          summary="работа"):
    e = {"ts": _fmt(ts), "session": session, "summary": summary,
         "files": [str(f) for f in files], "verified": ""}
    if card:
        e["card"], e["card_state"] = card, card_state
    if anchor:
        e.update(anchor)
    return e


def write_log(path, entries):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                    encoding="utf-8")


def run(guard, sibling, tracker, log, card=CARD, *, session="cycle-48146", ps=None,
        planned_files=()):
    return guard.gather(card, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=session, now=NOW, grace_hours=3.0,
                        planned_files=planned_files, ps=ps, self_anchor=None)


class TestHostAnchorNoLongerLocksForever:
    """Положительные контроли: ровно форма замера 28.08."""

    def test_silent_desktop_session_is_stale_not_claimed(self, guard, sibling, tracker, log,
                                                         ps_host_alive):
        """Живой якорь-хост + молчание 3.5ч ⇒ `stale`, а не вечное «ЗАНЯТА».

        На неисправленном сторже здесь `claimed` — и никакое ожидание этого не меняет."""
        write_card(tracker, CARD)
        write_log(log, [entry(DESKTOP_LABEL, NOW - timedelta(hours=3.5), anchor=ANCHOR,
                              card=CARD)])
        r = run(guard, sibling, tracker, log, ps=ps_host_alive)

        assert r["verdict"] == guard.STALE
        assert r["claims"][0]["state"] == "stale"
        assert r["claims"][0]["silent_hours"] == 3.5

    def test_the_lock_was_eternal_not_merely_long(self, guard, sibling, tracker, log,
                                                  ps_host_alive):
        """Суть аварии: замок не истекал НИКОГДА. Через неделю молчания — по-прежнему не
        `claimed`. Именно это отличает дефект от «окно великовато»."""
        write_card(tracker, CARD)
        write_log(log, [entry(DESKTOP_LABEL, NOW - timedelta(days=7), anchor=ANCHOR,
                              card=CARD)])
        r = run(guard, sibling, tracker, log, ps=ps_host_alive)

        assert r["verdict"] == guard.STALE, "неделя молчания при живом хосте — всё ещё замок"

    def test_takeover_path_is_open_on_stale(self, guard, sibling, tracker, log, ps_host_alive):
        """Находка обязана иметь ВЫХОД, и он проверяется настоящим `claim --takeover`.

        Без этого сторож запрещал бы ровно то действие, к которому зовёт протокол (подъём
        осиротевшей работы). На неисправленном сторже вердикт `claimed`, и `claim_card`
        отказывает флагу подъёма — то есть карточку нельзя взять НИКАК."""
        card_path = write_card(tracker, CARD)
        write_log(log, [entry(DESKTOP_LABEL, NOW - timedelta(hours=3.5), anchor=ANCHOR,
                              card=CARD)])
        out = guard.claim_card(
            CARD, log=log, tracker_dir=tracker, sibling=sibling, session="cycle-48146",
            now=NOW, grace_hours=3.0, ps=ps_host_alive,
            # Своя личность — СВОЙ процесс, отличный от хоста: подъём обязан быть измеримым
            # для следующего цикла, иначе он воспроизводит ту же болезнь.
            self_anchor=(48146, _lstart(NOW - timedelta(minutes=5))),
            takeover_reason="сверил: прогон приёмки держателя осиротел (ppid=1), "
                            "работа на origin не уехала")

        assert out.get("claimed") or out.get("claimed_by"), out
        body = card_path.read_text(encoding="utf-8")
        assert "cycle-48146" in body, "подъём обязан отметиться на карточке"
        assert "claim_takeover_reason" in body, "причина подъёма записывается, а не молчит"


class TestNotAWeakening:
    """Обратные контроли: карточку живой сессии по-прежнему не отдают."""

    def test_live_and_speaking_session_still_claimed(self, guard, sibling, tracker, log,
                                                     ps_host_alive):
        """Захват стар, но сессия объявилась 10 минут назад ⇒ работает ⇒ `claimed`.

        Это и есть причина мерить голос по ВСЕМУ журналу, а не по захвату: сессия,
        копающая одну карточку четвёртый час, не должна её терять."""
        write_card(tracker, CARD)
        write_log(log, [
            entry(DESKTOP_LABEL, NOW - timedelta(hours=3.5), anchor=ANCHOR, card=CARD),
            entry(DESKTOP_LABEL, NOW - timedelta(minutes=10), anchor=ANCHOR,
                  summary="всё ещё копаю", files=["/x/y.py"]),
        ])
        r = run(guard, sibling, tracker, log, ps=ps_host_alive)

        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["state"] == "fresh"

    def test_stale_is_not_free_queue_stays_closed(self, guard, sibling, tracker, log,
                                                  ps_host_alive):
        """`stale` ≠ «свободна»: код возврата 1, взять молча по-прежнему нельзя."""
        write_card(tracker, CARD)
        write_log(log, [entry(DESKTOP_LABEL, NOW - timedelta(hours=3.5), anchor=ANCHOR,
                              card=CARD)])
        r = run(guard, sibling, tracker, log, ps=ps_host_alive)

        assert r["verdict"] != guard.FREE
        assert guard.exit_code(r) == 1

    def test_unmeasured_still_wins_over_stale(self, guard, sibling, tracker, log):
        """fail-CLOSED не тронут: «занятость не измерена» по-прежнему перебивает и даёт 2."""
        write_card(tracker, CARD)
        write_log(log, [entry("cycle-no-anchor", NOW - timedelta(hours=3.5), card=CARD)])
        r = run(guard, sibling, tracker, log, ps=lambda pid: (127, ""))

        assert r["verdict"] == guard.UNCHECKED
        assert guard.exit_code(r) == 2

    def test_fresh_claim_of_a_dead_session_is_still_stale(self, guard, sibling, tracker, log):
        """Починка #238 цела: свежий захват измеримо мёртвой сессии — `stale`, не `claimed`."""
        write_card(tracker, CARD)
        write_log(log, [entry(DESKTOP_LABEL, NOW - timedelta(minutes=20), anchor=ANCHOR,
                              card=CARD)])
        r = run(guard, sibling, tracker, log, ps=lambda pid: (1, ""))

        assert r["verdict"] == guard.STALE
