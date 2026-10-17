"""ОКНО мутационного прибора: что видит тот, кто пришёл после (ADR-772, цикл #888).

Предмет — `scripts/delta_mutation_run.py` в части ЗАПИСИ ОКНА и два её читателя:
сам прибор (отказ открыть второе окно, возврат по записи) и пушер
(`push_to_github.py` / `push_to_github_batch.py` — отказ доставить файл из дерева под
открытым окном).

**Почему батарея отдельная от `test_delta_mutation_run.py`.** Та отвечает на вопрос
«верно ли прибор мерит мутантов». Эта — на другой: «что остаётся в дереве и кто об этом
скажет, если прибор НЕ ДОЖИЛ до возврата». Замер цикла #888: `finally` обеспечивает
возврат для исключения и не обеспечивает его для `SIGKILL`; дерево `/private/tmp/spa_c886`
сутки держало мутацию №7 своей же спецификации, и назвать её было нечем — слепок исходных
байтов жил в локальной переменной мёртвого процесса.

Устройство — по звеньям, у каждого обратная сторона с НАЗВАННЫМ звеном:

* запись переживает СМЕРТЬ процесса (положительный контроль — настоящий `SIGKILL`
  настоящего прибора), а чистый прогон записи НЕ оставляет;
* читатель различает ЧЕТЫРЕ исхода, и «запись есть, а слепка нет» — третий исход, а не
  «чисто» (инв. #17);
* набор доставки СУЖАЕТ находку: мутант в чужом файле не запрещает доставку соседнего,
  иначе сторож научит себя обходить;
* второе окно в том же дереве ОТКАЗЫВАЕТ, и слепок первого остаётся нетронутым;
* возврат ПРОВЕРЯЕТСЯ: испорченный слепок записи не снимает;
* дверей доставки ДВЕ, и обе зовут одну реализацию (урок номеров ADR, 26.08).

Часы, номер процесса, обработчик сигналов и прогон батареи — ВХОДЫ. Литеральных дат и
литеральных pid в файле нет (`.claude/rules/deployment.md` §§ «ВРЕМЯ В ТЕСТАХ»,
«ЛИЧНОСТЬ ПРОЦЕССА»): номер процесса берётся у НАСТОЯЩЕГО потомка, одноразовый
репозиторий создаётся `git init -b main` (§ «GIT-ОКРУЖЕНИЕ»).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOL = os.path.join(_REPO_ROOT, "scripts", "delta_mutation_run.py")
_PUSHER = os.path.join(_REPO_ROOT, "push_to_github.py")
_BATCH = os.path.join(_REPO_ROOT, "push_to_github_batch.py")


def _load(path, name):
    """Ввезти модуль из файла. Регистрация в `sys.modules` ДО исполнения — требование
    `dataclasses` (строковые аннотации разрешаются через `sys.modules[__module__]`)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dmr = _load(_TOOL, "_delta_mutation_run_window_under_test")


# ───────────────────────── подмостки ─────────────────────────

_BODY = "VALUE = 1\n\n\ndef answer():\n    return VALUE\n"
_REL = "pkg/mod.py"


def _tree(tmp_path, *, body: str = _BODY, rel: str = _REL) -> str:
    root = tmp_path / "tree"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return str(root)


def _spec_obj(*, rel: str = _REL, old: str = "VALUE = 1", new: str = "VALUE = 2",
              name: str = "ответ подменён", tests=("t/test_x.py",)):
    return dmr.Spec("стенд окна", tuple(tests), (dmr.Mutation(name, rel, old, new),))


def _open(root, *, rel: str = _REL, now: str = "СТЕНД-ОТМЕТКА", pid: int | None = None,
          label: str = "СТЕНД-РАБОТНИК"):
    """Открыть окно так, как это делает прибор: слепок = то, что лежит СЕЙЧАС."""
    real = os.path.join(root, *rel.split("/"))
    return dmr.open_window(root, _spec_obj(rel=rel), {rel: real},
                           {rel: open(real, encoding="utf-8").read()},
                           spec_path="стенд.json", now=now,
                           pid=pid if pid is not None else os.getpid(), label=label)


def _mutate(root, *, rel: str = _REL, text: str = "VALUE = 2\n"):
    (open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8")).write(text)


def _record(root) -> dict:
    return json.loads(open(dmr.window_record_path(root), encoding="utf-8").read())


def _write_record(root, doc) -> None:
    path = dmr.window_record_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False))


def _digest(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _real_tree(tmp_path, *, sleep_s: float) -> str:
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
        "title": "стенд окна (живой прогон)", "tests": ["t/test_x.py"],
        "mutations": [{"name": "ответ подменён", "file": "pkg/mod.py",
                       "old": "VALUE = 1", "new": "VALUE = 2"}]}, ensure_ascii=False),
        encoding="utf-8")
    return str(root)


def _git_repo(tmp_path, name="repo") -> str:
    """Одноразовый репозиторий. Имя ветки ОБЪЯВЛЕНО (`-b`): умолчание хоста разное,
    и тест, зависящий от него, зелен здесь и красен на `ubuntu-latest`."""
    root = tmp_path / name
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text(_BODY, encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(root)],
                   capture_output=True, text=True, check=True)
    return str(root)


# ───── 1. ЗАПИСЬ ПЕРЕЖИВАЕТ СМЕРТЬ ПРОЦЕССА (а чистый прогон её не оставляет) ─────


class TestWindowRecordOutlivesTheProcess:

    def test_the_record_names_who_what_and_the_pristine_digest(self, tmp_path):
        root = _tree(tmp_path)
        rec = _open(root, now="ОТМЕТКА-ВХОД", pid=os.getpid(), label="МЕТКА-ВХОД")
        assert rec["opened_at"] == "ОТМЕТКА-ВХОД"      # часы — ВХОД
        assert rec["run_label"] == "МЕТКА-ВХОД"        # личность — ВХОД
        assert rec["pid"] == os.getpid()               # номер живой по построению
        assert [f["file"] for f in rec["files"]] == [_REL]
        on_disk = _record(root)
        assert on_disk["files"][0]["sha256"] == _digest(
            os.path.join(root, *_REL.split("/")))
        assert on_disk["mutations"] == [{"name": "ответ подменён", "file": _REL}]

    def test_the_pristine_bytes_themselves_are_on_disk_not_only_their_hash(self, tmp_path):
        """Хеш говорит «байты не те», вернуть по нему нельзя — порви звено, и наследник
        окна останется с названным мутантом и без пути наверх."""
        root = _tree(tmp_path)
        rec = _open(root)
        copy = os.path.join(root, *rec["files"][0]["pristine_copy"].split("/"))
        assert os.path.isfile(copy)
        assert open(copy, encoding="utf-8").read() == _BODY

    def test_a_real_sigkill_inside_the_window_leaves_a_named_mutant(self, tmp_path):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария цикла #886 воспроизведена настоящим прибором.

        `SIGKILL` не исполняет ни `finally`, ни `atexit`, ни обработчик сигнала — это
        свойство ОС, а не прибора. Поэтому единственное, что может назвать оставшегося
        мутанта, — запись на диске; её тут и спрашивают. Номер процесса берётся у
        НАСТОЯЩЕГО потомка (литерального pid в файле нет).
        """
        root = _real_tree(tmp_path, sleep_s=20.0)
        proc = subprocess.Popen(
            [sys.executable, _TOOL, "--spec", os.path.join(root, "spec.json"),
             "--repo-root", root],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        target = os.path.join(root, "pkg", "mod.py")
        deadline = time.time() + 60.0
        while time.time() < deadline:
            if open(target, encoding="utf-8").read().startswith("VALUE = 2"):
                break
            if proc.poll() is not None:
                pytest.fail("прибор завершился ДО того, как мутант лёг в дерево: "
                            "стенд не обеспечил предпосылку, и судить о смерти внутри "
                            f"окна нечем (rc={proc.returncode})")
            time.sleep(0.2)
        else:
            proc.kill()
            pytest.fail("мутант не появился в дереве за 60 с — предпосылка НЕ ОБЕСПЕЧЕНА")

        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
        assert proc.returncode != 0

        # (а) вред ЕСТЬ: дерево держит мутанта
        assert open(target, encoding="utf-8").read().startswith("VALUE = 2")
        # (б) и он НАЗВАН: запись окна переживает SIGKILL
        state = dmr.window_state(root)
        assert state["state"] == dmr.WINDOW_HOLDS_MUTANT, state["detail"]
        assert state["rc"] == dmr.RC_WINDOW_FINDING
        assert state["mutants"][0]["file"] == "pkg/mod.py"
        assert state["mutants"][0]["mutations"] == ["ответ подменён"]
        assert str(proc.pid) in json.dumps(state["record"])
        # (в) и у него есть путь наверх
        out = dmr.restore_window(root)
        assert out["measured"] and out["restored"] == ["pkg/mod.py"] and out["closed"]
        assert open(target, encoding="utf-8").read() == _BODY
        assert dmr.window_state(root)["state"] == dmr.WINDOW_NONE

    def test_a_clean_run_leaves_no_record_and_a_byte_identical_tree(self, tmp_path):
        """Обратная сторона: «записи нет» обязано означать «чисто», а не «не измерено».
        Порви звено (не снимай запись), и сторож закричит на каждом исправном дереве —
        ровно тот ложный красный, который учит гасить сторожа."""
        root = _tree(tmp_path)
        before = _digest(os.path.join(root, *_REL.split("/")))
        calls = [(0, "1 passed"), (1, "FAILED t/test_x.py::test_answer")]
        report = dmr.run(_spec_obj(), repo_root=root,
                         runner=lambda tests: calls.pop(0))
        assert report.exit_code() == dmr.RC_MEASURED_CLEAN, report.to_dict()
        assert not os.path.exists(dmr.window_record_path(root))
        assert not os.path.isdir(os.path.join(root, dmr.WINDOW_DIR))
        assert _digest(os.path.join(root, *_REL.split("/"))) == before
        assert dmr.window_state(root)["state"] == dmr.WINDOW_NONE

    def test_a_run_that_leaves_a_mutant_keeps_the_record_for_the_next_reader(self, tmp_path):
        """Прогон, испортивший дерево, падает ГРОМКО — и запись остаётся, иначе мутанта
        стало бы нечем вернуть ровно в том случае, для которого запись и нужна."""
        root = _tree(tmp_path)
        rel_real = os.path.join(root, *_REL.split("/"))
        second = os.path.join(root, "pkg", "сосед.py")
        with open(second, "w", encoding="utf-8") as fh:
            fh.write("B = 1\n")
        calls = {"n": 0}

        def _foreign_edit(_tests):
            # Сцена та же, что у соседней батареи: файл ПЕРВОЙ мутации уже возвращён,
            # и пока идёт прогон ВТОРОЙ, его правит кто-то ещё.
            calls["n"] += 1
            if calls["n"] == 3:
                with open(rel_real, "w", encoding="utf-8") as fh:
                    fh.write("VALUE = 99\n")
            return 0, "1 passed"

        spec = dmr.Spec("стенд окна", ("t/test_x.py",),
                        (dmr.Mutation("первая", _REL, "VALUE = 1", "VALUE = 2"),
                         dmr.Mutation("вторая", "pkg/сосед.py", "B = 1", "B = 2")))
        with pytest.raises(dmr.TreeNotRestored) as err:
            dmr.run(spec, repo_root=root, runner=_foreign_edit)
        assert dmr.WINDOW_RECORD_REL in str(err.value)
        assert os.path.exists(dmr.window_record_path(root))
        assert dmr.window_state(root)["state"] == dmr.WINDOW_HOLDS_MUTANT


# ───── 2. ЧИТАТЕЛЬ РАЗЛИЧАЕТ ЧЕТЫРЕ ИСХОДА, И ТРЕТИЙ — ПЕРВОКЛАССНЫЙ ─────


class TestReaderTellsFourOutcomesApart:

    def test_no_record_is_measured_clean(self, tmp_path):
        state = dmr.window_state(_tree(tmp_path))
        assert state["state"] == dmr.WINDOW_NONE
        assert state["rc"] == dmr.RC_WINDOW_CLEAN
        assert state["mutants"] == [] and state["window_files"] == []

    def test_drifted_bytes_under_a_record_are_a_mutant(self, tmp_path):
        root = _tree(tmp_path)
        _open(root)
        _mutate(root)
        state = dmr.window_state(root)
        assert state["state"] == dmr.WINDOW_HOLDS_MUTANT
        assert state["rc"] == dmr.RC_WINDOW_FINDING
        assert "ответ подменён" in state["detail"]

    def test_an_open_window_with_pristine_bytes_is_not_a_finding_by_itself(self, tmp_path):
        """Обратная сторона предыдущего: идущий прогон — не вред. Порви звено, и каждый
        честный замер станет находкой, то есть прибор начнёт запрещать себя."""
        root = _tree(tmp_path)
        _open(root)
        state = dmr.window_state(root)
        assert state["state"] == dmr.WINDOW_OPEN_PRISTINE
        assert state["rc"] == dmr.RC_WINDOW_CLEAN
        assert state["window_files"] == [_REL]

    @pytest.mark.parametrize("doc,expect", [
        ("{не json", "не читается"),
        (["список"], "не объект"),
        ({"files": []}, "непустого раздела `files`"),
        ({"files": [{"sha256": "x"}]}, "без имени файла"),
    ])
    def test_a_record_that_cannot_be_read_is_the_third_outcome_not_clean(
            self, tmp_path, doc, expect):
        """Самое важное звено: неполная запись НЕ зачитывается как «чисто». Порви его —
        и вернётся fail-OPEN, против которого написан инв. #17."""
        root = _tree(tmp_path)
        _write_record(root, doc)
        state = dmr.window_state(root)
        assert state["state"] == dmr.WINDOW_UNMEASURED
        assert state["rc"] == dmr.RC_UNMEASURED
        assert expect in state["detail"]

    def test_a_record_without_a_digest_is_unmeasured_not_pristine(self, tmp_path):
        root = _tree(tmp_path)
        rec = _record(root) if os.path.exists(dmr.window_record_path(root)) else None
        assert rec is None
        _open(root)
        doc = _record(root)
        doc["files"][0].pop("sha256")
        _write_record(root, doc)
        state = dmr.window_state(root)
        assert state["state"] == dmr.WINDOW_UNMEASURED
        assert "в записи нет слепка" in state["detail"]

    def test_a_file_named_by_the_record_but_missing_is_unmeasured(self, tmp_path):
        root = _tree(tmp_path)
        _open(root)
        os.unlink(os.path.join(root, *_REL.split("/")))
        state = dmr.window_state(root)
        assert state["state"] == dmr.WINDOW_UNMEASURED
        assert "не прочитан" in state["detail"]

    def test_the_list_of_states_is_closed(self):
        """Перечень исходов закрыт: исход вне перечня означал бы ветку, о которой ни
        один читатель ничего не знает."""
        assert set(dmr.WINDOW_STATES) == {
            dmr.WINDOW_NONE, dmr.WINDOW_HOLDS_MUTANT, dmr.WINDOW_OPEN_PRISTINE,
            dmr.WINDOW_UNMEASURED}
        assert len(set(dmr.WINDOW_STATES)) == 4


# ───── 3. НАБОР ДОСТАВКИ СУЖАЕТ НАХОДКУ ─────


class TestTheDeliverySetNarrowsTheFinding:

    def test_a_mutant_in_the_delivered_file_is_a_finding(self, tmp_path):
        root = _tree(tmp_path)
        _open(root)
        _mutate(root)
        state = dmr.window_state(root, files=[os.path.join(root, *_REL.split("/"))])
        assert state["rc"] == dmr.RC_WINDOW_FINDING
        assert state["touching"] == [_REL]

    def test_a_mutant_outside_the_delivered_set_does_not_block_the_neighbour(self, tmp_path):
        """Обратная сторона: порви звено, и сторож запретит доставку файла, которого
        прибор не трогал, — это ровно та придирчивость, которая учит его обходить.
        Вердикт при этом НЕ лжёт: мутант по-прежнему НАЗВАН в тексте."""
        root = _tree(tmp_path)
        (os.path.join(root, "other.py"))
        with open(os.path.join(root, "other.py"), "w", encoding="utf-8") as fh:
            fh.write("# сосед\n")
        _open(root)
        _mutate(root)
        state = dmr.window_state(root, files=[os.path.join(root, "other.py")])
        assert state["state"] == dmr.WINDOW_HOLDS_MUTANT
        assert state["rc"] == dmr.RC_WINDOW_CLEAN
        assert "ДЕРЖИТ МУТАНТА" in state["detail"]
        assert "набор доставки этих файлов не содержит" in state["detail"]

    def test_delivering_a_file_under_an_open_window_is_a_race_and_refused(self, tmp_path):
        """Байты целы ПРЯМО СЕЙЧАС — но прогон перепишет их в любую секунду. Порви
        звено, и вернётся дефект цикла #885: копия снята ВНУТРИ окна."""
        root = _tree(tmp_path)
        _open(root)
        state = dmr.window_state(root, files=[_REL])
        assert state["state"] == dmr.WINDOW_OPEN_PRISTINE
        assert state["rc"] == dmr.RC_WINDOW_FINDING
        assert "ГОНКА" in state["detail"]

    def test_a_path_outside_the_tree_is_simply_not_about_this_tree(self, tmp_path):
        root = _tree(tmp_path)
        _open(root)
        _mutate(root)
        state = dmr.window_state(root, files=["/заведомо/чужой/путь.py"])
        assert state["rc"] == dmr.RC_WINDOW_CLEAN
        assert state["touching"] == []

    def test_relative_and_absolute_paths_name_the_same_file(self, tmp_path):
        root = _tree(tmp_path)
        _open(root)
        _mutate(root)
        a = dmr.window_state(root, files=[_REL])
        b = dmr.window_state(root, files=[os.path.join(root, *_REL.split("/"))])
        assert a["rc"] == b["rc"] == dmr.RC_WINDOW_FINDING
        assert a["touching"] == b["touching"] == [_REL]


# ───── 4. ВТОРОЕ ОКНО В ТОМ ЖЕ ДЕРЕВЕ ОТКАЗЫВАЕТ ─────


class TestASecondWindowInTheSameTreeRefuses:

    def test_the_second_run_refuses_and_the_first_pristine_copy_survives(self, tmp_path):
        """Затереть слепок первого окна значило бы сделать его мутанта ВЕЧНЫМ: вернуть
        байты стало бы нечем. Порви звено — и дефект цикла #885 вернётся."""
        root = _tree(tmp_path)
        rec = _open(root)
        copy = os.path.join(root, *rec["files"][0]["pristine_copy"].split("/"))
        _mutate(root)
        before = _digest(copy)
        with pytest.raises(dmr.OpenWindow) as err:
            dmr.run(_spec_obj(), repo_root=root, runner=lambda tests: (1, ""))
        assert "УЖЕ открыто окно" in str(err.value)
        assert "--window-restore" in str(err.value)
        assert _digest(copy) == before
        assert open(copy, encoding="utf-8").read() == _BODY

    def test_a_record_that_cannot_be_read_also_refuses_fail_closed(self, tmp_path):
        root = _tree(tmp_path)
        _write_record(root, "{битая запись")
        with pytest.raises(dmr.OpenWindow) as err:
            dmr.run(_spec_obj(), repo_root=root, runner=lambda tests: (1, ""))
        assert "не читается" in str(err.value)

    def test_the_cli_turns_the_refusal_into_the_unmeasured_code(self, tmp_path, capsys):
        """Батарея здесь НАСТОЯЩАЯ: с выдуманной отказ пришёл бы от pytest (код 4), и
        тест зеленел бы, ничего не сказав про окно."""
        root = _real_tree(tmp_path, sleep_s=0)
        _open(root)
        rc = dmr.main(["--spec", os.path.join(root, "spec.json"), "--repo-root", root])
        assert rc == dmr.RC_UNMEASURED
        assert "окно прибора" in capsys.readouterr().err


# ───── 5. ВОЗВРАТ ПРОВЕРЯЕТСЯ, А НЕ ОБЕЩАЕТСЯ ─────


class TestRestoreIsVerifiedNotAssumed:

    def test_a_corrupted_pristine_copy_does_not_close_the_window(self, tmp_path):
        """Записать испорченный слепок значило бы доставить ТРЕТЬИ байты — не код и не
        мутанта. Порви звено, и дерево станет «чистым» по мерке самого сторожа."""
        root = _tree(tmp_path)
        rec = _open(root)
        copy = os.path.join(root, *rec["files"][0]["pristine_copy"].split("/"))
        with open(copy, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 777\n")
        _mutate(root)
        out = dmr.restore_window(root)
        assert out["measured"] and out["failed"] and not out["closed"]
        assert "сам испорчен" in out["failed"][0]
        assert os.path.exists(dmr.window_record_path(root))
        assert dmr.window_state(root)["state"] == dmr.WINDOW_HOLDS_MUTANT

    def test_a_missing_pristine_copy_is_named_not_silently_skipped(self, tmp_path):
        root = _tree(tmp_path)
        rec = _open(root)
        os.unlink(os.path.join(root, *rec["files"][0]["pristine_copy"].split("/")))
        _mutate(root)
        out = dmr.restore_window(root)
        assert out["failed"] and not out["closed"]
        assert "не прочитан" in out["failed"][0]

    def test_already_clean_bytes_close_the_window_without_writing(self, tmp_path):
        """Сессия, умершая МЕЖДУ возвратом и уборкой, оставляет запись при целых
        байтах. Возврат обязан снять её, а не переписать файл заново."""
        root = _tree(tmp_path)
        _open(root)
        out = dmr.restore_window(root)
        assert out["already_clean"] == [_REL] and out["restored"] == []
        assert out["closed"] and not os.path.exists(dmr.window_record_path(root))

    def test_restore_without_a_record_says_there_is_nothing_to_return(self, tmp_path):
        out = dmr.restore_window(_tree(tmp_path))
        assert out["measured"] and out["restored"] == [] and not out["closed"]
        assert "возвращать нечего" in out["reason"]

    def test_restore_on_an_unreadable_record_is_unmeasured_not_success(self, tmp_path):
        root = _tree(tmp_path)
        _write_record(root, "{битая")
        out = dmr.restore_window(root)
        assert out["measured"] is False and not out["closed"]
        assert "не читается" in out["reason"]

    def test_death_between_the_two_removals_leaves_a_clean_verdict(
            self, tmp_path, monkeypatch):
        """Порядок снятия меряется ИСХОДОМ: сессия умирает МЕЖДУ двумя действиями.

        Первая редакция этого теста следила за вызовами `os.unlink` и была УКРАШЕНИЕМ:
        мутация «снимать каталог целиком вместо записи» прошла ЗЕЛЁНОЙ, потому что
        `shutil.rmtree` зовёт тот же `os.unlink` внутри (замер цикла #888 — выживший
        мутант №10). Поэтому спрашивается не «кого позвали», а что увидит ЧИТАТЕЛЬ.

        Порви звено (снимай слепки раньше записи) — и смерть между двумя действиями
        оставит запись, указывающую на исчезнувший слепок, то есть громкое «НЕ
        ИЗМЕРЕНО» на дереве, с которым всё в порядке.
        """
        root = _tree(tmp_path)
        _open(root)

        def _dies(*_a, **_kw):
            raise OSError("смерть между снятием записи и снятием слепков")

        monkeypatch.setattr(dmr.shutil, "rmtree", _dies)
        with pytest.raises(OSError):
            dmr.close_window(root)
        assert not os.path.exists(dmr.window_record_path(root)), (
            "запись обязана быть снята ПЕРВОЙ: байты к этому моменту уже сверены")
        assert os.path.isdir(os.path.join(root, *dmr.WINDOW_PRISTINE_REL.split("/"))), (
            "слепки ещё на месте — сцена не обеспечила предпосылку")
        assert dmr.window_state(root)["state"] == dmr.WINDOW_NONE

    def test_a_whole_close_removes_both_the_record_and_the_copies(self, tmp_path):
        """Обратная сторона: дожившее до конца снятие не оставляет мусора."""
        root = _tree(tmp_path)
        _open(root)
        assert dmr.close_window(root) is True
        assert not os.path.isdir(os.path.join(root, dmr.WINDOW_DIR))
        assert dmr.close_window(root) is False


# ───── 6. ДВЕРЕЙ ДОСТАВКИ ДВЕ, И ОБЕ ЗОВУТ ОДНУ РЕАЛИЗАЦИЮ ─────


class TestTheDeliveryDoorRefusesAMutant:

    def test_the_pusher_refuses_a_file_under_an_open_window(self, tmp_path):
        pusher = _load(_PUSHER, "_pusher_window_under_test")
        root = _git_repo(tmp_path)
        real = os.path.join(root, "pkg", "mod.py")
        dmr.open_window(root, _spec_obj(), {"pkg/mod.py": real},
                        {"pkg/mod.py": open(real, encoding="utf-8").read()},
                        now="ОТМЕТКА", pid=os.getpid(), label="МЕТКА")
        with open(real, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 2\n")
        with pytest.raises(pusher.DeliveredMutant) as err:
            pusher.enforce_no_delivered_mutant([real])
        assert "окно мутационного прибора" in str(err.value)
        assert pusher.MUTATION_WINDOW_EXIT == 10

    def test_the_pusher_lets_a_clean_tree_through(self, tmp_path):
        """Обратная сторона: порви звено, и ни одна доставка не уедет вовсе."""
        pusher = _load(_PUSHER, "_pusher_window_clean")
        root = _git_repo(tmp_path, name="clean")
        verdict = pusher.enforce_no_delivered_mutant(
            [os.path.join(root, "pkg", "mod.py")])
        assert verdict["findings"] == [] and verdict["unmeasured"] == []

    def test_a_conscious_bypass_is_printed_not_silent(self, tmp_path, capsys):
        pusher = _load(_PUSHER, "_pusher_window_bypass")
        root = _git_repo(tmp_path, name="bypass")
        real = os.path.join(root, "pkg", "mod.py")
        dmr.open_window(root, _spec_obj(), {"pkg/mod.py": real},
                        {"pkg/mod.py": open(real, encoding="utf-8").read()},
                        now="ОТМЕТКА", pid=os.getpid(), label="МЕТКА")
        with open(real, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 2\n")
        pusher.enforce_no_delivered_mutant([real], allow=True)
        assert "разрешена явно" in capsys.readouterr().err

    def test_a_missing_reader_everywhere_is_unmeasured_and_refuses(
            self, tmp_path, monkeypatch):
        """Сторожа нет НИ В ОДНОМ из трёх мест ⇒ «держит ли дерево мутанта» НЕ ИЗМЕРЕНО,
        и это отказ, а не тихий пропуск (fail-CLOSED). Порви звено — и пушер начнёт
        доставлять из дерева, о котором ничего не знает."""
        pusher = _load(_PUSHER, "_pusher_window_noguard")
        root = _git_repo(tmp_path, name="noguard")
        fake_runner = tmp_path / "дерево-без-сторожа" / "push_to_github.py"
        fake_runner.parent.mkdir(parents=True)
        fake_runner.write_text("# не настоящий пушер\n", encoding="utf-8")
        monkeypatch.setattr(pusher, "MODULE_FILE", str(fake_runner))
        with pytest.raises(pusher.DeliveredMutant) as err:
            pusher.enforce_no_delivered_mutant(
                [os.path.join(root, "pkg", "mod.py")], runner_file=str(fake_runner))
        assert "НЕ ИЗМЕРЕНО" in str(err.value)
        assert "ни в одном из деревьев" in str(err.value)

    def test_a_runner_tree_without_the_reader_still_gets_measured(self, tmp_path):
        """Обратная сторона: порядок поиска существует затем, чтобы вопрос БЫЛ ЗАДАН.

        Стенды соседних сюит зовут пушер с подменённым `__file__` из синтетического
        дерева, где лежат только копии инструмента доставки. Если бы читатель искался
        ТОЛЬКО там, гейт вечно отвечал бы «НЕ ИЗМЕРЕНО» и запрещал бы каждую такую
        доставку — ложный отказ, который учит снимать гейт целиком.
        """
        pusher = _load(_PUSHER, "_pusher_window_fallback")
        root = _git_repo(tmp_path, name="fallback")
        fake_runner = tmp_path / "дерево-доставки" / "push_to_github.py"
        fake_runner.parent.mkdir(parents=True)
        fake_runner.write_text("# копия инструмента доставки\n", encoding="utf-8")
        verdict = pusher.mutation_window_verdict(
            [os.path.join(root, "pkg", "mod.py")], runner_file=str(fake_runner))
        assert verdict["unmeasured"] == []
        assert verdict["reader"] == os.path.join(_REPO_ROOT, "scripts",
                                                 "delta_mutation_run.py")
        assert verdict["trees"] == {root: 0}

    def test_a_file_whose_tree_is_unknown_is_unmeasured_too(self, tmp_path):
        pusher = _load(_PUSHER, "_pusher_window_notree")
        loose = tmp_path / "не-репозиторий" / "file.py"
        loose.parent.mkdir(parents=True)
        loose.write_text("x = 1\n", encoding="utf-8")
        verdict = pusher.mutation_window_verdict([str(loose)])
        assert verdict["unmeasured"] and "дерево файла не определяется" in \
            verdict["unmeasured"][0]

    def test_both_doors_call_one_implementation(self):
        """Урок номеров ADR дословно (26.08): блок, живущий строками в одном CLI,
        вторая дверь не исполняет, и через неё уезжает то, что первая отклоняла."""
        pusher = _load(_PUSHER, "_pusher_window_identity")
        batch = _load(_BATCH, "_batch_window_identity")
        # Тождество ОБЪЕКТОВ здесь ничего не значит (каждый `_load` даёт свой экземпляр
        # модуля). Значение имеет ФАЙЛ, в котором живёт исполняемый код: своей копии
        # правила у batch-CLI быть не должно.
        assert batch.enforce_no_delivered_mutant is \
            batch._root_push.enforce_no_delivered_mutant
        assert batch.mutation_window_verdict is \
            batch._root_push.mutation_window_verdict
        assert batch.enforce_no_delivered_mutant.__code__.co_filename == _PUSHER
        assert pusher.enforce_no_delivered_mutant.__code__.co_filename == _PUSHER
        assert batch.MUTATION_WINDOW_EXIT == pusher.MUTATION_WINDOW_EXIT
        batch_src = open(_BATCH, encoding="utf-8").read()
        for name in ("enforce_no_delivered_mutant", "mutation_window_verdict"):
            assert f"def {name}" not in batch_src, (
                f"push_to_github_batch.py определяет {name} САМ — починка в одном "
                f"пушере не доедет до другого (так уехал второй ADR-145)")
        for src in (_PUSHER, _BATCH):
            text = open(src, encoding="utf-8").read()
            assert "enforce_no_delivered_mutant(all_files" in text, src
            assert "--allow-open-mutation-window" in text, src

    @pytest.mark.parametrize("cli", ["push_to_github.py", "push_to_github_batch.py"])
    def test_each_cli_refuses_with_the_same_code_as_a_process(self, tmp_path, cli):
        """ИСХОД каждой двери, а не её исходник: CLI поднимается процессом и обязан
        дать код 10. Сцена — ОДНОРАЗОВЫЙ репозиторий с копиями инструмента доставки
        и читателя: открывать окно в дереве САМОГО прогона нельзя, иначе этот тест
        краснел бы от любого мутационного замера по этому же дереву (чужое красное
        сделало бы «убитыми» всех мутантов разом, урок цикла #810).
        """
        root = _git_repo(tmp_path, name=f"cli-{cli}")
        os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
        for rel in ("push_to_github.py", "push_to_github_batch.py",
                    "scripts/delta_mutation_run.py"):
            src = os.path.join(_REPO_ROOT, *rel.split("/"))
            with open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8") as fh:
                fh.write(open(src, encoding="utf-8").read())
        real = os.path.join(root, "pkg", "mod.py")
        dmr.open_window(root, _spec_obj(), {"pkg/mod.py": real},
                        {"pkg/mod.py": open(real, encoding="utf-8").read()},
                        now="ОТМЕТКА-СТЕНД", pid=os.getpid(), label="МЕТКА-СТЕНД")
        with open(real, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 2\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(root, cli), "--dry-run", "--files", real,
             "--message", "стенд окна"],
            capture_output=True, text=True, cwd=root)
        assert proc.returncode == 10, (proc.returncode, proc.stdout[-400:],
                                       proc.stderr[-400:])
        assert "окно мутационного прибора" in proc.stderr
        assert "ДЕРЖИТ МУТАНТА" in proc.stderr


# ───── 7. ВОСХОДИТЕЛЬ ПО ВЫХОДУ: ЧТО ОН ЗАКРЫВАЕТ И ЧТО НЕТ ─────


class TestTheExitRestorerAndItsNamedLimit:

    def test_the_signal_guard_is_wired_to_the_signals_that_can_be_caught(self):
        """Обработчик — ВХОД: проверяется ПРОВОДКА, а не поведение настоящего сигнала
        в процессе pytest (поднять его здесь значило бы убить сам прогон)."""
        marker = []

        def _handler(signum, _frame):
            marker.append(signum)

        saved = {name: signal.getsignal(getattr(signal, name))
                 for name in ("SIGTERM", "SIGINT", "SIGHUP")
                 if hasattr(signal, name)}
        try:
            armed = dmr.install_signal_guard(_handler)
            assert int(signal.SIGTERM) in armed
            assert signal.getsignal(signal.SIGTERM) is _handler
        finally:
            for name, old in saved.items():
                signal.signal(getattr(signal, name), old)

    def test_the_default_handler_unwinds_through_finally(self):
        """`SystemExit` разворачивает стек ⇒ `finally` прибора исполняется. Порви
        звено (проглоти сигнал), и возврат не случится даже на SIGTERM."""
        with pytest.raises(SystemExit) as err:
            dmr._raise_on_signal(int(signal.SIGTERM), None)
        assert "finally" in str(err.value)

    def test_sigkill_is_not_in_the_armed_list_and_that_is_the_point(self):
        """Предел НАЗВАН, а не замаскирован: `SIGKILL` перехватить нельзя, и поэтому у
        прибора есть ЗАПИСЬ окна. Положительный контроль на этот предел — настоящий
        `SIGKILL` в батарее №1."""
        saved = {name: signal.getsignal(getattr(signal, name))
                 for name in ("SIGTERM", "SIGINT", "SIGHUP")
                 if hasattr(signal, name)}
        try:
            armed = dmr.install_signal_guard()
        finally:
            for name, old in saved.items():
                signal.signal(getattr(signal, name), old)
        assert int(signal.SIGKILL) not in armed
