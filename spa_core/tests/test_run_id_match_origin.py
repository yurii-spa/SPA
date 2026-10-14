"""ОТКУДА взялось совпадение метки работника: окружение или командная строка (ADR-722, G721 п. 2).

`ps -A -Ewww` печатает командную строку и окружение ОДНИМ полем, поэтому прибор владения
(`claude_run_with_timeout._inst_run_id`) не различал «метка унаследована работником» и
«метка упомянута в аргументах». Карточка `inbox-zhurnal-obyavlenii-merit-zapuskatelya-vt`
(п. 2) назвала подозреваемым обёртку `claude_run_with_timeout.py --run-id <метка>`.

ЗАМЕР 14.10 ПОДОЗРЕВАЕМОГО НЕ ПОДТВЕРДИЛ, и это закреплено тестом ниже: игла прибора —
`SPA_RUN_ID=<метка>`, а в командной строке обёртки стои́т `--run-id <метка>`, то есть
обёртка в население совпадений НЕ попадает вовсе (она и не кладёт метку себе: `env` для
метки собирается ПЕРЕД `Popen` и достаётся только потомку).

НАШЛОСЬ ДРУГОЕ, и оно больше: из ЧЕТЫРЁХ живых носителей метки идущего цикла ДВА были
САМИМ ПРИБОРОМ ЗАМЕРА — python, задавший вопрос, и `ps`, которого он для этого позвал;
метку они несут в окружении по наследству. Вердикт это не меняет (о своей метке
спрашивают только там, где ответ короткий), но число в прозе вердикта звучало как
население РАБОТНИКОВ, которым не было. Поэтому `origin_census` считает «сам прибор»
ОТДЕЛЬНО и НЕ вычитает: вычитание отдало бы карточку живого работника всякий раз, когда
работник оказывается предком замерщика — а он им и оказывается по построению.

Все двери к ОС — ВХОДЫ (`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»): снимок и
таблица командных строк передаются сценой, живую машину тест не спрашивает ни разу.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARK = "orchestrator-24396-ABC"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def w():
    return _load("_t866_wrapper", "scripts/claude_run_with_timeout.py")


@pytest.fixture(scope="module")
def lock():
    return _load("_t866_lock2", "scripts/orchestrator_cycle_lock.py")


def _snap(w, rows):
    """Снимок из сцены: pid → (ppid, состояние, возраст, «команда + окружение»)."""
    readable = sum(1 for _p, (_pp, _s, _a, tail) in rows.items()
                   if "=" in tail and " PATH=" in " " + tail)
    return w.Snapshot(rows, readable, len(rows) - readable)


class TestWhereTheMatchCameFrom:
    def test_a_label_inherited_in_the_environment_is_env_origin(self, w):
        argv = "python3 -m spa_core.cycle"
        rows = {7: (1, "S", 10.0, f"{argv} PATH=/bin {w.RUN_ID_VAR}={MARK}")}
        org = w.match_origin(_snap(w, rows), MARK, argv={7: argv})
        assert org[7][0] == w.MATCH_ENV, org[7]

    def test_a_label_passed_as_an_argument_is_cmdline_origin(self, w):
        """Положительный контроль: так выглядел бы мой собственный замер `grep`."""
        argv = f"grep {w.RUN_ID_VAR}={MARK}"
        rows = {7: (1, "S", 10.0, f"{argv} PATH=/bin")}
        org = w.match_origin(_snap(w, rows), MARK, argv={7: argv})
        assert org[7][0] == w.MATCH_CMDLINE, org[7]
        assert "работником это не доказано" in org[7][1]

    def test_the_wrappers_own_flag_is_not_a_match_at_all(self, w):
        """Подозреваемый из карточки: ИГЛА не `--run-id`, а `SPA_RUN_ID=`.

        Обёртка кладёт метку только в окружение ПОТОМКА, поэтому её собственная строка
        совпадением не является — замер поправляет формулировку карточки, а не
        подтверждает её."""
        argv = f"python3 scripts/claude_run_with_timeout.py --run-id {MARK}"
        rows = {7: (1, "S", 10.0, f"{argv} PATH=/bin")}
        assert w.match_origin(_snap(w, rows), MARK, argv={7: argv}) == {}
        assert w._inst_run_id(_snap(w, rows), 0, MARK) == set()

    def test_the_boundary_is_pinned_from_both_REACHABLE_sides(self, w):
        """Граница «конец командной строки» — с двух сторон, по одному символу.

        Равенство `at == len(argv)` недостижимо (разделитель — пробел, игла начинается
        с буквы), и мутант `<=` поэтому ВЫЖИЛ; закрепляем то, что достижимо."""
        needle = f"{w.RUN_ID_VAR}={MARK}"
        # игла УПИРАЕТСЯ в конец командной строки ⇒ последний символ argv
        argv = f"grep {needle}"
        rows = {7: (1, "S", 10.0, f"{argv} PATH=/bin")}
        assert w.match_origin(_snap(w, rows), MARK, argv={7: argv})[7][0] == w.MATCH_CMDLINE
        # игла — ПЕРВЫЙ символ окружения ⇒ ровно на один символ правее границы
        argv2 = "python3 x"
        rows2 = {7: (1, "S", 10.0, f"{argv2} {needle} PATH=/bin")}
        assert w.match_origin(_snap(w, rows2), MARK, argv={7: argv2})[7][0] == w.MATCH_ENV

    def test_a_pid_absent_from_the_second_table_is_the_third_outcome(self, w):
        """Таблицы снимаются не в один миг: 1 pid из 650 в живом замере. Выдать его за
        `env` значило бы объявить обёртку работником (инв. #17)."""
        rows = {7: (1, "S", 10.0, f"python3 x PATH=/bin {w.RUN_ID_VAR}={MARK}")}
        org = w.match_origin(_snap(w, rows), MARK, argv={})
        assert org[7][0] == w.MATCH_UNMEASURED
        assert "не в один миг" in org[7][1]

    def test_a_broken_prefix_is_the_third_outcome(self, w):
        """Свойство «строка без окружения есть ПРЕФИКС строки с окружением» измерено
        (649 из 649), но не обещано: не совпало ⇒ границу не определить."""
        rows = {7: (1, "S", 10.0, f"python3 x PATH=/bin {w.RUN_ID_VAR}={MARK}")}
        org = w.match_origin(_snap(w, rows), MARK, argv={7: "СОВСЕМ ДРУГОЕ"})
        assert org[7][0] == w.MATCH_UNMEASURED
        assert "префиксом" in org[7][1]

    def test_an_unavailable_second_table_does_not_kill_the_axis(self, w):
        """Происхождение — ДОПОЛНИТЕЛЬНОЕ сведение. Его неизмеримость не вправе
        превратить вердикт о занятости в `unchecked`: это была бы вечная блокировка."""
        def _boom():
            raise w.PsUnavailable("вторая таблица не снята (сцена)")
        rows = {7: (1, "S", 10.0, f"python3 x PATH=/bin {w.RUN_ID_VAR}={MARK}")}
        snap = _snap(w, rows)
        org = w.match_origin(snap, MARK, probe=_boom)
        assert org[7][0] == w.MATCH_UNMEASURED
        assert "не снята" in org[7][1], org[7]
        assert w._inst_run_id(snap, 0, MARK) == {7}, (
            "ось РАБОТНИКА обязана остаться измеримой без второй таблицы")


class TestTheCensusNamesTheMeasurerItself:
    def test_the_measuring_process_is_counted_apart_and_not_subtracted(self, w):
        """Замер 14.10: 4 носителя, из них 2 — сам прибор. Вычитать нельзя: работник
        по построению ПРЕДОК замерщика (python зовут из его же дерева)."""
        argv = {10: "claude -p цикл", 11: "python3 census.py", 12: "ps -A -Ewww"}
        rows = {pid: ((11 if pid == 12 else 1), "S", 10.0,
                      f"{cmd} PATH=/bin {w.RUN_ID_VAR}={MARK}")
                for pid, cmd in argv.items()}
        c = w.origin_census(_snap(w, rows), MARK, argv=argv, self_pid=11)
        assert c["total"] == 3 and c["counts"][w.MATCH_ENV] == 3
        assert c["self"] == [11, 12], c["self"]

    def test_the_lock_names_the_origin_in_its_verdict_prose(self, w, lock):
        rows = {10: (1, "S", 10.0, f"claude -p x PATH=/bin {w.RUN_ID_VAR}={MARK}")}
        words = lock.origin_words(w, _snap(w, rows), MARK,
                                  argv={10: "claude -p x"})
        assert "по происхождению" in words and "окружение 1" in words

    def test_an_old_instrument_without_the_census_is_named_not_measured(self, lock):
        """Частичная доставка (старая копия прибора рядом) НЕ вправе краснить ось."""
        class _Old:
            pass
        words = lock.origin_words(_Old(), object(), MARK)
        assert "НЕ ИЗМЕРЕНО" in words and "origin_census" in words
