"""Контроли прибора «достижим ≠ зовётся» — в ОБЕ стороны, на настоящем приборе.

# LLM_FORBIDDEN

Главный контроль здесь — ДИФФЕРЕНЦИАЛЬНЫЙ, и он же есть доказательство, что
класс существует: на одной и той же одноразовой сцене снимается использование
импортированного имени, а сам импорт остаётся. Старый прибор (`_mention_wiring`,
ADR-1026/1027) при этом вердикт НЕ МЕНЯЕТ — субъект числится подключённым, —
а новый переводит его в `MENTION_ONLY`. Ровно эту проверку заказал G1016 п. 1
(«снять использование, оставив импорт, перемерить вердикт»).

Каждая сцена — одноразовое дерево в `tmp_path`; живое дерево не читается и не
пишется. Пол непустоты поверхности сдвигается явно (`min_subjects=1`): сцене
нужны два-три файла, а не двести.

# FROZEN-DATE-OK: нет ни одной литеральной даты — вопрос прибора не о свежести
"""
from __future__ import annotations

import pathlib

import pytest

from spa_core.tests import _call_wiring as cw
from spa_core.tests import _mention_wiring as mw

SUBJ_DIR = "spa_core/monitoring"
ENTRY = '\n\ndef main():\n    return 0\n'


def _write(root: pathlib.Path, rel: str, body: str) -> pathlib.Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _scene(root: pathlib.Path, *, mentioner: str, mentioner_body: str,
           subject: str = "x_monitor") -> dict:
    """Дерево из субъекта, упоминающего и одного стороннего корня."""
    _write(root, f"{SUBJ_DIR}/{subject}.py", f'"""{subject}."""{ENTRY}')
    _write(root, mentioner, mentioner_body)
    # Корень-извне, чтобы поверхность скана не выродилась в один файл.
    _write(root, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    return cw.measure(root, min_subjects=1)


def _verdict(rep: dict, subject: str = "x_monitor") -> str:
    return rep["status"][f"{SUBJ_DIR}/{subject}.py"]


# --- ДИФФЕРЕНЦИАЛЬНЫЙ КОНТРОЛЬ: ровно то, что заказал G1016 п. 1 -------------

_IMPORT = "from spa_core.monitoring import x_monitor\n"
_USE = "\n\ndef go():\n    return x_monitor.main()\n"


def test_removing_the_use_but_keeping_the_import_flips_only_the_new_verdict(tmp_path):
    """Снять использование, оставив импорт: новый прибор видит, старый — нет."""
    whole = tmp_path / "whole"
    half = tmp_path / "half"
    rep_whole = _scene(whole, mentioner="scripts/caller.py",
                       mentioner_body=_IMPORT + _USE)
    rep_half = _scene(half, mentioner="scripts/caller.py",
                      mentioner_body=_IMPORT)

    assert _verdict(rep_whole) == cw.CALLED, "целый контур обязан быть CALLED"
    assert _verdict(rep_half) == cw.MENTION_ONLY, (
        "импорт без использования — предмет класса, а не проводка")

    # А старый прибор на ОБЕИХ сценах отвечает одинаково: он слеп к этой двери.
    old_whole = mw.measure(whole, min_subjects=1)
    old_half = mw.measure(half, min_subjects=1)
    subj = f"{SUBJ_DIR}/x_monitor.py"
    assert old_whole["status"][subj] == mw.REACHABLE
    assert old_half["status"][subj] == mw.REACHABLE, (
        "ЕСЛИ старый прибор здесь покраснел — дверь уже закрыта и новый "
        "прибор не о ней; вердикт обязан остаться REACHABLE")


# --- КОНТРОЛИ НА КАЖДОЕ ПОРВАННОЕ ЗВЕНО, с НАЗВАННЫМ звеном ------------------

def test_import_with_use_is_a_call(tmp_path):
    assert _verdict(_scene(tmp_path, mentioner="scripts/caller.py",
                           mentioner_body=_IMPORT + _USE)) == cw.CALLED


def test_relative_import_with_use_is_a_call(tmp_path):
    """Звено «разрешение относительного импорта»: `from . import x` + вызов."""
    body = ("from . import x_monitor\n"
            "\n\ndef go():\n    return x_monitor.main()\n")
    assert _verdict(_scene(tmp_path, mentioner=f"{SUBJ_DIR}/neighbour.py",
                           mentioner_body=body)) == cw.CALLED


def test_dotted_import_with_root_use_is_a_call(tmp_path):
    """Звено «dotted-импорт»: щедрость объявлена, корень тронут ⇒ вызов."""
    body = ("import spa_core.monitoring.x_monitor\n"
            "\n\ndef go():\n    return spa_core.monitoring.x_monitor.main()\n")
    assert _verdict(_scene(tmp_path, mentioner="scripts/caller.py",
                           mentioner_body=body)) == cw.CALLED


def test_exec_string_in_a_wrapper_is_a_call(tmp_path):
    """Звено «исполнение строкой»: обёртка зовёт `python -m <путь>`."""
    body = "#!/bin/bash\npython3 -m spa_core.monitoring.x_monitor\n"
    assert _verdict(_scene(tmp_path, mentioner="scripts/agent_x.sh",
                           mentioner_body=body)) == cw.CALLED


def test_a_label_that_merely_looks_like_the_module_is_not_a_call(tmp_path):
    """Механизм (а) замера: соимённый ЯРЛЫК обёртки вызовом не является."""
    body = ("#!/bin/bash\n# обёртка для com.spa.x_monitor\n"
            "python3 /repo/scripts/other_thing.py\n")
    assert _verdict(_scene(tmp_path, mentioner="scripts/agent_x_monitor.sh",
                           mentioner_body=body)) == cw.MENTION_ONLY


def test_an_artifact_name_carrying_the_stem_is_not_a_call(tmp_path):
    """Механизм (б) замера: имя АРТЕФАКТА несёт стем, вызова нет."""
    body = 'PATHS = {"hvg": "data/x_monitor.json"}\n' + ENTRY
    assert _verdict(_scene(tmp_path, mentioner="scripts/caller.py",
                           mentioner_body=body)) == cw.MENTION_ONLY


def test_a_longer_name_containing_the_stem_is_not_a_call(tmp_path):
    """Механизм (в) замера: ПРЕФИКС чужого имени — и проверка «не подстрокой».

    Короткий субъект обязан остаться `MENTION_ONLY`, ДЛИННЫЙ — стать `CALLED`.
    Один assert из двух прошёл бы и на подстроке; нужны оба.
    """
    _write(tmp_path, f"{SUBJ_DIR}/x_monitor.py", f'"""x_monitor."""{ENTRY}')
    _write(tmp_path, f"{SUBJ_DIR}/x_monitors.py", f'"""x_monitors."""{ENTRY}')
    _write(tmp_path, "scripts/caller.py",
           "from spa_core.monitoring import x_monitors\n"
           "\n\ndef go():\n    return x_monitors.main()\n")
    _write(tmp_path, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    rep = cw.measure(tmp_path, min_subjects=1)
    assert _verdict(rep, "x_monitors") == cw.CALLED
    assert _verdict(rep, "x_monitor") == cw.MENTION_ONLY, (
        "стем-префикс чужого имени проводкой не является")


def test_a_homonym_function_is_not_a_call(tmp_path):
    """Механизм (г) замера: ОМОНИМ — чужая функция с тем же именем."""
    body = "def x_monitor(a):\n    return a\n"
    assert _verdict(_scene(tmp_path, mentioner="scripts/caller.py",
                           mentioner_body=body)) == cw.MENTION_ONLY


def test_nobody_mentions_is_census_not_a_member(tmp_path):
    """Субъекта не упоминает никто ⇒ он на учёте храповика, не предмет класса."""
    _write(tmp_path, f"{SUBJ_DIR}/x_monitor.py", f'"""x_monitor."""{ENTRY}')
    _write(tmp_path, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    rep = cw.measure(tmp_path, min_subjects=1)
    assert _verdict(rep) == cw.CENSUS
    assert not rep["mention_only"]


# --- ТРЕТИЙ ИСХОД: «не измерено» ≠ «класс пуст» (инв. #17) -------------------

def test_an_unparsable_mentioner_is_unmeasured_not_a_clean_pass(tmp_path):
    """Неразобранный упоминающий и мог звать ⇒ громкий третий исход."""
    _write(tmp_path, f"{SUBJ_DIR}/x_monitor.py", f'"""x_monitor."""{ENTRY}')
    _write(tmp_path, "scripts/caller.py",
           "from spa_core.monitoring import x_monitor\ndef (\n")
    _write(tmp_path, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    with pytest.raises(cw.Unmeasured) as exc:
        cw.measure(tmp_path, min_subjects=1)
    assert "scripts/caller.py" in str(exc.value), "звено обязано быть НАЗВАНО"


def test_a_thin_subject_surface_is_unmeasured(tmp_path):
    _write(tmp_path, f"{SUBJ_DIR}/x_monitor.py", f'"""x_monitor."""{ENTRY}')
    _write(tmp_path, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    with pytest.raises(cw.Unmeasured):
        cw.measure(tmp_path, min_subjects=50)


def test_cli_prints_unmeasured_and_exits_two(tmp_path, capsys):
    _write(tmp_path, f"{SUBJ_DIR}/x_monitor.py", f'"""x_monitor."""{ENTRY}')
    rc = cw.main(["--root", str(tmp_path)])
    assert rc == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_cli_exit_codes_distinguish_empty_from_found(tmp_path):
    """Измерено и равно нулю ⇒ код 0; найдено ⇒ код 1. Два разных исхода."""
    empty = tmp_path / "empty"
    _write(empty, f"{SUBJ_DIR}/x_monitor.py", f'"""x_monitor."""{ENTRY}')
    _write(empty, "scripts/caller.py",
           "from spa_core.monitoring import x_monitor\n"
           "\n\ndef go():\n    return x_monitor.main()\n")
    _write(empty, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    assert cw.main(["--root", str(empty), "--min-subjects", "1"]) == 0

    found = tmp_path / "found"
    _write(found, f"{SUBJ_DIR}/x_monitor.py", f'"""x_monitor."""{ENTRY}')
    _write(found, "scripts/caller.py",
           'PATHS = {"a": "data/x_monitor.json"}\n')
    _write(found, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    assert cw.main(["--root", str(found), "--min-subjects", "1"]) == 1


# --- ПРАВИЛО ЖИВЁТ В ОДНОМ МЕСТЕ --------------------------------------------

def test_the_mention_relation_has_no_second_copy():
    """Отношение «упоминает» берётся у прибора упоминаний, а тот — у храповика."""
    assert cw.WATCHED_DIRS is mw.WATCHED_DIRS
    assert cw.SCAN_SUBDIRS is mw.SCAN_SUBDIRS
    assert cw.SCAN_SUFFIXES is mw.SCAN_SUFFIXES


# --- НАСТОЯЩЕЕ ДЕРЕВО: вопрос задаётся, и он разрешим ------------------------

def test_the_real_repo_answers_without_unmeasured():
    """На живом дереве прибор обязан ОТВЕТИТЬ, а не упасть в «не измерено».

    Числа замера живут в ADR и в журнале, а не здесь: храповика на класс
    заказ G1016 п. 1 заводить ЗАПРЕТИЛ до решения «подключить или вывести».
    Этот контроль держит только разрешимость вопроса и непустоту поверхности.
    """
    rep = cw.measure()
    assert rep["subjects"] >= cw.MIN_SUBJECTS
    assert rep["pairs_examined"] > 0
    assert rep["deemed_wired_depth1"] == rep["called"] + len(rep["mention_only"])
