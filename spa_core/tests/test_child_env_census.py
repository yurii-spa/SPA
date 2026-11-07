#!/usr/bin/env python3
"""Сторож переписи «обрезанное окружение дочернего прогона» (ADR-939).

Каждая проверка здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: она либо воспроизводит настоящую
аварию (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»), либо
воспроизводит ЛОЖНУЮ НАХОДКУ, которую первая редакция прибора выдала на живом дереве
и которая была снята ручной сверкой ДО того, как число попало в ADR:

* ``communicate`` — без него предметом назывался `test_capital_shadow_lifecycle.py`,
  где вывод читается ровно им (замер: предмет 8 → 6);
* путь артефакта, уехавший ребёнку ПЕРЕМЕННОЙ ОКРУЖЕНИЯ, — без него предметом
  назывался `rule_second_copy_census.py:8339`, который читает свой журнал (2 → 1);
* ЧЕТВЁРТАЯ форма импорта (``from p import m`` → ``m.f()``) — без неё переход через
  границу вызова находился у 5 вызовов из 12, то есть прибор отвечал о форме импорта,
  а не о классе;
* совпадение ИМЕНИ вместо импорта — функций ``run``/``_run``/``push``/``git`` в дереве
  много, и перепись по имени приписала бы вызывающему чужой подъёмник.

Сцены — одноразовое дерево в ``tmp_path``; живой репозиторий ни одной проверкой не
читается, кроме двух, которые ОБЪЯВЛЕНЫ как замер живого дерева и названы в своих
именах.

Время и личность процесса здесь не участвуют: прибор не спрашивает ни часы, ни
``ps`` — поэтому ни один класс из `.claude/rules/deployment.md` (календарь, pid,
git-окружение) к этому файлу не применим, и литеральных дат в нём нет.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.monitoring import child_env_census as cec


# --------------------------------------------------------------------------- #
# сцена
# --------------------------------------------------------------------------- #

def _tree(root: Path, files: dict[str, str]) -> Path:
    """Одноразовое дерево: ``{'pkg/mod.py': '<код>'}`` → каталог-корень."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _rows(root: Path, files: dict[str, str]) -> list[dict]:
    doc = cec.census(_tree(root, files), roots=("pkg",))
    assert doc["surface"]["reason"] is None, doc["surface"]
    return doc["rows"]


def _one(root: Path, body: str, *, head: str = "import os, subprocess, sys") -> dict:
    rows = _rows(root, {"pkg/mod.py": f"{head}\n\n\ndef f():\n" + body})
    assert len(rows) == 1, [(r["file"], r["line"], r["call"]) for r in rows]
    return rows[0]


# --------------------------------------------------------------------------- #
# дверь 1 — происхождение окружения
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("expr", [
    'os.environ.copy()',
    'dict(os.environ)',
    '{**os.environ, "K": "V"}',
    'os.environ | {"K": "V"}',
    'None',
])
def test_env_from_the_parent_in_every_living_form_is_derived(tmp_path, expr):
    row = _one(tmp_path, f'    subprocess.run(["git", "x"], env={expr})\n')
    assert row["env"] == "derived", row


def test_env_derived_through_a_chain_of_names_is_still_derived(tmp_path):
    """Разрешение имён идёт ДО НЕПОДВИЖНОЙ ТОЧКИ, а не на один шаг."""
    row = _one(tmp_path,
               '    base = os.environ.copy()\n'
               '    mid = base\n'
               '    env = mid\n'
               '    subprocess.run(["git", "x"], env=env)\n')
    assert row["env"] == "derived", row


def test_env_derived_through_from_os_import_environ(tmp_path):
    row = _one(tmp_path, '    subprocess.run(["git", "x"], env=dict(environ))\n',
               head="import subprocess\nfrom os import environ")
    assert row["env"] == "derived", row


def test_a_handbuilt_env_is_named_handbuilt(tmp_path):
    """Авария #1055 дословно: окружение собрано РУКАМИ, ребёнок теряет PATH и
    PYTHONPATH, и «инструмента нет» становится неотличимо от ответа инструмента."""
    row = _one(tmp_path,
               '    env = {"SPA_ENV": "ci"}\n'
               '    subprocess.run([sys.executable, "-m", "pytest"], env=env)\n')
    assert row["env"] == "handbuilt", row
    assert "os.environ" in row["env_reason"]


def test_env_that_arrived_as_a_parameter_is_unmeasured_not_handbuilt(tmp_path):
    """Третий исход (инв. #17): происхождение решает ВЫЗЫВАЮЩИЙ, и назвать его
    рукотворным здесь значило бы выдумать находку."""
    rows = _rows(tmp_path, {"pkg/mod.py":
                            "import subprocess\n\n\n"
                            "def spawn(env):\n"
                            "    subprocess.run(['git', 'x'], env=env)\n"})
    assert len(rows) == 1 and rows[0]["env"] == "unmeasured", rows


def test_mentioning_environ_inside_a_string_is_not_derivation(tmp_path):
    """Отрицательный контроль на подстроку (ADR-333): претензия судится AST, а
    упоминание ``os.environ`` в тексте происхождением не является."""
    row = _one(tmp_path,
               '    env = {"NOTE": "построено без os.environ намеренно"}\n'
               '    subprocess.run(["git", "x"], env=env)\n')
    assert row["env"] == "handbuilt", row


# --------------------------------------------------------------------------- #
# дверь 2 — ищется ли инструмент через окружение
# --------------------------------------------------------------------------- #

def test_a_module_run_with_dash_m_is_looked_up_through_pythonpath(tmp_path):
    row = _one(tmp_path,
               '    subprocess.run([sys.executable, "-m", "pytest", "x"],'
               ' env=os.environ.copy())\n')
    assert row["tool"] == "needs_env_lookup" and row["tool_name"] == "pytest", row


def test_a_bare_binary_is_looked_up_through_path(tmp_path):
    row = _one(tmp_path, '    subprocess.run(["git", "status"], env=os.environ.copy())\n')
    assert row["tool"] == "needs_env_lookup" and row["tool_name"] == "git", row


@pytest.mark.parametrize("argv,expected_head", [
    ('[sys.executable, "script.py"]', "<sys.executable>"),
    ('["/bin/echo", "hi"]', "/bin/echo"),
])
def test_an_absolutely_named_tool_does_not_depend_on_the_environment(tmp_path, argv,
                                                                    expected_head):
    row = _one(tmp_path, f'    subprocess.run({argv}, env=os.environ.copy())\n')
    assert row["tool"] == "named_absolutely" and row["tool_name"] == expected_head, row


def test_an_argv_computed_at_runtime_is_unmeasured(tmp_path):
    row = _one(tmp_path,
               '    subprocess.run(build_argv(), env=os.environ.copy())\n')
    assert row["tool"] == "unmeasured", row


def test_dash_m_is_judged_by_position_so_a_computed_element_keeps_its_slot(tmp_path):
    """Нелитеральный элемент сохраняет ПОЗИЦИЮ: потеря позиции сдвинула бы ответ
    о ``-m`` на соседний аргумент."""
    row = _one(tmp_path,
               '    subprocess.run([sys.executable, chosen_flag, "pytest"],'
               ' env=os.environ.copy())\n')
    assert row["tool"] == "named_absolutely", row


def test_argv_assembled_by_a_helper_in_the_same_file_is_still_read(tmp_path):
    """Без шага «что возвращает соседняя функция» ЕДИНСТВЕННАЯ дверь дочернего
    `pytest` отвечала бы «argv не читается литералами» — то есть прибор не увидел бы
    ``-m pytest``, написанное прямым текстом."""
    rows = _rows(tmp_path, {"pkg/mod.py":
                            "import os, subprocess, sys\n\n\n"
                            "def argv_for(p):\n"
                            "    return [sys.executable, '-m', 'pytest', str(p)]\n\n\n"
                            "def f(p):\n"
                            "    argv = argv_for(p)\n"
                            "    subprocess.run(argv, env=os.environ.copy())\n"})
    assert len(rows) == 1 and rows[0]["tool_name"] == "pytest", rows


@pytest.mark.parametrize("wrap", ["list({})", "tuple({})", "{}"])
def test_a_sequence_wrapper_around_argv_is_only_a_form_of_writing(tmp_path, wrap):
    """``list(argv)`` — скобки, а не инструмент. Без снятия обёртки ЕДИНСТВЕННАЯ дверь
    дочернего `pytest` (`run_child_pytest` передаёт именно ``list(argv)``) отвечала
    «argv не читается литералами», и прибор отвечал бы о скобках."""
    rows = _rows(tmp_path, {"pkg/mod.py":
                            "import os, subprocess, sys\n\n\n"
                            "def f():\n"
                            "    argv = [sys.executable, '-m', 'pytest']\n"
                            f"    subprocess.run({wrap.format('argv')},\n"
                            "                   env=os.environ.copy())\n"})
    assert len(rows) == 1 and rows[0]["tool_name"] == "pytest", rows


# --------------------------------------------------------------------------- #
# дверь 3 — доказательство прогона
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("body,why", [
    ('    subprocess.run(["git", "x"], env=os.environ.copy(), check=True)\n',
     "check=True — ошибка уходит в шум"),
    ('    subprocess.check_output(["git", "x"], env=os.environ.copy())\n',
     "check_output сам поднимает на ненулевом коде"),
])
def test_a_caller_whose_error_goes_to_noise_demands_evidence(tmp_path, body, why):
    row = _one(tmp_path, body)
    assert row["evidence"] == "demands_evidence", (why, row)


@pytest.mark.parametrize("read", ["proc.stdout", "proc.stderr", "proc.output"])
def test_reading_the_child_output_is_evidence(tmp_path, read):
    row = _one(tmp_path,
               '    proc = subprocess.run(["git", "x"], env=os.environ.copy(),\n'
               '                          capture_output=True)\n'
               f'    print({read})\n')
    assert row["evidence"] == "demands_evidence", row


def test_communicate_is_a_way_of_reading_the_output_and_was_the_first_false_finding(tmp_path):
    """ЛОЖНАЯ НАХОДКА первой редакции, воспроизведённая дословно.

    `test_capital_shadow_lifecycle.py:958/960` читает вывод ровно так — через
    ``communicate()``, — и попадал в предмет только потому, что прибор знал
    ``.stdout`` и не знал ``.communicate``. Замер: предмет 8 → 6.
    """
    row = _one(tmp_path,
               '    p = subprocess.Popen(["git", "x"], env=os.environ.copy(),\n'
               '                         stdout=subprocess.PIPE)\n'
               '    out, err = p.communicate(timeout=60)\n'
               '    assert out is not None\n')
    assert row["evidence"] == "demands_evidence", row


def test_a_caller_that_only_looks_at_the_return_code_cannot_tell_the_two_apart(tmp_path):
    row = _one(tmp_path,
               '    proc = subprocess.run(["git", "x"], env=os.environ.copy(),\n'
               '                          capture_output=True)\n'
               '    return proc.returncode\n')
    assert row["evidence"] == "returncode_only", row
    assert "один и тот же ненулевой код" in row["evidence_reason"]


def test_an_unbound_result_without_check_is_unmeasured(tmp_path):
    """Третий исход: что именно судится, в этом месте не читается вовсе."""
    row = _one(tmp_path, '    subprocess.run(["git", "x"], env=os.environ.copy())\n')
    assert row["evidence"] == "unmeasured", row


def test_a_computed_check_is_unmeasured_not_evidence(tmp_path):
    row = _one(tmp_path,
               '    subprocess.run(["git", "x"], env=os.environ.copy(), check=strict)\n')
    assert row["evidence"] == "unmeasured", row


# --------------------------------------------------------------------------- #
# дверь 4 — положительный контроль
# --------------------------------------------------------------------------- #

def test_reading_an_artifact_whose_path_went_to_the_child_in_argv_is_a_control(tmp_path):
    row = _one(tmp_path,
               '    out = Path("o.json")\n'
               '    subprocess.run([sys.executable, "-m", "p", str(out)],\n'
               '                   env=os.environ.copy())\n'
               '    rec = out.read_text()\n',
               head="import os, subprocess, sys\nfrom pathlib import Path")
    assert row["control"] == "artifact_read", row


def test_an_artifact_path_carried_in_the_environment_is_a_control_too(tmp_path):
    """ВТОРАЯ ложная находка первой редакции, воспроизведённая дословно.

    `rule_second_copy_census.py:8339` передаёт журнал повторных входов ПЕРЕМЕННОЙ
    ОКРУЖЕНИЯ и затем читает его. Дверь, смотревшая только в argv, назвала этот
    call-site предметом. Замер: предмет 2 → 1.
    """
    row = _one(tmp_path,
               '    ledger = Path("reentry.log")\n'
               '    env = dict(os.environ)\n'
               '    env.update({"SPA_REENTRY": str(ledger)})\n'
               '    subprocess.run([sys.executable, "-m", "pytest"], env=env)\n'
               '    marks = ledger.read_text()\n',
               head="import os, subprocess, sys\nfrom pathlib import Path")
    assert row["control"] == "artifact_read", row
    assert "ledger" in row["control_reason"], row


def test_asking_whether_the_child_is_alive_is_a_control_even_with_devnull(tmp_path):
    """ТРЕТЬЯ ложная находка: `test_safe_terminate_ownership.py:283` отправляет вывод
    в ``DEVNULL`` НАМЕРЕННО — прочитать его нельзя по построению, и контроль там
    единственно возможный такой: ``assertIsNone(neigh.poll())``."""
    row = _one(tmp_path,
               '    neigh = subprocess.Popen([sys.executable, "-m", "pytest"],\n'
               '                             env=os.environ.copy(),\n'
               '                             stdout=subprocess.DEVNULL)\n'
               '    assert neigh.poll() is None\n')
    assert row["control"] == "liveness_checked", row


def test_a_caller_with_no_proof_of_the_run_at_all_has_no_control(tmp_path):
    row = _one(tmp_path,
               '    proc = subprocess.run([sys.executable, "-m", "p"],\n'
               '                          env=os.environ.copy())\n'
               '    return proc.returncode\n')
    assert row["control"] == "none", row
    assert "ни одного" in row["control_reason"], row


# --------------------------------------------------------------------------- #
# поверхность: ОДИН переход через границу вызова
# --------------------------------------------------------------------------- #

_SPAWNER = ("import os, subprocess, sys\n\n\n"
            "def run_child(test, env=None, cwd=None):\n"
            "    return subprocess.run([sys.executable, '-m', 'pytest', str(test)],\n"
            "                          env=dict(env) if env is not None else None,\n"
            "                          capture_output=True)\n")


def test_the_list_of_spawners_is_measured_not_declared(tmp_path):
    """Подъёмником считается функция, у которой ``env=`` ребёнка происходит от её
    СОБСТВЕННОГО параметра. Список из головы расходился бы с кодом молча."""
    found = cec.find_spawners(_tree(tmp_path, {"pkg/helper.py": _SPAWNER}),
                              roots=("pkg",))
    assert list(found) == [("pkg.helper", "run_child")], found
    assert found[("pkg.helper", "run_child")]["tool_name"] == "pytest", found


@pytest.mark.parametrize("body", [
    # окружение целиком своё — параметра в нём нет вовсе
    "def run_child(test):\n"
    "    return subprocess.run([sys.executable, '-m', 'pytest'],\n"
    "                          env=os.environ.copy())\n",
    # окружение своё, а параметр в него лишь ДОЛИВАЮТ: обрезать его вызывающий
    # не может, и объявить такую функцию подъёмником значило бы судить вызывающего
    # за окружение, которого он не выбирал. Эта форма раздувала перечень 55 → 119.
    "def run_child(test, extra):\n"
    "    env = os.environ.copy()\n"
    "    env.update(extra)\n"
    "    return subprocess.run([sys.executable, '-m', 'pytest'], env=env)\n",
])
def test_a_function_building_its_own_env_is_not_a_spawner(tmp_path, body):
    """Обратный контроль: подъёмник — тот, у кого окружение приходит СНАРУЖИ ЦЕЛИКОМ."""
    found = cec.find_spawners(
        _tree(tmp_path, {"pkg/helper.py": "import os, subprocess, sys\n\n\n" + body}),
        roots=("pkg",))
    assert found == {}, found


@pytest.mark.parametrize("head,call", [
    ("from pkg.helper import run_child", "run_child"),
    ("import pkg.helper", "pkg.helper.run_child"),
    ("from pkg import helper", "helper.run_child"),
])
def test_all_living_import_forms_cross_the_call_boundary(tmp_path, head, call):
    """Четвёртая форма (``from p import m`` → ``m.f()``) добавлена ЗАМЕРОМ: без неё
    переход находился у 5 вызовов из 12, потому что ПЯТЬ из семи вызывающих
    единственной двери дочернего `pytest` пишут именно её."""
    rows = _rows(tmp_path, {
        "pkg/helper.py": _SPAWNER,
        "pkg/caller.py": f"import os\n{head}\n\n\ndef t():\n"
                         f"    {call}('t.py', env=os.environ.copy())\n",
    })
    crossing = [r for r in rows if r["hop"] == "through_spawner"]
    assert len(crossing) == 1, rows
    assert crossing[0]["tool_name"] == "pytest", crossing
    assert crossing[0]["spawner"].startswith("pkg/helper.py:"), crossing


def test_a_name_that_merely_collides_does_not_cross(tmp_path):
    """`.claude/rules/adapters.md` «одно имя — один объект»: функций ``run_child`` в
    дереве может быть много, и переход по СОВПАДЕНИЮ ИМЕНИ приписал бы вызывающему
    чужой подъёмник вместе с чужим инструментом."""
    rows = _rows(tmp_path, {
        "pkg/helper.py": _SPAWNER,
        "pkg/other.py": "import os\n\n\n"
                        "def run_child(test, env=None):\n"
                        "    return 0\n\n\n"
                        "def t():\n"
                        "    run_child('t.py', env=os.environ.copy())\n",
    })
    assert [r["hop"] for r in rows if r["file"] == "pkg/other.py"] == [], rows


def test_the_spawner_body_is_never_the_subject_itself(tmp_path):
    """Происхождение окружения в теле подъёмника решает ВЫЗЫВАЮЩИЙ. Считать тело
    предметом значило бы считать одну дыру дважды и указать на место, где её нечем
    ни найти, ни починить."""
    doc = cec.census(_tree(tmp_path, {"pkg/helper.py": _SPAWNER}), roots=("pkg",))
    body = [r for r in doc["rows"] if r["hop"] == "spawner_body"]
    assert len(body) == 1, doc["rows"]
    assert body[0] not in doc["subject"] and body[0] not in doc["not_excluded"]
    assert doc["surface"]["sites_spawner_body"] == 1, doc["surface"]


# --------------------------------------------------------------------------- #
# предмет и третий исход
# --------------------------------------------------------------------------- #

def test_the_subject_is_the_conjunction_of_its_declared_axes(tmp_path):
    doc = cec.census(_tree(tmp_path, {"pkg/mod.py":
                                      "import os, subprocess, sys\n\n\n"
                                      "def f():\n"
                                      "    p = subprocess.run(\n"
                                      "        [sys.executable, '-m', 'pytest'],\n"
                                      "        env=os.environ.copy())\n"
                                      "    return p.returncode\n"}), roots=("pkg",))
    assert len(doc["subject"]) == 1, doc["rows"]
    row = doc["subject"][0]
    for axis, dangerous in cec.SUBJECT_AXES.items():
        assert row[axis] == dangerous, (axis, row)


@pytest.mark.parametrize("safe_axis,body", [
    ("tool", "    p = subprocess.run([sys.executable, 'x.py'], env=os.environ.copy())\n"
             "    return p.returncode\n"),
    ("evidence", "    subprocess.run([sys.executable, '-m', 'pytest'],\n"
                 "                   env=os.environ.copy(), check=True)\n"),
    ("control", "    out = Path('o')\n"
                "    p = subprocess.run([sys.executable, '-m', 'pytest', str(out)],\n"
                "                       env=os.environ.copy())\n"
                "    out.read_text()\n"
                "    return p.returncode\n"),
])
def test_one_proven_safe_axis_takes_the_site_out_of_the_subject(tmp_path, safe_axis, body):
    """Сторож в ОБЕ стороны: каждая ось предмета проверяется ПОРВАННОЙ по одной, с
    названным звеном. Иначе зелёная проверка не отличала бы «оси работают» от
    «условие всегда истинно»."""
    doc = cec.census(_tree(tmp_path, {"pkg/mod.py":
                                      "import os, subprocess, sys\n"
                                      "from pathlib import Path\n\n\n"
                                      "def f():\n" + body}), roots=("pkg",))
    assert doc["subject"] == [], (safe_axis, doc["rows"])
    assert doc["not_excluded"] == [], (safe_axis, doc["rows"])


def test_an_unmeasured_axis_is_not_excluded_and_not_found(tmp_path):
    """Третий исход (инв. #17): «не измерено» не сливается ни с «чисто», ни с
    «найдено» — иначе оно стало бы неотличимо от ответа."""
    doc = cec.census(_tree(tmp_path, {"pkg/mod.py":
                                      "import os, subprocess\n\n\n"
                                      "def f():\n"
                                      "    subprocess.run(build(),\n"
                                      "                   env=os.environ.copy())\n"}),
                     roots=("pkg",))
    assert doc["subject"] == [] and len(doc["not_excluded"]) == 1, doc["rows"]


def test_an_argv_that_is_not_positional_is_unmeasured_and_never_a_finding(tmp_path):
    """Третий исход оси ИНСТРУМЕНТА у ВТОРОЙ её ветки — добавлен циклом #1058.

    Сосед (`test_an_unmeasured_axis_is_not_excluded_and_not_found`) закрывает ветку
    «argv передан, но литералами не читается»; ветка «argv не передан ПОЗИЦИОННО»
    сцены не имела вовсе, и мутант, подменивший её ``unmeasured`` на
    ``needs_env_lookup``, пережил весь набор (мутационная проба #1058, M06). Вред
    шёл бы в сторону ВЫДУМАННОЙ НАХОДКИ: вызов, об инструменте которого прибор не
    знает ничего, попал бы в ПРЕДМЕТ — ровно схлопывание третьего исхода (инв. #17),
    против которого написано само решение ADR-939.
    """
    doc = cec.census(_tree(tmp_path, {"pkg/mod.py":
                                      "import os, subprocess, sys\n\n\n"
                                      "def f():\n"
                                      "    p = subprocess.run(args=[sys.executable, '-m', 'pytest'],\n"
                                      "                       env=os.environ.copy())\n"
                                      "    return p.returncode\n"}),
                     roots=("pkg",))
    assert len(doc["rows"]) == 1, doc["rows"]
    row = doc["rows"][0]
    assert row["tool"] == "unmeasured", row
    assert row["tool_name"] is None, row
    assert doc["subject"] == [], doc["rows"]
    assert len(doc["not_excluded"]) == 1, doc["rows"]


def test_the_default_roots_cover_every_declared_root(tmp_path):
    """Умолчание корней меряется ПОВЕДЕНИЕМ — добавлено циклом #1058.

    Мутант ``DECLARED_ROOTS = ("spa_core",)`` пережил весь набор (проба #1058, M11):
    живое дерево проверяется двумя объявленными замерами, но ни один не спрашивает,
    СКОЛЬКО корней обошли, — а сужение умолчания молча уносит из переписи целые
    поддеревья (`scripts/`, `tests/`). Ошибка шла бы в сторону ТИШИНЫ: предмет
    уменьшился бы, и прибор доложил бы «стало лучше».

    Сцена поэтому зовёт ``census`` БЕЗ ``roots=`` — предметом является именно
    умолчание, а не способность принять список.
    """
    body = ("import os, subprocess, sys\n\n\n"
            "def f():\n"
            "    p = subprocess.run([sys.executable, '-m', 'pytest'],\n"
            "                       env=os.environ.copy())\n"
            "    return p.returncode\n")
    root = _tree(tmp_path, {f"{name}/mod.py": body for name in cec.DECLARED_ROOTS})
    doc = cec.census(root)
    assert doc["surface"]["reason"] is None, doc["surface"]
    seen = {row["file"].split("/")[0] for row in doc["rows"]}
    assert seen == set(cec.DECLARED_ROOTS), (seen, cec.DECLARED_ROOTS, doc["rows"])
    assert seen >= {"spa_core", "scripts", "tests"}, (
        "перечень корней сузился против объявленного в ADR-939: " + repr(sorted(seen)))


def test_an_unreadable_root_is_unmeasured_and_never_a_clean_pass(tmp_path):
    doc = cec.census(tmp_path / "нет-такого-дерева")
    assert doc["surface"]["reason"], doc
    assert cec.exit_code(doc) == 2, doc


def test_exit_code_tells_the_three_outcomes_apart(tmp_path):
    clean = cec.census(_tree(tmp_path / "a", {"pkg/mod.py": "x = 1\n"}), roots=("pkg",))
    assert cec.exit_code(clean) == 0 and clean["rows"] == [], clean
    found = cec.census(_tree(tmp_path / "b", {"pkg/mod.py":
                                              "import os, subprocess, sys\n\n\n"
                                              "def f():\n"
                                              "    p = subprocess.run(\n"
                                              "        [sys.executable, '-m', 'pytest'],\n"
                                              "        env=os.environ.copy())\n"
                                              "    return p.returncode\n"}),
                       roots=("pkg",))
    assert cec.exit_code(found) == 1, found


def test_a_file_that_does_not_parse_is_named_and_not_counted_as_clean(tmp_path):
    doc = cec.census(_tree(tmp_path, {"pkg/broken.py": 'x = "незакрытая строка\n'}),
                     roots=("pkg",))
    assert doc["surface"]["files_unparsed"] == 1, doc["surface"]
    assert doc["surface"]["unparsed"][0]["reason"], doc["surface"]
    assert "НЕ РАЗОБРАНО 1" in "\n".join(cec.format_report(doc))


# --------------------------------------------------------------------------- #
# паритет объявления с кодом
# --------------------------------------------------------------------------- #

def test_every_outcome_the_doors_return_is_declared(tmp_path):
    """Объявленный перечень исходов есть МЕРКА, с которой сверяется сторож. Дверь,
    вернувшая имя вне своего списка, обязана краснить, а не проезжать молча
    (урок ADR-928: объявление обязано нести СВОЙ контракт)."""
    declared = {"env": cec.ENV_OUTCOMES, "tool": cec.TOOL_OUTCOMES,
                "evidence": cec.EVIDENCE_OUTCOMES, "control": cec.CONTROL_OUTCOMES}
    doc = cec.census(Path(cec.REPO_ROOT))
    assert doc["rows"], "поверхность живого дерева пуста — сцена не та"
    for row in doc["rows"]:
        for axis, outcomes in declared.items():
            assert row[axis] in outcomes, (axis, row[axis], row["file"], row["line"])
    for axis, outcomes in declared.items():
        assert set(doc["axes"][axis]) == set(outcomes), (axis, doc["axes"][axis])


def test_the_aggravation_axis_is_measured_on_a_scene_and_not_only_declared(tmp_path):
    """Положительный контроль ОСИ УСУГУБЛЕНИЯ в обе стороны — добавлен циклом #1058.

    Мутационная проба #1058 (ADR-939 доставлен этим циклом) показала, что мутант
    ``AGGRAVATING = {}`` переживает ВЕСЬ набор: единственная проверка, упоминавшая
    перечень, перебирала его ЦИКЛОМ, а цикл по пустому словарю истинен вхолостую —
    ровно та дыра, которую ADR-938 назвал у ``all(...)`` на пустом списке, только
    на словаре и на цикл позже. Хуже того, ошибка шла в сторону ЛОЖНОГО УСИЛЕНИЯ:
    при пустом перечне ``all(AGGRAVATING.items())`` истинно для КАЖДОЙ строки, то
    есть отчёт объявил бы усугублённым весь предмет.

    Поэтому ось меряется СЦЕНОЙ, а не объявлением: окружение, собранное руками,
    обязано помечать строку предмета, унаследованное — не обязано, и напечатанное
    число обязано сойтись с измеренным.
    """
    assert cec.AGGRAVATING, (
        "перечень усугубления ПУСТ — цикл по нему истинен вхолостую, и ось "
        "«окружение ещё и собрано руками» перестала бы меряться молча")

    handbuilt = cec.census(_tree(tmp_path / "h", {"pkg/mod.py":
                                                  "import subprocess, sys\n\n\n"
                                                  "def f():\n"
                                                  "    p = subprocess.run(\n"
                                                  "        [sys.executable, '-m', 'pytest'],\n"
                                                  "        env={'PATH': '/usr/bin'})\n"
                                                  "    return p.returncode\n"}),
                           roots=("pkg",))
    assert len(handbuilt["subject"]) == 1, handbuilt["rows"]
    assert handbuilt["subject"][0]["env"] == "handbuilt", handbuilt["subject"][0]
    assert handbuilt["subject"][0]["aggravated"] is True, handbuilt["subject"][0]
    assert "УСУГУБЛЕНО (окружение ещё и собрано руками): 1" in \
        "\n".join(cec.format_report(handbuilt)), cec.format_report(handbuilt)

    derived = cec.census(_tree(tmp_path / "d", {"pkg/mod.py":
                                                "import os, subprocess, sys\n\n\n"
                                                "def f():\n"
                                                "    p = subprocess.run(\n"
                                                "        [sys.executable, '-m', 'pytest'],\n"
                                                "        env=os.environ.copy())\n"
                                                "    return p.returncode\n"}),
                         roots=("pkg",))
    assert len(derived["subject"]) == 1, derived["rows"]
    assert derived["subject"][0]["env"] == "derived", derived["subject"][0]
    assert derived["subject"][0]["aggravated"] is False, derived["subject"][0]
    assert "УСУГУБЛЕНО (окружение ещё и собрано руками): 0" in \
        "\n".join(cec.format_report(derived)), cec.format_report(derived)


def test_the_subject_axes_are_a_subset_of_the_declared_axes():
    for axis, dangerous in {**cec.SUBJECT_AXES, **cec.AGGRAVATING}.items():
        outcomes = {"env": cec.ENV_OUTCOMES, "tool": cec.TOOL_OUTCOMES,
                    "evidence": cec.EVIDENCE_OUTCOMES,
                    "control": cec.CONTROL_OUTCOMES}[axis]
        assert dangerous in outcomes, (axis, dangerous)


def test_the_instrument_writes_nothing_into_the_tree_it_reads(tmp_path):
    """ADVISORY объявлен в отчёте словами — здесь он ИЗМЕРЕН."""
    root = _tree(tmp_path, {"pkg/mod.py":
                            "import os, subprocess\n\n\n"
                            "def f():\n"
                            "    subprocess.run(['git', 'x'], env=os.environ.copy())\n"})
    before = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*")) if p.is_file()}
    cec.census(root, roots=("pkg",))
    after = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*")) if p.is_file()}
    assert before == after, "прибор тронул дерево, которое обязан только читать"


def test_the_report_names_the_hop_limit_as_a_choice(tmp_path):
    """Предел глубины — ВЫБОР, и он обязан быть НАПЕЧАТАН: предел, живущий только в
    коде, читается как свойство дерева."""
    doc = cec.census(_tree(tmp_path, {"pkg/helper.py": _SPAWNER}), roots=("pkg",))
    text = "\n".join(cec.format_report(doc))
    assert "глубина перехода 1" in text and "ВЫБОР" in text, text


def test_the_subject_is_not_called_a_defect_in_the_report(tmp_path):
    """Граница утверждения обязана быть в САМОМ отчёте, а не только в ADR: читатель
    видит число, а не историю его появления."""
    doc = cec.census(_tree(tmp_path, {"pkg/mod.py":
                                      "import os, subprocess, sys\n\n\n"
                                      "def f():\n"
                                      "    p = subprocess.run(\n"
                                      "        [sys.executable, '-m', 'pytest'],\n"
                                      "        env=os.environ.copy())\n"
                                      "    return p.returncode\n"}), roots=("pkg",))
    text = "\n".join(cec.format_report(doc))
    assert "ПРЕДМЕТ НЕ ЕСТЬ ДЕФЕКТ" in text and "НЕ ИЗМЕРЕНО" in text, text


# --------------------------------------------------------------------------- #
# замер ЖИВОГО дерева — объявлен в имени, а не спрятан
# --------------------------------------------------------------------------- #

def test_the_living_tree_still_has_the_single_door_for_a_child_pytest():
    """Предпосылка всей второй половины прибора: дверь дочернего `pytest` в дереве
    ОДНА и окружение ей ПЕРЕДАЮТ. Исчезни она — перепись отвечала бы о форме,
    которой больше нет, и молчала бы об этом."""
    source = (Path(cec.REPO_ROOT) / "spa_core/tests/_child_pytest.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    spawn = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "run_child_pytest")
    assert "env" in cec._param_names(spawn), ast.dump(spawn.args)
    found = cec.find_spawners(Path(cec.REPO_ROOT), roots=("spa_core",))
    assert ("spa_core.tests._child_pytest", "run_child_pytest") in found, sorted(found)
