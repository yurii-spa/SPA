"""CI-ISOLATION-01: журнал анализатора пишется во ВРЕМЕННУЮ сцену теста, а не в git-tracked `data/`.

Девять модулей тестов (лог CI 41176617446, шард 4) писали ring-buffer журналы своих анализаторов в
`data/*.json` репозитория, и `tracked_write_guard` честно ронял сессию. Сторож и его база не меняются;
меняется место записи под тестом. Запись остаётся НАСТОЯЩЕЙ — тот же код анализатора пишет тот же файл,
только по пути внутри `tmp_path`.

Путь бывает захвачен двумя способами, и оба закрываются здесь:
  * глобальная модуля, читаемая в момент вызова (`_LOG_PATH`, `LOG_PATH`, `LOG_FILE`) — подменяется атрибут;
  * значение по умолчанию функции, вычисленное на импорте (`def _append_log(..., log_path=LOG_PATH)`) —
    подменяется соответствующий элемент ``__defaults__``.
Подмена — через ``monkeypatch``: после теста всё возвращается к исходному значению.
"""
from __future__ import annotations

import os
from pathlib import Path


def redirect_log(monkeypatch, tmp_path: Path, module, attr: str, *, defaults_of=()) -> Path:
    """Направить журнал ``module.attr`` в сцену ``tmp_path``; вернуть путь журнала в сцене.

    Исходный путь обязан указывать в `data/` — иначе изолировать нечего и контроль был бы пустым.
    Значение по умолчанию у ``defaults_of`` обязано совпадать с исходным путём — иначе подмена промахнулась.
    """
    original = getattr(module, attr)
    assert os.path.basename(os.path.dirname(os.path.abspath(original))) == "data", (
        f"{module.__name__}.{attr} указывает не в data/: {original}")
    scene = tmp_path / "scene_data" / os.path.basename(original)
    scene.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, attr, str(scene))
    for fn in defaults_of:
        defaults = fn.__defaults__ or ()
        assert original in defaults, f"{fn.__qualname__}: путь по умолчанию не найден в __defaults__"
        monkeypatch.setattr(fn, "__defaults__",
                            tuple(str(scene) if d == original else d for d in defaults))
    return scene
