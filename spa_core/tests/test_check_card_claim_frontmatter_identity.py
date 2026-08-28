"""Шаг 0b: захват из frontmatter перестал быть ВЕЧНЫМ замком.

**Авария, которую воспроизводит каждый тест этого файла** (замерено циклом #146, 2026-08-07).
`check_card_claim.py` классифицировал захват из поля `claimed_by` с `process=None`, а
`session_state` для ярлыка без pid отдаёт `UNKNOWN` детерминированно и НЕОБРАТИМО. Старый
СИЛЬНЫЙ захват + `UNKNOWN` ⇒ «НЕ ИЗМЕРЕНО» ⇒ код возврата 2 ⇒ «брать нельзя». Вердикт,
который не может проясниться сам: захватившая сессия мертва, её ярлык pid не содержит, а
личность процесса инструмент не спрашивал. Живьём этим были заперты три карточки:

    inbox-kartochka-sozdannaya-posredi-tsikla-ne-d   cycle-20906   8.7ч
    inbox-tier-c-171-iz-180-modulei-ne-otvechayut    cycle-63608  14.7ч
    agent-fleet-parity-guard-never-scheduled         cycle-28258    44ч

— то есть 3 из 5 открытых inbox-карточек были недоступны КАЖДОЙ будущей сессии, и не потому,
что кто-то работает, а потому что формат ярлыка, который пишет сам же `claim`, не измеряется
проверкой `check`.

**Личность при этом лежала в том же журнале**, который инструмент уже читает: `claim` пишет
объявление, а `log_session_change.durable_process` кладёт в него `session_pid` +
`session_pid_start`. Проверено для всех трёх ярлыков выше — поля есть.

**Направление правки — не ослабление, а недостающее измерение.** Живой держатель теперь даёт
`ACTIVE` и блокирует СИЛЬНЕЕ прежнего (раньше он тоже читался как «не измерено»); мёртвый —
честный `stale`, то есть кандидат на ручной подъём по шагу 0a, а не разрешение забрать работу.
Обратное направление закреплено тестами: нет личности в журнале / личности противоречат /
`ps` сломан ⇒ поведение прежнее, fail-CLOSED.

Время — ВХОД, а не окружение (`.claude/rules/deployment.md`, преференция №1): `now` подаётся
в `gather`, отметки выводятся из него же. Литеральных дат в файле нет — обе стороны закреплены,
и календарь его не уронит.
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Личность держателя карточки: ярлык БЕЗ pid — ровно тот случай, который запирал очередь.
HOLDER = "cycle-20906"
HOLDER_PID = 20906


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_card_claim_identity", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture()
def now():
    """Часы инъектируются — фикстура не привязана ни к одной календарной дате."""
    return datetime.now(timezone.utc)


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lstart(dt):
    """`ps -o lstart=` — вербатим-формат, в котором пишется `session_pid_start`."""
    return dt.astimezone().strftime("%a %b %d %H:%M:%S %Y")


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


def write_card(tracker, cid, *, claimed_by=None, claimed_at=None, status="new"):
    fm = ["---", "trackerStatus:", "  type: inbox", "title: Карточка под захватом",
          f"status: {status}"]
    if claimed_by:
        fm.append(f"claimed_by: {claimed_by}")
    if claimed_at:
        fm.append(f"claimed_at: {claimed_at}")
    fm.append("---")
    p = tracker / f"{cid}.md"
    p.write_text("\n".join(fm) + "\n\nтело\n", encoding="utf-8")
    return p


def write_log(path, entries):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                    encoding="utf-8")


def claim_entry(session, ts, *, pid=None, started=None, card="other-card"):
    """Объявление захвата — ровно то, что пишет `claim` через `announce_claim`.

    `card` намеренно указывает на ДРУГУЮ карточку: личность держателя должна браться из
    журнала по ярлыку, а не из записи, относящейся к этой же карточке (иначе тест проверял бы
    путь журнала, а не путь frontmatter — дефект был именно во втором)."""
    e = {"ts": _fmt(ts), "session": session, "summary": "работа", "files": [],
         "card": card, "card_state": "claim", "verified": ""}
    if pid is not None:
        e["session_pid"] = pid
    if started is not None:
        e["session_pid_start"] = _lstart(started)
    return e


def run(guard, sibling, tracker, log, card, *, now, ps, session="cycle-146"):
    return guard.gather(card, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=session, now=now, grace_hours=3.0,
                        planned_files=(), ps=ps, self_anchor=None)


# ── авария 07.08: вечный замок ───────────────────────────────────────────────

class TestDeadHolderIsMeasuredNotLocked:
    """Каждый тест — воспроизведение реального замка; на неисправленном коде все красные."""

    def test_dead_holder_is_stale_not_unmeasured(self, guard, sibling, tracker, log, now):
        """Держатель мёртв, личность в журнале есть ⇒ `stale`, а не вечное «не измерено»."""
        started = now - timedelta(hours=12)
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=8.7)))
        write_log(log, [claim_entry(HOLDER, now - timedelta(hours=8.7),
                                    pid=HOLDER_PID, started=started)])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now, ps=lambda pid: (1, ""))

        assert r["unmeasured"] == [], "замок остался: захват снова ушёл в «не измерено»"
        assert r["verdict"] == guard.STALE
        assert guard.exit_code(r) == 1, "код 2 = «брать нельзя» — это и был вечный замок"
        claim = r["claims"][0]
        assert claim["source"] == "frontmatter" and claim["session"] == HOLDER
        assert claim["state"] == "stale"
        assert f"pid{HOLDER_PID}" in claim["session_state"], claim["session_state"]

    def test_stale_verdict_still_demands_manual_pickup(self, guard, sibling, tracker, log, now):
        """`stale` — это НЕ «забирай»: порядок подъёма осиротевшей работы остаётся ручным."""
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=8.7)))
        write_log(log, [claim_entry(HOLDER, now - timedelta(hours=8.7),
                                    pid=HOLDER_PID, started=now - timedelta(hours=12))])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now, ps=lambda pid: (1, ""))
        assert "вручную" in guard.render(r).lower()

    def test_live_holder_is_measured_not_unmeasured(self, guard, sibling, tracker, log, now):
        """Обратное направление: живой держатель ИЗМЕРЕН (раньше — «не измерено»).

        **Правка намеренная (инвариант #16, цикл #412).** То, ради чего тест написан —
        «личность держателя берётся из журнала, и „не измерено" больше не возвращается» —
        закреплено сильнее прежнего: `unmeasured` пуст, код возврата 1, карточка не отдана.
        Изменился ярлык исхода: захват здесь старше окна (8.7ч при 3ч) и голоса моложе у
        сессии нет, а живой якорь с 28.08 не держит карточку бессрочно. Живой И говорящий
        держатель по-прежнему `claimed` — тест ниже."""
        started = now - timedelta(hours=12)
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=8.7)))
        write_log(log, [claim_entry(HOLDER, now - timedelta(hours=8.7),
                                    pid=HOLDER_PID, started=started)])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now,
                ps=lambda pid: (0, _lstart(started) + "\n"))

        assert r["verdict"] == guard.STALE
        assert guard.exit_code(r) == 1
        assert r["claims"][0]["state"] == "stale"
        assert r["unmeasured"] == [], "личность держателя измерена — это и защищает тест"

    def test_live_and_speaking_holder_blocks(self, guard, sibling, tracker, log, now):
        """Та же форма, но захват в окне ⇒ `claimed` и `fresh`, как до цикла #412."""
        started = now - timedelta(hours=12)
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=0.5)))
        write_log(log, [claim_entry(HOLDER, now - timedelta(hours=0.5),
                                    pid=HOLDER_PID, started=started)])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now,
                ps=lambda pid: (0, _lstart(started) + "\n"))

        assert r["verdict"] == guard.CLAIMED
        assert guard.exit_code(r) == 1
        assert r["claims"][0]["state"] == "fresh", "подтверждённая активность важнее возраста"
        assert r["unmeasured"] == []

    def test_reused_pid_is_another_process_not_a_live_holder(self, guard, sibling, tracker,
                                                             log, now):
        """Тот же номер pid с ДРУГИМ временем старта — измеренное «это другой процесс»."""
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=8.7)))
        write_log(log, [claim_entry(HOLDER, now - timedelta(hours=8.7),
                                    pid=HOLDER_PID, started=now - timedelta(hours=12))])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now,
                ps=lambda pid: (0, _lstart(now - timedelta(minutes=5)) + "\n"))

        assert r["verdict"] == guard.STALE, "чужой процесс на том же номере — не живой держатель"
        assert r["unmeasured"] == []
        assert "ДРУГИМ процессом" in r["claims"][0]["session_state"]


# ── контроль в обратную сторону: fail-CLOSED там, где мерить нечем ───────────

class TestUnmeasurableStaysUnmeasured:
    def test_holder_without_identity_in_log_stays_unmeasured(self, guard, sibling, tracker,
                                                             log, now):
        """Личности в журнале нет ⇒ поведение прежнее: «не измерено», код 2."""
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=8.7)))
        write_log(log, [claim_entry(HOLDER, now - timedelta(hours=8.7))])  # без pid/старта
        r = run(guard, sibling, tracker, log, "inbox-x", now=now, ps=lambda pid: (1, ""))

        assert r["unmeasured"], "молчаливого «свободна» здесь быть не должно"
        assert guard.exit_code(r) == 2

    def test_contradicting_identities_stay_unmeasured(self, guard, sibling, tracker, log, now):
        """Один ярлык — два РАЗНЫХ процесса: угадывать держателя инструмент не станет."""
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=8.7)))
        write_log(log, [
            claim_entry(HOLDER, now - timedelta(hours=20), pid=HOLDER_PID,
                        started=now - timedelta(hours=30)),
            claim_entry(HOLDER, now - timedelta(hours=8.7), pid=HOLDER_PID + 7,
                        started=now - timedelta(hours=12)),
        ])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now, ps=lambda pid: (1, ""))

        assert r["unmeasured"] and guard.exit_code(r) == 2

    def test_broken_ps_stays_unmeasured(self, guard, sibling, tracker, log, now):
        """`ps` не отработал — это «не измерено», а не «сессия мертва»."""
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(hours=8.7)))
        write_log(log, [claim_entry(HOLDER, now - timedelta(hours=8.7),
                                    pid=HOLDER_PID, started=now - timedelta(hours=12))])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now, ps=lambda pid: (127, ""))

        assert r["unmeasured"] and guard.exit_code(r) == 2

    def test_fresh_claim_blocks_regardless_of_identity(self, guard, sibling, tracker, log, now):
        """Защита от коллизии #46 не тронута: свежий сильный захват блокирует как прежде."""
        write_card(tracker, "inbox-x", claimed_by=HOLDER,
                   claimed_at=_fmt(now - timedelta(minutes=20)))
        write_log(log, [])
        r = run(guard, sibling, tracker, log, "inbox-x", now=now, ps=lambda pid: (1, ""))

        assert r["verdict"] == guard.CLAIMED and guard.exit_code(r) == 1


# ── единица измерения: durable_by_session ────────────────────────────────────

class TestDurableBySession:
    def test_picks_identity_and_drops_contradictions(self, guard, sibling, now):
        started = now - timedelta(hours=12)
        entries = [
            claim_entry("cycle-a", now, pid=11, started=started),
            claim_entry("cycle-a", now, pid=11, started=started),      # повтор — не конфликт
            claim_entry("cycle-b", now, pid=22, started=started),
            claim_entry("cycle-b", now, pid=23, started=started),      # конфликт ⇒ ключа нет
            claim_entry("cycle-c", now),                               # якоря нет вовсе
        ]
        got = guard.durable_by_session(entries, sibling)

        assert got["cycle-a"]["session_pid"] == 11
        assert "cycle-b" not in got, "противоречивая личность обязана исчезать, а не выбираться"
        assert "cycle-c" not in got

    def test_conflict_is_not_healed_by_a_later_repeat(self, guard, sibling, now):
        """Однажды противоречивый ярлык не «чинится» следующей согласной записью."""
        started = now - timedelta(hours=12)
        entries = [
            claim_entry("cycle-b", now, pid=22, started=started),
            claim_entry("cycle-b", now, pid=23, started=started),
            claim_entry("cycle-b", now, pid=22, started=started),
        ]
        assert "cycle-b" not in guard.durable_by_session(entries, sibling)

    def test_empty_log_yields_nothing(self, guard, sibling):
        assert guard.durable_by_session([], sibling) == {}
        assert guard.durable_by_session(None, sibling) == {}
