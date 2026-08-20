"""Сторож: прогон тестов НЕ создаёт файлов в `spa_core/data/`.

## Зачем он есть

`spa_core/data/` — каталог ПАКЕТА с git-tracked фикстурами (`apy_history.json`,
`covariance_summary.json`, …), а не runtime-state. Ничего, что рождается прогоном,
там лежать не должно.

Полный прогон командой CI начинается с `cd spa_core` (шаг «Run spa_core/tests»),
поэтому относительный `DATA_FILE = Path("data/<имя>_log.json")` у analytics-модулей
резолвится в `spa_core/data/` — и каждый тест, который зовёт `analyze()`, не подменив
путь, оставляет там файл. Замер #314: **14 таких файлов**, один в один в контрольном
дереве на чистом `origin`, где не сделано ни одной правки.

**Цена, из-за которой это не косметика.** 14 путей untracked и на `origin` их нет ⇒
`scripts/reap_stale_worktrees.py` выносит вердикт `absent` и ОТКАЗЫВАЕТСЯ снимать
дерево: «здесь может лежать НЕДОСТАВЛЕННАЯ работа». Отказ правильный — сторож не умеет
отличить наш мусор от потерянной работы и не должен угадывать. Итог до починки: каждое
дерево, где хоть раз шёл полный прогон, оставалось на диске НАВСЕГДА и потом
докладывалось шагом 0a как удерживающее недоставленное. И «чистое дерево» переставало
быть сигналом перед пушем.

## Почему сторож, а не только починка писателей

Починка адресная (13 тест-файлов подменяют путь на `tmp_path`), а класс — общий: любой
следующий тест, зовущий `analyze()` без подмены, вернёт осадок молча. Сторож ШИРЕ
подопечного намеренно: он ловит ЛЮБОЙ новый файл в каталоге пакета, а не поимённый
список из 14 — иначе он был бы эхом собственной починки.

Сторож НАЗЫВАЕТ (тест + имя файла) и НЕ убирает улику: спрятать файл значило бы
починить отчёт вместо дефекта.

Регистрируется как autouse-фикстура через `spa_core/tests/conftest.py`; для
положительного контроля тот же модуль подключается плагином (`-p`), поэтому фикстура
живёт здесь, а не в самом conftest.
"""

from pathlib import Path

import pytest

#: Каталог пакета, за которым следим. Считается от ЭТОГО файла, а не от cwd:
#: сторож обязан работать одинаково и из корня репо, и из `spa_core/` (шаг CI).
PACKAGE_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def snapshot(directory=PACKAGE_DATA_DIR):
    """Имена файлов в *directory* (пусто, если каталога нет)."""
    path = Path(directory)
    if not path.is_dir():
        return frozenset()
    return frozenset(p.name for p in path.iterdir())


def new_files(before, after):
    """Что появилось между двумя снимками (отсортировано)."""
    return tuple(sorted(frozenset(after) - frozenset(before)))


def failure_message(test_id, names, directory=PACKAGE_DATA_DIR):
    """Текст отказа: кто, что и почему это не косметика."""
    listed = ", ".join(names)
    return (
        f"тест {test_id} создал в каталоге пакета {directory} файл(ы): {listed}.\n"
        "`spa_core/data/` — git-tracked фикстуры пакета, не runtime-state. Скорее всего "
        "тест зовёт analyze()/_append_log(), не подменив путь лога: под `cd spa_core` "
        "относительный `data/...` резолвится СЮДА.\n"
        "Починка: подменить путь лога на tmp в autouse-фикстуре этого тест-файла "
        "(образцы — spa_core/tests/test_protocol_maturity_scorer.py и соседи).\n"
        "Почему нельзя оставить: файл untracked и на origin его нет ⇒ "
        "reap_stale_worktrees выносит `absent` и не снимает рабочее дерево НИКОГДА "
        "(карточка agent-test-run-dirties-tracked-fixtures)."
    )


@pytest.fixture(autouse=True)
def _package_data_stays_clean(request):
    """Роняет тест, который оставил новый файл в `spa_core/data/`."""
    before = snapshot()
    yield
    appeared = new_files(before, snapshot())
    if appeared:
        pytest.fail(failure_message(request.node.nodeid, appeared), pytrace=False)
