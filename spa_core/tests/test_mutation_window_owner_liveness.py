"""ЖИВОСТЬ ВЛАДЕЛЬЦА окна мутационного прибора (ADR-791, цикл #913).

Предмет — `scripts/delta_mutation_run.py` в части вопроса «а владелец этого окна ещё
работает?», которого до ADR-791 не задавал НИКТО: `--window-restore` возвращал байты
молча, в том числе из-под работающего прибора.

**Авария, которую воспроизводит батарея** (карточка
`inbox-zhivost-mutacionnogo-progona-sprasivali`, цикл #906). Прибор шёл в отдельном
дереве, его вывод был полностью буферизован, лог оставался 0 байт двадцать с лишним
минут — то есть «работает» и «умер» выглядели ОДИНАКОВО. Живость спросили так::

    ps -eo pid,etime | grep -q " 62944"      # совпадение по ВЕДУЩЕМУ ПРОБЕЛУ

Колонка `pid` выравнивается паддингом, и ведущий пробел не гарантирован: ответ вышел
«процесса нет» и был неверен в ОПАСНУЮ сторону. Действуя по нему, цикл выполнил
`--window-restore` на дереве РАБОТАЮЩЕГО прибора: вернулся мутант, который прибор держал
в тот миг, запись окна снялась, и остальные вердикты прогона стали недостоверны —
откаченная под прибором мутация читается как «выжила», то есть как дыра покрытия,
которой нет.

Устройство — по звеньям, у каждого обратная сторона с НАЗВАННЫМ звеном:

* ЖИВОЙ чужой владелец ⇒ ОТКАЗ со своим кодом (4), и байты дерева не тронуты — это
  положительный контроль на НАСТОЯЩЕМ приборе, без единой инъекции;
* мёртвый владелец ⇒ возврат идёт: порви звено, и путь наверх для дерева, доставшегося
  в наследство, закроется навсегда;
* СВОЁ окно ⇒ возврат идёт: вопрос сторожа — «держит ли окно живым КТО-ТО ДРУГОЙ», и
  запрет закрывать своё окно остановил бы КАЖДЫЙ исправный прогон на выходе;
* номер, ПЕРЕРАБОТАННЫЙ ОС (старт позже открытия окна), владельцем быть не может —
  иначе вчерашняя запись запирала бы возврат, и обход стал бы привычкой;
* «номер занят живым процессом, но владелец это или сосед — НЕ ИЗМЕРЕНО» — третий исход
  со своим кодом (2), а не подстановка одного из двух (инв. #17);
* обход ПЕЧАТАЕТСЯ: обход, о котором молчат, есть просто отсутствие сторожа;
* продвижение прибора ВИДНО: молчание было вторым условием аварии, и оно же сделало
  «работает» неотличимым от «умер».

Живость, номер звонящего, часы и прогон батареи — ВХОДЫ. Литеральных дат и литеральных
pid в файле нет (`.claude/rules/deployment.md` §§ «ВРЕМЯ В ТЕСТАХ», «ЛИЧНОСТЬ ПРОЦЕССА»):
номер живого берётся у `os.getpid()` (жив на любой машине по построению), номер мёртвого —
у НАСТОЯЩЕГО потомка, измеренного ТОЙ ЖЕ дверью, и не нашли мёртвого ⇒ падаем ГРОМКО.

Чего батарея НЕ мерит, и это сказано вслух: форму `grep " <pid>"` воспроизвести тестом
нельзя — она врёт или не врёт в зависимости от паддинга `ps` на конкретном хосте, то
есть ровно от того свойства, из-за которого она и запрещена. Вместо неё закреплены ОБА
направления настоящей двери: живой номер читается живым, мёртвый — мёртвым.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOL = os.path.join(_REPO_ROOT, "scripts", "delta_mutation_run.py")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dmr = _load(_TOOL, "_delta_mutation_run_owner_under_test")

_BODY = "VALUE = 1\n\n\ndef answer():\n    return VALUE\n"
_REL = "pkg/mod.py"


# ───────────────────────── подмостки ─────────────────────────


def _tree(tmp_path, *, name: str = "tree") -> str:
    root = tmp_path / name
    target = root / _REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_BODY, encoding="utf-8")
    return str(root)


def _spec_obj(*, mutations: int = 1):
    muts = tuple(dmr.Mutation(f"ответ подменён {i}", _REL, "VALUE = 1", f"VALUE = {i + 2}")
                 for i in range(mutations))
    return dmr.Spec("стенд владельца окна", ("t/test_x.py",), muts)


def _open(root: str, *, pid: int, opened_at: str | None = None, label: str = "СТЕНД"):
    """Открыть окно так, как это делает прибор, с ОБЪЯВЛЕННЫМ владельцем."""
    real = os.path.join(root, *_REL.split("/"))
    stamp = opened_at if opened_at is not None else _iso(minutes_ago=30)
    return dmr.open_window(root, _spec_obj(), {_REL: real},
                           {_REL: open(real, encoding="utf-8").read()},
                           spec_path="стенд.json", now=stamp, pid=pid, label=label)


def _write_record(root: str, doc: dict) -> None:
    with open(dmr.window_record_path(root), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)


def _mutate(root: str, text: str = "VALUE = 2\n") -> None:
    with open(os.path.join(root, *_REL.split("/")), "w", encoding="utf-8") as fh:
        fh.write(text)


def _body(root: str) -> str:
    return open(os.path.join(root, *_REL.split("/")), encoding="utf-8").read()


def _iso(*, minutes_ago: float = 0.0) -> str:
    """Отметка ОТНОСИТЕЛЬНАЯ: литеральная дата здесь — бомба замедленного действия."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _probe(*, exists, started_at=None, command=None, why=None, calls=None):
    """Инъекция ЦЕЛИКОМ той двери, за которой живут обе пробы к ОС."""
    def door(pid: int) -> dict:
        if calls is not None:
            calls.append(pid)
        return {"exists": exists, "started_at": started_at, "command": command,
                "why": why}
    return door


def _dead_pid() -> int:
    """Номер, МЁРТВЫЙ по измерению ТОЙ ЖЕ дверью, которой ответит проверяемый код.

    «Кажется, свободен» причиной не является, а литерал `999_999` безопасен только на
    macOS (поправка #453: на 64-битном Linux `pid_max` по умолчанию 4 194 304). Поэтому
    номер берётся у НАСТОЯЩЕГО потомка, который уже вышел и пожат, и сразу же
    перемеряется дверью. Не вышло ⇒ падаем ГРОМКО: тест, не обеспечивший свою
    предпосылку, обязан сказать это вслух, а не судить о живом номере как о мёртвом.
    """
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait(timeout=60)
    seen = dmr._process_probe(proc.pid)
    if seen.get("exists") is not False:
        pytest.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА: номер {proc.pid} сразу после выхода "
                    f"потомка не читается свободным ({seen}) — судить о мёртвом "
                    f"владельце нечем")
    return proc.pid


def _live_tree(tmp_path, *, sleep_s: float, mutations: int) -> str:
    """Дерево с НАСТОЯЩЕЙ батареей, которую можно застать в середине прогона."""
    root = tmp_path / "live"
    (root / "pkg").mkdir(parents=True)
    (root / "t").mkdir()
    (root / "pkg" / "mod.py").write_text(_BODY, encoding="utf-8")
    (root / "t" / "test_x.py").write_text(
        "import os, sys, time\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "from pkg.mod import answer\n\n\n"
        f"def test_answer():\n    time.sleep({sleep_s})\n    assert answer() == 1\n",
        encoding="utf-8")
    (root / "spec.json").write_text(json.dumps({
        "title": "стенд владельца окна (живой прогон)", "tests": ["t/test_x.py"],
        "mutations": [{"name": f"ответ подменён {i}", "file": _REL,
                       "old": "VALUE = 1", "new": f"VALUE = {i + 2}"}
                      for i in range(mutations)]}, ensure_ascii=False), encoding="utf-8")
    return str(root)


# ───── 1. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ НА НАСТОЯЩЕМ ПРИБОРЕ (без инъекций) ─────


class TestTheAccidentOfCycle906:

    def test_restore_refuses_while_the_real_instrument_holds_the_window(self, tmp_path):
        """Авария #906 целиком: прибор РАБОТАЕТ, кто-то зовёт возврат — и получает
        ОТКАЗ, а не мутанта в дереве. Затем прибор умирает, и тот же зов СРАБАТЫВАЕТ.

        Инъекций здесь нет ни одной: и живость, и смерть измеряются настоящей дверью к
        ОС, потому что предмет теста — именно она. Порви звено (не спрашивай владельца),
        и первый зов вернёт байты из-под работающего прибора — ровно то, что случилось.
        """
        root = _live_tree(tmp_path, sleep_s=4.0, mutations=2)
        proc = subprocess.Popen(
            [sys.executable, _TOOL, "--spec", os.path.join(root, "spec.json"),
             "--repo-root", root],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        record_path = dmr.window_record_path(root)
        deadline = time.time() + 120.0
        while time.time() < deadline:
            if os.path.exists(record_path):
                break
            if proc.poll() is not None:
                pytest.fail("прибор завершился ДО того, как открыл окно: стенд не "
                            f"обеспечил предпосылку (rc={proc.returncode})")
            time.sleep(0.05)
        else:
            proc.kill()
            pytest.fail("окно не открылось за 120 с — предпосылка НЕ ОБЕСПЕЧЕНА")

        try:
            record = json.loads(open(record_path, encoding="utf-8").read())
            assert record["pid"] == proc.pid != os.getpid()

            # (а) живость ИЗМЕРЕНА настоящей дверью и названа
            owner = dmr.owner_liveness(record)
            assert owner["verdict"] == dmr.OWNER_ALIVE, owner["detail"]
            assert "delta_mutation_run" in (owner["command"] or "")

            # (б) возврат ОТКАЗАН, и у отказа свой код
            out = dmr.restore_window(root)
            assert out["measured"] and out["refused"] and not out["closed"]
            assert out["restored"] == [] and out["already_clean"] == []
            assert "#906" in out["reason"] and "--allow-live-owner" in out["reason"]
            assert dmr.main(["--window-restore", "--repo-root", root]) == \
                dmr.RC_WINDOW_OWNER_ALIVE

            # (в) и вред НЕ НАНЕСЁН: запись окна на месте, слепок не снят
            assert os.path.exists(record_path)
            assert os.path.isdir(os.path.join(root, dmr.WINDOW_PRISTINE_REL))
        finally:
            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=60)

        # (г) обратная сторона: владелец мёртв ⇒ тот же зов ВОЗВРАЩАЕТ
        after = dmr.owner_liveness(json.loads(open(record_path, encoding="utf-8").read()))
        assert after["verdict"] == dmr.OWNER_DEAD, after["detail"]
        done = dmr.restore_window(root)
        assert done["measured"] and not done.get("refused") and done["closed"]
        assert _body(root) == _BODY
        assert dmr.window_state(root)["state"] == dmr.WINDOW_NONE

    def test_the_real_door_reads_a_live_number_as_live(self):
        """Второе направление настоящей двери. Номер живой ПО ПОСТРОЕНИЮ на любой
        машине; именно это утверждение и было неверным в аварии #906."""
        seen = dmr._process_probe(os.getpid())
        assert seen["exists"] is True and seen["why"] is None
        assert isinstance(seen["started_at"], datetime)
        assert (seen["command"] or "").strip(), "команда живого номера не прочитана"

    def test_the_real_door_reads_a_reaped_child_as_dead(self):
        """Первое направление. Номер измерен у ТОЙ ЖЕ двери (см. `_dead_pid`)."""
        seen = dmr._process_probe(_dead_pid())
        assert seen["exists"] is False and seen["why"] is None


# ───── 2. ВЕРДИКТ О ВЛАДЕЛЬЦЕ: ЧЕТЫРЕ ИСХОДА, И ТРЕТИЙ ПЕРВОКЛАССНЫЙ ─────


class TestOwnerVerdictOutcomes:

    def test_a_free_number_is_a_dead_owner(self, tmp_path):
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())
        owner = dmr.owner_liveness(rec, probe=_probe(exists=False))
        assert owner["verdict"] == dmr.OWNER_DEAD and "МЁРТВ" in owner["detail"]

    def test_our_own_window_is_not_a_foreign_live_owner(self, tmp_path):
        """СВОЁ окно. Порви звено — и `mutation_gate.close_gate_window` вместе с
        `run()` на выходе перестанут закрываться за собой: сторож запретит КАЖДОМУ
        исправному прогону снять собственную запись."""
        root = _tree(tmp_path)
        calls: list[int] = []
        rec = _open(root, pid=os.getpid())
        owner = dmr.owner_liveness(rec, probe=_probe(exists=True, calls=calls),
                                   caller_pid=os.getpid())
        assert owner["verdict"] == dmr.OWNER_SELF
        # дверь к ОС не трогали вовсе: спрашивающий и есть владелец
        assert calls == []
        out = dmr.restore_window(root, caller_pid=os.getpid())
        assert not out.get("refused") and out["closed"]

    def test_the_instrument_in_the_command_line_proves_a_live_owner(self, tmp_path):
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())
        owner = dmr.owner_liveness(rec, probe=_probe(
            exists=True, started_at=datetime.now().astimezone() - timedelta(hours=1),
            command=f"{sys.executable} scripts/delta_mutation_run.py --spec x.json"))
        assert owner["verdict"] == dmr.OWNER_ALIVE
        assert "ЖИВ" in owner["detail"]

    def test_a_number_recycled_after_the_window_opened_is_not_the_owner(self, tmp_path):
        """Урок #343 на этом предмете: номер сам по себе личностью НЕ является.

        Порви звено (считай занятый номер владельцем всегда) — и вчерашняя запись с
        переработанным номером запрёт возврат НАВСЕГДА; обход станет привычкой, то есть
        сторож научит себя обходить.
        """
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid(), opened_at=_iso(minutes_ago=600))
        owner = dmr.owner_liveness(rec, probe=_probe(
            exists=True, started_at=datetime.now().astimezone() - timedelta(minutes=5),
            command="/usr/libexec/siriactionsd"))
        assert owner["verdict"] == dmr.OWNER_DEAD
        assert "переработан" in owner["detail"]
        assert "siriactionsd" in owner["detail"]

    def test_a_live_stranger_older_than_the_window_is_the_third_outcome(self, tmp_path):
        """Ни «жив», ни «мёртв»: номер занят, прибор в команде не назван, и дата старта
        не опровергает владения. Подстановка любого из двух делает одну из двух аварий,
        поэтому исход СВОЙ (инв. #17)."""
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid(), opened_at=_iso(minutes_ago=5))
        owner = dmr.owner_liveness(rec, probe=_probe(
            exists=True, started_at=datetime.now().astimezone() - timedelta(hours=2),
            command="/usr/sbin/cupsd"))
        assert owner["verdict"] == dmr.OWNER_UNMEASURED
        assert "сказать НЕЧЕМ" in owner["detail"]

    def test_a_probe_that_cannot_tell_is_unmeasured_not_a_guess(self, tmp_path):
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())
        owner = dmr.owner_liveness(rec, probe=_probe(
            exists=None, why="os.kill(0) отказал: стенд"))
        assert owner["verdict"] == dmr.OWNER_UNMEASURED
        assert "стенд" in owner["detail"] and "НЕ ИЗМЕРЕНА" in owner["detail"]

    def test_a_probe_that_explodes_is_unmeasured_not_dead(self, tmp_path):
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())

        def boom(pid):
            raise RuntimeError("стенд: дверь сломалась")

        owner = dmr.owner_liveness(rec, probe=boom)
        assert owner["verdict"] == dmr.OWNER_UNMEASURED
        assert "дверь сломалась" in owner["detail"]

    def test_a_probe_returning_junk_is_unmeasured(self, tmp_path):
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())
        owner = dmr.owner_liveness(rec, probe=lambda pid: "жив")
        assert owner["verdict"] == dmr.OWNER_UNMEASURED

    @pytest.mark.parametrize("bad", [None, 0, -1, 1, True, "4242", 4242.0])
    def test_an_unusable_number_is_unmeasured_and_never_signalled(self, tmp_path, bad):
        """Номер ≤ 1 к ОС НЕ УХОДИТ: `os.kill(0, …)` означает ГРУППУ процессов, то есть
        сигнал всем, а `pid=True` молча прошёл бы как единица."""
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())
        doc = dict(rec)
        doc["pid"] = bad
        calls: list[int] = []
        owner = dmr.owner_liveness(doc, probe=_probe(exists=True, calls=calls))
        assert owner["verdict"] == dmr.OWNER_UNMEASURED
        assert calls == []
        assert "НЕ ИЗМЕРЕНА" in owner["detail"]

    def test_a_record_from_another_host_is_unmeasured(self, tmp_path):
        """Номер процесса имеет смысл только вместе с машиной. Запись, привезённую с
        другого хоста, судить здесь нечем — и это не «мёртв»."""
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())
        owner = dmr.owner_liveness(rec, probe=_probe(exists=False),
                                   hostname="ДРУГОЙ-ХОСТ")
        assert owner["verdict"] == dmr.OWNER_UNMEASURED
        assert "ЧУЖОЙ" in owner["detail"]

    def test_the_vocabulary_is_closed(self):
        assert set(dmr.OWNER_VERDICTS) == {
            dmr.OWNER_DEAD, dmr.OWNER_SELF, dmr.OWNER_ALIVE, dmr.OWNER_UNMEASURED}
        assert set(dmr.OWNER_MAY_RESTORE) == {dmr.OWNER_DEAD, dmr.OWNER_SELF}


# ───── 3. ОТКАЗ ДОХОДИТ ДО КОДА ВОЗВРАТА, И ОБХОД ПЕЧАТАЕТСЯ ─────


class TestRefusalReachesTheExitCode:

    def _refusing(self, tmp_path, **probe_kw):
        root = _tree(tmp_path)
        _open(root, pid=_dead_pid())
        _mutate(root)
        return root, _probe(**probe_kw)

    def test_a_live_owner_gets_its_own_exit_code_and_leaves_the_mutant(self, tmp_path):
        """Код у отказа СВОЙ: слить его с 1 значило бы сказать «в дереве мутант» о
        дереве, в котором идёт исправный прогон; слить с 2 — назвать «не измерено»
        ровно то, что измерено лучше всего."""
        root, door = self._refusing(
            tmp_path, exists=True,
            started_at=datetime.now().astimezone() - timedelta(hours=1),
            command="python3 scripts/delta_mutation_run.py --spec s.json")
        out = dmr.restore_window(root, owner_probe=door)
        assert out["refused"] and out["owner"]["verdict"] == dmr.OWNER_ALIVE
        assert _body(root) == "VALUE = 2\n"          # мутант НЕ тронут
        assert os.path.exists(dmr.window_record_path(root))
        assert dmr.RC_WINDOW_OWNER_ALIVE == 4 != dmr.RC_WINDOW_FINDING

    def test_unmeasured_liveness_keeps_the_unmeasured_code(self, tmp_path):
        root, door = self._refusing(tmp_path, exists=None, why="стенд молчит")
        out = dmr.restore_window(root, owner_probe=door)
        assert out["refused"] and out["owner"]["verdict"] == dmr.OWNER_UNMEASURED
        assert _body(root) == "VALUE = 2\n"

    def test_the_cli_maps_an_unmeasured_owner_to_the_unmeasured_code(
            self, tmp_path, capsys):
        """Второй код отказа — через дверь ХОСТА, а не ОС: запись, привезённую с другой
        машины, судить здесь нечем, и это ровно «НЕ ИЗМЕРЕНО», а не «мёртв».

        Порви звено (отвечай «мёртв» на чужую запись) — и возврат пойдёт по номеру,
        который на этой машине принадлежит кому угодно.
        """
        root = _tree(tmp_path)
        rec = _open(root, pid=_dead_pid())
        _write_record(root, dict(rec, hostname="ДРУГОЙ-ХОСТ"))
        _mutate(root)
        rc = dmr.main(["--window-restore", "--repo-root", root])
        err = capsys.readouterr().err
        assert rc == dmr.RC_UNMEASURED, err
        assert "ОТКАЗ" in err and "ЧУЖОЙ" in err
        assert _body(root) == "VALUE = 2\n"
        assert os.path.exists(dmr.window_record_path(root))

    def test_the_override_restores_and_says_so_out_loud(self, tmp_path, capsys):
        """Обход, о котором молчат, есть просто отсутствие сторожа."""
        root = _live_tree(tmp_path, sleep_s=0.0, mutations=1)
        _open(root, pid=os.getpid())      # владелец ЖИВ по построению
        _mutate(root)
        rc = dmr.main(["--window-restore", "--repo-root", root,
                       "--allow-live-owner"])
        err = capsys.readouterr().err
        assert "ОБХОД ОБЪЯВЛЕН" in err and "--allow-live-owner" in err
        assert rc == dmr.RC_WINDOW_CLEAN
        assert _body(root) == _BODY

    def test_the_override_outside_restore_is_refused_not_swallowed(self, capsys):
        rc = dmr.main(["--window-check", "--allow-live-owner"])
        assert rc == dmr.RC_UNMEASURED
        assert "ТОЛЬКО" in capsys.readouterr().err

    def test_window_check_is_not_touched_by_the_owner_question(self, tmp_path):
        """Граница названа: пушеры зовут ЧИТАТЕЛЯ окна, и его вердикт не зависит от
        живости владельца — файл под открытым окном не доставляется в любом случае."""
        root = _tree(tmp_path)
        _open(root, pid=os.getpid())
        _mutate(root)
        state = dmr.window_state(root)
        assert state["state"] == dmr.WINDOW_HOLDS_MUTANT
        assert state["rc"] == dmr.RC_WINDOW_FINDING


# ───── 4. ПРОДВИЖЕНИЕ ВИДНО: МОЛЧАНИЕ БЫЛО ВТОРЫМ УСЛОВИЕМ АВАРИИ ─────


class TestProgressIsVisible:

    def test_every_mutation_says_its_outcome_on_stderr(self, tmp_path, capsys):
        """Строк об исходе ровно столько, сколько мутаций: порви звено на ОДНОЙ ветке
        (забудь сказать о `НЕ ПРИМЕНЕНА`), и прибор замолчит именно там, где молчание
        дороже всего."""
        root = _tree(tmp_path)
        spec = dmr.Spec("стенд прогресса", ("t/test_x.py",), (
            dmr.Mutation("видимая", _REL, "VALUE = 1", "VALUE = 2"),
            dmr.Mutation("якоря нет", _REL, "ТАКОГО-ЯКОРЯ-НЕТ", "x"),
        ))
        calls = [(0, "1 passed"), (1, "FAILED t/test_x.py::test_answer")]
        report = dmr.run(spec, repo_root=root, runner=lambda tests: calls.pop(0))
        err = capsys.readouterr().err
        assert len(report.results) == 2
        for name in ("видимая", "якоря нет"):
            assert f"«{name}»" in err
        assert err.count("[прибор] 1/2") == 1 and err.count("[прибор] 2/2") == 1
        assert "окно открыто" in err and "окно снято" in err
        assert "контроль шума" in err

    def test_progress_never_lands_on_stdout(self, tmp_path, capsys):
        """`--json` читают машины: строка прогресса в stdout сломала бы разбор у
        КАЖДОГО читателя (проба приёмки берёт вердикт именно оттуда)."""
        root = _live_tree(tmp_path, sleep_s=0.0, mutations=1)
        rc = dmr.main(["--spec", os.path.join(root, "spec.json"),
                       "--repo-root", root, "--json"])
        got = capsys.readouterr()
        assert rc == dmr.RC_MEASURED_CLEAN, got.err
        assert json.loads(got.out)["population"] == 1
        assert "[прибор]" in got.err and "[прибор]" not in got.out


# ───── 5. РАЗБОР СТРОКИ `ps` — ПО ТОКЕНАМ, А НЕ ПО СРЕЗУ ─────


class TestPsLineParsing:

    def test_the_padded_day_of_month_still_parses(self):
        """`lstart` выравнивает день месяца паддингом (`Oct  5`). Разбор по срезу строки
        поехал бы на нём, и дата старта стала бы «не измерена» ровно в первые девять
        дней каждого месяца."""
        when = datetime.now().astimezone().replace(microsecond=0)
        line = (when.strftime("%a %b ") + f"{when.day:2d}"
                + when.strftime(" %H:%M:%S %Y") + "  python3 scripts/x.py --flag")
        started, command = dmr._parse_ps_line(line)
        assert started is not None
        assert started.replace(tzinfo=None) == when.replace(tzinfo=None)
        assert command == "python3 scripts/x.py --flag"

    def test_an_unparsable_stamp_is_none_not_today(self):
        started, command = dmr._parse_ps_line("не дата а просто строка /bin/sleep 9")
        assert started is None and command == "/bin/sleep 9"

    def test_a_short_line_is_not_mistaken_for_a_date(self):
        started, command = dmr._parse_ps_line("  12345  ")
        assert started is None and command == "12345"

    def test_the_window_stamp_is_parsed_or_declared_unreadable(self):
        """Отметка записи окна. Литеральных дат нет: все три читаемые формы строятся из
        НАСТОЯЩИХ часов, а нечитаемые — это не дата вовсе."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with_offset = now.isoformat()
        with_zulu = now.isoformat().replace("+00:00", "Z")
        naive = now.replace(tzinfo=None).isoformat()
        for text in (with_offset, with_zulu, naive):
            got = dmr._parse_stamp(text)
            assert got is not None, text
            assert got.utcoffset() == timedelta(0), text
            assert got == now, text
        for text in ("СТЕНД-ОТМЕТКА", "", None, 42, {}):
            assert dmr._parse_stamp(text) is None, text
