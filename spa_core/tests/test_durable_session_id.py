"""Долгоживущий процесс сессии в announce-логе — активность СЕССИИ становится измеримой.

Карточка `agent-durable-session-id` (заведена циклом #45 при постройке шага 0a). Дефект:
`scripts/log_session_change.py` писал в `session` идентификатор вида `pid<os.getpid()>` —
pid **однократной CLI-команды**, который умирает вместе с ней. Следствия, все три измерены:

1. `ps -p <pid>` отвечает «процесса нет» для ЛЮБОЙ записи, включая сделанную секунду назад
   своей же сессией ⇒ вывод «активность не подтверждена» бессодержателен;
2. идентификаторы без pid (`cycle49`, `cycle55`, `cycle61` — их выставляет `SPA_SESSION_ID`)
   давали `UNKNOWN` **детерминированно и необратимо**: 31.07 это заперло две карточки бэклога
   на 19ч+ (карточка `agent-weak-mention-locks-card-forever` разбирала последствия, а не корень);
3. шаг 0a вынужден решать по ВОЗРАСТУ объявления, а не по факту активности.

Здесь корень: сессия, у которой есть долгоживущий процесс (`scripts/agent_orchestrator.sh` —
его оболочка ждёт весь цикл), объявляет его через `SPA_SESSION_PID`, и запись несёт
`session_pid` + `session_pid_start`. Дальше активность ИЗМЕРЯЕТСЯ, а окно ожидания остаётся
запасным критерием.

Два направления ошибки различаются намеренно и пиннятся тестами:
- pid НЕ берётся из `os.getppid()` — оболочка терминала живёт сутками, и такой «долгоживущий
  процесс» отвечал бы ACTIVE вечно, а шаг 0a (его работа — замечать недоставленное) молчал бы.
  Это fail-OPEN, класс #29/#31/#35–#38/#40, поэтому только явное объявление сессии;
- переиспользованный ОС pid ловится сверкой времени старта (проверка ЛИЧНОСТИ процесса), а не
  списывается в «не измерено»: это измеренный факт «это другой процесс».

Тесты герметичны: свой журнал в `tmp_path`, `ps` подменяется, время подаётся явно; сети,
git и живого журнала здесь нет.
"""
import ast
import importlib.util
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

NOW = datetime(2026, 7, 31, 20, 0, 0, tzinfo=timezone.utc)
# Объявления в тестах делаются в NOW-6ч: «до» — старт процесса раньше объявления,
# «после» — позже (так выглядит переиспользованный ОС pid).
STARTED_BEFORE = (NOW - timedelta(hours=12)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
STARTED_AFTER = (NOW - timedelta(hours=1)).astimezone().strftime("%a %b %d %H:%M:%S %Y")


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def writer():
    return _load("_test_durable_writer", "scripts/log_session_change.py")


@pytest.fixture(scope="module")
def guard():
    return _load("_test_durable_guard", "scripts/check_undelivered_work.py")


@pytest.fixture(scope="module")
def claim_guard():
    return _load("_test_durable_claim_guard", "scripts/check_card_claim.py")


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ps_alive(_pid):
    """Процесс жив и стартовал ДО объявления."""
    return 0, STARTED_BEFORE + "\n"


def ps_dead(_pid):
    return 1, ""


def ps_broken(_pid):
    return 127, ""


def ps_reused(_pid):
    """pid занят ДРУГИМ процессом — стартовал позже, чем записан старт сессии."""
    return 0, STARTED_AFTER + "\n"


def entry(session="cycle62", *, ts=None, pid=None, start=None, **extra):
    e = {"ts": _fmt(ts or (NOW - timedelta(hours=6))), "session": session,
         "summary": "работа", "files": [], "verified": ""}
    if pid is not None:
        e["session_pid"] = pid
    if start is not None:
        e["session_pid_start"] = start
    e.update(extra)
    return e


# ── писатель: что вообще попадает в журнал ───────────────────────────────────

class TestWriterRecordsOnlyConfirmedProcess:
    def test_declared_live_process_is_recorded_with_its_start(self, writer):
        proc, why = writer.durable_process(env={"SPA_SESSION_PID": "4242"}, ps=ps_alive)
        assert why == ""
        assert proc == {"session_pid": 4242, "session_pid_start": STARTED_BEFORE}

    def test_nothing_declared_means_no_new_keys(self, writer):
        """Обычный случай сегодня: схема записи не меняется ни на байт."""
        proc, why = writer.durable_process(env={}, ps=ps_alive)
        assert proc == {}
        assert "SPA_SESSION_PID" in why

    def test_declared_process_that_is_already_gone_is_not_recorded(self, writer):
        """Записать pid, которого нет, — это и есть правдоподобное число ни о чём."""
        proc, why = writer.durable_process(env={"SPA_SESSION_PID": "4242"}, ps=ps_dead)
        assert proc == {}
        assert "pid4242" in why

    def test_unmeasurable_ps_is_not_recorded(self, writer):
        proc, why = writer.durable_process(env={"SPA_SESSION_PID": "4242"}, ps=ps_broken)
        assert proc == {}
        assert "rc=127" in why

    @pytest.mark.parametrize("raw", ["", "   ", "abc", "12x", "-5", "0", "1"])
    def test_garbage_or_init_pid_is_refused(self, writer, raw):
        """pid 1 (launchd) жив всегда и не принадлежит сессии ⇒ вечный ложный ACTIVE."""
        proc, _why = writer.durable_process(env={"SPA_SESSION_PID": raw}, ps=ps_alive)
        assert proc == {}

    def test_parent_pid_is_never_used_as_the_durable_process(self, writer):
        """Явный запрет ppid: оболочка терминала пережила бы работу и молча дала бы ACTIVE.

        Пиннится и поведением, и AST — «в докстринге объяснено, а в коде вызывается» это
        ровно тот разрыв между обещанием и измерением, из-за которого заведена карточка."""
        proc, _why = writer.durable_process(env={}, ps=ps_alive)
        assert proc == {}
        src = (ROOT / "scripts" / "log_session_change.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        called |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "getppid" not in called


class TestWriterEntrySchema:
    def test_entry_carries_durable_fields(self, writer, tmp_path):
        log = tmp_path / "j.jsonl"
        writer.record("s", [], "", log=log, session="cycle62",
                      process=({"session_pid": 77, "session_pid_start": STARTED_BEFORE}, ""))
        row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        assert row["session_pid"] == 77 and row["session_pid_start"] == STARTED_BEFORE
        # старые ключи на месте и не переименованы
        assert set(("ts", "session", "summary", "files", "verified")) <= set(row)

    def test_entry_without_durable_process_is_byte_compatible(self, writer, tmp_path):
        log = tmp_path / "j.jsonl"
        writer.record("s", ["/a"], "v", log=log, session="cycle62", process=({}, "нет"))
        row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        assert row == {"ts": row["ts"], "session": "cycle62", "summary": "s",
                       "files": ["/a"], "verified": "v"}

    def test_all_entries_of_one_session_share_id_and_process(self, writer, tmp_path):
        """Критерий приёмки №1: записи одной сессии несут ОДИН идентификатор и один процесс."""
        log = tmp_path / "j.jsonl"
        proc = ({"session_pid": 77, "session_pid_start": STARTED_BEFORE}, "")
        for n in range(3):
            writer.record(f"шаг {n}", [], "", log=log, session="cycle62", process=proc)
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        assert {r["session"] for r in rows} == {"cycle62"}
        assert {r["session_pid"] for r in rows} == {77}
        assert {r["session_pid_start"] for r in rows} == {STARTED_BEFORE}


# ── читатель: основной критерий активности ───────────────────────────────────

class TestSessionStateUsesDurableProcess:
    def test_id_without_pid_is_now_measured(self, guard):
        """Ровно тот случай, который не измерялся НИКОГДА: `cycle62` + живой процесс."""
        state, why = guard.session_state(
            entry("cycle62", pid=4242, start=STARTED_BEFORE), "pid1", ps=ps_alive)
        assert state == guard.ACTIVE
        assert "pid4242" in why

    def test_dead_durable_process_is_not_confirmed_not_unknown(self, guard):
        state, why = guard.session_state(
            entry("cycle62", pid=4242, start=STARTED_BEFORE), "pid1", ps=ps_dead)
        assert state == guard.NOT_CONFIRMED
        assert "pid4242" in why

    def test_recycled_pid_is_caught_by_start_time(self, guard):
        """Положительный контроль: живой процесс ≠ живая сессия, если это другой процесс."""
        state, why = guard.session_state(
            entry("cycle62", pid=4242, start=STARTED_BEFORE), "pid1", ps=ps_reused)
        assert state == guard.NOT_CONFIRMED
        assert "ДРУГИМ процессом" in why

    def test_unreadable_ps_stays_unknown(self, guard):
        state, _why = guard.session_state(
            entry("cycle62", pid=4242, start=STARTED_BEFORE), "pid1", ps=ps_broken)
        assert state == guard.UNKNOWN

    @pytest.mark.parametrize("bad", ["abc", "", None, 0, 1, -3, True, 1.5, []])
    def test_garbage_durable_pid_is_unknown_never_active(self, guard, bad):
        state, _why = guard.session_state(
            entry("cycle62", pid=bad, start=STARTED_BEFORE), "pid1", ps=ps_alive)
        assert state == guard.UNKNOWN

    def test_unparsable_recorded_start_is_unknown(self, guard):
        state, _why = guard.session_state(
            entry("cycle62", pid=4242, start="не время"), "pid1", ps=ps_alive)
        assert state == guard.UNKNOWN

    def test_durable_pid_without_recorded_start_falls_back_to_announcement(self, guard):
        """Совместимость вперёд: старт не записан → прежнее правило «старт до объявления»."""
        alive = guard.session_state(entry("cycle62", pid=4242), "pid1", ps=ps_alive)
        later = guard.session_state(entry("cycle62", pid=4242), "pid1", ps=ps_reused)
        assert alive[0] == guard.ACTIVE
        assert later[0] == guard.NOT_CONFIRMED

    def test_durable_process_outranks_the_id_pid(self, guard):
        """Основной критерий — процесс записи, а не pid из идентификатора."""
        state, _why = guard.session_state(
            entry("pid4242", pid=99, start=STARTED_BEFORE), "pid1",
            ps=lambda pid: ps_alive(pid) if pid == 4242 else ps_dead(pid))
        assert state == guard.NOT_CONFIRMED

    def test_self_session_still_wins(self, guard):
        state, why = guard.session_state(
            entry("cycle62", pid=4242, start=STARTED_BEFORE), "cycle62", ps=ps_dead)
        assert state == guard.ACTIVE and why == "это текущая сессия"

    def test_broken_timestamp_still_unknown_before_process_is_probed(self, guard):
        probed = []

        def _ps(pid):
            probed.append(pid)
            return ps_alive(pid)

        state, _why = guard.session_state(
            entry("cycle62", ts=None, pid=4242, start=STARTED_BEFORE) | {"ts": "не дата"},
            "pid1", ps=_ps)
        assert state == guard.UNKNOWN and probed == []


class TestBackwardCompatibility:
    """Старые записи (их в живом журнале сотни) разбираются ровно как раньше."""

    def test_old_entry_without_new_keys_uses_id_pid(self, guard):
        alive = guard.session_state(entry("pid4242"), "pid1", ps=ps_alive)
        dead = guard.session_state(entry("pid4242"), "pid1", ps=ps_dead)
        assert alive[0] == guard.ACTIVE and "pid4242 жив" in alive[1]
        assert dead[0] == guard.NOT_CONFIRMED

    def test_old_entry_with_pidless_id_is_still_unknown(self, guard):
        """Записи ДО этой правки не становятся задним числом «измеренными»."""
        state, why = guard.session_state(entry("cycle49"), "pid1", ps=ps_alive)
        assert state == guard.UNKNOWN
        assert "не содержит pid" in why

    def test_durable_fields_extracts_only_the_two_keys(self, guard):
        e = entry("cycle62", pid=7, start=STARTED_BEFORE, card="agent-x")
        assert guard.durable_fields(e) == {"session_pid": 7,
                                           "session_pid_start": STARTED_BEFORE}
        assert guard.durable_fields(entry("pid1")) == {}
        assert guard.durable_fields("не запись") == {}


# ── шаг 0b: улучшение обязано доехать до второго потребителя ─────────────────

class TestStep0bSeesTheDurableProcess:
    def _run(self, claim_guard, tmp_path, rows, *, ps, status="backlog"):
        tracker = tmp_path / "tracker"
        tracker.mkdir(exist_ok=True)
        (tracker / "agent-x.md").write_text(
            "---\ntrackerStatus:\n  type: agent-task\ntitle: T\n"
            f"status: {status}\n---\n\nтело\n", encoding="utf-8")
        log = tmp_path / "session_changes.jsonl"
        log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                       encoding="utf-8")
        return claim_guard.gather("agent-x", log=log, tracker_dir=tracker,
                                  self_session="pid1", now=NOW, ps=ps)

    def _claim(self, ts_hours_ago, **kw):
        return entry(ts=NOW - timedelta(hours=ts_hours_ago), card="agent-x",
                     card_state="claim", **kw)

    def test_live_process_and_silence_makes_an_old_claim_stale(self, claim_guard, tmp_path):
        """Старый захват + живой процесс + МОЛЧАНИЕ дольше окна ⇒ `stale`, не «занята».

        **Изменение теста намеренное, инвариант #16 (цикл #413).** Раньше здесь стояло
        `verdict == CLAIMED` под заголовком «живой процесс = сессия работает, а не бросила
        работу». Замер 28.08 показал цену этого равенства: цикл #410 объявил якорем pid10980 —
        процесс `claude` ДЕСКТОПНОГО приложения (ppid=1533 = Claude.app), который хостит идущие
        одна за другой сессии и переживает каждую. Сессия умерла, работа осталась в `/tmp`, а
        карточка с ОТВЕТОМ ВЛАДЕЛЬЦА стала неберущейся НАВСЕГДА: `ps` отвечал бы «жив» и через
        неделю. «Процесс существует» и «сессия работает» — разные утверждения, и первое не
        доказывает второго.

        **Что тест защищает по-прежнему, и это главное:** карточку НЕ отдают — код возврата
        остаётся 1, `free` не произносится, авто-захвата нет; подъём требует явного
        `--takeover` с письменной причиной. Меняется ровно ярлык исхода: вечная блокировка
        становится разбираемой находкой. Личность держателя по-прежнему НАЗЫВАЕТСЯ.

        Обратный контроль — тест ниже: живой И говорящий держатель даёт `claimed`, как раньше.
        """
        r = self._run(claim_guard, tmp_path, [self._claim(9, pid=4242, start=STARTED_BEFORE)],
                      ps=ps_alive)
        assert r["verdict"] == claim_guard.STALE
        assert r["claims"][0]["state"] == "stale"
        assert claim_guard.exit_code(r) == 1, "очередь закрыта: карточку брать нельзя"
        assert r["verdict"] != claim_guard.FREE
        assert "pid4242" in r["claims"][0]["session_state"]

    def test_live_and_speaking_process_still_claims(self, claim_guard, tmp_path):
        """Обратный контроль: тот же живой процесс, но сессия подала голос в окне ⇒ `claimed`.

        Это и есть граница, проведённая циклом #413: держит не существование процесса, а
        измеренное присутствие сессии. Сессия, копающая одну задачу девятый час и объявляющая
        по дороге, остаётся свежей — и её карточку по-прежнему не отдают.
        """
        rows = [self._claim(9, pid=4242, start=STARTED_BEFORE),
                entry(ts=NOW - timedelta(minutes=10), pid=4242, start=STARTED_BEFORE)]
        r = self._run(claim_guard, tmp_path, rows, ps=ps_alive)
        assert r["verdict"] == claim_guard.CLAIMED
        assert r["claims"][0]["state"] == "fresh"
        assert claim_guard.exit_code(r) == 1

    def test_dead_process_makes_it_stale_instead_of_unmeasured(self, claim_guard, tmp_path):
        """До правки id без pid давал `unchecked` — «брать нельзя», и это не проходило."""
        r = self._run(claim_guard, tmp_path, [self._claim(9, pid=4242, start=STARTED_BEFORE)],
                      ps=ps_dead)
        assert r["verdict"] == claim_guard.STALE
        assert r["unmeasured"] == []

    def test_recycled_pid_does_not_pass_as_a_live_session(self, claim_guard, tmp_path):
        r = self._run(claim_guard, tmp_path, [self._claim(9, pid=4242, start=STARTED_BEFORE)],
                      ps=ps_reused)
        assert r["verdict"] == claim_guard.STALE

    def test_claim_without_durable_process_behaves_exactly_as_before(self, claim_guard,
                                                                     tmp_path):
        """Положительный контроль: без новых полей вердикт прежний (fail-CLOSED сохранён)."""
        r = self._run(claim_guard, tmp_path, [self._claim(9, session="cycle49")], ps=ps_alive)
        assert r["verdict"] == claim_guard.UNCHECKED
        assert claim_guard.exit_code(r) == 2

    def test_unmeasurable_ps_keeps_fail_closed(self, claim_guard, tmp_path):
        r = self._run(claim_guard, tmp_path, [self._claim(9, pid=4242, start=STARTED_BEFORE)],
                      ps=ps_broken)
        assert r["verdict"] == claim_guard.UNCHECKED
        assert claim_guard.exit_code(r) == 2

    def test_done_release_still_wins_over_a_live_process(self, claim_guard, tmp_path):
        """Объявленное `done` снимает захват — живой процесс это не отменяет."""
        rows = [self._claim(9, pid=4242, start=STARTED_BEFORE),
                self._claim(8, pid=4242, start=STARTED_BEFORE) | {"card_state": "done"}]
        r = self._run(claim_guard, tmp_path, rows, ps=ps_alive)
        assert r["verdict"] == claim_guard.FREE


# ── production-путь: цикл обязан объявлять свой долгоживущий процесс ─────────

class TestOrchestratorWrapperDeclaresItsProcess:
    def test_wrapper_exports_its_own_shell_pid(self):
        src = (ROOT / "scripts" / "agent_orchestrator.sh").read_text(encoding="utf-8")
        assert re.search(r"^export SPA_SESSION_PID=\$\$", src, re.M)
        assert re.search(r"^export SPA_SESSION_ID=", src, re.M)

    def test_export_happens_before_claude_is_invoked(self):
        """Иначе сессия унаследует пустое окружение и объявления снова будут неизмеримы."""
        src = (ROOT / "scripts" / "agent_orchestrator.sh").read_text(encoding="utf-8")
        assert src.index("export SPA_SESSION_PID=$$") < src.index('"$CLAUDE_BIN"')
