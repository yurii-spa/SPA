#!/usr/bin/env python3
"""Живое состояние ищется в ЖИВОМ дереве, а не в том, откуда нас запустили.

Замер (день инцидента, разбор в журнале W32): владельцу пришло решение с текстом
«Нажми кнопку» и БЕЗ единой кнопки. Отправляла сессия из своего рабочего дерева (worktree).
Маячок живого бота пишется ТОЛЬКО в прод-дерево; отправитель искал его у себя, не находил и
по правилу fail-CLOSED кнопок не вешал — молча.

Это родовой класс: **путь, разрешаемый относительно исполняемого дерева, тихо меняет
поведение**. Хост-дерево дрейфует от origin по построению, сессии работают из worktree —
значит «мой data/» и «живой data/» это разные вещи.

Здесь пиннится порядок разрешения и то, ради чего он вообще нужен.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from spa_core.utils import live_paths as LP


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(LP.DATA_DIR_ENV, raising=False)
    monkeypatch.delenv(LP.LIVE_ROOT_ENV, raising=False)


def test_sandbox_wins_over_everything(monkeypatch, tmp_path):
    """`SPA_DATA_DIR` сильнее всего: иначе пред-деплойный гейт писал бы в ЖИВОЕ состояние.

    Это не предпочтение, а защита: гейт запускает модуль по-настоящему, и без приоритета
    песочницы его прогон трогал бы боевые файлы.
    """
    sandbox = tmp_path / "sandbox"
    monkeypatch.setenv(LP.DATA_DIR_ENV, str(sandbox))
    monkeypatch.setenv(LP.LIVE_ROOT_ENV, str(tmp_path / "live"))
    assert LP.live_data_dir(tmp_path / "caller") == sandbox


def test_explicit_live_root_is_honoured(monkeypatch, tmp_path):
    """Прод может переехать — корень задаётся явно, без правки кода."""
    monkeypatch.setenv(LP.LIVE_ROOT_ENV, str(tmp_path / "elsewhere"))
    assert LP.live_data_dir(tmp_path / "caller") == tmp_path / "elsewhere" / "data"


def test_caller_tree_is_the_last_resort_not_the_first(monkeypatch, tmp_path):
    """Положительный контроль аварии: дерево вызывающего — ПОСЛЕДНИЙ вариант.

    Пока живое дерево видно, отправитель из worktree обязан смотреть в НЕГО, иначе маячок
    бота не находится и кнопки исчезают молча.
    """
    live = tmp_path / "live"
    (live / "data").mkdir(parents=True)
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", live)
    caller = tmp_path / "worktree"
    (caller / "data").mkdir(parents=True)

    assert LP.live_data_dir(caller) == live / "data"
    assert LP.live_data_dir(caller) != caller / "data"


def test_falls_back_to_the_caller_when_there_is_no_live_tree(monkeypatch, tmp_path):
    """На чужой машине / в CI живого дерева нет — работаем от себя, а не падаем."""
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", tmp_path / "нет-такого")
    caller = tmp_path / "ci"
    assert LP.live_data_dir(caller) == caller / "data"


def test_without_a_fallback_the_answer_does_not_depend_on_cwd(monkeypatch, tmp_path):
    """Положительный контроль аварии CI 14.08: ответ не имеет права зависеть от cwd.

    Job гонял тесты как `cd spa_core && pytest tests/`, и `live_data_dir(None)` отдавал
    `<репо>/spa_core/data` — каталог, которого нет. Агенты стартуют из разных каталогов;
    путь, который меняется от рабочего каталога, — ровно тот класс, ради которого написан
    этот модуль. Меряем ЭФФЕКТ: два вызова из РАЗНЫХ cwd обязаны совпасть.
    """
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", tmp_path / "нет-живого-дерева")

    here = tmp_path / "откуда-то"
    here.mkdir()
    monkeypatch.chdir(here)
    first = LP.live_data_dir(None)

    there = tmp_path / "и-отсюда-тоже"
    there.mkdir()
    monkeypatch.chdir(there)
    second = LP.live_data_dir(None)

    assert first == second, "ответ уехал вместе с рабочим каталогом"
    assert first == LP.OWN_TREE / "data"
    # контроль в обратную сторону: cwd действительно менялся, тест не вхолостую
    assert here.resolve() != there.resolve()
    assert first != here / "data" and first != there / "data"


def test_an_explicit_caller_tree_still_wins_over_our_own(monkeypatch, tmp_path):
    """Обратная сторона: назвал дерево — берётся ОНО, а не дерево модуля.

    Иначе починка cwd превратилась бы в «всегда своё дерево» и сломала вызывающих,
    которые честно передают свой корень.
    """
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", tmp_path / "нет-такого")
    caller = tmp_path / "чужое-дерево"
    assert LP.live_data_dir(caller) == caller / "data"
    assert LP.live_data_dir(caller) != LP.OWN_TREE / "data"


def test_the_beacon_and_the_journal_agree_on_one_tree():
    """Маячок и журнал обязаны жить в ОДНОМ дереве.

    Разойдись они — кнопка нашлась бы (маячок виден), а записи о ней нет, и нажатие
    владельца получило бы «не нашёл эту карточку». Хуже отсутствия кнопки.
    """
    from spa_core.telegram import alert_actions as aa
    from spa_core.telegram import owner_decisions as od

    assert aa.BEACON_PATH.parent == od.STATE_PATH.parent
    assert aa.STATE_PATH.parent == od.STATE_PATH.parent


def test_module_creates_no_directories(monkeypatch, tmp_path):
    """Разрешение пути — чистое: сторож не имеет права наплодить каталогов на диске."""
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", tmp_path / "нет")
    LP.live_data_dir(tmp_path / "тоже-нет")
    assert not (tmp_path / "нет").exists()
    assert not (tmp_path / "тоже-нет").exists()
