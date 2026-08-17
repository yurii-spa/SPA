"""Ни один тест не имеет права писать git-tracked ``spa_core/database/spa.db``.

Найдено и починено 2026-08-17, цикл #274, карточка
``agent-test-run-dirties-tracked-fixtures``.

Дефект
======
``spa_core/database/db_url.py`` резолвит SQLite-умолчание из собственного
``__file__``::

    _DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "spa.db"

Файл по этому пути **git-tracked**. Замер (инструментированный прогон
``pytest spa_core/tests/``, обёртка вокруг ``sqlite3.connect``): пять тестов
``spa_core/tests/test_api.py`` — ``test_api_status_returns_200`` и соседи —
доходят до него по цепочке::

    api/routers/misc.py:352  get_status
      api/routers/misc.py:65   get_live_portfolio
        api/_shared.py:197     get_live_portfolio
          database/init_db.py:253  init_database
            database/connection.py:66 get_connection → sqlite3.connect(<репо>/spa_core/database/spa.db)

После прогона ``git status`` показывал ``M spa_core/database/spa.db``, и
«чистое дерево» переставало быть сигналом перед пушем — той самой проверкой,
которой цикл отделяет свои правки от чужих.

Что делает сторож
=================
Пинует ``$SPA_DATABASE_URL`` на файл в песочнице, которую набор себе и создаёт.
Это **редирект, а не мок**: ``get_db_url`` / ``get_connection`` / ``init_database``
и все схемы исполняются целиком, меняется только файл назначения. Работает
потому, что путь БД, в отличие от логов-производных, уже разрешается на вызове
и уже имеет вход — переменную окружения; ничего в проде трогать не пришлось.

Ставится и снимается вокруг каждого теста (не один раз за сессию): тест вправе
сам выставить или удалить эту переменную (``test_db_url.py`` так и делает), и
это не должно протекать в следующий тест.

``install()`` идемпотентен, каталог песочницы создаётся лениво.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ENV_VAR = "SPA_DATABASE_URL"

_SANDBOX_ROOT: Path | None = None
_UNSET = object()
_saved: object = _UNSET


def sandbox_db_path() -> Path:
    """Файл SQLite в песочнице (создаётся каталог, не файл)."""
    global _SANDBOX_ROOT
    if _SANDBOX_ROOT is None:
        _SANDBOX_ROOT = Path(tempfile.mkdtemp(prefix="spa_test_db_"))
    return _SANDBOX_ROOT / "spa.db"


def install() -> None:
    """Увести ``$SPA_DATABASE_URL`` в песочницу, запомнив текущее значение."""
    global _saved
    _saved = os.environ.get(ENV_VAR, _UNSET)
    os.environ[ENV_VAR] = f"sqlite:///{sandbox_db_path()}"


def restore() -> None:
    """Вернуть ``$SPA_DATABASE_URL`` в то состояние, в котором его нашли."""
    global _saved
    if _saved is _UNSET:
        os.environ.pop(ENV_VAR, None)
    else:
        os.environ[ENV_VAR] = _saved  # type: ignore[assignment]
    _saved = _UNSET
