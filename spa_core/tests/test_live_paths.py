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
    monkeypatch.delenv(LP.SANDBOX_ENV, raising=False)
    monkeypatch.delenv(LP.PROBE_TREE_ENV, raising=False)


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


# ===========================================================================
# C8(a) ADR-580 — реплей INC-1: маркер песочницы делает отказ сильнее умолчания
# ===========================================================================
# Прод-агент `com.spa.decision_loop` зовёт G97-зонд в одноразовом дереве; зонд
# выставляет свои `SPA_STAMP_*`, но не `SPA_DATA_DIR`/`SPA_LIVE_ROOT`, и
# `owner_decision_pending.json` получил отметку 2041 года — запись ушла в прод
# (REVIEW_1.md, п. 1). Тесты ниже закрепляют защиту НА ПРИЁМНИКЕ.


def test_sandbox_marker_refuses_the_prod_default(monkeypatch, tmp_path):
    """Маркер есть, явного пути нет ⇒ `SandboxLeakError`, а НЕ прод-путь молча.

    Это ровно форма INC-1: харнесс забыл `SPA_DATA_DIR`/`SPA_LIVE_ROOT`, и
    умолчание указывает на `DEFAULT_LIVE_ROOT`.
    """
    fake_prod = tmp_path / "prod"
    fake_prod.mkdir()
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
    monkeypatch.setenv(LP.SANDBOX_ENV, "1")
    with pytest.raises(LP.SandboxLeakError):
        LP.live_root()
    with pytest.raises(LP.SandboxLeakError):
        LP.live_data_dir()


def test_probe_tree_env_alone_is_a_sandbox_marker_too(monkeypatch, tmp_path):
    """Переменная дерева зонда (`SPA_STAMP_TREE`) — ВТОРАЯ форма маркера.

    Это буквально переменная G97-зонда из INC-1, а не выдуманный пример: сам
    зонд её выставляет, общего `SPA_SANDBOX` не зная.
    """
    fake_prod = tmp_path / "prod"
    fake_prod.mkdir()
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
    monkeypatch.setenv(LP.PROBE_TREE_ENV, str(tmp_path / "одноразовое-дерево"))
    with pytest.raises(LP.SandboxLeakError):
        LP.live_root()


def test_explicit_sandbox_path_still_wins_over_the_marker(monkeypatch, tmp_path):
    """C8(b): харнесс, назвавший СВОЙ путь, не отказывает — он и есть починка."""
    fake_prod = tmp_path / "prod"
    fake_prod.mkdir()
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
    monkeypatch.setenv(LP.SANDBOX_ENV, "1")
    sandbox = tmp_path / "sandbox"
    monkeypatch.setenv(LP.LIVE_ROOT_ENV, str(sandbox))
    monkeypatch.setenv(LP.DATA_DIR_ENV, str(sandbox / "data"))
    assert LP.live_root() == sandbox
    assert LP.live_data_dir() == sandbox / "data"


def test_explicit_path_equal_to_prod_still_refuses(monkeypatch, tmp_path):
    """Явный путь, который СЛУЧАЙНО совпал с прод-деревом, не спасает умолчание.

    «Явно указал» ≠ «указал внутрь песочницы» — ADR-580 различает их буквально:
    совпадение с `DEFAULT_LIVE_ROOT` отказывает независимо от того, пришёл ли
    путь из переменной или из умолчания.
    """
    fake_prod = tmp_path / "prod"
    fake_prod.mkdir()
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
    monkeypatch.setenv(LP.SANDBOX_ENV, "1")
    monkeypatch.setenv(LP.LIVE_ROOT_ENV, str(fake_prod))
    with pytest.raises(LP.SandboxLeakError):
        LP.live_root()


def test_no_marker_no_change_for_ordinary_prod_agents(monkeypatch, tmp_path):
    """Обычный прод-агент (без маркера) поведения не меняет — нулевой побочный эффект."""
    real_prod = tmp_path / "prod"
    real_prod.mkdir()
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", real_prod)
    assert LP.live_root() == real_prod
    assert LP.live_data_dir() == real_prod / "data"


# ===========================================================================
# F6 (REVIEW_1) — `Path.resolve()` raises ``ValueError`` (embedded NUL byte),
# not only ``OSError``. The guard's string-comparison fallback must catch it
# too, instead of letting a different exception crash out of the leak check.
# ===========================================================================


def test_embedded_nul_path_falls_back_to_string_compare_not_a_crash(monkeypatch, tmp_path):
    """Положительный контроль F6: путь со встроенным NUL-байтом не совпадает
    СТРОКОЙ с прод-путём ⇒ это не утечка, и функция обязана тихо вернуть, а не
    упасть `ValueError`-ом (до фикса `except OSError` не ловил этот тип, и
    настоящий вердикт «утечка или нет» заслонялся крашем самого сторожа).

    ``os.environ`` сам отказывает записывать строку со встроенным NUL (C-уровень),
    поэтому путь строится не через переменную окружения, а напрямую — что и так
    вернее: предмет теста — поведение ``_refuse_if_leaking_to_prod``, а не то,
    как путь попал на вход. Маркер выставлен явно: без него функция возвращает
    СРАЗУ (до самого сравнения) и тест прошёл бы, ничего не измерив."""
    monkeypatch.setenv(LP.SANDBOX_ENV, "1")
    fake_prod = tmp_path / "prod"
    nul_candidate = Path(str(fake_prod) + "\x00-not-prod")
    LP._refuse_if_leaking_to_prod(nul_candidate, fake_prod, who="test")  # must not raise ValueError


def test_embedded_nul_path_equal_to_prod_by_string_still_refuses(monkeypatch, tmp_path):
    """Обратная сторона: если NUL-путь строкой СОВПАДАЕТ с прод-путём (та же
    строка), это всё равно утечка — `ValueError` не имеет права заслонить её
    тем, что превращает отказ в тихий успех."""
    monkeypatch.setenv(LP.SANDBOX_ENV, "1")
    fake_prod = tmp_path / "prod"
    nul_prod = Path(str(fake_prod) + "\x00")
    with pytest.raises(LP.SandboxLeakError):
        LP._refuse_if_leaking_to_prod(nul_prod, nul_prod, who="test")


def test_marker_without_prod_collision_does_not_refuse(monkeypatch, tmp_path):
    """Маркер стоит, но живого прод-дерева на этой машине вообще нет (CI) — не отказ.

    Отказывать здесь значило бы ломать CI, где `DEFAULT_LIVE_ROOT` не существует
    по построению и умолчание честно падает на `fallback`/`OWN_TREE`.
    """
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", tmp_path / "нет-такого-дерева")
    monkeypatch.setenv(LP.SANDBOX_ENV, "1")
    caller = tmp_path / "дерево-вызывающего"
    assert LP.live_root(caller) == caller
    assert LP.live_data_dir(caller) == caller / "data"


def test_r2_nested_claude_worktree_is_not_prod_but_prod_itself_still_refused(tmp_path, monkeypatch):
    """R2 (ADR-580 §C8, REVIEW_INTEGRATION_3): одноразовый worktree Claude Code внутри
    `<прод>/.claude/worktrees/<имя>` — не прод; сам прод и его прочие подкаталоги — по-прежнему
    отказ (положительный контроль рядом: исключение не расширяет дыру)."""
    prod = tmp_path / "SPA_Claude"
    wt = prod / ".claude" / "worktrees" / "w1"
    (wt / "nimbalyst-local" / "tracker").mkdir(parents=True)
    (prod / "nimbalyst-local" / "tracker").mkdir(parents=True)
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", prod)
    monkeypatch.setenv(LP.SANDBOX_ENV, "1")
    LP.assert_not_prod_realpath(wt / "nimbalyst-local" / "tracker", who="t")
    with pytest.raises(LP.SandboxLeakError):
        LP.assert_not_prod_realpath(prod / "nimbalyst-local" / "tracker", who="t")
    with pytest.raises(LP.SandboxLeakError):
        LP.assert_not_prod_realpath(prod, who="t")
    with pytest.raises(LP.SandboxLeakError):
        LP.assert_not_prod_realpath(prod / ".claude" / "settings.json", who="t")
