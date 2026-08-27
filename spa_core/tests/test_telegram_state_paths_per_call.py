#!/usr/bin/env python3
"""Пути состояния отправителя разрешаются В МОМЕНТ ВЫЗОВА, а не на импорте модуля.

Замер карточки `agent-puti-sostoyaniya-vychislyayutsya-na-impo` (циклы #391/#394):
`spa_core/alerts/telegram_client` вычислял три пути на импорте —

    _RATE_STATE / _HISTORY_STATE / _OUTBOUND_LOCK_PATH = live_data_dir(...) / ...

а `live_data_dir()` первым делом читает `SPA_DATA_DIR`. Импорт случается ОДИН раз (на сборе
тестов или на первом тесте, который модуль тянет), поэтому значение прибивалось к окружению
одного случайного момента:

* под изоляцией — к песочнице ЧУЖОГО теста; следующие тесты видят каталог, которого уже нет
  (в журнале W35 это 14 падений полного прогона с `_spa_isolated_data` в тексте);
* без изоляции — к ПРОД-дереву владельца, то есть к живому состоянию дедупа и лимита потока.

Ни одно из двух состояний не есть «каждый вызов знает, где живёт состояние СЕЙЧАС».

Что проверяется здесь — ЭФФЕКТ, а не форма записи: смена `SPA_DATA_DIR` после импорта обязана
менять все три пути, две «песочницы подряд» обязаны давать РАЗНЫЕ каталоги, а точка подмены
для тестов (`monkeypatch.setattr(tc, "_HISTORY_STATE", ...)`, которой пользуются семь файлов)
обязана продолжать выигрывать. Каждый тест — положительный контроль: верните вычисление на
импорт, и он покраснеет.

Сети здесь нет: проверяются только пути.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from spa_core.alerts import telegram_client as tc

ROOT = Path(__file__).resolve().parents[2]

_ACCESSORS = (
    (tc._rate_state_path, ".telegram_rate.json"),
    (tc._history_state_path, "alert_history.json"),
    (tc._outbound_lock_path, ".telegram_outbound.lock"),
)


def test_env_change_after_import_moves_every_state_path(tmp_path, monkeypatch):
    """Положительный контроль дефекта: песочница, выставленная ПОСЛЕ импорта, обязана быть услышана.

    На импортном варианте все три пути остались бы в каталоге, который действовал в момент
    импорта модуля, и этот тест краснеет.
    """
    first = tmp_path / "первая"
    second = tmp_path / "вторая"
    first.mkdir()
    second.mkdir()

    monkeypatch.setenv("SPA_DATA_DIR", str(first))
    before = [fn() for fn, _ in _ACCESSORS]
    assert [p.parent for p in before] == [first, first, first]

    monkeypatch.setenv("SPA_DATA_DIR", str(second))
    after = [fn() for fn, _ in _ACCESSORS]
    assert [p.parent for p in after] == [second, second, second]

    # и это именно ПЕРЕЕЗД, а не совпадение имён
    assert all(a != b for a, b in zip(before, after))


def test_file_names_do_not_drift_between_the_two_sandboxes(tmp_path, monkeypatch):
    """Меняется КАТАЛОГ, имя файла — нет: иначе «починка» тихо развела бы прод и тест."""
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    for fn, name in _ACCESSORS:
        assert fn().name == name
        assert fn().parent == tmp_path


def test_two_consecutive_sandboxes_get_different_directories(tmp_path, monkeypatch):
    """Приёмочный критерий карточки: два вызова в РАЗНЫХ песочницах — разные каталоги.

    Ровно этого не давал импортный вариант: следующий тест получал каталог предыдущего.
    """
    seen = []
    for name in ("s1", "s2"):
        sandbox = tmp_path / name
        sandbox.mkdir()
        monkeypatch.setenv("SPA_DATA_DIR", str(sandbox))
        seen.append(tc._history_state_path().parent)
    assert seen[0] != seen[1]
    assert seen == [tmp_path / "s1", tmp_path / "s2"]


def test_the_module_variable_is_still_the_override_point(tmp_path, monkeypatch):
    """Подмена переменной обязана выигрывать у окружения — на ней стоят семь тест-файлов.

    Если бы аксессор просто игнорировал переменную, тесты дедупа/истории молча начали бы
    читать не тот файл и перестали бы проверять то, что написано в их именах.
    """
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path / "окружение"))
    подмена = tmp_path / "подменённый.json"
    monkeypatch.setattr(tc, "_HISTORY_STATE", подмена)
    assert tc._history_state_path() == подмена

    monkeypatch.setattr(tc, "_RATE_STATE", tmp_path / "лимит.json")
    assert tc._rate_state_path() == tmp_path / "лимит.json"

    monkeypatch.setattr(tc, "_OUTBOUND_LOCK_PATH", tmp_path / "лок")
    assert tc._outbound_lock_path() == tmp_path / "лок"


def test_default_is_none_so_nothing_is_frozen_at_import():
    """Замороженного на импорте значения быть не должно вовсе — иначе дефект возвращается тихо."""
    assert tc._RATE_STATE is None
    assert tc._HISTORY_STATE is None
    assert tc._OUTBOUND_LOCK_PATH is None


def test_outbound_lock_takes_the_lock_in_the_current_sandbox(tmp_path, monkeypatch):
    """Эффект на РАБОТАЮЩЕМ пути: лок создаётся в песочнице ЭТОГО теста.

    `outbound_lock()` держится и под pytest (иначе тест на конкуренцию ничего бы не проверял),
    поэтому на импортном варианте он лочил каталог чужого — уже снятого — теста.
    """
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    with tc.outbound_lock():
        pass
    assert (tmp_path / ".telegram_outbound.lock").exists()


def test_a_child_process_resolves_its_own_sandbox(tmp_path):
    """Тот же вопрос в ЧУЖОМ процессе — там, где импорт заведомо случается при своём окружении.

    Дочерний процесс — единственный способ проверить утверждение «путь берётся из ТЕКУЩЕГО
    окружения» без следов чужих тестов в собственном интерпретаторе.
    """
    script = (
        "import os, sys; sys.path.insert(0, {root!r})\n"
        # песочница выставляется ПОСЛЕ импорта — иначе тест зелен и на импортном варианте
        # (там путь тоже верен, просто по счастливому совпадению момента) и контролем не был бы
        "os.environ.pop('SPA_DATA_DIR', None)\n"
        "from spa_core.alerts import telegram_client as tc\n"
        "os.environ['SPA_DATA_DIR'] = {sandbox!r}\n"
        "print(tc._history_state_path())\n"
    ).format(root=str(ROOT), sandbox=str(tmp_path))
    env = dict(os.environ)
    env.pop("SPA_DATA_DIR", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    out = subprocess.run([sys.executable, "-c", script], env=env, cwd=str(ROOT),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == str(tmp_path / "alert_history.json")
